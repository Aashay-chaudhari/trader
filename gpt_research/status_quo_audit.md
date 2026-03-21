# Status Quo Audit

This audit is based on the current codebase as of 2026-03-21.

## What The Repo Already Does Well

- The architecture already separates discovery, screening, research, strategy, risk, execution, and journaling cleanly.
- The orchestrator already runs news discovery before screening, which is the right place to inject better catalyst data.
- The screener already has hooks for `news_discoveries`, `hot_stocks`, and analyst actions.
- The research prompt is already designed to consume richer market context and news context than the current `NewsAgent` actually provides.
- The journal and cache structure gives a good place to persist richer research artifacts later.

## What The Code Is Actually Doing Today

### News ingestion

`src/agent_trader/agents/news_agent.py`

- The named RSS feeds are all Yahoo Finance feeds.
- Per-symbol news comes from `yf.Ticker(symbol).news`.
- The "Finviz" branch does not scrape Finviz. It uses `yfinance` `upgrades_downgrades` on a fixed list of large-cap tickers.
- Sentiment is simple keyword matching on titles.
- Ticker extraction from RSS is based on a hardcoded set of known tickers, not general entity recognition.
- There is no canonical article ID, URL-based dedupe, provider health tracking, cache layer, or source weighting.

### Screening

`src/agent_trader/agents/screener_agent.py`

- The screener already supports a merged scoring path for technicals plus news boosts.
- This means the system can benefit quickly from better news inputs without changing the overall flow.

### Research prompting

`src/agent_trader/agents/research_agent.py`

- The prompt format already accepts `market_context`, per-stock news, discoveries, hot stocks, and analyst actions.
- The biggest prompt issue is not lack of room. It is that the upstream news objects are still noisy and weakly normalized.

### Settings

`src/agent_trader/config/settings.py` and `.env.example`

- There are no settings yet for:
  - SEC user-agent declaration
  - Marketaux token
  - Alpha Vantage key
  - FRED key
  - provider priority
  - cache TTLs
  - source weighting or rate limiting

### Data concentration

`src/agent_trader/agents/data_agent.py` and `src/agent_trader/agents/news_agent.py`

- Price data, fundamentals, analyst data, and a large share of news inputs all come from the same Yahoo/yfinance stack.
- That means the architecture says "multi-source", but the runtime dependency graph still has a major single-vendor concentration.

## Main Gaps

### 1. Cross-source confirmation is weaker than advertised

The repo talks about multiple independent sources agreeing on a stock, but today many of those "sources" are different views of Yahoo/yfinance data. That weakens the information edge.

### 2. Official catalysts are underused

The system does not yet use SEC filings as a first-class signal even though:

- 8-K filings often matter more than opinion coverage
- Form 4 filings can strengthen insider activity logic
- 10-Q and 10-K arrivals can change the regime around a stock instantly

### 3. News objects are not normalized enough for evaluation

Missing fields today include:

- stable provider IDs
- article URLs in a canonical schema
- first-seen timestamps
- explicit event types
- source class such as official filing vs media story vs fallback feed

Without those, it is hard to measure which news inputs help.

### 4. Market regime is still too Yahoo-centric

The current market context logic is useful, but most of it still comes from yfinance tickers. The system would be stronger if macro state also pulled from FRED.

### 5. Production and licensing risk is understated

The current stack leans heavily on `yfinance`. The yfinance docs describe it as an open-source tool using Yahoo's public endpoints and intended for research, educational work, and personal use, not as a licensed production news feed. Source: https://ranaroussi.github.io/yfinance/index.html

## Highest-Value Direction

The repo does not need a new architecture. It needs better source layering:

1. Official events first.
2. Structured news API second.
3. Yahoo/yfinance third as a fallback or discovery supplement.

That preserves the current agent layout while making the "information edge" much more real.

