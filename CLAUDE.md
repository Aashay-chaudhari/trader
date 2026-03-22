# Agent Trader Local Strategist Guide

This repo uses a profile-first workflow.

## Your role

When running locally as the Claude strategist, your job is to perform the heavy thinking phases and write only to the Claude profile root:

- `data/profiles/claude/`

Never write strategist outputs into:

- `data/`
- `data/profiles/codex/`

## Supported local phases

- `morning`
- `evening`
- `weekly`
- `monthly`

These are normally run through:

```bash
./scripts/run_both.sh <phase> parallel
```

## Core rules

1. Treat `data/profiles/claude/` as the source of truth.
2. Heavy market research is local CLI work, not GitHub Actions work.
3. GitHub Actions is reserved for lightweight monitor checks during market hours.
4. Do not rely on legacy root-level paths like `data/journal/` or `data/knowledge/`.
5. Do not use removed legacy environment variables.

## Active architecture

### Local strategist layer

Use prompt files in `scripts/prompts/` to produce:

- `cache/morning_research.json`
- `cache/watchlist.json`
- daily, weekly, and monthly observations
- knowledge updates when the prompt requires them

### Remote monitor layer

GitHub Actions reads the latest pushed profile state and runs only the monitor pipeline.

It uses cheap API models to make small approval decisions intraday.

## Data layout

Durable Claude state lives in:

- `data/profiles/claude/cache/`
- `data/profiles/claude/knowledge/`
- `data/profiles/claude/observations/`
- `data/profiles/claude/positions/`
- `data/profiles/claude/profile.json`

Legacy top-level runtime folders are not part of the supported design.

## Configuration model

Supported variables:

- `RUN_MODE`
- `LLM_PROVIDER`
- `DATA_DIR`
- `AGENT_PROFILE`
- `AGENT_LABEL`
- `RESEARCH_MODEL`
- `MONITOR_MODEL`
- `MONITOR_MODEL_OPENAI`
- `MONITOR_CANDIDATE_LIMIT`
- `MONITOR_ENTRY_PROXIMITY_PCT`

Removed from the supported workflow:

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

## Practical workflow

### Morning

- read the Claude profile memory
- research the current market
- write the new morning cache files
- commit and push through the runner

### Evening

- review the day using the latest pushed monitor state
- write the daily observation
- update any reflection outputs required by the prompt

### Weekly and monthly

- synthesize observations into higher-level lessons
- keep outputs grounded in the actual stored profile history

## Quality bar

- Keep output JSON valid.
- Keep recommendations concrete.
- Prefer profile-specific evidence over generic market advice.
- If you need to raise concerns or ideas for improvements, put them in the improvement artifacts instead of blocking the run with unnecessary questions.
