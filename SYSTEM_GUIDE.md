# System Guide

This repo is a two-layer trading system:

1. A strategist layer that uses Claude and Codex to think, research, reflect, and write profile artifacts.
2. A Python runtime layer that gathers market data, evaluates strategies, applies risk rules, executes paper trades, tracks portfolio state, and accumulates knowledge over time.

The most important mental model is:

`strategists think -> files are written -> Python runtime consumes them -> trades are monitored and logged -> observations become knowledge -> future strategist prompts get better`

## The Two Layers

### 1. Strategist Layer

This is the `scripts/run_both.sh` workflow.

It directly launches:

- `claude`
- `codex`

using the prompt files in `scripts/prompts/`.

Its job is to produce higher-level market thinking and structured artifacts such as:

- `cache/morning_research.json`
- `cache/watchlist.json`
- daily / weekly / monthly observations
- knowledge files

Each strategist writes only into its own profile:

- `data/profiles/claude/`
- `data/profiles/codex/`

This layer is best when you want:

- richer visible reasoning
- deep web research
- side-by-side strategist comparison
- manual supervision

### 2. Python Runtime Layer

This is the `python -m agent_trader ...` workflow.

It wires together agents for:

- screening
- market data
- news
- research
- strategy generation
- risk checks
- execution
- portfolio tracking
- reflection and knowledge accumulation

This layer is best when you want:

- structured execution
- repeatable automation
- GitHub Actions runs
- validation and testability

## What Uses an LLM

Not every part of the repo is an LLM call.

### LLM-heavy component

The main LLM user is `ResearchAgent`.

It is used in these phases:

- morning research
- monitor-time model check
- evening reflection
- weekly review
- monthly retrospective
- evolution

### Mostly deterministic components

These are code-driven, not free-form LLM reasoning:

- `ScreenerAgent`
- `DataAgent`
- `NewsAgent`
- `StrategyAgent`
- `RiskAgent`
- `ExecutionAgent`
- `PortfolioAgent`
- `KnowledgeBase`

They can call external market/news APIs, but they do not behave like chat agents.

## CLI vs API

There are three practical ways the system can use a model.

### A. External CLI mode

This is `./scripts/run_both.sh`.

The script calls the Claude CLI and Codex CLI directly. Those tools handle model interaction themselves. The Python app is not in the middle.

Use this when you want visible strategist sessions.

### B. Internal CLI-agent mode

This is inside the Python runtime.

If these are set:

- `USE_CLI_AGENT=true`
- `CLI_AGENT_PROVIDER=claude` or `codex`

then `ResearchAgent` stages current context into files and launches the selected CLI as a subprocess.

That means the Python app is still running the phase, but the model work happens through the CLI tool rather than direct Anthropic/OpenAI API calls from Python.

### C. Direct API mode

If CLI-agent mode is disabled, unavailable, or fails, `ResearchAgent` falls back to direct provider API calls.

That fallback is controlled by:

- `LLM_PROVIDER`
- `RESEARCH_MODEL`
- `MONITOR_MODEL`
- `RESEARCH_MODEL_OPENAI`

## Direct Answer: “If CLI always works, will I have no API calls?”

If by “API calls” you mean direct LLM API calls from your Python app to Anthropic or OpenAI, then mostly yes:

- if `USE_CLI_AGENT=true`
- and the selected CLI is available
- and it succeeds

then `ResearchAgent` uses the CLI path and does not need to fall back to direct LLM API calls.

But there are two important caveats:

1. The CLI itself still talks to a model backend. So model usage still exists; it is just happening through the CLI tool rather than through your Python code calling the API directly.
2. You will still have non-LLM API usage, including:
   - Alpaca
   - Market data/news providers
   - macro/economic data providers

So the accurate statement is:

`If CLI works, you can avoid direct Python LLM API calls, but you do not avoid model usage or external APIs in general.`

## Direct Answer: “Does GitHub Actions monitoring have LLM calls?”

Yes, in the current system it does.

The monitor phase is not purely deterministic. It does:

1. refresh prices
2. refresh news
3. run a lighter `ResearchAgent` check
4. generate strategy signals
5. run risk checks
6. execute approved trades
7. update portfolio state

So the monitoring path still includes a model step.

In GitHub Actions, the workflow is now configured for API-only analysis.

That means:

- no CLI authentication requirement in Actions
- monitor-time analysis uses a small direct API call
- the strategist family still determines which provider is used

## Run Modes

The system now uses a single run-mode model.

### `debug`

- template responses
- no real LLM call
- no broker orders
- reduced scope

### `paper`

- real LLM analysis
- Alpaca paper orders
- full pipeline

### `live`

- intended future path for real-money execution

Today, `paper` is the correct mode for real paper trading.

## What the Python Runtime Actually Does

### Morning research

Command:

```bash
python -m agent_trader research
```

Flow:

1. News discovery
2. Screener pass
3. Detailed market data
4. Detailed stock news
5. ResearchAgent analysis
6. Save watchlist and context

### Monitor and trade

Command:

```bash
python -m agent_trader monitor
```

Flow:

1. Load watchlist
2. Add any active positions so open swings remain supervised
2. Refresh market data
3. Refresh news
4. Build a tiny candidate set only for symbols near entry/stop/target or with fresh headlines
5. Run a lightweight monitor LLM gate against those candidates
6. Generate strategy signals only for gate-approved entries and active positions
7. Filter through risk rules
8. Submit paper orders
9. Update local portfolio state

### Reflection and learning phases

Commands:

```bash
python -m agent_trader reflect
python -m agent_trader weekly
python -m agent_trader monthly
python -m agent_trader evolve
```

These phases are how the system learns from its own behavior rather than just producing daily output.

## Where Learning Lives

Each profile has its own memory root:

- `data/profiles/claude/`
- `data/profiles/codex/`

Important subdirectories:

- `cache/` for current working artifacts
- `observations/` for daily, weekly, monthly reflections
- `knowledge/` for distilled lessons, patterns, regime rules, and strategy effectiveness
- `positions/` for active and closed position tracking
- `snapshots/` and runtime files for portfolio/dashboard state

The knowledge loop is:

1. Observe what happened
2. Store it
3. Distill it into compact knowledge
4. Feed that compact knowledge back into future prompts
5. Measure outcomes
6. Propose improvements

## How Context Is Limited

This matters a lot because unlimited memory would become expensive and noisy.

The system limits context in several ways.

### Knowledge is summarized

The app does not dump entire history files into prompts. It builds compressed context from:

- lessons learned
- regime library
- strategy effectiveness
- recent patterns
- recent observations

### Token and size budgets

Key limits in settings include:

- `KNOWLEDGE_TOKEN_BUDGET`
- `OBSERVATIONS_TOKEN_BUDGET`
- `LLM_MAX_PROMPT_CHARS`
- `LLM_MAX_OUTPUT_TOKENS`
- `CLI_AGENT_MAX_TURNS`
- `CLI_AGENT_TIMEOUT`

### External CLI runner budgets

`scripts/run_both.sh` adds extra operational limits for Codex such as:

- max runtime
- max web searches
- max loop/tool cycles
- reasoning effort

That keeps the strategist sessions from wandering indefinitely.

## How to Use It Day to Day

### Local strategist workflow

Use:

```bash
./scripts/run_both.sh morning parallel
./scripts/run_both.sh evening parallel
./scripts/run_both.sh weekly parallel
./scripts/run_both.sh monthly parallel
```

This is your best “visible brain” workflow.

### Local Python runtime workflow

For Claude profile:

```powershell
$env:RUN_MODE="paper"
$env:DATA_DIR="data/profiles/claude"
$env:AGENT_PROFILE="claude"
$env:AGENT_LABEL="Claude Strategist"
$env:USE_CLI_AGENT="true"
$env:CLI_AGENT_PROVIDER="claude"
python -m agent_trader research
python -m agent_trader monitor
```

For Codex profile:

```powershell
$env:RUN_MODE="paper"
$env:DATA_DIR="data/profiles/codex"
$env:AGENT_PROFILE="codex"
$env:AGENT_LABEL="Codex Strategist"
$env:USE_CLI_AGENT="true"
$env:CLI_AGENT_PROVIDER="codex"
python -m agent_trader research
python -m agent_trader monitor
```

### Validation

Use:

```bash
python -m agent_trader validate --data-dir data/profiles/claude
python -m agent_trader validate --data-dir data/profiles/codex
pytest -q
```

## Important Operational Truths

### 1. `run_both.sh` is not the intraday execution engine

It is a strategist orchestration script.

It is excellent for:

- research
- reflection
- side-by-side outputs
- commit/push workflow

It is not the same thing as the Python monitor/execution engine.

### 2. `DATA_DIR` matters

If you run the Python app without setting `DATA_DIR`, it defaults to top-level `data/`.

For profile-specific work, you should set:

- `DATA_DIR`
- `AGENT_PROFILE`
- `AGENT_LABEL`

Otherwise you can accidentally write outside the strategist roots.

### 3. GitHub Actions uses API-only monitoring

This is intentional.

The monitor pass is designed to be a small, cheap API call rather than a full CLI session.
That keeps the intraday loop reliable in GitHub Actions and avoids CLI auth complexity.

### 4. Paper mode is now real paper execution

In the current code, `RUN_MODE=paper` is the correct path for real Alpaca paper trading.

That was not reliably true before the recent fix.

## Is the Python System Good Enough to Execute Trades Right Now?

For paper trading: yes, with caution.

For live trading: no, not yet.

### Why I’m comfortable saying “yes” for paper

The current Python system can:

- collect market/news context
- run strategist analysis
- generate signals
- apply basic risk checks
- submit paper orders to Alpaca
- track portfolio state locally
- persist observations and knowledge

That makes it good enough to start learning in paper mode.

### Why I would still keep expectations grounded

The current execution stack is still early-stage in a few important ways:

1. Orders are simple market orders.
2. Portfolio state is tracked locally and is not yet a full broker-reconciled ledger.
3. Risk controls are solid as a baseline, but still basic compared with a production trading system.
4. There is not yet full duplicate-order prevention, broker-state reconciliation, or sophisticated execution handling.
5. The system is strong as a learning and paper-trading platform, but not yet hardened enough for unattended live trading.

So my honest recommendation is:

`Use it in paper mode now to build evidence and tighten the system. Do not treat it as live-ready yet.`

## Recommended Operating Pattern

For now, the cleanest operating pattern is:

1. Run strategist research with `run_both.sh`
2. Let GitHub Actions or local Python monitor handle the intraday loop
3. Run evening reflection
4. Run weekly/monthly reviews
5. Review evolution proposals before changing logic
6. Validate after changes

## What To Remember Most

- The system has two layers, not one.
- Monitoring still uses a model step.
- CLI success can avoid direct Python LLM API calls, but not model usage entirely.
- External data APIs and Alpaca still remain in the loop.
- The Python runtime is ready for paper-trading learning, not live deployment.
