"""Diagnostic script — test each news provider individually.

Run: python scripts/test_news_sources.py

Tests each source, shows what came back, and reports any issues.
Works with or without API keys (skips providers that aren't configured).
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_trader.config.settings import get_settings, reset_settings
from agent_trader.utils.news_types import (
    NewsItem, aggregate_stock_news, score_headline, extract_tickers,
)
from agent_trader.utils.news_providers import (
    YFinanceProvider, RSSProvider, MarketauxProvider,
    SECEdgarProvider, FREDProvider,
)


TEST_SYMBOLS = ["NVDA", "AAPL", "TSLA"]
DIVIDER = "=" * 60


def print_items(items: list[NewsItem], max_show: int = 5):
    if not items:
        print("  (no items returned)")
        return
    for item in items[:max_show]:
        syms = ", ".join(item.symbols) if item.symbols else "—"
        print(f"  [{item.source}] [{item.category}] {item.title[:80]}")
        print(f"    symbols: {syms} | sentiment: {item.sentiment:+.2f} | published: {item.published or '—'}")
        if item.summary:
            print(f"    summary: {item.summary[:100]}...")
        if item.metadata:
            print(f"    metadata: {item.metadata}")
        print()
    if len(items) > max_show:
        print(f"  ... and {len(items) - max_show} more items\n")


def test_yfinance():
    print(f"\n{DIVIDER}")
    print("1. YFINANCE PROVIDER (per-stock headlines)")
    print(DIVIDER)
    provider = YFinanceProvider()
    print(f"   Available: {provider.is_available()}")

    # Headlines
    items = provider.fetch(TEST_SYMBOLS)
    print(f"   Headlines: {len(items)} items for {TEST_SYMBOLS}")
    print_items(items)

    # Analyst upgrades/downgrades
    upgrades = provider.fetch_upgrades_downgrades(TEST_SYMBOLS)
    print(f"   Analyst changes: {len(upgrades)} items")
    print_items(upgrades)

    # Analyst consensus
    for sym in TEST_SYMBOLS:
        consensus = provider.fetch_analyst_data(sym)
        if consensus:
            print(f"   {sym} analyst consensus: {consensus['consensus']} "
                  f"(score: {consensus['consensus_score']:+.2f}, "
                  f"buy:{consensus['strong_buy']+consensus['buy']} "
                  f"hold:{consensus['hold']} "
                  f"sell:{consensus['sell']+consensus['strong_sell']})")

    # Insider activity
    for sym in TEST_SYMBOLS:
        insider = provider.fetch_insider_activity(sym)
        if insider:
            print(f"   {sym} insider: {insider['signal']} "
                  f"(buys:{insider['recent_buys']}, sells:{insider['recent_sells']})")

    # Earnings proximity
    for sym in TEST_SYMBOLS:
        earnings = provider.fetch_earnings_proximity(sym)
        if earnings:
            print(f"   {sym} earnings: {earnings.get('date', '?')} "
                  f"({earnings.get('days_until', '?')} days away, "
                  f"warning: {earnings.get('warning', False)})")

    return items + upgrades


def test_rss():
    print(f"\n{DIVIDER}")
    print("2. RSS PROVIDER (Yahoo Finance RSS feeds)")
    print(DIVIDER)
    provider = RSSProvider()
    print(f"   Available: {provider.is_available()}")

    items = provider.fetch(TEST_SYMBOLS)
    print(f"   Items: {len(items)}")
    print_items(items)
    return items


def test_marketaux():
    print(f"\n{DIVIDER}")
    print("3. MARKETAUX PROVIDER (entity-linked news)")
    print(DIVIDER)
    settings = get_settings()
    provider = MarketauxProvider(settings.marketaux_api_key)
    print(f"   Available: {provider.is_available()}")

    if not provider.is_available():
        print("   SKIPPED — set MARKETAUX_API_KEY in .env")
        return []

    items = provider.fetch(TEST_SYMBOLS)
    print(f"   Per-stock items: {len(items)}")
    print_items(items)

    broad = provider.fetch_broad()
    print(f"   Broad scan items: {len(broad)}")
    print_items(broad)
    return items + broad


def test_sec_edgar():
    print(f"\n{DIVIDER}")
    print("4. SEC EDGAR PROVIDER (filings: 8-K, Form 4)")
    print(DIVIDER)
    settings = get_settings()
    provider = SECEdgarProvider(settings.sec_edgar_user_agent)
    print(f"   Available: {provider.is_available()}")
    print(f"   User-Agent: {provider._user_agent}")

    items = provider.fetch(TEST_SYMBOLS, form_types=["8-K", "4"])
    print(f"   Items: {len(items)}")
    print_items(items, max_show=8)
    return items


def test_fred():
    print(f"\n{DIVIDER}")
    print("5. FRED PROVIDER (macro regime)")
    print(DIVIDER)
    settings = get_settings()
    provider = FREDProvider(settings.fred_api_key)
    print(f"   Available: {provider.is_available()}")

    if not provider.is_available():
        print("   SKIPPED — set FRED_API_KEY in .env")
        return {}

    context = provider.fetch_macro_context()
    print(f"   Series fetched: {len([k for k in context if k != 'regime_signals'])}")
    for key, data in context.items():
        if key == "regime_signals":
            continue
        print(f"   {key}: {data['value']} — {data['description']}")

    signals = context.get("regime_signals", {})
    if signals:
        print(f"\n   Regime signals:")
        for name, signal in signals.items():
            print(f"   {name}: {signal.get('level', signal.get('status', '?'))} — {signal.get('action', signal.get('implication', ''))}")

    return context


def test_aggregation(all_items: list[NewsItem]):
    print(f"\n{DIVIDER}")
    print("6. UNIFIED AGGREGATION")
    print(DIVIDER)
    print(f"   Total items collected: {len(all_items)}")

    # Source breakdown
    by_source: dict[str, int] = {}
    for item in all_items:
        by_source[item.source] = by_source.get(item.source, 0) + 1
    print(f"   By source: {by_source}")

    # Category breakdown
    by_cat: dict[str, int] = {}
    for item in all_items:
        by_cat[item.category] = by_cat.get(item.category, 0) + 1
    print(f"   By category: {by_cat}")

    # Aggregate per stock
    summaries = aggregate_stock_news(all_items, TEST_SYMBOLS)
    for sym, summary in summaries.items():
        print(f"\n   {sym}:")
        print(f"     Items: {len(summary.items)} | Sources: {summary.source_count} | "
              f"Sentiment: {summary.sentiment_score:+.2f} ({summary.sentiment_label})")
        if summary.analyst_consensus:
            print(f"     Analyst: {summary.analyst_consensus.get('consensus', '?')}")
        if summary.insider_signal:
            print(f"     Insider: {summary.insider_signal.get('signal', '?')}")
        if summary.filing_catalysts:
            print(f"     Filings: {len(summary.filing_catalysts)}")
            for f in summary.filing_catalysts[:2]:
                print(f"       - {f['title']}")
        if summary.upcoming_events:
            for e in summary.upcoming_events:
                print(f"     Event: {e.get('type', '?')} on {e.get('date', '?')}")

    # Show the dict format (what downstream consumers see)
    print(f"\n   Output dict sample (NVDA):")
    nvda_dict = summaries["NVDA"].to_dict()
    print(f"     Keys: {list(nvda_dict.keys())}")
    print(f"     headline count: {len(nvda_dict['news_headlines'])}")
    print(f"     sentiment: {nvda_dict['sentiment']} ({nvda_dict['sentiment_score']})")


def main():
    reset_settings()
    settings = get_settings()

    print("NEWS PROVIDER DIAGNOSTIC")
    print(DIVIDER)
    print(f"Symbols: {TEST_SYMBOLS}")
    print(f"MARKETAUX_API_KEY: {'SET' if settings.marketaux_api_key else 'MISSING'}")
    print(f"FRED_API_KEY: {'SET' if settings.fred_api_key else 'MISSING'}")
    print(f"SEC_EDGAR_USER_AGENT: {'SET' if settings.sec_edgar_user_agent else 'MISSING (using default)'}")

    all_items: list[NewsItem] = []

    all_items.extend(test_yfinance())
    all_items.extend(test_rss())
    all_items.extend(test_marketaux())
    all_items.extend(test_sec_edgar())
    fred_context = test_fred()
    test_aggregation(all_items)

    print(f"\n{DIVIDER}")
    print("DONE")
    print(DIVIDER)
    configured = sum(1 for x in [True, True, settings.marketaux_api_key, True, settings.fred_api_key] if x)
    print(f"Providers active: {configured}/5")
    if not settings.marketaux_api_key:
        print("  -> Get MARKETAUX_API_KEY at https://www.marketaux.com/")
    if not settings.fred_api_key:
        print("  -> Get FRED_API_KEY at https://fred.stlouisfed.org/docs/api/api_key.html")
    if not settings.sec_edgar_user_agent:
        print("  -> Set SEC_EDGAR_USER_AGENT='Your Name your@email.com' (no signup needed)")


if __name__ == "__main__":
    main()
