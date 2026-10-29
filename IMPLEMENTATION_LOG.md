# Refactor implementation log

Authoritative brief: REFACTOR_SCOPE.md. User approved complete implementation,
local scheduling, Pages publishing, ntfy alerts, controlled paper smoke tests,
and fresh application state while preserving Git history.

Launch target: Thursday October 29, 2026; see the launch-date interpretation below.

## Checkpoint 1 — foundation

- Legacy application artifacts archived locally under ignored .runtime/archive/.
- Original Git history remains intact; current baseline is commit 9b33a865.
- Replacement Alpaca account previously verified ACTIVE, $30,000 cash/equity,
  no positions/orders, level 3 options. Refresh before activation.
- WSL Ubuntu, Python virtual environment, Codex CLI, Windows PowerShell and
  Windows Git Credential Manager are available.
- No populated local ntfy environment existed; user supplied and confirmed a topic.
- New architecture: SQLite local state, Codex app-server task turns, deterministic
  broker execution, static sanitized dashboard; Actions limited to CI/Pages.

## Pending

Implement runtime, tests, frontend, safe fresh reset, publication, scheduler,
paper smoke check, end-to-end verification, and operator docs. Record observed
outcomes here rather than assuming a written feature is operating.

## Checkpoint 2 — integrated implementation and observed checks

- Added v2 local runtime: transactional SQLite state; branch ledgers; partial-fill
  accounting; deterministic order IDs; quote/risk revalidation; protective brackets;
  intraday closing; account reconciliation; calendar-aware supervisor.
- Added subscription-authenticated Codex app-server turns with task-specific models,
  live-search limits, bounded runtime/tool cycles, persistent daily thread and quota
  control. Research worker is independent of deterministic tick and publication.
- Verified actual lightweight-model inference and a switch to the workhorse model
  on the same thread. Verified configured models appear in authenticated catalog.
- Live research integration returned schema-valid brief with 11 cited sources.
  No plans were invented for the stale overnight snapshot. This integration output
  was archived and is not used as live trading research.
- Added structured rates/Fed/earnings research, free delayed FRED series, IEX
  observations, indicative options chain collection, event updates, thesis review.
- Added challenger contracts, paired forward observation/cost assumptions,
  conservative promotion gates, isolated pure-code maintenance candidates.
- Rebuilt frontend with overview, market intelligence, strategy lab, options desk,
  decision journal and system/usage views. All initial browser routes rendered
  without page errors; 390px mobile viewport had no horizontal overflow.
- Full regression pass: 202 passed at this checkpoint. Additional edge-case tests
  are being added for bracket legs, persistent daily halts, and code filters.
- Fresh reset completed, archived locally; no Git history rewritten. New $30,000
  ledger reconciles to replacement broker account, flat with no open orders.
- Actual paper API accepted and confirmed cancellation of a nonmarketable $1 SPY
  limit order. Zero fills. This verifies submission/cancel, NOT execution fills.
  A guarded one-share market-open round-trip remains a runtime launch gate.
- Retired legacy trading/reminder/reset workflows; only CI and Pages remain active.
- Windows Git push authentication and GitHub Pages workflow hosting verified available.

## Next activation steps

Finish regression/failure-path checks, publish source and clean dashboard, install
and verify Windows scheduled task, check actual scheduled-process heartbeat, verify
GitHub CI/Pages results and deployed frontend, send ready notification, record exact
launch mode and limitations. Target start remains October 30 per latest instruction.

## Checkpoint 3 — launch candidate

- Regression suite: 212 passed; active-runtime lint and JavaScript syntax passed.
- Six frontend views passed actual Chromium desktop and 390px mobile checks with
  no page errors or horizontal overflow. Screenshots are private under .runtime/.
- Added protective-stop repair, partial-entry handling, target exits, active position
  reviews, persistent daily loss halts, and independent publication worker.
- App and lockfile version are 2.0.0. No dependency upgrades were required.
- Submission/cancellation passed with no fills. Equity execution remains gated
  until the first trading session's one-share round-trip verifies broker fills.
- Windows scheduled task is next; source/dashboard publication is being committed.

## Launch-date interpretation

The user's explicit absolute date was October 29, sent at 00:17 EDT. Later overnight
references to tomorrow are interpreted as the upcoming morning, so first trading is
October 29 rather than idling until October 30. Configuration and operator docs now
use October 29 consistently. The earlier October 30 assumption above is superseded.
No order can be sent before regular-market opening and execution verification.

## Checkpoint 4 — deployment and background verification

- Source pushed to main; GitHub Pages successfully deployed and serves v2 HTML/JSON.
- Windows task registered and observed Running, with daily 07:40/sign-in triggers,
  WakeToRun, StartWhenAvailable, IgnoreNew and no execution time limit.
- Scheduler smoke test exposed Windows npm shim selection; corrected to prefer the
  native Linux Codex binary. Background account/quota checks now pass.
- A prelaunch launcher incident is retained in the audit journal; it is resolved.
- CI tests passed but an unpinned newer Ruff changed default rules. Workflow now
  installs from uv.lock so local and CI tooling match; final CI pass pending.
- Isolated code-maintenance integration passed regression validation, committed a
  candidate on its own branch and left operational strategy/ledger unchanged.
