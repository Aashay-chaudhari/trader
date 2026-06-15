#!/usr/bin/env bash
# Read-only launch audit, except for creating missing empty profile schemas.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

export AGENT_PROFILE="${AGENT_PROFILE:-codex}"
export AGENT_LABEL="${AGENT_LABEL:-Codex Strategist}"
export DATA_DIR="${DATA_DIR:-data/profiles/${AGENT_PROFILE}}"
export MONITOR_RUNTIME="${MONITOR_RUNTIME:-codex_loop}"
export MONITOR_EXECUTION_OWNER="${MONITOR_EXECUTION_OWNER:-github_actions}"
export RUN_MODE="${RUN_MODE:-paper}"

if command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
elif command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.tmp/uv-cache}"
  PYTHON_CMD=(uv run --extra dev python)
else
  echo "FAIL: neither python nor uv is available."
  exit 1
fi

CODEX_BIN="${CODEX_BIN:-}"
if [[ -z "$CODEX_BIN" ]]; then
  for candidate in /c/Users/"${USERNAME:-$USER}"/AppData/Local/OpenAI/Codex/bin/*/codex.exe; do
    if [[ -x "$candidate" ]]; then
      CODEX_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$CODEX_BIN" ]] && command -v codex >/dev/null 2>&1; then
  CODEX_BIN="$(command -v codex)"
fi
if [[ -z "$CODEX_BIN" ]]; then
  echo "FAIL: Codex CLI was not found."
  exit 1
fi

echo "Agent Trader readiness check"
echo "  repo=$PWD"
echo "  branch=$(git branch --show-current)"
echo "  profile=$AGENT_PROFILE"
echo "  data_dir=$DATA_DIR"
echo "  run_mode=$RUN_MODE"
echo "  monitor_runtime=$MONITOR_RUNTIME"
echo "  monitor_execution_owner=$MONITOR_EXECUTION_OWNER"
echo "  codex=$("$CODEX_BIN" --version 2>/dev/null || echo available)"

test "$RUN_MODE" = "paper" || { echo "FAIL: RUN_MODE must be paper for the normal day loop."; exit 1; }
test "$MONITOR_RUNTIME" = "codex_loop" || { echo "FAIL: MONITOR_RUNTIME must be codex_loop."; exit 1; }
test "$MONITOR_EXECUTION_OWNER" = "github_actions" || { echo "FAIL: broker execution must be owned by github_actions."; exit 1; }
test -f data/profiles/codex/fresh_start.json || { echo "FAIL: fresh_start.json is missing."; exit 1; }

"${PYTHON_CMD[@]}" - <<'PY'
import json
import os
from datetime import date
from pathlib import Path

from agent_trader.config.settings import get_settings
from agent_trader.utils.knowledge_base import KnowledgeBase
from agent_trader.utils.profiles import ensure_profile_metadata

settings = get_settings()
ensure_profile_metadata(settings)
KnowledgeBase(os.environ["DATA_DIR"]).ensure_cold_start_schemas()

marker = json.loads(Path(os.environ["DATA_DIR"], "fresh_start.json").read_text(encoding="utf-8"))
date.fromisoformat(marker["start_date"])
print(f"  fresh_start={marker['start_date']}")
PY

"${PYTHON_CMD[@]}" -m agent_trader validate --data-dir "$DATA_DIR"

for workflow in \
  .github/workflows/local-monitor-execution.yml \
  .github/workflows/pages.yml \
  .github/workflows/tests.yml \
  .github/workflows/verify-paper-account.yml; do
  test -s "$workflow" || { echo "FAIL: missing workflow $workflow"; exit 1; }
done

git remote get-url origin >/dev/null
git ls-remote --exit-code origin refs/heads/main >/dev/null

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "WARN: tracked working-tree changes exist; inspect them before the loop commits."
else
  echo "  working_tree=clean"
fi

echo "PASS: local runner, schemas, validation, workflows, and GitHub remote are ready."
echo "EXTERNAL: run the Verify Alpaca Paper Account workflow after changing broker keys."
