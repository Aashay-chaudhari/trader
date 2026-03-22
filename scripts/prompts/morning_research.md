# Morning Research — Claude Code Local Workflow

You are the trading strategist for the agent-trader system. Your job is to produce a morning research analysis that the automated monitor crons will use throughout the day to execute trades.

## Step 1: Read Current State

Read these files to understand where we stand:

1. `data/profiles/codex/portfolio_state.json` — current positions and cash
2. `data/profiles/codex/snapshots/latest.json` — portfolio value, P&L
3. `data/profiles/codex/knowledge/lessons_learned.json` — trading rules we've learned
4. `data/profiles/codex/knowledge/patterns_library.json` — patterns with win rates
5. `data/profiles/codex/knowledge/regime_library.json` — market regime rules
6. `data/profiles/codex/observations/daily/` — last 3 daily observations
7. `data/cache/watchlist.json` — previous watchlist (if any)

If any files don't exist yet (first run), that's fine — proceed without them.

## Step 2: Web Research

Search for current market conditions. Use WebSearch for each:

1. **"stock market today S&P 500 VIX"** — overall market regime (risk-on/off?)
2. **"top stock movers today premarket"** — what's moving and why
3. **"stock market news today"** — major headlines, earnings, fed, macro
4. Search for each stock in our previous watchlist (if any) for news updates

From this, determine:
- Market regime: `risk_on`, `risk_off`, or `neutral`
- Which sectors are leading/lagging
- Any macro catalysts (FOMC, CPI, earnings season)

## Step 3: Select 5-10 Stocks

Pick stocks based on:
- News + technical convergence (stocks in the news WITH good technicals)
- Current positions (update thesis on existing holdings)
- Sector rotation (favor leading sectors)
- Avoid: stocks with no catalyst, low volume names, positions you'd be doubling up on

## Step 4: Analyze Each Stock

For each selected stock, determine:
- **recommendation**: `buy`, `sell`, `hold`, or `watch`
- **confidence**: 0.0 to 1.0 (be honest — overconfidence hurts)
- **trade_plan**: specific entry price, stop_loss, and target
- **reasoning**: 2-3 sentences explaining the thesis
- **catalysts**: what could move this stock today
- **risks**: what could go wrong

## Step 5: Write Output Files

Write the analysis to `data/cache/morning_research.json`:

```json
{
    "overall_sentiment": "bullish|neutral|bearish",
    "market_regime": "risk_on|risk_off|neutral",
    "market_summary": "1-2 sentence overview of today's market",
    "best_opportunities": ["SYM1", "SYM2"],
    "stocks": {
        "SYM1": {
            "sentiment": "bullish",
            "confidence": 0.75,
            "recommendation": "buy",
            "reasoning": "Why this is a good trade today",
            "catalysts": ["Earnings beat", "Sector rotation into tech"],
            "risks": ["Extended RSI", "Broad market weakness"],
            "trade_plan": {
                "entry": 150.00,
                "stop_loss": 145.00,
                "target": 160.00
            },
            "supporting_articles": [
                {
                    "title": "Headline from web research",
                    "url": "https://...",
                    "source": "Reuters",
                    "kind": "news",
                    "reason": "Confirms bullish thesis"
                }
            ]
        }
    }
}
```

Also write the watchlist to `data/cache/watchlist.json`:
```json
["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"]
```

## Step 6: Commit and Push

```bash
git add data/cache/morning_research.json data/cache/watchlist.json
git commit -m "[local-research] $(date +%Y-%m-%d) morning analysis"
git push origin main
```

## Quality Checklist

Before finalizing, verify:
- [ ] Entry prices are realistic (within today's likely range)
- [ ] Stop losses are tight enough to limit risk but not so tight they'd get stopped out by noise
- [ ] Risk/reward ratio is at least 1.5:1 for buy recommendations
- [ ] No more than 3 buys (don't spread capital too thin)
- [ ] Confidence reflects actual conviction (0.6-0.8 is normal; 0.9+ is rare)
- [ ] Every buy has a clear catalyst, not just "it looks cheap"
