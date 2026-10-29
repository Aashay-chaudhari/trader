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
  registered and verified; release reload/CI evidence is in the implementation log.

Do not use legacy cloud trading or the old phase runner. The active command is
`.venv/bin/python -m agent_trader run`, normally launched by the Windows task.

The market-open fill/exit gate is intentionally pending, not a completed test.
Normal entries are blocked until it passes. CLI/quota outages block new entries
without interrupting the deterministic broker/closing path.

See READINESS.md for verified behavior, the first-session schedule and boundaries.
