# Weekly Review — Claude Code Local Workflow

You are conducting the weekly trading review. Your job is to **consolidate
the week's observations**, **research the week in review**, and **update the
knowledge base** so the system performs better next week.

Write to BOTH profiles (`claude` and `codex`) — same content.

> This is where patterns emerge. Take time to find the signal in the noise.

---

## Step 1 — Read the week's data

**For each profile** (`codex`, then `claude`):
1. `data/profiles/<PROFILE>/observations/daily/` — all daily observations this week
2. `data/profiles/<PROFILE>/journal/` — journal entries from each trading day
3. `data/profiles/<PROFILE>/portfolio_state.json` — current positions
4. `data/profiles/<PROFILE>/snapshots/history.json` — portfolio value history
5. `data/profiles/<PROFILE>/knowledge/` — all 4 knowledge files
6. `data/profiles/<PROFILE>/IMPROVEMENT_PROPOSALS.md` — pending proposals

---

## Step 2 — Web research: the week in review

**Search for** (at least 4 searches):
- "stock market week in review" — how did the market perform?
- "S&P 500 weekly performance sectors" — which sectors led/lagged?
- "VIX weekly trend" — how did volatility evolve?
- "market outlook next week" — upcoming catalysts, events, earnings?
- "trading strategy performance this week" — what worked for other traders?

**Synthesize**: Compare what you find with our daily observations.
Were our regime calls correct? Did the strategies we expected to work actually work?

---

## Step 3 — Deep analysis (THINK BEFORE WRITING)

1. **Win rate**: How many trades won vs lost this week? Calculate actual numbers.
2. **Strategy breakdown**: For each of our 8 strategies — did it fire? Did it win?
   Grade each: A (consistent wins), B (mostly good), C (mixed), D (mostly bad), F (avoid).
3. **Best/worst trades**: What made the best ones work? What went wrong on the worst?
   Be specific — "entry too late" is better than "bad trade."
4. **Regime accuracy**: Was our daily regime call correct each day?
5. **Pattern detection**: Do you see any setups that repeated across multiple days?
6. **Confidence calibration**: Aggregate the week's confidence data.
   High-confidence trades should win more often. Do they?
7. **Knowledge quality**: Are our lessons_learned actually helping?
   Any lesson that led us astray this week?

---

## Step 4 — Write weekly observation

File: `data/profiles/<PROFILE>/observations/weekly/week_YYYY-MM-DD.json`
(Write to BOTH profiles. Use the Sunday date or the last trading day.)

**Schema** (strict):
```json
{
    "week_ending": "YYYY-MM-DD",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "3-4 sentences synthesizing the week from research + observations",
    "performance": {
        "trades_taken": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl_pct": 0.0,
        "best_trade": {
            "symbol": "TICKER",
            "pnl_pct": 0.0,
            "strategy": "which strategy"
        },
        "worst_trade": {
            "symbol": "TICKER",
            "pnl_pct": 0.0,
            "lesson": "what we learned from this loss"
        }
    },
    "strategy_grades": {
        "momentum":          {"grade": "A|B|C|D|F|N/A", "notes": "assessment with evidence"},
        "mean_reversion":    {"grade": "", "notes": ""},
        "trend":             {"grade": "", "notes": ""},
        "volume_breakout":   {"grade": "", "notes": ""},
        "support_resistance":{"grade": "", "notes": ""},
        "vwap":              {"grade": "", "notes": ""},
        "relative_strength": {"grade": "", "notes": ""},
        "news_catalyst":     {"grade": "", "notes": ""}
    },
    "patterns_confirmed": [
        {
            "name": "snake_case_name",
            "occurrences": 0,
            "win_rate": 0.0,
            "notes": "Evidence from this week"
        }
    ],
    "new_rules": [
        "Concrete trading rule derived from this week's experience"
    ],
    "regime_forecast": "What you expect next week based on research + this week's trends",
    "focus_areas": [
        "Specific thing to focus on next week"
    ]
}
```

---

## Step 5 — Update knowledge base

Write to BOTH profiles.

### 5a. Lessons learned
Read `knowledge/lessons_learned.json`.
- Add new rules from `new_rules` above
- Remove any lesson this week DISPROVED
- Keep max 50, remove weakest if over limit
- Write back

### 5b. Patterns library
Read `knowledge/patterns_library.json`.
- Update existing patterns: increment occurrences, recalculate win rates
- Add any new patterns from `patterns_confirmed`
- Write back

### 5c. Strategy effectiveness
Read `knowledge/strategy_effectiveness.json`.
- Update `win_rate` and `sample_size` for every strategy that fired this week
- Formula: `new_rate = (old_rate * old_size + wins) / (old_size + total)`
- Update `last_updated` to today
- Write back

### 5d. Regime library
Read `knowledge/regime_library.json`.
- If this week taught us something new about a regime, update the rules
- If indicators need calibrating (e.g., VIX threshold), adjust
- Write back

---

## Step 6 — Commit and push

```bash
git add data/profiles/claude/observations/weekly/ data/profiles/claude/knowledge/ \
        data/profiles/codex/observations/weekly/ data/profiles/codex/knowledge/
git commit -m "[weekly] week ending $(date +%Y-%m-%d) review"
git push origin main
```

---

## Quality checklist

- [ ] Read ALL daily observations from this week
- [ ] Did at least 4 web searches for week-in-review context
- [ ] Strategy grades have evidence, not just letters
- [ ] Knowledge base files are UPDATED, not overwritten from scratch
- [ ] New rules are specific enough to be testable next week
- [ ] JSON is valid in both profiles
- [ ] Same content in both claude and codex profiles
