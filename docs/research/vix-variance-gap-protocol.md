# Proposed VIX–SPX daily-close variance-gap diagnostic

Status: **proposal for independent review; not registered, scheduled, or activated**.
Prepared November 7, 2026. This document grants no operational authority and does
not amend a research card, frozen study, risk gate, or execution policy.

## Question and scope

Can the existing free-data boundary support an auditable, prospective collection
of date-matched VIX implied variance and subsequent SPX daily-close variation over
fixed 30-calendar-day windows? The first proposed cohort measures data coverage and
describes the resulting variance gaps, with scheduled-FOMC labels as context.

The original stricter question—whether exactly synchronized, horizon-matched
implied variance contains an event premium—remains unresolved. A positive gap in
this diagnostic is neither a demonstrated event premium nor option profit. There
is no directional return hypothesis, portfolio simulation, executable option
position, promotion criterion, or automatic continuation in this proposal.

## What the sources establish

- [Cboe's VIX methodology](https://cdn.cboe.com/resources/vix/VIX_Methodology.pdf)
  describes a 30-day SPX option-implied volatility index, quoted as volatility
  multiplied by 100. Its calculation/dissemination section lists regular-session
  dissemination through 16:15 ET; the document read for this proposal is version
  6.0, revised February 26, 2026.
- [Cboe's mathematics methodology](https://cdn.cboe.com/api/global/us_indices/governance/Cboe_Volatility_Index_Mathematics_Methodology.pdf)
  defines calendar time using minutes divided by 525,600 and interpolates term
  variances to a constant maturity. These conventions motivate the variance units
  below; they do not make our daily-close estimator an exact VIX replication.
- [Cboe's historical-data page](https://www.cboe.com/tradable-products/vix/vix-historical-data)
  links daily VIX history. The CSV inspected contains dates and OHLC values, not
  a calculation timestamp for each closing value.
- [FRED's SP500 notes](https://fred.stlouisfed.org/series/SP500) identify the series
  as the S&P 500 daily closing **price index**, excluding dividends, with ten years
  of daily history. The notes describe the usual equity close as 16:00 ET.
- [Federal Reserve research, section 2](https://www.federalreserve.gov/pubs/feds/2011/201145/index.html)
  distinguishes expected variance under risk-neutral and physical measures. Our
  comparison subtracts an observed realization proxy, so it also contains
  realization error. Daily sampling is coarser than the paper's intraday measure.

A November 7 read-only access check succeeded for the public Cboe CSV and FRED
SP500 CSV. Their bounded historical downloads had 298 common dated rows between
September 2, 2025 and November 5, 2026. This is an access/overlap receipt, not a
calibration result, a point-in-time archive, or proof of synchronized observations.
Historical values were not used here to tune a signal or estimate a premium.

## Timestamp limitation that must remain visible

A shared date does not establish a shared observation clock. VIX dissemination
continues after the usual SPX equity close, and the public daily CSV does not prove
that its CLOSE field is a 16:00 observation. Conversely, an index quote updated
after 16:00 can repeat or finalize the earlier closing index level. Neither clock
alignment nor its numerical effect may be assumed.

For every input retain the provider's as-of date, any documented calculation time,
first retrieval time, source URL, raw-response hash, and processing version. An
undocumented calculation timestamp remains unknown. Never stamp a value retrieved
later as if the system had observed it at the market close. The proposed outcome
must be labeled **date-matched daily-close diagnostic**, even if all other checks
pass. An exact forecast-calibration study requires separately verified synchronized
index observations and a new independently reviewed contract.

## Proposed frozen inputs and estimator

Use Cboe VIX CLOSE and FRED SP500 price-index closes only. SPY, an ETF adjusted
close, a total-return index, VIX futures, and VIX derivatives' settlement quotation
are not substitutes. No paid feed or modeled data fills a missing observation.

For a planned start date `s` and endpoint `e = s + 30 calendar days`, let
`P_0 = SP500_s`, followed by every required actual equity-session close through
`P_n = SP500_e`. Define:

```text
r_i = ln(P_i / P_(i-1)), for i = 1,...,n
Q_s = sum(r_i^2)
I_s = (VIX_s / 100)^2 * (30 / 365)
D_s = I_s - Q_s
D_annual_s = D_s * (365 / 30)
```

`I`, `Q`, and `D` are integrated decimal-return variance units over the named
30-day interval. `D_annual` is the equivalent annualized variance gap. For example,
VIX 20 first becomes `0.20`, then annual implied variance `0.04`.

This is a sum of squared successive log returns, **not** the square of the total
30-day return. Do not subtract the sample mean, divide by `n-1`, annualize a
variable trading-day count with an unexplained 252 convention, or subtract a
standard deviation from a variance. Weekend and holiday movement enters the next
actual close-to-close return. Do not manufacture zero-return observations for
nontrading dates. An interior early close remains an actual close, with its
calendar metadata retained.

Daily-close squared returns miss intraday reversals and do not recover continuous
quadratic variation exactly. `D_s` is not a variance-swap settlement, option mark,
return on capital, fee-adjusted payoff, or estimated ex-ante variance risk premium.

## Proposed calendar construction

Before any study registration, obtain and retain complete actual broker-calendar
response evidence covering the proposed registration date through all planned
endpoints. Retain request bounds, retrieval time, raw response, hash, and every
session's opening/closing times. Public holiday tables alone cannot certify this
operational calendar. No calendar confirmation is asserted by this document.

The proposed deterministic rule is:

1. Registration precedes the first selected session's open. Choose the earliest
   subsequent full session whose date plus 30 calendar days is also a full session.
   For this contract a full endpoint session opens at 09:30 and closes at 16:00 ET.
2. Require exactly 720 elapsed hours between the two 16:00 ET endpoints. This
   excludes intervals crossing a daylight-saving offset change in advance; do
   not silently change the denominator to 29 or 31 days.
3. For the next block choose the earliest eligible start date on or after the
   prior endpoint, using the same rules, until exactly twelve windows are listed.
   A shared endpoint price is allowed; no close-to-close return interval overlaps.
4. Freeze all twelve windows and required interior sessions before observing their
   outcomes. Missing data never causes a window to move, be replaced, or be added.
   An extraordinary session cancellation or changed endpoint close is a recorded
   calendar incompatibility, not permission to improvise a new endpoint.

Nonoverlap reduces mechanical reuse of returns. It does not make adjacent windows
independent: persistent volatility and other common conditions can still link them.

## Event-label definition and feasibility

For each block, freeze a readable [official FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
observed no later than that block's start close and no more than seven calendar
days earlier. Define `E_s = 1` if a **scheduled FOMC meeting-end date** lies in
`(s, e]`, otherwise `E_s = 0`. Missing or insufficiently current primary calendar
evidence gives an unknown label; it is not assigned to the zero group.

This is deliberately a date-level scheduled-meeting label. Exact policy-release
time, surprise magnitude, unscheduled actions, and causal exposure are different
variables. Retain the calendar vintage and tentative/confirmed status. Subsequent
rescheduling and unscheduled actions receive separate annotations; never relabel
the primary group using information learned after the start. A zero label means
no scheduled FOMC meeting end in the frozen interval, not an ordinary, event-free,
or otherwise comparable market month. Do not combine every monthly macro release
into an event label that leaves no comparison group.

The following is a **calendar-only illustration**, not the study's schedule. It
uses the currently published FOMC dates and [NYSE holiday/full-session information](https://www.nyse.com/trade/hours-calendars).
Future FOMC dates are tentative. Actual registration must regenerate the complete
schedule from retained broker-calendar evidence and re-review group feasibility.

| Illustrative start | Illustrative end | Scheduled FOMC meeting end in interval |
| --- | --- | --- |
| 2026-11-09 | 2026-12-09 | 2026-12-09 |
| 2026-12-09 | 2027-01-08 | None |
| 2027-01-11 | 2027-02-10 | 2027-01-27 |
| 2027-02-10 | 2027-03-12 | None |
| 2027-03-15 | 2027-04-14 | 2027-03-17 |
| 2027-04-14 | 2027-05-14 | 2027-04-28 |
| 2027-05-17 | 2027-06-16 | 2027-06-09 |
| 2027-06-16 | 2027-07-16 | None |
| 2027-07-19 | 2027-08-18 | 2027-07-28 |
| 2027-08-18 | 2027-09-17 | 2027-09-15 |
| 2027-09-20 | 2027-10-20 | None |
| 2027-11-08 | 2027-12-08 | 2027-12-08 |

This illustration has eight event-labeled and four other windows over about
thirteen months. It demonstrates that both planned labels can exist; four planned
comparison windows are not an adequate basis for a reliable conditioned event
premium claim. Actual missingness or rescheduling can further reduce coverage.

## Input locking, invalidity, and reporting

Proposed acquisition deadline: for each required index date, 18:00 ET on the
second subsequent actual broker session. Use the first valid provider row retained
by that deadline. Preserve the first-seen receipt and later revisions separately;
later corrections are sensitivity data, not replacements for the frozen primary
observation. An input arriving after its deadline remains late for this cohort.
This collection convention does not imply the input was available at its as-of
close and cannot support a contemporaneous trading-decision claim.

A window is not numerically evaluable if any required SPX close or start VIX value
is absent, late, nonfinite, nonpositive, duplicated ambiguously, attached to the
wrong index/date, or unsupported by its retained source receipt. Do not bridge a
missing interior trading session, forward-fill it, or replace it from another
feed. Endpoint/calendar incompatibility, conflicting source identity, or a material
methodology change also prevents pooling that window into the primary definition.
An unknown FOMC label permits reporting an otherwise valid ungrouped gap but not
assigning the window to either event group. Timestamp incompatibility with the
strict original forecast claim remains disclosed for **every** computed gap.

The terminal report retains all twelve planned windows, status and exclusion
reason, acquisition lag, method/calendar versions, required/received input counts,
`VIX_s`, `I_s`, `Q_s`, `D_s`, and the frozen event label. Report equal-window means,
medians and ranges for evaluable windows, alongside their full missing denominator.
Do not give greater weight to a window because it contains more trading sessions.
No partial window contributes cash, zero variance, or a favorable imputed gap.

This first cohort evaluates collection feasibility and describes dispersion. It
must not estimate a causal FOMC effect, claim that VIX-level conditioning has been
satisfied, annualize the gap into a portfolio return, or trigger promotion. Report
small or empty event groups as such. A later event-premium investigation requires
a separate prospective registration with its own VIX-level conditioning,
common-support assessment, uncertainty method, and adequate sample design. Any
pilot observations used to design that investigation remain exploratory history.
Stop after the twelve planned windows and their fixed acquisition deadlines;
there is no automatic extension, replacement window, or outcome-dependent tuning.
