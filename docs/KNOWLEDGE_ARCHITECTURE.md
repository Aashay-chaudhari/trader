# Knowledge Accumulation Architecture

How the agent gets smarter over time through structured introspection,
accumulated knowledge, and feedback loops.

---

## Phase Timeline (Daily)

```
 9:00 AM ET   Phase 1: Morning Research
              ├── ScreenerAgent → find today's stocks
              ├── DataAgent → prices + technicals
              ├── NewsAgent → headlines, sentiment, analyst recs
              └── ResearchAgent (Sonnet) → deep analysis + trade plans
                   Reads: staging/ + knowledge/ + observations/ + positions/active/

 9:30 AM -    Phase 2: Monitor & Trade (every 30 min)
 4:00 PM ET   ├── DataAgent → refresh prices
              ├── NewsAgent → new headlines
              ├── ResearchAgent (Haiku) → "what changed?"
              ├── StrategyAgent → 8 strategies vote
              ├── RiskAgent → validate
              ├── ExecutionAgent → trade or log
              └── PortfolioAgent → update P&L
                   Reads: cache/morning_research.json + positions/active/

 4:15 PM ET   Phase 3: Evening Reflection (NEW)
              ├── Load today's journals + trades + market data
              ├── ResearchAgent → "what did we learn today?"
              ├── Save observations/daily/obs_YYYY-MM-DD.json
              ├── Update positions/active/ with end-of-day prices
              └── Write IMPROVEMENT_PROPOSALS.md (self-improvement ideas)
                   Reads: journal/ + positions/ + observations/daily/ (last 3)
                   Writes: IMPROVEMENT_PROPOSALS.md + improvement_proposals.json

 Sunday       Phase 4: Weekly Review (NEW)
 8:00 PM ET   ├── Load 5 daily observations + performance data
              ├── ResearchAgent → consolidate patterns, strategies, lessons
              ├── Save observations/weekly/week_YYYY-MM-DD.json
              └── Update knowledge/ files (patterns, strategies, regime rules)
                   Reads: observations/daily/ + feedback/ + knowledge/

 Last biz     Phase 5: Monthly Retrospective (NEW)
 day 5 PM ET  ├── Load 4 weekly reviews + monthly performance
              ├── ResearchAgent → deep review, confidence curves, strategy matrix
              ├── Save observations/monthly/month_YYYY-MM.json
              └── Update knowledge/lessons_learned.json
                   Reads: observations/weekly/ + knowledge/ + feedback/
```

---

## Monthly Flow Diagram

```
Week 1                    Week 2                    Week 3                    Week 4
─────────────────────     ─────────────────────     ─────────────────────     ─────────────────────
Mon: Research+Monitor     Mon: Research+Monitor     Mon: Research+Monitor     Mon: Research+Monitor
     Evening Reflect           Evening Reflect           Evening Reflect           Evening Reflect
     → obs_03-03.json          → obs_03-10.json          → obs_03-17.json          → obs_03-24.json

Tue: Monitor (×14)        Tue: Monitor (×14)        Tue: Monitor (×14)        Tue: Monitor (×14)
     Evening Reflect           Evening Reflect           Evening Reflect           Evening Reflect
     → obs_03-04.json          → obs_03-11.json          → obs_03-18.json          → obs_03-25.json

Wed: Monitor (×14)        Wed: Monitor (×14)        Wed: Monitor (×14)        Wed: Monitor (×14)
     Evening Reflect           Evening Reflect           Evening Reflect           Evening Reflect

Thu: Monitor (×14)        Thu: Monitor (×14)        Thu: Monitor (×14)        Thu: Monitor (×14)
     Evening Reflect           Evening Reflect           Evening Reflect           Evening Reflect

Fri: Monitor (×14)        Fri: Monitor (×14)        Fri: Monitor (×14)        Fri: Monitor (×14)
     Evening Reflect           Evening Reflect           Evening Reflect           Evening Reflect
     → obs_03-07.json          → obs_03-14.json          → obs_03-21.json          → obs_03-28.json

Sun: WEEKLY REVIEW        Sun: WEEKLY REVIEW        Sun: WEEKLY REVIEW        Sun: WEEKLY REVIEW
     → week_03-03.json         → week_03-10.json         → week_03-17.json         → week_03-24.json
     → update knowledge/       → update knowledge/       → update knowledge/       → update knowledge/

                                                                               Fri: MONTHLY REVIEW
                                                                                    → month_03.json
                                                                                    → update lessons

Files created per month:
  ~20 daily observations     (20 trading days × 1)
   4 weekly reviews          (4 Sundays × 1)
   1 monthly retrospective   (1 × 1)
   ~200 trades (positions/)  (varies)
```

---

## Data Flow: What Feeds What

```
                    ┌─────────────────────────────────────────────────┐
                    │              KNOWLEDGE BASE                     │
                    │  knowledge/patterns_library.json                │
                    │  knowledge/strategy_effectiveness.json          │
                    │  knowledge/regime_library.json                  │
                    │  knowledge/lessons_learned.json                 │
                    └────────────┬──────────────────┬─────────────────┘
                                 │                  │
                    Updated by   │                  │  Read by
                    Weekly +     │                  │  Morning Research
                    Monthly      │                  │  (token-budgeted)
                    Reviews      │                  │
                                 │                  ▼
┌──────────────┐    ┌────────────┴───┐    ┌─────────────────────┐
│ Daily        │───▶│ Weekly         │    │ Morning Research    │
│ Observations │    │ Review         │    │ Prompt Assembly     │
│              │    │                │    │                     │
│ obs_MM-DD    │    │ week_MM-DD     │    │ performance_feedback│ ~300 tok
│ (5 days)     │    │ (consolidates) │    │ learned_rules       │ ~200 tok
└──────┬───────┘    └────────┬───────┘    │ artifact_context    │ ~200 tok
       │                     │            │ ─── NEW ───         │
       │            ┌────────▼───────┐    │ knowledge_context   │ ~1500 tok
       │            │ Monthly        │    │ observations_context│ ~500 tok
       │            │ Retrospective  │    │ swing_context       │ ~300 tok
       │            │                │    │ ─── EXISTING ───    │
       │            │ month_MM       │    │ market_context      │ ~300 tok
       │            │ (deep review)  │    │ market_data         │ ~2000 tok
       │            └────────────────┘    │ news_context        │ ~1500 tok
       │                                  │ screener_context    │ ~500 tok
       │                                  │                     │
       │                                  │ TOTAL: ~7300 tokens │
       ▼                                  └─────────────────────┘
┌──────────────┐
│ Evening      │    ┌─────────────────┐
│ Reflection   │───▶│ Swing Positions │
│              │    │                 │
│ Reviews day  │    │ positions/      │
│ Updates obs  │    │   active/       │──▶ Read by Monitor + Research
│ Updates pos  │    │   closed/       │──▶ Read by Weekly Review
└──────────────┘    └─────────────────┘
```

---

## Directory Structure (per profile)

```
data/profiles/[profile_id]/
│
├── observations/
│   ├── daily/
│   │   ├── obs_2026-03-21.json          # ~2KB, agent's daily reflection
│   │   ├── obs_2026-03-20.json
│   │   └── ...
│   ├── weekly/
│   │   ├── week_2026-03-17.json         # ~5KB, consolidated weekly review
│   │   └── ...
│   ├── monthly/
│   │   ├── month_2026-03.json           # ~10KB, monthly retrospective
│   │   └── ...
│   └── archive/
│       └── 2026-Q1_daily.json.gz        # Compressed old daily observations
│
├── knowledge/
│   ├── patterns_library.json            # Max 100 entries, ~50KB
│   │   # Every pattern observed + win rate + regime context
│   ├── strategy_effectiveness.json      # Overwritten weekly, ~10KB
│   │   # Which of our 8 strategies works in which regime
│   ├── regime_library.json              # Overwritten weekly, ~5KB
│   │   # Rules per market regime (risk_on, risk_off, high_vol, etc.)
│   └── lessons_learned.json             # Rolling 50 entries, ~20KB
│       # Top actionable insights across all time
│
├── positions/
│   ├── active/
│   │   ├── NVDA_20260321.json           # ~1KB, open swing position
│   │   └── TSLA_20260318.json
│   └── closed/
│       ├── AAPL_20260315_20260319.json  # ~2KB, closed with P&L + lessons
│       └── ...
│
├── IMPROVEMENT_PROPOSALS.md              # Agent's self-improvement ideas (human-readable)
├── improvement_proposals.json            # Structured proposals (last 90 days)
│
├── (existing directories unchanged)
├── journal/
├── research/
├── context/
├── analytics/
├── snapshots/
├── staging/current/
├── cache/
└── feedback/
```

---

## File Schemas

### Daily Observation (`observations/daily/obs_YYYY-MM-DD.json`)

```json
{
  "date": "2026-03-21",
  "market_regime": "risk_on",
  "market_summary": "Tech led risk-on rally, VIX fell to 15.2, yields stable",
  "sector_leaders": ["Technology", "Energy"],
  "sector_laggards": ["Utilities", "Consumer Staples"],
  "trades_review": [
    {
      "symbol": "NVDA",
      "action": "buy",
      "entry": 128.50,
      "exit": 131.20,
      "pnl_pct": 2.1,
      "confidence": 0.8,
      "assessment": "Good entry at support, thesis confirmed by volume"
    }
  ],
  "patterns_detected": [
    {
      "name": "gap_and_go",
      "symbol": "TSLA",
      "outcome": "won",
      "notes": "Gapped up 2.5% on volume, continued in first hour"
    }
  ],
  "confidence_calibration": {
    "high_conf_count": 2,
    "high_conf_win_rate": 1.0,
    "medium_conf_count": 3,
    "medium_conf_win_rate": 0.67,
    "assessment": "Slightly overconfident on medium-confidence calls"
  },
  "swing_updates": [
    {
      "symbol": "TSLA",
      "action": "hold",
      "current_pnl_pct": 1.5,
      "reason": "Momentum intact, 2 days to target"
    }
  ],
  "forward_outlook": "FOMC minutes tomorrow, expect vol spike. Tighten stops.",
  "lessons": [
    "Momentum trades work best in first hour after open",
    "Mean reversion failed on gap days — avoid this pattern on gaps"
  ]
}
```

### Weekly Review (`observations/weekly/week_YYYY-MM-DD.json`)

```json
{
  "week_start": "2026-03-17",
  "week_end": "2026-03-21",
  "summary": {
    "trades_count": 18,
    "win_rate": 0.72,
    "total_pnl_pct": 2.3,
    "swing_positions_held": 4,
    "swing_win_rate": 0.75
  },
  "pattern_effectiveness": [
    {
      "pattern": "gap_and_go",
      "occurrences": 6,
      "win_rate": 0.83,
      "avg_return_pct": 1.5,
      "best_regime": "risk_on",
      "note": "Very effective this week, especially Mon-Wed"
    }
  ],
  "strategy_effectiveness": {
    "momentum": {"win_rate": 0.80, "avg_return": 1.2, "best_regime": "risk_on"},
    "mean_reversion": {"win_rate": 0.55, "avg_return": 0.4, "best_regime": "range_bound"},
    "trend_follow": {"win_rate": 0.60, "avg_return": 0.8, "best_regime": "trending"}
  },
  "regime_analysis": {
    "dominant": "risk_on",
    "shifts": 1,
    "shift_date": "2026-03-19",
    "shift_description": "Brief rotation to defensives Wed AM, reversed by close"
  },
  "confidence_calibration": {
    "high": {"expected": 0.80, "actual": 0.85},
    "medium": {"expected": 0.60, "actual": 0.58},
    "low": {"expected": 0.40, "actual": 0.33}
  },
  "forward_thesis": {
    "outlook": "Risk-on continues but earnings season starting — expect vol increase",
    "confidence": 0.70,
    "key_risks": ["FOMC next week", "Tech earnings concentration"],
    "opportunities": ["Rotation to small-caps if risk-on holds"]
  },
  "knowledge_updates": {
    "new_patterns": [],
    "updated_strategies": ["momentum", "mean_reversion"],
    "new_lessons": ["Gap days invalidate mean reversion setups"],
    "regime_rules_updated": true
  }
}
```

### Monthly Review (`observations/monthly/month_YYYY-MM.json`)

```json
{
  "month": "2026-03",
  "summary": {
    "trading_days": 20,
    "total_trades": 72,
    "win_rate": 0.68,
    "total_pnl_pct": 5.2,
    "best_week": "2026-03-17 (+2.3%)",
    "worst_week": "2026-03-03 (-0.8%)"
  },
  "strategy_regime_matrix": {
    "momentum": {"risk_on": 0.82, "risk_off": 0.45, "range_bound": 0.60},
    "mean_reversion": {"risk_on": 0.55, "risk_off": 0.70, "range_bound": 0.75}
  },
  "confidence_accuracy_curve": {
    "0.9+": {"trades": 8, "actual_win_rate": 0.88},
    "0.7-0.9": {"trades": 25, "actual_win_rate": 0.72},
    "0.5-0.7": {"trades": 30, "actual_win_rate": 0.57},
    "<0.5": {"trades": 9, "actual_win_rate": 0.33}
  },
  "top_lessons": [
    "Momentum is our strongest strategy in risk-on (82% win rate)",
    "Mean reversion works best in range-bound markets, not trending",
    "High VIX (>25) improves mean reversion but kills momentum",
    "Our confidence calibration is accurate within 5% at all levels",
    "Gap days should trigger different strategy selection"
  ],
  "vs_last_month": {
    "win_rate_change": "+3%",
    "pnl_change": "+1.2%",
    "improvement_areas": "Better regime detection, faster exits on thesis breaks",
    "regression_areas": "Overtrading on low-conviction setups"
  }
}
```

### Knowledge: Patterns Library (`knowledge/patterns_library.json`)

```json
{
  "patterns": [
    {
      "name": "gap_and_go",
      "description": "Stock gaps up >2% on above-average volume, continuation in first hour",
      "first_seen": "2026-03-05",
      "last_seen": "2026-03-21",
      "total_occurrences": 24,
      "win_rate": 0.71,
      "avg_return_pct": 1.4,
      "best_regime": "risk_on",
      "worst_regime": "risk_off",
      "symbols_seen": ["TSLA", "NVDA", "AMD", "META"],
      "notes": "Works best Mon-Wed, weaker on Fridays"
    }
  ],
  "last_updated": "2026-03-21"
}
```

### Knowledge: Regime Library (`knowledge/regime_library.json`)

```json
{
  "regimes": {
    "risk_on": {
      "indicators": "VIX < 18, S&P above 20-day MA, tech leading",
      "preferred_strategies": ["momentum", "trend_follow"],
      "avoid_strategies": ["mean_reversion"],
      "position_size_modifier": 1.0,
      "stop_loss_modifier": 1.0,
      "rules": [
        "Prefer breakout entries over pullback entries",
        "Widen targets by 20%, tighter stops"
      ]
    },
    "risk_off": {
      "indicators": "VIX > 25, S&P below 20-day MA, defensives leading",
      "preferred_strategies": ["mean_reversion"],
      "avoid_strategies": ["momentum", "trend_follow"],
      "position_size_modifier": 0.5,
      "stop_loss_modifier": 1.5,
      "rules": [
        "Reduce position sizes by 50%",
        "Only trade highest conviction setups (>0.8)"
      ]
    }
  },
  "last_updated": "2026-03-21"
}
```

### Active Position (`positions/active/NVDA_20260321.json`)

```json
{
  "symbol": "NVDA",
  "entry_date": "2026-03-21",
  "entry_price": 128.50,
  "quantity": 78,
  "stop_loss": 126.50,
  "target": 135.00,
  "timeframe": "swing_2_5_days",
  "reasoning": "Post-earnings breakout above 200-day MA on 2x volume",
  "confidence": 0.75,
  "position_size_pct": 4.0,
  "daily_updates": [
    {
      "date": "2026-03-21",
      "close": 129.80,
      "pnl_pct": 1.01,
      "note": "Day 1: Holding above entry, volume confirmed"
    }
  ],
  "status": "active"
}
```

### Closed Position (`positions/closed/NVDA_20260321_20260324.json`)

```json
{
  "symbol": "NVDA",
  "entry_date": "2026-03-21",
  "exit_date": "2026-03-24",
  "entry_price": 128.50,
  "exit_price": 134.20,
  "quantity": 78,
  "pnl": 444.60,
  "pnl_pct": 4.44,
  "days_held": 3,
  "exit_reason": "target_hit",
  "confidence": 0.75,
  "lessons": "Breakout thesis confirmed — volume + 200-day MA support was key signal"
}
```

---

## Token Budget Breakdown

### Morning Research Prompt (~7300 tokens total)

```
Section                    Tokens   Source
─────────────────────────  ──────   ────────────────────────────
performance_feedback        ~300    feedback.py → formatted text
learned_rules               ~200    feedback/learned_rules.json
artifact_context            ~200    research_context.py

knowledge_context          ~1500    knowledge_base.py (NEW)
  ├── lessons_learned        200      Top 10 bullet points
  ├── regime_rules           150      Current regime only
  ├── strategy_scores        200      Top 5 strategies, 1 line each
  ├── recent_patterns        400      10 most relevant patterns
  ├── recent_observations    300      Last 3 days, 2 lines each
  └── forward_thesis         250      From latest weekly review

observations_context        ~500    knowledge_base.py (NEW)
  ├── 3-day observation       300      Compressed daily summaries
  └── weekly insight          200      Key thesis + confidence

swing_context               ~300    swing_tracker.py (NEW)
  └── Active positions        300      Symbol, entry, P&L, thesis

market_context              ~300    Market regime, VIX, S&P
market_data                ~2000    Per-stock technicals (10 stocks)
news_context               ~1500    Headlines + sentiment per stock
screener_context            ~500    Why these stocks were selected
─────────────────────────  ──────
TOTAL                      ~7300    Under 8000 budget ✓
```

### Debug Mode Prompt (~4000 tokens total)

```
Section                    Tokens   Change
─────────────────────────  ──────   ───────
performance_feedback        ~300    unchanged
learned_rules               ~200    unchanged
artifact_context            ~200    unchanged
knowledge_context           ~750    halved budget
observations_context        ~250    halved budget
swing_context               ~150    active only, no history
market_context              ~300    unchanged
market_data                 ~800    3 stocks, price+RSI+MACD only
news_context                ~600    3 stocks, yfinance only
screener_context            ~250    abbreviated
─────────────────────────  ──────
TOTAL                      ~3800    ~50% reduction
```

---

## GitHub Storage Estimates

```
Per profile, per year:
  Daily observations:    2KB × 250 days  =    500 KB
  Weekly reviews:        5KB × 52 weeks  =    260 KB
  Monthly reviews:      10KB × 12 months =    120 KB
  Knowledge base:       ~200KB total (capped, overwritten)
  Positions:             1KB × 200 trades =    200 KB
  Archive (compressed):  ~100KB/quarter   =    400 KB
                                           ──────────
  Total per profile:                       ~1.7 MB/year
  Two profiles:                            ~3.4 MB/year

  GitHub repo soft limit: 1 GB
  At this rate: ~300 years before concern
```

### Archival Strategy

Daily observations older than 90 days get compressed:
```
observations/archive/2026-Q1_daily.json.gz   (~50KB for 60 files)
```

Weekly and monthly reviews are never archived (small, always useful).

Knowledge base files are capped:
- patterns_library: max 100 entries (oldest removed)
- lessons_learned: max 50 entries (oldest removed)
- strategy_effectiveness: overwritten each week
- regime_library: overwritten each week

---

## Context Assembly Strategy

The key design principle: **never dump raw JSON into prompts**.

`KnowledgeBase.build_knowledge_context()` returns pre-summarized natural language:

```
ACCUMULATED KNOWLEDGE (47 trading days, 156 trades):
LESSONS: (1) Momentum is our strongest strategy in risk-on, 82% win rate
(2) Mean reversion fails on gap days (3) High VIX (>25) flips strategy
preference (4) Confirmation day adds 15% to win rate on swings ...
CURRENT REGIME RULES (risk_on): Prefer breakout entries, widen targets 20%,
momentum + trend_follow strategies favored, avoid mean reversion.
TOP STRATEGIES: momentum 78% win (best: risk_on), mean_reversion 62%
(best: range_bound), trend_follow 55% (best: trending)
RECENT PATTERNS: gap_and_go 71% win (24 occurrences), RSI_bounce 65% win
(18 occ), volume_breakout 60% win (15 occ)
```

This approach:
- Fits within token budget (measurable, truncatable)
- Gives Claude actionable context, not raw data to parse
- Filters by relevance (current regime, today's watchlist)
- Degrades gracefully (empty if no data yet)

---

## Debug Mode

| Setting | Normal | Debug |
|---------|--------|-------|
| `DEBUG_MODE` | `false` | `true` |
| Stocks analyzed | 10 | 3 |
| Research model | Sonnet | Haiku |
| Web research | 2 stocks | Skipped |
| Knowledge budget | 1500 tok | 750 tok |
| CLI max turns | 5 | 2 |
| News sources | All | yfinance only |
| Market data | Full technicals | Price + RSI + MACD |
| Cost per research | ~$0.02 | ~$0.001 |

Activate: `python -m agent_trader research --debug` or `DEBUG_MODE=true`
