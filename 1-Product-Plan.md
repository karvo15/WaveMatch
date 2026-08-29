# WaveMatch — Product Plan
*WhatsApp bot for personalized opportunity discovery & application tracking*

**Competition:** IEEE ComSoc "Communication Technology Changing the World" Student Competition
**Team:** [Your name]

---

*For the exhaustive, branch-by-branch logic, see Full-Product-Logic.md. For exact sample wording, see Message-Flow-Examples.md. For the database schema, see Data-Schema.sql.*

## 1. The Problem

Students miss out on scholarships, bootcamps, volunteering opportunities, and events — not because information doesn't exist, but because:

- Opportunities are scattered across dozens of WhatsApp groups, buried under unrelated messages
- There's no personalization — everyone sees everything, or nothing
- Students start applications and forget to finish them before the deadline
- Students forget to check whether they got accepted, and forget to attend events they were accepted into
- No single place tracks "what am I currently applying to, and what's the status?"

## 2. The Solution

A **WhatsApp bot** — no new app to install, works on the platform students already live in — that:

1. Lets trusted **posters** (admin-approved) share opportunities, tagged by category
2. Matches opportunities to **users** based on their selected interest categories
3. Tracks each user's applications through a full lifecycle: **Available → Ongoing → Under Review → Scheduled**
4. Sends smart, non-spammy reminders at the right moments (before deadlines, for unfinished applications, for result dates)
5. Automatically schedules events/programs once a user confirms they were accepted

The bot is the entire interface — posting, browsing, applying, tracking, and reminders all happen through WhatsApp messages, buttons, and text replies. No separate website or app required for either posters or users.

## 3. Who Uses It

### Posters (admin-approved)
Individuals or organizations (e.g. IEEE IAS chapter, other clubs, later — institutions) who share opportunities. Approved manually by the admin for now, to keep quality high and avoid spam in the MVP.

### Users (students)
Anyone who registers, sets their interest categories, and receives matched opportunities.

---

## 4. Poster Flow

1. **Register** — provide a poster/organization name (shown on every post they share, so users know who's posting).
2. **Wait for admin approval** — admin manually approves new posters before they can post. The admin can additionally require any specific poster's *individual posts* to be reviewed one-by-one (a toggle, separate from the one-time registration approval) — useful for posters who are approved but not yet fully trusted.
3. **Post a new opportunity** via a "Post" button, providing (everything required except Result Announcement Date and Event/Program Start Date, which can be skipped):
   - Event name
   - Description
   - Type (meeting, volunteering, event, scholarship, etc.)
   - Category tags — poster is shown the fixed list as text and replies with a comma-separated list of tags; typos and alternate phrasings are matched automatically, anything unmatched becomes a new custom tag
   - Application start date
   - Application deadline
   - Result announcement date (skippable)
   - Event/program start date (skippable)
   - Application link
4. **See interest count** — after tagging, the poster sees *how many users* match that category (count only, never names — privacy-safe).
5. **Edit a post anytime** — changing dates, description, etc. Any user who clicked "Apply" or "Remind Me Later" on that post is automatically notified of the change, and if dates changed, their tracked application is updated automatically to match.

---

## 5. User Flow

### Registration
- Set interest categories by replying to a fixed list with a comma-separated list of interests (typos and alternate phrasings are matched automatically; unmatched terms become custom tags).
- Categories can be edited anytime.

### Main Menu — two views
- **Available Applications** — opportunities matched to the user's interests that they haven't acted on yet.
- **My Applications** — split into three lists:
  - **Under Review** — applied, waiting for result
  - **Ongoing** — started but not finished
  - **Scheduled** — confirmed acceptance, event/program date locked in

Each list also supports **manually adding an event** (for things outside the bot's own postings — the user opens the specific list they want to add into first), **editing** any tracked item (dates, description), and **deleting** any tracked item — deletions always show a confirmation warning first, a rule that applies everywhere an application could be removed (Ignore, Never, a rejection, or a manual delete).

### When a matched opportunity arrives
User gets the opportunity (description + link) with three buttons:
- **Apply Now** → link opens immediately, application moves to *Ongoing*
- **Remind Me Later** → default reminder in 2 days (see reminder logic below)
- **Ignore** → opportunity is removed from their chat entirely

If the user doesn't respond at all, they're treated the same as "Remind Me Later" (default 2-day follow-up).

### Ongoing applications
Every 2 days (subject to the batching rule below), the bot checks in with three buttons:
- **Remind Me Later** → also offers a **Never** option to stop reminders for that specific application (removes it from tracking)
- **Continue Application** → re-opens the link
- **Finished Application** → moves it to *Under Review*

**Deadline behavior:** the bot always sends one heads-up message exactly **2 days before the deadline**, regardless of the normal reminder cycle. If the deadline passes and the application was never marked "Finished," it stops reminding and **removes the application automatically**.

### Under Review applications
- If the poster provided a results date, the bot waits until **1 day after** that date, then asks: **Yes / No / Waiting**
  - **No** → application removed from dashboard
  - **Waiting** → bot checks back again in 3 days
  - **Yes** → 
    - If the poster provided an event start date → application is **automatically scheduled**
    - If not provided → user is prompted to enter the date themselves, and the application moves into *Scheduled*
- If the poster never provided a results date, the bot checks in with the user every 3 days asking whether they've heard back yet.

### Reminder batching (anti-spam rule)
If a user has more than two reminders due on the same day, the bot only sends the **two with the nearest deadlines** that day and automatically pushes the rest to the next day. This logic always re-evaluates by deadline proximity — not by how long a reminder has already been delayed.

---

## 6. Category/Tag System

A fixed starter list of 12 categories — Scholarships, Internships, Volunteering, Tech Events/Conferences, Competitions/Hackathons, Workshops/Trainings, Bootcamps, Job Opportunities, Research Opportunities, Fellowships, Grants/Funding, Networking Events — is shown as plain text to both posters and users, who reply with a comma-separated list of the ones that apply. Typed terms are matched through a layered process — exact match, keyword match, typo-tolerant fuzzy match, then a small alias dictionary for alternate phrasings (e.g. "job" → Job Opportunities) — before falling back to creating a new custom tag for anything genuinely unmatched. A nightly job merges near-duplicate custom tags (e.g. "Volunteering" vs. "volunteer") into one canonical tag, so matching doesn't silently break from inconsistent naming over time.

---

## 7. What's in the MVP vs. Future Roadmap

**Building now (MVP):**
- Full application lifecycle (Available → Ongoing → Under Review → Scheduled)
- Admin-approved posters
- Fixed + custom tag matching
- Three-button interaction pattern throughout
- Deadline heads-up + expiry/cleanup logic
- Reminder batching by nearest deadline
- Post editing with auto-notification and date sync
- Manual add/edit of personal applications and events

**Future roadmap (mentioned in submission, not built for demo):**
- Self-serve poster registration (no manual approval) once trust/moderation tooling exists
- Auto-import of opportunities from external websites via LLM-based scraping
- WhatsApp Flows for a full in-chat dashboard experience
- Institutional multi-tenant accounts (universities/organizations run their own branded community)
- Outcome-pattern-based smart recommendations (e.g. suggesting different categories after repeated rejections)

---

## 8. Why This Fits the Competition

- **Communication technology angle:** built entirely on WhatsApp — the channel with near-universal adoption in our context — removing the barrier of app downloads, storage, or new interfaces.
- **Social impact:** tackles real information inequality — students without strong networks or personal organization systems lose access to life-changing opportunities simply from missed deadlines or scattered information.
- **Scalable model:** starts with one community (our IEEE IAS chapter) but the architecture is designed to extend to any university, TVET school, or youth organization.
- **Practical results:** we can demonstrate real usage data from our own chapter as proof of concept — not just theory.
