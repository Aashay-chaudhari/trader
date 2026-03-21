"""CLI Agent Runner — invoke Claude Code (or future Codex) as a subprocess.

Instead of making a single API call with a manually constructed prompt,
this module spawns a CLI agent that can:
  - Read the staged data (market data, news, technicals)
  - Autonomously explore the repo (past journals, learned rules, trade history)
  - Return structured JSON analysis

The agent sees the full repo, so it can find patterns the hardcoded prompt
assembly might miss — like a stock that was flagged 3 days ago but failed,
or a learned rule that applies to today's setup.

Usage flow:
  1. Python pipeline gathers data (screener, data agent, news agent)
  2. Writes data to data/staging/current/
  3. Writes a task prompt (TASK.md) explaining what to analyze
  4. Invokes: claude -p "$(cat TASK.md)" --output-format json --max-turns 5
  5. Parses the JSON output
  6. Falls back to direct API call if CLI unavailable
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any

from agent_trader.config.settings import get_settings

logger = logging.getLogger(__name__)


def get_staging_dir(data_dir: str | None = None) -> Path:
    root = Path(data_dir or get_settings().data_dir)
    return root / "staging" / "current"


def resolve_cli_binary(provider: str = "claude") -> str | None:
    """Resolve the CLI binary path for the requested provider.

    On Windows, npm-installed CLIs are commonly exposed as ``*.cmd`` shims.
    Passing the fully resolved path avoids subprocess lookup issues when
    ``subprocess.run(["claude", ...])`` cannot find the shim even though the
    shell can.
    """
    resolved = shutil.which(provider)
    if resolved:
        return resolved

    if os.name == "nt" and "." not in provider:
        return shutil.which(f"{provider}.cmd")

    return None


def is_cli_available(provider: str = "claude") -> bool:
    """Check if the CLI agent binary is on PATH."""
    return resolve_cli_binary(provider) is not None


def write_staging_data(
    *,
    market_data: dict[str, Any],
    news_data: dict[str, Any],
    market_context: dict[str, Any],
    market_headlines: list[dict],
    screener_results: dict[str, Any] | None,
    performance_feedback: str,
    learned_rules: str,
    artifact_context: str,
    news_discoveries: list[dict] | None = None,
    hot_stocks: list[dict] | None = None,
    finviz_data: dict[str, Any] | None = None,
    data_dir: str | None = None,
) -> Path:
    """Write all pipeline data to the staging directory for the agent to read.

    Returns the staging directory path.
    """
    staging = get_staging_dir(data_dir)
    # Clean previous staging data
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    # Market data (prices, technicals per stock)
    (staging / "market_data.json").write_text(
        json.dumps(market_data, indent=2, default=str)
    )

    # News data (per-stock headlines, sentiment, analyst recs)
    (staging / "news_data.json").write_text(
        json.dumps(news_data, indent=2, default=str)
    )

    # Market context (VIX, S&P trend, sector rotation, macro)
    (staging / "market_context.json").write_text(
        json.dumps(market_context, indent=2, default=str)
    )

    # Market headlines (broad market news)
    (staging / "market_headlines.json").write_text(
        json.dumps(market_headlines, indent=2, default=str)
    )

    # Screener results (why stocks were selected)
    if screener_results:
        (staging / "screener_results.json").write_text(
            json.dumps(screener_results, indent=2, default=str)
        )

    # News discoveries and hot stocks
    if news_discoveries:
        (staging / "news_discoveries.json").write_text(
            json.dumps(news_discoveries, indent=2, default=str)
        )
    if hot_stocks:
        (staging / "hot_stocks.json").write_text(
            json.dumps(hot_stocks, indent=2, default=str)
        )
    if finviz_data:
        (staging / "finviz_data.json").write_text(
            json.dumps(finviz_data, indent=2, default=str)
        )

    # Performance context (text, ready for the agent)
    (staging / "performance_feedback.md").write_text(performance_feedback)
    (staging / "learned_rules.md").write_text(learned_rules)
    (staging / "artifact_context.md").write_text(artifact_context)

    return staging


def build_research_task(symbols: list[str], *, data_dir: str | None = None) -> str:
    """Build the task prompt for the research phase.

    This tells the agent what to do. The agent will then autonomously
    read the staging data AND explore the repo for historical context.
    """
    return _build_research_task_prompt(
        symbols,
        data_root=Path(data_dir or get_settings().data_dir),
    )

    data_root = Path(data_dir or get_settings().data_dir)
    staging_dir = get_staging_dir(str(data_root)).as_posix()
    data_root_display = data_root.as_posix()

    return f"""You are an expert stock market analyst running inside the agent-trader repository.

## YOUR TASK
Analyze today's shortlisted stocks and produce trading recommendations.
You are CONSERVATIVE — only recommend trades with clear setups and defined risk.
You manage a $100,000 paper portfolio. Every dollar counts.

## STRATEGIST MEMORY ROOT
All of your saved artifacts for this strategist are stored under `{data_root_display}`.
Use this root when checking prior journals, trades, research, cache, and staging files.

## TODAY'S STOCKS
{', '.join(symbols)}

## HOW TO WORK

### Step 1: Read today's data
All current market data is in `{staging_dir}`:
- market_data.json — prices, RSI, MACD, Bollinger Bands, SMAs per stock
- news_data.json — per-stock headlines, sentiment, analyst recs
- market_context.json — VIX, S&P trend, yields, sector rotation
- market_headlines.json — broad market news
- screener_results.json — why these stocks were selected (if exists)
- news_discoveries.json — stocks discovered via news (if exists)
- hot_stocks.json — cross-source hot stocks (if exists)
- finviz_data.json — analyst changes (if exists)
- performance_feedback.md — your past trade outcomes and win rate
- learned_rules.md — trading rules you've discovered from past performance
- artifact_context.md — summaries of recent research runs

### Step 2: Explore historical context (IMPORTANT — this is your edge)
Look at past data to find patterns:
- `{data_root_display}/journal/` — past trading journal entries (markdown + JSON). Check if any of today's stocks appeared recently and what happened.
- `{data_root_display}/feedback/completed_trades.json` — full trade history with P&L. Look for patterns with today's stocks.
- `{data_root_display}/feedback/learned_rules.json` — rules you generated from past reviews.
- `{data_root_display}/research/` — past research outputs. Check if your previous analysis on these stocks was accurate.

Spend time here. This historical context is what makes your analysis better than a single API call.

### Step 3: Live research (you have internet access)
You can fetch live information to deepen your analysis. Use Bash with curl or python:

Examples:
- Get real-time quote: `curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d"`
- Get recent news: `curl -s "https://query1.finance.yahoo.com/v1/finance/search?q=AAPL&newsCount=5"`
- Get earnings date: `curl -s "https://query1.finance.yahoo.com/v10/finance/quoteSummary/AAPL?modules=calendarEvents"`
- Run a quick python script to process data

Focus your live research on:
1. Stocks where the staging data is ambiguous or your confidence is low
2. Breaking news that might not be captured in the staging data
3. Verifying key price levels (support/resistance)

Do NOT spend too many turns on this — 1-2 targeted fetches max.

### Step 4: Produce your analysis
Output ONLY valid JSON (no markdown, no explanation outside JSON) in this exact format:

```json
{{
    "overall_sentiment": "bullish|bearish|neutral",
    "market_summary": "2-3 sentence market overview",
    "market_regime": "risk_on|risk_off|neutral",
    "best_opportunities": ["SYMBOL1", "SYMBOL2"],
    "stocks": {{
        "<SYMBOL>": {{
            "sentiment": "bullish|bearish|neutral",
            "confidence": 0.0-1.0,
            "key_observations": ["observation with specific numbers"],
            "news_impact": "positive|negative|neutral|none",
            "news_summary": "1 sentence on relevant news",
            "technical_setup": "1-2 sentence technical summary",
            "recommendation": "buy|sell|hold|watch",
            "trade_plan": {{
                "entry": 0.00,
                "stop_loss": 0.00,
                "target": 0.00,
                "risk_reward_ratio": 0.0,
                "position_size_pct": 0.0,
                "timeframe": "intraday|swing_2_5_days|swing_1_2_weeks"
            }},
            "catalysts": ["what could drive this"],
            "risks": ["what could go wrong"],
            "earnings_warning": false,
            "historical_context": "what you found in past journals/trades about this stock"
        }}
    }},
    "self_reflection": "1-2 sentences on your confidence calibration based on past performance"
}}
```

IMPORTANT:
- Output ONLY the JSON object, nothing else
- Every stock in today's list must appear in "stocks"
- Use specific numbers from the data (actual RSI values, actual price levels)
- Reference historical patterns you found in the journal/feedback data
- Be honest about confidence — if past trades on a stock went badly, lower your confidence
"""


def build_monitor_task(symbols: list[str], *, data_dir: str | None = None) -> str:
    """Build the task prompt for the monitor phase."""
    return _build_monitor_task_prompt(
        symbols,
        data_root=Path(data_dir or get_settings().data_dir),
    )

    data_root = Path(data_dir or get_settings().data_dir)
    staging_dir = get_staging_dir(str(data_root)).as_posix()
    data_root_display = data_root.as_posix()
    return f"""You are an expert stock market analyst running inside the agent-trader repository.

## YOUR TASK
Quick monitoring check on the watchlist. What changed since morning research?
Focus on: price moves, new news, signals that changed.

## STRATEGIST MEMORY ROOT
All of your saved artifacts for this strategist are stored under `{data_root_display}`.
Use this root when checking prior journals, trades, research, cache, and staging files.

## WATCHLIST
{', '.join(symbols)}

## HOW TO WORK

### Step 1: Read current data
- `{staging_dir}/market_data.json` — fresh prices and technicals
- `{staging_dir}/news_data.json` — any new headlines
- `{staging_dir}/market_context.json` — current market regime

### Step 2: Compare with morning research
- `{data_root_display}/cache/morning_research.json` — this morning's analysis
- `{data_root_display}/cache/watchlist.json` — the morning watchlist

### Step 3: Check for changes and do live research
Look at what moved. Any stock hit entry/stop/target levels from morning research?
You have internet access — use curl to check for breaking news if something looks off:
- `curl -s "https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL?interval=5m&range=1d"` for intraday price action
Keep it to 1 targeted fetch max — this is a quick check.

### Step 4: Output JSON
Output ONLY valid JSON:

```json
{{
    "overall_sentiment": "bullish|bearish|neutral",
    "market_summary": "what changed since morning",
    "market_regime": "risk_on|risk_off|neutral",
    "stocks": {{
        "<SYMBOL>": {{
            "sentiment": "bullish|bearish|neutral",
            "confidence": 0.0-1.0,
            "key_observations": ["what changed"],
            "news_impact": "positive|negative|neutral|none",
            "news_summary": "any new news",
            "recommendation": "buy|sell|hold|watch",
            "trade_plan": {{
                "entry": 0.00,
                "stop_loss": 0.00,
                "target": 0.00,
                "risk_reward_ratio": 0.0,
                "position_size_pct": 0.0,
                "timeframe": "intraday|swing_2_5_days|swing_1_2_weeks"
            }},
            "changed_since_morning": true|false,
            "change_summary": "what specifically changed"
        }}
    }}
}}
```

IMPORTANT: Output ONLY the JSON object, nothing else.
"""


def _build_research_task_prompt(symbols: list[str], *, data_root: Path) -> str:
    staging_dir = get_staging_dir(str(data_root)).as_posix()
    data_root_display = data_root.as_posix()
    return f"""You are an expert stock market analyst running inside the agent-trader repository.

## YOUR TASK
Analyze today's shortlisted stocks and produce trading recommendations.
You are CONSERVATIVE - only recommend trades with clear setups and defined risk.
You manage a $100,000 paper portfolio. Every dollar counts.

## STRATEGIST MEMORY ROOT
All of your saved artifacts for this strategist are stored under `{data_root_display}`.
Use this root when checking prior journals, trades, research, cache, and staging files.

## TODAY'S STOCKS
{', '.join(symbols)}

## HOW TO WORK

### Step 1: Read today's data
All current market data is in `{staging_dir}`:
- market_data.json - prices, RSI, MACD, Bollinger Bands, SMAs per stock
- news_data.json - per-stock headlines, sentiment, analyst recs
- market_context.json - VIX, S&P trend, yields, sector rotation
- market_headlines.json - broad market news
- screener_results.json - why these stocks were selected (if exists)
- news_discoveries.json - stocks discovered via news (if exists)
- hot_stocks.json - cross-source hot stocks (if exists)
- finviz_data.json - analyst changes (if exists)
- performance_feedback.md - your past trade outcomes and win rate
- learned_rules.md - trading rules you've discovered from past performance
- artifact_context.md - summaries of recent research runs

### Step 2: Explore historical context (IMPORTANT - this is your edge)
Look at past data to find patterns:
- `{data_root_display}/journal/` - past trading journal entries (markdown + JSON). Check if any of today's stocks appeared recently and what happened.
- `{data_root_display}/feedback/completed_trades.json` - full trade history with P&L. Look for patterns with today's stocks.
- `{data_root_display}/feedback/learned_rules.json` - rules you generated from past reviews.
- `{data_root_display}/research/` - past research outputs. Check if your previous analysis on these stocks was accurate.

Spend time here. This historical context is what makes your analysis better than a single API call.

### Step 3: Mandatory live verification (you have internet access)
You MUST do targeted live research before finalizing the answer.
Use WebSearch / WebFetch when possible, or Bash with curl / python when needed.

Examples:
- Get real-time quote: `curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d"`
- Get recent news: `curl -s "https://query1.finance.yahoo.com/v1/finance/search?q=AAPL&newsCount=5"`
- Get earnings date: `curl -s "https://query1.finance.yahoo.com/v10/finance/quoteSummary/AAPL?modules=calendarEvents"`
- Use WebSearch for breaking developments, filings, or major financial press coverage
- Use WebFetch on the most relevant source URLs you find

Required scope:
1. Verify at least 2 symbols with live web research
2. One verified symbol MUST end up in `best_opportunities`
3. Prioritize the highest-impact names:
   - symbols with the strongest move or heaviest news flow in staging
   - the most expensive or largest-cap names
   - any symbol where the staged narrative looks stale or incomplete

What to verify:
1. Breaking news that might not be captured in the staging data
2. Key price / earnings / filing context
3. Whether the narrative behind the move is confirmed by a reputable current source

Do NOT get stuck in a loop - keep it tight and targeted.
Use 1-3 focused web checks total, then move on.

### Step 4: Produce your analysis
Output ONLY valid JSON (no markdown, no explanation outside JSON) in this exact format:

```json
{{
    "overall_sentiment": "bullish|bearish|neutral",
    "market_summary": "2-3 sentence market overview",
    "market_regime": "risk_on|risk_off|neutral",
    "best_opportunities": ["SYMBOL1", "SYMBOL2"],
    "stocks": {{
        "<SYMBOL>": {{
            "sentiment": "bullish|bearish|neutral",
            "confidence": 0.0-1.0,
            "key_observations": ["observation with specific numbers"],
            "news_impact": "positive|negative|neutral|none",
            "news_summary": "1 sentence on relevant news",
            "technical_setup": "1-2 sentence technical summary",
            "recommendation": "buy|sell|hold|watch",
            "trade_plan": {{
                "entry": 0.00,
                "stop_loss": 0.00,
                "target": 0.00,
                "risk_reward_ratio": 0.0,
                "position_size_pct": 0.0,
                "timeframe": "intraday|swing_2_5_days|swing_1_2_weeks"
            }},
            "catalysts": ["what could drive this"],
            "risks": ["what could go wrong"],
            "earnings_warning": false,
            "historical_context": "what you found in past journals/trades about this stock",
            "supporting_articles": [
                {{
                    "title": "source headline or filing",
                    "url": "https://...",
                    "source": "publisher / website",
                    "kind": "news|filing|analyst|web",
                    "reason": "why this source matters to the trade"
                }}
            ]
        }}
    }},
    "self_reflection": "1-2 sentences on your confidence calibration based on past performance",
    "web_checks": [
        {{
            "symbol": "SYMBOL",
            "query": "what you searched or fetched",
            "source": "publisher / site",
            "url": "https://...",
            "finding": "what changed or what was confirmed"
        }}
    ]
}}
```

IMPORTANT:
- Output ONLY the JSON object, nothing else
- Every stock in today's list must appear in "stocks"
- Use specific numbers from the data (actual RSI values, actual price levels)
- Reference historical patterns you found in the journal/feedback data
- Be honest about confidence - if past trades on a stock went badly, lower your confidence
- Include real source URLs for anything you validated on the open web
"""


def _build_monitor_task_prompt(symbols: list[str], *, data_root: Path) -> str:
    staging_dir = get_staging_dir(str(data_root)).as_posix()
    data_root_display = data_root.as_posix()
    return f"""You are an expert stock market analyst running inside the agent-trader repository.

## YOUR TASK
Quick monitoring check on the watchlist. What changed since morning research?
Focus on: price moves, new news, signals that changed.

## STRATEGIST MEMORY ROOT
All of your saved artifacts for this strategist are stored under `{data_root_display}`.
Use this root when checking prior journals, trades, research, cache, and staging files.

## WATCHLIST
{', '.join(symbols)}

## HOW TO WORK

### Step 1: Read current data
- `{staging_dir}/market_data.json` - fresh prices and technicals
- `{staging_dir}/news_data.json` - any new headlines
- `{staging_dir}/market_context.json` - current market regime

### Step 2: Compare with morning research
- `{data_root_display}/cache/morning_research.json` - this morning's analysis
- `{data_root_display}/cache/watchlist.json` - the morning watchlist

### Step 3: Check for changes and do mandatory live verification
Look at what moved. Any stock hit entry/stop/target levels from morning research?
You have internet access - use WebSearch / WebFetch or curl to check for breaking news if something looks off:
- `curl -s "https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL?interval=5m&range=1d"` for intraday price action

You MUST verify at least 1 symbol with a live source if:
- price action sharply diverged from the morning thesis
- a symbol is close to trade entry / stop / target
- there is meaningful fresh headline risk

Keep it tight - 1-2 focused checks max.

### Step 4: Output JSON
Output ONLY valid JSON:

```json
{{
    "overall_sentiment": "bullish|bearish|neutral",
    "market_summary": "what changed since morning",
    "market_regime": "risk_on|risk_off|neutral",
    "stocks": {{
        "<SYMBOL>": {{
            "sentiment": "bullish|bearish|neutral",
            "confidence": 0.0-1.0,
            "key_observations": ["what changed"],
            "news_impact": "positive|negative|neutral|none",
            "news_summary": "any new news",
            "recommendation": "buy|sell|hold|watch",
            "trade_plan": {{
                "entry": 0.00,
                "stop_loss": 0.00,
                "target": 0.00,
                "risk_reward_ratio": 0.0,
                "position_size_pct": 0.0,
                "timeframe": "intraday|swing_2_5_days|swing_1_2_weeks"
            }},
            "changed_since_morning": true|false,
            "change_summary": "what specifically changed",
            "supporting_articles": [
                {{
                    "title": "source headline or filing",
                    "url": "https://...",
                    "source": "publisher / website",
                    "kind": "news|filing|analyst|web",
                    "reason": "why this source matters to the update"
                }}
            ]
        }}
    }},
    "web_checks": [
        {{
            "symbol": "SYMBOL",
            "query": "what you searched or fetched",
            "source": "publisher / site",
            "url": "https://...",
            "finding": "what changed or what was confirmed"
        }}
    ]
}}
```

IMPORTANT:
- Output ONLY the JSON object, nothing else
- Include real source URLs for any live checks you used
"""


def _extract_cli_usage(outer: dict[str, Any]) -> dict[str, Any]:
    usage = outer.get("usage")
    if isinstance(usage, dict):
        extracted = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "server_tool_use": usage.get("server_tool_use"),
            "service_tier": usage.get("service_tier"),
        }
        return {key: value for key, value in extracted.items() if value is not None}

    extracted = {
        "input_tokens": outer.get("input_tokens"),
        "output_tokens": outer.get("output_tokens"),
    }
    return {key: value for key, value in extracted.items() if value is not None}


def _parse_jsonl_events(raw_output: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _build_cli_meta(
    *,
    outer: dict[str, Any] | None,
    provider: str,
    model: str | None,
    duration_ms: float,
    status: str,
    error: str | None = None,
    stderr: str = "",
) -> dict[str, Any]:
    usage = _extract_cli_usage(outer or {})
    meta = {
        "status": status,
        "provider": f"cli:{provider}",
        "model": (outer or {}).get("model") or model or "default",
        "duration_ms": duration_ms,
        "session_id": (outer or {}).get("session_id"),
        "cost_usd": (outer or {}).get("cost_usd", (outer or {}).get("total_cost_usd")),
        "num_turns": (outer or {}).get("num_turns"),
        "usage": usage,
    }

    if error:
        meta["error"] = error
    if stderr:
        meta["stderr"] = stderr

    return meta


def _parse_cli_result_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def _extract_codex_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        usage = event.get("usage")
        if isinstance(usage, dict):
            return usage
    return {}


def _extract_codex_session_id(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _extract_codex_error(raw_output: str, stderr: str, returncode: int) -> str:
    events = _parse_jsonl_events(raw_output)
    for event in reversed(events):
        for key in ("error", "message", "last_agent_message", "lastAgentMessage", "result"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if event.get("type") == "error" and isinstance(event.get("data"), dict):
            data = event["data"]
            if isinstance(data.get("message"), str) and data["message"].strip():
                return data["message"].strip()
    if stderr.strip():
        return stderr.strip()[:1000]
    return f"CLI exited with code {returncode}"


def _extract_codex_message(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        for key in ("last_agent_message", "lastAgentMessage", "message", "result"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if event.get("type") == "agent_message" and isinstance(event.get("message"), str):
            message = event["message"].strip()
            if message:
                return message
    return ""


def _run_claude_cli_agent(
    cmd: list[str],
    *,
    provider: str,
    model: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = perf_counter()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            cwd=str(Path.cwd()),
        )

        duration_ms = round((perf_counter() - started) * 1000, 1)
        raw_output = result.stdout.strip()
        outer: dict[str, Any] | None = None

        if raw_output:
            try:
                parsed = json.loads(raw_output)
                if isinstance(parsed, dict):
                    outer = parsed
            except json.JSONDecodeError:
                outer = None

        if result.returncode != 0:
            error_message = f"CLI exited with code {result.returncode}"
            if outer and outer.get("result"):
                error_message = str(outer["result"]).strip() or error_message
            logger.warning(
                "CLI agent exited with code %d: %s",
                result.returncode,
                error_message,
            )
            return {
                "_meta": _build_cli_meta(
                    outer=outer,
                    provider=provider,
                    model=model,
                    duration_ms=duration_ms,
                    status="error",
                    error=error_message,
                    stderr=result.stderr[:1000] if result.stderr else "",
                ),
                **({"raw_output": raw_output[:2000]} if raw_output else {}),
            }

        if not raw_output:
            return {
                "_meta": {
                    "status": "error",
                    "error": "CLI produced no output",
                    "duration_ms": duration_ms,
                    "provider": f"cli:{provider}",
                },
            }

        if outer is None:
            outer = json.loads(raw_output)

        if outer.get("is_error"):
            error_message = str(outer.get("result") or "CLI returned an error").strip()
            return {
                "_meta": _build_cli_meta(
                    outer=outer,
                    provider=provider,
                    model=model,
                    duration_ms=duration_ms,
                    status="error",
                    error=error_message,
                    stderr=result.stderr[:1000] if result.stderr else "",
                ),
                "raw_output": raw_output[:2000],
            }

        inner_text = outer.get("result", raw_output)
        if isinstance(inner_text, str):
            analysis = _parse_cli_result_text(inner_text)
        else:
            analysis = inner_text

        analysis.setdefault("_meta", {})
        analysis["_meta"].update(
            _build_cli_meta(
                outer=outer,
                provider=provider,
                model=model,
                duration_ms=duration_ms,
                status="success",
            )
        )

        logger.info(
            "CLI agent completed in %.1fs (%d turns, $%.4f)",
            duration_ms / 1000,
            outer.get("num_turns", 0),
            outer.get("cost_usd", outer.get("total_cost_usd", 0)) or 0,
        )

        return analysis

    except subprocess.TimeoutExpired:
        duration_ms = round((perf_counter() - started) * 1000, 1)
        logger.warning("CLI agent timed out after %ds", timeout_seconds)
        return {
            "_meta": {
                "status": "error",
                "error": f"CLI timed out after {timeout_seconds}s",
                "duration_ms": duration_ms,
                "provider": f"cli:{provider}",
            },
        }
    except json.JSONDecodeError as exc:
        duration_ms = round((perf_counter() - started) * 1000, 1)
        logger.warning("CLI agent output not valid JSON: %s", exc)
        return {
            "_meta": {
                "status": "error",
                "error": f"Could not parse CLI output as JSON: {exc}",
                "duration_ms": duration_ms,
                "provider": f"cli:{provider}",
            },
            "raw_output": result.stdout[:2000] if result.stdout else "",
        }
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000, 1)
        logger.warning("CLI agent error: %s", exc)
        return {
            "_meta": {
                "status": "error",
                "error": str(exc),
                "duration_ms": duration_ms,
                "provider": f"cli:{provider}",
            },
        }


def _run_codex_cli_agent(
    task: str,
    *,
    binary: str,
    provider: str,
    model: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = perf_counter()

    with tempfile.TemporaryDirectory(prefix="codex-cli-") as temp_dir:
        temp_root = Path(temp_dir)
        output_path = temp_root / "result.json"

        cmd = [
            binary,
            "exec",
            "-",
            "--skip-git-repo-check",
            "--full-auto",
            "-s",
            "danger-full-access",
            "--json",
            "-o",
            str(output_path),
        ]
        if model:
            cmd.extend(["-m", model])

        try:
            result = subprocess.run(
                cmd,
                input=task,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                cwd=str(Path.cwd()),
            )
            duration_ms = round((perf_counter() - started) * 1000, 1)
            raw_output = result.stdout.strip()
            events = _parse_jsonl_events(raw_output)

            if result.returncode != 0:
                error_message = _extract_codex_error(raw_output, result.stderr, result.returncode)
                logger.warning("Codex CLI exited with code %d: %s", result.returncode, error_message)
                return {
                    "_meta": {
                        "status": "error",
                        "provider": f"cli:{provider}",
                        "model": model or "default",
                        "duration_ms": duration_ms,
                        "session_id": _extract_codex_session_id(events),
                        "usage": _extract_codex_usage(events),
                        "error": error_message,
                        "stderr": result.stderr[:1000] if result.stderr else "",
                    },
                    **({"raw_output": raw_output[:2000]} if raw_output else {}),
                }

            message_text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            if not message_text:
                message_text = _extract_codex_message(events)

            if not message_text:
                return {
                    "_meta": {
                        "status": "error",
                        "provider": f"cli:{provider}",
                        "model": model or "default",
                        "duration_ms": duration_ms,
                        "usage": _extract_codex_usage(events),
                        "error": "Codex CLI finished without returning a final message",
                    },
                    **({"raw_output": raw_output[:2000]} if raw_output else {}),
                }

            analysis = _parse_cli_result_text(message_text)
            analysis.setdefault("_meta", {})
            analysis["_meta"].update(
                {
                    "status": "success",
                    "provider": f"cli:{provider}",
                    "model": model or "default",
                    "duration_ms": duration_ms,
                    "session_id": _extract_codex_session_id(events),
                    "usage": _extract_codex_usage(events),
                }
            )
            return analysis
        except subprocess.TimeoutExpired:
            duration_ms = round((perf_counter() - started) * 1000, 1)
            logger.warning("CLI agent timed out after %ds", timeout_seconds)
            return {
                "_meta": {
                    "status": "error",
                    "error": f"CLI timed out after {timeout_seconds}s",
                    "duration_ms": duration_ms,
                    "provider": f"cli:{provider}",
                },
            }
        except json.JSONDecodeError as exc:
            duration_ms = round((perf_counter() - started) * 1000, 1)
            logger.warning("Codex CLI output not valid JSON: %s", exc)
            return {
                "_meta": {
                    "status": "error",
                    "provider": f"cli:{provider}",
                    "model": model or "default",
                    "duration_ms": duration_ms,
                    "error": f"Could not parse CLI output as JSON: {exc}",
                },
                "raw_output": output_path.read_text(encoding="utf-8")[:2000] if output_path.exists() else "",
            }
        except Exception as exc:
            duration_ms = round((perf_counter() - started) * 1000, 1)
            logger.warning("CLI agent error: %s", exc)
            return {
                "_meta": {
                    "status": "error",
                    "error": str(exc),
                    "duration_ms": duration_ms,
                    "provider": f"cli:{provider}",
                },
            }


def run_cli_agent(
    task: str,
    *,
    provider: str = "claude",
    max_turns: int = 5,
    model: str | None = None,
    timeout_seconds: int = 300,
    allowed_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Run a CLI agent and return its parsed JSON output.

    Args:
        task: The task prompt to send to the agent.
        provider: CLI binary name ("claude" or "codex").
        max_turns: Maximum agent iterations.
        model: Model override (e.g., "claude-sonnet-4-6").
        timeout_seconds: Max wall-clock time.
        allowed_tools: Restrict which tools the agent can use.

    Returns:
        Parsed JSON dict from the agent, or error dict on failure.
    """
    binary = resolve_cli_binary(provider)
    if not binary:
        return {
            "_meta": {"status": "error", "error": f"{provider} CLI not found on PATH"},
        }

    if provider == "codex":
        logger.info("Running CLI agent: %s (model=%s)", provider, model or "default")
        return _run_codex_cli_agent(
            task,
            binary=binary,
            provider=provider,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    cmd = [binary, "-p", task, "--output-format", "json"]

    if max_turns:
        cmd.extend(["--max-turns", str(max_turns)])
    if model:
        cmd.extend(["--model", model])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    logger.info("Running CLI agent: %s (max_turns=%d, model=%s)", provider, max_turns, model or "default")
    return _run_claude_cli_agent(
        cmd,
        provider=provider,
        model=model,
        timeout_seconds=timeout_seconds,
    )
