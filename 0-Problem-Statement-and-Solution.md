# WaveMatch (Opportunity Radar) — Problem Statement & Solution Introduction

## 1. The Problem

Students — particularly in under-resourced or emerging-market contexts like Rwanda — routinely miss out on scholarships, internships, bootcamps, volunteering opportunities, fellowships, and events. This is almost never because the opportunities don't exist. It's because of a cluster of interconnected, everyday failures in how information and personal follow-through work:

### 1.1 Information overload without personalization
Opportunities are shared into large, general WhatsApp groups, mixed in with dozens of unrelated messages a day. A student interested specifically in tech scholarships has no way to filter that firehose down to what's relevant to them — so they either scroll past everything, or give up checking the group at all. There is no concept of "show me only what matches my interests."

### 1.2 No structured way to track personal progress
A student starts an application, gets interrupted by life, and has no system reminding them it's unfinished. By the time they remember, the deadline has passed. There's no external memory keeping track of "you started this, you didn't finish it, here's how long you have left."

### 1.3 Missed opportunities from scattered or absent channels
Some students aren't even in the right WhatsApp groups to see an opportunity in the first place. Others are in so many groups that the volume itself becomes the barrier — the opportunity was technically shared, but functionally invisible.

### 1.4 No outcome tracking or follow-through after applying
Once a student submits an application, most tracking stops entirely. Students forget to check whether they were accepted or rejected. If accepted, they may then forget to prepare for or attend the actual event/program, because nothing in their environment is proactively reminding them as the date approaches.

### 1.5 The deeper equity problem
Students with strong personal networks, older mentors, or naturally organized habits tend to self-correct for all of the above — they hear about opportunities through personal connections, and they have their own systems (calendars, reminders, habits) for staying on top of deadlines. Students without those networks or habits are disproportionately locked out — not because they're less capable or less deserving, but because the *information and follow-through infrastructure* around them is weaker. This is a real, quantifiable form of inequality in access to opportunity, and it compounds over time: missed scholarships and bootcamps early on mean fewer opportunities, connections, and momentum later.

### 1.6 Why existing solutions don't solve this
- **Plain WhatsApp groups/broadcast lists** — no personalization, no tracking, no reminders. They only solve the "opportunity exists somewhere" part of the problem, not the "I saw it, engaged with it, and followed through" part.
- **Dedicated apps/platforms** (job boards, scholarship databases) — require a separate app download, separate login, and separate habit of checking them. This adds friction exactly where the problem already is: getting students to reliably engage with something.
- **Generic to-do or reminder apps** — not opportunity-aware. A student would have to manually create every reminder themselves, which is exactly the follow-through step that's already failing.

## 2. The Solution — Introduction

**WaveMatch is a WhatsApp bot** that closes the loop between "an opportunity exists" and "a student successfully engages with it, on time, all the way through" — without requiring anyone to install anything new, since it lives inside the messaging app people already use every day.

At its core, WaveMatch does three things:

1. **Personalized delivery** — opportunities are tagged by category, students select their interests once at registration, and the bot only surfaces what's actually relevant to them. No more scrolling through noise.

2. **End-to-end lifecycle tracking** — every opportunity a student engages with moves through a defined lifecycle (**Available → Ongoing → Under Review → Scheduled**), and the bot proactively reminds the student at the right moments: before a deadline, if an application is left unfinished, and after a results date has passed, to check whether they were accepted.

3. **A trusted, curated posting layer** — approved posters (starting with the IEEE IAS chapter and its officers) share opportunities directly into the bot, which then handles matching, notification, and tracking automatically. This keeps quality high while removing the manual burden of a student having to hunt for and organize opportunities themselves.

### Why WhatsApp specifically
WhatsApp is already the dominant, near-universal communication platform among students in this context. Building on it — rather than a separate app — means zero onboarding friction: no download, no new login, no new habit to build. The "communication technology" is not incidental to this solution; it *is* the solution. The same infrastructure students already use to talk to friends and family becomes the infrastructure that keeps them from missing out on their future.

### The scaling vision
WaveMatch starts with a single community (the IEEE IAS Student Branch Chapter at UR-CST) to prove the model with real usage and real outcomes. The underlying architecture is designed so that any university, TVET school, youth organization, or NGO — anywhere opportunities are scattered and students lack organizational infrastructure — could stand up their own instance of this same system. The problem WaveMatch solves is not unique to one campus or one country; it is a structural gap in how opportunity information flows to the people who need it most, and this is a reusable, scalable answer to that gap.
