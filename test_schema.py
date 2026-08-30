import os
from dotenv import load_dotenv
from database import supabase

load_dotenv()

def test_table_exists(table_name):
    """Test if a table exists by trying to select from it"""
    try:
        result = supabase.from_(table_name).select("*").limit(1).execute()
        return True, result.data
    except Exception as e:
        return False, str(e)

def main():
    print("Testing database connection and table existence...")

    # Test tags table (we know this works from /db-test)
    print("\n1. Testing tags table:")
    success, data = test_table_exists("tags")
    if success:
        print(f"   Tags table exists. Found {len(data)} rows.")
        if data:
            print(f"   Sample tag: {data[0]}")
    else:
        print(f"   Tags table error: {data}")

    # List of all tables we expect from the schema
    tables = [
        "tags",
        "users",
        "user_tags",
        "posters",
        "opportunities",
        "opportunity_tags",
        "conversation_states",
        "applications"
    ]

    print("\n2. Testing all expected tables:")
    for table in tables:
        success, data = test_table_exists(table)
        if success:
            print(f"   ✓ {table}: EXISTS ({len(data)} rows sampled)")
        else:
            print(f"   ✗ {table}: ERROR - {data}")

    # Specifically check for seed tags count
    print("\n3. Checking seed tags count:")
    try:
        result = supabase.from_("tags").select("id", count="exact").execute()
        print(f"   Total tags in database: {result.count}")
        if result.count == 12:
            print("   ✓ Correctly has 12 seed tags")
        else:
            print(f"   ✗ Expected 12 seed tags, got {result.count}")
    except Exception as e:
        print(f"   ✗ Error counting tags: {e}")

if __name__ == "__main__":
    main()