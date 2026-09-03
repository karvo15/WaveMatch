import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(supabase_url, supabase_key)

# Force HTTP/1.1 to prevent HTTP/2 concurrency issues under concurrent webhook load
try:
    from postgrest.utils import SyncClient
    if hasattr(supabase, 'postgrest'):
        postgrest_client = supabase.postgrest
        # Replace the session with one that forces HTTP/1.1
        original_session = postgrest_client.session
        new_session = SyncClient(
            base_url=original_session.base_url,
            headers=original_session.headers,
            timeout=original_session.timeout,
            verify=original_session.verify,
            follow_redirects=original_session.follow_redirects,
            http2=False,  # Critical: Force HTTP/1.1 instead of HTTP/2
        )
        postgrest_client.session = new_session
except Exception as e:
    # Fallback if postgrest.utils.SyncClient not available or any other error - log but continue
    import logging
    logging.getLogger(__name__).error(f"Failed to force HTTP/1.1 on Supabase client: {e}")
