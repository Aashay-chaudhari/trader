# Week 1 Plan

This is the practical checklist for the first real week of Agent Trader operation.

Use this file as the "what do I do next?" guide.

## Goal Of Week 1

The goal is not maximum trading activity.
The goal is to prove that the full operating loop works:

1. local strategist research runs cleanly
2. GitHub Actions monitor reads the latest pushed state
3. the cheap monitor model only makes small execution-gate calls
4. paper trades can be approved and routed correctly
5. evening reflections turn daily activity into durable memory
6. weekly review begins shaping the knowledge base from real evidence

If week 1 does that reliably, the repo becomes a real learning system instead of just a collection of scripts.

## Daily Operating Rhythm

```text
Pre-market:   local CLI research
Market hours: GitHub Actions monitor
After close:  local CLI reflection
Weekend:      weekly review
Month end:    monthly review
```

## The Plan, In Order

### 0. Sunday Preflight

Ideal time: Sunday evening

Run:

```powershell
pytest -q
python -m agent_trader validate --data-dir data/profiles/claude
python -m agent_trader validate --data-dir data/profiles/codex
```

What this contributes to the repo:
- does not change strategy state
- confirms the code, schemas, prompts, and profile layouts are intact before markets open
- reduces the chance that Monday becomes a debugging day

What success looks like:
- tests pass
- both profile validations pass

### 1. Monday Morning Research

Ideal time: `8:15 AM - 8:45 AM ET`

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning parallel
```

What this contributes to the repo:
- creates the first real thesis for each strategist
- writes fresh daily intent into:
  - `data/profiles/claude/cache/morning_research.json`
  - `data/profiles/claude/cache/watchlist.json`
  - `data/profiles/codex/cache/morning_research.json`
  - `data/profiles/codex/cache/watchlist.json`
- archives the exact prompt and readable transcript into `interactions/`
- regenerates `docs/` so GitHub Pages reflects the latest strategist session
- commits and pushes the new state to `main`

Why it matters:
- this is the state the remote monitor will use all day
- without this step, the monitor has nothing current to enforce

### 2. Monday Intraday Monitoring

Ideal time: automatic from `9:30 AM ET` to `4:00 PM ET`

What runs:
- GitHub Actions `Trading Pipeline`
- `monitor` only

What this contributes to the repo:
- reads the pushed morning thesis
- refreshes market/news data
- makes a cheap LLM gate call only when a symbol is actually interesting
- writes updated runtime artifacts, reports, and portfolio state
- republishes the dashboard

Why it matters:
- this is the execution layer
- it tests whether the repo can convert a morning idea into an actual monitored trading decision

What success looks like:
- workflow runs on schedule
- no broken imports or publish failures
- if a setup is near trigger, the gate can approve or reject it cleanly
- if no trade occurs, the system still behaves correctly

### 3. Monday Evening Reflection

Ideal time: `4:20 PM - 5:00 PM ET`

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening parallel
```

What this contributes to the repo:
- writes the day into durable memory
- creates:
  - `observations/daily/obs_YYYY-MM-DD.json`
  - `voice/voice_YYYY-MM-DD.json`
  - `voice/latest_voice.json`
  - updated `knowledge/` files
  - `IMPROVEMENT_PROPOSALS.md`
  - `improvement_proposals.json`
  - new interaction logs for the evening session
- regenerates `docs/`
- commits and pushes everything back to `main`

Why it matters:
- morning creates intent, evening creates learning
- this is where the system starts becoming self-referential instead of stateless

### 4. Tuesday Through Thursday

Repeat the same three-step rhythm:

1. `morning`
2. let `monitor` run remotely
3. `evening`

What this contributes to the repo:
- accumulates multiple independent theses across different market days
- grows observation history
- begins shaping lessons, patterns, and strategy effectiveness with actual evidence
- builds an interaction log library you can review later on GitHub Pages

Why it matters:
- one day gives anecdotes
- three to four days starts giving patterns

### 5. Friday Close Or Sunday Weekly Review

Ideal time: Friday after close or Sunday evening

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh weekly parallel
```

What this contributes to the repo:
- consolidates the week into a weekly observation file for each strategist
- upgrades short-lived daily lessons into more durable knowledge
- updates strategy effectiveness, patterns, and regime memory using a broader sample
- creates weekly interaction logs and refreshes the dashboard again

Why it matters:
- daily reflections are noisy
- weekly review is where the repo starts deciding what is worth remembering

### 6. Optional Evolution Review

Use this only if you want a deliberate improvement pass after a few trading
days or after the weekly review.

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evolve parallel
```

What this contributes to the repo:
- reads the existing improvement backlog instead of inventing a new one from scratch
- creates:
  - `EVOLUTION_REPORT.md`
  - `evolution_review.json`
  - interaction logs for the evolution session
- pushes a clearer operator-facing priority queue back into the repo and dashboard

Why it matters:
- it separates real evidence-backed changes from noise
- it gives you a cleaner place to decide what to implement next

## Command Checklist

### Every trading morning

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning parallel
```

### Every trading evening

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening parallel
```

### End of week

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh weekly parallel
```

### End of month

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh monthly parallel
```

## What To Inspect During Week 1

### In the repo

Look for these to grow naturally:
- `data/profiles/<profile>/cache/`
- `data/profiles/<profile>/observations/daily/`
- `data/profiles/<profile>/knowledge/`
- `data/profiles/<profile>/voice/`
- `data/profiles/<profile>/interactions/`
- `docs/data/`

### In GitHub Actions

Look for:
- scheduled `Trading Pipeline` runs during market hours
- green `publish-results`
- green `deploy-dashboard`

### In GitHub Pages

Look for:
- the latest strategist state
- the `Session Log` button
- the strategist voice summary
- the `Strategist Interactions` section
- updated reports and knowledge summaries

### In Alpaca paper

Look for:
- orders only when monitor/risk/execution all agree
- no obviously duplicated submissions
- positions that match the repo state

## Expected Repo Progression Over The Week

### After Monday morning
- fresh thesis files exist
- interaction logging starts
- dashboard reflects the first real strategist run

### After Monday evening
- the first daily observation exists
- first meaningful lessons or proposals may appear

### By midweek
- the knowledge files begin to contain repeated themes rather than empty stubs
- the dashboard becomes a genuine activity surface rather than a shell

### By the end of the week
- both strategists have a real short history
- prompt archives exist for multiple sessions
- the weekly review has enough evidence to start shaping future behavior

## What Week 1 Gives The Evolution Layer Later

Week 1 does not try to auto-refactor the system.
It prepares the evidence needed for evolution later.

Specifically, it creates:
- real observations
- real improvement proposals
- real strategy effectiveness updates
- real interaction history showing how the strategists reasoned

That means when we come back to the evolution piece, we will not be designing it in a vacuum.
We will have actual data to evolve from.

## Default Rule

If you are unsure what to do next, default to this:

1. run `morning` before market open
2. let Actions handle `monitor`
3. run `evening` after close
4. run `weekly` on the weekend

That is the operating loop.
