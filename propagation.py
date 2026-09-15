"""
Poster Edit Propagation (Phase M).

Spec: 3-Full-Product-Logic.md Section 3.1 ("Editing a Post") and
2-Architecture-Doc.md Section 3D ("Poster Edit Propagation").

When a poster edits an opportunity, everyone still tracking it has to be told -- and in
the same pass the parts of their `applications` rows that were *derived* from the
poster's dates have to be brought back in line:

  * `deadline_heads_up_sent` -> reset to false when the deadline moved, so the one-time
    2-day heads-up fires again relative to the new date (Section 3.1's explicit rule).
  * `scheduled_event_date`   -> follow the poster's new `event_start_date`, but only for
    a row whose value still equals the *old* poster value, i.e. one that was actually
    derived from it. A user who typed their own date during the Phase K
    `outcome_event_date` flow keeps their own date.
  * `next_reminder_at` on `under_review` rows -> re-derived from the new `result_date`,
    again only where the current value still matches what the old `result_date` implied.

That "only if it still matches the old derived value" rule is what stops a poster's edit
from silently stomping a value the *user* chose -- their own event date, or a reminder
time they typed in. Values the user owns outright (`custom_deadline` /
`custom_result_date` on manually-added rows) are never touched, and editing a
poster-sourced item never writes back to the opportunity (Section 9.2).

Who gets told: every row still linked to the opportunity -- `available`, `ongoing`,
`under_review` and `scheduled`. Section 3.1's parenthetical names only "available or
ongoing", but that sentence predates `under_review`/`scheduled` existing, and the
matching example says "Everyone tracking this will be notified of the new deadline" --
a user whose accepted event date just moved is exactly who must not be missed. Users who
ignored the post have no row left, so they are excluded automatically, as 3.1 requires.

Nothing here is ever batched: a deadline change is mandatory and goes out immediately
(3.1), which is why this is not routed through the Phase L daily scheduler.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import anyio
from dotenv import load_dotenv

from conversation import _db_semaphore
from database import supabase
from whatsapp import send_opportunity_update_notification

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Every status that still represents a live row for a user tracking this opportunity.
TRACKED_STATUSES = ("available", "ongoing", "under_review", "scheduled")

# Fields compared between the old and new opportunity snapshots. `title` is included
# because it is worth notifying about, but a title change needs no line of its own.
_COMPARED_FIELDS = (
    "title",
    "description",
    "type",
    "application_start_date",
    "application_deadline",
    "result_date",
    "event_start_date",
    "link",
)

# Hour (UTC) used when a poster's date change re-derives a reminder timestamp, matching
# the convention used when those timestamps are first set (Phase J / Phase K).
_DERIVED_REMINDER_HOUR = 9

# Fallback gap when an under_review row loses its result date (Section 8.4).
_NO_RESULT_DATE_DAYS = 3


def _text(value: Any) -> Optional[str]:
    """Normalise a stored value for comparison: blank/None -> None, else a trimmed string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    normalised = str(value).strip()
    return normalised or None


def _date_of(value: Any) -> Optional[date]:
    """Pull a date out of the many shapes Supabase returns (DATE, TIMESTAMPTZ, ISO string)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _display(value: Optional[date]) -> str:
    """Poster-facing date, e.g. 2026-09-25 -> 'Sep 25, 2026'."""
    return f"{value.strftime('%b')} {value.day}, {value.year}" if value else "not set"


def diff_opportunity(old: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
    """
    Return the field names that actually differ between two opportunity snapshots.

    Section 3D is explicit that this comparison happens *before* the write, against the
    row as it was fetched -- otherwise every edit looks like it changed everything and
    the deadline-moved logic fires on unrelated edits.
    """
    return [f for f in _COMPARED_FIELDS if _text(old.get(f)) != _text(new.get(f))]


def build_change_lines(changed: List[str], new: Dict[str, Any]) -> Tuple[List[str], bool]:
    """
    Turn the changed-field list into the plain-language lines the user reads.

    Returns (lines, reminders_adjusted). The flag drives the "Your reminders have been
    adjusted automatically." sentence, which is only honest when a date actually moved.
    Section 3.1 requires the new deadline to be stated explicitly rather than as a
    generic "was updated" line.
    """
    lines: List[str] = []
    reminders_adjusted = False

    if "application_deadline" in changed:
        lines.append(f"\U0001F4C5 Deadline moved to {_display(_date_of(new.get('application_deadline')))}.")
        reminders_adjusted = True
    if "result_date" in changed:
        lines.append(f"\U0001F4C5 Results date is now {_display(_date_of(new.get('result_date')))}.")
        reminders_adjusted = True
    if "event_start_date" in changed:
        lines.append(f"\U0001F4C5 Event date is now {_display(_date_of(new.get('event_start_date')))}.")
        reminders_adjusted = True
    if "application_start_date" in changed:
        lines.append(f"\U0001F4C5 Applications open {_display(_date_of(new.get('application_start_date')))}.")
        reminders_adjusted = True

    if "description" in changed:
        lines.append("The description was updated.")
    if "link" in changed:
        lines.append("The application link was updated.")
    if "type" in changed:
        lines.append("The opportunity type was updated.")

    # A title change contributes no line: the new title is already the message heading.
    if not lines:
        lines.append("The opportunity details were updated.")

    return lines, reminders_adjusted


async def _get_tracked_applications(opportunity_id: str) -> List[Dict[str, Any]]:
    """Every live applications row still linked to this opportunity, with its phone number."""
    def _get():
        return (
            supabase.from_("applications")
            .select("id, user_id, status, next_reminder_at, scheduled_event_date, users(phone_number)")
            .eq("opportunity_id", opportunity_id)
            .in_("status", list(TRACKED_STATUSES))
            .execute()
        )

    async with _db_semaphore:
        result = await anyio.to_thread.run_sync(_get)
    return result.data or []


async def _update_application(application_id: str, fields: Dict[str, Any]) -> None:
    def _update():
        payload = dict(fields)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        return supabase.from_("applications").update(payload).eq("id", application_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_update)


def _derived_next_reminder(result_date: Optional[date]) -> str:
    """The reminder timestamp a result date implies (Section 7.4 / 8.4)."""
    moment = (
        datetime.combine(result_date + timedelta(days=1), time(_DERIVED_REMINDER_HOUR, 0), tzinfo=timezone.utc)
        if result_date
        else datetime.now(timezone.utc) + timedelta(days=_NO_RESULT_DATE_DAYS)
    )
    return moment.isoformat()


def sync_fields_for_row(
    row: Dict[str, Any],
    changed: List[str],
    old: Dict[str, Any],
    new: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Work out the fields THIS user's row needs so it stays consistent with the edit.

    Only poster-derived values are touched, and only when the row's current value still
    matches what the old poster value implied -- so a value the user chose themselves is
    left alone. Returns {} when the row needs no change at all.
    """
    fields: Dict[str, Any] = {}

    if "application_deadline" in changed:
        # Section 3.1: re-arm the one-time 2-day heads-up against the new deadline.
        fields["deadline_heads_up_sent"] = False

    if "event_start_date" in changed and row.get("status") == "scheduled":
        old_event = _date_of(old.get("event_start_date"))
        new_event = _date_of(new.get("event_start_date"))
        current = _date_of(row.get("scheduled_event_date"))
        if current is not None and current == old_event and new_event:
            fields["scheduled_event_date"] = new_event.isoformat()

    if "result_date" in changed and row.get("status") == "under_review":
        old_result = _date_of(old.get("result_date"))
        new_result = _date_of(new.get("result_date"))
        current_date = _date_of(row.get("next_reminder_at"))
        # e.g. Phase J set this to result_date + 1 day; if it still matches, re-derive it.
        if old_result and current_date == old_result + timedelta(days=1):
            fields["next_reminder_at"] = _derived_next_reminder(new_result)

    return fields


async def propagate_opportunity_edit(
    opportunity_id: str,
    old_row: Optional[Dict[str, Any]],
    new_row: Optional[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Notify everyone still tracking this opportunity, and sync their derived fields.

    `old_row` must be the opportunity as it was *before* the update and `new_row` the
    values just written (Section 3D's compare-before-writing rule). Returns a summary for
    logging and tests: notified / rows_synced / changed_fields / notify_failed.

    Never raises for one user's failure, and never lets a sync failure suppress that
    user's notification -- the notification is the mandatory half.
    """
    summary = {"changed_fields": 0, "notified": 0, "rows_synced": 0, "notify_failed": 0}

    if not old_row or not new_row:
        logger.warning(f"PROPAGATION_SKIP: opportunity_id={opportunity_id} missing snapshot")
        return summary

    changed = diff_opportunity(old_row, new_row)
    if not changed:
        logger.info(f"PROPAGATION_SKIP: opportunity_id={opportunity_id} no tracked field changed")
        return summary
    summary["changed_fields"] = len(changed)

    rows = await _get_tracked_applications(opportunity_id)
    title = new_row.get("title") or old_row.get("title") or "Opportunity"
    change_lines, reminders_adjusted = build_change_lines(changed, new_row)
    deadline_changed = "application_deadline" in changed

    logger.info(
        f"PROPAGATION_START: opportunity_id={opportunity_id} changed={changed} "
        f"deadline_changed={deadline_changed} tracked_rows={len(rows)}"
    )

    for row in rows:
        application_id = row.get("id")

        try:
            fields = sync_fields_for_row(row, changed, old_row, new_row)
            if fields:
                await _update_application(application_id, fields)
                summary["rows_synced"] += 1
                logger.info(f"PROPAGATION_SYNCED: application_id={application_id} fields={sorted(fields)}")
        except Exception:
            logger.exception(f"PROPAGATION_SYNC_FAILED: application_id={application_id}")

        phone_number = (row.get("users") or {}).get("phone_number")
        if not phone_number:
            logger.warning(f"PROPAGATION_NOTIFY_SKIP: application_id={application_id} has no phone number")
            continue

        try:
            await send_opportunity_update_notification(
                phone_number, title, change_lines, reminders_adjusted
            )
            summary["notified"] += 1
            logger.info(f"PROPAGATION_NOTIFIED: application_id={application_id} deadline_changed={deadline_changed}")
        except Exception:
            summary["notify_failed"] += 1
            logger.exception(f"PROPAGATION_NOTIFY_FAILED: application_id={application_id}")

    logger.info(f"PROPAGATION_DONE: opportunity_id={opportunity_id} {summary}")
    return summary