"""Screener Agent — news + data hybrid stock discovery.

Two-stage screening process:
  1. NEWS DISCOVERS — check NewsAgent's discoveries and hot stocks
  2. DATA CONFIRMS — validate with price action, volume, liquidity

Stocks can enter from two paths:
  - News path: NewsAgent found them via headlines, analyst changes, or
    cross-source mentions. These get a boost in ranking.
  - Technical path: scanned from the universe for momentum × volume.

The final shortlist merges both paths and ranks by a composite score
that weights news conviction alongside technical strength.

Runs once at 9:00 AM ET during the morning research phase.
Outputs a shortlist of 5-15 stocks for the day.
"""

from typing import Any
import yfinance as yf

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.utils.runtime import configure_yfinance_cache

# Top liquid stocks across sectors — our screening universe.
# We scan these for momentum/volume rather than watching all of them.
UNIVERSE = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "CRM", "ORCL",
    "AVGO", "ADBE", "INTC", "CSCO", "NFLX", "QCOM", "AMAT", "MU", "NOW", "PANW",
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
]


class ScreenerAgent(BaseAgent):
    """Hybrid screener: news discovers, data confirms."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.DATA, message_bus)
        self.role_name = "screener"
        configure_yfinance_cache()

    @property
    def name(self) -> str:
        return "screener_agent"

    async def process(self, message: Message) -> Any:
        max_stocks = message.data.get("max_stocks", 10)
        news_discoveries = message.data.get("news_discoveries", [])
        hot_stocks = message.data.get("hot_stocks", [])
        finviz_data = message.data.get("finviz", {})

        # Stage 1: Technical scan of full universe
        tech_candidates = self._scan_universe()

        # Stage 2: Merge news-discovered stocks
        merged = self._merge_news_and_technicals(
            tech_candidates, news_discoveries, hot_stocks, finviz_data
        )

        # Stage 3: Final ranking
        ranked = self._rank_candidates(merged)
        shortlist = ranked[:max_stocks]

        # Tag each stock with how it was found
        for stock in shortlist:
            stock["source"] = stock.get("source", "technical")

        return {
            "shortlist": shortlist,
            "symbols": [s["symbol"] for s in shortlist],
            "total_scanned": len(UNIVERSE),
            "candidates_found": len(merged),
            "news_discovered": len(news_discoveries),
            "hot_stocks_count": len(hot_stocks),
        }

    def _merge_news_and_technicals(
        self, tech_candidates: list[dict],
        news_discoveries: list[dict],
        hot_stocks: list[dict],
        finviz_data: dict,
    ) -> list[dict]:
        """Merge news-discovered stocks with technically-scanned stocks.

        News-discovered stocks that also have technical confirmation
        get the highest ranking. Pure-news or pure-technical stocks
        still make it, but with lower scores.
        """
        by_symbol: dict[str, dict] = {}

        # Add all technical candidates
        for c in tech_candidates:
            by_symbol[c["symbol"]] = {**c, "source": "technical", "news_boost": 0}

        # Merge news discoveries — these are stocks NOT in watchlist with
        # strong sentiment + confirming price action
        for disc in news_discoveries:
            symbol = disc["symbol"]
            if symbol in by_symbol:
                # Already found technically — boost it
                by_symbol[symbol]["news_boost"] = 0.3
                by_symbol[symbol]["source"] = "news+technical"
                by_symbol[symbol]["news_sentiment"] = disc.get("news_sentiment", 0)
                by_symbol[symbol]["top_headline"] = disc.get("top_headline", "")
                by_symbol[symbol]["discovery_reason"] = disc.get("discovery_reason", "")
            else:
                # News-only discovery — add with basic data
                by_symbol[symbol] = {
                    "symbol": symbol,
                    "price": disc.get("price", 0),
                    "change_pct": disc.get("price_change_pct", 0),
                    "volume": 0,
                    "avg_volume": 0,
                    "volume_ratio": 1.0,
                    "abs_change": abs(disc.get("price_change_pct", 0)),
                    "source": "news",
                    "news_boost": 0.25,
                    "news_sentiment": disc.get("news_sentiment", 0),
                    "top_headline": disc.get("top_headline", ""),
                    "discovery_reason": disc.get("discovery_reason", ""),
                }

        # Boost hot stocks (mentioned across multiple news sources)
        for hot in hot_stocks:
            symbol = hot["symbol"]
            if symbol in by_symbol:
                # Multi-source coverage = higher conviction
                source_count = hot.get("source_count", 1)
                by_symbol[symbol]["news_boost"] += min(source_count * 0.1, 0.3)
                by_symbol[symbol]["hot_stock"] = True
                by_symbol[symbol]["hot_sentiment"] = hot.get("sentiment", "mixed")
            else:
                # Hot stock not in universe — skip (we only trade liquid names)
                pass

        # Boost stocks with recent analyst upgrades
        for change in finviz_data.get("analyst_changes", []):
            symbol = change.get("symbol", "")
            if symbol in by_symbol:
                action = change.get("action", "")
                if "upgrade" in action:
                    by_symbol[symbol]["news_boost"] += 0.15
                    by_symbol[symbol].setdefault("analyst_action", action)
                elif "downgrade" in action:
                    by_symbol[symbol]["news_boost"] += 0.1  # Still interesting
                    by_symbol[symbol].setdefault("analyst_action", action)

        return list(by_symbol.values())

    def _scan_universe(self) -> list[dict]:
        """Quick scan of all stocks in the universe for volume and momentum."""
        candidates = []

        tickers_str = " ".join(UNIVERSE)
        try:
            data = yf.download(
                tickers_str, period="5d", group_by="ticker",
                progress=False, threads=True,
            )
        except Exception:
            return self._scan_individual()

        for symbol in UNIVERSE:
            try:
                if symbol not in data.columns.get_level_values(0):
                    continue

                ticker_data = data[symbol]
                if ticker_data.empty or len(ticker_data) < 2:
                    continue

                latest_close = float(ticker_data["Close"].iloc[-1])
                prev_close = float(ticker_data["Close"].iloc[-2])
                volume = float(ticker_data["Volume"].iloc[-1])
                avg_volume = float(ticker_data["Volume"].mean())

                if avg_volume < 500_000:
                    continue

                change_pct = (latest_close - prev_close) / prev_close * 100
                volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

                candidates.append({
                    "symbol": symbol,
                    "price": round(latest_close, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": int(volume),
                    "avg_volume": int(avg_volume),
                    "volume_ratio": round(volume_ratio, 2),
                    "abs_change": round(abs(change_pct), 2),
                })

            except (KeyError, IndexError):
                continue

        return candidates

    def _scan_individual(self) -> list[dict]:
        """Fallback: scan stocks one by one."""
        candidates = []
        for symbol in UNIVERSE:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                if hist.empty or len(hist) < 2:
                    continue

                latest_close = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[-2])
                volume = float(hist["Volume"].iloc[-1])
                avg_volume = float(hist["Volume"].mean())

                if avg_volume < 500_000:
                    continue

                change_pct = (latest_close - prev_close) / prev_close * 100
                volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

                candidates.append({
                    "symbol": symbol,
                    "price": round(latest_close, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": int(volume),
                    "avg_volume": int(avg_volume),
                    "volume_ratio": round(volume_ratio, 2),
                    "abs_change": round(abs(change_pct), 2),
                })
            except Exception:
                continue

        return candidates

    def _rank_candidates(self, candidates: list[dict]) -> list[dict]:
        """Rank by composite score: momentum × volume × news boost.

        Score components:
          - Momentum: abs price change (capped at 5%)
          - Volume: volume ratio vs average (capped at 3x)
          - Confirmation: big move on high volume bonus
          - News boost: from discoveries, hot stocks, analyst actions
        """
        for c in candidates:
            momentum_score = min(c.get("abs_change", 0) / 5.0, 1.0)
            volume_score = min(c.get("volume_ratio", 1.0) / 3.0, 1.0)

            # Bonus: big move ON high volume is more meaningful
            confirmation_bonus = 0.2 if (
                c.get("abs_change", 0) > 1.5 and c.get("volume_ratio", 0) > 1.5
            ) else 0

            # News boost from discoveries, hot stock status, analyst changes
            news_boost = min(c.get("news_boost", 0), 0.5)  # Cap at 0.5

            c["score"] = round(
                momentum_score * 0.3
                + volume_score * 0.3
                + confirmation_bonus
                + news_boost
                + 0.1,  # base score
                3,
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates
