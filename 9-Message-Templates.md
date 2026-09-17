# WaveMatch - Message Template Register

**The authoritative list of every Meta Message Template this product needs, and the code path each one is sent from.**

Templates exist because of one hard platform rule (`6-Platform-Constraints.md` Section 1): a business may only send **free-form** messages within **24 hours of that user's last message**. Every proactive message this bot sends can land outside that window, so it needs a pre-approved template. Replies to something the user just did are *always* in-window and deliberately need no template (Section 5 lists those).

All 11 are submitted as **UTILITY** category, language **en_US**, and each must be approved before it can be sent outside the window.

**Status legend**

| Status | Meaning |
|---|---|
| TO DRAFT | Not yet submitted to Meta. The body shown is the proposed wording, derived from what the code composes today. |
| SUBMITTED | Already in WhatsApp Manager, drafted by the team. The body shown is quoted verbatim. |

There are **11 templates**: the original 5 user-facing ones (Templates 1-5, derived from `3-Full-Product-Logic.md` and `4-Message-Flow-Examples.md`), plus the 6 admin- and poster-facing ones (Templates 7-12). *The team numbering skips 6 - an artefact of an earlier miscount; 1-5 + 7-12 = 11.*

---

## 1. Summary

| # | Template name | Recipient | Params | Buttons | Sent from | Status |
|---|---|---|---|---|---|---|
| 1 | `new_match_notification` | matched user | 5 | 3 quick replies | `whatsapp.py:271` (called from `matching.py:186`, `poster_flow.py:984`, `scheduler.py:330`) | TO DRAFT |
| 2 | `deadline_heads_up` | user tracking it | 2 | none | `whatsapp.py:407` (called from `scheduler.py:270`) | TO DRAFT |
| 3 | `ongoing_checkin` | user, Ongoing | 2 | 3 quick replies | `whatsapp.py:328` (called from `scheduler.py:351`, `my_applications.py:280`) | TO DRAFT |
| 4 | `outcome_check` | user, Under Review | 1 | 3 quick replies | `whatsapp.py:371` (called from `scheduler.py:342`, `my_applications.py:284`) | TO DRAFT |
| 5 | `opportunity_updated` | user tracking it | 3 | none | `whatsapp.py:428` (called from `propagation.py:292`) | TO DRAFT |
| 7 | `poster_registration_pending` | **admin** | 3 | none | `registration.py:135` | SUBMITTED |
| 8 | `poster_approved` | poster | 0 | none | `webhook.py:136` | SUBMITTED |
| 9 | `poster_rejected` | poster | 0 | none | `webhook.py:144` | SUBMITTED |
| 10 | `post_pending_approval` | **admin** | 7 | none | `poster_flow.py:759` | SUBMITTED |
| 11 | `post_approved` | poster | 1 | none | `poster_flow.py:1109` | SUBMITTED |
| 12 | `post_rejected` | poster | 1 | none | `poster_flow.py:1119` | SUBMITTED |

**Why the six are not optional.** Templates 7 and 10 go to the **admin's** personal number, which has its own separate 24-hour window from every poster's - so they need templates for exactly the reason the user-facing ones do. And a poster may register days before the admin acts on it, so 8, 9, 11 and 12 need them too. None of the six can be dropped.

---

## 2. Templates 1-5: user-facing (TO DRAFT)

These are not quoted from anywhere - the code composes them today as free-form interactive messages, and what follows is the proposed template form of each.

**Drafting constraint:** templates have **no conditionals**. Where the code includes a line only sometimes, the template must either always carry it or take it as a parameter that may be sent empty (confirm at submission time that Meta accepts an empty parameter value; if it does not, that message needs two template variants).

### Template 1 - `new_match_notification`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Buttons | 3 quick replies |

**Parameters**

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |
| {{2}} | Poster display name | IEEE IAS Chapter |
| {{3}} | Description | Full tuition grant for STEM students |
| {{4}} | Applications open date | 2026-09-01 |
| {{5}} | Deadline | 2026-09-30 |

**Body (proposed)**

```
🎓 {{1}}
Posted by {{2}}
{{3}}
📆 Applications open: {{4}}
📅 Deadline: {{5}}
```

**Buttons:** `✅ Apply Now` / `⏰ Remind Me Later` / `🚫 Ignore`

**Sent from:** `whatsapp.py:271` `send_new_match_notification`. Fired by `matching.py:186` (a poster posts), `poster_flow.py:984` (the admin approves a post), and `scheduler.py:330` (the daily pass re-sends it for a match still sitting untouched, because its buttons are what move it forward).

**Drafting notes**

- `{{3}}` is a poster's free-text description, so it is the one parameter whose length we do not control, and it must be truncated to fit the template body cap.
- The code omits lines 3-5 when the data is missing. The template cannot, so those parameters take a placeholder value instead.

---

### Template 2 - `deadline_heads_up`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Buttons | none |

**Parameters**

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |
| {{2}} | Deadline, formatted for display | 30 Sep 2026 |

**Body (proposed)**

```
⏳ Reminder: {{1}} deadline is in 2 days ({{2}}).
```

**Sent from:** `whatsapp.py:407` `send_deadline_heads_up_notification`, fired by the Phase L scheduler (`scheduler.py:270`) once per application, 2 days before its deadline. Nothing is asked of the user, so there are no buttons by design (`3-Full-Product-Logic.md` Section 7.1).

---

### Template 3 - `ongoing_checkin`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Buttons | 3 quick replies |

**Parameters**

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |
| {{2}} | Deadline, formatted (may be empty) | 30 Sep 2026 |

**Body (proposed)**

```
👋 Still working on {{1}}? Deadline is {{2}}.
```

**Buttons:** `⏰ Remind Me Later` / `🔗 Continue App` / `✅ Finished App`

**Sent from:** `whatsapp.py:328` `send_ongoing_checkin_notification`. Fired by the Phase L scheduler's reminder pass (`scheduler.py:351`) and when the user opens an Ongoing row (`my_applications.py:280`).

**Drafting notes:** the code drops the "Deadline is ..." clause entirely when there is no deadline. Button titles are already abbreviated to fit the 20-character cap (`6-Platform-Constraints.md` Section 10.2).

---

### Template 4 - `outcome_check`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Buttons | 3 quick replies |

**Parameters**

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |

**Body (proposed)**

```
Any news on {{1}}? Were you picked?
```

**Buttons:** `🎉 Yes` / `❌ No` / `⏳ Still Waiting`

**Sent from:** `whatsapp.py:371` `send_outcome_check_notification`. Fired by the scheduler's result-check pass (`scheduler.py:342`) and when the user opens an Under Review row (`my_applications.py:284`).

---

### Template 5 - `opportunity_updated`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Buttons | none |

**Parameters**

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |
| {{2}} | One line per changed field, newline-joined | Deadline is now 15 Oct 2026 |
| {{3}} | Reminder note, or empty | Your reminders have been adjusted automatically. |

**Body (proposed)**

```
📢 Update: {{1}}
{{2}}
{{3}}
```

**Sent from:** `whatsapp.py:428` `send_opportunity_update_notification`, fired by `propagation.py:292` whenever a poster's edit actually changes something.

**Drafting notes:** `{{2}}` is built by `propagation.py` as a variable number of lines (that module is where the diffing logic lives, so it knows what really changed), which is why it is joined into a single parameter rather than given a fixed set of slots. The mandatory deadline-change notice (`3-Full-Product-Logic.md` Section 3.1 - never batched, never skipped) uses this same template.

---

## 3. Templates 7-12: admin- and poster-facing (SUBMITTED)

Quoted verbatim from the team's submission sheet. **All six are text-only with no buttons** - which matters for Section 4.

### Template 7 - `poster_registration_pending`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Parameters | 3 |

**Body**

```
New poster registration: {{1}} wants to join as a poster. To approve, send approve {{2}}. To reject, send reject {{3}}.
```

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Display name | IEEE Test Poster |
| {{2}} | Poster ID | 550e8400-e29b-41d4-a716-446655440000 |
| {{3}} | Poster ID (same value as {{2}}) | 550e8400-e29b-41d4-a716-446655440000 |

**Sent from:** `registration.py:135`, replacing today's raw free-form text to the admin.

**Wiring note:** because `{{2}}` and `{{3}}` are **full UUIDs**, the existing admin parser in `webhook.py:100` (`^(approve|reject)\s+<full uuid>$`) matches the admin's reply unchanged. This is the one admin template that needs no new parsing.

---

### Template 8 - `poster_approved`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Parameters | none |

**Body**

```
You're approved! You can now post opportunities. Send any message to get started.
```

**Sent from:** `webhook.py:136`, replacing today's free-form message **with a button**.

**Wiring note:** the template carries no button, so the approved poster must send any message to get started. That works - a returning poster with no active flow gets the Main Menu including the Post button (`webhook.py:507` -> `registration.send_main_menu(is_returning_poster=True)`) - but it is two taps where it used to be one. Resubmitting with a quick-reply button would restore one-tap, and with the Section 4 normalisation already in place, its payload `post_opportunities` would work with no code change.

---

### Template 9 - `poster_rejected`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Parameters | none |

**Body**

```
Your registration was not approved. Please contact support if you believe this is an error.
```

**Sent from:** `webhook.py:144`, replacing today's free-form text. Clean swap.

---

### Template 10 - `post_pending_approval`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Parameters | 7 |

**Body**

```
New post pending approval. Title: {{1}} Type: {{2}} Description: {{3}} Link: {{4}} Deadline: {{5}} To approve, reply approve_post {{6}}. To reject, reply reject_post {{7}}. Please review and respond at your earliest convenience.
```

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Title | MTN Foundation STEM Grant |
| {{2}} | Type | scholarship |
| {{3}} | Description | Full tuition grant for STEM students |
| {{4}} | Link | https://example.com/apply |
| {{5}} | Deadline | 2026-09-30 |
| {{6}} | **Short** opportunity ID | e5f6a7b8 |
| {{7}} | Short opportunity ID (same value as {{6}}) | e5f6a7b8 |

**Sent from:** `poster_flow.py:759`, replacing today's free-form **button** message to the admin (Approve Post / Reject Post).

**Wiring note - needs new code.** The template switches the admin from tapping buttons to typing `approve_post <id>` / `reject_post <id>`, and `{{6}}` is a **short** id, not a UUID. `handle_admin_command` currently parses only `approve|reject <full uuid>`, so as written the admin would type a perfectly reasonable command and get **silence**, because that function returns without complaint on anything it does not recognise. Wiring it needs: (a) a new pattern for `approve_post|reject_post <short id>`, (b) a short-id to UUID resolution against `status = 'pending_approval'` rows, and (c) ideally a "I did not catch that" reply so a typo is not invisible.

---

### Template 11 - `post_approved`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Parameters | 1 |

**Body**

```
Your post "{{1}}" has been approved and is now live! Matched students will be notified.
```

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |

**Sent from:** `poster_flow.py:1109`, replacing today's free-form text.

**Wiring note - loses information the spec requires.** The code currently tells the poster the **match count** ("It was sent to N matching student(s)", or "No students match those tags yet"), which `3-Full-Product-Logic.md` Section 4 requires. The approved template has only the title parameter, and the count cannot be sent as a follow-up either, because the 24-hour window opens on *user*-initiated messages, not on our template. Either resubmit with a second parameter for the count, or accept dropping it.

---

### Template 12 - `post_rejected`

| Field | Value |
|---|---|
| Category | UTILITY |
| Language | en_US |
| Parameters | 1 |

**Body**

```
Your post "{{1}}" was not approved. Please contact the admin for more information.
```

| Param | Meaning | Example |
|---|---|---|
| {{1}} | Opportunity title | MTN Foundation STEM Grant |

**Sent from:** `poster_flow.py:1119`, replacing today's free-form text. Clean swap.

---

## 4. How a reply comes back (read this before drafting buttons)

WhatsApp sends us **three different inbound shapes**, and they are not interchangeable:

| What the user tapped | Payload shape |
|---|---|
| A button on a free-form interactive message we sent | `messages[0].type = "interactive"`, `interactive.button_reply.id` |
| A row on a free-form list message we sent | `messages[0].type = "interactive"`, `interactive.list_reply.id` |
| A quick-reply button on a **template** | `messages[0].type = "button"`, `button.payload` (no `interactive` key at all) |

`webhook.py` normalises all three through `extract_reply_ids(message_obj)` into one `(button_id, list_id)` pair, so every existing `button_id.startswith(...)` branch works whichever shape arrived. This was added because the third shape previously fell through the button dispatch into the conversation-state router and was silently treated as stray text.

**The rule for drafting Templates 1, 3 and 4's buttons:** set each quick reply's id/payload to the **same stateless id the free-form button already uses** - `apply_now_<application uuid>`, `remind_later_<application uuid>`, `ignore_<application uuid>`, `continue_application_<uuid>`, `finished_application_<uuid>`, `outcome_yes_<uuid>`, `outcome_no_<uuid>`, `outcome_waiting_<uuid>`.

**OPEN QUESTION - confirm while drafting.** Our own interactive sends carry those ids because the interactive API lets us set them. It is **not yet verified** whether a *template's* quick-reply button can carry a custom payload: Meta's template UI may only accept button **text**, in which case a tap arrives with the button text as the payload (which is why `extract_reply_ids` falls back to `button.text` rather than dropping the tap). If that is the case, a template tap carries **no row id**, and the handler must resolve which row it means from the database (for example, "the user's newest `available` row" for `apply_now`, newest `under_review` for `outcome_*`, newest `ongoing` for `continue`/`finished`/`remind_later`). This could not be confirmed from the build environment - Meta's documentation returns 400/403 to non-browser requests here - so it must be checked directly in WhatsApp Manager when the first buttoned template is drafted. Templates 7-12 are unaffected: they are text-only.

---

## 5. Messages that deliberately need NO template

Everything the bot sends as a **reply** to something the user just did is in-window and must **not** become a template - it would add Meta review risk for no benefit. This is the full list:

- First contact / welcome and the Student vs Poster choice (Section 1.1)
- Poster display-name prompt (1.2); interest prompt and the "Got it, [tags]" confirmation (1.3)
- Main Menu (2) and the My Applications sub-menu (2)
- The three My Applications lists and the Available Applications list (2) - **note** these are list messages, and templates cannot send list messages at all
- Every poster posting-flow prompt: type, title, description, tags, dates, link, and the "This will go out to ~N students" confirmation (3)
- The Apply Now link, Remind Me Later prompts and confirmations, Ignore confirmation (5.1-5.3)
- The reusable deletion confirmation (13)
- Manual add and edit-item prompts (9.1, 9.2), including the calendar-picker fallback (14)
- All error and "that item is no longer in your list" replies

Two architecture decisions already removed some candidates from this space: tag/interest selection is **free text, not a list** (`6-Platform-Constraints.md` Section 10.3 - 12 categories exceed the 10-row cap and lists are single-select), and the date picker has a free-text fallback.

---

## 6. Open items

| # | Item | Owner decision needed |
|---|---|---|
| 1 | Template 10 needs new admin command parsing (short id, `approve_post` / `reject_post`) and currently fails silently | Build it, and add a "did not catch that" reply |
| 2 | Template 11 drops the match count required by Section 4 | Resubmit with a count parameter, or accept the loss |
| 3 | Template 8 has no button (two taps instead of one) | Accept, or resubmit with a `post_opportunities` quick reply |
| 4 | Whether template quick-reply buttons can carry a custom payload | Confirm in WhatsApp Manager (Section 4) |
| 5 | Templates 1-5 still need drafting and submission | Draft from Section 2 (checklist Phase P) |
| 6 | Are Templates 7-12 approved, or still in review? | Confirmed by the team |
