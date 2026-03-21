# Spec: Macro And Evaluation Upgrades

This spec covers the next layer after News Pipeline V2.

## Goal

Give Claude better regime context and create a real learning loop for news/event quality, not just trade outcomes.

## Part 1: FRED-Backed Macro Context

The current `market_context` in `NewsAgent` is useful but mostly built from Yahoo tickers. Add FRED so macro state is less dependent on one public market-data stack.

## Suggested FRED Series

- `VIXCLS` for daily VIX close
- `DGS10` for 10-year Treasury yield
- `DFF` for effective federal funds rate
- `T10Y2Y` for curve slope
- `BAMLH0A0HYM2` for high-yield spread

These series can feed a cleaner regime classifier:

- `risk_on`
- `neutral`
- `cautious`
- `risk_off`

## Suggested Derived Rules

- Rising VIX and widening high-yield spread should cap position size and reduce confidence.
- Bullish single-name setups should be discounted when the curve, credit, and vol picture all worsen together.
- Sector leadership should remain in the prompt, but macro regime should become a separate top-level input.

## Part 2: Event Dataset For Research Quality

Right now the system journals trade outcomes, but it does not really measure whether a headline source or event type added predictive value.

Add a small event-observation store under `data/research_eval/`.

## Proposed Event Record Schema

```json
{
  "id": "provider:provider_id",
  "provider": "marketaux",
  "source_class": "licensed_api",
  "symbol": "NVDA",
  "title": "example headline",
  "url": "https://...",
  "published_at": "2026-03-21T13:10:00Z",
  "first_seen_at": "2026-03-21T13:12:07Z",
  "event_types": ["analyst_upgrade"],
  "sentiment_score": 0.62,
  "market_regime": "risk_on",
  "price_at_first_seen": 923.11
}
```

Later, attach forward labels:

- `return_30m`
- `return_1d`
- `return_3d`
- `return_5d`
- `max_upside_1d`
- `max_drawdown_1d`

## Why This Matters

Claude can only "learn" from trade results today. That is too coarse.

This event dataset lets you answer better questions:

- Which providers produce the most useful catalysts?
- Which event types work best in which regimes?
- Does analyst-upgrade news help or just add noise?
- Are official filings better than media stories for this strategy?

## Part 3: Provider Health And Coverage Metrics

Persist basic provider metrics per run:

- request count
- cache hit count
- empty result rate
- error rate
- unique articles returned
- unique symbols covered
- average article age

This will help future development decide whether a provider is genuinely valuable or just technically integrated.

## Part 4: Research Prompt Upgrades

Once the news objects are normalized, change the prompt inputs.

Instead of mostly headline lists, give Claude:

- official catalysts
- media catalysts
- source agreement summary
- freshness summary
- event-type summary
- provider confidence note

Example prompt section shape:

```json
{
  "NVDA": {
    "official_events": ["8-K filed", "Form 4 insider buy"],
    "media_events": ["analyst upgrade", "AI capex coverage"],
    "source_agreement": 3,
    "freshest_minutes_ago": 24,
    "net_sentiment": 0.58
  }
}
```

This is usually more useful than dumping many near-duplicate headlines.

## Part 5: Journal And Audit Improvements

Extend journal entries so future reviews can cite exactly what the model saw:

- provider name
- source URL
- source class
- published time
- first-seen time
- event type

That will make manual debugging and retrospective model reviews much easier.

## Suggested Implementation Order

1. Add FRED client and enrich `market_context`.
2. Persist normalized event observations on every research and monitor run.
3. Label forward returns in a simple daily batch job.
4. Add provider and event-type hit-rate summaries to the weekly review.
5. Update Claude prompts to use event summaries instead of raw headline floods.

## Acceptance Criteria

- `market_context` can be built even if Yahoo market headline endpoints are flaky.
- Every news item used in research has a reconstructable provider and first-seen timestamp.
- Weekly review can report provider-level and event-level precision.
- Prompt size falls while information density rises.

## Primary References

- FRED API docs: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- SEC developer resources: https://www.sec.gov/about/developer-resources
- SEC EDGAR APIs: https://www.sec.gov/edgar/sec-api-documentation
- Marketaux docs: https://www.marketaux.com/documentation
- Alpha Vantage docs: https://www.alphavantage.co/documentation/
