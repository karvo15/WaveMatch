"""
User-side application flow handlers for WaveMatch (Phase I).

Covers the "Available" stage of the application lifecycle, driven by the three
buttons on the New Match Notification (3-Full-Product-Logic.md Section 5):

  Apply Now        -> status 'available' -> 'ongoing', send the link, +2 day reminder
  Remind Me Later  -> ask for a custom time (free text, Section 14) else default to
                      +2 days; status stays 'available'
  Ignore           -> deletion confirmation first (Section 13), then delete the row

Also provides:
  * the reusable deletion-confirmation step (Section 13) -- built once, called from
    every deletion trigger (Ignore now; Never / No / Delete in later phases);
  * the (status, action) -> handler dispatch table from 2-Architecture-Doc.md
    Section 3B, implemented as a dict rather than an if/elif chain.

Interaction types follow 3-Full-Product-Logic.md Section 0 (the authoritative
table): the New Match buttons are buttons (3), the Remind-Me-Later time choice is
free text, and the deletion confirmation is buttons (2).

The Section 5.2 "no response at all" fallback (behave as if the user tapped Remind
Me Later, i.e. default +2 days) is implemented where the row is created -- see
matching.py, which sets next_reminder_at = now + 2 days on each new `applications`
row. Apply Now overwrites it with a fresh +2 days; Remind Me Later overwrites it
with the chosen time; Ignore deletes the row entirely.
"""

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import anyio
from dotenv import load_dotenv

from conversation import (
    _db_semaphore,
    clear_conversation_state,
    set_conversation_state,
)
from database import supabase
from whatsapp import send_whatsapp_buttons, send_whatsapp_message

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default follow-up delay when the user gives no usable time (Section 5.2).
REMINDER_DEFAULT_DAYS = 2

# Prompt shown after "Remind Me Later" (free text, Section 0 / Section 14.2).
REMINDER_PROMPT = (
    "When should I remind you? Reply with a time (e.g. \"in 3 days\", \"in 5 hours\", "
    "\"Sept 18\"), or reply \"default\" for 2 days."
)

# Button-id prefixes this module owns. The ids are stateless (they carry the
# `applications` row id), so handlers never need conversation_states to know which
# row was tapped. Exported so webhook.py routes on the same source of truth.
APPLICATION_BUTTON_PREFIXES = ("apply_now_", "remind_later_", "ignore_")
DELETION_BUTTON_PREFIXES = ("confirm_delete_", "cancel_delete_")


# ============================================================
# DB HELPERS
# ============================================================

async def _get_application(application_id: str) -> Optional[Dict[str, Any]]:
    """Fetch an application (with its linked opportunity's title/link/deadline)."""
    def _get():
        return (
            supabase.from_("applications")
            .select(
                "id, user_id, status, opportunity_id, custom_title, "
                "opportunities(title, link, application_deadline)"
            )
            .eq("id", application_id)
            .limit(1)
            .execute()
        )

    async with _db_semaphore:
        res = await anyio.to_thread.run_sync(_get)
    return res.data[0] if res.data else None


async def _update_application(application_id: str, fields: Dict[str, Any]) -> None:
    """Update the given fields on an application, refreshing updated_at."""
    def _update():
        data = dict(fields)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return supabase.from_("applications").update(data).eq("id", application_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_update)


async def _delete_application(application_id: str) -> None:
    """Delete an application row."""
    def _delete():
        return supabase.from_("applications").delete().eq("id", application_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_delete)


def _application_title(application: Dict[str, Any]) -> str:
    """Human title for an application (linked opportunity title, else custom title)."""
    opportunity = application.get("opportunities") or {}
    return opportunity.get("title") or application.get("custom_title") or "this opportunity"


def _extract_message_text(payload: Dict[str, Any]) -> str:
    """Pull the free-text body out of a webhook payload (empty string on any miss)."""
    try:
        message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        return message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


# ============================================================
# REMINDER-TIME PARSING (Section 14.2 free-text formats)
# ============================================================

_RELATIVE_RE = re.compile(
    r"^in\s+(\d+)\s*(day|days|hour|hours|hr|hrs|min|mins|minute|minutes)$"
)

_FULL_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)
_PARTIAL_DATE_FORMATS = ("%d/%m", "%d %B", "%d %b", "%B %d", "%b %d")


def _normalise_time_text(raw: str) -> str:
    """
    Lower-case, strip trailing periods, collapse whitespace, and fix the one month
    abbreviation Python's strptime rejects: Section 14.2 lists "Sept 20", but %b
    only knows "Sep".
    """
    text = (raw or "").strip().lower().replace(".", "")
    text = re.sub(r"\bsept\b", "sep", text)
    return " ".join(text.split())


def _parse_absolute_date(text: str, now: datetime) -> Optional[date]:
    """Parse an absolute date; a missing year means the next occurrence."""
    for fmt in _FULL_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    for fmt in _PARTIAL_DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date().replace(year=now.year)
        except ValueError:
            continue
        if parsed < now.date():
            parsed = parsed.replace(year=now.year + 1)
        return parsed
    return None


def _parse_reminder_time(raw_text: str, now: Optional[datetime] = None) -> Tuple[datetime, str]:
    """
    Turn a free-text reminder time into (when_utc, human_phrase).

    Relative ("in 3 days", "in 5 hours"), absolute ("Sept 18", "20/09",
    "20/09/2026"), and the literal "default" are accepted (Section 14.2). Anything
    else -- including an empty reply -- falls back to the default +2 days, exactly
    as Section 5.2 specifies. Date-only inputs are scheduled for 09:00 UTC.
    """
    now = now or datetime.now(timezone.utc)
    default_when = now + timedelta(days=REMINDER_DEFAULT_DAYS)
    text = _normalise_time_text(raw_text)

    if not text or text == "default":
        return default_when, f"in {REMINDER_DEFAULT_DAYS} days"

    match = _RELATIVE_RE.match(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if amount <= 0:
            return default_when, f"in {REMINDER_DEFAULT_DAYS} days"
        if unit.startswith("day"):
            return now + timedelta(days=amount), f"in {amount} day(s)"
        if unit.startswith("hr") or unit.startswith("hour"):
            return now + timedelta(hours=amount), f"in {amount} hour(s)"
        return now + timedelta(minutes=amount), f"in {amount} minute(s)"

    absolute = _parse_absolute_date(text, now)
    if absolute:
        when = datetime(absolute.year, absolute.month, absolute.day, 9, 0, tzinfo=timezone.utc)
        return when, f"on {absolute.strftime('%b %d, %Y')}"

    return default_when, f"in {REMINDER_DEFAULT_DAYS} days"


# ============================================================
# REUSABLE DELETION CONFIRMATION (Section 13)
# ============================================================

async def send_deletion_confirmation(phone_number: str, application_id: str, item_title: str) -> None:
    """
    The single reusable "are you sure?" step (Section 13). Every deletion trigger
    (Ignore now; Never / No / Delete later) calls this rather than rolling its own.
    Stateless: the row id is carried in the button ids.
    """
    await send_whatsapp_buttons(
        phone_number,
        body=f"Are you sure? This will remove {item_title} from your list and can't be undone.",
        buttons=[
            {"type": "reply", "reply": {"id": f"confirm_delete_{application_id}", "title": "\u2705 Confirm"}},
            {"type": "reply", "reply": {"id": f"cancel_delete_{application_id}", "title": "\u21a9\ufe0f Cancel"}},
        ],
    )


# ============================================================
# ACTION HANDLERS (each small + independently testable -- Architecture 3B)
# ============================================================

async def _handle_apply_now(phone_number: str, application_id: str, application: Dict[str, Any]) -> None:
    """available + Apply Now -> ongoing, send the link, +2 day reminder (Section 5.1)."""
    opportunity = application.get("opportunities") or {}
    link = opportunity.get("link")

    await _update_application(
        application_id,
        {
            "status": "ongoing",
            "next_reminder_at": (
                datetime.now(timezone.utc) + timedelta(days=REMINDER_DEFAULT_DAYS)
            ).isoformat(),
        },
    )

    body = "Opening the link now \u2014 good luck! \U0001f340 I'll check in with you in a couple of days."
    if link:
        body = f"{body}\n{link}"
    await send_whatsapp_message(phone_number, body=body)
    logger.info(f"APPLY_NOW_OK: phone_number={phone_number} application_id={application_id}")


async def _handle_remind_later(phone_number: str, application_id: str, application: Dict[str, Any]) -> None:
    """available + Remind Me Later -> ask for a time; status stays available (Section 5.2)."""
    await set_conversation_state(
        phone_number=phone_number,
        flow="remind_later",
        step="awaiting_time",
        data={"application_id": application_id},
    )
    await send_whatsapp_message(phone_number, body=REMINDER_PROMPT)
    logger.info(f"REMIND_LATER_PROMPT: phone_number={phone_number} application_id={application_id}")


async def _handle_ignore(phone_number: str, application_id: str, application: Dict[str, Any]) -> None:
    """available + Ignore -> confirmation first; the row is deleted only on Confirm (Section 13)."""
    await send_deletion_confirmation(phone_number, application_id, _application_title(application))
    logger.info(f"IGNORE_CONFIRM_PROMPT: phone_number={phone_number} application_id={application_id}")


# ============================================================
# DISPATCH TABLE (2-Architecture-Doc.md Section 3B -- dict, not if/elif)
# ============================================================

# Only the `available` rows exist in Phase I; later phases add their own
# (status, action) entries here -- the single place that stays readable as more
# button types arrive.
_DISPATCH = {
    ("available", "apply_now"): _handle_apply_now,
    ("available", "remind_later"): _handle_remind_later,
    ("available", "ignore"): _handle_ignore,
}


def _split_application_button(button_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a stateless button id into (action, application_id)."""
    for action in ("apply_now", "remind_later", "ignore"):
        prefix = action + "_"
        if button_id.startswith(prefix):
            return action, button_id[len(prefix):]
    return None, None


# ============================================================
# ENTRY POINTS (called from webhook.py)
# ============================================================

async def handle_application_button(phone_number: str, button_id: str) -> None:
    """
    Route an Apply Now / Remind Me Later / Ignore tap through the (status, action)
    dispatch table. Guards against rows that no longer exist or have moved on.
    """
    action, application_id = _split_application_button(button_id)
    if not action or not application_id:
        logger.warning(f"APPLICATION_BUTTON_UNPARSEABLE: phone_number={phone_number} button_id={button_id!r}")
        return

    application = await _get_application(application_id)
    if not application:
        await send_whatsapp_message(phone_number, body="That opportunity is no longer on your list.")
        return

    status = application.get("status")
    handler = _DISPATCH.get((status, action))
    if handler is None:
        logger.info(
            f"APPLICATION_ACTION_UNHANDLED: phone_number={phone_number} "
            f"status={status} action={action}"
        )
        await send_whatsapp_message(phone_number, body="That action isn't available for this application anymore.")
        return

    logger.info(
        f"APPLICATION_ACTION: phone_number={phone_number} status={status} "
        f"action={action} application_id={application_id}"
    )
    await handler(phone_number, application_id, application)


async def handle_deletion_confirmation(phone_number: str, button_id: str) -> None:
    """Handle Confirm / Cancel on the reusable deletion confirmation (Section 13)."""
    # "confirm_delete_<uuid>" -> ["confirm", "delete", "<uuid>"]
    parts = button_id.split("_", 2)
    if len(parts) != 3:
        logger.warning(f"DELETION_CONFIRMATION_UNPARSEABLE: phone_number={phone_number} button_id={button_id!r}")
        return

    action, application_id = parts[0], parts[2]

    if action == "confirm":
        application = await _get_application(application_id)
        if not application:
            await send_whatsapp_message(phone_number, body="That item is already gone.")
            return
        await _delete_application(application_id)
        logger.info(f"DELETION_CONFIRMED: phone_number={phone_number} application_id={application_id}")
        await send_whatsapp_message(phone_number, body="No problem \u2014 I won't show you this one again.")
    else:
        # Cancel -> nothing changes (Section 13, step 4).
        await send_whatsapp_message(phone_number, body="Okay, I've kept it in your list.")


async def handle_remind_later_time_step(
    phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]
) -> None:
    """Free-text reply to the Remind-Me-Later prompt: set next_reminder_at (Section 5.2)."""
    application_id = (conversation_state.get("collected_data") or {}).get("application_id")
    application = await _get_application(application_id) if application_id else None
    if not application or application.get("status") != "available":
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="That opportunity is no longer available to remind you about.")
        return

    when, human = _parse_reminder_time(_extract_message_text(payload))
    await _update_application(application_id, {"next_reminder_at": when.isoformat()})
    await clear_conversation_state(phone_number)
    logger.info(
        f"REMIND_LATER_SET: phone_number={phone_number} application_id={application_id} "
        f"next_reminder_at={when.isoformat()}"
    )
    await send_whatsapp_message(phone_number, body=f"Got it \u2014 I'll remind you {human}.")