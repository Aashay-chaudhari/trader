# Agent Trader

Multi-agent stock trading system that runs autonomously, paper-trades on Alpaca, and displays results on GitHub Pages. Two independent AI strategists (Claude + Codex) run in parallel with separate paper accounts; their books merge into a single comparison dashboard.

The agent accumulates knowledge across days through a structured 5-phase introspection loop — it gets smarter every trading day.

## How It Works

```
YOU (Claude Code)                    GITHUB ACTIONS (automated)
─────────────────                    ────────────────────────────
Morning (~8:30 AM ET)                Every 30 min (9:30 AM - 4:00 PM ET)
┌────────────────────────┐           ┌─────────────────────────────┐
│ Open Claude Code       │           │  Monitor & Trade            │
│ "Follow morning_       │  push →   │  ├── Refresh prices         │
│  research.md"          │ ────────→ │  ├── 8 strategies vote      │
│                        │           │  ├── Risk validation        │
│ Claude does:           │           │  ├── LLM quick check ($0.001│
│ • Web research         │           │  └── Execute on Alpaca      │
│ • Read portfolio       │           │                             │
│ • Pick stocks          │           │  Pure Python + tiny API call│
│ • Write trade plans    │           │  Cost: ~$0.04/month total   │
│ • Push to GitHub       │           └─────────────────────────────┘
└────────────────────────┘
                                     Dashboard auto-updates on
Evening (~4:30 PM ET)                GitHub Pages after each run
┌────────────────────────┐
│ Open Claude Code       │
│ "Follow evening_       │
│  reflection.md"        │
│                        │
│ Claude does:           │
│ • Review today's trades│
│ • Extract patterns     │
│ • Update knowledge     │
│ • Push to GitHub       │
└────────────────────────┘

Weekly (Sunday) / Monthly (last business day):
Same pattern — follow the prompt, Claude does research + updates knowledge.
```

## Architecture: 5-Phase Knowledge Loop

| Phase | When | What | Powered By | Cost |
|-------|------|------|-----------|------|
| 1. Research | 8:30 AM ET | Web research, stock picks, trade plans | Claude Code (you) | $0 (subscription) |
| 2. Monitor | Every 30 min | Price check, strategy vote, execute trades | GitHub Actions + Haiku | ~$0.04/mo |
| 3. Reflect | 4:30 PM ET | Daily review, lessons, pattern extraction | Claude Code (you) | $0 (subscription) |
| 4. Weekly | Sunday | Consolidate week, update knowledge base | Claude Code (you) | $0 (subscription) |
| 5. Monthly | Last biz day | Deep retrospective, strategy audit | Claude Code (you) | $0 (subscription) |

**Total running cost: ~$0.04/month** (monitor phase LLM calls only). Everything else uses your Claude Code subscription.

## 9 Agents

| Agent | Role | Cost |
|-------|------|------|
| ScreenerAgent | Find today's stocks (news + technicals) | Free (yfinance) |
| DataAgent | Prices + RSI, MACD, BBands, SMAs | Free (yfinance + ta) |
| NewsAgent | Headlines, analyst recs, earnings, VIX, Finviz | Free (yfinance) |
| ResearchAgent | Deep analysis + trade plans + reflections | Claude Sonnet/Haiku |
| StrategyAgent | 8 strategies: momentum, mean reversion, trend, volume breakout, S/R, VWAP, relative strength, news catalyst | Free (Python) |
| RiskAgent | Signal strength, position size, volume, price sanity | Free (Python) |
| ExecutionAgent | Alpaca paper trading or dry-run logging | Free (Alpaca) |
| PortfolioAgent | Track positions, P&L, generate snapshots | Free (Python) |
| KnowledgeBase | Accumulated patterns, lessons, regime rules | Free (JSON files) |

## Quick Start

### Prerequisites

- Python 3.11+
- [Claude Code](https://claude.com/claude-code) subscription (for morning/evening prompts)
- Free [Alpaca](https://alpaca.markets) paper trading account(s)

### Setup

```bash
# Clone and install
git clone https://github.com/<your-username>/agent-trader.git
cd agent-trader
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env: add your API keys (ANTHROPIC_API_KEY and/or OPENAI_API_KEY)
# Add Alpaca paper trading keys (free)

# Bootstrap knowledge base (first time only)
# Open Claude Code and say:
# "Follow the instructions in scripts/prompts/seed_knowledge.md"

# Verify everything works
python -m agent_trader research --debug   # Zero-cost test run
pytest tests/unit -v                      # Run 99 unit tests
```

### GitHub Actions Setup

1. **Secrets** (Settings → Secrets and variables → Actions → Secrets):
   - `ANTHROPIC_API_KEY` — for Claude strategist
   - `OPENAI_API_KEY` — for Codex strategist
   - `ALPACA_API_KEY_CLAUDE` + `ALPACA_SECRET_KEY_CLAUDE` — paper account 1
   - `ALPACA_API_KEY_CODEX` + `ALPACA_SECRET_KEY_CODEX` — paper account 2

2. **Variables** (Settings → Secrets and variables → Actions → Variables):
   - `PRODUCTION_MODE=true` — enables real LLM calls + Alpaca orders
   - `RESEARCH_MODEL_OPENAI=gpt-4o-mini` — OpenAI model for Codex strategist

3. Enable GitHub Pages (Settings → Pages → Source: GitHub Actions)

## Daily Workflow

### Morning (~8:30 AM ET)
Open Claude Code in this repo and say:
> Follow the instructions in scripts/prompts/morning_research.md

Claude will:
- Do 6+ web searches (market regime, movers, earnings, sectors)
- Read your portfolio state and knowledge base
- Pick 5-10 stocks with entry/stop/target prices
- Write `data/cache/morning_research.json` and `data/cache/watchlist.json`
- Commit and push

### Monitor (automated, every 30 min)
GitHub Actions runs automatically:
- Refreshes prices, checks for news
- 8 Python strategies vote on each stock
- Ultra-lean LLM check (~500 tokens, $0.001/call)
- Executes trades on Alpaca if signals align
- Updates dashboard on GitHub Pages

### Evening (~4:30 PM ET)
Open Claude Code and say:
> Follow the instructions in scripts/prompts/evening_reflection.md

### Weekly (Sunday)
> Follow the instructions in scripts/prompts/weekly_review.md

### Monthly (last business day)
> Follow the instructions in scripts/prompts/monthly_retrospective.md

## Commands

```bash
# Core phases
python -m agent_trader research            # Phase 1: Morning research
python -m agent_trader monitor             # Phase 2: Monitor & trade
python -m agent_trader run                 # Phases 1 + 2
python -m agent_trader reflect             # Phase 3: Evening reflection
python -m agent_trader weekly              # Phase 4: Weekly review
python -m agent_trader monthly             # Phase 5: Monthly retrospective
python -m agent_trader cycle               # All 5 phases back-to-back

# Utilities
python -m agent_trader status              # Show portfolio
python -m agent_trader dashboard           # Generate dashboard HTML
python -m agent_trader reset               # Clear runtime state
python -m agent_trader reset --keep-knowledge  # Clear runtime, keep knowledge

# Add --debug to any command for zero-cost test (template responses, 3 stocks)
python -m agent_trader research --debug
```

## Project Structure

```
agent-trader/
├── src/agent_trader/
│   ├── agents/              # 8 agents (research, strategy, risk, execution, etc.)
│   ├── core/                # Orchestrator + message bus
│   ├── config/              # Settings (Pydantic, env-driven)
│   ├── utils/               # Knowledge base, swing tracker, journal, feedback
│   └── dashboard/           # GitHub Pages generator
├── scripts/prompts/         # Claude Code workflow prompts
│   ├── seed_knowledge.md    # First-time knowledge bootstrap
│   ├── morning_research.md  # Daily morning analysis
│   ├── evening_reflection.md# Daily evening review
│   ├── weekly_review.md     # Weekly consolidation
│   └── monthly_retrospective.md
├── data/profiles/           # Per-strategist runtime data
│   ├── claude/              # Claude strategist (knowledge, observations, positions)
│   └── codex/               # Codex strategist (same structure)
├── docs/                    # GitHub Pages dashboard
├── tests/unit/              # 99 unit tests
└── .github/workflows/       # GitHub Actions pipeline
```

## Knowledge Accumulation

The agent builds up knowledge over time:

```
data/profiles/<strategist>/
├── knowledge/
│   ├── lessons_learned.json          # Rolling top-50 lessons
│   ├── patterns_library.json         # Named patterns with win rates
│   ├── strategy_effectiveness.json   # Per-strategy win rates by regime
│   └── regime_library.json           # Rules for risk_on/risk_off/neutral
├── observations/
│   ├── daily/   obs_YYYY-MM-DD.json  # Daily market observations
│   ├── weekly/  week_YYYY-MM-DD.json # Weekly consolidation
│   └── monthly/ month_YYYY-MM.json   # Monthly retrospective
└── positions/
    ├── active/                       # Open swing trades
    └── closed/                       # Completed trades with P&L
```

This knowledge feeds back into morning research prompts (~1500 tokens of accumulated context).

## Dual-Strategist Architecture

Two AI strategists run independently on GitHub Actions:

| | Claude Strategist | Codex Strategist |
|---|---|---|
| CLI | Claude Code | OpenAI Codex |
| API fallback | Anthropic (Sonnet) | OpenAI (GPT-4o) |
| Data | `data/profiles/claude/` | `data/profiles/codex/` |
| Alpaca | Paper account 1 | Paper account 2 |

Results merge into a single comparison dashboard on GitHub Pages.

## Documentation

- [Architecture diagram](docs/ARCHITECTURE.md) — full 5-phase pipeline flow
- [Knowledge architecture](docs/KNOWLEDGE_ARCHITECTURE.md) — knowledge accumulation design
- [.env.example](.env.example) — all configuration options

## License

MIT
