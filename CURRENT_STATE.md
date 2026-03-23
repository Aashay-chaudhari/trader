# Current State

Date: 2026-03-22

## Status

The repo is in a paper-trading-ready operator state.

What that means:

- local CLI research and reflection are the primary workflow
- GitHub Actions runs only the lightweight monitor path
- monitor uses cheap API models
- Alpaca paper execution is wired through the Python runtime
- dashboard output includes knowledge, interactions, strategist voice, and evolution artifacts
- the first local morning run has completed and been pushed
- the remote monitor path has been dry-run validated and deployed successfully

## Primary Commands

### Daily

```bash
./scripts/run_both.sh morning parallel
./scripts/run_both.sh evening parallel
```

### Periodic

```bash
./scripts/run_both.sh weekly parallel
./scripts/run_both.sh monthly parallel
./scripts/run_both.sh evolve parallel
```

### Validation

```bash
pytest -q
python -m agent_trader validate --data-dir data/profiles/claude
python -m agent_trader validate --data-dir data/profiles/codex
python -m agent_trader dashboard
```

## Current Frontend Surface

GitHub Pages should now show:

- strategist comparison
- trade history and market intelligence
- knowledge summaries
- local session logs plus monitor evaluations in the same daily timeline
- strategist voice
- evolution summary plus report link
- `Session Log` routes to the readable interactions panel
- `Evolution` routes to the proposals/evolution panel

## Current Remote Automation

Workflow: `Trading Pipeline`

- schedule: every 30 minutes on weekday market hours
- run mode is controlled by `MONITOR_RUN_MODE`
- current production setting: `paper`
- normal production use: `monitor` only
- publish path: commits updated runtime state and deploys GitHub Pages

## Current Cheap Monitor Models

- provider for both strategist monitor jobs: `openai`
- model for both strategist monitor jobs: `gpt-4o-mini`

## Evolution State

Evolution is now available in two forms:

1. ongoing evening proposal backlog
   - `IMPROVEMENT_PROPOSALS.md`
   - `improvement_proposals.json`

2. explicit on-demand local review
   - `./scripts/run_both.sh evolve parallel`
   - outputs `evolution_review.json` and `EVOLUTION_REPORT.md`

Current live state:

- the evolution pipeline is wired and exposed in the dashboard
- no evolution review has been run yet
- an empty evolution card is expected until the first explicit evolve pass

## Operator Expectation

From here, the normal week should only require:

1. local morning research
2. remote monitor automation
3. local evening reflection
4. weekly review on the weekend
5. optional evolution review when you want a deliberate improvement pass
