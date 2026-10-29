# Implementation handoff

Read `REFACTOR_SCOPE.md`, `IMPLEMENTATION_LOG.md`, `CURRENT_STATE.md`, then
`ARCHITECTURE.md` and `SYSTEM_GUIDE.md`. These replace the legacy execution model.

The active CLI is `agent_trader.runtime.cli`; the operational database is local
`.runtime/trader.sqlite3`. Python owns execution, ledgers, fixed risk and closing.
Codex subscription-authenticated app-server turns provide structured judgments.
GitHub Actions owns CI and sanitized GitHub Pages publication only.

Never import old profile trades as current holdings, publish private artifacts,
use a paid model API fallback, weaken risk/promotion gates, or rewrite Git history.
Preserve unrelated user work. Stop the local supervisor before editing/resetting
operational state. Use narrow staging paths, not `git add .`.

After behavior changes, run relevant runtime tests and full regressions as needed,
run active-runtime lint, regenerate the dashboard, and record observed outcomes in
the implementation log. Do not claim scheduled/deployed behavior without checking it.
