# Trader — the autonomous paper-trading laboratory

Trader runs locally on this Windows PC through WSL Ubuntu. A systemd-owned supervisor
uses authenticated Codex CLI sessions for research and judgment; Python owns broker
access, risk enforcement, fills, ledgers, recovery, and closing routines. GitHub
Pages publishes a sanitized, read-only view. No metered model API or paid data is used.

**First trading date: October 29, 2026.** Three separate $10,000 internal allocations:
long-only intraday equities/ETFs, long-only swing equities/ETFs, and options research.
Options remain shadow-only while using the free indicative feed. No borrowing.

- [Dashboard](https://aashay-chaudhari.github.io/trader/)
- [Final scope](REFACTOR_SCOPE.md)
- [Implementation evidence](IMPLEMENTATION_LOG.md)
- [Operations and recovery](SYSTEM_GUIDE.md)
- [Architecture](ARCHITECTURE.md)

## Operation

The lingering `agent-trader.service` systemd user service owns the runtime and
restarts it after exits/crashes. Hidden Windows tasks keep WSL alive and independently
check/recover the service every two minutes. The old visible-console task is disabled.
Schedules use `America/New_York` and Alpaca's holiday/early-close calendar. Windows
must remain powered, networked and signed in; locking the desktop is fine. Sign in
once after reboot to restore the user-owned WSL distribution and CLI authentication.

The supervisor sends a 07:45 ET phone notification, begins research at 08:15, checks
paper execution after 09:32, monitors throughout the session, begins intraday closing
12 minutes before the actual close, and runs reflection after close. Position
reconciliation and closing do not wait for a model response.

```bash
.venv/bin/python -m agent_trader status
.venv/bin/python -m agent_trader doctor
.venv/bin/python -m agent_trader dashboard
.venv/bin/python -m agent_trader publish
.venv/bin/python -m agent_trader run
```

`run` holds a single-instance lock. The systemd service is the normal execution owner.
`doctor` performs read-only broker/quota/model checks. `smoke` performs an explicitly
nonmarketable paper submission/cancellation check; a separate market-open round-trip
must pass before equity pilots can submit normal entries.

## Configuration and private state

Local `.env` supplies `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `NTFY_TOPIC`,
`TRADER_START_DATE`, and `TRADER_EXECUTION`. See `.env.example`. The broker endpoint
is fixed to Alpaca paper; there is no live toggle. Operational state, raw research
integration artifacts, logs, and archives are ignored under `.runtime/`.

SQLite records plans, fills, branch cash, holdings, equity, jobs, experiments,
usage and memory. Git is not an order queue. Only the allowlisted export
`docs/data/lab.json` and frontend assets are published. Old artifacts are archived
locally and remain recoverable from Git history.

## Research and experimentation

Morning research covers rates/bonds, Fed and macro events, earnings/company events,
market conditions, cross-market developments, and influential narratives. Source
and observation times, uncertainty and contradictions travel with decisions.

Strategies have immutable versions. New hypotheses run as paired forward shadow
experiments against an incumbent. Supported filters require at least 20 sessions,
30 observations and conservative evaluation gates before staged promotion; these
minimums do not establish certainty. Arbitrary ideas remain proposed until there
is executable, tested evaluation support. Daily reflection can choose no change.

Autonomous code maintenance creates an isolated worktree, validates a pure strategy
extension, runs regression tests, commits a shadow candidate, and registers its
forward evaluation. It cannot alter the risk kernel, credentials, tests, or its
own promotion gates. A validated code change does not immediately become active.

## Risk and resource policy

Maximum planned loss is $100 per trade, daily branch entry halt is $200 loss,
and branch drawdown pause is 10%. Initial pilots use a tighter $50 risk budget and
$2,000 position-notional cap and five symbols per branch. Actual losses can exceed planned stops. Submitted
orders are never counted as filled holdings. Unknown positions/orders/cash mismatches
halt new entries. Symbol ownership is exclusive across branches initially.

The project may use up to 80% of weekly account allowance, with 20% reserved.
Account-wide quota and project task tokens are displayed separately. Calls have
runtime/search/cycle/output ceilings; routine numerical checks need no model.
No automatic purchases, paid fallbacks, or reset-credit consumption occur.

## Development

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src/agent_trader/runtime src/agent_trader/strategies
```

Actions runs tests and deploys Pages only. Legacy cloud trading/reminder/reset
workflows are retained outside the active workflows directory. The older Python
agents remain for reference and regression coverage; the CLI uses only the v2 runtime.

Position reviews are batched hourly. Four daily model-call slots and a portion of
the paced daily quota are reserved for after-close review/maintenance. Calendar
checks include broker-session confirmation and clock drift; CLI outages cannot
stop Python reconciliation and closing. Promoted filters have a fixed 2%
post-promotion equity-loss rollback condition.

Initial exploration now includes a ten-morning research sprint, twelve frozen
historical screens and up to six parallel shadow challengers per equity branch.
Independently reviewed research cards feed the morning brief; historical results
and source review remain distinct from forward-validated evidence. See
[RESEARCH_WORKFLOW.md](RESEARCH_WORKFLOW.md).

The October 29 runtime interruption exposed a console-lifetime/recovery gap. The
active owner is now `agent-trader.service` with automatic restarts, a hidden WSL
keepalive host and a separate Windows heartbeat watchdog. The old visible-console
task is disabled. See SYSTEM_GUIDE.md for hidden installation and recovery commands.

## Project account and research acceleration

The [Project & progress dashboard](https://aashay-chaudhari.github.io/trader/#project)
explains the repo, architecture, decisions, schedule, public resources, evidence
milestones and next questions. Its assessment is computed from recorded evidence;
it does not express subjective feelings or assign a probability of profitability.
October 29 was operationally missed, despite successful recovery drills afterwards.

A separate deterministic lab preregisters twelve fixed signal/horizon protocols
across thirty liquid symbols. It records observed quote opportunities even when
there are no model trade plans. Missing entry/exit data remains not evaluable;
results are holding-horizon unit returns, not portfolio profits or guaranteed fills.
The first study fixes twenty entry sessions from October 30 through November 27,
with final swing maturation through December 3. Provisional observations stay visible.
This lab cannot submit orders or promote a strategy automatically.

Official BEA calendar intake, explicit BLS fetch failures, complete review packets
and bounded role-specific model contexts improve the daily handoff. Read the
[primary-source review and limitations](PUBLIC_RESEARCH_NOTES.md) and
[research workflow](RESEARCH_WORKFLOW.md). All existing paper/free-only risk and
quota limits remain enforced.

The daily [research-quality audit](RESEARCH_QUALITY_AUDIT.md) now tracks missing
inputs, source-check attestations, full artifact coverage and redundant work. Its
findings feed retrospectives and a durable development backlog. Research uses free
completed-minute IEX features when available; offline checks are never backfilled
as forward evidence. The dashboard shows the audit and explicit source-review status.
