# Agent Trader — System Architecture

## How It Works (Visual Flow)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     GITHUB ACTIONS (FREE)                               │
│    Two strategist books run in parallel — Claude + Codex                │
│    Each has isolated data/profiles/<strategist>/ directory              │
│    Results merged into a single comparison dashboard on GitHub Pages    │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │    Which phase is it?    │
              └─┬──────┬──────┬──┬──────┘
                │      │      │  │
     ┌──────────▼─┐ ┌──▼──┐ ┌▼─┐ ┌▼────────┐ ┌──────────┐
     │ 9:00 AM ET │ │30min│ │4:15│ │Sunday  │ │Last biz  │
     │ RESEARCH   │ │MONI-│ │REFL│ │WEEKLY  │ │day MTHLY │
     └──────────┬─┘ └──┬──┘ └┬──┘ └┬────────┘ └──┬───────┘
                │      │     │     │              │
                ▼      ▼     ▼     ▼              ▼
             Phase 1  Ph 2  Ph 3  Ph 4           Ph 5


═══════════════════════════════════════════════════════════════════════════
 PHASE 1: MORNING RESEARCH  (9:00 AM ET, once daily)
═══════════════════════════════════════════════════════════════════════════

  ┌─────────────────────┐
  │    NEWS AGENT       │  STEP 1: What's in the news today?
  │   (yfinance + RSS)  │
  │   ~15 seconds       │  Sources:
  │                     │  ├── yfinance per-stock headlines
  │                     │  ├── Yahoo Finance RSS (market-wide)
  │                     │  ├── Finviz (analyst upgrades/downgrades)
  │                     │  ├── Insider activity signals
  │                     │  └── Market context (VIX, sectors, S&P)
  │                     │
  │  NEWS DISCOVERY:    │  Scans 40 key stocks → finds which are
  │  finds stocks IN    │  in 2+ news sources with aligned sentiment
  │  the news           │  = "hot stocks"
  └──────────┬──────────┘
             │ {news_discoveries, hot_stocks, finviz, market_context}
             ▼
  ┌─────────────────────┐
  │   SCREENER AGENT    │  STEP 2: Hybrid news + data screening
  │  (Python + yfinance)│
  │   ~5 seconds        │  Two paths in:
  │                     │  ├── NEWS PATH: stocks from discoveries
  │                     │  │   get a score boost
  │                     │  └── TECH PATH: scan 60 liquid US stocks
  │                     │      for momentum × volume
  │                     │
  │  MERGE & RANK:      │  NEWS+TECH = highest rank
  │  news discovers,    │  NEWS only or TECH only = lower rank
  │  data confirms      │  → top 10 stocks selected
  └──────────┬──────────┘
             │ ["NVDA", "META", "AAPL", ...]  (top 10)
             ▼
  ┌─────────────────────┐
  │    DATA AGENT       │  STEP 3: Deep technical data
  │   (yfinance, free)  │  Downloads 3 months of price history
  │   ~10 seconds       │  Calculates: RSI, MACD, BBands, SMAs
  └──────────┬──────────┘
             │ {prices, indicators, price_history}
             ▼
  ┌─────────────────────┐
  │    NEWS AGENT       │  STEP 4: Detailed per-stock news (2nd pass)
  │   (2nd pass)        │  Full headlines + sentiment scores
  │   ~10 seconds       │  + analyst recs, earnings dates, insider
  │                     │  activity, cross-source hot-stock flags
  └──────────┬──────────┘
             │ {per-stock news, analyst recs, market_context}
             ▼
  ┌──────────────────────────────────────────────────────┐
  │  RESEARCH AGENT  (Claude Sonnet, ~$0.02/call)        │  STEP 5
  │                                                      │
  │  Full context assembled before API call:             │
  │  ├── Market regime (risk-on/off, VIX, sectors)       │
  │  ├── Technical data (RSI, MACD, BBands, trends)      │
  │  ├── News (headlines, sentiment, insider activity)   │
  │  ├── Screener context (how each stock was found)     │
  │  ├── Own past trade performance + win rate           │
  │  ├── Self-generated trading rules (learned rules)    │
  │  ├── Knowledge context (patterns, strategies,        │
  │  │   regime rules, recent lessons) ← NEW             │
  │  ├── Recent daily observations (last 3 days) ← NEW  │
  │  └── Active swing positions ← NEW                   │
  │                                                      │
  │  Output: sentiment, trade plans with entry/stop/     │
  │  target prices, best opportunities                   │
  └──────────┬───────────────────────────────────────────┘
             │ {sentiment, trade_plans, best_opportunities}
             ▼
  ┌─────────────────────┐
  │   SAVE TO CACHE     │  Morning research cached for monitor phase
  │   + JOURNAL ENTRY   │  Full markdown log committed to git
  └─────────────────────┘


═══════════════════════════════════════════════════════════════════════════
 PHASE 2: MONITOR & TRADE  (every 30 min, 9:30 AM – 4:00 PM ET)
═══════════════════════════════════════════════════════════════════════════

  ┌─────────────────────┐
  │    DATA AGENT       │  Refresh current prices only (~2 sec)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │    NEWS AGENT       │  Quick check for new headlines (~3 sec)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  RESEARCH AGENT     │  Claude Haiku (cheap: ~$0.001/call)
  │  (Claude Haiku)     │  "What changed since morning?"
  │                     │  "Any entry zones hit?"
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  STRATEGY AGENT     │  8 strategies vote (pure Python, instant)
  │                     │
  │  Tier 1 — Classic   │  ├── Momentum (RSI + MACD)
  │  Technical          │  ├── Mean Reversion (Bollinger Bands)
  │                     │  └── Trend Following (SMA crossover)
  │  Tier 2 — Volume    │  ├── Volume Breakout
  │  & Price Action     │  ├── Support/Resistance
  │                     │  └── VWAP Reversion
  │  Tier 3 — Smart     │  ├── Relative Strength (vs market)
  │  Context            │  └── News Catalyst
  │                     │
  │  Need 2+ votes      │  Claude gets DOUBLE vote weight
  │  to execute trade   │  Best-available: 2% position if no signal
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │    RISK AGENT       │  4 checks on every signal:
  │                     │  ├── Signal strength ≥ 0.3?
  │                     │  ├── Position size ≤ 10%?
  │                     │  ├── Price move < 15%? (sanity)
  │                     │  └── Volume ≥ 100K? (liquidity)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  EXECUTION AGENT    │  DRY_RUN=true (default): logs what WOULD trade
  │                     │  DRY_RUN=false: places real Alpaca paper order
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  PORTFOLIO AGENT    │  Updates positions + P&L
  │  + JOURNAL ENTRY    │  Saves snapshot → dashboard JSON
  └─────────────────────┘


═══════════════════════════════════════════════════════════════════════════
 PHASE 3: EVENING REFLECTION  (4:15 PM ET weekdays)    ← NEW
═══════════════════════════════════════════════════════════════════════════

  Inputs assembled before calling Claude:
  ├── Today's journal entries (trades executed, P&L, reasoning)
  ├── Market regime from morning research cache
  ├── Active swing positions (multi-day holds)
  └── Last 3 daily observations (continuity)

  ┌─────────────────────────────────────────────────────────┐
  │  RESEARCH AGENT  (Claude Sonnet)                        │
  │                                                         │
  │  Thinks through:                                        │
  │  • What patterns appeared today?                        │
  │  • Which trades worked? What was the setup quality?     │
  │  • Confidence calibration — was I over/under-confident? │
  │  • What would I do differently?                         │
  │  • What data / strategy / infrastructure gaps did I see?│
  └──────────┬──────────────────────────────────────────────┘
             │
             ├─→ observations/daily/obs_YYYY-MM-DD.json
             ├─→ IMPROVEMENT_PROPOSALS.md  (self-generated backlog)
             └─→ improvement_proposals.json  (structured, filterable)


═══════════════════════════════════════════════════════════════════════════
 PHASE 4: WEEKLY REVIEW  (Sunday 8:00 PM ET)           ← NEW
═══════════════════════════════════════════════════════════════════════════

  Inputs: 5 daily observations + performance data + current knowledge files

  ┌─────────────────────────────────────────────────────────┐
  │  RESEARCH AGENT  (Claude Sonnet)                        │
  │                                                         │
  │  Consolidates:                                          │
  │  • Which patterns had the best win rate this week?      │
  │  • Strategy effectiveness by regime                     │
  │  • Confidence calibration across the week              │
  │  • Sector rotation summary                              │
  │  • Forward thesis for next week                         │
  └──────────┬──────────────────────────────────────────────┘
             │
             ├─→ observations/weekly/week_YYYY-MM-DD.json
             └─→ knowledge/ files updated:
                  ├── patterns_library.json  (max 100 entries)
                  ├── strategy_effectiveness.json
                  ├── regime_library.json
                  └── lessons_learned.json  (max 50 entries)


═══════════════════════════════════════════════════════════════════════════
 PHASE 5: MONTHLY RETROSPECTIVE  (last business day, 5:00 PM ET)  ← NEW
═══════════════════════════════════════════════════════════════════════════

  Inputs: 4 weekly reviews + monthly performance + knowledge base

  ┌─────────────────────────────────────────────────────────┐
  │  RESEARCH AGENT  (Claude Sonnet)                        │
  │                                                         │
  │  Deep review:                                           │
  │  • Win rate by strategy × regime matrix                 │
  │  • Confidence accuracy curve                            │
  │  • Top 10 lessons of the month                          │
  │  • What changed from last month?                        │
  │  • Strategic adjustments for next month                 │
  └──────────┬──────────────────────────────────────────────┘
             │
             └─→ observations/monthly/month_YYYY-MM.json


═══════════════════════════════════════════════════════════════════════════
 KNOWLEDGE ACCUMULATION LAYER  (feeds back into Phase 1)  ← NEW
═══════════════════════════════════════════════════════════════════════════

  data/profiles/<strategist>/knowledge/
  ├── patterns_library.json      Named patterns with win_rate, occurrences
  ├── strategy_effectiveness.json Per-strategy win rates by regime
  ├── regime_library.json         Rules for risk_on / risk_off / neutral
  └── lessons_learned.json        Rolling top-50 lessons

  data/profiles/<strategist>/observations/
  ├── daily/    obs_YYYY-MM-DD.json  (~2 KB, 1/day)
  ├── weekly/   week_YYYY-MM-DD.json (~5 KB, 1/week)
  ├── monthly/  month_YYYY-MM.json   (~10 KB, 1/month)
  └── archive/  YYYY-Qn_daily.json.gz (after 90 days)

  Token budget injected into morning research prompt:
  ├── lessons_learned: top 10 bullet points         ~200 tokens
  ├── regime_library: ONLY current regime's rules   ~150 tokens
  ├── strategy_effectiveness: top 5                 ~200 tokens
  ├── patterns_library: 10 most recent/relevant     ~400 tokens
  ├── recent observations: last 3 days, 2 lines ea  ~300 tokens
  └── forward thesis from latest weekly review      ~250 tokens
  Total added context: ~1500 tokens (budget-capped)


═══════════════════════════════════════════════════════════════════════════
 DUAL-STRATEGIST ARCHITECTURE  ← NEW
═══════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────┐
  │                        GitHub Actions                               │
  │                                                                     │
  │  ┌──────────────────────────┐   ┌──────────────────────────┐        │
  │  │   Claude Strategist      │   │   Codex Strategist       │        │
  │  │                          │   │                          │        │
  │  │  CLI: claude (primary)   │   │  CLI: codex (primary)   │        │
  │  │  API: Anthropic fallback │   │  API: OpenAI fallback   │        │
  │  │  Model: claude-sonnet    │   │  Model: gpt-4o-mini     │        │
  │  │                          │   │                          │        │
  │  │  data/profiles/claude/   │   │  data/profiles/codex/   │        │
  │  │  Alpaca: paper account 1 │   │  Alpaca: paper account 2│        │
  │  └────────────┬─────────────┘   └─────────────┬────────────┘        │
  │               │                               │                     │
  │               └──────────┬────────────────────┘                     │
  │                          ▼                                          │
  │              ┌───────────────────────┐                              │
  │              │  Merged dashboard     │                              │
  │              │  Side-by-side compare │                              │
  │              │  docs/ → GitHub Pages │                              │
  │              └───────────────────────┘                              │
  └─────────────────────────────────────────────────────────────────────┘

  Each strategist has completely isolated:
  ├── Data directory (journal, research, portfolio, knowledge, observations)
  ├── Alpaca paper account (separate API keys: ALPACA_API_KEY_CLAUDE / _CODEX)
  └── IMPROVEMENT_PROPOSALS.md (their own product backlog)


═══════════════════════════════════════════════════════════════════════════
 THE INFORMATION EDGE — HOW STOCKS ARE SELECTED
═══════════════════════════════════════════════════════════════════════════

  ┌───────────────┐         ┌───────────────┐
  │  NEWS PATH    │         │  TECH PATH    │
  │               │         │               │
  │ RSS headlines │         │ Scan 60 stocks│
  │ Analyst recs  │         │ Momentum score│
  │ Insider buys  │         │ Volume surge  │
  │ Finviz movers │         │ Price action  │
  └───────┬───────┘         └───────┬───────┘
          │                         │
          └────────┬────────────────┘
                   ▼
        ┌──────────────────┐
        │  MERGE & RANK    │
        │                  │
        │  NEWS+TECH = top │  ← In news WITH technical confirmation
        │  NEWS only = mid │
        │  TECH only = base│
        │                  │
        │  Hot stocks boost│  ← Mentioned in 2+ independent sources
        │  Analyst upgrade │  ← Recent upgrade from major firm
        └──────────────────┘


═══════════════════════════════════════════════════════════════════════════
 FEEDBACK LOOP — HOW THE AGENT IMPROVES OVER TIME
═══════════════════════════════════════════════════════════════════════════

  Day 1:  Research → Monitor → trade executed
  4:15 PM: Evening Reflection → patterns, lessons, confidence calibration
           → IMPROVEMENT_PROPOSALS.md updated

  Day 2:  Morning Research reads:
          ├── Win rate from last N trades
          ├── Learned rules (Claude's own rules from past reviews)
          ├── Knowledge context (patterns, strategies, regime rules)
          └── Recent daily observations

  Each Sunday: Weekly Review updates knowledge base files
  Each month:  Monthly Retrospective updates top lessons

  After ~30 trading days, the agent has:
  ├── ~30 daily observations
  ├── ~4 weekly reviews
  ├── Up to 100 named patterns with win rates
  ├── Strategy effectiveness by regime
  └── 50 hard-won lessons injected into every morning prompt


═══════════════════════════════════════════════════════════════════════════
 COST BREAKDOWN (monthly estimate)
═══════════════════════════════════════════════════════════════════════════

  Component                │ Cost     │ Notes
  ─────────────────────────┼──────────┼──────────────────────────────
  GitHub Actions           │ FREE     │ ~500 min of 2000/month
  GitHub Pages             │ FREE     │ Static HTML dashboard
  yfinance / Finviz        │ FREE     │ All market data
  Claude Sonnet (research) │ ~$0.40   │ 1 call/day × $0.02 × 20 days
  Claude Haiku (monitor)   │ ~$0.30   │ 13 calls/day × $0.001
  Claude Sonnet (reflect)  │ ~$0.40   │ 1 call/day × $0.02 × 20 days
  Claude Sonnet (weekly)   │ ~$0.08   │ 4 calls/month × $0.02
  Claude Sonnet (monthly)  │ ~$0.02   │ 1 call/month × $0.02
  Alpaca paper trading     │ FREE     │ Paper trading API, no cost
  ─────────────────────────┼──────────┼──────────────────────────────
  TOTAL (1 strategist)     │ ~$1.20   │ Per month
  TOTAL (2 strategists)    │ ~$2.40   │ Claude + Codex running together


═══════════════════════════════════════════════════════════════════════════
 DEBUG MODE — ZERO-COST TESTING
═══════════════════════════════════════════════════════════════════════════

  Set DEBUG_MODE=true (default in .env.example) to:
  ├── Use deterministic template responses (zero LLM API calls)
  ├── Analyze only 3 stocks (instead of 10)
  ├── Skip live web research
  └── Reduce context sizes

  Use this to validate workflow plumbing without burning API credits.
  Set DEBUG_MODE=false in GitHub repository variables for real runs.

  python -m agent_trader research --debug     # Free test
  python -m agent_trader reflect --debug      # Free test
  python -m agent_trader cycle --debug        # Full 5-phase free test


═══════════════════════════════════════════════════════════════════════════
 PRODUCTION CHECKLIST
═══════════════════════════════════════════════════════════════════════════

  GitHub Secrets (Settings → Secrets and variables → Actions → Secrets):
  ├── ANTHROPIC_API_KEY          (for Claude strategist)
  ├── OPENAI_API_KEY             (for Codex strategist)
  ├── ALPACA_API_KEY_CLAUDE      (paper account 1 — claude strategist)
  ├── ALPACA_SECRET_KEY_CLAUDE   (paper account 1)
  ├── ALPACA_API_KEY_CODEX       (paper account 2 — codex strategist)
  ├── ALPACA_SECRET_KEY_CODEX    (paper account 2)
  └── Optional: FINNHUB_API_KEY, MARKETAUX_API_KEY, FRED_API_KEY

  GitHub Variables (Settings → Secrets and variables → Actions → Variables):
  ├── DEBUG_MODE = false          ← CRITICAL: enables real LLM calls
  └── DRY_RUN = false             ← enables actual Alpaca paper orders

  Alpaca setup (alpaca.markets — free):
  ├── Create 2 paper trading accounts (use 2 emails)
  ├── Each: Dashboard → API Keys → Generate paper trading keys
  └── Paper trading endpoint: https://paper-api.alpaca.markets


═══════════════════════════════════════════════════════════════════════════
 WHERE TO LOOK
═══════════════════════════════════════════════════════════════════════════

  What you want to see                │ Where to look
  ────────────────────────────────────┼──────────────────────────────────
  Today's stock picks + reasoning     │ data/profiles/<id>/journal/YYYY-MM-DD/
  Claude's full analysis JSON         │ data/profiles/<id>/research/*.json
  Trade history + win rate            │ data/profiles/<id>/analytics/
  Accumulated patterns & lessons      │ data/profiles/<id>/knowledge/
  Daily observations                  │ data/profiles/<id>/observations/daily/
  Agent's improvement proposals       │ data/profiles/<id>/IMPROVEMENT_PROPOSALS.md
  Portfolio value + positions         │ data/profiles/<id>/snapshots/latest.json
  Visual dashboard                    │ GitHub Pages (docs/index.html)
  System Intelligence tab             │ Dashboard → System Intelligence section
  Configuration                       │ .env (local) / GitHub Secrets+Vars (CI)
  Agent source code                   │ src/agent_trader/agents/
  Knowledge accumulation design       │ docs/KNOWLEDGE_ARCHITECTURE.md
```
