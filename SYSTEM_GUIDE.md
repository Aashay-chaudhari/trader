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
