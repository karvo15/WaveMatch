## Current progress (update this section as phases complete)

> **CURRENT PHASE: Phase K (Under Review -> Outcome) - in progress.** Phase J (Ongoing Reminder Cycle) is COMPLETE and verified (see its bullet below); Phase I (Core Button Handlers) is COMPLETE and verified (see its bullet below); Phase H (Matching Engine) is COMPLETE and verified live (see its bullet below). Phase G was marked COMPLETE by decision; its one deferred item (the second full-phase live re-test of the poster posting entry path) is tracked in the Phase G bullet below and is NOT a blocker. Every phase follows the 5-step building plan recorded in `8-Build-Process.md`; progress is ticked off in `7-Build-Checklist.md`.

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
- **Phase G (Poster Posting Flow): implementation code COMPLETE and pushed — the second full-phase live re-test is the
  only remaining gate when it was written; per the decision at the top of this file this is now a deferred re-test, not a blocker.** `poster_flow.py` created, `webhook.py` 
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
    `[➕ Post Opportunity] [📝 My Posts]` (2 buttons — label shortened from 21 chars to
    fit WhatsApp's 20-char limit — "My Applications" correctly 
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

  **All previously-flagged code issues are FIXED and verified via direct full-file
  reads (commit `8c12493`):** STEP 6 now matches `button_reply` or `list_reply`; all
  `webhook.py` calls use fully-qualified `poster_flow.*` names with
  `send_whatsapp_message` imported at module top; `handle_opportunity_confirmation_step`
  reads `parsed_interests` from `collected_data` so tags are attached on create/edit.

  **Bugs found during the first full-phase live-test attempt — FIXED in this session's
  working tree, pending re-test:**
  1. STEP 6 `post_opportunities` fell through to poster *registration* for an
     already-approved poster (silent dead-end — tapping "Post" did nothing). Now an
     approved poster starts a new posting flow: state cleared, then
     `flow="post_opportunity"`, `step="awaiting_type"`, and the type prompt is sent.
  2. Admin free-text `approve <poster_id>` sent the poster only a plain-text notice with
     no tappable entry. Now it sends a real interactive button message
     (`➕ Post Opportunity`, id `post_opportunities`), matching
     `4-Message-Flow-Examples.md` §2.
  3. (Found by inspection on the same path) Returning poster/user menus are real
     `send_whatsapp_buttons()` calls, but two titles exceeded WhatsApp's 20-char button
     limit and would raise `ValueError` at runtime: poster `➕ Post an Opportunity` (21)
     → `➕ Post Opportunity`, and user `📋 Available Applications` (24) → `📋 Available
     Apps`. All other button titles confirmed ≤ 20 chars.

  **State & deferred live re-test (NOT blocking):** Phase G code is complete and pushed to GitHub (`8c12493`
  + the fixes above). The second full-phase live test is still un-run; diagnostic logging for it (OPPORTUNITY_CONFIRM_START / OPPORTUNITY_CONFIRM_TAP / OPPORTUNITY_CONFIRM_UPDATE_OK / OPPORTUNITY_CONFIRM_CREATE_OK / WEBHOOK_MID_FLOW_ROUTE markers) was added in commit `2476653` to make that re-test easy to run later — the first
  attempt failed at "approved poster taps Post"; the posting entry point and the
  approval button above are exactly what that test hit. **Decision: Phase G is now marked COMPLETE and Phase H is the current phase (see the banner at the top of this file). The deferred re-test above no longer gates progression - the confirm-step latency bug under investigation was judged low-impact (it does not break core flows) and not worth further debugging spend.** Message templates (user
  registration / outcome notifications) were created and submitted for Meta review
  earlier in this phase; review is pending and does not block the current poster-flow
  test path. Admin short-ID parsing (e.g. `approve P1042`) stays deferred — the live
  admin flow uses full poster UUIDs and stateless `approve_post_<uuid>` /
  `reject_post_<uuid>` post-approval buttons. The untracked scratch files from the
  earlier session (`IMPLEMENTATION_COMPLETE.md`, `test_poster_flow.py`) are
  intentionally kept on disk and gitignored so the working tree stays clean.
- **Phase H (Matching Engine): COMPLETE and verified live.** Built `matching.py` with `run_matching_engine(opportunity_id)` per `3-Full-Product-Logic.md` Section 4: (1) the tag intersection is done Postgres-side - a single `user_tags` query filtered by `tag_id IN (...)` with an embedded `users(phone_number)` join, de-duplicated in Python (no full-table pull, per the checklist's join/RPC preference); (2) one `applications` row with `status = 'available'` is created per match; (3) the New Match Notification is sent per match through one named function, `whatsapp.py:send_new_match_notification()` (free-form interactive for now, with the code comment marking it as the single swap point to the pre-approved template once Meta review clears - `6-Platform-Constraints.md` Section 1); (4) returns the match count only (never names) so the poster can be told how many students were reached, per the Section 4 privacy rule. Wired at both trigger points in `poster_flow.py` (direct-post success path and admin post-approval path), each wrapped so a matching/notify failure can never undo a successful post or leave the poster without a reply. Verified live against Supabase with three temporary tagged users (two matching the opportunity's tag, one tagged only with a non-matching tag) plus untagged-opportunity and nonexistent-opportunity edge cases: exactly 2 matched, no false positives/negatives, every created row `status='available'`, and the real Graph API send returned HTTP 200. All temporary fixtures were deleted afterwards (0 leftovers).
- **Phase I (Core Button Handlers): COMPLETE and verified.** Built `application_flow.py` -- the `(status, action)` dispatch is a dict (`_DISPATCH`) per `2-Architecture-Doc.md` Section 3B, with small single-purpose handlers: Apply Now (`available -> ongoing`, sends the link, `next_reminder_at = now + 2 days`), Remind Me Later (asks for a free-text time and keeps the row `available`; parsed by `_parse_reminder_time`, which handles relative "in 3 days"/"in 5 hours", absolute "Sept 20"/"20/09"/"20/09/2026", the literal "default", and falls back to +2 days on anything unparseable -- Section 14.2), and Ignore (confirmation first). The reusable Section 13 deletion confirmation (`send_deletion_confirmation` + `handle_deletion_confirmation`) is built once so Never / No / Delete can call it in later phases. The no-response-at-all fallback (Section 5.2) is implemented at row creation in `matching.py` (`next_reminder_at = now + 2 days`), so an untouched match is reminded like a Remind-Me-Later. Wired into `webhook.py` STEP 6 (stateless ids `apply_now_<id>` / `remind_later_<id>` / `ignore_<id>` / `confirm_delete_<id>` / `cancel_delete_<id>`) and STEP 9 (`remind_later` + `awaiting_time` free-text step). Verified against Supabase with temporary fixtures (sends stubbed): 28/28 checks passed -- Apply Now -> `ongoing` + link + ~+2d; Remind Me Later keeps `available`, sets the parsed time (+5h case), clears state, confirms back; Ignore confirms first and deletes only on Confirm while Cancel leaves the row; an unhandled `(status, action)` combo (e.g. ongoing+ignore) is refused without deleting; a missing row and every parser format are handled. All temporary fixtures removed (0 leftovers).
- **Phase J (Ongoing Reminder Cycle): COMPLETE and verified.** Added `send_ongoing_checkin_notification` in `whatsapp.py` -- the recurring "Still working on <title>? Deadline is <date>." message with the 3 buttons (Remind Me Later / Continue App / Finished App; titles abbreviated to fit the 20-char cap). Extended the Phase I `(status, action)` dict with three `ongoing` handlers: Continue Application re-sends the link and leaves the row untouched (Section 6.2); Finished Application moves `ongoing -> under_review` and sets `next_reminder_at` to `result_date + 1 day` when the opportunity has a result date, else `now + 3 days` (Section 6.3); Remind Me Later (ongoing) reuses the free-text time step and additionally accepts the free-text `"never"` keyword, which routes into the same reusable Section 13 deletion confirmation (Confirm deletes, Cancel keeps). "Never" is deliberately a free-text keyword, not a button: Section 0 classifies the time choice as free text and the Section 6 example types `never`; it is honoured only from `ongoing` (from `available`, `never` is unparseable and falls back to +2 days, since Section 5.2 offers no Never option). The check-in sender is the single template swap-point for when Meta approval clears. Note: advancing `next_reminder_at` on send (so a silent check-in defaults to +2 days) is the scheduler's job in Phase L. Verified live against Supabase with temporary fixtures (sends stubbed): 29/29 checks passed, 0 fixture leftovers. Phase K (Under Review -> Outcome) is next per `7-Build-Checklist.md`.
