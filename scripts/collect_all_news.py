"""Collect ALL news context from every provider and dump to markdown.

Run: python scripts/collect_all_news.py

Outputs: data/news_collection_{date}.md
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_trader.config.settings import get_settings, reset_settings
from agent_trader.utils.news_types import (
    NewsItem, aggregate_stock_news, score_headline, extract_tickers,
)
from agent_trader.utils.news_providers import (
    YFinanceProvider, RSSProvider, MarketauxProvider,
    SECEdgarProvider, FREDProvider, FinnhubProvider, AlphaVantageProvider,
)


TEST_SYMBOLS = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT"]
DIVIDER = "=" * 60


def collect_yfinance(provider: YFinanceProvider, symbols: list[str]) -> tuple[list[NewsItem], list[str]]:
    lines = ["## 1. YFinance (per-stock headlines + analyst data)\n"]
    items = provider.fetch(symbols)
    lines.append(f"**Headlines:** {len(items)} items\n")

    for item in items:
        lines.append(
            f"- [{item.symbols[0] if item.symbols else '?'}] "
            f"**{item.title[:100]}**\n"
            f"  - sentiment: `{item.sentiment:+.2f}` | publisher: {item.publisher} | "
            f"published: {item.published}\n"
            f"  - {item.summary[:150]}...\n"
        )

    # Upgrades/downgrades
    upgrades = provider.fetch_upgrades_downgrades(symbols)
    lines.append(f"\n**Analyst Upgrades/Downgrades:** {len(upgrades)} items\n")
    for item in upgrades:
        lines.append(f"- {item.title} (sentiment: `{item.sentiment:+.2f}`)\n")

    # Per-stock enrichment
    for sym in symbols:
        lines.append(f"\n### {sym} Enrichment\n")

        analyst = provider.fetch_analyst_data(sym)
        if analyst:
            lines.append(
                f"- **Analyst Consensus:** {analyst['consensus']} "
                f"(score: {analyst['consensus_score']:+.2f}, "
                f"buy:{analyst['strong_buy']+analyst['buy']} "
                f"hold:{analyst['hold']} "
                f"sell:{analyst['sell']+analyst['strong_sell']})\n"
            )

        insider = provider.fetch_insider_activity(sym)
        if insider:
            lines.append(
                f"- **Insider Activity:** {insider['signal']} "
                f"(buys:{insider['recent_buys']}, sells:{insider['recent_sells']})\n"
            )

        earnings = provider.fetch_earnings_proximity(sym)
        if earnings:
            lines.append(
                f"- **Earnings:** {earnings.get('date', '?')} "
                f"({earnings.get('days_until', '?')} days away"
                f"{', IMMINENT!' if earnings.get('warning') else ''})\n"
            )

    return items + upgrades, lines


def collect_rss(provider: RSSProvider, symbols: list[str]) -> tuple[list[NewsItem], list[str]]:
    lines = ["## 2. RSS (Yahoo Finance feeds)\n"]
    items = provider.fetch(symbols)
    lines.append(f"**Items:** {len(items)}\n")

    for item in items:
        syms = ", ".join(item.symbols) if item.symbols else "none"
        lines.append(
            f"- **{item.title[:100]}**\n"
            f"  - symbols: {syms} | sentiment: `{item.sentiment:+.2f}` | "
            f"feed: {item.publisher}\n"
        )

    return items, lines


def collect_marketaux(provider: MarketauxProvider, symbols: list[str]) -> tuple[list[NewsItem], list[str]]:
    lines = ["## 3. Marketaux (entity-linked news)\n"]
    if not provider.is_available():
        lines.append("**SKIPPED** — set MARKETAUX_API_KEY in .env\n")
        return [], lines

    items = provider.fetch(symbols)
    lines.append(f"**Per-stock items:** {len(items)}\n")

    for item in items:
        syms = ", ".join(item.symbols) if item.symbols else "none"
        lines.append(
            f"- **{item.title[:100]}**\n"
            f"  - symbols: {syms} | sentiment: `{item.sentiment:+.3f}` | "
            f"publisher: {item.publisher}\n"
            f"  - {item.summary[:150]}...\n"
        )

    broad = provider.fetch_broad()
    lines.append(f"\n**Broad scan items:** {len(broad)}\n")
    for item in broad:
        syms = ", ".join(item.symbols) if item.symbols else "none"
        lines.append(
            f"- **{item.title[:100]}**\n"
            f"  - symbols: {syms} | sentiment: `{item.sentiment:+.3f}`\n"
        )

    return items + broad, lines


def collect_sec_edgar(provider: SECEdgarProvider, symbols: list[str]) -> tuple[list[NewsItem], list[str]]:
    lines = ["## 4. SEC EDGAR (filings: 8-K, Form 4)\n"]
    items = provider.fetch(symbols, form_types=["8-K", "4"])
    lines.append(f"**Items:** {len(items)}\n")

    for item in items:
        lines.append(
            f"- **{item.title}**\n"
            f"  - sentiment: `{item.sentiment:+.2f}` | filed: {item.published}\n"
            f"  - [link]({item.url})\n"
        )

    return items, lines


def collect_fred(provider: FREDProvider) -> tuple[dict, list[str]]:
    lines = ["## 5. FRED (macro regime)\n"]
    if not provider.is_available():
        lines.append("**SKIPPED** — set FRED_API_KEY in .env\n")
        return {}, lines

    context = provider.fetch_macro_context()
    lines.append(f"**Series fetched:** {len([k for k in context if k != 'regime_signals'])}\n")

    for key, data in context.items():
        if key == "regime_signals":
            continue
        lines.append(f"- **{key}:** {data['value']} — {data['description']}\n")

    signals = context.get("regime_signals", {})
    if signals:
        lines.append("\n### Regime Signals\n")
        for name, signal in signals.items():
            lines.append(
                f"- **{name}:** {signal.get('level', signal.get('status', '?'))} — "
                f"{signal.get('action', signal.get('implication', ''))}\n"
            )

    return context, lines


def collect_finnhub(provider: FinnhubProvider, symbols: list[str]) -> tuple[list[NewsItem], list[str]]:
    lines = ["## 6. Finnhub (company news + social sentiment + insider trades)\n"]
    if not provider.is_available():
        lines.append("**SKIPPED** — set FINNHUB_API_KEY in .env\n")
        return [], lines

    # Company news
    items = provider.fetch(symbols)
    lines.append(f"**Company news:** {len(items)} items\n")
    for item in items:
        lines.append(
            f"- [{', '.join(item.symbols)}] **{item.title[:100]}**\n"
            f"  - sentiment: `{item.sentiment:+.2f}` | publisher: {item.publisher} | "
            f"published: {item.published}\n"
            f"  - {item.summary[:150]}...\n"
        )

    # Per-stock enrichment
    all_insider_items: list[NewsItem] = []
    for sym in symbols:
        lines.append(f"\n### {sym} — Finnhub Enrichment\n")

        # Social sentiment
        social = provider.fetch_social_sentiment(sym)
        if social:
            lines.append(
                f"- **Social Sentiment:** {social['sentiment']} "
                f"(score: {social['avg_score']:+.4f}, "
                f"reddit:{social['reddit_mentions']}, twitter:{social['twitter_mentions']})\n"
            )
        else:
            lines.append("- **Social Sentiment:** no data\n")

        # Insider transactions
        insider_items = provider.fetch_insider_transactions(sym)
        all_insider_items.extend(insider_items)
        if insider_items:
            lines.append(f"- **Insider Transactions:** {len(insider_items)}\n")
            for ix in insider_items:
                lines.append(f"  - {ix.title} (sentiment: `{ix.sentiment:+.2f}`, filed: {ix.published})\n")
        else:
            lines.append("- **Insider Transactions:** none recent\n")

        # Recommendation trends
        rec = provider.fetch_recommendation_trends(sym)
        if rec:
            lines.append(
                f"- **Analyst Trend:** score {rec['score']:+.2f}, trend: {rec['trend']} "
                f"(SB:{rec['strong_buy']} B:{rec['buy']} H:{rec['hold']} "
                f"S:{rec['sell']} SS:{rec['strong_sell']})\n"
            )
        else:
            lines.append("- **Analyst Trend:** no data\n")

        # Key financial metrics
        metrics = provider.fetch_key_metrics(sym)
        if metrics:
            lines.append("- **Key Metrics:**\n")
            pe = metrics.get("pe_ttm")
            eps = metrics.get("eps_ttm")
            if pe is not None:
                lines.append(f"  - P/E: {pe:.1f}" + (f" | EPS: ${eps:.2f}" if eps else "") + "\n")
            rev_g = metrics.get("revenue_growth_yoy")
            eps_g = metrics.get("eps_growth_yoy")
            if rev_g is not None:
                lines.append(f"  - Revenue Growth YoY: {rev_g:.1f}%" + (f" | EPS Growth: {eps_g:.1f}%" if eps_g else "") + "\n")
            gm = metrics.get("gross_margin")
            nm = metrics.get("net_margin")
            roe = metrics.get("roe")
            if gm is not None:
                parts = [f"Gross Margin: {gm:.1f}%"]
                if nm is not None: parts.append(f"Net Margin: {nm:.1f}%")
                if roe is not None: parts.append(f"ROE: {roe:.1f}%")
                lines.append(f"  - {' | '.join(parts)}\n")
            beta = metrics.get("beta")
            mcap = metrics.get("market_cap_m")
            if beta is not None:
                lines.append(f"  - Beta: {beta:.2f}" + (f" | Market Cap: ${mcap:,.0f}M" if mcap else "") + "\n")
            h52 = metrics.get("52w_high")
            l52 = metrics.get("52w_low")
            if h52 is not None and l52 is not None:
                lines.append(f"  - 52W Range: ${l52:.2f} — ${h52:.2f} (high: {metrics.get('52w_high_date', '?')})\n")

        # Real-time quote
        quote = provider.fetch_quote(sym)
        if quote:
            lines.append(
                f"- **Quote:** ${quote['price']:.2f} ({quote['change_pct']:+.2f}%) "
                f"| Open: ${quote['open']:.2f} | Range: ${quote['low']:.2f}-${quote['high']:.2f}\n"
            )

        # Peers
        peers = provider.fetch_peers(sym)
        if peers:
            lines.append(f"- **Peers:** {', '.join(peers[:8])}\n")

    return items + all_insider_items, lines


def collect_alpha_vantage(provider: AlphaVantageProvider, symbols: list[str]) -> tuple[list[NewsItem], list[str]]:
    lines = ["## 7. Alpha Vantage (NLP news sentiment)\n"]
    if not provider.is_available():
        lines.append("**SKIPPED** — set ALPHA_VANTAGE_API_KEY in .env\n")
        return [], lines

    items = provider.fetch(symbols)
    lines.append(f"**Per-stock NLP news:** {len(items)} items\n")

    for item in items:
        syms = ", ".join(item.symbols) if item.symbols else "broad"
        meta = item.metadata
        overall_label = meta.get("overall_label", "")
        topics = ", ".join(meta.get("topics", [])[:3])

        lines.append(
            f"- **{item.title[:100]}**\n"
            f"  - symbols: {syms} | NLP sentiment: `{item.sentiment:+.3f}` ({overall_label}) | "
            f"publisher: {item.publisher}\n"
            f"  - topics: {topics}\n"
        )

        # Show per-ticker sentiment detail
        ticker_sents = meta.get("ticker_sentiments", {})
        if ticker_sents:
            for tick, ts in ticker_sents.items():
                lines.append(
                    f"    - {tick}: relevance={ts['relevance']:.2f}, "
                    f"sentiment={ts['sentiment_score']:+.4f} ({ts['sentiment_label']})\n"
                )

        lines.append(f"  - {item.summary[:200]}...\n")

    # Also try broad market news (1 API call)
    broad = provider.fetch_broad()
    lines.append(f"\n**Broad market NLP news:** {len(broad)} items\n")
    for item in broad:
        lines.append(
            f"- **{item.title[:100]}**\n"
            f"  - NLP sentiment: `{item.sentiment:+.3f}` | publisher: {item.publisher}\n"
        )

    return items + broad, lines


def build_aggregation(all_items: list[NewsItem], symbols: list[str]) -> list[str]:
    lines = ["## Unified Aggregation\n"]
    lines.append(f"**Total items collected:** {len(all_items)}\n")

    # Source breakdown
    by_source: dict[str, int] = {}
    for item in all_items:
        by_source[item.source] = by_source.get(item.source, 0) + 1
    lines.append("**By source:**\n")
    for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
        lines.append(f"- {src}: {count}\n")

    # Category breakdown
    by_cat: dict[str, int] = {}
    for item in all_items:
        by_cat[item.category] = by_cat.get(item.category, 0) + 1
    lines.append("\n**By category:**\n")
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- {cat}: {count}\n")

    # Per-stock summary
    summaries = aggregate_stock_news(all_items, symbols)
    for sym, summary in summaries.items():
        lines.append(f"\n### {sym}\n")
        lines.append(
            f"- Items: {len(summary.items)} | Sources: {summary.source_count} | "
            f"Sentiment: `{summary.sentiment_score:+.2f}` ({summary.sentiment_label})\n"
        )
        if summary.filing_catalysts:
            lines.append(f"- Filing catalysts: {len(summary.filing_catalysts)}\n")
            for f in summary.filing_catalysts[:3]:
                lines.append(f"  - {f['title']}\n")

        # Show all headlines grouped by source
        by_src: dict[str, list[NewsItem]] = {}
        for item in summary.items:
            by_src.setdefault(item.source, []).append(item)
        for src, src_items in by_src.items():
            lines.append(f"\n**{src}** ({len(src_items)} items):\n")
            for item in src_items[:5]:
                lines.append(
                    f"- {item.title[:80]} (sentiment: `{item.sentiment:+.2f}`)\n"
                )

    return lines


def main():
    reset_settings()
    settings = get_settings()

    print("Collecting news from ALL sources...")
    print(f"Symbols: {TEST_SYMBOLS}")
    print(f"MARKETAUX_API_KEY: {'SET' if settings.marketaux_api_key else 'MISSING'}")
    print(f"FRED_API_KEY: {'SET' if settings.fred_api_key else 'MISSING'}")
    print(f"FINNHUB_API_KEY: {'SET' if settings.finnhub_api_key else 'MISSING'}")
    print(f"ALPHA_VANTAGE_API_KEY: {'SET' if settings.alpha_vantage_api_key else 'MISSING'}")
    print()

    # Initialize providers
    yf_provider = YFinanceProvider()
    rss_provider = RSSProvider()
    mx_provider = MarketauxProvider(settings.marketaux_api_key)
    sec_provider = SECEdgarProvider(settings.sec_edgar_user_agent)
    fred_provider = FREDProvider(settings.fred_api_key)
    fh_provider = FinnhubProvider(settings.finnhub_api_key)
    av_provider = AlphaVantageProvider(settings.alpha_vantage_api_key)

    # Collect from each source
    all_items: list[NewsItem] = []
    all_lines: list[str] = []

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_lines.append(f"# News Collection Report\n\n")
    all_lines.append(f"**Date:** {now}\n")
    all_lines.append(f"**Symbols:** {', '.join(TEST_SYMBOLS)}\n\n")
    all_lines.append("---\n\n")

    # 1. YFinance
    print("1/7 YFinance...", end=" ", flush=True)
    items, lines = collect_yfinance(yf_provider, TEST_SYMBOLS)
    all_items.extend(items)
    all_lines.extend(lines)
    print(f"{len(items)} items")

    # 2. RSS
    print("2/7 RSS...", end=" ", flush=True)
    items, lines = collect_rss(rss_provider, TEST_SYMBOLS)
    all_items.extend(items)
    all_lines.extend(lines)
    all_lines.append("\n---\n\n")
    print(f"{len(items)} items")

    # 3. Marketaux
    print("3/7 Marketaux...", end=" ", flush=True)
    items, lines = collect_marketaux(mx_provider, TEST_SYMBOLS)
    all_items.extend(items)
    all_lines.extend(lines)
    all_lines.append("\n---\n\n")
    print(f"{len(items)} items")

    # 4. SEC EDGAR
    print("4/7 SEC EDGAR...", end=" ", flush=True)
    items, lines = collect_sec_edgar(sec_provider, TEST_SYMBOLS)
    all_items.extend(items)
    all_lines.extend(lines)
    all_lines.append("\n---\n\n")
    print(f"{len(items)} items")

    # 5. FRED
    print("5/7 FRED...", end=" ", flush=True)
    fred_context, lines = collect_fred(fred_provider)
    all_lines.extend(lines)
    all_lines.append("\n---\n\n")
    print(f"{len([k for k in fred_context if k != 'regime_signals'])} series")

    # 6. Finnhub
    print("6/7 Finnhub...", end=" ", flush=True)
    items, lines = collect_finnhub(fh_provider, TEST_SYMBOLS)
    all_items.extend(items)
    all_lines.extend(lines)
    all_lines.append("\n---\n\n")
    print(f"{len(items)} items")

    # 7. Alpha Vantage
    print("7/7 Alpha Vantage...", end=" ", flush=True)
    items, lines = collect_alpha_vantage(av_provider, TEST_SYMBOLS)
    all_items.extend(items)
    all_lines.extend(lines)
    all_lines.append("\n---\n\n")
    print(f"{len(items)} items")

    # Unified aggregation
    print("\nBuilding aggregation...")
    agg_lines = build_aggregation(all_items, TEST_SYMBOLS)
    all_lines.extend(agg_lines)

    # Summary
    by_source: dict[str, int] = {}
    for item in all_items:
        by_source[item.source] = by_source.get(item.source, 0) + 1

    all_lines.append("\n---\n\n")
    all_lines.append("## Summary\n\n")
    all_lines.append(f"| Source | Items |\n")
    all_lines.append(f"|--------|-------|\n")
    for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
        all_lines.append(f"| {src} | {count} |\n")
    all_lines.append(f"| **TOTAL** | **{len(all_items)}** |\n")

    configured = sum(1 for available in [
        True, True, mx_provider.is_available(), True,
        fred_provider.is_available(), fh_provider.is_available(),
        av_provider.is_available(),
    ] if available)
    all_lines.append(f"\n**Providers active:** {configured}/7\n")

    if not settings.finnhub_api_key:
        all_lines.append("- Get FINNHUB_API_KEY at https://finnhub.io/\n")
    if not settings.alpha_vantage_api_key:
        all_lines.append("- Get ALPHA_VANTAGE_API_KEY at https://www.alphavantage.co/support/#api-key\n")
    if not settings.marketaux_api_key:
        all_lines.append("- Get MARKETAUX_API_KEY at https://www.marketaux.com/\n")
    if not settings.fred_api_key:
        all_lines.append("- Get FRED_API_KEY at https://fred.stlouisfed.org/docs/api/api_key.html\n")

    # Write output
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = data_dir / f"news_collection_{date_str}.md"
    output_path.write_text("".join(all_lines), encoding="utf-8")

    print(f"\n{DIVIDER}")
    print(f"DONE — {len(all_items)} total items from {len(by_source)} sources")
    print(f"Output: {output_path}")
    print(DIVIDER)


if __name__ == "__main__":
    main()
