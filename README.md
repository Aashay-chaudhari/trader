# Trader — the autonomous paper-trading laboratory

Trader runs locally on this Windows PC through WSL Ubuntu. A scheduled supervisor
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

The Windows scheduled task `AgentTrader-LocalSupervisor` starts at 07:40 local
Windows time and at sign-in. The runtime schedules trading in `America/New_York`,
using Alpaca's calendar for holidays and early closes. Windows must remain powered,
networked, and signed in; locking the desktop is fine. After reboot, sign in once
so the user-owned WSL distribution and CLI authentication become available.

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

`run` holds a single-instance lock. The scheduler is the normal execution owner.
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
