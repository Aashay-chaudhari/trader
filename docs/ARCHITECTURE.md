# Agent Trader — System Architecture

## How It Works (Visual Flow)

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS (FREE)                        │
│                  Ubuntu VM, ~2 min per run                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
            ┌────────────▼────────────┐
            │    Which phase is it?    │
            └──┬──────────────────┬───┘
               │                  │
    ┌──────────▼──────────┐  ┌───▼───────────────────────┐
    │  9:00 AM ET         │  │  Every 30 min             │
    │  MORNING RESEARCH   │  │  MONITOR & TRADE          │
    └──────────┬──────────┘  └───┬───────────────────────┘
               │                  │
               ▼                  ▼

═══════════════════════════════════════════════════════════════════
 PHASE 1: MORNING RESEARCH (runs once at 9:00 AM ET)
═══════════════════════════════════════════════════════════════════

  ┌─────────────────────┐
  │    NEWS AGENT       │  STEP 1: What's in the news?
  │   (yfinance + RSS)  │
  │   ~15 seconds       │  Sources:
  │                     │  ├── yfinance news (per-stock headlines)
  │                     │  ├── Yahoo Finance RSS (market-wide)
  │                     │  ├── Finviz (analyst upgrades/downgrades)
  │                     │  ├── Insider activity signals
  │                     │  └── Market context (VIX, sectors, S&P)
  │                     │
  │  NEWS DISCOVERY:    │  Scans ~40 key stocks for headline
  │  finds stocks IN    │  activity, sentiment scoring, and
  │  the news that      │  price confirmation
  │  deserve a look     │
  │                     │  Cross-source: stocks in 2+ sources
  │                     │  with aligned sentiment = "hot stocks"
  └──────────┬──────────┘
             │ {news_discoveries, hot_stocks, finviz, market_context}
             ▼
  ┌─────────────────────┐
  │   SCREENER AGENT    │  STEP 2: Hybrid news + data screening
  │  (Python + yfinance) │
  │   ~5 seconds        │  Two paths in:
  │                     │  ├── NEWS PATH: stocks from news
  │                     │  │   discoveries & hot stocks get
  │                     │  │   a score boost
  │                     │  └── TECH PATH: scans 60 liquid US
  │                     │      stocks for momentum × volume
  │                     │
  │  MERGE & RANK:      │  News+technical stocks rank highest
  │  news discovers,    │  Pure news or pure technical follow
  │  data confirms      │  Each stock tagged: NEWS / TECH / BOTH
  └──────────┬──────────┘
             │ ["NVDA", "META", "AAPL", ...]  (top 10)
             ▼
  ┌─────────────────────┐
  │    DATA AGENT       │  STEP 3: Deep technical data
  │   (yfinance, free)  │  Downloads 3 months of price history
  │   ~10 seconds       │  Calculates: RSI, MACD, BBands, SMAs
  └──────────┬──────────┘
             │ {prices, indicators, history}
             ▼
  ┌─────────────────────┐
  │    NEWS AGENT       │  STEP 4: Detailed per-stock news
  │   (2nd pass)        │  Now fetches full news for shortlisted
  │   ~10 seconds       │  stocks: headlines with sentiment scores,
  │                     │  analyst recs, earnings dates, insider
  │                     │  activity, cross-source hot stock flags
  └──────────┬──────────┘
             │ {per-stock news, market_context}
             ▼
  ┌─────────────────────┐
  │  RESEARCH AGENT     │  STEP 5: Claude deep analysis
  │  (Claude Sonnet)    │  ONE API call with FULL context:
  │  ~$0.02, ~5 sec     │
  │                     │  Claude receives:
  │                     │  ├── Market regime (risk-on/off, VIX)
  │                     │  ├── Sector rotation (leaders/laggards)
  │                     │  ├── Technical data (RSI, MACD, trends)
  │                     │  ├── News (headlines, sentiment scores)
  │                     │  ├── Hot stocks & analyst actions
  │                     │  ├── Insider activity signals
  │                     │  ├── Screener context (HOW each stock
  │                     │  │   was found: NEWS/TECH/BOTH)
  │                     │  ├── Its own past trade performance
  │                     │  └── Self-generated trading rules
  │                     │
  │                     │  Output: sentiment, trade plans with
  │                     │  specific entry/stop/target prices
  └──────────┬──────────┘
             │ {sentiment, trade_plans, best_opportunities}
             ▼
  ┌─────────────────────┐
  │   SAVE TO CACHE     │  Morning research cached for monitor
  │   + JOURNAL ENTRY   │  Full markdown log committed to git
  └─────────────────────┘


═══════════════════════════════════════════════════════════════════
 PHASE 2: MONITOR & TRADE (runs every 30 min, 9:30 AM - 4 PM ET)
═══════════════════════════════════════════════════════════════════

  ┌─────────────────────┐
  │    DATA AGENT       │  Refresh current prices only
  │   ~2 seconds        │  (much faster than morning)
  └──────────┬──────────┘
             │ {updated prices + indicators}
             ▼
  ┌─────────────────────┐
  │    NEWS AGENT       │  Quick check for new headlines
  │   ~3 seconds        │  + market context update
  └──────────┬──────────┘
             │ {any new news}
             ▼
  ┌─────────────────────┐
  │  RESEARCH AGENT     │  ONE API call to Claude Haiku (cheap)
  │  (Claude Haiku)     │  "What changed since morning?"
  │  ~$0.001, ~2 sec    │  "Any entry zones hit?"
  └──────────┬──────────┘
             │ {updated recommendations}
             ▼
  ┌─────────────────────┐
  │  STRATEGY AGENT     │  Runs 8 strategies (pure Python, instant):
  │  (Python, ~0 sec)   │
  │                     │  TIER 1 — Classic Technical
  │  ┌─────────────┐    │  ├── Momentum (RSI + MACD)
  │  │ 8 strategies │    │  ├── Mean Reversion (Bollinger)
  │  │ vote on each │    │  ├── Trend Following (SMA crossover)
  │  │ stock. Need  │    │  │
  │  │ 2+ to agree  │    │  TIER 2 — Volume & Price Action
  │  │ for a trade. │    │  ├── Volume Breakout
  │  │              │    │  ├── Support/Resistance
  │  │ Claude gets  │    │  ├── VWAP Reversion
  │  │ DOUBLE vote  │    │  │
  │  │ weight.      │    │  TIER 3 — Smart Context
  │  └─────────────┘    │  ├── Relative Strength (vs market)
  │                     │  └── News Catalyst
  │                     │
  │  If no strong signal│  "Best Available" mode:
  │  → take best with   │  tiny 2% position for learning
  │    tiny position     │
  └──────────┬──────────┘
             │ {signals: [{symbol, action, strength, reasoning}]}
             ▼
  ┌─────────────────────┐
  │    RISK AGENT       │  4 checks on every signal:
  │  (Python, instant)  │  ├── Signal strength ≥ 0.3?
  │                     │  ├── Position size ≤ 10%?
  │                     │  ├── Price move < 15%? (sanity)
  │                     │  └── Volume ≥ 100K? (liquidity)
  │                     │
  │                     │  APPROVED → proceed
  │                     │  REJECTED → logged with reason
  └──────────┬──────────┘
             │ {approved: [...], rejected: [...]}
             ▼
  ┌─────────────────────┐
  │  EXECUTION AGENT    │  DRY RUN (default):
  │                     │    Logs what WOULD have traded
  │  If dry_run=True:   │    Records price, qty, reasoning
  │    → log only       │
  │                     │  PAPER TRADING (when Alpaca connected):
  │  If dry_run=False:  │    Places real paper orders
  │    → Alpaca API     │    via Alpaca free API
  └──────────┬──────────┘
             │ {executed: [{symbol, qty, price, status}]}
             ▼
  ┌─────────────────────┐
  │  PORTFOLIO AGENT    │  Updates positions and P&L
  │                     │  Saves snapshot for dashboard
  │                     │  Tracks: value, cash, unrealized P&L
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │  JOURNAL + DASHBOARD│  Markdown journal → viewable on GitHub
  │                     │  Dashboard JSON → GitHub Pages
  └─────────────────────┘


═══════════════════════════════════════════════════════════════════
 THE INFORMATION EDGE — HOW STOCKS ARE SELECTED
═══════════════════════════════════════════════════════════════════

  Most algo systems pick stocks from technicals alone (momentum,
  volume). That's already priced in. Our edge is the hybrid approach:

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
        │  NEWS+TECH = top │  ← Stock in the news WITH technical
        │  NEWS only = mid │     confirmation ranks highest
        │  TECH only = base│
        │                  │
        │  Hot stocks get  │  ← Mentioned in 2+ independent
        │  extra boost     │     sources with aligned sentiment
        │                  │
        │  Analyst upgrade │  ← Recent upgrade/downgrade
        │  = boost         │     from major firms
        └──────────────────┘


═══════════════════════════════════════════════════════════════════
 FEEDBACK LOOP (what makes this improve over time)
═══════════════════════════════════════════════════════════════════

  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ Claude makes │────▶│ Trade plays  │────▶│ Outcome      │
  │ recommendation│     │ out over     │     │ recorded     │
  │ with entry/  │     │ 1-5 days     │     │ (win/loss,   │
  │ stop/target  │     │              │     │  P&L %)      │
  └──────────────┘     └──────────────┘     └──────┬───────┘
         ▲                                          │
         │                                          │
         │  Next morning, Claude sees:              │
         │  • Its own win rate                      │
         │  • Confidence calibration                │
         │  • What worked / what failed             │
         │  • Self-generated trading rules          │
         │                                          │
         └──────────────────────────────────────────┘
              FEEDBACK LOOP — Claude learns


═══════════════════════════════════════════════════════════════════
 COST BREAKDOWN (monthly)
═══════════════════════════════════════════════════════════════════

  Component          │ Cost    │ Notes
  ───────────────────┼─────────┼────────────────────────
  GitHub Actions     │ FREE    │ ~450 min of 2000/month
  GitHub Pages       │ FREE    │ Static HTML dashboard
  yfinance           │ FREE    │ All market data
  Claude Sonnet      │ ~$0.40  │ 1 call/day × $0.02
  Claude Haiku       │ ~$0.30  │ 13 calls/day × $0.001
  Alpaca paper       │ FREE    │ Paper trading API
  ───────────────────┼─────────┼────────────────────────
  TOTAL              │ ~$0.70  │ Per month

═══════════════════════════════════════════════════════════════════
 WHERE TO LOOK
═══════════════════════════════════════════════════════════════════

  Want to see...            │ Look at...
  ──────────────────────────┼────────────────────────────
  What stocks were picked   │ data/journal/YYYY-MM-DD/
  Claude's full analysis    │ data/research/*.json
  Trade history             │ data/feedback/completed_trades.json
  Claude's learned rules    │ data/feedback/learned_rules.json
  Portfolio performance     │ data/snapshots/latest.json
  Visual dashboard          │ GitHub Pages (docs/index.html)
  System configuration      │ .env file
  Agent source code         │ src/agent_trader/agents/
```
