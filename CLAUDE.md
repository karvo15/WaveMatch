## Current progress (update this section as phases complete)

- **Phase A (Foundation):** complete — health check + Supabase connectivity verified 
  both locally and on the real Render deployment, after resolving the Python-version 
  and Render-env-var issues described in Section 5.
- **Phase B (Database):** complete — schema applied (all 8 tables including 
  `conversation_states`), seed tags confirmed, insert/select tested on every core table 
  and both join tables, Pydantic models built matching the schema with correct enum 
  usage, verified via direct file read after an initial line-number discrepancy was 
  caught and corrected.
- **Phase C (WhatsApp Connection):** complete — `send_whatsapp_message()`, 
  `send_whatsapp_buttons()`, `send_whatsapp_list_message()` built in `whatsapp.py`, each 
  tested with real, distinct API calls to a live number. All read credentials via 
  `os.getenv()`, no existing files touched.
- **Phase D (Webhook Receiving):** complete — real Meta-signed webhook verified live on 
  Render (signature check passing), WABA subscription confirmed via a real Graph API 
  call, two real bugs fixed (mislabeled "live" tests that were actually self-constructed; 
  a `NameError: name 'Request' is not defined` startup crash from a missing import).
- **Phase E (Conversation State Machine):** complete — `conversation.py` built 
  (`get_conversation_state()`, `set_conversation_state()`, `clear_conversation_state()`, 
  `user_exists()`, `poster_exists()`), dispatch logic added to `webhook.py`. Verified 
  live: 3-step state merge with correct incremental JSONB merge, state clearing, 
  persistence across a real Render restart, first-contact and returning-user detection 
  via real signed WhatsApp webhooks, signature verification present on every real 
  webhook log. Pushed to GitHub, clean working tree. Tagged as `v1-phase-e-stable`.
- **Phase F0 (Interaction Type Pass):** complete — all required Phase F steps (first-
  contact fork, poster display name, admin approve/reject, user interest selection) 
  confirmed against `3-Full-Product-Logic.md` Section 0 via fresh line-numbered reads. 
  No table additions needed. Pure documentation/verification pass, no code touched.
- **Phase F (Registration Flows):** complete — first-contact fork, poster registration 
  (pending → admin notification → approve/reject), user registration with layered tag 
  matching (exact/keyword/fuzzy/alias/custom), all driven by Phase E's conversation 
  state machine. Real bugs found and fixed during live testing, each verified against 
  actual file content and/or live behavior:
  - WhatsApp button format mismatch (`{"text": ...}` vs. the real 
    `{"type": "reply", "reply": {"id", "title"}}` structure) — caused a 500 on every 
    first contact
  - Button-tap detection read the wrong payload path (`value["interactive"]` instead of 
    `value["messages"][0]["interactive"]`) — meant tapping a button did nothing
  - Admin approval notification was sent to the admin instead of the poster
  - Admin ID regex assumed a short code format; posters.id is a real UUID
  - Duplicate/contradictory admin-check code block in the dispatcher (two step numbers 
    for the same logic)
  - Button-tap detection was ordered before the phone-number guard, reopening the 
    `phone_number=None` risk it was meant to close
  - `KeyError: 'messages'` crash when a WhatsApp status/read callback (no `messages` 
    key) reached MID-FLOW handlers expecting real message text
  - Retry-storm: no message-ID deduplication meant Meta's webhook retries reprocessed 
    the same event repeatedly; first dedup attempt was dead code (function-local state 
    reset every call) with a broken `datetime` import — fixed to real module-scope state
  - HTTP/2 concurrency crash under burst load (`KeyError` on stream IDs, `ProtocolError`) 
    — fixed by forcing HTTP/1.1 on the Supabase client (verified against the real 
    installed `postgrest` 0.19.3 `SyncClient` signature), adding an `asyncio.Semaphore` 
    around all DB operations in `conversation.py` and the previously-unwrapped calls in 
    `registration.py`, and an early-return for non-message webhook events placed 
    *before* any routing decision (not a forced `user_exists=False`, which would have 
    misrouted existing users into a false first-contact welcome)
  - `clear_conversation_state` had a typo crash (`run_sync.run_sync`)
  - `send_main_menu()` was called with no arguments after successful registration, so 
    new users got the generic fallback menu instead of the tailored returning-user menu
  
  All fixes verified via real file reads and/or live Render logs, not self-reports alone. 
  Final stable tag for this phase: **`v3-hotfix-http2-concurrency`** (note: 
  `v2-hotfix-http2-concurrency` also exists in git history as an earlier, 
  since-superseded checkpoint from mid-session — `v3` is the one that reflects the fully 
  verified end state; don't confuse the two).
- **Phase G (Poster Posting Flow):** next up. Reuses the layered tag-matching logic 
  already built in Phase F (`parse_interests()` in `registration.py`) — per 
  `7-Build-Checklist.md` Phase N's explicit note, this should be shared/reused for 
  poster tag parsing, not rebuilt from scratch.