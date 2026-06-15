"""Latest-price overlays used immediately before broker execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def refresh_with_alpaca_iex(
    market_data: dict[str, Any],
    symbols: list[str],
    *,
    api_key: str,
    secret_key: str,
    client: Any | None = None,
) -> dict[str, Any]:
    """Overlay real-time Alpaca IEX trades and quotes onto market data.

    IEX is the real-time stock feed available to Alpaca paper-only accounts.
    The original Yahoo fields remain available for indicators and daily volume.
    """
    clean_symbols = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    if not clean_symbols:
        return market_data
    if not api_key or not secret_key:
        raise ValueError("Alpaca credentials are required for the execution-time quote refresh")

    if client is None:
        from alpaca.data.historical.stock import StockHistoricalDataClient

        client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest

    trades = client.get_stock_latest_trade(
        StockLatestTradeRequest(symbol_or_symbols=clean_symbols, feed=DataFeed.IEX)
    )
    quotes = client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=clean_symbols, feed=DataFeed.IEX)
    )
    now = datetime.now(timezone.utc)

    for symbol in clean_symbols:
        trade = trades.get(symbol)
        quote = quotes.get(symbol)
        if trade is None:
            raise RuntimeError(f"Alpaca returned no latest IEX trade for {symbol}")

        trade_timestamp = _utc_datetime(trade.timestamp)
        price = float(trade.price)
        price_timestamp = trade_timestamp
        source = "alpaca_iex_latest_trade"
        if quote is not None and float(quote.bid_price) > 0 and float(quote.ask_price) > 0:
            price = (float(quote.bid_price) + float(quote.ask_price)) / 2
            price_timestamp = _utc_datetime(quote.timestamp)
            source = "alpaca_iex_quote_midpoint"
        age_seconds = max(0, int((now - price_timestamp).total_seconds()))
        if age_seconds > 120:
            raise RuntimeError(f"Alpaca IEX price for {symbol} is stale ({age_seconds}s old)")
        payload = dict(market_data.get(symbol) or {})
        payload.update(
            {
                "latest_price": price,
                "quote_timestamp": price_timestamp.isoformat(),
                "last_trade_price": float(trade.price),
                "last_trade_timestamp": trade_timestamp.isoformat(),
                "quote_source": source,
                "quote_age_seconds": age_seconds,
                "quote_is_fresh": True,
            }
        )
        if quote is not None:
            payload.update(
                {
                    "bid_price": float(quote.bid_price),
                    "ask_price": float(quote.ask_price),
                    "bid_size": float(quote.bid_size),
                    "ask_size": float(quote.ask_size),
                    "bid_ask_timestamp": _utc_datetime(quote.timestamp).isoformat(),
                }
            )
        market_data[symbol] = payload

    return market_data


def _utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
