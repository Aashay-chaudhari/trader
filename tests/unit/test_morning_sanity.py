"""Tests for morning research sanity validation."""

import json

from agent_trader.utils.morning_sanity import (
    enrich_morning_theory_fields,
    validate_morning_research_payload,
)


def test_validate_morning_research_flags_large_entry_mismatch():
    payload = {
        "overall_sentiment": "bullish",
        "market_regime": "risk_off",
        "stocks": {
            "XOM": {
                "recommendation": "buy",
                "confidence": 0.74,
                "execution_condition": "XOM must hold above $118.50 while oil stays firm.",
                "trade_plan": {"entry": 122.0, "stop_loss": 118.34, "target": 130.54},
            }
        },
    }

    errors, warnings = validate_morning_research_payload(
        payload,
        reference_prices={"XOM": 159.67},
    )

    assert any("159.67" in error for error in errors)
    assert any("execution_condition" in warning for warning in warnings)


def test_validate_morning_research_accepts_well_formed_buy_plan():
    payload = {
        "overall_sentiment": "bullish",
        "market_regime": "risk_off",
        "stocks": {
            "XOM": {
                "recommendation": "buy",
                "confidence": 0.74,
                "execution_condition": "XOM must hold above $158 before the monitor approves entry.",
                "trade_plan": {"entry": 159.5, "stop_loss": 154.0, "target": 168.0},
            }
        },
    }

    errors, warnings = validate_morning_research_payload(
        payload,
        reference_prices={"XOM": 159.67},
    )

    assert errors == []
    assert warnings == []


def test_enrich_morning_theory_fields_populates_operational_metadata(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    payload = {
        "overall_sentiment": "bullish",
        "market_regime": "risk_on",
        "stocks": {
            "QCOM": {
                "sentiment": "bullish",
                "recommendation": "buy",
                "confidence": 0.68,
                "trade_plan": {"entry": 226.5, "stop_loss": 220.5, "target": 238.0},
            }
        },
    }
    (cache_dir / "morning_research.json").write_text(json.dumps(payload), encoding="utf-8")

    changed = enrich_morning_theory_fields(tmp_path, reference_prices={"QCOM": 218.0})
    enriched = json.loads((cache_dir / "morning_research.json").read_text(encoding="utf-8"))

    assert "QCOM" in changed
    assert enriched["stocks"]["QCOM"]["setup_state"] == "invalidated"
    assert enriched["stocks"]["QCOM"]["watchlist_bucket"] == "repair_watch"
    assert enriched["watchlist_buckets"]["repair_watch"] == ["QCOM"]
    assert enriched["regime_scorecard"]["declared_regime"] == "risk_on"
