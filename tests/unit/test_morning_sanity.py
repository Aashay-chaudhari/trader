"""Tests for morning research sanity validation."""

from agent_trader.utils.morning_sanity import validate_morning_research_payload


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
