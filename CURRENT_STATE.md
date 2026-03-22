# Current State

Date: 2026-03-22

## Stable Baseline

The repo is now stabilized around a two-layer architecture:

1. Local strategist layer
   - `scripts/run_both.sh` runs Claude + Codex locally for rich morning/evening/weekly/monthly work.
   - Outputs are isolated under `data/profiles/claude/` and `data/profiles/codex/`.

2. Python runtime layer
   - `python -m agent_trader ...` powers research, monitor, reflection, weekly, monthly, and evolution phases.
   - GitHub Actions is configured to use the Python runtime for automated monitor runs.

## What Changed In This Stabilization Pass

- Fixed paper-mode behavior so `RUN_MODE=paper` now means:
  - real LLM analysis
  - real Alpaca paper orders
- Unified knowledge-file compatibility so the runtime can read both:
  - prompt-managed profile JSON
  - app-managed cold-start JSON
- Added BOM-safe JSON loading across the runtime.
- Wired `evolution` into the full cycle.
- Added [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md) as the operator manual.
- Switched GitHub Actions monitor flow to API-only operation:
  - no CLI auth dependency in Actions
  - no CLI execution requirement in Actions
- Refactored monitor into a lightweight execution gate:
  - morning research writes `execution_condition` per stock
  - monitor only considers a tiny candidate set
  - monitor can skip the LLM entirely when nothing is near a trigger
  - strategy execution is blocked unless the monitor gate marks a setup `ready_to_trade=true`
  - active positions are always kept in the monitor loop

## Monitor Gate Design

Morning research remains the heavy-thinking phase.

Intraday monitor is now intentionally small:

1. Load watchlist + active positions
2. Refresh prices and news
3. Build candidate list:
   - near entry
   - near stop
   - near target
   - fresh headlines
   - active positions
4. Run a cheap LLM gate only on those candidates
5. Let strategy/risk/execution proceed only when the gate approves

This keeps some intelligence intraday without paying for repeated deep reasoning.

## Current GitHub Actions Model

- Strategist family remains dual-profile:
  - `claude` profile uses Anthropic API in Actions
  - `codex` profile uses OpenAI API in Actions
- Actions currently uses:
  - `USE_CLI_AGENT=false`
  - API-only monitor path
- Local CLI workflows remain available for manual strategist sessions.

## Key New Config Knobs

Available in settings / `.env`:

- `MONITOR_MODEL_OPENAI`
- `USE_CLI_AGENT_FOR_MONITOR`
- `MONITOR_CANDIDATE_LIMIT`
- `MONITOR_ENTRY_PROXIMITY_PCT`

## Verification Status

Verified on 2026-03-22:

- `pytest -q` -> passing
- `python -m agent_trader validate --data-dir data/profiles/claude` -> passing
- `python -m agent_trader validate --data-dir data/profiles/codex` -> passing

## Repo Truths To Remember

- `run_both.sh` is the local strategist orchestration tool, not the intraday engine.
- GitHub Actions monitor now relies on cheap API calls, not CLI sessions.
- `SYSTEM_GUIDE.md` is the best current operator reference.
- `data/profiles/*` is the source of truth for strategist state.

## Next Intended Step

Prepare a demo production run by adding repo-level GitHub Actions secrets and variables, then trigger a manual workflow run to validate:

- schema shapes
- journal artifacts
- dashboard output
- monitor gating behavior
- Alpaca paper execution path
