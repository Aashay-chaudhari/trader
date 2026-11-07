import json

from agent_trader.runtime.publish import snapshot


def test_legacy_input_is_not_retroactively_calendar_validated(config, store):
    store.set("market_packet", {
        "observed_at": "2026-11-06T13:15:00+00:00",
        "daily_indicators": {"SPY": {"return_3d": 0.02}},
    })
    result = snapshot(config, store)["research_input_quality"]
    assert result["state"] == "legacy_or_unversioned"
    assert "expected_previous_session" not in result
    assert "field_missing_counts" not in result
    assert result["acquisition_interval"]["completed_at"] is None


def test_public_input_quality_retains_availability_without_private_source_rows(config, store):
    store.set("market_packet", {
        "observed_at": "2026-11-09T14:29:50+00:00",
        "acquisition_interval": {
            "started_at": "2026-11-09T14:29:50+00:00",
            "completed_at": "2026-11-09T14:30:10+00:00",
            "crossed_et_date": False,
            "crossed_regular_open": True,
            "crossed_regular_close": False,
            "raw_response": "private-acquisition-row",
        },
        "daily_input_validation": {
            "version": "calendar-daily-inputs-v1", "state": "partial",
            "expected_previous_session": "2026-11-06",
            "field_missing_counts": {"return_1d": 1},
            "receipt_reference": "private-source-reference",
            "source": {"feed": "iex", "adjustment": "all", "timeframe": "1Day",
                       "raw_response": "private-source-row"},
        },
    })
    result = snapshot(config, store)["research_input_quality"]
    assert result["state"] == "partial"
    assert result["expected_previous_session"] == "2026-11-06"
    assert result["field_missing_counts"] == {"return_1d": 1}
    assert result["acquisition_interval"]["crossed_regular_open"] is True
    assert result["source"] == {"feed": "iex", "adjustment": "all", "timeframe": "1Day"}
    assert "private-" not in json.dumps(result)


def test_failed_new_collection_is_unavailable_not_legacy(config, store):
    store.set("market_packet", {
        "observed_at": "2026-11-09T14:29:50+00:00",
        "daily_input_validation": {
            "version": "calendar-daily-inputs-v1", "state": "unavailable",
            "collection_error": "provider_transport_error",
            "expected_previous_session": None,
            "source": {"feed": "iex", "adjustment": "all", "timeframe": "1Day"},
        },
    })
    result = snapshot(config, store)["research_input_quality"]
    assert result["state"] == "unavailable"
    assert result["collection_error"] == "provider_transport_error"
    assert "field_missing_counts" not in result
    assert "receipt_reference" not in result
