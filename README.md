# WaveMatch

> A WhatsApp bot that matches students to opportunities — and then makes sure they follow through.

Students miss scholarships, internships and bootcamps not because the opportunities don't
exist, but because of how information and personal follow-through work: opportunities are
buried in noisy group chats, there is no external memory that remembers an application was
started, and nothing chases the outcome afterwards. WaveMatch closes that loop **inside
WhatsApp** — no app to install, no new login, no new habit.

---

## What it does

1. **Personalised delivery.** Opportunities are tagged by category. Students pick their
   interests once at registration, and the bot surfaces only what matches — scholarships,
   internships, jobs, grants, competitions, fellowships, volunteering, research, bootcamps
   and networking events.
2. **End-to-end lifecycle tracking.** Every opportunity a student engages with moves through
   a defined lifecycle, and the bot proactively messages at the moments that matter: before
   a deadline, when an application is left unfinished, and after a results date passes.
3. **A curated posting layer.** Approved posters (starting with the IEEE IAS UR-CST chapter)
   post opportunities directly into the bot, which handles matching, notification and
   tracking automatically.

### The application lifecycle

```
   (matched)         Apply Now          Finished App           Yes
available  ──────▶  ongoing  ──────▶  under_review  ──────▶  scheduled
   │                   │                    │
   │                   │                    └─ "Still Waiting" → recheck in 3 days
   │                   └─ Ignore / Never → deletion confirmation → removed
   └─ Ignore → deletion confirmation → removed

  Expiry: available / ongoing rows past their deadline are deleted silently.
          under_review and scheduled are never auto-deleted.
```

---

## Architecture

```
WhatsApp Cloud API ──webhook──▶ FastAPI (main.py)
                                   │
                    ┌──────────────┼───────────────┐
                    ▼              ▼               ▼
              registration.py  poster_flow.py  application_flow.py
              my_applications.py  matching.py   propagation.py
                    │              │               │
                    └──────────────┴───────────────┘
                                   ▼
                            Supabase (Postgres)

  scheduler.py ── driven by two independent clocks ──▶ the four daily passes
                 (in-process APScheduler + Render Cron Job)
```

**Two scheduler drivers, one shared marker.** The service does not stay awake — a free-tier
host sleeps after ~15 idle minutes — so an in-process cron alone silently loses days of
reminders. `scheduler_runs` is a marker table that guarantees exactly one driver performs a
given day's work, and a late boot runs a catch-up pass so a slept-through day is not skipped.

**Two reminder clocks.** Most reminders ride the daily rhythm (`available → +2 days`,
`under_review → result_date + 1`, "Still Waiting" → `+3 days`). A reply naming an explicit
time ("in 1 hour") is marked `reminder_is_exact = true` and served by a separate fine-grained
pass, because a once-a-day job cannot honour "in 1 hour".

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11 (`.python-version`) |
| HTTP | FastAPI + Uvicorn |
| Messaging | WhatsApp Cloud API (Graph API) |
| Database | Supabase (hosted Postgres) |
| Scheduling | APScheduler (in-process) + Render Cron Job |
| Matching | RapidFuzz over tag categories |
| Hosting | Render |

---

## Quick start

```bash
git clone <repo-url>
cd WaveMatch

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

copy .env.example .env         # cp on macOS/Linux
# fill in .env (see the table below)

uvicorn main:app --reload
```

Then:

- `http://127.0.0.1:8000/` → `{"status": "ok", "message": "WaveMatch is running"}`
- `http://127.0.0.1:8000/db-test` → confirms the Supabase connection

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `WHATSAPP_TOKEN` | yes | Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | yes | Sending number's ID (not the display number) |
| `WHATSAPP_BUSINESS_ID` | yes | WhatsApp Business account ID |
| `WHATSAPP_APP_ID` | yes | Meta app ID |
| `WHATSAPP_APP_SECRET` | yes | Verifies inbound webhook signatures (HMAC) |
| `WHATSAPP_VERIFY_TOKEN` | yes | Webhook GET handshake |
| `WHATSAPP_GRAPH_API_VERSION` | yes | e.g. `v21.0` |
| `SUPABASE_URL` | yes | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Server-side key (never ship to a client) |
| `ADMIN_PHONE_NUMBER` | yes | Number allowed to approve/reject posts |
| `SCHEDULER_TZ` | no | Product timezone, default `Africa/Kigali` |
| `SCHEDULER_HOUR` / `SCHEDULER_MINUTE` | no | Daily pass time, default 08:00 |
| `SCHEDULER_ENABLED` | no | Toggle the in-process scheduler |
| `EXACT_REMINDER_ENABLED` | no | Toggle the fine-grained pass |
| `EXACT_REMINDER_INTERVAL_MINUTES` | no | Exact-pass interval, default 10 |
| `INTERNAL_TICK_SECRET` | recommended | Shared secret for the cron endpoint; **unset disables the route** |
| `BOT_DISPLAY_NUMBER` | recommended | The number students dial, for the `/wa` link. Digits only, no `+`. **Not** `WHATSAPP_PHONE_NUMBER_ID`, which is an internal Meta id no client can dial |

---

## HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Liveness check |
| `GET` | `/health` | Health/version detail |
| `GET` | `/db-test` | Supabase connectivity check |
| `GET` | `/webhook` | WhatsApp verification handshake |
| `POST` | `/webhook` | All inbound messages (HMAC-verified) |
| `POST` | `/internal/run-scheduler` | Protected scheduler tick; called by the Render Cron Job |
| `GET` | `/wa` | Click-to-chat redirect to WhatsApp; `?text=` pre-fills the message |

The tick endpoint compares `INTERNAL_TICK_SECRET` in constant time and returns `503` when the
secret is not configured, so it can never be left open as a way to make the bot message people.

```bash
curl -X POST https://<service>.onrender.com/internal/run-scheduler \
     -H "x-tick-secret: $INTERNAL_TICK_SECRET"
```

---

## Chat with the bot

**→ https://wavematch-bot.onrender.com/wa**

That short link 302-redirects to WhatsApp with the message box pre-filled:

```
https://wa.me/250736544482?text=Hi%20WaveMatch
```

It is the link to print on a poster, put in a slide, or paste into a bio. The indirection
earns its keep twice over: the display number can change without reprinting anything, and
WhatsApp reports no attribution at all for `wa.me` traffic, so the `CHAT_LINK_OPENED` log
line is the only click count that will ever exist.

`?text=` overrides the pre-filled message, e.g. `/wa?text=Hi%20from%20the%20IEEE%20poster`.
The visitor still has to press **send** — WhatsApp never sends a pre-filled message on its
own — and that send is what matters: because the **user** initiates, the 24-hour
customer-service window opens and the bot may reply with ordinary free-form messages.

Format, if you ever build the link by hand: digits only, full international format, no `+`,
no spaces, no leading zero.

---

## Project layout

```
main.py              FastAPI app, lifespan, scheduler tick endpoint
webhook.py           Verification, HMAC check, reply-shape normalisation, routing
registration.py      First contact, role selection, poster + user registration
poster_flow.py       Opportunity creation / editing (date parsing, confirmation)
matching.py          Tag matching, New Match Notification dispatch
application_flow.py  Apply Now / Remind Me Later / Ignore / outcome handlers
my_applications.py   Available Apps, My Applications, add-manually, edit
propagation.py       Notifying engaged users when a post is edited
scheduler.py         The four daily passes + the exact-time pass
conversation.py      Conversation state get/set/clear
whatsapp.py          Cloud API senders (single place to swap in templates)
tags.py              Tag categories, fuzzy matching, maintenance
models.py            Pydantic models mirroring the tables
database.py          Supabase client
```

### Verification harnesses

Stubbed and offline where possible, so they never message a real user:

```bash
python verify_reminder_parser.py    # the free-text time parser (offline, 125 checks)
python verify_exact_reminders.py    # flag decision, both scheduler drivers, endpoint (stubbed)
python verify_3step_flow.py         # poster flow + matching + first notification
```

---

## Deployment

Render, one web service plus one cron job:

1. Deploy the web service from this repo; set every variable from the table above
   (`BOT_DISPLAY_NUMBER` included, otherwise `/wa` answers `503`).
2. Run the `MIGRATIONS` block at the bottom of `5-Data-Schema.sql` against Supabase.
3. Add a **Cron Job** every 10 minutes:
   `curl -X POST https://<service>.onrender.com/internal/run-scheduler -H "x-tick-secret: <secret>"`

The cron request also wakes a sleeping service, so it works from cold.

## Project status

**Working and verified:** the full lifecycle, registration and matching, the four daily
passes, the exact-time pass, both scheduler drivers and the marker table, and HMAC webhook
verification — all exercised against real rows.

**Known gaps:**
- Proactive sends are still free-form text. Moving them to approved templates is in progress;
  the reply-shape layer already accepts both tap formats.
- Sends are not batched across users, and there is no click analytics — a click-to-chat link
  is currently unattributable.
- On a free tier the service sleeps; the first message after a sleep can take up to a minute
  to get a reply (Meta retries the webhook, so nothing is lost).

## Documentation

Read in order — each file is written to be the single source of truth for its area:

| File | Contents |
|---|---|
| `0-Problem-Statement-and-Solution.md` | Problem, why existing solutions fail, the solution |
| `1-Product-Plan.md` | Users, flows, scope |
| `2-Architecture-Doc.md` | Components, choices, deployment shape |
| `3-Full-Product-Logic.md` | Every rule, numbered (the executable spec) |
| `4-Message-Flow-Examples.md` | Real message examples for each flow |
| `5-Data-Schema.sql` | Tables, indexes, RLS, migrations |
| `6-Platform-Constraints.md` | WhatsApp API limits and their consequences |
| `7-Build-Checklist.md` | Phase-by-phase build and verification status |
| `8-Build-Process.md` | How the build was approached |
| `9-Message-Templates.md` | Template register for Meta approval |
| `CLAUDE.md` | Engineering log — every phase, decision and defect |