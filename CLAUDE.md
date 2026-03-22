# Agent Trader

Multi-agent stock trading system. Runs autonomously via GitHub Actions, paper-trades on Alpaca, displays results on GitHub Pages. Two independent AI strategists (Claude + Codex) run in parallel; their books are merged into a single comparison dashboard. The agent accumulates knowledge across days through a structured introspection loop.

## Architecture — Five-Phase Pipeline

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full visual flow diagram.
See [docs/KNOWLEDGE_ARCHITECTURE.md](docs/KNOWLEDGE_ARCHITECTURE.md) for the knowledge accumulation layer.

### Phase 1: Morning Research (9:00 AM ET)
```
NewsAgent     → discover stocks from headlines + Finviz + insider activity
ScreenerAgent → hybrid news + technical screening (60 stocks → top 10)
DataAgent     → detailed data + RSI, MACD, BBands, SMAs
NewsAgent     → per-stock detailed headlines (2nd pass)
ResearchAgent → Claude Sonnet deep analysis with full context:
                  performance feedback, learned rules, knowledge context,
                  recent observations, active swing positions
Output: watchlist + trade plans with entry/stop/target
```

### Phase 2: Monitor & Trade (every 30 min, 9:30 AM – 4:00 PM ET)
```
DataAgent     → refresh prices
NewsAgent     → check for new headlines
ResearchAgent → Claude Haiku light check ("what changed?")
StrategyAgent → 8 strategies vote (need 2+ to agree)
RiskAgent     → validate position size, volume, sanity
ExecutionAgent→ dry-run log or Alpaca paper trade
PortfolioAgent→ update P&L, dashboard snapshot
```

### Phase 3: Evening Reflection (4:15 PM ET)
```
ResearchAgent → review today's trades + journal entries + market regime
Output: daily observation (patterns, lessons, confidence calibration)
         self-improvement proposals → IMPROVEMENT_PROPOSALS.md
         swing position end-of-day updates
```

### Phase 4: Weekly Review (Sunday 8:00 PM ET)
```
ResearchAgent → consolidate 5 daily observations + performance data
Output: weekly observation + knowledge base updates
         (patterns_library, strategy_effectiveness, regime_library, lessons_learned)
```

### Phase 5: Monthly Retrospective (last business day 5:00 PM ET)
```
ResearchAgent → deep review of 4 weekly observations + monthly performance
Output: monthly retrospective + updated top lessons
```

## Agents

| Agent | What it does | Powered by | Cost |
|-------|-------------|-----------|------|
| ScreenerAgent | Find today's stocks dynamically (news + technicals) | yfinance | Free |
| DataAgent | Prices + RSI, MACD, BBands, SMAs | yfinance + ta | Free |
| NewsAgent | Headlines, analyst recs, earnings, VIX, sectors, Finviz | yfinance | Free |
| ResearchAgent | Deep analysis + trade plans + reflections + reviews | Claude Sonnet/Haiku | ~$1/mo |
| StrategyAgent | 8 strategies: momentum, mean reversion, trend, volume breakout, S/R, VWAP, relative strength, news catalyst | Python | Free |
| RiskAgent | Signal strength, position size, volume, price sanity | Python | Free |
| ExecutionAgent | Alpaca paper trading or dry-run logging | Alpaca API | Free |
| PortfolioAgent | Track positions, P&L, generate snapshots | Python | Free |

## Key Features

- **5-phase knowledge loop**: research → trade → reflect → consolidate → retrospect — agent gets smarter every day
- **Dual-strategist comparison**: Claude + Codex run independently, separate Alpaca books, merged dashboard
- **Knowledge accumulation**: patterns, strategies, lessons, regime rules persist across days in `data/knowledge/`
- **Swing position tracking**: multi-day positions tracked with daily updates, stop/target monitoring
- **Self-improvement proposals**: agent generates its own product backlog each evening
- **Feedback loop**: Claude sees its own win rate, confidence calibration, past mistakes
- **Learned rules**: Claude generates trading rules from performance reviews, loaded into future prompts
- **Best available mode**: guarantees at least 1 trade/day (tiny 2% position) for continuous learning
- **Full audit trail**: every decision logged as markdown journal entries (viewable on GitHub)
- **Debug mode**: zero-cost template responses for testing workflow plumbing (DEBUG_MODE=true)

## Commands

```bash
pip install -e ".[dev]"                    # Install
python -m agent_trader research            # Phase 1: Morning research
python -m agent_trader monitor             # Phase 2: Monitor & trade
python -m agent_trader run                 # Phases 1 + 2
python -m agent_trader reflect             # Phase 3: Evening reflection
python -m agent_trader weekly              # Phase 4: Weekly review
python -m agent_trader monthly             # Phase 5: Monthly retrospective
python -m agent_trader cycle               # All 5 phases back-to-back
python -m agent_trader status              # Show portfolio
python -m agent_trader dashboard           # Generate dashboard
python -m agent_trader reset               # Clear runtime state
pytest tests/unit -v                       # Run 99 unit tests

# Add --debug to any command for zero-cost test run (Haiku/template, 3 stocks)
python -m agent_trader research --debug
python -m agent_trader reflect --debug
```

## Local Workflow (Claude Code as Strategist)

The most cost-effective way to run this system: use your Claude Code subscription for the expensive analysis phases, and let GitHub Actions handle the cheap Python-only monitoring.

**Daily workflow:**
1. **Morning (~8:30 AM ET)**: Open Claude Code, say "Follow the instructions in scripts/prompts/morning_research.md". Claude Code does web research, reads your portfolio, picks stocks, writes trade plans, and pushes to GitHub.
2. **Monitor (automated, every 30 min)**: GitHub Actions crons run the Python pipeline — refreshes prices, runs 8 strategies, validates risk, executes trades on Alpaca. Ultra-lean LLM call (~500 tokens) for final trade/skip decisions. Cost: ~$0.04/month.
3. **Evening (~4:30 PM ET)**: Open Claude Code, say "Follow the instructions in scripts/prompts/evening_reflection.md". Claude Code reviews the day's trades, extracts patterns/lessons, writes observations, and pushes.

**Weekly/Monthly**: Same pattern — "Follow the instructions in scripts/prompts/weekly_review.md" or "monthly_retrospective.md".

**First time setup**: "Follow the instructions in scripts/prompts/seed_knowledge.md" to bootstrap the knowledge base.

**Prompt files:**
- `scripts/prompts/morning_research.md` — morning analysis + trade plans
- `scripts/prompts/evening_reflection.md` — daily review + lessons
- `scripts/prompts/weekly_review.md` — weekly consolidation
- `scripts/prompts/monthly_retrospective.md` — monthly deep retrospective
- `scripts/prompts/seed_knowledge.md` — first-time knowledge bootstrap

## Configuration

All config via `.env` (locally) or GitHub Secrets + Variables (CI). See `.env.example`.

**Critical settings:**
- `PRODUCTION_MODE=true` — single GitHub variable that controls everything: sets `DEBUG_MODE=false` + `DRY_RUN=false`
- `PRODUCTION_MODE=false` (default) — development mode: templates + dry-run logging
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — in GitHub Secrets
- `ALPACA_API_KEY_CLAUDE` / `ALPACA_API_KEY_CODEX` — separate Alpaca paper accounts per strategist
- `RESEARCH_MODEL_OPENAI` — GitHub variable, default `gpt-4o-mini`, set to `gpt-4o` for quality

**Alpaca paper trading:**
- Free accounts at alpaca.markets — create 2 accounts (one per strategist)
- Paper trading is 100% free, resets available via dashboard (Paper Trading → Account → Reset)
