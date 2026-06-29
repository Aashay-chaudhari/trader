# Local Codex Monitor Gate

Run id: 20260629_195551
Candidate symbols: NKE, AVAV, MU
Decision output: `data/profiles/codex/cache/local_monitor_decision.json`

You are an intraday execution gate. Do not re-research the market, broaden the
watchlist, or invent new trades. Evaluate only the candidates below against the
morning execution conditions and the live snapshot.

## Monitor Candidates

  NKE: watch | entry=$41.2 stop=$39.8 target=$44.5
    Setup state: planned | bucket: event_watch | top blocker: Earnings are Tuesday after the close and expectations are mixed after a large YTD decline.
    Action confidence: long_thesis=0.52 entry=0.3 avoid=0.57 data_quality=0.76
    Execution condition: Watch only before earnings; consider action only after NKE clears the event and holds above 41 with constructive guidance reaction.
    Why it is being checked now: price is within 0.1% of entry; 10 fresh headline(s)
  AVAV: buy | entry=$138.5 stop=$134.5 target=$147.0
    Setup state: planned | bucket: buy_today_if_confirmed | top blocker: After-close earnings create event risk, so the setup needs price strength and smaller sizing discipline.
    Action confidence: long_thesis=0.66 entry=0.58 avoid=0.31 data_quality=0.69
    Execution condition: Buy only if AVAV is trading around 138.50, holds VWAP through the first hour, and the position can be kept small ahead of after-close earnings.
    Why it is being checked now: price is within 0.9% of entry; 10 fresh headline(s)
  MU: watch | entry=$1150.0 stop=$1115.0 target=$1225.0
    Setup state: repair_watch | bucket: repair_watch | top blocker: Post-earnings AI-memory thesis is strong, but current quote action shows high crowding and poor entry quality.
    Action confidence: long_thesis=0.64 entry=0.28 avoid=0.62 data_quality=0.7
    Execution condition: Watch only unless MU forms a tight base above 1130 and holds VWAP while QQQ stabilizes.
    Why it is being checked now: price is within 1.3% of entry; 9 fresh headline(s)

## Live Market Snapshot

| Stock | Price | Chg% | RSI | VolRatio | Quote source | Quote age | Headlines |
|-------|-------|------|-----|----------|--------------|-----------|-----------|
| NKE   | $   41.26 |  +1.2% |  39 |     0.8x | yahoo_1m | 57s |        10 |
| AVAV  | $  139.71 |  +1.3% |  33 |     0.8x | yahoo_1m | 54s |        10 |
| MU    | $ 1135.29 |  +0.3% |  59 |     0.9x | yahoo_1m | 55s |         9 |

## Relevant Commodity Snapshot

No direct commodity driver mapped for current candidates.

## Regime Scorecard

Morning scorecard:
Computed regime: neutral (score=1, bullish=3, bearish=2, unknown=1).
Rule: risk_on requires at least 5 bullish factors and no more than 1 bearish factor; otherwise use neutral/risk_off.
- sp500_trend: neutral (0); StreetStats showed the S&P 500 near its 50-day average at 7354.02 versus a 50-day average of 7363.43, above the 200-day but with neutral RSI; finance quote showed SPY slightly lower at 728.99 during premarket.
- qqq_trend: bearish (-1); IBD/Barron's described recent Nasdaq weakness and a sharp tech pullback; finance quote showed QQQ down 1.35% at 706.52.
- small_cap_breadth: bearish (-1); Investing.com premarket data showed IWM lagging at -0.16% while QQQ/SPY futures were higher; finance quote showed IWM slightly lower at 299.83.
- vix_direction: bullish (1); Yahoo/MarketWatch/Investing.com showed VIX around 18.4-18.6, down versus the prior 19.7 area.
- ten_year_yield: bullish (1); Kapitales market summary reported the U.S. 10-year Treasury yield declined for a fourth straight session to 4.37%, its lowest since May 8.
- sector_breadth: unknown (0); Yahoo sector and Schwab calendar sources did not provide a clean real-time sector-leadership read; available evidence showed stock-specific movers rather than broad sector confirmation.
- candidate_relative_strength: bullish (1); Premarket sources showed CMCSA/CHTR/PLTR among active gainers, and finance quote showed PLTR up 5.2% and AVAV up 1.0% before the open.
- headline_risk: neutral (0); U.S.-Iran de-escalation reduced immediate oil/geopolitical risk, but Thursday jobs data and Fed-rate expectations remain unresolved macro risks.

Live scorecard:
Computed regime: neutral (score=4, bullish=4, bearish=0, unknown=2).
Rule: risk_on requires at least 5 bullish factors and no more than 1 bearish factor; otherwise use neutral/risk_off.
- sp500_trend: bullish (1); SPY change=1.56, trend=up
- qqq_trend: bullish (1); QQQ change=2.34
- small_cap_breadth: unknown (0); not available
- vix_direction: bullish (1); VIX level=normal, change=-1.9
- ten_year_yield: neutral (0); 10Y yield=4.37, change=None
- sector_breadth: neutral (0); 6 sectors positive, 5 sectors negative
- candidate_relative_strength: unknown (0); not available
- headline_risk: bullish (1); declared regime=risk_on

## Watchlist Buckets

- avoid_until_new_thesis: QURE
- buy_today_if_confirmed: AVAV, PLTR
- do_not_chase: CHTR, CMCSA
- event_watch: NKE
- repair_watch: MU, QCOM, WDC

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
  - Current market regime hint: risk_on.

Write ONLY valid JSON to `data/profiles/codex/cache/local_monitor_decision.json` with this schema:

```json
{
  "run_id": "20260629_195551",
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

