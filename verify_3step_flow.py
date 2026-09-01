"""
Verify 3-step flow by directly testing conversation state functions
and showing database state at each step.
"""

import os
import asyncio
from dotenv import load_dotenv
from conversation import get_conversation_state, set_conversation_state, clear_conversation_state

# Load environment variables
load_dotenv()

async def verify_3step_flow():
    """Verify a 3-step flow and show the database state at each step."""
    print("Verifying 3-Step Flow Conversation State")
    print("=" * 50)

    # Use a test phone number that's unlikely to exist
    test_phone = "+15559990000"

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
        data={"name": "Alice Smith", "age": 20}
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
        data={"city": "New York", "interests": ["coding", "sports"]}  # This should merge with existing data
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

    # Show the merged data clearly
    print(f"\n5. Final merged data verification:")
    final_data = state_after_step3.get('collected_data', {})
    expected_keys = ['name', 'age', 'city', 'interests', 'education', 'year']
    for key in expected_keys:
        if key in final_data:
            print(f"   {key}: {final_data[key]}")
        else:
            print(f"   {key}: MISSING")

    # Final: Clear state
    print(f"\n6. After clearing conversation state:")
    await clear_conversation_state(test_phone)
    final_state = await get_conversation_state(test_phone)
   print(f"   {final_state}")

    print("\n" + "=" * 50)
    print("3-Step Flow Verification Complete")
    return True

if __name__ == "__main__":
    asyncio.run(verify_3step_flow())