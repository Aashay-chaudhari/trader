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

## Command Reference

### Pipeline Commands
| Command | What it does | When to use |
|---------|-------------|-------------|
| `python -m agent_trader research` | Phase 1: screen stocks, fetch data, run deep AI analysis | Every morning ~8:30 AM ET |
| `python -m agent_trader monitor` | Phase 2: refresh prices, check signals, execute trades | Automated via GitHub Actions |
| `python -m agent_trader run` | Phases 1 + 2 back-to-back | Quick local test |
| `python -m agent_trader reflect` | Phase 3: review the day, extract lessons | Every evening ~4:30 PM ET |
| `python -m agent_trader weekly` | Phase 4: consolidate 5 daily observations | Sunday ~8:00 PM ET |
| `python -m agent_trader monthly` | Phase 5: deep retrospective + strategic adjustments | Last business day ~5:00 PM ET |
| `python -m agent_trader evolve` | Phase 6: evidence-backed system improvement proposals | After weekly/monthly (optional) |
| `python -m agent_trader cycle` | All 5 phases back-to-back | First-time seeding or testing |

### Utility Commands
| Command | What it does |
|---------|-------------|
| `python -m agent_trader status` | Show current portfolio: value, P&L, positions |
| `python -m agent_trader dashboard` | Generate merged dashboard HTML → `docs/index.html` |
| `python -m agent_trader validate` | Validate system structure (schemas, prompts, strategies) |
| `python -m agent_trader validate --smoke` | + debug-mode smoke tests for all phases |
| `python -m agent_trader reset` | Clear runtime state (cache, journal, snapshots) |
| `python -m agent_trader reset --keep-knowledge` | Reset but preserve accumulated knowledge |
| `python -m agent_trader reset --all-profiles --docs` | Full reset of all strategist data + dashboard |
| `python -m agent_trader alert test` | Send a test push notification to verify ntfy/Twilio |
| `python -m agent_trader alert morning` | Manually trigger a morning reminder notification |

### Dual-Strategist Commands (both Claude + Codex)
| Command | What it does |
|---------|-------------|
| `./scripts/run_both.sh morning` | Both strategists do morning research, then commit + push |
| `./scripts/run_both.sh evening` | Both strategists do evening reflection |
| `./scripts/run_both.sh weekly` | Both strategists do weekly review |
| `./scripts/run_both.sh monthly` | Both strategists do monthly retrospective |
| `./scripts/run_both.sh morning parallel` | Run both in parallel (faster but more resource-heavy) |

### Dev Commands
| Command | What it does |
|---------|-------------|
| `pip install -e ".[dev]"` | Install with test/lint dependencies |
| `pip install -e ".[dev]"` | Install with SMS alert support (Twilio) |
| `pip install -e ".[dev]"` | Install everything |
| `pytest tests/unit -v` | Run unit tests |
| `ruff check src/` | Lint source code |
| `python -m agent_trader research --debug` | Zero-cost debug run (template responses, 3 stocks) |

### Flags (add to any pipeline command)
| Flag | What it does |
|------|-------------|
| `--debug` | Debug mode: template responses, 3 stocks, zero API cost |
| `--symbols AAPL MSFT` | Override the stock watchlist |
| `--dry-run` | Log trades without placing Alpaca orders |

## How This System Works — Your Daily Workflow

### What's automated (you do nothing)
- **Monitoring & trading** (9:30 AM – 4:00 PM ET, every 30 min) — GitHub Actions runs both strategists, checks signals, executes trades, updates dashboard
- **SMS reminders** — you'll get a text message when it's time to run local phases
- **Dashboard deployment** — GitHub Pages auto-updates after every pipeline run

### What you do manually (with SMS reminders)

**Weekday mornings (~8:30 AM ET):**
1. Get SMS: "Time for morning research!"
2. `cd agent-trader && git pull && ./scripts/run_both.sh morning`
3. Takes ~5 min. Both Claude and Codex analyze the market independently.
4. Auto-commits and pushes. GitHub Actions takes over for the rest of the day.

**Weekday evenings (~4:30 PM ET):**
1. Get SMS: "Market closed — time for evening reflection."
2. `cd agent-trader && git pull && ./scripts/run_both.sh evening`
3. Both strategists review their day, extract lessons, update knowledge.

**Sunday evening (~8:00 PM ET):**
1. Get SMS: "Weekly review time!"
2. `cd agent-trader && git pull && ./scripts/run_both.sh weekly`

**Last business day of month (~5:00 PM ET):**
1. Get SMS: "Monthly retrospective due."
2. `cd agent-trader && git pull && ./scripts/run_both.sh monthly`

### First-time setup
1. Copy `.env.example` → `.env`, fill in API keys
2. `pip install -e ".[dev]"`
3. Install ntfy app on phone, subscribe to your topic, set `NTFY_TOPIC` in `.env`
4. `python -m agent_trader alert test` — verify notification arrives on your phone
5. Run `python -m agent_trader cycle --debug` to verify all phases work (no API calls)
6. Set `PRODUCTION_MODE=true` as a GitHub repo variable when ready to go live

## Configuration

All config via `.env` (locally) or GitHub Secrets + Variables (CI). See `.env.example`.

**Critical settings:**
- `RUN_MODE` — the single control variable: `debug` (default, templates + no orders), `paper` (real LLM + Alpaca paper), `live` (real everything)
- `PRODUCTION_MODE=true` (GitHub Actions) — maps to `RUN_MODE=paper`: real LLM calls + paper orders
- `PRODUCTION_MODE=false` (default) — maps to `RUN_MODE=debug`: template responses + dry-run logging
- Legacy vars (`DEBUG_MODE`, `DRY_RUN`) still work for backward compatibility
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — in GitHub Secrets
- `ALPACA_API_KEY_CLAUDE` / `ALPACA_API_KEY_CODEX` — separate Alpaca paper accounts per strategist
- `RESEARCH_MODEL_OPENAI` — GitHub variable, default `gpt-4o-mini`, set to `gpt-4o` for quality

**Push notifications (optional but recommended — FREE, no signup):**
- Install the ntfy app on your phone (iOS / Android)
- Pick a unique topic name (e.g., `agent-trader-yourname`)
- Subscribe to that topic in the app
- Set `NTFY_TOPIC=agent-trader-yourname` in `.env` and as a GitHub Secret
- That's it — push notifications to your phone, zero cost

**Alpaca paper trading:**
- Free accounts at alpaca.markets — create 2 accounts (one per strategist)
- Paper trading is 100% free, resets available via dashboard (Paper Trading → Account → Reset)
