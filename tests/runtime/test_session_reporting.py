"""Published session health follows current evidence, not a cached open label."""

from copy import deepcopy

from agent_trader.runtime import publish


def evidence():
    return {
        "version": "operational-session-evidence-v1",
        "day": "2026-11-09",
        "calendar_raw": [{"date": "2026-11-09", "open": "09:30", "close": "16:00", "private_debug": "private-provider-extra"}],
        "clock_raw": {"is_open": True, "timestamp": "2026-11-09T10:00:00-05:00", "next_open": "2026-11-10T09:30:00-05:00", "next_close": "2026-11-09T16:00:00-05:00", "private_debug": "private-provider-extra"},
        "source_errors": [],
        "calendar_receipt": {"requested_at": "2026-11-09T09:00:00-05:00", "received_at": "2026-11-09T09:00:01-05:00", "sha256": "a" * 64, "reference": "private-reference"},
        "clock_receipt": {"requested_at": "2026-11-09T09:59:59-05:00", "received_at": "2026-11-09T10:00:00-05:00", "sha256": "b" * 64, "reference": "private-reference"},
        "assessment": {"state": "open", "market_open": True},
    }


def test_snapshot_reassesses_old_open_receipt_without_rewriting_it(config, store, monkeypatch):
    original = evidence()
    store.set("operational_session", original)
    monkeypatch.setattr(publish, "utc_now", lambda: "2026-11-09T15:00:00+00:00")
    assert publish.snapshot(config, store)["operational_session"]["state"] == "open"
    monkeypatch.setattr(publish, "utc_now", lambda: "2026-11-09T15:00:31+00:00")
    stale = publish.snapshot(config, store)["operational_session"]
    assert stale["state"] == "unknown"
    assert stale["market_open"] is False
    assert "clock_timestamp_stale" in stale["reason_codes"]
    assert store.get("operational_session") == original


def test_public_session_projection_retains_diagnostic_receipts_without_private_raw(config, store, monkeypatch):
    store.set("operational_session", evidence())
    monkeypatch.setattr(publish, "utc_now", lambda: "2026-11-09T15:00:00+00:00")
    session = publish.snapshot(config, store)["operational_session"]
    assert session["calendar"]["close_at"] == "2026-11-09T16:00:00-05:00"
    assert session["receipts"]["clock"]["sha256"] == "b" * 64
    assert session["receipts"]["calendar"]["received_at"] == "2026-11-09T09:00:01-05:00"
    assert "private-reference" not in str(session)
    assert "private-provider-extra" not in str(session)
    assert "clock_raw" not in session
    assert "not a guarantee" in session["scope"]


def test_missing_or_unavailable_session_never_inherits_boolean_market_open(config, store, monkeypatch):
    monkeypatch.setattr(publish, "utc_now", lambda: "2026-11-09T15:00:00+00:00")
    store.set("market_open", True)
    for value in (None, {}, {"assessment": {"state": "open"}}, {**deepcopy(evidence()), "source_errors": ["clock_fetch_failed"]}):
        store.set("operational_session", value)
        result = publish.snapshot(config, store)["operational_session"]
        assert result["state"] == "unknown"
        assert result["market_open"] is False
        assert result["reason_codes"]
