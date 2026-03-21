# GPT Research Pack

Created on 2026-03-21 for this repository as a handoff pack for future Claude work.

## What This Pack Is For

This folder is meant to save the next model from re-discovering the same context:

- what the repo already does well
- where the current "multi-source news" story is weaker than the architecture suggests
- which free or free-tier sources are actually worth integrating
- what implementation order gives the best improvement for the least code churn

## Quick Take

The system architecture describes a multi-source information edge, but the current implementation is still concentrated around Yahoo/yfinance-derived data. That is not fatal for a prototype, but it means the "cross-source confirmation" logic is weaker in practice than it looks on paper.

The best next step is not a giant rewrite. It is a provider abstraction plus three targeted upgrades:

1. Add SEC EDGAR as the official catalyst source.
2. Add one structured news API with a real free tier, preferably Marketaux first.
3. Add FRED-backed macro context so regime detection is less tied to the same Yahoo stack.

## Files In This Folder

- `status_quo_audit.md`: repo-specific audit of the current pipeline and its main research gaps
- `free_news_and_event_sources.md`: vetted source matrix for free and free-tier news/event feeds
- `spec_news_pipeline_v2.md`: implementation spec for a real provider-based news pipeline
- `spec_macro_and_eval_upgrades.md`: macro, evaluation, and prompt/data quality upgrades

## Recommended Build Order

1. Extract the current Yahoo/yfinance logic behind a `NewsProvider` interface.
2. Add an SEC provider for 8-K, 10-Q, 10-K, Form 4, and 13D/13G style catalysts.
3. Add Marketaux as the primary third-party structured news feed.
4. Keep Yahoo/yfinance as a fallback provider instead of the main provider.
5. Add FRED regime inputs and persist news/event observations for later evaluation.

## Source Note

External source research in this folder was checked on 2026-03-21. The main primary sources used were:

- SEC developer resources and EDGAR API docs
- St. Louis Fed FRED API docs
- Alpha Vantage docs and support pages
- Marketaux docs and pricing pages
- NewsAPI pricing and terms
- yfinance docs

