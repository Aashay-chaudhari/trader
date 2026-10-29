# Agent Trader — Final Refactor Scope

Status: implemented; local runtime and Pages verified. Market-open fill/exit gate pending.
Recorded: October 29, 2026, approximately 00:17 America/New_York.
Target first operating session: Thursday, October 29, 2026 (explicit user trading-day target).

This document is the persistent implementation brief for the refactor. Read it
after a restart or context compaction. It describes intended behavior, not
features already implemented. Later explicit user decisions supersede it.
Existing documentation describes the legacy application and must be updated as
the implementation changes; do not mistake legacy defaults for this design.

## 1. Vision and success criteria

Build an autonomous local paper-trading research application that discovers,
tests, executes, evaluates, and improves strategies while explaining its work
to a human. The agent may evolve its prompts, roles, strategies, and code.
Changes must be controlled experiments with visible evidence and release history.

The primary objective is sustained portfolio performance; the secondary objective
is learning which decisions, strategies, and system components contribute to it.
Overall end-of-day return is the headline measure. Branch attribution, comparable
baselines, exposure, drawdown, execution quality, and uncertainty qualify it.
Profit alone is not evidence of an edge. No target return is promised.

Reuse useful execution concepts, tests, prompts, memory, dashboard infrastructure,
and GitHub Pages. Replace legacy orchestration where it conflicts with this scope.

## 2. Non-negotiable constraints

- Paper trading only. Live credentials/endpoints and live-order submission are
  outside this release. Future live validation requires separate authorization.
- Run on this Windows PC, using its local CLI access; no paid hosted runtime.
- Free data and services only. No purchases, metered API fallback, paid feeds,
  paid SMS, or automatic credit/reset consumption.
- Existing CLI subscription capacity may be used. This project has priority and
  may consume up to 80% of the weekly allowance; reserve 20% for other work.
- Never publish credentials, notification topic secrets, private raw session
  transcripts, or local authentication material to Git or GitHub Pages.
- Research content is evidence, not executable instructions. Web pages cannot
  authorize trades, code changes, credential access, or policy changes.
- The agent can choose not to trade. There is no daily trade quota.
- Tests, data quality, or risk failures must never silently turn into approval.

## 3. Capital, branches, and broker state

| Branch | Initial allocation | Initial behavior |
| --- | ---: | --- |
| Intraday US equities/ETFs | $10,000 | Long-only paper pilots; close within that trading day |
| Swing US equities/ETFs | $10,000 | Long-only paper pilots; overnight holding permitted |
| Options | $10,000 | Research/shadow initially; paper activation requires explicit capability and data-quality gates |

Total intended initial capital: $30,000. Each branch keeps its allocation and
profits/losses; no automatic inter-branch transfers initially. Idle cash is valid.

One broker account may support three internal ledgers; these are not separate
broker-enforced balances. Reconcile the aggregate to Alpaca and attribute every
order, fill, fee, position, and realized/unrealized result to its branch and
strategy version. Prevent conflicting intents and accidental closure of another
branch's holdings. If overlap cannot be reconciled safely, block the new intent.

Broker-confirmed fills, positions, cash, and equity are authoritative. Submission
is not a fill. Handle partial fills, rejections, cancel/replace, duplicate retries,
corporate actions, and unexpected external positions explicitly.

The replacement paper account was verified read-only on October 29: ACTIVE,
account ending BKM5, $30,000 cash/equity, no positions or open orders, no reported
trading/account blocks, and options trading level 3. Broker buying power is
$120,000; the application must still enforce its $30,000 no-borrowing policy.
Credentials pasted into chat should be
rotated before deployment and the replacement stored locally, never in this file.
No old profile ledger may be imported as the new account's current positions.

Options: purchased calls/puts and defined-risk spreads only initially. Verify
contract multiplier, permissions, quotes, liquidity, expiration, exercise and
assignment handling. No naked short options. Default to avoiding expiry holds.
The previously tested account allowed level 3 options and free indicative data;
OPRA access returned 403. Recheck the replacement account. Indicative observations
are not firm executable quotes. Missing trustworthy data means abstain or mark
the result not evaluable, not fabricate fills or performance.

## 4. Initial risk envelope

- Maximum planned loss per trade: $100 per branch, including modeled costs.
- Daily loss threshold per branch: $200, measured from start-of-day branch equity
  including realized and unrealized P&L, adjusted for explicit transfers if any.
  Cancel pending entry orders and block new entries when breached; manage exits.
- At 10% drawdown from the branch equity high-water mark, pause new entries and
  route the branch to review/shadow. Resume only under recorded recovery criteria.
- No borrowing initially. Option premium/collateral and aggregate exposure must
  remain within allocated unencumbered capital.
- Python enforces sizing, available cash/collateral, liquidity, price freshness,
  aggregate exposure, and duplicate-order checks independently of model outputs.
- The agent may tighten limits and adjust sizing within ceilings. It cannot
  raise ceilings, change paper-only policy, or weaken evaluation gates on its own.
- Intraday entries have a cutoff; the closing routine starts before actual market
  close, retries and verifies outcomes, and alerts on unresolved exposure.
- Swing positions require documented invalidation/exit plans and broker-held
  protective orders where supported. Protection is not guaranteed execution.
- Planned loss and daily limits are decision thresholds, not guarantees against
  gaps, illiquidity, outages, or larger realized losses.

Risk numbers are conservative experiment defaults, not optimized conclusions.
Freeze and version the initial policy before submitting orders.

## 5. Architecture and responsibility boundaries

1. Windows Task Scheduler starts/restarts a local supervisor without requiring
   the editor, repo UI, or an interactive terminal to be open.
2. The supervisor owns the market calendar, work queue, persistent state,
   instance lock, retries, bounded backoff, heartbeat, and recovery.
3. A persistent daily Codex thread maintains continuity. Models/effort may change
   between turns. Focused tasks receive compact evidence rather than all history.
4. Agent roles research, propose hypotheses, evaluate candidates, and review
   outcomes. Add roles only with a stated benefit and evaluation plan.
5. Python retrieves structured data, validates plans, monitors triggers, enforces
   limits, submits paper orders, reconciles fills, and handles closing fallbacks.
6. Transactional local storage records events and current state. Prefer SQLite
   for operational durability, with versioned JSON/Markdown exports for inspection.
7. Sanitized static exports feed GitHub Pages. Git is not the execution queue or
   sole operational database. Publication failure must not block protective exits.
8. GitHub Actions remains for tests and Pages deployment. Disable old trading and
   reminder schedules before new execution ownership becomes active.

One logical control point does not require one immortal process. Recovery must
work after a restart, context compaction, authentication failure, or network loss.
Use stored thread IDs, never an ambiguous resume-most-recent-session command.
Use bounded queues and prevent overlapping decisions for the same allocation.

## 6. Structured research with adaptive exploration

Every morning produce a concise market brief covering:

| Area | Required coverage |
| --- | --- |
| Rates and bonds | Treasury yields/curve, real yields and available credit spreads; observation age |
| Fed and macro | FOMC decisions/minutes, relevant speeches, inflation, employment, and other material releases |
| Company events | Earnings date/time, guidance, filings, investor events, dividends/splits |
| Market conditions | Index trends, volatility, breadth, sector leadership, liquidity |
| Cross-market | Dollar, oil/commodities, overseas and geopolitical developments relevant to exposures |
| Narratives/influence | Analyst/company commentary and prominent stories; verify underlying claims |

Use live agent web search for discovery and interpretation. Prefer primary
sources: official agencies, central banks, SEC filings, and company IR pages.
Structured free feeds remain the source for numerical execution inputs.
Do not equate generic web search with a guaranteed Google-specific backend.

Record publication/event time, first observed/retrieved time, source, relevance,
freshness, uncertainty, affected symbols/positions, and any conflicting evidence.
Daily/delayed series cannot masquerade as real-time market observations. Unknown
earnings times and unavailable consensus estimates must stay unknown.

Research starts with a liquid universe plus catalyst-driven discovery. Refresh
around scheduled events, material price changes, new evidence, and expiring
theses. Deduplicate syndicated headlines. Every significant item should explain
which decision it changes or why no change is warranted.

Before entry, check company/macro events and evidence age. Calendar restrictions
and rates filters are testable hypotheses, not universally valid trading rules.

## 7. Executable plans and memory

Every plan records branch, strategy/version, symbol/contract, thesis, sources,
entry trigger, expiry, invalidation, sizing, exit rules, maximum planned loss,
expected holding window, and data requirements. Revalidate immediately before
submission; an agent decision may be stale by the time it arrives.

Memory has three layers:
- Expiring observations: quotes, headlines, event times, and current market facts.
- Active theses: positions/candidates, assumptions, invalidation and review dates.
- Tested lessons: claims linked to experiments, supporting/contradicting evidence,
  applicability conditions, and retirement criteria.

Reflection can propose a lesson but cannot certify it. Preserve original evidence
when summaries change. Provide concise decision rationales, not hidden reasoning
traces or unfiltered internal transcripts.

## 8. Challenger experiments and promotion

Maintain an incumbent and up to six simultaneous shadow challengers per equity
branch. The first ten research mornings emphasize broad investigation, independent
source/method review, fixed historical screens and diversified forward hypotheses.
Historical screening never replaces forward evidence for promotion.

Each experiment records its hypothesis, parent version, exact change, rationale,
eligible universe, metrics, execution assumptions, evaluation period, minimum
evidence, and promotion/retirement conditions before observing outcomes.
Keep failed and abandoned attempts. Material edits create new versions.

Compare incumbent/challenger on the same eligible forward observations. Shadow
performance uses explicit fill/cost assumptions; it is not broker execution.
Count missed opportunities and abstentions without assuming a trade would fill.
Account for shared market exposure, clustered trades, uncertainty, and repeated
testing. Do not promote from a single winning day or an arbitrary Sharpe threshold.

Freeze historical evaluation windows and prevent future evidence leakage.
Historical LLM research may reflect model training knowledge; distinguish it
from recorded forward tests. Prefer forward evidence for promotion decisions.
Promotion may be autonomous only when recorded criteria pass, with staged paper
allocation and rollback conditions. Lack of evidence means continue shadowing.

Initial equity pilots are explicitly unproven operational experiments, not
strategies claimed to have passed forward promotion gates. Options are conditional.

Test the research machinery too: extra searches, review roles, event filters,
memory policies, and model routing must justify their complexity and usage.

## 9. Daily controlled self-improvement

After reconciliation, review decisions, failures, non-trades, costs, data issues,
quota use, and experiment results. Daily review does not require daily changes.

For each proposed change, record problem, hypothesis, expected benefit, competing
explanations, affected behavior, tests/evaluation, deployment time, and rollback.
Use an isolated branch/worktree. Run meaningful unit/integration/regression tests,
replay known incidents, and validate storage/schema compatibility.

Behavioral changes normally activate next session. Existing positions retain
their strategy version unless an explicit risk action overrides it. Operational
repairs can ship sooner with validation. Failed validation leaves the prior
release active. Preserve immutable policy and evaluation checks outside routine
strategy mutation paths; audit every maintenance release.

## 10. Models and account-aware usage budgets

| Task | Default allocation |
| --- | --- |
| Quotes, risk math, broker reconciliation, closing, scheduling | Python; zero model calls |
| Deduplication/classification and concise change summaries | Lightweight model, low effort |
| Established trade-plan judgment | Workhorse model, medium effort |
| Research, hypotheses, ambiguity, selective skeptical review | Strong model, higher effort |
| Retrospective and justified code updates | Strong reasoning/coding model |

Discover models available through existing CLI authentication and validate access.
Use configurable roles, not permanent assumptions about particular model names.
No paid API fallback. Check limits using the authenticated local CLI/app-server.

The account endpoint exposes quota-window usage, not a guaranteed fixed token
pool or perfect project attribution. Track project token/event usage separately;
record start/end quota observations and conservatively handle concurrent activity.
Never describe account-wide changes as exact project-only consumption.

Plan across remaining trading days and the actual reset timestamp. Enforce both
the project's 80% weekly share and the need to preserve remaining account capacity.
Initial allocation of the project budget: 30% research, 30% trading decisions,
20% retrospective/maintenance, 20% contingency. Adapt to measured consumption.
Implementation consumes the same weekly allowance and must be accounted for.

Bound searches, context, tool cycles, runtime, retries, and task concurrency.
A prompt asking the model to stop is not a hard budget enforcement mechanism.
Prefer event-triggered calls; do not repeatedly reason about unchanged snapshots.
Defer maintenance/new research before open-position decisions. On quota failure,
block new discretionary entries and keep deterministic exits/reconciliation alive.

## 11. Dashboard and notifications

GitHub Pages is a read-only monitoring/learning surface, not an authenticated
broker control panel. Display last successful update and distinguish stale data.

Primary view: aggregate equity, daily return, branch allocations/results, exposure,
positions, operating mode, heartbeat, blockers, and next scheduled work.
Supporting views:
- Why each trade/non-trade occurred, source links, invalidation and next review.
- Market brief and upcoming events with affected positions.
- Incumbent/challenger results, experiments, promotions, retirements, and changes.
- Passive/fixed-rule baselines, costs, drawdowns, observation counts, uncertainty.
- Broker paper versus shadow versus conservative cost-adjusted estimates.
- Weekly allowance/reset, project usage estimates, model/role usage, budget skips.
- Releases, test results, incidents, rollback history, and daily lessons.

Reuse the user-confirmed ntfy destination, stored in local configuration rather
than public source. A dummy notification was delivered and confirmed on phone.
Send startup failures, execution/risk incidents, unresolved closing exposure,
budget warnings, significant strategy changes, and daily results with a dashboard
link. Deduplicate/retry with limits; avoid flooding and confidential account data.
Remove paid Twilio fallback from the active path.

## 12. Schedule and October 29 launch

All scheduling uses America/New_York and the broker market calendar, including
holidays and early closes. October 29 is in EDT (UTC-4), not EST.

| Target | Activity |
| --- | --- |
| 08:00 ET | Startup/recovery and broker/data/quota/calendar checks |
| 08:15–09:20 ET | Research, hypotheses, plans, readiness decision |
| During market session | Python monitoring plus event-triggered and bounded periodic agent review |
| Before actual close | Entry cutoff, intraday exits, fill/order verification |
| After close | Reconcile, publish, notify |
| Evening | Retrospective, experiments, validated next-session release |

The explicit user trading-day target is October 29. Overnight references to tomorrow
are interpreted as the upcoming morning; this avoids silently missing that session.
Prioritize an operationally correct core over additional strategies or elaborate analysis.
If launched late, run fresh readiness checks and skip stale phases/plans.

## 13. Implementation order and launch gates

- [x] Snapshot legacy state; inspect clean/dirty worktree and preserve user work.
- [x] Verify replacement paper account, intended balance, permissions and holdings.
  Read-only account check passed October 29; refresh state again at activation.
- [x] Implement transactional state, branch ledgers, policy and execution engine.
- [x] Implement broker reconciliation, idempotency, closing and recovery paths.
- [x] Implement supervisor, scheduler, CLI model routing and quota controller.
- [x] Implement evidence/event calendar, research roles, memory and plan schemas.
- [x] Implement pilots, challenger registry, evaluation and maintenance releases.
- [x] Build sanitized dashboard exports, Pages publication and ntfy notifications.
- [x] Run relevant tests, failure simulations, and controlled paper-order smoke test.
- [x] Disable legacy execution/reminder owners and install/test local scheduled task.
- [x] Verify first scheduled startup outside an interactive shell; record launch mode.
- [x] Update README, CURRENT_STATE, operator/recovery guides and implementation log.

Required tests cover duplicate/retried submission, restart recovery, partial fills,
cancel/replace, branch overlap, stale/missing data, invalid model output, risk
limits, quote-age revalidation, quota/auth failure, early close, failed publication,
credential redaction, and failed maintenance release rollback.

A controlled paper-order smoke test is in the approved scope. Avoid accidental
overnight pending orders; reconcile any fills and cleanup outcomes. If market
conditions prevent a meaningful fill test, state exactly what was/wasn't tested.

Launch modes:
- PAPER PILOT: all required execution/account gates pass; unproven equity pilots
  may operate under risk limits. Options evaluated separately.
- RESEARCH/SHADOW: supervisor, research and reporting operate, but a failed or
  incomplete broker/data/execution gate blocks entries and is prominently shown.
- HALTED: state integrity or existing-position handling cannot be trusted; alert
  and execute only validated protective/reconciliation procedures.

Being operational on day one is not equivalent to having demonstrated an edge.

## 14. Deferred scope

No live trading, paid feeds, cloud migration, high-frequency execution, naked
options, reinforcement-learning training, mass parameter search, complex agent
debates, automatic capital transfers, or authenticated remote dashboard controls.
Advanced statistical attribution can follow once sufficient observations exist.
Preserve the evidence needed to support later evaluations without pretending
small-sample results establish significance.

## 15. Research informing these choices

- Quant-Arena (October 2026): frozen out-of-sample evaluation and baseline comparison.
  https://arxiv.org/abs/2610.30113
- Agents Are Not Algorithms (May 2026): reasoning latency and deterministic execution.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6713620
- KTD-Fin (May 2026): historical-memory leakage and return attribution.
  https://arxiv.org/abs/2605.28359
- FinMem: layered memory as architectural inspiration, not proof of our edge.
  https://arxiv.org/abs/2311.13743
- TradingAgents: specialized analysis/review and task-dependent model effort.
  https://tauric.ai/research/tradingagents
- Probability of Backtest Overfitting: preserve trials and control selection bias.
  https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- Alpaca paper limitations and options capabilities:
  https://docs.alpaca.markets/us/docs/paper-trading
  https://docs.alpaca.markets/us/docs/options-trading
  https://docs.alpaca.markets/us/docs/historical-option-data
- Codex app-server model/turn controls and usage endpoints:
  https://learn.chatgpt.com/docs/app-server

## 16. Continuation protocol

Maintain a separate implementation log with completed work, commands/check results,
active branch/release, blockers, next action, and launch evidence. Update it at
meaningful checkpoints. Read this scope and that log before resuming work.
Never infer successful deployment, account funding, scheduled execution, or
notification delivery solely from code being present. Record observed results.

## Implementation boundary notes

The initial autonomous code-mutation path is a validated pure strategy filter,
committed on an isolated branch and evaluated in shadow before activation. Broader
role/orchestration changes remain recorded proposals until executable validation
support is added. Options have a research/data desk and reserved allocation; no
options execution is enabled with the indicative feed. Submission/cancellation
was verified without fills; the regular-session fill/exit gate is scheduled.


## Research sprint and reusable knowledge — October 29 update

The first ten research mornings add a strong-model discovery pass (up to twelve
searches) and a separate strong-model source/method review (up to four searches).
The daily call ceiling, weekly reserve, broker policies and closing routines remain
fixed. Exploration runs before 09:15; held-position review takes priority in-session.

Twelve fixed daily-bar rule/horizon combinations across the liquid universe are
screened with a chronological development/holdout split, boundary-label purge, and
20bp/50bp assumed cost checks. Freeze the dataset and report every trial, including
losers. Adjusted IEX bars, survivor bias, missing intraday execution detail and
unconstrained unit-opportunity accounting remain explicit limitations. These
results cannot authorize trades or satisfy forward promotion requirements.

Research moves from draft to independent review to persistent knowledge cards.
Only reviewed cards enter the morning brief, alongside counterevidence and linked
experiment states. Cards expire after 30 days without re-review. Source/method
review means suitable for testing; forward validation refers to a linked supported
filter that passes the experiment gates, not a blanket certification of the claim.
Same-morning validated findings request a refreshed brief before the open.

Up to sixteen research shadow plans can broaden forward observations without
entering the executable plan table or allocating broker capital. At most six
challengers per equity branch share paired observations. Promotion additionally
requires positive net challenger performance, a penalty for the recorded trial
family and predeclared doubling-session review looks. Siblings with a superseded
parent become stale; arbitrary repeated daily significance checks are disabled.
Options remain research-only with no simulated executable fills from indicative data.
