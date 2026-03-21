"""Strategy Agent — generates trade signals from data + research + news.

Strategies (from simple to sophisticated):

  TIER 1 — Classic Technical
  1. Momentum: RSI + MACD crossover
  2. Mean reversion: Bollinger Band bounces
  3. Trend following: SMA crossover + price vs MAs

  TIER 2 — Volume & Price Action
  4. Volume breakout: unusual volume + significant price move
  5. Support/Resistance: bounces off key levels
  6. VWAP reversion: price relative to volume-weighted average

  TIER 3 — Smart Context
  7. Relative strength: strongest stock in the strongest sector
  8. Opening range breakout: first 30 min defines the day
  9. News catalyst: trade only when news confirms the technical setup

  COMBINATION LOGIC:
  - Default: requires 2+ strategies to agree (conservative)
  - "Best available" mode: if no strong signals, take the single best setup
    with a small position (2%) to guarantee daily activity and learning
  - Claude's research gets double weight in the vote
  - Claude's trade_plan (entry/stop/target) overrides if provided
"""

from typing import Any
from dataclasses import dataclass

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.config.settings import get_settings


@dataclass
class TradeSignal:
    symbol: str
    action: str
    strength: float
    strategy: str
    reasoning: str
    suggested_size_pct: float
    latest_price: float | None = None
    entry: float | None = None
    stop_loss: float | None = None
    target: float | None = None

    def to_dict(self) -> dict:
        d = {
            "symbol": self.symbol,
            "action": self.action,
            "strength": self.strength,
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "suggested_size_pct": self.suggested_size_pct,
        }
        if self.latest_price is not None:
            d["latest_price"] = self.latest_price
        if self.entry:
            d["entry"] = self.entry
        if self.stop_loss:
            d["stop_loss"] = self.stop_loss
        if self.target:
            d["target"] = self.target
        return d


class StrategyAgent(BaseAgent):
    """Generates trade signals using multiple strategies + Claude context."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.STRATEGY, message_bus)

    async def process(self, message: Message) -> Any:
        market_data = message.data.get("market_data", {})
        research = message.data.get("research", {})
        news = message.data.get("news", {})
        market_context = message.data.get("market_context", {})
        symbols = message.data.get("symbols", [])
        settings = get_settings()

        all_signals = []
        for symbol in symbols:
            stock_data = market_data.get(symbol, {})
            stock_research = research.get("stocks", {}).get(symbol, {})
            stock_news = news.get(symbol, {})

            if "error" in stock_data:
                continue

            signal = self._evaluate(
                symbol, stock_data, stock_research, stock_news,
                market_context, settings,
            )
            if signal:
                signal.latest_price = stock_data.get("latest_price")
                all_signals.append(signal.to_dict())

        # "Best available" mode: if no signals passed the strict filter,
        # take the single best one with a tiny position
        if not all_signals and settings.guarantee_daily_trade:
            best = self._find_best_available(symbols, market_data, research, news, market_context)
            if best:
                best.suggested_size_pct = 2.0  # Tiny position — learning trade
                best.reasoning = f"[BEST AVAILABLE] {best.reasoning}"
                best.latest_price = market_data.get(best.symbol, {}).get("latest_price")
                all_signals.append(best.to_dict())

        return {
            "symbols": symbols,
            "signals": all_signals,
            "market_data": market_data,
        }

    def _evaluate(
        self, symbol: str, data: dict, research: dict,
        news: dict, market_ctx: dict, settings,
    ) -> TradeSignal | None:
        """Run all strategies and combine their signals."""
        indicators = data.get("indicators", {})
        price_history = data.get("price_history", [])
        if not indicators:
            return None

        # Run all strategy checks
        sub_signals = []
        for strategy_fn in [
            self._momentum_strategy,
            self._mean_reversion_strategy,
            self._trend_following_strategy,
            self._volume_breakout_strategy,
            self._support_resistance_strategy,
            self._vwap_strategy,
            self._relative_strength_strategy,
            self._news_catalyst_strategy,
        ]:
            result = strategy_fn(symbol, data, indicators, price_history, news, market_ctx)
            if result is not None:
                sub_signals.append(result)

        if not sub_signals:
            return None

        # Claude's recommendation gets double weight
        research_rec = research.get("recommendation")
        research_conf = research.get("confidence", 0.5)

        actions = [s.action for s in sub_signals]
        if research_rec in ("buy", "sell", "hold"):
            actions.extend([research_rec] * 2)

        buy_votes = actions.count("buy")
        sell_votes = actions.count("sell")

        if buy_votes > sell_votes:
            final_action = "buy"
        elif sell_votes > buy_votes:
            final_action = "sell"
        else:
            return None

        # Require minimum number of confirming strategies
        confirming = [s for s in sub_signals if s.action == final_action]
        if len(confirming) < settings.min_strategies_agree:
            return None

        avg_strength = sum(s.strength for s in confirming) / len(confirming)
        adjusted_strength = min(1.0, avg_strength * (0.5 + research_conf * 0.5))

        # Use Claude's trade plan if provided
        trade_plan = research.get("trade_plan", {})
        entry = trade_plan.get("entry")
        stop_loss = trade_plan.get("stop_loss")
        target = trade_plan.get("target")

        reasons = [s.reasoning for s in confirming]
        if research_rec:
            reasons.append(f"Research: {research_rec} ({research_conf:.0%} confidence)")

        return TradeSignal(
            symbol=symbol,
            action=final_action,
            strength=round(adjusted_strength, 3),
            strategy=f"combined({'+'.join(s.strategy for s in confirming)})",
            reasoning=" | ".join(reasons),
            suggested_size_pct=self._size_from_strength(adjusted_strength),
            entry=entry,
            stop_loss=stop_loss,
            target=target,
        )

    def _find_best_available(
        self, symbols: list, market_data: dict, research: dict,
        news: dict, market_ctx: dict,
    ) -> TradeSignal | None:
        """Find the single best signal across all stocks, even if weak.

        Used when no signal passes the strict multi-strategy filter.
        This ensures we get at least 1 trade/day for learning.
        """
        best_signal = None
        best_score = 0

        for symbol in symbols:
            data = market_data.get(symbol, {})
            if "error" in data:
                continue

            indicators = data.get("indicators", {})
            history = data.get("price_history", [])
            stock_news = news.get(symbol, {})
            stock_research = research.get("stocks", {}).get(symbol, {})

            if not indicators:
                continue

            for strategy_fn in [
                self._momentum_strategy,
                self._mean_reversion_strategy,
                self._trend_following_strategy,
                self._volume_breakout_strategy,
                self._support_resistance_strategy,
            ]:
                signal = strategy_fn(symbol, data, indicators, history, stock_news, market_ctx)
                if signal and signal.strength > best_score:
                    # Boost if Claude agrees
                    research_rec = stock_research.get("recommendation", "")
                    if research_rec == signal.action:
                        signal.strength = min(1.0, signal.strength * 1.3)

                    best_signal = signal
                    best_score = signal.strength

        return best_signal

    # ══════════════════════════════════════════════════════════════
    # TIER 1 — Classic Technical
    # ══════════════════════════════════════════════════════════════

    def _momentum_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        rsi = indicators.get("rsi_14")
        macd = indicators.get("macd")
        macd_signal = indicators.get("macd_signal")

        if rsi is None or macd is None or macd_signal is None:
            return None

        if rsi < 35 and macd > macd_signal:
            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, (35 - rsi) / 35 * 0.8 + 0.2),
                strategy="momentum",
                reasoning=f"RSI oversold ({rsi:.1f}) + MACD bullish crossover",
                suggested_size_pct=0,
            )

        if rsi > 70 and macd < macd_signal:
            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, (rsi - 70) / 30 * 0.8 + 0.2),
                strategy="momentum",
                reasoning=f"RSI overbought ({rsi:.1f}) + MACD bearish crossover",
                suggested_size_pct=0,
            )
        return None

    def _mean_reversion_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        price = data.get("latest_price")
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")

        if price is None or bb_upper is None or bb_lower is None:
            return None

        bb_width = bb_upper - bb_lower
        if bb_width == 0:
            return None

        if price <= bb_lower * 1.02:
            distance = (bb_lower - price) / bb_width
            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, 0.3 + abs(distance) * 0.7),
                strategy="mean_reversion",
                reasoning=f"Price ({price:.2f}) at lower BB ({bb_lower:.2f})",
                suggested_size_pct=0,
            )

        if price >= bb_upper * 0.98:
            distance = (price - bb_upper) / bb_width
            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, 0.3 + abs(distance) * 0.7),
                strategy="mean_reversion",
                reasoning=f"Price ({price:.2f}) at upper BB ({bb_upper:.2f})",
                suggested_size_pct=0,
            )
        return None

    def _trend_following_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        price = data.get("latest_price")
        sma_20 = indicators.get("sma_20")
        sma_50 = indicators.get("sma_50")

        if price is None or sma_20 is None or sma_50 is None:
            return None

        if price > sma_20 > sma_50:
            pct_above = (price - sma_50) / sma_50 * 100
            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, 0.3 + pct_above / 10 * 0.5),
                strategy="trend",
                reasoning=f"Uptrend: price > SMA20 ({sma_20:.2f}) > SMA50 ({sma_50:.2f})",
                suggested_size_pct=0,
            )

        if price < sma_20 < sma_50:
            pct_below = (sma_50 - price) / sma_50 * 100
            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, 0.3 + pct_below / 10 * 0.5),
                strategy="trend",
                reasoning=f"Downtrend: price < SMA20 ({sma_20:.2f}) < SMA50 ({sma_50:.2f})",
                suggested_size_pct=0,
            )
        return None

    # ══════════════════════════════════════════════════════════════
    # TIER 2 — Volume & Price Action
    # ══════════════════════════════════════════════════════════════

    def _volume_breakout_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        if len(history) < 5:
            return None

        change_pct = data.get("price_change_pct", 0)
        volume = data.get("volume", 0)
        volumes = [bar["volume"] for bar in history[-10:]]
        avg_vol = sum(volumes) / len(volumes) if volumes else 0

        if avg_vol == 0:
            return None

        volume_ratio = volume / avg_vol

        if volume_ratio < 1.5 or abs(change_pct) < 1.5:
            return None

        action = "buy" if change_pct > 0 else "sell"
        strength = min(1.0, 0.3 + (volume_ratio - 1.5) * 0.2 + abs(change_pct) / 10 * 0.3)

        return TradeSignal(
            symbol=symbol, action=action,
            strength=strength, strategy="volume_breakout",
            reasoning=f"Vol {volume_ratio:.1f}x avg with {change_pct:+.1f}% move",
            suggested_size_pct=0,
        )

    def _support_resistance_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        if len(history) < 10:
            return None

        price = data.get("latest_price")
        if price is None:
            return None

        lows = [bar["low"] for bar in history[-20:]]
        highs = [bar["high"] for bar in history[-20:]]

        support = min(lows)
        resistance = max(highs)
        price_range = resistance - support
        if price_range == 0:
            return None

        support_dist = (price - support) / price_range
        if support_dist < 0.05:
            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, 0.4 + (0.05 - support_dist) * 10),
                strategy="support_resistance",
                reasoning=f"Price ({price:.2f}) near support ({support:.2f})",
                suggested_size_pct=0,
            )

        resistance_dist = (resistance - price) / price_range
        if resistance_dist < 0.05:
            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, 0.4 + (0.05 - resistance_dist) * 10),
                strategy="support_resistance",
                reasoning=f"Price ({price:.2f}) near resistance ({resistance:.2f})",
                suggested_size_pct=0,
            )
        return None

    def _vwap_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        """VWAP reversion — price tends to return to volume-weighted average.

        When price is significantly below VWAP → buy (undervalued intraday)
        When price is significantly above VWAP → sell (overextended intraday)

        We approximate VWAP from recent price history since we don't have
        intraday VWAP from yfinance.
        """
        if len(history) < 5:
            return None

        price = data.get("latest_price")
        if price is None:
            return None

        # Approximate VWAP: volume-weighted average of typical price
        total_vp = 0
        total_vol = 0
        for bar in history[-10:]:
            typical = (bar["high"] + bar["low"] + bar["close"]) / 3
            total_vp += typical * bar["volume"]
            total_vol += bar["volume"]

        if total_vol == 0:
            return None

        vwap = total_vp / total_vol
        deviation = (price - vwap) / vwap * 100

        # Price >2% below VWAP → buy
        if deviation < -2.0:
            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, 0.3 + abs(deviation) / 5 * 0.5),
                strategy="vwap",
                reasoning=f"Price ({price:.2f}) is {deviation:.1f}% below VWAP ({vwap:.2f})",
                suggested_size_pct=0,
            )

        # Price >2% above VWAP → sell
        if deviation > 2.0:
            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, 0.3 + abs(deviation) / 5 * 0.5),
                strategy="vwap",
                reasoning=f"Price ({price:.2f}) is +{deviation:.1f}% above VWAP ({vwap:.2f})",
                suggested_size_pct=0,
            )
        return None

    # ══════════════════════════════════════════════════════════════
    # TIER 3 — Smart Context
    # ══════════════════════════════════════════════════════════════

    def _relative_strength_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        """Buy stocks outperforming the market, sell underperformers.

        If S&P is down 1% but this stock is up 0.5%, it's showing relative strength.
        """
        sp500 = mkt_ctx.get("sp500", {}) if mkt_ctx else {}
        market_change = sp500.get("change_pct", 0)
        stock_change = data.get("price_change_pct", 0)

        if market_change == 0:
            return None

        relative = stock_change - market_change

        # Strong relative strength: stock outperforming market by 2%+
        if relative > 2.0 and stock_change > 0:
            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, 0.3 + relative / 5 * 0.5),
                strategy="relative_strength",
                reasoning=f"Outperforming market by {relative:+.1f}% (stock {stock_change:+.1f}% vs SPY {market_change:+.1f}%)",
                suggested_size_pct=0,
            )

        # Weak relative strength: stock underperforming by 2%+
        if relative < -2.0 and stock_change < 0:
            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, 0.3 + abs(relative) / 5 * 0.5),
                strategy="relative_strength",
                reasoning=f"Underperforming market by {relative:.1f}% (stock {stock_change:+.1f}% vs SPY {market_change:+.1f}%)",
                suggested_size_pct=0,
            )
        return None

    def _news_catalyst_strategy(self, symbol, data, indicators, history, news, mkt_ctx):
        """Trade when news sentiment CONFIRMS the price direction.

        Key improvement: sentiment direction must align with price move.
        A stock dropping on bullish news is NOT a buy signal — it's a warning.
        A stock rising on bearish news is NOT a sell signal — it shows strength.

        Fires when: headlines exist + price move > 1% + sentiment aligns with direction.
        """
        if not news:
            return None

        headlines = news.get("news_headlines", [])
        analyst = news.get("analyst_recommendations")
        news_sentiment = news.get("sentiment_score", 0)
        source_count = news.get("source_count", 0)

        if not headlines and not analyst:
            return None

        change_pct = data.get("price_change_pct", 0)

        # Need meaningful price move + news
        if abs(change_pct) < 1.0:
            return None

        # Compute headline sentiment if not pre-aggregated
        if news_sentiment == 0 and headlines:
            sentiments = [
                h.get("sentiment", 0) if isinstance(h.get("sentiment"), (int, float))
                else 0
                for h in headlines
            ]
            news_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

        # Analyst consensus
        analyst_signal = 0
        if analyst:
            buys = analyst.get("strong_buy", 0) + analyst.get("buy", 0)
            sells = analyst.get("sell", 0) + analyst.get("strong_sell", 0)
            if buys > sells * 2:
                analyst_signal = 1
            elif sells > buys * 2:
                analyst_signal = -1

        # CRITICAL: Sentiment must align with price direction
        # Bullish news + price up = confirmed buy signal
        # Bearish news + price down = confirmed sell signal
        # Mismatch = no signal (conflicting information)
        sentiment_bullish = news_sentiment > 0.1 or analyst_signal > 0
        sentiment_bearish = news_sentiment < -0.1 or analyst_signal < 0

        # Multi-source confirmation bonus
        multi_source_bonus = 0.1 if source_count >= 2 else 0
        # Filing catalyst bonus (SEC filings add conviction)
        filing_bonus = 0.1 if news.get("filing_catalysts") else 0

        if change_pct > 1.0 and sentiment_bullish:
            strength = 0.4 + multi_source_bonus + filing_bonus
            if analyst_signal > 0:
                strength += 0.2
            # Stronger sentiment = stronger signal
            strength += min(0.2, abs(news_sentiment) * 0.3)

            parts = [f"{len(headlines)} news items (sentiment {news_sentiment:+.2f})"]
            parts.append(f"{change_pct:+.1f}% move confirms bullish news")
            if analyst_signal > 0:
                parts.append("analyst buy consensus")
            if source_count >= 2:
                parts.append(f"{source_count} sources agree")
            if news.get("filing_catalysts"):
                parts.append("SEC filing catalyst")

            return TradeSignal(
                symbol=symbol, action="buy",
                strength=min(1.0, strength + abs(change_pct) / 10 * 0.2),
                strategy="news_catalyst",
                reasoning=" | ".join(parts),
                suggested_size_pct=0,
            )

        if change_pct < -1.0 and sentiment_bearish:
            strength = 0.4 + multi_source_bonus + filing_bonus
            if analyst_signal < 0:
                strength += 0.2
            strength += min(0.2, abs(news_sentiment) * 0.3)

            parts = [f"{len(headlines)} news items (sentiment {news_sentiment:+.2f})"]
            parts.append(f"{change_pct:+.1f}% move confirms bearish news")
            if analyst_signal < 0:
                parts.append("analyst sell consensus")
            if source_count >= 2:
                parts.append(f"{source_count} sources agree")

            return TradeSignal(
                symbol=symbol, action="sell",
                strength=min(1.0, strength + abs(change_pct) / 10 * 0.2),
                strategy="news_catalyst",
                reasoning=" | ".join(parts),
                suggested_size_pct=0,
            )

        return None

    # ══════════════════════════════════════════════════════════════
    # Position Sizing
    # ══════════════════════════════════════════════════════════════

    def _size_from_strength(self, strength: float) -> float:
        """Conservative sizing: weak=2%, medium=5%, strong=8%."""
        if strength < 0.3:
            return 2.0
        elif strength < 0.6:
            return 5.0
        else:
            return 8.0
