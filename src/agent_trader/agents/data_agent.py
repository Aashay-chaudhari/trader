"""Data Agent — fetches market data from free sources.

Sources:
  - yfinance: historical prices, fundamentals (free, no API key needed)
  - Future: Alpha Vantage, Polygon.io for real-time data

This agent runs first in the pipeline. Its output (price data + indicators)
feeds into the Research and Strategy agents.
"""

import math
import time
from datetime import datetime, timezone
from typing import Any

import yfinance as yf
import pandas as pd
import ta

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.utils.runtime import configure_yfinance_cache

# yfinance calls can hang on poor network — cap each call
_YFINANCE_TIMEOUT = 30  # seconds


def _safe_float(value) -> float | None:
    """Convert to float, returning None for NaN/Inf."""
    if value is None:
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


class DataAgent(BaseAgent):
    """Fetches and prepares market data."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.DATA, message_bus)
        configure_yfinance_cache()

    async def process(self, message: Message) -> Any:
        symbols: list[str] = message.data.get("symbols", [])
        if not symbols:
            raise ValueError("No symbols provided to DataAgent")

        results = {}
        data_warnings: list[str] = []
        for symbol in symbols:
            t0 = time.monotonic()
            data = self._fetch_stock_data(symbol)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            data["fetch_time_ms"] = elapsed_ms
            results[symbol] = data

            # Check data freshness — flag stale weekend/holiday data
            freshness = self._check_freshness(data)
            if freshness:
                data["freshness_warning"] = freshness
                data_warnings.append(f"{symbol}: {freshness}")

        return {
            "symbols": symbols,
            "market_data": results,
            "data_warnings": data_warnings,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        }

    def _fetch_stock_data(self, symbol: str, period: str = "3mo") -> dict:
        """Fetch price history and compute technical indicators."""
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, timeout=_YFINANCE_TIMEOUT)

        if hist.empty:
            return {"error": f"No data found for {symbol}"}

        # Add technical indicators
        hist = self._add_indicators(hist)

        # Get current info
        info = {}
        try:
            raw_info = ticker.info
            info = {
                "name": raw_info.get("shortName", symbol),
                "sector": raw_info.get("sector", "Unknown"),
                "market_cap": raw_info.get("marketCap"),
                "pe_ratio": raw_info.get("trailingPE"),
                "dividend_yield": raw_info.get("dividendYield"),
                "fifty_two_week_high": raw_info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": raw_info.get("fiftyTwoWeekLow"),
            }
        except Exception:
            pass  # Info fetch can fail; price data is what matters

        # Convert to serializable format (last 30 days for the pipeline)
        recent = hist.tail(30)

        # Sanitize indicators — replace NaN/Inf with None so downstream
        # agents (StrategyAgent) don't silently compute on garbage values.
        return {
            "info": info,
            "latest_price": float(hist["Close"].iloc[-1]),
            "last_trade_date": hist.index[-1].isoformat(),
            "price_change_pct": float(
                (hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100
            ),
            "volume": int(hist["Volume"].iloc[-1]),
            "indicators": {
                "rsi_14": _safe_float(hist["rsi_14"].iloc[-1]) if "rsi_14" in hist else None,
                "sma_20": _safe_float(hist["sma_20"].iloc[-1]) if "sma_20" in hist else None,
                "sma_50": _safe_float(hist["sma_50"].iloc[-1]) if "sma_50" in hist else None,
                "macd": _safe_float(hist["macd"].iloc[-1]) if "macd" in hist else None,
                "macd_signal": _safe_float(hist["macd_signal"].iloc[-1]) if "macd_signal" in hist else None,
                "bb_upper": _safe_float(hist["bb_upper"].iloc[-1]) if "bb_upper" in hist else None,
                "bb_lower": _safe_float(hist["bb_lower"].iloc[-1]) if "bb_lower" in hist else None,
            },
            "price_history": [
                {
                    "date": idx.isoformat(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
                for idx, row in recent.iterrows()
            ],
        }

    def _check_freshness(self, data: dict) -> str | None:
        """Return a warning string if the data looks stale."""
        if "error" in data:
            return None
        last_trade = data.get("last_trade_date")
        if not last_trade:
            return None
        try:
            last_dt = pd.Timestamp(last_trade)
            now = pd.Timestamp.now(tz="UTC")
            # If last trade date is >2 calendar days old (covers weekends),
            # check if today is a weekday — if so, data might be stale.
            gap = (now - last_dt).days
            today_weekday = datetime.now(timezone.utc).weekday()  # 0=Mon
            if gap > 2 or (gap > 1 and today_weekday < 5):
                return f"last trade {gap}d ago ({last_trade[:10]}) — data may be stale"
        except Exception:
            pass
        return None

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add standard technical indicators to price data."""
        close = df["Close"]

        # RSI
        df["rsi_14"] = ta.momentum.RSIIndicator(close, window=14).rsi()

        # Moving averages
        df["sma_20"] = ta.trend.SMAIndicator(close, window=20).sma_indicator()
        df["sma_50"] = ta.trend.SMAIndicator(close, window=50).sma_indicator()

        # MACD
        macd = ta.trend.MACD(close)
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(close, window=20)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()

        return df
