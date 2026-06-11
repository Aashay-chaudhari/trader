# Current State

Date: 2026-06-11

## Status

The repository is aligned around one active strategist profile: `codex`.

- June 11 morning research is committed to `main`.
- Market regime: `risk_on`.
- Watchlist: `CCL`, `RCL`, `KBH`, `BRZE`, `AIR`, `NVDA`.
- Morning price-anchor validation passed.
- GitHub Pages contains the June 11 successful morning interaction.
- The remote monitor workflow is Codex-only and scheduled every 30 minutes during weekday market hours.
- The monitor uses OpenAI and defaults to Alpaca paper mode when `MONITOR_RUN_MODE` is absent.

## Monitor Readiness

Repository-side prerequisites are satisfied for June 11, 2026. External readiness still depends on repository configuration that is intentionally not stored in Git:

- `OPENAI_API_KEY` is available to GitHub Actions.
- `ALPACA_API_KEY_CODEX` and `ALPACA_SECRET_KEY_CODEX`, or the fallback Alpaca key pair, are available.
- `MONITOR_RUN_MODE` is `paper` for paper execution or `debug` for observation-only runs.

## Active Workflow

1. Run local morning research.
2. Push validated morning state to `main`.
3. Let GitHub Actions monitor candidates intraday.
4. Let the workflow commit runtime state and redeploy GitHub Pages.
5. Run local evening reflection after the close.
6. Run weekly, monthly, and evolution reviews on demand.

## Recent Reliability Changes

- Removed active Claude workflow branches and dashboard bundles.
- Added Codex-only workflow dispatch and artifact publication.
- Added portable Python discovery through `python` or `uv`.
- Added discovery of the current Codex desktop CLI.
- Changed local runner pushes to `HEAD:main`.
- Added required empty profile directories to source control.
- Kept morning thesis and later monitor decisions separate in the dashboard.

## Validation Baseline

- Focused unit suite: 18 passed.
- Profile validation: 37 passed, 0 failed.
- Dashboard generation completed successfully.

