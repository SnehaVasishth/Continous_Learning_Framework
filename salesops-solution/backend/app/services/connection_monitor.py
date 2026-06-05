"""Background connection monitor.

Actively re-probes every active enterprise connection (Salesforce, SharePoint)
on a fixed interval, so `last_tested_at` is always recent enough for the
readiness gate. Without this loop the UI banner shows "connection stale" the
moment the readiness freshness window (30 min) expires after the last manual
"Test connection" click, even though the connection itself is perfectly fine.

The probe is the same one the /refresh endpoint runs — a real round-trip to
the provider — so a true outage will still surface as `last_error` and the
banner will (correctly) light up.

Interval is short enough (4 minutes by default) that a missed tick still
leaves plenty of headroom inside the 30-minute freshness window.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from ..db import SessionLocal
from . import salesforce as sf_svc
from . import sharepoint as sp_svc

log = logging.getLogger("connection_monitor")

MONITOR_INTERVAL_SEC = int(os.environ.get("CONNECTION_MONITOR_INTERVAL_SEC", "240"))

_task: asyncio.Task | None = None


def _probe_once() -> dict:
    """Run one probe cycle synchronously. Returns a small status dict for the log."""
    out = {"salesforce": "skipped", "sharepoint": "skipped"}
    db = SessionLocal()
    try:
        sf_conn = sf_svc.get_active_connection(db)
        if sf_conn is not None:
            try:
                sf_svc.refresh_status(db, sf_conn)
                out["salesforce"] = "ok" if not sf_conn.last_error else f"error:{sf_conn.last_error[:80]}"
            except Exception as e:
                out["salesforce"] = f"probe_failed:{type(e).__name__}"
                log.exception("salesforce probe crashed")
        sp_conn = sp_svc.get_active_connection(db)
        if sp_conn is not None:
            try:
                sp_svc.refresh_status(db, sp_conn)
                out["sharepoint"] = "ok" if not sp_conn.last_error else f"error:{sp_conn.last_error[:80]}"
            except Exception as e:
                out["sharepoint"] = f"probe_failed:{type(e).__name__}"
                log.exception("sharepoint probe crashed")
    finally:
        db.close()
    return out


async def _tick() -> None:
    result = await asyncio.to_thread(_probe_once)
    log.info("connection_monitor tick: sf=%s sp=%s at=%s",
             result.get("salesforce"), result.get("sharepoint"),
             datetime.now(timezone.utc).isoformat(timespec="seconds"))


async def _run_forever() -> None:
    log.info("connection monitor started — tick every %ss", MONITOR_INTERVAL_SEC)
    # First tick after a short delay so backend startup isn't blocked by network I/O.
    await asyncio.sleep(5)
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("connection_monitor tick crashed")
        await asyncio.sleep(MONITOR_INTERVAL_SEC)


def start() -> asyncio.Task:
    global _task
    if _task and not _task.done():
        return _task
    _task = asyncio.create_task(_run_forever())
    return _task


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
