from datetime import datetime

import pytest

from agent_trader.runtime.config import ET
from agent_trader.runtime.quality import daily_audit, digest, record_artifact


def capture(store, at, unknowns, *, minute=True, daily=True, calendar=True, close="16:00"):
    day = at.date().isoformat()
    if calendar:
        store.set("calendar:" + day, [{"date": day, "open": "09:30", "close": close}])
    packet = {
        "observed_at": at.isoformat(), "focus_symbols": ["NVDA"],
        "market": {}, "daily_indicators": {}, "intraday_indicators": {},
    }
    for symbol in ("NVDA", "SPY", "QQQ", "TLT"):
        if daily:
            packet["daily_indicators"][symbol] = {"return_1d": 0.01, "return_3d": -0.02, "return_5d": 0.02}
        if minute:
            packet["intraday_indicators"][symbol] = {"bar_vwap_iex": 100, "opening_5m_high": 102, "opening_5m_low": 98}
    store.set("market_packet", packet)
    store.memory_put("input:" + at.isoformat(), "research_input", {
        "observed_at": at.isoformat(), "packet": packet, "day": day,
    })
    record_artifact(store, day, "research", {"summary": "No entry justified", "unknowns": unknowns, "plans": []}, "research:" + at.isoformat(), observed_at=at.isoformat())
    return packet


def report(store, day="2026-11-06"):
    result = daily_audit(store, day)
    return result, {f["id"] for f in result["findings"]}


def test_preopen_missing_minute_features_are_expected_not_a_collection_fault(store):
    capture(store, datetime(2026, 11, 6, 8, 15, tzinfo=ET), ["No current-session opening-range or bar-VWAP features exist."], minute=False)
    result, findings = report(store)
    feature = result["feature_diagnostics"]
    assert result["reported_mentions"]["price_structure"] == 1
    assert result["reported_blockers"]["price_structure"] == 1
    assert feature["phase_counts"] == {"preopen": 1}
    assert feature["state_counts"] == {"expected_session_phase_absence": 1}
    assert feature["records"][0]["expected_missing_count"] == 12
    assert "missing_price_features" not in findings


def test_same_missing_fields_during_regular_session_need_actual_input_inspection(store):
    capture(store, datetime(2026, 11, 6, 10, 0, tzinfo=ET), ["Opening range and VWAP are unavailable."], minute=False)
    result, findings = report(store)
    feature = result["feature_diagnostics"]
    assert feature["matched_inputs"] == 1
    assert feature["state_counts"] == {"reported_blocker_with_input_gaps": 1}
    assert feature["records"][0]["unexpected_missing_count"] == 12
    assert "missing_price_features" in findings


@pytest.mark.parametrize("text", [
    "VWAP is not missing and no longer the blocker.",
    "Opening range and VWAP are quote observations, not guaranteed fills.",
    "Fresh VWAP resolves the earlier price-data gap.",
])
def test_negations_resolution_and_limitations_are_not_missing_feature_claims(store, text):
    capture(store, datetime(2026, 11, 6, 10, 0, tzinfo=ET), [text])
    result, findings = report(store)
    assert result["reported_mentions"]["price_structure"] == 1
    assert "price_structure" not in result["reported_blockers"]
    assert "missing_price_features" not in findings
    assert "feature_blocker_attribution" not in findings


def test_a_reported_setup_gap_with_supplied_fields_is_not_called_missing_data(store):
    capture(store, datetime(2026, 11, 6, 10, 0, tzinfo=ET), ["Actionable entry structure and VWAP confirmation are unavailable."])
    result, findings = report(store)
    assert result["feature_diagnostics"]["state_counts"] == {"reported_blocker_with_supplied_features": 1}
    assert "feature_blocker_attribution" in findings
    assert "missing_price_features" not in findings


def test_no_matching_packet_means_unknown_not_a_missing_input_diagnosis(store):
    record_artifact(store, "2026-11-06", "research", {"unknowns": ["VWAP unavailable"], "plans": []}, "no-input")
    result, findings = report(store)
    assert result["feature_diagnostics"]["matched_inputs"] == 0
    assert result["feature_diagnostics"]["records"][0]["unexpected_missing_count"] is None
    assert "feature_input_lineage" in findings
    assert "missing_price_features" not in findings


def test_phase_requires_broker_calendar_not_a_guessed_regular_open(store):
    capture(store, datetime(2026, 11, 6, 8, 15, tzinfo=ET), ["Opening range unavailable"], minute=False, calendar=False)
    result, findings = report(store)
    assert result["feature_diagnostics"]["state_counts"] == {"phase_unverified": 1}
    assert "feature_input_lineage" in findings
    assert "missing_price_features" not in findings


def test_early_close_and_non_session_inputs_do_not_use_regular_day_assumptions(store):
    capture(store, datetime(2026, 11, 27, 13, 1, tzinfo=ET), ["VWAP unavailable"], minute=False, close="13:00")
    result, findings = report(store, "2026-11-27")
    assert result["feature_diagnostics"]["phase_counts"] == {"after_close": 1}
    assert "missing_price_features" not in findings
    capture(store, datetime(2026, 11, 28, 10, 0, tzinfo=ET), ["VWAP unavailable"], minute=False)
    store.set("calendar:2026-11-28", [])
    result, findings = report(store, "2026-11-28")
    assert result["feature_diagnostics"]["phase_counts"] == {"non_session": 1}
    assert "missing_price_features" not in findings


def test_missing_completed_daily_features_are_not_excused_by_preopen_phase(store):
    capture(store, datetime(2026, 11, 6, 8, 15, tzinfo=ET), ["Exact three-session returns are missing."], minute=False, daily=False)
    result, findings = report(store)
    assert "missing_price_features" in findings
    assert result["feature_diagnostics"]["records"][0]["daily_complete_symbols"] == 0


def test_rejected_research_is_retained_but_does_not_drive_input_failure_diagnosis(store):
    record_artifact(store, "2026-11-06", "research", {"unknowns": ["VWAP unavailable"], "plans": []}, "rejected", outcome="rejected")
    result, findings = report(store)
    assert result["reported_mentions"]["price_structure"] == 1
    assert result["feature_diagnostics"]["research_reports"] == 0
    assert not findings


def test_digest_has_bounded_phase_summary_without_full_private_packets(store):
    capture(store, datetime(2026, 11, 6, 8, 15, tzinfo=ET), ["Opening range unavailable"], minute=False)
    capture(store, datetime(2026, 11, 6, 9, 45, tzinfo=ET), ["VWAP no longer the blocker"])
    summary = digest(store, "2026-11-06")["feature_diagnostics"]
    assert summary["research_reports"] == 2 and summary["matched_inputs"] == 2
    assert len(summary["recent_records"]) == 2
    assert "records" not in summary
    assert "daily_indicators" not in str(summary)
    assert "intraday_indicators" not in str(summary)
