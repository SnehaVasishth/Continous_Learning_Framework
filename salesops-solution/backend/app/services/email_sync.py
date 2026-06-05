"""Background poller + in-process SSE event bus.

Runs one asyncio task that wakes every POLL_TICK_SEC, looks for accounts whose
sync window has elapsed, and fetches new mail in a thread (IMAP is blocking).
Each new batch fans out a `new_emails` event on the bus so the UI can refresh
without a full poll.

Cloud notes:
- Single-process deployment is fine for the demo. For multi-replica deployments
  promote the bus to Redis pub/sub or a managed queue and lock account polling
  with a short TTL key so two replicas don't race the same mailbox.
- Outbound TCP 993 is the only network requirement.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from ..db import SessionLocal
from ..models import EmailAccount
from . import email_hitl_reconcile, email_sweeper, imap_client

log = logging.getLogger("email_sync")

POLL_TICK_SEC = 10

# Stale-inbox sweep cadence. The IMAP poller runs every POLL_TICK_SEC; the
# sweep only needs to fire occasionally (newly-aged mail crosses the
# threshold over hours, not seconds). 15 minutes keeps the Dashboard fresh
# without churning the DB.
STALE_SWEEP_INTERVAL_SEC = 15 * 60
_last_stale_sweep_at: datetime | None = None

_subscribers: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


async def _broadcast(event: dict[str, Any]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def broadcast_threadsafe(event: dict[str, Any]) -> None:
    """Callable from any thread; schedules broadcast on the poller's loop."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(event), _loop)


def _due(account: EmailAccount, now: datetime) -> bool:
    if not account.last_synced_at:
        return True
    interval = max(15, int(account.sync_interval_sec or 60))
    # SQLite stores last_synced_at tz-naive; coerce both sides to naive for compare.
    last = account.last_synced_at
    n = now.replace(tzinfo=None) if now.tzinfo is not None else now
    if last.tzinfo is not None:
        last = last.replace(tzinfo=None)
    return (n - last).total_seconds() >= interval


def _sync_account_blocking(account_id: int) -> tuple[int, list[int], str | None]:
    db = SessionLocal()
    try:
        account = db.get(EmailAccount, account_id)
        if not account or not account.is_active:
            return account_id, [], None
        try:
            new_ids = imap_client.fetch_new(account, db)
            return account_id, new_ids, None
        except Exception as e:
            account.last_error = f"{type(e).__name__}: {e}"[:500]
            account.last_error_at = datetime.now(timezone.utc)
            db.commit()
            log.warning("imap sync failed for %s: %s", account.email_address, e)
            return account_id, [], str(e)
    finally:
        db.close()


async def sync_one(account_id: int) -> tuple[list[int], str | None]:
    """Manual refresh — runs the same blocking IMAP fetch in a thread."""
    _, new_ids, err = await asyncio.to_thread(_sync_account_blocking, account_id)
    if new_ids:
        await _broadcast({"type": "new_emails", "account_id": account_id, "ids": new_ids})
    await _broadcast({"type": "sync_done", "account_id": account_id, "count": len(new_ids), "error": err})
    return new_ids, err


async def _tick() -> None:
    db = SessionLocal()
    try:
        active = db.query(EmailAccount).filter_by(is_active=True).all()
        now = datetime.now(timezone.utc)
        due_ids = [a.id for a in active if _due(a, now)]
    finally:
        db.close()

    for account_id in due_ids:
        try:
            _, new_ids, err = await asyncio.to_thread(_sync_account_blocking, account_id)
            if new_ids:
                await _broadcast({"type": "new_emails", "account_id": account_id, "ids": new_ids})
            if err:
                await _broadcast({"type": "sync_error", "account_id": account_id, "error": err})
        except Exception:
            log.exception("tick failed for account %s", account_id)

    # Periodic stale-inbox sweep. Runs at most once per
    # STALE_SWEEP_INTERVAL_SEC regardless of how often the IMAP poller
    # ticks, so the Dashboard "New" tile keeps shedding aged-out mail
    # without manual intervention.
    global _last_stale_sweep_at
    now_ts = datetime.now(timezone.utc)
    if (
        _last_stale_sweep_at is None
        or (now_ts - _last_stale_sweep_at).total_seconds() >= STALE_SWEEP_INTERVAL_SEC
    ):
        _last_stale_sweep_at = now_ts
        try:
            await asyncio.to_thread(_sweep_stale_inbox_blocking)
        except Exception:
            log.exception("stale-inbox sweep crashed")

    # Email/HITL status reconciliation runs every tick. It is cheap
    # (a small filtered query) and idempotent, so we do not gate it
    # behind STALE_SWEEP_INTERVAL_SEC: any stranded awaiting_hitl email
    # gets forwarded within one POLL_TICK_SEC.
    try:
        await asyncio.to_thread(_reconcile_email_hitl_blocking)
    except Exception:
        log.exception("email_hitl_reconcile tick crashed")

    # Zombie + errored-pipeline recovery runs every tick. Pipelines stuck
    # in `running` after a worker crash, or marked `error` from a
    # transient failure, get their associated email reset to `new` so the
    # poller re-ingests them automatically. This is the "errors retry on
    # their own behind the scenes" contract: the operator does not have
    # to visit an Errors page to retry; the system recovers itself.
    try:
        await asyncio.to_thread(_recover_pipeline_zombies_blocking)
    except Exception:
        log.exception("pipeline zombie recovery tick crashed")


def _sweep_stale_inbox_blocking() -> int:
    db = SessionLocal()
    try:
        return email_sweeper.sweep_stale_new(db)
    finally:
        db.close()


def _reconcile_email_hitl_blocking() -> int:
    db = SessionLocal()
    try:
        return email_hitl_reconcile.reconcile_awaiting_hitl(db)
    finally:
        db.close()


def _recover_pipeline_zombies_blocking() -> dict:
    from . import pipeline_recovery
    db = SessionLocal()
    try:
        return pipeline_recovery.sweep_zombies(db)
    finally:
        db.close()


async def _run_forever() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    log.info("email poller started — tick every %ss", POLL_TICK_SEC)
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("poller tick crashed")
        await asyncio.sleep(POLL_TICK_SEC)


_task: asyncio.Task | None = None


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


# Note: do NOT switch to WindowsSelectorEventLoopPolicy here — the Selector loop
# on Windows doesn't support asyncio.create_subprocess_exec, which the LLM SDK
# uses to spawn the Claude Code transport. Stick with the default Proactor loop.
