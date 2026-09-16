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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import anyio
from dotenv import load_dotenv

from conversation import _db_semaphore
from database import supabase
# "Today" in the product timezone, and the DB-DATE coercion it needs. Imported rather than
# re-derived so this module can't disagree with the scheduler about what "today" means.
from scheduler import _as_date, _today
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


# ============================================================
# USER-SIDE BACK-FILL (Full-Product-Logic.md Section 1.3 / 2)
# ============================================================

async def _get_user_tag_ids(user_id: str) -> List[str]:
    """Return the tag ids a user is subscribed to."""
    def _get():
        result = (
            supabase.from_("user_tags")
            .select("tag_id")
            .eq("user_id", user_id)
            .execute()
        )
        return [row["tag_id"] for row in (result.data or [])]

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _get_live_opportunity_ids_for_tags(tag_ids: List[str]) -> List[str]:
    """
    Return the ids of the opportunities a user with these tags should be offered.

    "Should be offered" is stricter than "tags intersect":
      - `status = active` only. `pending_approval` isn't approved yet, and `expired` /
        `rejected` must never reach a user.
      - the deadline hasn't already passed. A user registering today must not be handed
        an application link that closed last week.

    The tag intersection is done Postgres-side, the same way `_get_matched_users` does it.
    """
    def _get():
        result = (
            supabase.from_("opportunity_tags")
            .select("opportunity_id, opportunities(status, application_deadline, created_at)")
            .in_("tag_id", tag_ids)
            .execute()
        )
        return result.data or []

    async with _db_semaphore:
        rows = await anyio.to_thread.run_sync(_get)

    today = _today()
    candidates: Dict[str, str] = {}
    for row in rows:
        opportunity_id = row.get("opportunity_id")
        opportunity = row.get("opportunities") or {}
        if not opportunity_id or opportunity_id in candidates:
            continue
        if (opportunity.get("status") or "") != "active":
            continue
        deadline = _as_date(opportunity.get("application_deadline"))
        if deadline and deadline < today:
            continue
        # Oldest first, so the user's Available Apps list reads chronologically.
        candidates[opportunity_id] = str(opportunity.get("created_at") or "")

    return [oid for oid, _ in sorted(candidates.items(), key=lambda pair: pair[1])]


async def _backfill_available_applications(user_id: str, opportunity_ids: List[str]) -> int:
    """
    Create the `applications` rows this user is missing, and report how many were created.

    `applications` has no unique constraint on (user_id, opportunity_id), so the existing
    rows are read and skipped first -- otherwise every future "Edit my interests" would
    stack another duplicate row for the same opportunity.
    """
    def _run():
        existing = (
            supabase.from_("applications")
            .select("opportunity_id")
            .eq("user_id", user_id)
            .execute()
        ).data or []
        already_have = {row["opportunity_id"] for row in existing if row.get("opportunity_id")}

        missing = [oid for oid in opportunity_ids if oid not in already_have]
        if not missing:
            return 0

        supabase.from_("applications").insert([
            {
                "user_id": user_id,
                "opportunity_id": opportunity_id,
                "status": "available",
                # Same no-response default the post-time engine sets (Phase I / Section 5.2).
                "next_reminder_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            }
            for opportunity_id in missing
        ]).execute()
        return len(missing)

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_run)


async def run_matching_engine_for_user(user_id: str) -> int:
    """
    The user-side counterpart of `run_matching_engine`: back-fill this user's matches.

    Section 4's engine fires when an opportunity goes *live*, which leaves a hole: an
    opportunity posted before a user registered had no `applications` row for them, and
    the Available Apps list reads those rows -- so the user was told nothing matched even
    when every tag matched, permanently (the post-time engine has already run and won't
    run again for that opportunity). This is the other half of the same engine, called
    whenever interests are saved: at registration and on every "Edit my interests".

    Deliberately sends **no** New Match Notifications. Section 1.3 step 3 / the example in
    Message-Flow-Examples.md Section 3 expect exactly one reply at that moment (the tag
    confirmation + Main Menu), and a user whose interests match six live opportunities
    would otherwise be buried in six interactive messages on the spot. The rows are what
    Available Apps lists, and opening a row re-sends the Phase H notification anyway.

    Returns the number of rows created. Never raises for one bad opportunity: the caller
    is mid-registration and a matching problem must not cost the user their interests.
    """
    try:
        tag_ids = await _get_user_tag_ids(user_id)
        if not tag_ids:
            logger.info(f"USER_MATCHING_SKIP: user_id={user_id} has no interests")
            return 0

        opportunity_ids = await _get_live_opportunity_ids_for_tags(tag_ids)
        if not opportunity_ids:
            logger.info(f"USER_MATCHING_DONE: user_id={user_id} live_matches=0 created=0")
            return 0

        created = await _backfill_available_applications(user_id, opportunity_ids)
        logger.info(
            f"USER_MATCHING_DONE: user_id={user_id} "
            f"live_matches={len(opportunity_ids)} created={created}"
        )
        return created
    except Exception:
        logger.exception(f"USER_MATCHING_FAILED: user_id={user_id}")
        return 0
