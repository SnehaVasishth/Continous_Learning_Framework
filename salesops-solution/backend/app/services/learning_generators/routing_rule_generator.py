"""Routing-rule candidate generator.

Surfaces a candidate when CSRs systematically reassign HITL tasks from the
queue Stage 3.4 originally routed to. The hypothesis is that the
track-classifier owner rule is wrong for that (intent, segment) combination.

Signal: HitlTask rows where the most recent `assignee_queue` differs from
the queue stamped on the originating Case (case_state.owner_label). If
N reassignments share the same `(intent, from_queue, to_queue)` triple,
propose a routing-rule update so future cases of that shape go to the new
queue.

Apply path: edits the `track_classifier` KB rule body to add or modify a
routing entry for the matching (intent, segment) key. Body shape is
intentionally a list of routing entries so additions are append-friendly.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...models import HitlTask, LearningOpportunity, Pipeline


def _anchor(db: Session, segment: str | None) -> int | None:
    try:
        from . import resolve_baseline_id_for_segment
        return resolve_baseline_id_for_segment(db, segment)
    except Exception:
        return None


_LOOKBACK_DAYS = 30
_MIN_REASSIGNMENTS = 3


def _fingerprint(intent: str, from_queue: str, to_queue: str) -> str:
    return f"routing_rule:{intent}:{from_queue}->{to_queue}"


def generate(db: Session) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    tasks = (
        db.query(HitlTask)
        .filter(HitlTask.assigned_at.isnot(None))
        .filter(HitlTask.created_at >= cutoff)
        .all()
    )
    if not tasks:
        return []

    pipe_ids = sorted({t.pipeline_id for t in tasks if t.pipeline_id is not None})
    pipes = {p.id: p for p in db.query(Pipeline).filter(Pipeline.id.in_(pipe_ids)).all()} if pipe_ids else {}

    reassignment_triples: list[tuple[str, str, str, int]] = []  # (intent, from_q, to_q, pipeline_id)
    for t in tasks:
        if not t.pipeline_id or not t.assignee_queue:
            continue
        p = pipes.get(t.pipeline_id)
        if not p or not p.intent:
            continue
        # The originating "from queue" comes from the decision block stamped
        # by Stage 3.4 onto the pipeline.
        decision = p.decision if isinstance(p.decision, dict) else {}
        owner_block = (decision or {}).get("owner") or {}
        from_q = owner_block.get("owner_label") or owner_block.get("salesforce_queue_label")
        if not from_q or from_q == t.assignee_queue:
            continue
        reassignment_triples.append((str(p.intent), str(from_q), str(t.assignee_queue), int(p.id)))

    if not reassignment_triples:
        return []

    counter: Counter[tuple[str, str, str]] = Counter()
    sample_pids: dict[tuple[str, str, str], list[int]] = {}
    for intent, fq, tq, pid in reassignment_triples:
        key = (intent, fq, tq)
        counter[key] += 1
        sample_pids.setdefault(key, []).append(pid)

    inserted: list[dict[str, Any]] = []
    for (intent, from_q, to_q), n in counter.items():
        if n < _MIN_REASSIGNMENTS:
            continue
        fp = _fingerprint(intent, from_q, to_q)
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            continue
        opp = LearningOpportunity(
            segment=f"intent:{intent} · {from_q}→{to_q}",
            fingerprint=fp,
            proposed_remedy=json.dumps({
                "change_type": "routing_rule",
                "scope": {"namespace": "track_classifier", "key": "owner_routing"},
                "current": {"intent": intent, "queue": from_q},
                "proposed": {"intent": intent, "queue": to_q},
                "rationale": (
                    f"{n} HITL tasks for intent '{intent}' were reassigned from "
                    f"'{from_q}' to '{to_q}' by CSRs in the last {_LOOKBACK_DAYS} days. "
                    f"Future cases with the same intent should route directly to '{to_q}'."
                ),
            }),
            expected_lift=f"Save {n} reassignment clicks per period",
            effort="Low",
            risk="Med",
            score=round(min(n / 3.0, 10.0), 2),
            status="open",
            source="hitl_reassignment_cluster",
            sample_pipeline_ids=sample_pids.get((intent, from_q, to_q), [])[:30],
            baseline_id=_anchor(db, f"intent:{intent}"),
        )
        db.add(opp)
        inserted.append({"intent": intent, "from": from_q, "to": to_q, "count": n})
    if inserted:
        db.commit()
    return inserted
