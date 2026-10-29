#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p .runtime
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# Prefer the native Linux binary over Windows npm shims inherited through WSL PATH.
if [[ -z "${TRADER_CODEX_BIN:-}" ]]; then
  for candidate in /mnt/c/Users/aasha/.vscode/extensions/openai.chatgpt-*/bin/linux-x86_64/codex; do
    if [[ -x "$candidate" ]]; then export TRADER_CODEX_BIN="$candidate"; fi
  done
fi
exec .venv/bin/python -m agent_trader run >> .runtime/launcher.log 2>&1
