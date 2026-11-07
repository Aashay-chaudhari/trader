# Operations and recovery

## Daily operation

The `agent-trader.service` **systemd user service** owns the Python supervisor.
It restarts after clean exits and crashes, independently of terminal windows. User
lingering is enabled. A hidden Windows task, `AgentTrader-WSLHost`, keeps the WSL
instance alive; services alone do not prevent WSL's idle shutdown.

`AgentTrader-IndependentWatchdog` runs every two minutes and at sign-in, through a
GUI launcher that opens no console. It checks `.runtime/heartbeat.json` and the
service, restores a stopped host/service, restarts a service with a stale heartbeat,
and sends deduplicated ntfy incident/recovery alerts directly from Windows.
The old visible `AgentTrader-LocalSupervisor` task is disabled.

The desktop can be locked. Sign in after a Windows reboot; keep power/network
available. Both the service and its Windows recovery mechanism remain local to
this PC, so neither can report a complete power/network outage in real time.

Install/update from WSL:

```bash
bash scripts/runtime/install-service.sh
/mnt/c/Windows/System32/wscript.exe //B //NoLogo 'C:\Users\aasha\Desktop\trader\scripts\runtime\hidden-launch.vbs' install
```

Inspect without opening a PowerShell console:

```bash
systemctl --user status agent-trader.service
journalctl --user -u agent-trader.service -n 40
/mnt/c/Windows/System32/wscript.exe //B //NoLogo 'C:\Users\aasha\Desktop\trader\scripts\runtime\hidden-launch.vbs' status
cat .runtime/windows-inspection.json
```

For an intentional maintenance stop, pause the watchdog **before** stopping the
service; otherwise the watchdog correctly restores it:

```bash
touch .runtime/maintenance.flag
systemctl --user stop agent-trader.service
# perform maintenance
rm .runtime/maintenance.flag
systemctl --user start agent-trader.service
```

`.runtime/agent-pause.flag` pauses new model jobs only, preserving Python broker
reconciliation and closing. Remove it to resume research/review. The watchdog
remains active during this model pause.

The supervisor uses Eastern market-calendar times: startup notification at/after
07:45 ET, research from 08:15, and broker-calendar closing routines. A late startup
reports its actual time; it cannot recreate a missed trading session.

## Operator commands (from repo root in WSL)

```bash
.venv/bin/python -m agent_trader status
.venv/bin/python -m agent_trader doctor
.venv/bin/python -m agent_trader dashboard
.venv/bin/python -m agent_trader publish
```

Read `.runtime/supervisor.log`, `.runtime/launcher.log`, `.runtime/watchdog.log`
and `journalctl --user -u agent-trader.service` locally. Private state
must never be pasted into a public issue or committed wholesale.

## Launch gates

Read-only broker checks, model availability and funded ledgers must pass. The
preflight submission check verifies an accepted/canceled $1 SPY limit, not a fill.
At/after 09:32 ET, a controlled one-share SPY paper round-trip verifies an actual
entry fill, closing fill and final reconciliation. Until that succeeds, normal
entries remain blocked and the dashboard says research/shadow. The smoke position
has broker-held protective bracket orders. No other intraday entries run during it.

The check records its exact one-share SPY intent and a two-minute expiry before
submission. Cleanup recognizes only the matching persisted client ID, day, branch,
symbol and quantity; prefix matches, missing metadata and extended expiries do not
qualify. A branch pause, entry cutoff or expiry still cancels it. A cancellation
request is recorded separately from a broker-fed terminal state. A restart never
creates another entry for the same daily check. Partial fills are unwound, but do
not satisfy the complete one-share gate. Passing requires confirmed entry and exit
fills plus successful reconciliation and no remaining intraday holdings/SPY orders.

Free IEX quotes must be fresh and sufficiently narrow. Missing data or an unfilled
smoke check can prevent paper pilots from activating; that is reported explicitly.
Options remain research/shadow because indicative data cannot establish executable
prices. Their allocation remains reserved. No live trading is supported.

## Failure behavior

- Missing/stale quotes, stale approval, unknown event risk: reject entry.
- Broker timeout: query deterministic client ID; never blindly duplicate.
- External positions/orders or cash mismatch: halt entries and alert. Inspect
  account activity, reconcile attribution deliberately; do not overwrite the ledger.
- Partial fills: book only the broker-confirmed delta. Preserve outstanding capital.
- Quota/auth/model failure: bounded retries; no paid fallback. Broker protection,
  reconciliation and intraday closing use Python independently.
- Publishing failure: local operation continues; the site shows its snapshot time.
- Intraday closing failure: retry before close and alert if holdings remain.
- Broker-held stop orders can gap or fail to fill; they are not guaranteed loss caps.
- An isolated maintenance candidate that fails validation cannot become active.

A local PC/power/network outage can still prevent scheduled actions. Waking a PC is
not a guarantee against outages. The independent Windows watchdog covers the Python/WSL process, but no external
always-on monitor is included.

## Emergency entry pause

Set `TRADER_EXECUTION=false` in `.env`, terminate the supervisor with SIGTERM and
restart it. This disables new entries and the execution smoke check; it does not
cancel broker-held protective orders. Use the Alpaca dashboard for urgent account
inspection. Deterministic closing/reconciliation remains enabled in the runtime.

## Application reset

Stop the supervisor, verify a flat broker account with no open orders, then:

```bash
.venv/bin/python -m agent_trader reset --confirm RESET
```

This archives application state and old published artifacts under ignored
`.runtime/archive/`, starts fresh $10,000 branch ledgers, and preserves Git history.
It does not reset or delete the Alpaca account. A non-flat broker account blocks reset.
The first trading date comes from `.env`. Re-run doctor/smoke and publish afterwards.

## Maintenance and rollback

New pure strategy-filter code lives in an isolated `maintenance/<id>` branch and
worktree. It must pass static checks, regression tests and forward paired evaluation
before activation. The current executable extension is identified by a content hash.
Promotion is staged at reduced risk. Risk enforcement and promotion rules are fixed.
Rollback removes the active extension/filter reference while leaving the ledger and
all historical plans/fills intact. Never use git reset to roll back broker state.

## GitHub Pages

Two active workflows remain: Tests and Publish Dashboard. The local publisher
commits sanitized snapshots at most every 15 minutes. Manual `publish` is available
for milestones. Pages adds deployment latency; check snapshot and heartbeat times.
Windows Git Credential Manager is the fallback for authenticated pushes from WSL.
The public dashboard has no authenticated execution controls. A published heartbeat
older than 35 minutes is flagged; publication normally occurs every 15 minutes.

## Isolated research checks and one-time schedules

Operational checks use the real free-data/inference/schema/reviewer paths but keep
research state in ignored `.runtime/probes/<id>/`. They cannot submit orders,
register production challengers, replace the production brief or import knowledge.
Usage is still charged to the existing project quota/call allowance. Start and
completion/failure notifications are sent through the normal ntfy destination.

```bash
.venv/bin/python -m agent_trader.runtime.probe --id my-research-check --kind research --quick
.venv/bin/python -m agent_trader.runtime.probe --id my-hypothesis-check --kind hypotheses --quick
.venv/bin/python -m agent_trader.runtime.probe --id adhoc-20261029-1900 --schedule-at 2026-10-29T19:00:00-04:00
systemctl --user list-timers 'agent-trader-probe-*'
```

One-time timers specify America/New_York explicitly and persist across a restart.
A full scheduled check runs research, hypothesis generation, separate review and a
scratch morning-handoff check. The status/events are in the local ledger and public
journal; full reports remain private. IDs are idempotent after success. A failed
check can be retried once under the same ID; changing IDs must not bypass budgets.

## Fixed signal lab and evidence integrity

The lab is automatic and observational: it has no order API or allocated capital.
Morning market-data preparation freezes prior completed daily IEX bars, rule flags,
exact normalized inputs and hashes privately in SQLite. Frozen inputs cannot be
replaced by a later provider revision. Entries observe first valid quotes from
open+5 to open+30; exits observe the recorded session close−12 minute window on
holding session one or five. Early closes and DST follow the broker calendar.

The first study preregisters twenty entry dates (October 30–November 27), followed
by four possible swing-maturation sessions (final review after December 3 close).
All twelve variants are reported; daily provisional results cannot trigger promotion
or extend the window to find a winner. Missing entry/exit quotes are not evaluable,
never synthetic fills or zero returns. Missing-history and overlap exclusions are
reported separately. Observed abstentions may earn zero; net results condition on
valid observations and are holding-horizon unit returns, not account P&L.

`cohort_expected` is the opportunity denominator; `cohort_observations` contains
open/closed/not-evaluable records. `cohort-inputs:<date>` retains private frozen
inputs, `cohort-signals:<date>` their decision flags/hash, and `cohort_study` the
fixed contract/reporting window. A protocol change after the study starts is rejected.
Pre-observation amendments archive the original protocol hash explicitly.

`session_health` records broker-confirmed five-minute slots. The Project view
requires a fully instrumented completed session, at least 95% recorded slots and
no unobserved gap above ten minutes before calling coverage complete. This is
separate from the heartbeat, research availability, fills and restart drills.

## Research context and official public resources

BEA/BLS official ICS results are cached for six hours; recent failures back off for
thirty minutes. Missing feeds remain unknown, and stale cached events are labeled.
These feeds do not cover Fed policy meetings or a complete earnings calendar.
Primary-source web verification remains necessary. Never substitute delayed FRED
observations or indicative options data for current execution quotes.

Roles get separate bounded contexts and explicit durable knowledge. Threads rotate
after two turns or a measured input above 48,000 tokens; decision and independent
review turns start fresh. Review packets contain complete selected JSON objects,
counts and selection limits. Soft budget notices do not increase hard limits;
failed/started calls with unreported totals are disclosed in System & usage.

The one-off production design audit can be inspected with:

```bash
.venv/bin/python -m agent_trader.runtime.audit
```

It is idempotent after success, budgeted and scratch-isolated; only source/method
reviewed definitions enter knowledge. It cannot create plans/contracts or certify
profitability. Reports live under ignored `.runtime/audits/`. It is not a recurring
nightly job. Normal retrospectives and controlled maintenance retain their schedule.

Both morning research and daily/periodic retrospectives receive a complete compact
forward-evidence digest: study window/hash, all twelve trial denominators, missing
data, net/baseline/stressed horizon means and observed session count. Provisional
results may explain data gaps; they cannot tune or promote the fixed study.

## Operational evidence and follow-up review

Retrospectives include broker-fed order statuses and confirmation timestamps,
execution-check state, last reconciliation/errors, bounded incident details and
explicit selection counts. Period boundaries use Eastern midnight converted to
UTC, so a daily review does not accidentally include the previous evening.
A tested code repair remains separate from a real regular-session fill/exit check.

Operational code-change proposals are stored in the `improvement_proposal` memory
layer. Automated maintenance still edits only the pure adaptive strategy filter;
it cannot change runtime/risk/promotion code. A developer handles broader proposals.
Confirmed diagnoses and repair evidence use `operational_finding`; a follow-up
review uses `operational_review` and preserves the original daily review. The latest
follow-up is visible in Project & progress and its summary in the decision journal.

## Daily research-quality audit and development backlog

Every completed research, exploration, validation, pulse and review task archives
its full structured output with task identity, outcome and capture provenance.
Research intake also preserves the supplied market packet privately. Rejected
outputs stay distinct from adopted output; surviving legacy snapshots are labeled
partial history and never presented as complete old research transcripts.

`quality.py` derives a daily audit from measured model/web usage, artifacts,
reported input/source blockers, catalogue verification and redundant work. It runs
before retrospective and after completed model tasks, feeds complete bounded
context to retrospective and maintenance, and updates deduplicated
`quality-proposal:<finding>` records in the `improvement_proposal` memory layer.
Audit findings are diagnostics, not an accuracy or profitability score. The latest
snapshot appears in Project & progress. Full artifacts remain local in SQLite.

Reviewer verdicts now require explicit `source_check_status=verified` and matching
`checked_source_urls` for every cited source before a card can be reused as reviewed
or authorize a new experiment. Blocked/partial/supplied-only checks are held.
These fields are reviewer attestations; URL consistency checks do not authenticate
page contents. Original reports and before/after card versions remain recorded.

Numerical research uses exact one/three/five-session returns and, during the regular
session, completed one-minute IEX bars: opening range, volume, highs/lows and
volume-weighted provider bar VWAP. Missing bars/fields and age are explicit. No
synthetic VWAP or opening-range fill is created. Bounded pagination rejects an
unfinished batch instead of silently dropping later symbols. A three-symbol research
focus prioritizes data readiness then absolute five-session return; it does not
approve trades or modify the fixed forward-study universe or signal rules.

Without positions or eligible plans, there is one 13:00 ET context pulse. With
exposure/plans, the existing 11:00/13:00/14:30 checkpoints remain. Pulses receive
current time and recent updates, not the entire stale morning transcript. Period
reviews can reuse an existing review only when the larger window adds no retained
substantive events, orders or equity records. Derived rollups are explicitly labeled
and consume no inference call; earlier failures prevent inappropriate reuse.

Runtime/data changes still require controlled developer work. Automatic maintenance
can only edit the pure adaptive strategy filter; audit findings cannot expand it.
Free-only data, existing account quota reserve, execution/risk gates and frozen
cohort protocol remain unchanged. See RESEARCH_QUALITY_AUDIT.md for audit receipts.

## Return objective and adaptive research

The Project view reports reconciled account returns, explicit extra-friction stress,
prospective verified drawdown and learning/development bottlenecks. Strategy lab
shows independently reviewed adaptive observation studies and their motivating
questions. The original fixed forward study remains separate and unchanged.

Discovery continues after ten mornings for new observations/expired cards and Monday
review. Supported new studies need no executable trade plan and have no broker
permission. Their registration and exact definitions are immutable. Research prompt
budgets retain complete records; oversized inputs fail before a model call. Broad
runtime maintenance remains a developer release task, not unattended kernel mutation.
Post-change mechanics are assessed only on later completed sessions, with preserved
baseline metadata and explicit evidence scope. See ADAPTIVE_ENGINE_AUDIT.md.


## Focused background research — November 7

Weekends, overnight before 07:00 ET, and after the actual close plus 90 minutes,
the free worker can investigate unresolved retained evidence. Core daily/weekly
reviews receive scheduling priority. The queue covers event/source verification,
company-specific coverage, feature lineage, sampling, accounting and reliability.
Four additional questions follow exact held-card identities: VIX horizon/units,
earnings IV coverage, reversal evidence lineage and rally/giveback universe
consistency. They preserve original drafts, contracts, contrary evidence and
missing-source receipts. Quote refreshes and repeated unchanged drafts do not
create new work. Each analyst report requires a fresh independent reviewer. Accepted reports have
explicit validity windows and enter research context only; they cannot submit
orders, promote filters, edit code, or rewrite frozen studies.

Unchanged question/evidence combinations are deduplicated. At most two requested
revisions and two attempts per stage are allowed, with a 30-minute failure cooldown.
A queue with no distinct useful work waits for new evidence. The System/Project
views show measured usage, question status and reviewed outcomes.

The user-requested weekly objective is 50–80% account usage, with admission blocked
at 80% and no paid fallback/reset-credit use. Core work retains its 16 ordinary /
20 decision /24 review daily attempt limits; background work has up to 96 separate
attempts per day. Fresh account telemetry is checked before inference and streamed
limit updates can interrupt a turn. Quota is account-wide and rounded: raw task
tokens are measured separately, and an in-flight turn can cross a reported limit.
An objective is not a guarantee that sufficient useful work or allowance exists.

Use .runtime/agent-pause.flag to pause all model jobs while Python protection
continues. Existing maintenance/watchdog procedures remain unchanged.


## Prospective options coverage

The coverage probe is a one-time, independently reviewed registration, separate
from the ordinary morning chain sample. It can make at most 12 read-only HTTP
attempts over its entire registration; interrupted requests consume reservations.
It uses no model turn and grants no order, promotion or execution authority.

The first future broker session is fixed at registration. At open +30 minutes,
metadata selects the earliest eligible 7–14-calendar-day expiry and nearest strike
with both a standard 100-share call and put, within ±1% of the initial underlying
midpoint. SPY and QQQ retain those same contracts at open +45 minutes. Both receipt
windows last two minutes. Selection never depends on IV availability. Pagination
must be complete within its bound, and missing metadata never becomes a default.
The denominator remains eight planned contract observations even when selection,
collection or a window fails. No rescheduling, retry, substitute contract or backfill.

Protection, closing, position review, candidate decisions and quota refresh keep
priority. A busy or paused worker can miss a window; the result remains explicitly
unknown. A changed broker-session calendar prevents collection under the old window.
The existing morning sampler continues independently and does not spend this
registration's request reservations.

The Options view separates the frozen old sampler, future fixed selections and
same-window legacy sampler comparisons. Positive IV, fresh ordered quotes and a
nearby underlying timestamp are coverage checks. They cannot establish synchronized
valuation because IV/Greek as-of times are unavailable. Indicative quotes are
modified and are not executable OPRA quotes. This ETF probe cannot establish an
issuer earnings effect or profitable option strategy.

Register only after review of the exact protocol hash and completed tests, while
the supervisor is stopped under the normal maintenance procedure. Preserve the
calendar receipt and original baseline. An existing registration cannot be silently
replaced or extended. The [VIX variance-gap proposal](docs/research/vix-variance-gap-protocol.md)
is a separate design document, not a registered or scheduled study.

## Execution release verification and recovery

A release that changes execution semantics sets a new EXECUTION_KERNEL identifier.
Preflight records that required version; historical successful round trips retain
their original flag/time and receipts. Normal entries require a verified matching
version. The next eligible regular session runs the same bounded one-share paper
check; off-hours commands cannot manufacture acceptance. A previous version's
same-day check cannot cause a second daily entry or certify the new release.

Confirmed terminal rejected/canceled exits can be retried with distinct persisted
attempt IDs. Unconfirmed or nonterminal exits retain their identity and block a
duplicate. `done_for_day` remains nonterminal. Reconciliation must still pass after
canceling protection. Carried intraday exposure is recovered at the next confirmed
market session; liquidation takes priority over quote-dependent stop repair.
Broker quantity/identity changes and nonfinite fields block automatic accounting
or new execution until reviewed. These checks do not guarantee an available fill.

## Manual command ownership

`run`, `tick`, `doctor`, `reset`, `smoke`, `explore`, `research-test` and `agent-check`
require the same ownership lock. Stop the service before running them; use the
maintenance flag during planned work so the independent watchdog does not restart
it. `status`, `dashboard` and publication can read/export the running service's
state. The lock is held through command completion and worker cleanup. A one-shot
`tick` applies its completed worker result before releasing ownership.

`doctor` makes read-only external requests but updates local readiness and
reconciliation. `agent-check` uses two bounded turns on an isolated thread to
check a model switch; both require fresh quota admission and count toward the
ordinary daily allowance. Reaching the account reserve between turns stops the
second turn. Neither command certifies a market fill/exit.

Graceful shutdown retains completed worker evidence while holding ownership.
Background reports and data refreshes may finish their safe recording step.
Execution decisions, position reviews, pulses and maintenance replies are retained
privately as deferred, with their original token accounting; shutdown does not
apply their operational authority. A later scheduled task must reassess them.
An operating-system kill can still interrupt an unfinished turn.

## Publication review boundary

`TRADER_PUBLISH_BRANCH` names the established local release branch (default `main`).
Publication requires a reviewed `release.source_commit` ancestor. Every subsequent
commit and tracked working change must be limited to the five generated dashboard
paths; a source change followed by a revert still requires review. Unrelated staged
files are preserved and postpone publication. The publisher pushes the exact
validated commit SHA with a normal fast-forward push, including through the hidden
Windows launcher. Trading protection does not depend on publication succeeding.

## Prospective observation and promotion receipts

New observation transitions retain the exact bid, ask, quote time and cost terms
in immutable sidecar receipts. Earlier observations remain without those receipts;
their missing fields cannot be reconstructed later and presented as contemporaneous.
Date composition shows how equal-date estimates weight unequal numbers of outcomes.
The displayed date and symbol counts are not independent sample counts.

The reviewed `paired-entry-date-absolute-v2` promotion policy requires positive
absolute returns under both equal-date and equal-opportunity weighting, alongside
the existing paired, cost, minimum-evidence and rollback gates. Existing experiments
need an explicit zero-observation, no-prior-look migration receipt. A global approval
of the exact policy lets future registrations pin it before their first observation;
it cannot silently migrate historical studies. Policy and review bookkeeping are
atomic. Frozen experiment definitions and prior results are retained.
