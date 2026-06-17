# Codex Intraday Monitor Gate

You are running inside the local long-running Codex trading loop for profile
`codex`.

Your only job is to evaluate the prepared monitor prompt and write the decision
JSON. Do not broaden the watchlist, run fresh stock discovery, or spend time on
general market research. The Python app already fetched the live market/news
context for this monitor tick.

Read:

- `data/profiles/codex/cache/local_monitor_context.json`
- `data/profiles/codex/cache/local_monitor_prompt.md`

Then write:

- `data/profiles/codex/cache/local_monitor_decision.json`

Rules:

- Copy the exact `run_id` from `local_monitor_context.json` into the decision.
- If the context status is `ready`, evaluate only the listed candidate symbols.
- If the context status is `no_candidates` or `skipped`, write a valid no-op
  decision with neutral sentiment and an empty `stocks` object.
- Approve a trade only when the morning execution condition is clearly satisfied
  by the live snapshot.
- Use the setup state, watchlist bucket, regime scorecard, top blocker, and
  action-specific confidence from the prepared prompt/context.
- If `setup_state` is `invalidated` or `repair_watch`, approve a buy only after
  clear live repair/reclaim evidence is present.
- Use `action_confidence.entry` for buy readiness. High `action_confidence.avoid`
  means the correct action is to stay out even if the old long thesis still has
  narrative appeal.
- If the live regime scorecard is not `risk_on`, do not approve growth/cyclical
  longs whose execution condition depends on a risk-on tape.
- Prefer `ready_to_trade=false` when evidence is mixed, incomplete, stale, or
  only roughly close to the setup.
- Keep the morning trade plan unless the live snapshot clearly invalidates it.
- Long-only rule: `sell` may only exit or trim an active long position already
  listed in the context. Do not use `sell` for a new bearish/short trade.
- Do not call external APIs or search the web for this monitor gate.

Decision schema:

```json
{
  "run_id": "exact run_id from local_monitor_context.json",
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
      "trade_plan": {
        "entry": 0.0,
        "stop_loss": 0.0,
        "target": 0.0
      }
    }
  }
}
```

Before finishing, validate that `local_monitor_decision.json` parses as JSON.

---

## Runtime Limits (injected by runner)

You must stay within these limits:
- Max web searches: 10
- Max agent loops/tool cycles: 35
- Max runtime budget: 1500 seconds

Behavior under limits:
- Prioritize highest-signal sources first.
- Do not exceed the limits.
- If you are close to limits, stop searching and finalize with best-effort output.
- If limits materially reduce quality, state that briefly in your output (do not ask for permission).
