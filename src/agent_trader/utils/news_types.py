"""Unified news data types — every source produces the same format.

All news providers (yfinance, Marketaux, SEC EDGAR, FRED, RSS)
produce NewsItem objects. These flow through a single pipeline:

    Source → NewsItem → tag symbols → score sentiment → aggregate → consume

Consumers (screener, strategies, research prompt) all work with
the same structure regardless of where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


# ── Sentiment keywords (shared across providers) ──────────────

BULLISH_KEYWORDS = [
    "upgrade", "upgrades", "upgraded", "raises", "raised", "beat", "beats",
    "surges", "surge", "soars", "jumps", "rally", "rallies", "breakout",
    "record high", "all-time high", "outperform", "buy rating", "strong buy",
    "positive", "growth", "expands", "acquisition", "deal", "partnership",
    "bullish", "upside", "profit", "revenue beat", "guidance raise",
    "buying", "bought", "wins", "winning", "boosts", "boost", "gains",
    "climbs", "rises", "rising", "higher", "tops", "brilliant buy",
    "screaming deal", "best stock", "top pick", "stay bullish",
    "keep bullish", "reiterated outperform", "price target raised",
]

BEARISH_KEYWORDS = [
    "downgrade", "downgrades", "downgraded", "cuts", "cut", "miss", "misses",
    "falls", "drops", "plunges", "crash", "sell-off", "selloff", "decline",
    "warning", "warns", "underperform", "sell rating", "negative", "loss",
    "layoffs", "recall", "investigation", "lawsuit", "probe", "bearish",
    "downside", "weak", "guidance cut", "revenue miss", "disappointing",
    "plummets", "tumbles", "sinks", "sliding", "slips", "dips", "down",
    "falls", "falling", "lower", "slumps", "threat", "threatens",
    "liability", "indicted", "charged", "smuggling", "fraud", "worried",
    "concern", "pressure", "under pressure", "falters", "struggles",
]


@dataclass
class NewsItem:
    """A single piece of news from any source.

    Every news provider normalizes its output to this format.
    The pipeline then tags symbols, scores sentiment, and aggregates.
    """

    title: str
    source: str          # "yfinance", "marketaux", "sec_edgar", "rss", "alpha_vantage"
    published: str       # ISO-ish timestamp string
    symbols: list[str] = field(default_factory=list)
    sentiment: float = 0.0  # -1.0 (bearish) to +1.0 (bullish)
    category: str = "headline"  # headline, filing, analyst, insider, earnings, macro
    url: str = ""
    summary: str = ""
    publisher: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "published": self.published,
            "symbols": self.symbols,
            "sentiment": self.sentiment,
            "category": self.category,
            "url": self.url,
            "summary": self.summary,
            "publisher": self.publisher,
            "metadata": self.metadata,
        }


@dataclass
class StockNewsSummary:
    """Aggregated news for a single stock across all sources.

    Built by collecting all NewsItems tagged to a symbol and
    computing aggregate scores.
    """

    symbol: str
    items: list[NewsItem] = field(default_factory=list)
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"  # bullish / bearish / neutral
    source_count: int = 0
    analyst_consensus: dict | None = None
    insider_signal: dict | None = None
    upcoming_events: list[dict] = field(default_factory=list)
    filing_catalysts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "news_headlines": [item.to_dict() for item in self.items],
            "sentiment_score": self.sentiment_score,
            "sentiment": self.sentiment_label,
            "source_count": self.source_count,
            "analyst_recommendations": self.analyst_consensus,
            "insider_signal": self.insider_signal,
            "upcoming_events": self.upcoming_events,
            "filing_catalysts": self.filing_catalysts,
        }


class NewsProvider(Protocol):
    """Interface that all news providers implement."""

    @property
    def name(self) -> str: ...

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        """Fetch news items. Symbols may be empty for broad scans."""
        ...

    def is_available(self) -> bool:
        """Check if this provider is configured and usable."""
        ...


# ── Shared utilities ──────────────────────────────────────────

def score_headline(title: str) -> float:
    """Score a headline's sentiment: -1 (bearish) to +1 (bullish).

    Simple keyword matching — fast and surprisingly effective.
    """
    title_lower = title.lower()
    bull_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in title_lower)
    bear_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in title_lower)

    total = bull_hits + bear_hits
    if total == 0:
        return 0.0

    return round((bull_hits - bear_hits) / total, 2)


def extract_tickers(text: str, known_tickers: set[str] | None = None) -> list[str]:
    """Extract stock tickers from text using a dynamic known-ticker set.

    If no known_tickers provided, uses a broad default set.
    """
    import re

    if known_tickers is None:
        known_tickers = DEFAULT_TICKERS

    # Match uppercase 1-5 letter words
    words = re.findall(r'\b[A-Z]{1,5}\b', text)

    # Filter: must be a known ticker and not a common English word
    return list(dict.fromkeys(w for w in words if w in known_tickers and w not in _COMMON_WORDS))


def deduplicate_items(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicate headlines across sources.

    When the same article appears in yfinance AND finnhub (both source Yahoo),
    keep the one with better sentiment data. Priority:
    alpha_vantage > marketaux > finnhub > yfinance > rss

    Deduplication is by normalized title (lowercase, stripped).
    """
    # Source quality ranking (higher = prefer this source's version)
    source_priority = {
        "alpha_vantage": 5,  # Has NLP sentiment
        "marketaux": 4,      # Has entity sentiment
        "sec_edgar": 3,      # Unique filings data
        "finnhub": 2,        # More sources (CNBC, SeekingAlpha)
        "yfinance": 1,       # Baseline
        "rss": 0,            # Least detailed
    }

    best_by_title: dict[str, NewsItem] = {}
    for item in items:
        key = item.title.lower().strip()[:80]  # Normalize for matching
        existing = best_by_title.get(key)
        if existing is None:
            best_by_title[key] = item
        else:
            # Keep the one from the higher-priority source
            existing_prio = source_priority.get(existing.source, 0)
            new_prio = source_priority.get(item.source, 0)
            if new_prio > existing_prio:
                # Merge symbols from both before replacing
                merged_symbols = list(dict.fromkeys(existing.symbols + item.symbols))
                item.symbols = merged_symbols
                best_by_title[key] = item
            else:
                # Merge symbols from the new item into existing
                for sym in item.symbols:
                    if sym not in existing.symbols:
                        existing.symbols.append(sym)

    return list(best_by_title.values())


def aggregate_stock_news(
    items: list[NewsItem],
    symbols: list[str],
) -> dict[str, StockNewsSummary]:
    """Group NewsItems by symbol and compute aggregate scores.

    This is THE central aggregation point — all downstream consumers
    (screener, strategies, research prompt) read from this output.

    Deduplicates across sources first so the same headline doesn't
    inflate sentiment or counts.
    """
    # Deduplicate before aggregating
    deduped = deduplicate_items(items)

    by_symbol: dict[str, StockNewsSummary] = {
        s: StockNewsSummary(symbol=s) for s in symbols
    }

    for item in deduped:
        for symbol in item.symbols:
            if symbol not in by_symbol:
                continue
            summary = by_symbol[symbol]
            summary.items.append(item)

            # Track distinct sources
            sources = {i.source for i in summary.items}
            summary.source_count = len(sources)

            # Populate special categories
            if item.category == "filing":
                summary.filing_catalysts.append({
                    "title": item.title,
                    "source": item.source,
                    "published": item.published,
                    "metadata": item.metadata,
                })

    # Compute aggregate sentiment per stock
    for summary in by_symbol.values():
        if not summary.items:
            continue
        sentiments = [i.sentiment for i in summary.items]
        avg = sum(sentiments) / len(sentiments)
        summary.sentiment_score = round(avg, 2)
        summary.sentiment_label = (
            "bullish" if avg > 0.2 else
            "bearish" if avg < -0.2 else
            "neutral"
        )

    return by_symbol


# Broad default ticker set — covers the screener universe + common ETFs
DEFAULT_TICKERS = {
    # Tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AMD",
    "CRM", "ORCL", "AVGO", "ADBE", "INTC", "CSCO", "NFLX", "QCOM", "AMAT",
    "MU", "NOW", "PANW",
    # Finance
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BLK", "C",
    # Healthcare
    "UNH", "JNJ", "PFE", "ABBV", "LLY", "MRK", "TMO", "ABT", "BMY", "AMGN",
    # Consumer
    "WMT", "HD", "MCD", "NKE", "SBUX", "TGT", "COST", "LOW", "TJX", "DG",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL",
    # Industrial
    "CAT", "DE", "BA", "UNP", "HON", "GE", "RTX", "LMT", "MMM", "UPS",
    # ETFs
    "SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLV", "XLE", "XLY", "XLP",
    "XLI", "XLC", "XLB", "XLU", "XLRE",
}

# Common English words that look like tickers but aren't
_COMMON_WORDS = {
    "A", "I", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF",
    "IN", "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "OUR",
    "SO", "TO", "UP", "US", "WE", "CEO", "IPO", "CEO", "CFO", "CTO",
    "THE", "FOR", "AND", "BUT", "NOT", "YOU", "ALL", "CAN", "HAS", "HER",
    "WAS", "ONE", "ARE", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID",
    "GET", "HIT", "HOW", "ITS", "MAY", "SAY", "SHE", "TOO", "USE",
    "AI", "EV", "PE", "US", "SEC", "FDA", "FED", "GDP", "CPI", "ETF",
}
