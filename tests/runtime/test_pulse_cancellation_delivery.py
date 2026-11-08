"""Pulse safety commits before independently retried cancellation delivery."""
import json
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agent_trader.runtime import supervisor
from agent_trader.runtime.models import Pulse
from agent_trader.runtime.store import Store
from tests.runtime import test_atomic_applications as applications
from tests.runtime import test_scheduler_priorities as priorities

runtime = applications.runtime
scheduler = priorities.scheduler


@pytest.fixture(autouse=True)
def instant_delivery_clock(monkeypatch):
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: 0)


def pulse(runtime, *, symbols=("AAPL", "MSFT"), missing_broker=False):
    for symbol in symbols:
        runtime.store.db.execute(
            "INSERT INTO orders(client_id,broker_id,branch,symbol,side,qty,status,plan_id,payload,at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (symbol, None if missing_broker else "broker-" + symbol, "intraday", symbol, "buy", 1,
             "prepared" if missing_broker else "new", "plan-" + symbol, "{}", "before"),
        )
    runtime.store.set("needs_research", False)
    runtime.store.set("research_refresh_required", False)
    runtime.store.set("entry_budget_blocked", False)
    result = Pulse.model_validate({
        "summary": "A verified material event changes the current assumptions.", "material_change": True,
        "affected_symbols": list(symbols), "events": [], "sources": [], "unknowns": [],
    }).model_dump(mode="json")
    applications.queue(runtime, result, role="pulse")
    return result


def intents(store):
    return {item["identity"]["client_id"]: item for row in store.rows(
        "SELECT value FROM kv WHERE key LIKE 'pulse-cancellation:%'"
    ) for item in [json.loads(row["value"]) ]}


@pytest.mark.parametrize("after_acceptance", [False, True])
def test_transport_uncertainty_keeps_safety_refresh_and_sibling_delivery(runtime, monkeypatch, after_acceptance):
    pulse(runtime)
    attempted, accepted = [], []

    def cancel(identity):
        assert not runtime.store.db.in_transaction
        assert runtime.store.get("needs_research") is True
        assert runtime.store.get("research_refresh_required") is True
        assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "done"
        assert intents(runtime.store)[identity.removeprefix("broker-")]["state"] == "attempting"
        attempted.append(identity)
        if identity == "broker-AAPL":
            if after_acceptance:
                accepted.append(identity)
            raise TimeoutError("Injected transport uncertainty")
        accepted.append(identity)

    monkeypatch.setattr(runtime.broker, "cancel", cancel)
    runtime.finish_task()
    assert not attempted
    now = datetime.now(timezone.utc)
    runtime.apply_pulse_cancellations(now)
    assert set(attempted) == {"broker-AAPL", "broker-MSFT"}
    assert ("broker-AAPL" in accepted) == after_acceptance
    saved = intents(runtime.store)
    assert saved["AAPL"]["state"] == "uncertain"
    assert saved["MSFT"]["state"] == "requested"
    assert runtime.store.get("entry_budget_blocked") is True
    assert all(x["attempts"] == 1 for x in saved.values())
    assert runtime.qualities == ["applied"]
    assert json.loads(runtime.store.rows("SELECT payload FROM usage")[0]["payload"])["application_outcome"] == "accepted"
    runtime.apply_pulse_cancellations(now + timedelta(seconds=59))
    assert len(attempted) == 2
    assert runtime.broker.submissions == 0


def test_lost_ack_persistence_preserves_attempt_cooldown_across_restart(runtime, monkeypatch):
    pulse(runtime, symbols=("AAPL",))
    runtime.finish_task()
    requests = []
    monkeypatch.setattr(runtime.broker, "cancel", lambda identity: requests.append(identity))
    connection = runtime.store.db
    runtime.store.db = applications.FailExecute(connection, lambda sql, args:
        "INTO kv" in sql and args[0].startswith("pulse-cancellation:") and json.loads(args[1])["state"] == "requested")
    now = datetime.now(timezone.utc)
    try:
        runtime.apply_pulse_cancellations(now)
    finally:
        runtime.store.db = connection
    assert requests == ["broker-AAPL"]
    assert intents(runtime.store)["AAPL"]["state"] == "attempting"
    assert runtime.store.get("entry_budget_blocked") is True
    with closing(Store(runtime.store.path)) as reopened:
        restarted = supervisor.Supervisor.__new__(supervisor.Supervisor)
        restarted.store, restarted.broker = reopened, runtime.broker
        restarted.apply_pulse_cancellations(now + timedelta(seconds=59))
        assert len(requests) == 1
        restarted.apply_pulse_cancellations(now + timedelta(seconds=60))
        assert requests == ["broker-AAPL", "broker-AAPL"]
        assert intents(reopened)["AAPL"]["attempts"] == 2
        assert intents(reopened)["AAPL"]["state"] == "requested"


def test_failure_before_attempt_commit_sends_nothing_and_can_retry(runtime, monkeypatch):
    pulse(runtime, symbols=("AAPL",))
    runtime.finish_task()
    requests = []
    monkeypatch.setattr(runtime.broker, "cancel", lambda identity: requests.append(identity))
    connection = runtime.store.db
    runtime.store.db = applications.FailExecute(connection, lambda sql, args:
        "INTO kv" in sql and args[0].startswith("pulse-cancellation:") and json.loads(args[1])["state"] == "attempting")
    now = datetime.now(timezone.utc)
    try:
        runtime.apply_pulse_cancellations(now)
    finally:
        runtime.store.db = connection
    assert requests == [] and intents(runtime.store)["AAPL"]["attempts"] == 0
    assert runtime.store.get("entry_budget_blocked") is False
    runtime.apply_pulse_cancellations(now)
    assert requests == ["broker-AAPL"]


@pytest.mark.parametrize("change", ["missing", "broker_id", "branch", "plan_id", "qty"])
def test_changed_or_missing_owned_identity_remains_unresolved_without_guessed_cancel(runtime, monkeypatch, change):
    pulse(runtime, symbols=("AAPL",))
    runtime.finish_task()
    if change == "missing":
        runtime.store.db.execute("DELETE FROM orders")
    else:
        values = {"broker_id": "replacement", "branch": "swing", "plan_id": "replacement-plan", "qty": 2}
        runtime.store.db.execute("UPDATE orders SET " + change + "=?", (values[change],))
    monkeypatch.setattr(runtime.broker, "cancel", lambda *a: pytest.fail("Cannot guess changed ownership"))
    runtime.apply_pulse_cancellations(datetime.now(timezone.utc))
    assert intents(runtime.store)["AAPL"]["state"] == "unresolved"
    assert intents(runtime.store)["AAPL"]["attempts"] == 0


def test_missing_broker_identity_is_retained_unresolved(runtime, monkeypatch):
    pulse(runtime, symbols=("AAPL",), missing_broker=True)
    runtime.finish_task()
    assert intents(runtime.store)["AAPL"]["state"] == "unresolved"
    runtime.store.db.execute("UPDATE orders SET broker_id='later-unbound-id'")
    monkeypatch.setattr(runtime.broker, "cancel", lambda *a: pytest.fail("Cannot guess an unresolved target"))
    runtime.apply_pulse_cancellations(datetime.now(timezone.utc))
    assert intents(runtime.store)["AAPL"]["attempts"] == 0


def test_partial_fill_and_new_research_do_not_erase_cancel_intent(runtime, monkeypatch, plan):
    pulse(runtime, symbols=("AAPL",))
    runtime.finish_task()
    requests = []
    monkeypatch.setattr(runtime.broker, "cancel", lambda identity: requests.append(identity))
    now = datetime.now(timezone.utc)
    runtime.apply_pulse_cancellations(now)
    receipt = {"id": "broker-AAPL", "client_order_id": "AAPL", "symbol": "AAPL", "side": "buy",
               "qty": "1", "filled_qty": "0.4", "filled_avg_price": "100", "status": "partially_filled"}
    runtime.engine.ingest_order(receipt, "intraday", "plan-AAPL", expected_client_id="AAPL", expected_broker_id="broker-AAPL")
    assert applications.apply(runtime, applications.brief(plan), key="fresh-research")["state"] == "done"
    assert runtime.store.get("research_refresh_required") is False
    runtime.apply_pulse_cancellations(now + timedelta(seconds=60))
    assert requests == ["broker-AAPL", "broker-AAPL"]
    assert intents(runtime.store)["AAPL"]["state"] == "requested"
    runtime.engine.ingest_order({**receipt, "status": "canceled"}, "intraday", "plan-AAPL",
                               expected_client_id="AAPL", expected_broker_id="broker-AAPL")
    runtime.apply_pulse_cancellations(now + timedelta(seconds=61))
    assert intents(runtime.store)["AAPL"]["state"] == "terminal"
    assert intents(runtime.store)["AAPL"]["observed_status"] == "canceled"
    assert len(requests) == 2
    assert runtime.store.rows("SELECT qty FROM holdings") == [{"qty": 0.4}]
    assert runtime.broker.submissions == 0


def test_pulse_job_completion_failure_rolls_back_safety_and_cancel_queue(runtime, monkeypatch):
    pulse(runtime, symbols=("AAPL",))
    connection = runtime.store.db
    runtime.store.db = applications.FailExecute(connection, lambda sql, args: "UPDATE jobs SET state=" in sql and args[0] == "done")
    monkeypatch.setattr(runtime.broker, "cancel", lambda *a: pytest.fail("No delivery before local commit"))
    try:
        runtime.finish_task()
    finally:
        runtime.store.db = connection
    assert intents(runtime.store) == {}
    assert runtime.store.get("pulses") is None
    assert runtime.store.get("research_refresh_required") is False
    assert runtime.store.rows("SELECT state FROM jobs")[0]["state"] == "failed"
    assert runtime.store.get("entry_budget_blocked") is True


def test_slow_first_cancel_refreshes_later_attempt_time_and_preserves_next_tick_cooldown(runtime, monkeypatch):
    pulse(runtime)
    runtime.finish_task()
    elapsed, requests = [0], []
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])

    def cancel(identity):
        requests.append(identity)
        if len(requests) == 1:
            elapsed[0] = 90

    monkeypatch.setattr(runtime.broker, "cancel", cancel)
    now = datetime.now(timezone.utc)
    runtime.apply_pulse_cancellations(now)
    later_identity = requests[1].removeprefix("broker-")
    assert intents(runtime.store)[later_identity]["last_attempt_at"] == (now + timedelta(seconds=90)).isoformat()
    assert intents(runtime.store)[later_identity]["next_retry_at"] == (now + timedelta(seconds=150)).isoformat()
    runtime.apply_pulse_cancellations(now + timedelta(seconds=100))
    assert requests.count("broker-" + later_identity) == 1
    assert len(requests) == 3  # Only the earlier request is eligible again.


def test_tick_uses_time_after_slow_market_work_for_cancellation_cooldown(scheduler, broker, monkeypatch):
    from agent_trader.runtime.config import ET

    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    priorities.prepare(scheduler, broker, monkeypatch, now)
    pulse(scheduler, symbols=("AAPL",))
    elapsed, requests = [0], []
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(scheduler, "market_tick", lambda *args: elapsed.__setitem__(0, 120))
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    monkeypatch.setattr(broker, "cancel", lambda identity: requests.append(identity))
    scheduler.tick(now)
    saved = intents(scheduler.store)["AAPL"]
    assert saved["last_attempt_at"] == (now + timedelta(seconds=120)).isoformat()
    assert saved["next_retry_at"] == (now + timedelta(seconds=180)).isoformat()
    scheduler.apply_pulse_cancellations(now + timedelta(seconds=130))
    assert requests == ["broker-AAPL"]


@pytest.mark.parametrize("early_return", ["overdue", "clock", "prestart"])
def test_early_tick_return_preserves_cancellation_delivery_after_priority_work(
    scheduler, broker, monkeypatch, early_return
):
    from agent_trader.runtime.config import ET

    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    priorities.prepare(scheduler, broker, monkeypatch, now)
    pulse(scheduler, symbols=("AAPL",))
    calls = []
    monkeypatch.setattr(broker, "cancel", lambda identity: calls.append("cancel"))
    monkeypatch.setattr(scheduler, "launch", lambda *args: pytest.fail("Early return cannot dispatch model work"))
    if early_return == "overdue":
        monkeypatch.setattr(scheduler.engine, "overdue_intraday", lambda _: True)
        monkeypatch.setattr(scheduler.engine, "close_intraday", lambda **kwargs: calls.append("close"))
    elif early_return == "clock":
        monkeypatch.setattr(broker, "clock", lambda: {"is_open": False, "timestamp": now.isoformat()})
    else:
        monkeypatch.setattr(scheduler, "config", replace(scheduler.config, start_date="2026-11-10"))
    scheduler.tick(now)
    assert calls == (["close", "cancel"] if early_return == "overdue" else ["cancel"])
    assert intents(scheduler.store)["AAPL"]["state"] == "requested"
    assert broker.submissions == 0
