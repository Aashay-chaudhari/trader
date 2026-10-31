# Adaptive return-engine audit — October 31, 2026

The objective is a repeatable paper portfolio return that survives explicit cost
stress and controlled drawdown, with evidence sufficient to assess later real-world
transfer. Research volume, eloquent explanations, source counts, and idle cash are
not evidence of a trading edge. This audit and implementation preserve the original
capital, ledger, fixed forward study, free-resource policy and Git history.

## What the audit found

The unattended execution/recovery infrastructure was stronger than the learning
process. At audit start the account was $30,000 with zero fills, eight plan-filter
challengers had no samples, and all four reviewed catalogue cards lacked an
implemented experiment link. One complete market session cannot establish an edge.

Discovery received a large historical screen but little structured current evidence,
ran only during the first ten mornings, and required external literature even for a
new empirical conjecture. No model trade plans meant no filter-test observations.
The daily developer backlog recorded proposals and deployed fixes without later
mechanical-effect assessments. Review context could exceed its input budget and be
cut inside JSON. An already-completed fresh-open job could suppress a requested
research refresh. Shadow-plan admission used branch-wide acceptance rather than
linkage to the exact reviewed hypothesis.

## Agreement and challenges to the vision

- Observation-led adaptation is aligned. Discarding historical base rates is not.
  Current anomalies are hypotheses, not causal explanations. Recent outcomes can
  be overfit just as easily as historical data. Register the question, alternatives,
  threshold, universe, horizon, costs and failure condition before future outcomes.
- Treating this as the main project means measuring economic outcomes and rejecting
  weak ideas. It does not mean spending all tokens, forcing daily trades or making
  the system more complex whenever it abstains. Tokens cannot create independent
  market sessions or executable liquidity.
- Greater autonomy is useful for observation capture, research design and bounded
  parallel tests. It must not let the same researcher rewrite its old results,
  evaluator, risk policy or account balances to manufacture success. Independent
  review and immutable test versions strengthen the intended autonomy.
- Paper success would justify further execution validation, not a credential-only
  switch to live trading. Alpaca explicitly omits market impact, latency slippage,
  queue position, fees and dividends from its simulation, and paper order size is
  not constrained by displayed liquidity.

Sources informing these choices:
[Alpaca paper-trading specification](https://docs.alpaca.markets/us/docs/paper-trading),
[Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
The latter explains why many tests on finite data increase false discoveries; it
is not evidence that this application or any selected strategy is profitable.

## Implemented learning cycle

1. Capture bounded, immutable observations from current free IEX quotes, completed
   bars, relative moves, delayed macro changes and data gaps. Preserve capture time,
   original event dates, exact values, provenance and competing explanations.
   Existing session quotes supply a fifteen-minute monitor without another data fee.
2. Give current questions, catalogue claims and prospective outcomes priority in
   discovery. Historical summaries are secondary and cannot displace the duplicate
   check. Continue after ten mornings when observations change or cards expire,
   with Monday review as a fallback, under the existing account budget.
3. Independently review local conjectures using their actual archived IDs and dates.
   External factual claims still require primary-source checks. Local empirical
   ideas do not need a paper asserting the mechanism. Review means suitable to
   investigate; it never means the mechanism is causal or profitable.
4. Register separate declarative observation contracts: up to three numeric
   conditions, six symbols per contract, six active contracts per branch. Supported
   fields are completed one/three/five-session returns, prior close versus SMA20,
   current ask change from prior close, and that change relative to SPY. Ratios are
   decimals. Event/earnings/macro mechanisms outside these fields remain research
   questions or development proposals rather than pretended executable tests.
5. Freeze each contract and its future actual-session window. At least twenty entry
   dates and thirty closed active signals are assessment floors. Same-day motivating
   data cannot validate the idea. First eligible ask is fifteen to thirty minutes
   after open; exits use the first valid bid during the twelve minutes before the
   actual close of holding session one or five. Missing windows are not backfilled.
6. Compare cash and the same-symbol always-long observation, with 20bp base/50bp
   stressed additional round-trip costs. False conditions count as cash abstentions;
   unknown inputs remain missing. Keep all denominators, variants and hashes.
   Results are dependent holding-horizon research units, not portfolio profits.
7. Hand reviewed hypotheses and their actual test progress/results to morning
   research and retrospectives. New observation contracts have no broker or automatic
   promotion authority. Existing plan/risk/decision gates govern paper pilots.
8. Evaluate deployed input/source/artifact mechanics only on later completed sessions.
   Preserve development baselines and explicit awaiting/observed/attention states.
   Qualitative pulse usefulness remains a review question; no-change is not failure.
9. Show reconciled account returns, an explicit friction stress, prospective verified
   drawdown, execution readiness, research bottlenecks, observations and studies in
   the frontend. Proposed lessons are deduplicated and remain untested until supported.

## Boundaries and practical limitations

The old twelve-rule study stays frozen. New studies do not inherit its results.
Twenty dates are a minimum design, not proof of independence or sufficient power;
correlated symbols and overlapping swing horizons remain explicit. Threshold and
universe selection itself can overfit, and selected anomaly leads are not neutral
samples. A completed test may be inconclusive or reject the idea.

This remains a local PC service with hidden Windows host/watchdog, GitHub Actions
for CI and static Pages deployment, and ntfy notifications. Broad nightly runtime
rewrites are not implemented: automated code maintenance still stages pure entry
filters in isolation; application changes use the reviewed development/release path.
No paid provider, live endpoint, capital transfer or increased financial risk was
introduced. The paper entry/exit verification gate remains separate from code tests.

## Validation and live integration

New regression coverage checks future-only windows, immutable versions, duplicate
trials, missing versus false signals, timestamps, archived input identity, source and
method review, old evidence retrieval, independent shadow linkage, scheduler
fallthrough and output-schema compatibility.

An actual discovery call exposed an optional-field schema rejection. The harness
now makes all transport fields explicit recursively while retaining Pydantic defaults
for old persisted records. This follows the [Structured Outputs requirements](https://developers.openai.com/api/docs/guides/structured-outputs).
A subsequent actual run completed but proposed no hypotheses because historical
context had displaced the duplicate catalogue. Prompt priority was corrected rather
than treating that abstention as a successful learning outcome. Original attempts
and outputs remain recorded. Final run/test/deployment receipts are appended in
IMPLEMENTATION_LOG.md; market-session outcomes remain unobserved at this release.
