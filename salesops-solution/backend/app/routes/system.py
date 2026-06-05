"""System-wide endpoints — readiness, build info, health, verification rollup."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.readiness import check_readiness

router = APIRouter()


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    """Return the live system-readiness report.

    The frontend banner polls this every ~10 seconds. The pipeline ingress
    consults the same logic synchronously and refuses with HTTP 412 when
    `ok=false`, so the banner and the gate stay in sync."""
    return check_readiness(db).to_dict()


@router.get("/verification/rollup")
def verification_rollup(db: Session = Depends(get_db), window_days: int = 7):
    """Aggregate verification results across pipelines in the window.

    Counts blocker / warn / audit failures per rule, plus pass totals, so the
    Dashboard Verification tile can show 'X invariants violated in the last
    Y days, top firing rules:'."""
    from ..models import Pipeline, TraceEvent
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    rows = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "verification")
        .filter(TraceEvent.kind == "checked")
        .filter(TraceEvent.ts >= cutoff)
        .all()
    )
    rule_counts: Counter = Counter()
    pass_counts: Counter = Counter()
    block_pipes: set[int] = set()
    warn_pipes: set[int] = set()
    audit_pipes: set[int] = set()
    halted_pipes = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.stage == "verification")
        .filter(TraceEvent.kind == "halted")
        .filter(TraceEvent.ts >= cutoff)
        .distinct()
        .all()
    )
    halted_pipe_ids = {r[0] for r in halted_pipes if r[0]}
    for ev in rows:
        data = ev.data or {}
        for r in (data.get("results") or []):
            key = r.get("rule_key")
            if not key:
                continue
            verdict = r.get("verdict")
            severity = r.get("severity")
            mode = r.get("mode")
            if verdict == "pass":
                pass_counts[key] += 1
            elif verdict in ("fail", "error"):
                rule_counts[key] += 1
                if severity == "block" and mode == "active":
                    block_pipes.add(ev.pipeline_id)
                elif severity == "warn" and mode == "active":
                    warn_pipes.add(ev.pipeline_id)
                else:
                    audit_pipes.add(ev.pipeline_id)
    top_failing = [
        {"rule_key": k, "fail_count": v, "pass_count": pass_counts.get(k, 0)}
        for k, v in rule_counts.most_common(10)
    ]
    return {
        "window_days": window_days,
        "total_evaluations": sum(pass_counts.values()) + sum(rule_counts.values()),
        "pass_count": sum(pass_counts.values()),
        "fail_count": sum(rule_counts.values()),
        "pipelines_with_block": len(block_pipes),
        "pipelines_with_warn": len(warn_pipes),
        "pipelines_with_audit_only": len(audit_pipes - block_pipes - warn_pipes),
        "halted_pipelines": list(halted_pipe_ids),
        "top_failing_rules": top_failing,
    }
