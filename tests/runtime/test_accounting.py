import copy
import json

import pytest

from agent_trader.runtime.accounting import Accounting, accounting_summary
from agent_trader.runtime.broker import Broker


def activity_history(store, *, branch="intraday"):
    for oid, side, price in (("entry", "buy", 759.39), ("exit", "sell", 759.26)):
        store.db.execute(
            "INSERT INTO orders(client_id,broker_id,branch,symbol,side,qty,status,filled,notional,plan_id,payload,at) VALUES(?,?,?,?,?,1,'filled',1,?,'paper-check','{}',?)",
            ("local-" + oid, oid, branch, "SPY", side, price, "2026-11-02T14:35:31Z"),
        )
    store.db.execute("UPDATE branches SET cash=9999.87 WHERE name=?", (branch,))
    store.set("account", {"cash": "29999.84"})
    store.set("last_reconciled", "2026-11-07T18:00:00Z")
    return [
        {
            "id": "funding",
            "activity_type": "JNLC",
            "net_amount": "30000",
            "description": "PRIVATE ACCOUNT DESCRIPTION",
        },
        {
            "id": "cat",
            "activity_type": "FEE",
            "activity_sub_type": "CAT",
            "date": "2026-11-02",
            "currency": "USD",
            "status": "executed",
            "net_amount": "-0.01",
            "description": "CAT fee for proceed of 2 trades on 2026-11-02 by PRIVATE-ACCOUNT",
        },
        {
            "id": "reg",
            "activity_type": "FEE",
            "activity_sub_type": "REG",
            "date": "2026-11-02",
            "currency": "USD",
            "status": "executed",
            "net_amount": "-0.02",
            "description": "REG fee for proceed of $759.26 on 2026-11-02 by PRIVATE-ACCOUNT",
        },
        {
            "id": "fill-entry",
            "activity_type": "FILL",
            "order_id": "entry",
            "type": "fill",
            "transaction_time": "2026-11-02T14:32:42Z",
            "symbol": "SPY",
            "side": "buy",
            "price": "759.39",
            "qty": "1",
        },
        {
            "id": "fill-exit",
            "activity_type": "FILL",
            "order_id": "exit",
            "type": "fill",
            "transaction_time": "2026-11-02T14:35:31Z",
            "symbol": "SPY",
            "side": "sell",
            "price": "759.26",
            "qty": "1",
        },
    ]


def test_receipt_explains_real_fee_shape_without_booking_or_leaking_private_fields(store):
    activities = activity_history(store)
    ledger = Accounting(store)
    summary = ledger.record(activities, complete_history=True)
    assert summary["cash_bridge"]["attributed_unbooked_fee_net"] == -0.03
    assert abs(summary["cash_bridge"]["remaining_after_attributed_fees"]) < 1e-8
    assert summary["cash_bridge"]["arithmetic_matches"]
    assert {f["branch"] for f in summary["fees"]} == {"intraday"}
    assert all(f["attribution_status"] == "attributed_unbooked" for f in summary["fees"])
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 9999.87
    assert not store.rows("SELECT * FROM booked_fees")
    assert "PRIVATE" not in json.dumps(summary)
    assert "activity_id" not in json.dumps(summary)
    assert (
        "PRIVATE"
        in store.rows("SELECT payload FROM broker_activities WHERE id='cat'")[0]["payload"]
    )
    ledger.record(activities, complete_history=True)
    assert len(store.rows("SELECT * FROM broker_activities")) == 5


def test_fee_application_requires_exact_receipt_and_is_atomic_and_idempotent(store):
    ledger = Accounting(store)
    ledger.record(activity_history(store), complete_history=True)
    receipt = store.get("account_activity_receipt")["receipt_hash"]
    with pytest.raises(ValueError, match="receipt changed"):
        ledger.book_attributed_fees(["cat"], expected_receipt_hash="old")
    with pytest.raises(ValueError, match="not unambiguous"):
        ledger.book_attributed_fees(["cat", "not-a-fee"], expected_receipt_hash=receipt)
    assert not store.rows("SELECT * FROM booked_fees")
    ledger.book_attributed_fees(["cat", "reg"], expected_receipt_hash=receipt)
    ledger.book_attributed_fees(["cat", "reg"], expected_receipt_hash=receipt)
    assert len(store.rows("SELECT * FROM booked_fees")) == 2
    assert len(store.rows("SELECT * FROM events WHERE kind='fee_booked'")) == 2
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0][
        "cash"
    ] == pytest.approx(9999.84)
    summary = ledger.summary()
    assert summary["cash_bridge"]["attributed_unbooked_fee_net"] == 0
    assert summary["cash_bridge"]["arithmetic_matches"]


def test_cash_update_failure_rolls_back_fee_entry_and_event(store):
    ledger = Accounting(store)
    ledger.record(activity_history(store), complete_history=True)
    store.db.execute(
        "CREATE TRIGGER fail_fee_update BEFORE UPDATE ON branches BEGIN SELECT RAISE(ABORT, 'fail'); END"
    )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        ledger.book_attributed_fees(
            ["cat"], expected_receipt_hash=store.get("account_activity_receipt")["receipt_hash"]
        )
    assert not store.rows("SELECT * FROM booked_fees")
    assert not store.rows("SELECT * FROM events WHERE kind='fee_booked'")


def test_fee_already_reflected_in_cash_cannot_be_booked_again_without_receipt(store):
    ledger = Accounting(store)
    ledger.record(activity_history(store), complete_history=True)
    store.db.execute("UPDATE branches SET cash=9999.84 WHERE name='intraday'")
    with pytest.raises(ValueError, match="cash bridge"):
        ledger.book_attributed_fees(
            ["cat", "reg"],
            expected_receipt_hash=store.get("account_activity_receipt")["receipt_hash"],
        )
    assert not store.rows("SELECT * FROM booked_fees")
    assert store.rows("SELECT cash FROM branches WHERE name='intraday'")[0]["cash"] == 9999.84


@pytest.mark.parametrize(
    "mutation",
    [
        "external_fill",
        "other_branch",
        "wrong_price",
        "missing_fill",
        "unposted",
        "unsupported_description",
        "positive_fee",
        "foreign_currency",
    ],
)
def test_ambiguous_or_unverified_fees_stay_unattributed(store, mutation):
    activities = activity_history(store)
    if mutation == "external_fill":
        activities[-1]["order_id"] = "unowned-order"
    elif mutation == "other_branch":
        store.db.execute("UPDATE orders SET branch='swing' WHERE broker_id='exit'")
    elif mutation == "wrong_price":
        activities[-1]["price"] = "750"
    elif mutation == "missing_fill":
        activities.pop()
    elif mutation == "unposted":
        activities[1]["status"] = "pending"
        activities[2]["status"] = "pending"
    elif mutation == "unsupported_description":
        activities[1]["description"] = "Unspecified account charge"
        activities[2]["description"] = "Unspecified account charge"
    elif mutation == "positive_fee":
        activities[1]["net_amount"] = "0.01"
        activities[2]["net_amount"] = "0.02"
    elif mutation == "foreign_currency":
        activities[1]["currency"] = activities[2]["currency"] = "EUR"
    ledger = Accounting(store)
    summary = ledger.record(activities, complete_history=True)
    assert all(f["attribution_status"] == "unattributed" for f in summary["fees"])
    assert summary["cash_bridge"]["attributed_unbooked_fee_net"] == 0


def test_partial_history_cannot_support_unique_branch_inference(store):
    ledger = Accounting(store)
    summary = ledger.record(activity_history(store))
    assert not summary["complete_history"]
    assert all(f["reason"] == "incomplete_history" for f in summary["fees"])


def test_changed_activity_identity_does_not_replace_original_or_partially_import(store):
    activities = activity_history(store)
    ledger = Accounting(store)
    ledger.record(activities, complete_history=True)
    receipt = store.get("account_activity_receipt")
    changed = copy.deepcopy(activities)
    changed[1]["net_amount"] = "-999"
    changed.insert(0, {"id": "new", "activity_type": "FEE", "net_amount": "-1"})
    with pytest.raises(ValueError, match="identity changed"):
        ledger.record(changed, complete_history=True)
    assert store.get("account_activity_receipt") == receipt
    assert not store.rows("SELECT * FROM broker_activities WHERE id='new'")
    assert (
        json.loads(
            store.rows("SELECT payload FROM broker_activities WHERE id='cat'")[0]["payload"]
        )["net_amount"]
        == "-0.01"
    )


def test_public_summary_before_intake_is_read_only(store):
    assert accounting_summary(store)["observed_at"] is None
    assert not store.rows("SELECT name FROM sqlite_master WHERE name='broker_activities'")


def test_activity_pagination_uses_last_id_and_rejects_partial_or_repeated_pages():
    broker = Broker.__new__(Broker)
    calls = []
    pages = [[{"id": "a"}, {"id": "b"}], [{"id": "c"}]]

    def request(method, path, *, params):
        assert method == "GET" and path == "/v2/account/activities"
        calls.append(params)
        return pages.pop(0)

    broker.request = request
    assert [r["id"] for r in broker.account_activities(page_size=2)] == ["a", "b", "c"]
    assert calls[1]["page_token"] == "b"
    assert "after" not in calls[0] and "date" not in calls[0]
    broker.request = lambda *a, **k: [{"id": "repeated"}]
    with pytest.raises(ValueError, match="repeated"):
        broker.account_activities(page_size=1)
    with pytest.raises(ValueError, match="partial batch rejected"):
        broker.account_activities(page_size=1, max_pages=1)
