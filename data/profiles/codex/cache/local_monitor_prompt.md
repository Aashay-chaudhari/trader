# Local Codex Monitor Gate

Run id: 20260616_173517
Candidate symbols: GM, QCOM, HOOD
Decision output: `data/profiles/codex/cache/local_monitor_decision.json`

You are an intraday execution gate. Do not re-research the market, broaden the
watchlist, or invent new trades. Evaluate only the candidates below against the
morning execution conditions and the live snapshot.

## Monitor Candidates

  GM: buy | entry=$85.0 stop=$82.5 target=$90.0
    Execution condition: Buy only if GM is trading between 84.00 and 86.00, holding above VWAP, and the broader market remains risk-on.
    Why it is being checked now: price is within 1.7% of entry; 9 fresh headline(s)
  QCOM: buy | entry=$226.5 stop=$220.5 target=$238.0
    Execution condition: Buy only if QCOM is trading between 224.00 and 229.50, holding above VWAP, and semiconductor ETFs are not rolling over.
    Why it is being checked now: price is near stop loss; 9 fresh headline(s)
  HOOD: watch | entry=$124.0 stop=$120.0 target=$132.0
    Execution condition: Watch only unless HOOD holds the opening range and fintech/crypto risk appetite remains constructive.
    Why it is being checked now: price is near stop loss; 13 fresh headline(s)

## Live Market Snapshot

| Stock | Price | Chg% | RSI | VolRatio | Quote source | Quote age | Headlines |
|-------|-------|------|-----|----------|--------------|-----------|-----------|
| GM    | $   83.59 |  +2.6% |  59 |     0.5x | yahoo_1m | 20s |         9 |
| QCOM  | $  219.29 |  +3.6% |  53 |     0.6x | yahoo_1m | 20s |         9 |
| HOOD  | $   96.43 |  -1.7% |  63 |     0.7x | yahoo_1m | 22s |        13 |

## Relevant Commodity Snapshot

No direct commodity driver mapped for current candidates.

## Active Positions

  (none)

## Deterministic Strategy Snapshot

  Gate runs before the deterministic strategy engine. Use this check only to approve or reject planned setups.

## Decision Rules

  - Approve only when the natural-language execution condition is clearly satisfied now.
  - Prefer 'ready_to_trade=false' when evidence is mixed or incomplete.
  - Never invent a new setup that was not part of the morning plan.
  - Current market regime hint: neutral.

Write ONLY valid JSON to `data/profiles/codex/cache/local_monitor_decision.json` with this schema:

```json
{
  "run_id": "20260616_173517",
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

