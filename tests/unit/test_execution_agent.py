"""Tests for ExecutionAgent behavior."""

import pytest

from agent_trader.agents.execution_agent import ExecutionAgent
from agent_trader.core.message_bus import Message, MessageType


@pytest.mark.asyncio
async def test_execution_agent_uses_market_data_price_for_dry_run(message_bus, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    agent = ExecutionAgent(message_bus)

    result = await agent.process(
        Message(
            type=MessageType.COMMAND,
            source="test",
            data={
                "approved_trades": [
                    {
                        "symbol": "AAPL",
                        "action": "buy",
                        "suggested_size_pct": 5.0,
                    }
                ],
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"latest_price": 250.0}},
            },
        )
    )

    assert len(result["executed"]) == 1
    assert result["executed"][0]["status"] == "dry_run"
    assert result["executed"][0]["estimated_price"] == 250.0
    assert result["executed"][0]["quantity"] == 20
