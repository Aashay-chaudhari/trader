# Monthly Retrospective — Claude Code Local Workflow

You are conducting the monthly deep retrospective for the agent-trader system. This is the highest-level review — analyzing 4 weeks of data to identify systemic patterns and make strategic adjustments.

## Step 1: Read Monthly Data

Read these files:

1. `data/profiles/codex/observations/weekly/` — all weekly reviews from this month
2. `data/profiles/codex/observations/daily/` — daily observations for broader context
3. `data/profiles/codex/snapshots/history.json` — full portfolio value curve
4. `data/profiles/codex/portfolio_state.json` — current state
5. `data/profiles/codex/knowledge/` — all knowledge files
6. `data/profiles/codex/IMPROVEMENT_PROPOSALS.md` — month's proposals

## Step 2: Web Research — Month in Review

Search for:
1. **"stock market monthly review [month] [year]"** — macro performance
2. **"market outlook next month"** — upcoming catalysts
3. **"best performing sectors [month]"** — sector trends
4. **"trading strategy performance [year]"** — what's working in current environment

## Step 3: Deep Analysis

Think through:
1. **Monthly P&L**: Total return, drawdown, Sharpe-like consistency
2. **Equity curve**: Steady growth? Spiky? Drawdown periods?
3. **Strategy meta-analysis**: Which strategies contributed most to P&L? Which destroyed value?
4. **Regime transitions**: Did we correctly identify regime changes?
5. **Knowledge quality**: Are our learned lessons actually helping? Which rules fire most?
6. **Improvement proposals**: Which proposed improvements would have the most impact?
7. **Risk management**: Were position sizes appropriate? Any near-catastrophic events?

## Step 4: Write Monthly Retrospective

Write to `data/profiles/codex/observations/monthly/month_YYYY-MM.json`:

```json
{
    "month": "YYYY-MM",
    "market_summary": "3-4 sentences about the month's market environment",
    "performance": {
        "starting_value": 100000,
        "ending_value": 100000,
        "return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "total_trades": 0,
        "win_rate": 0.0,
        "avg_win_pct": 0.0,
        "avg_loss_pct": 0.0,
        "profit_factor": 0.0
    },
    "strategy_rankings": [
        {"strategy": "momentum", "pnl_contribution": 0.0, "win_rate": 0.0, "grade": "A"},
        {"strategy": "mean_reversion", "pnl_contribution": 0.0, "win_rate": 0.0, "grade": "B"}
    ],
    "top_lessons": [
        "The most important lesson from this month",
        "Second most important",
        "Third"
    ],
    "regime_accuracy": {
        "correct_calls": 0,
        "total_calls": 0,
        "accuracy": 0.0,
        "notes": "Assessment of regime detection quality"
    },
    "next_month_plan": {
        "regime_expectation": "risk_on|risk_off|neutral",
        "strategy_focus": ["Which strategies to emphasize"],
        "risk_adjustments": ["Any position sizing or stop changes"],
        "watchlist_themes": ["Sectors or themes to focus on"]
    }
}
```

## Step 5: Update Top Lessons

Read `data/profiles/codex/knowledge/lessons_learned.json`. Rerank all lessons based on this month's experience. Keep the top 50. Remove any that proved wrong.

## Step 6: Commit and Push

```bash
git add data/profiles/codex/observations/monthly/ data/profiles/codex/knowledge/
git commit -m "[local-monthly] $(date +%Y-%m) monthly retrospective"
git push origin main
```
