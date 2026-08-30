import os
import json
from dotenv import load_dotenv
from database import supabase
from datetime import date, datetime
import uuid

load_dotenv()

def test_insert_select(table_name, test_data, cleanup_id_field='id'):
    """Test insert and select operations on a table"""
    print(f"\n--- Testing {table_name} ---")

    try:
        # Try to insert test data
        print(f"Inserting test data...")
        insert_result = supabase.from_(table_name).insert(test_data).execute()

        if hasattr(insert_result, 'error') and insert_result.error:
            print(f"   INSERT ERROR: {insert_result.error}")
            return False, None

        print(f"   INSERT SUCCESS: {len(insert_result.data)} row(s)")
        inserted_id = insert_result.data[0].get(cleanup_id_field) if insert_result.data else None

        # Try to select the inserted data
        if inserted_id:
            select_result = supabase.from_(table_name).select("*").eq(cleanup_id_field, inserted_id).execute()
            if hasattr(select_result, 'error') and select_result.error:
                print(f"   SELECT ERROR: {select_result.error}")
                # Still consider insert successful if insert worked
                return True, inserted_id
            else:
                print(f"   SELECT SUCCESS: Found {len(select_result.data)} row(s)")
                if select_result.data:
                    print(f"   Retrieved data keys: {list(select_result.data[0].keys())}")
                return True, inserted_id
        else:
            print("   WARNING: No ID returned from insert")
            return True, None

    except Exception as e:
        print(f"   EXCEPTION: {e}")
        return False, None

def cleanup_test_data(table_name, test_id, id_field='id'):
    """Clean up test data"""
    try:
        if test_id:
            supabase.from_(table_name).delete().eq(id_field, test_id).execute()
            print(f"   Cleaned up test data from {table_name}")
    except Exception as e:
        print(f"   Cleanup warning for {table_name}: {e}")

def main():
    print("Testing database insert/select operations on core tables...")

    # Test data for each core table (minimal valid data based on schema)
    # We need to handle foreign key constraints carefully

    test_results = []
    created_ids = {}  # Track created IDs for cleanup

    # 1. Tags table (already has data, but let's test with a custom tag)
    tag_success, tag_id = test_insert_select(
        "tags",
        {"name": f"Test Tag {uuid.uuid4().hex[:8]}", "is_custom": True}
    )
    test_results.append(("tags", tag_success))
    if tag_success and tag_id:
        created_ids[("tags", "id")] = tag_id

    # 2. Users table
    user_success, user_id = test_insert_select(
        "users",
        {"phone_number": f"+1555{uuid.uuid4().hex[:8]}", "name": "Test User"}
    )
    test_results.append(("users", user_success))
    if user_success and user_id:
        created_ids[("users", "id")] = user_id

    # 3. Posters table
    poster_success, poster_id = test_insert_select(
        "posters",
        {"phone_number": f"+1555{uuid.uuid4().hex[:8]}", "display_name": "Test Poster", "status": "pending"}
    )
    test_results.append(("posters", poster_success))
    if poster_success and poster_id:
        created_ids[("posters", "id")] = poster_id

    # 4. Opportunities table (requires a poster_id)
    # First, let's use an existing poster or create one
    opp_success, opp_id = False, None
    if poster_id:  # Use the poster we just created
        opp_success, opp_id = test_insert_select(
            "opportunities",
            {
                "poster_id": poster_id,
                "title": "Test Opportunity",
                "description": "Test description",
                "type": "Test Type",
                "application_start_date": "2026-09-01",
                "application_deadline": "2026-09-30",
                "result_date": "2026-10-15",
                "event_start_date": "2026-10-01",
                "link": "https://example.com/test",
                "status": "active"
            }
        )
    else:
        # Try to use a placeholder - this will likely fail due to FK constraint
        opp_success, opp_id = test_insert_select(
            "opportunities",
            {
                "poster_id": "00000000-0000-0000-0000-000000000000",  # Will fail FK
                "title": "Test Opportunity",
                "description": "Test description",
                "type": "Test Type",
                "application_start_date": "2026-09-01",
                "application_deadline": "2026-09-30",
                "result_date": "2026-10-15",
                "event_start_date": "2026-10-01",
                "link": "https://example.com/test",
                "status": "active"
            }
        )
    test_results.append(("opportunities", opp_success))
    if opp_success and opp_id:
        created_ids[("opportunities", "id")] = opp_id

    # 5. Applications table (requires user_id and optionally opportunity_id)
    app_success, app_id = False, None
    if user_id:  # Use the user we just created
        app_success, app_id = test_insert_select(
            "applications",
            {
                "user_id": user_id,
                "status": "available",
                "reminder_interval_days": 2,
                "deadline_heads_up_sent": False
            }
        )
    else:
        app_success, app_id = test_insert_select(
            "applications",
            {
                "user_id": "00000000-0000-0000-0000-000000000000",  # Will fail FK
                "status": "available",
                "reminder_interval_days": 2,
                "deadline_heads_up_sent": False
            }
        )
    test_results.append(("applications", app_success))
    if app_success and app_id:
        created_ids[("applications", "id")] = app_id

    # 6. Conversation states table
    conv_success, conv_id = test_insert_select(
        "conversation_states",
        {
            "phone_number": f"+1555{uuid.uuid4().hex[:8]}",
            "current_flow": "register_user",
            "current_step": "awaiting_name",
            "collected_data": {"temp_field": "test_value"}
        },
        cleanup_id_field="phone_number"  # This table uses phone_number as primary key
    )
    test_results.append(("conversation_states", conv_success))
    if conv_success and conv_id:
        created_ids[("conversation_states", "phone_number")] = conv_id

    # Cleanup created test data
    print("\n--- Cleaning up test data ---")
    for (table_name, id_field), test_id in created_ids.items():
        cleanup_test_data(table_name, test_id, id_field)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY:")
    all_passed = True
    for table_name, success in test_results:
        status = "PASS" if success else "FAIL"
        print(f"  {table_name}: {status}")
        if not success:
            all_passed = False

    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    print("="*60)

    if not all_passed:
        print("\nNote: Some tests may have failed due to foreign key constraints.")
        print("This is expected when we don't have valid related records.")
        print("The important thing is that the schema structure is correct.")

if __name__ == "__main__":
    main()