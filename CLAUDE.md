# Agent Trader

Multi-agent stock trading system. Runs autonomously via GitHub Actions, trades on Alpaca (paper), displays results on GitHub Pages. Claude learns from its own trades via a feedback loop.

## Architecture — Two-Phase Pipeline

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full visual flow diagram.

### Phase 1: Morning Research (9:00 AM ET)
```
ScreenerAgent → scans 60 liquid US stocks for momentum/volume
DataAgent     → detailed data + technical indicators
NewsAgent     → headlines, analyst recs, earnings, sector performance, VIX
ResearchAgent → Claude Sonnet deep analysis with full context + performance feedback
Output: watchlist + trade plans with entry/stop/target
```

### Phase 2: Monitor & Trade (every 30 min, 9:30 AM - 4 PM ET)
```
DataAgent     → refresh prices
NewsAgent     → check for new headlines
ResearchAgent → Claude Haiku light check ("what changed?")
StrategyAgent → 8 strategies vote (need 2+ to agree)
RiskAgent     → validate position size, volume, sanity
ExecutionAgent→ dry-run log or Alpaca paper trade
PortfolioAgent→ update P&L, dashboard snapshot
```

## Agents

| Agent | What it does | Powered by | Cost |
|-------|-------------|-----------|------|
| ScreenerAgent | Find today's stocks dynamically | yfinance | Free |
| DataAgent | Prices + RSI, MACD, BBands, SMAs | yfinance + ta | Free |
| NewsAgent | Headlines, analyst recs, earnings, VIX, sectors | yfinance | Free |
| ResearchAgent | Deep analysis + trade plans + self-review | Claude Sonnet/Haiku | ~$0.70/mo |
| StrategyAgent | 8 strategies: momentum, mean reversion, trend, volume breakout, S/R, VWAP, relative strength, news catalyst | Python | Free |
| RiskAgent | Signal strength, position size, volume, price sanity | Python | Free |
| ExecutionAgent | Alpaca paper trading or dry-run logging | Alpaca API | Free |
| PortfolioAgent | Track positions, P&L, generate snapshots | Python | Free |

## Key Features

- **Feedback loop**: Claude sees its own win rate, confidence calibration, past mistakes
- **Learned rules**: Claude generates trading rules from performance reviews, loaded into future prompts
- **Best available mode**: guarantees at least 1 trade/day (tiny 2% position) for continuous learning
- **Full audit trail**: every decision logged as markdown journal entries (viewable on GitHub)
- **Pipeline flow visualization**: dashboard shows which agents ran and what they produced

## Commands

```bash
pip install -e ".[dev]"                    # Install
python -m agent_trader research            # Morning research phase
python -m agent_trader monitor             # Monitor & trade phase
python -m agent_trader run                 # Both phases
python -m agent_trader status              # Show portfolio
python -m agent_trader dashboard           # Generate dashboard
pytest tests/unit -v                       # Run tests
```

## Configuration

All config via `.env` (locally) or GitHub Secrets (CI). See `.env.example`.
