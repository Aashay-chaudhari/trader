# Current State

Date: 2026-03-22

## What We Completed

- Bootstrapped seed knowledge + observations for both strategist profiles and pushed the seed baseline.
- Upgraded `scripts/run_both.sh` to support:
  - serial + parallel execution modes
  - Claude live stream parsing (human-readable terminal output)
  - Codex output logging + PowerShell warning cleanup
  - Codex runtime guardrails (timeout, search/loop budget messaging)
  - Codex host-write mode toggle (`CODEX_HOST_WRITE`) to persist file edits reliably
  - pre-creation of `data/profiles/claude/cache` and `data/profiles/codex/cache`
- Fixed Codex CLI invocation compatibility (`codex --search exec`, not `codex --print`).
- Added stronger autonomy + budget behavior to `scripts/prompts/morning_research.md`:
  - no unnecessary permission questions
  - visible `RESEARCH LOG`
  - idempotency skip check (`SKIP_REASON`) if same-day cache already exists
  - search budget discipline guidance
- Recovered misplaced Codex outputs from repo root and moved them to:
  - `data/profiles/codex/cache/morning_research.json`
  - `data/profiles/codex/cache/watchlist.json`

## Current Runner Defaults

- `RUN_MODE`: `serial` (or pass `parallel` as arg 2)
- Codex limits:
  - `CODEX_MAX_SECONDS=900`
  - `CODEX_MAX_WEB_SEARCHES=10`
  - `CODEX_MAX_AGENT_LOOPS=30` (instructional)
  - `CODEX_REASONING_EFFORT=medium`
- Codex write mode:
  - `CODEX_HOST_WRITE=true` (default, uses bypass mode)
  - set `CODEX_HOST_WRITE=false` to force sandbox mode

## Known Notes

- Codex may still print non-fatal local warnings about its state DB migration and PowerShell shell snapshot support; these are upstream CLI/runtime warnings.
- For dual-profile workflow, `data/profiles/*` is the active source of truth.

## Tomorrow Quick Start

1. Run:
   - `./scripts/run_both.sh morning parallel`
2. If you want stricter budgets:
   - `CODEX_MAX_SECONDS=600 CODEX_MAX_WEB_SEARCHES=8 CODEX_REASONING_EFFORT=low ./scripts/run_both.sh morning parallel`
3. Review outputs in:
   - `data/profiles/claude/cache/`
   - `data/profiles/codex/cache/`

## Files Intentionally Changed In This Session

- `scripts/run_both.sh`
- `scripts/prompts/morning_research.md`
- `data/profiles/codex/cache/morning_research.json`
- `data/profiles/codex/cache/watchlist.json`
- `CURRENT_STATE.md`
