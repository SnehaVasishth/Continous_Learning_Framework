#!/usr/bin/env bash
# One-time setup for the local app.solution.zbrain.ai HTTPS reverse proxy.
# Idempotent. Re-run safe.
#
# What this does:
#   1. Installs the mkcert local CA into the system trust store (one-time
#      prompt). Required for the browser lock icon to be valid.
#   2. Adds 127.0.0.1 app.solution.zbrain.ai to /etc/hosts (idempotent).
#
# Both steps require sudo. The script prompts once and runs to completion.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/2] Installing mkcert local CA into the system trust store..."
# mkcert -install needs sudo because it writes to /Library/Keychains/System.keychain
sudo -v
~/bin/mkcert -install

echo
echo "[2/2] Adding 127.0.0.1 app.solution.zbrain.ai to /etc/hosts..."
if grep -q "app.solution.zbrain.ai" /etc/hosts; then
    echo "  already present in /etc/hosts, skipping"
else
    echo "127.0.0.1 app.solution.zbrain.ai" | sudo tee -a /etc/hosts > /dev/null
    echo "  added"
fi

echo
echo "Setup complete. Start the proxy with:"
echo "    bash $HERE/start.sh"
echo
echo "Then open https://app.solution.zbrain.ai/keysight-salesops/"
