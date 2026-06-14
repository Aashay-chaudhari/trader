# Current State

Date: 2026-06-14

## Status

The repository is aligned around one active strategist profile: `codex`.

- June 11 morning research is committed to `main`.
- Market regime: `risk_on`.
- Watchlist: `CCL`, `RCL`, `KBH`, `BRZE`, `AIR`, `NVDA`.
- Morning price-anchor validation passed.
- GitHub Pages contains the June 11 successful morning interaction.
- The default intraday monitor owner is now the local Codex loop via `MONITOR_RUNTIME=codex_loop`.
- `./scripts/run_both.sh monitor serial` now implements the local monitor path: Python prepares live context, Codex writes a monitor decision only when candidates need review, and the runner pushes it to GitHub.
- Local non-secret defaults now select the `codex` profile, `data/profiles/codex`, `codex_loop`, and paper mode in the operator runner. Raw Python commands remain debug by default.
- `MONITOR_EXECUTION_OWNER=github_actions` is the default. The `Codex Decision Execution` workflow uses repository Alpaca secrets to run deterministic strategy/risk/execution/portfolio, commits the artifacts, and deploys Pages without an OpenAI API call.
- `MONITOR_EXECUTION_OWNER=local` remains available for machines with local Alpaca credentials.
- Monitor execution now uses deterministic Alpaca client order IDs and `local_monitor_applied.json` to prevent duplicate submission on workflow reruns.
- The remote GitHub/OpenAI monitor is opt-in only. It runs when repository variable `MONITOR_RUNTIME=github_actions_api` is set, or when `github_actions_api` is selected in manual workflow dispatch.

## Monitor Readiness

Repository-side prerequisites are satisfied for June 11, 2026. External readiness still depends on repository configuration that is intentionally not stored in Git:

- `OPENAI_API_KEY` is available to GitHub Actions if the API monitor is enabled.
- `ALPACA_API_KEY_CODEX` and `ALPACA_SECRET_KEY_CODEX`, or the fallback Alpaca key pair, are available.
- `MONITOR_RUNTIME` is `codex_loop` for local Codex terminal monitoring or `github_actions_api` for scheduled API monitoring.
- `MONITOR_EXECUTION_OWNER` is `github_actions` for repository-secret paper submission.
- `MONITOR_RUN_MODE` is `paper` for paper execution or `debug` for observation-only runs.

## Active Workflow

1. Run local morning research.
2. Push validated morning state to `main`.
3. Keep the local Codex terminal loop running and call `./scripts/run_both.sh monitor serial` every 30 minutes during market hours.
4. Track `Codex Decision Execution` for broker submission and its artifact commit.
5. Use the OpenAI API monitor only when `MONITOR_RUNTIME=github_actions_api` is intentionally selected.
6. Run local evening reflection after the close.
7. Run weekly, monthly, and evolution reviews on demand.

## Recent Reliability Changes

- Removed active Claude workflow branches and dashboard bundles.
- Added Codex-only workflow dispatch and artifact publication.
- Added portable Python discovery through `python` or `uv`.
- Added discovery of the current Codex desktop CLI.
- Changed local runner pushes to `HEAD:main`.
- Added required empty profile directories to source control.
- Kept morning thesis and later monitor decisions separate in the dashboard.
- Added local monitor prepare/apply commands and a Codex monitor prompt so intraday checks no longer require the GitHub/OpenAI API monitor path by default.
- Added GitHub-secret execution handoff and automatic Pages publishing for all local phase pushes.

## Validation Baseline

- Unit suite: 140 passed after the June 14 execution-handoff change.
- Profile validation: 37 passed, 0 failed.
- Dashboard generation completed successfully.
