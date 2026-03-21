"""Tests for the Risk Agent — the safety net."""

import pytest
from unittest.mock import patch

from agent_trader.core.message_bus import MessageBus, Message, MessageType
from agent_trader.agents.risk_agent import RiskAgent


@pytest.fixture
def risk_agent():
    bus = MessageBus()
    return RiskAgent(bus)


def _make_message(signals, market_data=None):
    return Message(
        type=MessageType.COMMAND,
        source="orchestrator",
        data={
            "signals": signals,
            "market_data": market_data or {},
            "symbols": [],
        },
    )


def _mock_settings(**overrides):
    """Create a mock settings object."""
    defaults = {
        "min_signal_strength": 0.3,
        "max_position_pct": 10.0,
        "max_daily_loss_pct": 2.0,
    }
    defaults.update(overrides)

    class MockSettings:
        pass

    s = MockSettings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


@pytest.mark.asyncio
async def test_strong_signal_approved(risk_agent):
    """A strong signal with normal market data should be approved."""
    with patch("agent_trader.agents.risk_agent.get_settings", return_value=_mock_settings()):
        msg = _make_message(
            signals=[{
                "symbol": "AAPL",
                "action": "buy",
                "strength": 0.7,
                "suggested_size_pct": 5.0,
            }],
            market_data={
                "AAPL": {"price_change_pct": 1.5, "volume": 500_000},
            },
        )

        result = await risk_agent.process(msg)
        assert len(result["approved_trades"]) == 1
        assert len(result["rejected_trades"]) == 0


@pytest.mark.asyncio
async def test_weak_signal_rejected(risk_agent):
    """A signal below minimum strength should be rejected."""
    with patch("agent_trader.agents.risk_agent.get_settings", return_value=_mock_settings()):
        msg = _make_message(
            signals=[{
                "symbol": "AAPL",
                "action": "buy",
                "strength": 0.1,  # Below 0.3 minimum
                "suggested_size_pct": 5.0,
            }],
            market_data={
                "AAPL": {"price_change_pct": 1.0, "volume": 500_000},
            },
        )

        result = await risk_agent.process(msg)
        assert len(result["approved_trades"]) == 0
        assert len(result["rejected_trades"]) == 1
        assert "signal" in str(result["rejected_trades"][0]["rejection_reasons"]).lower()


@pytest.mark.asyncio
async def test_extreme_price_move_rejected(risk_agent):
    """Stocks with >15% daily move should be flagged."""
    with patch("agent_trader.agents.risk_agent.get_settings", return_value=_mock_settings()):
        msg = _make_message(
            signals=[{
                "symbol": "WILD",
                "action": "buy",
                "strength": 0.8,
                "suggested_size_pct": 5.0,
            }],
            market_data={
                "WILD": {"price_change_pct": 20.0, "volume": 500_000},
            },
        )

        result = await risk_agent.process(msg)
        assert len(result["rejected_trades"]) == 1


@pytest.mark.asyncio
async def test_low_volume_rejected(risk_agent):
    """Stocks with very low volume should be rejected."""
    with patch("agent_trader.agents.risk_agent.get_settings", return_value=_mock_settings()):
        msg = _make_message(
            signals=[{
                "symbol": "THIN",
                "action": "buy",
                "strength": 0.7,
                "suggested_size_pct": 5.0,
            }],
            market_data={
                "THIN": {"price_change_pct": 1.0, "volume": 50},
            },
        )

        result = await risk_agent.process(msg)
        assert len(result["rejected_trades"]) == 1
