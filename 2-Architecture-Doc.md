# WaveMatch — Technical Architecture (Python / FastAPI)

> **Stack change note:** this project originally planned a Node.js/Express backend. It has been switched to **Python/FastAPI** — the developer knows Python better than Node, and earlier Node.js development produced messy, hard-to-verify fixes. Every module below keeps the exact same *logic* as the original design (matching engine, state machine, scheduler) — only the implementation language and its idioms change. Nothing about WhatsApp, Supabase, or the database schema changes.

---

## 1. High-Level Architecture

```
WhatsApp User/Poster
       |
       v
WhatsApp Cloud API (Meta)  <-- messaging interface only
       |
       v
Backend Server (Python / FastAPI, served by Uvicorn)
   - Webhook handler (incoming messages/button clicks)
   - Matching engine (tags -> users)
   - State machine (application lifecycle)
   - Scheduler (reminders, deadline checks, batching)
       |
       v
Database (Postgres via Supabase)
   - Users, Posters, Opportunities, Applications, Tags
       |
   Admin approval (poster approval) -- a simple WhatsApp
   command to admin's own number for MVP, no separate
   dashboard needed
```

**Stack — confirmed and locked in:**
- Messaging: Meta WhatsApp Cloud API, on the real registered phone number already set up (see Platform-Constraints.md — unchanged, this is a Meta-side concern, not a language concern).
- Backend: **Python 3.11+, FastAPI**, served by **Uvicorn** (the ASGI server FastAPI needs to actually run — FastAPI defines the app, Uvicorn is what listens on a port and serves it).
- Database client: **`supabase-py`** (the Python equivalent of `supabase-js` — same Supabase project, same URL, same `service_role` key, same schema).
- Validation: **Pydantic** — every incoming webhook payload and every outgoing message gets a Pydantic model, so malformed data fails loudly at the boundary instead of causing a confusing crash three functions deep.
- HTTP calls out to the Graph API: **`httpx`** (async-friendly; use `AsyncClient`, not `requests`, so calls to Meta don't block the event loop while a webhook is also trying to come in).
- Scheduler: **APScheduler** running inside the same FastAPI process (or a Render Cron Job hitting a protected `/internal/run-scheduler` endpoint — see Section 5 for the tradeoff), replacing the originally-planned Node cron job.
- Hosting: **Render**, free tier — unchanged.

### Why this combination, in plain terms
- FastAPI is **async by default**, which matches this bot's actual shape well: a webhook POST arrives, you need to respond to Meta fast, then do slower work (DB writes, matching, sending replies) without blocking the next incoming webhook. `async def` route handlers are the right tool for that — but see Section 6 for the one thing to get right early (don't `await` a blocking call inside an async function, or you lose the benefit entirely).
- Pydantic gives you **typed, validated data structures** instead of raw dicts. This directly targets the "messy code, new bugs introduced while fixing old ones" problem from the Node attempt — if a field is missing or the wrong type, Pydantic raises a clear error at the edge of the system, not a silent `undefined`/`None` bug two layers deep.
- `supabase-py`'s query builder is close to `supabase-js`'s in shape (`.table("applications").select("*").eq("status", "ongoing").execute()`), so the mental model from the schema doc carries over directly.

---

## 2. Data Model

**One structural addition, otherwise no changes:** a new `conversation_states` table has been added to track multi-step flows (see Section 3F below — this is the fix for the registration dead-end bug from the earlier build). Beyond that, the authoritative schema is still **Data-Schema.sql** — it is pure SQL and Postgres, and doesn't know or care what language is querying it. Run it in Supabase's SQL Editor exactly as before. The quick-reference tables in the original architecture doc (`users`, `posters`, `tags`, `opportunities`, `applications`) still apply as a mental model; treat Data-Schema.sql as the source of truth for actual field names/types.

**One Python-specific addition:** mirror every table with a **Pydantic model** in a `models.py` (or a `models/` package) — e.g. `class Application(BaseModel): id: UUID; user_id: UUID; status: ApplicationStatus; ...`. This isn't required by Supabase, but it means every function that touches an `applications` row is working with a typed object, not a raw dict pulled out of a JSON response — which is what makes bugs visible immediately instead of three function calls later.

---

## 3. Core Logic Modules

The four modules are logically identical to the original design. What follows is the same logic, described in FastAPI/Python terms, plus the specific concept each module needs Claude Code to get right.

### A. Matching Engine
- Triggered when a poster creates a new opportunity (an `async def` function, not a route handler itself — called *from* the poster-flow route once an opportunity is confirmed).
- Query: users whose `user_tags` intersect the opportunity's `opportunity_tags`. In `supabase-py` this is most cleanly done as a Postgres query (a SQL join, or a Postgres function called via `.rpc()`) rather than pulling all users into Python and filtering in memory — let the database do the intersection.
- For each match: create an `applications` row (`status = "available"`), then send the WhatsApp message with the opportunity + 3 buttons.
- Return the **count** of matched users to the poster (never the list of names) — same privacy rule as before.
- **Concept for Claude Code:** this function should be `async def` and should `await` each Supabase call and each outgoing WhatsApp send. If there are many matched users, send in a loop with `await`, not `asyncio.gather` unless you've also handled WhatsApp rate limits — sending 30 messages at once with no throttling is the kind of thing that looks fine in testing and breaks at real scale.

### B. Button/Reply Handler (webhook logic)
Handles every user interaction. Central dispatcher based on `(current_status, button_clicked)` — same table as the original design:

| Current status | Button clicked | Action |
|---|---|---|
| available | Apply Now | status -> ongoing, open link, set next_reminder_at = +2 days |
| available | Remind Me Later | ask for custom time, else default +2 days, stays `available` |
| available | Ignore | delete application row |
| ongoing | Continue Application | re-send link, keep status |
| ongoing | Finished Application | status -> under_review, set reminder logic per result_date rules |
| ongoing | Remind Me Later | offer "Never" option; else +2 days |
| ongoing | Never | delete application row |
| under_review | Yes | if event_start_date known -> status = scheduled, scheduled_event_date set; else prompt user for date -> scheduled |
| under_review | No | delete application row |
| under_review | Waiting | next_reminder_at = +3 days |

- **Concept for Claude Code:** implement this dispatch as a plain Python **dict of `(status, button): handler_function`**, or a `match` statement (Python 3.10+ structural pattern matching) — not a long chain of `if/elif`. A dict/match dispatch is what will keep this readable as more button types get added, and it's the single easiest place for "fixing one bug introduces another" to happen if it's written as nested conditionals instead.
- Each handler function should be small, single-purpose, and independently testable (call it directly with a fake application object in a test, without going through the webhook at all).

### C. Scheduler (runs daily)
1. **Deadline heads-up pass:** find `ongoing`/`available` applications where `application_deadline - today = 2 days` and `deadline_heads_up_sent = false` → send heads-up, set flag true.
2. **Expiry pass:** find applications where `today > application_deadline` and `status != under_review/scheduled` → delete (auto-cleanup).
3. **Reminder pass:** find all applications where `next_reminder_at <= today`.
   - **Batching rule:** group by `user_id`. If more than 2 are due today, sort by nearest `application_deadline`, send the top 2, push the rest to `next_reminder_at = tomorrow`. Re-evaluate this sort fresh each day.
4. **Result-check pass:** find `under_review` applications where `today = result_date + 1 day` (or no result_date and `next_reminder_at <= today`) → send Yes/No/Waiting prompt.

- **Concept for Claude Code — two valid options, pick one deliberately, don't mix them:**
  1. **In-process APScheduler**: add `apscheduler` as a dependency, register a daily job inside the FastAPI app's startup event. Simple, no extra infra — but the job only runs while the app is actually awake, and Render's free tier can spin down an idle service, which could silently skip a day's run.
  2. **Render Cron Job hitting an endpoint**: build a `POST /internal/run-scheduler` route (protected by a shared secret header, not open to the public internet), and configure a Render Cron Job to call it daily. More reliable against spin-down, slightly more setup.
  - Given this project's scale and the Sept 5 deadline, **Option 1 (APScheduler) is the pragmatic choice** — simpler to build and debug — but note the spin-down risk if the free-tier service goes idle for long stretches during testing.

### D. Poster Edit Propagation
- On any edit to an `opportunities` row, find all `applications` linked to it where `status IN (available, ongoing)`.
- Send an "this opportunity was updated" notice to each affected user.
- If `application_deadline`, `result_date`, or `event_start_date` changed, auto-update the corresponding fields on the linked `applications` rows (and reset `deadline_heads_up_sent` if the deadline moved).
- **Concept for Claude Code:** compare old vs. new values *before* writing the update (fetch the existing row first), so you know which fields actually changed and only reset `deadline_heads_up_sent` when the deadline specifically moved — not on every edit.

### E. Admin Poster Approval
- Unchanged: no dashboard needed. New poster registrations get `status = pending`; admin approves via a plain WhatsApp command to the bot from the admin's own number (e.g. `approve P1042`), parsed the same way any other free-text reply is parsed.

### F. Conversation State Machine (new — fixes the registration dead-end bug)
**Why this module exists:** the earlier build attempt had every multi-step flow (registration, posting an opportunity, manual add) silently dead-end after the first button tap — the bot would echo back the user's choice and then go nowhere. The root cause wasn't a webhook bug; it was that **there was no table anywhere recording "this phone number is mid-flow, on step N, here's what's been collected so far."** Every webhook call is a fresh, stateless HTTP request — without persisted state, the handler receiving the *next* message has no way to know it's the answer to "what's your display name?" versus an unrelated stray message.

The fix is the new `conversation_states` table (see Data-Schema.sql):
```
phone_number (PK) | current_flow | current_step | collected_data (JSONB) | updated_at
```

**The rule every handler must follow, with no exceptions:**
1. **On every incoming webhook event** (button tap or free text), look up `conversation_states` by phone number **before** deciding how to handle the message.
   - **Row exists** → the phone number is mid-flow. Route the message to the handler for `(current_flow, current_step)`, not to a generic top-level menu handler.
   - **No row** → the phone number has no active flow. Check whether it already exists in `users` or `posters`:
     - **Not found in either** → this is a first contact. Send the welcome message (Poster vs. User buttons, Full-Product-Logic.md Section 1.1). No `conversation_states` row is created yet — there's nothing to track until they pick a role.
     - **Found in `users` or `posters`** → treat the message as a fresh top-level action for that role (main menu for a user, post/menu options for a poster; or a reply to a button on an already-sent notification, e.g. Apply Now on a match).
2. **Whenever a step handler finishes processing input**, it must do *both* of these, never just one:
   - Persist whatever was just collected into `collected_data` (a JSON merge, not an overwrite of the whole blob).
   - Write the **next** `current_step` and send that next step's prompt — or, if the flow is complete, **delete the row** and create the real `posters`/`users`/`opportunities` row.
   - A handler that sends a reply but doesn't update `current_step` (or delete the row on completion) is exactly the bug from before: the flow looks like it responded, but the next message has nowhere correct to go.
3. **This state lives in Supabase, not in a Python variable/dict in memory.** Render can restart the process at any time; in-memory state would vanish mid-registration and look, from the user's side, like the exact same dead-end bug.
4. **Every flow needs an explicit "cancel" escape hatch** (e.g. typing "cancel" or "menu" at any step deletes the `conversation_states` row and returns to the main menu) — without one, a user who gets confused mid-flow has no way out except waiting for the row to become stale.

**Concept for Claude Code:** build one shared `get_conversation_state(phone_number)` / `set_conversation_state(...)` / `clear_conversation_state(...)` pair of functions, and route *every* multi-step flow through them — don't let individual flows (registration vs. posting vs. manual add) each invent their own ad-hoc way of tracking progress. One state-tracking mechanism, reused everywhere, is what makes this maintainable instead of a re-introduction of the same bug in a new flow later.

---

## 4. Message/UI Components Used

Identical to the original design and to the hard platform limits in Platform-Constraints.md — these are Meta/WhatsApp constraints, not language constraints, so nothing here changes:
- **List Messages** — max 10 rows total, 24-char row titles, 72-char row descriptions, 24-char section titles.
- **Free text with layered matching** — used for all tag/interest selection.
- **Quick Reply Buttons** (max 3, 20-char button text).
- **Rich text formatting**, **optional image cards** — unchanged.

Build each of these as a small, reusable Python function (e.g. `send_buttons(to: str, body: str, buttons: list[Button])`) that wraps an `httpx.AsyncClient` POST to the Graph API — the direct Python equivalent of the `sendWhatsAppMessage()` / `sendWhatsAppButtons()` / `sendWhatsAppListMessage()` functions from the original Node plan.

---

## 5. Build Order

The granular, phase-by-phase order now lives in the (soon to be rewritten) **Build-Checklist.md** — that file will be updated next to reflect Python/FastAPI specifics (virtual environment setup, `requirements.txt` instead of `package.json`, `uvicorn` run commands, etc.) in place of the Node-specific steps. The overall shape (foundation → database → WhatsApp connection → webhook receiving → registration flows → posting flow → matching → button handlers → scheduler → edit propagation → list views → deploy → submission prep) stays the same.

---

## 6. Concepts Claude Code Needs to Get Right (Python/FastAPI-specific)

These are the specific places where a Node-to-Python switch changes *how* something is built, not just *what language* it's built in. Flagging them explicitly so each build phase starts from a correct mental model instead of a half-transplanted Node pattern.

1. **Async all the way down.** If a route handler is `async def`, every I/O call inside it (Supabase queries via `supabase-py`, outgoing HTTP via `httpx`) should also be awaited using async-compatible clients. Mixing in a blocking call (e.g. the synchronous `requests` library, or a synchronous Supabase client method) inside an `async def` route blocks the entire event loop — every other incoming webhook waits behind it. This is the single most common way a FastAPI app becomes mysteriously slow/unresponsive under load.
2. **Raw body vs. parsed body for signature verification.** Same underlying problem as the original Node doc flagged (§10.4 of Platform-Constraints.md), different fix: in FastAPI, read `await request.body()` to get the raw bytes for HMAC signature verification *before* calling `request.json()` (which consumes/parses the body). Grab the raw bytes first, verify the signature against those raw bytes, and only then parse JSON from them.
3. **`requirements.txt` (or `pyproject.toml`) replaces `package.json`.** Pin versions explicitly (`fastapi==0.11x.x`, not a loose range) so a fresh `pip install` months from now doesn't silently pull a breaking newer version right before a deadline.
4. **Virtual environments are not optional.** Every dependency install happens inside a `venv` (or `poetry`/`uv` environment), never globally — this avoids the classic "works on my machine" problem when moving between local dev and Render's build environment.
5. **Pydantic models at every boundary.** Anywhere data crosses a boundary — an incoming webhook payload, a Supabase row, an outgoing message — define a Pydantic model for it. This is the direct fix for the "messy, bug-introducing-more-bugs" problem from the Node attempt: a shape mismatch fails immediately and legibly at the boundary, instead of surfacing as a confusing `None`/`KeyError` deep in unrelated code.
6. **Test each phase in isolation before moving on**, exactly as the Build Checklist already insists — this matters *more*, not less, in a fresh language, since neither you nor Claude Code has the same instinct for "this looks obviously wrong" in Python that you'd eventually build up over time. Small, verified steps compensate for that.

---

## 7. Decisions — Resolved

- **Backend language/framework:** Python 3.11+, FastAPI, served by Uvicorn (changed from Node.js/Express — see stack change note at top).
- **Scheduler approach:** in-process APScheduler for the MVP/demo timeline (see Section 3C for the tradeoff against a Render Cron Job).
- **Messaging provider:** Meta WhatsApp Cloud API, real registered number — unchanged.
- **Hosting:** Render, free tier — unchanged.
- **Database:** Supabase (Postgres), accessed via `supabase-py` — unchanged schema, changed client library only.
- **Starter tag list:** finalized at 12 categories — unchanged, see Product-Plan.md Section 6.
- **Admin-approved posters for the demo:** the project owner (admin) + IEEE IAS chapter officers — unchanged.
