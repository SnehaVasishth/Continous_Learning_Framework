"""Prompt-refinement candidate generator.

Sixth candidate type in the Continuous Learning loop. The deck names
"prompt refinement" alongside rule revision, model retrain, and workflow
change as a first-class remediation type — this generator emits them.

Trigger: an `extraction_completeness` or `classification_accuracy` drift
fires on a segment with enough CSR-edit feedback that we can name a
specific field / phrasing the prompt is missing. We don't try to write the
new prompt automatically; we surface the **diff hint** (which field is
being missed, which phrase the CSRs added on edit) so the rule owner can
write the prompt update and stage it as a shadow experiment.

Fingerprint format: `prompt_refinement:<stage>:<segment>`. Idempotent.

Apply path: a manual operator action — the candidate carries a structured
`proposed` block (`{ stage, target_field, missing_phrases, sample_edits }`)
so the operator sees exactly what is missing without opening the cases.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...models import DriftAlert, Feedback, LearningOpportunity, Pipeline


def _anchor(db: Session, segment: str | None) -> int | None:
    try:
        from . import resolve_baseline_id_for_segment
        return resolve_baseline_id_for_segment(db, segment)
    except Exception:
        return None


_LOOKBACK_DAYS = 30
_MIN_EDITS = 3
_STOPWORDS = {
    "the", "and", "for", "with", "from", "your", "this", "that", "have", "will",
    "are", "was", "were", "been", "you", "our", "we", "to", "of", "in", "on",
    "by", "is", "be", "as", "at", "an", "or", "it", "any", "all", "but",
}

# Drift metrics that map to prompt issues. Other metrics produce candidates
# in the other generators (threshold, validation_rule, etc.).
_PROMPT_RELEVANT_METRICS = {"extraction_completeness", "classification_accuracy"}

# Drift segment → stage. The stage tells us which prompt to refine.
_METRIC_TO_STAGE: dict[str, str] = {
    "extraction_completeness": "extract",
    "classification_accuracy": "intake",
}


def _fingerprint(stage: str, segment: str) -> str:
    return f"prompt_refinement:{stage}:{segment}"


def _phrases_from_edits(edits: list[Feedback], top_n: int = 6) -> list[str]:
    """Pull recurring noun-bigrams the CSR added on edit feedback. Heuristic,
    but enough to point a human at the missing concept."""
    counter: Counter[str] = Counter()
    for f in edits:
        text = (f.note or "")
        data = f.data or {}
        # Common shapes: data.edits = { field: new_value }; data.diff = "..."
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, str):
                    text += " " + v
                elif isinstance(v, dict):
                    text += " " + json.dumps(v)
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", text.lower())
        tokens = [t for t in tokens if t not in _STOPWORDS]
        for i in range(len(tokens) - 1):
            counter[f"{tokens[i]} {tokens[i+1]}"] += 1
    return [p for p, _ in counter.most_common(top_n)]


def _segment_to_filter(segment: str) -> tuple[str, str] | None:
    if not segment or ":" not in segment:
        return None
    kind, value = segment.split(":", 1)
    return kind.strip(), value.strip()


def generate(db: Session) -> list[dict[str, Any]]:
    """Scan recent drift alerts and emit prompt-refinement candidates."""
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    alerts = (
        db.query(DriftAlert)
        .filter(DriftAlert.detected_at >= cutoff)
        .filter(DriftAlert.metric.in_(list(_PROMPT_RELEVANT_METRICS)))
        .all()
    )
    if not alerts:
        return []

    inserted: list[dict[str, Any]] = []
    for a in alerts:
        stage = _METRIC_TO_STAGE.get(a.metric or "", "extract")
        segment = a.segment or "unknown"
        fp = _fingerprint(stage, segment)
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            continue

        # Pull supporting edit feedback for the segment.
        seg = _segment_to_filter(segment)
        q = (
            db.query(Feedback)
            .join(Pipeline, Pipeline.id == Feedback.pipeline_id)
            .filter(Feedback.kind.in_(("edit", "edit_and_approve")))
            .filter(Feedback.created_at >= cutoff)
        )
        if seg:
            kind, value = seg
            if kind == "intent":
                q = q.filter(Pipeline.intent == value)
            elif kind == "language":
                q = q.filter(Pipeline.language == value)
        edits = q.limit(60).all()
        if len(edits) < _MIN_EDITS:
            continue
        phrases = _phrases_from_edits(edits)

        sample_pipeline_ids = [e.pipeline_id for e in edits if e.pipeline_id][:8]

        opp = LearningOpportunity(
            segment=segment,
            fingerprint=fp,
            proposed_remedy=json.dumps({
                "change_type": "prompt_refinement",
                "scope": {"namespace": "agent_prompts", "key": f"{stage}:system"},
                "current": {"observed_drift": a.metric},
                "proposed": {
                    "stage": stage,
                    "target_field": "system_prompt",
                    "missing_phrases": phrases,
                    "edit_sample_count": len(edits),
                    "hint": (
                        "CSR edits cluster around the phrases above. Update the system prompt "
                        "for the {stage} agent to acknowledge them explicitly, then stage as a "
                        "shadow experiment for back-testing before promotion."
                    ).format(stage=stage),
                },
                "rationale": (
                    f"Drift on {a.metric} for {segment} (current {a.current} vs baseline {a.baseline}) "
                    f"correlates with {len(edits)} CSR edits in the same window. Recurring phrases "
                    f"in those edits ({', '.join(phrases[:3]) or 'n/a'}) suggest the {stage} prompt "
                    "is not handling the new shape."
                ),
                "advisory": False,
            }),
            expected_lift=f"Close drift on {a.metric} for {segment}",
            effort="Med",
            risk="Med",
            score=round(min(1.0, len(edits) / 20.0), 2),
            status="open",
            source="prompt_refinement",
            linked_drift_alert_id=a.id,
            baseline_id=a.baseline_id or _anchor(db, segment),
            sample_pipeline_ids=sample_pipeline_ids,
        )
        db.add(opp)
        db.flush()
        inserted.append({
            "id": opp.id,
            "segment": segment,
            "stage": stage,
            "metric": a.metric,
            "fingerprint": fp,
            "missing_phrases": phrases[:3],
            "linked_drift_alert_id": a.id,
        })

    if inserted:
        db.commit()
    return inserted
