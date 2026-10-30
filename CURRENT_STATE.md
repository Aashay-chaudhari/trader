# Current state — October 29, 2026 evening

The application is a local, free-data, subscription-authenticated paper-trading
research laboratory. The original vision is in REFACTOR_SCOPE.md; the latest
research/architecture upgrade is in IMPROVEMENT_SCOPE_20261029.md.

- Alpaca paper account: $30,000 cash/equity, three separate $10,000 allocations.
  No positions/open orders/fills at the latest direct check. No borrowing/live endpoint.
- October 29 was operationally missed after the heartbeat stopped at 08:12 ET.
  The initiating termination source remains unknown. No strategy result is inferred.
- A lingering systemd user service now owns Python. Hidden Windows host/watchdog
  tasks keep WSL alive, independently recover the service and send health alerts.
  Interrupt/crash/stopped-service drills passed; a whole unattended session is unproven.
- Paper submission/cancellation passed. The actual market-open fill/exit gate is
  pending and normal equity pilots remain blocked until it passes. Options stay
  indicative-data research/shadow only.
- The 19:00 one-time research timer completed successfully. Its two hypotheses
  were held for revision; isolated dummy checks separately verified positive retrieval.
- An additional independent design review accepted two repaired observational
  definitions for testing. Six total catalogue cards are source/method-reviewed;
  no card or strategy is certified profitable. Reviewed cards feed morning research.
- Twelve historical screens and eight filter challengers remain intact. A new
  separate fixed signal lab preregisters twelve protocols across thirty symbols:
  360 opportunities prepared for October 30, zero actual cohort observations yet.
  Entry study window is October 30–November 27; final swing maturity December 3.
- BEA official calendar loads; BLS direct requests return 403 and stay explicitly
  unavailable. Fed/earnings require separate official-page verification. Thirty
  daily indicator sets and five dated FRED series are available from free sources.
- Role contexts are bounded, complete review packets preserve units/selection, and
  failed inference attempts disclose missing token totals. All quota/risk rules remain.
- GitHub Pages has seven views, including Project & progress with repo map,
  decisions, automation schedule, resources and a candid evidence-based assessment.

Normal owner: `agent-trader.service`. Operator procedures: SYSTEM_GUIDE.md.
Verification receipts and deployment details: IMPLEMENTATION_LOG.md and READINESS.md.
Private `.runtime/` and `.env` stay local; Git history and existing paper ledgers persist.
