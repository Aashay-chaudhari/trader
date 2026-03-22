# Morning Research — Claude Code Local Workflow

You are the trading strategist for the agent-trader system. Your job is to
**research today's market**, **select stocks**, and **write trade plans** that
the automated monitor crons will execute throughout the day.

Read from BOTH profiles (claude and codex) for context — they may have
divergent positions. Write the shared research output to `data/cache/`.

> Spend time on web research. The quality of today's trades depends on it.

---

## Step 1 — Read current state

Read from BOTH profiles to understand our combined position:

**For each profile** (`codex`, then `claude`):
1. `data/profiles/<PROFILE>/portfolio_state.json` — current positions and cash
2. `data/profiles/<PROFILE>/snapshots/latest.json` — portfolio value, P&L
3. `data/profiles/<PROFILE>/knowledge/lessons_learned.json` — trading rules
4. `data/profiles/<PROFILE>/knowledge/patterns_library.json` — patterns with win rates
5. `data/profiles/<PROFILE>/knowledge/regime_library.json` — regime rules
6. `data/profiles/<PROFILE>/knowledge/strategy_effectiveness.json` — what works in which regime
7. `data/profiles/<PROFILE>/observations/daily/` — last 3 daily observations

**Shared:**
8. `data/cache/watchlist.json` — previous watchlist (if any)

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
- Look at our `patterns_library.json` — are any of our known patterns setting up today?
- "stock market technical setup today" — any widely-discussed setups?

**Synthesize**: After searching, form a clear thesis:
- What is today's regime? (risk_on / risk_off / neutral)
- What's the primary narrative driving markets?
- Where are the opportunities given this regime + our strategy effectiveness data?

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
- **trade_plan**: specific entry, stop_loss, target
- **reasoning**: 2-3 sentences explaining WHY, not just what
- **catalysts**: what could move this today
- **risks**: what could go wrong
- **supporting_articles**: links from your research

---

## Step 5 — Write output files

### 5a. Morning research

File: `data/cache/morning_research.json`

**Schema** (strict — the monitor crons parse this exact structure):
```json
{
    "overall_sentiment": "bullish|neutral|bearish",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "2-3 sentences about today's market from your research",
    "best_opportunities": ["SYM1", "SYM2"],
    "stocks": {
        "SYM1": {
            "sentiment": "bullish|neutral|bearish",
            "confidence": 0.75,
            "recommendation": "buy|sell|hold|watch",
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

File: `data/cache/watchlist.json`

```json
["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"]
```

---

## Step 6 — Commit and push

```bash
git add data/cache/morning_research.json data/cache/watchlist.json
git commit -m "[research] $(date +%Y-%m-%d) morning analysis"
git push origin main
```

---

## Quality checklist

- [ ] Did at least 6 web searches covering regime, news, movers, and watchlist
- [ ] Every buy has a specific entry price within today's realistic range
- [ ] Stop losses give 2-3% room (not so tight they trigger on noise)
- [ ] Risk/reward ratio is at least 1.5:1 for every buy
- [ ] No more than 3 active buy recommendations (capital concentration)
- [ ] Confidence reflects actual conviction (0.6-0.8 is normal; 0.9+ is rare)
- [ ] Checked lessons_learned.json and avoided known pitfalls
- [ ] Checked strategy_effectiveness.json and favored strategies that work in current regime
- [ ] JSON is valid (no trailing commas, no comments)
