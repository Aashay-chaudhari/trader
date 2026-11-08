"""Real cancellation paths retain protection until entry receipts confirm closure."""

from datetime import datetime, timedelta

import pytest

from agent_trader.runtime.config import ET
from agent_trader.runtime.engine import Engine, EXECUTION_KERNEL
from agent_trader.runtime.models import Pulse
from agent_trader.runtime import supervisor
from tests.runtime import test_atomic_applications as applications
from tests.runtime import test_scheduler_priorities as priorities
from tests.runtime.test_pulse_cancellation_delivery import intents
from tests.runtime.session_fixtures import install

runtime = applications.runtime
scheduler = priorities.scheduler


def seed_positions(instance, broker, now):
    rows = {}
    for symbol in ("AAPL", "MSFT"):
        buy = instance.engine.submit_intent({
            "symbol": symbol, "qty": "2" if symbol == "AAPL" else "1", "side": "buy",
            "type": "limit", "limit_price": "100", "time_in_force": "day",
            "client_order_id": "entry-" + symbol,
        }, "intraday", "plan-" + symbol)
        broker.items[buy["id"]].update(
            filled_qty="1", filled_avg_price="100", filled_at=now.isoformat(),
            status="partially_filled" if symbol == "AAPL" else "filled",
        )
        instance.engine.ingest_order(broker.order(buy["id"]), "intraday", "plan-" + symbol,
                                     expected_client_id="entry-" + symbol)
        stop = instance.engine.submit_intent({
            "symbol": symbol, "qty": "1", "side": "sell", "type": "stop", "stop_price": "90",
            "time_in_force": "gtc", "client_order_id": "stop-" + symbol,
        }, "intraday", "plan-" + symbol)
        rows[symbol] = (buy["id"], stop["id"])
    broker.cash = 29800
    broker.pos = [{"symbol": symbol, "qty": "1", "market_value": "100"} for symbol in rows]
    assert instance.engine.reconcile(now)
    install(instance.store, now)
    broker.quotes = lambda symbols: {s: {"bp": 100, "ap": 100.01, "t": now.isoformat()} for s in symbols}
    return rows


def queue_pulse(instance):
    result = Pulse.model_validate({
        "summary": "Material evidence requires refreshing every pending entry.",
        "material_change": True, "affected_symbols": ["AAPL"], "events": [], "sources": [], "unknowns": [],
    }).model_dump(mode="json")
    applications.queue(instance, result, role="pulse")


@pytest.mark.parametrize("pulse_owned", [False, True])
def test_actual_tick_attempts_sibling_cancellation_and_reaches_protection_after_timeout(
    scheduler, broker, monkeypatch, pulse_owned
):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    ids = {}
    for symbol in ("AAPL", "MSFT"):
        order = scheduler.engine.submit_intent({
            "symbol": symbol, "qty": "1", "side": "buy", "type": "limit", "limit_price": "100",
            "time_in_force": "day", "client_order_id": "entry-" + symbol,
        }, "intraday", "missing-plan-" + symbol)
        ids[symbol] = order["id"]
    priorities.prepare(scheduler, broker, monkeypatch, now)
    monkeypatch.setattr(scheduler.engine, "reconcile", Engine.reconcile.__get__(scheduler.engine, Engine))
    monkeypatch.setattr(scheduler.engine, "cancel_entries", Engine.cancel_entries.__get__(scheduler.engine, Engine))
    scheduler.store.set("readiness", {
        "execution_verified": True, "models_available": True, "funded": True,
        "required_execution_kernel": EXECUTION_KERNEL, "verified_execution_kernel": EXECUTION_KERNEL,
    })
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    if pulse_owned:
        queue_pulse(scheduler)
    requests, reached = [], []
    original_cancel, protection = broker.cancel, scheduler.engine.ensure_protection

    def cancel(identity):
        requests.append(identity)
        if identity == ids["AAPL"]:
            raise TimeoutError("First cancellation fails independently")
        original_cancel(identity)

    def ensure_protection(**kwargs):
        reached.append("protection")
        protection(**kwargs)

    monkeypatch.setattr(broker, "cancel", cancel)
    monkeypatch.setattr(scheduler.engine, "ensure_protection", ensure_protection)
    scheduler.tick(now)
    assert set(requests) == set(ids.values()) and len(requests) == 2
    assert reached == ["protection"]
    assert broker.submissions == 2
    if pulse_owned:
        assert intents(scheduler.store)["entry-AAPL"]["state"] == "uncertain"
        assert intents(scheduler.store)["entry-MSFT"]["state"] == "requested"


def test_same_tick_market_candidate_cannot_enter_after_ordinary_cancel_failure(
    scheduler, broker, monkeypatch, plan
):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    close = now.replace(hour=16)
    scheduler.engine.submit_intent({
        "symbol": "SPY", "qty": "1", "side": "buy", "type": "limit", "limit_price": "100",
        "time_in_force": "day", "client_order_id": "expired-entry",
    }, "intraday", "missing-plan")
    priorities.prepare(scheduler, broker, monkeypatch, now)
    monkeypatch.setattr(scheduler.engine, "reconcile", Engine.reconcile.__get__(scheduler.engine, Engine))
    monkeypatch.setattr(scheduler.engine, "cancel_entries", Engine.cancel_entries.__get__(scheduler.engine, Engine))
    monkeypatch.setattr(scheduler, "market_tick", supervisor.Supervisor.market_tick.__get__(scheduler, supervisor.Supervisor))
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    scheduler.store.set("readiness", {
        "execution_verified": True, "models_available": True, "funded": True,
        "required_execution_kernel": EXECUTION_KERNEL, "verified_execution_kernel": EXECUTION_KERNEL,
    })
    scheduler.store.set("market_open", True)
    scheduler.store.set("brief", {"regime": "mixed"})
    plan["expires_at"] = (now + timedelta(hours=2)).isoformat()
    plan["evidence"][0].update(observed_at=now.isoformat(), published_at=now.isoformat())
    scheduler.engine.add_plans([plan], now.date().isoformat())
    scheduler.store.db.execute("UPDATE plans SET state='approved'")
    scheduler.store.set("approval:" + plan["id"], {"at": now.isoformat()})
    quote = {"bp": 99.99, "ap": 100.0, "t": now.isoformat()}
    monkeypatch.setattr(broker, "quotes", lambda symbols: {symbol: quote for symbol in symbols})
    assert scheduler.engine.reconcile(now)
    install(scheduler.store, now)
    assert scheduler.engine.validate_entry(plan, quote, now, close)[0] > 0

    def fail_cancel(identity):
        raise TimeoutError("Ordinary cancellation is uncertain")

    monkeypatch.setattr(broker, "cancel", fail_cancel)
    scheduler.tick(now)
    assert scheduler.store.get("reconciled") is True
    assert scheduler.store.get("entry_budget_blocked") is True
    assert broker.submissions == 1
    assert scheduler.store.rows("SELECT client_id FROM orders WHERE symbol='AAPL'") == []
    blocked = scheduler.store.rows("SELECT payload FROM events WHERE kind='entry_blocked'")
    assert any("new entries blocked" in item["payload"] for item in blocked)


@pytest.mark.parametrize("pulse_owned", [False, True])
def test_failed_or_deferred_entry_keeps_its_stop_while_other_symbol_closes(runtime, broker, monkeypatch, pulse_owned):
    now = datetime(2026, 11, 9, 15, 50, tzinfo=ET)
    rows = seed_positions(runtime, broker, now)
    if pulse_owned:
        queue_pulse(runtime)
        runtime.finish_task()
    requests, original = [], broker.cancel

    def cancel(identity):
        requests.append(identity)
        if identity == rows["AAPL"][0]:
            raise TimeoutError("Entry cancellation is uncertain")
        original(identity)

    monkeypatch.setattr(broker, "cancel", cancel)
    runtime.engine.close_intraday(now=now)
    assert broker.items[rows["AAPL"][1]]["status"] == "new"
    assert rows["AAPL"][1] not in requests
    assert (rows["AAPL"][0] in requests) is not pulse_owned
    exits = [order for order in broker.items.values() if order["type"] == "market"]
    assert [order["symbol"] for order in exits] == ["MSFT"]
    assert exits[0]["qty"] == "1.0"
    if not pulse_owned:
        assert runtime.store.rows("SELECT id FROM events WHERE kind='order_cancellation_uncertain'")


def test_authorized_exit_waits_for_terminal_entry_before_canceling_protection(runtime, broker, monkeypatch):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    rows = seed_positions(runtime, broker, now)
    queue_pulse(runtime)
    runtime.finish_task()
    requests, original = [], broker.cancel
    monkeypatch.setattr(broker, "cancel", lambda identity: requests.append(identity) or original(identity))
    assert runtime.engine.exit_holding("AAPL", "Verified exit condition", now=now) is False
    assert requests == []
    assert broker.items[rows["AAPL"][1]]["status"] == "new"
    runtime.apply_pulse_cancellations(now)
    assert requests == [rows["AAPL"][0]]
    assert runtime.engine.reconcile(now)
    assert runtime.engine.exit_holding("AAPL", "Verified exit condition", now=now) is True
    assert requests == [rows["AAPL"][0], rows["AAPL"][1]]
    assert [o["symbol"] for o in broker.items.values() if o["type"] == "market"] == ["AAPL"]


def test_protection_repair_keeps_pending_entry_stop_and_repairs_unrelated_symbol(runtime, broker):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
    rows = seed_positions(runtime, broker, now)
    queue_pulse(runtime)
    runtime.finish_task()
    broker.items[rows["MSFT"][1]]["status"] = "canceled"
    assert runtime.engine.reconcile(now)
    previous = broker.submissions
    runtime.engine.ensure_protection(now=now)
    assert broker.items[rows["AAPL"][0]]["status"] == "partially_filled"
    assert broker.items[rows["AAPL"][1]]["status"] == "new"
    assert broker.submissions == previous + 1
    assert broker.items["broker-" + str(broker.submissions)]["symbol"] == "MSFT"
    assert broker.items["broker-" + str(broker.submissions)]["type"] == "stop"


@pytest.mark.parametrize("closing,overdue", [(False, False), (True, False), (False, True)])
def test_real_tick_isolates_pulse_transport_failure_and_preserves_cooldown(
    scheduler, broker, monkeypatch, closing, overdue
):
    now = datetime(2026, 11, 9, 15 if closing else 10, 50 if closing else 0, tzinfo=ET)
    rows = seed_positions(scheduler, broker, now - timedelta(days=1) if overdue else now)
    priorities.prepare(scheduler, broker, monkeypatch, now)
    monkeypatch.setattr(scheduler.engine, "reconcile", Engine.reconcile.__get__(scheduler.engine, Engine))
    monkeypatch.setattr(scheduler.engine, "cancel_entries", Engine.cancel_entries.__get__(scheduler.engine, Engine))
    scheduler.store.set("readiness", {
        "execution_verified": True, "models_available": True, "funded": True,
        "required_execution_kernel": EXECUTION_KERNEL, "verified_execution_kernel": EXECUTION_KERNEL,
    })
    monkeypatch.setattr(scheduler, "launch", lambda *args: False)
    queue_pulse(scheduler)
    requests = []
    original = broker.cancel

    def cancel(identity):
        requests.append(identity)
        if identity == rows["AAPL"][0]:
            raise TimeoutError("Pulse entry cancellation remains uncertain")
        original(identity)

    monkeypatch.setattr(broker, "cancel", cancel)
    scheduler.tick(now)
    assert requests.count(rows["AAPL"][0]) == 1
    assert broker.items[rows["AAPL"][1]]["status"] == "new"
    assert intents(scheduler.store)["entry-AAPL"]["state"] == "uncertain"
    if closing or overdue:
        assert [o["symbol"] for o in broker.items.values() if o["type"] == "market"] == ["MSFT"]
    else:
        assert not any(o["type"] == "market" for o in broker.items.values())
    scheduler.engine.cancel_entries(now + timedelta(seconds=10), now.replace(hour=16, minute=0))
    scheduler.engine.close_intraday(now=now + timedelta(seconds=10))
    scheduler.apply_pulse_cancellations(now + timedelta(seconds=10))
    assert requests.count(rows["AAPL"][0]) == 1
    assert broker.items[rows["AAPL"][1]]["status"] == "new"
