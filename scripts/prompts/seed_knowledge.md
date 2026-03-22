# Seed Knowledge — First Run Bootstrap

You are bootstrapping the agent-trader knowledge base for its first day of trading. This creates the initial context that the system needs to make informed decisions from day 1.

## Step 1: Create Knowledge Directory Structure

```bash
mkdir -p data/profiles/codex/knowledge
mkdir -p data/profiles/codex/observations/daily
mkdir -p data/profiles/codex/observations/weekly
mkdir -p data/profiles/codex/observations/monthly
mkdir -p data/profiles/codex/positions/active
mkdir -p data/profiles/codex/positions/closed
```

## Step 2: Web Research — Current Market State

Search the web to understand today's market:
1. **"stock market regime 2026"** — are we in a bull/bear/sideways market?
2. **"VIX level today"** — volatility environment
3. **"sector rotation today"** — which sectors are leading
4. **"S&P 500 trend 2026"** — broad market direction
5. **"best trading strategies current market"** — what's working now

## Step 3: Create Initial Lessons Learned

Based on your web research and general trading knowledge, write to `data/profiles/codex/knowledge/lessons_learned.json`:

```json
[
    "Always respect stop losses — the market can stay irrational longer than you can stay solvent",
    "Momentum trades work best in risk-on regimes; mean reversion works better in choppy markets",
    "Volume confirms price: breakouts on low volume often fail",
    "Don't chase: if you missed the entry, wait for a pullback or move to the next setup",
    "Position size matters more than entry price — keep individual positions under 8% of portfolio",
    "News catalyst + technical confirmation = highest conviction setups",
    "RSI divergence is more reliable than absolute RSI levels",
    "Earnings reactions in the first 30 minutes are often overreactions — wait for the dust to settle",
    "Sector rotation is a leading indicator: money flows tell you where the market is going",
    "The best trade is often no trade: sitting out uncertain setups preserves capital"
]
```

## Step 4: Create Initial Regime Library

Write to `data/profiles/codex/knowledge/regime_library.json`:

```json
{
    "risk_on": {
        "description": "Bullish regime: VIX < 18, S&P trending up, growth leading",
        "rules": [
            "Prefer momentum and breakout strategies",
            "Widen stops by 1.5x (trends run further than expected)",
            "Increase position sizes slightly (up to 8%)",
            "Focus on growth and tech sectors",
            "Mean reversion sells are lower probability"
        ]
    },
    "risk_off": {
        "description": "Bearish regime: VIX > 25, S&P trending down, defensives leading",
        "rules": [
            "Prefer mean reversion and defensive strategies",
            "Tighten stops (trends reverse faster in fear)",
            "Reduce position sizes (max 5%)",
            "Focus on utilities, healthcare, consumer staples",
            "Avoid catching falling knives in momentum names"
        ]
    },
    "neutral": {
        "description": "Choppy regime: VIX 18-25, no clear trend, sector rotation",
        "rules": [
            "Prefer range-bound strategies (support/resistance, VWAP)",
            "Keep positions small (max 5%)",
            "Take profits quickly — moves don't follow through",
            "Look for sector rotation opportunities",
            "Avoid trend-following strategies (false breakouts common)"
        ]
    }
}
```

## Step 5: Create Initial Strategy Effectiveness

Write to `data/profiles/codex/knowledge/strategy_effectiveness.json`:

```json
{
    "last_updated": "seed",
    "by_regime": {
        "risk_on": {
            "momentum": {"win_rate": 0.65, "avg_pnl": 2.1, "sample_size": 0},
            "trend": {"win_rate": 0.60, "avg_pnl": 1.8, "sample_size": 0},
            "volume_breakout": {"win_rate": 0.55, "avg_pnl": 2.5, "sample_size": 0}
        },
        "risk_off": {
            "mean_reversion": {"win_rate": 0.60, "avg_pnl": 1.5, "sample_size": 0},
            "support_resistance": {"win_rate": 0.55, "avg_pnl": 1.2, "sample_size": 0}
        },
        "neutral": {
            "vwap": {"win_rate": 0.55, "avg_pnl": 1.0, "sample_size": 0},
            "support_resistance": {"win_rate": 0.50, "avg_pnl": 0.8, "sample_size": 0}
        }
    },
    "note": "Initial estimates from general trading research. Will be updated with real data after first weekly review."
}
```

## Step 6: Create Initial Patterns Library

Write to `data/profiles/codex/knowledge/patterns_library.json`:

```json
[]
```

(Empty — patterns will be discovered from actual trading. No point guessing.)

## Step 7: Create Genesis Observation

Based on your web research, write to `data/profiles/codex/observations/daily/obs_$(date +%Y-%m-%d).json`:

```json
{
    "date": "YYYY-MM-DD",
    "market_regime": "(from your web research)",
    "market_summary": "(1-2 sentences about current market conditions)",
    "sector_leaders": ["(from research)"],
    "sector_laggards": ["(from research)"],
    "trades_review": [],
    "patterns_detected": [],
    "confidence_calibration": {
        "assessment": "Day 1 — no calibration data yet"
    },
    "forward_outlook": "(what to watch for tomorrow based on research)",
    "lessons": ["Day 1: focus on small positions and learning the market rhythm"]
}
```

## Step 8: Commit and Push

```bash
git add data/profiles/codex/knowledge/ data/profiles/codex/observations/
git commit -m "[seed] $(date +%Y-%m-%d) initial knowledge base bootstrap"
git push origin main
```

After this, run the morning research prompt to create the first trade plan.
