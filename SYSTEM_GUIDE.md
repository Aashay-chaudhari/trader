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
