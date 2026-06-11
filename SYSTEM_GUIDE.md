# System Guide

## Operating Model

Agent Trader separates expensive reasoning from deterministic trading operations.

- Local Codex CLI: morning research, evening reflection, weekly review, monthly retrospective, evolution review.
- Python runtime: data collection, candidate selection, strategy voting, risk limits, order submission, journaling, validation, dashboard generation.
- GitHub Actions: scheduled monitor execution, artifact merge, commit, and GitHub Pages deployment.
- Alpaca: paper brokerage execution.
- `data/profiles/codex/`: durable system memory.

## Local Phases

All local phases run through `scripts/run_both.sh`. The historical filename remains for compatibility, but only Codex runs.

| Phase | Prompt | Main outputs |
|---|---|---|
| Morning | `morning_research.md` | research cache, watchlist, interaction log |
| Evening | `evening_reflection.md`, `strategist_voice.md` | observations, knowledge, proposals, voice |
| Weekly | `weekly_review.md` | consolidated lessons and patterns |
| Monthly | `monthly_retrospective.md` | longer-horizon effectiveness updates |
| Evolve | `evolution_review.md` | prioritized system-improvement report |

The morning phase is idempotent. If valid cache files were already written on the local market date, it records a successful skip rather than repeating research.

## Monitor Phase

The monitor reads the pushed morning thesis but does not replace it. It refreshes live evidence, limits the candidate set, asks a low-cost OpenAI model whether execution conditions remain valid, and then passes approved opportunities through deterministic strategy, risk, and execution logic.

`RUN_MODE` behavior:

- `debug`: template decisions and no orders.
- `paper`: real model calls and Alpaca paper orders.
- `live`: reserved for a future live-trading path.

## Publication

Each scheduled workflow run uploads the Codex profile as an artifact. The publish job checks out current `main`, replaces the generated Codex runtime bundle, regenerates `docs/`, commits changed state, and deploys GitHub Pages.

The dashboard exposes:

- morning decisions and trade plans
- monitor outcomes without overwriting the morning thesis
- portfolio and trade history
- market and news context
- local and remote interaction transcripts
- knowledge, strategist voice, proposals, and evolution reports

## Configuration

GitHub Actions requires OpenAI and Alpaca credentials. Optional MarketAux, FRED, Finnhub, Alpha Vantage, and SEC configuration improve context but are not required for the workflow to start.

The important repository variable is `MONITOR_RUN_MODE`. The workflow default is `paper`, so explicitly set it to `debug` when orders must be disabled.

## Failure Boundaries

- Missing or stale morning entries are demoted or rejected before local commit.
- Missing required secrets fail the remote monitor rather than fabricating execution.
- Monitor artifacts are retained for 30 days even when publication fails.
- The publish job runs after monitor completion and records available output.
- GitHub Pages deploys only after publication succeeds.

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.

