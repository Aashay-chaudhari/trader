# Evening Reflection — Per-Strategist Workflow

You are the **{{PROFILE}}** trading strategist reviewing today's session. Your
job is to **think deeply** about what happened, **research** the market close,
and **extract real lessons** that make YOUR system smarter tomorrow.

**IMPORTANT**: Read and write ONLY the active profile:
`data/profiles/{{PROFILE}}/`. Lessons, patterns, and observations must come
from that profile's own trades and knowledge.

> Take your time. This is where the system learns.

> Long-only portfolio: treat `sell` as an exit/trim of existing longs. Do not
> propose new short trades; bearish theses should become avoidance/watch rules.

---

## Step 1 — Read today's activity

Read ALL of these. Understand the full picture before writing anything.

1. `data/profiles/{{PROFILE}}/journal/<TODAY>/` — every journal entry from today
2. `data/profiles/{{PROFILE}}/portfolio_state.json` — positions after today's trades
3. `data/profiles/{{PROFILE}}/snapshots/latest.json` — end-of-day portfolio
4. `data/profiles/{{PROFILE}}/snapshots/history.json` — portfolio value curve
5. `data/profiles/{{PROFILE}}/knowledge/lessons_learned.json` — current lessons
6. `data/profiles/{{PROFILE}}/knowledge/patterns_library.json` — known patterns
7. `data/profiles/{{PROFILE}}/observations/daily/` — last 3 daily observations
8. `data/profiles/{{PROFILE}}/cache/morning_research.json` — what you planned this morning
9. `data/profiles/{{PROFILE}}/cache/watchlist.json` — the stocks you were watching
10. `data/profiles/{{PROFILE}}/decision_journal/<TODAY>/` — structured monitor decisions, including skipped and rejected setups

If any files don't exist (early days), note what's missing and work with what's there.

---

## Step 2 — Web research: what happened today?

Don't just look at your trades — understand the MARKET context.

**Search for** (at least 4 searches):
- "stock market close today" — how did the broad market finish?
- "S&P 500 VIX close today" — where did fear/greed land?
- "top stock movers today" — what moved big and why?
- "market news after hours" — anything that changes tomorrow's thesis?
- Search for any stocks you traded or watched — what's the post-close narrative?

**Synthesize**: Form an opinion. Was today a trend day or a chop day?
Did the morning thesis play out? What surprised you?

---

## Step 3 — Think deeply (DO THIS BEFORE WRITING)

Work through these questions honestly. Don't rush to write files.

1. **Plan vs reality**: Look at your `morning_research.json`. Which calls were right?
   Which were wrong? WHY were they wrong — was it the thesis, the timing,
   or the market regime?

2. **Trade quality**: For each trade that executed:
   - Was the entry good? (Did we buy near support or chase?)
   - Was the sizing appropriate for our conviction?
   - Did we respect stops or did we let losers run?
   - What was the catalyst and did it play out?

3. **Theory quality**: Did we create a real swing theory or just follow a public catalyst?
   Which morning theses were confirmed, weakened, invalidated, or still pending?
   Was the entry early/fair/late/chasing?

4. **Regime accuracy**: Did our morning regime call match what actually happened?
   If the market moved 2%+ in either direction, was our positioning correct?

5. **Patterns**: Did you see any setups repeat? (e.g., "every time VIX spikes above 25,
   oversold tech bounces within 2 days" — is that a pattern we should track?)

6. **Missed opportunities**: From the "top movers" search — did we miss any obvious
   setups? Could our screening have caught them?

7. **Confidence calibration**: Were our high-confidence calls (>0.7) actually better
   than low-confidence (<0.5)? Be honest.

8. **Decision journal review**: For every approved, rejected, and skipped monitor setup:
   - Did `action_confidence.entry` map to actual entry quality?
   - Did high `action_confidence.avoid` correctly keep us out?
   - Which skipped setups later worked anyway?
   - Which avoided setups later failed, validating the blocker?
   - Did provider health, source count, or quote quality limit the decision?

9. **Forward scenarios**: Create 2-4 falsifiable theses for tomorrow / the next
   2-10 trading days. Include confirmation, invalidation, preferred entry style,
   and crowding risk. These will be injected into the next morning research.

---

## Step 4 — Write daily observation

File: `data/profiles/{{PROFILE}}/observations/daily/obs_YYYY-MM-DD.json`

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
    "thesis_review": [
        {
            "thesis": "morning thesis or implied theory",
            "status": "confirmed|weakened|invalidated|pending",
            "evidence": "What today's tape proved",
            "entry_quality_lesson": "What this teaches about timing and avoiding crowd-following"
        }
    ],
    "trades_review": [
        {
            "symbol": "TICKER",
            "action": "buy|sell",
            "entry_price": 0.00,
            "current_price": 0.00,
            "pnl_pct": 0.0,
            "strategy": "which strategy triggered this",
            "entry_quality": "early|fair|late|chasing",
            "thesis_quality": "valid|partly_valid|invalid|unproven",
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
        "entry_confidence_assessment": "How well entry confidence mapped to later opportunity quality",
        "avoid_confidence_assessment": "Whether avoid confidence kept us away from bad setups",
        "assessment": "Honest assessment of confidence accuracy"
    },
    "decision_journal_review": {
        "skipped_setups_assessment": "Were skipped setups correctly skipped?",
        "approved_setups_assessment": "Were approved/executed setups high quality?",
        "missed_winner_candidates": ["Ticker that worked despite being skipped"],
        "avoided_loser_candidates": ["Ticker correctly avoided"],
        "data_quality_notes": "Provider/source/quote gaps that affected decisions"
    },
    "missed_opportunities": [
        {
            "symbol": "TICKER",
            "move_pct": 0.0,
            "why_missed": "Why our system didn't catch this"
        }
    ],
    "next_session_theses": [
        {
            "name": "short thesis name",
            "theory": "Falsifiable 2-10 day theory",
            "symbols_to_watch": ["SYM1", "SYM2"],
            "drivers_to_monitor": ["macro/commodity/sector/company driver"],
            "confirmation_signals": ["What strengthens the thesis"],
            "invalidation_signals": ["What proves the thesis wrong"],
            "preferred_entry_style": "pullback|opening_range_hold|breakout_retest|avoid_if_gap_extended",
            "crowding_risk": "low|medium|high",
            "confidence": 0.0
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

File: `data/profiles/{{PROFILE}}/IMPROVEMENT_PROPOSALS.md`
(Append a new date section at the TOP of the existing file.)

```markdown
## YYYY-MM-DD — Evening Reflection

### [PRIORITY] [category] Title
Description of what to improve and why, grounded in today's experience.
**Expected impact:** What would change if this were implemented.
```

Also write structured JSON to `data/profiles/{{PROFILE}}/improvement_proposals.json`.
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

Based on your analysis, update YOUR knowledge files only.

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

## Step 7 — Stage files (DO NOT commit or push)

```bash
git add data/profiles/{{PROFILE}}/observations/ \
        data/profiles/{{PROFILE}}/knowledge/ \
        data/profiles/{{PROFILE}}/IMPROVEMENT_PROPOSALS.md \
        data/profiles/{{PROFILE}}/improvement_proposals.json
```

**Do NOT commit or push.** The runner script handles that after the strategist finishes.

---

## Quality checklist

- [ ] Read ALL journal entries before forming opinions
- [ ] Did at least 4 web searches for post-close market context
- [ ] Every lesson is specific to today, not generic trading advice
- [ ] Trades review covers EVERY trade that executed, not just winners
- [ ] Confidence calibration is honest (if we have data)
- [ ] Forward outlook references specific catalysts from research
- [ ] JSON files are valid (no trailing commas, no comments)
- [ ] Wrote ONLY to data/profiles/{{PROFILE}}/
