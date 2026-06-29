# Evolution Report - codex Strategist

Generated: 2026-06-29

## Current Read

The profile has enough repeated evidence to tighten process rules, but not enough executed trade history to claim a durable trading edge. Most snapshots are all cash until one AVAV entry on 2026-06-29, and that position was opened minutes before scheduled earnings. The strongest repeated signals are about decision labeling and failed setup handling; the newer WDC and theme-mapping misses are useful but still under-sampled.

## Top Priority

- Title: Block Unplanned Late Earnings Entries
- Category: risk
- Why now: AVAV created real overnight event exposure from a technically fair entry placed minutes before an after-close earnings call.
- Expected impact: Prevents future monitor cycles from turning ordinary technical entries into unmanaged binary-event bets.

## Priority Queue

### high Block Unplanned Late Earnings Entries
- Action: implement_now
- Reason: This is a low-complexity guardrail against a live process risk, and it does not need more samples to justify.

### high Separate Entry, Avoid, Thesis, and Data Confidence
- Action: prepare
- Reason: Repeated evidence across QCOM, GM, HOOD, and MU shows confidence is being used for different decision types and should not be collapsed into one bullish score.

### high Invalidate Failed Buy Ranges Until Fresh Setup Forms
- Action: prepare
- Reason: QCOM, GM, and HOOD all support the rule that breached pre-entry stop or range references should force invalidated or repair-watch status.

### medium Treat Missing VWAP as Unknown, Not Failed
- Action: prepare
- Reason: WDC was a clear miss, but this is one main occurrence. Build a narrow data-quality distinction and alternate confirmation path without weakening VWAP discipline globally.

### low Expand Theme Mapping to Adjacent Liquid Winners
- Action: defer
- Reason: ASTS, RKLB, SPCX, MRNA, and AMKR point to scanner gaps, but the sample is still anecdotal. Track missed-mover reason codes first.

### low Add Afternoon Regime Escalation
- Action: defer
- Reason: June 29 under-called the afternoon strength, but the regime library already allows selective risk-on when indexes, VIX, and leaders confirm. More evidence is needed before changing logic.

## Strong Signals

- Action-specific confidence is repeatedly supported across QCOM, GM, HOOD, and MU.
- Failed buy ranges should not be recycled without a fresh setup; QCOM, GM, and HOOD support this with repeated occurrences.
- VWAP, opening-range, and peer confirmation prevented several low-quality entries in mixed or crowded tapes.
- The live performance sample is still extremely thin, so process controls matter more than edge claims.

## Weak Signals

- WDC supports distinguishing missing VWAP from failed VWAP, but it is still one clear missed-winner case.
- Theme expansion is plausible but under-sampled.
- Afternoon risk-on escalation rests mainly on one strong QQQ/SPY rebound with small-cap lag.
- AVAV is the only executed position and remains unresolved in the profile state.

## Recommended Changes Now

- Add a hard block on new entries during the final 30 minutes before scheduled earnings unless an explicit hold-through-earnings flag is present.
- Require the next monitor cycle to resolve AVAV first using post-earnings price action and the predeclared stop/hold criteria.
- Prepare prompt/schema changes so confidence is labeled separately for entry, avoid, thesis, and data quality.
- Prepare execution gating so a breached pre-entry stop reference forces invalidated or repair-watch status until a fresh setup forms.

## Changes To Avoid Now

- Do not broaden watchlists aggressively from one session of missed adjacent winners.
- Do not weaken VWAP confirmation globally; only separate unavailable data from failed confirmation.
- Do not turn afternoon risk-on escalation into automatic buy permission.
- Do not infer strategy edge from one unresolved executed trade.

## Operator Note

Implement the earnings cutoff first and manage AVAV before optimizing opportunity capture. The next best upgrade is schema discipline around confidence and failed-setup state; scanner expansion should wait for tracked missed-mover reason codes.
