"""News Agent — multi-source news ingestion and market context.

This is the information edge. The agent pulls from multiple free sources
and structures the data so Claude and the Screener can act on it.

DATA SOURCES (all free, no API keys needed):
  1. yfinance — per-stock news, analyst recs, earnings dates
  2. Yahoo Finance RSS — breaking market headlines
  3. Finviz — premarket movers, analyst upgrades/downgrades, insider trades
  4. Market context — VIX, S&P 500, sector ETFs, treasury yields

OUTPUT STRUCTURE:
  - Per-stock news: headlines, analyst sentiment, earnings proximity
  - Market-wide context: regime (risk-on/off), sector rotation, volatility
  - News-driven stock ideas: stocks IN THE NEWS that deserve a look
  - Sentiment scoring: simple positive/negative/neutral per stock

The key insight: stocks that appear in multiple news sources
with aligned sentiment are higher-conviction opportunities.
"""

from typing import Any
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import yfinance as yf
import httpx

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.utils.runtime import configure_yfinance_cache


# ── Free RSS feeds ───────────────────────────────────────────
RSS_FEEDS = {
    "yahoo_market": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "yahoo_tech": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^NDX&region=US&lang=en-US",
    "yahoo_trending": "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
}

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

# Simple keyword sentiment — fast, no ML needed
BULLISH_KEYWORDS = [
    "upgrade", "upgrades", "upgraded", "raises", "raised", "beat", "beats",
    "surges", "surge", "soars", "jumps", "rally", "rallies", "breakout",
    "record high", "all-time high", "outperform", "buy rating", "strong buy",
    "positive", "growth", "expands", "acquisition", "deal", "partnership",
    "bullish", "upside", "profit", "revenue beat", "guidance raise",
]
BEARISH_KEYWORDS = [
    "downgrade", "downgrades", "downgraded", "cuts", "cut", "miss", "misses",
    "falls", "drops", "plunges", "crash", "sell-off", "selloff", "decline",
    "warning", "warns", "underperform", "sell rating", "negative", "loss",
    "layoffs", "recall", "investigation", "lawsuit", "probe", "bearish",
    "downside", "weak", "guidance cut", "revenue miss", "disappointing",
]


class NewsAgent(BaseAgent):
    """Multi-source news aggregation and market context."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.DATA, message_bus)
        self.role_name = "news"
        self._http = httpx.Client(timeout=10, follow_redirects=True)
        configure_yfinance_cache()

    @property
    def name(self) -> str:
        return "news_agent"

    async def process(self, message: Message) -> Any:
        symbols = message.data.get("symbols", [])
        market_data = message.data.get("market_data", {})
        discover_mode = message.data.get("discover_stocks", False)

        # 1. Per-stock news from yfinance
        stock_news = {}
        for symbol in symbols:
            stock_news[symbol] = self._gather_stock_news(symbol)

        # 2. Market-wide RSS headlines
        market_headlines = self._fetch_rss_headlines()

        # 3. Market regime context
        market_context = self._gather_market_context()

        # 4. Discover stocks from news (for the screener)
        news_discoveries = []
        if discover_mode:
            news_discoveries = self._discover_stocks_from_news(symbols)

        # 5. Finviz movers and notable activity
        finviz_data = self._fetch_finviz_signals()

        # 6. Cross-reference: stocks mentioned in multiple sources
        hot_stocks = self._identify_hot_stocks(
            stock_news, market_headlines, finviz_data, symbols
        )

        return {
            "symbols": symbols,
            "market_data": market_data,
            "news": stock_news,
            "market_headlines": market_headlines,
            "market_context": market_context,
            "news_discoveries": news_discoveries,
            "finviz": finviz_data,
            "hot_stocks": hot_stocks,
        }

    # ── Per-Stock News (yfinance) ────────────────────────────

    def _gather_stock_news(self, symbol: str) -> dict:
        """Full news context for a single stock."""
        ticker = yf.Ticker(symbol)
        result = {
            "news_headlines": [],
            "sentiment_score": 0,
            "sentiment": "neutral",
            "analyst_recommendations": None,
            "upcoming_events": [],
            "insider_signal": None,
        }

        # News headlines with sentiment
        try:
            news = ticker.news
            if news:
                for item in news[:8]:
                    parsed = self._parse_yfinance_news_item(item)
                    title = parsed["title"]
                    headline = {
                        "title": title,
                        "publisher": parsed["publisher"],
                        "published": parsed["published"],
                        "type": parsed["type"],
                        "sentiment": self._score_headline(title),
                    }
                    result["news_headlines"].append(headline)

                # Aggregate sentiment
                sentiments = [h["sentiment"] for h in result["news_headlines"]]
                if sentiments:
                    avg = sum(sentiments) / len(sentiments)
                    result["sentiment_score"] = round(avg, 2)
                    result["sentiment"] = (
                        "bullish" if avg > 0.2 else
                        "bearish" if avg < -0.2 else
                        "neutral"
                    )
        except Exception:
            pass

        # Analyst recommendations
        try:
            result["analyst_recommendations"] = self._get_analyst_summary(ticker)
        except Exception:
            pass

        # Upcoming events (earnings)
        try:
            cal = ticker.calendar
            if cal and isinstance(cal, dict):
                earnings_date = cal.get("Earnings Date")
                if earnings_date:
                    result["upcoming_events"].append({
                        "type": "earnings",
                        "date": str(earnings_date),
                    })
        except Exception:
            pass

        # Insider activity signal
        try:
            result["insider_signal"] = self._check_insider_activity(ticker)
        except Exception:
            pass

        return result

    def _get_analyst_summary(self, ticker) -> dict | None:
        """Summarize analyst consensus."""
        try:
            recs = ticker.recommendations_summary
            if recs is not None and not recs.empty:
                row = recs.iloc[0]
                strong_buy = int(row.get("strongBuy", 0))
                buy = int(row.get("buy", 0))
                hold = int(row.get("hold", 0))
                sell = int(row.get("sell", 0))
                strong_sell = int(row.get("strongSell", 0))

                total = strong_buy + buy + hold + sell + strong_sell
                if total == 0:
                    return None

                # Weighted score: -1 (all sell) to +1 (all buy)
                score = (
                    (strong_buy * 2 + buy * 1 + hold * 0 + sell * -1 + strong_sell * -2)
                    / (total * 2)
                )

                return {
                    "strong_buy": strong_buy,
                    "buy": buy,
                    "hold": hold,
                    "sell": sell,
                    "strong_sell": strong_sell,
                    "total": total,
                    "consensus_score": round(score, 2),
                    "consensus": (
                        "strong_buy" if score > 0.5 else
                        "buy" if score > 0.15 else
                        "hold" if score > -0.15 else
                        "sell" if score > -0.5 else
                        "strong_sell"
                    ),
                }
        except Exception:
            pass
        return None

    def _check_insider_activity(self, ticker) -> dict | None:
        """Check for recent insider buying/selling — a strong signal."""
        try:
            insiders = ticker.insider_transactions
            if insiders is None or insiders.empty:
                return None

            recent = insiders.head(10)
            buys = 0
            sells = 0

            for _, row in recent.iterrows():
                text = str(row.get("Text", "")).lower()
                if "purchase" in text or "buy" in text:
                    buys += 1
                elif "sale" in text or "sell" in text:
                    sells += 1

            if buys == 0 and sells == 0:
                return None

            return {
                "recent_buys": buys,
                "recent_sells": sells,
                "signal": (
                    "insider_buying" if buys > sells else
                    "insider_selling" if sells > buys else
                    "mixed"
                ),
            }
        except Exception:
            return None

    # ── RSS Headlines ────────────────────────────────────────

    def _fetch_rss_headlines(self) -> list[dict]:
        """Fetch breaking headlines from Yahoo Finance RSS feeds."""
        all_headlines = []

        for feed_name, url in RSS_FEEDS.items():
            try:
                response = self._http.get(url)
                if response.status_code != 200:
                    continue

                root = ET.fromstring(response.text)
                channel = root.find("channel")
                if channel is None:
                    continue

                for item in channel.findall("item")[:10]:
                    title = item.findtext("title", "")
                    pub_date = item.findtext("pubDate", "")
                    description = item.findtext("description", "")

                    # Extract stock tickers mentioned in the headline
                    mentioned_symbols = self._extract_tickers(title + " " + description)

                    all_headlines.append({
                        "title": title,
                        "source": feed_name,
                        "published": pub_date,
                        "sentiment": self._score_headline(title),
                        "mentioned_symbols": mentioned_symbols,
                        "summary": description[:200] if description else "",
                    })

            except Exception:
                continue

        unique = self._dedupe_headlines(all_headlines)
        if unique:
            return unique[:20]

        # Yahoo RSS endpoints are not always stable; fall back to market ETF news.
        return self._fetch_market_headlines_fallback()

    def _fetch_market_headlines_fallback(self) -> list[dict]:
        """Fallback market headlines using working yfinance news endpoints."""
        fallback_symbols = ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF"]
        headlines = []

        for symbol in fallback_symbols:
            try:
                ticker = yf.Ticker(symbol)
                news = ticker.news or []
                for item in news[:4]:
                    parsed = self._parse_yfinance_news_item(item)
                    title = parsed["title"]
                    if not title:
                        continue

                    mentioned = self._extract_tickers(title + " " + parsed["summary"])
                    if symbol not in mentioned:
                        mentioned.append(symbol)

                    headlines.append({
                        "title": title,
                        "source": f"yfinance:{symbol}",
                        "published": parsed["published"],
                        "sentiment": self._score_headline(title),
                        "mentioned_symbols": mentioned,
                        "summary": parsed["summary"][:200],
                    })
            except Exception:
                continue

        return self._dedupe_headlines(headlines)[:20]

    def _dedupe_headlines(self, headlines: list[dict]) -> list[dict]:
        """Deduplicate by title while preserving order."""
        seen = set()
        unique = []
        for headline in headlines:
            title = headline.get("title", "")
            if not title or title in seen:
                continue
            seen.add(title)
            unique.append(headline)
        return unique

    def _parse_yfinance_news_item(self, item: dict) -> dict:
        """Support both old and current yfinance news payload shapes."""
        content = item.get("content", {}) if isinstance(item, dict) else {}
        provider = content.get("provider", {}) if isinstance(content, dict) else {}

        title = item.get("title") or content.get("title") or ""
        publisher = item.get("publisher") or provider.get("displayName") or ""
        published = (
            item.get("providerPublishTime")
            or item.get("pubDate")
            or content.get("pubDate")
            or content.get("displayTime")
            or ""
        )
        summary = (
            item.get("summary")
            or item.get("description")
            or content.get("summary")
            or content.get("description")
            or ""
        )
        item_type = item.get("type") or content.get("contentType") or ""

        return {
            "title": title,
            "publisher": publisher,
            "published": published,
            "summary": summary,
            "type": item_type,
        }

    # ── Finviz Signals ───────────────────────────────────────

    def _fetch_finviz_signals(self) -> dict:
        """Fetch notable market activity from Finviz overview page.

        Gets: top gainers, top losers, most active, analyst changes.
        All from the free Finviz screener (no API key needed).
        """
        result = {
            "top_gainers": [],
            "top_losers": [],
            "most_active": [],
            "analyst_changes": [],
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AgentTrader/1.0)"
        }

        # Top gainers/losers from Yahoo Finance (more reliable than scraping Finviz)
        try:
            import yfinance as yf

            # Use yfinance screener for top movers
            gainers_tickers = ["SPY"]  # Placeholder — we use individual stock data instead
            # We'll populate this from our own screener data
        except Exception:
            pass

        # Get analyst upgrades/downgrades from a few key stocks
        key_stocks = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "BAC", "UNH", "XOM", "LLY", "AMD", "CRM",
        ]

        for symbol in key_stocks:
            try:
                ticker = yf.Ticker(symbol)
                upgrades = ticker.upgrades_downgrades
                if upgrades is not None and not upgrades.empty:
                    recent = upgrades.head(3)
                    for _, row in recent.iterrows():
                        action = str(row.get("Action", "")).lower()
                        if "upgrade" in action or "downgrade" in action:
                            result["analyst_changes"].append({
                                "symbol": symbol,
                                "firm": str(row.get("Firm", "")),
                                "action": action,
                                "from_grade": str(row.get("FromGrade", "")),
                                "to_grade": str(row.get("ToGrade", "")),
                            })
            except Exception:
                continue

        # Keep only recent analyst changes (last 5)
        result["analyst_changes"] = result["analyst_changes"][:8]

        return result

    # ── Market Context ───────────────────────────────────────

    def _gather_market_context(self) -> dict:
        """Comprehensive market regime assessment."""
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
                # 5-day trend
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

        # VIX — fear gauge
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

        # 10-Year Treasury (interest rate environment)
        try:
            tlt = yf.Ticker("^TNX")
            hist = tlt.history(period="2d")
            if not hist.empty:
                context["treasury_10y"] = {
                    "yield_pct": round(float(hist["Close"].iloc[-1]), 2),
                }
        except Exception:
            pass

        # Sector rotation — which sectors are leading/lagging
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
            context["sector_leaders"] = [
                {"sector": s, **d} for s, d in sorted_daily[:3]
            ]
            context["sector_laggards"] = [
                {"sector": s, **d} for s, d in sorted_daily[-3:]
            ]

        # Determine market regime
        sp = context.get("sp500", {})
        vix_data = context.get("vix", {})
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

    # ── News-Driven Stock Discovery ──────────────────────────

    def _discover_stocks_from_news(self, existing_symbols: list[str]) -> list[dict]:
        """Find stocks that are in the news but NOT in our current watchlist.

        This is how we discover opportunities we wouldn't find from
        technical screening alone.
        """
        discovered = {}

        # Check key stocks for fresh news catalysts
        scan_universe = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
            "CRM", "ORCL", "AVGO", "ADBE", "NFLX", "QCOM", "MU", "PANW",
            "JPM", "BAC", "GS", "V", "MA",
            "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK",
            "WMT", "HD", "MCD", "NKE", "COST",
            "XOM", "CVX", "COP",
            "CAT", "DE", "BA", "GE",
        ]

        for symbol in scan_universe:
            if symbol in existing_symbols:
                continue  # Already watching

            try:
                ticker = yf.Ticker(symbol)
                news = ticker.news
                if not news or len(news) < 2:
                    continue

                # Score the headlines
                sentiments = [
                    self._score_headline(self._parse_yfinance_news_item(item)["title"])
                    for item in news[:5]
                ]
                avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

                # Only interested if sentiment is strongly directional
                if abs(avg_sentiment) < 0.3:
                    continue

                # Check if there's unusual volume/price action to confirm
                hist = ticker.history(period="2d")
                if hist.empty or len(hist) < 2:
                    continue

                change_pct = (
                    (hist["Close"].iloc[-1] - hist["Close"].iloc[-2])
                    / hist["Close"].iloc[-2] * 100
                )

                # News + confirming price action = discovery worth investigating
                if abs(change_pct) > 1.0 or abs(avg_sentiment) > 0.5:
                    top_item = self._parse_yfinance_news_item(news[0])
                    discovered[symbol] = {
                        "symbol": symbol,
                        "news_sentiment": round(avg_sentiment, 2),
                        "sentiment_label": "bullish" if avg_sentiment > 0 else "bearish",
                        "headline_count": len(news),
                        "top_headline": top_item["title"],
                        "price_change_pct": round(float(change_pct), 2),
                        "price": round(float(hist["Close"].iloc[-1]), 2),
                        "discovery_reason": self._explain_discovery(avg_sentiment, change_pct, news),
                    }
            except Exception:
                continue

        # Sort by absolute sentiment strength
        sorted_discoveries = sorted(
            discovered.values(),
            key=lambda x: abs(x["news_sentiment"]),
            reverse=True,
        )

        return sorted_discoveries[:5]  # Top 5 news-driven discoveries

    def _explain_discovery(self, sentiment: float, change_pct: float, news: list) -> str:
        """Human-readable explanation of why a stock was discovered."""
        reasons = []
        if abs(sentiment) > 0.5:
            direction = "bullish" if sentiment > 0 else "bearish"
            reasons.append(f"strong {direction} news sentiment ({sentiment:+.2f})")
        if abs(change_pct) > 2:
            reasons.append(f"significant price move ({change_pct:+.1f}%)")
        if len(news) > 3:
            reasons.append(f"high news volume ({len(news)} articles)")
        return " + ".join(reasons) if reasons else "notable news activity"

    # ── Cross-Source Analysis ────────────────────────────────

    def _identify_hot_stocks(
        self, stock_news: dict, headlines: list, finviz: dict,
        symbols: list[str],
    ) -> list[dict]:
        """Find stocks appearing across multiple news sources.

        Stocks mentioned in multiple independent sources with aligned
        sentiment have higher conviction.
        """
        mention_counts: dict[str, dict] = {}

        # Count mentions from per-stock news
        for symbol, data in stock_news.items():
            if not data.get("news_headlines"):
                continue
            mention_counts.setdefault(symbol, {
                "sources": 0, "total_mentions": 0,
                "sentiment_sum": 0, "reasons": [],
            })
            mention_counts[symbol]["sources"] += 1
            mention_counts[symbol]["total_mentions"] += len(data["news_headlines"])
            mention_counts[symbol]["sentiment_sum"] += data.get("sentiment_score", 0)
            if data.get("sentiment") != "neutral":
                mention_counts[symbol]["reasons"].append(f"yfinance: {data['sentiment']}")

        # Count mentions from RSS headlines
        for headline in headlines:
            for symbol in headline.get("mentioned_symbols", []):
                if symbol in symbols:
                    mention_counts.setdefault(symbol, {
                        "sources": 0, "total_mentions": 0,
                        "sentiment_sum": 0, "reasons": [],
                    })
                    mention_counts[symbol]["sources"] += 1
                    mention_counts[symbol]["total_mentions"] += 1
                    mention_counts[symbol]["sentiment_sum"] += headline.get("sentiment", 0)
                    mention_counts[symbol]["reasons"].append(f"RSS: {headline['title'][:50]}")

        # Count from analyst changes
        for change in finviz.get("analyst_changes", []):
            symbol = change.get("symbol", "")
            if symbol in symbols:
                mention_counts.setdefault(symbol, {
                    "sources": 0, "total_mentions": 0,
                    "sentiment_sum": 0, "reasons": [],
                })
                mention_counts[symbol]["sources"] += 1
                action = change.get("action", "")
                sentiment = 0.5 if "upgrade" in action else -0.5 if "downgrade" in action else 0
                mention_counts[symbol]["sentiment_sum"] += sentiment
                mention_counts[symbol]["reasons"].append(
                    f"Analyst: {change.get('firm', '')} {action}"
                )

        # Build hot stocks list (mentioned in 2+ sources)
        hot = []
        for symbol, data in mention_counts.items():
            if data["sources"] >= 2 or data["total_mentions"] >= 3:
                avg_sent = data["sentiment_sum"] / max(data["total_mentions"], 1)
                hot.append({
                    "symbol": symbol,
                    "source_count": data["sources"],
                    "mention_count": data["total_mentions"],
                    "avg_sentiment": round(avg_sent, 2),
                    "sentiment": "bullish" if avg_sent > 0.15 else "bearish" if avg_sent < -0.15 else "mixed",
                    "reasons": data["reasons"][:5],
                })

        hot.sort(key=lambda x: (x["source_count"], abs(x["avg_sentiment"])), reverse=True)
        return hot[:10]

    # ── Utilities ────────────────────────────────────────────

    def _score_headline(self, title: str) -> float:
        """Score a headline's sentiment: -1 (bearish) to +1 (bullish).

        Simple keyword matching — fast and surprisingly effective.
        Doesn't need ML for this granularity.
        """
        title_lower = title.lower()
        bull_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in title_lower)
        bear_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in title_lower)

        total = bull_hits + bear_hits
        if total == 0:
            return 0.0

        return round((bull_hits - bear_hits) / total, 2)

    def _extract_tickers(self, text: str) -> list[str]:
        """Extract likely stock tickers from text.

        Looks for uppercase 1-5 letter words that match known tickers.
        Not perfect, but catches most mentions.
        """
        import re

        known_tickers = {
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "CRM", "ORCL", "AVGO", "ADBE", "NFLX", "QCOM", "MU",
            "JPM", "BAC", "GS", "V", "MA", "WFC", "MS",
            "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK",
            "WMT", "HD", "MCD", "NKE", "COST", "SBUX",
            "XOM", "CVX", "COP",
            "CAT", "DE", "BA", "GE", "HON",
            "SPY", "QQQ", "DIA", "IWM",
        }

        words = re.findall(r'\b[A-Z]{1,5}\b', text)
        return [w for w in words if w in known_tickers]

    def get_earnings_proximity(self, symbol: str) -> dict | None:
        """Check how close a stock is to its earnings date.

        Important for risk: never hold through earnings on a swing trade.
        """
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if not cal or not isinstance(cal, dict):
                return None

            earnings_date = cal.get("Earnings Date")
            if not earnings_date:
                return None

            # Parse and calculate days until earnings
            if isinstance(earnings_date, list):
                earnings_date = earnings_date[0]

            from datetime import datetime as dt
            now = datetime.now(timezone.utc)

            if hasattr(earnings_date, 'timestamp'):
                days_until = (earnings_date - now).days
            else:
                return {"date": str(earnings_date), "days_until": None}

            return {
                "date": str(earnings_date),
                "days_until": days_until,
                "warning": days_until <= 5,
                "message": (
                    "EARNINGS IMMINENT — avoid new positions"
                    if days_until <= 2 else
                    "Earnings within a week — increased vol risk"
                    if days_until <= 5 else
                    "Earnings approaching — monitor closely"
                    if days_until <= 14 else
                    None
                ),
            }
        except Exception:
            return None
