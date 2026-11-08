"""Pure validation of operational paper-broker session evidence.

This module has no I/O or order authority. Its raw formats match Alpaca's paper
/v2/calendar (YYYY-MM-DD plus HH:MM) and /v2/clock (boolean plus aware timestamps).
It does not reinterpret fixed/adaptive study inputs or change their protocols.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .config import ET

VERSION = "operational-session-v1"
EVIDENCE_VERSION = "operational-session-evidence-v1"
CLOCK_MAX_AGE_SECONDS = 30
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})"
)


class SessionValidationError(ValueError):
    """A stable diagnostic code, never the untrusted provider response."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CalendarDay:
    day: str
    opened: datetime | None
    closed: datetime | None

    @property
    def state(self):
        return "session" if self.opened is not None else "non_session"


@dataclass(frozen=True)
class MarketClock:
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime


@dataclass(frozen=True)
class SessionAssessment:
    state: str
    assessed_at: datetime | None
    calendar: CalendarDay | None
    clock: MarketClock | None
    reasons: tuple[str, ...] = ()

    @property
    def market_open(self):
        return self.state == "open"

    @property
    def market_window(self):
        """No usable market-execution deadline on missing/conflicting evidence."""
        if self.market_open:
            return self.calendar.opened, self.calendar.closed
        return None

    def summary(self):
        def stamp(value):
            return value.isoformat() if value is not None else None

        return {
            "validation_version": VERSION,
            "state": self.state,
            "assessed_at": stamp(self.assessed_at),
            "market_open": self.market_open,
            "reason_codes": list(self.reasons),
            "calendar": {
                "state": self.calendar.state if self.calendar else "unknown",
                "day": self.calendar.day if self.calendar else None,
                "open_at": stamp(self.calendar.opened) if self.calendar else None,
                "close_at": stamp(self.calendar.closed) if self.calendar else None,
            },
            "clock": {
                "reported_is_open": self.clock.is_open if self.clock else None,
                "timestamp": stamp(self.clock.timestamp) if self.clock else None,
                "next_open": stamp(self.clock.next_open) if self.clock else None,
                "next_close": stamp(self.clock.next_close) if self.clock else None,
            },
        }


def _day(value):
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        raise SessionValidationError("requested_day_invalid")
    return parsed


def parse_calendar(raw, day):
    """Only an exact empty JSON list certifies a day with no regular session."""
    _day(day)
    if not isinstance(raw, list):
        raise SessionValidationError("calendar_not_list")
    if not raw:
        return CalendarDay(day, None, None)
    if len(raw) != 1:
        raise SessionValidationError("calendar_cardinality")
    row = raw[0]
    if not isinstance(row, dict):
        raise SessionValidationError("calendar_row_not_object")
    if row.get("date") != day:
        raise SessionValidationError("calendar_date_mismatch")
    values = []
    for name in ("open", "close"):
        value = row.get(name)
        if not isinstance(value, str) or not _TIME.fullmatch(value):
            raise SessionValidationError("calendar_time_format")
        values.append(datetime.fromisoformat(day + "T" + value).replace(tzinfo=ET))
    opened, closed = values
    if opened >= closed:
        raise SessionValidationError("calendar_time_order")
    return CalendarDay(day, opened, closed)


def _clock_stamp(value, field):
    try:
        if not isinstance(value, str) or not _STAMP.fullmatch(value):
            raise ValueError("Unsupported timestamp shape")
        parsed = datetime.fromisoformat(
            value.replace("t", "T").replace("z", "Z").replace("Z", "+00:00")
        )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timestamp is not aware")
        return parsed.astimezone(ET)
    except (TypeError, ValueError, OverflowError):
        raise SessionValidationError("clock_" + field + "_invalid") from None


def parse_market_clock(raw):
    if not isinstance(raw, dict):
        raise SessionValidationError("clock_not_object")
    if type(raw.get("is_open")) is not bool:
        raise SessionValidationError("clock_is_open_not_boolean")
    current, opened, closed = (
        _clock_stamp(raw.get(field), field) for field in ("timestamp", "next_open", "next_close")
    )
    if opened < current or closed < current:
        raise SessionValidationError("clock_next_event_in_past")
    if not raw["is_open"] and opened >= closed:
        raise SessionValidationError("clock_closed_event_order")
    # At the exact opening instant, next_open can be inclusive of timestamp.
    if raw["is_open"] and (opened == closed or current < opened < closed):
        raise SessionValidationError("clock_open_event_order")
    return MarketClock(current, raw["is_open"], opened, closed)


def _observed_at(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise SessionValidationError("local_observation_time_invalid")
    return now.astimezone(ET)


def evaluate_session(calendar, clock, now):
    """Reevaluate retained evidence at actual use time; it never becomes fresher."""
    now = _observed_at(now)

    def result(state, *reasons):
        return SessionAssessment(state, now, calendar, clock, reasons)

    if now.date().isoformat() != calendar.day:
        return result("unknown", "calendar_day_not_current")
    age = (now - clock.timestamp).total_seconds()
    if abs(age) > CLOCK_MAX_AGE_SECONDS:
        return result("unknown", "clock_timestamp_stale" if age > 0 else "clock_timestamp_future")
    if calendar.state == "non_session":
        if clock.is_open or any(
            stamp.date().isoformat() == calendar.day
            for stamp in (clock.next_open, clock.next_close)
        ):
            return result("unknown", "non_session_clock_conflict")
        return result("non_session")
    opened, closed = calendar.opened, calendar.closed
    if clock.is_open:
        if not opened <= clock.timestamp < closed:
            return result("unknown", "clock_open_outside_calendar_session")
        if clock.next_close != closed:
            return result("unknown", "clock_calendar_close_mismatch")
    elif clock.timestamp < opened:
        if clock.next_open != opened or clock.next_close != closed:
            return result("unknown", "clock_calendar_upcoming_session_mismatch")
    elif clock.timestamp < closed:
        return result("unknown", "clock_closed_during_calendar_session")
    # Preserve the actual-use bounds even when a timely clock response straddles
    # an opening/closing instant. A past-open receipt cannot extend the close.
    if now < opened:
        return result("before_open")
    if now >= closed or clock.timestamp >= closed:
        return result("after_close")
    if not clock.is_open:
        return result("before_open", "broker_open_not_yet_confirmed")
    return result("open")


def assess_session(calendar_raw, clock_raw, day, now):
    """Return explicit unknown diagnostics for malformed raw provider evidence."""
    calendar, clock, observed = None, None, None
    errors = []
    for parser, args, field in (
        (parse_calendar, (calendar_raw, day), "calendar"),
        (parse_market_clock, (clock_raw,), "clock"),
        (_observed_at, (now,), "observed"),
    ):
        try:
            value = parser(*args)
            if field == "calendar":
                calendar = value
            elif field == "clock":
                clock = value
            else:
                observed = value
        except SessionValidationError as exc:
            errors.append(exc.code)
    if errors:
        return SessionAssessment("unknown", observed, calendar, clock, tuple(errors))
    return evaluate_session(calendar, clock, observed)


def assess_evidence(evidence, now):
    """Reassess complete retained sources, never a cached Boolean assessment.

    Receipt times establish availability, not renewed provider freshness. Hash
    references remain provenance for the caller; this pure function has no Store.
    """
    try:
        observed = _observed_at(now)
    except SessionValidationError as exc:
        return SessionAssessment("unknown", None, None, None, (exc.code,))
    if not isinstance(evidence, dict):
        return SessionAssessment("unknown", observed, None, None, ("session_evidence_missing",))
    if evidence.get("version") != EVIDENCE_VERSION:
        return SessionAssessment("unknown", observed, None, None, ("session_evidence_version",))
    result = assess_session(
        evidence.get("calendar_raw"), evidence.get("clock_raw"), evidence.get("day"), observed
    )
    errors = []
    source_errors = evidence.get("source_errors")
    if not isinstance(source_errors, list) or source_errors:
        errors.append("session_source_unavailable")
    for key in ("calendar_receipt", "clock_receipt"):
        metadata = evidence.get(key)
        try:
            if not isinstance(metadata, dict):
                raise SessionValidationError(key + "_invalid")
            requested = _clock_stamp(metadata.get("requested_at"), "receipt_requested_at")
            received = _clock_stamp(metadata.get("received_at"), "receipt_received_at")
        except SessionValidationError:
            errors.append(key + "_invalid")
            continue
        if requested > received or received > observed:
            errors.append(key + "_chronology")
    if errors:
        return SessionAssessment(
            "unknown", observed, result.calendar, result.clock, (*result.reasons, *errors)
        )
    return result
