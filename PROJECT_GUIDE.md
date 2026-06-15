# Agent Trader Project Guide

Last reviewed: 2026-06-14

This guide documents the current implementation, the intended model, what is manual, what GitHub Actions does, and where the documentation is or is not consistent with the code. Diagrams are plain text only.

## Executive Summary

Agent Trader is a Codex/GPT-centered paper-trading research and monitoring system.

The project models one active strategist profile, `codex`, with a durable memory store under `data/profiles/codex/`. Local Codex CLI sessions create the richer morning and review artifacts and own intraday reasoning by default through `MONITOR_RUNTIME=codex_loop`. Python owns deterministic data collection, strategy voting, risk checks, execution, journaling, validation, and dashboard generation. For ready monitor decisions, GitHub Actions owns broker submission by default through `MONITOR_EXECUTION_OWNER=github_actions`, because that is where the Alpaca secrets are available. The legacy OpenAI API monitor remains opt-in through `MONITOR_RUNTIME=github_actions_api`.

Intraday prices use a guarded two-stage path. The local monitor reads a
timestamped Yahoo one-minute bar and refuses stale market-hours snapshots. The
GitHub execution job then refreshes selected symbols from Alpaca's real-time IEX
trade/quote feed immediately before strategy, risk sizing, and paper orders.

GPT/OpenAI is enabled in implementation, but the scheduled monitor is opt-in:

- GitHub Actions sets `LLM_PROVIDER=openai` and `MONITOR_LLM_PROVIDER=openai` only in the API monitor job.
- `OPENAI_API_KEY` is passed to the monitor workflow only when `MONITOR_RUNTIME=github_actions_api`.
- `settings.py` has OpenAI model settings for research and monitor phases.
- The monitor default model is `gpt-4o-mini`, overridable with `MONITOR_MODEL_OPENAI`.

Important nuance: local scripted research is not the same path as the GitHub monitor. `scripts/run_both.sh` invokes the Codex CLI with phase prompts. The Python CLI can also run research directly through `python -m agent_trader research`, but the documented operator flow uses Codex CLI plus validation and push.

## Responsibility Segregation

### AI Agent Handled

```text
Codex CLI
  +-- searches and interprets public market/news evidence for morning research
  +-- writes the morning thesis, watchlist, trade plans, and execution conditions
  +-- evaluates prepared intraday candidates against those conditions
  +-- writes local_monitor_decision.json
  +-- performs evening reflection and weekly/monthly/evolution reviews
  +-- writes human-readable reasoning, lessons, and proposals
```

The AI recommends and explains. It does not bypass the Python strategy and risk pipeline to submit an order. However, the current local runner gives Codex workspace write access, so local files available to the Codex process are part of the trusted AI boundary.

### Exposed Interfaces and External Systems

```text
Public/input side:
  market prices, volume, indicators, headlines, filings, macro data

Broker/integration side:
  Alpaca paper API
  GitHub repository, Actions, artifacts, and Pages
  optional OpenAI API monitor
  optional MarketAux, FRED, Finnhub, Alpha Vantage, SEC, ntfy/Twilio

Operator-visible outputs:
  data/profiles/codex/cache
  research, context, interactions, journal, analytics, snapshots
  docs/ dashboard
  git commits and GitHub Actions logs
```

GitHub Actions secrets are injected only inside Actions jobs and cannot be read back by the local application. The local Codex gate therefore pushes its decision to `main`; the `Codex Decision Execution` workflow injects the Alpaca secrets, applies the deterministic pipeline, commits the outcome, and deploys Pages. Local submission is still available with `MONITOR_EXECUTION_OWNER=local` and local credentials.

### Deterministic Python Handled

```text
Settings and profile resolution
  -> choose codex profile, data directory, run mode, runtime owner

DataAgent / NewsAgent
  -> fetch and normalize machine-readable evidence

ResearchAgent monitor helpers
  -> select candidates near entry, stop, target, fresh-news, or active-position checks

StrategyAgent
  -> calculate strategy votes and produce structured signals

RiskAgent
  -> approve/reject signals using configured numerical limits

ExecutionAgent
  -> dry-run or submit an Alpaca paper order

PortfolioAgent
  -> update ledger, positions, P&L, and snapshots

Utilities
  -> schema validation, stale-price checks, journaling, telemetry, dashboard generation
```

The shell runner deterministically sequences these components, invokes Codex only at the reasoning steps, and commits/pushes each completed phase.
If WSL Git cannot authenticate the push, the runner retries through Windows Git Credential Manager automatically.

## What You Have Modeled

You have modeled a trading desk with six loops:

```text
1. Discover      -> find stocks with news, volume, momentum, and catalysts
2. Research      -> produce morning thesis, watchlist, trade plans, and evidence
3. Monitor       -> check live prices/news against morning execution conditions
4. Execute       -> strategy vote, risk approval, Alpaca paper order, portfolio update
5. Reflect       -> convert the day into observations, lessons, proposals, and voice
6. Evolve        -> consolidate longer-term evidence into system improvement ideas
```

The core design is a feedback loop:

```text
Market/news data
      |
      v
Morning thesis + watchlist
      |
      v
Intraday monitor decisions
      |
      v
Trades, rejects, portfolio snapshots
      |
      v
Journal + observations + knowledge
      |
      v
Future prompts become more informed
```

## System Architecture

```text
Operator
  |
  | local phase commands
  v
scripts/run_both.sh
  |
  +--> Codex CLI phase prompts
  |       |
  |       +--> morning thesis
  |       +--> monitor decision JSON when candidates need review
  |       +--> evening/weekly/monthly/evolution reviews
  |
  +--> Python runtime
          |
          +--> market/news collection
          +--> strategy and risk preparation
          +--> journal, validation, dashboard
  |
  | writes profile artifacts
  v
data/profiles/codex/
  |
  | dashboard generation + git push
  v
GitHub main
  |
  +--> local monitor decision
  |       |
  |       v
  |     Codex Decision Execution
  |       +--> StrategyAgent -> RiskAgent -> ExecutionAgent -> Alpaca paper
  |       +--> PortfolioAgent -> artifacts -> commit
  |       +--> deploy GitHub Pages
  |
  +--> docs/ -> Publish Dashboard -> GitHub Pages dashboard
  |
  +--> Optional GitHub Actions API monitor
          only when MONITOR_RUNTIME=github_actions_api
          |
          +--> yfinance/news/FRED/SEC/etc.
          +--> OpenAI monitor gate
          +--> StrategyAgent
          +--> RiskAgent
          +--> ExecutionAgent -> Alpaca paper
          +--> PortfolioAgent
          +--> commits generated state
  |
```

## ER-Style Data Model

```text
[StrategistProfile]
  id = codex
  label = Codex Strategist
  data_dir = data/profiles/codex
        |
        | owns
        v
[MorningResearchCache]
  cache/morning_research.json
  cache/watchlist.json
        |
        | selects many
        v
[SymbolPlan]
  symbol
  recommendation
  confidence
  execution_condition
  trade_plan(entry, stop_loss, target, size, timeframe)
  supporting_articles[]
        |
        | evaluated by many
        v
[MonitorContext]
  context/<date>_monitor_<time>.json
  prompt_sections
  prompt_text
  llm_meta
        |
        | produces
        v
[MonitorDecision]
  research/<date>_monitor_<time>.json
  ready_to_trade
  matched_conditions[]
  failed_conditions[]
        |
        | feeds
        v
[TradeSignal]
  symbol
  action
  strength
  strategy
  reasoning
  suggested_size_pct
        |
        | checked by
        v
[RiskDecision]
  approved_trades[]
  rejected_trades[]
  rejection_reasons[]
        |
        | executed as
        v
[ExecutionRecord]
  status = dry_run | submitted | failed
  quantity
  estimated_price
  order_id
        |
        | updates
        v
[PortfolioState]
  portfolio_state.json
  snapshots/latest.json
  snapshots/history.json
        |
        | summarized by
        v
[JournalEntry]
  journal/<date>/<time>_<phase>_report.md
  journal/<date>/<time>_<phase>_report.json

[JournalEntry] -> [DailyObservation] -> [WeeklyReview] -> [MonthlyReview]
                                  \       |              |
                                   \      v              v
                                    -> [KnowledgeStore] <-

[KnowledgeStore]
  knowledge/lessons_learned.json
  knowledge/patterns_library.json
  knowledge/strategy_effectiveness.json
  knowledge/regime_library.json
  observations/daily/*.json
  observations/weekly/*.json
  observations/monthly/*.json
```

## Runtime Components

```text
src/agent_trader/
  cli.py                  command entrypoint
  runner.py               builds orchestrator and registered agents
  core/orchestrator.py    phase choreography and journal writing
  core/message_bus.py     lightweight event/message layer
  agents/
    screener_agent.py     universe scan and news+technical shortlist
    data_agent.py         yfinance prices, fundamentals, indicators
    news_agent.py         yfinance/RSS/Marketaux/SEC/FRED/Finnhub/Alpha Vantage
    research_agent.py     OpenAI/Anthropic model calls, prompts, telemetry, learning phases
    strategy_agent.py     deterministic strategy ensemble
    risk_agent.py         signal strength, size, price, volume checks
    execution_agent.py    dry-run or Alpaca paper/live order submission
    portfolio_agent.py    positions, P&L, snapshots
  dashboard/              static dashboard generator and template
  utils/                  validation, knowledge, journal, alerts, state reset, telemetry
```

## Command Surface

Python CLI:

```text
python -m agent_trader research [--symbols ...] [--debug]
python -m agent_trader monitor [--symbols ...] [--debug]
python -m agent_trader monitor-local-prepare [--symbols ...] [--debug]
python -m agent_trader monitor-local-apply [--debug]
python -m agent_trader run [--symbols ...] [--debug]
python -m agent_trader cycle [--symbols ...] [--debug]
python -m agent_trader reflect [--debug]
python -m agent_trader weekly [--debug]
python -m agent_trader monthly [--debug]
python -m agent_trader evolve [--debug]
python -m agent_trader validate [--smoke] [--data-dir ...]
python -m agent_trader dashboard
python -m agent_trader status
python -m agent_trader reset [--all-profiles] [--docs] [--keep-knowledge] [--fresh-start-date YYYY-MM-DD]
python -m agent_trader alert morning|evening|weekly|monthly|test
```

Operator runner:

```text
./scripts/run_both.sh morning serial
./scripts/run_both.sh monitor serial
./scripts/run_both.sh evening serial
./scripts/run_both.sh weekly serial
./scripts/run_both.sh monthly serial
./scripts/run_both.sh evolve serial
./scripts/reset_for_fresh_start.sh YYYY-MM-DD RESET
```

The `parallel` argument is now historical. Claude is disabled in the runner, so it prints that parallel mode was requested but runs Codex only.

## Manual Local Workflow

Morning:

```text
1. Pull latest main.
2. Run scripts/run_both.sh morning serial.
3. Runner injects scripts/prompts/morning_research.md into Codex CLI.
4. Codex writes profile artifacts, especially cache/morning_research.json.
5. Runner validates stale/invalid morning price anchors.
6. Runner regenerates docs/ dashboard bundles.
7. Runner commits data/profiles/codex/, docs/, and WEEKBOOK.md.
8. Runner pushes HEAD:main.
```

Monitor:

```text
1. Run scripts/run_both.sh monitor serial.
2. Runner prepares local_monitor_context.json and local_monitor_prompt.md.
3. If no symbols need review, runner skips the Codex call and writes a monitor-skip artifact.
4. If symbols need review, Codex writes local_monitor_decision.json.
5. Runner applies that decision through strategy, risk, execution, portfolio, journal, dashboard, commit, and push.
```

Evening:

```text
1. Run scripts/run_both.sh evening serial.
2. Codex runs evening_reflection.md.
3. Runner also runs strategist_voice.md.
4. Outputs include observations, knowledge changes, proposals, voice artifacts, transcripts.
5. Dashboard is regenerated and changes are pushed.
```

Weekly, monthly, evolution:

```text
weekly  -> consolidate recent observations and update knowledge
monthly -> longer retrospective and lesson consolidation
evolve  -> review evidence and produce engineering/system proposals
```

Useful local validation:

```text
python -m pytest tests/unit -v --tb=short
ruff check src/
python -m agent_trader validate --data-dir data/profiles/codex
python -m agent_trader validate --smoke --data-dir data/profiles/codex
python -m agent_trader dashboard
```

## GitHub Actions Workflow

### Tests

`.github/workflows/tests.yml`

```text
Trigger: push to main, pull_request
Steps:
  checkout
  setup Python 3.12
  pip install -e ".[dev]"
  pytest tests/unit -v --tb=short
  ruff check src/
```

### Smoke Test

`.github/workflows/smoke-test.yml`

```text
Trigger: PR to main when src/, tests/, or pyproject.toml changes
Steps:
  unit tests
  ruff
  RUN_MODE=debug python -m agent_trader research --debug
  RUN_MODE=debug python -m agent_trader monitor --debug
  python -m agent_trader dashboard
```

### Trading Pipeline

`.github/workflows/trading.yml`

```text
Trigger:
  scheduled every 30 minutes across weekday market window
  manual workflow_dispatch

Job 1: strategist-run
  skipped by default while MONITOR_RUNTIME=codex_loop
  runs only when MONITOR_RUNTIME=github_actions_api
  checkout latest code
  install package
  optionally reset data/profiles/codex on manual dispatch
  print runtime config
  run python -m agent_trader monitor
  run python -m agent_trader.utils.check_mode
  upload data/profiles/codex as artifact

Job 2: publish-results
  checkout main
  pull latest
  optionally reset all profiles/docs on manual dispatch
  remove old generated profile bundles
  download Codex monitor artifact
  run python -m agent_trader dashboard
  commit data/profiles and docs changes
  push to main

Job 3: deploy-dashboard
  checkout main
  upload docs/ as Pages artifact
  deploy GitHub Pages
```

Monitor environment:

```text
MONITOR_RUNTIME = codex_loop by default, github_actions_api to enable scheduled API monitoring
RUN_MODE = vars.MONITOR_RUN_MODE or paper
LLM_PROVIDER = openai
MONITOR_LLM_PROVIDER = openai
MONITOR_MODEL_OPENAI = vars.MONITOR_MODEL_OPENAI or gpt-4o-mini
DATA_DIR = data/profiles/codex
AGENT_PROFILE = codex
AGENT_LABEL = Codex Strategist
```

Required secrets for github_actions_api:

```text
OPENAI_API_KEY
ALPACA_API_KEY_CODEX or ALPACA_API_KEY
ALPACA_SECRET_KEY_CODEX or ALPACA_SECRET_KEY
```

### Codex Decision Execution

`.github/workflows/local-monitor-execution.yml`

```text
Trigger:
  push to main changing local_monitor_decision.json
  manual workflow_dispatch for recovery/testing

Steps:
  validate the Alpaca key pair exists
  run monitor-local-apply with RUN_MODE=paper
  require local_monitor_applied.json status=completed
  generate the dashboard
  commit profile, journal, portfolio, analytics, and docs artifacts
  upload a 30-day execution artifact
  deploy the resulting docs/ bundle to GitHub Pages
```

This workflow does not use an LLM API. Alpaca client order IDs are derived from
the decision run ID, and a completed applied marker prevents duplicate order
submission when a workflow is rerun.

Required secrets:

```text
ALPACA_API_KEY_CODEX or ALPACA_API_KEY
ALPACA_SECRET_KEY_CODEX or ALPACA_SECRET_KEY
```

### Publish Dashboard

`.github/workflows/pages.yml`

```text
Trigger: any local push to main that changes docs/, or manual dispatch
Action: upload docs/ and deploy GitHub Pages
```

The decision-execution workflow deploys Pages itself because commits made by a
workflow's built-in token do not trigger another push workflow. Morning,
evening, weekly, monthly, and evolution pushes use `Publish Dashboard`.

### Reset Application State

`.github/workflows/reset-application.yml`

```text
Trigger: manual workflow_dispatch only
Inputs: start_date=YYYY-MM-DD and confirmation=RESET
Action:
  remove generated Codex profile and docs state
  write fresh_start.json
  regenerate an empty dashboard
  commit the baseline
  deploy GitHub Pages
```

### Verify Alpaca Paper Account

`.github/workflows/verify-paper-account.yml`

```text
Trigger: manual workflow_dispatch only
Action:
  connect to the configured Alpaca paper account read-only
  print masked account, status, cash, equity, and buying power
  require zero open positions and zero open orders
```

Optional evidence-quality secrets:

```text
MARKETAUX_API_KEY
FRED_API_KEY
SEC_EDGAR_USER_AGENT
FINNHUB_API_KEY
ALPHA_VANTAGE_API_KEY
```

### Reminders

`.github/workflows/reminders.yml`

```text
Trigger:
  morning reminder
  evening reminder
  weekly reminder
  monthly reminder
  manual dispatch

Action:
  installs package
  calls agent_trader.utils.alerts.alert_reminder(phase)
```

This workflow sends reminders. It does not run the local Codex research/reflection phases for you.

## End-to-End Monitor Flow

```text
cache/watchlist.json + cache/morning_research.json
       |
       v
./scripts/run_both.sh monitor serial
       |
       +--> python -m agent_trader monitor-local-prepare
       |       |
       |       +--> load active portfolio symbols
       |       +--> DataAgent refreshes prices
       |       +--> NewsAgent refreshes headlines and regime context
       |       +--> ResearchAgent selects monitor candidates without API LLM call
       |       |
       |       +--> if no candidate near triggers: skip Codex call
       |       +--> else write local_monitor_prompt.md
       |
       +--> local Codex CLI writes local_monitor_decision.json when needed
       |
       +--> stamp prepared run_id, dashboard generation, commit, push
               |
               v
       Codex Decision Execution workflow
               +--> validate repository Alpaca paper secrets
               +--> python -m agent_trader monitor-local-apply
               +--> save monitor context/analytics/research artifact
               +--> StrategyAgent requires ready_to_trade for new monitor entries
               +--> RiskAgent checks signal strength, position size, price move, volume
               +--> ExecutionAgent submits approved Alpaca paper orders
               +--> PortfolioAgent records trades and snapshots
               +--> Journal and local_monitor_applied.json are written
               +--> Dashboard generation, commit, Pages deployment

Optional GitHub Actions API monitor:
       |
       +--> Orchestrator.run_monitor_phase
       +--> ResearchAgent selects monitor candidates
       +--> if candidate exists, OpenAI JSON decision gate
       +--> same strategy/risk/execution/portfolio path
       |
```

## Run Modes

```text
debug:
  template model responses
  no broker orders
  smaller scope
  useful for tests and smoke checks

paper:
  real model calls
  Alpaca paper orders when trades are approved
  local Codex decisions submit through GitHub Actions by default
  API monitor submission also works after MONITOR_RUNTIME=github_actions_api is selected

live:
  code path exists for broker paper=False
  effectively reserved and should be treated as future/high-risk
```

## GPT/OpenAI Consistency Check

Consistent:

```text
Implementation:
  settings.py defines openai_api_key, research_model_openai, monitor_model_openai.
  ResearchAgent supports OpenAI chat completions with JSON response format.
  settings.py defines monitor_runtime with default codex_loop.
  trading.yml skips the API monitor by default.
  trading.yml forces LLM_PROVIDER=openai and MONITOR_LLM_PROVIDER=openai only when github_actions_api is selected.
  README.md and SYSTEM_GUIDE.md document MONITOR_RUNTIME.

Expected behavior:
  Default scheduled workflow does not spend OpenAI monitor tokens.
  GitHub monitor runs through OpenAI only when MONITOR_RUNTIME=github_actions_api and OPENAI_API_KEY is configured.
```

Nuances:

```text
settings.py default llm_provider is auto, not openai.
Local direct Python research may choose Anthropic first if both Anthropic and OpenAI keys exist and LLM_PROVIDER is unset.
Monitor preference is explicitly openai by default via monitor_llm_provider.
The orchestrator display label uses llm_provider for both research and monitor labels, so if llm_provider is auto but monitor_llm_provider is openai, the console label can say "auto provider" even when ResearchAgent resolves monitor to OpenAI.
```

In short: GPT/OpenAI support remains available, but the default monitor owner is now the local Codex loop. The GitHub/OpenAI monitor is a deliberate opt-in path.

## Documentation Consistency Notes

Mostly consistent:

```text
README.md correctly describes local Codex reasoning plus GitHub-secret broker execution.
SYSTEM_GUIDE.md matches the current Codex-only operating model.
CURRENT_STATE.md matches the recent shift to Codex-only GitHub monitor and OpenAI monitor gate, but it is dated 2026-06-11.
```

Inconsistent or stale:

```text
ARCHITECTURE.md still references two-strategist dashboard language in places through dashboard UI text, but generator.py ignores the old claude profile.
docs/PROMPT_FLOW.md says local morning writes cache artifacts through the prompt flow; that is true at the operator level, but the actual mechanism is Codex CLI writing files, followed by runner validation.
ResearchAgent docstrings still describe Claude as the main research edge, but implementation now supports OpenAI and GitHub monitor forces OpenAI.
Some comments mention SMS while alerts implementation supports ntfy/Twilio-style reminders; the user-facing workflows are clearer than a few older comments.
```

## Safety Boundaries

```text
Execution only receives RiskAgent-approved trades.
debug mode never submits orders.
paper mode uses Alpaca paper unless RUN_MODE=live.
Monitor does not invent a new watchlist; it evaluates morning plans and active positions.
Morning validation can demote stale entries before local commit.
GitHub monitor skips outside market hours unless debug/dry-run mode bypasses the guard.
Provider telemetry and prompt context are archived for auditability.
```

## Project Sections

```text
.github/workflows/
  CI, smoke tests, reminders, local-decision paper execution, optional API monitor, Pages deployment

scripts/
  local Codex phase runner, news utility scripts, phase prompt files

src/agent_trader/
  Python package for CLI, agents, orchestration, dashboard, utilities

tests/
  unit tests for agents, runner, validation, dashboard, knowledge, journal, etc.

data/profiles/codex/
  live durable strategist memory and runtime state

docs/
  generated static dashboard and exported JSON/Markdown bundles for GitHub Pages

top-level docs
  README, architecture notes, current state, weekbook, assistant handoffs
```

## Operational Checklist

Before market:

```text
1. Run morning local Codex flow.
2. Confirm it pushed to main.
3. Confirm cache/morning_research.json and cache/watchlist.json exist.
4. Confirm GitHub secrets are present.
5. Confirm MONITOR_RUNTIME is codex_loop or github_actions_api intentionally.
6. Confirm MONITOR_EXECUTION_OWNER=github_actions for repository-secret submission.
7. If using github_actions_api, confirm MONITOR_RUN_MODE is paper or debug intentionally.
```

During market:

```text
1. Keep the local Codex terminal loop running when MONITOR_RUNTIME=codex_loop.
2. Run ./scripts/run_both.sh monitor serial every 30 minutes during market hours.
3. Watch `Codex Decision Execution`; success means the deterministic pipeline completed and its commit was pushed.
4. If MONITOR_RUNTIME=github_actions_api, the separate scheduled API monitor runs every 30 minutes.
5. Watch `Publish Dashboard` and the GitHub Pages site for morning/evening/review updates.
6. Inspect the uploaded execution artifact if a handoff fails.
```

After market:

```text
1. Run evening local Codex flow.
2. Review generated observations, journal, and dashboard.
3. Run weekly/monthly/evolve when appropriate.
```

After code changes:

```text
1. python -m pytest tests/unit -v --tb=short
2. ruff check src/
3. python -m agent_trader validate --data-dir data/profiles/codex
4. python -m agent_trader dashboard
```

## Hard Reset and New Tracking Era

Application state and broker state are separate:

```text
Application hard reset
  deletes generated research, monitoring, portfolio, journal, interactions,
  analytics, observations, knowledge, positions, voice, evolution, and docs data
  preserves code and documentation
  writes data/profiles/codex/fresh_start.json

Alpaca hard reset
  cannot erase selected trades from the existing paper account
  requires a new paper account for a genuinely blank history and balance
```

Recommended order:

```text
1. In Alpaca, open a new paper account.
2. Generate its API key and secret.
3. Replace ALPACA_API_KEY_CODEX and ALPACA_SECRET_KEY_CODEX in GitHub Actions secrets.
4. Run Verify Alpaca Paper Account and require zero positions/orders.
5. Delete the old Alpaca paper account if it is no longer needed.
6. Run ./scripts/reset_for_fresh_start.sh YYYY-MM-DD RESET, or dispatch Reset Application State.
7. On the start date, open Codex in the repository and tell it to read and
   execute `scripts/prompts/codex_day_loop_master.md` as the long-running
   trading-day supervisor. Do not paste the entire file into chat.
```

The reset removes old artifacts from the current branch and dashboard, but Git
commits remain an audit trail. Completely purging prior files from Git history is
a separate destructive history rewrite and is not required for a clean new run.

## Quick Mental Model

```text
Codex creates the thesis.
The local Codex loop checks the thesis by default.
GitHub Actions submits approved local decisions with repository Alpaca secrets.
OpenAI gates intraday execution only when the GitHub API monitor is explicitly enabled.
Python enforces the rules.
Alpaca paper records the attempted execution.
The journal explains what happened.
The knowledge base remembers what mattered.

For the exact daily schedule, published Pages sections, and the boundary between
automatic learning and reviewed code changes, see `docs/OPERATIONS.md`.
The dashboard makes the whole loop inspectable.
```
