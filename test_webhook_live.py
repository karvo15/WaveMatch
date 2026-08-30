"""
Live test for webhook functionality.
Starts the server and tests the webhook endpoints with real HTTP requests.
"""

import os
import time
import subprocess
import requests
import json
import hmac
import hashlib
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

if not WHATSAPP_APP_SECRET or not WHATSAPP_VERIFY_TOKEN:
    raise ValueError("Missing required environment variables")

SERVER_URL = "http://localhost:8000"
WEBHOOK_VERIFY_URL = f"{SERVER_URL}/webhook"
WEBHOOK_RECEIVE_URL = f"{SERVER_URL}/webhook"

def start_server():
    """Start the FastAPI server in the background."""
    # Use the existing main.py
    server_proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=r"C:\Users\dell\WaveMatch",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return server_proc

def stop_server(server_proc):
    """Stop the background server."""
    server_proc.terminate()
    server_proc.wait()

def test_get_webhook_verification():
    """Test the GET webhook verification endpoint."""
    print("Testing GET /webhook (verification)")
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": WHATSAPP_VERIFY_TOKEN,
        "hub.challenge": "LIVE_TEST_CHALLENGE_123"
    }
    response = requests.get(WEBHOOK_VERIFY_URL, params=params)
    print(f"  Status Code: {response.status_code}")
    print(f"  Response Text: {response.text}")
    if response.status_code == 200 and response.text == "LIVE_TEST_CHALLENGE_123":
        print("  ✅ SUCCESS: Verification passed")
        return True
    else:
        print("  ❌ FAILED: Verification failed")
        return False

def create_signed_payload(payload_dict):
    """Create a JSON payload and its signature."""
    payload_json = json.dumps(payload_dict)
    payload_bytes = payload_json.encode('utf-8')
    secret_bytes = WHATSAPP_APP_SECRET.encode('utf-8')
    mac = hmac.new(secret_bytes, payload_bytes, hashlib.sha256)
    signature = mac.hexdigest()
    return payload_json, payload_bytes, f"sha256={signature}"

def test_post_webhook_receiver_genuine():
    """Test the POST webhook receiver with a genuine signature."""
    print("\nTesting POST /webhook (genuine payload)")
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
                        "id": "wamid.LIVE_TEST_123",
                        "timestamp": "1234567890",
                        "text": {
                            "body": "Hello from live test"
                        }
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    payload_json, payload_bytes, signature = create_signed_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature
    }
    response = requests.post(WEBHOOK_RECEIVE_URL, data=payload_bytes, headers=headers)
    print(f"  Status Code: {response.status_code}")
    print(f"  Response JSON: {response.json()}")
    if response.status_code == 200 and response.json().get("status") == "ok":
        print("  ✅ SUCCESS: Genuine payload accepted")
        return True
    else:
        print("  ❌ FAILED: Genuine payload rejected")
        return False

def test_post_webhook_receiver_tampered():
    """Test the POST webhook receiver with a tampered payload."""
    print("\nTesting POST /webhook (tampered payload)")
    # Create a payload
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
                        "id": "wamid.LIVE_TEST_TAMPERED",
                        "timestamp": "1234567890",
                        "text": {
                            "body": "Hello from live test"
                        }
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    # Sign a different payload (to simulate tampering)
    fake_payload = {"fake": "data"}
    fake_json = json.dumps(fake_payload)
    fake_bytes = fake_json.encode('utf-8')
    secret_bytes = WHATSAPP_APP_SECRET.encode('utf-8')
    mac = hmac.new(secret_bytes, fake_bytes, hashlib.sha256)
    fake_signature = mac.hexdigest()
    # Now send the real payload but with the fake signature
    payload_json = json.dumps(payload)
    payload_bytes = payload_json.encode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={fake_signature}"
    }
    response = requests.post(WEBHOOK_RECEIVE_URL, data=payload_bytes, headers=headers)
    print(f"  Status Code: {response.status_code}")
    print(f"  Response JSON: {response.json()}")
    if response.status_code == 403:
        print("  ✅ SUCCESS: Tampered payload rejected")
        return True
    else:
        print("  ❌ FAILED: Tampered payload accepted")
        return False

def main():
    print("Starting live webhook tests...")
    print("=" * 50)

    server = None
    try:
        server = start_server()
        # Wait for server to start
        time.sleep(3)

        # Test GET verification
        get_success = test_get_webhook_verification()

        # Test POST genuine
        post_genuine_success = test_post_webhook_receiver_genuine()

        # Test POST tampered
        post_tampered_success = test_post_webhook_receiver_tampered()

        # Summary
        print("\n" + "=" * 50)
        print("LIVE TEST SUMMARY:")
        print("=" * 50)
        print(f"  GET Verification: {'PASS' if get_success else 'FAIL'}")
        print(f"  POST Genuine:     {'PASS' if post_genuine_success else 'FAIL'}")
        print(f"  POST Tampered:    {'PASS' if post_tampered_success else 'FAIL'}")

        overall = get_success and post_genuine_success and post_tampered_success
        print(f"\nOverall: {'PASS' if overall else 'FAIL'}")

    finally:
        if server:
            stop_server(server)

    return get_success and post_genuine_success and post_tampered_success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)