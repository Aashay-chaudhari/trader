"""News Agent — unified multi-source news pipeline.

Every source (yfinance, RSS, Marketaux, SEC EDGAR) produces NewsItem
objects. These flow through a single pipeline:

    Sources → list[NewsItem] → tag symbols → aggregate → consume

Consumers (screener, strategies, research prompt) all work with
the same StockNewsSummary regardless of where the data came from.

DATA SOURCES:
  1. yfinance  — per-stock news, analyst recs, insider, earnings (free)
  2. Yahoo RSS — breaking market headlines (free, fragile)
  3. Marketaux — entity-linked news with sentiment (free: 100 req/day)
  4. SEC EDGAR — 8-K, Form 4, 13D/13G filings (free, no key)
  5. FRED      — macro regime: VIX, yields, spreads (free key)

Market context (SPY/VIX/sectors) is gathered separately since it's
regime data, not per-stock news.
"""

import time
from typing import Any

import yfinance as yf
from rich.console import Console

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.config.settings import get_settings
from agent_trader.utils.runtime import configure_yfinance_cache
from agent_trader.utils.news_types import (
    NewsItem,
    aggregate_stock_news,
    score_headline,
    DEFAULT_TICKERS,
)
from agent_trader.utils.news_providers import (
    YFinanceProvider,
    RSSProvider,
    MarketauxProvider,
    SECEdgarProvider,
    FREDProvider,
    FinnhubProvider,
    AlphaVantageProvider,
    _parse_yfinance_news_item,
)

console = Console()

# ── Sector ETFs for rotation analysis ────────────────────────
SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial": "XLF",
    "Energy": "XLE",
    "Consumer Disc.": "XLY",
    "Consumer Staples": "XLP",
    "Industrial": "XLI",
    "Communication": "XLC",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
}


class NewsAgent(BaseAgent):
    """Unified multi-source news aggregation and market context."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.DATA, message_bus)
        self.role_name = "news"
        configure_yfinance_cache()

        # Initialize providers
        settings = get_settings()
        self._yfinance = YFinanceProvider()
        self._rss = RSSProvider()
        self._marketaux = MarketauxProvider(settings.marketaux_api_key)
        self._sec_edgar = SECEdgarProvider(settings.sec_edgar_user_agent)
        self._fred = FREDProvider(settings.fred_api_key)
        self._finnhub = FinnhubProvider(settings.finnhub_api_key)
        self._alpha_vantage = AlphaVantageProvider(settings.alpha_vantage_api_key)

        # Build known tickers set (dynamic — includes screener universe)
        self._known_tickers = set(DEFAULT_TICKERS)

    @property
    def name(self) -> str:
        return "news_agent"

    def register_tickers(self, tickers: set[str]) -> None:
        """Expand the known-tickers set (called by orchestrator after screening)."""
        self._known_tickers |= tickers

    def _timed_fetch(self, name: str, fn, *args, **kwargs) -> tuple[list[NewsItem], dict]:
        """Run a provider fetch with timing and error capture.

        Returns (items, health_entry) where health_entry has:
          status, item_count, latency_ms, and optional error.
        """
        t0 = time.monotonic()
        try:
            items = fn(*args, **kwargs)
            elapsed = int((time.monotonic() - t0) * 1000)
            return items, {"status": "ok", "items": len(items), "latency_ms": elapsed}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return [], {"status": "error", "items": 0, "latency_ms": elapsed,
                        "error": f"{type(exc).__name__}: {exc}"}

    async def process(self, message: Message) -> Any:
        symbols = message.data.get("symbols", [])
        market_data = message.data.get("market_data", {})
        discover_mode = message.data.get("discover_stocks", False)

        # Register any symbols we're working with
        self._known_tickers |= set(symbols)

        # ── Gather all news items from all sources ────────────
        all_items: list[NewsItem] = []
        source_stats: dict[str, int] = {}
        provider_health: dict[str, dict] = {}  # latency + error tracking
        warnings: list[str] = []

        # 1. yfinance per-stock headlines
        yf_items, health = self._timed_fetch("yfinance", self._yfinance.fetch, symbols)
        all_items.extend(yf_items)
        source_stats["yfinance"] = len(yf_items)
        provider_health["yfinance"] = health

        # 2. yfinance analyst upgrades/downgrades (for all symbols + key stocks)
        upgrade_symbols = list(set(symbols) | {
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "BAC", "UNH", "XOM", "LLY", "AMD", "CRM",
        })
        analyst_items, health = self._timed_fetch("analyst", self._yfinance.fetch_upgrades_downgrades, upgrade_symbols)
        all_items.extend(analyst_items)
        source_stats["analyst"] = len(analyst_items)
        provider_health["analyst"] = health

        # 3. RSS headlines
        rss_items, health = self._timed_fetch("rss", self._rss.fetch, symbols, known_tickers=self._known_tickers)
        all_items.extend(rss_items)
        source_stats["rss"] = len(rss_items)
        provider_health["rss"] = health

        # 4. Marketaux (if configured)
        if self._marketaux.is_available():
            mx_items, health = self._timed_fetch("marketaux", self._marketaux.fetch, symbols)
            all_items.extend(mx_items)
            source_stats["marketaux"] = len(mx_items)
            provider_health["marketaux"] = health

        # 5. SEC EDGAR filings (8-K and Form 4)
        if symbols:
            sec_items, health = self._timed_fetch("sec_edgar", self._sec_edgar.fetch, symbols, form_types=["8-K", "4"])
            all_items.extend(sec_items)
            source_stats["sec_edgar"] = len(sec_items)
            provider_health["sec_edgar"] = health

        # 6. Finnhub company news + insider transactions
        if self._finnhub.is_available():
            fh_items, health = self._timed_fetch("finnhub", self._finnhub.fetch, symbols)
            all_items.extend(fh_items)
            source_stats["finnhub"] = len(fh_items)
            provider_health["finnhub"] = health

            # Also pull insider transactions from Finnhub
            for symbol in symbols:
                insider_items = self._finnhub.fetch_insider_transactions(symbol)
                all_items.extend(insider_items)
                source_stats["finnhub"] = source_stats.get("finnhub", 0) + len(insider_items)

        # 7. Alpha Vantage NLP news (sparingly — 25 req/day)
        if self._alpha_vantage.is_available() and symbols:
            av_items, health = self._timed_fetch("alpha_vantage", self._alpha_vantage.fetch, symbols[:10])
            all_items.extend(av_items)
            source_stats["alpha_vantage"] = len(av_items)
            provider_health["alpha_vantage"] = health

        # ── Provider health summary ─────────────────────────────
        failed_providers = [name for name, h in provider_health.items() if h["status"] == "error"]
        if failed_providers:
            warnings.append(f"Providers failed: {', '.join(failed_providers)}")
        if not all_items:
            warnings.append("ALL news providers returned zero items — research quality degraded")

        # ── Aggregate into per-stock summaries ────────────────
        stock_summaries = aggregate_stock_news(all_items, symbols)

        # Enrich summaries with analyst, insider, earnings, and social data
        for symbol in symbols:
            summary = stock_summaries[symbol]
            summary.analyst_consensus = self._yfinance.fetch_analyst_data(symbol)
            summary.insider_signal = self._yfinance.fetch_insider_activity(symbol)
            earnings = self._yfinance.fetch_earnings_proximity(symbol)
            if earnings:
                summary.upcoming_events.append(earnings)

            # Finnhub enrichment: social sentiment + recommendation trends
            if self._finnhub.is_available():
                social = self._finnhub.fetch_social_sentiment(symbol)
                if social:
                    summary.metadata = getattr(summary, '_extra', {})
                    if not hasattr(summary, 'social_sentiment'):
                        summary.social_sentiment = social
                rec_trend = self._finnhub.fetch_recommendation_trends(symbol)
                if rec_trend:
                    if not hasattr(summary, 'recommendation_trend'):
                        summary.recommendation_trend = rec_trend

        # Convert to dict format for downstream consumers
        stock_news = {s: summary.to_dict() for s, summary in stock_summaries.items()}

        # ── Market-wide context ───────────────────────────────
        market_context = self._gather_market_context()

        # Enrich with FRED macro data if available
        if self._fred.is_available():
            fred_data = self._fred.fetch_macro_context()
            if fred_data:
                market_context["fred"] = fred_data
                # Override VIX with authoritative FRED data if available
                fred_vix = fred_data.get("VIXCLS")
                if fred_vix and market_context.get("vix"):
                    market_context["vix"]["fred_value"] = fred_vix["value"]
                # Add regime signals
                regime_signals = fred_data.get("regime_signals", {})
                if regime_signals:
                    market_context["fred_regime"] = regime_signals

        # ── Market-wide headlines (not tagged to specific stocks) ──
        market_headlines = [
            item.to_dict() for item in rss_items
        ]

        # ── News-driven stock discovery ───────────────────────
        news_discoveries = []
        if discover_mode:
            news_discoveries = self._discover_stocks_from_news(
                existing_symbols=symbols, all_items=all_items
            )
            # Also try Marketaux broad scan for discovery
            if self._marketaux.is_available():
                mx_broad = self._marketaux.fetch_broad()
                for item in mx_broad:
                    for sym in item.symbols:
                        if sym not in symbols and abs(item.sentiment) > 0.3:
                            news_discoveries.append({
                                "symbol": sym,
                                "news_sentiment": round(item.sentiment, 2),
                                "sentiment_label": "bullish" if item.sentiment > 0 else "bearish",
                                "headline_count": 1,
                                "top_headline": item.title,
                                "top_headline_url": item.url,
                                "source": item.source,
                                "price_change_pct": 0,
                                "price": 0,
                                "discovery_reason": f"Marketaux: {item.title[:60]}",
                            })

        # ── Cross-source hot stocks ───────────────────────────
        hot_stocks = self._identify_hot_stocks(all_items, symbols)

        # ── Build finviz-compatible output (analyst changes) ──
        finviz_data = {
            "analyst_changes": [
                {
                    "symbol": item.symbols[0] if item.symbols else "",
                    "firm": item.publisher,
                    "action": item.metadata.get("action", ""),
                    "from_grade": item.metadata.get("from", ""),
                    "to_grade": item.metadata.get("to", ""),
                }
                for item in analyst_items
            ]
        }

        return {
            "symbols": symbols,
            "market_data": market_data,
            "news": stock_news,
            "market_headlines": market_headlines,
            "market_context": market_context,
            "news_discoveries": news_discoveries,
            "finviz": finviz_data,
            "hot_stocks": hot_stocks,
            "source_stats": source_stats,
            "provider_health": provider_health,
            "warnings": warnings,
        }

    # ── News-Driven Stock Discovery ──────────────────────────

    def _discover_stocks_from_news(
        self, existing_symbols: list[str], all_items: list[NewsItem]
    ) -> list[dict]:
        """Find stocks in the news that aren't in the current watchlist.

        Uses ALL collected NewsItems plus a targeted yfinance scan of
        the screener universe for stocks with strong sentiment + price action.
        """
        discovered: dict[str, dict] = {}

        # Path 1: Check if any collected news items mention unwatched stocks
        for item in all_items:
            for symbol in item.symbols:
                if symbol in existing_symbols or symbol in discovered:
                    continue
                if abs(item.sentiment) < 0.3:
                    continue
                discovered[symbol] = {
                    "symbol": symbol,
                    "news_sentiment": round(item.sentiment, 2),
                    "sentiment_label": "bullish" if item.sentiment > 0 else "bearish",
                    "headline_count": 1,
                    "top_headline": item.title,
                    "top_headline_url": item.url,
                    "source": item.source,
                    "price_change_pct": 0,
                    "price": 0,
                    "discovery_reason": f"{item.source}: {item.title[:60]}",
                }

        # Path 2: Targeted yfinance scan of universe stocks not yet watched
        from agent_trader.agents.screener_agent import UNIVERSE

        for symbol in UNIVERSE:
            if symbol in existing_symbols or symbol in discovered:
                continue

            try:
                ticker = yf.Ticker(symbol)
                news = ticker.news
                if not news or len(news) < 2:
                    continue

                sentiments = [score_headline(
                    (item.get("title") or item.get("content", {}).get("title", ""))
                ) for item in news[:5]]
                avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

                if abs(avg_sentiment) < 0.3:
                    continue

                hist = ticker.history(period="2d")
                if hist.empty or len(hist) < 2:
                    continue

                change_pct = (
                    (hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
                    / hist["Close"].iloc[-2] * 100
                )

                if abs(change_pct) > 1.0 or abs(avg_sentiment) > 0.5:
                    first_title = (
                        news[0].get("title")
                        or news[0].get("content", {}).get("title", "")
                    )
                    parsed_first = _parse_yfinance_news_item(news[0])
                    discovered[symbol] = {
                        "symbol": symbol,
                        "news_sentiment": round(avg_sentiment, 2),
                        "sentiment_label": "bullish" if avg_sentiment > 0 else "bearish",
                        "headline_count": len(news),
                        "top_headline": first_title,
                        "top_headline_url": parsed_first.get("url", ""),
                        "source": "yfinance",
                        "price_change_pct": round(float(change_pct), 2),
                        "price": round(float(hist["Close"].iloc[-1]), 2),
                        "discovery_reason": _explain_discovery(avg_sentiment, change_pct, news),
                    }
            except Exception:
                continue

        sorted_disc = sorted(
            discovered.values(),
            key=lambda x: abs(x["news_sentiment"]),
            reverse=True,
        )
        return sorted_disc[:8]

    # ── Cross-Source Hot Stocks ───────────────────────────────

    def _identify_hot_stocks(
        self, all_items: list[NewsItem], symbols: list[str]
    ) -> list[dict]:
        """Find stocks mentioned across multiple independent sources.

        Now works off the unified NewsItem list instead of
        separate data structures.
        """
        mention_counts: dict[str, dict] = {}

        for item in all_items:
            for symbol in item.symbols:
                if symbol not in symbols:
                    continue

                mention_counts.setdefault(symbol, {
                    "sources": set(),
                    "total_mentions": 0,
                    "sentiment_sum": 0.0,
                    "reasons": [],
                    "articles": [],
                })
                mention_counts[symbol]["sources"].add(item.source)
                mention_counts[symbol]["total_mentions"] += 1
                mention_counts[symbol]["sentiment_sum"] += item.sentiment
                mention_counts[symbol]["reasons"].append(
                    f"{item.source}: {item.title[:50]}"
                )
                mention_counts[symbol]["articles"].append(
                    {
                        "title": item.title,
                        "url": item.url,
                        "source": item.source,
                        "publisher": item.publisher,
                        "published": item.published,
                        "sentiment": item.sentiment,
                    }
                )

        hot = []
        for symbol, data in mention_counts.items():
            source_count = len(data["sources"])
            if source_count >= 2 or data["total_mentions"] >= 3:
                avg_sent = data["sentiment_sum"] / max(data["total_mentions"], 1)
                hot.append({
                    "symbol": symbol,
                    "source_count": source_count,
                    "mention_count": data["total_mentions"],
                    "avg_sentiment": round(avg_sent, 2),
                    "sentiment": (
                        "bullish" if avg_sent > 0.15 else
                        "bearish" if avg_sent < -0.15 else
                        "mixed"
                    ),
                    "reasons": data["reasons"][:5],
                    "articles": _dedupe_article_refs(data["articles"])[:5],
                })

        hot.sort(key=lambda x: (x["source_count"], abs(x["avg_sentiment"])), reverse=True)
        return hot[:10]

    # ── Market Context (regime assessment) ────────────────────

    def _gather_market_context(self) -> dict:
        """Market regime from ETF prices. FRED enriches this if available."""
        context = {
            "sp500": None,
            "nasdaq": None,
            "vix": None,
            "treasury_10y": None,
            "sector_performance": {},
            "sector_leaders": [],
            "sector_laggards": [],
            "market_regime": "neutral",
            "breadth": None,
        }

        # S&P 500
        try:
            spy = yf.Ticker("SPY")
            hist = spy.history(period="5d")
            if len(hist) >= 2:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                change = (price - prev) / prev * 100
                five_day_change = (price - float(hist["Close"].iloc[0])) / float(hist["Close"].iloc[0]) * 100
                context["sp500"] = {
                    "price": round(price, 2),
                    "change_pct": round(change, 2),
                    "five_day_pct": round(five_day_change, 2),
                    "trend": "up" if five_day_change > 0.5 else "down" if five_day_change < -0.5 else "flat",
                }
        except Exception:
            pass

        # Nasdaq
        try:
            qqq = yf.Ticker("QQQ")
            hist = qqq.history(period="2d")
            if len(hist) >= 2:
                context["nasdaq"] = {
                    "price": round(float(hist["Close"].iloc[-1]), 2),
                    "change_pct": round(
                        (hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
                        / hist["Close"].iloc[-2] * 100, 2
                    ),
                }
        except Exception:
            pass

        # VIX
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="5d")
            if not hist.empty:
                vix_val = float(hist["Close"].iloc[-1])
                vix_prev = float(hist["Close"].iloc[0]) if len(hist) >= 2 else vix_val
                context["vix"] = {
                    "value": round(vix_val, 2),
                    "change": round(vix_val - vix_prev, 2),
                    "level": (
                        "low" if vix_val < 15 else
                        "normal" if vix_val < 20 else
                        "elevated" if vix_val < 25 else
                        "high" if vix_val < 35 else
                        "extreme"
                    ),
                    "interpretation": (
                        "Complacency — low vol environment, breakouts likely"
                        if vix_val < 15 else
                        "Normal conditions — standard position sizing"
                        if vix_val < 20 else
                        "Caution — reduce position sizes, tighter stops"
                        if vix_val < 25 else
                        "Fear — avoid new longs unless strong conviction"
                        if vix_val < 35 else
                        "Panic — potential capitulation, watch for reversals"
                    ),
                }
        except Exception:
            pass

        # 10-Year Treasury
        try:
            tlt = yf.Ticker("^TNX")
            hist = tlt.history(period="2d")
            if not hist.empty:
                context["treasury_10y"] = {
                    "yield_pct": round(float(hist["Close"].iloc[-1]), 2),
                }
        except Exception:
            pass

        # Sector rotation
        sector_changes = {}
        for sector, etf in SECTOR_ETFS.items():
            try:
                t = yf.Ticker(etf)
                h = t.history(period="5d")
                if len(h) >= 2:
                    daily = (h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2] * 100
                    weekly = (h["Close"].iloc[-1] - h["Close"].iloc[0]) / h["Close"].iloc[0] * 100
                    sector_changes[sector] = {
                        "daily_pct": round(float(daily), 2),
                        "weekly_pct": round(float(weekly), 2),
                    }
            except Exception:
                continue

        context["sector_performance"] = sector_changes

        if sector_changes:
            sorted_daily = sorted(sector_changes.items(), key=lambda x: x[1]["daily_pct"], reverse=True)
            context["sector_leaders"] = [{"sector": s, **d} for s, d in sorted_daily[:3]]
            context["sector_laggards"] = [{"sector": s, **d} for s, d in sorted_daily[-3:]]

        # Determine market regime
        sp = context.get("sp500") or {}
        vix_data = context.get("vix") or {}
        sp_change = sp.get("change_pct", 0)
        vix_level = vix_data.get("level", "normal")

        if sp_change > 0.5 and vix_level in ("low", "normal"):
            context["market_regime"] = "risk_on"
        elif sp_change < -0.5 or vix_level in ("high", "extreme"):
            context["market_regime"] = "risk_off"
        elif vix_level == "elevated":
            context["market_regime"] = "cautious"
        else:
            context["market_regime"] = "neutral"

        return context


# ── Module-level helpers ──────────────────────────────────────

def _explain_discovery(sentiment: float, change_pct: float, news: list) -> str:
    reasons = []
    if abs(sentiment) > 0.5:
        direction = "bullish" if sentiment > 0 else "bearish"
        reasons.append(f"strong {direction} news sentiment ({sentiment:+.2f})")
    if abs(change_pct) > 2:
        reasons.append(f"significant price move ({change_pct:+.1f}%)")
    if len(news) > 3:
        reasons.append(f"high news volume ({len(news)} articles)")
    return " + ".join(reasons) if reasons else "notable news activity"


def _dedupe_article_refs(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in items:
        title = str(item.get("title") or "").strip().lower()
        url = str(item.get("url") or "").strip().lower()
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
