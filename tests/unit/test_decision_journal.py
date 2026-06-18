"""Tests for monitor decision journal evidence capture."""

import json
from pathlib import Path

from agent_trader.utils.decision_journal import (
    build_decision_journal,
    format_decision_journals_for_prompt,
    write_decision_journal,
)


def test_build_decision_journal_tracks_skipped_setup_and_distances():
    payload = build_decision_journal(
        run_id="20260616_150000",
        symbols=["AAPL"],
        morning_context={
            "market_regime": "neutral",
            "stocks": {
                "AAPL": {
                    "recommendation": "buy",
                    "confidence": 0.7,
                    "execution_condition": "AAPL must reclaim $101.",
                    "trade_plan": {"entry": 101, "stop_loss": 97, "target": 110},
                }
            },
        },
        monitor_research={
            "stocks": {
                "AAPL": {
                    "recommendation": "watch",
                    "ready_to_trade": False,
                    "top_blocker": "Still below trigger",
                    "action_confidence": {
                        "long_thesis": 0.7,
                        "entry": 0.35,
                        "avoid": 0.65,
                        "data_quality": 0.8,
                    },
                }
            }
        },
        market_data={"AAPL": {"latest_price": 100}},
        market_context={"sp500_trend": "up", "vix_direction": "down"},
        news_data={"AAPL": {"news_headlines": [{"title": "test"}], "source_count": 1}},
        source_stats={"yfinance": 1},
        provider_health={"yfinance": {"status": "ok", "items": 1}},
        signals=[],
        risk_data={},
        execution_data={},
    )

    decision = payload["decisions"][0]
    assert decision["outcome"] == "skipped"
    assert decision["top_blocker"] == "Still below trigger"
    assert decision["pct_from_entry"] == -0.99
    assert payload["summary"]["skipped"] == 1
    assert payload["news_quality"]["source_stats"]["yfinance"] == 1


def test_write_and_format_decision_journal(tmp_path):
    payload = build_decision_journal(
        run_id="20260616_150000",
        symbols=["MSFT"],
        morning_context={"stocks": {"MSFT": {"recommendation": "watch"}}},
        monitor_research={},
        market_data={"MSFT": {"latest_price": 410}},
        market_context={},
        news_data={},
        risk_data={},
        execution_data={},
    )

    path = write_decision_journal(payload, data_dir=str(tmp_path))
    stored = json.loads(Path(path).read_text(encoding="utf-8"))
    formatted = format_decision_journals_for_prompt([stored])

    assert Path(path).exists()
    assert stored["decisions"][0]["symbol"] == "MSFT"
    assert "MSFT: outcome=skipped" in formatted
