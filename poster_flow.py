"""
Poster flow handlers for WaveMatch.
Handles poster opportunity creation and editing flows.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timezone
import anyio
import tags  # Phase N: shared tag matching + maintenance
from dotenv import load_dotenv

from conversation import get_conversation_state, set_conversation_state, clear_conversation_state, _db_semaphore
from database import supabase
from whatsapp import send_whatsapp_message, send_whatsapp_buttons, send_whatsapp_list_message, send_new_match_notification
from tags import parse_interests  # Phase N: shared layered matching (Section 10.2)
from matching import run_matching_engine  # Phase H: Matching Engine
from propagation import propagate_opportunity_edit  # Phase M: poster edit propagation

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper functions for DB operations with semaphore wrapping

async def _get_poster_id_from_phone(phone_number: str) -> Optional[str]:
    """Get poster ID from phone number, returns None if not found."""
    def _get():
        return supabase.from_("posters").select("id").eq("phone_number", phone_number).execute()
    async with _db_semaphore:
        res = await anyio.to_thread.run_sync(_get)
    if res.data and len(res.data) > 0:
        return res.data[0]["id"]
    return None

async def _create_opportunity(collected_data: Dict[str, Any]) -> Optional[str]:
    """Insert a new opportunity and return its ID."""
    def _create():
        data = {
            "poster_id": collected_data["poster_id"],
            "title": collected_data["title"],
            "description": collected_data.get("description"),
            "type": collected_data["type"],
            "application_start_date": collected_data.get("application_start_date"),
            "application_deadline": collected_data["application_deadline"],
            "result_date": collected_data.get("result_date"),
            "event_start_date": collected_data.get("event_start_date"),
            "link": collected_data["link"],
            "status": collected_data.get("status", "active")
        }
        data = {k: v for k, v in data.items() if v is not None}
        result = supabase.from_("opportunities").insert(data).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
        return None
    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_create)
async def _get_or_create_tag(tag_name: str, is_custom: bool) -> Optional[str]:
    """
    Find or create a tag by name (case-insensitive).

    Phase N moved the implementation to tags.py so the poster side, the user side and the
    nightly dedup job all share one answer to "which tag is this". Kept as a named wrapper
    here because it is the single write point both the create and edit paths call.
    """
    return await tags.get_or_create_tag(tag_name, is_custom)

async def _count_matched_users(tag_ids: List[str]) -> int:
    """Count distinct users who have at least one of the given tag IDs."""
    def _count():
        result = supabase.from_("user_tags").select("user_id").in_("tag_id", tag_ids).execute()
        if result.data:
            unique_user_ids = {str(row["user_id"]) for row in result.data}
            return len(unique_user_ids)
        return 0
    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_count)

async def _get_opportunity_by_id(opportunity_id: str) -> Optional[Dict[str, Any]]:
    """Fetch opportunity by ID."""
    def _get():
        return supabase.from_("opportunities").select("*").eq("id", opportunity_id).execute()
    async with _db_semaphore:
        res = await anyio.to_thread.run_sync(_get)
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None

async def _update_opportunity(opportunity_id: str, collected_data: Dict[str, Any]) -> None:
    """Update opportunity fields."""
    def _update():
        data = {}
        for field in ["title", "description", "type", "application_start_date", "application_deadline",
                      "result_date", "event_start_date", "link"]:
            if field in collected_data:
                data[field] = collected_data[field]
        if not data:
            return
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return supabase.from_("opportunities").update(data).eq("id", opportunity_id).execute()
    async with _db_semaphore:
        await anyio.to_thread.run_sync(_update)

async def _delete_opportunity_tags(opportunity_id: str) -> None:
    """Delete all tag links for an opportunity."""
    def _delete():
        return supabase.from_("opportunity_tags").delete().eq("opportunity_id", opportunity_id).execute()
    async with _db_semaphore:
        await anyio.to_thread.run_sync(_delete)

async def _create_opportunity_tag(opportunity_id: str, tag_id: str) -> None:
    """Create a link between opportunity and tag."""
    def _create():
        return supabase.from_("opportunity_tags").insert({
            "opportunity_id": opportunity_id,
            "tag_id": tag_id
        }).execute()
    async with _db_semaphore:
        await anyio.to_thread.run_sync(_create)

def _parse_date(date_str: str) -> Optional[date]:
    """Parse a date string in YYYY-MM-DD format; return None if invalid or empty."""
    if not date_str or not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

def _get_current_field_values(collected_data: Dict[str, Any], step: str) -> Dict[str, Any]:
    """Return current values for fields relevant to a given step, for edit button."""
    step_to_field = {
        "awaiting_type": "type",
        "awaiting_title": "title",
        "awaiting_description": "description",
        "awaiting_tags": "tag_names",
        "awaiting_application_start_date": "application_start_date",
        "awaiting_application_deadline": "application_deadline",
        "awaiting_result_date": "result_date",
        "awaiting_event_start_date": "event_start_date",
        "awaiting_application_link": "link"
    }
    field = step_to_field.get(step)
    if field and field in collected_data:
        return {field: collected_data[field]}
    return {}

async def handle_opportunity_type_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process opportunity type input."""
    opp_type = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                opp_type = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        opp_type = ""

    if not opp_type:
        await send_whatsapp_message(
            phone_number,
            body="Opportunity type cannot be empty. Please enter the type (e.g., scholarship, internship, volunteering, event)."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_title",
        data={"type": opp_type}
    )
    await send_whatsapp_message(phone_number, body="Please enter a title for the opportunity.")

async def handle_opportunity_title_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process opportunity title input."""
    title = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                title = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        title = ""

    if not title:
        await send_whatsapp_message(
            phone_number,
            body="Title cannot be empty. Please enter a title for the opportunity."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_description",
        data={"title": title}
    )
    await send_whatsapp_message(phone_number, body="Please enter a description for the opportunity.")

async def handle_opportunity_description_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process opportunity description input."""
    description = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                description = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        description = ""

    if not description:
        await send_whatsapp_message(
            phone_number,
            body="Description cannot be empty. Please enter a description for the opportunity."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_tags",
        data={"description": description}
    )
    await send_whatsapp_message(
        phone_number,
        body="Please enter tags for the opportunity, separated by commas (e.g., \"scholarships, tech events, volunteering\"). "
             "You can also type new tags; we'll add them."
    )

async def handle_opportunity_tags_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process opportunity tags input."""
    raw_text = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                raw_text = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        raw_text = ""

    # Parse interests using the shared function from registration.py
    parsed_interests = parse_interests(raw_text)

    if not parsed_interests:
        await send_whatsapp_message(
            phone_number,
            body="No valid tags found. Please enter at least one tag (e.g., scholarships, internships, volunteering)."
        )
        return

    # Save tag_names + parsed_interests and advance to next step in one call
    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_application_start_date",
        data={"tag_names": raw_text, "parsed_interests": parsed_interests}
    )

    # Count matched users
    tag_ids = []
    for interest in parsed_interests:
        tag_name = interest["name"]
        is_custom = interest["is_custom"]
        # Get or create tag
        tag_id = await _get_or_create_tag(tag_name, is_custom)
        if tag_id:
            tag_ids.append(tag_id)

    matched_count = await _count_matched_users(tag_ids)

    # Format tag list for display
    tag_names_list = [interest["name"] for interest in parsed_interests]
    if len(tag_names_list) == 1:
        tag_list = tag_names_list[0]
    elif len(tag_names_list) == 2:
        tag_list = f"{tag_names_list[0]} and {tag_names_list[1]}"
    else:
        tag_list = f"{', '.join(tag_names_list[:-1])}, and {tag_names_list[-1]}"

    await send_whatsapp_message(
        phone_number,
        body=f"This will be sent to approximately {matched_count} students interested in {tag_list}. "
             f"Application start date?"
    )

async def handle_application_start_date_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process application start date input."""
    date_str = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                date_str = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        date_str = ""

    parsed_date = _parse_date(date_str)
    if not parsed_date:
        await send_whatsapp_message(
            phone_number,
            body="Invalid date format. Please enter the date in YYYY-MM-DD format (e.g., 2024-01-15)."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_application_deadline",
        data={"application_start_date": parsed_date.isoformat()}
    )
    await send_whatsapp_message(phone_number, body="Please enter the application deadline date.")

async def handle_application_deadline_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process application deadline input."""
    date_str = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                date_str = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        date_str = ""

    parsed_date = _parse_date(date_str)
    if not parsed_date:
        await send_whatsapp_message(
            phone_number,
            body="Invalid date format. Please enter the date in YYYY-MM-DD format (e.g., 2024-01-15)."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_result_date",
        data={"application_deadline": parsed_date.isoformat()}
    )
    await send_whatsapp_message(
        phone_number,
        body="Please enter the result announcement date (or type 'skip' if not applicable)."
    )

async def handle_result_date_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process result date input (can be skipped)."""
    date_str = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                date_str = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        date_str = ""

    # Check for skip
    if date_str.lower() == "skip":
        await set_conversation_state(
            phone_number=phone_number,
            flow=conversation_state["current_flow"],
            step="awaiting_event_start_date",
            data={"result_date": None}
        )
        await send_whatsapp_message(
            phone_number,
            body="Please enter the event/program start date (or type 'skip' if not applicable)."
        )
        return

    parsed_date = _parse_date(date_str)
    if not parsed_date:
        await send_whatsapp_message(
            phone_number,
            body="Invalid date format. Please enter the date in YYYY-MM-DD format (e.g., 2024-01-15) or type 'skip'."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_event_start_date",
        data={"result_date": parsed_date.isoformat()}
    )
    await send_whatsapp_message(
        phone_number,
        body="Please enter the event/program start date (or type 'skip' if not applicable)."
    )

async def handle_event_start_date_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process event start date input (can be skipped)."""
    date_str = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                date_str = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        date_str = ""

    # Check for skip
    if date_str.lower() == "skip":
        await set_conversation_state(
            phone_number=phone_number,
            flow=conversation_state["current_flow"],
            step="awaiting_application_link",
            data={"event_start_date": None}
        )
        await send_whatsapp_message(phone_number, body="Please enter the application link (URL).")
        return

    parsed_date = _parse_date(date_str)
    if not parsed_date:
        await send_whatsapp_message(
            phone_number,
            body="Invalid date format. Please enter the date in YYYY-MM-DD format (e.g., 2024-01-15) or type 'skip'."
        )
        return

    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_application_link",
        data={"event_start_date": parsed_date.isoformat()}
    )
    await send_whatsapp_message(phone_number, body="Please enter the application link (URL).")

# ============================================================
# STEP 9: APPLICATION LINK INPUT
# ============================================================

async def handle_application_link_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Process application link input and show confirmation summary with buttons."""
    link = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):
            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                link = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        link = ""

    if not link:
        await send_whatsapp_message(
            phone_number,
            body="Link cannot be empty. Please enter the application link (URL)."
        )
        return

    # Save link + advance to confirmation in one call
    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step="awaiting_confirmation",
        data={"link": link}
    )

    # Build summary from collected_data (state before this message) + current link
    cd = conversation_state.get("collected_data", {})
    title = cd.get("title", "N/A")
    opp_type = cd.get("type", "N/A")
    description = cd.get("description", "N/A")
    tag_names = cd.get("tag_names", "N/A")
    start_date = cd.get("application_start_date", "N/A")
    deadline = cd.get("application_deadline", "N/A")
    result_date = cd.get("result_date") or "Not specified"
    event_date = cd.get("event_start_date") or "Not specified"

    summary = (
        f"\U0001f4cb Here's your opportunity:\n\n"
        f"Title: {title}\n"
        f"Type: {opp_type}\n"
        f"Description: {description}\n"
        f"Tags: {tag_names}\n"
        f"Application starts: {start_date}\n"
        f"Deadline: {deadline}\n"
        f"Results: {result_date}\n"
        f"Starts: {event_date}\n"
        f"Link: {link}\n\n"
        f"Send it out?"
    )

    await send_whatsapp_buttons(
        phone_number,
        body=summary,
        buttons=[
            {"type": "reply", "reply": {"id": "confirm_send", "title": "\u2705 Confirm & Send"}},
            {"type": "reply", "reply": {"id": "edit_post", "title": "\u270f\ufe0f Edit"}}
        ]
    )

# ============================================================
# STEP 10: OPPORTUNITY CONFIRMATION (Confirm & Send / Edit)
# ============================================================

async def handle_opportunity_confirmation_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """Handle Confirm & Send or Edit button on the confirmation step."""
    # Extract button_id from payload
    button_id = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0 and
            "interactive" in payload["entry"][0]["changes"][0]["value"]["messages"][0] and
            "button_reply" in payload["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"]):
            button_id = payload["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"]["button_reply"]["id"]
    except (KeyError, IndexError, TypeError):
        button_id = ""

    logger.info(f"OPPORTUNITY_CONFIRM_TAP: phone_number={phone_number} button_id='{button_id}' "
                f"flow={conversation_state.get('current_flow')} step={conversation_state.get('current_step')}")

    if button_id == "confirm_send":
        await _confirm_and_send_opportunity(phone_number, conversation_state)
    elif button_id == "edit_post":
        # Restart flow from the beginning, keeping collected_data for reference
        await set_conversation_state(
            phone_number=phone_number,
            flow=conversation_state["current_flow"],
            step="awaiting_type",
            data={}  # data={} preserves existing collected_data via merge
        )
        current_type = conversation_state.get("collected_data", {}).get("type", "")
        prompt = "Let's edit your opportunity. Please enter the type:"
        if current_type:
            prompt = f"Current type: {current_type}\nPlease enter the type:"
        await send_whatsapp_message(phone_number, body=prompt)
    else:
        # Unknown button or free text -- re-show confirmation buttons
        await send_whatsapp_buttons(
            phone_number,
            body="Please tap a button to confirm or edit your opportunity.",
            buttons=[
                {"type": "reply", "reply": {"id": "confirm_send", "title": "\u2705 Confirm & Send"}},
                {"type": "reply", "reply": {"id": "edit_post", "title": "\u270f\ufe0f Edit"}}
            ]
        )

async def _confirm_and_send_opportunity(phone_number: str, conversation_state: Dict[str, Any]) -> None:
    """Create or update the opportunity, create tags, and clean up conversation state."""
    cd = conversation_state.get("collected_data", {})
    flow = conversation_state["current_flow"]
    logger.info(f"OPPORTUNITY_CONFIRM_START: phone_number={phone_number} flow={flow} "
                f"has_opportunity_id={bool(cd.get('opportunity_id'))} has_poster_id={bool(cd.get('poster_id'))} "
                f"collected_keys={sorted(cd.keys())}")

    # Get poster_id and opportunity_id based on flow
    if flow == "edit_opportunity":
        poster_id = cd.get("poster_id")
        opportunity_id = cd.get("opportunity_id")
    else:
        poster_id = await _get_poster_id_from_phone(phone_number)
        opportunity_id = None

    if not poster_id:
        await send_whatsapp_message(
            phone_number,
            body="Error: Could not find your poster account. Please try registering again."
        )
        return

    # Read parsed_interests from collected_data (NOT top-level -- fixes CLAUDE.md bug #3)
    parsed_interests = cd.get("parsed_interests", [])

    # Build the data for create/update
    opp_data = {
        "poster_id": poster_id,
        "title": cd.get("title"),
        "description": cd.get("description"),
        "type": cd.get("type"),
        "application_start_date": cd.get("application_start_date"),
        "application_deadline": cd.get("application_deadline"),
        "result_date": cd.get("result_date"),
        "event_start_date": cd.get("event_start_date"),
        "link": cd.get("link"),
    }

    if flow == "edit_opportunity" and opportunity_id:

        try:
            # Snapshot BEFORE writing: Phase M propagation needs to know which fields
            # actually moved (2-Architecture-Doc.md Section 3D "compare old vs. new
            # values before writing"), and once the UPDATE runs the old values are gone.
            old_row = await _get_opportunity_by_id(opportunity_id)
            # UPDATE existing opportunity
            await _update_opportunity(opportunity_id, opp_data)
            # Delete old tags
            await _delete_opportunity_tags(opportunity_id)
            # Create new tags (skip repeats -- duplicate tag terms resolve to one tag_id,
            # and re-inserting the same (opportunity_id, tag_id) violates the PK)
            inserted_tag_ids = set()
            for interest in parsed_interests:
                tag_id = await _get_or_create_tag(interest["name"], interest["is_custom"])
                if tag_id and tag_id not in inserted_tag_ids:
                    inserted_tag_ids.add(tag_id)
                    await _create_opportunity_tag(opportunity_id, tag_id)
            # Clear state (flow complete)
            await clear_conversation_state(phone_number)
            logger.info(f"OPPORTUNITY_CONFIRM_UPDATE_OK: phone_number={phone_number} opportunity_id={opportunity_id}")
        except Exception:
            # A mid-way failure must never leave the poster frozen at confirm with no reply.
            # Reset to a safe state and tell them instead of a bare 500 that Meta retries
            # into the message-id dedup black hole.
            logger.exception(f"OPPORTUNITY_CONFIRM_EDIT_FAILED: phone_number={phone_number}")
            try:
                await clear_conversation_state(phone_number)
            except Exception:
                logger.exception(f"OPPORTUNITY_CONFIRM_EDIT_CLEAR_STATE_FAILED: phone_number={phone_number}")
            try:
                await send_whatsapp_message(
                    phone_number,
                    body="Something went wrong while saving your changes. Please try again."
                )
            except Exception:
                logger.exception(f"OPPORTUNITY_CONFIRM_EDIT_NOTIFY_FAILED: phone_number={phone_number}")
            return

        # Phase M: tell everyone still tracking this post, and bring the date-derived
        # parts of their rows back in line. Deliberately its own try/except -- the edit
        # is already saved, so a propagation problem must never reach the poster as
        # "saving failed", nor leave them without a reply.
        try:
            await propagate_opportunity_edit(opportunity_id, old_row, opp_data)
        except Exception:
            logger.exception(
                f"OPPORTUNITY_EDIT_PROPAGATION_FAILED: phone_number={phone_number} "
                f"opportunity_id={opportunity_id}"
            )

        await send_whatsapp_message(
            phone_number,
            body="\u2705 Your opportunity has been updated! All tracked users will be notified of the changes."
        )
    else:
        # CREATE new opportunity

        new_opp_id = None
        try:
            # Check requires_post_approval flag
            def _get_poster_approval_flag():
                result = supabase.from_("posters").select("requires_post_approval").eq("id", poster_id).execute()
                return result.data[0].get("requires_post_approval", False) if result.data else False

            async with _db_semaphore:
                requires_approval = await anyio.to_thread.run_sync(_get_poster_approval_flag)

            if requires_approval:
                opp_data["status"] = "pending_approval"
            else:
                opp_data["status"] = "active"

            # Create opportunity
            new_opp_id = await _create_opportunity(opp_data)
            if not new_opp_id:
                await send_whatsapp_message(
                    phone_number,
                    body="Error: Could not create the opportunity. Please try again."
                )
                return

            # Create opportunity tags (skip repeats -- duplicate tag terms resolve to one
            # tag_id, and re-inserting the same (opportunity_id, tag_id) violates the PK)
            inserted_tag_ids = set()
            for interest in parsed_interests:
                tag_id = await _get_or_create_tag(interest["name"], interest["is_custom"])
                if tag_id and tag_id not in inserted_tag_ids:
                    inserted_tag_ids.add(tag_id)
                    await _create_opportunity_tag(new_opp_id, tag_id)

            # Clear state (flow complete)
            await clear_conversation_state(phone_number)
        except Exception:
            # A mid-way failure (e.g. duplicate tag insert) must never leave the poster
            # frozen at confirm with a partial/orphan live post and no reply. Roll back
            # the just-created opportunity (cascades its tags) and reset to a safe state
            # instead of a bare 500 that Meta retries into the dedup black hole.
            logger.exception(f"OPPORTUNITY_CONFIRM_CREATE_FAILED: phone_number={phone_number}")
            if new_opp_id:
                try:
                    def _delete_opportunity():
                        return supabase.from_("opportunities").delete().eq("id", new_opp_id).execute()
                    async with _db_semaphore:
                        await anyio.to_thread.run_sync(_delete_opportunity)
                except Exception:
                    logger.exception(f"OPPORTUNITY_CONFIRM_ROLLBACK_FAILED: opportunity_id={new_opp_id}")
            try:
                await clear_conversation_state(phone_number)
            except Exception:
                logger.exception(f"OPPORTUNITY_CONFIRM_CLEAR_STATE_FAILED: phone_number={phone_number}")
            try:
                await send_whatsapp_message(
                    phone_number,
                    body="Something went wrong while publishing your opportunity. Nothing was published - please try again."
                )
            except Exception:
                logger.exception(f"OPPORTUNITY_CONFIRM_NOTIFY_FAILED: phone_number={phone_number}")
            return

        logger.info(f"OPPORTUNITY_CONFIRM_CREATE_OK: phone_number={phone_number} "
                    f"opportunity_id={new_opp_id} requires_approval={requires_approval}")

        if requires_approval:
            await send_whatsapp_message(
                phone_number,
                body="Your opportunity has been submitted and is pending admin approval. We'll notify you once it's approved."
            )
            # Send admin preview with Approve/Reject buttons
            admin_phone = os.getenv("ADMIN_PHONE_NUMBER")
            if admin_phone:
                admin_preview = (
                    f"\U0001f4dd New post pending approval:\n\n"
                    f"Title: {cd.get('title', 'N/A')}\n"
                    f"Type: {cd.get('type', 'N/A')}\n"
                    f"Description: {cd.get('description', 'N/A')}\n"
                    f"Link: {cd.get('link', 'N/A')}\n"
                    f"Deadline: {cd.get('application_deadline', 'N/A')}"
                )
                await send_whatsapp_buttons(
                    admin_phone,
                    body=admin_preview,
                    buttons=[
                        {"type": "reply", "reply": {"id": f"approve_post_{new_opp_id}", "title": "Approve Post"}},
                        {"type": "reply", "reply": {"id": f"reject_post_{new_opp_id}", "title": "Reject Post"}}
                    ]
                )
        else:
            # Phase H (Matching Engine): the post is now live, so run the matching
            # engine and report the match count back to the poster (count only --
            # never a list of names; 3-Full-Product-Logic.md Section 4).
            try:
                match_count = await run_matching_engine(new_opp_id)
                if match_count:
                    await send_whatsapp_message(
                        phone_number,
                        body=f"Sent! \U0001f389 Your opportunity was sent to {match_count} matching student(s)."
                    )
                else:
                    await send_whatsapp_message(
                        phone_number,
                        body="Sent! \U0001f389 Your post is live. No students match those tags yet."
                    )
            except Exception:
                # Matching must never undo a successful post or leave the poster
                # without a reply.
                logger.exception(f"MATCHING_ENGINE_FAILED (direct post): opportunity_id={new_opp_id}")
                await send_whatsapp_message(phone_number, body="Sent! \U0001f389")

# ============================================================
# MY POSTS BUTTON -- List poster's opportunities for editing
# ============================================================

async def _handle_my_posts_button(phone_number: str) -> None:
    """Show a list of the poster's opportunities for editing."""
    poster_id = await _get_poster_id_from_phone(phone_number)
    if not poster_id:
        await send_whatsapp_message(phone_number, body="You need to register as a poster first.")
        return

    def _get_opportunities():
        return (supabase.from_("opportunities")
                .select("id, title, type, application_deadline, status")
                .eq("poster_id", poster_id)
                .order("created_at", desc=True)
                .limit(10)
                .execute())

    async with _db_semaphore:
        result = await anyio.to_thread.run_sync(_get_opportunities)

    if not result.data or len(result.data) == 0:
        await send_whatsapp_message(
            phone_number,
            body="You haven't posted any opportunities yet. Tap 'Post Opportunity' to create one."
        )
        return

    # Build list rows with emoji-aware title truncation
    status_emojis = {
        "active": "\u2705",
        "pending_approval": "\u23f3",
        "rejected": "\u274c",
        "expired": "\U0001f4c9",
        "edited": "\U0001f4dd"
    }
    rows = []
    for opp in result.data:
        status = opp.get("status", "active")
        emoji = status_emojis.get(status, "\U0001f4cb")
        title = opp.get("title", "Untitled")
        # Truncate title to fit 24 chars including emoji + space
        max_title_len = 24 - len(emoji) - 1  # emoji + space + title
        if len(title) > max_title_len:
            title = title[:max_title_len - 3] + "..."
        row_title = f"{emoji} {title}"
        # Build description
        opp_type = opp.get("type", "")
        deadline = opp.get("application_deadline", "")
        desc_parts = []
        if opp_type:
            desc_parts.append(opp_type)
        if deadline:
            desc_parts.append(f"Deadline: {deadline}")
        description = " \u00b7 ".join(desc_parts) if desc_parts else ""
        if len(description) > 72:
            description = description[:69] + "..."
        rows.append({
            "id": f"select_post_{opp['id']}",
            "title": row_title,
            "description": description
        })

    await send_whatsapp_list_message(
        phone_number,
        body="\U0001f4dd Your posts -- tap one to edit:",
        sections=[{
            "title": "Your Opportunities",
            "rows": rows
        }]
    )

# ============================================================
# MY APPLICATIONS -- moved to my_applications.py
# ============================================================
# The stub that used to live here was replaced in Phase M by the real Section 2 lists
# (`handle_my_applications_button` / `handle_my_list`) plus the Section 9.1 / 9.2
# add-and-edit flows, all in my_applications.py -- they need the lists and the flows
# to sit together, because Section 9.1's entry point lives inside a list.


# ============================================================
# AVAILABLE APPS BUTTON -- the user's matched opportunities
# (Phase N bullet 1: the Available Applications list view)
# ============================================================

AVAILABLE_PAGE_SIZE = 10  # WhatsApp list cap: 10 rows total (Section 10.1)


async def _handle_available_applications_button(phone_number: str, offset: int = 0) -> None:
    """Show the user's Available Applications (status='available') as a paginated list.

    Those rows are created by the Matching Engine (Phase H), so this is exactly "the
    opportunities matching their selected tags". Titles/descriptions respect the
    24/72-char caps and the list is paginated per Section 10.1.
    """
    def _get_user_apps():
        user = supabase.from_("users").select("id").eq("phone_number", phone_number).limit(1).execute()
        if not user.data:
            return None
        user_id = user.data[0]["id"]
        apps = (supabase.from_("applications")
                .select("id, custom_title, opportunities(title, type, application_deadline)")
                .eq("user_id", user_id)
                .eq("status", "available")
                .order("created_at", desc=False)
                .execute())
        return apps.data or []

    async with _db_semaphore:
        apps = await anyio.to_thread.run_sync(_get_user_apps)

    if apps is None:
        await send_whatsapp_message(phone_number, body="You don't have any opportunities to view yet.")
        return
    if not apps:
        await send_whatsapp_message(
            phone_number,
            body="No available opportunities right now. We'll message you as soon as something matches your interests."
        )
        return

    # Paginate: 10 rows max; when there are more, show 9 + a "More" row (Section 10.1)
    has_more = len(apps) > offset + AVAILABLE_PAGE_SIZE
    take = (AVAILABLE_PAGE_SIZE - 1) if has_more else AVAILABLE_PAGE_SIZE
    page = apps[offset: offset + take]

    rows = []
    for app in page:
        opp = app.get("opportunities") or {}
        title = opp.get("title") or app.get("custom_title") or "Opportunity"
        if len(title) > 24:
            title = title[:21] + "..."
        desc_parts = []
        if opp.get("type"):
            desc_parts.append(opp["type"])
        if opp.get("application_deadline"):
            desc_parts.append(f"Deadline: {opp['application_deadline']}")
        description = " \u00b7 ".join(desc_parts)
        if len(description) > 72:
            description = description[:69] + "..."
        rows.append({"id": f"avail_open_{app['id']}", "title": title, "description": description})

    if has_more:
        rows.append({"id": f"avail_more_{offset + take}", "title": "More \u2192", "description": ""})

    await send_whatsapp_list_message(
        phone_number,
        body="\U0001F4CB Opportunities matched to your interests -- tap one to view it:",
        sections=[{"title": "Available Apps", "rows": rows}]
    )


async def _handle_available_application_open(phone_number: str, application_id: str) -> None:
    """Re-send a matched opportunity's New Match Notification (Phase H) when its row is tapped.

    Reusing the Phase H sender gives the user the same Apply Now / Remind Me Later /
    Ignore buttons without duplicating that composition here.
    """
    def _fetch():
        res = (supabase.from_("applications")
               .select("id, status, custom_title, "
                       "opportunities(title, description, application_start_date, application_deadline, "
                       "posters(display_name))")
               .eq("id", application_id)
               .limit(1)
               .execute())
        return res.data[0] if res.data else None

    async with _db_semaphore:
        application = await anyio.to_thread.run_sync(_fetch)

    if not application:
        await send_whatsapp_message(phone_number, body="That opportunity is no longer available.")
        return
    if application.get("status") != "available":
        await send_whatsapp_message(
            phone_number,
            body="That one has already moved on -- check My Applications for its current status."
        )
        return

    opp = application.get("opportunities") or {}
    poster = opp.get("posters") or {}
    await send_new_match_notification(
        to=phone_number,
        title=opp.get("title") or application.get("custom_title") or "Opportunity",
        poster_name=poster.get("display_name") or "",
        description=opp.get("description") or "",
        application_id=application_id,
        application_start_date=opp.get("application_start_date"),
        application_deadline=opp.get("application_deadline"),
    )


# ============================================================
# SELECT POST FOR EDIT -- Pre-fill data and start edit flow
# ============================================================

async def _handle_select_post_for_edit(phone_number: str, opportunity_id: str) -> None:
    """Pre-fill collected_data with the opportunity's current values and start edit flow."""
    opp = await _get_opportunity_by_id(opportunity_id)
    if not opp:
        await send_whatsapp_message(phone_number, body="Error: Could not find that opportunity.")
        return

    # Fetch the opportunity's tags
    def _get_tags():
        tag_links = supabase.from_("opportunity_tags").select("tag_id").eq("opportunity_id", opportunity_id).execute()
        if not tag_links.data:
            return []
        tag_ids = [link["tag_id"] for link in tag_links.data]
        tags_result = supabase.from_("tags").select("name, is_custom").in_("id", tag_ids).execute()
        return tags_result.data if tags_result.data else []

    async with _db_semaphore:
        tags = await anyio.to_thread.run_sync(_get_tags)

    # Build parsed_interests and tag_names from tags
    parsed_interests = [{"name": tag["name"], "is_custom": tag.get("is_custom", False)} for tag in tags]
    tag_names = ", ".join([tag["name"] for tag in tags])

    # Pre-fill collected_data with current values
    collected_data = {
        "opportunity_id": opportunity_id,
        "poster_id": opp.get("poster_id"),
        "type": opp.get("type", ""),
        "title": opp.get("title", ""),
        "description": opp.get("description", ""),
        "tag_names": tag_names,
        "parsed_interests": parsed_interests,
        "application_start_date": opp.get("application_start_date"),
        "application_deadline": opp.get("application_deadline"),
        "result_date": opp.get("result_date"),
        "event_start_date": opp.get("event_start_date"),
        "link": opp.get("link", ""),
    }

    # Clear any existing state first to avoid stale data merging in
    await clear_conversation_state(phone_number)
    # Set conversation state for edit flow
    await set_conversation_state(
        phone_number=phone_number,
        flow="edit_opportunity",
        step="awaiting_type",
        data=collected_data
    )

    # Send type prompt showing current value
    current_type = opp.get("type", "")
    prompt = "Let's edit your opportunity. Please enter the type:"
    if current_type:
        prompt = f"Current type: {current_type}\nPlease enter the type:"
    await send_whatsapp_message(phone_number, body=prompt)

# ============================================================
# ADMIN POST APPROVAL BUTTON -- Stateless approve/reject handler
# ============================================================

async def handle_admin_post_approval_button(button_id: str) -> Dict[str, Any]:
    """Handle admin's Approve Post / Reject Post button tap (stateless)."""
    # Parse button_id: "approve_post_<uuid>" or "reject_post_<uuid>"
    parts = button_id.split("_", 2)
    if len(parts) != 3:
        return {"status": "error", "message": "Invalid button ID format"}

    action = parts[0]  # "approve" or "reject"
    opportunity_id = parts[2]  # UUID string

    # Fetch opportunity to check current status
    opp = await _get_opportunity_by_id(opportunity_id)
    if not opp:
        return {"status": "error", "message": "Opportunity not found"}

    # Guard: only proceed if still pending_approval (protects against stale retries/double-taps)
    if opp.get("status") != "pending_approval":
        logger.info(f"POST_APPROVAL_SKIP: opportunity {opportunity_id} status is {opp.get('status')}, not pending_approval")
        return {"status": "ok", "message": "Already processed"}

    # Update status
    new_status = "active" if action == "approve" else "rejected"

    def _update_status():
        return supabase.from_("opportunities").update({"status": new_status}).eq("id", opportunity_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_update_status)

    # Get poster info for notification
    poster_id = opp.get("poster_id")

    def _get_poster_phone():
        result = supabase.from_("posters").select("phone_number").eq("id", poster_id).execute()
        return result.data[0]["phone_number"] if result.data else None

    async with _db_semaphore:
        poster_phone = await anyio.to_thread.run_sync(_get_poster_phone)

    if poster_phone:
        if action == "approve":
            # Phase H (Matching Engine): the post just became active, so run the
            # matching engine and report the match count to the poster (count only
            # -- never a list of names; 3-Full-Product-Logic.md Section 4).
            try:
                match_count = await run_matching_engine(opportunity_id)
            except Exception:
                logger.exception(f"MATCHING_ENGINE_FAILED (admin approve): opportunity_id={opportunity_id}")
                match_count = 0
            if match_count:
                await send_whatsapp_message(
                    poster_phone,
                    body=f"\u2705 Your post has been approved and is now live! It was sent to {match_count} matching student(s)."
                )
            else:
                await send_whatsapp_message(
                    poster_phone,
                    body="\u2705 Your post has been approved and is now live! No students match those tags yet."
                )
        else:
            await send_whatsapp_message(
                poster_phone,
                body="\u274c Your post was not approved. Please contact the admin for more information."
            )

    return {"status": "ok"}