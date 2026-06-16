"""Tests for ExecutionAgent behavior."""

import pytest
import json

from agent_trader.agents.execution_agent import ExecutionAgent
from agent_trader.config.settings import reset_settings
from agent_trader.core.message_bus import Message, MessageType


@pytest.mark.asyncio
async def test_execution_agent_uses_market_data_price_for_dry_run(message_bus, monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_MODE", "debug")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings()
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
async def test_execution_agent_submits_paper_order_when_not_dry_run(message_bus, monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_MODE", "paper")
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings()

    class FakeOrder:
        id = "order-123"

    submitted_requests = []

    class FakeClient:
        def submit_order(self, order_request):
            submitted_requests.append(order_request)
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
                        "client_order_id": "codex-20260614-aapl-buy-1",
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
    assert result["executed"][0]["client_order_id"] == "codex-20260614-aapl-buy-1"
    assert result["executed"][0]["estimated_price"] == 250.0
    assert result["executed"][0]["estimated_value"] == 5000.0
    assert submitted_requests[0].kwargs["client_order_id"] == "codex-20260614-aapl-buy-1"


@pytest.mark.asyncio
async def test_execution_agent_uses_stop_loss_risk_sizing_with_position_cap(
    message_bus, monkeypatch, tmp_path
):
    monkeypatch.setenv("RUN_MODE", "debug")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "latest.json").write_text(
        json.dumps({"portfolio_value": 100_000, "cash": 100_000}),
        encoding="utf-8",
    )
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
                        "entry": 100.0,
                        "stop_loss": 95.0,
                    }
                ],
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"latest_price": 100.0}},
            },
        )
    )

    assert result["executed"][0]["status"] == "dry_run"
    assert result["executed"][0]["quantity"] == 100
    assert result["executed"][0]["estimated_value"] == 10_000


@pytest.mark.asyncio
async def test_execution_agent_blocks_when_position_cap_is_full(
    message_bus, monkeypatch, tmp_path
):
    monkeypatch.setenv("RUN_MODE", "debug")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "latest.json").write_text(
        json.dumps({"portfolio_value": 100_000, "cash": 50_000}),
        encoding="utf-8",
    )
    (tmp_path / "portfolio_state.json").write_text(
        json.dumps({"AAPL": {"current_value": 10_000}}),
        encoding="utf-8",
    )
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
                        "entry": 100.0,
                        "stop_loss": 95.0,
                    }
                ],
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"latest_price": 100.0}},
            },
        )
    )

    assert result["executed"][0]["status"] == "failed"
    assert "below 1 share" in result["executed"][0]["reason"]


@pytest.mark.asyncio
async def test_execution_agent_rejects_sell_without_modeled_long_position(
    message_bus, monkeypatch, tmp_path
):
    monkeypatch.setenv("RUN_MODE", "debug")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "latest.json").write_text(
        json.dumps({"portfolio_value": 100_000, "cash": 100_000}),
        encoding="utf-8",
    )
    agent = ExecutionAgent(message_bus)

    result = await agent.process(
        Message(
            type=MessageType.COMMAND,
            source="test",
            data={
                "approved_trades": [
                    {
                        "symbol": "AAPL",
                        "action": "sell",
                        "entry": 100.0,
                        "stop_loss": 105.0,
                    }
                ],
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"latest_price": 100.0}},
            },
        )
    )

    assert result["executed"][0]["status"] == "failed"
    assert "short sales are not modeled" in result["executed"][0]["reason"]


@pytest.mark.asyncio
async def test_execution_agent_sell_exits_existing_position_without_buy_side_cap(
    message_bus, monkeypatch, tmp_path
):
    monkeypatch.setenv("RUN_MODE", "debug")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    reset_settings()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "latest.json").write_text(
        json.dumps({"portfolio_value": 100_000, "cash": 0}),
        encoding="utf-8",
    )
    (tmp_path / "portfolio_state.json").write_text(
        json.dumps({"AAPL": {"shares": 80, "current_value": 20_000}}),
        encoding="utf-8",
    )
    agent = ExecutionAgent(message_bus)

    result = await agent.process(
        Message(
            type=MessageType.COMMAND,
            source="test",
            data={
                "approved_trades": [
                    {
                        "symbol": "AAPL",
                        "action": "sell",
                        "entry": 250.0,
                        "stop_loss": 260.0,
                    }
                ],
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"latest_price": 250.0}},
            },
        )
    )

    assert result["executed"][0]["status"] == "dry_run"
    assert result["executed"][0]["quantity"] == 80
    assert result["executed"][0]["estimated_value"] == 20_000
