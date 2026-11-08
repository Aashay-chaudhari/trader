"""Session authority comes from compatible receipts, never truthy wire values."""

from datetime import datetime, timedelta

import pytest

from agent_trader.runtime import supervisor
from agent_trader.runtime.config import ET
from tests.runtime import test_scheduler_priorities as priorities
from tests.runtime.test_operational_session import clock

scheduler = priorities.scheduler


@pytest.fixture(autouse=True)
def instant_requests(monkeypatch):
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: 0)


def setup(scheduler, broker, monkeypatch, *, now=None, close="13:00", session=True):
    now = now or datetime(2026, 11, 27, 12, 49, tzinfo=ET)
    priorities.prepare(scheduler, broker, monkeypatch, now, close=close, session=session)
    calls = []
    monkeypatch.setattr(scheduler.engine, "cancel_entries", lambda at, deadline: calls.append(("cancel", deadline)))
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: calls.append(("close", None)))
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: calls.append(("protection", None)))
    monkeypatch.setattr(scheduler, "market_tick", lambda *args: calls.append(("market", None)))
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda *args: False)
    return now, calls


@pytest.mark.parametrize("raw", [None, {}, False, "", 0, [{"date": "2026-11-26", "open": "09:30", "close": "13:00"}],
    [{"date": "2026-11-27", "open": "09:30", "close": "13:00"}] * 2,
    [{"date": "2026-11-27", "open": "14:30:00+00:00", "close": "18:00:00+00:00"}]])
def test_malformed_calendar_cannot_become_holiday_or_supply_cancel_deadline(
    scheduler, broker, monkeypatch, raw
):
    now, calls = setup(scheduler, broker, monkeypatch)
    scheduler.store.set("calendar:" + now.date().isoformat(), raw)
    monkeypatch.setattr(broker, "calendar", lambda _: raw)
    scheduler.store.set("market_open", True)
    scheduler.tick(now)
    assert calls == [("cancel", None)]
    assert scheduler.store.get("market_open") is False
    assert scheduler.store.get("operational_session")["assessment"]["state"] == "unknown"
    assert "holiday or weekend" not in scheduler.store.get("status")
    assert "protection retained" in scheduler.store.get("status")
    assert broker.submissions == 0


def test_confirmed_empty_calendar_and_closed_clock_remain_non_session(scheduler, broker, monkeypatch):
    now, calls = setup(scheduler, broker, monkeypatch,
                       now=datetime(2026, 11, 7, 12, tzinfo=ET), session=False)
    scheduler.tick(now)
    assert calls == [("cancel", None)]
    assert scheduler.store.get("mode") == "market_closed"
    assert scheduler.store.get("operational_session")["assessment"]["state"] == "non_session"


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_invalid_clock_boolean_never_runs_close_or_market_work(scheduler, broker, monkeypatch, value):
    now, calls = setup(scheduler, broker, monkeypatch)
    raw = clock(now, close="13:00", next_day="2026-11-30")
    raw["is_open"] = value
    monkeypatch.setattr(broker, "clock", lambda: raw)
    scheduler.tick(now)
    assert calls == [("cancel", None)]
    assert scheduler.store.get("operational_session")["assessment"]["reason_codes"] == ["clock_is_open_not_boolean"]


def test_conflicting_early_close_refetches_once_after_cooldown_and_keeps_prior_receipt(
    scheduler, broker, monkeypatch
):
    now, calls = setup(scheduler, broker, monkeypatch, close="16:00")
    first = scheduler.acquire_operational_session(now)
    assert first.market_open
    previous = scheduler.store.get("operational_session")["calendar_receipt"]
    old_record = scheduler.store.get(previous["reference"])
    reads = []
    repaired = [{"date": "2026-11-27", "open": "09:30", "close": "13:00"}]
    monkeypatch.setattr(broker, "calendar", lambda day: reads.append(day) or repaired)
    later = now + timedelta(seconds=10)
    monkeypatch.setattr(broker, "clock", lambda: clock(later, close="13:00", next_day="2026-11-30"))
    scheduler.tick(later)
    assert reads == [] and calls == [("cancel", None)]
    assert scheduler.store.get("market_open") is False
    later = now + timedelta(seconds=60)
    scheduler.tick(later)
    assert reads == ["2026-11-27"]
    assert calls[-2:] == [("cancel", now.replace(hour=13, minute=0)), ("close", None)]
    proof = scheduler.store.get("operational_session")
    assert proof["calendar_receipt"]["sha256"] != previous["sha256"]
    assert scheduler.store.get(previous["reference"]) == old_record
    assert proof["assessment"]["state"] == "open"


def test_failed_corrective_fetch_cannot_fall_back_to_old_success(scheduler, broker, monkeypatch):
    now, calls = setup(scheduler, broker, monkeypatch, close="16:00")
    scheduler.acquire_operational_session(now)
    previous = scheduler.store.get("operational_session")["calendar_receipt"]
    attempts = []

    def failure(day):
        attempts.append(day)
        raise TimeoutError("Private transport diagnostic must not enter status")

    monkeypatch.setattr(broker, "calendar", failure)
    later = now + timedelta(seconds=60)
    monkeypatch.setattr(broker, "clock", lambda: clock(later, close="13:00", next_day="2026-11-30"))
    scheduler.tick(later)
    failed = scheduler.store.get("operational_session")["calendar_receipt"]
    assert failed != previous
    assert scheduler.store.get(failed["reference"])["error_code"] == "calendar_fetch_failed"
    assert scheduler.store.get("calendar:2026-11-27")[0]["close"] == "16:00"
    later += timedelta(seconds=10)
    monkeypatch.setattr(broker, "clock", lambda: clock(later, close="16:00", next_day="2026-11-30"))
    scheduler.tick(later)
    assert attempts == ["2026-11-27"]
    assert scheduler.store.get("operational_session")["calendar_raw"] is None
    assert calls == [("cancel", None), ("cancel", None)]
    assert "Private transport" not in scheduler.store.get("status")


def test_initial_conflicting_response_cannot_trigger_second_calendar_get(scheduler, broker, monkeypatch):
    now, calls = setup(scheduler, broker, monkeypatch, close="16:00")
    reads = []
    monkeypatch.setattr(broker, "calendar", lambda day: reads.append(day) or [
        {"date": day, "open": "09:30", "close": "16:00"}])
    monkeypatch.setattr(broker, "clock", lambda: clock(now, close="13:00", next_day="2026-11-30"))
    scheduler.tick(now)
    assert reads == ["2026-11-27"] and calls == [("cancel", None)]


def test_tick_clears_old_market_authority_before_completed_result_application(scheduler, broker, monkeypatch):
    now, _ = setup(scheduler, broker, monkeypatch)
    scheduler.store.set("market_open", True)
    scheduler.store.set("operational_session", {"old": "proof"})

    def finish():
        assert scheduler.store.get("market_open") is False
        assert scheduler.store.get("operational_session") is None

    monkeypatch.setattr(scheduler, "finish_task", finish)
    scheduler.tick(now)


def test_corrective_get_latency_does_not_refresh_clock_observation(scheduler, broker, monkeypatch):
    now, calls = setup(scheduler, broker, monkeypatch, close="16:00")
    scheduler.acquire_operational_session(now)
    elapsed = [0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    later = now + timedelta(seconds=60)
    monkeypatch.setattr(broker, "clock", lambda: clock(later, close="13:00", next_day="2026-11-30"))

    def slow_calendar(day):
        elapsed[0] = 31
        return [{"date": day, "open": "09:30", "close": "13:00"}]

    monkeypatch.setattr(broker, "calendar", slow_calendar)
    scheduler.tick(later)
    proof = scheduler.store.get("operational_session")
    assert proof["clock_raw"]["timestamp"] == later.isoformat()
    assert proof["assessment"]["reason_codes"] == ["clock_timestamp_stale"]
    assert calls == [("cancel", None)]


def test_market_quote_latency_rechecks_clock_before_actions_or_observation_capture(
    scheduler, broker, monkeypatch
):
    now, _ = setup(scheduler, broker, monkeypatch,
                   now=datetime(2026, 11, 9, 10, tzinfo=ET), close="16:00")
    scheduler.acquire_operational_session(now)
    elapsed = [0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(scheduler, "benchmarks", lambda *args: pytest.fail("Stale session cannot record timed observations"))

    def slow_quotes(symbols):
        elapsed[0] = 31
        return {}

    monkeypatch.setattr(broker, "quotes", slow_quotes)
    supervisor.Supervisor.market_tick(scheduler, now, now.replace(hour=16))
    assert scheduler.store.get("market_open") is False
    assert scheduler.store.get("operational_session")["assessment"]["reason_codes"] == ["clock_timestamp_stale"]
    assert broker.submissions == 0


def test_unknown_session_incident_is_bounded_and_notification_cannot_restore_authority(
    scheduler, broker, monkeypatch
):
    now, calls = setup(scheduler, broker, monkeypatch)
    raw = clock(now, close="13:00", next_day="2026-11-30")
    raw["is_open"] = "false"
    monkeypatch.setattr(broker, "clock", lambda: raw)
    sent = []

    def notify(*args, **kwargs):
        assert scheduler.store.get("market_open") is False
        sent.append(True)
        return False

    monkeypatch.setattr(supervisor, "notify", notify)
    scheduler.tick(now)
    scheduler.unknown_session_status()
    scheduler.tick(now + timedelta(seconds=1))
    assert len(sent) == 1
    assert len(scheduler.store.rows("SELECT id FROM events WHERE kind='incident'")) == 1
    assert calls == [("cancel", None), ("cancel", None)]
    assert scheduler.store.get("market_open") is False


def test_cleanup_session_expiry_keeps_durable_buy_cancellations_reachable(
    scheduler, broker, monkeypatch
):
    from agent_trader.runtime.engine import SessionProofUnavailable
    from tests.runtime.test_pulse_cancellation_delivery import pulse, intents

    now, _ = setup(scheduler, broker, monkeypatch,
                   now=datetime(2026, 11, 9, 10, tzinfo=ET), close="16:00")
    pulse(scheduler)
    elapsed, canceled = [0], []
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(broker, "cancel", lambda identity: canceled.append(identity))
    monkeypatch.setattr(scheduler, "launch", lambda *args: pytest.fail("Unknown session cannot launch model work"))

    def aged_cleanup(**kwargs):
        elapsed[0] = 31
        raise SessionProofUnavailable("clock_timestamp_stale")

    monkeypatch.setattr(scheduler.engine, "ensure_protection", aged_cleanup)
    scheduler.tick(now)
    assert set(canceled) == {"broker-AAPL", "broker-MSFT"}
    assert {item["state"] for item in intents(scheduler.store).values()} == {"requested"}
    assert scheduler.store.get("operational_session")["assessment"]["state"] == "unknown"
    assert scheduler.store.get("market_open") is False
    assert broker.submissions == 0


def test_slow_first_exit_cannot_give_next_sibling_the_old_observation_time(
    scheduler, broker, monkeypatch
):
    from tests.runtime.session_fixtures import install

    now = datetime(2026, 11, 9, 10, tzinfo=ET)
    install(scheduler.store, now)
    elapsed, attempted = [0], []
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    for symbol in ("AAPL", "MSFT"):
        scheduler.store.db.execute("INSERT INTO holdings VALUES(?,?,?,?,?)", (symbol, "swing", 1, 100, symbol))
        scheduler.store.set("exit-intent:" + symbol, {"at": now.isoformat(), "plan_id": symbol,
                                                   "branch": "swing", "reason": "Validated exit"})

    def exit_holding(symbol, reason, *, now):
        scheduler.engine._session_window(now)
        attempted.append(symbol)
        elapsed[0] = 31
        return False

    monkeypatch.setattr(scheduler.engine, "exit_holding", exit_holding)
    scheduler.apply_pending_exits(now)
    assert len(attempted) == 1
    assert all(scheduler.store.get("exit-intent:" + symbol) for symbol in ("AAPL", "MSFT"))
    assert scheduler.store.get("market_open") is False
