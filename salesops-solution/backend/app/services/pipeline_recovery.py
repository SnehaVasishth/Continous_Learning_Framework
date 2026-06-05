"""Zombie pipeline recovery on backend startup.

The worker pool keeps in-flight pipeline state in memory (ThreadPoolExecutor
tasks). When the process is restarted, those tasks vanish but the `pipelines`
and `emails` rows still say `status='running'` / `status='processing'`. The
dashboard then shows stale "in flight" counts forever, throughput percentiles
are wildly inflated by the never-finishing pipelines, and the inbox shows
emails as "processing" that no worker will ever pick up.

This service sweeps those zombies on startup: marks running pipelines as
errored with a clear reason, and resets the associated email back to `new`
so the operator can re-run from the inbox.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Email, Pipeline, TraceEvent

log = logging.getLogger("pipeline_recovery")

# Minimum seconds since the last trace-event activity before we treat a
# `running` pipeline as a zombie. The poller fires sweep_zombies every 10s;
# without this gate we would kill freshly-resumed pipelines (e.g. an AIOA
# PASS that just re-submitted to the pool and is still in Stage 1) mid-flight.
_ZOMBIE_INACTIVITY_GRACE_SECONDS = 120


def sweep_zombies(db: Session) -> dict:
    """Sweep stranded pipeline/email rows from a previous backend run.

    Two cases handled:
      1. Pipelines stuck in `running` — the worker that owned them is gone.
         Mark errored, stamp finished_at, reset the linked email to `new`.
      2. Emails stuck in `processing` whose pipeline is no longer running
         (errored / completed / discarded) — the pipeline finished but the
         email status was never updated, so the inbox shows a phantom
         "processing" forever.

    Idempotent. Returns counts so the caller can log / report.
    """
    now = datetime.now(timezone.utc)
    pipelines_swept = 0
    emails_reset = 0

    running = db.query(Pipeline).filter(Pipeline.status == "running").all()
    grace_cutoff = now - timedelta(seconds=_ZOMBIE_INACTIVITY_GRACE_SECONDS)
    for p in running:
        # Recency gate: only treat as zombie if the pipeline has been silent
        # for the grace window. The AIOA PASS resume path re-submits the
        # pipeline to the worker pool with status=running and the worker
        # then re-walks Stage 1 onwards; without this check the very next
        # 10-second poller tick would kill it mid-Stage-2.
        latest_event = (
            db.query(TraceEvent.ts)
            .filter(TraceEvent.pipeline_id == p.id)
            .order_by(TraceEvent.id.desc())
            .first()
        )
        last_active = latest_event[0] if latest_event else p.started_at
        if last_active is not None:
            # SQLite often returns naive datetimes; normalize to UTC-aware.
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)
            if last_active > grace_cutoff:
                continue
        p.status = "error"
        p.error = (p.error or "process_killed_during_run (backend restarted while pipeline was in flight)")
        p.finished_at = now
        pipelines_swept += 1
        if p.email_id:
            e = db.get(Email, p.email_id)
            if e is not None and e.status == "processing":
                e.status = "new"
                e.pipeline_id = None
                emails_reset += 1

    orphans = (
        db.query(Email)
        .filter(Email.status == "processing")
        .all()
    )
    for e in orphans:
        if e.pipeline_id is None:
            e.status = "new"
            emails_reset += 1
            continue
        p = db.get(Pipeline, e.pipeline_id)
        if p is None or p.status != "running":
            e.status = "new"
            e.pipeline_id = None
            emails_reset += 1

    # Third pass: emails that say "new" but already have a non-running
    # pipeline. The orchestrator failed to write back the terminal email
    # status (older guards only updated when status was "processing"), so
    # the inbox over-counts under "New" and CSRs open items that have
    # already been processed.
    emails_synced = 0
    stale_new = (
        db.query(Email)
        .filter(Email.status == "new")
        .all()
    )
    for e in stale_new:
        latest = (
            db.query(Pipeline)
            .filter(Pipeline.email_id == e.id)
            .order_by(Pipeline.id.desc())
            .first()
        )
        if latest is None:
            continue
        if latest.status == "running":
            continue
        if latest.status in ("awaiting_hitl", "awaiting_one_click"):
            e.status = "awaiting_hitl"
        elif latest.status == "awaiting_aioa":
            e.status = "awaiting_aioa"
        elif latest.status == "completed":
            if (latest.intent or "") in ("kso", "collections", "portal_admin", "brazil_tax"):
                e.status = "redirected"
            else:
                e.status = "processed"
        elif latest.status == "discarded":
            e.status = "discarded"
        elif latest.status == "error":
            # Errored pipelines were never delivered — keep them visible as
            # "new" so an operator can re-run from the inbox.
            continue
        else:
            continue
        emails_synced += 1

    db.commit()
    if pipelines_swept or emails_reset or emails_synced:
        log.warning(
            "pipeline_recovery: swept %d zombie pipeline(s), reset %d email(s) to 'new', synced %d stale email status",
            pipelines_swept, emails_reset, emails_synced,
        )
    return {
        "pipelines_swept": pipelines_swept,
        "emails_reset": emails_reset,
        "emails_synced": emails_synced,
    }
