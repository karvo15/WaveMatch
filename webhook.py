"""
Webhook handling for WhatsApp Cloud API.
Implements verification and message receiving with proper signature verification.
"""

import os
import hmac
import hashlib
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime  # Fixed: import datetime class directly
from fastapi import Request, HTTPException
from dotenv import load_dotenv
from conversation import get_conversation_state, set_conversation_state, clear_conversation_state, user_exists, poster_exists
import registration  # Import the registration module
import poster_flow  # Import the poster flow module
import application_flow  # Phase I: user-side application button handlers
from whatsapp import send_whatsapp_message, send_whatsapp_buttons
from database import supabase
import anyio

# Load environment variables
load_dotenv()

# WhatsApp Configuration from environment variables
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_ID = os.getenv("WHATSAPP_APP_ID")  # For WABA subscription check

# Validate required environment variables
if not WHATSAPP_APP_SECRET:
    raise ValueError("WHATSAPP_APP_SECRET environment variable is required")
if not WHATSAPP_VERIFY_TOKEN:
    raise ValueError("WHATSAPP_VERIFY_TOKEN environment variable is required")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MODULE-LEVEL DEDUPLICATION TRACKING (MVP TRADEOFF)
# Simple in-memory set with timestamp expiry - resets on process restart/redeploy
# Acceptable for MVP as webhook retries happen within minutes; production would use Redis/cache
_recently_seen_message_ids = {}  # msg_id -> timestamp (epoch seconds)


async def verify_webhook(request: Request) -> str:
    """
    Handle Meta's webhook verification challenge (GET request).

    Args:
        request: FastAPI Request object

    Returns:
        The hub.challenge value as string if verification succeeds

    Raises:
        HTTPException: 403 if verification fails
    """
    # Extract query parameters
    query_params = request.query_params
    mode = query_params.get("hub.mode")
    token = query_params.get("hub.verify_token")
    challenge = query_params.get("hub.challenge")

    # Verify the request
    if mode and token and mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("WEBHOOK_VERIFIED")
        return challenge
    else:
        logger.warning(f"WEBHOOK_VERIFICATION_FAILED. mode:{mode}, token:{token}")
        raise HTTPException(status_code=403, detail="Verification failed")


async def handle_admin_command(phone_number: str, payload: Dict[str, Any]) -> None:
    """
    Handle admin commands from admin's personal number.
    Only processes if phone_number matches admin's personal number.
    """
    # Extract message text from payload
    message_text = ""
    try:
        if ("entry" in payload and len(payload["entry"]) > 0 and
            "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
            "value" in payload["entry"][0]["changes"][0] and
            "messages" in payload["entry"][0]["changes"][0]["value"] and
            len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):

            message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            if ("text" in message_obj and
                "body" in message_obj["text"]):
                message_text = message_obj["text"]["body"].strip()
    except (KeyError, IndexError, TypeError):
        # If any part of the structure is missing, treat as non-message event
        message_text = ""

    # Parse command using UUID-aware regex: r'^(approve|reject)\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'
    import re
    pattern = r'^(approve|reject)\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$'
    match = re.match(pattern, message_text, re.IGNORECASE)

    if not match:
        # Not a valid admin command, ignore
        return

    action = match.group(1).lower()  # approve or reject
    poster_id = match.group(2)  # UUID string

    # Validate action
    if action not in ["approve", "reject"]:
        return

    # Update posters table: SET status = 'approved' if action == 'approve' ELSE 'rejected' WHERE id = poster_id
    new_status = "approved" if action == "approve" else "rejected"

    def _update_poster_status():
        result = supabase.from_("posters").update({"status": new_status}).eq("id", poster_id).execute()
        return result

    update_result = await anyio.to_thread.run_sync(_update_poster_status)

    # Get poster info for notification (including phone_number)
    def _get_poster_info():
        result = supabase.from_("posters").select("display_name", "phone_number").eq("id", poster_id).execute()
        return result.data[0] if result.data else None

    poster_info = await anyio.to_thread.run_sync(_get_poster_info)

    if poster_info:
        display_name = poster_info["display_name"]
        poster_phone_number = poster_info["phone_number"]
        # Notify poster of outcome via WhatsApp (send to poster's phone number, not admin's)
        if action == "approve":
            # Send a real tappable "Post an Opportunity" button so the approved poster can start posting
            await send_whatsapp_buttons(
                poster_phone_number,
                body="✅ You're approved! Tap below anytime to post a new opportunity.",
                buttons=[
                    {"type": "reply", "reply": {"id": "post_opportunities", "title": "➕ Post Opportunity"}}
                ]
            )
        else:
            await send_whatsapp_message(
                poster_phone_number,
                body="❌ Your registration was rejected. Please contact support if you believe this is in error."
            )

        # Also send a confirmation to admin (optional)
        admin_confirmation = f"Poster '{display_name}' has been {action}ed."
        await send_whatsapp_message(phone_number, body=admin_confirmation)


async def receive_webhook(request: Request) -> Dict[str, str]:
    """
    Handle incoming webhook payloads (POST request) with signature verification.
    Consolidated dispatcher showing all steps in order.

    CRITICAL: Follows Section 10.4 exactly - read raw body BEFORE parsing JSON.

    Args:
        request: FastAPI Request object

    Request object

    Returns:
        Acknowledgment dict for Meta

    Raises:
        HTTPException: 403 if signature verification fails
    """
    # STEP 1: READ RAW BODY FIRST (Section 10.4 requirement)
    raw_body = await request.body()

    # STEP 2: SIGNATURE VERIFICATION (Section 10.4 requirement)
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        logger.warning("MISSING_X_HUB_SIGNATURE_256_HEADER")
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")

    # Extract the signature hex value (remove 'sha256=' prefix)
    expected_signature = signature.replace("sha256=", "")
    if not expected_signature:
        logger.warning("INVALID_X_HUB_SIGNATURE_256_FORMAT")
        raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256 format")

    # Compute HMAC-SHA256 of raw body using app secret
    # Ensure secret is bytes for HMAC
    secret_bytes = WHATSAPP_APP_SECRET.encode('utf-8')
    mac = hmac.new(secret_bytes, raw_body, hashlib.sha256)
    computed_signature = mac.hexdigest()

    # Compare using constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(computed_signature, expected_signature):
        logger.warning(f"WEBHOOK_SIGNATURE_VERIFICATION_FAILED. computed:{computed_signature}, expected:{expected_signature}")
        raise HTTPException(status_code=403, detail="Invalid signature")

    logger.info("WEBHOOK_SIGNATURE_VERIFIED")

    # STEP 3: PARSE JSON FROM THE SAME RAW BYTES (Section 10.4 requirement)
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except json.JSONDecodeError as e:
        logger.error(f"JSON_DECODE_ERROR: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # STEP 3.5: MESSAGE-ID DEDUPLICATION (PREVENTS RETRY STORMS)
    def is_duplicate_message(payload: Dict[str, Any]) -> bool:
        """Check if we've seen this message ID recently (deduplication)."""
        try:
            msg_id = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
            # Simple in-memory tracking - in production would use Redis/cache

            now = datetime.now().timestamp()
            # Clean old entries (>5 minutes old)
            global _recently_seen_message_ids
            _recently_seen_message_ids = {
                k: v for k, v in _recently_seen_message_ids.items()
                if now - v < 300  # 5 minutes
            }

            if msg_id in _recently_seen_message_ids:
                return True
            _recently_seen_message_ids[msg_id] = now
            return False
        except (KeyError, IndexError, TypeError):
            # If we can't extract message ID, don't deduplicate (fail open)
            return False

    # Skip if duplicate message (Meta webhook retry)
    if is_duplicate_message(payload):
        logger.info(f"WEBHOOK_DEDUPLICATED: skipping duplicate message ID")
        return {"status": "ok"}  # Early return, acknowledge receipt to Meta

    # STEP 4: EXTRACT PHONE NUMBER FROM PAYLOAD (with defensive error handling)
    def extract_phone_number_from_payload(payload: Dict[str, Any]) -> Optional[str]:
        try:
            return payload["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
        except (KeyError, IndexError, TypeError):
            return None

    phone_number = extract_phone_number_from_payload(payload)

    # STEP 5: PHONE NUMBER GUARD - return error if phone_number is None/missing
    if not phone_number:
        logger.error(f"WEBHOOK_PAYLOAD_MISSING_PHONE_NUMBER: unable to extract wa_id from payload")
        return {"status": "error", "message": "Missing phone number in payload"}

    # STEP 5.5: SKIP NON-MESSAGE EARLY - avoid unwanted welcome messages and reduce load
    def is_message_event(payload: Dict[str, Any]) -> bool:
        """Check if the payload contains a real message (not a status callback)."""
        try:
            return ("entry" in payload and len(payload["entry"]) > 0 and
                    "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
                    "value" in payload["entry"][0]["changes"][0] and
                    "messages" in payload["entry"][0]["changes"][0]["value"] and
                    len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0)
        except (KeyError, IndexError, TypeError):
            return False

    if not is_message_event(payload):
        logger.info(f"WEBHOOK_NON_MESSAGE_EVENT: skipping processing for phone_number={phone_number}")
        return {"status": "ok"}  # Early return, acknowledge receipt to Meta

    # STEP 6: BUTTON TAP DETECTION - check for Poster/User button replies to welcome message
    # This handles the case where we sent welcome buttons, user tapped one, and now we need to set initial state
    if ("entry" in payload and len(payload["entry"]) > 0 and
        "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
        "value" in payload["entry"][0]["changes"][0] and
        "messages" in payload["entry"][0]["changes"][0]["value"] and
        len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0 and
        "interactive" in payload["entry"][0]["changes"][0]["value"]["messages"][0] and
        ("button_reply" in payload["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"] or
         "list_reply" in payload["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"])):

        # Extract interactive ID (button_reply or list_reply)
        interactive_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"]
        if "button_reply" in interactive_obj:
            button_id = interactive_obj["button_reply"]["id"]
            list_id = ""
        elif "list_reply" in interactive_obj:
            list_id = interactive_obj["list_reply"]["id"]
            button_id = ""
        else:
            # Neither button nor list reply, fall through
            button_id = ""
            list_id = ""
        if button_id == "post_opportunities":
            # Poster-approval gate: check if poster is approved before allowing to post
            def _get_poster_status():
                return supabase.from_("posters").select("status").eq("phone_number", phone_number).execute()
            poster_status_result = await anyio.to_thread.run_sync(_get_poster_status)
            if poster_status_result.data and len(poster_status_result.data) > 0:
                poster_status = poster_status_result.data[0].get("status")
                if poster_status != "approved":
                    await poster_flow.send_whatsapp_message(
                        phone_number,
                        body="Your poster registration is still pending approval. You'll be able to post opportunities once approved."
                    )
                    return {"status": "ok"}
                # Approved poster -> start a NEW posting flow. Clear any stale state first so old
                # collected_data can't merge in (mirrors how the edit flow starts).
                await clear_conversation_state(phone_number)
                await set_conversation_state(
                    phone_number=phone_number,
                    flow="post_opportunity",
                    step="awaiting_type",
                    data={}  # No data collected yet
                )
                await poster_flow.send_whatsapp_message(
                    phone_number,
                    body="What type of opportunity is this? (meeting / volunteering / event / scholarship / other)"
                )
                return {"status": "ok"}
            # Poster row not found -> new first-contact poster: start poster registration flow
            await registration.handle_role_selection(phone_number, payload, "register_poster")
            return {"status": "ok"}
        elif button_id == "find_opportunities":
            # First-contact role button (Section 1.1) - only ever shown when no user
            # row exists yet, so this starts a fresh user registration.
            await registration.handle_role_selection(phone_number, payload, "register_user")
            return {"status": "ok"}
        elif button_id == "available_apps":
            # Main-menu "Available Apps" (Section 2) - list the user's matched
            # opportunities. This used to share the first-contact id above, which
            # wrongly re-started registration and sent the "personalize" prompt.
            await poster_flow._handle_available_applications_button(phone_number)
            return {"status": "ok"}
        elif button_id == "my_posts":
            # Show list of poster's opportunities
            await poster_flow._handle_my_posts_button(phone_number)
            return {"status": "ok"}
        elif button_id == "my_applications":
            # Show list of user's applications
            await poster_flow._handle_my_applications_button(phone_number)
            return {"status": "ok"}
        elif button_id == "edit_interests":
            # Start edit interests flow
            await registration.handle_interests_edit_start(phone_number)
            return {"status": "ok"}
        # Admin post-approval button handling (approve_post_<uuid> / reject_post_<uuid>)
        elif button_id.startswith("approve_post_") or button_id.startswith("reject_post_"):
            # Delegate to poster_flow handler
            result = await poster_flow.handle_admin_post_approval_button(button_id)
            return result
        # Phase I: Available-application buttons (Apply Now / Remind Me Later / Ignore)
        elif button_id.startswith(application_flow.APPLICATION_BUTTON_PREFIXES):
            await application_flow.handle_application_button(phone_number, button_id)
            return {"status": "ok"}
        # Phase I: reusable deletion confirmation (Section 13) - Confirm / Cancel
        elif button_id.startswith(application_flow.DELETION_BUTTON_PREFIXES):
            await application_flow.handle_deletion_confirmation(phone_number, button_id)
            return {"status": "ok"}
        # Handle list replies (e.g., from "My Posts" list)
        elif list_id.startswith("select_post_"):
            # Extract opportunity ID and set up edit flow
            opportunity_id = list_id.split("_", 2)[2]
            await poster_flow._handle_select_post_for_edit(phone_number, opportunity_id)
            return {"status": "ok"}
        # Available-Applications list rows (Phase N bullet 1)
        elif list_id.startswith("avail_open_"):
            application_id = list_id.split("_", 2)[2]
            await poster_flow._handle_available_application_open(phone_number, application_id)
            return {"status": "ok"}
        elif list_id.startswith("avail_more_"):
            offset = int(list_id.split("_", 2)[2])
            await poster_flow._handle_available_applications_button(phone_number, offset=offset)
            return {"status": "ok"}
        # If it's some other interactive we don't recognize, fall through to normal processing

    # STEP 7: ADMIN NUMBER CHECK - handle admin commands before regular flows
    ADMIN_PHONE_NUMBER = os.getenv("ADMIN_PHONE_NUMBER")
    if phone_number == ADMIN_PHONE_NUMBER:
        await handle_admin_command(phone_number, payload)
        return {"status": "ok"}  # Admin commands handled, no further processing needed

    # STEP 8: ESCAPE HATCH CHECK - check for "cancel"/"menu" in message text (guarded for non-message events)
    phone_number = extract_phone_number_from_payload(payload)  # Re-extract in case it was cleared
    if phone_number:
        # Safely extract message text with fallback for non-message events (status, etc.)
        message_text = ""
        try:
            # Check if this is a message event (has messages array)
            if ("entry" in payload and len(payload["entry"]) > 0 and
                "changes" in payload["entry"][0] and len(payload["entry"][0]["changes"]) > 0 and
                "value" in payload["entry"][0]["changes"][0] and
                "messages" in payload["entry"][0]["changes"][0]["value"] and
                len(payload["entry"][0]["changes"][0]["value"]["messages"]) > 0):

                message_obj = payload["entry"][0]["changes"][0]["value"]["messages"][0]
                if ("text" in message_obj and
                    "body" in message_obj["text"]):
                    message_text = message_obj["text"]["body"].strip().lower()
        except (KeyError, IndexError, TypeError):
            # If any part of the structure is missing, treat as non-message event
            message_text = ""

        # Only check for escape hatch if we actually have message text
        if message_text in ["cancel", "menu"]:
            # Escape hatch triggered - clear state and treat as no active flow
            await clear_conversation_state(phone_number)
            # Continue to dispatcher below (will route to main menu/returning user logic)

    # STEP 9: MAIN DISPATCH RULE - conversation state lookup and routing logic
    conversation_state = await get_conversation_state(phone_number) if phone_number else None

    if conversation_state:
        # ROW EXISTS -> MID-FLOW
        # Route to handler for (conversation_state['current_flow'], conversation_state['current_step'])
        flow = conversation_state["current_flow"]
        step = conversation_state["current_step"]
        logger.info(f"WEBHOOK_MID_FLOW_ROUTE: phone_number={phone_number} flow={flow} step={step}")

        if flow == "register_poster" and step == "awaiting_display_name":
            await registration.handle_poster_display_name_step(phone_number, payload, conversation_state)
        elif flow == "register_user" and step == "awaiting_interests":
            await registration.handle_user_interests_step(phone_number, payload, conversation_state)
        elif flow == "edit_interests" and step == "awaiting_interests":
            await registration.handle_interests_edit_step(phone_number, payload, conversation_state)
        elif flow in ["post_opportunity", "edit_opportunity"]:
            # Dispatch to poster_flow step handler based on step
            if step == "awaiting_type":
                await poster_flow.handle_opportunity_type_step(phone_number, payload, conversation_state)
            elif step == "awaiting_title":
                await poster_flow.handle_opportunity_title_step(phone_number, payload, conversation_state)
            elif step == "awaiting_description":
                await poster_flow.handle_opportunity_description_step(phone_number, payload, conversation_state)
            elif step == "awaiting_tags":
                await poster_flow.handle_opportunity_tags_step(phone_number, payload, conversation_state)
            elif step == "awaiting_application_start_date":
                await poster_flow.handle_application_start_date_step(phone_number, payload, conversation_state)
            elif step == "awaiting_application_deadline":
                await poster_flow.handle_application_deadline_step(phone_number, payload, conversation_state)
            elif step == "awaiting_result_date":
                await poster_flow.handle_result_date_step(phone_number, payload, conversation_state)
            elif step == "awaiting_event_start_date":
                await poster_flow.handle_event_start_date_step(phone_number, payload, conversation_state)
            elif step == "awaiting_application_link":
                await poster_flow.handle_application_link_step(phone_number, payload, conversation_state)
            elif step == "awaiting_confirmation":
                await poster_flow.handle_opportunity_confirmation_step(phone_number, payload, conversation_state)
            else:
                logger.warning(f"UNEXPECTED POSTER FLOW STEP: flow={flow}, step={step}")
        elif flow == "remind_later" and step == "awaiting_time":
            await application_flow.handle_remind_later_time_step(phone_number, payload, conversation_state)
        elif flow == "outcome_event_date" and step == "awaiting_event_date":
            # Phase K (Section 8.3): free-text event start date after a "Yes" outcome.
            await application_flow.handle_outcome_event_date_step(phone_number, payload, conversation_state)
        else:
            # Log unexpected flow/step combination for debugging
            logger.warning(f"UNEXPECTED FLOW/STEP: flow={flow}, step={step}")
    else:
        # NO ROW -> CHECK IF RETURNING USER OR FIRST CONTACT
        # Use async helpers to check existence without blocking event loop
        user_exists_result = await user_exists(phone_number) if phone_number else False
        poster_exists_result = await poster_exists(phone_number) if phone_number else False

        if not user_exists_result and not poster_exists_result:
            # FIRST CONTACT -> Welcome message (Poster/User buttons)
            await registration.handle_first_contact(phone_number)
        else:
            # RETURNING USER/POSTER WITH NO ACTIVE FLOW -> Main menu or relevant top-level handler
            await registration.send_main_menu(phone_number, is_returning_user=user_exists_result, is_returning_poster=poster_exists_result)

    # STEP 10: LOG THE PAYLOAD FOR DEBUGGING/VERIFICATION
    logger.info(f"WEBHOOK_PAYLOAD_RECEIVED: {json.dumps(payload, indent=2)}")

    # STEP 11: RETURN ACKNOWLEDGMENT TO META
    # Meta expects a 200 OK response to know we received the webhook
    return {"status": "ok"}


# Section 10.5: WABA-level Webhook Subscription Helper
def check_waba_subscription() -> bool:
    """
    Check if our WABA is subscribed to our app via Graph API.
    This should be called during startup or as a one-time verification step.

    Returns:
        True if subscribed, False otherwise

    Note: This requires making authenticated calls to the Graph API.
    For simplicity in this implementation, we assume this has been done
    as part of the already-complete app/WABA publication step per CLAUDE.md.
    In a production implementation, this would verify/subscribe via:
    - GET /{WABA_ID}/subscribed_apps to check current subscriptions
    - POST /{WABA_ID}/subscribed_apps if not subscribed
    """
    # Per CLAUDE.md: "Already complete — registered phone number, System User access token,
    # message templates, app/WABA publication, privacy policy."
    # We'll log a reminder but assume it's done for this phase.
    logger.info("REMINDER: Verify WABA-level subscription via POST /{WABA_ID}/subscribed_apps if needed")
    return True  # Assume already handled per CLAUDE.md documentation