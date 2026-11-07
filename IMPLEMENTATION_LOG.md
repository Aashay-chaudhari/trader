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

### Recovery release verification

- Final source 25f6d88b passed CI run 40968728829; the core service/watchdog source
  07df1b4b passed run 40968675556. Local regression suite passed 243 tests.
- Scheduled publication through the hidden Windows Git/auth chain succeeded;
  Pages snapshot bf78865f deployed successfully. Public mobile System view reports
  independent recovery without page errors or horizontal overflow.
- Latest service preflight and subsequent heartbeats passed. Windows watchdog
  independently reported healthy at 18:50 ET; its incident state is cleared.
- Model-work pause flag removed; end-of-day review resumed under the service.
  The missed-session incident is retained in the public journal. No claim of a
  successful trading session or all-day reliability is inferred from this repair.

## Real research probes and 19:00 one-time trigger — October 29

- Added isolated research/hypothesis probes using the actual free-data, subscribed
  model inference, structured output, independent reviewer and scratch morning
  retrieval paths. Separate thread scopes prevent contaminating daily sessions;
  production plans, challengers and knowledge are never imported from a probe.
- First quick attempts hit overly small web-action caps while their prompts still
  requested broad research. Corrected prompt/allowance alignment to include source
  checks, preserving account quotas and bounded calls. Failed attempts remain in
  the journal; their successful retries are recorded under the same IDs.
- Dummy research passed at 18:59:53 ET: seven cited sources, zero execution plans.
- Dummy hypothesis/review passed at 18:59:58: two hypotheses accepted for testing,
  with actual retrieval in the scratch morning prompt verified.
- A persistent systemd one-time timer explicitly used America/New_York. It fired
  at 19:00 ET and independently launched the full research check, which completed
  at 19:02:38 with exit status zero: nine sources, two hypotheses, both held for
  further work. Reviewer identified return-unit wording and undefined test rules.
  Workflow success does not imply hypothesis approval or profitability.
- Receipt metadata distinguishes a verified positive handoff from zero approved
  cards. The scheduled check approved zero cards; the earlier hypothesis dummy
  verifies positive handoff. Full reports stay private under .runtime/probes/.
- Broker checks confirm $30,000 equity/cash, no fills, positions or open orders.
  Main service/watchdog continued while the timer and checks ran. The completed
  one-time timer is disabled; daily operation remains enabled.
- Initial probe release passed all 247 tests and CI. Added a further regression
  covering rejected hypotheses and non-vacuous handoff reporting for final CI.

Final probe source 284ac714 passed full CI (248 tests). The completed scheduled
service exited zero. All three completion notifications were server-accepted.
Public snapshot exposes all receipts; model work remained bounded under existing
quota limits. Production still has four reviewed cards and no executable plans or
positions. The main service/watchdog remain active after the one-time timer retired.

## Public-resource and learning acceleration — October 29 late evening

- Primary-source review covers agent-trading evaluation, multiple-testing risk,
  reversal mechanisms, official release calendars and public-data limitations.
  PUBLIC_RESEARCH_NOTES.md records citations, selected changes and limits.
- New official BEA/BLS ICS collector validates dates/time zones, source URLs,
  payload size and unsupported recurrence, caches six hours and backs off failures.
  Actual BEA fetch yielded three dated events; BLS returned 403 and stays unknown.
  Five dated FRED series and thirty completed-bar indicator sets were verified.
- Added an independent deterministic forward lab: six fixed rules × one/five-session
  horizons; actual quote windows, numerical costs, frozen normalized inputs/hashes,
  missing-data denominators and overlap exclusions. It has no broker order authority.
  Twenty entry dates are fixed October 30–November 27, final maturity December 3.
  Day-one preparation records 360 planned opportunities and zero quote observations.
  Pre-observation input/protocol amendments archive originals explicitly.
- Preserved historical raw data/hash/split. Derived fields now identify horizon unit
  returns, never daily portfolio P&L. Correlated symbols/variants are not independent.
- Independent research audit initially held two definitions; a revised precise
  protocol passed a fresh reviewer for descriptive testing only. Six total reviewed
  knowledge cards are now available to the morning loop, no new executable plans.
- Separated/rotated role contexts, fresh decision/review contexts, complete bounded
  retrospective JSON and explicit selection/counts. Failed inference calls expose
  missing token totals. Real app-server soft-steering acknowledgments passed;
  hard ceilings and 80% weekly/20% reserve policy remain unchanged.
- Added broker-confirmed five-minute session coverage, separate from heartbeats,
  drill success and fills. Auxiliary cohort/coverage errors cannot block owned exits.
- Added Project & progress: architecture, decisions, automations, resource register,
  repo map, research agenda and computed assessment. October 29's operational miss
  remains explicit. No subjective feelings or probability-of-profitability score.
- Local full regression: 266 passed (96 runtime), one legacy dependency warning;
  runtime/test lint passed. Seven-view Chromium desktop/mobile QA and in-page
  Project navigation passed. Deployment/activation receipts follow below.

The source upgrade ddb7d60d passed Tests run 40983096271 and Pages run 40983096283.
A final integration follow-up also injects complete provisional forward evidence
into morning research and retrospectives; the live morning/review packets fit the
input cap and retrieved the revised reviewed hypothesis. No inference or order
was required for this deterministic handoff check.

Final daily-handoff source db4427ce passed Tests run 40983375627. The publisher
now hashes CSS/JavaScript references in exported HTML so releases request matching
assets. An initial browser assertion mistook CSS-uppercased table headings for a
missing column; direct DOM inspection confirmed the columns were present. The
corrected checks are repeated against the actual site. No stale-script incident
is inferred from that assertion failure.

### Final public-research upgrade activation

- Final source a6f2eac9 passed Tests run 40983632867 (266 tests); Pages snapshot
  d9154692 deployed successfully in run 40983660049.
- All seven actual public views passed Chromium desktop/390px-mobile verification,
  including versioned assets, complete Project assessment, all twelve forward rows
  and net/baseline/stress columns. No JavaScript errors or viewport overflow.
- Reloaded systemd service reconciled broker/ledgers, confirmed model availability
  and published automatically. Subsequent heartbeat matched the active service PID;
  independent Windows watchdog reported healthy. Hidden host running, old visible
  task disabled, native PowerShell parse errors zero. No new runtime/cohort incidents.
- Direct broker check remained $30,000, zero positions/open orders/fills. The exact
  frozen input hash verifies, with 360 expected opportunities and zero observations.
  Actual fill/exit and a completed unattended trading day remain pending.
- Source CI and public QA receipts are reflected in the exported release metadata.
  Final metadata/doc publication does not change the tested source or risk policy.

## Execution-test lifecycle and operational review repair — October 31

- Confirmed Friday's one-share SPY test lacked an ordinary strategy-plan row.
  Cleanup requested cancellation at 09:32:58 ET, before its intended two-minute
  window; broker cancellation was confirmed at 09:33:28. Zero fills occurred.
- Persist the exact operational intent before submission. Only matching daily
  client ID, SPY, one share, intraday branch and a two-minute expiry qualify for
  cleanup recognition. Missing/forged/extended intents remain cancelable; branch
  pause and close cutoff still apply. Existing client-ID recovery avoids duplicates.
- Cancellation-requested and broker-confirmed terminal outcomes are distinct.
  Passing requires one-share entry and exit fill receipts, successful reconciliation
  and no remaining intraday holdings/SPY orders. Partial fills cannot pass the gate.
- Added bounded operational review evidence: broker order states/timestamps,
  execution checks, reconciliation, incident details and diagnoses. Eastern period
  boundaries exclude the previous evening from daily reviews. Whole records/counts
  remain explicit under the input budget.
- Persist operational repair proposals separately from strategy lessons. Automated
  maintenance permissions remain restricted to the pure adaptive filter. Original
  Friday reviews remain intact; a fresh operational follow-up is recorded separately.
- Full local regression: 287 tests passed (117 active runtime), one legacy dependency
  warning. Runtime/test lint passed. Real follow-up and deployment receipts follow.

### Independent operational follow-up

A real subscription-authenticated, fresh-context review used the repaired packet
(23,788 characters, within the existing input cap). It confirmed the entry and both
sell orders were broker-canceled with zero fills, distinguished request/final times,
recognized the early-cleanup defect and kept real fill/exit verification pending.
No experiments or strategy changes were proposed. The original Friday daily review
was preserved byte-for-byte as structured state. The separate follow-up is stored
locally and displayed under Project & progress; its summary is in the public journal.

All seven views passed local Chromium desktop/390px-mobile checks, including the
follow-up panel. Source lint passed. Risk, quota, options restrictions and the fixed
cohort protocol/window remain unchanged. Deployment receipts follow below.

### Operational repair activation

Final source ad2dafe9 passed GitHub Tests run 41173094113 (287 tests). Pages
snapshot 24bf33a6 deployed successfully in run 41173121542. All seven actual public
views passed desktop/390px-mobile QA with the operational follow-up visible and
no browser errors/viewport overflow.

Reloaded systemd service confirmed broker reconciliation, funding and model
availability. Broker directly reported $30,000 cash/equity, zero positions/open
orders. Frozen protocol hash, cohort counts, branch cash and zero filled-order
count matched the saved pre-reload baseline. Original Friday review remains intact.
The real fill/exit gate remains false. Broker next-open is November 2 at 09:30 EST;
the controlled check is eligible from 09:32, subject to existing quote/risk gates.

## Research-log quality audit and daily development integration — October 31

Audited actual research, pulses, source reviews, missing inputs, usage and logs.
Primary spot checks supported selected Fed/BLS/BEA facts. The main gaps were missing
price features, incomplete source verification, stale repeated pulses, incomplete
artifact history and redundant review windows. RESEARCH_QUALITY_AUDIT.md records
sources, measurements, selected changes and limitations.

Implemented exact daily features, free IEX completed-minute features with missingness,
complete bounded pagination, focused research/pulse context, explicit source-check
attestations and all-citation gating. Added durable full input/output artifacts,
deterministic daily quality findings, deduplicated developer proposals and complete
review/maintenance handoffs. Period reuse requires identical retained evidence and
is labeled derived. Soft budget steering waits for an in-flight web result to finish.
Forward summaries now expose active signal counts so abstention can explain zero.

Two actual fresh-context reviewer runs rechecked twelve definitions; current
catalogue is four reviewed-for-testing / thirteen held, with no reviewed card lacking
explicit source attestation. Original reports and card history were preserved;
existing experiment registry and fixed cohort protocol were not rewritten.

Real free-data checks: 872 replay minute bars across thirty symbols, thirty VWAP
values, twenty-six complete opening ranges. Offline replay was not imported as
forward evidence. A latest-end IEX access check succeeded off-hours. Future live
freshness and paper fill/exit are still separate unverified gates.

Regression/deployment/public QA receipts follow after final validation.

Final local quality-upgrade regression: 306 tests passed, including 136 active
runtime tests, with the same single legacy dependency warning. Runtime/test lint
passed. Live source-check schema/gates were exercised by both independent rechecks.

Final quality-upgrade suite after explicit review-window correction: 307 tests
passed (137 active runtime), one unchanged legacy warning. Weekly/monthly review
packets now use the final day's quality audit and explicitly bound period events;
later operational diagnoses remain separately labeled current snapshots. Local
seven-view desktop/mobile QA passed for quality, attestations and active-signal UI.

### Research-quality upgrade activation

Final source 11d9c89f passed GitHub Tests run 41175540423. Pages snapshot ce5c47c3
passed deployment run 41175579709. All seven actual public views passed Chromium
desktop/390px-mobile checks with quality findings, source attestations and closed
active-signal counts visible; no browser errors or horizontal overflow.

The reloaded systemd service reconciled funding/broker state and confirmed models.
Direct broker check remained $30,000 cash/equity, zero positions/open orders. Cohort
counts, frozen protocol hash, branch cash and zero filled-order count matched the
pre-upgrade baseline. The original Friday daily review and original source reports
remain preserved. Four current reviewed cards have explicit source attestations;
thirteen are held. Actual next-session feature freshness, improved decision quality
and regular-session fill/exit remain unproven; no paid resources or risk increases.

## Adaptive return-engine audit — October 31, 2026

Audited the gap between research activity and measurable economic learning. Added
immutable observation leads, continuing discovery, independent local-method versus
external-source review, typed future-only observation contracts, explicit test
handoff, return/cost-stress/drawdown metrics and later-session development effects.
Original fixed study, account allocation, execution/risk gates and free-only policy
were preserved. ADAPTIVE_ENGINE_AUDIT.md records rationale and challenges to vision.

Independent code reviews identified and resolved scheduler fallthrough, evidence
linkage, older-reference retrieval, complete-packet budgeting, malformed timestamps
and research fault isolation. Actual model integration exposed required-field schema
compatibility, catalogue displacement, an infeasible signal budget and an unsupported
symbol. The supported universe is now explicit in schema/context; mathematical and
metric constraints are explicit. Rejected completed replies retain their private
payload and measured usage. An independent reviewer also rejected an unsupported
historical statement and requested implemented measurement definitions. The repaired
specification uses the actual all-opportunity metric and was independently accepted
for descriptive testing only; original drafts/rejections remain recorded.

Two contracts now bind six symbols over sixty actual entry sessions, November 2–
January 28, each 360 preregistered opportunities. All 720 remain pending; zero adaptive
outcomes, orders or promotions. Catalogue: four source-reviewed plus one local
observation/method-reviewed hypothesis; thirteen held. The fixed study remains
174 closed / 174 open / 12 not evaluable, with identical protocol hash; cash remains $10,000 per
branch and filled-order count 0. Return is 0%, no edge established.

Full local suite: 368 passed, including 198 runtime tests; one unchanged legacy
websockets deprecation warning. Runtime/test lint and native JavaScript syntax pass.
All seven actual populated views passed at 1440px / 390px QA, expanded contracts and real
observations included, no errors/overflow. Receipts are retained privately under
.runtime/integrated-learning-populated-*. Final CI/deployment activation follows.

### Adaptive upgrade release verification

Source 513767466a32fd5548ab6687ed39944c8e16abf3 passed GitHub Tests run 41220429757:
full regression suite, locked dependency install, runtime lint and JavaScript syntax.
Snapshot 79105e12 initiated Pages run 41220441316. The actual post-registration knowledge
handoff includes both prospective contracts; current morning/review prompt lengths
22,704 / 24,421 remain complete under the 28,000-character ceiling. The fixed study hash,
174/174/12 counts, branch cash and zero fills match the prior baseline after all real
research and calendar-binding runs. Service/public activation follows this receipt.

Activation verified: systemd service is active, refreshed heartbeat/reconciliation,
models available, entry budget unblocked, and independent hidden watchdog reports
no incident. Both pause flags are absent. Startup snapshot 0cd05959 deployed through
Pages run 41220542958. Public seven-view desktop/mobile QA confirmed source 51376746,
two studies / 720 pending opportunities, five reviewed hypotheses and three actual
observation leads. No errors or overflow; no preview servers remain. Profitability
and the regular-session paper entry/exit gate remain unproven.


## November 7, 2026 — useful research capacity and runtime refinement

User authorized a broader cleanup and substantially increased useful subscription
work, targeting 50–80% weekly allowance. Initial live account meter was 2%; later
maintenance readings reached 16%. These are account-wide readings, not an exact
repo token budget. The existing 80% stop/20% reserve and no-paid-fallback policy
remain. Consumption target completion is not claimed by this release receipt.

Implemented a distinct bounded off-hours/weekend research queue: 20 questions from
retained evidence, high-effort analyst then fresh skeptical reviewer, immutable
packets, no unchanged-evidence loops, bounded retries/revisions and safe feedback.
Accepted research has expiry; expired verified URLs remain leads requiring a fresh
source check. No order, promotion or automatic code-edit authority is granted.
Core 16/20/24 daily attempt slots remain separate from up to 96 background attempts.
Admission and attempt reservation are atomic across processes, charged to actual
Eastern admission day. Every quota bucket is checked; missing/stale/malformed
telemetry fails closed. Streamed limits can interrupt a turn; in-flight percentage
overshoot remains possible because the meter is account-wide and rounded.

The eight challenger experiments were starved upstream by zero valid parent plans.
Added prospective eligibility counts and event/evidence checks for both plan paths,
immutable eligibility versions, stale-parent/mixed-scope promotion blocking and
not-evaluable missed intraday exits. No samples were invented. Adaptive prompt
arithmetic now reflects actual opportunity bounds; the frozen USO 120-vs60 prose
mismatch is recorded as a historical caveat, not silently rewritten.

Morning source work is expanded and prioritized around company-event coverage.
Whole-prompt budgeting preserves current prices/features before optional old
context. Retained packet replays fit; price fields distinguish evolving session
bars from dated prior closes. Phase-aware quality replay matched eight November 5–6
reports to their exact inputs: preopen missing minute features were expected;
regular-session features were present. Raw word mentions no longer imply missing
input defects on their own.

Failure telemetry now links request/schema/attempt IDs, safe validation paths,
partial reported tokens and application outcomes. Valid replies survive metadata
refresh faults but entries remain blocked. Private rejected artifacts are retained.
Actual early background checks exposed an out-of-range source reference and two
oversized reports; their exact replies were recovered from their own app-server
threads and preserved as rejected artifacts. Prompts gained explicit 7,000-character
response targets, source-index lists and bounded retry feedback; gates stayed strict.
A skeptical reviewer requested a correction before the experiment-lifecycle report
was accepted. Other accepted analyses and held/revised outcomes remain distinct.

Jobs now have boot/process/start identity and unique claims. Recovery cannot steal
live independent probes or finish successor jobs. Dead capped jobs enter scoped
backoff. Unknown legacy owners are not inferred dead from age. Concurrent cold
SQLite initialization retries only a bounded WAL lock contention.

The execution review repaired confirmed-terminal exit retries, cross-date pending
liquidation handling, post-cancel reconciliation, done_for_day recovery/reservations,
exact protection coverage, rounded-price risk/cash sizing, fresh validation after
asset lookup, broker identity/authorized quantity checks and nonfinite/corrected
broker data handling. Intraday closing and next-session overdue recovery precede
quote-dependent protection repair. Independent code review caught and fixed a
pending-order variable overwrite before activation.

Current execution kernel is paper-execution-20261107. Production preflight requires
its own bounded regular-session acceptance. November 2 historical verification/time
are preserved; new-version market acceptance remains pending. No maintenance work
submitted a broker order. The next actual regular session may perform the existing
bounded one-share check; code tests do not substitute for that receipt.

Read-only complete account-activity intake identified posted CAT-$0.01 and
REG-$0.02 fees for the uniquely matched November 2 intraday executions. After
immutable receipt, exact-fill linkage and cash-bridge checks, these two fees were
explicitly booked once. Branch cash now matches broker $29,999.84 exactly; future
intake is read-only and does not auto-book charges. Raw activity IDs/descriptions
remain private. Dashboard totals use broker cash/equity and actual position exposure.

Evidence preservation check: orders 8, positions 0, plans 0; fixed expectations and
observations 1,440 each; adaptive contracts 3 and observations 780. Counts, frozen study
metadata and specification hashes match the maintenance baseline. Only the two
proved fees changed branch cash. Original reports and historical findings remain.

Local verification: full regression run 533 passed with the existing single legacy
websockets deprecation warning; later focused research/application/scheduler
integration 107 passed, final research-work 36 passed and execution-version 14 passed.
Active runtime/tests lint, JavaScript syntax and diff-whitespace checks passed.
All seven populated views passed browser QA at exact 1440px and 390px widths using
CDP: no JavaScript errors or horizontal overflow, correct $0 exposure and broker cash.
Native Edge window sizing alone measured 492px for the requested 390px, so those
older receipts were superseded by measured CDP viewport checks.

Source CI, activation and subsequent live-loop receipts follow separately.

Source d844f079 was published in snapshot b96b296e. Tests run 42414531421 and Pages
run 42414531427 both completed successfully. The local service restarted at
2026-11-07T21:10:29.563043Z and resumed useful analyst/reviewer jobs with a fresh
heartbeat, reconciled market-closed state and no maintenance pause. Public-site
browser QA then passed all seven views at exact 1440px and 390px widths, with no
JavaScript errors/overflow and the correct $29,999.84 cash/equity and $0 exposure.
The verified release receipt preserves this actual activation time and cloud run
IDs; old October activation fields no longer stand in for this release.

The live loop accepted an evidence-integrity review and independently reviewed
NVDA/AMD event coverage. Subsequent audit found the event report was too large for
the morning handoff and was omitted, motivating a bounded, purpose-aware handoff
repair. Additional isolated boundary audits found operational CLI ownership and
connectivity-budget gaps, exit handling coupled to quote availability, protective
order ancestry loss, and a publisher staged-file allowlist gap. Follow-up changes
are being validated under a maintenance stop after the active research task ended.
At 21:20:15Z the live account meter was 19%; the requested 80% objective remains
in progress, with no exact repo-attributable weekly token denominator claimed.

## November 7 follow-up — operational boundaries and prospective evidence

Independent reproductions drove a second controlled release. Nested broker order
retrieval now preserves bracket ancestry through partial fills. Approved exits run
before quote-dependent stop repair or quote fetching, retaining ownership checks
and cancellation/reconciliation gates. Monotonic elapsed time advances the session
clock after slow requests; crossing closing cutoffs routes to closing, while an
actual-close boundary cannot authorize another market exit. The revised execution
kernel is paper-execution-20261107-r2; its regular-session acceptance is pending.

Operational CLI commands share the supervisor ownership lock through worker cleanup.
One-shot ticks apply their completed result. Connectivity checks use two measured,
quota-admitted turns rather than a raw uncounted inference path. Graceful shutdown
records safe background reports and preserves other completed replies privately as
deferred, without applying order/cancel/promotion/source-edit authority. A reproduced
rollback defect in job completion was repaired: in-memory claims release only after
the database commit, with SQL/commit failures and retry behavior covered by tests.

Publication now protects exact generated paths, unrelated staged drafts, configured
branch ownership and a reviewed source-commit ancestor. It rejects intervening
source commits even if later reverted, and rejects dirty tracked source. The actual
validated SHA is passed through the hidden Windows launcher and pushed normally.
The established local branch remains disable-claude-enable-gpt-only, configured
privately as the permitted publication branch; Git history was not rewritten.
Windows PowerShell parsing and invalid/missing SHA rejection were checked without
a push during tests. Failed account-activity intake now has bounded same-day retry.

Actual event-research replay exposed a handoff truncation problem. The bounded
projection now preserves complete relevant claims, qualifications and cited source
receipts; at 3,000 characters it retains the verified NVDA and macro findings.
Held/revised newer generations suppress older accepted conclusions. Reviewer timing
cannot renew a stale source check. Runtime packets now distinguish six 78-slot
historical coverage receipts from current-kernel verification; accounting packets
include the actual $30,000 journal and signed fill/fee totals with scoped cutoffs.
Refresh-only timestamps cannot create a new research question. Quota deltas compare
one stable bucket identity; reset/missing/legacy measurements display unreported.

The fixed-study audit found that 29 October 30 observations and one November 2 XOM
observation give each date 50% weight under the frozen estimator. Additive composition
tables now show that concentration. New quote sidecars retain bid/ask/time, costs and
hashes atomically; no historical quote field was invented. Both absolute estimators
are visible, and their sign disagreement cannot pass the newly reviewed policy.
At 21:42:58.772258Z an independent global approval of
paired-entry-date-absolute-v2 was recorded, plus explicit prospective receipts for
the eight current zero-observation/no-prior-look challengers. Future registrations
pin the globally approved exact version before sampling. Historical contracts are
unchanged; review looks, promotion and rollback now commit atomically.

Prospective fixed-cohort input validation requires the explicit prior 21 broker
sessions, with hash-addressed calendar receipts. Stale or internally missing daily
bars cannot become signals; absent SPY regime evidence excludes only its dependent
rule. All six existing freezes passed a fresh read-only broker-calendar comparison:
180 of 180 symbol/date sequences matched. Existing freezes/protocol hashes remain
unchanged. Minute data must lie on minute boundaries; macro parsing excludes
nonfinite numbers and selects the latest valid dated value even in unsorted rows.
Provider timestamp/aggregation semantics were checked against the official Alpaca
Market Data FAQ: https://docs.alpaca.markets/us/docs/market-data-faq.

Full follow-up regression: 660 passed, with the existing single legacy websockets
deprecation warning. Active runtime/tests lint, JavaScript syntax and whitespace
checks passed. Local browser QA passed all seven views at 1440px and 390px, including
expanded date-weight tables; no JavaScript errors or page overflow. A sensitive-value
scan of the 41 changed/new release files found no configured secret, private order
identity or model-thread identity. Cloud and activation receipts follow in local
release metadata. No maintenance broker order was submitted.

Automatic safety review rejected the optional maintenance sandbox audit and its
narrower follow-up. That portion remains unverified; this is not a finding of a
repository vulnerability. The ordinary data/recovery/research reviews above completed.
