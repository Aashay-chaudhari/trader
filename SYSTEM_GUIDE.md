# System Guide

## Operating Model

Agent Trader separates expensive reasoning from deterministic trading operations.

- Local Codex CLI: morning research, evening reflection, weekly review, monthly retrospective, evolution review.
- Python runtime: data collection, candidate selection, strategy voting, risk limits, order submission, journaling, validation, dashboard generation.
- GitHub Actions: CI, reminders, repository-secret paper execution, dashboard publication, and optional scheduled API monitor execution.
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

The monitor reads the pushed morning thesis but does not replace it. The runtime owner is controlled by `MONITOR_RUNTIME`.

- `codex_loop` is the default. A local long-running Codex terminal session owns intraday reasoning. The runner pushes each ready decision, then the `Codex Decision Execution` workflow uses repository Alpaca secrets for deterministic strategy, risk, paper execution, persistence, and dashboard generation.
- `github_actions_api` opts into the legacy scheduled GitHub Actions monitor. It refreshes live evidence, limits the candidate set, asks a low-cost OpenAI model whether execution conditions remain valid, and then passes approved opportunities through deterministic strategy, risk, and execution logic.

`RUN_MODE` behavior:

- `debug`: template decisions and no orders.
- `paper`: real model calls and Alpaca paper orders.
- `live`: reserved for a future live-trading path.

## Publication

When `MONITOR_RUNTIME=github_actions_api`, each scheduled workflow run uploads the Codex profile as an artifact. The publish job checks out current `main`, replaces the generated Codex runtime bundle, regenerates `docs/`, commits changed state, and deploys GitHub Pages. When `MONITOR_RUNTIME=codex_loop`, scheduled API-monitor runs skip, while local decision pushes trigger deterministic paper execution and publication without an OpenAI API call.

The dashboard exposes:

- morning decisions and trade plans
- monitor outcomes without overwriting the morning thesis
- portfolio and trade history
- market and news context
- local and remote interaction transcripts
- knowledge, strategist voice, proposals, and evolution reports

## Configuration

GitHub Actions requires OpenAI and Alpaca credentials only when `MONITOR_RUNTIME=github_actions_api`. Optional MarketAux, FRED, Finnhub, Alpha Vantage, and SEC configuration improve context but are not required for the workflow to start.

The important repository variable is `MONITOR_RUNTIME`. The default is `codex_loop`, which avoids scheduled OpenAI API monitor calls. `MONITOR_EXECUTION_OWNER=github_actions` is the local runner default and routes ready decisions to repository-secret paper execution. Set `MONITOR_RUNTIME=github_actions_api` only when the GitHub workflow should spend API tokens for monitoring. `MONITOR_RUN_MODE` still controls `debug`, `paper`, or `live` behavior inside the API monitor after it is enabled.

## Failure Boundaries

- Missing or stale morning entries are demoted or rejected before local commit.
- Missing required secrets fail the remote API monitor rather than fabricating execution.
- Monitor artifacts are retained for 30 days even when publication fails.
- The publish job runs after monitor completion and records available output.
- GitHub Pages deploys only after publication succeeds.

## Fresh-Start Boundary

`python -m agent_trader reset --docs --fresh-start-date YYYY-MM-DD` clears one
profile's generated application state and writes a dated baseline marker. The
guarded wrapper is `./scripts/reset_for_fresh_start.sh YYYY-MM-DD RESET`; the
same operation is available through the `Reset Application State` workflow.

This does not erase Alpaca activity. Alpaca's current paper-account reset model
is to create a new paper account, generate new keys, update GitHub secrets, and
optionally delete the old account. The `Verify Alpaca Paper Account` workflow
checks the configured account read-only and fails when open positions or orders
remain.

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.
