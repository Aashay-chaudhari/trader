"""Prospective feature qualification and atomic comparison-quote provenance."""

import copy
from datetime import timedelta

import pytest

from agent_trader.runtime import adaptive_lab
from agent_trader.runtime.adaptive_lab import INPUT_VALIDATION_VERSION, PROTOCOL
from agent_trader.runtime.daily_inputs import build_daily_inputs
from agent_trader.runtime.observation_audit import content_hash, quote_receipt_status
from agent_trader.runtime.store import dumps
from tests.runtime.test_adaptive_lab import (
    archive, at, contract, daily_source_fixture, quote, rows, run, setup,
)


def relative_setup(store):
    return setup(store, predicates=[{"field": "relative_gap_spy", "operator": "gte", "value": 0}])


def test_relative_entry_retains_exact_used_spy_quote_and_does_not_change_contract(store):
    lab, now, supplied = relative_setup(store)
    contract_before = store.rows("SELECT * FROM adaptive_contracts")[0]
    protocol_before = copy.deepcopy(PROTOCOL)
    older_spy = quote(now - timedelta(minutes=30), 99.99, 100)
    supplied["market"] = {"SPY": {"latestQuote": older_spy}}
    archive(store, supplied, now)
    actual_spy = {**quote(now - timedelta(seconds=70), 100.24, 100.25), "private_extra": "not part of quote receipt"}
    run(lab, now, supplied, {"AAPL": quote(now), "SPY": actual_spy})
    entry = rows(store)[0]
    assert entry["state"] == "open"
    value = entry["payload"]["features"]["relative_gap_spy"]
    assert value == pytest.approx(100.01 / 99 - 1 - (100.25 / 100 - 1))
    validation = entry["payload"]["input_validation"]
    assert validation["version"] == INPUT_VALIDATION_VERSION
    assert validation["daily_fields"] == {"AAPL": ["last_daily_close"], "SPY": ["last_daily_close"]}
    assert validation["subject_spy_quote_gap_seconds"] == 70  # Existing 90-second freshness policy retained.
    receipt = store.get("observation-quote:adaptive:" + entry["id"] + ":entry")
    assert receipt["version"] == "observation-quote-receipt-v2"
    assert receipt["quote"] == quote(now)
    assert receipt["dependencies"] == {"SPY": {k: actual_spy[k] for k in ("bp", "ap", "t")}}
    assert receipt["dependencies"]["SPY"] != older_spy
    assert receipt["calculation"]["input_validation"] == validation
    assert quote_receipt_status(receipt, ["SPY"], identity=("adaptive", entry["id"], "entry")) == "retained"
    assert PROTOCOL == protocol_before
    contract_after = store.rows("SELECT * FROM adaptive_contracts")[0]
    for field in ("id", "payload", "specification_sha256", "fingerprint", "registered_at"):
        assert contract_after[field] == contract_before[field]
    assert not store.rows("SELECT * FROM plans") and not store.rows("SELECT * FROM orders")


@pytest.mark.parametrize("case", ["no_validation", "missing_receipt", "value_tamper", "late_receipt"])
def test_latest_asof_and_archived_packet_alone_cannot_qualify_future_daily_inputs(store, case):
    lab, now, supplied = setup(store)
    reference = supplied["daily_input_validation"]["receipt_reference"]
    if case == "no_validation":
        supplied.pop("daily_input_validation")
    elif case == "missing_receipt":
        store.db.execute("DELETE FROM kv WHERE key=?", (reference,))
    elif case == "value_tamper":
        supplied["daily_indicators"]["AAPL"]["return_3d"] = -0.10
    else:
        original = store.get(reference)
        payload = {k: v for k, v in original.items() if k != "sha256"}
        payload["received_at"] = (now + timedelta(seconds=1)).isoformat()
        digest = content_hash(payload)
        newer_reference = "daily-inputs:" + digest
        store.set(newer_reference, {**payload, "sha256": digest})
        supplied["daily_input_validation"].update(receipt_reference=newer_reference, sha256=digest)
    archive(store, supplied, now)
    run(lab, now, supplied)
    first = rows(store)[0]
    assert first["state"] == "pending" and "signal" not in first["payload"]
    assert "Daily" in first["payload"]["last_missing_reason"]
    assert store.get("observation-quote:adaptive:" + first["id"] + ":entry") is None
    lab.expire(at(clock="10:00"))
    assert rows(store)[0]["state"] == "not_evaluable"
    assert "signal" not in rows(store)[0]["payload"]


@pytest.mark.parametrize("minutes_before_entry,expected", [(31, "pending"), (0.5, "pending"), (-1, "pending"), (2, "open")])
def test_acquisition_completion_must_follow_start_and_precede_archive(store, minutes_before_entry, expected):
    lab, now, supplied = setup(store)
    supplied["completed_at"] = (now - timedelta(minutes=minutes_before_entry)).isoformat()
    archive(store, supplied, now)
    run(lab, now, supplied)
    first = rows(store)[0]
    assert first["state"] == expected
    if expected == "pending":
        assert "acquisition interval" in first["payload"]["last_missing_reason"]
        assert "signal" not in first["payload"]


def test_missing_intermediate_close_preserves_calendar_return_but_not_one_day_return(store):
    lab, now, supplied = setup(store)
    bars, calendar = daily_source_fixture(now)
    bars["AAPL"] = [b for b in bars["AAPL"] if not b["t"].startswith("2026-10-29")]
    indicators, validation = build_daily_inputs(
        store, bars, calendar, as_of=now.date().isoformat(), observed_at=supplied["observed_at"],
        received_at=(now - timedelta(minutes=29)).isoformat(),
        source_metadata={"feed": "iex", "adjustment": "all", "timeframe": "1Day"},
        symbols=["AAPL", "SPY"],
    )
    supplied.update(daily_indicators=indicators, daily_input_validation=validation)
    archive(store, supplied, now)
    assert indicators["AAPL"]["return_1d"] is None and indicators["AAPL"]["sma20"] is None
    assert indicators["AAPL"]["return_3d"] == pytest.approx(-0.04)
    run(lab, now, supplied)
    assert rows(store)[0]["state"] == "open"
    assert rows(store)[0]["payload"]["features"]["return_3d"] == pytest.approx(-0.04)
    # The absent one-session endpoint cannot be borrowed from an older row.
    with pytest.raises(ValueError, match="return_1d unavailable"):
        lab._features({"predicates": [{"field": "return_1d"}]}, "AAPL", quote(now), {}, supplied, now, "2026-10-30")


def test_spy_quote_receipt_failure_rolls_back_entry_and_retry_is_immutable(store, monkeypatch):
    lab, now, supplied = relative_setup(store)
    original = adaptive_lab.record_quote

    def fail_after_receipt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected dependency receipt failure")

    monkeypatch.setattr(adaptive_lab, "record_quote", fail_after_receipt)
    quotes = {"AAPL": quote(now), "SPY": quote(now, 100.24, 100.25)}
    with pytest.raises(RuntimeError, match="dependency receipt"):
        run(lab, now, supplied, quotes)
    first = rows(store)[0]
    assert first["state"] == "pending" and "entered_at" not in first["payload"]
    assert store.get("observation-quote:adaptive:" + first["id"] + ":entry") is None
    monkeypatch.setattr(adaptive_lab, "record_quote", original)
    run(lab, now, supplied, quotes)
    receipt = store.get("observation-quote:adaptive:" + first["id"] + ":entry")
    run(lab, now + timedelta(seconds=10), supplied, {"AAPL": quote(now), "SPY": quote(now, 100.49, 100.5)})
    assert store.get("observation-quote:adaptive:" + first["id"] + ":entry") == receipt
    assert receipt["dependencies"]["SPY"] == quotes["SPY"]


def test_summary_reports_legacy_and_prospective_lineage_without_backfill(store):
    lab, now, supplied = relative_setup(store)
    quotes = {"AAPL": quote(now), "SPY": quote(now, 100.24, 100.25)}
    run(lab, now, supplied, quotes)
    legacy = rows(store)[0]
    legacy["payload"].pop("input_validation")
    legacy_blob = dumps(legacy["payload"])
    store.db.execute("UPDATE adaptive_observations SET payload=? WHERE id=?", (legacy_blob, legacy["id"]))
    store.db.execute("DELETE FROM kv WHERE key=?", ("observation-quote:adaptive:" + legacy["id"] + ":entry",))
    lab.register(contract(id="future-version", predicates=[{"field": "relative_gap_spy", "operator": "gte", "value": 0.001}]), at("2026-10-31", "12:00"))
    run(lab, now, supplied, quotes)
    before = store.db.total_changes
    trials = {t["id"]: t for t in lab.summary()["trials"]}
    assert store.db.total_changes == before
    old = trials[legacy["contract_id"]]["input_lineage"]
    new = trials["future-version"]["input_lineage"]
    assert old["legacy_or_unversioned"] == old["missing_or_invalid_spy_receipts"] == 1
    assert old["daily_validation_recorded"] == old["direct_spy_quote_receipts"] == 0
    assert new["daily_validation_recorded"] == new["direct_spy_quote_receipts"] == 1
    assert new["legacy_or_unversioned"] == new["missing_or_invalid_spy_receipts"] == 0
    assert store.rows("SELECT payload FROM adaptive_observations WHERE id=?", (legacy["id"],))[0]["payload"] == legacy_blob
    assert store.get("observation-quote:adaptive:" + legacy["id"] + ":entry") is None


def test_dependency_receipt_status_rejects_changed_content_or_wrong_observation_identity(store):
    lab, now, supplied = relative_setup(store)
    run(lab, now, supplied, {"AAPL": quote(now), "SPY": quote(now, 100.24, 100.25)})
    first = rows(store)[0]
    receipt = store.get("observation-quote:adaptive:" + first["id"] + ":entry")
    changed = copy.deepcopy(receipt)
    changed["dependencies"]["SPY"]["ap"] = 999
    assert quote_receipt_status(changed, ["SPY"]) == "invalid"
    assert quote_receipt_status(receipt, ["SPY"], identity=("adaptive", "different-observation", "entry")) == "invalid"
    assert quote_receipt_status(receipt, ["QQQ"]) == "dependencies_missing"
