import copy
import json
from datetime import timedelta

import pytest

from agent_trader.runtime.engine import Engine, order_id, quote_values
from agent_trader.runtime.models import Plan


def ready(store, broker, config, now):
    e = Engine(config, store, broker)
    assert e.reconcile(now)
    store.set("readiness", {"execution_verified": True})
    return e


def fill(cid="entry-1", qty=10, price=100, side="buy", symbol="AAPL", status="partially_filled"):
    return {
        "id": "broker-" + cid,
        "client_order_id": cid,
        "symbol": symbol,
        "side": side,
        "qty": "20",
        "status": status,
        "filled_qty": str(qty),
        "filled_avg_price": str(price),
    }


def test_submitted_orders_are_not_positions(store, broker, config, now, plan, quote):
    e = ready(store, broker, config, now)
    e.add_plans([plan], "2026-10-30")
    e.enter(plan, quote, now, now + timedelta(hours=5))
    assert not store.rows("SELECT * FROM holdings")
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 10000


def test_partial_fill_and_repeat_reconciliation_do_not_double_book(store, broker, config):
    e = Engine(config, store, broker)
    e.ingest_order(fill(qty=3, price=100), "intraday", "test-plan")
    e.ingest_order(fill(qty=3, price=100), "intraday", "test-plan")
    e.ingest_order(fill(qty=5, price=102), "intraday", "test-plan")
    h = store.rows("SELECT * FROM holdings")[0]
    assert h["qty"] == 5 and h["cost"] == 510
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 9490


def test_partial_sell_allocates_cost_and_cash(store, broker, config):
    e = Engine(config, store, broker)
    e.ingest_order(fill(qty=10), "swing", "plan")
    e.ingest_order(fill(cid="exit", qty=4, price=110, side="sell"), "swing", "plan")
    h = store.rows("SELECT * FROM holdings")[0]
    assert h["qty"] == 6 and h["cost"] == 600
    assert store.rows("SELECT cash FROM branches WHERE name='swing'")[0]["cash"] == 9440


def test_short_or_wrong_branch_sell_rolls_back(store, broker, config):
    e = Engine(config, store, broker)
    e.ingest_order(fill(qty=3), "swing", "plan")
    with pytest.raises(ValueError):
        e.ingest_order(fill(cid="bad", qty=5, side="sell"), "intraday", "bad")
    assert store.rows("SELECT qty FROM holdings")[0]["qty"] == 3
    assert not store.rows("SELECT * FROM orders WHERE client_id='bad'")


def test_timeout_after_accept_recovers_same_order(store, broker, config):
    e = Engine(config, store, broker)
    broker.fail_after_accept = True
    payload = {
        "client_order_id": "stable",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "1",
        "type": "limit",
        "limit_price": "100",
    }
    e.submit_intent(payload, "intraday", "plan")
    e.submit_intent(payload, "intraday", "plan")
    assert broker.submissions == 1
    assert store.rows("SELECT status FROM orders")[0]["status"] == "new"


def test_prepared_unknown_order_blocks_recovery(store, broker, config, now):
    e = Engine(config, store, broker)
    broker.submit = lambda _: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(TimeoutError):
        e.submit_intent(
            {
                "client_order_id": "ambiguous",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "1",
                "limit_price": "100",
            },
            "intraday",
            "plan",
        )
    with pytest.raises(ValueError, match="Unresolved"):
        e.reconcile(now)
    assert store.get("reconciled") is False


def test_external_positions_and_cash_changes_block_entries(store, broker, config, now):
    e = Engine(config, store, broker)
    broker.pos = [{"symbol": "TSLA", "qty": "1", "market_value": "200"}]
    broker.cash = 29800
    assert not e.reconcile(now)
    assert {"TSLA", "cash_ledger"} <= set(store.get("reconciliation_errors"))


@pytest.mark.parametrize(
    "change,match",
    [
        ({"event_risk_known": False}, "event risk"),
        ({"confidence": 0.4}, "confidence"),
        ({"branch": "options"}, "shadow-only"),
        ({"target": 101.5}, "Reward/risk"),
    ],
)
def test_entry_policy_rejects_unsafe_plans(store, broker, config, now, plan, quote, change, match):
    e = ready(store, broker, config, now)
    plan.update(change)
    with pytest.raises(ValueError, match=match):
        e.validate_entry(plan, quote, now, now + timedelta(hours=4))


def test_revalidation_blocks_stale_price_after_model_reply(store, broker, config, now, plan, quote):
    e = ready(store, broker, config, now)
    quote["t"] = (now - timedelta(minutes=3)).isoformat()
    with pytest.raises(ValueError, match="stale"):
        e.enter(plan, quote, now, now + timedelta(hours=4))
    assert broker.submissions == 0


def test_early_close_uses_actual_close(store, broker, config, now, plan, quote):
    e = ready(store, broker, config, now)
    with pytest.raises(ValueError, match="cutoff"):
        e.validate_entry(plan, quote, now, now + timedelta(minutes=20))


def test_duplicate_plan_submission_and_cross_branch_overlap_blocked(
    store, broker, config, now, plan, quote
):
    e = ready(store, broker, config, now)
    e.enter(plan, quote, now, now + timedelta(hours=4))
    with pytest.raises(ValueError, match="already submitted"):
        e.enter(plan, quote, now, now + timedelta(hours=4))
    plan["id"] = "other-plan"
    plan["branch"] = "swing"
    with pytest.raises(ValueError, match="pending order"):
        e.enter(plan, quote, now, now + timedelta(hours=4))
    assert broker.submissions == 1


def test_risk_sizing_and_cash_reservations(store, broker, config, now, plan, quote):
    e = ready(store, broker, config, now)
    qty, price = e.validate_entry(plan, quote, now, now + timedelta(hours=4))
    assert qty * price <= 2000
    assert qty * (price - plan["stop"] + price * 0.001 + 0.01) <= 50
    store.db.execute("UPDATE branches SET cash=50 WHERE name='intraday'")
    with pytest.raises(ValueError, match="Insufficient"):
        e.validate_entry(plan, quote, now, now + timedelta(hours=4))


def test_daily_loss_includes_unrealized_and_drawdown_pause(store, broker, config, now):
    e = ready(store, broker, config, now)
    store.db.execute("UPDATE branches SET cash=9700 WHERE name='intraday'")
    broker.cash = 29700
    assert e.reconcile(now + timedelta(minutes=1))
    b = store.rows("SELECT * FROM branches WHERE name='intraday'")[0]
    assert b["paused"] and b["pause_reason"] == "Daily loss threshold reached"


def test_plan_schema_rejects_inverted_nan_and_timezone_free(plan):
    with pytest.raises(ValueError):
        Plan.model_validate({**plan, "stop": 110})
    with pytest.raises(ValueError):
        Plan.model_validate({**plan, "entry_low": float("nan")})
    with pytest.raises(ValueError):
        Plan.model_validate({**plan, "expires_at": "2026-10-30T10:00:00"})


def test_order_ids_are_stable_and_unique():
    assert order_id("plan", "entry") == order_id("plan", "entry")
    assert order_id("plan", "exit") != order_id("plan", "entry")
    assert len(order_id("plan", "entry")) < 48


def test_daily_halt_stays_closed_after_same_day_recovery(store, broker, config, now):
    e = ready(store, broker, config, now)
    store.db.execute("UPDATE branches SET cash=9700 WHERE name='intraday'")
    broker.cash = 29700
    e.reconcile(now + timedelta(minutes=1))
    store.db.execute("UPDATE branches SET cash=10000 WHERE name='intraday'")
    broker.cash = 30000
    e.reconcile(now + timedelta(minutes=2))
    assert store.rows("SELECT paused FROM branches WHERE name='intraday'")[0]["paused"] == 1
    e.reconcile(now + timedelta(days=1))
    assert store.rows("SELECT paused FROM branches WHERE name='intraday'")[0]["paused"] == 0


def test_child_bracket_fill_after_parent_terminal_is_reconciled(store, broker, config, now):
    e = Engine(config, store, broker)
    parent = fill(qty=10, status="filled")
    parent["legs"] = [fill(cid="stop", qty=0, price=0, side="sell", status="held")]
    broker.items[parent["id"]] = parent
    broker.items[parent["legs"][0]["id"]] = parent["legs"][0]
    e.ingest_order(parent, "swing", "plan")
    broker.cash = 29000
    broker.pos = [{"symbol": "AAPL", "qty": "10", "market_value": "1000"}]
    assert e.reconcile(now)
    child = fill(cid="stop", qty=10, price=97, side="sell", status="filled")
    broker.items[child["id"]] = child
    broker.items[parent["id"]]["legs"] = [child]
    broker.cash = 29970
    broker.pos = []
    assert e.reconcile(now + timedelta(minutes=1))
    assert not store.rows("SELECT * FROM holdings")
    assert store.rows("SELECT cash FROM branches WHERE name='swing'")[0]["cash"] == 9970


def test_pending_orders_reserve_risk_as_well_as_cash(store, broker, config, now, plan, quote):
    e = ready(store, broker, config, now)
    e.submit_intent(
        {
            "client_order_id": "risk-reservation",
            "symbol": "MSFT",
            "side": "buy",
            "qty": "100",
            "limit_price": "20",
            "stop_loss": {"stop_price": "16"},
        },
        "intraday",
        "pending",
    )
    with pytest.raises(ValueError, match="risk limit"):
        e.validate_entry(plan, quote, now, now + timedelta(hours=4))


def test_invalid_fill_price_never_creates_free_position(store, broker, config):
    e = Engine(config, store, broker)
    with pytest.raises(ValueError, match="Invalid broker fill"):
        e.ingest_order(fill(qty=10, price=0), "intraday", "bad")
    assert not store.rows("SELECT * FROM holdings")


def test_cannot_cancel_protection_with_unreconciled_state(store, broker, config):
    e = Engine(config, store, broker)
    store.set("reconciled", False)
    with pytest.raises(ValueError, match="unreconciled"):
        e.close_intraday()


def test_missing_stop_is_restored_after_rejected_exit(store, broker, config, now, plan):
    e = Engine(config, store, broker)
    e.add_plans([plan], "2026-10-30")
    parent = fill(qty=10, status="filled")
    e.ingest_order(parent, "swing", plan["id"])
    broker.items[parent["id"]] = parent
    broker.pos = [{"symbol": "AAPL", "qty": "10", "market_value": "1000"}]
    broker.cash = 29000
    assert e.reconcile(now)
    e.ensure_protection()
    protect = [o for o in broker.items.values() if o["side"] == "sell"]
    assert len(protect) == 1 and protect[0]["type"] == "stop"
    assert protect[0]["stop_price"] == "97.0"


def test_active_strategy_extension_contract(plan):
    from agent_trader.strategies.adaptive import candidate_filter, VERSION

    assert isinstance(VERSION, str)
    for regime in ["risk_on", "mixed", "risk_off", "unknown"]:
        assert type(candidate_filter(plan, {"regime": regime})) is bool
