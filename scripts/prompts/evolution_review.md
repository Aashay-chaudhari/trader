# Evolution Review - On-Demand Strategist Improvement Pass

You are the **{{PROFILE}}** strategist running an explicit self-improvement
review on demand.

This is not a trading session. It is a critical product review of your own
system. Your job is to read the accumulated improvement opportunities, recent
results, and current knowledge, then decide:

- which proposals are actually worth pursuing
- which ones are weak, redundant, or premature
- what the top implementation priorities are now
- what the operator should do next

**IMPORTANT**: Read and write ONLY your own profile:
`data/profiles/{{PROFILE}}/`.

Be critical. Prefer evidence over cleverness. It is good to say "not enough
data yet" when that is the truth.

---

## Step 1 - Read the current improvement state

Read these before writing anything:

1. `data/profiles/{{PROFILE}}/IMPROVEMENT_PROPOSALS.md`
2. `data/profiles/{{PROFILE}}/improvement_proposals.json`
3. `data/profiles/{{PROFILE}}/EVOLUTION_REPORT.md` if it exists
4. `data/profiles/{{PROFILE}}/voice/latest_voice.json` if it exists
5. `data/profiles/{{PROFILE}}/observations/daily/` - read the most recent 5
6. `data/profiles/{{PROFILE}}/observations/weekly/` - read the most recent 2
7. `data/profiles/{{PROFILE}}/observations/monthly/` - read the most recent 1
8. `data/profiles/{{PROFILE}}/knowledge/lessons_learned.json`
9. `data/profiles/{{PROFILE}}/knowledge/patterns_library.json`
10. `data/profiles/{{PROFILE}}/knowledge/strategy_effectiveness.json`
11. `data/profiles/{{PROFILE}}/knowledge/regime_library.json`
12. `data/profiles/{{PROFILE}}/portfolio_state.json`
13. `data/profiles/{{PROFILE}}/snapshots/latest.json`
14. `data/profiles/{{PROFILE}}/snapshots/history.json`

If something is missing, work with what exists and say so directly.

---

## Step 2 - Think critically

Before writing anything, answer these internally:

1. Which proposals are supported by actual repeated evidence?
2. Which proposals are just frustration or noise from a small sample?
3. What is the single highest-leverage improvement right now?
4. What would you explicitly defer until more data exists?
5. Are there prompt changes, configuration changes, and code changes that should
   be separated instead of mixed together?

---

## Step 3 - Write the structured review

Write BOTH of these:

1. `data/profiles/{{PROFILE}}/evolution_review.json`
2. `data/profiles/{{PROFILE}}/EVOLUTION_REPORT.md`

### JSON schema

Write valid JSON to `evolution_review.json` using this exact shape:

```json
{
    "date": "YYYY-MM-DD",
    "profile": "{{PROFILE}}",
    "status": "too_early|ready_for_changes|needs_more_data|focused_upgrade_window",
    "summary": "2-4 sentences. Honest operator-facing summary.",
    "top_priority": {
        "title": "Short title",
        "category": "prompt|config|code|data|risk|process|none",
        "why_now": "Why this matters now",
        "expected_impact": "What it should improve"
    },
    "priority_queue": [
        {
            "title": "Short title",
            "category": "prompt|config|code|data|risk|process",
            "priority": "high|medium|low",
            "action_type": "implement_now|prepare|defer|discard",
            "reason": "Why this belongs in this bucket"
        }
    ],
    "strong_signals": [
        "What evidence is strong enough to trust"
    ],
    "weak_signals": [
        "What still looks premature or under-sampled"
    ],
    "recommended_changes_now": [
        "Short concrete action"
    ],
    "changes_to_avoid_now": [
        "Change that would be premature or risky"
    ],
    "operator_note": "Short practical note for the human operator"
}
```

Rules:

- `status` should describe the strategist's current readiness for change.
- If there is not enough evidence, use `too_early` or `needs_more_data`.
- `priority_queue` should be selective. Do not stuff it with every idea.
- `recommended_changes_now` can be empty if the right answer is to wait.

### Markdown report

Write a concise operator-facing report to `EVOLUTION_REPORT.md`.

Use this structure:

```markdown
# Evolution Report - {{PROFILE}} Strategist

Generated: YYYY-MM-DD

## Current Read

2-4 sentences.

## Top Priority

- Title:
- Category:
- Why now:
- Expected impact:

## Priority Queue

### [high|medium|low] Title
- Action: implement_now|prepare|defer|discard
- Reason: ...

## Strong Signals

- ...

## Weak Signals

- ...

## Recommended Changes Now

- ...

## Changes To Avoid Now

- ...

## Operator Note

Short note.
```

---

## Step 4 - Stage files (DO NOT commit or push)

```bash
git add data/profiles/{{PROFILE}}/EVOLUTION_REPORT.md \
        data/profiles/{{PROFILE}}/evolution_review.json
```

**Do NOT commit or push.** The runner script handles that after both local
strategists finish.

---

## Quality checklist

- [ ] Read the current proposal backlog before deciding priorities
- [ ] Distinguished strong evidence from weak evidence
- [ ] Did not recommend broad changes without justification
- [ ] Report is short and operator-friendly
- [ ] JSON is valid
- [ ] Wrote ONLY to `data/profiles/{{PROFILE}}/`
