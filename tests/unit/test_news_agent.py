"""Tests for news parsing helpers."""

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
