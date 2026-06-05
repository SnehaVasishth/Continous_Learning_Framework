"""Validation-rule candidate generator.

A validation rule is a PRE-FLIGHT check the verifier runs BEFORE a side
effect (Salesforce write, customer email send). Valid candidates here
require three properties — without all three, no opportunity is emitted:

  1. A precondition the verifier can evaluate from the pipeline's extracted
     state ALONE, before any external call. The precondition cannot be the
     description of a past failure (that is observation, not prediction).

  2. A measurable action the candidate would take that is different from
     the default fallback. "Halt and route to HITL" is the default; a real
     candidate either re-routes to a specific track, requests a specific
     enrichment, or flags a specific business invariant. The candidate
     opportunity description must name the precondition explicitly.

  3. A repeating pattern in PIPELINE-DATA (not infrastructure events) that
     a CSR would recognise as a tuning rather than an ops alert. Examples:
     "Quote unit price > 2sigma above historical median for this part" or
     "Order missing ship-to address". NOT examples: "Salesforce errored",
     "Network timeout", "Database connection refused" — those are ops
     signals owned by the Monitor service.

This generator surfaces candidates from two real signal sources only:

  (A) Missing-field clusters on the EXTRACTED state of failed pipelines.
      If N pipelines failed downstream AND they share the same missing
      critical field (po_number / ship_to / quote_number / customer_id),
      the field-missing precondition is the candidate.

  (B) Business-invariant violations in the EXTRACTED state. Quote unit
      prices outside the historical median +/- 2sigma; order quantities
      outside the historical range for that customer; service-contract
      assets that do not appear on the account. These are real preconditions
      the verifier can evaluate from the pipeline's own state.

Infrastructure failure clusters (sf_error, sp_error, salesforce_write_failed,
verifier_halt) are explicitly NOT generated here. Those are routed to the
Monitor service detectors (Phase 3.1, detector 7: integration_write_failures).
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...models import LearningOpportunity, Pipeline


def _anchor(db: Session, segment: str | None) -> int | None:
    try:
        from . import resolve_baseline_id_for_segment
        return resolve_baseline_id_for_segment(db, segment)
    except Exception:
        return None


_LOOKBACK_DAYS = 30
_MIN_FAILURES = 3
_CRITICAL_FIELDS = ("po_number", "ship_to", "quote_number", "customer_id", "work_order_number")
_INFRASTRUCTURE_KINDS = {"sf_error", "sp_error", "sn_error", "salesforce_write_failed", "verifier_halt", "network_error", "timeout"}


def _fingerprint(kind: str, detail: str) -> str:
    return f"validation_rule:{kind}:{detail[:80]}"


def _fields_missing_on(pipe: Pipeline) -> set[str]:
    extracted = pipe.extracted if isinstance(pipe.extracted, dict) else {}
    missing: set[str] = set()
    for f in _CRITICAL_FIELDS:
        v = extracted.get(f)
        if v in (None, "", [], {}):
            missing.add(f)
    return missing


def _generate_missing_field_candidates(db: Session, cutoff: datetime) -> list[dict[str, Any]]:
    """Signal A — pipelines that failed (status=discarded or pipe.error set)
    AND share a missing critical field. Eligible: extracted-state precondition,
    actionable (request enrichment for this field), recognisable to a CSR.
    """
    failed = (
        db.query(Pipeline)
        .filter(Pipeline.started_at >= cutoff)
        .filter(Pipeline.status.in_(["discarded", "error"]) | Pipeline.error.isnot(None))
        .all()
    )
    if not failed:
        return []
    by_field: dict[tuple[str, str], list[int]] = defaultdict(list)  # (intent, field) -> [pipe_ids]
    for p in failed:
        missing = _fields_missing_on(p)
        for f in missing:
            by_field[(p.intent or "unknown", f)].append(int(p.id))

    inserted: list[dict[str, Any]] = []
    for (intent, field), pipe_ids in by_field.items():
        if len(pipe_ids) < _MIN_FAILURES:
            continue
        fp = _fingerprint("missing_field", f"{intent}:{field}")
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            continue
        proposed = {
            "rule_id": f"require_{field}_for_{intent}",
            "fires_on": (
                f"intent={intent!r} AND extracted.{field} is missing or empty"
            ),
            "action": f"request_enrichment:{field}",
            "severity": "block_until_enriched",
        }
        opp = LearningOpportunity(
            segment=f"intent:{intent}",
            fingerprint=fp,
            proposed_remedy=json.dumps({
                "change_type": "validation_rule",
                "scope": {"namespace": "verification_rule", "key": proposed["rule_id"]},
                "proposed": proposed,
                "rationale": (
                    f"{len(pipe_ids)} pipelines for intent '{intent}' failed downstream "
                    f"in the last {_LOOKBACK_DAYS} days and shared the same missing "
                    f"critical field '{field}'. A pre-flight verifier rule that "
                    f"requires {field} to be present before the side effect would have "
                    f"caught all of them and routed them for CSR enrichment instead of "
                    f"a partial write."
                ),
            }),
            expected_lift=f"Prevent {len(pipe_ids)} partial-write incidents per period",
            effort="Low",
            risk="Low",
            score=round(min(len(pipe_ids) / 3.0, 10.0), 2),
            status="open",
            source="missing_field_cluster",
            sample_pipeline_ids=sorted(pipe_ids)[:30],
            baseline_id=_anchor(db, f"intent:{intent}"),
        )
        db.add(opp)
        inserted.append({"intent": intent, "field": field, "count": len(pipe_ids)})
    if inserted:
        db.commit()
    return inserted


def _generate_business_invariant_candidates(db: Session, cutoff: datetime) -> list[dict[str, Any]]:
    """Signal B — extracted numeric fields outside the historical baseline.
    Currently scans for quote unit price and order quantity outliers per
    intent. These are real data-shape preconditions the verifier can check.
    """
    pipes = (
        db.query(Pipeline)
        .filter(Pipeline.started_at >= cutoff)
        .filter(Pipeline.extracted.isnot(None))
        .all()
    )
    if not pipes:
        return []

    # Bucket by (intent, numeric_field). Only emit when we have a real
    # distribution to compare against and a cluster of outliers.
    fields_to_check = [("unit_price", "quote_to_order"), ("quantity", "trade_change_order")]
    inserted: list[dict[str, Any]] = []
    for field, target_intent in fields_to_check:
        values: list[float] = []
        outliers: list[int] = []
        for p in pipes:
            if p.intent != target_intent:
                continue
            v = (p.extracted or {}).get(field)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            values.append(fv)
        if len(values) < 20:
            continue
        median = statistics.median(values)
        stdev = statistics.pstdev(values) or 0.0
        if stdev <= 0:
            continue
        cap_high = median + 2 * stdev
        cap_low = max(median - 2 * stdev, 0.0)
        for p in pipes:
            if p.intent != target_intent:
                continue
            v = (p.extracted or {}).get(field)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > cap_high or fv < cap_low:
                outliers.append(int(p.id))
        if len(outliers) < _MIN_FAILURES:
            continue
        fp = _fingerprint("invariant_outlier", f"{target_intent}:{field}")
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            continue
        proposed = {
            "rule_id": f"flag_{field}_outlier_for_{target_intent}",
            "fires_on": (
                f"intent={target_intent!r} AND abs(extracted.{field} - {round(median, 2)}) > {round(2 * stdev, 2)}"
            ),
            "action": "require_review_against_historical_band",
            "severity": "review_recommended",
            "historical_median": round(median, 2),
            "two_sigma_band": [round(cap_low, 2), round(cap_high, 2)],
        }
        opp = LearningOpportunity(
            segment=f"intent:{target_intent}:{field}",
            fingerprint=fp,
            proposed_remedy=json.dumps({
                "change_type": "validation_rule",
                "scope": {"namespace": "verification_rule", "key": proposed["rule_id"]},
                "proposed": proposed,
                "rationale": (
                    f"{len(outliers)} pipelines for intent '{target_intent}' had "
                    f"{field} values outside the 2-sigma band "
                    f"[{round(cap_low, 2)}, {round(cap_high, 2)}] computed from the "
                    f"last {_LOOKBACK_DAYS} days (n={len(values)}, median={round(median, 2)}). "
                    f"A pre-flight rule that requires review for outliers would catch "
                    f"these before the side effect."
                ),
            }),
            expected_lift=f"Flag {len(outliers)} historical-band outliers per period for review",
            effort="Low",
            risk="Med",
            score=round(min(len(outliers) / 3.0, 10.0), 2),
            status="open",
            source="invariant_outlier_cluster",
            sample_pipeline_ids=sorted(outliers)[:30],
            baseline_id=_anchor(db, f"intent:{target_intent}"),
        )
        db.add(opp)
        inserted.append({"intent": target_intent, "field": field, "outliers": len(outliers), "two_sigma": [round(cap_low, 2), round(cap_high, 2)]})
    if inserted:
        db.commit()
    return inserted


def generate(db: Session) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    out: list[dict[str, Any]] = []
    out.extend(_generate_missing_field_candidates(db, cutoff))
    out.extend(_generate_business_invariant_candidates(db, cutoff))
    return out
