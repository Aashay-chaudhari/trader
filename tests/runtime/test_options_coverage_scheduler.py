from concurrent.futures import Future
from datetime import timedelta

import pytest

from agent_trader.runtime import supervisor
from tests.runtime.test_options_coverage import at, confirm, registration
from tests.runtime.test_scheduler_priorities import prepare, scheduler as scheduler


def fresh_quota(now):
    return {"at": now.isoformat(), "ordinary_usage_allowed": True, "windows": [{
        "usedPercent": 10, "windowDurationMins": 10080,
        "resetsAt": (now + timedelta(days=7)).timestamp(),
    }]}


def prepare_probe(scheduler, broker, monkeypatch):
    now = at()
    registration(scheduler.store)
    prepare(scheduler, broker, monkeypatch, now)
    confirm(scheduler.store, now)
    scheduler.store.set("quota", fresh_quota(now))
    return now, now.replace(hour=16, minute=0)


def test_capture_queue_preserves_candidate_and_quota_refresh_priority(
    scheduler, broker, monkeypatch
):
    now, close = prepare_probe(scheduler, broker, monkeypatch)
    launched = []
    monkeypatch.setattr(
        scheduler, "launch", lambda key, role, context, day: launched.append(role) or True
    )
    monkeypatch.setattr(scheduler, "launch_candidate", lambda *args: True)
    assert scheduler.launch_options_coverage(now, close)
    assert not launched
    monkeypatch.setattr(scheduler, "launch_candidate", lambda *args: False)
    scheduler.store.set("quota", {})
    assert scheduler.launch_options_coverage(now, close)
    assert launched == ["quota_refresh"]
    scheduler.store.set("quota", fresh_quota(now))
    assert scheduler.launch_options_coverage(now, close)
    assert launched == ["quota_refresh", "options_coverage"]


def test_busy_worker_and_closing_prevent_probe_dispatch(scheduler, broker, monkeypatch):
    now, close = prepare_probe(scheduler, broker, monkeypatch)
    monkeypatch.setattr(
        scheduler, "launch", lambda *args: pytest.fail("No probe while occupied or closing")
    )
    scheduler.future = Future()
    assert not scheduler.launch_options_coverage(now, close)
    scheduler.future = None
    assert not scheduler.launch_options_coverage(close.replace(minute=49, hour=15), close)


def test_changed_calendar_is_terminal_without_quota_or_model_call(scheduler, broker, monkeypatch):
    now, close = prepare_probe(scheduler, broker, monkeypatch)
    scheduler.store.set("calendar:2026-11-09", [{"open": "10:00", "close": "16:00"}])
    monkeypatch.setattr(
        scheduler, "launch", lambda *args: pytest.fail("Changed session is not rescheduled")
    )
    assert not scheduler.launch_options_coverage(now, close)
    from agent_trader.runtime.options_coverage import public_summary

    assert public_summary(scheduler.store)["captures"][0]["reason"] == "calendar_incompatibility"


def test_full_tick_protection_and_position_review_precede_data_probe(
    scheduler, broker, monkeypatch
):
    now, _ = prepare_probe(scheduler, broker, monkeypatch)
    calls = []
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda **kwargs: calls.append("protection"))
    monkeypatch.setattr(scheduler, "market_tick", lambda *args: calls.append("market"))
    monkeypatch.setattr(
        scheduler, "launch_position_review", lambda *args: calls.append("position_review") or False
    )
    monkeypatch.setattr(
        scheduler, "launch_options_coverage", lambda *args: calls.append("coverage") or True
    )
    scheduler.tick(now)
    assert calls.index("protection") < calls.index("coverage")
    assert calls.index("market") < calls.index("coverage")
    assert calls.index("position_review") < calls.index("coverage")


def test_data_only_worker_bypasses_model_and_closes_broker(config, monkeypatch):
    from agent_trader.runtime import options_coverage

    closed, captures = [], []

    class Data:
        client = type("Client", (), {"close": lambda self: closed.append(True)})()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.client.close()

    monkeypatch.setattr(supervisor, "Broker", lambda _: Data())
    monkeypatch.setattr(supervisor, "run_task", lambda *a, **kw: pytest.fail("No model invocation"))
    monkeypatch.setattr(
        options_coverage,
        "run_capture",
        lambda store, broker, slot: captures.append(slot) or {"registered": True},
    )
    assert supervisor.worker(config, "options_coverage", {"slot": 1}, "2026-11-09") == {
        "registered": True
    }
    assert captures == [1] and closed == [True]


def test_agent_pause_blocks_capture_launch_without_resetting_windows(
    scheduler, broker, monkeypatch
):
    now, close = prepare_probe(scheduler, broker, monkeypatch)
    scheduler.config.state_dir.mkdir(parents=True, exist_ok=True)
    (scheduler.config.state_dir / "agent-pause.flag").touch()
    assert not scheduler.launch_options_coverage(now, close)
    assert scheduler.future is None
