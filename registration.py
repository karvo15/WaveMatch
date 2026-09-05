"""
Registration flow handlers for WaveMatch.
Handles first contact, role selection, poster registration, user registration, and interest editing.
"""

import os
import logging
from typing import Dict, Any, List
from dotenv import load_dotenv
from whatsapp import send_whatsapp_buttons, send_whatsapp_message
from conversation import get_conversation_state, set_conversation_state, clear_conversation_state, _db_semaphore
from database import supabase
import anyio
from rapidfuzz import fuzz, process

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Fixed category list for user interests (from Section 10.2 and 4-Message-Flow-Examples.md)
FIXED_CATEGORIES = [
    "Scholarships",
    "Internships",
    "Volunteering",
    "Tech Events / Conferences",
    "Competitions / Hackathons",
    "Workshops / Trainings",
    "Bootcamps",
    "Job Opportunities",
    "Research Opportunities",
    "Fellowships",
    "Grants / Funding",
    "Networking Events"
]

# Normalized versions for matching (lowercase, stripped)
NORMALIZED_FIXED_CATEGORIES = [cat.lower().strip() for cat in FIXED_CATEGORIES]

# Alias dictionary for common shorthands
ALIAS_DICT = {
    "job": "Job Opportunities",
    "internship": "Internships",
    "volunteer": "Volunteering",
    "scholarship": "Scholarships",
    "grant": "Grants / Funding",
    "fellowship": "Fellowships",
    "hackathon": "Competitions / Hackathons",
    "bootcamp": "Bootcamps",
    "workshop": "Workshops / Trainings",
    "training": "Workshops / Trainings",
    "event": "Tech Events / Conferences",
    "conference": "Tech Events / Conferences",
    "research": "Research Opportunities",
    "networking": "Networking Events"
}


async def handle_first_contact(phone_number: str) -> None:
    """
    Sends welcome message with Poster/User buttons for new phone numbers.
    Does NOT create conversation state yet (per Section 1.1 - state created only after button tap).
    """
    await send_whatsapp_buttons(
        phone_number,
        body="👋 Welcome to WaveMatch! Are you here to:",
        buttons=[
            {"type": "reply", "reply": {"id": "find_opportunities", "title": "🎓 Find Opportunities"}},
            {"type": "reply", "reply": {"id": "post_opportunities", "title": "📢 Post Opportunities"}}
        ]
    )


async def handle_role_selection(phone_number: str, payload: Dict[str, Any], selected_flow: str) -> None:
    """
    Called when user taps Poster/User button from welcome message.
    Sets initial conversation state for selected flow and sends first prompt.
    """
    if selected_flow == "register_poster":
        await set_conversation_state(
            phone_number=phone_number,
            flow="register_poster",
            step="awaiting_display_name",
            data={}  # No data collected yet
        )
        await send_whatsapp_message(
            phone_number,
            body="Great! What name should we show on your posts? (Your name or your organization's name)"
        )
    elif selected_flow == "register_user":
        await set_conversation_state(
            phone_number=phone_number,
            flow="register_user",
            step="awaiting_interests",
            data={}  # No data collected yet
        )
        # Send fixed category list (12 starter tags) and prompt for comma-separated interests
        # CONFIRMED: Matches 4-Message-Flow-Examples.md line 45 exactly with "·" separators between ALL categories
        categories_text = "Let's personalize what you see. Here are our categories:\n🎓 Scholarships · 💼 Internships · 🤝 Volunteering · 🎤 Tech Events / Conferences · 🏆 Competitions / Hackathons · 🛠️ Workshops / Trainings · 🚀 Bootcamps · 👔 Job Opportunities · 🔬 Research Opportunities · 🎗️ Fellowships · 💰 Grants / Funding · 🌐 Networking Events\n\nReply with the ones you're interested in, separated by commas (e.g. \"scholarships, tech events, volunteering\"). Not seeing something? Just type it — we'll add it."
        await send_whatsapp_message(phone_number, body=categories_text)


async def handle_poster_display_name_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """
    Processes display name input, creates pending poster record, clears state, sends admin notification.
    """
    # Extract display name from message body with defensive guarding
    display_name = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):

            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                display_name = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        # If any part of the structure is missing, treat as non-message event
        display_name = ""

    # Early return for non-message events (status callbacks, etc.)
    if not display_name:
        logger.debug(f"WEBHOOK_NON_MESSAGE_EVENT: skipping processing for phone_number={phone_number}")
        return

    # Save display name to collected_data
    await set_conversation_state(
        phone_number=phone_number,
        flow=conversation_state["current_flow"],
        step=conversation_state["current_step"],
        data={"display_name": display_name}
    )

    # Create posters row with pending status
    def _create_poster():
        result = supabase.from_("posters").insert({
            "phone_number": phone_number,
            "display_name": display_name,
            "status": "pending"
        }).execute()
        return result

    async with _db_semaphore:
        poster_result = await anyio.to_thread.run_sync(_create_poster)
    poster_id = poster_result.data[0]["id"] if poster_result.data else None

    # Clear conversation state (flow complete)
    await clear_conversation_state(phone_number)

    # Send confirmation to user
    await send_whatsapp_message(
        phone_number,
        body="Thanks! Your registration is pending approval. We'll notify you once it's confirmed."
    )

    # Send admin notification via WhatsApp to admin's personal number
    admin_phone_number = os.getenv("ADMIN_PHONE_NUMBER")
    if admin_phone_number and poster_id:
        admin_message = f"New poster registration: {display_name} wants to join as a poster. Reply 'approve {poster_id}' to confirm, or 'reject {poster_id}' to decline."
        await send_whatsapp_message(admin_phone_number, body=admin_message)


async def handle_user_interests_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """
    Parses interests via layered matching, creates user + user_tags, clears state, shows Main Menu.
    """
    # Extract raw interests text from message body with defensive guarding
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
        # If any part of the structure is missing, treat as non-message event
        raw_text = ""

    # Early return for non-message events (status callbacks, etc.)
    if not raw_text:
        logger.debug(f"WEBHOOK_NON_MESSAGE_EVENT: skipping processing for phone_number={phone_number}")
        return

    # Parse interests using layered matching
    parsed_interests = parse_interests(raw_text)

    # Create user record
    def _create_user():
        result = supabase.from_("users").insert({
            "phone_number": phone_number,
            "name": None  # Name collected later if needed
        }).execute()
        return result

    async with _db_semaphore:
        user_result = await anyio.to_thread.run_sync(_create_user)
    user_id = user_result.data[0]["id"] if user_result.data else None

    if user_id:
        # For each parsed interest, create user_tags junction entries
        for interest in parsed_interests:
            tag_name = interest["name"]
            is_custom = interest["is_custom"]

            # Find or create tag
            def _get_or_create_tag():
                # First try to find existing tag by name (case-insensitive)
                existing = supabase.from_("tags").select("id").ilike("name", tag_name).limit(1).execute()
                if existing.data and len(existing.data) > 0:
                    return existing.data[0]["id"]

                # If not found and it's a custom tag, create it
                if is_custom:
                    new_tag = supabase.from_("tags").insert({
                        "name": tag_name,
                        "is_custom": True
                    }).execute()
                    return new_tag.data[0]["id"] if new_tag.data else None

                # If not found and not custom, return None (shouldn't happen with our parsing)
                return None

            async with _db_semaphore:
                tag_id = await anyio.to_thread.run_sync(_get_or_create_tag)
            if tag_id:
                # Create user_tag junction
                def _create_user_tag():
                    return supabase.from_("user_tags").insert({
                        "user_id": user_id,
                        "tag_id": tag_id
                    }).execute()

                async with _db_semaphore:
                    await anyio.to_thread.run_sync(_create_user_tag)

    # Clear conversation state (flow complete)
    await clear_conversation_state(phone_number)

    # Show Main Menu
    await send_main_menu(phone_number, is_returning_user=True)


async def handle_interests_edit_step(phone_number: str, payload: Dict[str, Any], conversation_state: Dict[str, Any]) -> None:
    """
    Same as handle_user_interests_step but updates existing user's interests instead of creating new user.
    """
    # Extract raw interests text from message body with defensive guarding
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
        # If any part of the structure is missing, treat as non-message event
        raw_text = ""

    # Early return for non-message events (status callbacks, etc.)
    if not raw_text:
        logger.debug(f"WEBHOOK_NON_MESSAGE_EVENT: skipping processing for phone_number={phone_number}")
        return

    # Parse interests using layered matching
    parsed_interests = parse_interests(raw_text)

    # Get existing user
    def _get_user():
        result = supabase.from_("users").select("id").eq("phone_number", phone_number).execute()
        return result.data[0]["id"] if result.data else None

    async with _db_semaphore:
        user_id = await anyio.to_thread.run_sync(_get_user)

    if user_id:
        # Delete existing user_tags for user
        def _delete_user_tags():
            return supabase.from_("user_tags").delete().eq("user_id", user_id).execute()

        async with _db_semaphore:
            await anyio.to_thread.run_sync(_delete_user_tags)

        # For each parsed interest, create user_tags junction entries
        for interest in parsed_interests:
            tag_name = interest["name"]
            is_custom = interest["is_custom"]

            # Find or create tag
            def _get_or_create_tag():
                # First try to find existing tag by name (case-insensitive)
                existing = supabase.from_("tags").select("id").ilike("name", tag_name).limit(1).execute()
                if existing.data and len(existing.data) > 0:
                    return existing.data[0]["id"]

                # If not found and it's a custom tag, create it
                if is_custom:
                    new_tag = supabase.from_("tags").insert({
                        "name": tag_name,
                        "is_custom": True
                    }).execute()
                    return new_tag.data[0]["id"] if new_tag.data else None

                # If not found and not custom, return None (shouldn't happen with our parsing)
                return None

            async with _db_semaphore:
                tag_id = await anyio.to_thread.run_sync(_get_or_create_tag)
            if tag_id:
                # Create user_tag junction
                def _create_user_tag():
                    return supabase.from_("user_tags").insert({
                        "user_id": user_id,
                        "tag_id": tag_id
                    }).execute()

                async with _db_semaphore:
                    await anyio.to_thread.run_sync(_create_user_tag)

    # Clear conversation state (flow complete)
    await clear_conversation_state(phone_number)

    # Show Main Menu
    await send_main_menu(phone_number, is_returning_user=True)


def parse_interests(raw_text: str) -> List[Dict[str, Any]]:
    """
    Implements layered matching process from Section 10.2:
    1. Normalize: lowercase, trim whitespace, strip trailing punctuation
    2. Exact match against normalized fixed list (12 starter tags)
    3. Substring/keyword match: e.g. "hackathon" matches "Competitions / Hackathons"
    4. Fuzzy match: using rapidfuzz with score cutoff 80 for typos like "scholarshp"
    5. Alias dictionary: e.g. "job" → Job Opportunities, "grant" → Grants / Funding
    6. Fallback: custom tag - if no match above, create new tag with `is_custom = true`
    Returns list of dicts: [{"name": "tag_name", "is_custom": bool}, ...]
    """
    # 1. Normalize — lowercase, trim whitespace, strip trailing punctuation
    normalized = raw_text.lower().strip().rstrip('.,!?;')
    # Split by comma and clean each term
    raw_terms = [term.strip() for term in normalized.split(',') if term.strip()]

    result = []

    for term in raw_terms:
        # Skip empty terms
        if not term:
            continue

        matched = False

        # 2. Exact match against normalized fixed list
        if term in NORMALIZED_FIXED_CATEGORIES:
            # Find the original category name to preserve formatting
            idx = NORMALIZED_FIXED_CATEGORIES.index(term)
            result.append({"name": FIXED_CATEGORIES[idx], "is_custom": False})
            matched = True
            continue

        # 3. Substring/keyword match
        for idx, category in enumerate(NORMALIZED_FIXED_CATEGORIES):
            if term in category or category in term:
                result.append({"name": FIXED_CATEGORIES[idx], "is_custom": False})
                matched = True
                break
        if matched:
            continue

        # 4. Fuzzy match using rapidfuzz (score cutoff >= 80)
        best_match = process.extractOne(term, NORMALIZED_FIXED_CATEGORIES, scorer=fuzz.ratio)
        if best_match and best_match[1] >= 80:  # score >= 80
            idx = NORMALIZED_FIXED_CATEGORIES.index(best_match[0])
            result.append({"name": FIXED_CATEGORIES[idx], "is_custom": False})
            matched = True
            continue

        # 5. Alias dictionary lookup
        if term in ALIAS_DICT:
            alias_target = ALIAS_DICT[term]
            # Find the category in our fixed list
            try:
                idx = FIXED_CATEGORIES.index(alias_target)
                result.append({"name": FIXED_CATEGORIES[idx], "is_custom": False})
                matched = True
            except ValueError:
                # Alias target not in fixed list (shouldn't happen with our dict)
                pass
            if matched:
                continue

        # 6. Fallback: custom tag
        result.append({"name": term.title(), "is_custom": True})  # Title case for display

    return result


async def send_main_menu(phone_number: str, is_returning_user: bool = False, is_returning_poster: bool = False) -> None:
    """
    Helper to send Main Menu options based on user/poster type.
    """
    if is_returning_poster and not is_returning_user:
        # Poster-only menu
        await send_whatsapp_message(
            phone_number,
            body="Welcome back! What would you like to do?\n[➕ Post an Opportunity] [📁 My Applications]"
        )
    elif is_returning_user and not is_returning_poster:
        # User-only menu
        await send_whatsapp_message(
            phone_number,
            body="Welcome back! What would you like to do?\n[📋 Available Applications] [📁 My Applications] [⚙️ Edit my interests]"
        )
    elif is_returning_user and is_returning_poster:
        # Both user and poster
        await send_whatsapp_message(
            phone_number,
            body="Welcome back! What would you like to do?\n[➕ Post an Opportunity] [📋 Available Applications] [📁 My Applications] [⚙️ Edit my interests]"
        )
    else:
        # Shouldn't reach here if called properly, but fallback
        await send_whatsapp_message(
            phone_number,
            body="Welcome to WaveMatch! What would you like to do?\n[📋 Available Applications] [📁 My Applications]"
        )