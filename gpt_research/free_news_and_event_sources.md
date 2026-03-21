# Free News And Event Sources

Checked on 2026-03-21.

## Summary Recommendation

For this repo, the strongest free-stack upgrade is:

1. SEC EDGAR APIs plus RSS for official filings and insider/regulatory catalysts
2. Marketaux free tier for structured entity-linked market news
3. FRED for macro regime context
4. Yahoo/yfinance kept only as a fallback and broad supplement

Alpha Vantage is still useful, but its free daily quota is much tighter than Marketaux, so it fits better as a targeted enrichment provider than as the main news API.

## Source Matrix

| Source | Access Model | Why It Matters | Best Use In This Repo | Recommendation |
| --- | --- | --- | --- | --- |
| SEC EDGAR APIs | Free, no API key | Official company filing history, XBRL facts, near-real-time updates | 8-K, 10-Q, 10-K, Form 4, 13D/13G catalyst detection | Highest priority |
| SEC EDGAR RSS | Free, no API key | Company-search and latest-filings RSS feeds for filing monitoring | Lightweight filing alerts by ticker/form type | Highest priority |
| Marketaux | Free token, 100 requests/day, 3 articles/request | Structured entity-linked news with sentiment, highlights, source metadata, domain filters | Main third-party news API for morning research | Best free-tier news API for this repo |
| Alpha Vantage `NEWS_SENTIMENT` | Free key, 25 requests/day | Ticker/topic/time filtered news and sentiment | Targeted checks on top shortlist names or macro topics | Good secondary provider |
| GDELT DOC 2.0 | Public query API, no key | Broad global query-based discovery with JSON and RSS outputs | Theme discovery, broad sector or macro topic scans | Optional discovery-only provider |
| FRED API | Free registered key | Economic data series and regime inputs | Macro context, rates, spreads, volatility regime | High priority, but not a news provider |
| NewsAPI | Free developer plan only, 24h delay, non-production | General news coverage | Not suitable for deployed pipeline | Avoid for production use |
| yfinance / Yahoo public endpoints | No key | Easy access and already integrated | Fallback and supplemental discovery only | De-emphasize |

## Notes By Source

## SEC EDGAR APIs And RSS

Why it is strong:

- It is the official source for filings.
- The SEC says `data.sec.gov` APIs do not require authentication or API keys.
- The SEC says filings data is updated throughout the day in real time.
- The SEC also offers RSS feeds from company and latest-filings searches.

Important implementation constraints:

- The SEC asks automated users to declare a user-agent.
- The fair-access guideline is currently 10 requests per second.

Best repo fit:

- Promote SEC filings to first-class catalysts instead of burying them inside generic news sentiment.
- Treat SEC events as separate from media stories in prompts and scoring.

## Marketaux

Why it is strong:

- The free tier is still usable for a daily research pipeline.
- The API is already shaped around entity-level finance news, not just generic headlines.
- It includes article URLs, source domains, symbol filters, sentiment scores, highlights, and similar-article grouping.

Best repo fit:

- Use it as the primary structured news provider in the morning research phase.
- Use symbol and sentiment filters to keep daily usage low.
- Pull only for:
  - shortlist names
  - hot-stock candidates
  - a small set of sector or macro queries

Known limit:

- The free plan allows 100 daily requests but only 3 articles per news request.

## Alpha Vantage

Why it is useful:

- The `NEWS_SENTIMENT` endpoint supports ticker filters, topic filters, time windows, sort order, and result limits.
- It can complement Marketaux for targeted high-value checks.

Known limit:

- Alpha Vantage says the free service covers most datasets for up to 25 requests per day.

Best repo fit:

- Use only for:
  - final enrichment on the top 3 to 5 names
  - macro-theme spot checks
  - a backup source when Marketaux is unavailable

## GDELT DOC 2.0

Why it is useful:

- It supports broad text queries, `artlist` output, JSON, RSS, domain filters, and time windows.
- It is better for discovery than for clean per-ticker normalization.

Best repo fit:

- Use for theme scans such as:
  - AI capex
  - semis export controls
  - regional banking stress
  - energy policy

Do not use it as the main per-symbol feed unless the repo adds stronger normalization logic first.

## FRED

Why it matters:

- Not a news feed, but a better macro context source than deriving everything from ETF and Yahoo snapshots.
- Useful for rates, spreads, volatility regime, and other top-down state signals.

Best repo fit:

- Feed `market_context` with FRED-backed series such as:
  - `VIXCLS`
  - `DGS10`
  - `DFF`
  - `T10Y2Y`
  - `BAMLH0A0HYM2`

## NewsAPI

Why not to use it here:

- The current free plan is explicitly for development and testing only.
- It has a 24-hour delay on the free plan.
- That makes it a poor fit for an autonomous market-hours pipeline.

## yfinance / Yahoo

Why it should not stay primary:

- It is convenient and already wired in.
- But the yfinance docs position it as an open-source tool for research and personal-use style workflows, not as the backbone of a production-grade multi-source news layer.

Best repo fit:

- Keep for:
  - quick fallback headlines
  - lightweight analyst data already present in the code
  - low-friction prototyping

Do not keep it as the only meaningful news dependency.

## Primary Sources

- SEC EDGAR APIs: https://www.sec.gov/edgar/sec-api-documentation
- SEC developer resources and RSS notes: https://www.sec.gov/about/developer-resources
- SEC fair-access guidance: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- Marketaux docs: https://www.marketaux.com/documentation
- Marketaux pricing: https://www.marketaux.com/pricing
- Alpha Vantage docs: https://www.alphavantage.co/documentation/
- Alpha Vantage support and free-tier limits: https://www.alphavantage.co/support/
- FRED API docs: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- NewsAPI pricing: https://newsapi.org/pricing
- NewsAPI terms: https://newsapi.org/terms
- yfinance docs: https://ranaroussi.github.io/yfinance/index.html
- GDELT DOC 2.0 overview: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

