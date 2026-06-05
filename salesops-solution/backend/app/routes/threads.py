"""Thread context endpoint — returns the chronological email chain for a pipeline.

Powers the Trace UI's "Thread context" panel. Uses `email_thread.walk_thread`
to assemble the chain (Message-Id / In-Reply-To / References) and exposes:

  - the chronological list of messages
  - the root (primary intent source)
  - any prior pipeline executions on this thread (idempotency log)

Kept in its own router file so concurrent edits to `pipeline.py` don't conflict.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Email, Pipeline
from ..services.email_thread import normalize_subject, walk_thread
from ..services.pipeline_execution_log import find_executions_for_thread

router = APIRouter()


@router.get("/{pipeline_id}")
def get_thread_for_pipeline(pipeline_id: int, db: Session = Depends(get_db)):
    """Return the email thread context for the given pipeline plus any prior
    Stage-4 executions that happened on the same thread (cross-pipeline).
    """
    p = db.get(Pipeline, pipeline_id)
    if not p:
        raise HTTPException(404, "pipeline not found")
    seed_email = db.get(Email, p.email_id) if p.email_id else None
    if not seed_email:
        return {
            "pipeline_id": pipeline_id,
            "thread_root_message_id": None,
            "messages": [],
            "executions": [],
        }

    chain = walk_thread(db, seed_email)
    root = chain[0] if chain else seed_email
    root_msg_id = root.message_id

    executions = find_executions_for_thread(
        db, thread_root_message_id=root_msg_id
    ) if root_msg_id else []

    return {
        "pipeline_id": pipeline_id,
        "thread_root_message_id": root_msg_id,
        "thread_root_pipeline_id": root.pipeline_id,
        "thread_normalized_subject": normalize_subject(root.subject),
        "message_count": len(chain),
        "seed_email_id": seed_email.id,
        "messages": [
            {
                "id": m.id,
                "is_root": (m.id == root.id),
                "position": idx + 1,
                "message_id": m.message_id,
                "in_reply_to": m.in_reply_to,
                "from_address": m.from_address,
                "subject": m.subject,
                "received_at": m.received_at.isoformat() if m.received_at else None,
                "body_preview": (m.body or "")[:600],
                "body_chars": len(m.body or ""),
                "attachments": [
                    {"name": a.get("name"), "type": a.get("type")}
                    for a in (m.attachments or [])
                ],
                "language_hint": m.language_hint,
                "pipeline_id": m.pipeline_id,
            }
            for idx, m in enumerate(chain)
        ],
        "executions": [
            {
                "id": e.id,
                "action": e.action,
                "args_hash": e.args_hash,
                "pipeline_id": e.pipeline_id,
                "email_id": e.email_id,
                "succeeded": e.succeeded,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "result": e.result,
            }
            for e in executions
        ],
    }
