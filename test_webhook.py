"""
Test script for webhook functionality.
Tests the webhook verification and receiver functions directly.
"""

import os
import hmac
import hashlib
import json
from unittest.mock import Mock
from webhook import verify_webhook, receive_webhook, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


async def test_webhook_verification_success():
    """Test successful webhook verification."""
    print("Testing webhook verification - SUCCESS case")
    print("-" * 50)

    # Create a mock request with correct verification parameters
    mock_request = Mock()
    mock_request.query_params = {
        "hub.mode": "subscribe",
        "hub.verify_token": WHATSAPP_VERIFY_TOKEN,
        "hub.challenge": "TEST_CHALLENGE_12345"
    }

    try:
        result = await verify_webhook(mock_request)
        if result == "TEST_CHALLENGE_12345":
            print("SUCCESS: Webhook verification passed")
            print(f"   Returned challenge: {result}")
            return True
        else:
            print(f"❌ FAILED: Expected 'TEST_CHALLENGE_12345', got '{result}'")
            return False
    except Exception as e:
        print(f"❌ FAILED: Exception occurred: {e}")
        return False


async def test_webhook_verification_failure():
    """Test failed webhook verification."""
    print("\nTesting webhook verification - FAILURE case")
    print("-" * 50)

    # Test wrong token
    mock_request = Mock()
    mock_request.query_params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "WRONG_TOKEN",
        "hub.challenge": "TEST_CHALLENGE_12345"
    }

    try:
        result = await verify_webhook(mock_request)
        print(f"❌ FAILED: Should have raised HTTPException, but got: {result}")
        return False
    except Exception as e:
        if "403" in str(e):
            print("SUCCESS: Webhook verification correctly failed with wrong token")
            return True
        else:
            print(f"❌ FAILED: Unexpected exception: {e}")
            return False


async def test_webhook_receiver_signature_verification():
    """Test webhook receiver signature verification."""
    print("\nTesting webhook receiver signature verification")
    print("-" * 50)

    # Create a sample payload
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "15551234567",
                        "phone_number_id": "1357215354134244"
                    },
                    "contacts": [{
                        "profile": {
                            "name": "Test User"
                        },
                        "wa_id": "250795158652"
                    }],
                    "messages": [{
                        "from": "250795158652",
                        "id": "wamid.HBgMTEST123",
                        "timestamp": "1234567890",
                        "text": {
                            "body": "Hello"
                        }
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    # Convert payload to JSON string then to bytes
    payload_json = json.dumps(payload)
    payload_bytes = payload_json.encode('utf-8')

    # Create signature using the app secret
    secret_bytes = WHATSAPP_APP_SECRET.encode('utf-8')
    mac = hmac.new(secret_bytes, payload_bytes, hashlib.sha256)
    expected_signature = mac.hexdigest()
    signature_header = f"sha256={expected_signature}"

    # Create mock request with correct signature
    mock_request = Mock()
    async def mock_body():
        return payload_bytes
    mock_request.body = mock_body
    mock_request.headers = {
        "X-Hub-Signature-256": signature_header
    }

    try:
        result = await receive_webhook(mock_request)
        if result.get("status") == "ok":
            print("SUCCESS: Webhook receiver passed with valid signature")
            return True
        else:
            print(f"FAILED: Unexpected response: {result}")
            return False
    except Exception as e:
        print(f"❌ FAILED: Exception occurred: {e}")
        return False


async def test_webhook_receiver_invalid_signature():
    """Test webhook receiver with invalid signature."""
    print("\nTesting webhook receiver - INVALID signature")
    print("-" * 50)

    # Create a sample payload
    payload = {"test": "data"}
    payload_bytes = json.dumps(payload).encode('utf-8')

    # Create mock request with WRONG signature
    mock_request = Mock()
    async def mock_body():
        return payload_bytes
    mock_request.body = mock_body
    mock_request.headers = {
        "X-Hub-Signature-256": "sha256=invalid_signature_here"
    }

    try:
        result = await receive_webhook(mock_request)
        print(f"FAILED: Should have raised HTTPException, but got: {result}")
        return False
    except Exception as e:
        if "403" in str(e) and "signature" in str(e).lower():
            print("SUCCESS: Webhook receiver correctly rejected invalid signature")
            return True
        else:
            print(f"❌ FAILED: Unexpected exception: {e}")
            return False


async def test_webhook_receiver_tampered_payload():
    """Test webhook receiver with tampered payload (valid signature for different payload)."""
    print("\nTesting webhook receiver - TAMPERED payload")
    print("-" * 50)

    # Original payload
    original_payload = {"original": "data"}
    original_bytes = json.dumps(original_payload).encode('utf-8')

    # Create signature for ORIGINAL payload
    secret_bytes = WHATSAPP_APP_SECRET.encode('utf-8')
    mac = hmac.new(secret_bytes, original_bytes, hashlib.sha256)
    expected_signature = mac.hexdigest()
    signature_header = f"sha256={expected_signature}"

    # Tampered payload (different content)
    tampered_payload = {"tampered": "data"}
    tampered_bytes = json.dumps(tampered_payload).encode('utf-8')

    # Create mock request with ORIGINAL signature but TAMPERED payload
    mock_request = Mock()
    async def mock_body():
        return tampered_bytes  # Note: body is tampered
    mock_request.body = mock_body
    mock_request.headers = {
        "X-Hub-Signature-256": signature_header  # But signature is for original
    }

    try:
        result = await receive_webhook(mock_request)
        print(f"FAILED: Should have raised HTTPException, but got: {result}")
        return False
    except Exception as e:
        if "403" in str(e) and "signature" in str(e).lower():
            print("SUCCESS: Webhook receiver correctly rejected tampered payload")
            return True
        else:
            print(f"❌ FAILED: Unexpected exception: {e}")
            return False


async def run_all_tests():
    """Run all webhook tests."""
    print("Webhook Function Tests")
    print("=" * 60)

    tests = [
        test_webhook_verification_success,
        test_webhook_verification_failure,
        test_webhook_receiver_signature_verification,
        test_webhook_receiver_invalid_signature,
        test_webhook_receiver_tampered_payload
    ]

    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"FAILED: Test {test.__name__} crashed: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    print("TEST SUMMARY:")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    for i, (test, result) in enumerate(zip(tests, results)):
        status = "PASS" if result else "FAIL"
        print(f"  {test.__name__}: {status}")

    print(f"\nOverall: {passed}/{total} tests passed")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    # Run the async test suite
    import asyncio
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)