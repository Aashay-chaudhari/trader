# Architecture

## System Context

```mermaid
flowchart TB
    User[Operator]
    CLI[Codex CLI]
    Repo[GitHub main]
    Actions[GitHub Actions]
    OpenAI[OpenAI monitor model]
    Data[Market and news providers]
    Alpaca[Alpaca paper account]
    Pages[GitHub Pages]

    User -->|Morning, evening, reviews| CLI
    CLI -->|Writes and pushes| Repo
    Repo -->|Scheduled checkout| Actions
    Actions --> Data
    Actions --> OpenAI
    Actions -->|Approved paper orders| Alpaca
    Actions -->|Runtime commits| Repo
    Repo --> Pages
    Pages --> User
```

## Runtime Components

```mermaid
flowchart LR
    Research[Morning research cache]
    Collector[Data and news agents]
    Gate[Monitor LLM gate]
    Strategies[Strategy ensemble]
    Risk[Risk agent]
    Execution[Execution agent]
    Broker[Alpaca paper]
    Memory[Codex profile memory]
    Dashboard[Dashboard generator]

    Research --> Collector
    Collector --> Gate
    Collector --> Strategies
    Gate --> Strategies
    Strategies --> Risk
    Risk --> Execution
    Execution --> Broker
    Execution --> Memory
    Gate --> Memory
    Memory --> Dashboard
```

## Durable State

```mermaid
flowchart TB
    Profile[data/profiles/codex]
    Cache[cache: morning thesis and watchlist]
    Portfolio[portfolio state, snapshots, positions]
    Journal[journal and trade history]
    Knowledge[lessons, patterns, regimes, effectiveness]
    Observations[daily, weekly, monthly observations]
    Interactions[prompts, transcripts, metadata]
    Voice[voice and evolution artifacts]

    Profile --> Cache
    Profile --> Portfolio
    Profile --> Journal
    Profile --> Knowledge
    Profile --> Observations
    Profile --> Interactions
    Profile --> Voice
```

## Scheduled Workflow

```mermaid
sequenceDiagram
    participant Cron as GitHub schedule
    participant Monitor as Monitor job
    participant APIs as Data and OpenAI
    participant Broker as Alpaca paper
    participant Publish as Publish job
    participant Git as GitHub main
    participant Pages as GitHub Pages

    Cron->>Monitor: Start Codex monitor
    Monitor->>Git: Checkout latest morning state
    Monitor->>APIs: Refresh evidence and evaluate candidates
    Monitor->>Broker: Submit approved paper orders
    Monitor-->>Publish: Upload Codex profile artifact
    Publish->>Git: Checkout current main
    Publish->>Publish: Merge artifact and regenerate docs
    Publish->>Git: Commit runtime state
    Git->>Pages: Deploy docs directory
```

## Local Session Workflow

```mermaid
sequenceDiagram
    participant Operator
    participant Runner as run_both.sh
    participant Codex
    participant Validator
    participant Dashboard
    participant Git

    Operator->>Runner: Run phase
    Runner->>Git: Pull latest main
    Runner->>Codex: Execute phase prompt
    Codex->>Git: Write Codex profile artifacts
    Runner->>Validator: Validate morning anchors when applicable
    Runner->>Dashboard: Regenerate GitHub Pages data
    Runner->>Git: Commit and push HEAD:main
```

## Safety Boundaries

- The monitor can execute only after strategy and risk approval.
- `debug` mode never places orders.
- `paper` mode targets Alpaca paper trading only.
- Morning research is preserved separately from intraday monitor outcomes.
- Local morning validation rejects structurally invalid plans and demotes stale entries.
- Publication and Pages deployment are separate jobs, so failures remain visible.

