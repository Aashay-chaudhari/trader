# Daily Operations, Pages, and Evolution

This is the operator runbook for the default local Codex workflow. The active
tracking era starts on `2026-06-15`, as recorded in
`data/profiles/codex/fresh_start.json`.

## Tomorrow Morning

Open a fresh Codex chat in the repository and send:

```text
Read scripts/prompts/codex_day_loop_master.md completely and execute it as the long-running trading-day supervisor. Start now, use America/New_York time, and keep the session alive until all due phases are complete.
```

Codex reads the full prompt from disk, avoiding chat paste and attachment-size
limits. The supervisor will:

```text
Pull main
  -> run scripts/check_readiness.sh
  -> read fresh_start.json
  -> wait until the next due phase in Eastern Time
  -> run the phase through scripts/run_both.sh
  -> regenerate docs/
  -> commit and push main
  -> continue sleeping and checking until the trading day is complete
```

Normal weekday cadence:

```text
08:45 ET        morning research
09:35-15:55 ET  monitor every 30 minutes
16:10 ET        final post-close status check
16:15 ET        evening reflection
```

Starting late is supported. The supervisor first checks whether today's morning
research is valid and current, then catches up only the phases that are due.

Keep the computer awake, connected to the internet, and the Codex chat running.
Closing the app, sleeping Windows, losing connectivity, or ending the chat stops
the local scheduler. Restarting with the same master prompt is safe because it
inspects current files and Git history before resuming.

## Monitor And Broker Handoff

```text
Local Codex monitor
  -> Python gathers Yahoo one-minute prices, timestamps, news, positions, and plans
  -> monitoring stops if a market-hours quote is more than five minutes old
  -> Codex writes local_monitor_decision.json
  -> local runner commits and pushes the decision
  -> Codex Decision Execution starts in GitHub Actions
  -> GitHub injects Alpaca paper secrets
  -> Alpaca IEX latest bid/ask and trade refresh the execution price
  -> execution stops if the Alpaca price is more than two minutes old
  -> deterministic strategy and risk checks run
  -> approved paper orders are submitted
  -> portfolio, journal, analytics, and dashboard are committed
  -> GitHub Pages is deployed
```

The local machine does not need Alpaca secrets. It cannot verify their values.
Run the `Verify Alpaca Paper Account` workflow whenever keys change and before a
new tracking era. A successful check proves that GitHub can reach an empty paper
account with the configured secrets.

Yahoo does not impose one universal 15-minute delay. Its published exchange
table labels U.S. Nasdaq equities as real-time, while various other exchanges,
indices, options, and futures are delayed. `yfinance` is still an unofficial
client with no execution-grade service guarantee, so it is used only for the
local decision snapshot. Alpaca's authenticated IEX feed is the final quote
authority before paper execution. Free paper accounts receive real-time IEX,
which covers one exchange; consolidated all-exchange SIP data requires the paid
Alpaca market-data subscription.

## What Appears On Pages

The dashboard has five primary views:

1. **Overview**: current portfolio value, cash, exposure, P&L, active positions,
   latest run, and direct links to generated reports.
2. **Decisions**: morning recommendations, entries, stops, targets, confidence,
   monitor decisions, strategy signals, risk outcomes, and executed trades.
3. **Knowledge**: daily observations, weekly and monthly reviews, lessons,
   patterns, strategy effectiveness, regime rules, improvement proposals, and
   the latest evolution review.
4. **News**: market regime, market headlines, ticker catalysts, supporting
   articles, source links, and discovery context.
5. **Activity**: Codex prompt/transcript metadata, provider and model telemetry,
   context snapshots, and run artifacts.

After the fresh reset, these views begin empty. They fill in progressively:

```text
Morning -> research, watchlist, sources, plans, interaction log
Monitor -> current decision, signals, risk result, orders, portfolio, journal
Evening -> daily observation, lessons, patterns, proposals, strategist voice
Weekly -> weekly scorecard and consolidated knowledge
Monthly -> monthly performance and knowledge audit
Evolve -> prioritized evolution report and operator recommendations
```

Morning, evening, weekly, monthly, and evolution pushes trigger `Publish
Dashboard`. A ready monitor decision triggers `Codex Decision Execution`, which
publishes again after broker execution so Pages reflects the outcome rather than
only the proposed decision.

## Introspection And Learning

The application has three learning layers:

```text
Daily reflection
  -> observations/daily
  -> lessons, patterns, strategy effectiveness
  -> improvement proposal backlog

Weekly/monthly consolidation
  -> observations/weekly and observations/monthly
  -> prune or strengthen accumulated knowledge

Evolution review
  -> evolution_review.json + EVOLUTION_REPORT.md
  -> classify proposals as implement, prepare, defer, or discard
```

Future research consumes the knowledge store. The strategy agent also loads
`strategy_effectiveness.json` to weight signal confidence. This is how behavior
adapts without bypassing deterministic risk controls.

The app does **not** silently modify source code, prompts, GitHub workflows, or
risk limits. Evolution proposes changes; a separate reviewed coding session
implements worthwhile proposals, runs tests, and commits them. This prevents a
small or noisy sample from autonomously changing production trading behavior.

Recommended cadence:

```text
Evening reflection  once after every market day
Weekly review       Sunday 19:45 ET, or Monday before the open if missed
Monthly review      after the last market day of the month
Evolution review    after weekly and monthly review, at most once per week
Code changes        only when an evolution proposal has enough evidence
```

Running evolution more often is technically possible with
`./scripts/run_both.sh evolve serial`, but it adds little value without new
trades and observations. The master loop intentionally caps it at once per
calendar week unless the operator explicitly requests another pass.

## Readiness Commands

Local launch audit:

```bash
./scripts/check_readiness.sh
```

Full unit suite:

```bash
UV_CACHE_DIR="$PWD/.tmp/uv-cache" uv run --extra dev pytest -s tests/unit -q
```

GitHub-side broker audit:

```text
Actions -> Verify Alpaca Paper Account -> Run workflow
```

The system is ready only when the local readiness check passes, the GitHub test
workflow is green, and the Alpaca verification workflow succeeds for the paper
account intended for the new tracking era.
