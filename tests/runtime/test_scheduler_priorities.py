from concurrent.futures import Future
from datetime import datetime, timedelta

import pytest

from agent_trader.runtime.config import ET


@pytest.fixture
def scheduler(config, broker, monkeypatch):
    from agent_trader.runtime import supervisor

    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor, "notify", lambda *args, **kwargs: False)
    instance = supervisor.Supervisor(config)
    monkeypatch.setattr(instance, "maybe_publish", lambda: None)
    monkeypatch.setattr(instance, "market_tick", lambda *args: None)
    monkeypatch.setattr(instance, "finish_shadow", lambda *args, **kwargs: None)
    monkeypatch.setattr(instance, "launch_position_review", lambda *args: False)
    monkeypatch.setattr(instance, "pending_research_validation", lambda *args: False)
    monkeypatch.setattr(instance, "launch_exploration", lambda *args: False)
    monkeypatch.setattr(instance, "launch_candidate", lambda *args: False)
    yield instance
    instance.future = None
    instance.pool.shutdown(wait=False)
    instance.publisher_pool.shutdown(wait=False)
    instance.store.close()


def prepare(scheduler, broker, monkeypatch, now, *, session=True, reconciles=True, close="16:00"):
    day = now.date().isoformat()
    scheduler.store.set("calendar:" + day, [{"date": day, "open": "09:30", "close": close}] if session else [])
    scheduler.store.set("preflight_day", day)
    scheduler.store.set("brief_day", day)
    scheduler.store.set("readiness", {"execution_verified": True, "models_available": True})
    scheduler.store.set("last-week-session:" + day, False)
    scheduler.store.set("last-session:" + day, False)
    monkeypatch.setattr(broker, "clock", lambda: {"is_open": True, "timestamp": now.isoformat()}, raising=False)
    monkeypatch.setattr(scheduler.engine, "reconcile", lambda *args: reconciles)
    monkeypatch.setattr(scheduler.engine, "cancel_entries", lambda *args: None)
    return day


@pytest.mark.parametrize("close,now", [
    ("16:00", datetime(2026, 11, 6, 15, 49, tzinfo=ET)),
    ("13:00", datetime(2026, 11, 27, 12, 49, tzinfo=ET)),
])
def test_session_close_runs_before_a_failing_protection_check_even_with_busy_model(
    scheduler, broker, monkeypatch, close, now
):
    prepare(scheduler, broker, monkeypatch, now, close=close)
    calls = []
    scheduler.future = Future()  # inference is still pending; Python must not wait

    def protection_failure():
        calls.append("protection")
        raise TimeoutError("simulated protection lookup failure")

    monkeypatch.setattr(scheduler.engine, "ensure_protection", protection_failure)
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda: calls.append("close"))
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda *_: pytest.fail("Closing has priority"))
    scheduler.tick(now)
    assert calls and calls[0] == "close"
    assert "protection" not in calls
    assert "Closing intraday" in scheduler.store.get("status")
    assert not scheduler.future.done()


@pytest.mark.parametrize("healthy,expected", [(True, "market_closed"), (False, "halted")])
def test_weekend_reconciles_and_cancels_before_background_work(
    scheduler, broker, monkeypatch, healthy, expected
):
    now = datetime(2026, 11, 7, 12, 0, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now, session=False, reconciles=healthy)
    scheduler.store.set("mode", "halted")
    calls = []
    monkeypatch.setattr(scheduler.engine, "reconcile", lambda: calls.append("reconcile") or healthy)
    monkeypatch.setattr(scheduler.engine, "cancel_entries", lambda *args: calls.append("cancel_entries"))
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda *_: calls.append("background"))
    scheduler.tick(now)
    assert calls == ["reconcile", "cancel_entries", "background"]
    assert scheduler.store.get("mode") == expected
    assert scheduler.store.get("market_open") is False
    assert ("Reconciliation failed" in scheduler.store.get("status")) is (not healthy)
    assert broker.submissions == 0


def test_pending_daily_review_takes_worker_before_off_hours_research(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 6, 18, 0, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    calls = []

    def launch(key, role, context, day):
        calls.append(role)
        scheduler.future = Future()
        return True

    monkeypatch.setattr(scheduler, "launch", launch)
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda *_: pytest.fail("Daily review takes the worker first"))
    scheduler.tick(now)
    assert calls == ["retrospective"]


def test_due_period_review_precedes_background_after_daily_maintenance(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 6, 18, 0, tzinfo=ET)
    day = prepare(scheduler, broker, monkeypatch, now)
    scheduler.store.set("review_day", day)
    scheduler.store.set("last-week-session:" + day, True)
    calls = []
    monkeypatch.setattr(scheduler, "launch", lambda key, role, context, day: calls.append(role) or False)

    def period(role, day):
        calls.append(role)
        scheduler.future = Future()
        return True

    monkeypatch.setattr(scheduler, "launch_period", period)
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda *_: pytest.fail("Due weekly review takes the worker first"))
    scheduler.tick(now)
    assert calls == ["maintenance", "weekly"]


@pytest.mark.parametrize("hour,minute", [(7, 0), (7, 45), (8, 15), (9, 31), (10, 30), (13, 5), (15, 50)])
def test_background_work_does_not_launch_during_morning_or_market_priority_window(
    scheduler, broker, monkeypatch, hour, minute
):
    now = datetime(2026, 11, 6, hour, minute, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda: None)
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda: None)
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda *_: pytest.fail("Background work must wait outside market priority hours"))
    scheduler.tick(now)
    assert broker.submissions == 0


def test_overnight_idle_worker_can_run_useful_background_research(scheduler, broker, monkeypatch):
    now = datetime(2026, 11, 6, 6, 30, tzinfo=ET)
    prepare(scheduler, broker, monkeypatch, now)
    calls = []
    monkeypatch.setattr(scheduler, "launch_deep_research", lambda at: calls.append(at))
    scheduler.tick(now)
    assert len(calls) == 1 and now <= calls[0] < now + timedelta(minutes=1)
