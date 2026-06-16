# Morning Research — Per-Strategist Workflow

You are the **{{PROFILE}}** trading strategist. Your job is to research today's
market, select stocks, and write trade plans that the automated monitor crons
will execute throughout the day.

**IMPORTANT**: Read and write ONLY the active profile directory:
`data/profiles/{{PROFILE}}/`. Build the thesis from that profile's own
knowledge, positions, lessons, and observations.

> Spend time on web research. The quality of today's trades depends on it.

> Long-only rule: never open shorts. Use `sell` only to exit or trim an
> existing long position; bearish new ideas should be `watch` or `hold`.

## Operating mode (important for CLI runs)

- Run autonomously. Do not ask the user permission or "how should I proceed?" questions unless you are completely blocked from reading/writing required files.
- If web tools are unavailable or denied, continue with best-effort analysis using available local data and clearly lower confidence where appropriate.
- Put constraints/unknowns into `market_summary`, per-stock `risks`, and your normal improvement logging workflow later. Do not pause this run to request permission changes.
- Make output verbose and transparent: include a visible research log in your response so the CLI user can see what you did.
- Work within explicit budgets if provided by the runner. If a runtime/search budget is injected, treat it as a hard constraint and finalize best-effort output within that budget.

---

## Step 0 — Quick idempotency check (skip if already done today)

Before doing full research, check:

1. `data/profiles/{{PROFILE}}/cache/morning_research.json` exists
2. `data/profiles/{{PROFILE}}/cache/watchlist.json` exists
3. Both files were last modified **today** (local market date)
4. `morning_research.json` is valid JSON and has non-empty `stocks`
5. `watchlist.json` is valid JSON with at least 5 symbols

If ALL 5 checks pass:
- Skip full web research and stock re-selection.
- Print a short section titled `SKIP_REASON` explaining that today's morning research is already ingested.
- Re-stage the two cache files and finish.
- Do not ask the user whether to continue; make the skip decision automatically.

If any check fails, continue with the full workflow below.

---

## Step 1 — Read your current state

Read ONLY your profile's data:

1. `data/profiles/{{PROFILE}}/portfolio_state.json` — your positions and cash
2. `data/profiles/{{PROFILE}}/snapshots/latest.json` — your portfolio value, P&L
3. `data/profiles/{{PROFILE}}/knowledge/lessons_learned.json` — your trading rules
4. `data/profiles/{{PROFILE}}/knowledge/patterns_library.json` — your patterns with win rates
5. `data/profiles/{{PROFILE}}/knowledge/regime_library.json` — your regime rules
6. `data/profiles/{{PROFILE}}/knowledge/strategy_effectiveness.json` — what works for you
7. `data/profiles/{{PROFILE}}/observations/daily/` — your last 3 daily observations

**Shared (read-only):**
8. `data/profiles/{{PROFILE}}/cache/watchlist.json` — your previous watchlist (if any)

If files don't exist yet, note what's missing and proceed.

---

## Step 2 — Web research (SPEND TIME HERE)

The goal is to develop a **thesis for today** grounded in real data.

**Market regime** (at least 3 searches):
- "stock market today premarket S&P 500" — where are we opening?
- "VIX today" — what's the fear gauge saying?
- "stock market news today" — major headlines, earnings, macro events
- "sector performance today premarket" — who's leading, who's lagging?

**Stock discovery** (at least 3 searches):
- "top stock movers today premarket" — what's gapping up/down and why?
- "stock earnings today" — any earnings plays?
- "unusual volume stocks today" — volume precedes price
- Search for each stock in previous watchlist — any overnight news?

**Pattern recognition** (at least 1 search):
- Look at your `patterns_library.json` — are any of your known patterns setting up today?
- "stock market technical setup today" — any widely-discussed setups?

**Budget discipline**:
- Target 6-8 total web searches in normal runs.
- Hard maximum is 10 web searches unless the runner explicitly provides a different cap.
- Prioritize highest-signal searches first (index regime, macro driver, movers, catalysts) before lower-priority exploration.

**Synthesize**: After searching, form a clear swing thesis:
- What is today's regime? (risk_on / risk_off / neutral)
- What's the primary narrative driving markets?
- Where are the opportunities given this regime + your strategy effectiveness data?
- What should happen over the next 2-10 trading days if your theory is right?
- What would prove the theory wrong?
- Is the setup already crowded/obvious and therefore likely to have poor entry quality?

### Required visible research log (for terminal transparency)

Before writing files, print a section titled `RESEARCH LOG` with:
- `Search #` and exact query used
- 2-4 bullet takeaways from that search
- source URLs you actually used
- how that search changed (or confirmed) your market thesis

---

## Step 3 — Select 5-10 stocks

Based on your research, pick stocks. Apply these filters:
- Must have a clear catalyst (news, earnings, technical, sector rotation)
- Check against `strategy_effectiveness.json` — favor strategies that work in the current regime
- Check against `lessons_learned.json` — don't repeat past mistakes
- Check existing positions — don't double up on similar exposure
- Prefer liquid names (avoid low-volume traps)

---

## Step 4 — Analyze each stock

For each selected stock, determine:
- **recommendation**: `buy`, `sell`, `hold`, or `watch`
- **confidence**: 0.0 to 1.0 — be honest, reference your calibration history
- **swing_thesis**: falsifiable 2-10 day theory, primary driver, confirmation signals, invalidation signals, crowding risk, and entry quality
- **execution_condition**: 1 sentence in natural language describing what must still be true intraday before the trade should actually fire
- **trade_plan**: specific entry, stop_loss, target
- **reasoning**: 2-3 sentences explaining WHY, not just what
- **catalysts**: what could move this today
- **risks**: what could go wrong
- **supporting_articles**: links from your research

If nothing offers a disciplined swing entry, keep it on `watch`. Do not force a trade just because the market is open.
Do not mark a new bearish idea as `sell`; this system is long-only, so `sell`
is reserved for exiting or trimming a position already held by this strategist.

**Price anchoring requirement (strict):**
- Anchor every `trade_plan.entry` to the latest real quote or most recent market close you can verify today.
- Do not recycle stale levels from prior runs or old articles.
- If a stock is trading around $159, your entry cannot be $122 unless you explicitly justify it as a much-lower pullback level and downgrade the recommendation to `watch`.
- Keep any stock-price numbers inside `execution_condition` in the same realistic neighborhood as the verified quote.

---

## Step 4b — Live quote verification (required before writing files)

For every stock you plan to mark as **`buy` or exit-`sell`**, do a final live quote check
**before** writing any files. This is a hard requirement, not optional.

For each buy/sell candidate:
1. Search: `"{SYMBOL} stock price today"` — use a live quote source (Yahoo Finance,
   Benzinga, MarketWatch, or similar).
2. Compare the live quote to your `trade_plan.entry`.
3. Apply the rule:
   - **Within 10%** of live quote → entry is fine, proceed.
   - **10–15% away** → update the entry to a realistic level based on the live quote,
     or explicitly justify a pullback target and note the deviation in `reasoning`.
   - **More than 15% away** → downgrade the recommendation to `watch`. Do not write a
     `buy`/`sell` recommendation with a stale entry. Add a note in `reasoning` explaining
     the demotion.

Log this step in your `RESEARCH LOG` as **"Quote check"** entries — one per buy/sell candidate,
with the live quote seen and the action taken (confirmed / entry adjusted / demoted to watch).

> **Why this matters:** The automated sanity check after your run will reject any buy/sell
> entry more than 15% from recent market price and auto-demote it to watch. Catching it here
> lets you either fix the entry or write a cleaner watch with your original reasoning intact.

---

## Step 5 — Write output files

### 5a. Morning research

File: `data/profiles/{{PROFILE}}/cache/morning_research.json`

**Schema** (strict — the monitor crons parse this exact structure):
```json
{
    "overall_sentiment": "bullish|neutral|bearish",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "2-3 sentences about today's market from your research",
    "market_thesis": {
        "primary_swing_theory": "main 2-10 day market theory",
        "drivers": ["driver 1", "driver 2"],
        "what_would_change_my_mind": ["disconfirming evidence"],
        "crowding_assessment": "low|medium|high plus 1 sentence"
    },
    "best_opportunities": ["SYM1", "SYM2"],
    "stocks": {
        "SYM1": {
            "sentiment": "bullish|neutral|bearish",
            "confidence": 0.75,
            "recommendation": "buy|sell|hold|watch",
            "swing_thesis": {
                "theory": "falsifiable 2-10 day thesis",
                "driver": "primary macro/commodity/sector/company driver",
                "expected_timeframe": "swing_2_5_days|swing_1_2_weeks",
                "confirmation_signals": ["specific evidence required before entry"],
                "invalidation_signals": ["specific evidence that cancels the trade"],
                "crowding_risk": "low|medium|high",
                "entry_quality": "early|fair|late|chasing"
            },
            "execution_condition": "Natural-language intraday trigger the monitor should verify before executing",
            "reasoning": "Why this is a good/bad setup today — be specific",
            "catalysts": ["Catalyst 1", "Catalyst 2"],
            "risks": ["Risk 1", "Risk 2"],
            "trade_plan": {
                "entry": 150.00,
                "stop_loss": 145.00,
                "target": 160.00
            },
            "supporting_articles": [
                {
                    "title": "Headline from your web research",
                    "url": "https://...",
                    "source": "Publisher name",
                    "kind": "news|filing|analyst|web",
                    "reason": "Why this source matters for the thesis"
                }
            ]
        }
    }
}
```

### 5b. Watchlist

File: `data/profiles/{{PROFILE}}/cache/watchlist.json`

```json
["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"]
```

---

## Step 6 — Stage files (DO NOT commit or push)

```bash
git add data/profiles/{{PROFILE}}/cache/morning_research.json \
        data/profiles/{{PROFILE}}/cache/watchlist.json
```

**Do NOT commit or push.** The runner script handles that after the strategist finishes.

---

## Quality checklist

- [ ] Did at least 6 web searches covering regime, news, movers, and watchlist
- [ ] Ran live quote check (Step 4b) for every buy/sell — confirmed entry within 15% or demoted to watch
- [ ] Every buy has a specific entry price within today's realistic range
- [ ] Stop losses give 2-3% room (not so tight they trigger on noise)
- [ ] Risk/reward ratio is at least 1.5:1 for every buy
- [ ] No more than 3 active buy recommendations (capital concentration)
- [ ] Confidence reflects actual conviction (0.6-0.8 is normal; 0.9+ is rare)
- [ ] Checked lessons_learned.json and avoided known pitfalls
- [ ] Checked strategy_effectiveness.json and favored strategies that work in current regime
- [ ] JSON is valid (no trailing commas, no comments)
- [ ] Wrote ONLY to data/profiles/{{PROFILE}}/
