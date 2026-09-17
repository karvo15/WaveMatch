# WaveMatch — Platform Constraints & Rules (WhatsApp Cloud API)

These are hard, confirmed platform rules and quirks, learned directly through hands-on setup and testing. Design and build around these from the start — they are not optional or workaroundable.

> **Stack change note:** backend is now Python/FastAPI (see Architecture-Doc.md). Everything in this document is a **Meta/WhatsApp-side constraint** — templates, tiers, number registration, message limits — and applies identically regardless of backend language, with one exception: **Section 10.4** (webhook signature verification) was written against Express/Node and has been rewritten below for FastAPI, since *how* you get the raw request body differs between the two frameworks even though *why* you need it doesn't.

---

## 1. The 24-Hour Messaging Window (most important rule)

A business can only send **free-form messages** to a user within **24 hours of that user's last message** to the business. Every time a user messages the bot, this 24-hour window resets.

**Outside that window, only pre-approved Message Templates can be sent.**

### What this means for WaveMatch
Nearly every proactive message this bot sends is, by definition, outside a live conversation:
- New match notifications
- Deadline heads-up (2 days before)
- Ongoing reminders
- Result/outcome check-ins
- Opportunity-updated notifications

**All of these require pre-approved Message Templates.** Free-form replies (like answering a button click, or responding to something the user just typed) are fine within the 24-hour window and don't need templates.

### Practical implication for the build
Design the messaging layer so every proactive message is sent via a **named template function**, not raw text — this makes it trivial to swap in the approved template name/structure once templates clear review, without restructuring the codebase later.

**The register of all 11 templates this product needs** - each one's name, parameters, body, the code path it is sent from, and which message types deliberately need no template at all - lives in `9-Message-Templates.md`.

### Template categories
Templates are submitted under categories: **UTILITY** or **MARKETING**. Reminders/notifications for this product should be UTILITY category. Submit templates for approval as early as possible in the build — approval isn't always instant, and building/testing can proceed in parallel using direct API calls to your own verified test number in the meantime (since messaging your own confirmed-owned number for testing doesn't require the same constraints, as you're both the business and a legitimate confirmed contact).

---

## 2. Messaging Tiers & Volume Caps

- An **unverified** WABA (no Meta Business Verification completed) is capped at roughly **250 unique conversations per rolling 24-hour period**.
- This is more than sufficient for a chapter-scale prototype and demo. **Business Verification is not required for this project's scope** — do not pursue it; it requires a registered legal business entity with documents, which doesn't apply here, and the messaging cap is a non-issue at this scale.

---

## 3. Free Test Number vs. Real Registered Number

Meta offers two distinct ways to get a sending number, with materially different restrictions:

### 3.1 Free auto-assigned test number
- Provisioned instantly, no verification needed.
- **Restricted to messaging a maximum of 5 pre-approved recipient numbers.** Each recipient must be manually added and verified (via a code sent to their WhatsApp) through the dashboard before the number can message them.
- This recipient allowlist is **dashboard-only** — there is no public API endpoint to manage it.

### 3.2 Real registered number (what WaveMatch actually uses)
- Added manually in WhatsApp Manager, verified via SMS or voice call (or via the API's `/request_code` and `/verify_code` endpoints).
- **No 5-recipient restriction** — can message any WhatsApp user, subject only to the 24-hour window / template rule above.
- Still subject to the same overall unverified-tier conversation cap (~250/24hr) as any other number on an unverified WABA.

**WaveMatch is built on a real registered number, not the free test number** — this is the correct choice and avoids the recipient allowlist limitation entirely.

---

## 4. Number Registration (required, one-time, per number)

Even after a number is added and phone-verified, it must be explicitly **registered** before it can send/receive messages via the API:

```
POST /{PHONE_NUMBER_ID}/register
Body: { "messaging_product": "whatsapp", "pin": "<a 6-digit PIN you choose>" }
```

This PIN is the number's two-step verification PIN going forward. It can be changed later via:

```
POST /{PHONE_NUMBER_ID}
Body: { "pin": "<new 6-digit PIN>" }
```

Attempting to send a message before registration returns error code `133010` ("Account not registered").

**Important:** a phone number cannot simultaneously be registered to the Cloud API and remain active on the regular consumer WhatsApp or WhatsApp Business app. Never register a number that needs to keep functioning normally as someone's personal WhatsApp.

---

## 5. Authentication: System User Tokens

- Use a **System User access token** (generated via Business Settings → System Users), not the Developer App dashboard's temporary token. The dashboard token expires in ~24 hours; System User tokens are long-lived and appropriate for a continuously-running backend.
- Required permissions: `whatsapp_business_messaging` and `whatsapp_business_management`. No other permissions are needed.
- **The System User must be explicitly granted access to both the relevant App and the relevant WABA as Business Assets (Full Control) before a scoped token will work.** If you add a new WABA or App to the business later, the System User needs to be granted access to it too, and a **new token regenerated** — access granted after a token was issued does not retroactively apply to that already-issued token.

---

## 6. Webhooks

- Incoming messages, button replies, and status updates arrive via a webhook POST to a URL you configure in the Meta dashboard.
- Verify incoming webhook requests are genuinely from Meta using the **App Secret** (not the App ID) to check the request signature.
- A separate one-time **GET** request handshake (webhook verification challenge) must be handled correctly when first configuring the webhook URL in the dashboard.

---

## 7. No Way to Read Other WhatsApp Groups/Channels

There is no official API to read, scrape, or monitor content from WhatsApp groups or channels that the business account doesn't itself own. **Opportunity content must come from posters actively submitting it to the bot** — there is no automated way to pull opportunities from existing WhatsApp groups where they're currently being shared. (Auto-importing from external websites via a separate scraper + LLM parser remains a legitimate future-roadmap idea, but that's a website-scraping concern, not a WhatsApp-reading one.)

---

## 8. Pricing (for awareness beyond the competition deadline)

- At present, messages sent within an active 24-hour window (service messages, and utility templates sent in-window) are free.
- This is scheduled to change **October 1, 2026**, when Meta begins charging for service messages and in-window utility messages again. This postdates the competition deadline (Sept 5) and shouldn't affect the submission, but is relevant if the bot continues running for the chapter afterward.
- Outside the window, template messages are billed per conversation, at rates that vary by destination country and template category — negligible at this project's testing/demo scale, but worth monitoring if usage grows.

---

## 9. Business Verification — Explicitly Skipped

Meta's formal Business Verification process (document upload, legal entity name/address matching, domain-matched business email) is **not pursued for this project**. It requires a registered legal business entity, which doesn't apply to a student project or an informal chapter. It is not required to send messages — only to raise the messaging volume cap above ~250 conversations/24hr, which is unnecessary at this project's scale.

---

## 10. Interactive Message Limits (discovered during build — real, hard API constraints)

These are exact limits confirmed by live API errors during development, not documentation guesses. Any interactive message must respect all of them:

### 10.1 List messages
- **Max 10 rows total, across all sections combined** — not 10 per section. Confirmed via live error: `(#131009) Parameter value is not valid — Total row count exceed max allowed count: 10`. This is why tag selection (12 categories) was moved to free text instead of a list — it couldn't fit even before adding a custom-tag row.
- **Row title: max 24 characters.** Confirmed via live error after two category names ("Tech Events / Conferences," "Competitions / Hackathons," both 25 characters) were rejected. Any list-based UI (e.g. Available Applications, My Applications) must keep item titles under this limit or truncate/abbreviate them.
- **Row description: max 72 characters** (per Meta's documentation — not yet hit in testing, but design around it).
- **Section title: max 24 characters.**
- Any list that could exceed 10 rows (e.g. a long Available Applications list once real opportunities accumulate) must **paginate** — show 9 items + a "More →" row, not truncate silently or crash.

### 10.2 Quick Reply buttons
- **Max 3 buttons per message.**
- **Button text: max 20 characters** (per Meta's documentation).

### 10.3 Why tag/interest selection uses free text, not a list
Two of the above limits combined ruled out lists for this specific step: 12 fixed categories already exceeds the 10-row cap even before adding "Add my own," and WhatsApp lists are single-select per message anyway (no native multi-select), which would have required an awkward repeated-list-resend pattern. Free text with layered matching (see Full-Product-Logic.md Section 10.2) avoids both problems in one message.

### 10.4 Webhook signature verification vs. body parsing (a build gotcha, not a Meta limit)
Verifying a webhook's signature requires the **raw, unparsed request body**; the rest of the handler needs the **parsed JSON**. This is true regardless of backend framework — the gotcha is *how* to get both from the same request without one consuming the other.

**FastAPI/Starlette fix:** in the webhook route, read `await request.body()` **first** — this gives the raw bytes exactly as Meta sent them. Compute the HMAC-SHA256 signature over those raw bytes using the App Secret, and compare it against the `X-Hub-Signature-256` header (constant-time comparison — use `hmac.compare_digest`, not `==`, to avoid a timing side-channel). **Only after** the signature check passes, call `request.json()` (or `json.loads()` on the same raw bytes you already have) to get the parsed payload for normal handling.

```python
@app.post("/webhook")
async def receive_webhook(request: Request):
    raw_body = await request.body()          # raw bytes — for signature check
    if not verify_signature(raw_body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="Invalid signature")
    payload = json.loads(raw_body)            # parsed — for normal handling
    ...
```

The key rule: never call a body-parsing method (`request.json()`, or any dependency that implicitly parses the body, like a Pydantic request-body model on the route) **before** you've captured `await request.body()` — once the body stream is consumed, it's gone, and a second read returns empty. Grab the raw bytes exactly once, at the top of the handler, and derive everything else from that same variable.

### 10.5 App-level vs. WABA-level webhook configuration (a build gotcha, not a Meta limit)
Configuring a Callback URL, Verify Token, and subscribing to the `messages` field at the **App level** is not sufficient on its own if the app has more than one WhatsApp Business Account (WABA) under it. Each WABA must also be explicitly subscribed to the app via a direct API call:
```
POST /{WABA_ID}/subscribed_apps
```
(no request body needed, just an authenticated POST). Without this, the app-level webhook config can appear fully correct while no events ever actually arrive, because the specific WABA sending them was never linked to it.
