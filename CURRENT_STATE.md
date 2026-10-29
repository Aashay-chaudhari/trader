# Current state — October 29, 2026

The v2 local trading laboratory replaces the old local/cloud decision handoff.
The persistent scope is `REFACTOR_SCOPE.md`; observed checks and activation
evidence are in `IMPLEMENTATION_LOG.md`.

- First trading date: October 29, 2026.
- Paper account verified with $30,000 equity/cash, zero positions/open orders,
  options level 3. Three internal $10,000 allocations; no borrowing.
- Application state was reset and old artifacts archived locally. Git history kept.
- Paper submission/cancellation smoke check passed with zero fills. The actual
  fill/exit/reconciliation round-trip is gated until the market opens.
- Equity pilots remain disabled until that gate passes. Options remain shadow-only.
- CLI inference, same-thread model switching and live web research verified.
- Full frontend rebuilt and deployed to GitHub Pages. Windows scheduled task
  running independently of the editor; source CI passed and automatic snapshot
  publication was verified. Exact evidence is in the implementation log.

Do not use legacy cloud trading or the old phase runner. The active command is
`.venv/bin/python -m agent_trader run`, normally launched by the Windows task.

The market-open fill/exit gate is intentionally pending, not a completed test.
Normal entries are blocked until it passes. CLI/quota outages block new entries
without interrupting the deterministic broker/closing path.

See READINESS.md for verified behavior, the first-session schedule and boundaries.

The research sprint is enabled for the first ten research mornings. The initial
pass produced nine hypotheses from thirteen sources; four cards passed review and
automated reference checks for morning reuse. Twelve historical screens and eight
parallel shadow challengers are recorded. These are exploratory findings, not
proven strategies. See RESEARCH_WORKFLOW.md for the explicit daily handoff.

October 29 evening correction: the unattended process stopped at 08:12 ET and
missed the session. No fills, positions or forward shadow samples occurred. The
original visible task is disabled. A lingering systemd service, hidden WSL host
and independent two-minute Windows watchdog now own execution/recovery. Actual
interrupt, crash and stopped-service recovery drills passed. The initiating morning
termination source remains unconfirmed. See the implementation log for evidence.
