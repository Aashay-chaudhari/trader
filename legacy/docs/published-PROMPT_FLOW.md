# Prompt Flow

## Overview

```mermaid
flowchart LR
    M[Morning research] --> Monitor[Intraday monitor]
    Monitor --> E[Evening reflection]
    E --> W[Weekly review]
    W --> Month[Monthly retrospective]
    E --> Backlog[Improvement backlog]
    Backlog --> Evo[Evolution review]
```

All local prompts operate on `data/profiles/codex/`. The runner substitutes `{{PROFILE}}` with `codex`, captures the prompt and transcript, writes interaction metadata, regenerates the dashboard, commits, and pushes.

## Morning Research

Command: `./scripts/run_both.sh morning parallel`

Reads portfolio state, knowledge, recent observations, and the prior watchlist. Writes `cache/morning_research.json`, `cache/watchlist.json`, and interaction files. Same-day valid cache triggers an idempotent skip. The runner validates price anchors before commit.

## Intraday Monitor

Trigger: scheduled or manual GitHub Actions run.

Reads the pushed morning thesis and live evidence. The monitor gate may confirm, weaken, or reject a setup, but it does not replace the morning thesis. Strategy, risk, and execution remain deterministic Python layers.

## Evening Reflection

Command: `./scripts/run_both.sh evening parallel`

Reads the morning plan, monitor reports, trades, portfolio state, and knowledge. Writes daily observations, lesson and pattern updates, improvement proposals, strategist voice, and interaction files.

## Weekly and Monthly Reviews

```bash
./scripts/run_both.sh weekly parallel
./scripts/run_both.sh monthly parallel
```

These phases consolidate evidence at longer horizons and update durable knowledge without replacing history.

## Evolution Review

Command: `./scripts/run_both.sh evolve parallel`

Reads the proposal backlog, observations, knowledge, and runtime evidence. Writes `evolution_review.json` and `EVOLUTION_REPORT.md` with prioritized engineering recommendations.

