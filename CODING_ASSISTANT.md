# Coding Assistant Guide

## Read Order

1. `CURRENT_STATE.md`
2. `ARCHITECTURE.md`
3. `SYSTEM_GUIDE.md`
4. `WEEKBOOK.md`
5. `README.md`

## Invariants

- The active profile is `data/profiles/codex/`.
- Local reasoning uses the Codex CLI through `scripts/run_both.sh`.
- Intraday monitoring runs in GitHub Actions through OpenAI.
- Python owns strategy, risk, execution, persistence, and dashboard generation.
- Morning thesis data must remain distinct from monitor gate results.
- Never overwrite unrelated user changes in a dirty worktree.
- Generated GitHub Pages data belongs under `docs/`.

## Validation

```powershell
$env:UV_CACHE_DIR="$PWD\.tmp\uv-cache"
uv run --extra dev python -m pytest -q
uv run --extra dev python -m agent_trader validate --data-dir data/profiles/codex
uv run --extra dev python -m agent_trader dashboard
& "C:\Program Files\Git\bin\bash.exe" -n scripts/run_both.sh
```

For workflow changes, also inspect `.github/workflows/trading.yml` for valid dependency names, artifact names, profile paths, and Pages deployment ordering.

## Runtime Notes

- `scripts/run_both.sh` uses `python` when available and otherwise uses `uv run --extra dev python`.
- It prefers the Codex desktop binary under the user's local app directory and falls back to `codex` on PATH.
- It commits generated profile and dashboard changes and pushes the checked-out commit with `HEAD:main`.
- The branch name may differ from `main`; verify `origin/main` after a run.

## Writeback Contract

After meaningful behavior changes:

1. update code and tests
2. run focused tests and profile validation
3. regenerate the dashboard when its inputs or generator changed
4. update `CURRENT_STATE.md`
5. update architecture or operator docs when workflow boundaries changed
6. commit with a focused message

