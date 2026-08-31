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
from fastapi import Request, HTTPException
from dotenv import load_dotenv
from conversation import get_conversation_state, set_conversation_state, clear_conversation_state, user_exists, poster_exists

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


async def receive_webhook(request: Request) -> Dict[str, str]:
    """
    Handle incoming webhook payloads (POST request) with signature verification.

    CRITICAL: Follows Section 10.4 exactly - read raw body BEFORE parsing JSON.

    Args:
        request: FastAPI Request object

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

    # STEP 4: EXTRACT PHONE NUMBER AND CHECK FOR ESCAPE HATCH
    def extract_phone_number_from_payload(payload: Dict[str, Any]) -> Optional[str]:
        try:
            return payload["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
        except (KeyError, IndexError, TypeError):
            return None

    # STEP 5: CHECK FOR ESCAPE HATCH (cancel/menu) - PROPERLY GUARDED
    phone_number = extract_phone_number_from_payload(payload)
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

    # STEP 6: MAIN DISPATCH RULE - MUST BE FIRST THING AFTER SIGNATURE VERIFICATION
    conversation_state = await get_conversation_state(phone_number) if phone_number else None

    if conversation_state:
        # ROW EXISTS -> MID-FLOW
        # Route to handler for (conversation_state['current_flow'], conversation_state['current_step'])
        # Implementation will be completed in Phase F
        flow = conversation_state["current_flow"]
        step = conversation_state["current_step"]
        # TODO: In Phase F, add logic like:
        # if flow == "register_user" and step == "awaiting_interests":
        #     await handle_user_interests_step(phone_number, payload, conversation_state)
        # For now, we just log that we found a conversation state
        logger.info(f"MID-FLOW DETECTED: phone_number={phone_number}, flow={flow}, step={step}")
    else:
        # NO ROW -> CHECK IF RETURNING USER OR FIRST CONTACT
        # Use async helpers to check existence without blocking event loop
        user_exists_result = await user_exists(phone_number) if phone_number else False
        poster_exists_result = await poster_exists(phone_number) if phone_number else False

        if not user_exists_result and not poster_exists_result:
            # FIRST CONTACT -> Welcome message (Poster vs User buttons)
            # TODO: In Phase F, add logic to send welcome message with Poster/User buttons
            logger.info(f"FIRST CONTACT DETECTED: phone_number={phone_number}")
        else:
            # RETURNING USER/POSTER WITH NO ACTIVE FLOW -> Main menu or relevant top-level handler
            # TODO: In Phase F, add logic to show appropriate main menu based on user/poster type
            logger.info(f"RETURNING USER/POSTER DETECTED: phone_number={phone_number}")

    # STEP 7: LOG THE PAYLOAD FOR DEBUGGING/VERIFICATION
    logger.info(f"WEBHOOK_PAYLOAD_RECEIVED: {json.dumps(payload, indent=2)}")

    # STEP 8: RETURN ACKNOWLEDGMENT TO META
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