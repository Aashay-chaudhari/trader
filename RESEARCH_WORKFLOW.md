# Research → reviewed knowledge → daily decisions

The initial ten research mornings emphasize discovery and parallel testing.
Ordinary execution risk, account budgets and the paper-only boundary stay fixed.

1. Initial bootstrap: `.venv/bin/python -m agent_trader explore` performs a bounded
   research pass, independent review and knowledge handoff. It never authorizes orders.
2. Historical screening: twelve fixed combinations (six rule families × intraday /
   five-session swing horizon), 30 liquid instruments, approximately 420 calendar
   days of free IEX bars. The original dataset, split and hash are frozen locally.
   All trials and development/holdout results remain visible, including failures.
3. At 08:15 ET the morning brief receives reviewed knowledge, current structured
   observations, event research, contrary evidence and linked forward experiments.
4. From 08:35 to 09:15, during the first ten research mornings, a stronger model
   explores diverse hypotheses with up to twelve searches. A separate review uses
   up to four searches to inspect cited sources and methods. Missing verification
   means needs-work. A newly reviewed premarket batch requests a refreshed brief.
5. Up to six shadow challengers per equity branch compare the same forward quote
   observations. Up to sixteen extra research shadow plans can broaden that sample;
   they never enter the broker's executable plan queue or claim allocated returns.
6. Daily reviews inspect preliminary evidence and failures. Forward promotion keeps
   its twenty-session / thirty-sample floor, requires positive net results, applies
   a conservative trial-family penalty and uses doubling-session review checkpoints.
   Historical screening cannot satisfy these gates. Options remain research only.

Knowledge cards retain claim, mechanism, falsification, source links, free-data
feasibility, review reason, screen references and experiment references. Review
history is append-only in memory; the current catalogue is persistent. Cards need
re-review after thirty days. The morning prompt explicitly retrieves this catalogue,
not just whatever the model remembers from yesterday's session.

Evidence labels have limited meanings:

| Label | Meaning |
| --- | --- |
| Draft | Not eligible for the morning knowledge handoff |
| Reviewed hypothesis | Sources/methods reviewed; suitable for investigation, profitability unproven |
| Historical screen | Fixed exploratory comparison with stated limitations; inspected holdout is not pristine future evidence |
| Forward-validated filter | A linked executable filter passed its recorded forward gate; applies only within that tested scope |
| Rolled back / rejected / needs work | Preserved counterevidence; never silently promoted to trusted knowledge |

The strategy dashboard displays research, all twelve screens, known limitations,
parallel experiments and observed progress. Account-wide weekly allowance and the
24-call core daily ceiling remain, including reserved review capacity. A separate
bounded background queue permits up to 96 attempts per day across evidence-linked
questions and independent reviews. Both queues stop admitting model work at 80%
weekly account usage. They do not buy capacity, require trades, or relax risk gates.

Background work is keyed to retained evidence, with limited revisions and retries;
unchanged evidence is not repeatedly analyzed to fill a quota. Accepted findings
carry sources, uncertainty and expiry into later briefs. The planning audit found
23 historical research invocations with empty plan arrays, so adding model calls
alone cannot be presented as a repair for dropped plans. New fresh-open priority
and input-quality fixes require future-session observations to establish benefit.

## Source quality, input readiness and daily audit

A reviewer must attest independent readable-primary-content checks, name the actual
checked URLs and hold partial/blocked checks. Source approval does not validate a
mechanism's transfer to our horizon, executable liquidity or profitability. Current
catalogue states may change after rechecks; original reports remain historical.
The October 31 recheck left four cards reviewed for testing and thirteen held.

Research receives exact daily inputs, feed-specific completed-minute context when
available, and exact existing experiment/parent definitions. It focuses company
verification on a bounded shortlist. Missing event timing remains unknown; IEX is
the approved free experiment feed, never a consolidated-price substitute.

Full input/output artifacts, measured usage, reported blockers and verification
states feed a deterministic daily quality audit. Retrospective and maintenance get
that audit in complete JSON; operational proposals persist in a development backlog.
The audit itself grants no trade, promotion or kernel-editing authority. Offline
feature replays remain separate from recorded forward observations.

## Continuing observation-led discovery (October 31 upgrade)

The ten mornings are an initial cadence, not an end to discovery. At08:35 the role
continues when new observation IDs exist, reviewed cards expire, or on Monday.
Fifteen-minute quote captures, market packets and later test outcomes support new
questions. Every local conjecture names its actual recorded IDs, alternatives and a
prediction; external factual claims still require independently checked sources.

A separate adaptive observation lab can test supported numeric conjunctions without
waiting for executable plans. Reviewed contracts bind only future actual sessions,
retain failed/missing opportunities and compare cash and unconditional same-symbol
observations. Results feed morning knowledge and retrospectives; no observation
result automatically promotes an executable strategy. Unsupported event features
remain explicit development work. ADAPTIVE_ENGINE_AUDIT.md specifies the full path.
