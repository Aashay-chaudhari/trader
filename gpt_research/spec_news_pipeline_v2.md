# Spec: News Pipeline V2

This spec is intended as a practical implementation handoff, not a blue-sky redesign.

## Goal

Turn the current `NewsAgent` into a provider-based, source-aware ingestion layer that:

- treats official filings differently from media coverage
- supports multiple providers without rewriting the orchestrator
- normalizes articles into a stable schema
- gives the screener and research prompt better structured inputs
- preserves Yahoo/yfinance as a fallback instead of the main feed

## Non-Goals

- full article scraping
- NLP-heavy summarization outside the current agent flow
- replacing the overall orchestration model

## Proposed Package Layout

Add a small news package under `src/agent_trader/`:

- `src/agent_trader/news/models.py`
- `src/agent_trader/news/cache.py`
- `src/agent_trader/news/scoring.py`
- `src/agent_trader/news/providers/base.py`
- `src/agent_trader/news/providers/yahoo.py`
- `src/agent_trader/news/providers/sec.py`
- `src/agent_trader/news/providers/marketaux.py`
- `src/agent_trader/news/providers/alphavantage.py`

Keep `src/agent_trader/agents/news_agent.py` as the orchestration wrapper around these providers.

## Normalized Data Model

Define a normalized article/event schema roughly like this:

```python
from dataclasses import dataclass, field
from typing import Literal


SourceClass = Literal["official_filing", "licensed_api", "public_feed", "fallback"]


@dataclass
class NewsItem:
    provider: str
    provider_id: str
    source_class: SourceClass
    title: str
    url: str | None
    source_domain: str | None
    published_at: str | None
    first_seen_at: str
    symbols: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    sentiment_score: float | None = None
    relevance_score: float | None = None
    raw: dict = field(default_factory=dict)
```

Add a bundle object for agent output:

```python
@dataclass
class NewsBundle:
    articles: list[NewsItem]
    by_symbol: dict[str, list[NewsItem]]
    market_items: list[NewsItem]
    provider_health: dict[str, dict]
    hot_symbols: list[dict]
    discoveries: list[dict]
```

## Provider Contract

Each provider should expose the same minimal interface:

```python
class BaseNewsProvider(Protocol):
    name: str

    def fetch_symbol_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsItem]:
        ...

    def fetch_market_news(self, since: datetime | None = None) -> list[NewsItem]:
        ...

    def healthcheck(self) -> dict:
        ...
```

The SEC provider should additionally expose filing-event fetch helpers, but the `NewsAgent` can adapt those into normal `NewsItem` objects before returning them downstream.

## Event Taxonomy

Normalize into explicit event tags instead of only sentiment:

- `earnings`
- `guidance`
- `mna`
- `analyst_upgrade`
- `analyst_downgrade`
- `insider_buy`
- `insider_sell`
- `regulatory`
- `product_launch`
- `litigation`
- `macro`
- `sector_rotation`
- `other`

For SEC filings:

- 8-K -> usually `regulatory`, `guidance`, `mna`, or `other` depending on the header/body
- 10-Q / 10-K -> `earnings`
- Form 4 -> `insider_buy` or `insider_sell`
- 13D / 13G -> `regulatory`

## Source Weighting

Do not treat every source equally.

Suggested starting weights:

- official filing: `1.00`
- licensed structured API: `0.80`
- public feed or query API: `0.55`
- fallback Yahoo/yfinance: `0.30`

Suggested relevance score inputs:

- source weight
- freshness decay
- event-type weight
- multi-source agreement bonus
- symbol-specific match strength

Suggested event weights:

- earnings/guidance/mna/regulatory: `0.90`
- insider activity: `0.75`
- analyst action: `0.45`
- generic market coverage: `0.25`

Suggested freshness half-life:

- research phase: 6 hours
- monitor phase: 2 hours

## Dedupe Rules

Deduplicate by:

1. exact URL when present
2. provider plus provider ID
3. normalized title plus source domain plus same calendar day

Track `first_seen_at` separately from `published_at` so later evaluation uses what the system knew when it knew it.

## How To Wire It Into Existing Agents

### `NewsAgent`

Keep the existing public interface but change internals to:

1. load configured providers
2. fetch per-symbol and market items
3. normalize and dedupe
4. compute `hot_stocks` from true multi-provider agreement
5. return legacy-compatible summary fields plus normalized bundles

### `ScreenerAgent`

Use the normalized fields instead of heuristics where possible:

- boost official filings more than opinion headlines
- boost symbols with agreement across SEC plus one media provider
- down-rank stale headlines

### `ResearchAgent`

Prompt with:

- official catalysts
- structured media catalysts
- disagreement or agreement across providers
- source class and freshness

Do not send raw headline spam when a structured event summary will do.

## Suggested Settings Additions

Add to `src/agent_trader/config/settings.py` and `.env.example`:

- `marketaux_api_token`
- `alpha_vantage_api_key`
- `fred_api_key`
- `sec_user_agent`
- `news_provider_order`
- `news_cache_ttl_minutes`
- `news_discovery_lookback_hours`
- `news_max_items_per_symbol`

Example environment values:

```env
MARKETAUX_API_TOKEN=
ALPHA_VANTAGE_API_KEY=
FRED_API_KEY=
SEC_USER_AGENT=AgentTrader research@example.com
NEWS_PROVIDER_ORDER=sec,marketaux,yahoo
NEWS_CACHE_TTL_MINUTES=20
NEWS_DISCOVERY_LOOKBACK_HOURS=18
NEWS_MAX_ITEMS_PER_SYMBOL=12
```

## Cache Design

Use file-backed cache under `data/cache/news/`:

- one file per provider plus query hash
- include fetch timestamp
- include provider name and request parameters
- short TTL during market hours

This matters because the free tiers are small and repeated monitor runs can burn them quickly.

## Suggested PR Sequence

### PR 1

- Extract Yahoo logic into `providers/yahoo.py`
- Add normalized models
- Keep behavior functionally similar

### PR 2

- Add SEC provider
- Add filing-to-event normalization
- Add `sec_user_agent`

### PR 3

- Add Marketaux provider
- Use it only in morning research at first

### PR 4

- Add scoring, dedupe, provider health, and caching
- Update screener boosts

### PR 5

- Update research prompt formatting to separate official catalysts from media catalysts
- Add tests and fixtures

## Acceptance Criteria

- The `NewsAgent` still returns the fields the orchestrator expects today.
- A stock with a fresh 8-K and confirming third-party coverage ranks above a stock with only Yahoo headlines.
- Monitor runs do not exceed configured free-tier budgets under normal daily operation.
- The journal or saved research artifacts include enough fields to reconstruct what information was seen and when.
- Tests cover provider normalization, dedupe, and fallback behavior.

