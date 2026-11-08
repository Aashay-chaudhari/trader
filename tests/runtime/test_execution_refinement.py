import copy
from datetime import timedelta

import pytest

from agent_trader.runtime.engine import Engine
from tests.runtime.session_fixtures import install


def own_position(store, broker, config, now, plan, *, branch="intraday"):
    engine = Engine(config, store, broker)
    engine.add_plans([{**plan, "branch": branch}], now.date().isoformat())
    parent = {
        "id": "owned-buy",
        "client_order_id": "owned-entry",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "filled_qty": "10",
        "filled_avg_price": "100",
        "status": "filled",
        "type": "limit",
        "limit_price": "100",
        "filled_at": now.isoformat(),
    }
    broker.items[parent["id"]] = parent
    engine.ingest_order(parent, branch, plan["id"])
    broker.cash = 29000
    broker.pos = [{"symbol": "AAPL", "qty": "10", "market_value": "1000"}]
    assert engine.reconcile(now)
    install(store, now)
    broker.quotes = lambda symbols: {s: {"bp": 100, "ap": 100.01, "t": now.isoformat()} for s in symbols}
    return engine, parent


def ready_empty(store, broker, config, now):
    engine = Engine(config, store, broker)
    assert engine.reconcile(now)
    store.set("readiness", {"execution_verified": True})
    install(store, now, closed=now + timedelta(hours=4))
    return engine


def test_exit_does_not_submit_after_post_cancel_reconciliation_fails(
    store, broker, config, now, plan
):
    engine, _ = own_position(store, broker, config, now, plan)
    broker.cash -= 100  # An external change arrives after prior reconciliation.
    assert engine.exit_holding("AAPL", "target reached", now=now) is False
    assert not store.get("reconciled")
    assert broker.submissions == 0


@pytest.mark.parametrize("terminal", ["rejected", "canceled", "expired"])
@pytest.mark.parametrize("kind", ["close", "exit"])
def test_confirmed_terminal_liquidation_can_retry_but_pending_attempt_is_preserved(
    store, broker, config, now, plan, terminal, kind
):
    engine, _ = own_position(store, broker, config, now, plan)
    close = (
        (lambda: engine.close_intraday(now=now)) if kind == "close" else lambda: engine.exit_holding("AAPL", "exit", now=now)
    )
    close()
    first = next(o for o in broker.items.values() if o["side"] == "sell")
    close()
    assert broker.submissions == 1 and first["status"] == "new"
    first["status"] = terminal
    assert engine.reconcile(now)
    close()
    assert broker.submissions == 2
    sells = [o for o in broker.items.values() if o["side"] == "sell"]
    assert len({o["client_order_id"] for o in sells}) == 2
    assert len(store.rows("SELECT * FROM events WHERE kind='liquidation_attempt'")) == 2


def test_ambiguous_liquidation_is_not_retried_under_a_new_id(store, broker, config, now, plan):
    engine, _ = own_position(store, broker, config, now, plan)
    calls = []

    def unknown(payload):
        calls.append(payload)
        raise TimeoutError("No response")

    broker.submit = unknown
    with pytest.raises(TimeoutError):
        engine.close_intraday(now=now)
    with pytest.raises(ValueError, match="Unresolved prepared"):
        engine.close_intraday(now=now)
    assert len(calls) == 1
    assert store.rows("SELECT status FROM orders WHERE side='sell'")[0]["status"] == "prepared"


def test_cancel_request_is_not_confirmation_and_cannot_create_competing_exit(
    store, broker, config, now, plan
):
    engine, _ = own_position(store, broker, config, now, plan)
    stop = {
        "id": "stop",
        "client_order_id": "stop",
        "symbol": "AAPL",
        "side": "sell",
        "qty": "10",
        "filled_qty": "0",
        "filled_avg_price": None,
        "status": "new",
        "type": "stop",
        "stop_price": "97",
    }
    broker.items["stop"] = stop
    engine.ingest_order(stop, "intraday", plan["id"])
    broker.cancel = lambda oid: broker.items[oid].update(status="pending_cancel")
    assert not engine.exit_holding("AAPL", "exit", now=now)
    assert not engine.exit_holding("AAPL", "exit", now=now)
    assert broker.submissions == 0


def test_done_for_day_entry_remains_cancellable_and_reconciles_next_session_fill(
    store, broker, config, now, plan
):
    engine = Engine(config, store, broker)
    engine.add_plans([plan], now.date().isoformat())
    payload = {
        "client_order_id": "gtc",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "1",
        "type": "limit",
        "limit_price": "100",
        "time_in_force": "gtc",
    }
    order = engine.submit_intent(payload, "intraday", plan["id"])
    broker.items[order["id"]]["status"] = "done_for_day"
    engine.ingest_order(broker.items[order["id"]], "intraday", plan["id"])
    engine.cancel_entries(now + timedelta(hours=3), now + timedelta(hours=5))
    assert broker.items[order["id"]]["status"] == "canceled"
    # Cancellation and a fill can race. The previously observed done_for_day
    # status must not exclude this order from the following reconciliation.
    broker.items[order["id"]].update(status="filled", filled_qty="1", filled_avg_price="100")
    broker.cash = 29900
    broker.pos = [{"symbol": "AAPL", "qty": "1", "market_value": "100"}]
    assert engine.reconcile(now + timedelta(days=1))
    assert store.rows("SELECT qty FROM holdings")[0]["qty"] == 1


def test_done_for_day_keeps_symbol_and_cash_reservations(store, broker, config, now, plan, quote):
    engine = ready_empty(store, broker, config, now)
    order = engine.submit_intent(
        {
            "client_order_id": "gtc",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "1",
            "limit_price": "100",
        },
        "swing",
        "other-plan",
    )
    broker.items[order["id"]]["status"] = "done_for_day"
    engine.ingest_order(broker.items[order["id"]], "swing", "other-plan")
    with pytest.raises(ValueError, match="pending order"):
        engine.validate_entry(plan, quote, now, now + timedelta(hours=4))


def test_prior_day_pending_liquidation_not_in_open_list_cannot_duplicate(
    store, broker, config, now, plan
):
    engine, _ = own_position(store, broker, config, now, plan)
    old = {
        "id": "old-exit",
        "client_order_id": "old-exit",
        "symbol": "AAPL",
        "side": "sell",
        "qty": "10",
        "filled_qty": "0",
        "filled_avg_price": None,
        "type": "market",
        "status": "done_for_day",
    }
    broker.items["old-exit"] = old
    engine.ingest_order(old, "intraday", "close:2026-10-29:AAPL")
    broker.orders = lambda: []  # Endpoint view is not a terminal-state receipt.
    engine.close_intraday(now=now)
    assert not engine.exit_holding("AAPL", "exit", now=now)
    assert broker.submissions == 0


def test_candidate_prices_do_not_use_another_pending_order_price(
    store, broker, config, now, plan, quote
):
    engine = ready_empty(store, broker, config, now)
    engine.submit_intent(
        {
            "client_order_id": "other-symbol",
            "symbol": "MSFT",
            "side": "buy",
            "qty": "1",
            "type": "limit",
            "limit_price": "50",
            "stop_loss": {"stop_price": "49"},
        },
        "intraday",
        "other-plan",
    )
    qty, limit = engine.validate_entry(plan, quote, now, now + timedelta(hours=4))
    assert limit == 100
    assert qty * (limit - plan["stop"] + limit * 0.001 + 0.01) <= 50


@pytest.mark.parametrize("where", ["cash", "equity", "qty", "market_value"])
def test_nonfinite_broker_values_cannot_pass_reconciliation(store, broker, config, now, where):
    engine = Engine(config, store, broker)
    if where in ("cash", "equity"):
        original = broker.account
        broker.account = lambda: {**original(), where: "NaN"}
    else:
        broker.pos = [{"symbol": "AAPL", "qty": "1", "market_value": "100", where: "NaN"}]
    with pytest.raises(ValueError, match="valid nonnegative|not finite"):
        engine.reconcile(now)
    assert store.get("reconciled") is False


def test_broker_cannot_enlarge_submitted_buy_quantity(store, broker, config):
    engine = Engine(config, store, broker)
    order = engine.submit_intent(
        {
            "client_order_id": "one-share",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "1",
            "type": "limit",
            "limit_price": "100",
        },
        "intraday",
        "one-share-plan",
    )
    enlarged = {
        **order,
        "qty": "100",
        "filled_qty": "100",
        "filled_avg_price": "100",
        "status": "filled",
    }
    with pytest.raises(ValueError, match="authorized intent"):
        engine.ingest_order(enlarged, "intraday", "one-share-plan")
    assert not store.rows("SELECT * FROM holdings")
    assert store.rows("SELECT qty FROM orders")[0]["qty"] == 1
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 10000


def test_owned_bracket_leg_may_shrink_after_partial_take_profit(store, broker, config, now, plan):
    engine, parent = own_position(store, broker, config, now, plan)
    leg = {
        "id": "bracket-stop",
        "client_order_id": "bracket-stop",
        "symbol": "AAPL",
        "side": "sell",
        "qty": "10",
        "filled_qty": "0",
        "filled_avg_price": None,
        "status": "new",
        "type": "stop",
        "stop_price": "97",
    }
    parent["legs"] = [leg]
    parent["order_class"] = "bracket"
    engine.ingest_order(parent, "intraday", plan["id"])
    engine.ingest_order({**leg, "qty": "6"}, "intraday", plan["id"])
    assert store.rows("SELECT qty FROM orders WHERE broker_id='bracket-stop'")[0]["qty"] == 6


def test_rounding_cannot_spend_more_cash_than_the_branch_owns(store, broker, config, now, plan):
    store.db.execute("UPDATE branches SET cash=100.12,high_water=100.12 WHERE name='intraday'")
    broker.cash = 20100.12
    engine = ready_empty(store, broker, config, now)
    low_price = {**plan, "entry_low": 5.0, "entry_high": 5.1, "stop": 4.9, "target": 5.5}
    quote = {"bp": 5.005, "ap": 5.006, "t": now.isoformat()}
    qty, limit = engine.validate_entry(low_price, quote, now, now + timedelta(hours=4))
    assert limit == 5.01
    assert qty * limit <= 100.12


def test_rounded_order_price_must_remain_in_the_researched_interval(
    store, broker, config, now, plan
):
    engine = ready_empty(store, broker, config, now)
    narrow = {**plan, "entry_low": 100.005, "entry_high": 100.007, "stop": 99, "target": 102}
    with pytest.raises(ValueError, match="Rounded broker prices"):
        engine.validate_entry(
            narrow,
            {"bp": 100.005, "ap": 100.006, "t": now.isoformat()},
            now,
            now + timedelta(hours=4),
        )


def test_asset_lookup_delay_rechecks_quote_age_before_submission(
    store, broker, config, now, plan, quote, monkeypatch
):
    engine = ready_empty(store, broker, config, now)
    engine.add_plans([plan], now.date().isoformat())
    ticks = iter([100.0, 106.0])
    monkeypatch.setattr("agent_trader.runtime.engine.monotonic", lambda: next(ticks))
    quote["t"] = (now - timedelta(seconds=85)).isoformat()
    with pytest.raises(ValueError, match="Quote is stale"):
        engine.enter(plan, quote, now, now + timedelta(hours=4))
    assert broker.submissions == 0


def test_insufficient_stop_quantity_is_replaced_after_confirmed_cancellation(
    store, broker, config, now, plan
):
    engine, _ = own_position(store, broker, config, now, plan)
    stop = {
        "id": "undersized-stop",
        "client_order_id": "undersized-stop",
        "symbol": "AAPL",
        "side": "sell",
        "qty": "1",
        "filled_qty": "0",
        "filled_avg_price": None,
        "status": "new",
        "type": "stop",
        "stop_price": "97",
    }
    broker.items[stop["id"]] = stop
    engine.ingest_order(stop, "intraday", plan["id"])
    engine.ensure_protection(now=now)
    assert stop["status"] == "canceled" and broker.submissions == 0
    assert engine.reconcile(now)
    engine.ensure_protection(now=now)
    active = [o for o in broker.orders() if o["side"] == "sell"]
    assert len(active) == 1 and float(active[0]["qty"]) == 10


def test_same_quantity_fill_price_correction_does_not_silently_rewrite_notional(
    store, broker, config, now, plan
):
    engine, parent = own_position(store, broker, config, now, plan)
    corrected = {**parent, "filled_avg_price": "99.99"}
    with pytest.raises(ValueError, match="corrected fill notional"):
        engine.ingest_order(corrected, "intraday", plan["id"])
    assert store.rows("SELECT notional FROM orders")[0]["notional"] == 1000
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 9000


def test_broker_identity_mutation_cannot_reassign_owned_fills(store, broker, config, now, plan):
    engine, parent = own_position(store, broker, config, now, plan)
    with pytest.raises(ValueError, match="owned intent"):
        engine.ingest_order({**parent, "symbol": "MSFT"}, "intraday", plan["id"])
    missing_client = copy.deepcopy(parent)
    missing_client.pop("client_order_id")
    engine.ingest_order(missing_client, "intraday", plan["id"])
    assert len(store.rows("SELECT * FROM orders")) == 1
    assert store.rows("SELECT symbol FROM holdings")[0]["symbol"] == "AAPL"


def test_overnight_intraday_hold_is_identified_from_broker_fill_date(
    store, broker, config, now, plan
):
    engine, _ = own_position(store, broker, config, now, plan)
    assert engine.overdue_intraday(now) == []
    assert engine.overdue_intraday(now + timedelta(days=1)) == ["AAPL"]
