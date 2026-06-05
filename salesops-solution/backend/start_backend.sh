#!/usr/bin/env bash
# === v1.1 macOS === macOS launcher mirroring start_backend.bat
set -euo pipefail
cd "$(dirname "$0")"

export OUTBOUND_EMAIL_ENABLED="${OUTBOUND_EMAIL_ENABLED:-0}"
export APP_BASIC_AUTH_USER="${APP_BASIC_AUTH_USER:-keysight}"
export APP_BASIC_AUTH_PASS="${APP_BASIC_AUTH_PASS:-zbrain-demo-2026}"
export APP_BASE_URL="${APP_BASE_URL:-http://localhost:8000}"

# Kill any lingering listener on 8000
PID=$(lsof -ti tcp:8000 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$PID" ]; then kill -9 $PID || true; sleep 1; fi

exec .venv/bin/python -m uvicorn app.main:app --port 8000 --host 127.0.0.1
