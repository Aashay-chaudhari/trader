# Architecture

## System Context

```text
Operator
  |
  | local morning / monitor / review commands
  v
scripts/run_both.sh
  |
  +--> Local Codex CLI
  |       |
  |       +--> morning thesis, monitor decision, reflections, reviews
  |
  +--> Python runtime
          |
          +--> market/news data
          +--> strategy votes
          +--> risk approval
          +--> portfolio snapshots
          +--> journal and dashboard generation
  |
  v
data/profiles/codex
  |
  v
GitHub main
  |
  +--> local_monitor_decision.json -> Codex Decision Execution
  |       -> strategy -> risk -> Alpaca paper -> portfolio -> commit
  |
  +--> docs/ -> Publish Dashboard -> GitHub Pages

Optional path:
  GitHub Actions scheduled monitor
    runs only when MONITOR_RUNTIME=github_actions_api
    uses OpenAI monitor gate and Alpaca paper execution
```

## Runtime Components

```text
MorningResearchCache
  |
  v
Monitor context preparation
  |
  +--> DataAgent
  +--> NewsAgent
  +--> ResearchAgent candidate selector, no API call
  |
  v
Local Codex monitor gate
  |
  v
local_monitor_decision.json
  |
  v
git push to main
  |
  v
Codex Decision Execution (GitHub Actions, repository Alpaca secrets)
  |
  v
StrategyAgent -> RiskAgent -> ExecutionAgent -> PortfolioAgent
  |
  v
Journal + research archive + analytics + dashboard
```

## Durable State

```text
data/profiles/codex/
  |
  +-- cache/
  |     +-- morning_research.json
  |     +-- watchlist.json
  |     +-- local_monitor_context.json
  |     +-- local_monitor_prompt.md
  |     +-- local_monitor_decision.json
  |     +-- local_monitor_applied.json
  |
  +-- context/
  |     +-- latest_monitor.json
  |
  +-- interactions/
  |     +-- prompt, transcript, metadata per phase
  |
  +-- journal/
  |     +-- timestamped phase reports
  |
  +-- research/
  |     +-- timestamped research and monitor outputs
  |
  +-- analytics/
  |     +-- LLM/runtime usage metadata
  |
  +-- snapshots/ and portfolio_state.json
  |
  +-- knowledge/, observations/, voice/, evolution/
```

## Local Monitor Workflow

```text
./scripts/run_both.sh monitor serial
  |
  v
python -m agent_trader monitor-local-prepare
  |
  +-- market closed?       -> write skipped context, no Codex call
  +-- no candidates?       -> write no-candidate context, no Codex call
  +-- candidates present?  -> write local monitor prompt
                              |
                              v
                          Codex CLI writes decision JSON
                              |
                              v
                       stamp run_id, commit, push
                              |
                              v
                    GitHub Actions applies decision
                              |
                              v
strategy -> risk -> execution -> portfolio -> journal -> dashboard -> commit -> Pages
```

## GitHub Actions Workflow

```text
Schedule or manual dispatch
  |
  v
Trading Pipeline workflow
  |
  +-- MONITOR_RUNTIME=codex_loop?        -> skip API monitor by default
  |
  +-- MONITOR_RUNTIME=github_actions_api?
          |
          +-- checkout latest main
          +-- run python -m agent_trader monitor
          +-- use OpenAI monitor model
          +-- submit approved Alpaca paper orders
          +-- upload profile artifact
          +-- publish job merges artifact, regenerates docs, commits state

Local Codex decision push
  |
  v
Codex Decision Execution workflow
  +-- validate Alpaca paper secrets
  +-- apply decision without an LLM API call
  +-- reject incomplete/dry-run execution as a failed workflow
  +-- commit profile and dashboard artifacts
  +-- deploy GitHub Pages

Any local push that changes docs/
  |
  v
Publish Dashboard workflow -> deploy GitHub Pages
```

## Local Session Workflow

```text
Operator
  |
  v
./scripts/run_both.sh <phase> serial
  |
  +-- pull latest main
  +-- run phase prompt through Codex CLI
  +-- validate morning anchors when phase=morning
  +-- hand ready monitor decision to GitHub Actions by default
  +-- regenerate docs/
  +-- git add data/profiles/codex/ docs/ WEEKBOOK.md
  +-- commit and push HEAD:main when files changed
```

## Safety Boundaries

- `debug` mode never places orders.
- `paper` mode targets Alpaca paper trading only.
- `live` mode is not part of the normal operator flow.
- The monitor can execute only after strategy and risk approval.
- Monitor submissions use deterministic Alpaca client order IDs and an applied marker.
- Local monitor skips the Codex call when no candidate needs review.
- GitHub Actions API monitoring is opt-in via `MONITOR_RUNTIME=github_actions_api`.
- Morning validation rejects structurally invalid plans and demotes stale entries.

## Fresh-Start Flow

```text
Operator confirms RESET + start date
  |
  v
reset_for_fresh_start.sh or Reset Application State workflow
  |
  +-- delete generated Codex profile state
  +-- delete generated docs/ dashboard state
  +-- preserve source code and documentation
  +-- write fresh_start.json
  +-- regenerate empty dashboard
  +-- commit, push, deploy Pages

Separate Alpaca operation:
  create new paper account -> generate keys -> update GitHub secrets
  -> Verify Alpaca Paper Account -> begin day loop
```
