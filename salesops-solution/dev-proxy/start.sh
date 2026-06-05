#!/usr/bin/env bash
# Start the Caddy reverse proxy. Requires sudo only because Caddy binds :443.
# Run setup.sh first (one-time) to install the local CA and edit /etc/hosts.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Sanity checks
if [ ! -f "$HERE/app.solution.zbrain.ai.pem" ] || [ ! -f "$HERE/app.solution.zbrain.ai-key.pem" ]; then
    echo "ERROR: cert files missing in $HERE"
    echo "Regenerate them with: cd $HERE && ~/bin/mkcert app.solution.zbrain.ai"
    exit 1
fi

if ! grep -q "app.solution.zbrain.ai" /etc/hosts; then
    echo "ERROR: app.solution.zbrain.ai is not in /etc/hosts"
    echo "Run $HERE/setup.sh once to fix this."
    exit 1
fi

# Kill any existing caddy instance bound to :443 we started before
sudo pkill -f "caddy run --config $HERE/Caddyfile" 2>/dev/null || true
sleep 0.5

echo "Starting Caddy on :443 with TLS for app.solution.zbrain.ai..."
sudo nohup ~/bin/caddy run --config "$HERE/Caddyfile" > /tmp/caddy-zbrain.out 2>&1 &
CADDY_PID=$!
sleep 1.5

# Health probe
if curl -sk --resolve app.solution.zbrain.ai:443:127.0.0.1 https://app.solution.zbrain.ai/keysight-salesops/ -o /dev/null -w "HTTP %{http_code}\n" 2>&1 | grep -q "HTTP"; then
    echo "Caddy is up. Logs: /tmp/caddy-zbrain.log (Caddy) and /tmp/caddy-zbrain.out (stdout)."
    echo
    echo "Open: https://app.solution.zbrain.ai/keysight-salesops/"
    echo
    echo "Requires: backend on :8000 and Vite dev server on :5173 to be running."
else
    echo "Caddy may not have started cleanly. Check /tmp/caddy-zbrain.out"
    exit 1
fi
