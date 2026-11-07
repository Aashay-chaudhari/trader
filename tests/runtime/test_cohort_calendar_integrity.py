import copy
from datetime import datetime, timedelta

import pytest

from agent_trader.runtime import cohorts, research
from agent_trader.runtime.config import ET
from agent_trader.runtime.observation_audit import content_hash


def inputs(day="2026-11-27"):
    now = datetime.fromisoformat(day + "T08:15").replace(tzinfo=ET)
    closed = {"2026-11-26", "2026-12-25", "2027-01-01"}
    dates = [now.date() + timedelta(days=i) for i in range(-80, 46)]
    calendar = [
        {
            "date": d.isoformat(),
            "open": "09:30",
            "close": "13:00" if d.isoformat() == "2026-11-27" else "16:00",
        }
        for d in dates
        if d.weekday() < 5 and d.isoformat() not in closed
    ]
    prior = [s["date"] for s in calendar if s["date"] < day]
    bars = [
        {
            "t": d + "T00:00:00-05:00",
            "o": 100 + i,
            "h": 102 + i,
            "l": 99 + i,
            "c": 101 + i,
            "v": 1000,
        }
        for i, d in enumerate(prior)
    ]
    return now, calendar, {"AAPL": copy.deepcopy(bars), "SPY": copy.deepcopy(bars)}


def test_all_stale_histories_defer_without_fabricating_observed_abstentions(store):
    now, calendar, bars = inputs()
    stale = {symbol: rows[:-1] for symbol, rows in bars.items()}
    assert cohorts.freeze_signals(store, stale, calendar, now) is None
    status = store.get("cohort_freeze_latest")
    assert status["state"] == "deferred"
    assert status["expected_prior_session"] == "2026-11-25"
    assert status["input_exclusions"][0]["observed_last_session"] == "2026-11-24"
    assert not store.rows("SELECT id FROM cohort_expected")
    assert not store.rows("SELECT id FROM cohort_observations")
    assert cohorts.freeze_signals(store, bars, calendar, now + timedelta(minutes=1))


@pytest.mark.parametrize(
    "day,previous", [("2026-11-27", "2026-11-25"), ("2026-11-30", "2026-11-27")]
)
def test_holiday_and_weekend_use_actual_broker_predecessor(store, day, previous):
    now, calendar, bars = inputs(day)
    result = cohorts.freeze_signals(store, bars, calendar, now)
    assert result["last_completed_session"] == previous
    assert (
        result["required_session_dates"]
        == sorted(s["date"] for s in calendar if s["date"] < day)[-21:]
    )
    assert len(result["flags"]["AAPL"]) == 6
    assert result["feature_validation_version"] == "fixed-broker-session-inputs-v3"


def test_missing_internal_session_excludes_affected_symbol_not_healthy_peers(store):
    now, calendar, bars = inputs()
    missing = bars["AAPL"][-5]["t"][:10]
    del bars["AAPL"][-5]
    result = cohorts.freeze_signals(store, bars, calendar, now)
    assert set(result["flags"]) == {"SPY"}
    exclusion = store.get("cohort-exclusions:" + now.date().isoformat())["input_exclusions"][0]
    assert exclusion["rule"] == "all_rules"
    assert exclusion["reason"] == "noncontiguous_required_sessions"
    assert exclusion["missing_sessions"] == [missing]
    assert not store.rows("SELECT id FROM cohort_expected WHERE symbol='AAPL'")


def test_missing_internal_spy_session_does_not_become_false_regime(store):
    now, calendar, bars = inputs()
    del bars["SPY"][-5]
    result = cohorts.freeze_signals(store, bars, calendar, now)
    assert len(result["flags"]["AAPL"]) == 5
    assert "market_confirmed_trend" not in result["flags"]["AAPL"]
    assert not store.rows("SELECT id FROM cohort_expected WHERE rule='market_confirmed_trend'")


@pytest.mark.parametrize("case", ["empty", "future_only", "too_short", "duplicate", "malformed"])
def test_unknown_or_ambiguous_calendar_defers_without_guessing(store, case):
    now, calendar, bars = inputs()
    if case == "empty":
        calendar = []
    elif case == "future_only":
        calendar = [s for s in calendar if s["date"] >= now.date().isoformat()]
    elif case == "too_short":
        calendar = [s for s in calendar if s["date"] >= "2026-11-20"]
    elif case == "duplicate":
        calendar.append({**calendar[0], "close": "12:00"})
    else:
        calendar[0]["date"] = "not-a-date"
    assert cohorts.freeze_signals(store, bars, calendar, now) is None
    assert store.get("cohort_freeze_latest")["reason"] == "required_broker_calendar_unavailable"
    assert not store.get("cohort-signals:" + now.date().isoformat())
    assert not store.rows("SELECT id FROM cohort_expected")


def test_existing_freeze_preserves_original_inputs_scope_and_protocol(store):
    now, calendar, bars = inputs()
    original = cohorts.freeze_signals(store, bars, calendar, now)
    study = store.get("cohort_study")
    inputs_before = store.get("cohort-inputs:" + now.date().isoformat())
    assert cohorts.freeze_signals(store, {}, [], now + timedelta(minutes=1)) == original
    assert store.get("cohort_study") == study
    assert store.get("cohort-inputs:" + now.date().isoformat()) == inputs_before


def test_named_calendar_receipt_must_match_exact_supplied_calendar(store):
    now, calendar, bars = inputs()
    store.set("calendar-receipt", {"sha256": "wrong", "sessions": calendar})
    assert (
        cohorts.freeze_signals(store, bars, calendar, now, calendar_reference="calendar-receipt")
        is None
    )
    assert store.get("cohort_freeze_latest")["reason"] == "broker_calendar_receipt_mismatch"
    store.set("calendar-receipt", {"sha256": content_hash(calendar), "sessions": calendar})
    frozen = cohorts.freeze_signals(
        store, bars, calendar, now, calendar_reference="calendar-receipt"
    )
    assert frozen["calendar_reference"] == "calendar-receipt"
    assert frozen["calendar_sha256"] == content_hash(calendar)


def test_market_packet_fetches_and_retains_required_past_and_future_calendar(store, monkeypatch):
    from agent_trader.runtime import calendars

    now, calendar, bars = inputs()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    class Data:
        calls = []

        def snapshots(self, symbols):
            return {}

        def bars(self, symbols):
            return bars

        def calendar_range(self, start, end):
            self.calls.append((start, end))
            return calendar

        def calendar(self, day):
            return []

        def option_chain(self, symbol):
            return {"snapshots": {}}

    monkeypatch.setattr(research, "datetime", Clock)
    monkeypatch.setattr(cohorts, "datetime", Clock)
    monkeypatch.setattr(
        calendars, "official_calendar", lambda *a: {"events": [], "sources": [], "unknowns": []}
    )
    monkeypatch.setattr(
        "httpx.get", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline fixture"))
    )
    broker = Data()
    research.market_packet(broker, store)
    assert broker.calls == [
        (
            (now.date() - timedelta(days=80)).isoformat(),
            (now.date() + timedelta(days=45)).isoformat(),
        )
    ]
    frozen = store.get("cohort-signals:" + now.date().isoformat())
    retained = store.get(frozen["calendar_reference"])
    assert retained["sessions"] == calendar
    assert retained["sha256"] == frozen["calendar_sha256"]
