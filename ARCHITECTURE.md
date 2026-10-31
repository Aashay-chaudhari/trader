# Architecture

```text
Hidden Windows WSL host + independent 2-minute watchdog
  └─ lingering systemd user service → WSL local supervisor
  ├─ Python / 30-second tick
  │    ├─ Alpaca PAPER account, calendar, IEX data, orders and fills
  │    ├─ SQLite transactional branch ledger and durable work queue
  │    ├─ deterministic limits, trigger revalidation, protective orders, closing
  │    └─ sanitized static snapshot → Git push → Actions → GitHub Pages
  ├─ one bounded background model worker
  │    └─ local Codex app-server / existing subscription authentication
  │         ├─ bounded role-specific threads, role/model selection between turns
  │         ├─ morning researcher, official calendars and live web event updates
  │         ├─ entry reviewer, daily retrospective, controlled maintenance
  │         └─ structured JSON validated before entering runtime state
  └─ ntfy free push notifications
```

The execution kernel has no live endpoint and no paid data/model fallback.
Research cannot access broker credentials through its environment or submit orders.
Shell and app tools are disabled for research. Model approval/permission requests
are rejected; read-only agent turns operate in a separate workspace.

SQLite lives at `.runtime/trader.sqlite3` and uses WAL transactions. An intent is
persisted before submission. Broker client IDs are deterministic; timeout recovery
queries the same ID. An ambiguous prepared intent blocks further entries rather
than being blindly replayed. Parent and protective-leg fills update branch cash and
holdings incrementally using cumulative filled quantities and notionals.

Branches share one account but maintain distinct capital/results. A symbol has a
single branch owner. Actual broker positions, cash and orders must reconcile with
the ledger. Unrecognized activity blocks new entries. Broker protective orders
remain independent of local model availability.

Research results create immutable plans. Approval is short-lived and prices/risk
are checked again immediately before submission. A material event update invalidates
approvals and requests fresh research. No plan is manufactured to guarantee activity.

Experiments record paired forward observations with explicit conservative costs.
Promotion changes only supported filters within fixed risk. Maintenance candidates
are committed in isolated worktrees and remain shadow candidates until evaluated.
The kernel, test suite, and promotion criteria are outside the automated mutation path.

Only `docs/index.html`, `style.css`, `app.js`, `data/lab.json`, and `.nojekyll` are
published. Raw credentials, SQLite files and session artifacts are excluded.
Publisher failures do not stop trading protection. GitHub is not a runtime dependency
for order handling. See `SYSTEM_GUIDE.md` for failure recovery and current limits.

## Runtime ownership and independent recovery

The systemd user service owns Python. A GUI-hosted Windows task anchors WSL without
a terminal window. A separate GUI-hosted task checks heartbeat/service state every
two minutes and can restart the host/service and alert through ntfy without Python.
The heartbeat file is written before broker checks and does not depend on GitHub
publication. Graceful signal exits and forced crashes are covered by systemd's
Restart=always; an intentional service stop is covered by the Windows watchdog.
User lingering is enabled. This remains a local-PC design requiring Windows sign-in
after reboot; complete power/network outages cannot self-report immediately.

## Research evidence and context

`cohorts.py` is a deterministic observational path, separate from execution and
paired filter promotion. Before the open it freezes prior completed IEX daily bars,
exact normalized inputs, flags and hashes. A fixed twenty-entry-session study uses
actual broker sessions for one/five-session horizons, first eligible ask entries
and bid exits, explicit assumed cost buffers and missing-data denominators.
The lab has no broker order authority. Auxiliary lab/coverage failures are caught
so they cannot interrupt an owned-position exit or the closing path.

`calendars.py` caches official BEA/BLS feeds with provenance and failure backoff.
Source failures remain unavailable/stale, not evidence of an empty calendar. Fed
and earnings still require separate primary-source checks. `project.py` derives
public decisions, schedule, coverage and evidence milestones from recorded state.
Restart drills never substitute for whole-session or fill/exit verification.

The model harness hands roles explicit durable knowledge, rotates after two turns
or large measured input, and gives decision/reviewer roles fresh contexts. Complete
bounded JSON packets replace raw string truncation for retrospective evidence.
Soft budget steering asks for an answer after a completed tool item; hard runtime,
search, cycle, account-reserve and daily-call ceilings remain in force. Failed
attempts retain an explicit unreported-token status rather than appearing free.

## Research-quality feedback

Full market packets and structured model outputs are retained privately with task,
outcome and capture provenance. `quality.py` computes a bounded daily diagnostic
from those artifacts and measured usage, supplies it to retrospective/maintenance,
and deduplicates development proposals. It has no order or promotion authority.
`features.py` computes completed-bar IEX research context with missingness; it does
not change the preregistered signal lab. Source reuse requires explicit reviewer
attestations and matching checked URLs, not mere URL presence. Partial/blocked
checks are held, and original reports remain historical. Period rollups can reuse
an existing review only when no earlier retained evidence broadens their window.
