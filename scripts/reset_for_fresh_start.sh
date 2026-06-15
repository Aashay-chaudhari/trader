#!/usr/bin/env bash
# Delete generated Codex application state and publish an empty dated baseline.
# Usage: ./scripts/reset_for_fresh_start.sh YYYY-MM-DD RESET

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

START_DATE="${1:?Usage: $0 YYYY-MM-DD RESET}"
CONFIRMATION="${2:-}"

if [[ "$CONFIRMATION" != "RESET" ]]; then
  echo "Refusing to reset. Pass the literal confirmation RESET as the second argument."
  exit 1
fi

if [[ ! "$START_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Error: start date must use YYYY-MM-DD."
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: commit or stash tracked changes before running a fresh-start reset."
  exit 1
fi

git pull --ff-only origin main

export AGENT_PROFILE="${AGENT_PROFILE:-codex}"
export AGENT_LABEL="${AGENT_LABEL:-Codex Strategist}"
export DATA_DIR="${DATA_DIR:-data/profiles/${AGENT_PROFILE}}"

if command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
elif command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.tmp/uv-cache}"
  PYTHON_CMD=(uv run --extra dev python)
else
  echo "Error: neither python nor uv is available."
  exit 1
fi

push_main() {
  if git push origin HEAD:main; then
    return 0
  fi

  local windows_git="/mnt/c/Program Files/Git/cmd/git.exe"
  if [[ -x "$windows_git" ]]; then
    echo "Retrying push with Windows Git Credential Manager..."
    GCM_INTERACTIVE=Never "$windows_git" push origin HEAD:main
    return 0
  fi

  return 1
}

echo "Resetting generated application state for a fresh start on ${START_DATE}..."
"${PYTHON_CMD[@]}" -m agent_trader reset \
  --data-dir "$DATA_DIR" \
  --docs \
  --fresh-start-date "$START_DATE"
"${PYTHON_CMD[@]}" -m agent_trader dashboard

git add -A "$DATA_DIR" docs/
if git diff --staged --quiet; then
  echo "No generated state changed."
  exit 0
fi

git commit -m "[fresh-start] ${START_DATE} reset application state"
push_main

echo "Fresh application baseline pushed. Alpaca paper-account replacement is separate."
