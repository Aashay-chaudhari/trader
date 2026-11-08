import copy
import json
from datetime import datetime, timedelta

import pytest

from agent_trader.runtime.config import ET
from agent_trader.runtime.operational_session import (
    SessionValidationError,
    EVIDENCE_VERSION,
    VERSION,
    assess_evidence,
    assess_session,
    evaluate_session,
    parse_calendar,
    parse_market_clock,
)


def instant(clock="10:00:00", day="2026-11-09"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=ET)


def calendar(day="2026-11-09", close="16:00"):
    return [{"date": day, "open": "09:30", "close": close}]


def clock(now=None, *, is_open=True, close="16:00", next_day="2026-11-10"):
    now = now or instant()
    next_open = instant("09:30:00", next_day)
    next_close = instant(close + ":00", now.date().isoformat())
    return {
        "timestamp": now.isoformat(),
        "is_open": is_open,
        "next_open": next_open.isoformat(),
        "next_close": next_close.isoformat(),
    }


def assessment(rows=None, market_clock=None, now=None):
    now = now or instant()
    return assess_session(
        calendar() if rows is None else rows,
        clock(now) if market_clock is None else market_clock,
        now.date().isoformat(),
        now,
    )


def test_actual_two_get_provider_shapes_are_compatible_without_live_requests():
    # Safe fields copied from the authorized Nov7 schema receipt; no account data.
    rows = [
        {
            "close": "13:00",
            "date": "2026-11-27",
            "open": "09:30",
            "session_close": "1700",
            "session_open": "0400",
            "settlement_date": "2026-11-30",
        }
    ]
    parsed = parse_calendar(rows, "2026-11-27")
    assert parsed.opened == instant("09:30:00", "2026-11-27")
    assert parsed.closed == instant("13:00:00", "2026-11-27")
    weekend_clock = {
        "is_open": False,
        "next_close": "2026-11-09T16:00:00-05:00",
        "next_open": "2026-11-09T09:30:00-05:00",
        "timestamp": "2026-11-07T18:29:05.028462-05:00",
    }
    received = datetime.fromisoformat("2026-11-07T23:29:03.571529+00:00")
    # [] for Nov7 is a synthetic non-session fixture, not a third live receipt.
    result = assess_session([], weekend_clock, "2026-11-07", received)
    assert result.state == "non_session"
    assert result.market_window is None
    assert result.summary()["validation_version"] == VERSION
    json.dumps(result.summary(), allow_nan=False)


@pytest.mark.parametrize("raw", [None, {}, False, "", 0, ()])
def test_only_empty_json_list_can_certify_non_session(raw):
    with pytest.raises(SessionValidationError, match="calendar_not_list"):
        parse_calendar(raw, "2026-11-09")
    result = assess_session(raw, clock(), "2026-11-09", instant())
    assert result.state == "unknown" and result.market_window is None
    assert result.summary()["calendar"]["state"] == "unknown"


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda rows: rows.append(copy.deepcopy(rows[0])), "calendar_cardinality"),
        (lambda rows: rows.append({**rows[0], "close": "13:00"}), "calendar_cardinality"),
        (lambda rows: rows[0].update(date="2026-11-06"), "calendar_date_mismatch"),
        (lambda rows: rows[0].pop("date"), "calendar_date_mismatch"),
        (lambda rows: rows.__setitem__(0, None), "calendar_row_not_object"),
        (lambda rows: rows[0].update(open="16:00", close="09:30"), "calendar_time_order"),
        (lambda rows: rows[0].update(open="16:00"), "calendar_time_order"),
    ],
)
def test_calendar_identity_multiplicity_and_time_order_fail_closed(change, reason):
    rows = calendar()
    change(rows)
    result = assessment(rows)
    assert result.state == "unknown" and result.reasons == (reason,)
    assert result.market_window is None


@pytest.mark.parametrize(
    "value",
    [
        "9:30",
        "09:30:00",
        "14:30:00+00:00",
        "09:30-05:00",
        "24:00",
        "09:60",
        " 09:30",
        "09:30 ",
        None,
        930,
    ],
)
def test_calendar_requires_documented_raw_hh_mm(value):
    rows = calendar()
    rows[0]["open"] = value
    assert assessment(rows).reasons == ("calendar_time_format",)


@pytest.mark.parametrize(
    "day", ["20261109", "2026-11-9", "2026-02-30", "2026-11-09T00:00:00", None]
)
def test_requested_calendar_day_is_canonical(day):
    with pytest.raises(SessionValidationError, match="requested_day_invalid"):
        parse_calendar([], day)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_clock_open_flag_is_boolean_without_coercion(value):
    raw = clock()
    raw["is_open"] = value
    result = assessment(market_clock=raw)
    assert result.reasons == ("clock_is_open_not_boolean",)
    assert not result.market_open and result.market_window is None


@pytest.mark.parametrize("field", ["timestamp", "next_open", "next_close"])
@pytest.mark.parametrize(
    "value", [None, "2026-11-09T10:00:00", "2026-11-09", 1, "2026-11-09T25:00:00Z"]
)
def test_all_clock_timestamps_require_valid_aware_wire_values(field, value):
    raw = clock()
    raw[field] = value
    result = assessment(market_clock=raw)
    assert result.reasons == ("clock_" + field + "_invalid",)
    assert result.market_window is None


def test_clock_offsets_are_converted_and_nanosecond_z_format_is_accepted():
    raw = clock()
    raw.update(
        timestamp="2026-11-09T15:00:00.123456789Z",
        next_close="2026-11-09T21:00:00Z",
        next_open="2026-11-10T14:30:00+00:00",
    )
    parsed = parse_market_clock(raw)
    assert parsed.timestamp.hour == 10 and parsed.timestamp.microsecond == 123456
    assert parsed.next_close.hour == 16
    result = assessment(market_clock=raw, now=instant() + timedelta(seconds=1))
    assert result.market_open


@pytest.mark.parametrize(
    "age,expected", [(30, "open"), (31, "unknown"), (-30, "open"), (-31, "unknown")]
)
def test_existing_clock_freshness_bounds_are_preserved(age, expected):
    now = instant()
    result = assessment(market_clock=clock(now - timedelta(seconds=age)), now=now)
    assert result.state == expected
    if expected == "unknown":
        assert result.market_window is None


@pytest.mark.parametrize(
    "change,reason",
    [
        (
            lambda raw: raw.update(next_close="2026-11-08T16:00:00-05:00"),
            "clock_next_event_in_past",
        ),
        (lambda raw: raw.update(next_open=raw["next_close"]), "clock_open_event_order"),
        (lambda raw: raw.update(next_open="2026-11-09T12:00:00-05:00"), "clock_open_event_order"),
    ],
)
def test_next_event_chronology_is_not_guessed(change, reason):
    raw = clock()
    change(raw)
    assert assessment(market_clock=raw).reasons == (reason,)


def test_fresh_clock_close_conflict_never_supplies_execution_window():
    now = instant("12:49:00", "2026-11-27")
    raw = clock(now, close="13:00", next_day="2026-11-30")
    result = assessment(calendar("2026-11-27", "16:00"), raw, now)
    assert result.state == "unknown"
    assert result.reasons == ("clock_calendar_close_mismatch",)
    assert result.summary()["calendar"]["close_at"] == "2026-11-27T16:00:00-05:00"
    assert result.summary()["clock"]["next_close"] == "2026-11-27T13:00:00-05:00"
    assert result.market_window is None


def test_conflict_resolves_only_from_new_matching_evidence():
    now = instant("12:49:00", "2026-11-27")
    raw = clock(now, close="13:00", next_day="2026-11-30")
    old_rows = calendar("2026-11-27", "16:00")
    retained = copy.deepcopy(old_rows)
    assert assessment(old_rows, raw, now).state == "unknown"
    corrected = assessment(calendar("2026-11-27", "13:00"), raw, now)
    assert corrected.market_open
    assert corrected.market_window[1] == instant("13:00:00", "2026-11-27")
    assert old_rows == retained  # Validators never replace stored source evidence.


def test_valid_early_close_and_actual_use_boundary_keep_original_deadline():
    now = instant("12:48:00", "2026-11-27")
    rows = calendar("2026-11-27", "13:00")
    raw = clock(now, close="13:00", next_day="2026-11-30")
    result = assessment(rows, raw, now)
    assert result.market_window == (instant("09:30:00", "2026-11-27"), now + timedelta(minutes=12))
    just_before = instant("12:59:59", "2026-11-27")
    retained = parse_market_clock(clock(just_before, close="13:00", next_day="2026-11-30"))
    result = evaluate_session(
        parse_calendar(rows, "2026-11-27"), retained, just_before + timedelta(seconds=1)
    )
    assert result.state == "after_close" and result.market_window is None
    assert retained.next_close == instant("13:00:00", "2026-11-27")


def test_repeated_assessment_cannot_renew_clock_age():
    parsed_calendar = parse_calendar(calendar(), "2026-11-09")
    parsed_clock = parse_market_clock(clock())
    assert evaluate_session(parsed_calendar, parsed_clock, instant()).market_open
    later = evaluate_session(parsed_calendar, parsed_clock, instant() + timedelta(seconds=31))
    assert later.reasons == ("clock_timestamp_stale",)
    assert later.market_window is None


def test_closed_clock_during_declared_session_is_unknown_and_retains_both_receipts():
    now = instant()
    raw = clock(now, is_open=False)
    raw["next_close"] = "2026-11-10T16:00:00-05:00"
    result = assessment(market_clock=raw)
    assert result.reasons == ("clock_closed_during_calendar_session",)
    assert result.calendar is not None and result.clock is not None
    assert result.market_window is None


def test_before_open_clock_confirmation_and_boundary_lag_do_not_authorize_entry():
    stamp = instant("09:29:59")
    raw = clock(stamp, is_open=False, next_day="2026-11-09")
    result = assessment(market_clock=raw, now=stamp + timedelta(seconds=2))
    assert result.state == "before_open" and result.market_window is None
    assert result.reasons == ("broker_open_not_yet_confirmed",)
    raw["next_close"] = "2026-11-09T13:00:00-05:00"
    assert assessment(market_clock=raw, now=stamp).state == "unknown"


def test_empty_calendar_cannot_override_clock_indicating_today_session():
    assert assessment([], clock()).reasons == ("non_session_clock_conflict",)
    stamp = instant("08:00:00")
    raw = clock(stamp, is_open=False, next_day="2026-11-09")
    assert assessment([], raw, stamp).reasons == ("non_session_clock_conflict",)


def test_after_close_clock_may_correctly_reference_the_next_session():
    now = instant("16:01:00")
    raw = clock(now, is_open=False)
    raw["next_close"] = "2026-11-10T16:00:00-05:00"
    result = assessment(market_clock=raw, now=now)
    assert result.state == "after_close" and not result.reasons


@pytest.mark.parametrize("day,offset", [("2026-03-06", -5), ("2026-03-09", -4)])
def test_calendar_uses_local_eastern_date_across_daylight_saving_change(day, offset):
    parsed = parse_calendar(calendar(day), day)
    assert parsed.opened.hour == 9 and parsed.opened.minute == 30
    assert parsed.opened.utcoffset() == timedelta(hours=offset)


def test_unknown_local_observation_time_or_different_day_never_exposes_window():
    assert (
        assess_session(calendar(), clock(), "2026-11-09", datetime(2026, 11, 9)).state == "unknown"
    )
    result = assessment(
        now=instant() + timedelta(days=1),
        market_clock=clock(instant() + timedelta(days=1), next_day="2026-11-11"),
    )
    assert result.reasons == ("calendar_date_mismatch",)
    parsed = parse_calendar(calendar(), "2026-11-09")
    current_clock = parse_market_clock(clock(instant() + timedelta(days=1), next_day="2026-11-11"))
    assert evaluate_session(parsed, current_clock, instant() + timedelta(days=1)).reasons == (
        "calendar_day_not_current",
    )


def test_exact_opening_instant_can_have_inclusive_next_open():
    now = instant("09:30:00")
    raw = clock(now, next_day="2026-11-09")
    assert assessment(market_clock=raw, now=now).market_open
    earlier = evaluate_session(
        parse_calendar(calendar(), "2026-11-09"),
        parse_market_clock(raw),
        now - timedelta(seconds=1),
    )
    assert earlier.state == "before_open" and earlier.market_window is None


def evidence(now=None):
    now = now or instant()
    return {
        "version": EVIDENCE_VERSION,
        "day": now.date().isoformat(),
        "calendar_raw": calendar(now.date().isoformat()),
        "clock_raw": clock(now),
        "calendar_receipt": {"requested_at": now.isoformat(), "received_at": now.isoformat()},
        "clock_receipt": {"requested_at": now.isoformat(), "received_at": now.isoformat()},
        "source_errors": [],
        "assessment": {"market_open": True},
    }


def test_retained_evidence_reassessment_uses_raw_clock_not_cached_result():
    proof = evidence()
    retained = copy.deepcopy(proof)
    assert assess_evidence(proof, instant()).market_open
    proof["assessment"] = {
        "market_open": True,
        "assessed_at": (instant() + timedelta(seconds=35)).isoformat(),
    }
    result = assess_evidence(proof, instant() + timedelta(seconds=35))
    assert result.reasons == ("clock_timestamp_stale",)
    assert result.market_window is None
    assert proof["clock_raw"] == retained["clock_raw"]


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda proof: proof.update(version="old"), "session_evidence_version"),
        (
            lambda proof: proof.update(source_errors=["clock_fetch_failed"]),
            "session_source_unavailable",
        ),
        (lambda proof: proof.pop("source_errors"), "session_source_unavailable"),
        (lambda proof: proof.pop("clock_receipt"), "clock_receipt_invalid"),
        (
            lambda proof: proof["clock_receipt"].update(received_at="unknown"),
            "clock_receipt_invalid",
        ),
        (
            lambda proof: proof["clock_receipt"].update(
                received_at=(instant() + timedelta(seconds=1)).isoformat()
            ),
            "clock_receipt_chronology",
        ),
        (
            lambda proof: proof["calendar_receipt"].update(
                requested_at=(instant() + timedelta(seconds=1)).isoformat()
            ),
            "calendar_receipt_chronology",
        ),
        (
            lambda proof: proof["calendar_raw"][0].update(close="13:00"),
            "clock_calendar_close_mismatch",
        ),
    ],
)
def test_incomplete_unavailable_or_changed_retained_evidence_cannot_authorize(change, reason):
    proof = evidence()
    change(proof)
    result = assess_evidence(proof, instant())
    assert reason in result.reasons
    assert result.market_window is None


def test_missing_evidence_does_not_inherit_legacy_market_open():
    result = assess_evidence(None, instant())
    assert result.reasons == ("session_evidence_missing",)
    assert result.market_window is None
