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
- **Phase G (Poster Posting Flow): implementation exists, NOT YET COMPLETE — do not
  mark done, do not proceed to Phase H.** `poster_flow.py` created, `webhook.py` 
  modified, `3-Full-Product-Logic.md` Section 0 updated with two new interaction-type 
  rows (opportunity confirmation buttons, admin post-approval buttons). Schema fix 
  applied and confirmed live: `opportunity_status` enum extended with `pending_approval` 
  and `rejected` via `ALTER TYPE` (run directly in Supabase, `5-Data-Schema.sql` updated 
  to match) — this was a real pre-existing gap between the schema and 
  `3-Full-Product-Logic.md` Section 16, not something introduced this phase.

  Multiple real bugs found and fixed across several review rounds, each verified via 
  direct full-file reads (not summaries):
  - `_create_opportunity_tag()` was called but never defined — guaranteed crash on any 
    confirmed post with tags. Fixed.
  - `handle_opportunity_confirmation_step()` didn't branch on `current_flow`, so an edit 
    would silently INSERT a duplicate opportunity instead of UPDATE-ing the original. 
    Fixed — now correctly routes to update-path when `current_flow == "edit_opportunity"`.
  - No entry point existed into the edit flow at all (step handlers existed, nothing set 
    `conversation_state` to enter them) — fixed by adding a `[📝 My Posts]` button → 
    WhatsApp list of the poster's own opportunities → row selection sets 
    `flow='edit_opportunity'`, `opportunity_id` populated, existing field values 
    pre-filled into `collected_data`.
  - A "hybrid" main menu briefly existed showing both poster and user menu items 
    simultaneously — violates the explicit one-time-fork rule in 
    `1-Product-Plan.md` Section 4 / `3-Full-Product-Logic.md` Section 1.1 (a phone 
    number is never both). Root cause: dead-code `elif is_returning_user and 
    is_returning_poster` branch. Removed; poster-only menu is now 
    `[➕ Post an Opportunity] [📝 My Posts]` (2 buttons — "My Applications" correctly 
    excluded from the poster menu since `applications.user_id` references `users`, not 
    `posters`, per the schema).
  - Menu items were initially sent as plain text with bracket-decorated labels (e.g. 
    `"[📝 My Posts]"` inside a `send_whatsapp_message()` body) rather than real WhatsApp 
    interactive buttons — nothing was actually tappable. This was pre-existing behavior 
    carried over from Phase F, not a regression introduced this phase, but is now fixed 
    for the poster-only and user-only menus via real `send_whatsapp_buttons()` calls.
  - `_handle_my_posts_button()`'s list-row title truncation didn't account for the 
    prepended status emoji + space, risking exceeding WhatsApp's 24-char row-title limit 
    (`6-Platform-Constraints.md` §10.1 — the same class of failure already confirmed live 
    via `(#131009)` earlier in the project). Fixed with dynamic length calculation based 
    on the actual emoji length.
  - Admin post-approval redesigned to be fully stateless: `opportunity_id` is encoded 
    directly in the button ID (`approve_post_<uuid>` / `reject_post_<uuid>`) rather than 
    relying on `conversation_states` (which is keyed by phone_number and would silently 
    clobber a second pending approval for the same admin). Includes a status-check guard 
    before acting (only proceeds if the opportunity is still `pending_approval`), which 
    protects against both stale webhook retries and genuine admin double-taps.
  - Edit-flow prompts briefly claimed a poster could "keep current" a field's value with 
    no code actually supporting that — misleading UI text corrected to match real 
    behavior (edit currently requires re-entering all 9 fields; true partial-edit support 
    is a possible future improvement, not built now).
  - `_handle_my_applications_button()` is a deliberate stub (Phase N builds the real 
    My Applications list views per `7-Build-Checklist.md`) — exists only to prevent a 
    `NameError` crash if a user taps that menu item early.

  **Confirmed outstanding as of the last direct full-file read — NOT yet fixed:**
  1. `webhook.py` calls `send_whatsapp_message()`, `_handle_my_posts_button()`, 
     `_handle_my_applications_button()`, and `_handle_select_post_for_edit()` as bare 
     unqualified names. `send_whatsapp_message` is never imported in `webhook.py`; the 
     other three are defined in `poster_flow.py` and need the `poster_flow.` prefix 
     (compare to the correctly-prefixed `poster_flow.handle_opportunity_type_step` calls 
     elsewhere in the same file). **Will raise `NameError`** on: the poster-approval 
     gate, tapping "My Posts", tapping "My Applications", and selecting a post from the 
     edit list.
  2. The outer guard in `webhook.py` STEP 6 only checks for `"button_reply"` before 
     entering the interactive-message handling block. A WhatsApp list selection (e.g. 
     from "My Posts") arrives with `"list_reply"`, not `"button_reply"` — so the block, 
     including the `select_post_` dispatch, is **never reached** for any list tap. The 
     edit entry point is currently unreachable by its actual intended trigger, 
     independent of bug #1.
  3. In `poster_flow.py`'s `handle_opportunity_confirmation_step()`, 
     `parsed_interests = conv_state.get("parsed_interests", [])` appears twice (create 
     and edit branches) but `parsed_interests` was stored inside `collected_data`, not 
     as a top-level key on `conv_state` (compare to `conv_state["collected_data"].get
     ("opportunity_id")`, done correctly a few lines below in the same function). This 
     line always evaluates to an empty list — **every opportunity created or edited 
     silently gets zero tags attached**, no crash, no error shown to the poster.

  None of these three have been confirmed fixed via a direct file read since they were 
  identified. **Do not trust a "done"/"verified" self-report for this phase without 
  re-reading the actual current `webhook.py` and `poster_flow.py` in full first** — this 
  phase has already produced multiple confident "complete" reports that turned out, on 
  direct file inspection, to still contain the exact bug just described as fixed.

  Not yet pushed to GitHub, not yet deployed, not yet tested live. `git status` as of 
  the last check showed several untracked scratch files 
  (`temp_fixed_func.py`, `temp_head.py`, `temp_tail.py`, `test_poster_flow.py`, 
  `.bak`/`.backup` files) that should NOT be staged — only `poster_flow.py`, `webhook.py`, 
  and `3-Full-Product-Logic.md` are the real Phase G deliverable.