"""
Daily Scheduler for WaveMatch (Phase L).

Spec: 3-Full-Product-Logic.md Section 7 (deadline / expiry / reminder rules) and
2-Architecture-Doc.md Section 3C (the four passes, and the deliberate
APScheduler-over-Render-Cron choice).

One run performs, in order:
  1. Deadline heads-up  -- deadline exactly 2 days out   -> one-time warning     (7.1)
  2. Expiry / cleanup   -- deadline already passed       -> delete the row       (7.2)
  3. Reminder batching  -- reminders now due             -> at most 2 per user
                           per day, nearest deadline first, rest -> tomorrow     (7.3)
  4. Result check       -- `under_review` checks now due -> the Phase K prompt    (7.4)

Note on passes 3 and 4: they are implemented as ONE batched pass. Section 7.3 puts the
2-per-user-per-day cap on "all applications where next_reminder_at <= today", and
Section 7.4 fires on exactly that same `next_reminder_at` condition -- so a user with
several things due on the same morning is never sent more than two messages, whichever
stage each row is at. Which message goes out depends on the row's status: `available`
gets the New Match Notification again (those are the buttons that can still move it
forward), `ongoing` gets the Ongoing check-in, `under_review` gets the Outcome check.
(2-Architecture-Doc.md describes the reminder pass and the result-check pass as
separate, and attaches the cap only to the reminder pass; capping only one half would
let a single user collect five messages in one morning, so the union above is the
reading that satisfies both documents.)

"Today" is evaluated in the product timezone (SCHEDULER_TZ, default Africa/Kigali).
The deadline columns are plain DATEs that posters fill in against their own calendar,
so a UTC-based "today" would be up to two hours out of step with them.

Spin-down caveat (2-Architecture-Doc.md Section 3C): an in-process APScheduler job only
runs while the service is awake, so a long idle stretch on Render's free tier can skip a
day. run_daily_scheduler() is deliberately a plain callable so the same passes can be
triggered on demand -- from a test script now, or a protected Render Cron endpoint later
-- without touching any of the logic below.
"""

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import anyio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import tags  # Phase N: Section 10.3's nightly dedup pass
from dotenv import load_dotenv

from conversation import _db_semaphore
from database import supabase
from whatsapp import (
    send_deadline_heads_up_notification,
    send_new_match_notification,
    send_ongoing_checkin_notification,
    send_outcome_check_notification,
)

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to the default rather than crashing at import."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning(f"SCHEDULER_BAD_ENV: {name} is not an integer, using {default}")
        return default


# ---- configuration (env-overridable, so run timing can be tuned without a code change) ----
SCHEDULER_TZ = os.getenv("SCHEDULER_TZ", "Africa/Kigali")
SCHEDULER_HOUR = _env_int("SCHEDULER_HOUR", 8)
SCHEDULER_MINUTE = _env_int("SCHEDULER_MINUTE", 0)
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

# Section 10.3's dedup pass runs on the same scheduler instance but on its own cron (early
# morning, so it never races the daytime reminder passes) and its own on/off switch.
TAG_DEDUP_HOUR = _env_int("TAG_DEDUP_HOUR", 3)
TAG_DEDUP_MINUTE = _env_int("TAG_DEDUP_MINUTE", 30)
TAG_DEDUP_ENABLED = os.getenv("TAG_DEDUP_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

# ---- Section 7 constants ----
HEADS_UP_DAYS = 2                   # 7.1: warn two days before the deadline
MAX_REMINDERS_PER_USER_PER_DAY = 2  # 7.3
REMINDER_DEFAULT_DAYS = 2           # 5.2 / 6.1: default gap when the user gives no time
OUTCOME_RECHECK_DAYS = 3            # 8.2 / 8.4: recurring outcome check

# Expiry (7.2) only applies to rows that are still moving; the reminder pass (7.3) also
# covers `under_review` (7.4). `scheduled` rows carry next_reminder_at = NULL, so they
# are never picked up by either query.
ACTIVE_STATUSES = ("available", "ongoing")
REMINDABLE_STATUSES = ("available", "ongoing", "under_review")

_APP_SELECT = (
    "id, user_id, status, next_reminder_at, custom_title, custom_deadline, "
    "deadline_heads_up_sent, users(phone_number), "
    "opportunities(title, description, application_start_date, application_deadline, "
    "result_date, posters(display_name))"
)


# ============================================================
# TIMEZONE HELPERS
# ============================================================

def _tz() -> ZoneInfo:
    """Product timezone, falling back to UTC if the tz database key is unavailable."""
    try:
        return ZoneInfo(SCHEDULER_TZ)
    except Exception:
        logger.warning(f"SCHEDULER_TZ_UNAVAILABLE: {SCHEDULER_TZ!r} not found, using UTC")
        return ZoneInfo("UTC")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now_utc().astimezone(_tz()).date()


def _due_cutoff_utc(today: date) -> datetime:
    """
    The instant "today" ends in the product timezone, as UTC.

    A row is due when `next_reminder_at` is earlier than this -- i.e. its reminder is
    dated today or earlier (Section 7.3's "next_reminder_at <= today"). Phrasing it as
    a date comparison rather than "<= now" is what keeps the daily job from skipping a
    reminder that was set for later today but is still "due today".
    """
    start_of_tomorrow = datetime.combine(today + timedelta(days=1), time.min, tzinfo=_tz())
    return start_of_tomorrow.astimezone(timezone.utc)


def _as_date(raw: Any) -> Optional[date]:
    """Coerce a Supabase DATE (already a date, or an ISO string) to a date, or None."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _display_date(value: date) -> str:
    """Poster-facing date, e.g. 2026-09-20 -> 'Sep 20' (4-Message-Flow-Examples.md Section 7)."""
    return f"{value.strftime('%b')} {value.day}"


# ============================================================
# ROW HELPERS
# ============================================================

def _opportunity(app: Dict[str, Any]) -> Dict[str, Any]:
    return app.get("opportunities") or {}


def _title(app: Dict[str, Any]) -> str:
    return _opportunity(app).get("title") or app.get("custom_title") or "this opportunity"


def _phone(app: Dict[str, Any]) -> Optional[str]:
    return (app.get("users") or {}).get("phone_number")


def _effective_deadline(app: Dict[str, Any]) -> Optional[date]:
    """`opportunities.application_deadline`, or the custom one for manually-added rows."""
    return _as_date(_opportunity(app).get("application_deadline") or app.get("custom_deadline"))


def _deadline_sort_key(app: Dict[str, Any]) -> Tuple[bool, date]:
    """Order due rows by nearest deadline; rows with no deadline at all go last."""
    deadline = _effective_deadline(app)
    return (deadline is None, deadline or date.max)


# ============================================================
# DATABASE ACCESS (all through the shared semaphore -- see Architecture Doc Section 3F)
# ============================================================

async def _fetch_active_applications() -> List[Dict[str, Any]]:
    """Every `available` / `ongoing` row, with the fields the heads-up and expiry passes need."""
    def _get():
        return (
            supabase.from_("applications")
            .select(_APP_SELECT)
            .in_("status", list(ACTIVE_STATUSES))
            .execute()
        )

    async with _db_semaphore:
        result = await anyio.to_thread.run_sync(_get)
    return result.data or []


async def _fetch_due_applications(cutoff_utc: datetime) -> List[Dict[str, Any]]:
    """Every row whose next reminder is dated today or earlier (7.3)."""
    def _get():
        return (
            supabase.from_("applications")
            .select(_APP_SELECT)
            .lt("next_reminder_at", cutoff_utc.isoformat())
            .execute()
        )

    async with _db_semaphore:
        result = await anyio.to_thread.run_sync(_get)
    return result.data or []


async def _update_application(application_id: str, fields: Dict[str, Any]) -> None:
    def _update():
        payload = dict(fields)
        payload["updated_at"] = _now_utc().isoformat()
        return supabase.from_("applications").update(payload).eq("id", application_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_update)


async def _delete_application(application_id: str) -> None:
    def _delete():
        return supabase.from_("applications").delete().eq("id", application_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_delete)


# ============================================================
# PASS 1 -- DEADLINE HEADS-UP (Section 7.1)
# ============================================================

async def run_deadline_heads_up_pass(today: date, active_rows: Optional[List[Dict[str, Any]]] = None) -> int:
    """
    Warn once, two days before the deadline, on rows still in `available` / `ongoing`.

    The `deadline_heads_up_sent` flag is what makes this one-time-only, and it is only
    set *after* a successful send -- a failed send is retried on the next run rather
    than being silently lost. (Section 3.1 resets the flag when a poster moves the
    deadline, which is what lets the warning correctly re-fire.)

    Returns the number of heads-ups actually sent.
    """
    rows = active_rows if active_rows is not None else await _fetch_active_applications()
    sent = 0

    for app in rows:
        if app.get("deadline_heads_up_sent"):
            continue
        deadline = _effective_deadline(app)
        phone = _phone(app)
        if not deadline or not phone:
            continue
        if (deadline - today).days != HEADS_UP_DAYS:
            continue

        try:
            await send_deadline_heads_up_notification(phone, _title(app), _display_date(deadline))
            await _update_application(app["id"], {"deadline_heads_up_sent": True})
            sent += 1
            logger.info(
                f"SCHEDULER_HEADS_UP_SENT: application_id={app['id']} "
                f"deadline={deadline.isoformat()} phone_number={phone}"
            )
        except Exception:
            logger.exception(f"SCHEDULER_HEADS_UP_FAILED: application_id={app.get('id')}")

    return sent


# ============================================================
# PASS 2 -- EXPIRY / AUTO-CLEANUP (Section 7.2)
# ============================================================

async def run_expiry_pass(today: date, active_rows: Optional[List[Dict[str, Any]]] = None) -> int:
    """
    Delete stale `available` / `ongoing` rows whose deadline has passed.

    Deliberately silent: the user is not chased about an opportunity they never
    acted on (Section 7.2). Rows awaiting a result or already scheduled are never
    touched -- `scheduled`/`under_review` are still live decisions, so expiry only
    looks at ACTIVE_STATUSES.

    Returns the number of rows deleted.
    """
    rows = active_rows if active_rows is not None else await _fetch_active_applications()
    deleted = 0

    for app in rows:
        deadline = _effective_deadline(app)
        if not deadline or today <= deadline:
            continue
        try:
            await _delete_application(app["id"])
            deleted += 1
            logger.info(
                f"SCHEDULER_EXPIRED_DELETED: application_id={app['id']} "
                f"status={app.get('status')} deadline={deadline.isoformat()}"
            )
        except Exception:
            logger.exception(f"SCHEDULER_EXPIRY_FAILED: application_id={app.get('id')}")

    return deleted


# ============================================================
# PASS 3 + 4 -- REMINDER BATCHING & RESULT CHECK (Sections 7.3 / 7.4)
# ============================================================

async def _send_reminder(app: Dict[str, Any], phone_number: str) -> None:
    """Send the message that fits this row's current status."""
    status = app.get("status")
    opportunity = _opportunity(app)

    if status == "available":
        # Re-send the New Match Notification: its Apply Now / Remind Me Later / Ignore
        # buttons are the ones that can still move an untouched match forward.
        await send_new_match_notification(
            to=phone_number,
            title=_title(app),
            poster_name=(opportunity.get("posters") or {}).get("display_name") or "",
            description=opportunity.get("description") or "",
            application_id=app["id"],
            application_start_date=opportunity.get("application_start_date"),
            application_deadline=opportunity.get("application_deadline"),
        )
        return

    if status == "under_review":
        await send_outcome_check_notification(
            to=phone_number,
            title=_title(app),
            application_id=app["id"],
        )
        return

    # ongoing
    deadline = _effective_deadline(app)
    await send_ongoing_checkin_notification(
        to=phone_number,
        title=_title(app),
        application_id=app["id"],
        deadline=_display_date(deadline) if deadline else None,
    )


def _next_reminder_after_send(status: str, now: datetime) -> datetime:
    """
    When an unanswered check-in should be repeated from.

    `under_review` recurs every 3 days (8.2/8.4: the outcome check keeps asking until
    it gets a Yes or No); everything else uses the +2 day default that Section 5.2 /
    6.1 promise when the user doesn't pick a time. Advancing the timestamp on send is
    what stops the same reminder firing every single day.
    """
    days = OUTCOME_RECHECK_DAYS if status == "under_review" else REMINDER_DEFAULT_DAYS
    return now + timedelta(days=days)


async def run_reminder_pass(today: date) -> Tuple[int, int]:
    """
    Batch and send everything due today (Sections 7.3 + 7.4).

    Grouped by user: at most MAX_REMINDERS_PER_USER_PER_DAY go out, closest deadline
    first; the remainder are pushed to tomorrow, where they are re-sorted from scratch
    against whatever else is due then.

    Returns (reminders_sent, reminders_deferred).
    """
    now = _now_utc()
    due_rows = await _fetch_due_applications(_due_cutoff_utc(today))

    by_user: Dict[str, List[Dict[str, Any]]] = {}
    for app in due_rows:
        user_id = app.get("user_id")
        if user_id:
            by_user.setdefault(user_id, []).append(app)

    sent = 0
    deferred = 0
    tomorrow = now + timedelta(days=1)

    for user_id, rows in by_user.items():
        rows.sort(key=_deadline_sort_key)

        if len(rows) > MAX_REMINDERS_PER_USER_PER_DAY:
            send_now = rows[:MAX_REMINDERS_PER_USER_PER_DAY]
            push_to_tomorrow = rows[MAX_REMINDERS_PER_USER_PER_DAY:]
        else:
            send_now, push_to_tomorrow = rows, []

        for app in push_to_tomorrow:
            try:
                # Section 7.3: the overflow waits a day, so nothing is dropped and the
                # per-user cap still holds.
                await _update_application(app["id"], {"next_reminder_at": tomorrow.isoformat()})
                deferred += 1
                logger.info(
                    f"SCHEDULER_REMINDER_DEFERRED: application_id={app['id']} "
                    f"user_id={user_id} reason=daily_batch_cap"
                )
            except Exception:
                logger.exception(f"SCHEDULER_DEFER_FAILED: application_id={app.get('id')}")

        for app in send_now:
            phone = _phone(app)
            status = app.get("status")
            if not phone or status not in REMINDABLE_STATUSES:
                logger.warning(
                    f"SCHEDULER_REMINDER_SKIPPED: application_id={app.get('id')} "
                    f"status={status} has_phone={bool(phone)}"
                )
                continue
            try:
                await _send_reminder(app, phone)
                await _update_application(
                    app["id"],
                    {"next_reminder_at": _next_reminder_after_send(status, now).isoformat()},
                )
                sent += 1
                logger.info(
                    f"SCHEDULER_REMINDER_SENT: application_id={app['id']} "
                    f"status={status} user_id={user_id}"
                )
            except Exception:
                # A failed send must not advance the timestamp, so it retries tomorrow.
                logger.exception(f"SCHEDULER_REMINDER_FAILED: application_id={app.get('id')}")

    return sent, deferred


# ============================================================
# ORCHESTRATION
# ============================================================

async def run_daily_scheduler() -> Dict[str, int]:
    """
    Run all four passes once, in order, and return a small summary.

    Each pass is isolated: a failure in one (a bad row, a send error) is logged and the
    others still run, so one problem can't cost the whole day's scheduling. The expiry
    pass runs before the reminder pass on purpose, so an expired row is deleted rather
    than reminded about.
    """
    today = _today()
    logger.info(f"SCHEDULER_START: today={today.isoformat()} timezone={SCHEDULER_TZ}")

    summary = {"heads_up_sent": 0, "expired_deleted": 0, "reminders_sent": 0, "reminders_deferred": 0}

    try:
        active_rows = await _fetch_active_applications()
    except Exception:
        logger.exception("SCHEDULER_FETCH_FAILED: aborting this run")
        return summary

    try:
        summary["heads_up_sent"] = await run_deadline_heads_up_pass(today, active_rows)
    except Exception:
        logger.exception("SCHEDULER_HEADS_UP_PASS_FAILED")

    try:
        summary["expired_deleted"] = await run_expiry_pass(today, active_rows)
    except Exception:
        logger.exception("SCHEDULER_EXPIRY_PASS_FAILED")

    try:
        sent, deferred = await run_reminder_pass(today)
        summary["reminders_sent"] = sent
        summary["reminders_deferred"] = deferred
    except Exception:
        logger.exception("SCHEDULER_REMINDER_PASS_FAILED")

    logger.info(f"SCHEDULER_DONE: {summary}")
    return summary


async def run_tag_dedup() -> Dict[str, Any]:
    """
    Section 10.3's nightly dedup pass: merge near-duplicate custom tags into one canonical
    tag, re-pointing the users and opportunities that referenced the duplicate.

    Deliberately separate from `run_daily_scheduler()`: it has nothing to do with anyone's
    day, and keeping it apart means a tagging problem can never cost a user a reminder.
    """
    logger.info("TAG_DEDUP_START")
    try:
        return await tags.merge_near_duplicate_tags()
    except Exception:
        logger.exception("TAG_DEDUP_FAILED")
        return {
            "groups": 0,
            "duplicates": 0,
            "repointed_user_tags": 0,
            "repointed_opportunity_tags": 0,
            "deleted_tags": 0,
        }


# ============================================================
# APSCHEDULER REGISTRATION (2-Architecture-Doc.md Section 3C, option 1)
# ============================================================

def create_scheduler() -> AsyncIOScheduler:
    """Build (but do not start) both jobs, so tests can inspect them without running either."""
    scheduler = AsyncIOScheduler(timezone=_tz())
    scheduler.add_job(
        run_daily_scheduler,
        CronTrigger(hour=SCHEDULER_HOUR, minute=SCHEDULER_MINUTE, timezone=_tz()),
        id="wave_match_daily_scheduler",
        replace_existing=True,
        coalesce=True,              # one catch-up run, never a burst of them
        misfire_grace_time=3600,    # still run if the process woke up within the hour
    )
    logger.info(
        f"SCHEDULER_REGISTERED: daily at {SCHEDULER_HOUR:02d}:{SCHEDULER_MINUTE:02d} {SCHEDULER_TZ}"
    )

    # Phase N: the second job on the same instance (7-Build-Checklist.md).
    if TAG_DEDUP_ENABLED:
        scheduler.add_job(
            run_tag_dedup,
            CronTrigger(hour=TAG_DEDUP_HOUR, minute=TAG_DEDUP_MINUTE, timezone=_tz()),
            id="wave_match_tag_dedup",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info(
            f"SCHEDULER_REGISTERED: tag dedup nightly at "
            f"{TAG_DEDUP_HOUR:02d}:{TAG_DEDUP_MINUTE:02d} {SCHEDULER_TZ}"
        )
    else:
        logger.info("TAG_DEDUP_DISABLED: TAG_DEDUP_ENABLED is false -- not registering the dedup job")

    return scheduler


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """Start the scheduler's jobs, unless SCHEDULER_ENABLED is turned off. Returns None if disabled."""
    if not SCHEDULER_ENABLED:
        logger.info("SCHEDULER_DISABLED: SCHEDULER_ENABLED is false -- not starting the daily job")
        return None
    scheduler = create_scheduler()
    scheduler.start()
    return scheduler