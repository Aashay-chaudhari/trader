"""Research Agent — Claude-powered deep market analysis.

This is the system's real edge. Unlike basic technical analysis (which
every algo already trades on), this agent feeds Claude:

  1. TECHNICALS — price action, indicators, chart patterns
  2. NEWS — recent headlines, analyst upgrades/downgrades
  3. FUNDAMENTALS — earnings calendar, P/E, sector context
  4. MARKET REGIME — VIX level, S&P trend, sector rotation
  5. PERFORMANCE HISTORY — Claude's own past trade outcomes
  6. LEARNED RULES — patterns Claude discovered from its own results

Claude Sonnet is used for morning research (deep, $0.01-0.03/call).
Claude Haiku for periodic monitoring checks (cheap, $0.001/call).

The performance feedback loop is what makes this system improve over time.
Claude sees its own win rate, confidence calibration, and past mistakes.
"""

from typing import Any
import json
from pathlib import Path
from datetime import datetime, timezone

from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.config.settings import get_settings
from agent_trader.utils.feedback import PerformanceTracker
from agent_trader.utils.research_context import (
    build_recent_artifact_summary,
    save_prompt_context_snapshot,
)


RESEARCH_PROMPT = """You are an expert stock market analyst and trader. Your job is to find the best
2-3 trading opportunities from today's shortlist.

You are CONSERVATIVE — you only recommend trades with clear setups and defined risk.
You have a $100,000 paper portfolio. Every dollar counts.

{performance_feedback}

{learned_rules}

PREVIOUS RUN ARTIFACTS
{artifact_context}

═══════════════════════════════════════════════════════════
MARKET REGIME
═══════════════════════════════════════════════════════════
{market_context}

═══════════════════════════════════════════════════════════
TODAY'S STOCKS — TECHNICAL DATA
═══════════════════════════════════════════════════════════
{market_data}

═══════════════════════════════════════════════════════════
NEWS & CATALYSTS
═══════════════════════════════════════════════════════════
{news_context}

═══════════════════════════════════════════════════════════
SCREENER CONTEXT (why these were picked)
═══════════════════════════════════════════════════════════
{screener_context}

═══════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════
For each stock, analyze:
1. TECHNICAL SETUP: trend, momentum indicators, support/resistance levels
2. NEWS CATALYST: is there a reason for the move? Earnings? Upgrade? Sector rotation?
3. VOLUME STORY: is smart money involved (high volume) or is this noise (low volume)?
4. RISK/REWARD: specific entry, stop loss, and target prices

IMPORTANT RULES:
- Be SPECIFIC with numbers. "$142.50 entry with $139.00 stop" not "buy near support"
- Only recommend BUY or SELL when confidence > 0.65
- If nothing looks great, pick the BEST AVAILABLE setup — we want at least 1 trade/day
- Always include a stop loss. No trade without defined risk.
- Flag earnings dates — never hold through earnings on a swing trade
- Learn from your track record above. If your confidence is miscalibrated, adjust.
- Consider the market regime: don't buy aggressively when VIX is high/market is selling off

Respond with ONLY valid JSON:
{{
    "overall_sentiment": "bullish" | "bearish" | "neutral",
    "market_summary": "2-3 sentence overview including market regime assessment",
    "market_regime": "risk_on" | "risk_off" | "neutral",
    "best_opportunities": ["SYMBOL1", "SYMBOL2"],
    "stocks": {{
        "<SYMBOL>": {{
            "sentiment": "bullish" | "bearish" | "neutral",
            "confidence": 0.0-1.0,
            "key_observations": [
                "specific observation with numbers",
                "another observation"
            ],
            "news_impact": "positive" | "negative" | "neutral" | "none",
            "news_summary": "1 sentence on relevant news if any",
            "technical_setup": "1-2 sentence summary",
            "recommendation": "buy" | "sell" | "hold" | "watch",
            "trade_plan": {{
                "entry": 0.00,
                "stop_loss": 0.00,
                "target": 0.00,
                "risk_reward_ratio": 0.0,
                "position_size_pct": 0.0,
                "timeframe": "intraday" | "swing_2_5_days" | "swing_1_2_weeks"
            }},
            "catalysts": ["what could drive this"],
            "risks": ["what could go wrong"],
            "earnings_warning": true | false
        }}
    }},
    "self_reflection": "1-2 sentences on how your confidence calibration should adjust based on your track record"
}}"""


MONITOR_PROMPT = """You are monitoring your watchlist during market hours. Be brief and actionable.

{performance_feedback}

PREVIOUS RUN ARTIFACTS
{artifact_context}

CURRENT MARKET DATA:
{market_data}

MORNING RESEARCH (your earlier analysis):
{morning_context}

What has changed since the morning? Check:
1. Has price moved to any of your morning entry zones?
2. Any new news catalysts?
3. Has volume picked up confirming a move?
4. Should any stop losses be adjusted?

If an entry point has been hit, flag it clearly as READY TO TRADE.
If nothing actionable, just confirm "holding analysis" for each stock.

Respond with ONLY valid JSON:
{{
    "overall_sentiment": "bullish" | "bearish" | "neutral",
    "market_summary": "1 sentence update",
    "stocks": {{
        "<SYMBOL>": {{
            "sentiment": "bullish" | "bearish" | "neutral",
            "confidence": 0.0-1.0,
            "key_observations": ["what changed"],
            "recommendation": "buy" | "sell" | "hold" | "watch",
            "ready_to_trade": true | false,
            "catalysts": [],
            "risks": [],
            "trade_plan": {{
                "entry": 0.00,
                "stop_loss": 0.00,
                "target": 0.00
            }}
        }}
    }}
}}"""


WEEKLY_REVIEW_PROMPT = """You are reviewing your trading performance for the past week.

{performance_summary}

DETAILED TRADE LOG:
{trade_details}

Analyze your performance:
1. What patterns led to your WINNING trades?
2. What mistakes led to your LOSING trades?
3. Was your confidence well-calibrated? (High confidence = high win rate?)
4. Were there trades you missed that you should have taken?
5. Were there trades you took that you should have skipped?

Generate 3-5 concrete rules for yourself going forward.
Example rules:
- "Avoid buying into earnings within 3 days"
- "RSI < 25 with volume confirmation has 80% win rate — increase position size"
- "My high-confidence calls on tech stocks lose 60% — reduce confidence on tech"

Respond with ONLY valid JSON:
{{
    "performance_grade": "A" | "B" | "C" | "D" | "F",
    "key_insight": "most important thing I learned this week",
    "winning_patterns": ["pattern1", "pattern2"],
    "losing_patterns": ["pattern1", "pattern2"],
    "confidence_assessment": "am I overconfident, underconfident, or well-calibrated?",
    "new_rules": [
        "rule 1 — specific and actionable",
        "rule 2",
        "rule 3"
    ],
    "strategy_adjustments": "what I should do differently next week"
}}"""


class ResearchAgent(BaseAgent):
    """Analyzes market data using Claude with full context and feedback loop."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.RESEARCH, message_bus)
        self._llm_clients: dict[str, Any] = {}
        self._last_provider = None
        self._last_model = None
        self._tracker = PerformanceTracker()

    def _get_client(self, provider: str):
        if provider in self._llm_clients:
            return self._llm_clients[provider]

        settings = get_settings()

        if provider == "anthropic" and settings.anthropic_api_key:
            import anthropic
            self._llm_clients[provider] = anthropic.Anthropic(
                api_key=settings.anthropic_api_key
            )
        elif provider == "openai" and settings.openai_api_key:
            import openai
            self._llm_clients[provider] = openai.OpenAI(api_key=settings.openai_api_key)
        else:
            raise RuntimeError(f"No API key configured for provider '{provider}'")

        return self._llm_clients[provider]

    def _get_available_providers(self) -> list[str]:
        settings = get_settings()
        providers = []
        if settings.anthropic_api_key:
            providers.append("anthropic")
        if settings.openai_api_key:
            providers.append("openai")
        return providers

    def _get_provider_preference(self) -> str:
        preference = get_settings().llm_provider.strip().lower()
        if preference in {"auto", "anthropic", "openai"}:
            return preference
        return "auto"

    def _get_provider_sequence(self) -> list[str]:
        available = self._get_available_providers()
        preference = self._get_provider_preference()

        if preference == "auto":
            return available
        if preference in available:
            return [preference] + [provider for provider in available if provider != preference]
        return available

    def _get_provider_name(self) -> str:
        """Resolve the preferred provider based on config and available keys."""
        providers = self._get_provider_sequence()
        return providers[0] if providers else ""

    async def process(self, message: Message) -> Any:
        market_data = message.data.get("market_data", {})
        phase = message.data.get("phase", "research")
        screener_results = message.data.get("screener_results")
        morning_context = message.data.get("morning_context")
        news_data = message.data.get("news", {})
        market_context = message.data.get("market_context", {})
        news_discoveries = message.data.get("news_discoveries", [])
        hot_stocks = message.data.get("hot_stocks", [])
        finviz_data = message.data.get("finviz", {})

        if not market_data:
            raise ValueError("No market data provided to ResearchAgent")

        summary = self._prepare_rich_summary(market_data)
        artifact_context = build_recent_artifact_summary()
        provider = self._get_provider_name()
        prompt_sections: dict[str, Any] = {}

        run_mode = "research"

        # Build the prompt based on phase
        if phase == "monitor" and morning_context:
            performance_feedback = self._tracker.get_recent_trades_for_prompt(5)
            prompt_sections = {
                "performance_feedback": performance_feedback,
                "artifact_context": artifact_context,
                "market_data": summary,
                "morning_context": morning_context,
            }
            prompt = MONITOR_PROMPT.format(
                performance_feedback=performance_feedback,
                artifact_context=artifact_context,
                market_data=json.dumps(summary, indent=2),
                morning_context=json.dumps(morning_context, indent=2),
            )
            run_mode = "monitor"
        elif phase == "weekly_review":
            performance_summary = self._tracker.get_performance_summary()
            trade_details = self._tracker.get_recent_trades_for_prompt(20)
            prompt_sections = {
                "performance_summary": performance_summary,
                "trade_details": trade_details,
                "artifact_context": artifact_context,
            }
            prompt = WEEKLY_REVIEW_PROMPT.format(
                performance_summary=json.dumps(performance_summary, indent=2),
                trade_details=trade_details,
            )
        else:
            performance_feedback = self._tracker.get_recent_trades_for_prompt()
            learned_rules = self._tracker.get_learned_rules()
            market_context_text = self._format_market_context(market_context)
            news_context = self._format_news(
                news_data, news_discoveries, hot_stocks, finviz_data
            )
            screener_context = self._format_screener_context(screener_results)
            prompt_sections = {
                "performance_feedback": performance_feedback,
                "learned_rules": learned_rules,
                "artifact_context": artifact_context,
                "market_context": market_context,
                "market_data": summary,
                "news_context": news_context,
                "screener_context": screener_results or {},
            }
            prompt = RESEARCH_PROMPT.format(
                performance_feedback=performance_feedback,
                learned_rules=learned_rules,
                artifact_context=artifact_context,
                market_context=market_context_text,
                market_data=json.dumps(summary, indent=2),
                news_context=news_context,
                screener_context=screener_context,
            )
            run_mode = "research"

        model = self._get_model_for_phase(provider, run_mode)

        save_prompt_context_snapshot(
            phase=phase,
            provider=provider or "unresolved",
            model=model,
            symbols=message.data.get("symbols", []),
            prompt_sections=prompt_sections,
        )

        analysis = await self._call_llm(prompt, phase=run_mode)

        # If this is a weekly review, save the learned rules
        if phase == "weekly_review" and "new_rules" in analysis:
            self._tracker.save_learned_rules(analysis["new_rules"])

        self._save_research(analysis, phase)

        return {
            "symbols": message.data.get("symbols", []),
            "market_data": market_data,
            "research": analysis,
            "phase": phase,
            "news": news_data,
            "market_context": market_context,
        }

    def _get_research_model(self, provider: str | None = None) -> str:
        """Sonnet for deep research — smarter, worth the extra $0.02."""
        settings = get_settings()
        provider = provider or self._get_provider_name()
        if provider == "anthropic":
            return settings.research_model
        return settings.research_model_openai

    def _get_monitor_model(self, provider: str | None = None) -> str:
        """Haiku for monitoring — fast and cheap."""
        settings = get_settings()
        provider = provider or self._get_provider_name()
        if provider == "anthropic":
            return settings.monitor_model
        return settings.research_model_openai

    def _get_model_for_phase(self, provider: str, phase: str) -> str:
        if phase == "monitor":
            return self._get_monitor_model(provider)
        return self._get_research_model(provider)

    def _prepare_rich_summary(self, market_data: dict) -> dict:
        """Build comprehensive but token-efficient summary for Claude."""
        summary = {}
        for symbol, data in market_data.items():
            if "error" in data:
                summary[symbol] = {"error": data["error"]}
                continue

            entry = {
                "price": data.get("latest_price"),
                "change_today": f"{data.get('price_change_pct', 0):+.2f}%",
                "volume": f"{data.get('volume', 0):,}",
            }

            ind = data.get("indicators", {})
            if ind:
                rsi = ind.get("rsi_14")
                entry["technicals"] = {
                    "rsi_14": f"{rsi:.1f}" + (
                        " (OVERSOLD)" if rsi and rsi < 30 else
                        " (OVERBOUGHT)" if rsi and rsi > 70 else ""
                    ) if rsi else None,
                    "macd": ind.get("macd"),
                    "macd_signal": ind.get("macd_signal"),
                    "macd_direction": "bullish" if (ind.get("macd") or 0) > (ind.get("macd_signal") or 0) else "bearish",
                    "sma_20": ind.get("sma_20"),
                    "sma_50": ind.get("sma_50"),
                    "bb_upper": ind.get("bb_upper"),
                    "bb_lower": ind.get("bb_lower"),
                }

                price = data.get("latest_price", 0)
                sma_20 = ind.get("sma_20", 0)
                sma_50 = ind.get("sma_50", 0)
                if price and sma_20 and sma_50:
                    entry["price_context"] = {
                        "vs_sma20": f"{((price - sma_20) / sma_20 * 100):+.2f}%",
                        "vs_sma50": f"{((price - sma_50) / sma_50 * 100):+.2f}%",
                        "trend": "uptrend" if price > sma_20 > sma_50
                                 else "downtrend" if price < sma_20 < sma_50
                                 else "mixed",
                    }

            history = data.get("price_history", [])
            if len(history) >= 5:
                recent = history[-5:]
                highs = [d["high"] for d in recent]
                lows = [d["low"] for d in recent]
                entry["recent_5d"] = {
                    "high": max(highs), "low": min(lows),
                    "range_pct": f"{((max(highs) - min(lows)) / min(lows) * 100):.2f}%",
                    "direction": "up" if recent[-1]["close"] > recent[0]["close"] else "down",
                }

            info = data.get("info", {})
            if info:
                entry["fundamentals"] = {
                    k: v for k, v in {
                        "name": info.get("name"),
                        "sector": info.get("sector"),
                        "market_cap": info.get("market_cap"),
                        "pe_ratio": info.get("pe_ratio"),
                    }.items() if v is not None
                }

            summary[symbol] = entry

        return summary

    def _format_news(
        self, news_data: dict,
        news_discoveries: list | None = None,
        hot_stocks: list | None = None,
        finviz_data: dict | None = None,
    ) -> str:
        """Format all news context for Claude's prompt."""
        sections = []

        # Per-stock headlines, analyst recs, earnings, insider activity
        stock_lines = []
        for symbol, data in news_data.items():
            headlines = data.get("news_headlines", [])
            analyst = data.get("analyst_recommendations")
            events = data.get("upcoming_events", [])
            insider = data.get("insider_signal")
            sentiment = data.get("sentiment", "neutral")
            score = data.get("sentiment_score", 0)

            if not headlines and not analyst and not events:
                continue

            stock_lines.append(f"\n{symbol} (sentiment: {sentiment}, score: {score:+.2f}):")

            if headlines:
                for h in headlines[:4]:
                    sent_tag = f" [{h.get('sentiment', 0):+.1f}]" if h.get("sentiment") else ""
                    stock_lines.append(
                        f"  - [{h.get('publisher', '')}] {h.get('title', '')}{sent_tag}"
                    )

            if analyst:
                buys = analyst.get("strong_buy", 0) + analyst.get("buy", 0)
                sells = analyst.get("sell", 0) + analyst.get("strong_sell", 0)
                holds = analyst.get("hold", 0)
                consensus = analyst.get("consensus", "?")
                stock_lines.append(
                    f"  Analysts: {buys} Buy / {holds} Hold / {sells} Sell "
                    f"(consensus: {consensus})"
                )

            if insider:
                signal = insider.get("signal", "")
                stock_lines.append(
                    f"  Insider activity: {signal} "
                    f"(buys: {insider.get('recent_buys', 0)}, "
                    f"sells: {insider.get('recent_sells', 0)})"
                )

            if events:
                for e in events:
                    stock_lines.append(
                        f"  ⚠ UPCOMING: {e['type']} on {e.get('date', 'TBD')}"
                    )

        if stock_lines:
            sections.append("PER-STOCK NEWS:\n" + "\n".join(stock_lines))

        # News-discovered stocks (found via headlines, not technical scan)
        if news_discoveries:
            disc_lines = ["NEWS-DRIVEN DISCOVERIES (stocks in the news today):"]
            for d in news_discoveries:
                disc_lines.append(
                    f"  {d['symbol']}: {d.get('sentiment_label', '?')} sentiment "
                    f"({d.get('news_sentiment', 0):+.2f}), "
                    f"price {d.get('price_change_pct', 0):+.1f}%"
                )
                if d.get("top_headline"):
                    disc_lines.append(f"    Headline: {d['top_headline']}")
                if d.get("discovery_reason"):
                    disc_lines.append(f"    Why: {d['discovery_reason']}")
            sections.append("\n".join(disc_lines))

        # Hot stocks (mentioned across multiple independent sources)
        if hot_stocks:
            hot_lines = ["CROSS-SOURCE HOT STOCKS (multiple sources agree):"]
            for h in hot_stocks:
                hot_lines.append(
                    f"  {h['symbol']}: {h.get('sentiment', 'mixed')} across "
                    f"{h.get('source_count', 0)} sources, "
                    f"{h.get('mention_count', 0)} mentions"
                )
                for reason in h.get("reasons", [])[:3]:
                    hot_lines.append(f"    - {reason}")
            sections.append("\n".join(hot_lines))

        # Analyst upgrades/downgrades
        if finviz_data and finviz_data.get("analyst_changes"):
            analyst_lines = ["RECENT ANALYST ACTIONS:"]
            for c in finviz_data["analyst_changes"]:
                analyst_lines.append(
                    f"  {c.get('symbol', '?')}: {c.get('firm', '?')} — "
                    f"{c.get('action', '?')} "
                    f"({c.get('from_grade', '?')} → {c.get('to_grade', '?')})"
                )
            sections.append("\n".join(analyst_lines))

        return "\n\n".join(sections) if sections else "No significant news for watched stocks."

    def _format_market_context(self, ctx: dict) -> str:
        """Format market-wide context with full regime assessment."""
        if not ctx:
            return "Market context unavailable."

        lines = []

        # Market regime (top-level signal)
        regime = ctx.get("market_regime", "unknown")
        lines.append(f"REGIME: {regime.upper()}")

        # Index performance
        sp = ctx.get("sp500")
        if sp:
            trend = sp.get("trend", "?")
            lines.append(
                f"S&P 500: ${sp['price']} (today {sp['change_pct']:+.2f}%, "
                f"5-day {sp.get('five_day_pct', 0):+.2f}%, trend: {trend})"
            )

        nq = ctx.get("nasdaq")
        if nq:
            lines.append(f"Nasdaq (QQQ): ${nq['price']} ({nq['change_pct']:+.2f}%)")

        # VIX with interpretation
        vix = ctx.get("vix")
        if vix:
            lines.append(
                f"VIX: {vix['value']} ({vix['level'].upper()}) — "
                f"{vix.get('interpretation', '')}"
            )

        # Treasury yield
        treasury = ctx.get("treasury_10y")
        if treasury:
            lines.append(f"10Y Treasury: {treasury['yield_pct']}%")

        # Sector rotation
        sectors = ctx.get("sector_performance", {})
        if sectors:
            sorted_sectors = sorted(
                sectors.items(),
                key=lambda x: x[1].get("daily_pct", 0) if isinstance(x[1], dict) else x[1],
                reverse=True,
            )
            def fmt_sector(name, data):
                if isinstance(data, dict):
                    return f"{name}: {data['daily_pct']:+.2f}% (week: {data.get('weekly_pct', 0):+.2f}%)"
                return f"{name}: {data:+.2f}%"

            lines.append("Sector leaders: " + ", ".join(
                fmt_sector(s, v) for s, v in sorted_sectors[:3]
            ))
            lines.append("Sector laggards: " + ", ".join(
                fmt_sector(s, v) for s, v in sorted_sectors[-3:]
            ))

        return "\n".join(lines) if lines else "Market context unavailable."

    def _format_screener_context(self, screener_results: dict | None) -> str:
        if not screener_results:
            return "Using configured watchlist (no screener data)."

        shortlist = screener_results.get("shortlist", [])
        if not shortlist:
            return "Screener found no strong candidates today."

        news_disc = screener_results.get("news_discovered", 0)
        hot_count = screener_results.get("hot_stocks_count", 0)

        lines = []
        if news_disc or hot_count:
            lines.append(
                f"[{news_disc} news discoveries, {hot_count} hot stocks fed into screening]"
            )

        for s in shortlist:
            source = s.get("source", "technical")
            source_tag = {
                "news+technical": "NEWS+TECH",
                "news": "NEWS",
                "technical": "TECH",
            }.get(source, source.upper())

            parts = [
                f"- {s['symbol']} [{source_tag}]: "
                f"{s.get('change_pct', 0):+.2f}% move, "
                f"{s.get('volume_ratio', 1.0):.1f}x volume, "
                f"score {s.get('score', 0):.3f}"
            ]

            if s.get("top_headline"):
                parts.append(f"    News: {s['top_headline'][:80]}")
            if s.get("analyst_action"):
                parts.append(f"    Analyst: {s['analyst_action']}")
            if s.get("hot_stock"):
                parts.append(f"    Hot stock ({s.get('hot_sentiment', 'mixed')} cross-source)")

            lines.extend(parts)

        return "\n".join(lines)

    async def _call_llm(self, prompt: str, phase: str) -> dict:
        providers = self._get_provider_sequence()
        if not providers:
            return {
                "overall_sentiment": "neutral",
                "market_summary": "LLM analysis failed: No LLM API key configured",
                "stocks": {},
            }

        raw_text = ""
        errors = []

        for provider in providers:
            model = self._get_model_for_phase(provider, phase)
            client = self._get_client(provider)

            try:
                raw_text = self._call_llm_once(client, provider, model, prompt)
                analysis = self._parse_llm_response(raw_text)
                analysis.setdefault("_meta", {})
                analysis["_meta"].update({"provider": provider, "model": model})
                self._last_provider = provider
                self._last_model = model
                return analysis
            except json.JSONDecodeError as exc:
                errors.append(f"{provider}/{model}: could not parse JSON ({exc})")
            except Exception as exc:
                errors.append(f"{provider}/{model}: {exc}")

        failure = {
            "overall_sentiment": "neutral",
            "market_summary": f"LLM analysis failed: {' | '.join(errors)}",
            "stocks": {},
        }
        if raw_text:
            failure["raw_response"] = raw_text[:500]
        return failure

    def _call_llm_once(self, client: Any, provider: str, model: str, prompt: str) -> str:
        if provider == "anthropic":
            response = client.messages.create(
                model=model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        if provider == "openai":
            response = client.chat.completions.create(
                model=model,
                max_tokens=4000,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""

        raise RuntimeError(f"Unsupported LLM provider '{provider}'")

    def _parse_llm_response(self, raw_text: str) -> dict:
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            raw_text = raw_text.rsplit("```", 1)[0]
        return json.loads(raw_text)

    def _save_research(self, analysis: dict, phase: str) -> None:
        archive_dir = Path("data/research")
        archive_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        filepath = archive_dir / f"{now.strftime('%Y-%m-%d')}_{phase}_{now.strftime('%H%M')}.json"
        filepath.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
