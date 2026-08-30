# WaveMatch — Project Memory for Claude Code

Read this file at the start of every session, and re-read it after any `/compact` or `/clear` — it is the one thing guaranteed to survive context compaction, since it's loaded fresh from disk rather than carried in conversation history.

## What this project is
A WhatsApp bot (Python/FastAPI backend, Supabase/Postgres, Meta WhatsApp Cloud API, hosted on Render) that matches students to opportunities (scholarships, bootcamps, events) and tracks each one through a lifecycle: **Available → Ongoing → Under Review → Scheduled**. Built for the IEEE ComSoc Student Competition, piloting with the IEEE IAS Student Branch Chapter at UR-CST.

## Stack (do not deviate without flagging it first)
Python 3.11+, FastAPI, Uvicorn, `supabase-py`, `httpx` (async), Pydantic, APScheduler, `rapidfuzz`. Hosted on Render. Database is Supabase/Postgres, schema in `5-Data-Schema.sql`.

## Meta/WhatsApp setup status
Already complete — registered phone number, System User access token, message templates, app/WABA publication, privacy policy. Do not suggest or ask about any of this as a setup task. The one thing that remains a live, moment-to-moment concern (not a setup task) is the 24-hour messaging window (`6-Platform-Constraints.md` Section 1): a free-form message test will fail if the test number hasn't messaged the bot's business number recently enough for the session to be open. If a live test of a message-sending function fails, check whether the error is specifically the "outside 24-hour window" error before treating it as a code bug.

## The docs — read these, don't reconstruct from memory
1. `0-Problem-Statement-and-Solution.md` — why
2. `1-Product-Plan.md` — what, product-level
3. `2-Architecture-Doc.md` — stack + every core logic module, **Section 3F is the conversation state machine, read it fully**
4. `3-Full-Product-Logic.md` — the authoritative spec. **Section 0 is the Interaction Type Reference — the single source of truth for button/list/free-text on every step.**
5. `4-Message-Flow-Examples.md` — exact sample wording/sequence
6. `5-Data-Schema.sql` — full schema, including `conversation_states`
7. `6-Platform-Constraints.md` — hard WhatsApp API limits, webhook signature verification (FastAPI-specific, Section 10.4)
8. `7-Build-Checklist.md` — the exact phase order to follow, don't build ahead of it

## Two rules that override anything that looks "obvious"

**Rule A — Interaction type is a lookup, not a guess.** Check `3-Full-Product-Logic.md` Section 0 before building any interactive step. Don't infer button/list/free-text from a sample conversation. If a step isn't in that table, add it there first, then build it.

**Rule B — Every multi-step flow persists and advances `conversation_states`.** Registration, posting, editing, and manual-add are all multi-turn conversations spread across separate webhook calls. Use the shared `get_conversation_state()` / `set_conversation_state()` / `clear_conversation_state()` functions — no flow invents its own tracking. A step handler is incomplete unless it either (a) saves the answer + advances `current_step`, or (b) clears the row because the flow is done. This exact failure (a handler that replies but doesn't advance state) caused every multi-step flow to silently dead-end in an earlier build attempt — it must not happen again.

**Resolved decisions, not open questions:** Main Menu uses persistent buttons (not a list). Scheduler uses in-process APScheduler (not a Render Cron Job) for this build.

## Working discipline
- Follow `7-Build-Checklist.md` phase by phase. Complete and get one phase tested before starting the next — don't build several phases in one pass.
- Within a phase, build the smallest testable slice, say how to test it, then stop and wait.
- If code you're about to write would contradict a doc, stop and flag the conflict — don't silently resolve it either direction.
- Don't introduce a new library, pattern, or architectural choice not already named in `2-Architecture-Doc.md` without flagging it first.
- If anything in the docs is ambiguous or contradictory, say so explicitly rather than guessing — this has caught real bugs in this project already (see the conversation_states timing fix in `3-Full-Product-Logic.md` Section 1.1).

## Phase workflow (applies to every phase, automatically — don't wait to be told this each time)
Follow this exact sequence for every phase in `7-Build-Checklist.md`, no exceptions:
1. **Confirm the prior phase's status** before starting a new one.
2. **Write and show your implementation plan first** — files to be created/changed, function signatures, how each piece will be tested — and **wait for explicit approval before writing any code.** Do not start coding on your own initiative just because a phase was mentioned.
3. **Re-read the specific doc sections relevant to this phase fresh from disk** before planning — don't rely on a summary from earlier in the session, especially after a `/compact`.
4. Build the smallest testable slice, working through the phase's tasks in order.
5. **Before reporting a phase done, be explicit about how each claim was verified**, not just that it was: state plainly whether something was actually tested live (e.g. a real message sent to a real number, a real deployed endpoint hit) versus only written/reviewed without a live test. Show actual output (real responses, real file contents, real line numbers from the file you just read) rather than a description of expected output. If reporting on code you wrote, quote the actual current file content for anything you make a specific claim about (e.g. "the enum is defined at line X") rather than reconstructing it from memory of writing it earlier in the session.
6. **State explicitly whether any existing file was touched**, and list exactly which new files were created and where.
7. **Stop and wait** — don't move to the next phase without being told to, even if the current one looks complete to you.

This sequence exists because of two real incidents in this project: a multi-step flow that silently dead-ended because a handler reported "done" without actually advancing state (see Rule B), and a phase report that confidently gave specific line numbers for code that turned out not to match the real file. Both were caught by asking "how do you know, and can you show me the real thing" — apply that standard to your own reporting before it's asked of you.


`max` burns through context faster than lower effort levels, so compaction happens more often here than usual. Practical implications:
- At the end of every completed, tested phase, prefer running `/compact` proactively rather than waiting for it to trigger automatically — compacting at a clean phase boundary preserves a much better summary than compacting mid-debug.
- This file is your anchor after any compaction or `/clear` — if something feels uncertain about project rules after a context reset, re-read this file and the relevant doc section before proceeding, rather than reconstructing the rule from a compacted summary.
