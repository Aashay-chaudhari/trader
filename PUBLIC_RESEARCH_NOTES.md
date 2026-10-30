# Public research and architecture review — October 29, 2026

This review improves research quality and observability. It does not establish a
trading edge, train model weights, purchase data or authorize live trading.

## What the primary research suggests

[AI-Trader](https://arxiv.org/abs/2512.10971) evaluates autonomous agents in live
markets and reports that general benchmark capability does not reliably become
trading performance. [Agent Market Arena](https://arxiv.org/abs/2510.11695) emphasizes
continuous, verified evaluation and finds material differences between agent
frameworks. These are research results in particular settings, not evidence that
our selected model or strategy will be profitable. Borrow the evaluation discipline,
not an advertised return.

[Bailey et al.](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) explain how
searching many backtests can select noise. Report the trial family and failed ideas,
preregister methods/windows, cluster observations, and require forward evidence.
Our conservative filter-promotion checks are not a formal guarantee of error
control in dependent, changing market data. The signal lab cannot auto-promote.

The [New York Fed reversal study](https://www.newyorkfed.org/research/staff_reports/sr513.html)
is mechanism-level motivation; a raw three-session decline is not its isolated
nonfundamental component. A continuation rule is a descriptive negative comparator,
not a causal negative control. Source review cannot make either profitable.

## Use public resources precisely

- [BEA](https://www.bea.gov/news/schedule/icalendar) supplies public ICS/JSON release
  calendars. Its ICS endpoint was fetched successfully and dated events parsed.
- [BLS](https://www.bls.gov/schedule/news_release/) supplies an official calendar,
  but direct requests from this PC return 403. Keep that failure explicit and use
  primary-page verification through ordinary agent web search; no paid proxy.
- [Federal Reserve](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
  remains the reference for policy dates and releases. BLS/BEA do not cover it.
- [SEC developer resources](https://www.sec.gov/about/developer-resources) offer
  public submissions/XBRL data under fair-access and declared-user-agent rules.
  The direct connector is deferred; primary filings remain available to research.
  Do not equate filings with a reliable future earnings/surprise calendar.
- FRED daily CSV observations are dated, delayed and revision-prone. ALFRED/vintage
  methods are necessary before claiming a point-in-time macro backtest. Current
  public CSV values are not silently substituted into historical decisions.
- Free Alpaca IEX is one exchange. Options indicative observations cannot satisfy
  the execution-quality gate. Missing trustworthy data is a research constraint.

## Changes selected from the audit

1. **Independent forward collection:** twelve fixed signal/horizon cohorts can
   observe the liquid universe even when the model produces no executable plan.
   This addresses evidence starvation without forcing broker orders.
2. **One observation contract:** numerical quote gates, extra assumed cost formula,
   actual trading-session horizons, missing-data denominator and fixed reporting
   window live in code and are supplied unchanged to review and the frontend.
3. **Metric units:** derived historical packets say holding-horizon unit-opportunity
   returns. Preserve the raw frozen dataset/hash and original holdout. Never call
   five-session returns daily portfolio returns or correlated samples independent.
4. **Whole-session instrumentation:** broker-confirmed five-minute coverage records
   are separate from last-heartbeat, restart drills, model research and paper fills.
5. **Bounded role context:** preserve durable knowledge in SQLite, separate roles,
   give reviewers fresh context and rotate long/reused threads. The measured effect
   on token efficiency and decision quality still needs matched forward evidence.
6. **Complete evidence packets:** curate bounded objects and report selection/counts;
   never cut a retrospective in the middle of JSON. A previous review explicitly
   identified incomplete experiment context.
7. **Graceful budget pressure:** official [Codex app-server docs](https://learn.chatgpt.com/docs/app-server)
   support mid-turn steering. A soft budget notice asks for a final bounded answer
   before the existing hard limit; it cannot increase tool or account limits.
8. **Candid project account:** the new Project & progress page explains ownership,
   automations, decisions, resources, current evidence and next experiments. It
   displays no feelings or invented probability of profitability.

An independent design review held two initial definitions for missing numerical
and reporting detail. That feedback informed the shared contract. Its follow-up
review is recorded separately from implementation tests and forward evidence.

## Observed implementation and review receipts

The first independent review held both definitions for insufficient numeric
specification. A fresh follow-up reviewer received the exact shared protocol,
registered reporting window and actual free-data access constraints; it accepted
both as descriptive methods for testing. Six catalogue cards are now source/method
reviewed in total. Neither this review nor the historical screen validates returns.
The original rejection and revised review remain in private audit artifacts.

The first study fixes twenty broker-calendar entry dates from October 30 through
November 27, with final swing maturation through December 3. Thirty symbols and
twelve rule/horizon combinations yield 360 planned opportunities on day one, with
zero actual observations at deployment. Frozen inputs were amended before any
observation to retain the exact normalized artifact and a canonical hash; the
original snapshot/hash is archived explicitly. There is no historical quote backfill.

Quote validation requires ordered finite bid/ask, a $5 minimum bid, age −5 to 90
seconds, and at most 0.5% spread fractions. Net unit return is exit bid / entry ask
minus one, minus 0.2%, minus entry spread/ask and exit spread/ask. The additional
spread terms are conservative assumptions beyond the ask/bid crossing. Stress
subtracts another 0.3%. Missing quotes/discontinuities remain not evaluable; the
public denominator includes all preregistered opportunities and separate exclusions.

Real app-server checks acknowledged soft budget steering and returned valid bounded
JSON while explicitly retaining unavailable source details. That verifies harness
behavior, not research quality or measured token-efficiency gains. Full regression
and browser results are recorded in READINESS.md. All data and inference stay within
the existing free/subscription experiment; account/risk limits were not raised.
