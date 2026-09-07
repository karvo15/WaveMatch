# WaveMatch — Full Product Logic (Authoritative Spec)

This document describes the complete, exact behavior of the bot. It supersedes any earlier informal description. Every conditional branch is spelled out explicitly — if a case isn't listed here, it should be treated as undefined and flagged for a decision rather than assumed.

> **Stack change note:** backend is Python/FastAPI (see Architecture-Doc.md). Two additions since the earlier build attempt: **Section 0** below is a single lookup table for which interaction type (button / list / free text) each step uses — consult it directly, don't infer the type from reading the sample conversations. **Section 1** now explicitly calls out `conversation_states` tracking at each registration step — this is the fix for the bug where every multi-step flow dead-ended after one button tap (see Architecture-Doc.md Section 3F for why).

---

## 0. Interaction Type Reference

**Consult this table directly when building any step below — don't infer the interaction type from prose or from the sample conversations in Message-Flow-Examples.md.** The underlying rule: **≤3 mutually exclusive discrete choices → buttons. A browsable set of items (could exceed 3) → list, paginated at 10 rows/page per the platform cap. Anything open-ended (names, descriptions, dates, custom text) → free text.**

| Step | Section | Type | Notes |
|---|---|---|---|
| First contact: Student vs Poster | 1.1 | Buttons (2) | mutually exclusive |
| Poster: display name | 1.2 | Free text | open-ended |
| User: interest selection | 1.3 | Free text | 12 options exceeds 10-row list cap; no native multi-select |
| User: edit interests | 1.3.4 | Free text | same as above |
| Main Menu | 2 | Buttons (2) | Available Applications / My Applications — resolved to persistent buttons (not a list) for a single-tap experience |
| My Applications sub-menu | 2 | Buttons (3) | Under Review / Ongoing / Scheduled — exactly 3 |
| Poster: opportunity type | 3 | Free text | open category label |
| Poster: title, description | 3 | Free text | open-ended |
| Poster: tags | 3 | Free text | same reason as user interests |
| Poster: dates, link | 3 | Free text (or calendar picker, Section 14) | open-ended |
| Poster: opportunity confirmation | 3 | Buttons (2) | Confirm & Send / Edit — mutually exclusive |
| New Match Notification | 5 | Buttons (3) | Apply Now / Remind Me Later / Ignore |
| Remind Me Later — time choice | 5.2, 6.1 | Free text (or calendar picker) | open-ended, "default" is a valid free-text reply |
| Ongoing check-in | 6 | Buttons (3) | Remind / Continue / Finished |
| Outcome check | 8 | Buttons (3) | Yes / No / Waiting |
| Manual add: title, description, dates | 9.1 | Free text | open-ended |
| Edit an item | 9.2 | Free text | open-ended |
| Available Applications view | 2 | List | browsable, paginate at 10 |
| My Applications lists (Under Review / Ongoing / Scheduled) | 2 | List | browsable, paginate at 10 |
| Deletion confirmation | 13 | Buttons (2) | Confirm / Cancel — always exactly 2 |
| Admin: approve/reject poster | 12 | Free text | command syntax (`approve P1042`), not a button — admin isn't in the same webhook flow as the poster |
| Admin: post approval | 16 | Buttons (2) | Approve Post / Reject Post |

If a step is ever added that isn't in this table, add it here **before** building it — don't build first and categorize after.

---

## 1. Registration

### 1.1 New contact, first message
When any new phone number messages the bot for the first time, the bot checks `conversation_states` and finds no row — this absence, combined with no existing `users`/`posters` row for that phone number, is what identifies it as a first contact. The bot sends the welcome message asking whether they want to register as a **Poster** or as a **User** (two buttons — see Message-Flow-Examples.md Section 1 for exact wording). This is a one-time fork — a phone number is either a poster or a user, not both, for the MVP.

**State tracking:** no `conversation_states` row is created yet at this point — the welcome message itself requires no state, since there's nothing to track until the user actually picks a role. The row is created **only once the user taps a button**, at the start of Section 1.2 or 1.3 below. See Architecture-Doc.md Section 3F — every step below writes/reads this row; that requirement isn't repeated in every numbered step, but it applies to all of them without exception.

### 1.2 Poster registration
1. User taps **Poster**. Set `current_flow = 'register_poster'`, `current_step = 'awaiting_display_name'`. The poster is asked to provide a **display name** (their own name or their organization's name). This name is shown on every opportunity they post, so users know who's posting.
2. On reply, save the display name into `collected_data`. Once submitted, the poster's record is created with `status = pending`, and the `conversation_states` row for this phone number is **deleted** (the flow is complete — do not leave a stale row behind).
3. The bot sends a WhatsApp message to the **admin's number** (the project owner's personal WhatsApp): *"New poster registration: [display name] wants to join as a poster. Reply 'approve [poster_id]' to confirm, or 'reject [poster_id]' to decline."*
4. The prospective poster is told: *"Thanks! Your registration is pending approval. We'll notify you once it's confirmed."*
5. Until approved, the poster cannot post anything — if they try, the bot replies that they're still pending.
6. Once the admin replies "approve [poster_id]", the poster's status flips to `approved`, and the bot sends them a confirmation message with instructions on how to post.
7. If the admin replies "reject [poster_id]", the poster's status flips to `rejected`, and the bot informs them their request wasn't approved (no further detail required in MVP).

**This is exactly the flow that broke previously:** step 1 sent a message, but nothing recorded that the next free-text reply was "the answer to the display-name question" — so it fell through to a dead end instead of reaching step 2. The `conversation_states` row is what step 2's handler reads to know what it's looking at.

### 1.3 User registration
1. User taps **User**. Set `current_flow = 'register_user'`, `current_step = 'awaiting_interests'`. The bot sends a single text message listing all 12 fixed categories (see Section 10.1), and asks the user to reply with their interests as a **comma-separated list** (e.g. "scholarships, tech events, volunteering").
2. The bot parses the reply and matches each term against the fixed list using the layered matching process in Section 10.2 — correctly-typed terms, typos, and alternate phrasings are all resolved automatically; anything unmatched becomes a new custom tag.
3. Once parsed, the user's interest list is saved, the `conversation_states` row is **deleted** (flow complete), and they're shown the Main Menu (Section 2).
4. **Editing interests**: at any time, a user can type/select "Edit my interests" from the Main Menu, which sets `current_flow = 'edit_interests'`, `current_step = 'awaiting_interests'`, re-sends the same category list and free-text prompt, and on reply overwrites the saved interests — then deletes the `conversation_states` row.

---

## 2. Main Menu (User Side)

Once registered, a user always has access to two top-level options, shown as a list message or persistent quick-reply:

- **Available Applications** — opportunities matched to this user's interests that they have not yet acted on (not applied, not ignored).
- **My Applications** — a sub-menu with three lists:
  - **Under Review**
  - **Ongoing**
  - **Scheduled**

Inside **My Applications**, regardless of which sub-list is open, the user always has these additional options available:
- **Add an event/application manually** — for tracking something outside the bot's own postings (see Section 9.1). Entry point is phase-specific — see Section 9.1 for the updated flow.
- **Edit an existing item** — change dates, description, or other details of anything already being tracked (see Section 9.2).
- **Delete an item** — permanently remove a tracked application from any list. This goes through the same confirmation warning as any other deletion trigger (see Section 13).

---

## 3. Poster: Creating an Opportunity

An approved poster taps **Post** (always visible to them once approved), which sets `current_flow = 'post_opportunity'`, `current_step = 'awaiting_type'`, and is walked through providing:

1. **Type** — meeting, volunteering, event, scholarship, or another category label. *(required)*
2. **Title / event name** *(required)*
3. **Description** *(required)*
4. **Tags** — the poster is shown the fixed category list and replies with a comma-separated list of tags, matched using the same layered process as user interests (Section 10.2). *(required — at least one tag)*
5. **Application start date** *(required)*
6. **Application deadline** *(required)*
7. **Result announcement date** *(the only fields a poster may skip, along with #8 — if the poster doesn't know it yet, they can reply "skip")*
8. **Event/program start date** *(skippable, same as #7)*
9. **Application link** *(required)*

Every field except Result Announcement Date and Event/Program Start Date is mandatory — the poster cannot submit the post without providing them.

Once tags are selected, before final submission, the bot shows the poster: *"This will be sent to approximately N students interested in [tag(s)]."* — a **count only**, never a list of names or contacts (privacy).

Once submitted, the bot checks the poster's `requires_post_approval` flag (see Section 16):
- **If `false` (default for trusted posters):** the opportunity is created with `status = active`, and the **Matching Engine** (Section 4) runs immediately.
- **If `true`:** the opportunity is created with `status = pending_approval`. The Matching Engine does **not** run yet — see Section 16 for the approval step that must happen first.

Either way, once the opportunity row is created, the `conversation_states` row for this poster is deleted — the multi-step posting flow is complete. Each field above (type → title → description → tags → dates → link) is one `current_step` value in sequence; a step's handler must both save the answer into `collected_data` and advance `current_step` to the next field, per Architecture-Doc.md Section 3F — this is a 9-step version of the exact same pattern that broke registration before, so it needs the same discipline applied.

### 3.1 Editing a Post
A poster can edit any of their own posts at any time (same fields as creation).
- Any user who has already interacted with that opportunity (clicked Apply Now or Remind Me Later — i.e., anyone with an `applications` row still in `available` or `ongoing` status linked to it) is sent a notice: *"[Opportunity title] was updated: [what changed, in plain language]."*
- **This notification is mandatory whenever the deadline changes — it must never be skipped or batched silently.** The message must clearly state the new deadline explicitly (e.g., *"The deadline for [Opportunity title] moved to Sept 25."*), not just a generic "was updated" line.
- If the **application_deadline**, **result_date**, or **event_start_date** changed, the corresponding fields on those linked `applications` rows are **automatically updated to match** — the user does not need to do anything.
- If the deadline changed, the `deadline_heads_up_sent` flag is reset to `false`, so the 2-day-before heads-up will correctly re-fire relative to the new date.
- Users who **ignored** the opportunity are not notified of edits (their application row was already deleted).

---

## 4. Matching Engine

Triggered every time a new opportunity is created (and re-evaluated is NOT needed on edits — edits only notify existing matches, per Section 3.1; edits do not re-trigger fresh matching to previously-unmatched users in the MVP).

1. Query all users whose interest tags intersect the opportunity's tags.
2. For each matched user, create an `applications` row with `status = available`.
3. Send each matched user the **New Match Notification** (Section 5).
4. Report the match count back to the poster (count only).

---

## 5. New Match Notification (User Side)

The user receives a message containing the opportunity's title, description, poster name, and deadline, with three buttons:

- **Apply Now**
- **Remind Me Later**
- **Ignore**

### 5.1 Apply Now
- The application link is sent/opened immediately.
- The application's status moves from `available` → `ongoing`.
- `next_reminder_at` is set to **+2 days** from now (default).
- `deadline_heads_up_sent` remains `false` (the heads-up logic runs independently — see Section 7).

### 5.2 Remind Me Later
- The bot asks: *"When should I remind you?"* and offers **both** a free-text option and a **calendar/date-picker option** (see Section 14 for how the picker works and its fallback).
- Accepted free-text formats: **relative** ("in 3 days", "in 5 hours", "in 2 hours"), **absolute dates** ("Sept 20", "20/09", "20/09/2026"), or the word **"default"**.
- If the user provides a valid time/date in any of these formats, `next_reminder_at` is set accordingly.
- If the user replies "default," or doesn't answer within a reasonable window, or provides something the bot can't parse, `next_reminder_at` defaults to **+2 days**.
- The application **stays** in `available` status (the user hasn't applied yet — this only defers when they're reminded to look at it again).
- If the user does not respond to the New Match Notification **at all**, the same default (+2 days) behavior applies automatically, as if they had chosen "Remind Me Later."

### 5.3 Ignore
- Before deleting anything, the bot sends a confirmation warning (see Section 13) — the `applications` row is only deleted after the user confirms.
- Once confirmed, the `applications` row is deleted entirely. The opportunity will not be shown to this user again, even if the poster edits it later.

---

## 6. Ongoing Applications — Reminder Cycle

For any application in `ongoing` status, the bot checks in periodically (subject to the batching rule in Section 7.3) with three buttons:

- **Remind Me Later**
- **Continue Application**
- **Finished Application**

### 6.1 Remind Me Later (from Ongoing)
- The bot offers a time choice (same formats as Section 5.2, including the calendar option) **plus a "Never" option**.
- If a specific time is given, `next_reminder_at` is updated accordingly.
- If no time is given, defaults to **+2 days**.
- If **Never** is selected, the bot first sends a confirmation warning (Section 13). Once confirmed, the `applications` row is deleted — the user will not be reminded about this one again.

### 6.2 Continue Application
- The application link is re-sent/re-opened.
- Status remains `ongoing`.

### 6.3 Finished Application
- Status moves from `ongoing` → `under_review`.
- The bot immediately checks whether the linked opportunity has a `result_date`:
  - If yes, `next_reminder_at` is set to **result_date + 1 day** (this is when the Yes/No/Waiting check will fire — see Section 7).
  - If no, `next_reminder_at` is set to **+3 days** (the recurring check-in interval used when no result date is known).

---

## 7. Deadline, Expiry, and Reminder Scheduling Logic

This logic runs as a **daily scheduled job**, not in response to user actions.

### 7.1 Deadline Heads-Up (one-time, per application)
For any application in `available` or `ongoing` status: if `application_deadline - today == 2 days` AND `deadline_heads_up_sent == false`, send a heads-up message (*"Reminder: [opportunity] deadline is in 2 days."*) and set `deadline_heads_up_sent = true`. This fires exactly once per application unless a poster edit resets the flag (Section 3.1).

### 7.2 Expiry / Auto-Cleanup
For any application still in `available` or `ongoing` status: if `today > application_deadline`, stop all further reminders and **delete the application row**. The user is not chased further for something whose deadline has already passed and was never marked finished.

### 7.3 Reminder Batching (anti-spam rule)
For all applications where `next_reminder_at <= today`, group by `user_id`.
- If a user has **2 or fewer** reminders due today, send all of them.
- If a user has **more than 2** due today, sort those due-today reminders by **nearest `application_deadline`** (soonest deadline first), send only the **top 2**, and push the rest to `next_reminder_at = tomorrow`.
- This re-sorting happens **fresh every day** — an application that got pushed yesterday is not prioritized today just because it's now "more overdue." Only deadline proximity matters in the sort.

### 7.4 Result-Check Pass
For any application in `under_review` status:
- If `next_reminder_at <= today` (which was set either to `result_date + 1 day` or is recurring every 3 days per Section 6.3/7.5), send the **Outcome Check** message (Section 7.5... see below, renumbered as 7.6 for clarity — actually see Section 8 below for outcome handling).

---

## 8. Under Review → Outcome Handling

When an outcome check fires (per Section 7.4), the bot asks: *"Did you hear back on [opportunity]? Have you been picked?"* with three buttons:

- **Yes**
- **No**
- **Waiting**

### 8.1 No
- The bot first sends a confirmation warning (Section 13). Once confirmed, the `applications` row is deleted.

### 8.2 Waiting
- `next_reminder_at` is set to **+3 days** from now, and the same Yes/No/Waiting check will fire again then.

### 8.3 Yes
- The bot checks whether the linked opportunity has an `event_start_date`:
  - **If yes**: the application status moves directly to `scheduled`, and `scheduled_event_date` is set to that date automatically. No further input needed from the user.
  - **If no**: the bot prompts the user to enter the date themselves (*"Great! When does it start?"*). Once provided, status moves to `scheduled` and `scheduled_event_date` is set to what the user entered. The application also becomes visible/editable from the **Scheduled** list in My Applications.

### 8.4 No result_date was ever provided by the poster
If the linked opportunity never had a `result_date` set at all, the recurring check-in (every 3 days, per Section 6.3) continues asking "have you heard back yet?" using the same Yes/No/Waiting flow above, indefinitely until the user answers Yes or No.

---

## 9. Manual Add, Edit & Delete (User Side)

### 9.1 Add an event/application manually
The entry point is **phase-specific, not generic**: the user first opens the specific list they want to add into — **Ongoing**, **Under Review**, or **Scheduled** (not Available — that list is reserved for bot-matched opportunities awaiting a decision, not manual entries). The "Add manually" option lives inside each of those three lists individually.

Because the user opened a specific list first, the bot already knows the target status — it does **not** need to ask "what stage is this at" afterward.

Flow:
1. User taps into, e.g., **Ongoing**, then taps **Add manually** within that list.
2. Bot asks for: title, description (optional), and whichever dates are relevant to that stage (e.g., deadline for Ongoing; result date for Under Review; event date for Scheduled).
3. This creates an `applications` row with `opportunity_id = null`, `custom_title` set to what they entered, and `status` pre-set to match the list they opened from (`ongoing`, `under_review`, or `scheduled`).

### 9.2 Edit an existing tracked item
Applies to items in any status (Available, Ongoing, Under Review, Scheduled) and to both poster-sourced and manually-added items.
- The user can change dates, description, or other editable fields.
- Editing a manually-added item is unrestricted (it's their own data).
- Editing a poster-sourced item only changes the user's **personal tracking copy** — it does not modify the poster's original opportunity record.

### 9.3 Delete an item
Available from any list in My Applications, for any item (poster-sourced or manually-added), in any status. Goes through the standard confirmation warning (Section 13) before the row is actually removed.

---

## 10. Tag System

### 10.1 Fixed tags (starter list)
See the 12-category list in the Product Plan document. Both posters (when creating a post) and users (when registering or editing interests) are shown this same fixed list as plain text, and reply with a comma-separated list of the ones that apply (see Section 1.3 and Section 3).

### 10.2 Matching a typed term to a tag (layered process)
Free text is inherently messier than tapping a list, so every term the user types goes through this sequence before falling back to "custom":

1. **Normalize** — lowercase, trim whitespace, strip trailing punctuation.
2. **Exact match** against the normalized fixed list.
3. **Substring/keyword match** — e.g. "hackathon" matches "Competitions / Hackathons" because it's contained within it.
4. **Fuzzy match** — using a lightweight edit-distance library (e.g. Python's `rapidfuzz`, preferred for speed, or the simpler `thefuzz`), catching genuine typos like "scholarshp" or "voluteering" within a small distance threshold.
5. **Alias dictionary** — a short, manually maintained list of alternate words that aren't typos but mean the same thing (e.g. "job" → Job Opportunities, "grant" → Grants / Funding, "intern" → Internships, "comp" → Competitions / Hackathons), for cases fuzzy matching can't catch since the words aren't spelled similarly.
6. **Fallback: custom tag** — if nothing above matches confidently, the typed term is stored as a new tag with `is_custom = true`, using the lowercased, trimmed text as its name.

### 10.3 Deduplication
A nightly job compares custom tags for near-duplicates (e.g., "Volunteering" vs. "volunteer" vs. "Volunteer work") and merges them into a single canonical tag, re-pointing any users/opportunities that referenced the duplicate. This is a safety net for anything that still slips past the layered matching in 10.2 — prevents matching from silently breaking due to inconsistent tag naming over time.

---

## 11. Free Text vs. Buttons — Where Each Applies

**Buttons only** (no free text expected or parsed) govern every core lifecycle transition: Apply Now / Remind Me Later / Ignore, Continue / Finished / Remind Again / Never, Yes / No / Waiting, and Confirm / Cancel (Section 13). If a user sends free text while the bot is expecting one of these button responses, the bot should reply with a gentle fallback re-showing the relevant buttons, rather than trying to interpret the text.

**Free text is expected** at these specific points:
- Interest/tag selection, for both users and posters — a comma-separated reply to the fixed category list (Section 10)
- Providing a custom reminder time (unless using the calendar picker option — Section 14)
- Manually adding a personal event/application (title, description, dates)
- Editing an existing tracked item
- Entering an event start date (when a poster didn't provide one and the user was accepted) — unless using the calendar picker
- All fields when a poster is creating or editing an opportunity (title, description, dates, link) — dates may use the calendar picker where available
- Poster/organization display name at registration

---

## 12. Admin Role

- The admin is a single fixed WhatsApp number (the project owner's personal number for the MVP).
- The admin approves/rejects **poster registrations** via a simple reply command (`approve [poster_id]` / `reject [poster_id]`) sent from their regular WhatsApp.
- The admin can also toggle **per-post approval** on or off for individual posters (Section 16), and approve/reject individual posts when that toggle is on.
- No separate dashboard or web interface is required for any of this — it stays entirely inside WhatsApp, consistent with the product's overall interface philosophy.

---

## 13. Deletion Confirmations (applies everywhere a row can be deleted)

**Any action that would delete an `applications` row must first show a confirmation warning and wait for the user to confirm before actually deleting.** This applies uniformly to:
- **Ignore** (Section 5.3)
- **Never** (Section 6.1)
- **No** (Section 8.1)
- **Delete** from My Applications (Section 9.3)

**Pattern:**
1. User triggers a delete-causing action.
2. Bot replies: *"Are you sure? This will remove [item title] from your list and can't be undone."* with two buttons: **[Confirm]** / **[Cancel]**.
3. **Confirm** → the row is deleted, bot sends a short acknowledgment.
4. **Cancel** → nothing changes, the application stays exactly as it was (still in its prior status, e.g. still `available` if it was an Ignore attempt).

This is a single reusable confirmation step, not four separate implementations — build it once and call it from every deletion trigger.

---

## 14. Date & Time Input Handling

Anywhere the bot needs a date or time from a user or poster — custom reminder times (Section 5.2, 6.1), opportunity dates during posting (Section 3), manual add dates (Section 9.1), entering an event start date after acceptance (Section 8.3), editing dates (Section 3.1, 9.2) — the same input approach applies:

1. **Preferred: a calendar/date-picker.** If feasible within the build timeline, offer this via a **WhatsApp Flow** (Meta's native in-chat form/UI system, which supports a date-picker form component — see Platform-Constraints.md). This gives a tap-to-select calendar instead of free typing.
2. **Fallback / MVP-safe: free-text parsing.** Since Flows are a heavier build, the bot must also accept and correctly parse typed input in multiple formats:
   - Relative: "in 3 days", "in 5 hours", "in 2 days"
   - Absolute dates: "Sept 20", "20/09", "20/09/2026", "Sept 20 2026"
   - The bot should confirm back what it understood (e.g., *"Got it — Sept 20, 2026."*) so the user can catch a misparse before it's saved.
3. If the calendar picker isn't built in time for the demo, free-text parsing alone is an acceptable MVP substitute — the picker is a polish layer, not a hard requirement for the core flows to function.

---

## 15. ID Assignment

Every table (`users`, `posters`, `opportunities`, `applications`, `tags`) uses a **UUID primary key, auto-generated by the database** (`gen_random_uuid()` in Postgres — see Data-Schema.sql). This guarantees no two records ever share an ID, without needing any manual counter or sequence logic — collisions are effectively impossible by design. No additional ID-management logic needs to be built; this is handled entirely at the schema level.

---

## 16. Per-Post Admin Approval (toggle, per poster)

In addition to the one-time **poster registration approval** (Section 1.2), the admin can optionally require **every individual post** from a specific poster to be reviewed before it goes out to matched users.

- Each poster has a `requires_post_approval` flag, **default `false`**.
- The admin can turn this **on** for a specific poster — intended for posters who were approved at registration but whom the admin doesn't yet have full confidence in (e.g., a new officer, an outside organization with limited track record).
- **When `false` (default):** a new or edited post goes live immediately (per Section 3/3.1) — no extra step.
- **When `true`:**
  1. A submitted post is created with `status = pending_approval` instead of `active`.
  2. The admin receives a preview message with the full post content and two buttons: **[Approve Post]** / **[Reject Post]**.
  3. **Approve** → status flips to `active`, and the Matching Engine (Section 4) runs, exactly as if approval hadn't been required.
  4. **Reject** → the poster is notified their post wasn't approved; the opportunity is not sent to any users.
- This toggle is set by the admin directly (e.g., a command like `require_approval [poster_id] on` / `require_approval [poster_id] off`) — not something the poster can set for themselves.
