# Current State

Date: 2026-03-22

## Operating Model

Agent Trader now uses a streamlined two-layer workflow:

1. Local strategist sessions
   - Run with `scripts/run_both.sh`
   - Heavy research and reflection happen locally through CLI subscriptions
   - Supported phases: `morning`, `evening`, `weekly`, `monthly`

2. Remote monitor automation
   - GitHub Actions runs the monitor workflow every 30 minutes on weekdays
   - Monitor uses cheap API models only
   - Remote workflow is intentionally limited to the intraday monitor path

## Source Of Truth

Durable strategist state lives under:

- `data/profiles/claude/`
- `data/profiles/codex/`

Tracked long-term memory includes:

- `knowledge/`
- `observations/`
- `positions/`
- `cache/`
- `profile.json`

Legacy top-level runtime folders are no longer part of the supported architecture.

## Monitor Model Defaults

- Claude strategist monitor: `claude-haiku-4-5-20251001`
- Codex strategist monitor: `gpt-4o-mini`

## Current Workflow

Morning:

```bash
./scripts/run_both.sh morning parallel
```

Evening:

```bash
./scripts/run_both.sh evening parallel
```

Weekly:

```bash
./scripts/run_both.sh weekly parallel
```

Monthly:

```bash
./scripts/run_both.sh monthly parallel
```

Remote automation:

- GitHub Actions `Trading Pipeline`
- monitor only
- weekday schedule during market hours

## Configuration Direction

Supported control variables:

- `RUN_MODE`
- `LLM_PROVIDER`
- `DATA_DIR`
- `AGENT_PROFILE`
- `AGENT_LABEL`
- `RESEARCH_MODEL`
- `MONITOR_MODEL`
- `RESEARCH_MODEL_OPENAI`
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

## Verification Snapshot

Most recent migration state before final cleanup:

- code cleanup for legacy variables and internal CLI-agent path: done
- remote workflow narrowed to monitor-only: done
- docs rewrite to match the new architecture: in progress
- one test path expectation caused by `data/profiles/default`: being fixed during cleanup

## Next Step

Finish cleanup, rerun tests and validations, then commit the streamlined architecture as the new baseline.
