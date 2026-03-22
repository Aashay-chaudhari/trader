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

import logging
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote_plus

import httpx
from agent_trader.core.base_agent import BaseAgent, AgentRole
from agent_trader.core.message_bus import MessageBus, Message
from agent_trader.config.settings import get_settings
from agent_trader.utils.feedback import PerformanceTracker
from agent_trader.utils.llm_analytics import (
    build_runtime_metadata,
    record_llm_analytics,
)
from agent_trader.utils.research_context import (
    build_recent_artifact_summary,
    save_prompt_context_snapshot,
)
from agent_trader.utils.cli_agent import (
    is_cli_available,
    write_staging_data,
    build_research_task,
    build_monitor_task,
    build_reflection_task,
    build_weekly_consolidation_task,
    build_monthly_retrospective_task,
    run_cli_agent,
)
from agent_trader.utils.knowledge_base import KnowledgeBase
from agent_trader.utils.swing_tracker import SwingTracker


RESEARCH_PROMPT = """You are an expert stock market analyst and trader. Your job is to find the best
2-3 trading opportunities from today's shortlist.

You are CONSERVATIVE — you only recommend trades with clear setups and defined risk.
You have a $100,000 paper portfolio. Every dollar counts.

If you have limited historical data (few or no observations/patterns), this is normal early-stage
behavior. Focus on building quality observations from today's data — your future self depends on them.

{performance_feedback}

{learned_rules}

PREVIOUS RUN ARTIFACTS
{artifact_context}

{knowledge_context}

{observations_context}

{swing_context}

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
            "earnings_warning": true | false,
            "supporting_articles": [
                {{
                    "title": "source headline or filing",
                    "url": "https://...",
                    "source": "publisher / website",
                    "kind": "news" | "filing" | "analyst" | "web",
                    "reason": "why this source matters"
                }}
            ]
        }}
    }},
    "self_reflection": "1-2 sentences on how your confidence calibration should adjust based on your track record",
    "web_checks": [
        {{
            "symbol": "SYMBOL",
            "query": "what was searched or fetched",
            "source": "publisher / website",
            "url": "https://...",
            "finding": "what this confirmed"
        }}
    ]
}}"""


MONITOR_PROMPT = """You are a trading monitor making quick decisions. Be decisive and concise.

MORNING TRADE PLANS:
{morning_plans}

CURRENT MARKET STATE:
{current_state}

ACTIVE POSITIONS:
{active_positions}

DETERMINISTIC STRATEGY SIGNALS:
{strategy_signals}

For each watchlist stock: should we TRADE (buy/sell) or SKIP?
For each active position: HOLD, ADD, or CLOSE?
Consider: has price hit entry zone? Volume confirming? Any regime change?
One-line reason per decision. Keep trade_plan from morning unless you have reason to adjust.

Respond with ONLY valid JSON:
{{
    "overall_sentiment": "bullish" | "bearish" | "neutral",
    "market_summary": "1 sentence",
    "stocks": {{
        "<SYMBOL>": {{
            "recommendation": "buy" | "sell" | "hold" | "watch",
            "confidence": 0.0-1.0,
            "ready_to_trade": true | false,
            "key_observations": ["1 concise observation"],
            "trade_plan": {{"entry": 0.00, "stop_loss": 0.00, "target": 0.00}}
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


EVENING_REFLECTION_PROMPT = """You are reflecting on today's trading session. Review what happened and extract learnings.

If this is an early trading day with few or no prior observations, be extra thorough extracting
patterns and lessons — your future self will rely on what you document today. Start from what
you actually observed, not assumptions.

{todays_trades}

{market_regime_summary}

{active_positions}

{recent_observations}

YOUR TASK:
1. Review each trade: was the entry good? Did the thesis play out?
2. Log patterns you observed today (gap_and_go, RSI bounce, breakout, etc.)
3. Calibrate confidence: were high-confidence calls more accurate?
4. Update swing position outlook
5. Note anything forward-looking (events tomorrow, regime shifts)
6. SELF-IMPROVEMENT: Think critically about your own system. What would make you better?
   - Do you need access to more data sources? Which ones specifically?
   - Are there strategies you wish you could run but can't? (e.g., pairs trading, options flow)
   - Would more web searches during research help? How many, and for what?
   - Is there information you keep wanting but don't have? (e.g., order flow, dark pool data, sector ETF correlations)
   - Are there bugs or inefficiencies in how your data is presented?
   - Should your risk rules change? Should position sizing be different?
   - Any code changes that would make your analysis more effective?
   Write these as concrete, actionable proposals — you are your own product manager.

Respond with ONLY valid JSON:
{{
    "date": "{today_date}",
    "market_regime": "risk_on" | "risk_off" | "neutral",
    "market_summary": "1-2 sentence summary of today",
    "sector_leaders": ["sector1", "sector2"],
    "sector_laggards": ["sector1"],
    "trades_review": [
        {{
            "symbol": "AAPL",
            "action": "buy",
            "entry": 185.50,
            "exit": 187.20,
            "pnl_pct": 0.92,
            "confidence": 0.75,
            "assessment": "Good entry at support, volume confirmed"
        }}
    ],
    "patterns_detected": [
        {{
            "name": "pattern_name",
            "symbol": "SYMBOL",
            "outcome": "won" | "lost" | "pending",
            "notes": "what happened"
        }}
    ],
    "confidence_calibration": {{
        "high_conf_count": 0,
        "high_conf_win_rate": 0.0,
        "medium_conf_count": 0,
        "medium_conf_win_rate": 0.0,
        "assessment": "description of calibration"
    }},
    "swing_updates": [
        {{
            "symbol": "SYMBOL",
            "action": "hold" | "close" | "tighten_stop",
            "current_pnl_pct": 0.0,
            "reason": "why"
        }}
    ],
    "forward_outlook": "what to watch for tomorrow",
    "lessons": ["lesson 1", "lesson 2"],
    "self_improvement_proposals": [
        {{
            "category": "data_source" | "strategy" | "risk_management" | "web_research" | "code_change" | "infrastructure" | "other",
            "priority": "high" | "medium" | "low",
            "title": "short title",
            "description": "detailed description of what to change and why",
            "expected_impact": "what this would improve (win rate, coverage, speed, etc.)"
        }}
    ]
}}"""


WEEKLY_CONSOLIDATION_PROMPT = """You are consolidating this week's trading observations and updating your knowledge base.

WEEKLY PERFORMANCE:
{performance_summary}

THIS WEEK'S DAILY OBSERVATIONS:
{daily_observations}

CURRENT KNOWLEDGE BASE:
{current_knowledge}

COMPLETED TRADES THIS WEEK:
{trade_details}

YOUR TASK:
1. Which patterns worked this week? Which failed? Update win rates.
2. Which strategies were effective in this week's market regime?
3. Is your confidence calibration accurate? (high conf = high win rate?)
4. What sector dynamics are at play?
5. What is your forward thesis for next week?
6. Generate knowledge base updates: new patterns, strategy scores, regime rules, lessons.

Respond with ONLY valid JSON:
{{
    "week_start": "{week_start}",
    "week_end": "{week_end}",
    "summary": {{
        "trades_count": 0,
        "win_rate": 0.0,
        "total_pnl_pct": 0.0,
        "swing_positions_held": 0,
        "swing_win_rate": 0.0
    }},
    "pattern_effectiveness": [
        {{
            "pattern": "pattern_name",
            "occurrences": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "best_regime": "risk_on",
            "note": "context"
        }}
    ],
    "strategy_effectiveness": {{
        "strategy_name": {{
            "win_rate": 0.0,
            "avg_return": 0.0,
            "best_regime": "risk_on"
        }}
    }},
    "regime_analysis": {{
        "dominant": "risk_on",
        "shifts": 0,
        "shift_description": ""
    }},
    "confidence_calibration": {{
        "high": {{"expected": 0.80, "actual": 0.0}},
        "medium": {{"expected": 0.60, "actual": 0.0}},
        "low": {{"expected": 0.40, "actual": 0.0}}
    }},
    "forward_thesis": {{
        "outlook": "thesis for next week",
        "confidence": 0.0,
        "key_risks": ["risk1"],
        "opportunities": ["opportunity1"]
    }},
    "knowledge_updates": {{
        "new_patterns": [],
        "updated_strategies": [],
        "new_lessons": ["lesson1"],
        "regime_rules_updated": false
    }}
}}"""


MONTHLY_RETROSPECTIVE_PROMPT = """You are conducting a monthly retrospective on your trading performance.

MONTHLY PERFORMANCE:
{performance_summary}

WEEKLY REVIEWS THIS MONTH:
{weekly_reviews}

CURRENT KNOWLEDGE BASE:
{current_knowledge}

YOUR TASK:
1. Build a strategy × regime effectiveness matrix
2. Assess confidence accuracy at each level
3. Identify top 5-10 lessons of the month
4. Compare vs last month — what improved? What regressed?
5. Recommend strategic adjustments for next month.

Respond with ONLY valid JSON:
{{
    "month": "{month}",
    "summary": {{
        "trading_days": 0,
        "total_trades": 0,
        "win_rate": 0.0,
        "total_pnl_pct": 0.0,
        "best_week": "",
        "worst_week": ""
    }},
    "strategy_regime_matrix": {{
        "momentum": {{"risk_on": 0.0, "risk_off": 0.0, "range_bound": 0.0}},
        "mean_reversion": {{"risk_on": 0.0, "risk_off": 0.0, "range_bound": 0.0}}
    }},
    "confidence_accuracy_curve": {{
        "0.9+": {{"trades": 0, "actual_win_rate": 0.0}},
        "0.7-0.9": {{"trades": 0, "actual_win_rate": 0.0}},
        "0.5-0.7": {{"trades": 0, "actual_win_rate": 0.0}},
        "<0.5": {{"trades": 0, "actual_win_rate": 0.0}}
    }},
    "top_lessons": ["lesson1", "lesson2"],
    "vs_last_month": {{
        "win_rate_change": "+0%",
        "pnl_change": "+0%",
        "improvement_areas": "",
        "regression_areas": ""
    }}
}}"""


EVOLUTION_PROMPT = """You are reviewing your trading system's performance and proposing concrete improvements.

Only propose changes that are backed by evidence from your actual observations and performance data.
If you have few observations (cold start), propose data-gathering and strategy-testing ideas only.

PERFORMANCE DATA:
{performance_summary}

STRATEGY EFFECTIVENESS BY REGIME:
{strategy_effectiveness}

RECENT OBSERVATIONS (last 5 days):
{recent_observations}

AVAILABLE STRATEGIES:
{strategy_list}

PENDING PROPOSALS FROM PREVIOUS SESSIONS:
{pending_proposals}

YOUR TASK:
1. Identify strategies consistently underperforming (win_rate < 40% with 5+ samples)
2. Identify data gaps — what information would have changed your decisions?
3. Propose threshold adjustments with specific current → proposed values
4. If a new strategy type is needed, describe it precisely (name, signal, entry logic)
5. Flag which single change would most improve your win rate

For each proposal include:
- The specific file and function to change (if applicable)
- Current value and proposed value (for threshold changes)
- Evidence: sample size and current win rate

Respond with ONLY valid JSON:
{{
    "evolution_proposals": [
        {{
            "category": "strategy|threshold|data_source|risk_rule|infrastructure",
            "priority": "high|medium|low",
            "title": "short title",
            "description": "what to change and why",
            "expected_impact": "how this improves trading",
            "implementation_hint": {{
                "file": "src/agent_trader/agents/strategy_agent.py",
                "function": "_check_momentum",
                "current_value": "rsi < 35",
                "proposed_value": "rsi < 25",
                "type": "threshold_adjustment"
            }},
            "evidence": {{
                "sample_size": 0,
                "win_rate_current": 0.0,
                "dates": []
            }}
        }}
    ],
    "strategy_gaps": ["what strategy types are missing"],
    "data_gaps": ["what data sources would improve decisions"],
    "top_priority": "single most impactful change described in one sentence"
}}"""


class ResearchAgent(BaseAgent):
    """Analyzes market data using Claude with full context and feedback loop."""

    def __init__(self, message_bus: MessageBus):
        super().__init__(AgentRole.RESEARCH, message_bus)
        self.logger = logging.getLogger(__name__)
        self._llm_clients: dict[str, Any] = {}
        self._last_provider = None
        self._last_model = None
        self._tracker = PerformanceTracker(get_settings().data_dir)

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

    def _get_api_fallback_provider(self) -> str | None:
        """Keep API fallback within the same strategist family when CLI mode is enabled."""
        settings = get_settings()
        if settings.use_cli_agent:
            if settings.cli_agent_provider == "claude":
                return "anthropic"
            if settings.cli_agent_provider == "codex":
                return "openai"
        return None

    def _get_api_provider_sequence(self) -> list[str]:
        forced_provider = self._get_api_fallback_provider()
        available = self._get_available_providers()
        if forced_provider:
            return [forced_provider] if forced_provider in available else []
        return self._get_provider_sequence()

    def _get_provider_name(self) -> str:
        """Resolve the preferred provider based on config and available keys."""
        providers = self._get_api_provider_sequence()
        return providers[0] if providers else ""

    async def process(self, message: Message) -> Any:
        phase = message.data.get("phase", "research")
        if phase == "evening_reflection":
            return await self._handle_evening_reflection(message)
        if phase == "weekly_consolidation":
            return await self._handle_weekly_consolidation(message)
        if phase == "monthly_retrospective":
            return await self._handle_monthly_retrospective(message)
        if phase == "evolution":
            return await self._handle_evolution(message)

        market_data = message.data.get("market_data", {})
        screener_results = message.data.get("screener_results")
        morning_context = message.data.get("morning_context")
        news_data = message.data.get("news", {})
        market_headlines = message.data.get("market_headlines", [])
        market_context = message.data.get("market_context", {})
        news_discoveries = message.data.get("news_discoveries", [])
        hot_stocks = message.data.get("hot_stocks", [])
        finviz_data = message.data.get("finviz", {})

        if not market_data:
            raise ValueError("No market data provided to ResearchAgent")

        summary = self._prepare_rich_summary(market_data)
        artifact_context = build_recent_artifact_summary(data_dir=get_settings().data_dir)
        provider = self._get_provider_name()
        prompt_sections: dict[str, Any] = {}
        web_context: dict[str, Any] = {}

        run_mode = "research"

        # Build the prompt based on phase
        if phase == "monitor" and morning_context:
            lean = self._build_lean_monitor_context(
                summary, morning_context, news_data, market_context,
            )
            prompt_sections = lean
            prompt = MONITOR_PROMPT.format(**lean)
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

            # Knowledge context (accumulated learnings)
            settings = get_settings()
            knowledge_context = ""
            observations_context = ""
            swing_context = ""
            if settings.enable_knowledge_base:
                kb = KnowledgeBase(settings.data_dir)
                knowledge_context = kb.build_knowledge_context(
                    token_budget=settings.knowledge_token_budget
                    if not settings.is_debug else settings.knowledge_token_budget // 2,
                    watchlist=message.data.get("symbols", []),
                    current_regime=market_context.get("market_regime", ""),
                )
                observations_context = kb.build_observations_context(
                    token_budget=settings.observations_token_budget
                    if not settings.is_debug else settings.observations_token_budget // 2,
                )
            if settings.enable_swing_tracking:
                st = SwingTracker(settings.data_dir)
                swing_context = st.get_summary_for_prompt(
                    token_budget=300 if not settings.is_debug else 150,
                )

            market_context_text = self._format_market_context(market_context)
            web_context = self._collect_web_context(
                market_data,
                news_data,
                limit=0 if settings.skip_web else 2,
            )
            news_inputs = self._build_news_inputs_snapshot(
                news_data,
                market_headlines=market_headlines,
                news_discoveries=news_discoveries,
                hot_stocks=hot_stocks,
                finviz_data=finviz_data,
                web_context=web_context,
            )
            news_context = self._format_news(
                news_data,
                market_headlines=market_headlines,
                news_discoveries=news_discoveries,
                hot_stocks=hot_stocks,
                finviz_data=finviz_data,
                web_context=web_context,
            )
            screener_context = self._format_screener_context(screener_results)
            prompt_sections = {
                "performance_feedback": performance_feedback,
                "learned_rules": learned_rules,
                "artifact_context": artifact_context,
                "knowledge_context": knowledge_context,
                "observations_context": observations_context,
                "swing_context": swing_context,
                "market_context": market_context,
                "market_data": summary,
                "news_context": news_context,
                "news_inputs": news_inputs,
                "screener_context": screener_results or {},
            }
            prompt = RESEARCH_PROMPT.format(
                performance_feedback=performance_feedback,
                learned_rules=learned_rules,
                artifact_context=artifact_context,
                knowledge_context=knowledge_context,
                observations_context=observations_context,
                swing_context=swing_context,
                market_context=market_context_text,
                market_data=json.dumps(summary, indent=2),
                news_context=news_context,
                screener_context=screener_context,
            )
            run_mode = "research"

        # Try CLI agent mode first (if enabled), fall back to direct API call
        analysis = await self._call_analysis(
            prompt=prompt,
            phase=run_mode,
            symbols=message.data.get("symbols", []),
            market_data=market_data,
            news_data=news_data,
            market_context=market_context,
            market_headlines=market_headlines,
            screener_results=screener_results,
            news_discoveries=news_discoveries,
            hot_stocks=hot_stocks,
            finviz_data=finviz_data,
            performance_feedback=prompt_sections.get("performance_feedback", ""),
            learned_rules=prompt_sections.get("learned_rules", ""),
            artifact_context=artifact_context,
        )
        analysis = self._merge_web_context_into_analysis(analysis, web_context)
        llm_meta = analysis.get("_meta", {})
        selected_provider = llm_meta.get("provider", provider or "unresolved")
        selected_model = llm_meta.get(
            "model",
            self._get_model_for_phase(selected_provider, run_mode) if selected_provider else "",
        )

        save_prompt_context_snapshot(
            phase=phase,
            provider=selected_provider or "unresolved",
            model=selected_model,
            symbols=message.data.get("symbols", []),
            prompt_sections=prompt_sections,
            llm_meta=llm_meta,
            data_dir=get_settings().data_dir,
        )
        record_llm_analytics(
            phase=phase,
            symbols=message.data.get("symbols", []),
            llm_meta=llm_meta,
            data_dir=get_settings().data_dir,
        )

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
            "market_headlines": market_headlines,
            "news_discoveries": news_discoveries,
            "hot_stocks": hot_stocks,
            "finviz": finviz_data,
            "screener_results": screener_results,
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
        if phase in {
            "monitor",
            "evening_reflection",
            "weekly_consolidation",
            "monthly_retrospective",
        }:
            return self._get_monitor_model(provider)
        return self._get_research_model(provider)

    def _build_lean_monitor_context(
        self, market_summary: dict, morning_context: dict,
        news_data: dict, market_context: dict,
    ) -> dict:
        """Build ultra-concise monitor context (~400-600 tokens total).

        Packs only what the LLM needs to make trade/skip decisions:
        morning trade plans as a compact table, current prices + indicators,
        active positions, and deterministic strategy signals.
        """
        morning_stocks = morning_context.get("stocks", {})

        # Morning plans: 1 line per stock
        plan_lines = []
        for sym, info in morning_stocks.items():
            rec = info.get("recommendation", "watch")
            tp = info.get("trade_plan", {})
            entry = tp.get("entry", "—")
            stop = tp.get("stop_loss", "—")
            target = tp.get("target", "—")
            reason = (info.get("reasoning") or "")[:80]
            plan_lines.append(
                f"  {sym}: {rec} | entry=${entry} stop=${stop} target=${target} | {reason}"
            )
        if not plan_lines:
            plan_lines.append("  (no morning plans available)")

        # Current state: compact table
        state_lines = ["| Stock | Price | Chg% | RSI | VolRatio | Near Entry? |",
                        "|-------|-------|------|-----|----------|-------------|"]
        for sym, data in market_summary.items():
            price = data.get("latest_price", 0)
            change = data.get("price_change_pct", 0)
            indicators = data.get("indicators", {}) if isinstance(data.get("indicators"), dict) else {}
            rsi = indicators.get("rsi_14", "—")
            if isinstance(rsi, (int, float)):
                rsi = f"{rsi:.0f}"

            # Volume ratio
            history = data.get("price_history", [])
            vol = data.get("volume", 0)
            vol_ratio = "—"
            if history and len(history) >= 5:
                avg_vol = sum(b.get("volume", 0) for b in history[-10:]) / max(len(history[-10:]), 1)
                if avg_vol > 0:
                    vol_ratio = f"{vol / avg_vol:.1f}x"

            # Check proximity to morning entry
            plan_entry = morning_stocks.get(sym, {}).get("trade_plan", {}).get("entry")
            near = ""
            if plan_entry and price and plan_entry > 0:
                if abs(price - plan_entry) / plan_entry < 0.02:
                    near = "YES"

            state_lines.append(
                f"| {sym:5s} | ${price:>8.2f} | {change:+5.1f}% | {rsi:>3s} | {vol_ratio:>8s} | {near:>5s} |"
            )

        # Active positions (from portfolio state)
        pos_lines = ["  (none)"]
        try:
            portfolio_path = Path(get_settings().data_dir) / "portfolio_state.json"
            if portfolio_path.exists():
                portfolio = json.loads(portfolio_path.read_text())
                active = []
                for sym, pos in portfolio.items():
                    if isinstance(pos, dict) and pos.get("shares", 0) > 0:
                        shares = pos["shares"]
                        avg = pos.get("avg_cost", 0)
                        cur = pos.get("last_price", 0)
                        pnl = ((cur - avg) / avg * 100) if avg else 0
                        active.append(f"  {sym}: {shares} shares @ ${avg:.2f}, now ${cur:.2f} ({pnl:+.1f}%)")
                if active:
                    pos_lines = active
        except (OSError, json.JSONDecodeError):
            pass

        # Strategy signals placeholder (filled by orchestrator if available)
        sig_lines = ["  (will be computed by strategy engine)"]

        return {
            "morning_plans": "\n".join(plan_lines),
            "current_state": "\n".join(state_lines),
            "active_positions": "\n".join(pos_lines),
            "strategy_signals": "\n".join(sig_lines),
        }

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

    def _collect_web_context(
        self,
        market_data: dict[str, Any],
        news_data: dict[str, Any],
        *,
        limit: int,
    ) -> dict[str, Any]:
        priority_symbols = self._select_priority_web_symbols(
            market_data,
            news_data,
            limit=limit,
        )
        if not priority_symbols:
            return {"priority_symbols": [], "checks": [], "articles_by_symbol": {}}

        articles_by_symbol: dict[str, list[dict[str, Any]]] = {}
        checks: list[dict[str, Any]] = []

        for symbol in priority_symbols:
            query = self._build_web_query(symbol, market_data.get(symbol, {}))
            search_url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
            )
            articles = self._fetch_google_news_articles(
                symbol=symbol,
                query=query,
                search_url=search_url,
                limit=3,
            )
            if not articles:
                continue

            articles_by_symbol[symbol] = articles
            sources = [
                source
                for source in dict.fromkeys(
                    article.get("source", "") for article in articles if article.get("source")
                )
            ]
            source_text = ", ".join(sources[:2]) or "Google News"
            checks.append(
                {
                    "symbol": symbol,
                    "query": query,
                    "source": "Google News",
                    "url": search_url,
                    "finding": (
                        f"Verified recent coverage for {symbol} via {source_text}; "
                        f"captured {len(articles)} current article links."
                    ),
                }
            )

        return {
            "priority_symbols": priority_symbols,
            "checks": checks,
            "articles_by_symbol": articles_by_symbol,
        }

    def _select_priority_web_symbols(
        self,
        market_data: dict[str, Any],
        news_data: dict[str, Any],
        *,
        limit: int,
    ) -> list[str]:
        ranked: list[tuple[float, float, float, float, str]] = []
        for symbol, data in market_data.items():
            if not isinstance(data, dict) or data.get("error"):
                continue
            news_entry = news_data.get(symbol, {}) if isinstance(news_data.get(symbol), dict) else {}
            info = data.get("info", {}) if isinstance(data.get("info"), dict) else {}
            market_cap = self._safe_float(info.get("market_cap")) or 0.0
            price = self._safe_float(data.get("latest_price")) or 0.0
            source_count = float(news_entry.get("source_count") or 0.0)
            headline_count = float(len(news_entry.get("news_headlines", []) or []))
            ranked.append((market_cap, price, source_count, headline_count, symbol))

        ranked.sort(reverse=True)
        return [symbol for *_rest, symbol in ranked[:limit]]

    def _build_web_query(self, symbol: str, market_entry: dict[str, Any]) -> str:
        info = market_entry.get("info", {}) if isinstance(market_entry, dict) else {}
        company_name = str(info.get("name") or "").strip()
        if company_name:
            return f"{company_name} {symbol} stock"
        return f"{symbol} stock"

    def _fetch_google_news_articles(
        self,
        *,
        symbol: str,
        query: str,
        search_url: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            response = httpx.get(
                search_url,
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "agent-trader/1.0"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.text)
        except Exception as exc:
            self.logger.info(
                "Skipping live web verification for %s (%s): %s",
                symbol,
                query,
                exc,
            )
            return []

        articles: list[dict[str, Any]] = []
        for item in root.findall("./channel/item")[:limit]:
            raw_title = (item.findtext("title", "") or "").strip()
            source = (item.findtext("source", "") or "").strip() or "Google News"
            link = (item.findtext("link", "") or "").strip()
            if not raw_title or not link:
                continue

            title = self._clean_google_news_title(raw_title, source)
            description = (item.findtext("description", "") or "").strip()
            summary = self._strip_html(description)
            articles.append(
                {
                    "title": title,
                    "url": link,
                    "source": source,
                    "publisher": source,
                    "published": (item.findtext("pubDate", "") or "").strip(),
                    "kind": "web",
                    "reason": f"Live Google News verification for {symbol}",
                    "summary": summary or f"Live search result for {query}",
                }
            )

        return self._dedupe_article_list(articles)

    def _merge_web_context_into_analysis(
        self,
        analysis: dict[str, Any],
        web_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(analysis, dict):
            return analysis

        context = web_context or {}
        checks = list(context.get("checks") or [])
        articles_by_symbol = context.get("articles_by_symbol") or {}
        if not checks and not articles_by_symbol:
            return analysis

        merged = dict(analysis)
        merged["web_checks"] = self._dedupe_web_checks(
            [*list(merged.get("web_checks") or []), *checks]
        )

        stocks = merged.get("stocks")
        if not isinstance(stocks, dict):
            return merged

        updated_stocks: dict[str, Any] = {}
        for symbol, payload in stocks.items():
            stock_payload = dict(payload) if isinstance(payload, dict) else {}
            auto_articles = list(articles_by_symbol.get(symbol) or [])
            stock_payload["supporting_articles"] = self._dedupe_article_list(
                [
                    *list(stock_payload.get("supporting_articles") or []),
                    *auto_articles,
                ]
            )
            updated_stocks[symbol] = stock_payload
        merged["stocks"] = updated_stocks
        return merged

    def _dedupe_web_checks(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for check in checks:
            if not isinstance(check, dict):
                continue
            key = (
                str(check.get("symbol") or "").upper(),
                str(check.get("url") or check.get("query") or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(check)
        return deduped

    def _dedupe_article_list(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for article in articles:
            if not isinstance(article, dict):
                continue
            key = str(article.get("url") or article.get("title") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(article)
        return deduped

    def _clean_google_news_title(self, title: str, source: str) -> str:
        suffix = f" - {source}"
        if source and title.endswith(suffix):
            return title[: -len(suffix)].strip()
        return title.strip()

    def _strip_html(self, value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def _format_news(
        self, news_data: dict,
        market_headlines: list | None = None,
        news_discoveries: list | None = None,
        hot_stocks: list | None = None,
        finviz_data: dict | None = None,
        web_context: dict | None = None,
    ) -> str:
        """Format all news context for Claude's prompt."""
        sections = []

        if market_headlines:
            market_lines = ["MARKET HEADLINES:"]
            for headline in market_headlines[:6]:
                source = headline.get("source", "market")
                title = headline.get("title", "")
                if not title:
                    continue
                sentiment = headline.get("sentiment", 0)
                sent_tag = f" [{sentiment:+.1f}]" if sentiment else ""
                url = headline.get("url", "")
                url_tag = f" <{url}>" if url else ""
                market_lines.append(f"  - [{source}] {title}{sent_tag}{url_tag}")
            if len(market_lines) > 1:
                sections.append("\n".join(market_lines))

        # Per-stock headlines, analyst recs, earnings, insider activity, filings
        stock_lines = []
        for symbol, data in news_data.items():
            headlines = data.get("news_headlines", [])
            analyst = data.get("analyst_recommendations")
            events = data.get("upcoming_events", [])
            insider = data.get("insider_signal")
            filings = data.get("filing_catalysts", [])
            sentiment = data.get("sentiment", "neutral")
            score = data.get("sentiment_score", 0)
            source_count = data.get("source_count", 0)

            if not headlines and not analyst and not events and not filings:
                continue

            source_tag = f", {source_count} sources" if source_count >= 2 else ""
            stock_lines.append(f"\n{symbol} (sentiment: {sentiment}, score: {score:+.2f}{source_tag}):")

            if headlines:
                for h in headlines[:4]:
                    h_sentiment = h.get("sentiment", 0)
                    if isinstance(h_sentiment, (int, float)):
                        sent_tag = f" [{h_sentiment:+.1f}]"
                    else:
                        sent_tag = ""
                    h_source = h.get("source", h.get("publisher", ""))
                    url = h.get("url", "")
                    url_tag = f" <{url}>" if url else ""
                    stock_lines.append(
                        f"  - [{h_source}] {h.get('title', '')}{sent_tag}{url_tag}"
                    )

            if filings:
                for f in filings[:3]:
                    url = f.get("url", "")
                    url_tag = f" <{url}>" if url else ""
                    stock_lines.append(
                        f"  SEC FILING: {f.get('title', '')} ({f.get('published', '')}){url_tag}"
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
                    days = e.get("days_until")
                    days_tag = f" ({days}d away)" if days is not None else ""
                    warning = " *** IMMINENT ***" if e.get("warning") else ""
                    stock_lines.append(
                        f"  UPCOMING: {e.get('type', 'event')} on {e.get('date', 'TBD')}{days_tag}{warning}"
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

        live_articles = (web_context or {}).get("articles_by_symbol", {})
        live_checks = list((web_context or {}).get("checks", []))
        if live_checks or live_articles:
            web_lines = ["LIVE WEB VERIFICATION:"]
            for check in live_checks:
                web_lines.append(
                    f"  {check.get('symbol', '?')}: {check.get('finding', 'Live check completed.')}"
                )
                if check.get("url"):
                    web_lines.append(f"    Search: <{check['url']}>")
            for symbol, articles in live_articles.items():
                for article in articles[:2]:
                    web_lines.append(
                        f"  - {symbol}: [{article.get('source', 'web')}] "
                        f"{article.get('title', '')} <{article.get('url', '')}>"
                    )
            sections.append("\n".join(web_lines))

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

    def _build_news_inputs_snapshot(
        self,
        news_data: dict[str, Any],
        *,
        market_headlines: list | None = None,
        news_discoveries: list | None = None,
        hot_stocks: list | None = None,
        finviz_data: dict | None = None,
        web_context: dict | None = None,
    ) -> dict[str, Any]:
        """Persist the structured news inputs that fed the LLM prompt."""
        return {
            "per_symbol": news_data or {},
            "market_headlines": market_headlines or [],
            "news_discoveries": news_discoveries or [],
            "hot_stocks": hot_stocks or [],
            "finviz": finviz_data or {},
            "web_influence": web_context or {},
        }

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

        # FRED macro regime signals (when available)
        fred_regime = ctx.get("fred_regime", {})
        if fred_regime:
            lines.append("\nFRED MACRO SIGNALS:")
            vol = fred_regime.get("volatility")
            if vol:
                lines.append(
                    f"  VIX (FRED): {vol['value']} ({vol['level'].upper()}) — {vol['action']}"
                )
            yc = fred_regime.get("yield_curve")
            if yc:
                lines.append(
                    f"  Yield curve: {yc['value']:+.2f}% ({yc['status']}) — {yc['implication']}"
                )
            credit = fred_regime.get("credit_stress")
            if credit:
                lines.append(
                    f"  HY spread: {credit['value']:.2f}% ({credit['level']}) — {credit['action']}"
                )

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

    async def _call_analysis(
        self,
        *,
        prompt: str,
        phase: str,
        symbols: list[str],
        market_data: dict,
        news_data: dict,
        market_context: dict,
        market_headlines: list,
        screener_results: dict | None,
        news_discoveries: list | None,
        hot_stocks: list | None,
        finviz_data: dict | None,
        performance_feedback: str,
        learned_rules: str,
        artifact_context: str,
    ) -> dict:
        """Route analysis to CLI agent or direct API call.

        When CLI agent mode is enabled and available:
          1. Write all data to staging directory
          2. Build a task prompt for the agent
          3. Run the agent (it can explore the repo for historical context)
          4. If agent fails, fall back to direct API call

        When CLI agent mode is disabled or unavailable:
          Uses the traditional direct API call path.
        """
        settings = get_settings()
        cli_attempts: list[dict[str, Any]] = []
        if settings.is_debug:
            self.logger.info(
                "Debug mode enabled: returning template analysis for phase '%s' (no CLI/API call).",
                phase,
            )
            return self._build_template_analysis(
                phase=phase,
                symbols=symbols,
                market_data=market_data,
                prior_attempts=cli_attempts,
            )

        use_cli = settings.use_cli_agent

        if use_cli:
            cli_provider = settings.cli_agent_provider
            if is_cli_available(cli_provider):
                self.logger.info("CLI agent mode: writing staging data...")

                write_staging_data(
                    market_data=market_data,
                    news_data=news_data,
                    market_context=market_context,
                    market_headlines=market_headlines,
                    screener_results=screener_results,
                    performance_feedback=performance_feedback
                    if isinstance(performance_feedback, str) else str(performance_feedback),
                    learned_rules=learned_rules
                    if isinstance(learned_rules, str) else str(learned_rules),
                    artifact_context=artifact_context
                    if isinstance(artifact_context, str) else str(artifact_context),
                    news_discoveries=news_discoveries,
                    hot_stocks=hot_stocks,
                    finviz_data=finviz_data,
                    data_dir=settings.data_dir,
                )

                # Build the task prompt
                if phase == "monitor":
                    task = build_monitor_task(symbols, data_dir=settings.data_dir)
                elif phase == "evening_reflection":
                    task = build_reflection_task(data_dir=settings.data_dir)
                elif phase == "weekly_consolidation":
                    task = build_weekly_consolidation_task(data_dir=settings.data_dir)
                elif phase == "monthly_retrospective":
                    task = build_monthly_retrospective_task(data_dir=settings.data_dir)
                else:
                    task = build_research_task(symbols, data_dir=settings.data_dir)

                # Determine model for the CLI agent
                cli_model = None
                if cli_provider == "claude":
                    cli_model = self._get_model_for_phase(cli_provider, phase)

                self.logger.info(
                    "Running %s CLI agent (model=%s, max_turns=%d)...",
                    cli_provider,
                    cli_model or "default",
                    settings.cli_agent_max_turns,
                )

                analysis = run_cli_agent(
                    task,
                    provider=cli_provider,
                    max_turns=settings.cli_agent_max_turns,
                    model=cli_model,
                    timeout_seconds=settings.cli_agent_timeout,
                    allowed_tools=["Read", "Glob", "Grep", "Bash", "WebFetch", "WebSearch"],
                )

                meta = analysis.get("_meta", {})
                if meta.get("status") == "success":
                    self.logger.info(
                        "CLI agent succeeded in %.1fs",
                        meta.get("duration_ms", 0) / 1000,
                    )
                    analysis.setdefault("_meta", {})
                    analysis["_meta"].update(
                        {
                            "execution_mode": "cli",
                            "provider": meta.get("provider", f"cli:{cli_provider}"),
                            "model": meta.get("model", cli_model or "default"),
                            "selected_provider": meta.get("provider", f"cli:{cli_provider}"),
                            "selected_model": meta.get("model", cli_model or "default"),
                            "attempts": [
                                {
                                    "execution_mode": "cli",
                                    "provider": meta.get("provider", f"cli:{cli_provider}"),
                                    "model": meta.get("model", cli_model or "default"),
                                    "status": "success",
                                    "duration_ms": meta.get("duration_ms"),
                                    "usage": meta.get("usage", {}),
                                }
                            ],
                        }
                    )
                    self.logger.info(
                        "Execution mode selected: CLI (provider=%s, model=%s)",
                        analysis["_meta"].get("provider"),
                        analysis["_meta"].get("model"),
                    )
                    self._last_provider = f"cli:{cli_provider}"
                    self._last_model = cli_model or "default"
                    return analysis

                # CLI failed — fall through to API
                self.logger.warning(
                    "CLI agent failed (%s), falling back to direct API call",
                    meta.get("error", "unknown"),
                )
                cli_attempts.append(
                    {
                        "execution_mode": "cli",
                        "provider": meta.get("provider", f"cli:{cli_provider}"),
                        "model": meta.get("model", cli_model or "default"),
                        "status": meta.get("status", "error"),
                        "duration_ms": meta.get("duration_ms"),
                        "error": meta.get("error") or meta.get("stderr"),
                        "quota_issue_detected": self._is_quota_error(
                            str(meta.get("error") or meta.get("stderr") or "")
                        ),
                    }
                )
            else:
                self.logger.info(
                    "CLI agent enabled but '%s' not on PATH — using direct API",
                    cli_provider,
                )

        # Default path: direct API call
        api_providers = self._get_api_provider_sequence()
        self.logger.info(
            "Execution mode selected: API (providers=%s)",
            ",".join(api_providers) if api_providers else "none",
        )
        return await self._call_llm(
            prompt,
            phase=phase,
            providers=api_providers,
            prior_attempts=cli_attempts,
        )

    def _build_template_analysis(
        self,
        *,
        phase: str,
        symbols: list[str],
        market_data: dict[str, Any],
        prior_attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build deterministic no-token responses for debug/test runs."""
        settings = get_settings()
        runtime = build_runtime_metadata()
        now = datetime.now(timezone.utc)
        active_provider = (
            f"template:{settings.cli_agent_provider}"
            if settings.use_cli_agent
            else "template:debug"
        )
        template_note = (
            f"Template response generated in DEBUG_MODE for phase '{phase}'. "
            "No CLI/API model call was made and zero tokens were consumed."
        )

        attempts = list(prior_attempts or [])
        attempts.append(
            {
                "execution_mode": "template",
                "provider": active_provider,
                "model": "template-v1",
                "status": "success",
                "duration_ms": 0.0,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            }
        )

        meta = {
            "status": "success",
            "execution_mode": "template",
            "provider_preference": self._get_provider_preference(),
            "provider": active_provider,
            "model": "template-v1",
            "selected_provider": active_provider,
            "selected_model": "template-v1",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "service_tier": "debug-template",
            "request_id": None,
            "rate_limits": {},
            "runtime": runtime,
            "duration_ms": 0.0,
            "attempts": attempts,
            "quota_issue_detected": False,
            "quota_note": "Template mode active; no model usage was attempted.",
            "template_note": template_note,
            "generated_at": now.isoformat(),
        }

        effective_symbols = symbols or sorted(market_data.keys())
        stocks = {
            symbol: self._build_template_stock_entry(symbol, market_data.get(symbol, {}))
            for symbol in effective_symbols
        }
        best_opportunities = list(stocks.keys())[:2]

        if phase == "monitor":
            monitor_stocks = {}
            for symbol, entry in stocks.items():
                plan = entry.get("trade_plan", {})
                monitor_stocks[symbol] = {
                    "sentiment": entry.get("sentiment", "neutral"),
                    "confidence": entry.get("confidence", 0.5),
                    "key_observations": entry.get("key_observations", []),
                    "recommendation": "hold",
                    "ready_to_trade": False,
                    "catalysts": entry.get("catalysts", []),
                    "risks": entry.get("risks", []),
                    "trade_plan": {
                        "entry": plan.get("entry", 0.0),
                        "stop_loss": plan.get("stop_loss", 0.0),
                        "target": plan.get("target", 0.0),
                    },
                    "supporting_articles": [],
                }
            return {
                "overall_sentiment": "neutral",
                "market_summary": template_note,
                "stocks": monitor_stocks,
                "web_checks": [],
                "_meta": meta,
            }

        if phase == "evening_reflection":
            return {
                "date": now.strftime("%Y-%m-%d"),
                "market_regime": "neutral",
                "market_summary": template_note,
                "sector_leaders": [],
                "sector_laggards": [],
                "trades_review": [],
                "patterns_detected": [],
                "confidence_calibration": {
                    "high_conf_count": 0,
                    "high_conf_win_rate": 0.0,
                    "medium_conf_count": 0,
                    "medium_conf_win_rate": 0.0,
                    "assessment": "Debug template mode; calibration skipped.",
                },
                "swing_updates": [],
                "forward_outlook": "Debug template mode active; no model-generated outlook.",
                "lessons": [
                    "Debug template mode is enabled, so this reflection is deterministic."
                ],
                "self_improvement_proposals": [
                    {
                        "category": "infrastructure",
                        "priority": "high",
                        "title": "Switch off debug mode for live model validation",
                        "description": (
                            "Set DEBUG_MODE=false to re-enable CLI/API model calls once "
                            "token budget and provider access are ready."
                        ),
                        "expected_impact": (
                            "Restores full model reasoning and real confidence calibration."
                        ),
                    }
                ],
                "_meta": meta,
            }

        if phase == "weekly_consolidation":
            today = now.strftime("%Y-%m-%d")
            return {
                "week_start": today,
                "week_end": today,
                "summary": {
                    "trades_count": 0,
                    "win_rate": 0.0,
                    "total_pnl_pct": 0.0,
                    "swing_positions_held": 0,
                    "swing_win_rate": 0.0,
                },
                "pattern_effectiveness": [],
                "strategy_effectiveness": {},
                "regime_analysis": {
                    "dominant": "neutral",
                    "shifts": 0,
                    "shift_description": "Debug template mode; no weekly consolidation computed.",
                },
                "confidence_calibration": {
                    "high": {"expected": 0.8, "actual": 0.0},
                    "medium": {"expected": 0.6, "actual": 0.0},
                    "low": {"expected": 0.4, "actual": 0.0},
                },
                "forward_thesis": {
                    "outlook": template_note,
                    "confidence": 0.0,
                    "key_risks": ["Debug template mode active."],
                    "opportunities": [],
                },
                "knowledge_updates": {
                    "new_patterns": [],
                    "updated_strategies": [],
                    "new_lessons": [
                        "Template-only weekly review generated in debug mode."
                    ],
                    "regime_rules_updated": False,
                },
                "_meta": meta,
            }

        if phase == "monthly_retrospective":
            month = now.strftime("%Y-%m")
            return {
                "month": month,
                "summary": {
                    "trading_days": 0,
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl_pct": 0.0,
                    "best_week": "",
                    "worst_week": "",
                },
                "strategy_regime_matrix": {},
                "confidence_accuracy_curve": {},
                "top_lessons": [
                    "Template monthly retrospective generated while DEBUG_MODE=true."
                ],
                "vs_last_month": {
                    "win_rate_change": "0%",
                    "pnl_change": "0%",
                    "improvement_areas": "Enable real model mode to capture meaningful change.",
                    "regression_areas": "N/A in template mode.",
                },
                "_meta": meta,
            }

        if phase == "evolution":
            return {
                "evolution_proposals": [
                    {
                        "category": "infrastructure",
                        "priority": "high",
                        "title": "Enable paper mode to start accumulating real observations",
                        "description": (
                            "Set RUN_MODE=paper to begin real LLM analysis and build evidence "
                            "for strategy improvement proposals."
                        ),
                        "expected_impact": "Enables evidence-based evolution after first few trading days.",
                        "implementation_hint": {
                            "file": ".env",
                            "function": "RUN_MODE",
                            "current_value": "debug",
                            "proposed_value": "paper",
                            "type": "config_change",
                        },
                        "evidence": {"sample_size": 0, "win_rate_current": 0.0, "dates": []},
                    }
                ],
                "strategy_gaps": ["Insufficient data to identify gaps — run in paper mode first"],
                "data_gaps": ["Need real market observation data before data gaps can be assessed"],
                "top_priority": "Switch RUN_MODE=paper to begin accumulating real trading observations",
                "_meta": meta,
            }

        return {
            "overall_sentiment": "neutral",
            "market_summary": template_note,
            "market_regime": "neutral",
            "best_opportunities": best_opportunities,
            "stocks": stocks,
            "self_reflection": (
                "Debug template mode is active. This run validates wiring, not model quality."
            ),
            "web_checks": [],
            "_meta": meta,
        }

    def _build_template_stock_entry(self, symbol: str, stock_data: dict[str, Any]) -> dict[str, Any]:
        """Generate a deterministic stock payload for template mode."""
        price = self._safe_float(stock_data.get("latest_price")) or 0.0
        change_pct = self._safe_float(stock_data.get("price_change_pct")) or 0.0
        entry = round(price, 2) if price > 0 else 0.0
        stop_loss = round(price * 0.98, 2) if price > 0 else 0.0
        target = round(price * 1.03, 2) if price > 0 else 0.0
        risk = max(entry - stop_loss, 0.0)
        reward = max(target - entry, 0.0)
        risk_reward = round((reward / risk), 2) if risk > 0 else 0.0

        return {
            "sentiment": "neutral",
            "confidence": 0.5,
            "key_observations": [
                (
                    f"Template baseline for {symbol}: price {price:.2f}, "
                    f"change {change_pct:+.2f}%."
                ),
                "Deterministic debug output used to validate workflow plumbing.",
            ],
            "news_impact": "none",
            "news_summary": "Template mode active; no model-driven news synthesis executed.",
            "technical_setup": "Template setup only; no live inference in DEBUG_MODE.",
            "recommendation": "watch",
            "trade_plan": {
                "entry": entry,
                "stop_loss": stop_loss,
                "target": target,
                "risk_reward_ratio": risk_reward,
                "position_size_pct": 1.0,
                "timeframe": "swing_2_5_days",
            },
            "catalysts": ["Disable DEBUG_MODE to enable real catalyst ranking."],
            "risks": ["Template output may not reflect live market conditions."],
            "earnings_warning": False,
            "supporting_articles": [],
        }

    async def _call_llm(
        self,
        prompt: str,
        phase: str,
        *,
        providers: list[str] | None = None,
        prior_attempts: list[dict[str, Any]] | None = None,
    ) -> dict:
        providers = list(providers) if providers is not None else self._get_provider_sequence()
        runtime = build_runtime_metadata()
        attempts = list(prior_attempts or [])
        if not providers:
            fallback_provider = self._get_api_fallback_provider()
            if fallback_provider and get_settings().use_cli_agent:
                no_provider_message = (
                    f"No {fallback_provider} API key configured for "
                    f"{get_settings().cli_agent_provider} fallback"
                )
            else:
                no_provider_message = "No LLM API key configured"
            return {
                "overall_sentiment": "neutral",
                "market_summary": f"LLM analysis failed: {no_provider_message}",
                "stocks": {},
                "_meta": {
                    "status": "error",
                    "execution_mode": "none",
                    "provider_preference": self._get_provider_preference(),
                    "runtime": runtime,
                    "quota_issue_detected": any(
                        attempt.get("quota_issue_detected", False) for attempt in attempts
                    ),
                    "quota_note": self._build_quota_note(attempts) or no_provider_message,
                    "attempts": attempts,
                },
            }

        raw_text = ""
        errors = []

        for provider in providers:
            model = self._get_model_for_phase(provider, phase)
            client = self._get_client(provider)
            started = perf_counter()

            try:
                raw_text, response_meta = self._call_llm_once(client, provider, model, prompt)
                analysis = self._parse_llm_response(raw_text)
                response_meta["duration_ms"] = round((perf_counter() - started) * 1000, 1)
                attempts.append(
                    {
                        "execution_mode": "api",
                        "provider": provider,
                        "model": model,
                        "status": "success",
                        "duration_ms": response_meta["duration_ms"],
                        "usage": response_meta.get("usage", {}),
                    }
                )
                analysis.setdefault("_meta", {})
                analysis["_meta"].update(
                    {
                        "status": "success",
                        "execution_mode": "api",
                        "provider_preference": self._get_provider_preference(),
                        "provider": provider,
                        "model": response_meta.get("model", model),
                        "selected_provider": provider,
                        "selected_model": response_meta.get("model", model),
                        "usage": response_meta.get("usage", {}),
                        "service_tier": response_meta.get("service_tier"),
                        "request_id": response_meta.get("request_id"),
                        "rate_limits": response_meta.get("rate_limits", {}),
                        "runtime": runtime,
                        "duration_ms": response_meta.get("duration_ms"),
                        "attempts": attempts,
                        "quota_issue_detected": any(
                            attempt.get("quota_issue_detected", False) for attempt in attempts
                        ),
                        "quota_note": self._build_quota_note(attempts),
                    }
                )
                self._last_provider = provider
                self._last_model = model
                return analysis
            except json.JSONDecodeError as exc:
                duration_ms = round((perf_counter() - started) * 1000, 1)
                attempts.append(
                    {
                        "execution_mode": "api",
                        "provider": provider,
                        "model": model,
                        "status": "parse_error",
                        "duration_ms": duration_ms,
                        "error": f"Could not parse JSON: {exc}",
                        "quota_issue_detected": False,
                    }
                )
                errors.append(f"{provider}/{model}: could not parse JSON ({exc})")
            except Exception as exc:
                duration_ms = round((perf_counter() - started) * 1000, 1)
                attempts.append(
                    {
                        "execution_mode": "api",
                        "provider": provider,
                        "model": model,
                        "status": "error",
                        "duration_ms": duration_ms,
                        "error": str(exc),
                        "quota_issue_detected": self._is_quota_error(str(exc)),
                    }
                )
                errors.append(f"{provider}/{model}: {exc}")

        failure = {
            "overall_sentiment": "neutral",
            "market_summary": f"LLM analysis failed: {' | '.join(errors)}",
            "stocks": {},
            "_meta": {
                "status": "error",
                "execution_mode": "api" if any(
                    attempt.get("execution_mode") == "api" for attempt in attempts
                ) else "cli",
                "provider_preference": self._get_provider_preference(),
                "provider": providers[0] if providers else "",
                "model": self._get_model_for_phase(providers[0], phase) if providers else "",
                "selected_provider": providers[0] if providers else "",
                "selected_model": self._get_model_for_phase(providers[0], phase) if providers else "",
                "usage": {},
                "service_tier": None,
                "request_id": None,
                "rate_limits": {},
                "runtime": runtime,
                "duration_ms": None,
                "attempts": attempts,
                "quota_issue_detected": any(
                    attempt.get("quota_issue_detected", False) for attempt in attempts
                ),
                "quota_note": self._build_quota_note(attempts),
            },
        }
        if raw_text:
            failure["raw_response"] = raw_text[:500]
        return failure

    def _call_llm_once(
        self, client: Any, provider: str, model: str, prompt: str
    ) -> tuple[str, dict[str, Any]]:
        settings = get_settings()
        max_output_tokens = max(64, int(settings.llm_max_output_tokens))
        prompt_to_send = self._truncate_prompt(prompt, settings.llm_max_prompt_chars)

        if provider == "anthropic":
            raw_response = client.messages.with_raw_response.create(
                model=model,
                max_tokens=max_output_tokens,
                messages=[{"role": "user", "content": prompt_to_send}],
            )
            response = raw_response.parse()
            usage = self._extract_usage(provider, response)
            return response.content[0].text, {
                "provider": provider,
                "model": getattr(response, "model", model),
                "usage": usage,
                "request_id": getattr(raw_response, "request_id", None),
                "rate_limits": self._extract_rate_limits(raw_response.headers, usage),
                "max_output_tokens": max_output_tokens,
                "prompt_chars": len(prompt_to_send),
            }

        if provider == "openai":
            raw_response = client.chat.completions.with_raw_response.create(
                model=model,
                max_tokens=max_output_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt_to_send}],
            )
            response = raw_response.parse()
            usage = self._extract_usage(provider, response)
            return response.choices[0].message.content or "", {
                "provider": provider,
                "model": getattr(response, "model", model),
                "usage": usage,
                "service_tier": getattr(response, "service_tier", None),
                "request_id": getattr(raw_response, "request_id", None),
                "rate_limits": self._extract_rate_limits(raw_response.headers, usage),
                "max_output_tokens": max_output_tokens,
                "prompt_chars": len(prompt_to_send),
            }

        raise RuntimeError(f"Unsupported LLM provider '{provider}'")

    def _truncate_prompt(self, prompt: str, max_chars: int) -> str:
        if max_chars <= 0 or len(prompt) <= max_chars:
            return prompt
        self.logger.warning(
            "Prompt exceeded max chars (%d > %d). Truncating for low-cost safety.",
            len(prompt),
            max_chars,
        )
        return prompt[:max_chars]

    def _extract_usage(self, provider: str, response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}

        if provider == "anthropic":
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            cache_creation = getattr(usage, "cache_creation_input_tokens", None)
            cache_read = getattr(usage, "cache_read_input_tokens", None)
            total_tokens = (
                (input_tokens or 0)
                + (output_tokens or 0)
                + (cache_creation or 0)
                + (cache_read or 0)
            )
            payload = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "total_tokens": total_tokens,
            }
            return {key: value for key, value in payload.items() if value is not None}

        prompt_details = getattr(usage, "prompt_tokens_details", None)
        completion_details = getattr(usage, "completion_tokens_details", None)
        payload = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "cached_input_tokens": getattr(prompt_details, "cached_tokens", None),
            "reasoning_output_tokens": getattr(completion_details, "reasoning_tokens", None),
        }
        return {key: value for key, value in payload.items() if value is not None}

    def _extract_rate_limits(self, headers: Any, usage: dict[str, Any]) -> dict[str, Any]:
        if headers is None:
            return {}

        header_map = {str(key).lower(): str(value) for key, value in headers.items()}
        selected = {
            key: value
            for key, value in header_map.items()
            if "ratelimit" in key or key in {"retry-after", "anthropic-organization-id"}
        }

        tokens_used = (
            usage.get("total_tokens")
            or (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        )
        requests_after = self._safe_int(
            header_map.get("x-ratelimit-remaining-requests")
            or header_map.get("anthropic-ratelimit-requests-remaining")
        )
        tokens_after = self._safe_int(
            header_map.get("x-ratelimit-remaining-tokens")
            or header_map.get("anthropic-ratelimit-tokens-remaining")
        )
        input_tokens_after = self._safe_int(
            header_map.get("anthropic-ratelimit-input-tokens-remaining")
        )
        output_tokens_after = self._safe_int(
            header_map.get("anthropic-ratelimit-output-tokens-remaining")
        )

        estimates = {}
        if requests_after is not None:
            estimates["requests_remaining_after_request"] = requests_after
            estimates["requests_remaining_before_request_estimate"] = requests_after + 1
        if tokens_after is not None:
            estimates["tokens_remaining_after_request"] = tokens_after
            estimates["tokens_remaining_before_request_estimate"] = tokens_after + tokens_used
        if input_tokens_after is not None:
            estimates["input_tokens_remaining_after_request"] = input_tokens_after
            estimates["input_tokens_remaining_before_request_estimate"] = (
                input_tokens_after + (usage.get("input_tokens") or 0)
            )
        if output_tokens_after is not None:
            estimates["output_tokens_remaining_after_request"] = output_tokens_after
            estimates["output_tokens_remaining_before_request_estimate"] = (
                output_tokens_after + (usage.get("output_tokens") or 0)
            )

        return {
            "headers": selected,
            "estimates": estimates,
            "billing_balance_before_workflow": {
                "available": False,
                "reason": (
                    "Rate-limit headers are available, but billing/credit balance is not "
                    "available from these request responses."
                ),
            },
        }

    def _build_quota_note(self, attempts: list[dict[str, Any]]) -> str | None:
        for attempt in attempts:
            if attempt.get("quota_issue_detected") and attempt.get("error"):
                return attempt["error"]
        if attempts:
            return (
                "Billing balance is not exposed by normal request responses. "
                "This repo records token usage and any quota errors returned by the provider."
            )
        return None

    def _is_quota_error(self, message: str) -> bool:
        lowered = message.lower()
        markers = [
            "credit balance is too low",
            "insufficient_quota",
            "billing",
            "quota",
            "rate limit",
        ]
        return any(marker in lowered for marker in markers)

    def _safe_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).replace(",", "").strip())
        except ValueError:
            return None

    def _safe_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            return None

    def _parse_llm_response(self, raw_text: str) -> dict:
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            raw_text = raw_text.rsplit("```", 1)[0]
        return json.loads(raw_text)

    def _save_research(self, analysis: dict, phase: str) -> None:
        archive_dir = Path(get_settings().data_dir) / "research"
        archive_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        filepath = archive_dir / f"{now.strftime('%Y-%m-%d')}_{phase}_{now.strftime('%H%M')}.json"
        filepath.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")

    # ── New Phase Handlers ─────────────────────────────────────────────

    async def _handle_evening_reflection(self, message: Message) -> dict:
        """Evening reflection: review the day and extract observations."""
        settings = get_settings()
        data = message.data

        todays_trades = data.get("todays_trades", "No trades executed today.")
        market_regime_summary = data.get("market_regime_summary", "No regime data.")
        active_positions = data.get("active_positions", "No active swing positions.")
        recent_observations = data.get("recent_observations", "No prior observations.")
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        prompt = EVENING_REFLECTION_PROMPT.format(
            todays_trades=todays_trades,
            market_regime_summary=market_regime_summary,
            active_positions=active_positions,
            recent_observations=recent_observations,
            today_date=today_date,
        )

        analysis = await self._call_phase_analysis(prompt, "evening_reflection")

        # Save observation to knowledge base
        if settings.enable_knowledge_base and isinstance(analysis, dict):
            meta_status = analysis.get("_meta", {}).get("status", "")
            if meta_status != "error":
                kb = KnowledgeBase(settings.data_dir)
                kb.save_daily_observation(analysis)

        self._save_research(analysis, "evening_reflection")

        return {
            "research": analysis,
            "phase": "evening_reflection",
            "symbols": data.get("symbols", []),
            "market_data": data.get("market_data", {}),
        }

    async def _handle_weekly_consolidation(self, message: Message) -> dict:
        """Weekly review: consolidate observations and update knowledge base."""
        settings = get_settings()
        data = message.data
        kb = KnowledgeBase(settings.data_dir)

        # Gather inputs
        observations = kb.get_recent_observations(days=7)
        obs_text = json.dumps(observations, indent=2, default=str) if observations else "No observations this week."
        performance_summary = json.dumps(self._tracker.get_performance_summary(), indent=2)
        trade_details = self._tracker.get_recent_trades_for_prompt(20)
        current_knowledge = kb.build_knowledge_context(token_budget=800)

        today = datetime.now(timezone.utc)
        week_start = (today - __import__("datetime").timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        week_end = today.strftime("%Y-%m-%d")

        prompt = WEEKLY_CONSOLIDATION_PROMPT.format(
            performance_summary=performance_summary,
            daily_observations=obs_text,
            current_knowledge=current_knowledge or "No accumulated knowledge yet.",
            trade_details=trade_details,
            week_start=week_start,
            week_end=week_end,
        )

        analysis = await self._call_phase_analysis(prompt, "weekly_consolidation")

        # Save weekly review (this also updates knowledge base)
        if isinstance(analysis, dict) and analysis.get("_meta", {}).get("status") != "error":
            kb.save_weekly_review(analysis)

        # Save learned rules if present
        new_lessons = analysis.get("knowledge_updates", {}).get("new_lessons", [])
        if new_lessons:
            self._tracker.save_learned_rules(new_lessons)

        self._save_research(analysis, "weekly_consolidation")

        return {
            "research": analysis,
            "phase": "weekly_consolidation",
            "symbols": data.get("symbols", []),
            "market_data": data.get("market_data", {}),
        }

    async def _handle_monthly_retrospective(self, message: Message) -> dict:
        """Monthly review: deep retrospective and strategic adjustments."""
        settings = get_settings()
        data = message.data
        kb = KnowledgeBase(settings.data_dir)

        weekly_reviews = kb.get_recent_weekly_reviews(count=4)
        weekly_text = json.dumps(weekly_reviews, indent=2, default=str) if weekly_reviews else "No weekly reviews."
        performance_summary = json.dumps(self._tracker.get_performance_summary(), indent=2)
        current_knowledge = kb.build_knowledge_context(token_budget=800)
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        prompt = MONTHLY_RETROSPECTIVE_PROMPT.format(
            performance_summary=performance_summary,
            weekly_reviews=weekly_text,
            current_knowledge=current_knowledge or "No accumulated knowledge yet.",
            month=month,
        )

        analysis = await self._call_phase_analysis(prompt, "monthly_retrospective")

        if isinstance(analysis, dict) and analysis.get("_meta", {}).get("status") != "error":
            kb.save_monthly_review(analysis)

        self._save_research(analysis, "monthly_retrospective")

        return {
            "research": analysis,
            "phase": "monthly_retrospective",
            "symbols": data.get("symbols", []),
            "market_data": data.get("market_data", {}),
        }

    async def _handle_evolution(self, message: Message) -> dict:
        """Evolution phase: analyze performance and propose concrete system improvements."""
        from agent_trader.utils.improvement_log import (
            get_evolution_summary, save_evolution_proposals
        )
        settings = get_settings()
        kb = KnowledgeBase(settings.data_dir)

        performance_summary = json.dumps(self._tracker.get_performance_summary(), indent=2)
        strategy_effectiveness = kb.build_knowledge_context(
            token_budget=600
        ) or "No strategy effectiveness data yet."
        recent_observations = kb.build_observations_context(token_budget=600) or "No observations yet."

        # List available strategies from the strategy names in knowledge
        strategy_list = [
            "momentum", "mean_reversion", "trend", "volume_breakout",
            "support_resistance", "vwap", "relative_strength", "news_catalyst",
        ]

        pending_summary = get_evolution_summary(settings.data_dir)
        pending_text = (
            f"{pending_summary['total']} pending proposals "
            f"({pending_summary['high_priority_count']} high priority). "
            f"Recent titles: {', '.join(pending_summary['recent_titles'][-5:]) or 'none'}"
        )

        prompt = EVOLUTION_PROMPT.format(
            performance_summary=performance_summary,
            strategy_effectiveness=strategy_effectiveness,
            recent_observations=recent_observations,
            strategy_list=json.dumps(strategy_list),
            pending_proposals=pending_text,
        )

        analysis = await self._call_phase_analysis(prompt, "evolution")

        if isinstance(analysis, dict) and analysis.get("_meta", {}).get("status") != "error":
            proposals = analysis.get("evolution_proposals", [])
            if proposals:
                from agent_trader.utils.profiles import get_profile_id
                save_evolution_proposals(
                    proposals,
                    data_dir=settings.data_dir,
                    profile_id=get_profile_id(settings),
                )

        self._save_research(analysis, "evolution")

        return {
            "research": analysis,
            "phase": "evolution",
            "symbols": [],
            "market_data": {},
        }

    async def _call_phase_analysis(self, prompt: str, phase: str) -> dict:
        """Run reflection/review phases through the same resilient path as research."""
        settings = get_settings()
        return await self._call_analysis(
            prompt=prompt,
            phase=phase,
            symbols=[],
            market_data={},
            news_data={},
            market_context={},
            market_headlines=[],
            screener_results=None,
            news_discoveries=[],
            hot_stocks=[],
            finviz_data={},
            performance_feedback="",
            learned_rules="",
            artifact_context=build_recent_artifact_summary(data_dir=settings.data_dir),
        )
