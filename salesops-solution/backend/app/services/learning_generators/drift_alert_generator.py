"""Drift-alert candidate generator.

Walks the `drift_alerts` table and emits a typed remediation candidate for
each fired alert that does not already have an associated learning
opportunity. Closes the loop between the Drift signals on the Continuous
Learning page and the Tuning Queue: every drift alarm produces an
actionable, deduplicated improvement proposal the operator can promote.

Signal source: `DriftAlert` rows (table populated by the drift detector).
Each alert carries a (segment, metric, severity, current, baseline) tuple;
the generator maps the metric to a remedy template, computes a score from
severity + delta magnitude, and persists a LearningOpportunity with
`linked_drift_alert_id` pointing back at the source alert.

Idempotent: re-running does not duplicate rows. Each candidate's
fingerprint is derived from (metric, segment) so a recurring drift on the
same slice updates the existing open opportunity instead of cloning it.

Apply path: most drift opportunities propose KB rule changes that
`learning_promotion.promote_ab_to_production` already knows how to apply
(threshold + validation_rule change_types). A few — SLA latency, classifier
accuracy — generate an "advisory" candidate that lands in the queue with a
clear human-readable rationale, since the apply step is operator-led.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any


def _resolve_baseline_id(db, metric: str | None, segment: str | None) -> int | None:
    """Best-effort baseline anchor for a (metric, segment) tuple. Wraps the
    baselines service so this generator stays resilient if the helper is
    unavailable in unit tests."""
    try:
        from ..baselines import match_baseline_id
        return match_baseline_id(db, metric, segment)
    except Exception:
        return None

from sqlalchemy.orm import Session

from ...models import DriftAlert, LearningOpportunity


_LOOKBACK_DAYS = 30

# Severity → score multiplier. Drives the ranking of candidates so the
# critical drifts float to the top of the operator's queue.
_SEVERITY_WEIGHT: dict[str, float] = {
    "slo_breach": 1.0,
    "critical":   1.0,
    "warn":       0.65,
    "warning":    0.65,
    "info":       0.4,
}

def _worst_contributor(top_contributors: list[dict] | None) -> dict | None:
    """Return the worst-first contributor entry off the alert, or None when
    the alert carries no contributor breakdown (legacy or non-baseline
    detector)."""
    if not top_contributors:
        return None
    first = top_contributors[0]
    if not isinstance(first, dict):
        return None
    return first


def _contributor_phrase(c: dict | None, metric: str) -> str:
    """Render a short, enterprise-voice phrase identifying the worst
    contributor: 'PO intake', 'Japanese language', 'Extract stage', etc.
    Falls back to the bare segment string when no friendly label is
    available."""
    if not c:
        return ""
    seg = c.get("segment") or ""
    if seg.startswith("intent:"):
        return f"intent {seg.split(':', 1)[1]}"
    if seg.startswith("language:"):
        return f"language {seg.split(':', 1)[1]}"
    if seg.startswith("stage:"):
        return f"{seg.split(':', 1)[1]} stage"
    if seg.startswith("region:"):
        return f"region {seg.split(':', 1)[1]}"
    if seg.startswith("customer:"):
        return f"customer {seg.split(':', 1)[1]}"
    return seg or "the worst-performing segment"


# Remedy templates keyed by metric. Each entry describes the proposed
# change_type, scope, and rationale text. The scope mirrors what the
# threshold / validation_rule promoters expect so the operator's Promote
# action can write the change directly.
def _remedy_for(
    metric: str,
    segment: str,
    current: float,
    baseline: float,
    top_contributor: dict | None = None,
) -> dict[str, Any]:
    delta = current - baseline
    delta_pct = (delta / baseline) if baseline else 0.0
    contributor_phrase = _contributor_phrase(top_contributor, metric)
    contributor_observed = (top_contributor or {}).get("observed") if top_contributor else None

    if metric == "extraction_completeness":
        # Completeness dropped below baseline. Tighten the schema validator
        # for the affected slice so missing fields gate to HITL earlier.
        scope_key = (top_contributor or {}).get("segment") or segment
        if top_contributor and contributor_observed is not None:
            rationale = (
                f"{contributor_phrase.capitalize()} completeness is at "
                f"{float(contributor_observed):.2f}; the concept baseline target is "
                f"{baseline:.2f}. {contributor_phrase.capitalize()} is the top contributor "
                "to this breach. Tighten the per-intent required-fields list so the "
                "incomplete cases route to HITL before the LLM sees them."
            )
        else:
            rationale = (
                f"Extraction completeness is {current:.2f} versus a baseline of "
                f"{baseline:.2f} (delta {delta:+.2f}). Tighten the required-fields "
                "list so the incomplete cases route to HITL before the LLM sees them."
            )
        return {
            "change_type": "validation_rule",
            "scope": {"namespace": "verification_rule", "key": f"strict_extraction:{scope_key}"},
            "current": {"required_fields": "stage_default"},
            "proposed": {"required_fields": "stage_default + segment_specific"},
            "rationale": rationale,
            "advisory": False,
        }

    if metric in ("hitl_rate",):
        # HITL rate climbed. Suggest raising the autonomy threshold so the
        # decision agent stops mis-routing borderline cases to L4.
        intent = segment.split(":", 1)[-1]
        return {
            "change_type": "threshold",
            "scope": {"namespace": "threshold", "key": intent},
            "current": {"l4_floor": 0.95},
            "proposed": {"l4_floor": 0.97},
            "rationale": (
                f"HITL rate on {segment} is {current:.2f} versus a baseline of "
                f"{baseline:.2f}. Raising the L4 floor moves the marginal cases "
                "out of full autonomy and into one-click review."
            ),
            "advisory": False,
        }

    if metric == "aioa_fail_rate":
        # AIOA rejections climbed. Propose tightening the pre-AIOA validation
        # rules so cases that would fail are caught locally first.
        intent = segment.split(":", 1)[-1]
        return {
            "change_type": "validation_rule",
            "scope": {"namespace": "verification_rule", "key": f"pre_aioa_check:{intent}"},
            "current": {"strictness": "default"},
            "proposed": {"strictness": "strict"},
            "rationale": (
                f"AIOA fail rate on {segment} climbed from {baseline:.2f} to {current:.2f}. "
                "Tightening pre-AIOA validation locally catches the failure-prone cases before "
                "they round-trip externally."
            ),
            "advisory": False,
        }

    if metric == "intent_classification_accuracy":
        scope_key = (top_contributor or {}).get("segment") or segment
        if top_contributor and contributor_observed is not None:
            rationale = (
                f"Classifier accuracy on {contributor_phrase} is "
                f"{float(contributor_observed):.2f} against the concept baseline target of "
                f"{baseline:.2f}. {contributor_phrase.capitalize()} is the top contributor; "
                "expand the positive-example set for this slice and retighten the "
                "disambiguation rules."
            )
        else:
            rationale = (
                f"Intent classification accuracy is {current:.2f} versus a baseline of "
                f"{baseline:.2f}. Add representative examples to the classifier example "
                "set, then retrain."
            )
        return {
            "change_type": "advisory",
            "scope": {"namespace": "training_data", "key": scope_key},
            "current": {"accuracy": current},
            "proposed": {"accuracy": baseline},
            "rationale": rationale,
            "advisory": True,
        }

    if metric == "classification_accuracy":
        # Accuracy dropped. Surface as an advisory: the operator's action is
        # to expand the training set or example list for that slice.
        return {
            "change_type": "advisory",
            "scope": {"namespace": "training_data", "key": segment},
            "current": {"accuracy": baseline},
            "proposed": {"accuracy": "at or above baseline"},
            "rationale": (
                f"Classification accuracy on {segment} fell from {baseline:.2f} to {current:.2f}. "
                "Add representative examples from this slice to the classifier example set, then "
                "retrain. The apply step is operator-led."
            ),
            "advisory": True,
        }

    if metric == "p95_stage_latency_ms":
        scope_key = (top_contributor or {}).get("segment") or segment
        if top_contributor and contributor_observed is not None:
            rationale = (
                f"{contributor_phrase.capitalize()} p95 latency is "
                f"{int(float(contributor_observed))} ms against the concept baseline "
                f"ceiling of {int(baseline)} ms. {contributor_phrase.capitalize()} is the "
                "top contributor; investigate the stage's LLM provider mix and pool "
                "concurrency."
            )
        else:
            rationale = (
                f"p95 latency is {int(current)} ms versus a baseline of {int(baseline)} ms. "
                "Investigate provider mix and pool concurrency. Apply step is operator-led."
            )
        return {
            "change_type": "advisory",
            "scope": {"namespace": "sla", "key": scope_key},
            "current": {"p95_ms": current},
            "proposed": {"p95_ms": baseline},
            "rationale": rationale,
            "advisory": True,
        }

    if metric == "sla_adherence_p95_ms":
        # SLA breached. Advisory candidate; actions usually live outside the
        # KB (worker pool sizing, model selection, concurrency).
        return {
            "change_type": "advisory",
            "scope": {"namespace": "sla", "key": segment},
            "current": {"p95_ms": current},
            "proposed": {"p95_ms": baseline},
            "rationale": (
                f"p95 latency on {segment} is {int(current)} ms versus a baseline of "
                f"{int(baseline)} ms. Investigate per-segment LLM provider mix and pool "
                "concurrency. The apply step is operator-led."
            ),
            "advisory": True,
        }

    if metric == "language_detection_accuracy":
        scope_key = (top_contributor or {}).get("segment") or segment
        if top_contributor and contributor_observed is not None:
            rationale = (
                f"Language detection on {contributor_phrase} is "
                f"{float(contributor_observed):.2f}; the concept baseline target is "
                f"{baseline:.2f}. {contributor_phrase.capitalize()} is the top "
                "contributor; review the per-language heuristic rules and add labelled "
                "examples for this language."
            )
        else:
            rationale = (
                f"Language detection accuracy is {current:.2f} versus a baseline of "
                f"{baseline:.2f}. Review the language heuristic rules."
            )
        return {
            "change_type": "advisory",
            "scope": {"namespace": "language_heuristic_rules", "key": scope_key},
            "current": {"accuracy": current},
            "proposed": {"accuracy": baseline},
            "rationale": rationale,
            "advisory": True,
        }

    # Catch-all: produce an advisory candidate so the alert is at least
    # represented in the tuning queue.
    return {
        "change_type": "advisory",
        "scope": {"namespace": "drift", "key": f"{metric}:{segment}"},
        "current": {metric: current},
        "proposed": {metric: baseline},
        "rationale": (
            f"Drift detected on {metric} for {segment}: current {current} vs baseline {baseline} "
            f"(delta {delta_pct*100:+.1f}%). Operator review required to choose the remedy."
        ),
        "advisory": True,
    }


def _fingerprint(metric: str, segment: str) -> str:
    return f"drift:{metric}:{segment}"


def generate(db: Session) -> list[dict[str, Any]]:
    """Scan drift alerts and emit tuning opportunities. Idempotent."""
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    alerts = (
        db.query(DriftAlert)
        .filter(DriftAlert.detected_at >= cutoff)
        .order_by(DriftAlert.detected_at.desc())
        .all()
    )
    if not alerts:
        return []

    inserted: list[dict[str, Any]] = []
    for a in alerts:
        metric = a.metric or ""
        segment = a.segment or "unknown"
        severity = (a.severity or "info").lower()
        current = float(a.current or 0.0)
        baseline = float(a.baseline or 0.0)

        fp = _fingerprint(metric, segment)
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            # If the same drift surfaces again with higher severity, refresh
            # the linkage; otherwise leave the existing row alone.
            if existing.linked_drift_alert_id != a.id and a.severity in ("slo_breach", "critical"):
                existing.linked_drift_alert_id = a.id
                db.add(existing)
            # Anchor backfill: an opportunity created before the baseline FK
            # existed may still be missing its anchor. Copy the alert's
            # baseline_id onto it now so the timeline view groups correctly.
            if existing.baseline_id is None and a.baseline_id:
                existing.baseline_id = a.baseline_id
                db.add(existing)
            continue

        top_contributors = list(getattr(a, "top_contributors", None) or [])
        worst = _worst_contributor(top_contributors)
        remedy = _remedy_for(metric, segment, current, baseline, top_contributor=worst)
        weight = _SEVERITY_WEIGHT.get(severity, 0.5)
        delta_magnitude = abs(current - baseline) / max(abs(baseline), 1e-9)
        score = round(min(1.0, weight * (0.6 + 0.4 * min(1.5, delta_magnitude))), 2)

        if worst and worst.get("observed") is not None and worst.get("segment"):
            lift_text = (
                f"Close drift on {metric}. Worst contributor: "
                f"{worst.get('segment')} at {float(worst['observed']):.2f} "
                f"versus target {baseline}."
            )
        else:
            lift_text = f"Close drift on {metric} (current {current} vs baseline {baseline})"
        opp = LearningOpportunity(
            segment=segment,
            fingerprint=fp,
            proposed_remedy=json.dumps(remedy),
            expected_lift=lift_text,
            effort="Low" if not remedy.get("advisory") else "Med",
            risk="Low" if remedy.get("advisory") else "Med",
            score=score,
            status="open",
            source="drift_alert",
            linked_drift_alert_id=a.id,
            # Anchor the opportunity to the same baseline as the originating
            # alert. Falls back to a (metric, segment) match when the alert
            # itself is missing the FK (legacy data path).
            baseline_id=a.baseline_id or _resolve_baseline_id(db, metric, segment),
            sample_pipeline_ids=[],
        )
        db.add(opp)
        db.flush()
        inserted.append({
            "id": opp.id,
            "segment": segment,
            "metric": metric,
            "severity": severity,
            "fingerprint": fp,
            "linked_drift_alert_id": a.id,
        })

    if inserted:
        db.commit()
    return inserted
