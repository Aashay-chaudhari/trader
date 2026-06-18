# Local Codex Monitor Gate

Run id: 20260618_140555
Candidate symbols: QCOM, MU, HOOD
Decision output: `data/profiles/codex/cache/local_monitor_decision.json`

You are an intraday execution gate. Do not re-research the market, broaden the
watchlist, or invent new trades. Evaluate only the candidates below against the
morning execution conditions and the live snapshot.

## Monitor Candidates

  QCOM: watch | entry=$224.0 stop=$217.5 target=$238.0
    Setup state: repair_watch | bucket: repair_watch | top blocker: Prior AI/Tenstorrent gap failed; QCOM must reclaim the old failed zone before any new long thesis is actionable.
    Action confidence: long_thesis=0.49 entry=0.28 avoid=0.62 data_quality=0.64
    Execution condition: Watch only unless QCOM reclaims 220.50-224.00, holds VWAP, and outperforms SMH after the first hour.
    Why it is being checked now: price is within 1.0% of entry; 9 fresh headline(s)
  MU: buy | entry=$1090.0 stop=$1050.0 target=$1150.0
    Setup state: eligible | bucket: buy_today_if_confirmed | top blocker: Parabolic memory-stock run makes entry quality only fair unless MU holds VWAP and avoids chasing above the first-hour range.
    Action confidence: long_thesis=0.73 entry=0.58 avoid=0.3 data_quality=0.72
    Execution condition: Buy only if MU trades near 1085.00-1105.00, holds VWAP after the first hour, and WDC/STX/SMH remain constructive rather than fading the premarket gap.
    Why it is being checked now: price is within 1.6% of entry; 9 fresh headline(s)
  HOOD: watch | entry=$107.0 stop=$103.0 target=$116.0
    Setup state: repair_watch | bucket: repair_watch | top blocker: The restructuring/200-day reclaim narrative needs proof of fintech and crypto risk appetite before it is buyable.
    Action confidence: long_thesis=0.52 entry=0.34 avoid=0.58 data_quality=0.62
    Execution condition: Watch only unless HOOD holds its 200-day reclaim and VWAP after the first hour while crypto/fintech peers confirm risk appetite.
    Why it is being checked now: price is within 1.8% of entry; 11 fresh headline(s)

## Live Market Snapshot

| Stock | Price | Chg% | RSI | VolRatio | Quote source | Quote age | Headlines |
|-------|-------|------|-----|----------|--------------|-----------|-----------|
| QCOM  | $  226.14 |  +6.1% |  55 |     0.3x | yahoo_1m | 5s |         9 |
| MU    | $ 1107.05 |  +6.1% |  65 |     0.2x | yahoo_1m | 63s |         9 |
| HOOD  | $  105.06 |  -0.1% |  69 |     0.2x | yahoo_1m | 64s |        11 |

## Relevant Commodity Snapshot

No direct commodity driver mapped for current candidates.

## Regime Scorecard

Morning scorecard:
Computed regime: neutral (score=3, bullish=4, bearish=2, unknown=2).
Rule: risk_on requires at least 5 bullish factors and no more than 1 bearish factor; otherwise use neutral/risk_off.
- sp500_trend: neutral (0); Investopedia reported S&P 500 futures +0.8% early June 18, but Barron's reported the S&P 500 fell 1.2% on June 17 after the Fed.
- qqq_trend: neutral (0); Investopedia reported Nasdaq 100 futures +1.4%, but Barron's reported the Nasdaq fell 1.3% on June 17 and the profile's last observation warned that Nasdaq weakness can coexist with low VIX.
- small_cap_breadth: unknown (0); No reliable June 18 small-cap breadth source was verified within the 10-search budget.
- vix_direction: bullish (1); Yahoo Finance showed VIX near 17.13, down about 7.1%, and Investing.com showed S&P 500 VIX 17.13, down about 7.05%.
- ten_year_yield: bullish (1); Investing.com showed the U.S. 10Y around 4.437%, down about 0.020, while Investors.com cited 4.46% premarket.
- sector_breadth: bullish (1); Premarket leadership was concentrated but broad within semiconductors and storage: Investing.com listed INTC, ON, WDC, LRCX, KLAC, AMAT, TER, STX; MarketWatch highlighted Intel, Micron, and Marvell gains.
- candidate_relative_strength: bullish (1); INTC was reported up roughly 6-10% premarket and MU around 4-6% premarket on fresh company/analyst catalysts.
- headline_risk: bearish (-1); Guardian and Barron's reported that the Fed held rates but signaled possible hikes and unsettled markets; Juneteenth closure tomorrow may also reduce follow-through.

Live scorecard:
Computed regime: risk_on (score=5, bullish=5, bearish=0, unknown=2).
Rule: risk_on requires at least 5 bullish factors and no more than 1 bearish factor; otherwise use neutral/risk_off.
- sp500_trend: bullish (1); SPY change=0.59, trend=flat
- qqq_trend: bullish (1); QQQ change=1.9
- small_cap_breadth: unknown (0); not available
- vix_direction: bullish (1); VIX level=normal, change=-0.58
- ten_year_yield: neutral (0); 10Y yield=4.43, change=None
- sector_breadth: bullish (1); 7 sectors positive, 4 sectors negative
- candidate_relative_strength: unknown (0); not available
- headline_risk: bullish (1); declared regime=risk_on

## Watchlist Buckets

- avoid_until_new_thesis: (none)
- buy_today_if_confirmed: INTC, MU
- do_not_chase: QURE, WDC
- event_watch: (none)
- repair_watch: HOOD, QCOM

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
  "run_id": "20260618_140555",
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
