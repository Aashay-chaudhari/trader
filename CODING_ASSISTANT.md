# Coding Assistant Guide

This file is the shortest practical handoff for any coding assistant working in this repo.

If one assistant hits limits, another assistant should be able to read this file and continue with minimal re-discovery.


## Bridge Between Assistants

Use these files as the handoff contract between Codex, Claude, or any future coding assistant.

### Stable manual

`CODING_ASSISTANT.md` is the stable operator and debugging guide.

Update this file when:

- commands change
- workflow triggers change
- validation steps change
- dashboard/debugging rules change
- repo variables or secrets change

### Current baton

`CURRENT_STATE.md` is the short current-state baton.

Update this file when:

- a meaningful feature lands
- a reliability caveat appears or is removed
- run-mode defaults change
- a deploy or production-readiness fact changes

Keep it short and factual.

### Architecture reference

`SYSTEM_GUIDE.md` explains the deeper design and should change less often.

Update it when:

- the operating model changes
- prompt flow changes
- automation boundaries change
- memory layout changes

### Read order for a fresh assistant

1. `CURRENT_STATE.md`
2. `CODING_ASSISTANT.md`
3. `SYSTEM_GUIDE.md`
4. `README.md`

### Writeback rule

After any meaningful change:

1. update code
2. validate locally
3. update `CURRENT_STATE.md`
4. update `CODING_ASSISTANT.md` if the operating workflow changed
5. update `README.md` or `SYSTEM_GUIDE.md` if the user-facing behavior changed
6. commit and push

This keeps Claude and Codex anchored to the same source of truth instead of relying on stale chat context.

## Project Shape

```text
Local CLI work
  -> writes strategist state into data/profiles/{claude,codex}/
  -> commits to main
  -> regenerates docs/

GitHub Actions monitor
  -> reads latest pushed strategist state
  -> runs cheap OpenAI monitor gate
  -> updates runtime artifacts
  -> republishes GitHub Pages
```

## Core Operating Model

### Local only

Use local CLI subscriptions for:

- `morning`
- `evening`
- `weekly`
- `monthly`
- `evolve`

Command:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh morning parallel
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evening parallel
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh weekly parallel
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh monthly parallel
& "C:\Program Files\Git\bin\bash.exe" ./scripts/run_both.sh evolve parallel
```

### Remote only

GitHub Actions should normally run:

- `monitor` only

Workflow:

- `.github/workflows/trading.yml`

## State Layout

Each strategist owns:

- `data/profiles/claude/`
- `data/profiles/codex/`

Important subfolders:

- `cache/`
  - `morning_research.json`
  - `watchlist.json`
- `observations/`
- `knowledge/`
- `positions/`
- `interactions/`
- `voice/`
- optional evolution outputs:
  - `evolution_review.json`
  - `EVOLUTION_REPORT.md`

## Source Of Truth

### Morning thesis

Frontend decisions must come from:

- `data/profiles/<profile>/cache/morning_research.json`

Not from:

- latest file in `research/`

Reason:

- `research/` may later contain monitor subsets, debug templates, weekly/monthly outputs, etc.

### Monitor outcomes

Frontend gate state should come from:

- latest monitor report / monitor bundle

Keep morning thesis and monitor gate outcomes separate.

## Important Reliability Rules

### Morning plan sanity

`run_both.sh morning ...` now validates morning trade plans before commit.

Validation logic:

- `src/agent_trader/utils/morning_sanity.py`

What it catches:

- entry too far from recent market price
- impossible buy/sell geometry
- suspicious execution-condition price anchors

If morning validation fails, do not commit the artifacts.

### Debug monitor behavior

In debug/template mode, monitor must not silently replace the morning trade plan with synthetic prices.

Relevant file:

- `src/agent_trader/agents/research_agent.py`

## Dashboard / Pages

Generator:

- `src/agent_trader/dashboard/generator.py`

Frontend:

- `src/agent_trader/dashboard/template.html`

Build locally:

```powershell
python -m agent_trader dashboard
```

Important outputs:

- `docs/index.html`
- `docs/data/dashboard.json`
- `docs/data/profiles/<profile>/dashboard.json`

Useful rule:

- if the UI looks wrong, inspect the generated JSON bundle first before assuming frontend logic is wrong

## Validation / Tests

### Fast checks

```powershell
ruff check src tests
pytest -q
python -m agent_trader validate --data-dir data/profiles/claude
python -m agent_trader validate --data-dir data/profiles/codex
python -m agent_trader dashboard
```

### Bash script syntax

```powershell
& "C:\Program Files\Git\bin\bash.exe" -n scripts/run_both.sh
```

### Useful focused tests

```powershell
pytest -q tests/unit/test_dashboard_generator.py
pytest -q tests/unit/test_research_agent.py
pytest -q tests/unit/test_morning_sanity.py
```

## GitHub Actions

### Trigger monitor manually

```powershell
gh workflow run "Trading Pipeline" -f strategists=both -f low_cost_mode=true -f reset_state=false
gh run watch <run_id> --exit-status
```

### Current intended posture

- local CLI phases do the heavy thinking
- remote monitor is cheap and API-only

### Remote run mode toggle

```powershell
gh variable set MONITOR_RUN_MODE --body debug
gh variable set MONITOR_RUN_MODE --body paper
```

## Environment / Secrets

### Local `.env`

Important keys:

- `RUN_MODE`
- `OPENAI_API_KEY`
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`

### GitHub repo variables / secrets

Important:

- `MONITOR_RUN_MODE`
- `OPENAI_API_KEY`
- `ALPACA_API_KEY_CLAUDE`
- `ALPACA_SECRET_KEY_CLAUDE`
- `ALPACA_API_KEY_CODEX`
- `ALPACA_SECRET_KEY_CODEX`

## How To Debug “Why Is The Dashboard Wrong?”

1. Inspect `docs/data/dashboard.json`
2. Inspect `docs/data/profiles/<profile>/dashboard.json`
3. Inspect:
   - `research`
   - `monitor`
   - `context.prompt_sections.news_inputs`
4. Check whether the wrong data source is being shown:
   - morning cache
   - monitor report
   - latest context
5. Rebuild locally:

```powershell
python -m agent_trader dashboard
```

6. If local is right but live Pages is stale:

```powershell
gh workflow run "Trading Pipeline" -f strategists=both -f low_cost_mode=true -f reset_state=false
```

## How To Debug “Why Is News Empty?”

Morning CLI runs often store evidence in:

- `stocks.<SYMBOL>.supporting_articles`

The dashboard news panels prefer:

- `context.prompt_sections.news_inputs`

So if news looks empty:

1. check `supporting_articles` in morning cache
2. check `news_inputs` in dashboard bundle
3. if needed, backfill `news_inputs` from `supporting_articles` in the generator

## Good Files To Read First

If picking up cold, start here:

1. `CURRENT_STATE.md`
2. `SYSTEM_GUIDE.md`
3. `WEEKBOOK.md`
4. `scripts/run_both.sh`
5. `src/agent_trader/dashboard/generator.py`
6. `src/agent_trader/agents/research_agent.py`

## Safe Commit Pattern

After meaningful changes:

```powershell
ruff check src tests
pytest -q
python -m agent_trader dashboard
git status --short
git add <changed files>
git commit -m "<scope> <change>"
git push origin main
```

If frontend needs live refresh immediately:

```powershell
gh workflow run "Trading Pipeline" -f strategists=both -f low_cost_mode=true -f reset_state=false
```

## Final Handoff Rule

When handing off to another assistant, always include:

- what changed
- what was validated
- current commit hash
- whether local and remote are synced
- any remaining caveat that could affect tomorrow's market run
