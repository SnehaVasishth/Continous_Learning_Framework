@echo off
set OUTBOUND_EMAIL_ENABLED=0
set APP_BASIC_AUTH_USER=keysight
set APP_BASIC_AUTH_PASS=zbrain-demo-2026
python -m uvicorn app.main:app --port 8000 --host 127.0.0.1
