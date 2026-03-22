# Evening Reflection — Claude Code Local Workflow

You are reviewing today's trading session. Your job is to **think deeply**
about what happened, **research** the market close, and **extract real lessons**
that make the system smarter tomorrow.

Write to BOTH profiles (`claude` and `codex`) — same content, same schemas.

> Take your time. This is where the system learns.

---

## Step 1 — Read today's activity

Read ALL of these. Understand the full picture before writing anything.

**For each profile** (`codex` first, then `claude`):
1. `data/profiles/<PROFILE>/journal/<TODAY>/` — every journal entry from today
2. `data/profiles/<PROFILE>/portfolio_state.json` — positions after today's trades
3. `data/profiles/<PROFILE>/snapshots/latest.json` — end-of-day portfolio
4. `data/profiles/<PROFILE>/snapshots/history.json` — portfolio value curve
5. `data/profiles/<PROFILE>/knowledge/lessons_learned.json` — current lessons
6. `data/profiles/<PROFILE>/knowledge/patterns_library.json` — known patterns
7. `data/profiles/<PROFILE>/observations/daily/` — last 3 daily observations

**Shared context:**
8. `data/cache/morning_research.json` — what we planned this morning
9. `data/cache/watchlist.json` — the stocks we were watching

If any files don't exist (early days), note what's missing and work with what's there.

---

## Step 2 — Web research: what happened today?

Don't just look at our trades — understand the MARKET context.

**Search for** (at least 4 searches):
- "stock market close today" — how did the broad market finish?
- "S&P 500 VIX close today" — where did fear/greed land?
- "top stock movers today" — what moved big and why?
- "market news after hours" — anything that changes tomorrow's thesis?
- Search for any stocks we traded or watched — what's the post-close narrative?

**Synthesize**: Form an opinion. Was today a trend day or a chop day?
Did the morning thesis play out? What surprised you?

---

## Step 3 — Think deeply (DO THIS BEFORE WRITING)

Work through these questions honestly. Don't rush to write files.

1. **Plan vs reality**: Look at `morning_research.json`. Which calls were right?
   Which were wrong? WHY were they wrong — was it the thesis, the timing,
   or the market regime?

2. **Trade quality**: For each trade that executed:
   - Was the entry good? (Did we buy near support or chase?)
   - Was the sizing appropriate for our conviction?
   - Did we respect stops or did we let losers run?
   - What was the catalyst and did it play out?

3. **Regime accuracy**: Did our morning regime call match what actually happened?
   If the market moved 2%+ in either direction, was our positioning correct?

4. **Patterns**: Did you see any setups repeat? (e.g., "every time VIX spikes above 25,
   oversold tech bounces within 2 days" — is that a pattern we should track?)

5. **Missed opportunities**: From the "top movers" search — did we miss any obvious
   setups? Could our screening have caught them?

6. **Confidence calibration**: Were our high-confidence calls (>0.7) actually better
   than low-confidence (<0.5)? Be honest.

---

## Step 4 — Write daily observation

File: `data/profiles/<PROFILE>/observations/daily/obs_YYYY-MM-DD.json`
(Write to BOTH claude and codex profiles.)

**Schema** (strict — do not add or remove fields):
```json
{
    "date": "YYYY-MM-DD",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "2-3 sentences synthesizing today's market from your research",
    "sector_leaders": ["Sector1", "Sector2"],
    "sector_laggards": ["Sector1", "Sector2"],
    "key_drivers": [
        "Major market driver from your research",
        "Another driver"
    ],
    "trades_review": [
        {
            "symbol": "TICKER",
            "action": "buy|sell",
            "entry_price": 0.00,
            "current_price": 0.00,
            "pnl_pct": 0.0,
            "strategy": "which strategy triggered this",
            "assessment": "Honest 1-sentence assessment of this trade"
        }
    ],
    "patterns_detected": [
        {
            "name": "snake_case_pattern_name",
            "symbol": "TICKER",
            "outcome": "won|lost|pending",
            "notes": "What you observed"
        }
    ],
    "confidence_calibration": {
        "high_conf_win_rate": 0.0,
        "medium_conf_win_rate": 0.0,
        "low_conf_win_rate": 0.0,
        "assessment": "Honest assessment of confidence accuracy"
    },
    "missed_opportunities": [
        {
            "symbol": "TICKER",
            "move_pct": 0.0,
            "why_missed": "Why our system didn't catch this"
        }
    ],
    "forward_outlook": "What to watch for tomorrow based on your research and today's action",
    "lessons": [
        "Specific, actionable lesson from today — not generic advice"
    ]
}
```

---

## Step 5 — Generate improvement proposals

Think about what would concretely improve the system. Be specific.

**Categories**: `data_source`, `strategy`, `risk_management`, `screening`,
`execution`, `infrastructure`, `knowledge`, `other`

**Priorities**: `high` (would have changed today's outcome), `medium` (would help
this week), `low` (nice to have)

File: `data/profiles/<PROFILE>/IMPROVEMENT_PROPOSALS.md`
(Append a new date section at the TOP of the existing file. Write to BOTH profiles.)

```markdown
## YYYY-MM-DD — Evening Reflection

### [PRIORITY] [category] Title
Description of what to improve and why, grounded in today's experience.
**Expected impact:** What would change if this were implemented.
```

Also write structured JSON to `data/profiles/<PROFILE>/improvement_proposals.json`.
If the file exists, read it, append new entries, write back.
If it doesn't exist, create it.

**Schema** for each entry in the array:
```json
{
    "date": "YYYY-MM-DD",
    "category": "strategy|data_source|risk_management|screening|execution|infrastructure|knowledge|other",
    "priority": "high|medium|low",
    "title": "Short title",
    "description": "What to improve and why",
    "expected_impact": "What would change",
    "status": "proposed"
}
```

---

## Step 6 — Update knowledge base

Based on your analysis, update the knowledge files.
Write to BOTH profiles.

### 6a. Lessons learned
Read `knowledge/lessons_learned.json`. Add new lessons from today.
Remove any lesson that today's experience CONTRADICTS.
Keep max 50 lessons. If over 50, remove the weakest/most generic.
Write back.

### 6b. Patterns library
Read `knowledge/patterns_library.json`. For each pattern you detected today:
- If it already exists: increment `occurrences`, update `win_rate`, add symbol to `symbols_seen`
- If it's new: add it with `occurrences: 1`, `sample_size: 1`
Write back.

### 6c. Strategy effectiveness
Read `knowledge/strategy_effectiveness.json`. If any strategy fired today,
update its `win_rate` and `sample_size` for the current regime.
Use the formula: `new_rate = (old_rate * old_size + outcome) / (old_size + 1)`
Write back.

---

## Step 7 — Commit and push

```bash
git add data/profiles/claude/observations/ data/profiles/claude/knowledge/ \
        data/profiles/claude/IMPROVEMENT_PROPOSALS.md data/profiles/claude/improvement_proposals.json \
        data/profiles/codex/observations/ data/profiles/codex/knowledge/ \
        data/profiles/codex/IMPROVEMENT_PROPOSALS.md data/profiles/codex/improvement_proposals.json
git commit -m "[reflection] $(date +%Y-%m-%d) evening reflection"
git push origin main
```

---

## Quality checklist

- [ ] Read ALL journal entries before forming opinions
- [ ] Did at least 4 web searches for post-close market context
- [ ] Every lesson is specific to today, not generic trading advice
- [ ] Trades review covers EVERY trade that executed, not just winners
- [ ] Confidence calibration is honest (if we have data)
- [ ] Forward outlook references specific catalysts from research
- [ ] JSON files are valid (no trailing commas, no comments)
- [ ] Same content written to BOTH claude and codex profiles
