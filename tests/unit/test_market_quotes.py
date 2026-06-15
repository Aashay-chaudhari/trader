from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_trader.utils.market_quotes import refresh_with_alpaca_iex


class FakeMarketDataClient:
    def __init__(self, *, age_seconds: int = 5):
        timestamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        self.trade = SimpleNamespace(price=101.0, timestamp=timestamp)
        self.quote = SimpleNamespace(
            bid_price=100.8,
            ask_price=101.2,
            bid_size=10,
            ask_size=12,
            timestamp=timestamp,
        )

    def get_stock_latest_trade(self, request):
        return {symbol: self.trade for symbol in request.symbol_or_symbols}

    def get_stock_latest_quote(self, request):
        return {symbol: self.quote for symbol in request.symbol_or_symbols}


def test_refresh_with_alpaca_iex_uses_quote_midpoint_and_preserves_indicators():
    market_data = {"AAPL": {"latest_price": 99.0, "indicators": {"rsi_14": 55.0}}}

    result = refresh_with_alpaca_iex(
        market_data,
        ["AAPL"],
        api_key="key",
        secret_key="secret",
        client=FakeMarketDataClient(),
    )

    assert result["AAPL"]["latest_price"] == 101.0
    assert result["AAPL"]["quote_source"] == "alpaca_iex_quote_midpoint"
    assert result["AAPL"]["quote_is_fresh"] is True
    assert result["AAPL"]["indicators"]["rsi_14"] == 55.0


def test_refresh_with_alpaca_iex_rejects_stale_price():
    with pytest.raises(RuntimeError, match="stale"):
        refresh_with_alpaca_iex(
            {},
            ["AAPL"],
            api_key="key",
            secret_key="secret",
            client=FakeMarketDataClient(age_seconds=180),
        )
