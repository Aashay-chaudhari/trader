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

## Checkpoint 5 — final recovery and experimental controls

- CLI/quota outage simulation now confirms Python broker reconciliation remains
  available and new entries are blocked. Startup credential failures send alerts.
- Broker clock/session confirmation gates entries; stale GTC entries are canceled
  outside market hours too. Partial-fill protection/target/closing paths tested.
- Position reviews are batched hourly; daily calls reserve four slots for nightly
  retrospective/maintenance and reserve paced quota capacity for those roles.
- Challenger samples now record the actual incumbent's enter/abstain behavior.
  Promotions preserve prior versions, record activation equity, and roll back at
  a fixed 2% loss threshold. Executed plans retain their strategy version.
- Weekly/monthly retrospectives use the broker calendar, including holiday weeks.
- Actual retrospective and maintenance schema inference passed.
- Latest full suite was 220 passed before the final budget/batch edge-case run.
  Final code checks/CI, scheduled reload, public browser QA and ready notification
  are the remaining handoff checks.

## Checkpoint 6 — final release validation

- Full pre-release suite passed 226 tests; the subsequent batched-position worker
  schema regression passes with the active-runtime suite (57 tests), yielding
  227 total. Active runtime, strategy and runtime-test lint pass.
- Final live free-data packet returned 30 snapshots, 30 daily indicator sets,
  five delayed FRED series and 30 indicative option samples, without feed errors.
  FRED's mixed-calendar ZIP response is handled without extracting files to disk.
- Persistent thread context survived an actual app-server process restart and
  switched models successfully. Research returned dated primary-source links.
- Populated and empty desktop/mobile browser checks passed. Fixtures stayed private.
- Final audit corrected the batched position-review response schema at the worker
  boundary; a regression test verifies the actual schema supplied to inference.
- READINESS.md records the October 29 schedule and intentionally pending fill/exit
  gate. Final source CI, scheduled-process reload and public snapshot are checked
  after publication below.

## Activation evidence — 02:01 EDT, October 29

- Final full local regression suite: **227 passed** (57 active-runtime tests),
  one legacy dependency deprecation warning. Lint and JavaScript syntax passed.
- Source cc59e5e6 passed GitHub Tests run 40826664712. A later frontend-only
  correction displays the validated source revision; no trading logic changed.
- Windows task AgentTrader-LocalSupervisor was started through Task Scheduler,
  observed Running, with the next daily trigger October 29 at 07:40 Eastern.
  WakeToRun and StartWhenAvailable are true; execution time limit is PT0S.
- The scheduled process independently refreshed broker/model/quota preflight,
  recorded a heartbeat and published snapshot commit 9ad9c9eb to main at 02:01.
  Reconciliation errors are empty; entries are quota-eligible but still gated
  on the deliberately pending market-open execution check.
- A second supervisor invocation correctly refused to run, verifying the lock.
- Windows screen may be locked. Interactive user sign-in is required after reboot.

## Handoff verification

- Latest source 804bf4dc passed GitHub Tests run 40826756727 and Pages run
  40826756706. Public schema-v2 JSON reports the October 29 start, $30,000 equity,
  zero positions and the live scheduled-process heartbeat.
- Actual public-site Chromium checks passed all six views at 1440px and 390px,
  with no page errors or horizontal overflow.
- Scheduled process continued ticking with no new incidents; direct broker query
  reconfirmed zero positions/open orders. Execution stays gated until market open.
- Completion notification sent through the configured ntfy destination; delivery
  is server-accepted, while phone receipt can only be confirmed by the user.

## Research sprint and daily knowledge handoff — October 29 morning

- Replaced the single-shadow slot with up to six concurrent challengers per equity
  branch. Eight initial paired filter experiments are registered (four per branch).
  Dedicated research shadow plans never enter the broker execution plan table.
- Historical integration froze 30 instruments / twelve fixed rule-horizon trials,
  September 4, 2025–October 28, 2026, with a June 4, 2026 chronological split,
  boundary-label purge, and 20bp/50bp assumed cost checks. Dataset hash and raw bars
  are private. Every trial is reported; none counts as forward promotion evidence.
- Real research generated nine hypotheses with thirteen cited sources. A reviewer
  in a separate persistent thread inspected source/method claims and recorded four
  needs-work verdicts. Of five accepted-for-testing verdicts, one failed the exact
  citation-reference check. Four knowledge cards are currently eligible for reuse;
  all other hypotheses and their rejection/hold reasons remain in the catalogue.
- Clarified the generated draft's historical return units before full-data review:
  holding-horizon unit-opportunity averages grouped by entry session, never daily
  portfolio returns. The original draft is retained privately.
- The morning prompt explicitly retrieves reviewed cards, counterevidence and joined
  experiment states. Actual fresh-data prompt fit the 28,000-character ceiling;
  historical/market evidence remains present. Observation blobs no longer crowd
  reviewed knowledge or current market data out of the prompt.
- First ten research mornings: discovery from 08:35, separate validation, and a
  same-morning brief refresh before the open. Positions take priority in session;
  daily/weekly quota ceilings and broker risk policies remain fixed.
- Promotions retain minimum twenty sessions / thirty samples, require positive
  absolute net results, include a trial-family penalty and use doubling-session
  review looks. Superseded-parent candidates become stale.
- Full suite: 241 passed; active lint and JavaScript syntax passed. Browser checks
  cover six views at desktop/mobile widths, all twelve screens and actual reviewed
  research cards. CI passed the initial source and separate-reviewer commits;
  final prompt/check metadata is verified in the next CI release.

### Research release activation

Source fac33241 passed GitHub Tests run 40867595243. Pages run 40867740870
succeeded; public JSON and the mobile strategy view expose twelve screens, four
reviewed knowledge cards and eight shadow experiments. Windows task was re-registered
and started after a reload interruption; fresh 07:45 ET preflight confirmed models,
broker reconciliation and funding. The 07:45 startup notification was server-accepted.
No new trading/runtime incidents or broker positions were introduced.

## Console interruption and independent recovery repair — October 29 evening

- Original Windows launcher recorded 0xC000013A; the initiating source is not
  established. Task history was disabled. Morning heartbeat stopped at 08:12 ET,
  before the first scheduled research; broker directly confirmed $30,000, no
  fills/positions/open orders. Today was an operational miss, not a strategy result.
- Direct interactive console task is disabled. `agent-trader.service` now owns the
  process under systemd's lingering user manager with Restart=always. A hidden
  Windows WSL host keeps the distribution alive; a separate hidden watchdog runs
  every two minutes, checks an independent heartbeat, recovers and alerts via ntfy.
- Native Windows Git/authentication and diagnostic launches also use the hidden
  GUI host; no bare PowerShell/WSL console is used by the active scheduled tasks.
- Actual interruption drill: SIGINT changed service PID 198817→199204; hard-crash
  drill: SIGKILL changed 199204→199266, each with a fresh heartbeat after restart.
- Independent Windows drill: an intentional full service stop recovered under the
  scheduled watchdog in 72 seconds (PID 199266→199742). Incident and subsequent
  recovery notifications were accepted by ntfy. The recovery-confirmed log recorded
  a fresh 21-second heartbeat. No broker orders were introduced by these drills.
- Heartbeats are atomic and written before broker checks or publication. Signals
  and graceful stops are journaled. Windows watchdog/host logs survive Python loss.
- Operational model work was temporarily paused with a local flag during the drills;
  it is removed after validation. The Windows watchdog remains enabled throughout.
- New tests cover independent heartbeat output during broker failure and the hidden
  Windows publication path; native PowerShell parser checks reported zero errors.
