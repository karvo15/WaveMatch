"""
Standalone test script for WhatsApp messaging functions.
Tests all three functions by sending real messages to a confirmed working number.
"""

import os
import asyncio
import json
from dotenv import load_dotenv
from whatsapp import send_whatsapp_message, send_whatsapp_buttons, send_whatsapp_list_message

# Load environment variables
load_dotenv()

# Use ADMIN_PHONE_NUMBER as test recipient (confirmed working number)
TEST_RECIPIENT = os.getenv("ADMIN_PHONE_NUMBER")

if not TEST_RECIPIENT:
    raise ValueError("ADMIN_PHONE_NUMBER environment variable is required for testing")

print(f"Testing WhatsApp functions by sending messages to: {TEST_RECIPIENT}")
print("=" * 60)


async def test_send_whatsapp_message():
    """Test sending a simple text message."""
    print("\n1. Testing send_whatsapp_message()")
    print("-" * 40)

    try:
        result = await send_whatsapp_message(
            to=TEST_RECIPIENT,
            body="Hello from WaveMatch! This is a test text message."
        )
        print("SUCCESS: Text message sent")
        print(f"   Response: {json.dumps(result, indent=2)}")
        return True, result
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False, str(e)


async def test_send_whatsapp_buttons():
    """Test sending an interactive button message."""
    print("\n2. Testing send_whatsapp_buttons()")
    print("-" * 40)

    try:
        buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": "btn_1",
                    "title": "Option A"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "btn_2",
                    "title": "Option B"
                }
            },
            {
                "type": "reply",
                "reply": {
                    "id": "btn_3",
                    "title": "Option C"
                }
            }
        ]

        result = await send_whatsapp_buttons(
            to=TEST_RECIPIENT,
            body="Please choose an option:",
            buttons=buttons
        )
        print("SUCCESS: Button message sent")
        print(f"   Response: {json.dumps(result, indent=2)}")
        return True, result
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False, str(e)


async def test_send_whatsapp_list_message():
    """Test sending an interactive list message."""
    print("\n3. Testing send_whatsapp_list_message()")
    print("-" * 40)

    try:
        sections = [
            {
                "title": "Available Actions",
                "rows": [
                    {
                        "id": "row_1",
                        "title": "View Opportunities",
                        "description": "See what's available"
                    },
                    {
                        "id": "row_2",
                        "title": "My Applications",
                        "description": "Check your status"
                    },
                    {
                        "id": "row_3",
                        "title": "Settings",
                        "description": "Update preferences"
                    }
                ]
            }
        ]

        result = await send_whatsapp_list_message(
            to=TEST_RECIPIENT,
            body="What would you like to do?",
            sections=sections
        )
        print("SUCCESS: List message sent")
        print(f"   Response: {json.dumps(result, indent=2)}")
        return True, result
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return False, str(e)


async def run_all_tests():
    """Run all WhatsApp function tests."""
    print("Starting WhatsApp function tests...")
    print(f"Using recipient: {TEST_RECIPIENT}")

    # Run tests sequentially to avoid rate limiting issues
    results = []

    # Test 1: Simple text message
    success, result = await test_send_whatsapp_message()
    results.append(("send_whatsapp_message", success, result))

    # Wait a moment between tests to avoid rate limiting
    await asyncio.sleep(2)

    # Test 2: Button message
    success, result = await test_send_whatsapp_buttons()
    results.append(("send_whatsapp_buttons", success, result))

    # Wait a moment between tests
    await asyncio.sleep(2)

    # Test 3: List message
    success, result = await test_send_whatsapp_list_message()
    results.append(("send_whatsapp_list_message", success, result))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY:")
    print("=" * 60)

    all_passed = True
    for test_name, success, result in results:
        status = "PASS" if success else "FAIL"
        print(f"  {test_name}: {status}")
        if not success:
            all_passed = False

    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    # Run the async test suite
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)