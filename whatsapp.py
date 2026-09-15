"""
WhatsApp messaging functions for WaveMatch.
Provides reusable functions for sending messages via WhatsApp Cloud API.
All functions respect WhatsApp platform constraints and use async HTTP calls.
"""

import os
import httpx
import json
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# WhatsApp Configuration from environment variables - nothing hardcoded
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")  # From .env file
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v21.0")  # Default to v21.0 if not set

# Validate required environment variables
if not WHATSAPP_ACCESS_TOKEN:
    raise ValueError("WHATSAPP_TOKEN environment variable is required")
if not WHATSAPP_PHONE_NUMBER_ID:
    raise ValueError("WHATSAPP_PHONE_NUMBER_ID environment variable is required")

# Base URL for WhatsApp Cloud API
WHATSAPP_API_URL = f"https://graph.facebook.com/{WHATSAPP_GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"


async def send_whatsapp_message(to: str, body: str) -> Dict[str, Any]:
    """
    Send a simple text message via WhatsApp Cloud API.

    Args:
        to: Recipient phone number in international format (e.g., "+15551234567")
        body: Message text content

    Returns:
        Dictionary containing API response status and data

    Raises:
        httpx.HTTPStatusError: If the API returns an error status
        httpx.RequestError: If there's a network or request error
    """
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": body
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            WHATSAPP_API_URL,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()


async def send_whatsapp_buttons(to: str, body: str, buttons: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send an interactive message with quick-reply buttons.

    Args:
        to: Recipient phone number in international format
        body: Message text content (appears above buttons)
        buttons: List of button objects, each with:
            {
                "type": "reply",
                "reply": {
                    "id": str (unique button identifier),
                    "title": str (button text, max 20 characters)
                }
            }

    Returns:
        Dictionary containing API response status and data

    Raises:
        ValueError: If buttons don't meet WhatsApp constraints
        httpx.HTTPStatusError: If the API returns an error status
        httpx.RequestError: If there's a network or request error
    """
    # Validate WhatsApp constraints for buttons (per Platform-Constraints.md Section 10.2)
    if len(buttons) > 3:
        raise ValueError(f"Maximum 3 buttons allowed, got {len(buttons)}")

    for i, button in enumerate(buttons):
        if button.get("type") != "reply":
            raise ValueError(f"Button {i} must have type 'reply'")

        reply = button.get("reply", {})
        if not isinstance(reply, dict):
            raise ValueError(f"Button {i} reply must be a dictionary")

        button_id = reply.get("id")
        button_title = reply.get("title")

        if not button_id or not isinstance(button_id, str):
            raise ValueError(f"Button {i} must have a string 'id'")

        if not button_title or not isinstance(button_title, str):
            raise ValueError(f"Button {i} must have a string 'title'")

        if len(button_title) > 20:
            raise ValueError(f"Button {i} title exceeds 20 characters: '{button_title}' ({len(button_title)} chars)")

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": body
            },
            "action": {
                "buttons": buttons
            }
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            WHATSAPP_API_URL,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()


async def send_whatsapp_list_message(to: str, body: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send an interactive message with a list menu.

    Args:
        to: Recipient phone number in international format
        body: Message text content (appears above list)
        sections: List of section objects, each with:
            {
                "title": str (section title, max 24 characters),
                "rows": List[row objects] where each row has:
                    {
                        "id": str (unique row identifier),
                        "title": str (row title, max 24 characters),
                        "description": Optional[str] (row description, max 72 characters)
                    }
            }

    Returns:
        Dictionary containing API response status and data

    Raises:
        ValueError: If sections/rows don't meet WhatsApp constraints
        httpx.HTTPStatusError: If the API returns an error status
        httpx.RequestError: If there's a network or request error
    """
    # Validate WhatsApp constraints for list messages (per Platform-Constraints.md Section 10.1)
    total_rows = 0
    for i, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError(f"Section {i} must be a dictionary")

        section_title = section.get("title")
        section_rows = section.get("rows", [])

        if not section_title or not isinstance(section_title, str):
            raise ValueError(f"Section {i} must have a string 'title'")

        if len(section_title) > 24:
            raise ValueError(f"Section {i} title exceeds 24 characters: '{section_title}' ({len(section_title)} chars)")

        if not isinstance(section_rows, list):
            raise ValueError(f"Section {i} 'rows' must be a list")

        total_rows += len(section_rows)

        for j, row in enumerate(section_rows):
            if not isinstance(row, dict):
                raise ValueError(f"Section {i}, row {j} must be a dictionary")

            row_id = row.get("id")
            row_title = row.get("title")
            row_description = row.get("description")

            if not row_id or not isinstance(row_id, str):
                raise ValueError(f"Section {i}, row {j} must have a string 'id'")

            if not row_title or not isinstance(row_title, str):
                raise ValueError(f"Section {i}, row {j} must have a string 'title'")

            if len(row_title) > 24:
                raise ValueError(f"Section {i}, row {j} title exceeds 24 characters: '{row_title}' ({len(row_title)} chars)")

            if row_description is not None:
                if not isinstance(row_description, str):
                    raise ValueError(f"Section {i}, row {j} description must be a string or None")

                if len(row_description) > 72:
                    raise ValueError(f"Section {i}, row {j} description exceeds 72 characters: '{row_description}' ({len(row_description)} chars)")

    if total_rows > 10:
        raise ValueError(f"Maximum 10 rows allowed across all sections, got {total_rows}")

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": body
            },
            "action": {
                "button": "See options",  # Required button text for opening list
                "sections": sections
            }
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            WHATSAPP_API_URL,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        # Enhanced error handling to show response body on failure
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Try to get error details from response
            try:
                error_detail = response.json()
                raise httpx.HTTPStatusError(
                    f"{e}. Response: {error_detail}",
                    request=e.request,
                    response=e.response
                )
            except:
                # If we can't parse JSON, raise original error
                raise
        return response.json()


async def send_new_match_notification(
    to: str,
    title: str,
    poster_name: str,
    description: str,
    application_id: str,
    application_start_date: Optional[str] = None,
    application_deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send the "New Match Notification" to a matched user.

    Spec: 3-Full-Product-Logic.md Section 5 and 4-Message-Flow-Examples.md
    Section 5. Body layout:
        <title>
        Posted by <poster name>
        <description>
        Applications open: <application_start_date>
        Deadline: <application_deadline>
    with three buttons: Apply Now / Remind Me Later / Ignore.

    This is the single named place where this proactive message is composed.
    Per Platform-Constraints.md Section 1, proactive messages sent outside the
    24-hour window must use a pre-approved Message Template - once the template
    clears Meta review, swap the free-form interactive send below for the
    template send here, and no other code needs to change.

    Button ids are stateless (they carry the applications row id) so the Phase I
    handlers can act without relying on conversation_states.
    """
    lines = [f"\U0001f393 {title}", f"Posted by {poster_name}"]
    if description:
        lines.append(description)
    if application_start_date:
        lines.append(f"\U0001f4c6 Applications open: {application_start_date}")
    if application_deadline:
        lines.append(f"\U0001f4c5 Deadline: {application_deadline}")
    body = "\n".join(lines)

    buttons = [
        {
            "type": "reply",
            "reply": {"id": f"apply_now_{application_id}", "title": "\u2705 Apply Now"},
        },
        {
            "type": "reply",
            "reply": {"id": f"remind_later_{application_id}", "title": "\u23f0 Remind Me Later"},
        },
        {
            "type": "reply",
            "reply": {"id": f"ignore_{application_id}", "title": "\U0001f6ab Ignore"},
        },
    ]

    return await send_whatsapp_buttons(to, body=body, buttons=buttons)


async def send_ongoing_checkin_notification(
    to: str,
    title: str,
    application_id: str,
    deadline: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send the recurring "Ongoing check-in" message (3-Full-Product-Logic.md
    Section 6; 4-Message-Flow-Examples.md Section 6). Body:
        <wave> Still working on <title>? Deadline is <deadline>.
    with three buttons: Remind Me Later / Continue Application / Finished
    Application. (The scheduler in Phase L is what actually fires this.)

    Same single-swap-point rule as send_new_match_notification: this proactive
    message is composed here so the pre-approved template can be dropped in once
    Meta review clears (Platform-Constraints.md Section 1).

    Button titles are abbreviated to respect the 20-character cap
    (Platform-Constraints.md Section 10.2); button ids are stateless and carry
    the applications row id.
    """
    body = f"\U0001f44b Still working on {title}?"
    if deadline:
        body = f"{body} Deadline is {deadline}."

    buttons = [
        {
            "type": "reply",
            "reply": {"id": f"remind_later_{application_id}", "title": "\u23f0 Remind Me Later"},
        },
        {
            "type": "reply",
            "reply": {"id": f"continue_application_{application_id}", "title": "\U0001f517 Continue App"},
        },
        {
            "type": "reply",
            "reply": {"id": f"finished_application_{application_id}", "title": "\u2705 Finished App"},
        },
    ]

    return await send_whatsapp_buttons(to, body=body, buttons=buttons)


async def send_outcome_check_notification(
    to: str,
    title: str,
    application_id: str,
) -> Dict[str, Any]:
    """
    Send the "Under Review -> Outcome" check (3-Full-Product-Logic.md Section 8;
    4-Message-Flow-Examples.md Section 8). Body:
        Any news on <title>? Were you picked?
    with three buttons: Yes / No / Still Waiting. (The scheduler's Result-Check
    pass in Phase L is what actually fires this.)

    Same single-swap-point rule as the other proactive messages: composed here so
    the pre-approved template can be dropped in once Meta review clears
    (Platform-Constraints.md Section 1). Button ids are stateless and carry the
    applications row id.
    """
    body = f"Any news on {title}? Were you picked?"

    buttons = [
        {
            "type": "reply",
            "reply": {"id": f"outcome_yes_{application_id}", "title": "\U0001f389 Yes"},
        },
        {
            "type": "reply",
            "reply": {"id": f"outcome_no_{application_id}", "title": "\u274c No"},
        },
        {
            "type": "reply",
            "reply": {"id": f"outcome_waiting_{application_id}", "title": "\u23f3 Still Waiting"},
        },
    ]

    return await send_whatsapp_buttons(to, body=body, buttons=buttons)

async def send_deadline_heads_up_notification(
    to: str,
    title: str,
    deadline: str,
) -> Dict[str, Any]:
    """
    Send the one-time "Deadline heads-up" two days before an application deadline
    (3-Full-Product-Logic.md Section 7.1; 4-Message-Flow-Examples.md Section 7). Body:
        Reminder: <title> deadline is in 2 days (<deadline>).

    Plain text with no buttons -- nothing is asked of the user, the message just warns
    them before it's too late. `deadline` arrives already formatted for display.

    Same single-swap-point rule as the other proactive messages: composed here so the
    pre-approved template can replace it once Meta review clears
    (Platform-Constraints.md Section 1). Fired by the Phase L scheduler.
    """
    body = f"\u23f3 Reminder: {title} deadline is in 2 days ({deadline})."
    return await send_whatsapp_message(to, body=body)


async def send_opportunity_update_notification(
    to: str,
    title: str,
    change_lines: List[str],
    reminders_adjusted: bool = False,
) -> Dict[str, Any]:
    """
    Tell someone still tracking an opportunity that its poster edited it.
    Spec: 3-Full-Product-Logic.md Section 3.1, 4-Message-Flow-Examples.md Section 9. Body:
        Update: <title>
        <one line per changed field>
        Your reminders have been adjusted automatically.

    Sent whenever an edit actually changes something, and mandatory -- never batched,
    never silently skipped -- whenever the deadline moved (Section 3.1's hard rule).
    `change_lines` is built by propagation.py, so the wording sits next to the diffing
    logic that knows what really changed; a title change needs no line of its own
    because the new title is already the heading.

    Single template swap-point for this proactive message, like the other senders
    (Platform-Constraints.md Section 1).
    """
    lines = [f"\U0001F4E2 Update: {title}"]
    lines.extend(change_lines)
    if reminders_adjusted:
        lines.append("Your reminders have been adjusted automatically.")
    return await send_whatsapp_message(to, body="\n".join(lines))
