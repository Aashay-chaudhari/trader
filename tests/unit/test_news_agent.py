"""Tests for news parsing helpers."""

import pandas as pd

from agent_trader.agents.news_agent import NewsAgent
from agent_trader.core.message_bus import MessageBus
from agent_trader.utils.news_providers import _parse_yfinance_news_item


def test_parse_yfinance_news_item_extracts_url_and_summary():
    parsed = _parse_yfinance_news_item(
        {
            "content": {
                "title": "AbbVie expands its immunology pipeline",
                "summary": "A new deal extends antibody discovery work.",
                "provider": {"displayName": "Simply Wall St."},
                "canonicalUrl": {"url": "https://example.com/story"},
            }
        }
    )

    assert parsed["title"] == "AbbVie expands its immunology pipeline"
    assert parsed["summary"] == "A new deal extends antibody discovery work."
    assert parsed["publisher"] == "Simply Wall St."
    assert parsed["url"] == "https://example.com/story"


def test_gather_market_context_includes_commodity_futures(monkeypatch):
    commodity_symbols = {"CL=F", "BZ=F", "NG=F", "GC=F", "HG=F"}

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval=None, prepost=False):
            if self.symbol not in commodity_symbols:
                return pd.DataFrame()
            if interval == "1m":
                return pd.DataFrame(
                    {"Close": [79.5]},
                    index=[pd.Timestamp("2026-06-15T14:35:00Z")],
                )
            return pd.DataFrame(
                {"Close": [82.0, 80.0]},
                index=[
                    pd.Timestamp("2026-06-14T00:00:00Z"),
                    pd.Timestamp("2026-06-15T00:00:00Z"),
                ],
            )

    monkeypatch.setattr("agent_trader.agents.news_agent.yf.Ticker", FakeTicker)

    agent = NewsAgent(MessageBus())
    context = agent._gather_market_context()

    assert context["commodities"]["wti_crude"]["symbol"] == "CL=F"
    assert context["commodities"]["wti_crude"]["price"] == 79.5
    assert context["commodities"]["wti_crude"]["change_pct"] == -3.05
    assert context["commodities"]["brent_crude"]["symbol"] == "BZ=F"
    assert context["commodities"]["natural_gas"]["symbol"] == "NG=F"
    assert context["commodities"]["gold"]["symbol"] == "GC=F"
    assert context["commodities"]["copper"]["symbol"] == "HG=F"
