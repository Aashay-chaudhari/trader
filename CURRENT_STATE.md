# Current State

Date: 2026-06-14

## Status

The repository is aligned around one active strategist profile: `codex`.

- A new tracked application era begins on June 15, 2026.
- Generated Codex research, monitor, portfolio, journal, observations, knowledge,
  interactions, and dashboard state are being reset to an empty baseline.
- `data/profiles/codex/fresh_start.json` prevents the day-loop supervisor from
  creating catch-up reviews for the pre-reset era.
- A truly blank Alpaca trade history still requires a new paper account and new
  GitHub secret values; application reset cannot erase broker history.

- June 11 morning research is committed to `main`.
- Market regime: `risk_on`.
- Watchlist: `CCL`, `RCL`, `KBH`, `BRZE`, `AIR`, `NVDA`.
- Morning price-anchor validation passed.
- GitHub Pages contains the empty June 15 fresh-start baseline and will fill as
  the local day loop commits each new phase.
- The default intraday monitor owner is now the local Codex loop via `MONITOR_RUNTIME=codex_loop`.
- `./scripts/run_both.sh monitor serial` now implements the local monitor path: Python prepares live context, Codex writes a monitor decision only when candidates need review, and the runner pushes it to GitHub.
- Local non-secret defaults now select the `codex` profile, `data/profiles/codex`, `codex_loop`, and paper mode in the operator runner. Raw Python commands remain debug by default.
- `MONITOR_EXECUTION_OWNER=github_actions` is the default. The `Codex Decision Execution` workflow uses repository Alpaca secrets to run deterministic strategy/risk/execution/portfolio, commits the artifacts, and deploys Pages without an OpenAI API call.
- `MONITOR_EXECUTION_OWNER=local` remains available for machines with local Alpaca credentials.
- Monitor execution now uses deterministic Alpaca client order IDs and `local_monitor_applied.json` to prevent duplicate submission on workflow reruns.
- The remote GitHub/OpenAI monitor is opt-in only. It runs when repository variable `MONITOR_RUNTIME=github_actions_api` is set, or when `github_actions_api` is selected in manual workflow dispatch.

## Monitor Readiness

Repository-side prerequisites are satisfied for the June 15, 2026 fresh start.
External readiness still depends on repository configuration that is
intentionally not stored in Git:

- `OPENAI_API_KEY` is available to GitHub Actions if the API monitor is enabled.
- `ALPACA_API_KEY_CODEX` and `ALPACA_SECRET_KEY_CODEX`, or the fallback Alpaca key pair, are available.
- `MONITOR_RUNTIME` is `codex_loop` for local Codex terminal monitoring or `github_actions_api` for scheduled API monitoring.
- `MONITOR_EXECUTION_OWNER` is `github_actions` for repository-secret paper submission.
- `MONITOR_RUN_MODE` is `paper` for paper execution or `debug` for observation-only runs.

## Active Workflow

1. Verify the replacement Alpaca paper account has zero positions and orders.
2. On June 15, paste `codex_day_loop_master.md` into a fresh Codex session.
3. Run local morning research.
4. Push validated morning state to `main`.
5. Keep the local Codex terminal loop running and call `./scripts/run_both.sh monitor serial` every 30 minutes during market hours.
6. Track `Codex Decision Execution` for broker submission and its artifact commit.
7. Use the OpenAI API monitor only when `MONITOR_RUNTIME=github_actions_api` is intentionally selected.
8. Run local evening reflection after the close.
9. Run weekly, monthly, and evolution reviews only for periods after the fresh start.

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

- Unit suite: 141 passed after the June 14 fresh-start tooling change.
- Profile validation: 37 passed, 0 failed.
- Dashboard generation completed successfully.
