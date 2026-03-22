# Agent Trader

Agent Trader is a dual-strategist paper-trading system.

- Heavy research is done locally through `claude` and `codex` CLI subscriptions.
- Intraday monitoring runs in GitHub Actions every 30 minutes during market hours.
- Each strategist writes to its own profile root under `data/profiles/`.
- The Python runtime handles screening, data collection, signal generation, risk checks, execution, journaling, and dashboard output.

The supported operating model is:

1. Run local strategist research in the morning.
2. Push the updated profile files to GitHub.
3. Let GitHub Actions run lightweight monitor checks during the day.
4. Run local evening, weekly, and monthly reflection prompts.
5. Push again so the remote monitor and dashboard keep using current state.

## Architecture

There are two layers.

### 1. Strategist layer

Use `scripts/run_both.sh` to run:

- `claude`
- `codex`

against the prompt files in `scripts/prompts/`.

These sessions do the expensive thinking:

- morning market research
- evening reflection
- weekly review
- monthly retrospective

Outputs are written only to:

- `data/profiles/claude/`
- `data/profiles/codex/`

### 2. Python runtime layer

Use `python -m agent_trader ...` for the app runtime.

This layer powers:

- screening
- market and news data collection
- monitor-time LLM gate
- strategy voting
- risk validation
- Alpaca paper execution
- portfolio tracking
- journaling
- dashboard generation

GitHub Actions runs only the monitor pipeline in normal production use.

## Supported Workflow

### Morning

Run locally:

```bash
./scripts/run_both.sh morning parallel
```

This will:

- pull latest `main`
- run Claude and Codex research locally
- write fresh `morning_research.json` and `watchlist.json` for each profile
- commit and push the updated profile state

Generated files:

- `data/profiles/claude/cache/morning_research.json`
- `data/profiles/claude/cache/watchlist.json`
- `data/profiles/codex/cache/morning_research.json`
- `data/profiles/codex/cache/watchlist.json`

### Intraday monitor

GitHub Actions runs automatically every 30 minutes on weekdays.

The monitor flow:

1. loads the latest pushed profile state
2. refreshes prices and news
3. builds a small candidate set
4. makes a cheap API call only for those candidates
5. lets Python strategy, risk, and execution logic decide the trade

The monitor model is intentionally cheap:

- Claude strategist: `claude-haiku-4-5-20251001`
- Codex strategist: `gpt-4o-mini`

### Evening

Run locally:

```bash
./scripts/run_both.sh evening parallel
```

This will:

- pull the latest monitor updates from GitHub first
- write daily observations and reflections for both profiles
- commit and push the updated state

### Weekly and monthly

Run locally:

```bash
./scripts/run_both.sh weekly parallel
./scripts/run_both.sh monthly parallel
```

These sessions update observations and knowledge files under each profile.

## Data Layout

Tracked long-term memory lives here:

- `data/profiles/<profile>/knowledge/`
- `data/profiles/<profile>/observations/`
- `data/profiles/<profile>/positions/`
- `data/profiles/<profile>/cache/`
- `data/profiles/<profile>/profile.json`

Ignored runtime clutter includes legacy top-level paths such as:

- `data/journal/`
- `data/knowledge/`
- `data/observations/`
- `data/positions/`
- `data/cache/`
- `data/research/`
- `data/snapshots/`

The source of truth is `data/profiles/...`, not top-level `data/...`.

## Configuration

Main settings live in `.env` locally and GitHub Secrets / Variables remotely.

### Core variables

- `RUN_MODE=debug|paper|live`
- `LLM_PROVIDER=auto|anthropic|openai`
- `DATA_DIR`
- `AGENT_PROFILE`
- `AGENT_LABEL`
- `RESEARCH_MODEL`
- `MONITOR_MODEL`
- `RESEARCH_MODEL_OPENAI`
- `MONITOR_MODEL_OPENAI`
- `MONITOR_CANDIDATE_LIMIT`
- `MONITOR_ENTRY_PROXIMITY_PCT`

There is no supported legacy compatibility layer anymore.

Do not use:

- `PRODUCTION_MODE`
- `DEBUG_MODE`
- `DRY_RUN`
- `USE_CLI_AGENT`
- `CLI_AGENT_PROVIDER`
- `CLI_AGENT_MAX_TURNS`
- `CLI_AGENT_TIMEOUT`

## Commands

### Supported day-to-day commands

```bash
./scripts/run_both.sh morning parallel
./scripts/run_both.sh evening parallel
./scripts/run_both.sh weekly parallel
./scripts/run_both.sh monthly parallel
python -m agent_trader monitor
python -m agent_trader validate --data-dir data/profiles/claude
python -m agent_trader validate --data-dir data/profiles/codex
pytest -q
```

### Development utilities

These still exist, but they are not the primary production workflow:

```bash
python -m agent_trader research
python -m agent_trader run
python -m agent_trader reflect
python -m agent_trader weekly
python -m agent_trader monthly
python -m agent_trader evolve
python -m agent_trader cycle
python -m agent_trader reset
python -m agent_trader dashboard
```

## GitHub Actions

The remote workflow now supports one normal job: `monitor`.

What it does:

- runs per strategist profile
- uses provider-specific API keys
- reads the latest pushed profile state
- writes updated runtime artifacts and dashboard data
- commits and pushes the results back to `main`

Heavy research is intentionally not run in Actions because local CLI subscriptions are the cheaper path.

## Setup

1. Copy `.env.example` to `.env`
2. Fill in market data and broker keys
3. Install dependencies

```bash
pip install -e ".[dev]"
```

4. Add GitHub Secrets:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `ALPACA_API_KEY_CLAUDE`
- `ALPACA_SECRET_KEY_CLAUDE`
- `ALPACA_API_KEY_CODEX`
- `ALPACA_SECRET_KEY_CODEX`

5. Add GitHub Variables if desired:

- `MONITOR_MODEL`
- `MONITOR_MODEL_OPENAI`
- `MONITOR_CANDIDATE_LIMIT`

6. Validate locally:

```bash
pytest -q
python -m agent_trader validate --data-dir data/profiles/claude
python -m agent_trader validate --data-dir data/profiles/codex
```

## Current Recommendation

Use the system in `paper` mode to learn and validate behavior.

It is ready for paper-trading tests. It is not yet a live-trading system.

## More Docs

- [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md)
- [CURRENT_STATE.md](CURRENT_STATE.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/KNOWLEDGE_ARCHITECTURE.md](docs/KNOWLEDGE_ARCHITECTURE.md)
