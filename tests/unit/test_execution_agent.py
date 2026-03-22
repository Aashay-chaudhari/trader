"""Tests for ExecutionAgent behavior."""

import pytest

from agent_trader.agents.execution_agent import ExecutionAgent
from agent_trader.core.message_bus import Message, MessageType


@pytest.mark.asyncio
async def test_execution_agent_uses_market_data_price_for_dry_run(message_bus, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "debug")
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


@pytest.mark.asyncio
async def test_execution_agent_submits_paper_order_when_not_dry_run(message_bus, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "paper")
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    class FakeOrder:
        id = "order-123"

    class FakeClient:
        def submit_order(self, order_request):
            return FakeOrder()

    class FakeOrderSide:
        BUY = "buy"
        SELL = "sell"

    class FakeTimeInForce:
        DAY = "day"

    class FakeMarketOrderRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    import types
    import sys
    monkeypatch.setitem(sys.modules, "alpaca", types.ModuleType("alpaca"))
    monkeypatch.setitem(sys.modules, "alpaca.trading", types.ModuleType("alpaca.trading"))
    requests_mod = types.ModuleType("alpaca.trading.requests")
    requests_mod.MarketOrderRequest = FakeMarketOrderRequest
    enums_mod = types.ModuleType("alpaca.trading.enums")
    enums_mod.OrderSide = FakeOrderSide
    enums_mod.TimeInForce = FakeTimeInForce
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests_mod)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums_mod)

    agent = ExecutionAgent(message_bus)
    monkeypatch.setattr(agent, "_get_client", lambda: FakeClient())

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
                        "entry": 250.0,
                    }
                ],
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"latest_price": 250.0}},
            },
        )
    )

    assert len(result["executed"]) == 1
    assert result["executed"][0]["status"] == "submitted"
    assert result["executed"][0]["order_id"] == "order-123"
