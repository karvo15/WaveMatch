# WaveMatch — Message Flow Examples

These are illustrative sample conversations for every touchpoint in the bot. Exact wording can be refined during development, but the **structure, button labels, and sequence** shown here should be followed closely so behavior stays consistent with the Full Product Logic document.

---

## 1. First Contact

**Bot:**
> 👋 Welcome to WaveMatch! Are you here to:
> [🎓 Find Opportunities] [📢 Post Opportunities]

---

## 2. Poster Registration

**User taps [📢 Post Opportunities]**

**Bot:**
> Great! What name should we show on your posts? (Your name or your organization's name)

**User:** `IEEE IAS UR-CST`

**Bot:**
> Thanks! Your registration is pending admin approval. We'll let you know as soon as you're confirmed. 🙏

**→ Admin receives:**
> 🆕 New poster registration: *IEEE IAS UR-CST* wants to join as a poster.
> Reply `approve P1042` to confirm, or `reject P1042` to decline.

**Admin replies:** `approve P1042`

**→ Poster receives:**
> ✅ You're approved! Tap below anytime to post a new opportunity.
> [➕ Post Opportunity]

---

## 3. User Registration

**User taps [🎓 Find Opportunities]**

**Bot:**
> Let's personalize what you see. Here are our categories:
> 🎓 Scholarships · 💼 Internships · 🤝 Volunteering · 🎤 Tech Events / Conferences · 🏆 Competitions / Hackathons · 🛠️ Workshops / Trainings · 🚀 Bootcamps · 👔 Job Opportunities · 🔬 Research Opportunities · 🎗️ Fellowships · 💰 Grants / Funding · 🌐 Networking Events
>
> Reply with the ones you're interested in, separated by commas (e.g. "scholarships, tech events, volunteering"). Not seeing something? Just type it — we'll add it.

**User:** `scholarships, tech events, hackathons`

*(Bot matches "scholarships" and "tech events" exactly; "hackathons" matches via keyword to Competitions / Hackathons.)*

**Bot:**
> Got it — Scholarships, Tech Events / Conferences, Competitions / Hackathons. Here's your menu:
> [📋 Available Apps] [📁 My Applications]

---

## 4. Poster Creates an Opportunity

**Poster taps [➕ Post Opportunity]**

**Bot:**
> What type of opportunity is this? (meeting / volunteering / event / scholarship / other)

**Poster:** `scholarship`

**Bot:** > What's the title?

**Poster:** `MTN Foundation STEM Grant`

**Bot:** > Give a short description.

**Poster:** `Full tuition grant for 2nd-3rd year STEM students at Rwandan universities.`

**Bot:** > Now pick your tags — here are the categories:
> 🎓 Scholarships · 💼 Internships · 🤝 Volunteering · 🎤 Tech Events / Conferences · 🏆 Competitions / Hackathons · 🛠️ Workshops / Trainings · 🚀 Bootcamps · 👔 Job Opportunities · 🔬 Research Opportunities · 🎗️ Fellowships · 💰 Grants / Funding · 🌐 Networking Events
>
> Reply with the ones that fit, separated by commas.

**Poster:** `scholarships, grants`

**Bot:** > When does the application period start?

**Poster:** `Aug 25`

**Bot:** > What's the application deadline?

**Poster:** `Sept 20`

**Bot:** > When will results be announced? (or reply "skip" if unknown)

**Poster:** `skip`

**Bot:** > When does the program start, if known? (or reply "skip")

**Poster:** `skip`

**Bot:** > What's the application link?

**Poster:** `https://mtnfoundation.rw/apply`

**Bot:**
> This will go out to approximately **34 students** interested in Scholarships/Grants. Send it?
> [✅ Confirm & Send] [✏️ Edit]

**Poster taps [✅ Confirm & Send]**

**Bot:** > Sent! 🎉

---

## 5. New Match Notification (User Side)

**User receives:**
> 🎓 **MTN Foundation STEM Grant**
> Posted by *IEEE IAS UR-CST*
> Full tuition grant for 2nd-3rd year STEM students at Rwandan universities.
> 📆 Applications open: Aug 25
> 📅 Deadline: Sept 20
>
> [✅ Apply Now] [⏰ Remind Me Later] [🚫 Ignore]

### 5a. User taps [✅ Apply Now]
**Bot:** > Opening the link now — good luck! 🍀 I'll check in with you in a couple of days.
*(Link opens; application moves to Ongoing)*

### 5b. User taps [⏰ Remind Me Later]
**Bot:** > When should I remind you? Reply with a time (e.g. "in 3 days", "in 5 hours", "Sept 18"), or pick a date:
> [📅 Choose a Date] [Reply with default: 2 days]

**User:** `default`

**Bot:** > Got it, I'll remind you in 2 days.

### 5c. User taps [🚫 Ignore]
**Bot:** > Are you sure? This will remove **MTN Foundation STEM Grant** from your list and can't be undone.
> [✅ Confirm] [↩️ Cancel]

**User taps [✅ Confirm]**

**Bot:** > No problem, I won't show you this one again.

---

## 6. Ongoing Reminder Cycle

**Bot (2 days later):**
> 👋 Still working on **MTN Foundation STEM Grant**? Deadline is Sept 20.
> [⏰ Remind Me Later] [🔗 Continue Application] [✅ Finished Application]

### 6a. User taps [⏰ Remind Me Later]
**Bot:** > When should I check back? Reply with a time, pick a date, or reply `never` to stop reminders for this one.

**User:** `never`

**Bot:** > Are you sure? You won't be reminded about **MTN Foundation STEM Grant** again.
> [✅ Confirm] [↩️ Cancel]

**User taps [✅ Confirm]**

**Bot:** > Understood — I've removed this from your reminders.

### 6b. User taps [🔗 Continue Application]
**Bot:** > Here's the link again: https://mtnfoundation.rw/apply

### 6c. User taps [✅ Finished Application]
**Bot:** > Nice work finishing it! I'll check in around when results are expected.

---

## 7. Deadline Heads-Up (fires automatically, 2 days before deadline)

**Bot:**
> ⏳ Reminder: **MTN Foundation STEM Grant** deadline is in 2 days (Sept 20).

---

## 8. Under Review — Outcome Check

**Bot (fires 1 day after result_date, or every 3 days if no result_date known):**
> Any news on **MTN Foundation STEM Grant**? Were you picked?
> [🎉 Yes] [❌ No] [⏳ Still Waiting]

### 8a. User taps [🎉 Yes] — event date known
**Bot:** > Congratulations! 🎉 I've added the program start date to your Scheduled list.

### 8b. User taps [🎉 Yes] — event date unknown
**Bot:** > Congratulations! 🎉 When does it start?

**User:** `Oct 5`

**Bot:** > Got it — added to your Scheduled list. I'll remind you as it approaches.

### 8c. User taps [❌ No]
**Bot:** > Are you sure? This will remove **MTN Foundation STEM Grant** from your list.
> [✅ Confirm] [↩️ Cancel]

**User taps [✅ Confirm]**

**Bot:** > Sorry to hear that. Removed from your list — keep going, more opportunities are coming. 💪

### 8d. User taps [⏳ Still Waiting]
**Bot:** > No worries, I'll check back in 3 days.

---

## 9. Poster Edits a Post

**Poster:** *(selects an existing post to edit, changes deadline from Sept 20 to Sept 25)*

**Bot (to poster):** > Updated! Everyone tracking this will be notified of the new deadline.

**Bot (to each affected user):**
> 📢 Update: **MTN Foundation STEM Grant** deadline moved to **Sept 25**. Your reminders have been adjusted automatically.

---

## 10. Manually Adding a Personal Application

**User taps [➕ Add manually] from My Applications**

**Bot:** > What's it called?

**User:** `AWS re/Start Application`

**Bot:** > Any description? (or reply "skip")

**User:** `Cloud computing bootcamp, applied last week`

**Bot:** > What stage is it at — Ongoing or Under Review?

**User:** `Under Review`

**Bot:** > Got it. Do you know when results come out? (or reply "skip")

**User:** `Sept 1`

**Bot:** > Added to your Under Review list. I'll check in with you after Sept 1.

---

## 11. Available Applications / My Applications Views (List Message)

**User taps [📋 Available Apps]**

**Bot:** *(List message)*
> **Available Applications**
> 🎓 MTN Foundation STEM Grant — deadline Sept 20
> 💼 Bank of Kigali Internship — deadline Sept 30
> 🎤 Africa Tech Summit — deadline Oct 5

**User taps [📁 My Applications]**

**Bot:** > Which list?
> [Under Review] [Ongoing] [Scheduled]

**User taps [Ongoing]**

**Bot:** *(List message)*
> **Ongoing**
> 🎓 MTN Foundation STEM Grant — deadline Sept 20
> [➕ Add manually] [✏️ Edit an item]
