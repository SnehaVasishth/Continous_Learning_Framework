"""Threshold candidate generator.

Surfaces a candidate change when the L4 cohort for a given intent has an
abnormally high CSR edit rate. The hypothesis is that the L4 confidence
floor for that intent is set too low: cases that the classifier rates ≥ 0.95
are still requiring human correction often enough to suggest the floor
should rise.

Signal: per-intent, count completed pipelines tiered L4 (autonomy_tier ==
"L4_AUTO") in the last 30 days and the subset that received a CSR edit
feedback. If edits/total > 5% AND the cohort has at least 20 cases, emit a
candidate proposing the L4 floor be raised to the lowest confidence that
removes the bottom-quartile edited cases.

Apply path (handled in learning_promotion.promote_ab_to_production): writes
the new per-intent threshold to the KB rule body for
namespace="threshold", key=<intent>. Pipelines pick it up on next run.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...models import Feedback, LearningOpportunity, Pipeline


def _anchor(db: Session, segment: str | None) -> int | None:
    try:
        from . import resolve_baseline_id_for_segment
        return resolve_baseline_id_for_segment(db, segment)
    except Exception:
        return None


_LOOKBACK_DAYS = 30
_MIN_COHORT = 20
_EDIT_RATE_FLOOR = 0.05  # 5% edit rate triggers a candidate
_CURRENT_L4_FLOOR = 0.95


def _fingerprint(intent: str) -> str:
    return f"threshold:l4_floor:{intent}"


def generate(db: Session) -> list[dict[str, Any]]:
    """Scan and emit threshold-tuning opportunities. Idempotent.

    Returns the list of opportunities that were inserted in this pass.
    """
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    l4_rows = (
        db.query(Pipeline)
        .filter(Pipeline.autonomy_tier == "L4_AUTO")
        .filter(Pipeline.started_at >= cutoff)
        .filter(Pipeline.intent.isnot(None))
        .all()
    )
    if not l4_rows:
        return []
    by_intent: dict[str, list[Pipeline]] = {}
    for p in l4_rows:
        by_intent.setdefault(str(p.intent), []).append(p)

    inserted: list[dict[str, Any]] = []
    for intent, pipes in by_intent.items():
        if len(pipes) < _MIN_COHORT:
            continue
        pipe_ids = [p.id for p in pipes]
        edited_ids = set(
            int(pid)
            for (pid,) in db.query(Feedback.pipeline_id)
            .filter(Feedback.pipeline_id.in_(pipe_ids))
            .filter(Feedback.kind == "edit")
            .distinct()
            .all()
            if pid is not None
        )
        if not edited_ids:
            continue
        edit_rate = len(edited_ids) / len(pipes)
        if edit_rate < _EDIT_RATE_FLOOR:
            continue
        edited_confidences = sorted(
            float(p.confidence)
            for p in pipes
            if p.id in edited_ids and p.confidence is not None
        )
        if not edited_confidences:
            continue
        q1_index = max(0, len(edited_confidences) // 4)
        proposed_floor = round(edited_confidences[q1_index], 3)
        if proposed_floor <= _CURRENT_L4_FLOOR + 0.001:
            continue
        proposed_floor = min(proposed_floor, 0.995)

        fp = _fingerprint(intent)
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            continue

        opp = LearningOpportunity(
            segment=f"intent:{intent}",
            fingerprint=fp,
            proposed_remedy=json.dumps({
                "change_type": "threshold",
                "scope": {"namespace": "threshold", "key": intent},
                "current": {"l4_floor": _CURRENT_L4_FLOOR},
                "proposed": {"l4_floor": proposed_floor},
                "rationale": (
                    f"L4 cohort for intent '{intent}' (n={len(pipes)} over last "
                    f"{_LOOKBACK_DAYS}d) has a {edit_rate * 100:.1f}% CSR edit rate. "
                    f"Raising the L4 floor to {proposed_floor} would have moved "
                    f"the bottom quartile of edited cases to L3 review."
                ),
            }),
            expected_lift=f"Reduce L4 edit rate from {edit_rate*100:.1f}% (n={len(pipes)})",
            effort="Low",
            risk="Med",
            score=round(edit_rate * 10, 2),
            status="open",
            source="threshold_anomaly",
            sample_pipeline_ids=sorted(edited_ids),
            baseline_id=_anchor(db, f"intent:{intent}"),
        )
        db.add(opp)
        inserted.append({"intent": intent, "edit_rate": edit_rate, "proposed_floor": proposed_floor})
    if inserted:
        db.commit()
    return inserted
