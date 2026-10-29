#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p "$HOME/.config/systemd/user" .runtime
if [[ "$(loginctl show-user "$(id -un)" -p Linger --value)" != yes ]]; then
  loginctl enable-linger "$(id -un)"
fi
install -m 644 scripts/runtime/agent-trader.service "$HOME/.config/systemd/user/agent-trader.service"
systemctl --user daemon-reload
systemctl --user enable --now agent-trader.service
systemctl --user show agent-trader.service -p ActiveState -p SubState -p MainPID -p NRestarts
