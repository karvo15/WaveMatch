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