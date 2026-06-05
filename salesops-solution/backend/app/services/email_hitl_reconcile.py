"""Email/HITL status reconciliation sweeper.

Closes the gap between ``Email.status == 'awaiting_hitl'`` and the
``HitlTask`` ledger. Two failure modes can drift the two stores apart:

  a) A HitlTask was resolved (operator cleared it) but the inbound Email
     row was not synced back, leaving the inbox showing ``awaiting_hitl``
     forever even though the case is done.
  b) Email.status was written to ``awaiting_hitl`` eagerly but the
     subsequent HitlTask insert failed, leaving the email stranded with
     no live task to resolve.

The reconcile pass is idempotent: re-running it on a clean state is a
no-op. It only ever forwards the Email row; the HitlTask ledger is the
source of truth.

Wired into the FastAPI lifespan (after baselines backfill) and the
email poller tick (same cadence as ``email_sweeper.sweep_stale_new``).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models import Email, HitlTask, Pipeline

log = logging.getLogger("email_hitl_reconcile")


def reconcile_awaiting_hitl(db: Session) -> int:
    """Forward stranded ``awaiting_hitl`` emails to a real status.

    For every Email row with status ``awaiting_hitl`` whose latest
    pipeline has no pending HitlTask:

      - Pipeline.status == 'completed'      -> Email.status = 'processed'
      - Pipeline.status == 'awaiting_aioa'  -> Email.status = 'awaiting_aioa'
      - Pipeline.status == 'awaiting_hitl'  -> leave as-is (the pipeline
        itself is parked on HITL; the missing task is a genuine bug the
        operator surfaces via a separate alert, not something this sweep
        should paper over)
      - everything else                     -> leave as-is

    Returns the number of Email rows reconciled.
    """
    rows = db.query(Email).filter(Email.status == "awaiting_hitl").all()
    if not rows:
        return 0

    reconciled = 0
    for email in rows:
        pipe: Pipeline | None = None
        if email.pipeline_id is not None:
            pipe = db.query(Pipeline).filter(Pipeline.id == email.pipeline_id).first()
        if pipe is None:
            # Fall back: try the most recent pipeline for this email id.
            pipe = (
                db.query(Pipeline)
                .filter(Pipeline.email_id == email.id)
                .order_by(Pipeline.id.desc())
                .first()
            )
        if pipe is None:
            # Email is awaiting_hitl with no pipeline anchor at all. The
            # most likely cause is an upstream write that set the status
            # eagerly while pipeline creation failed. There is no live
            # work tied to this email; forward it to ``processed`` so
            # it stops inflating the HITL backlog. The original message
            # remains queryable for audit either way.
            email.status = "processed"
            reconciled += 1
            continue

        pending = (
            db.query(HitlTask)
            .filter(HitlTask.pipeline_id == pipe.id)
            .filter(HitlTask.status == "pending")
            .count()
        )
        if pending > 0:
            # Live HITL task exists; the email status is correct.
            continue

        new_status: str | None = None
        if pipe.status == "completed":
            new_status = "processed"
        elif pipe.status == "awaiting_aioa":
            new_status = "awaiting_aioa"
        # Any other pipeline.status (running, awaiting_hitl, error,
        # rejected, discarded) is left alone so we do not mask a real
        # backend bug behind a sweep.

        if new_status and new_status != email.status:
            email.status = new_status
            reconciled += 1

    if reconciled > 0:
        db.commit()
        log.info("email_hitl_reconcile: forwarded %s stranded awaiting_hitl emails", reconciled)
    return reconciled
