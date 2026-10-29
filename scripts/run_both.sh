#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-status}" in
  status|doctor|dashboard|publish) exec .venv/bin/python -m agent_trader "$1" ;;
  *) echo 'The legacy phase runner is retired. Use the scheduled local supervisor or: .venv/bin/python -m agent_trader run'; exit 2 ;;
esac
