# Agent Trader

Multi-agent stock trading system that runs autonomously, paper-trades on Alpaca, and displays results on GitHub Pages. Two independent AI strategists (Claude + Codex) run in parallel with separate paper accounts; their books merge into a single comparison dashboard.

The agent accumulates knowledge across days through a structured 6-phase introspection loop — it gets smarter every trading day.

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

## Architecture: 6-Phase Knowledge Loop

| Phase | When | What | Powered By | Cost |
|-------|------|------|-----------|------|
| 1. Research | 8:30 AM ET | Web research, stock picks, trade plans | Claude Code (you) | $0 (subscription) |
| 2. Monitor | Every 30 min | Price check, strategy vote, execute trades | GitHub Actions + Haiku | ~$0.04/mo |
| 3. Reflect | 4:30 PM ET | Daily review, lessons, pattern extraction | Claude Code (you) | $0 (subscription) |
| 4. Weekly | Sunday | Consolidate week, update knowledge base | Claude Code (you) | $0 (subscription) |
| 5. Monthly | Last biz day | Deep retrospective, strategy audit | Claude Code (you) | $0 (subscription) |
| 6. Evolve | Weekly / on demand | Evidence-backed improvement proposals | Python CLI + strategist LLM | Low |

**Total running cost: low**. Morning/evening strategist work is local CLI-driven; GitHub Actions uses small API calls for monitor-time checks.

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

# Cold start is automatic on first run.
# Optional: scripts/prompts/seed_knowledge_LEGACY.md exists if you want
# to manually pre-seed knowledge with a one-time research pass.

# Verify everything works
python -m agent_trader research --debug   # Zero-cost test run
pytest tests/unit -v                      # Run the unit suite
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
   - `MONITOR_MODEL_OPENAI=gpt-4o-mini` — cheap monitor gate model for Codex strategist

3. Enable GitHub Pages (Settings → Pages → Source: GitHub Actions)

## Daily Workflow

Each strategist (Claude + Codex) runs **independently** — different stock picks,
different lessons, different portfolios. With cold-start enabled, they can begin
from empty schemas and earn their rules from live observations.

### Option A: Bundled script (recommended)

```bash
# Morning — runs Claude CLI then Codex CLI, commits and pushes
./scripts/run_both.sh morning

# Evening
./scripts/run_both.sh evening

# Weekly (Sunday)
./scripts/run_both.sh weekly

# Monthly (last business day)
./scripts/run_both.sh monthly
```

### Option B: Run each manually in Claude Code / Codex

**Morning (~8:30 AM ET)** — run each separately:

In Claude Code:
> Follow the instructions in scripts/prompts/morning_research.md — replace {{PROFILE}} with "claude"

In Codex CLI:
> Follow the instructions in scripts/prompts/morning_research.md — replace {{PROFILE}} with "codex"

Then commit and push:
```bash
git add data/profiles/ && git commit -m "[research] $(date +%Y-%m-%d) dual-strategist" && git push
```

### Monitor (automated, every 30 min)
GitHub Actions runs automatically:
- Refreshes prices, checks for news
- Builds a tiny candidate set near entry / stop / target or with fresh headlines
- Runs a cheap API-only LLM gate against those candidates
- 8 Python strategies vote only after the gate approves entries
- Executes trades on Alpaca if signals align
- Updates dashboard on GitHub Pages

### Evening (~4:30 PM ET)
Same pattern — `./scripts/run_both.sh evening` or run each CLI separately.

### Weekly / Monthly
Same pattern — `./scripts/run_both.sh weekly` or `./scripts/run_both.sh monthly`.

## Commands

```bash
# Core phases
python -m agent_trader research            # Phase 1: Morning research
python -m agent_trader monitor             # Phase 2: Monitor & trade
python -m agent_trader run                 # Phases 1 + 2
python -m agent_trader reflect             # Phase 3: Evening reflection
python -m agent_trader weekly              # Phase 4: Weekly review
python -m agent_trader monthly             # Phase 5: Monthly retrospective
python -m agent_trader evolve              # Phase 6: Improvement proposals
python -m agent_trader cycle               # All 6 phases back-to-back
python -m agent_trader validate            # Validate schemas and structure
python -m agent_trader validate --data-dir data/profiles/claude

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
│   ├── seed_knowledge_LEGACY.md # Optional one-time manual bootstrap
│   ├── morning_research.md  # Daily morning analysis
│   ├── evening_reflection.md# Daily evening review
│   ├── weekly_review.md     # Weekly consolidation
│   └── monthly_retrospective.md
├── data/profiles/           # Per-strategist runtime data
│   ├── claude/              # Claude strategist (knowledge, observations, positions)
│   └── codex/               # Codex strategist (same structure)
├── docs/                    # GitHub Pages dashboard
├── tests/unit/              # Unit tests
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
| Local strategist workflow | Claude Code | OpenAI Codex |
| GitHub Actions provider | Anthropic API | OpenAI API |
| Data | `data/profiles/claude/` | `data/profiles/codex/` |
| Alpaca | Paper account 1 | Paper account 2 |

Results merge into a single comparison dashboard on GitHub Pages.

## Documentation

- [System guide](SYSTEM_GUIDE.md) — operator guide, runtime modes, CLI vs API, learning loop
- [Architecture diagram](docs/ARCHITECTURE.md) — full pipeline flow
- [Knowledge architecture](docs/KNOWLEDGE_ARCHITECTURE.md) — knowledge accumulation design
- [.env.example](.env.example) — all configuration options

## License

MIT
