"""Thread-level idempotency log for Stage 4 side-effects.

Lookup key:  (thread_root_message_id, action, args_hash)
Value:       the prior result dict the action returned

Why this exists
---------------
Once intake is fully automated, every inbound email triggers its own pipeline.
A single conversation may produce 5–20 pipelines. Without a guard, the same
side-effect (create SF Order, create SF WorkOrder, etc.) would be executed
once per pipeline — duplicates everywhere.

This module gives Stage 4 a tiny, thread-scoped cache. Before each side-effect
call, the orchestrator computes the key from the action name + relevant
arguments + the thread root, and:

  - on cache HIT  → return the prior result, skip the side-effect entirely
  - on cache MISS → execute the action, then record (key, result, ok)

The key is intentionally `(thread_root, action, args_hash)` not `(pipeline_id,
action)` — that's the whole point. Pipelines are per-email; idempotency must
span all pipelines on the same conversation.

When the args differ for the same `(thread_root, action)` (e.g., buyer
corrects qty in a later email), the call to `find_execution()` returns None
because the args_hash changed — Stage 4 then has the option to "amend"
(handled in execute.py) or "escalate to HITL" (when amend isn't safe).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import PipelineExecution

log = logging.getLogger("pipeline_execution_log")


def args_hash(args: dict[str, Any] | list[Any] | tuple) -> str:
    """Stable hash of an action's relevant arguments.

    We sort keys before serializing so equivalent dicts produce identical
    hashes regardless of key order. Non-JSON values are str()'d as a fallback
    so the call never raises."""
    try:
        canonical = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        canonical = str(args)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def find_execution(
    db: Session,
    *,
    thread_root_message_id: str | None,
    action: str,
    args_hash: str,
) -> PipelineExecution | None:
    """Look up a prior successful execution for this (thread, action, args)."""
    if not thread_root_message_id or not action:
        return None
    return (
        db.query(PipelineExecution)
        .filter(
            PipelineExecution.thread_root_message_id == thread_root_message_id,
            PipelineExecution.action == action,
            PipelineExecution.args_hash == args_hash,
            PipelineExecution.succeeded == True,  # noqa: E712 — SQLAlchemy comparison
        )
        .order_by(PipelineExecution.id.desc())
        .first()
    )


def find_executions_for_thread(
    db: Session, *, thread_root_message_id: str | None
) -> list[PipelineExecution]:
    """All recorded executions for a given thread — useful for trace UI / debug."""
    if not thread_root_message_id:
        return []
    return (
        db.query(PipelineExecution)
        .filter(PipelineExecution.thread_root_message_id == thread_root_message_id)
        .order_by(PipelineExecution.id.asc())
        .all()
    )


def record_execution(
    db: Session,
    *,
    thread_root_message_id: str | None,
    action: str,
    args_hash: str,
    pipeline_id: int | None,
    email_id: int | None,
    result: dict[str, Any],
    succeeded: bool,
) -> PipelineExecution:
    """Persist the (key, result) pair so the next pipeline on this thread skips."""
    row = PipelineExecution(
        thread_root_message_id=thread_root_message_id or "",
        action=action,
        args_hash=args_hash,
        pipeline_id=pipeline_id,
        email_id=email_id,
        result=result or {},
        succeeded=bool(succeeded),
    )
    db.add(row)
    db.flush()
    return row


def idempotent_call(
    db: Session,
    *,
    thread_root_message_id: str | None,
    action: str,
    args: dict[str, Any] | list[Any] | tuple,
    pipeline_id: int | None,
    email_id: int | None,
    fn,
) -> dict[str, Any]:
    """Run `fn()` only if no prior execution matches (thread, action, args).

    Returns a dict shaped like:
        {
            "applied": bool,        # whether the action took effect (mirrors fn's return)
            "result":  <fn return>, # the underlying result
            "idempotency": {
                "key": "<hash>",
                "outcome": "hit_skip" | "miss_executed",
                "prior_pipeline_id": int | None,
            }
        }

    The caller is responsible for emitting trace events about the outcome
    (so the trace UI can show "skipped: already executed by pipeline 47").
    """
    h = args_hash(args)

    prior = find_execution(
        db,
        thread_root_message_id=thread_root_message_id,
        action=action,
        args_hash=h,
    )
    if prior is not None:
        log.info(
            "idempotent skip: action=%s thread=%s prior_pipeline=%s",
            action, thread_root_message_id, prior.pipeline_id,
        )
        return {
            "applied": True,
            "result": prior.result,
            "idempotency": {
                "key": h,
                "outcome": "hit_skip",
                "prior_pipeline_id": prior.pipeline_id,
                "prior_execution_id": prior.id,
            },
        }

    try:
        result = fn() or {}
    except Exception as e:
        log.warning("idempotent miss but fn raised: action=%s err=%s", action, e)
        record_execution(
            db,
            thread_root_message_id=thread_root_message_id,
            action=action,
            args_hash=h,
            pipeline_id=pipeline_id,
            email_id=email_id,
            result={"error": f"{type(e).__name__}: {str(e)[:300]}"},
            succeeded=False,
        )
        raise

    succeeded = bool(
        result if not isinstance(result, dict) else result.get("applied", True)
    )
    record_execution(
        db,
        thread_root_message_id=thread_root_message_id,
        action=action,
        args_hash=h,
        pipeline_id=pipeline_id,
        email_id=email_id,
        result=result,
        succeeded=succeeded,
    )

    return {
        "applied": succeeded,
        "result": result,
        "idempotency": {
            "key": h,
            "outcome": "miss_executed",
            "prior_pipeline_id": None,
        },
    }
