# Weekly Review — Claude Code Local Workflow

You are conducting the weekly trading review for the agent-trader system. This consolidates the week's daily observations into patterns, strategy adjustments, and knowledge base updates.

## Step 1: Read the Week's Data

Read these files:

1. `data/profiles/codex/observations/daily/` — all daily observations from this week
2. `data/profiles/codex/journal/` — journal entries from each trading day this week
3. `data/profiles/codex/portfolio_state.json` — current positions
4. `data/profiles/codex/snapshots/history.json` — portfolio value history
5. `data/profiles/codex/knowledge/` — current knowledge base (all files)
6. `data/profiles/codex/IMPROVEMENT_PROPOSALS.md` — pending improvement ideas

## Step 2: Web Research — Week in Review

Search for:
1. **"stock market week in review"** — how did the market perform this week?
2. **"sector performance this week"** — which sectors led/lagged?
3. **"VIX trend this week"** — volatility environment change?
4. **"market outlook next week"** — what catalysts are ahead?

## Step 3: Analyze Performance

Think through:
1. **Win rate this week**: How many trades won vs lost?
2. **Best/worst trades**: What made the best ones work? What went wrong on the worst?
3. **Strategy effectiveness**: Which strategies (momentum, mean reversion, etc.) worked this week?
4. **Regime accuracy**: Was our regime call correct each day?
5. **Confidence calibration**: Are we over/under-confident?
6. **Missed opportunities**: What did we miss and why?

## Step 4: Write Weekly Observation

Write to `data/profiles/codex/observations/weekly/week_YYYY-MM-DD.json`:

```json
{
    "week_ending": "YYYY-MM-DD",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "2-3 sentences summarizing the week",
    "performance": {
        "trades_taken": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl_pct": 0.0,
        "best_trade": {"symbol": "", "pnl_pct": 0, "strategy": ""},
        "worst_trade": {"symbol": "", "pnl_pct": 0, "lesson": ""}
    },
    "strategy_grades": {
        "momentum": {"grade": "A|B|C|D|F", "notes": ""},
        "mean_reversion": {"grade": "", "notes": ""},
        "trend": {"grade": "", "notes": ""},
        "news_catalyst": {"grade": "", "notes": ""}
    },
    "patterns_confirmed": [
        {"name": "pattern_name", "occurrences": 0, "win_rate": 0.0}
    ],
    "new_rules": [
        "Concrete trading rule derived from this week's experience"
    ],
    "regime_forecast": "What to expect next week",
    "focus_areas": ["What to focus on next week"]
}
```

## Step 5: Update Knowledge Base

Based on your analysis:

1. **Update `knowledge/patterns_library.json`** — add new patterns, update win rates for existing ones
2. **Update `knowledge/lessons_learned.json`** — add new lessons (max 50, remove weakest if needed)
3. **Update `knowledge/strategy_effectiveness.json`** — update strategy win rates by regime
4. **Update `knowledge/regime_library.json`** — refine regime rules if needed

## Step 6: Commit and Push

```bash
git add data/profiles/codex/observations/weekly/ data/profiles/codex/knowledge/
git commit -m "[local-weekly] week ending $(date +%Y-%m-%d) review"
git push origin main
```
