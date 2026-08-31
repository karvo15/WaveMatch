"""
Test script for conversation state management functions.
Tests the conversation.py module directly.
"""

import os
import asyncio
from dotenv import load_dotenv
from conversation import get_conversation_state, set_conversation_state, clear_conversation_state, user_exists, poster_exists

# Load environment variables
load_dotenv()

async def test_conversation_functions():
    """Test all conversation state management functions."""
    print("Testing conversation state management functions...")
    print("=" * 60)

    # Use a test phone number that's unlikely to exist
    test_phone = "+15559998888"

    # Test 1: get_conversation_state on non-existent number (should return None)
    print(f"\n1. Testing get_conversation_state for non-existent {test_phone}")
    result = await get_conversation_state(test_phone)
    if result is None:
        print("   [PASS] Returned None for non-existent conversation state")
    else:
        print(f"   [FAIL] Expected None, got {result}")
        return False

    # Test 2: set_conversation_state
    print(f"\n2. Testing set_conversation_state for {test_phone}")
    try:
        await set_conversation_state(
            phone_number=test_phone,
            flow="test_flow",
            step="step1",
            data={"test_field": "test_value", "number": 42}
        )
        print("   [PASS] set_conversation_state completed without error")
    except Exception as e:
        print(f"   [FAIL] Exception in set_conversation_state: {e}")
        return False

    # Test 3: get_conversation_state after setting (should return the data)
    print(f"\n3. Testing get_conversation_state after setting")
    result = await get_conversation_state(test_phone)
    if result is not None:
        print("   [PASS] Retrieved conversation state:")
        print(f"      phone_number: {result.get('phone_number')}")
        print(f"      current_flow: {result.get('current_flow')}")
        print(f"      current_step: {result.get('current_step')}")
        print(f"      collected_data: {result.get('collected_data')}")
        print(f"      created_at: {result.get('created_at')}")
        print(f"      updated_at: {result.get('updated_at')}")

        # Verify the data was stored correctly
        if (result.get('phone_number') == test_phone and
            result.get('current_flow') == 'test_flow' and
            result.get('current_step') == 'step1' and
            result.get('collected_data', {}).get('test_field') == 'test_value'):
            print("   [PASS] All data fields match expected values")
        else:
            print("   [FAIL] Data fields don't match expected values")
            return False
    else:
        print("   [FAIL] Expected conversation state data, got None")
        return False

    # Test 4: set_conversation_state again to test data merging
    print(f"\n4. Testing set_conversation_state again to test data merging")
    try:
        await set_conversation_state(
            phone_number=test_phone,
            flow="test_flow",  # Same flow
            step="step2",      # Different step
            data={"another_field": "another_value"}  # New data to merge
        )
        print("   [PASS] Second set_conversation_state completed without error")
    except Exception as e:
        print(f"   [FAIL] Exception in second set_conversation_state: {e}")
        return False

    # Test 5: get_conversation_state after second setting (should show merged data)
    print(f"\n5. Testing get_conversation_state after second setting (data merging)")
    result = await get_conversation_state(test_phone)
    if result is not None:
        collected_data = result.get('collected_data', {})
        print(f"   Retrieved collected_data: {collected_data}")

        # Check that both original and new data are present (merged)
        if (collected_data.get('test_field') == 'test_value' and
            collected_data.get('number') == 42 and
            collected_data.get('another_field') == 'another_value'):
            print("   [PASS] Data merging worked correctly - both original and new data present")
        else:
            print("   [FAIL] Data merging failed - missing expected fields")
            return False
    else:
        print("   [FAIL] Expected conversation state data, got None")
        return False

    # Test 6: Test user_exists and poster_exists with our test number (should be False)
    print(f"\n6. Testing user_exists and poster_exists for {test_phone}")
    user_result = await user_exists(test_phone)
    poster_result = await poster_exists(test_phone)
    if user_result is False and poster_result is False:
        print("   [PASS] Both user_exists and poster_exists returned False (expected for test number)")
    else:
        print(f"   [FAIL] Expected both False, got user_exists={user_result}, poster_exists={poster_result}")
        return False

    # Test 7: clear_conversation_state
    print(f"\n7. Testing clear_conversation_state for {test_phone}")
    try:
        await clear_conversation_state(test_phone)
        print("   [PASS] clear_conversation_state completed without error")
    except Exception as e:
        print(f"   [FAIL] Exception in clear_conversation_state: {e}")
        return False

    # Test 8: get_conversation_state after clearing (should return None)
    print(f"\n8. Testing get_conversation_state after clearing")
    result = await get_conversation_state(test_phone)
    if result is None:
        print("   [PASS] Returned None after clearing conversation state")
    else:
        print(f"   [FAIL] Expected None after clearing, got {result}")
        return False

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    return True

if __name__ == "__main__":
    # Run the async test
    success = asyncio.run(test_conversation_functions())
    exit(0 if success else 1)