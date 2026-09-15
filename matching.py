"""
Matching Engine for WaveMatch (Phase H).

Spec: 3-Full-Product-Logic.md Section 4 ("Matching Engine"), with the message
shape taken from Section 5 and 4-Message-Flow-Examples.md Section 5.

Triggered every time a new opportunity becomes active, from two call sites in
poster_flow.py:
  1. the direct-post success path      (requires_post_approval = false)
  2. the admin post-approval path       (requires_post_approval = true)
Edits do NOT re-run matching - edits only notify existing matches (Section 3.1).

Steps (Section 4):
  1. Query users whose interest tags intersect the opportunity's tags.
  2. For each match, create an `applications` row with status = 'available'.
  3. Send each matched user the New Match Notification (Section 5).
  4. Return the match count (count only - never a list of names) so the caller
     can report it back to the poster (Section 4, step 4 / privacy rule).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import anyio
from dotenv import load_dotenv

from conversation import _db_semaphore
from database import supabase
from whatsapp import send_new_match_notification

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _get_opportunity_with_poster(opportunity_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the opportunity fields needed for the notification, plus the poster's
    display name, in a single PostgREST query (embedded resource join).

    Returns the row dict, or None if the opportunity does not exist.
    """
    def _get():
        result = (
            supabase.from_("opportunities")
            .select(
                "id, title, description, application_start_date, "
                "application_deadline, poster_id, posters(display_name)"
            )
            .eq("id", opportunity_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _get_opportunity_tag_ids(opportunity_id: str) -> List[str]:
    """Return the tag ids attached to an opportunity."""
    def _get():
        result = (
            supabase.from_("opportunity_tags")
            .select("tag_id")
            .eq("opportunity_id", opportunity_id)
            .execute()
        )
        return [row["tag_id"] for row in (result.data or [])]

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _get_matched_users(tag_ids: List[str]) -> List[Dict[str, str]]:
    """
    Return a de-duplicated list of {"user_id", "phone_number"} for every user
    whose tags intersect `tag_ids`.

    The tag intersection is done in Postgres: one query against `user_tags`
    filtered by `tag_id IN (...)`, with the user's phone number pulled in via an
    embedded resource join. A user with several matching tags appears several
    times in the result; we only de-duplicate the already-filtered rows in Python
    (we never pull all users into memory to filter them).
    """
    def _get():
        result = (
            supabase.from_("user_tags")
            .select("user_id, users(phone_number)")
            .in_("tag_id", tag_ids)
            .execute()
        )
        return result.data or []

    async with _db_semaphore:
        rows = await anyio.to_thread.run_sync(_get)

    matched: Dict[str, str] = {}
    for row in rows:
        user_id = row.get("user_id")
        if not user_id or user_id in matched:
            continue
        user = row.get("users") or {}
        phone_number = user.get("phone_number")
        if phone_number:
            matched[user_id] = phone_number

    return [{"user_id": uid, "phone_number": phone} for uid, phone in matched.items()]


async def _create_available_application(user_id: str, opportunity_id: str) -> Optional[str]:
    """
    Insert an `applications` row with status = 'available' for a matched user.

    Returns the new row's id (needed for the notification's stateless button
    ids), or None if the insert unexpectedly returned no row.
    """
    def _create():
        result = (
            supabase.from_("applications")
            .insert({
                "user_id": user_id,
                "opportunity_id": opportunity_id,
                "status": "available",
                # Phase I / Section 5.2: default +2 day reminder (no-response fallback).
                "next_reminder_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            })
            .execute()
        )
        return result.data[0]["id"] if result.data else None

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_create)


async def run_matching_engine(opportunity_id: str) -> int:
    """
    Run the Matching Engine for a newly-active opportunity.

    Returns the number of users matched (i.e. an `applications` row was created
    for them). Never raises for a single user's failure: one bad user/row/send
    must not abort the whole batch or crash the poster's webhook.
    """
    opportunity = await _get_opportunity_with_poster(opportunity_id)
    if not opportunity:
        logger.warning(f"MATCHING_SKIP: opportunity_id={opportunity_id} not found")
        return 0

    tag_ids = await _get_opportunity_tag_ids(opportunity_id)
    if not tag_ids:
        logger.info(f"MATCHING_SKIP: opportunity_id={opportunity_id} has no tags")
        return 0

    matched_users = await _get_matched_users(tag_ids)
    logger.info(
        f"MATCHING_START: opportunity_id={opportunity_id} "
        f"tag_ids={len(tag_ids)} matched_users={len(matched_users)}"
    )

    poster = opportunity.get("posters") or {}
    poster_name = poster.get("display_name") or "a poster"

    matched_count = 0
    for user in matched_users:
        try:
            application_id = await _create_available_application(
                user["user_id"], opportunity_id
            )
            if not application_id:
                logger.error(
                    f"MATCHING_APP_CREATE_EMPTY: user_id={user['user_id']} "
                    f"opportunity_id={opportunity_id}"
                )
                continue

            matched_count += 1

            try:
                await send_new_match_notification(
                    to=user["phone_number"],
                    title=opportunity.get("title") or "New opportunity",
                    poster_name=poster_name,
                    description=opportunity.get("description") or "",
                    application_start_date=opportunity.get("application_start_date"),
                    application_deadline=opportunity.get("application_deadline"),
                    application_id=application_id,
                )
            except Exception:
                # The match (application row) already exists - a failed send must
                # not drop it, and must not abort the remaining users.
                logger.exception(
                    f"MATCHING_NOTIFY_FAILED: user_id={user['user_id']} "
                    f"opportunity_id={opportunity_id} application_id={application_id}"
                )
        except Exception:
            logger.exception(
                f"MATCHING_USER_FAILED: user_id={user['user_id']} "
                f"opportunity_id={opportunity_id}"
            )

    logger.info(
        f"MATCHING_DONE: opportunity_id={opportunity_id} matched={matched_count}"
    )
    return matched_count