"""Tests for the Strategy Agent — signal generation logic."""

import pytest
from agent_trader.core.message_bus import MessageBus, Message, MessageType
from agent_trader.agents.strategy_agent import StrategyAgent


@pytest.fixture
def strategy_agent():
    bus = MessageBus()
    return StrategyAgent(bus)


def _make_message(symbols, market_data, research=None, **extra):
    """Helper to create a command message with market data."""
    return Message(
        type=MessageType.COMMAND,
        source="orchestrator",
        data={
            "symbols": symbols,
            "market_data": market_data,
            "research": research or {"stocks": {}},
            **extra,
        },
    )


@pytest.mark.asyncio
async def test_oversold_rsi_generates_buy(strategy_agent):
    """RSI < 35 + MACD bullish + uptrend should produce a buy signal."""
    msg = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 107.0,
                "price_change_pct": -2.0,
                "volume": 1_000_000,
                "indicators": {
                    "rsi_14": 25.0,       # Oversold
                    "macd": 0.5,          # MACD above signal = bullish
                    "macd_signal": 0.3,
                    "sma_20": 105.0,      # Price > SMA20 > SMA50 = uptrend
                    "sma_50": 102.0,
                    "bb_upper": 115.0,
                    "bb_lower": 95.0,
                },
            }
        },
    )

    result = await strategy_agent.process(msg)
    signals = result["signals"]

    assert len(signals) >= 1
    buy_signal = signals[0]
    assert buy_signal["action"] == "buy"
    assert buy_signal["strength"] > 0


@pytest.mark.asyncio
async def test_overbought_rsi_generates_sell(strategy_agent):
    """RSI > 70 + MACD bearish + downtrend should produce a sell signal."""
    msg = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 93.0,
                "price_change_pct": 3.0,
                "volume": 1_000_000,
                "indicators": {
                    "rsi_14": 80.0,       # Overbought
                    "macd": -0.2,         # MACD below signal = bearish
                    "macd_signal": 0.1,
                    "sma_20": 95.0,       # Price < SMA20 < SMA50 = downtrend
                    "sma_50": 98.0,
                    "bb_upper": 105.0,
                    "bb_lower": 90.0,
                },
            }
        },
    )

    result = await strategy_agent.process(msg)
    signals = result["signals"]

    assert len(signals) >= 1
    assert signals[0]["action"] == "sell"


@pytest.mark.asyncio
async def test_neutral_indicators_no_signal(strategy_agent):
    """Neutral indicators should produce no strong consensus signal."""
    msg = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 100.0,
                "price_change_pct": 0.5,
                "volume": 1_000_000,
                "indicators": {
                    "rsi_14": 50.0,       # Neutral
                    "macd": 0.1,
                    "macd_signal": 0.1,
                    "sma_20": 100.0,
                    "sma_50": 100.0,
                    "bb_upper": 110.0,
                    "bb_lower": 90.0,
                },
            }
        },
    )

    result = await strategy_agent.process(msg)
    # May produce a best-available signal, but not a strong consensus one
    for s in result["signals"]:
        if "[BEST AVAILABLE]" not in s.get("reasoning", ""):
            pytest.fail("Non-best-available signal found for neutral indicators")


@pytest.mark.asyncio
async def test_missing_data_skipped(strategy_agent):
    """Stocks with errors should be skipped gracefully."""
    msg = _make_message(
        symbols=["BAD"],
        market_data={"BAD": {"error": "No data found"}},
    )

    result = await strategy_agent.process(msg)
    assert len(result["signals"]) == 0


@pytest.mark.asyncio
async def test_research_boosts_signal(strategy_agent):
    """High research confidence should boost signal strength."""
    base_indicators = {
        "rsi_14": 28.0,
        "macd": 0.5,
        "macd_signal": 0.3,
        "sma_20": 105.0,      # Uptrend: price > SMA20 > SMA50
        "sma_50": 102.0,
        "bb_upper": 115.0,
        "bb_lower": 95.0,
    }

    # Without research
    msg_no_research = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 107.0, "price_change_pct": -2.0,
                "volume": 1_000_000, "indicators": base_indicators,
            }
        },
    )

    # With high-confidence bullish research
    msg_with_research = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 107.0, "price_change_pct": -2.0,
                "volume": 1_000_000, "indicators": base_indicators,
            }
        },
        research={
            "stocks": {
                "TEST": {"recommendation": "buy", "confidence": 0.9}
            }
        },
    )

    result_no = await strategy_agent.process(msg_no_research)
    result_yes = await strategy_agent.process(msg_with_research)

    # Both should have signals
    assert len(result_no["signals"]) > 0
    assert len(result_yes["signals"]) > 0
    # Research-boosted signal should be at least as strong
    assert result_yes["signals"][0]["strength"] >= result_no["signals"][0]["strength"]


@pytest.mark.asyncio
async def test_monitor_phase_requires_llm_gate_for_new_entries(strategy_agent):
    msg = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 107.0,
                "price_change_pct": -2.0,
                "volume": 1_000_000,
                "indicators": {
                    "rsi_14": 25.0,
                    "macd": 0.5,
                    "macd_signal": 0.3,
                    "sma_20": 105.0,
                    "sma_50": 102.0,
                    "bb_upper": 115.0,
                    "bb_lower": 95.0,
                },
            }
        },
        phase="monitor",
        research={"stocks": {"TEST": {"recommendation": "buy", "ready_to_trade": False}}},
    )

    result = await strategy_agent.process(msg)

    assert result["signals"] == []


@pytest.mark.asyncio
async def test_monitor_phase_allows_ready_to_trade_signal(strategy_agent):
    msg = _make_message(
        symbols=["TEST"],
        market_data={
            "TEST": {
                "latest_price": 107.0,
                "price_change_pct": -2.0,
                "volume": 1_000_000,
                "indicators": {
                    "rsi_14": 25.0,
                    "macd": 0.5,
                    "macd_signal": 0.3,
                    "sma_20": 105.0,
                    "sma_50": 102.0,
                    "bb_upper": 115.0,
                    "bb_lower": 95.0,
                },
            }
        },
        phase="monitor",
        research={"stocks": {"TEST": {"recommendation": "buy", "ready_to_trade": True, "confidence": 0.8}}},
    )

    result = await strategy_agent.process(msg)

    assert len(result["signals"]) >= 1
    assert result["signals"][0]["action"] == "buy"
