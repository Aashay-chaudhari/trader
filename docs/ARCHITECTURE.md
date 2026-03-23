# Architecture

This document is the technical view of the current streamlined system.

## Layered Design

```mermaid
flowchart TB
    subgraph Operator[Operator-driven local layer]
      MORNING[Morning research prompt]
      EVENING[Evening reflection prompt]
      VOICE[Strategist voice prompt]
      WEEKLY[Weekly review prompt]
      MONTHLY[Monthly retrospective prompt]
      EVOLVE[On-demand evolution review]
    end

    subgraph Profiles[Profile storage]
      CLAUDE[data/profiles/claude]
      CODEX[data/profiles/codex]
    end

    subgraph Runtime[Remote runtime layer]
      MONITOR[GitHub Actions monitor]
      DATA[Data + news refresh]
      GATE[Cheap monitor LLM gate]
      STRATEGY[StrategyAgent]
      RISK[RiskAgent]
      EXEC[ExecutionAgent]
      PORT[Portfolio + journal]
      DASH[Dashboard generator]
    end

    MORNING --> CLAUDE
    MORNING --> CODEX
    EVENING --> CLAUDE
    EVENING --> CODEX
    VOICE --> CLAUDE
    VOICE --> CODEX
    WEEKLY --> CLAUDE
    WEEKLY --> CODEX
    MONTHLY --> CLAUDE
    MONTHLY --> CODEX
    EVOLVE --> CLAUDE
    EVOLVE --> CODEX

    CLAUDE --> MONITOR
    CODEX --> MONITOR
    MONITOR --> DATA --> GATE --> STRATEGY --> RISK --> EXEC --> PORT --> DASH
```

## Monitor Decision Path

```mermaid
flowchart LR
    A[Latest pushed morning thesis] --> B[Live prices and fresh news]
    B --> C[Candidate filter]
    C --> D{Near entry, stop, target, or active?}
    D -- no --> E[Skip LLM]
    D -- yes --> F[Cheap monitor model]
    F --> G{ready_to_trade?}
    G -- no --> E
    G -- yes --> H[Strategy votes]
    H --> I[Risk checks]
    I --> J[Paper order]
```

## What Belongs To Which Layer

### Local prompt layer

Owns:
- thesis generation
- operator-facing reflection
- knowledge shaping through prompts
- voice summaries
- evolution reviews

### Python runtime layer

Owns:
- data and news refresh
- candidate narrowing
- strategy logic
- risk logic
- paper execution
- portfolio state
- dashboard generation

## Profile-First Storage

```text
data/profiles/<profile>/
  cache/
  observations/
  knowledge/
  positions/
  voice/
  interactions/
  IMPROVEMENT_PROPOSALS.md
  improvement_proposals.json
  EVOLUTION_REPORT.md
  evolution_review.json
```

The source of truth is profile-first. Top-level legacy `data/...` paths are not part of the supported workflow anymore.

## Dashboard Artifact Flow

```mermaid
flowchart LR
    A[Profile JSON and markdown files] --> B[python -m agent_trader dashboard]
    B --> C[docs/data/dashboard.json]
    B --> D[docs/data/profiles/claude/...]
    B --> E[docs/data/profiles/codex/...]
    B --> F[docs/index.html]
    F --> G[GitHub Pages]
```

Dashboard navigation behavior:

- `Session Log` focuses the `Strategist Interactions` panel
- `Evolution` focuses the proposals/evolution panel
- raw artifacts remain available from links inside those panels

## Why This Architecture Is Stable

- heavy research is kept off the remote scheduler
- remote monitor calls are bounded and cheap
- trading decisions still go through deterministic strategy and risk code
- all durable memory is file-based and inspectable
- operator prompts are archived in interaction logs

## Where Evolution Fits

Evolution is intentionally separate from daily trading.

It reads:
- improvement backlog
- observations
- knowledge
- voice summaries
- portfolio and snapshot history

It writes:
- `evolution_review.json`
- `EVOLUTION_REPORT.md`

That keeps self-improvement deliberate instead of letting the system rewrite itself intraday.

If those files do not exist yet, the dashboard should show an empty evolution state rather than an error.
