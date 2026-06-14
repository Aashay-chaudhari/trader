# Agent Trader

Agent Trader is a Codex-driven paper-trading system. Local Codex CLI sessions perform research, reflection, and by default intraday monitoring; Python enforces strategy, risk, execution, persistence, and dashboard generation. GitHub Actions can still run the legacy OpenAI API monitor, but only when explicitly enabled.

## Daily Flow

```text
Operator
  |
  +--> ./scripts/run_both.sh morning
  |       |
  |       v
  |     Local Codex morning research
  |
  +--> ./scripts/run_both.sh monitor
  |       |
  |       +--> Python prepares live market/news context
  |       +--> Local Codex writes local_monitor_decision.json when needed
  |       +--> Runner pushes the uniquely identified decision
  |       +--> GitHub Actions uses Alpaca secrets to run:
  |            strategy -> risk -> execution -> portfolio
  |
  +--> ./scripts/run_both.sh evening/weekly/monthly/evolve
          |
          v
data/profiles/codex -> dashboard -> git push -> GitHub Pages

Optional only:
  MONITOR_RUNTIME=github_actions_api -> GitHub Actions API monitor -> OpenAI gate
```

## Commands

On Windows PowerShell:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning serial
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh monitor serial
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening serial
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh weekly serial
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh monthly serial
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evolve serial
```

The runner discovers Python through `python` or `uv`, prefers the current Codex desktop CLI, validates morning price anchors, regenerates `docs/`, commits, and pushes `HEAD:main`. When WSL Git has no stored GitHub credentials, it automatically retries the push through Windows Git Credential Manager.

## Local Defaults

No local environment variables are required for the standard Codex loop.

```text
Raw Python CLI defaults:
  AGENT_PROFILE=codex
  AGENT_LABEL=Codex Strategist
  DATA_DIR=data/profiles/codex
  MONITOR_RUNTIME=codex_loop
  MONITOR_EXECUTION_OWNER=github_actions
  RUN_MODE=debug

scripts/run_both.sh defaults:
  same profile/data/monitor/execution-owner defaults
  RUN_MODE=paper
```

The split is intentional: an accidental raw Python command remains dry-run, while the operator runner uses real market data and the paper-trading path. Broker submission defaults to GitHub Actions because that is where the Alpaca secrets live. Set `MONITOR_EXECUTION_OWNER=local` only when this machine has its own Alpaca credentials.

GitHub Actions secrets cannot be read back or copied to the local machine. The default local Codex loop does not require `OPENAI_API_KEY`; it pushes the decision and the `Codex Decision Execution` workflow injects the Alpaca paper secrets during deterministic execution.

## Intraday Monitoring

The monitor owner is controlled by `MONITOR_RUNTIME`.

- `codex_loop` is the default. Keep the local long-running Codex terminal loop open for intraday monitoring. Scheduled GitHub Actions runs will skip the API monitor and will not spend OpenAI tokens.
- `github_actions_api` opts back into the old GitHub Actions monitor. Set repository variable `MONITOR_RUNTIME=github_actions_api`, or choose `github_actions_api` in manual workflow dispatch.

When `MONITOR_RUNTIME=codex_loop`, `./scripts/run_both.sh monitor serial`:

- prepares `local_monitor_context.json` and `local_monitor_prompt.md`
- skips the Codex call when market is closed or no candidates need review
- asks local Codex to write `local_monitor_decision.json` when candidates are ready
- stamps the decision with its prepared `run_id`, regenerates the dashboard, commits, and pushes
- triggers `Codex Decision Execution`, which applies strategy, risk, Alpaca paper execution, portfolio, journal, and analytics
- commits the execution outcome and deploys the updated dashboard to GitHub Pages

Alpaca `client_order_id` values are derived from the monitor `run_id`, symbol, action, and order index. A committed `local_monitor_applied.json` marker makes workflow reruns idempotent.

When `MONITOR_RUNTIME=github_actions_api`, the `Trading Pipeline` workflow:

- runs every 30 minutes during the configured weekday market window
- reads `data/profiles/codex/cache/morning_research.json`
- uses OpenAI for the small monitor decision gate
- defaults to `paper` when `MONITOR_RUN_MODE` is unset
- submits only approved paper orders to Alpaca
- commits updated Codex state and deploys `docs/` to GitHub Pages

Required GitHub secrets for `github_actions_api` are `OPENAI_API_KEY` and either the Codex-specific or fallback Alpaca key pair. Market-data keys are optional but improve evidence quality.

The default local-decision handoff does not use `OPENAI_API_KEY`. It requires only `ALPACA_API_KEY_CODEX` plus `ALPACA_SECRET_KEY_CODEX`, or the fallback Alpaca key pair.

## Repository Layout

```text
data/profiles/codex/   Durable strategy, portfolio, knowledge, and interaction state
src/agent_trader/      Deterministic Python runtime
scripts/prompts/       Local phase instructions
scripts/run_both.sh    Local orchestrator
.github/workflows/     Scheduled monitor and Pages deployment
docs/                  Generated GitHub Pages site and published artifacts
tests/                 Unit tests
```

## Validation

```powershell
$env:UV_CACHE_DIR="$PWD\.tmp\uv-cache"
uv run --extra dev python -m pytest -q
uv run --extra dev python -m agent_trader validate --data-dir data/profiles/codex
uv run --extra dev python -m agent_trader dashboard
```

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Current state](CURRENT_STATE.md)
- [Operator weekbook](WEEKBOOK.md)
- [System guide](SYSTEM_GUIDE.md)
- [Coding assistant handoff](CODING_ASSISTANT.md)
- [Prompt flow](docs/PROMPT_FLOW.md)
- [Knowledge architecture](docs/KNOWLEDGE_ARCHITECTURE.md)
