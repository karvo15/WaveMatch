"""
Verification harness for exact-time reminders (Section 14.2) and the two scheduler drivers.

Covers what was added for A1 + C:
  * only a time the user genuinely chose sets reminder_is_exact
  * run_exact_reminder_pass sends at the chosen moment, then hands the row back
  * the daily pass ignores exact rows until they are clearly stranded
  * run_catchup_daily_scheduler respects the marker, the hour, and fails open
  * POST /internal/run-scheduler is closed without the shared secret

Run: python verify_exact_reminders.py
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import application_flow
import main
import scheduler

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("[PASS] " + name)
    else:
        FAILED.append(name)
        print("[FAIL] " + name + " " + str(detail))


def row(app_id, status, *, exact=True, reminder_at=None, deadline=None,
        phone="250700000000", user=None):
    return {
        "id": app_id,
        "user_id": user or ("user-" + app_id),
        "status": status,
        "reminder_is_exact": exact,
        "next_reminder_at": (reminder_at or datetime.now(timezone.utc)).isoformat(),
        "custom_deadline": deadline.isoformat() if deadline else None,
        "deadline_heads_up_sent": False,
        "users": {"phone_number": phone},
        "opportunities": {
            "title": "Test Opportunity",
            "description": "desc",
            "application_start_date": None,
            "application_deadline": deadline.isoformat() if deadline else None,
            "result_date": None,
            "posters": {"display_name": "Poster"},
        },
    }


def test_flag_decision():
    print("\n--- 1. which replies count as an exact-time reminder ---")
    cases = [
        ("in 1 hour", True), ("in 5 hours", True), ("in 3 days", True),
        ("20/09/2026", True), ("Sept 20", True),
        ("default", False), ("", False), ("tomorrow", False),
        # "5 days" and "in 2 weeks" were asserted False here, which is exactly what made
        # the parser gap look intentional rather than wrong: a reply typed without the
        # leading "in", and every week-based reply, were silently replaced by the +2 day
        # default -- and because the confirmation is built from the same failed parse,
        # the bot still said "in 2 days", so the user never saw their time discarded.
        # Both are ordinary replies, so both are True now (see verify_reminder_parser.py
        # for the full accepted/rejected matrix).
        ("5 days", True), ("in 2 weeks", True), ("1 hour", True),
        ("an hour", True), ("1h", True), ("in 1 week", True),
        ("in 1 hour please", False), ("after 1 hour", False),
    ]
    for text, expected in cases:
        got = application_flow._parse_strict_time(text) is not None
        check("exact flag for %r is %s" % (text, expected), got == expected, "(got %s)" % got)


def test_exact_pass():
    print("\n--- 2. the fine-grained exact-time pass ---")
    now = datetime(2026, 9, 17, 16, 44, 52, tzinfo=timezone.utc)
    sent, updates = [], []
    originals = (
        scheduler._fetch_exact_due_applications,
        scheduler._send_reminder,
        scheduler._update_application,
    )

    async def fake_fetch(_now):
        return [
            row("due-1", "available", reminder_at=now - timedelta(minutes=1)),
            row("expired-1", "available", deadline=(now - timedelta(days=1)).date()),
        ]

    async def fake_send(app, phone):
        sent.append((app["id"], phone))

    async def fake_update(app_id, fields):
        updates.append((app_id, fields))

    scheduler._fetch_exact_due_applications = fake_fetch
    scheduler._send_reminder = fake_send
    scheduler._update_application = fake_update
    try:
        count = asyncio.run(scheduler.run_exact_reminder_pass(now))
    finally:
        (scheduler._fetch_exact_due_applications,
         scheduler._send_reminder,
         scheduler._update_application) = originals

    check("sends the row whose chosen time has arrived",
          count == 1 and [s[0] for s in sent] == ["due-1"], "(sent=%s)" % sent)
    check("skips a row whose deadline has already passed",
          all(s[0] != "expired-1" for s in sent), "(sent=%s)" % sent)
    check("hands the row back to the normal rhythm",
          updates and updates[0][0] == "due-1" and updates[0][1].get("reminder_is_exact") is False,
          "(updates=%s)" % updates)
    expected = now + timedelta(days=2)
    gap_ok = False
    if updates:
        got_at = datetime.fromisoformat(updates[0][1]["next_reminder_at"])
        gap_ok = abs(got_at - expected) < timedelta(seconds=1)
    check("advances next_reminder_at by the default gap", gap_ok, "(updates=%s)" % updates)


def test_exact_pass_send_failure():
    print("\n--- 3. a failed exact send waits a day, not a tick ---")
    now = datetime(2026, 9, 17, 16, 44, 52, tzinfo=timezone.utc)
    updates = []
    originals = (
        scheduler._fetch_exact_due_applications,
        scheduler._send_reminder,
        scheduler._update_application,
    )

    async def fake_fetch(_now):
        return [row("due-2", "available", reminder_at=now - timedelta(minutes=1))]

    async def fake_send(_app, _phone):
        raise RuntimeError("window closed (131047)")

    async def fake_update(app_id, fields):
        updates.append((app_id, fields))

    scheduler._fetch_exact_due_applications = fake_fetch
    scheduler._send_reminder = fake_send
    scheduler._update_application = fake_update
    try:
        count = asyncio.run(scheduler.run_exact_reminder_pass(now))
    finally:
        (scheduler._fetch_exact_due_applications,
         scheduler._send_reminder,
         scheduler._update_application) = originals

    check("a failed send counts as nothing sent", count == 0, "(count=%s)" % count)
    retried = False
    if updates:
        got_at = datetime.fromisoformat(updates[0][1]["next_reminder_at"])
        retried = abs(got_at - (now + timedelta(days=1))) < timedelta(seconds=1)
    check("reschedules a day out so it cannot retry every tick", retried, "(updates=%s)" % updates)


def test_daily_pass_filter():
    print("\n--- 4. the daily pass leaves exact rows to the exact pass ---")
    now = datetime.now(timezone.utc)
    sent = []
    originals = (
        scheduler._fetch_due_applications,
        scheduler._send_reminder,
        scheduler._update_application,
    )

    async def fake_fetch(_cutoff):
        return [
            row("exact-fresh", "available", reminder_at=now - timedelta(minutes=5)),
            row("exact-stranded", "available", reminder_at=now - timedelta(days=3)),
            row("normal", "available", exact=False, reminder_at=now - timedelta(days=1)),
        ]

    async def fake_send(app, phone):
        sent.append(app["id"])

    async def fake_update(_app_id, _fields):
        return None

    scheduler._fetch_due_applications = fake_fetch
    scheduler._send_reminder = fake_send
    scheduler._update_application = fake_update
    try:
        scheduler.run_reminder_pass
        asyncio.run(scheduler.run_reminder_pass(now.date()))
    finally:
        (scheduler._fetch_due_applications,
         scheduler._send_reminder,
         scheduler._update_application) = originals

    check("leaves a freshly-due exact row alone", "exact-fresh" not in sent, "(sent=%s)" % sent)
    check("picks up a stranded exact row itself", "exact-stranded" in sent, "(sent=%s)" % sent)
    check("still sends ordinary rows", "normal" in sent, "(sent=%s)" % sent)


def test_catchup():
    print("\n--- 5. the marker-guarded daily catch-up ---")
    tz = scheduler._tz()
    today = datetime(2026, 9, 18).date()
    scheduled = datetime.combine(
        today, scheduler.time(scheduler.SCHEDULER_HOUR, scheduler.SCHEDULER_MINUTE), tzinfo=tz
    )
    before = (scheduled - timedelta(hours=1)).astimezone(timezone.utc)
    after = (scheduled + timedelta(hours=1)).astimezone(timezone.utc)

    originals = (scheduler._has_daily_run, scheduler._mark_daily_run, scheduler.run_daily_scheduler)
    calls = {"daily": 0, "marked": []}

    async def fake_daily():
        calls["daily"] += 1
        return {"reminders_sent": 0}

    async def fake_mark(run_date):
        calls["marked"].append(run_date.isoformat())

    try:
        async def marked_true(_d):
            return True

        async def marked_false(_d):
            return False

        async def marked_raises(_d):
            raise RuntimeError("marker table missing")

        scheduler.run_daily_scheduler = fake_daily
        scheduler._mark_daily_run = fake_mark

        scheduler._has_daily_run = marked_false
        early = asyncio.run(scheduler.run_catchup_daily_scheduler(before))
        check("does nothing before the scheduled hour", early is None and calls["daily"] == 0,
              "(result=%s calls=%s)" % (early, calls))

        result = asyncio.run(scheduler.run_catchup_daily_scheduler(after))
        check("runs the day when it is past the hour and unmarked",
              result is not None and calls["daily"] == 1, "(result=%s calls=%s)" % (result, calls))
        check("marks the day so the other driver stands down",
              calls["marked"] == [today.isoformat()], "(marked=%s)" % calls["marked"])

        calls["daily"] = 0
        scheduler._has_daily_run = marked_true
        again = asyncio.run(scheduler.run_catchup_daily_scheduler(after))
        check("stands down when the day is already marked",
              again is None and calls["daily"] == 0, "(result=%s calls=%s)" % (again, calls))

        calls["daily"] = 0
        scheduler._has_daily_run = marked_raises
        failed_open = asyncio.run(scheduler.run_catchup_daily_scheduler(after))
        check("fails open: a marker read error still runs the day",
              failed_open is not None and calls["daily"] == 1,
              "(result=%s calls=%s)" % (failed_open, calls))
    finally:
        (scheduler._has_daily_run,
         scheduler._mark_daily_run,
         scheduler.run_daily_scheduler) = originals


def test_endpoint():
    print("\n--- 6. POST /internal/run-scheduler ---")
    from starlette.requests import Request

    def make_request(secret=None):
        headers = [(b"x-tick-secret", secret.encode())] if secret is not None else []
        return Request({
            "type": "http", "method": "POST", "path": "/internal/run-scheduler",
            "headers": headers, "query_string": b"", "scheme": "http",
            "server": ("testserver", 80), "client": ("testclient", 12345),
        })

    def status_of(resp):
        # A dict return is serialised to a 200 by FastAPI; a JSONResponse carries its own.
        return getattr(resp, "status_code", 200)

    def body_of(resp):
        if isinstance(resp, dict):
            return resp
        try:
            return json.loads(bytes(resp.body).decode())
        except Exception:
            return {}

    calls = {"exact": 0, "daily": 0}
    originals = (
        main.INTERNAL_TICK_SECRET,
        main.run_exact_reminder_pass,
        main.run_catchup_daily_scheduler,
    )

    async def fake_exact():
        calls["exact"] += 1
        return 2

    async def fake_daily():
        calls["daily"] += 1
        return {"reminders_sent": 1}

    main.INTERNAL_TICK_SECRET = "s3cret"
    main.run_exact_reminder_pass = fake_exact
    main.run_catchup_daily_scheduler = fake_daily
    try:
        no_header = asyncio.run(main.run_scheduler_tick(make_request()))
        wrong = asyncio.run(main.run_scheduler_tick(make_request("wrong")))
        after_rejects = dict(calls)
        ok = asyncio.run(main.run_scheduler_tick(make_request("s3cret")))
        after_ok = dict(calls)
        main.INTERNAL_TICK_SECRET = ""
        disabled = asyncio.run(main.run_scheduler_tick(make_request("s3cret")))
    finally:
        (main.INTERNAL_TICK_SECRET,
         main.run_exact_reminder_pass,
         main.run_catchup_daily_scheduler) = originals

    check("rejects a request with no secret", status_of(no_header) == 401,
          "(status=%s)" % status_of(no_header))
    check("rejects a request with the wrong secret", status_of(wrong) == 401,
          "(status=%s)" % status_of(wrong))
    check("a rejected tick sends nothing at all", after_rejects == {"exact": 0, "daily": 0},
          "(calls=%s)" % after_rejects)
    check("accepts the right secret and runs both drivers",
          status_of(ok) == 200 and after_ok == {"exact": 1, "daily": 1},
          "(status=%s calls=%s)" % (status_of(ok), after_ok))
    body = body_of(ok)
    check("reports what it did", body.get("exact_reminders_sent") == 2 and body.get("daily_pass_ran") is True,
          "(body=%s)" % body)
    check("is disabled entirely when no secret is configured", status_of(disabled) == 503,
          "(status=%s)" % status_of(disabled))


def main_run():
    print("=" * 68)
    print("EXACT-TIME REMINDERS + TWO SCHEDULER DRIVERS -- VERIFICATION")
    print("=" * 68)
    test_flag_decision()
    test_exact_pass()
    test_exact_pass_send_failure()
    test_daily_pass_filter()
    test_catchup()
    test_endpoint()
    print("\n" + "=" * 68)
    print("RESULT: %d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("  FAILED: " + name)
    print("=" * 68)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main_run())
