# Local Codex Monitor Gate

Run id: 20260615_140514
Candidate symbols: XOM, JBL, DAL
Decision output: `data/profiles/codex/cache/local_monitor_decision.json`

You are an intraday execution gate. Do not re-research the market, broaden the
watchlist, or invent new trades. Evaluate only the candidates below against the
morning execution conditions and the live snapshot.

## Monitor Candidates

  XOM: watch | entry=$144.0 stop=$148.5 target=$137.0
    Execution condition: Watch for XOM to lose $144 while WTI remains below $81; avoid a bearish entry if crude rebounds or XOM reclaims $148.
    Why it is being checked now: price is near stop loss; price is near target; 9 fresh headline(s)
  JBL: watch | entry=$390.0 stop=$378.0 target=$412.0
    Execution condition: Watch for JBL to build support above $380 and clear $390 on strong volume, but do not carry an oversized position into Wednesday's earnings.
    Why it is being checked now: price is within 0.7% of entry; 8 fresh headline(s)
  DAL: buy | entry=$86.2 stop=$83.8 target=$90.0
    Execution condition: Buy only if DAL stays above $85.80 after the open and trades back through $86.20 while WTI remains near or below $81.
    Why it is being checked now: price is within 1.2% of entry; 9 fresh headline(s)

## Live Market Snapshot

| Stock | Price | Chg% | RSI | VolRatio | Quote source | Quote age | Headlines |
|-------|-------|------|-----|----------|--------------|-----------|-----------|
| XOM   | $  139.40 |  -5.2% |  34 |     0.4x | yahoo_1m | 20s |         9 |
| JBL   | $  392.61 |  +2.0% |  63 |     0.2x | yahoo_1m | 21s |         8 |
| DAL   | $   85.20 |  +2.6% |  66 |     0.4x | yahoo_1m | 18s |         9 |

## Active Positions

  (none)

## Deterministic Strategy Snapshot

  Gate runs before the deterministic strategy engine. Use this check only to approve or reject planned setups.

## Decision Rules

  - Approve only when the natural-language execution condition is clearly satisfied now.
  - Prefer 'ready_to_trade=false' when evidence is mixed or incomplete.
  - Never invent a new setup that was not part of the morning plan.
  - Current market regime hint: risk_on.

Write ONLY valid JSON to `data/profiles/codex/cache/local_monitor_decision.json` with this schema:

```json
{
  "run_id": "20260615_140514",
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
      "trade_plan": {"entry": 0.0, "stop_loss": 0.0, "target": 0.0}
    }
  }
}
```
