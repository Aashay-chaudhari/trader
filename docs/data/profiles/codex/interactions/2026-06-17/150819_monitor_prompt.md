# Local Codex Monitor Gate

Run id: 20260617_150543
Candidate symbols: QCOM, HOOD, GM
Decision output: `data/profiles/codex/cache/local_monitor_decision.json`

You are an intraday execution gate. Do not re-research the market, broaden the
watchlist, or invent new trades. Evaluate only the candidates below against the
morning execution conditions and the live snapshot.

## Monitor Candidates

  QCOM: buy | entry=$226.5 stop=$220.5 target=$238.0
    Setup state: invalidated | bucket: repair_watch | top blocker: setup invalidated; require repair before any long entry
    Action confidence: long_thesis=0.68 entry=0.68 avoid=0.32 data_quality=0.5
    Execution condition: Buy only if QCOM is trading between 224.00 and 229.50, holding above VWAP, and semiconductor ETFs are not rolling over.
    Why it is being checked now: price is near stop loss; 9 fresh headline(s)
  HOOD: watch | entry=$124.0 stop=$120.0 target=$132.0
    Setup state: invalidated | bucket: repair_watch | top blocker: setup invalidated; require repair before any long entry
    Action confidence: long_thesis=0.55 entry=0.35 avoid=0.55 data_quality=0.5
    Execution condition: Watch only unless HOOD holds the opening range and fintech/crypto risk appetite remains constructive.
    Why it is being checked now: price is near stop loss; 12 fresh headline(s)
  GM: buy | entry=$85.0 stop=$82.5 target=$90.0
    Setup state: invalidated | bucket: repair_watch | top blocker: setup invalidated; require repair before any long entry
    Action confidence: long_thesis=0.64 entry=0.64 avoid=0.36 data_quality=0.5
    Execution condition: Buy only if GM is trading between 84.00 and 86.00, holding above VWAP, and the broader market remains risk-on.
    Why it is being checked now: price is near stop loss; 9 fresh headline(s)

## Live Market Snapshot

| Stock | Price | Chg% | RSI | VolRatio | Quote source | Quote age | Headlines |
|-------|-------|------|-----|----------|--------------|-----------|-----------|
| QCOM  | $  216.85 |  +1.3% |  52 |     0.2x | yahoo_1m | 44s |         9 |
| HOOD  | $  104.81 |  +6.9% |  70 |     0.6x | yahoo_1m | 47s |        12 |
| GM    | $   81.96 |  -0.7% |  54 |     0.2x | yahoo_1m | 44s |         9 |

## Relevant Commodity Snapshot

No direct commodity driver mapped for current candidates.

## Regime Scorecard

Morning scorecard:
No regime scorecard available.

Live scorecard:
Computed regime: neutral (score=1, bullish=2, bearish=1, unknown=2).
Rule: risk_on requires at least 5 bullish factors and no more than 1 bearish factor; otherwise use neutral/risk_off.
- sp500_trend: neutral (0); SPY change=-0.17, trend=up
- qqq_trend: bullish (1); QQQ change=0.27
- small_cap_breadth: unknown (0); not available
- vix_direction: bullish (1); VIX level=normal, change=-2.61
- ten_year_yield: neutral (0); 10Y yield=4.44, change=None
- sector_breadth: bearish (-1); 4 sectors positive, 7 sectors negative
- candidate_relative_strength: unknown (0); not available
- headline_risk: neutral (0); declared regime=neutral

## Watchlist Buckets

- avoid_until_new_thesis: (none)
- buy_today_if_confirmed: GM, QCOM
- do_not_chase: A, CYTK, MU, WDC
- event_watch: HOOD, TSLA
- repair_watch: (none)

## Active Positions

  (none)

## Deterministic Strategy Snapshot

  Gate runs before the deterministic strategy engine. Use this check only to approve or reject planned setups.

## Decision Rules

  - Approve only when the natural-language execution condition is clearly satisfied now.
  - Prefer 'ready_to_trade=false' when evidence is mixed or incomplete.
  - Never invent a new setup that was not part of the morning plan.
  - If setup_state is invalidated or repair_watch, require explicit repair/reclaim evidence before any buy.
  - Use action_confidence.entry for buy readiness; high action_confidence.avoid means stay out.
  - If live regime scorecard is not risk_on, do not approve growth/cyclical longs that require a risk-on tape.
  - Current market regime hint: neutral.

Write ONLY valid JSON to `data/profiles/codex/cache/local_monitor_decision.json` with this schema:

```json
{
  "run_id": "20260617_150543",
  "overall_sentiment": "bullish | bearish | neutral",
  "market_summary": "1 sentence on whether live conditions confirm or weaken the morning thesis",
  "stocks": {
    "SYMBOL": {
      "recommendation": "buy | sell | hold | watch",
      "confidence": 0.0,
      "ready_to_trade": false,
      "matched_conditions": ["condition currently satisfied"],
      "failed_conditions": ["condition still missing"],
      "monitor_reason": "1 concise sentence",
      "execution_condition": "condition evaluated",
      "setup_state": "planned | eligible | triggered | invalidated | repair_watch | retired",
      "watchlist_bucket": "buy_today_if_confirmed | repair_watch | do_not_chase | event_watch | avoid_until_new_thesis",
      "top_blocker": "single biggest blocker, or none",
      "action_confidence": {
        "long_thesis": 0.0,
        "entry": 0.0,
        "avoid": 0.0,
        "data_quality": 0.0
      },
      "trade_plan": {"entry": 0.0, "stop_loss": 0.0, "target": 0.0}
    }
  }
}
```
