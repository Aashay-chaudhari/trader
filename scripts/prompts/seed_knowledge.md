# Seed Knowledge — First Run Bootstrap

You are bootstrapping the agent-trader knowledge base for its very first day.
Your job is to **research**, **think**, and **learn** — then populate structured
files that both strategist profiles (claude and codex) will read on every future run.

> This is a one-time, token-intensive session. Take your time.

---

## Step 1 — Create directory structure

Run this once to ensure every path exists:

```bash
for PROFILE in claude codex; do
  for DIR in knowledge observations/daily observations/weekly observations/monthly positions/active positions/closed; do
    mkdir -p "data/profiles/$PROFILE/$DIR"
  done
done
```

---

## Step 2 — Deep web research (SPEND TIME HERE)

Search broadly. The goal is to form an **informed, current opinion** on
the market — not to copy-paste headlines. Synthesize what you find.

**Macro & regime** (at least 3 searches):
- Current S&P 500 level, YTD performance, trend direction
- VIX level and recent trajectory (is fear rising or falling?)
- Fed policy: current rate, next meeting date, market expectations for cuts/hikes
- Major geopolitical or macro risks affecting markets RIGHT NOW
- Bond yields (10Y), dollar strength, oil price — cross-asset context

**What's working** (at least 3 searches):
- Which trading strategies are performing well in the current environment?
- Which sectors are leading and why? Which are lagging and why?
- What patterns are professional traders talking about? (e.g., mean reversion in high VIX, momentum in low VIX)
- Are there any well-known setups that are specifically failing right now?

**Historical lessons** (at least 2 searches):
- Common mistakes retail/algo traders make in the current type of market
- Position sizing and risk management best practices for the current volatility level
- What happened the last time the market was in a similar regime?

After each search, write a few sentences of synthesis — what did you learn?
Build a mental model of the current environment before writing any files.

---

## Step 3 — Write knowledge files

Write IDENTICAL content to both profiles. For each file below, write to:
- `data/profiles/claude/knowledge/<filename>`
- `data/profiles/codex/knowledge/<filename>`

### 3a. `lessons_learned.json`

An array of 15–25 string lessons. Each lesson should be:
- Actionable (not vague platitudes)
- Grounded in your research (reference the current environment where relevant)
- A mix of timeless wisdom and regime-specific guidance

**Schema** (strict):
```json
[
    "Lesson string 1 — specific and actionable",
    "Lesson string 2 — grounded in current market context"
]
```

Do NOT hardcode generic filler. Every lesson should pass the test:
"Would a trader reading this today change their behavior?"

### 3b. `regime_library.json`

Three regime profiles. For each, include:
- A description grounded in current numbers (e.g., "VIX was 26.78 on seed date")
- Concrete indicators for detection
- 5–7 actionable rules per regime

**Schema** (strict):
```json
{
    "risk_on": {
        "description": "string — what does risk-on look like right now?",
        "indicators": ["VIX < 18", "S&P above 20-day SMA", "..."],
        "rules": [
            "Actionable rule 1",
            "Actionable rule 2"
        ]
    },
    "risk_off": {
        "description": "string",
        "indicators": ["..."],
        "rules": ["..."]
    },
    "neutral": {
        "description": "string",
        "indicators": ["..."],
        "rules": ["..."]
    }
}
```

### 3c. `strategy_effectiveness.json`

Baseline expected performance for each strategy in each regime.
Use your research to estimate realistic win rates. Mark `sample_size: 0`
since we have no live data yet. Add a `notes` field explaining your reasoning.

**Schema** (strict):
```json
{
    "last_updated": "YYYY-MM-DD-seed",
    "by_regime": {
        "risk_on": {
            "momentum":         {"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "mean_reversion":   {"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "trend":            {"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "volume_breakout":  {"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "support_resistance":{"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "vwap":             {"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "relative_strength":{"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"},
            "news_catalyst":    {"win_rate": 0.00, "avg_pnl": 0.0, "sample_size": 0, "notes": "reasoning"}
        },
        "risk_off": { "...same 8 strategies..." },
        "neutral":  { "...same 8 strategies..." }
    }
}
```

Include ALL 8 strategies in ALL 3 regimes (even if estimated win rate is low).
The system's 8 strategies are: `momentum`, `mean_reversion`, `trend`,
`volume_breakout`, `support_resistance`, `vwap`, `relative_strength`, `news_catalyst`.

### 3d. `patterns_library.json`

Start with 3–5 patterns you found from research that are relevant to the
CURRENT market environment. Don't leave this empty — give the agent something
to watch for from day 1.

**Schema** (strict):
```json
[
    {
        "name": "snake_case_name",
        "description": "What this pattern looks like and when it fires",
        "regime": "risk_on|risk_off|neutral|any",
        "win_rate": 0.00,
        "avg_pnl": 0.0,
        "occurrences": 0,
        "sample_size": 0,
        "symbols_seen": [],
        "notes": "Why this is relevant right now based on your research"
    }
]
```

---

## Step 4 — Write genesis observations

Write to BOTH profiles (`claude` and `codex`). Use the SAME content.

### 4a. Daily observation

File: `data/profiles/<PROFILE>/observations/daily/obs_YYYY-MM-DD.json`

(Use today's date.)

**Schema** (strict):
```json
{
    "date": "YYYY-MM-DD",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "2-3 sentences from your research about today's market",
    "sector_leaders": ["Sector1", "Sector2"],
    "sector_laggards": ["Sector1", "Sector2"],
    "key_drivers": [
        "1-sentence driver from research",
        "Another driver"
    ],
    "trades_review": [],
    "patterns_detected": [],
    "confidence_calibration": {
        "assessment": "Day 1 — no calibration data yet"
    },
    "forward_outlook": "What to watch for tomorrow/next week from your research",
    "lessons": [
        "Day 1 lesson derived from your research"
    ]
}
```

### 4b. Weekly observation

File: `data/profiles/<PROFILE>/observations/weekly/week_YYYY-MM-DD.json`

**Schema** (strict):
```json
{
    "week_ending": "YYYY-MM-DD",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "3-4 sentences. Synthesize what happened this week from your research.",
    "performance": {
        "trades_taken": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl_pct": 0.0,
        "best_trade": {"symbol": "N/A", "pnl_pct": 0, "strategy": "seed — no trades yet"},
        "worst_trade": {"symbol": "N/A", "pnl_pct": 0, "lesson": "seed — no trades yet"}
    },
    "strategy_grades": {
        "momentum": {"grade": "N/A", "notes": "Your assessment of how this strategy would have done this week"},
        "mean_reversion": {"grade": "N/A", "notes": ""},
        "trend": {"grade": "N/A", "notes": ""},
        "volume_breakout": {"grade": "N/A", "notes": ""},
        "support_resistance": {"grade": "N/A", "notes": ""},
        "vwap": {"grade": "N/A", "notes": ""},
        "relative_strength": {"grade": "N/A", "notes": ""},
        "news_catalyst": {"grade": "N/A", "notes": ""}
    },
    "patterns_confirmed": [],
    "new_rules": [
        "Rules derived from this week's market behavior"
    ],
    "regime_forecast": "What you expect next week based on research",
    "focus_areas": ["Specific things to focus on"]
}
```

### 4c. Monthly observation

File: `data/profiles/<PROFILE>/observations/monthly/month_YYYY-MM.json`

**Schema** (strict):
```json
{
    "month": "YYYY-MM",
    "market_summary": "4-5 sentences. Comprehensive month review from your research.",
    "performance": {
        "starting_value": 100000,
        "ending_value": 100000,
        "return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "total_trades": 0,
        "win_rate": 0.0,
        "avg_win_pct": 0.0,
        "avg_loss_pct": 0.0,
        "profit_factor": 0.0,
        "note": "System seed — no live trades yet"
    },
    "strategy_rankings": [
        {
            "strategy": "strategy_name",
            "pnl_contribution": 0.0,
            "win_rate": 0.0,
            "grade": "N/A",
            "notes": "Assessment based on market conditions"
        }
    ],
    "top_lessons": [
        "Top 5 lessons from this month's market, from your research"
    ],
    "regime_accuracy": {
        "correct_calls": 0,
        "total_calls": 0,
        "accuracy": 0.0,
        "notes": "Seed run"
    },
    "next_month_plan": {
        "regime_expectation": "risk_on|risk_off|neutral",
        "strategy_focus": ["Which strategies to emphasize based on research"],
        "risk_adjustments": ["Position sizing or stop-loss adjustments"],
        "watchlist_themes": ["Sectors, themes, or specific names to watch"]
    }
}
```

---

## Step 5 — Commit and push

```bash
git add data/profiles/claude/knowledge/ data/profiles/claude/observations/ \
        data/profiles/codex/knowledge/ data/profiles/codex/observations/
git commit -m "[seed] $(date +%Y-%m-%d) knowledge base bootstrap from market research"
git push origin main
```

---

## Quality checklist

Before committing, verify:
- [ ] All 4 knowledge files exist in BOTH `data/profiles/claude/knowledge/` AND `data/profiles/codex/knowledge/`
- [ ] All 3 observation files exist in BOTH profiles
- [ ] Every JSON file is valid (no trailing commas, no comments)
- [ ] Lessons are specific to the current market, not generic platitudes
- [ ] Regime library references actual current numbers (VIX level, S&P level, Fed rate)
- [ ] Strategy effectiveness covers ALL 8 strategies in ALL 3 regimes
- [ ] Patterns library has at least 3 patterns relevant to the current market
- [ ] Weekly/monthly observations include a forward outlook grounded in research
