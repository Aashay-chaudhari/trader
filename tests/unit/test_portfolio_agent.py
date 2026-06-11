"""Tests for portfolio accounting."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_trader.agents.portfolio_agent import PortfolioAgent
from agent_trader.core.message_bus import Message, MessageType


class MockSettings:
    data_dir = ""
    agent_profile = "codex"
    agent_label = "Codex Strategist"
    llm_provider = "openai"
    run_mode = "paper"
    paper_portfolio_value = 100_000.0

    @property
    def is_dry_run(self):
        return False


@pytest.mark.asyncio
async def test_portfolio_records_submitted_trade_cost_basis(message_bus, tmp_path):
    settings = MockSettings()
    settings.data_dir = str(tmp_path)
    agent = PortfolioAgent(message_bus)

    with patch("agent_trader.agents.portfolio_agent.get_settings", return_value=settings):
        snapshot = await agent.process(
            Message(
                type=MessageType.COMMAND,
                source="test",
                data={
                    "executed": [
                        {
                            "symbol": "KBH",
                            "action": "buy",
                            "quantity": 100,
                            "estimated_price": 50.0,
                            "status": "submitted",
                        }
                    ],
                    "market_data": {"KBH": {"latest_price": 52.0}},
                },
            )
        )

    assert snapshot["cash"] == 95_000.0
    assert snapshot["invested"] == 5_000.0
    assert snapshot["total_pnl"] == 200.0
    assert snapshot["positions"][0]["avg_cost"] == 50.0

    state = json.loads((Path(tmp_path) / "portfolio_state.json").read_text())
    assert state["KBH"]["total_invested"] == 5_000.0
    assert state["KBH"]["trades"][0]["price"] == 50.0


@pytest.mark.asyncio
async def test_portfolio_reduces_cost_basis_on_partial_sell(message_bus, tmp_path):
    settings = MockSettings()
    settings.data_dir = str(tmp_path)
    state_path = Path(tmp_path) / "portfolio_state.json"
    state_path.write_text(
        json.dumps(
            {
                "KBH": {
                    "shares": 100,
                    "avg_cost": 50.0,
                    "total_invested": 5_000.0,
                    "trades": [],
                }
            }
        )
    )
    agent = PortfolioAgent(message_bus)

    with patch("agent_trader.agents.portfolio_agent.get_settings", return_value=settings):
        snapshot = await agent.process(
            Message(
                type=MessageType.COMMAND,
                source="test",
                data={
                    "executed": [
                        {
                            "symbol": "KBH",
                            "action": "sell",
                            "quantity": 40,
                            "estimated_price": 55.0,
                            "status": "submitted",
                        }
                    ],
                    "market_data": {"KBH": {"latest_price": 56.0}},
                },
            )
        )

    assert snapshot["cash"] == 97_200.0
    assert snapshot["invested"] == 3_000.0
    assert snapshot["positions"][0]["shares"] == 60
    assert snapshot["positions"][0]["avg_cost"] == 50.0
    assert snapshot["positions"][0]["unrealized_pnl"] == 360.0
    assert snapshot["total_pnl"] == 560.0
    assert snapshot["realized_pnl"] == 200.0
