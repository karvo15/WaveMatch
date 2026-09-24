"""
verify_reminder_parser.py -- the Section 14.2 reminder-time parser, offline.

No database, no network: only the pure functions in application_flow that turn a
free-text reply into (when, phrase, exact). It exists because a parse failure is
invisible in production -- the bot answers with the +2 day default either way, so a
discarded time and a deliberate "default" look identical to the user. Pinning the
accepted and rejected forms down explicitly is the only way to notice a regression.

Run:  python verify_reminder_parser.py
"""
import sys
from datetime import datetime, timedelta, timezone

from application_flow import (
    REMINDER_DEFAULT_DAYS,
    _message_type,
    _normalise_time_text,
    _parse_reminder_time,
    _parse_strict_time,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
FALLBACK = "in %d days" % REMINDER_DEFAULT_DAYS

PASS = 0
FAIL = []


def check(label, got, want):
    global PASS
    if got == want:
        PASS += 1
    else:
        FAIL.append("%-46s got %r want %r" % (label, got, want))


# (reply, expected offset from NOW, or None for the +2 day default; expected phrase)
RELATIVE = [
    # Section 14.2 canonical form -- pre-existing behaviour, must not regress
    ("in 3 days", timedelta(days=3), "in 3 day(s)"),
    ("in 5 hours", timedelta(hours=5), "in 5 hour(s)"),
    ("in 30 minutes", timedelta(minutes=30), "in 30 minute(s)"),
    ("In 1 Hour", timedelta(hours=1), "in 1 hour(s)"),
    # the bare form, no "in" -- what people actually type
    ("1 hour", timedelta(hours=1), "in 1 hour(s)"),
    ("3 days", timedelta(days=3), "in 3 day(s)"),
    ("5 hours", timedelta(hours=5), "in 5 hour(s)"),
    ("30 minutes", timedelta(minutes=30), "in 30 minute(s)"),
    # keyboard abbreviations
    ("1h", timedelta(hours=1), "in 1 hour(s)"),
    ("in 1h", timedelta(hours=1), "in 1 hour(s)"),
    ("in 2 hrs", timedelta(hours=2), "in 2 hour(s)"),
    ("15m", timedelta(minutes=15), "in 15 minute(s)"),
    ("in 10 min", timedelta(minutes=10), "in 10 minute(s)"),
    ("1d", timedelta(days=1), "in 1 day(s)"),
    # articles
    ("in an hour", timedelta(hours=1), "in 1 hour(s)"),
    ("an hour", timedelta(hours=1), "in 1 hour(s)"),
    ("in a day", timedelta(days=1), "in 1 day(s)"),
    ("in one week", timedelta(weeks=1), "in 1 week(s)"),
    # weeks
    ("in 1 week", timedelta(weeks=1), "in 1 week(s)"),
    ("in 2 weeks", timedelta(weeks=2), "in 2 week(s)"),
    ("2 wks", timedelta(weeks=2), "in 2 week(s)"),
    # whitespace / punctuation noise
    ("  in   2   hours  ", timedelta(hours=2), "in 2 hour(s)"),
    ("in 2 hours.", timedelta(hours=2), "in 2 hour(s)"),
    # still unreadable -> Section 5.2's +2 day default, which must NOT be loosened
    ("", None, FALLBACK),
    (None, None, FALLBACK),
    ("default", None, FALLBACK),
    ("in 0 hours", None, FALLBACK),
    ("in 1 hour please", None, FALLBACK),
    ("after 1 hour", None, FALLBACK),
    ("never", None, FALLBACK),   # honoured earlier as a deletion keyword, never a time
    ("menu", None, FALLBACK),
    ("cancel", None, FALLBACK),
]

for reply, offset, phrase in RELATIVE:
    when, human = _parse_reminder_time(reply, NOW)
    label = "reply %r" % (reply,)
    want_when = NOW + offset if offset else NOW + timedelta(days=REMINDER_DEFAULT_DAYS)
    check(label + " -> when", when, want_when)
    check(label + " -> phrase", human, phrase)
    check(label + " -> exact", _parse_strict_time(reply, NOW) is not None, offset is not None)

# Absolute dates (Section 14.2). NOW is 2026-09-21, so a bare "Sep 20" rolls to next year.
ABSOLUTE = [
    ("Oct 5", "2026-10-05"),
    ("oct 5", "2026-10-05"),
    ("sept 20", "2027-09-20"),
    ("20/09", "2027-09-20"),
    ("05/10/2026", "2026-10-05"),
    ("20/09/2026", "2026-09-20"),   # explicit year taken literally, even if past
    ("2026-10-05", "2026-10-05"),
]
for reply, want_iso in ABSOLUTE:
    strict = _parse_strict_time(reply, NOW)
    check("absolute %r" % reply, strict.date().isoformat() if strict else None, want_iso)
    check("absolute %r 09:00" % reply, (strict.hour, strict.minute) if strict else None, (9, 0))
    _, human = _parse_reminder_time(reply, NOW)
    check("absolute %r phrase" % reply, human.startswith("on "), True)

check("normalise 'Sept 20'", _normalise_time_text("Sept 20"), "sep 20")
check("normalise 'IN   2  Hours.'", _normalise_time_text("IN   2  Hours."), "in 2 hours")


# _message_type -- the field the new diagnostic reads. An empty reply from a button tap
# and an empty reply from a blank text message are NOT the same failure.
def payload(msg):
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


check("type of a text reply", _message_type(payload({"type": "text", "text": {"body": "in 1 hour"}})), "text")
check("type of a button tap", _message_type(payload({"type": "button", "button": {"payload": "apply_now_x"}})), "button")
check("type of an interactive tap", _message_type(payload({"type": "interactive"})), "interactive")
check("type of a voice note", _message_type(payload({"type": "audio"})), "audio")
check("type of a status event", _message_type({"entry": [{"changes": [{"value": {}}]}]}), None)
check("type of garbage", _message_type({}), None)

print("=" * 78)
print("REMINDER PARSER: %d/%d checks passed" % (PASS, PASS + len(FAIL)))
print("=" * 78)
for line in FAIL:
    print("  FAIL " + line)
sys.exit(1 if FAIL else 0)