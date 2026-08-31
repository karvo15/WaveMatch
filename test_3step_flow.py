"""
Test the 3-step flow for conversation state management.
"""

import os
import asyncio
from dotenv import load_dotenv
from conversation import get_conversation_state, set_conversation_state, clear_conversation_state

# Load environment variables
load_dotenv()

async def test_3step_flow():
    """Test a 3-step flow and show the database state at each step."""
    print("Testing 3-Step Flow Conversation State")
    print("=" * 50)

    # Use a test phone number
    test_phone = "+15551234567"

    # Clean up any existing state
    await clear_conversation_state(test_phone)
    print(f"\n1. Initial state for {test_phone}:")
    initial_state = await get_conversation_state(test_phone)
    print(f"   {initial_state}")

    # Step 1: First interaction
    print(f"\n2. After step 1 (flow: register_user, step: awaiting_interests):")
    await set_conversation_state(
        phone_number=test_phone,
        flow="register_user",
        step="awaiting_interests",
        data={"name": "Alice Smith"}
    )
    state_after_step1 = await get_conversation_state(test_phone)
    print(f"   Phone: {state_after_step1.get('phone_number')}")
    print(f"   Flow: {state_after_step1.get('current_flow')}")
    print(f"   Step: {state_after_step1.get('current_step')}")
    print(f"   Data: {state_after_step1.get('collected_data')}")
    print(f"   Created: {state_after_step1.get('created_at')}")
    print(f"   Updated: {state_after_step1.get('updated_at')}")

    # Step 2: Second interaction
    print(f"\n3. After step 2 (flow: register_user, step: awaiting_display_name):")
    await set_conversation_state(
        phone_number=test_phone,
        flow="register_user",
        step="awaiting_display_name",
        data={"age": 25, "city": "New York"}  # This should merge with existing data
    )
    state_after_step2 = await get_conversation_state(test_phone)
    print(f"   Phone: {state_after_step2.get('phone_number')}")
    print(f"   Flow: {state_after_step2.get('current_flow')}")
    print(f"   Step: {state_after_step2.get('current_step')}")
    print(f"   Data: {state_after_step2.get('collected_data')}")
    print(f"   Created: {state_after_step2.get('created_at')}")
    print(f"   Updated: {state_after_step2.get('updated_at')}")

    # Step 3: Third interaction
    print(f"\n4. After step 3 (flow: register_user, step: awaiting_education):")
    await set_conversation_state(
        phone_number=test_phone,
        flow="register_user",
        step="awaiting_education",
        data={"education": "Computer Science", "year": "Junior"}  # More data to merge
    )
    state_after_step3 = await get_conversation_state(test_phone)
    print(f"   Phone: {state_after_step3.get('phone_number')}")
    print(f"   Flow: {state_after_step3.get('current_flow')}")
    print(f"   Step: {state_after_step3.get('current_step')}")
    print(f"   Data: {state_after_step3.get('collected_data')}")
    print(f"   Created: {state_after_step3.get('created_at')}")
    print(f"   Updated: {state_after_step3.get('updated_at')}")

    # Final: Clear state
    print(f"\n5. After clearing conversation state:")
    await clear_conversation_state(test_phone)
    final_state = await get_conversation_state(test_phone)
    print(f"   {final_state}")

    print("\n" + "=" * 50)
    print("3-Step Flow Test Complete")

if __name__ == "__main__":
    asyncio.run(test_3step_flow())