# WaveMatch — Build Checklist (Python / FastAPI)

Small, sequential, individually-testable steps. Each step should be verifiable before moving to the next — avoid building multiple layers at once without testing in between, since that makes it hard to isolate where something breaks. **This discipline matters more, not less, in a fresh language** — verify each phase actually works before starting the next one, rather than trusting that a large chunk of freshly-written code is correct.

> **Stack change note:** rewritten for Python/FastAPI (see Architecture-Doc.md). Two fixes from the earlier build are now built into the phases below rather than left implicit: **Phase B** includes the `conversation_states` table (fixes the registration dead-end bug), and **Phase E** explicitly requires every multi-step flow to read/write it. **Phase F0** requires consulting the Interaction Type Reference (Full-Product-Logic.md Section 0) before building any interactive step, rather than inferring button/list/free-text from prose.

---

## Phase A — Foundation

- [ ] Create a Python virtual environment (`python -m venv venv`) inside the existing GitHub repo, activate it
- [ ] Initialize `requirements.txt` (or `pyproject.toml`) with pinned versions: `fastapi`, `uvicorn`, `supabase`, `httpx`, `pydantic`, `apscheduler`, `rapidfuzz`, `python-dotenv`
- [ ] Add `.env.example` listing required variable **names** only (no values) — see Platform-Constraints.md for what's needed (Meta credentials, Supabase credentials, admin phone number, app secret)
- [ ] Add `.gitignore` confirmation — verify `.env`, `venv/`, and `__pycache__/` are excluded
- [ ] Build a basic health-check route (`GET /`) returning a 200 status via FastAPI — deploy this alone to Render as a Python web service first (`uvicorn main:app --host 0.0.0.0 --port $PORT`), confirm it's reachable at the public URL before building anything else
- [ ] Set up the Supabase client in the backend using `supabase-py` and the service_role key, and run one simple test query (e.g., `SELECT * FROM tags`) to confirm the connection works end-to-end

## Phase B — Database

- [ ] Run the full schema (Data-Schema.sql — now includes the `conversation_states` table) in the Supabase SQL Editor
- [ ] Confirm all tables were created correctly, including `conversation_states` (check the Supabase Table Editor)
- [ ] Confirm the seed data (12 starter tags) inserted correctly
- [ ] Write and test one insert + one select for each core table (`users`, `posters`, `opportunities`, `applications`, `conversation_states`) directly via a temporary script, to confirm the schema behaves as expected before building real logic on top of it
- [ ] Define a Pydantic model per table in `models.py` (or a `models/` package) — mirrors each schema table 1:1, so every function that touches a row is working with a typed object rather than a raw dict

## Phase C — WhatsApp Connection

- [ ] Build a reusable `async def send_whatsapp_message()` function wrapping the Graph API call via `httpx.AsyncClient` (reuse the exact request structure already confirmed working via Postman)
- [ ] Build a reusable `async def send_whatsapp_buttons()` function for interactive quick-reply messages (max 3 buttons)
- [ ] Build a reusable `async def send_whatsapp_list_message()` function for list-based menus
- [ ] Test all three by sending to your own confirmed-working number directly, outside any webhook logic yet — just prove the send-functions work in code, not only in Postman

## Phase D — Webhook Receiving

- [ ] Build the webhook verification route (`GET /webhook`) to handle Meta's one-time handshake challenge
- [ ] Configure this webhook URL in the Meta dashboard, confirm the handshake succeeds
- [ ] Build the webhook receiver route (`POST /webhook`), and initially just log the raw incoming payload to confirm messages/button clicks are actually arriving
- [ ] Add webhook signature verification per Platform-Constraints.md Section 10.4 (FastAPI version): read `await request.body()` first, verify via `hmac.compare_digest`, **then** parse JSON from those same raw bytes — confirm it correctly validates genuine requests and rejects tampered ones

## Phase E — Conversation State Machine (build before any multi-step flow)

*This phase didn't exist in the original checklist — it's the direct fix for the registration dead-end bug, and every later flow (registration, posting, manual add, editing) depends on it. Build and test it in isolation before Phase F.*

- [ ] Build `get_conversation_state(phone_number)`, `set_conversation_state(phone_number, flow, step, data)`, and `clear_conversation_state(phone_number)` as shared functions — every multi-step flow calls these, none invent their own tracking
- [ ] In the webhook receiver, add the dispatch rule as the **first** thing that happens after signature verification: look up `conversation_states` by phone number; a row present routes to that flow's step handler, no row present routes to top-level menu/button handling
- [ ] Build the "cancel" escape hatch (typing "cancel" or "menu" at any step clears state and returns to the main menu)
- [ ] Test in isolation with a fake 3-step flow (no real registration logic yet) — confirm state persists correctly across two separate simulated webhook calls, and confirm it survives a manual process restart (proves it's really in Supabase, not memory)

## Phase F0 — Interaction Type Pass (before building any single step)

- [ ] Before writing any step's handler, look it up in Full-Product-Logic.md Section 0 (Interaction Type Reference) and confirm the interaction type (buttons / list / free text) rather than inferring it from the sample conversation
- [ ] If a step is ever needed that isn't in that table, add it to the table first, then build it

## Phase F — Registration Flows

- [ ] Build the first-contact fork (Poster vs. User) — new phone number gets asked which they are; on tap, call `set_conversation_state(...)` per Full-Product-Logic.md Section 1.1
- [ ] Build poster registration: `awaiting_display_name` step reads state, on reply creates the `posters` row (`status = pending`), clears state, sends admin notification
- [ ] Build the admin approval command handler (`approve [id]` / `reject [id]` parsing from the admin's own number) — this one is free text/command syntax, not a button, per the Interaction Type Reference
- [ ] Build user registration: send fixed-category text list, parse comma-separated reply via layered matching (exact → keyword → fuzzy via `rapidfuzz` → alias dictionary → custom tag fallback), create `users` row and populate `user_tags`, clear state
- [ ] Test the full registration flow live, for both a poster and a user, end to end — **specifically confirm that after tapping the first button, the next message is correctly routed as an answer to the follow-up question**, not dropped (this is the exact bug being fixed)

## Phase G — Poster Posting Flow

- [ ] Build the step-by-step opportunity creation conversation (type → title → description → tags [free-text, same layered matching as user registration] → dates → link), matching Message-Flow-Examples.md — each field transition reads and writes `conversation_states` per Full-Product-Logic.md Section 3
- [ ] Build the "approximately N students" count-back-to-poster step before final confirmation
- [ ] Build opportunity creation in the database, including populating `opportunity_tags`, and clear the conversation state on completion
- [ ] Build the poster edit flow (re-walks the same fields, updates the existing row)
- [ ] Test end to end: confirm every intermediate step correctly advances (not just the first one) — same dead-end risk as registration, now a 9-step version of it

## Phase H — Matching Engine

- [ ] Build the matching query (users whose tags intersect the new opportunity's tags) — prefer a Postgres-side join/RPC over pulling all users into Python and filtering in memory
- [ ] Build automatic `applications` row creation (`status = available`) for each match
- [ ] Trigger the New Match Notification send for each matched user
- [ ] Test with at least 2-3 real tagged users to confirm matching is accurate (no false positives/negatives)

## Phase I — Core Button Handlers (Available → Ongoing)

- [ ] Handle **Apply Now**: open link, update status to `ongoing`, set `next_reminder_at = +2 days`
- [ ] Handle **Remind Me Later** (from Available): parse custom time or default to +2 days, keep status `available`
- [ ] Handle **Ignore**: confirmation warning first (Section 13), then delete the `applications` row
- [ ] Handle no-response-at-all fallback (defaults to Remind Me Later behavior)
- [ ] Implement the button/free-text dispatch as a dict of `(status, action): handler` or a Python `match` statement — not nested `if/elif` — per Architecture-Doc.md Section 3B

## Phase J — Ongoing Reminder Cycle

- [ ] Build the recurring Ongoing check-in message + 3 buttons
- [ ] Handle **Continue Application**: re-send link, status unchanged
- [ ] Handle **Finished Application**: move to `under_review`, set `next_reminder_at` based on whether `result_date` exists
- [ ] Handle **Remind Me Later** (from Ongoing), including the **Never** sub-option (confirmation first, then delete)

## Phase K — Under Review → Outcome

- [ ] Build the Yes/No/Waiting outcome check message
- [ ] Handle **No**: confirmation first, then delete the row
- [ ] Handle **Waiting**: set `next_reminder_at = +3 days`
- [ ] Handle **Yes** with known `event_start_date`: auto-move to `scheduled`
- [ ] Handle **Yes** with unknown `event_start_date`: prompt user for the date (free text/calendar picker), then move to `scheduled`

## Phase L — Daily Scheduler

- [ ] Register an APScheduler daily job on FastAPI startup (see Architecture-Doc.md Section 3C for the APScheduler-vs-Render-Cron tradeoff already decided)
- [ ] Implement the Deadline Heads-Up pass (2 days before, one-time per application)
- [ ] Implement the Expiry/Auto-Cleanup pass (delete unfinished applications past their deadline)
- [ ] Implement the Reminder Batching pass (max 2/day per user, sorted by nearest deadline, re-sorted fresh each day)
- [ ] Implement the Result-Check pass (fires outcome checks per Phase K logic)
- [ ] Test the scheduler manually (call the job function directly, on-demand, from a temporary route or script) before relying on actual APScheduler timing

## Phase M — Edit Propagation & Manual Tracking

- [ ] Build poster edit → affected-user notification logic (mandatory, explicit deadline-change wording per Full-Product-Logic.md Section 3.1)
- [ ] Build automatic date sync on linked `applications` when a poster edits dates, including resetting `deadline_heads_up_sent` if the deadline changed
- [ ] Build the user-facing "Add manually" flow (Section 9.1) — phase-specific entry point (opened from within Ongoing/Under Review/Scheduled), tracked via `conversation_states` like any other multi-step flow
- [ ] Build the user-facing "Edit an item" flow (Section 9.2)

## Phase N — List Views & Tag Dedup

- [ ] Build the Available Applications list view — **paginate if it could exceed 10 items** (9 items + "More →" row); keep item titles under 24 characters
- [ ] Build the My Applications sub-menu (Under Review / Ongoing / Scheduled) as list views — same 10-row/24-char constraints apply
- [ ] Build the fuzzy-match + alias-dictionary matching function using `rapidfuzz` (shared by both user interest parsing and poster tag parsing — build once, call from both)
- [ ] Build the nightly tag-dedup job (can reuse the same APScheduler instance from Phase L, registered as a second job)

## Phase O — Deploy & Real-World Test

- [ ] Deploy the finished backend to Render as a Python web service, confirm the webhook URL is correctly pointed at the live deployment (not localhost)
- [ ] Full manual walkthrough: register as a poster, register as a user, post an opportunity, receive and act on the match notification, move through the full lifecycle to Scheduled — **pay specific attention to every multi-step flow correctly advancing past its first step**
- [ ] Recruit 2-3 real IEEE IAS officers as posters and a handful of chapter members as test users
- [ ] Monitor real usage for a few days to gather genuine data (registrations, matches, applies, completions) for the competition submission

## Phase P — Submission Prep (parallel, not sequential — start early)

- [ ] Draft and submit the 5 message templates for Meta approval (do this as early as possible, in parallel with Phase C-D, since approval isn't instant)
- [ ] Collect real usage screenshots/data once Phase O testing has run for a few days
- [ ] Record the demo video
- [ ] Write the final competition submission using the Problem Statement, Product Plan, and real usage data
