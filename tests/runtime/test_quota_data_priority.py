from concurrent.futures import Future
from datetime import timedelta

import pytest

from agent_trader.runtime import options_coverage as probe, supervisor
from tests.runtime.test_options_coverage import Clock, DataBroker, at, registration
from tests.runtime.test_scheduler_priorities import prepare, scheduler as scheduler


def quota(now, used=80, minutes=10080):
    windows = [
        {
            "usedPercent": used,
            "windowDurationMins": minutes,
            "resetsAt": (now + timedelta(days=4)).timestamp(),
        }
    ]
    if minutes < 10000:
        windows.append(
            {
                "usedPercent": 20,
                "windowDurationMins": 10080,
                "resetsAt": (now + timedelta(days=4)).timestamp(),
            }
        )
    return {"at": now.isoformat(), "ordinary_usage_allowed": True, "windows": windows}


def setup_due(s, broker, monkeypatch, *, used=80, minutes=10080, stale=False):
    now = at()
    reg = registration(s.store)
    prepare(s, broker, monkeypatch, now)
    s.store.set("brief_day", "2026-11-06")
    s.store.set("entry_budget_blocked", used >= 80)
    s.store.set("quota", quota(now - timedelta(minutes=16) if stale else now, used, minutes))
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: 0)
    return now, reg


@pytest.mark.parametrize("used,minutes", [(80, 10080), (90, 300)])
def test_due_data_capture_precedes_missing_brief_only_at_known_account_ceiling(
    scheduler, broker, monkeypatch, used, minutes
):
    now, _ = setup_due(scheduler, broker, monkeypatch, used=used, minutes=minutes)
    calls = []
    monkeypatch.setattr(scheduler.engine, "ensure_protection", lambda: calls.append("protection"))
    monkeypatch.setattr(scheduler, "market_tick", lambda *args: calls.append("market"))
    monkeypatch.setattr(
        scheduler,
        "launch_candidate",
        lambda *args: pytest.fail("No model candidate at known ceiling"),
    )
    monkeypatch.setattr(
        scheduler, "launch", lambda key, role, context, day: calls.append(role) or True
    )
    scheduler.tick(now)
    assert calls == ["protection", "market", "options_coverage"]
    assert probe.capture_admission(scheduler.store, now) == 1
    assert broker.submissions == 0


def test_missing_brief_retains_priority_below_account_ceiling(scheduler, broker, monkeypatch):
    now, _ = setup_due(scheduler, broker, monkeypatch, used=79)
    calls = []
    monkeypatch.setattr(
        scheduler, "launch", lambda key, role, context, day: calls.append(role) or True
    )
    scheduler.tick(now)
    assert calls == ["research"]
    assert probe.public_summary(scheduler.store)["request_budget"]["reserved"] == 0


@pytest.mark.parametrize("case", ["stale", "missing", "malformed", "malformed_second_bucket"])
def test_unknown_quota_requests_metadata_refresh_before_due_capture(
    scheduler, broker, monkeypatch, case
):
    now, _ = setup_due(scheduler, broker, monkeypatch, stale=case == "stale")
    if case == "missing":
        scheduler.store.set("quota", {})
    elif case == "malformed":
        scheduler.store.set(
            "quota", {"at": now.isoformat(), "windows": "unknown", "ordinary_usage_allowed": True}
        )
    elif case == "malformed_second_bucket":
        receipt = quota(now)
        receipt["windows"].append({"usedPercent": "unknown"})
        scheduler.store.set("quota", receipt)
    calls = []
    monkeypatch.setattr(
        scheduler, "launch_candidate", lambda *args: pytest.fail("Unknown model admission")
    )
    monkeypatch.setattr(
        scheduler, "launch", lambda key, role, context, day: calls.append(role) or True
    )
    scheduler.tick(now)
    assert calls == ["quota_refresh"]
    assert not scheduler.fresh_quota_blocks_models(now)
    assert probe.public_summary(scheduler.store)["request_budget"]["reserved"] == 0


def test_fresh_ceiling_preempts_otherwise_eligible_candidate(scheduler, broker, monkeypatch, plan):
    now, _ = setup_due(scheduler, broker, monkeypatch)
    plan["expires_at"] = (now + timedelta(hours=2)).isoformat()
    for source in plan["evidence"]:
        source.update(published_at=now.isoformat(), observed_at=now.isoformat())
    scheduler.engine.add_plans([plan], now.date().isoformat())
    scheduler.store.set("brief_day", now.date().isoformat())
    scheduler.store.set("reconciled", True)
    scheduler.store.set("account", broker.account())
    scheduler.store.set("last_reconciled", now.isoformat())
    scheduler.store.set("market_open", True)
    # Model admission reads the fresh meter even if this cached flag lags it.
    scheduler.store.set("entry_budget_blocked", False)
    quote = {"bp": 99.99, "ap": 100, "t": now.isoformat()}
    scheduler.store.set("quotes", {plan["symbol"]: quote})
    assert scheduler.engine.validate_entry(plan, quote, now, now.replace(hour=16))[0] > 0
    monkeypatch.setattr(
        scheduler, "launch_candidate", supervisor.Supervisor.launch_candidate.__get__(scheduler)
    )
    calls = []
    monkeypatch.setattr(
        scheduler, "launch", lambda key, role, context, day: calls.append(role) or True
    )
    scheduler.tick(now)
    assert calls == ["options_coverage"]
    assert broker.submissions == 0


def test_busy_worker_retains_immutable_deadline_without_dispatch(scheduler, broker, monkeypatch):
    now, reg = setup_due(scheduler, broker, monkeypatch)
    scheduler.future = Future()
    monkeypatch.setattr(scheduler, "launch", lambda *args: pytest.fail("No overlapping worker"))
    scheduler.tick(now)
    assert probe.public_summary(scheduler.store)["captures"][0]["state"] == "pending"
    later = now + timedelta(minutes=2)
    monkeypatch.setattr(broker, "clock", lambda: {"is_open": True, "timestamp": later.isoformat()})
    scheduler.tick(later)
    summary = probe.public_summary(scheduler.store)
    assert summary["captures"][0]["state"] == "missed"
    assert summary["captures"][0]["deadline"] == reg["captures"][0]["deadline"]
    assert summary["request_budget"]["reserved"] == 0


def test_agent_pause_prevents_capture_worker_and_keeps_window(scheduler, broker, monkeypatch):
    now, reg = setup_due(scheduler, broker, monkeypatch)
    scheduler.config.state_dir.mkdir(parents=True, exist_ok=True)
    (scheduler.config.state_dir / "agent-pause.flag").touch()
    monkeypatch.setattr(scheduler.pool, "submit", lambda *args: pytest.fail("Paused worker"))
    scheduler.tick(now)
    assert scheduler.future is None
    summary = probe.public_summary(scheduler.store)
    assert summary["captures"][0]["scheduled_at"] == reg["captures"][0]["scheduled_at"]
    assert summary["request_budget"]["reserved"] == 0


def test_closing_and_protection_failure_do_not_yield_to_data_collection(
    scheduler, broker, monkeypatch
):
    now, _ = setup_due(scheduler, broker, monkeypatch)
    calls = []

    def failed_protection():
        raise TimeoutError("fixture protection lookup failed")

    monkeypatch.setattr(scheduler.engine, "ensure_protection", failed_protection)
    monkeypatch.setattr(
        scheduler, "launch", lambda *args: pytest.fail("Protection takes precedence")
    )
    with pytest.raises(TimeoutError):
        scheduler.tick(now)
    closing = now.replace(hour=15, minute=49)
    monkeypatch.setattr(
        broker, "clock", lambda: {"is_open": True, "timestamp": closing.isoformat()}
    )
    monkeypatch.setattr(scheduler.engine, "close_intraday", lambda: calls.append("close"))
    scheduler.tick(closing)
    assert calls == ["close"]
    assert probe.public_summary(scheduler.store)["request_budget"]["reserved"] == 0


def test_two_quota_blocked_windows_run_data_only_once_with_original_twelve_request_cap(
    scheduler, broker, monkeypatch
):
    now, reg = setup_due(scheduler, broker, monkeypatch)
    clock = Clock(now)

    class OwnedDataBroker(DataBroker):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    data = OwnedDataBroker(clock)
    monkeypatch.setattr(supervisor, "Broker", lambda _: data)
    monkeypatch.setattr(
        supervisor, "run_task", lambda *a, **kw: pytest.fail("No inference at quota80")
    )
    original_capture = probe.run_capture
    monkeypatch.setattr(
        probe,
        "run_capture",
        lambda store, broker, slot: original_capture(store, broker, slot, clock=clock),
    )
    roles = []

    def submit(fn, config, role, context, day, key):
        assert role == "options_coverage"
        roles.append(role)
        future = Future()
        future.set_result(fn(config, role, context, day, key))
        return future

    monkeypatch.setattr(scheduler.pool, "submit", submit)
    scheduler.tick(clock())
    first = probe.public_summary(scheduler.store)
    assert first["request_budget"]["reserved"] == 9
    assert first["captures"][0]["received_snapshots"] == 4
    clock.now = at(clock="10:15")
    scheduler.store.set("quota", quota(clock()))
    monkeypatch.setattr(
        broker, "clock", lambda: {"is_open": True, "timestamp": clock().isoformat()}
    )
    scheduler.tick(clock())
    final = probe.public_summary(scheduler.store)
    assert final["expected_observations"] == 8
    assert sum(c["received_snapshots"] for c in final["captures"]) == 8
    assert final["request_budget"] == {
        "limit": 12,
        "reserved": 12,
        "remaining": 0,
        "unknown_outcomes": 0,
        "failed": 0,
        "late": 0,
    }
    assert roles == ["options_coverage", "options_coverage"]
    assert len(data.calls) == 12
    assert final["selection"] == first["selection"]
    assert final["registration_id"] == reg["registration_id"]
    assert scheduler.store.get(probe.REGISTRATION_KEY) == reg
    assert all(
        c["scheduled_at"] == reg["captures"][i]["scheduled_at"]
        for i, c in enumerate(final["captures"])
    )
    assert original_capture(scheduler.store, data, 2, clock=clock) == final
    assert len(data.calls) == 12
    assert not scheduler.store.rows("SELECT * FROM orders")
    assert not scheduler.store.rows("SELECT * FROM usage")
    scheduler.future = None
