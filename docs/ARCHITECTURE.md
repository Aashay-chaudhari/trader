# Architecture

The canonical architecture reference is [`ARCHITECTURE.md`](../ARCHITECTURE.md)
at the repository root.

## Published System View

```text
Operator
  |
  v
Local Codex runner
  |
  +-- morning research
  +-- intraday monitor gate
  +-- evening / weekly / monthly / evolution reviews
  |
  +-- pushes monitor decision to main
  |       |
  |       v
  |     GitHub Actions -> strategy -> risk -> Alpaca paper execution
  |
  v
data/profiles/codex
  |
  +-- journal, research, context, interactions, portfolio, knowledge
  |
  v
Dashboard generator -> docs/ -> Publish Dashboard -> GitHub Pages

Optional:
  GitHub Actions API monitor
    enabled only by MONITOR_RUNTIME=github_actions_api
```

The active system has one profile, `codex`. Morning research and the intraday
reasoning gate are local by default. Python still owns deterministic strategy,
risk, execution, persistence, and dashboard generation. GitHub Actions owns the
default Alpaca paper submission handoff because repository secrets exist there;
the OpenAI API monitor remains a separate opt-in path.

Fresh starts are deliberately split: the application reset clears generated
repository state and writes `fresh_start.json`; a truly clean brokerage history
requires a newly created Alpaca paper account and replacement GitHub secrets.
