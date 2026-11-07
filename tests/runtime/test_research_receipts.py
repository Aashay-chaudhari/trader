import copy
from datetime import timedelta

from agent_trader.runtime.accounting import Accounting
from agent_trader.runtime.research_work import _context, evidence_packets, next_work, prepare_task
from agent_trader.runtime.store import dumps
from tests.runtime.test_research_work import complete


def runtime(store):
    store.set("readiness", {"at": "2026-10-30T21:00:00+00:00", "execution_verified": True,
                            "execution_verified_at": "2026-10-29T15:00:00+00:00",
                            "required_execution_kernel": "new-kernel", "verified_execution_kernel": "old-kernel"})
    store.set("calendar:2026-10-30", [{"date": "2026-10-30", "open": "09:30", "close": "13:00"}])
    store.set("coverage_tracking_started", "2026-10-29T00:00:00+00:00")
    for slot in (0, 1, 41):
        store.db.execute("INSERT INTO session_health VALUES(?,?,?,?,?)", ("2026-10-30", slot, "2026-10-30T16:55:00+00:00", 1, int(slot != 1)))
    store.db.execute("INSERT INTO session_health VALUES(?,?,?,?,?)", ("2026-10-30", 42, "2026-10-30T17:00:00+00:00", 1, 1))
    store.set("smoke:2026-10-29", {"state": "passed", "verified_at": "2026-10-29T15:00:00+00:00", "entry_filled_qty": 1, "exit_filled_qty": 1, "entry_client_id": "private-id"})


def test_current_kernel_and_distinct_early_close_coverage_are_truthful_and_private(store, now):
    runtime(store)
    packet = evidence_packets(store)["runtime_reliability"]
    record = packet["records"][0]
    facts = record["value"]
    assert facts["current_required_kernel_verified"] is False
    assert facts["historical_execution_checks"][0]["state"] == "passed"
    coverage = facts["completed_session_coverage"][0]
    assert coverage["expected_slots"] == 42
    assert coverage["distinct_recorded_slots"] == 3
    assert coverage["broker_confirmed_slots"] == 3 and coverage["research_ready_slots"] == 2
    assert coverage["longest_unconfirmed_gap_minutes"] == 195
    assert "five-minute sampled" in facts["scope"]
    assert "private-id" not in dumps(packet)
    assert record["observation_metadata"]["readiness_observed_at"]
    context = _context("runtime_reliability", packet)
    assert context["snapshot_hash"]
    prepare_task(store, context)


def test_refresh_only_metadata_preserves_work_identity_but_actual_coverage_and_kernel_changes_requeue(store, now):
    runtime(store)
    request = next_work(store, now)
    before = request["context"]
    complete(store, request, now)
    ready = store.get("readiness")
    ready["at"] = "2026-10-30T21:00:01.123456+00:00"
    store.set("readiness", ready)
    store.set("last_reconciled", "2026-10-30T21:00:01+00:00")
    store.db.execute("UPDATE session_health SET at='2026-10-30T16:56:00+00:00'")
    refreshed = _context("runtime_reliability", evidence_packets(store)["runtime_reliability"])
    assert before["work_id"] == refreshed["work_id"]
    assert before["snapshot_hash"] != refreshed["snapshot_hash"]
    assert next_work(store, now + timedelta(minutes=1)) is None
    store.db.execute("INSERT INTO session_health VALUES(?,?,?,?,?)", ("2026-10-30", 2, "2026-10-30T13:40:00+00:00", 1, 1))
    newer = next_work(store, now + timedelta(minutes=2))
    assert newer["context"]["work_id"] != before["work_id"]
    complete(store, newer, now + timedelta(minutes=2))
    ready["verified_execution_kernel"] = "new-kernel"
    store.set("readiness", ready)
    latest = next_work(store, now + timedelta(minutes=3))
    assert latest["context"]["work_id"] != newer["context"]["work_id"]


def test_signed_cash_receipts_expose_funding_and_flow_cutoffs_without_private_fields(store, now):
    store.set("account", {"cash": "29999.84", "equity": "29999.84"})
    store.set("last_reconciled", "2026-10-30T21:00:00+00:00")
    accounting = Accounting(store)
    activities = [
        {"id": "private-funding", "activity_type": "JNLC", "date": "2026-10-29", "status": "executed", "net_amount": "30000", "description": "private account"},
        {"id": "private-entry", "activity_type": "FILL", "transaction_time": "2026-10-30T14:30:00Z", "side": "buy", "qty": "1", "price": "759.39"},
        {"id": "private-exit", "activity_type": "FILL", "transaction_time": "2026-10-30T14:35:00Z", "side": "sell", "qty": "1", "price": "759.26"},
        {"id": "private-fee", "activity_type": "FEE", "date": "2026-10-30", "status": "executed", "net_amount": "-0.03"},
    ]
    accounting.record(activities, complete_history=True, observed_at="2026-10-30T21:00:00+00:00")
    packet = evidence_packets(store)["accounting_attribution"]
    record = next(r for r in packet["records"] if r["kind"] == "signed_broker_activity")
    facts = record["value"]
    assert facts["signed_cash_net_by_type"] == {"FEE": "-0.03", "FILL": "-0.13", "JNLC": "30000"}
    assert facts["signed_cash_net_total"] == "29999.84"
    assert facts["journal_receipts"] == [{"date": "2026-10-29", "signed_amount": "30000", "status": "executed"}]
    assert facts["last_activity_date_or_time"] == "2026-10-30T14:35:00Z"
    assert "private-" not in dumps(packet) and "private account" not in dumps(packet)
    assert "not proof of a prior zero balance" in facts["scope"]
    frozen = _context("accounting_attribution", packet)
    accounting.record(copy.deepcopy(activities), complete_history=True, observed_at="2026-10-30T21:02:00+00:00")
    refreshed = _context("accounting_attribution", evidence_packets(store)["accounting_attribution"])
    assert frozen["work_id"] == refreshed["work_id"]
    assert frozen["snapshot_hash"] != refreshed["snapshot_hash"]
    activities.append({"id": "private-extra-fee", "activity_type": "FEE", "date": "2026-10-30", "status": "executed", "net_amount": "-0.01"})
    accounting.record(activities, complete_history=True)
    assert _context("accounting_attribution", evidence_packets(store)["accounting_attribution"])["work_id"] != frozen["work_id"]


def test_old_frozen_context_remains_valid_after_observation_metadata_support(store):
    packet = {"records": [{"id": "ev:old", "kind": "receipt", "value": "historical fact"}], "omitted_records": 0}
    old = _context("accounting_attribution", packet)
    assert "snapshot_hash" not in old
    prepare_task(store, old)
