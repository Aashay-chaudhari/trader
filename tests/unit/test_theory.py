"""Tests for operational trading theory helpers."""

from agent_trader.utils.theory import (
    build_regime_scorecard,
    build_watchlist_buckets,
    normalize_stock_theory,
)


def test_regime_scorecard_requires_broad_confirmation_for_risk_on():
    scorecard = build_regime_scorecard(
        {
            "sp500": {"change_pct": 0.8, "trend": "up"},
            "nasdaq": {"change_pct": -0.4},
            "vix": {"level": "normal", "change": -0.2},
            "sector_performance": {
                "Technology": {"daily_pct": -0.6},
                "Industrial": {"daily_pct": 0.4},
                "Healthcare": {"daily_pct": 0.2},
            },
            "market_regime": "risk_on",
        },
        declared_regime="risk_on",
    )

    assert scorecard["declared_regime"] == "risk_on"
    assert scorecard["computed_regime"] == "neutral"
    assert scorecard["bullish_factors"] < 5


def test_normalize_stock_theory_marks_stop_breach_invalidated():
    stock = normalize_stock_theory(
        {
            "sentiment": "bullish",
            "recommendation": "buy",
            "confidence": 0.68,
            "trade_plan": {"entry": 226.5, "stop_loss": 220.5, "target": 238.0},
        },
        current_price=218.0,
    )

    assert stock["setup_state"] == "invalidated"
    assert stock["watchlist_bucket"] == "repair_watch"
    assert stock["action_confidence"]["entry"] == 0.68
    assert "repair" in stock["top_blocker"]


def test_build_watchlist_buckets_groups_operational_posture():
    buckets = build_watchlist_buckets(
        {
            "QCOM": normalize_stock_theory(
                {
                    "recommendation": "buy",
                    "confidence": 0.7,
                    "trade_plan": {"entry": 226.5, "stop_loss": 220.5, "target": 238.0},
                },
                current_price=218.0,
            ),
            "WDC": normalize_stock_theory(
                {
                    "recommendation": "watch",
                    "confidence": 0.6,
                    "catalysts": ["AI storage demand"],
                    "swing_thesis": {"entry_quality": "chasing", "crowding_risk": "high"},
                    "trade_plan": {"entry": 610.0, "stop_loss": 592.0, "target": 660.0},
                }
            ),
        }
    )

    assert buckets["repair_watch"] == ["QCOM"]
    assert buckets["do_not_chase"] == ["WDC"]
