import os
from dotenv import load_dotenv

load_dotenv()
print("Environment loaded successfully")
print(f"SUPABASE_URL present: {bool(os.getenv('SUPABASE_URL'))}")
print(f"ADMIN_PHONE_NUMBER present: {bool(os.getenv('ADMIN_PHONE_NUMBER'))}")