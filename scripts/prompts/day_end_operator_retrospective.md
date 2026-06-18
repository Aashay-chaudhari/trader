# Day-End Operator Retrospective Prompt

Start a fresh Codex session in this repository and send this short bootstrap
instruction:

```text
Read scripts/prompts/day_end_operator_retrospective.md completely and run the retrospective for the requested trading date. Use America/New_York time. Do not trade. Do not commit or push unless I explicitly ask.
```

This prompt is designed for the repository at
`C:\Users\aasha\Desktop\trader` / `/mnt/c/Users/aasha/Desktop/trader`.

---

You are auditing one completed trading day for Aasha's `agent-trader` project.
Your job is to explain what actually happened operationally, whether each phase
was triggered, whether morning research was fresh for the date, what decisions
were made, what failed, what was pushed, and what should be fixed next.

Default profile:

```text
DATA_DIR=data/profiles/codex
AGENT_PROFILE=codex
AGENT_LABEL=Codex Strategist
```

If the user does not provide a date, use today's date in America/New_York.

## Safety

- Do not run trading phases.
- Do not run direct API paper monitoring.
- Do not submit broker orders.
- Do not modify strategy state, portfolio state, observations, or knowledge files.
- Do not commit or push unless the user explicitly asks.
- You may create or update a retrospective notes file only if the user asks.
- Respect unrelated dirty worktree changes; do not revert them.

## Inputs To Inspect

Inspect these paths for the requested date:

```text
data/profiles/codex/fresh_start.json
data/profiles/codex/cache/morning_research.json
data/profiles/codex/cache/watchlist.json
data/profiles/codex/cache/local_monitor_context.json
data/profiles/codex/cache/local_monitor_prompt.md
data/profiles/codex/interactions/latest_morning.json
data/profiles/codex/interactions/latest_monitor.json
data/profiles/codex/interactions/latest_evening.json
data/profiles/codex/interactions/<YYYY-MM-DD>/
data/profiles/codex/journal/<YYYY-MM-DD>/
data/profiles/codex/research/
data/profiles/codex/decision_journal/<YYYY-MM-DD>/
data/profiles/codex/observations/daily/
docs/data/profiles/codex/
```

Also inspect:

```bash
git log --oneline --decorate --since="<YYYY-MM-DD> 00:00" --all -- data/profiles/codex docs WEEKBOOK.md
git status --short
```

Use `uv run --extra dev python` for JSON parsing if `python`, `node`, or `jq`
are unavailable.

## Required Questions

Answer all of these explicitly:

1. Did morning research trigger for the requested date?
2. Was the morning cache fresh for the requested date, or stale from a prior day?
3. What watchlist and thesis did monitors use?
4. Which monitor ticks succeeded, failed, or were skipped?
5. Were any trades approved or submitted?
6. Did GitHub Actions produce follow-up execution artifacts?
7. Did evening reflection run and produce learning artifacts?
8. What commits were pushed?
9. What safety constraints were respected?
10. What is the root cause of any bad behavior?

## Freshness Audit

Do not use file mtime alone. Compare:

- `interactions/latest_morning.json` timestamp and prompt path
- presence or absence of `<YYYY-MM-DD>/*_morning_*` files
- `morning_research.json` content, market dates, catalysts, and stated setup
- `watchlist.json`
- monitor summaries referencing the morning thesis
- `fresh_start.json` start date

If morning research was stale, say so plainly and explain why monitors still ran.

## Output Format

Produce a concise but complete retrospective with these sections:

```text
Verdict
Timeline
Morning Research
Monitor Decisions
Failures And Root Cause
Trading / Execution Impact
Artifacts And Commits
What To Fix Next
```

For `Timeline`, use exact ET times where available and call out UTC/local-time
filename confusion when relevant.

For `What To Fix Next`, prioritize actionable repo changes. Include suggested
commands or files to inspect, but do not implement them unless the user asks.
