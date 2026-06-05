"""Continuous Learning candidate generators.

One module per change_type. Each module exposes:

    def generate(db: Session) -> list[GeneratedOpportunity]:
        '''Scan signals, emit candidate opportunities for this change type.'''

A `GeneratedOpportunity` is a plain dict shaped to seed a LearningOpportunity
row plus enough context for the operator to evaluate the candidate without
opening the underlying data.

Generators are idempotent: calling generate() repeatedly does not duplicate
existing opportunities. Each generator owns the fingerprint format for its
change type so the de-duplication logic stays local.

The top-level `run_all_generators(db)` runs every registered generator and
returns a summary of how many candidates each produced. Wired into a periodic
sweep and into the manual "Refresh tuning queue" button on the Learning UI.
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session


def resolve_baseline_id_for_segment(db: Session, segment: str | None) -> int | None:
    """Best-effort baseline anchor for a CSR-correction-driven opportunity.

    The threshold / pattern_list / routing_rule / validation_rule generators
    emit candidates rooted in operator corrections, not in a metric breach.
    They still benefit from anchoring to the most-relevant Baseline Quality
    Target so the Baselines drill-through shows every related signal in one
    timeline. Resolution rule: pick the baseline whose segment matches
    exactly, preferring (in order) intent_classification_accuracy for
    intent segments, customer_match_rate for customer segments, the
    stage-default metric for stage segments, and otherwise the first
    baseline with a matching segment string."""
    if not segment:
        return None
    try:
        from ..baselines import match_baseline_id
        if segment.startswith("intent:"):
            bid = match_baseline_id(db, "intent_classification_accuracy", segment)
            if bid:
                return bid
        if segment.startswith("customer:"):
            bid = match_baseline_id(db, "customer_match_rate", segment)
            if bid:
                return bid
        if segment.startswith("language:"):
            bid = match_baseline_id(db, "language_detection_accuracy", segment)
            if bid:
                return bid
        if segment.startswith("stage:"):
            bid = match_baseline_id(db, "p95_stage_latency_ms", segment)
            if bid:
                return bid
        # Generic fallback: walk the cached index and return the first row
        # whose segment matches.
        from ..baselines import _ensure_index  # type: ignore[attr-defined]
        idx = _ensure_index(db)
        for (m, s), bid_candidate in idx.items():
            if s == segment:
                return bid_candidate
    except Exception:
        return None
    return None


from . import threshold_generator
from . import pattern_list_generator
from . import routing_rule_generator
from . import validation_rule_generator
from . import drift_alert_generator
from . import prompt_refinement_generator


# Registry of (change_type, generate-fn). Add new generators by appending.
_REGISTRY: list[tuple[str, Callable[[Session], list[dict[str, Any]]]]] = [
    ("threshold", threshold_generator.generate),
    ("pattern_list", pattern_list_generator.generate),
    ("routing_rule", routing_rule_generator.generate),
    ("validation_rule", validation_rule_generator.generate),
    ("drift_alert", drift_alert_generator.generate),
    ("prompt_refinement", prompt_refinement_generator.generate),
]


def run_all_generators(db: Session) -> dict[str, int]:
    """Run every generator. Returns {change_type: candidates_emitted}.

    A candidate counts as "emitted" only if it persisted as a new row;
    duplicate suppression is handled per-generator via the fingerprint
    convention.
    """
    out: dict[str, int] = {}
    for change_type, fn in _REGISTRY:
        try:
            results = fn(db) or []
            out[change_type] = len(results)
        except Exception as e:
            import logging
            logging.getLogger("learning_generators").exception(
                "generator %s failed: %s", change_type, e,
            )
            out[change_type] = 0
    return out
