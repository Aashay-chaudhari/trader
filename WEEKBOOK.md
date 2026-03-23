# Weekbook

This is the practical operating runbook for Agent Trader during a normal trading week.

## Core Rhythm

- Morning research is local and manual.
- Intraday monitoring is automatic in GitHub Actions.
- Evening reflection is local and manual.
- Weekly and monthly reviews are local and manual.

Use this as the default cadence unless you intentionally override it.

## Daily Timeline

### Morning

Ideal window: `8:15 AM - 8:45 AM ET`

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning parallel
```

What should happen:

- latest `main` is pulled first
- Claude and Codex each research independently
- each profile writes:
  - `cache/morning_research.json`
  - `cache/watchlist.json`
  - `interactions/<date>/..._prompt.md`
  - `interactions/<date>/..._transcript.txt`
  - `interactions/<date>/..._interaction.json`
- the runner commits and pushes automatically

What to check:

- both strategists complete successfully
- push to `main` succeeds
- `data/profiles/claude/cache/morning_research.json` exists
- `data/profiles/codex/cache/morning_research.json` exists

### Intraday

Ideal expectation: do nothing unless you want to inspect logs.

GitHub Actions should run automatically every 30 minutes during market hours.

What monitor does:

- reads latest pushed profile state
- refreshes data and news
- evaluates only a small candidate set
- makes a cheap OpenAI API call when needed
- lets strategy, risk, and execution logic decide trades
- updates portfolio state, journal, and dashboard artifacts

What to check:

- GitHub Actions `Trading Pipeline` shows scheduled or manual runs
- Alpaca paper accounts reflect any submitted paper trades
- GitHub Pages dashboard updates after publish

### Evening

Ideal window: `4:20 PM - 5:00 PM ET`

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening parallel
```

What should happen:

- latest remote state is pulled first
- both strategists review the day
- both strategists then run a short local "voice" check that summarizes their current state honestly
- each profile writes:
  - `observations/daily/obs_YYYY-MM-DD.json`
  - `voice/voice_YYYY-MM-DD.json`
  - `voice/latest_voice.json`
  - updated `knowledge/` files
  - `IMPROVEMENT_PROPOSALS.md`
  - `improvement_proposals.json`
  - interaction prompt/transcript/metadata files for the evening run
- the runner commits and pushes automatically

What to check:

- both strategists complete successfully
- push succeeds
- daily observation files exist for each profile

## Weekly

Ideal window: `Sunday 6:00 PM - 8:00 PM ET`

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh weekly parallel
```

What should happen:

- each strategist reads the week of observations and journals
- each strategist writes:
  - `observations/weekly/week_YYYY-MM-DD.json`
  - updated knowledge files
  - interaction logs for the weekly session
- the runner commits and pushes automatically

## Monthly

Ideal window: `Last trading day after close` or that weekend

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh monthly parallel
```

What should happen:

- each strategist performs a month-level retrospective
- each strategist writes:
  - `observations/monthly/month_YYYY-MM.json`
  - pruned and updated knowledge
  - interaction logs for the monthly session
- the runner commits and pushes automatically

## Optional Evolution Review

Best use: after a few trading days, after a weekly review, or whenever you want
an explicit sober review of what should change next.

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evolve parallel
```

What should happen:

- each strategist reads its own proposal backlog, voice summary, observations,
  knowledge, and portfolio history
- each strategist writes:
  - `EVOLUTION_REPORT.md`
  - `evolution_review.json`
  - interaction logs for the evolution session
- the runner commits and pushes automatically

What to check:

- each profile now has an evolution report
- GitHub Pages `System Intelligence -> Proposals` shows the evolution summary
- the resulting priority queue feels selective, not noisy

## Monday Checklist

### Before market open

1. Pull latest repo state if needed:

```powershell
git pull --ff-only origin main
```

2. Run morning research:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning parallel
```

3. Confirm push succeeded.

4. Open GitHub Actions and keep an eye on the first monitor run around `9:30 AM ET`.

### During the session

1. If you want to sanity-check automation, open:
   - GitHub Actions `Trading Pipeline`
   - GitHub Pages dashboard
   - Alpaca paper accounts

2. If the first scheduled monitor run does not appear when expected, manually dispatch the workflow once.

### After close

1. Run evening reflection:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening parallel
```

2. Verify both daily observation files exist.

## Expected Artifacts By End Of Week 1

Per profile, you should have:

- `cache/morning_research.json`
- `cache/watchlist.json`
- `journal/`
- `observations/daily/`
- `observations/weekly/`
- `knowledge/` with more meaningful content than day 1
- `voice/` with short strategist state summaries
- `interactions/` with readable prompt and transcript archives

On GitHub Pages, you should be able to browse:

- latest portfolio and comparison view
- research and monitor reports
- knowledge summaries
- strategist voice summaries
- local strategist interaction logs

## If Something Looks Wrong

### Morning run fails locally

- rerun `./scripts/run_both.sh morning parallel`
- check CLI authentication
- inspect `data/profiles/<profile>/interactions/..._transcript.txt`
- inspect `.tmp/cli_logs/`

### Monitor does not trade

That is not automatically a bug. It may mean:

- no candidate was near entry
- the monitor gate rejected the setup
- risk validation blocked the trade
- the market was closed

Check:

- GitHub Actions run logs
- dashboard `Monitor / Execution`
- Alpaca paper orders page

### Dashboard looks stale

Check:

- latest monitor run succeeded
- publish step succeeded
- `docs/data/` was updated in the latest commit

## First Principle

Do not over-seed the system.

Let week 1 create the real memory:

- morning theses
- monitor decisions
- evening lessons
- weekly consolidation

That gives you a cleaner learning loop than a heavily preloaded knowledge base.
