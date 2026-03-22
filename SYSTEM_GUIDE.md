# System Guide

This guide describes the streamlined operating model for Agent Trader.

## Mental Model

There are two systems working together:

1. Local strategist sessions for deep thinking.
2. Python runtime automation for intraday monitoring and execution.

Think of it like this:

`strategists think locally -> profile files are updated -> GitHub monitor reads them -> trades are checked and executed -> observations and knowledge accumulate`

## What Runs Where

### Local machine

You run the heavy phases locally with `scripts/run_both.sh`.

These phases are:

- `morning`
- `evening`
- `weekly`
- `monthly`

Why local:

- you already pay for CLI subscriptions
- strategist output is more visible
- no need to pay for heavy API research in GitHub Actions

### GitHub Actions

GitHub Actions runs only the lightweight intraday monitor.

Why remote:

- it is cheap enough to call a small model periodically
- it can run on a fixed schedule
- it keeps the dashboard and portfolio state moving during market hours

## Supported Architecture

### Strategist layer

Driven by:

- `scripts/run_both.sh`
- prompts in `scripts/prompts/`
- local `claude` CLI
- local `codex` CLI

Responsibilities:

- morning research
- trade plans
- explicit execution conditions
- evening reflection
- weekly review
- monthly review
- knowledge updates written by the prompts

### Python runtime layer

Driven by:

- `python -m agent_trader ...`
- `.github/workflows/trading.yml`

Responsibilities:

- screening
- data refresh
- news refresh
- monitor-time approval gate
- strategy signals
- risk validation
- Alpaca paper execution
- journaling
- dashboard generation

## LLM Usage

### Heavy LLM work

Heavy research happens locally through the strategist CLIs.

That includes:

- market thesis building
- stock selection
- detailed plans
- end-of-day reflection
- weekly and monthly synthesis

### Light LLM work

The intraday monitor uses a small API call.

It is not redoing the morning research.

Its job is narrower:

- check if a planned setup still matches live conditions
- approve or reject a small set of candidates

The monitor should feel like a thin layer of judgment, not a full analyst.

## Monitor Design

The monitor loop is:

1. load latest profile state from `main`
2. refresh market data and headlines
3. build a small candidate set
4. call the cheap model only for those candidates
5. let Python strategy and risk logic decide whether to trade
6. send paper orders through Alpaca when approved

Candidates are limited to symbols that are:

- near entry
- near stop
- near target
- active positions
- showing fresh headlines

## Which Models Are Used

### Morning and reflection phases

These are local CLI sessions, so the subscription-backed CLI decides how the model is accessed.

### Monitor phase

These are API-based in GitHub Actions.

Default cheap monitor models:

- Claude strategist: `claude-haiku-4-5-20251001`
- Codex strategist: `gpt-4o-mini`

That is the current cost-optimized path.

## What Is Tracked In Git

Tracked long-term memory:

- `data/profiles/claude/`
- `data/profiles/codex/`
- `docs/`

Within each profile, the durable memory is:

- `knowledge/`
- `observations/`
- `positions/`
- `cache/`
- `profile.json`

## What Is Not Part Of The Durable Memory Model

Legacy top-level single-root runtime paths are not part of the supported architecture anymore.

Examples:

- `data/journal/`
- `data/knowledge/`
- `data/observations/`
- `data/positions/`
- `data/cache/`
- `data/research/`
- `data/snapshots/`

The source of truth is profile-first.

## How Context Is Limited

The system keeps context small in a few ways.

### 1. Profile knowledge is distilled

The app summarizes prior lessons, patterns, regime rules, and observations before sending them into prompts.

### 2. Prompt budgets are capped

Important settings:

- `KNOWLEDGE_TOKEN_BUDGET`
- `OBSERVATIONS_TOKEN_BUDGET`
- `LLM_MAX_PROMPT_CHARS`
- `LLM_MAX_OUTPUT_TOKENS`

### 3. The monitor sees only a small candidate set

This is the biggest operational cost control.

Instead of evaluating every symbol every 30 minutes, the system only checks the few names that are near action.

## How To Use The System

### Every weekday morning

Run:

```bash
./scripts/run_both.sh morning parallel
```

Expected result:

- strategist cache files are refreshed
- a commit is made
- state is pushed to `main`

Generated files:

- `data/profiles/claude/cache/morning_research.json`
- `data/profiles/claude/cache/watchlist.json`
- `data/profiles/codex/cache/morning_research.json`
- `data/profiles/codex/cache/watchlist.json`

### During the trading day

Let GitHub Actions run the scheduled monitor workflow.

You only need to step in if:

- a workflow fails
- you want to inspect logs
- you want to manually dispatch a monitor run

### Every weekday evening

Run:

```bash
./scripts/run_both.sh evening parallel
```

This will pull the latest remote state first, then write reflections and push again.

### Weekly

Run:

```bash
./scripts/run_both.sh weekly parallel
```

### Monthly

Run:

```bash
./scripts/run_both.sh monthly parallel
```

## Core Commands

### Supported production workflow

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

### Secondary developer utilities

These remain available, but they are not the normal production path:

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

## Configuration You Still Need

### Local `.env`

Important keys:

- `RUN_MODE`
- `LLM_PROVIDER`
- `DATA_DIR`
- `AGENT_PROFILE`
- `AGENT_LABEL`
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- data/news provider keys

### GitHub Secrets

Required for the monitor workflow:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `ALPACA_API_KEY_CLAUDE`
- `ALPACA_SECRET_KEY_CLAUDE`
- `ALPACA_API_KEY_CODEX`
- `ALPACA_SECRET_KEY_CODEX`

### GitHub Variables

Useful but optional:

- `MONITOR_MODEL`
- `MONITOR_MODEL_OPENAI`
- `MONITOR_CANDIDATE_LIMIT`

## Variables That Are No Longer Part Of The Design

These should be considered removed from the supported workflow:

- `PRODUCTION_MODE`
- `DEBUG_MODE`
- `DRY_RUN`
- `USE_CLI_AGENT`
- `USE_CLI_AGENT_FOR_MONITOR`
- `CLI_AGENT_PROVIDER`
- `CLI_AGENT_MAX_TURNS`
- `CLI_AGENT_TIMEOUT`
- `debug_max_stocks`
- `debug_skip_web`

The streamlined model is:

- local CLI for heavy strategist work
- API-only monitor in Actions
- `RUN_MODE` as the single execution control

## What Paper Mode Means

`RUN_MODE=paper` now means:

- real model calls where the runtime uses a model
- real Alpaca paper order submission
- full Python execution path

`RUN_MODE=debug` means:

- template responses
- no broker orders
- reduced-cost testing

## Current Readiness

The system is ready for paper-trading tests.

It is not live-trading ready.

Why paper-ready:

- monitor is lightweight and bounded
- strategy, risk, and execution are code-driven
- profile state is separated by strategist
- validation and tests exist

Why not live-ready:

- execution handling is still basic
- reconciliation is still light
- safeguards are not yet at true production-trading depth

## One Sentence Summary

Use local CLI sessions for the thinking, GitHub Actions for the cheap intraday checks, and treat `data/profiles/...` as the durable memory of the system.
