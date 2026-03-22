# Evening Reflection — Claude Code Local Workflow

You are reviewing today's trading session for the agent-trader system. Your job is to extract lessons, update patterns, and generate self-improvement proposals.

## Step 1: Read Today's Activity

Read these files:

1. `data/profiles/codex/journal/$(date +%Y-%m-%d)/` — all journal entries from today
2. `data/profiles/codex/portfolio_state.json` — current positions after today's trades
3. `data/profiles/codex/snapshots/latest.json` — end-of-day portfolio value
4. `data/cache/morning_research.json` — what we planned this morning
5. `data/profiles/codex/observations/daily/` — last 3 observations for continuity
6. `data/profiles/codex/knowledge/lessons_learned.json` — current lessons

## Step 2: Analyze the Day

Think through:
1. **What trades executed today?** Were they good entries? Did the thesis play out?
2. **What did we plan vs what happened?** Any morning picks that moved but we missed?
3. **Confidence calibration**: Were high-confidence calls actually better than low?
4. **Patterns**: Any recurring setups you noticed (gap-and-go, reversal at support, etc.)?
5. **Market regime**: Was the regime assessment correct? How did it affect trades?
6. **What would you do differently?** Be specific.

## Step 3: Write Daily Observation

Write to `data/profiles/codex/observations/daily/obs_$(date +%Y-%m-%d).json`:

```json
{
    "date": "2026-03-22",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "1-2 sentences about today's market",
    "sector_leaders": ["Tech", "Energy"],
    "sector_laggards": ["Utilities"],
    "trades_review": [
        {
            "symbol": "NVDA",
            "action": "buy",
            "pnl_pct": 2.1,
            "assessment": "Good entry, thesis confirmed by volume"
        }
    ],
    "patterns_detected": [
        {
            "name": "gap_and_go",
            "symbol": "TSLA",
            "outcome": "won",
            "notes": "3% gap held, ran to target by 11am"
        }
    ],
    "confidence_calibration": {
        "high_conf_actual": 0.80,
        "medium_conf_actual": 0.55,
        "assessment": "Slightly over-confident on medium calls"
    },
    "forward_outlook": "Watch for FOMC minutes tomorrow, may shift regime",
    "lessons": [
        "Gap-and-go works best in first 90 minutes of risk-on days",
        "Mean reversion after 3%+ gap is risky in trending markets"
    ]
}
```

## Step 4: Generate Improvement Proposals

Think about what would make the system better. Write proposals for:
- **data_source**: Need more/different data?
- **strategy**: New trading approaches to try?
- **risk_management**: Position sizing adjustments?
- **infrastructure**: System improvements?

Write to `data/profiles/codex/IMPROVEMENT_PROPOSALS.md` (append new section at top):

```markdown
## 2026-03-22 — Evening Reflection Proposals

### [HIGH] [strategy] Add gap-fade strategy for overextended opens
Large gap-ups (>3%) in risk-off regimes tend to fade. We should track this pattern.
**Expected impact:** Capture 2-3% moves on gap fades with 70%+ historical win rate.

### [MED] [data_source] Add options flow data
Unusual options activity often precedes moves by 1-2 days.
**Expected impact:** Better timing on entries for swing trades.
```

Also write structured JSON to `data/profiles/codex/improvement_proposals.json` (append to existing array).

## Step 5: Update Knowledge Base

If you identified new patterns or lessons:

1. **Update lessons**: Read `data/profiles/codex/knowledge/lessons_learned.json`, add new lessons, keep max 50, dedup.
2. **Update patterns**: Read `data/profiles/codex/knowledge/patterns_library.json`, add/update patterns with win rates.

## Step 6: Commit and Push

```bash
git add data/profiles/codex/observations/ data/profiles/codex/knowledge/ data/profiles/codex/IMPROVEMENT_PROPOSALS.md data/profiles/codex/improvement_proposals.json
git commit -m "[local-reflection] $(date +%Y-%m-%d) evening reflection"
git push origin main
```
