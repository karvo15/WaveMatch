"""
My Applications -- the three list views (Phase N bullet 2) plus the Section 9
"Add manually" (9.1) and "Edit an item" (9.2) flows built on top of them (Phase M).

Spec: 3-Full-Product-Logic.md Sections 2 / 9.1 / 9.2 / 14.2,
      4-Message-Flow-Examples.md Sections 10-11.

Why the lists ship with the add flow (they live in the same module on purpose):
Section 9.1 is explicit that "Add manually" is *phase-specific, not generic* -- the user
opens the list they want to add into first, so the bot never has to ask "what stage is
this at?". That makes the three lists a hard prerequisite for the add flow, so Phase M
could not be finished without them (this also ticks Phase N bullet 2).

Everything here reads and writes the user's own `applications` row: the
personal-tracking-copy columns (`custom_title`, `custom_description`, `custom_deadline`,
`custom_result_date`) plus `scheduled_event_date`. Editing a poster-sourced item never
writes back to the poster's `opportunities` row (Section 9.2) -- the date columns are the
same ones Section 3D's propagation touches, which is why both sides agree on who owns
what: the user owns `custom_*`, the poster owns the opportunity.
"""

import logging
from datetime import date, datetime, timedelta, time, timezone
from typing import Any, Dict, List, Optional, Tuple

import anyio
from dotenv import load_dotenv

from application_flow import (
    _application_title,
    _extract_message_text,
    _normalise_time_text,
    _parse_absolute_date,
    send_deletion_confirmation,
)
from conversation import (
    _db_semaphore,
    clear_conversation_state,
    get_conversation_state,
    set_conversation_state,
)
from database import supabase
from whatsapp import (
    send_ongoing_checkin_notification,
    send_outcome_check_notification,
    send_whatsapp_buttons,
    send_whatsapp_list_message,
    send_whatsapp_message,
)

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The three lists inside My Applications (Section 2). "Available" is deliberately absent:
# Section 9.1 reserves that list for bot-matched opportunities, never manual entries.
_LISTS: Dict[str, Dict[str, str]] = {
    "ongoing": {
        "label": "Ongoing",
        "emoji": "\U0001F4CB",
        "date_field": "custom_deadline",
        "date_label": "deadline",
        "date_prompt": "What's the deadline? (e.g. Sept 20 -- or reply \"skip\")",
    },
    "under_review": {
        "label": "Under Review",
        "emoji": "\u23F3",
        "date_field": "custom_result_date",
        "date_label": "result date",
        "date_prompt": "Do you know when results come out? (e.g. Sept 1 -- or reply \"skip\")",
    },
    "scheduled": {
        "label": "Scheduled",
        "emoji": "\U0001F4C5",
        "date_field": "scheduled_event_date",
        "date_label": "event date",
        "date_prompt": "When is the event? (e.g. Nov 5 -- or reply \"skip\")",
    },
}

LIST_PAGE_SIZE = 10  # WhatsApp list cap: 10 rows total (Section 10.1)
LIST_ACTION_ROWS = 3  # Add manually / Edit an item / Delete an item (Section 2)

# Row/button id separators are "|" rather than "_" because the status values
# ("under_review") and the uuid payloads both contain "_" and "-".
_SEP = "|"


async def _user_id_for(phone_number: str) -> Optional[str]:
    def _get():
        res = supabase.from_("users").select("id").eq("phone_number", phone_number).limit(1).execute()
        return res.data[0]["id"] if res.data else None

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _fetch_applications(user_id: str, status: str) -> List[Dict[str, Any]]:
    def _get():
        res = (
            supabase.from_("applications")
            .select(
                "id, status, custom_title, custom_description, custom_deadline, "
                "custom_result_date, scheduled_event_date, next_reminder_at, opportunity_id, "
                "opportunities(title, type, application_deadline, result_date, event_start_date)"
            )
            .eq("user_id", user_id)
            .eq("status", status)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


def _title_for(application: Dict[str, Any]) -> str:
    """The user's own label wins over the poster's title (their personal tracking copy)."""
    opportunity = application.get("opportunities") or {}
    return application.get("custom_title") or opportunity.get("title") or "Application"


def _effective_date(application: Dict[str, Any], status: str) -> Optional[str]:
    """
    The date that actually applies to this row.

    Precedence: the user's own override wins, then the poster's value. Section 9.2 makes
    `custom_*` the user's "personal tracking copy", and a field the user can edit but
    never sees would be broken -- so this deliberately *inverts* the COALESCE order of the
    `applications_with_effective_dates` view (poster first). A later poster edit still
    reaches the user through the mandatory Section 3.1 notification, and `scheduled_event_date`
    is a single shared field that Phase M propagation only overwrites while it still
    matches the old poster value -- so the two sides never disagree silently.
    """
    opportunity = application.get("opportunities") or {}
    if status == "ongoing":
        return application.get("custom_deadline") or opportunity.get("application_deadline")
    if status == "under_review":
        return application.get("custom_result_date") or opportunity.get("result_date")
    return application.get("scheduled_event_date") or opportunity.get("event_start_date")


def _row_title(text: str) -> str:
    return text if len(text) <= 24 else text[:21] + "..."


def _row_description(text: str) -> str:
    return text if len(text) <= 72 else text[:69] + "..."


def _describe(application: Dict[str, Any], status: str) -> str:
    opportunity = application.get("opportunities") or {}
    parts = []
    if opportunity.get("type"):
        parts.append(str(opportunity["type"]))
    effective = _effective_date(application, status)
    if effective:
        parts.append(f"{_LISTS[status]['date_label'].capitalize()}: {effective}")
    if application.get("custom_description"):
        parts.append(str(application["custom_description"]))
    return _row_description(" \u00b7 ".join(parts))


async def handle_my_applications_button(phone_number: str) -> None:
    """Main-menu "My Applications": let the user pick which list to open (Section 2)."""
    await send_whatsapp_buttons(
        phone_number,
        body="\U0001F4C1 My Applications \u2014 which list?",
        buttons=[
            {"type": "reply", "reply": {"id": f"my_list_{key}", "title": f"{meta['emoji']} {meta['label']}"}}
            for key, meta in _LISTS.items()
        ],
    )
    logger.info(f"MY_APPLICATIONS_MENU: phone_number={phone_number}")


async def handle_my_list(phone_number: str, status: str, offset: int = 0, mode: str = "open") -> None:
    """
    Show one My Applications list (Section 2), or the Edit/Delete item picker over it.

    Every list carries the three Section 2 actions as extra rows ("Add manually" is the
    Section 9.1 entry point, and it is deliberately *inside* the list so the target
    status is already known). Item rows are paginated around those actions; titles and
    descriptions respect the 24/72-char caps.
    """
    if status not in _LISTS:
        await send_whatsapp_message(phone_number, body="That list isn't available.")
        return

    meta = _LISTS[status]
    user_id = await _user_id_for(phone_number)
    if not user_id:
        await send_whatsapp_message(phone_number, body="You don't have any applications yet.")
        return

    applications = await _fetch_applications(user_id, status)
    if not applications:
        await send_whatsapp_message(
            phone_number,
            body=f"Nothing in your {meta['label']} list yet.",
        )
        return

    # Action rows only apply to the plain list view; the pickers are item rows only.
    reserved = LIST_ACTION_ROWS if mode == "open" else 0
    per_page = LIST_PAGE_SIZE - reserved
    has_more = len(applications) > offset + per_page
    take = (per_page - 1) if has_more else per_page
    page = applications[offset : offset + take]

    row_prefix = {"open": "my_item", "edit": "my_edit", "delete": "my_del"}.get(mode, "my_item")
    rows = [
        {
            "id": f"{row_prefix}{_SEP}{app['id']}",
            "title": _row_title(_title_for(app)),
            "description": _describe(app, status),
        }
        for app in page
    ]

    if has_more:
        rows.append(
            {
                "id": f"my_more{_SEP}{mode}{_SEP}{status}{_SEP}{offset + take}",
                "title": "More \u2192",
                "description": "",
            }
        )

    if mode == "open":
        rows.extend(
            [
                {
                    "id": f"my_add{_SEP}{status}",
                    "title": "\u2795 Add manually",
                    "description": _row_description("Track something that wasn't posted here"),
                },
                {"id": f"my_editpick{_SEP}{status}", "title": "\u270F\uFE0F Edit an item", "description": ""},
                {"id": f"my_delpick{_SEP}{status}", "title": "\U0001F5D1\uFE0F Delete an item", "description": ""},
            ]
        )

    body = {
        "open": f"\U0001F4C1 Your {meta['label']} list \u2014 tap an item to open it:",
        "edit": f"\u270F\uFE0F Which {meta['label']} item do you want to edit?",
        "delete": f"\U0001F5D1\uFE0F Which {meta['label']} item do you want to delete?",
    }[mode]

    await send_whatsapp_list_message(
        phone_number,
        body=body,
        sections=[{"title": f"{meta['emoji']} {meta['label']}", "rows": rows}],
    )
    logger.info(
        f"MY_LIST_SHOWN: phone_number={phone_number} status={status} mode={mode} "
        f"offset={offset} total={len(applications)} shown={len(page)}"
    )


async def handle_item_open(phone_number: str, application_id: str) -> None:
    """
    Tapping an item re-sends that status's own proactive message, so the user gets the
    same buttons they'd get from the scheduled reminder -- Ongoing check-in for an
    ongoing row, the outcome check for one under review. (Mirrors how tapping a row in
    Available Apps re-sends the Phase H New Match Notification.)
    """
    application = await _get_application(application_id)
    if not application:
        await send_whatsapp_message(phone_number, body="That application is no longer in your list.")
        return

    status = application.get("status")
    title = _title_for(application)

    if status == "ongoing":
        await send_ongoing_checkin_notification(
            phone_number, title, application_id, _effective_date(application, "ongoing")
        )
    elif status == "under_review":
        await send_outcome_check_notification(phone_number, title, application_id)
    elif status == "scheduled":
        event_date = _effective_date(application, "scheduled")
        when = f" on {event_date}" if event_date else ""
        await send_whatsapp_message(phone_number, body=f"\U0001F4C5 {title} is scheduled{when}.")
    logger.info(f"MY_ITEM_OPENED: phone_number={phone_number} application_id={application_id} status={status}")


async def _get_application(application_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch one applications row with its opportunity fields attached."""
    if not application_id:
        return None

    def _get():
        res = (
            supabase.from_("applications")
            .select(
                "id, status, custom_title, custom_description, custom_deadline, "
                "custom_result_date, scheduled_event_date, next_reminder_at, opportunity_id, "
                "opportunities(title, type, application_deadline, result_date, event_start_date)"
            )
            .eq("id", application_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _update_application(application_id: str, fields: Dict[str, Any]) -> None:
    def _update():
        payload = dict(fields)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        return supabase.from_("applications").update(payload).eq("id", application_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_update)
# ============================================================
# SECTION 9.1 -- ADD AN EVENT/APPLICATION MANUALLY
#
# Entry point is the "Add manually" row *inside* one of the three lists, so the target
# status is already known and the bot never asks "what stage is this at" (Section 9.1).
# ============================================================

MANUAL_ADD_FLOW = "manual_add"
EDIT_ITEM_FLOW = "edit_item"


async def start_manual_add(phone_number: str, status: str) -> None:
    """Begin the Section 9.1 manual-add flow for the list the user opened."""
    if status not in _LISTS:
        await send_whatsapp_message(phone_number, body="That list isn't available.")
        return
    await clear_conversation_state(phone_number)
    await set_conversation_state(
        phone_number=phone_number, flow=MANUAL_ADD_FLOW, step="awaiting_manual_title", data={"status": status}
    )
    logger.info(f"MANUAL_ADD_START: phone_number={phone_number} status={status}")
    await send_whatsapp_message(phone_number, body="\u2795 What's it called?")


def _state_data(conversation_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return (conversation_state or {}).get("collected_data") or {}


def _pretty(value: Optional[date]) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}" if value else "not set"


def _under_review_reminder(result_date: Optional[date]) -> str:
    """When to check in on an under_review item (Sections 8.4 / 7.4)."""
    moment = (
        datetime.combine(result_date + timedelta(days=1), time(9, 0), tzinfo=timezone.utc)
        if result_date
        else datetime.now(timezone.utc) + timedelta(days=3)
    )
    return moment.isoformat()


def _initial_reminder(status: str, parsed: Optional[date]) -> Optional[str]:
    """First reminder for a freshly added item (None for `scheduled` -- nothing to chase)."""
    if status == "ongoing":
        return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    if status == "under_review":
        return _under_review_reminder(parsed)
    return None


def _added_confirmation(status: str, parsed: Optional[date]) -> str:
    label = _LISTS[status]["label"]
    if status == "ongoing":
        return f"\u2705 Added to your {label} list. I'll check in every couple of days."
    if status == "under_review":
        tail = f" I'll check in with you after {_pretty(parsed)}." if parsed else " I'll check in with you soon."
        return f"\u2705 Added to your {label} list.{tail}"
    tail = f" That's {_pretty(parsed)}." if parsed else ""
    return f"\u2705 Added to your {label} list.{tail}"


async def _insert_application(fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    def _insert():
        return supabase.from_("applications").insert(fields).execute()

    async with _db_semaphore:
        res = await anyio.to_thread.run_sync(_insert)
    return (res.data or [None])[0]


async def handle_manual_title_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Step 1 of Section 9.1: the item's name."""
    data = _state_data(conversation_state)
    status = data.get("status")
    if status not in _LISTS:
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="Something went wrong \u2014 please start again from My Applications.")
        return

    title = (_extract_message_text(payload) or "").strip()
    if not title:
        await send_whatsapp_message(phone_number, body="I need a name for it \u2014 what's it called?")
        return

    data["title"] = title[:120]
    await set_conversation_state(
        phone_number=phone_number, flow=MANUAL_ADD_FLOW, step="awaiting_manual_description", data=data
    )
    await send_whatsapp_message(phone_number, body="Any description? (or reply \"skip\")")


async def handle_manual_description_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Step 2 of Section 9.1: the optional description."""
    data = _state_data(conversation_state)
    status = data.get("status")
    if status not in _LISTS:
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="Something went wrong \u2014 please start again from My Applications.")
        return

    text = (_extract_message_text(payload) or "").strip()
    data["description"] = None if _normalise_time_text(text) in ("skip", "") else text[:500]
    await set_conversation_state(
        phone_number=phone_number, flow=MANUAL_ADD_FLOW, step="awaiting_manual_date", data=data
    )
    await send_whatsapp_message(phone_number, body=_LISTS[status]["date_prompt"])


async def handle_manual_date_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Step 3 of Section 9.1: the one date that matters for this stage, then create the row."""
    data = _state_data(conversation_state)
    status = data.get("status")
    meta = _LISTS.get(status)
    if not meta:
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="Something went wrong \u2014 please start again from My Applications.")
        return

    text = (_extract_message_text(payload) or "").strip()
    parsed: Optional[date] = None
    if _normalise_time_text(text) not in ("skip", ""):
        parsed = _parse_absolute_date(_normalise_time_text(text), datetime.now(timezone.utc))
        if parsed is None:
            await send_whatsapp_message(
                phone_number, body=f"I couldn't read that date. {meta['date_prompt']}"
            )
            logger.info(f"MANUAL_ADD_DATE_UNPARSED: phone_number={phone_number} text={text!r}")
            return

    # The row has to be owned by the user who is adding it -- applications.user_id is
    # NOT NULL, and it is what every My Applications query filters on.
    user_id = await _user_id_for(phone_number)
    if not user_id:
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="Something went wrong \u2014 please start again from My Applications.")
        return

    fields: Dict[str, Any] = {
        "user_id": user_id,
        # opportunity_id stays NULL: this is the user's own entry, not a matched post
        # (Section 9.1).
        "opportunity_id": None,
        "custom_title": data.get("title"),
        "custom_description": data.get("description"),
        "status": status,
        "reminder_interval_days": 2,
        "deadline_heads_up_sent": False,
        meta["date_field"]: parsed.isoformat() if parsed else None,
        "next_reminder_at": _initial_reminder(status, parsed),
    }
    try:
        created = await _insert_application(fields)
    except Exception:
        # Never leave the user mid-flow with no reply if the write fails.
        await clear_conversation_state(phone_number)
        logger.exception(f"MANUAL_ADD_FAILED: phone_number={phone_number} status={status}")
        await send_whatsapp_message(
            phone_number, body="Sorry \u2014 I couldn't save that. Please try again from My Applications."
        )
        return

    await clear_conversation_state(phone_number)
    logger.info(
        f"MANUAL_ADD_CREATED: phone_number={phone_number} status={status} "
        f"application_id={(created or {}).get('id')} date={fields[meta['date_field']]}"
    )
    await send_whatsapp_message(phone_number, body=_added_confirmation(status, parsed))


# ============================================================
# SECTION 9.2 -- EDIT AN EXISTING TRACKED ITEM
#
# Editable fields are the user's personal tracking copy: their own title, description,
# and the one date that matters for the row's stage. A poster-sourced item's underlying
# `opportunities` row is never touched (Section 9.2).
# ============================================================


async def start_edit_item(phone_number: str, application_id: str) -> None:
    """Ask which field to change on one item."""
    application = await _get_application(application_id)
    if not application:
        await send_whatsapp_message(phone_number, body="That item is no longer in your list.")
        return
    status = application.get("status")
    meta = _LISTS.get(status)
    if not meta:
        await send_whatsapp_message(phone_number, body="That item can't be edited from here.")
        return

    await send_whatsapp_buttons(
        phone_number,
        body=f"\u270F\uFE0F What do you want to change on {_row_title(_title_for(application))}?",
        buttons=[
            {
                "type": "reply",
                "reply": {"id": f"editf{_SEP}date{_SEP}{application_id}", "title": f"\U0001F4C5 {meta['date_label'].capitalize()}"},
            },
            {"type": "reply", "reply": {"id": f"editf{_SEP}desc{_SEP}{application_id}", "title": "\U0001F4DD Description"}},
            {"type": "reply", "reply": {"id": f"editf{_SEP}title{_SEP}{application_id}", "title": "\U0001F3F7\uFE0F Title"}},
        ],
    )
    logger.info(f"EDIT_ITEM_START: phone_number={phone_number} application_id={application_id} status={status}")


async def handle_edit_field_button(phone_number: str, button_id: str) -> None:
    """The user chose *which* field to edit; now ask for its new value."""
    parts = button_id.split(_SEP)
    if len(parts) != 3:
        await send_whatsapp_message(phone_number, body="Sorry, I didn't catch that. Please try again from My Applications.")
        return
    field, application_id = parts[1], parts[2]

    application = await _get_application(application_id)
    if not application:
        await send_whatsapp_message(phone_number, body="That item is no longer in your list.")
        return
    status = application.get("status")
    meta = _LISTS.get(status)
    if not meta:
        await send_whatsapp_message(phone_number, body="That item can't be edited from here.")
        return

    await clear_conversation_state(phone_number)
    await set_conversation_state(
        phone_number=phone_number,
        flow=EDIT_ITEM_FLOW,
        step="awaiting_edit_value",
        data={"application_id": application_id, "field": field, "status": status},
    )
    prompts = {
        "date": f"Send me the new {meta['date_label']} (e.g. Sept 25).",
        "desc": "Send me the new description.",
        "title": "Send me the new title.",
    }
    await send_whatsapp_message(phone_number, body=prompts.get(field, "Send me the new value."))


async def handle_edit_value_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Save the new value onto the user's personal tracking copy (Section 9.2)."""
    data = _state_data(conversation_state)
    application_id = data.get("application_id")
    field = data.get("field")

    application = await _get_application(application_id)
    if not application:
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="That item is no longer in your list.")
        return

    meta = _LISTS.get(data.get("status")) or _LISTS.get(application.get("status"))
    if not meta:
        await clear_conversation_state(phone_number)
        await send_whatsapp_message(phone_number, body="That item can't be edited from here.")
        return

    text = (_extract_message_text(payload) or "").strip()

    if field == "title":
        if not text:
            await send_whatsapp_message(phone_number, body="I need a title \u2014 what should it say?")
            return
        await _update_application(application_id, {"custom_title": text[:120]})
        acknowledgement = f"\u2705 Updated the title to \"{text[:120]}\"."

    elif field == "desc":
        description = None if _normalise_time_text(text) in ("skip", "") else text[:500]
        await _update_application(application_id, {"custom_description": description})
        acknowledgement = "\u2705 Updated the description." if description else "\u2705 Cleared the description."

    else:
        parsed = _parse_absolute_date(_normalise_time_text(text), datetime.now(timezone.utc)) if text else None
        if parsed is None:
            await send_whatsapp_message(
                phone_number, body=f"I couldn't read that date. Send me the new {meta['date_label']} (e.g. Sept 25)."
            )
            return
        fields: Dict[str, Any] = {meta["date_field"]: parsed.isoformat()}
        if meta["date_field"] == "custom_deadline":
            # Same rule as Section 3D: a moved deadline re-arms the one-time heads-up.
            fields["deadline_heads_up_sent"] = False
        if meta["date_field"] == "custom_result_date":
            fields["next_reminder_at"] = _under_review_reminder(parsed)
        await _update_application(application_id, fields)
        acknowledgement = f"\u2705 Updated the {meta['date_label']} to {_pretty(parsed)}."

    await clear_conversation_state(phone_number)
    logger.info(
        f"EDIT_ITEM_SAVED: phone_number={phone_number} application_id={application_id} field={field}"
    )
    await send_whatsapp_message(phone_number, body=acknowledgement)


# ============================================================
# SECTION 9.3 -- DELETE AN ITEM (reuses the single Section 13 confirmation)
# ============================================================


async def start_delete_item(phone_number: str, application_id: str) -> None:
    """Route a list-based delete through the same confirmation every other delete uses."""
    application = await _get_application(application_id)
    if not application:
        await send_whatsapp_message(phone_number, body="That item is no longer in your list.")
        return
    await send_deletion_confirmation(
        phone_number, application_id, _application_title(application), reason="delete"
    )
    logger.info(f"DELETE_ITEM_CONFIRM_PROMPT: phone_number={phone_number} application_id={application_id}")
