# WaveMatch - Build Process (the 5-Step Building Plan)

> **Origin note:** the 5-step plan is not written in any single repo file, so this
> document records it once, consolidated from how Phases A-G were actually executed
> per `7-Build-Checklist.md` and the per-phase records in `CLAUDE.md`. Review the
> steps below and adjust if any is phrased differently than intended - after that,
> this file is the authoritative copy.

## The 5 steps (applied to every phase)

1. **Scope from the build checklist.** Read the current phase section in
   `7-Build-Checklist.md` and enumerate its exact deliverable items. Do not invent
   scope beyond the checklist; work in small, sequential, individually-testable steps.

2. **Consult the source-of-truth docs BEFORE writing code (the F0 pass).** For every
   interactive step, message, and schema touchpoint in the phase, check
   `3-Full-Product-Logic.md` (especially Section 0 - the Interaction Type Reference -
   plus the phase's own section), `4-Message-Flow-Examples.md`, `5-Data-Schema.sql`,
   and `6-Platform-Constraints.md`. Confirm buttons vs lists vs free text and exact
   wording/rules rather than inferring them. If a phase needs an interaction type not
   already in Section 0, add it to that table first, then build it.

3. **Implement in small, verifiable increments.** Build the phase's handlers/modules
   following the established conventions: async throughout; every DB call wrapped in
   the shared `_db_semaphore`; every multi-step flow driven through
   `conversation_states` (no ad-hoc tracking); fully-qualified cross-module calls;
   real WhatsApp button/list payload shapes; respect signature verification, message-ID
   dedup, the phone-number guard, and the cancel/menu escape hatch. Prefer new files
   for new subsystems; make minimal, surgical edits to existing files.

4. **Verify honestly before declaring anything done.** Run `python -m py_compile` on
   every touched file; review via direct full-file reads (not summaries or self-
   reports); run the phase's targeted tests (unit, simulated webhook, and real/live
   where available); confirm every intermediate step advances (not just the first) and
   that both branches of any flag behave (e.g. `requires_post_approval` true/false);
   fix each real bug found before moving on.

5. **Close out: update docs, commit, tag, push.** Tick the phase's boxes in
   `7-Build-Checklist.md`; update the "Current progress" section of `CLAUDE.md`
   (status, real bugs found/fixed, stable-tag note) and move the current-phase banner;
   update `3-Full-Product-Logic.md` / `5-Data-Schema.sql` if the phase changed
   interaction types or schema; commit and push; cut a stable git tag for the phase
   (e.g. `v1-phase-e-stable`, `v3-hotfix-http2-concurrency`).

## Ground rules that reinforce the 5 steps

- Verify each phase actually works before starting the next (per `7-Build-Checklist.md`).
- Never trust a large chunk of fresh code as correct; isolate where something breaks.
- New Meta-approvable message templates get drafted/submitted as early as possible, in
  parallel with other work, never at the end.
