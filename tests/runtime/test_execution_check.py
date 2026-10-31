import json
from datetime import datetime, timedelta

import pytest

from agent_trader.runtime.config import ET
from agent_trader.runtime.engine import Engine
from agent_trader.runtime.operations import operational_evidence
from agent_trader.runtime.research import review_prompt
from agent_trader.runtime.store import Store
from agent_trader.runtime import supervisor


@pytest.fixture
def runtime(config, broker, monkeypatch):
    monkeypatch.setattr(supervisor, "Broker", lambda _: broker)
    monkeypatch.setattr(supervisor, "notify", lambda *a, **kw: True)
    s = supervisor.Supervisor(config)
    now = datetime.now(ET).replace(hour=9, minute=32, second=0, microsecond=0)
    broker.quotes = lambda symbols: {"SPY": {"bp": 100, "ap": 100.01, "t": now.isoformat()}}
    s.engine.reconcile(now)
    s.store.set(
        "readiness", {"funded": True, "models_available": True, "execution_verified": False}
    )
    yield s, broker, now, now.replace(hour=16, minute=0)
    s.pool.shutdown(wait=False)
    s.publisher_pool.shutdown(wait=False)
    s.store.close()


def start(runtime):
    s, broker, now, close = runtime
    assert not s.smoke(now, now.replace(minute=30), close)
    return s.store.rows("SELECT * FROM orders WHERE side='buy'")[0]


def test_execution_intent_survives_cleanup_restart_and_expires(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    assert s.store.rows("SELECT * FROM plans") == []
    # Reopen the actual persisted database, as a restarted supervisor would.
    reopened = Store(s.store.path)
    try:
        engine = Engine(s.config, reopened, broker)
        engine.cancel_entries(now + timedelta(seconds=30), close)
        assert broker.items[row["broker_id"]]["status"] == "new"
        engine.cancel_entries(now + timedelta(seconds=119), close)
        assert broker.items[row["broker_id"]]["status"] == "new"
        engine.cancel_entries(now + timedelta(minutes=2), close)
        assert broker.items[row["broker_id"]]["status"] == "canceled"
        stage = reopened.get("smoke:" + now.date().isoformat())
        assert stage["state"] == "cancel_requested"  # request is not an acknowledgment
        assert stage["reason"] == "execution_check_timeout"
    finally:
        reopened.close()
    s.engine.reconcile(now + timedelta(minutes=2, seconds=1))
    assert not s.smoke(now + timedelta(minutes=2, seconds=1), now.replace(minute=30), close)
    assert s.store.get("smoke:" + now.date().isoformat())["state"] == "unfilled"
    assert not s.store.get("readiness")["execution_verified"]
    assert broker.submissions == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "AAPL"),
        ("qty", 2),
        ("branch", "swing"),
        ("plan_id", "operational-smoke-fake"),
        ("client_id", "forged-id"),
    ],
)
def test_prefix_or_modified_order_cannot_gain_operational_exemption(runtime, field, value):
    s, broker, now, close = runtime
    row = start(runtime)
    s.store.db.execute(f"UPDATE orders SET {field}=? WHERE client_id=?", (value, row["client_id"]))
    s.engine.cancel_entries(now + timedelta(seconds=30), close)
    assert broker.items[row["broker_id"]]["status"] == "canceled"


@pytest.mark.parametrize(
    "condition", ["no_intent", "extended_deadline", "paused", "prior_day", "cutoff"]
)
def test_operational_intent_cannot_escape_other_cancellation_gates(runtime, condition):
    s, broker, now, close = runtime
    row = start(runtime)
    key = "smoke:" + now.date().isoformat()
    stage = s.store.get(key)
    if condition == "no_intent":
        s.store.set(key, {})
    elif condition == "extended_deadline":
        s.store.set(key, {**stage, "expires_at": (now + timedelta(minutes=20)).isoformat()})
    elif condition == "paused":
        s.store.db.execute("UPDATE branches SET paused=1 WHERE name='intraday'")
    elif condition == "prior_day":
        now += timedelta(days=1)
        close += timedelta(days=1)
    elif condition == "cutoff":
        close = now + timedelta(minutes=30)
    s.engine.cancel_entries(now + timedelta(seconds=30), close)
    assert broker.items[row["broker_id"]]["status"] == "canceled"


def test_cancellation_request_not_claimed_confirmed_before_broker_reconcile(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    s.engine.cancel_entries(now + timedelta(minutes=2), close)
    assert s.store.rows("SELECT status FROM orders")[0]["status"] == "new"
    evidence = operational_evidence(now.date().isoformat(), s.store)
    assert evidence["execution_checks"][0]["state"] == "cancel_requested"
    assert evidence["selected_orders"][0]["status"] == "new"
    assert not evidence["execution_verified"]
    s.engine.reconcile(now + timedelta(minutes=2, seconds=1))
    evidence = operational_evidence(now.date().isoformat(), s.store)
    assert evidence["selected_orders"][0]["status"] == "canceled"
    assert not evidence["execution_verified"]
    assert broker.items[row["broker_id"]]["status"] == "canceled"


def fill_entry(s, broker, row, qty):
    order = broker.items[row["broker_id"]]
    order.update(
        status="filled" if qty == 1 else "partially_filled",
        filled_qty=str(qty),
        filled_avg_price="100",
    )
    broker.cash -= qty * 100
    broker.pos = [{"symbol": "SPY", "qty": str(qty), "market_value": str(qty * 100)}]
    assert s.engine.reconcile()


def fill_exit(s, broker, qty):
    row = s.store.rows("SELECT * FROM orders WHERE side='sell'")[0]
    broker.items[row["broker_id"]].update(
        status="filled", filled_qty=str(qty), filled_avg_price="100"
    )
    broker.cash += qty * 100
    broker.pos = []
    assert s.engine.reconcile()


def test_gate_requires_real_confirmed_exit_fill_and_reconciliation(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    fill_entry(s, broker, row, 1)
    assert not s.smoke(now + timedelta(seconds=30), now.replace(minute=30), close)
    assert not s.store.get("readiness")["execution_verified"]
    assert broker.submissions == 2  # one entry + one exit, never a duplicate entry
    fill_exit(s, broker, 1)
    assert s.smoke(now + timedelta(minutes=1), now.replace(minute=30), close)
    assert s.store.get("readiness")["execution_verified"]
    assert s.store.get("smoke:" + now.date().isoformat())["exit_filled_qty"] == 1
    assert broker.submissions == 2


def test_partial_entry_is_unwound_but_cannot_pass_one_share_gate(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    fill_entry(s, broker, row, 0.5)
    assert not s.smoke(now + timedelta(seconds=30), now.replace(minute=30), close)
    fill_exit(s, broker, 0.5)
    assert not s.smoke(now + timedelta(minutes=1), now.replace(minute=30), close)
    assert not s.store.get("readiness")["execution_verified"]
    assert not s.store.rows("SELECT * FROM holdings")


def test_owned_kernel_exit_fill_is_recognized_as_confirmed_roundtrip(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    fill_entry(s, broker, row, 1)
    assert s.engine.exit_holding("SPY", "Protective kernel requested an exit")
    fill_exit(s, broker, 1)
    assert s.smoke(now + timedelta(minutes=1), now.replace(minute=30), close)
    assert s.store.get("readiness")["execution_verified"]


def test_ambiguous_submission_recovery_never_duplicates_entry(runtime):
    s, broker, now, close = runtime
    broker.fail_after_accept = True
    start(runtime)  # existing client-ID recovery resolves the lost response
    assert s.store.get("smoke:" + now.date().isoformat())["entry_client_id"]
    assert s.engine.reconcile(now + timedelta(seconds=30))
    s.engine.cancel_entries(now + timedelta(seconds=30), close)
    s.smoke(now + timedelta(seconds=30), now.replace(minute=30), close)
    assert broker.submissions == 1
    assert len(broker.orders()) == 1


def test_flat_account_without_exit_fill_receipt_cannot_pass(runtime, monkeypatch):
    s, broker, now, close = runtime
    row = start(runtime)
    fill_entry(s, broker, row, 1)
    monkeypatch.setattr(s.engine, "close_intraday", lambda: None)
    monkeypatch.setattr(s.engine, "reconcile", lambda: True)
    s.store.db.execute("DELETE FROM holdings")
    broker.pos = []
    assert not s.smoke(now + timedelta(seconds=30), now.replace(minute=30), close)
    assert not s.store.get("readiness")["execution_verified"]


def test_reconciliation_failure_blocks_gate_after_confirmed_roundtrip(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    fill_entry(s, broker, row, 1)
    s.smoke(now + timedelta(seconds=30), now.replace(minute=30), close)
    fill_exit(s, broker, 1)
    broker.cash += 100  # unexplained external cash cannot be silently accepted
    assert not s.smoke(now + timedelta(minutes=1), now.replace(minute=30), close)
    assert not s.store.get("readiness")["execution_verified"]
    assert "cash_ledger" in s.store.get("reconciliation_errors")


def test_retrospective_operational_proposal_is_durable_and_not_executed(runtime):
    from concurrent.futures import Future

    s, broker, now, close = runtime
    proposal = {
        "problem": "Operational intent is canceled too early",
        "hypothesis": "Persist an explicit bounded intent",
        "requested_change": "Repair execution-check lifecycle in engine.py",
        "validation_plan": "Verify restart recovery and expiration with fake broker",
    }
    s.future = Future()
    s.future.set_result(
        {
            "summary": "Preserve strategy; propose operational repair",
            "observations": [],
            "proposed_lessons": [],
            "experiments": [],
            "code_changes": [proposal],
            "no_change_reason": "No strategy edge",
        }
    )
    s.task = ("test-review", "retrospective", {}, now.date().isoformat())
    s.finish_task()
    row = s.store.rows("SELECT payload FROM memory WHERE layer='improvement_proposal'")[0]
    saved = json.loads(row["payload"])
    assert (
        saved["state"] == "proposed" and saved["requested_change"] == proposal["requested_change"]
    )
    assert broker.submissions == 0


def test_review_contains_terminal_states_incident_details_and_proposals_scope(runtime):
    s, broker, now, close = runtime
    row = start(runtime)
    s.engine.cancel_entries(now + timedelta(minutes=2), close)
    s.engine.reconcile(now + timedelta(minutes=2, seconds=1))
    s.store.event(
        "incident",
        {"code": "execution_timeout", "reason": "Broker cancellation confirmed; no fill"},
    )
    prompt = review_prompt(now.date().isoformat(), s.store)
    packet = json.loads(prompt.split("ROLE: retrospective and experiment designer.\n")[1])
    ops = packet["operational_evidence"]
    assert ops["selected_orders"][0]["status"] == "canceled"
    assert ops["recent_incident_details"][0]["facts"]["code"] == "execution_timeout"
    assert not ops["execution_verified"]
    assert "Runtime/operational repairs" in ops["maintenance_scope"]
    assert "broker_id" not in json.dumps(ops) and row["client_id"] not in json.dumps(ops)
    assert len(prompt) < s.config.max_input_chars


def test_review_period_starts_at_eastern_midnight(store):
    for when, code in [
        ("2026-10-30T02:00:00+00:00", "previous_evening"),
        ("2026-10-30T05:00:00+00:00", "current_day"),
    ]:
        store.db.execute(
            "INSERT INTO events(at,kind,payload) VALUES(?,?,?)",
            (when, "incident", json.dumps({"code": code, "reason": code})),
        )
    prompt = review_prompt("2026-10-30", store)
    packet = json.loads(prompt.split("ROLE: retrospective and experiment designer.\n")[1])
    assert packet["event_counts"] == [{"kind": "incident", "n": 1}]
    assert "previous_evening" not in prompt and "current_day" in prompt
