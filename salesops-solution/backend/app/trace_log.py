"""Helper to record + broadcast trace events from agent stages."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .models import TraceEvent
from .tracing import bus

_log = logging.getLogger("trace_log")


def _retry_locked(fn, *, op: str, attempts: int = 5, base_delay: float = 0.25):
    """Run `fn()`, retrying on SQLite "database is locked" OperationalError.

    Backoff is exponential (0.25s, 0.5s, 1s, 2s, 4s) so a brief contention
    spike never lands as an errored pipeline. Anything else, including a
    persistent lock past `attempts`, re-raises.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except OperationalError as e:
            msg = str(e).lower()
            if "locked" not in msg and "lock" not in msg:
                raise
            last = e
            if i == attempts - 1:
                break
            time.sleep(base_delay * (2 ** i))
            _log.warning("sqlite %s lock; retry %d/%d", op, i + 1, attempts - 1)
    if last is not None:
        raise last


def _safe_flush(db: Session) -> None:
    _retry_locked(db.flush, op="flush")


def _safe_commit(db: Session) -> None:
    _retry_locked(db.commit, op="commit")


def log_event(
    db: Session,
    pipeline_id: int,
    stage: str,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> TraceEvent:
    ev = TraceEvent(
        pipeline_id=pipeline_id,
        stage=stage,
        kind=kind,
        message=message,
        data=data or {},
        duration_ms=duration_ms,
    )
    db.add(ev)
    _safe_flush(db)
    try:
        payload = {
            "id": ev.id,
            "pipeline_id": pipeline_id,
            "ts": ev.ts.isoformat() if ev.ts else None,
            "stage": stage,
            "kind": kind,
            "message": message,
            "data": data or {},
            "duration_ms": duration_ms,
        }
        bus.publish(pipeline_id, payload)
    except Exception:
        # SSE push is best-effort — never block the pipeline thread on it.
        import logging
        logging.getLogger("trace_log").exception("bus.publish failed; trace event still persisted")
    return ev


@contextmanager
def stage_timer(db: Session, pipeline_id: int, stage: str, label: str):
    log_event(db, pipeline_id, stage, "stage_start", label)
    _safe_commit(db)
    t0 = time.perf_counter()
    # Bind cost-attribution context so any LLM round-trip emitted inside this
    # stage is metered against (pipeline_id, stage). Without this the Cost
    # dashboard reports 0% coverage even when LLMs are firing.
    from .agents.llm import set_cost_context, reset_cost_context
    cost_token = set_cost_context(db=db, pipeline_id=pipeline_id, stage=stage)
    try:
        yield
    except Exception as e:
        dt = int((time.perf_counter() - t0) * 1000)
        # The previous stage's exception probably aborted the SQLAlchemy
        # transaction. Calling log_event/flush again without a rollback would
        # hang forever. Rollback first so we can persist the stage_error.
        try:
            db.rollback()
        except Exception:
            pass
        try:
            log_event(db, pipeline_id, stage, "stage_error", f"{label} failed: {e}", duration_ms=dt)
            _safe_commit(db)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        raise
    else:
        dt = int((time.perf_counter() - t0) * 1000)
        log_event(db, pipeline_id, stage, "stage_end", f"{label} done", duration_ms=dt)
        _safe_commit(db)
        # Verifier hook — declarative invariants for this stage boundary.
        try:
            from .agents.pipeline_verifier import verify_stage_boundary, VerifierHaltError
            from .models import Pipeline as _Pipeline
            pipe = db.get(_Pipeline, pipeline_id)
            if pipe is not None:
                verify_stage_boundary(db, pipe, stage)
        except VerifierHaltError:
            raise
        except Exception:
            # Never let verifier issues abort a pipeline; verify_stage_boundary
            # already logs its own errors via trace events.
            import logging as _log
            _log.getLogger("trace_log").exception("verifier stage_boundary failed for %s", stage)
    finally:
        reset_cost_context(cost_token)
