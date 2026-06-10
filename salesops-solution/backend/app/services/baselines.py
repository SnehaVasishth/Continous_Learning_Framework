"""Quality baselines service.

Holds the helpers that read the `baselines` table and tell the rest of the
system whether observed metrics are healthy. Two consumers:

  1. The drift detector (`monitor.detect_baseline_violations`) computes the
     observed value for each enabled baseline, writes it back, and fires a
     DriftAlert when the observation crosses the tolerance band.
  2. The promotion gate (`learning_promotion`) refuses to auto-promote a
     candidate while any `severity="block_promotion"` baseline is currently
     breached for the affected segment.

The seed loader runs once on startup. Idempotent — re-seeding does not
duplicate rows. Existing rows are NEVER overwritten; admins own them after
the first seed lands.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import Baseline

log = logging.getLogger("baselines")


def seed_defaults(db: Session) -> int:
    """Insert default baselines if the table is empty for a given metric+segment.

    Returns the number of new rows created. Existing rows are untouched so
    admin edits survive subsequent restarts.
    """
    from ..kb_seeds.baselines import all_baselines

    rows = all_baselines()
    created = 0
    for r in rows:
        existing = (
            db.query(Baseline)
            .filter(Baseline.metric == r["metric"], Baseline.segment == r["segment"])
            .first()
        )
        if existing:
            # Backfill the rollup_strategy column on rows seeded before the
            # concept-baseline column existed. Admin edits stay untouched
            # because we only fill when the column is NULL or empty.
            if not existing.rollup_strategy and r.get("rollup_strategy"):
                existing.rollup_strategy = r["rollup_strategy"]
            continue
        b = Baseline(
            metric=r["metric"],
            segment=r["segment"],
            direction=r["direction"],
            target_value=float(r["target_value"]),
            drift_pct=float(r.get("drift_pct", 5.0)),
            severity=r.get("severity", "warn"),
            enabled=True,
            owner=r.get("owner", "role:cl_admin"),
            rationale=r.get("rationale"),
            source=r.get("source", "manual"),
            unit=r.get("unit"),
            label=r.get("label"),
            rollup_strategy=r.get("rollup_strategy", "weighted_avg"),
            updated_by="system_seed",
        )
        db.add(b)
        created += 1
    if created:
        db.commit()
        log.info("baselines: seeded %d default rows", created)
    return created


def evaluate_status(b: Baseline, observed: float | None) -> str:
    """Classify an observed value against a baseline.

    Returns one of:
      'healthy'  — within tolerance
      'drifting' — outside tolerance but still on the correct side of target
      'breached' — wrong side of target by more than drift_pct
      'unknown'  — observed is None (e.g. no data yet)
    """
    if observed is None:
        return "unknown"
    target = float(b.target_value or 0.0)
    if target == 0:
        return "unknown"
    drift = float(b.drift_pct or 0.0) / 100.0
    if b.direction == "min":
        # Observed should be >= target. Breached if below target * (1 - drift).
        if observed >= target:
            return "healthy"
        if observed >= target * (1 - drift):
            return "drifting"
        return "breached"
    # direction == "max" — observed should stay <= target
    if observed <= target:
        return "healthy"
    if observed <= target * (1 + drift):
        return "drifting"
    return "breached"


def record_observation(
    db: Session,
    b: Baseline,
    observed: float | None,
) -> str:
    """Persist an observed value + status on a baseline. Returns the status.

    Does NOT commit — caller batches commits for efficiency when the detector
    sweeps many baselines in one pass.
    """
    status = evaluate_status(b, observed)
    b.last_observed = observed
    b.last_observed_at = datetime.utcnow()
    b.last_status = status
    return status


def list_breached(
    db: Session,
    severity: str | None = None,
    max_age_minutes: int = 60,
) -> list[Baseline]:
    """Return baselines whose last observation breached the target.

    `severity=None`     → both warn and block_promotion
    `severity="block_promotion"` → only the hard gates

    `max_age_minutes` filters out stale rows whose detector pass hasn't run
    recently; callers gating on this can be sure the data isn't ancient.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    q = (
        db.query(Baseline)
        .filter(Baseline.enabled.is_(True))
        .filter(Baseline.last_status == "breached")
        .filter(Baseline.last_observed_at.isnot(None))
        .filter(Baseline.last_observed_at >= cutoff)
    )
    if severity:
        q = q.filter(Baseline.severity == severity)
    return q.all()


def to_dict(b: Baseline) -> dict[str, Any]:
    """Serialise a Baseline row for the API.

    Includes the per-segment observations and rollup strategy so the
    Baselines tab can render the expand-view (top contributors) without a
    second roundtrip.
    """
    return {
        "id": b.id,
        "domain": getattr(b, "domain", "keysight") or "keysight",
        "metric": b.metric,
        "segment": b.segment,
        "direction": b.direction,
        "target_value": b.target_value,
        "drift_pct": b.drift_pct,
        "severity": b.severity,
        "enabled": bool(b.enabled),
        "owner": b.owner,
        "rationale": b.rationale,
        "source": b.source,
        "unit": b.unit,
        "label": b.label,
        "last_observed": b.last_observed,
        "last_observed_at": b.last_observed_at.isoformat() if b.last_observed_at else None,
        "last_status": b.last_status or "unknown",
        "segments_observed": list(b.segments_observed or []) if b.segments_observed else [],
        "rollup_strategy": b.rollup_strategy or "weighted_avg",
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        "updated_by": b.updated_by,
    }


# ──────────────────────────────────────────────────────────────────────────
# Baseline anchor helpers. Every Continuous-Learning signal (DriftAlert,
# LearningOpportunity, ABExperiment, RCATicket, Feedback) carries a
# `baseline_id` foreign key to anchor it to one Baseline Quality Target.
# These helpers cover three needs: resolve (id → label), match (metric +
# segment → baseline row), and backfill (legacy rows missing the FK).
# ──────────────────────────────────────────────────────────────────────────

# Module-level cache of (metric, segment) → baseline_id. Rebuilt lazily on
# first lookup after seeding so detector and generator hot paths avoid a
# table scan per write. Invalidated when an admin creates / deletes a
# baseline via the CRUD endpoints.
_baseline_index: dict[tuple[str, str], int] | None = None


def invalidate_baseline_index() -> None:
    """Drop the cached (metric, segment) → id index. Call after any admin
    create / delete on the Baseline table so the next match_baseline lookup
    rebuilds against the current state."""
    global _baseline_index
    _baseline_index = None


def _ensure_index(db: Session) -> dict[tuple[str, str], int]:
    global _baseline_index
    if _baseline_index is None:
        rows = db.query(Baseline).all()
        _baseline_index = {(r.metric, r.segment): r.id for r in rows}
    return _baseline_index


def match_baseline(
    db: Session, metric: str | None, segment: str | None
) -> Baseline | None:
    """Return the most-specific Baseline row matching this (metric, segment),
    or None if no match exists. Two-pass resolution:

      1. Exact match on (metric, segment) — the canonical case used by the
         baseline-violation detector.
      2. Fall back to (metric, 'global') so a generic detector signal still
         anchors against the global baseline for that metric when no
         per-segment row exists.

    Returns the full Baseline object so callers can read the id, label,
    rationale, and target_value off one row.
    """
    if not metric:
        return None
    seg = segment or "global"
    idx = _ensure_index(db)
    bid = idx.get((metric, seg))
    if bid is None and seg != "global":
        bid = idx.get((metric, "global"))
    if bid is None:
        # The detector may write a segment string the seed loader doesn't
        # know about (e.g. 'intent:custom_intent'). Try a structural match:
        # split the segment into kind:value and prefer the most specific
        # row that shares the same kind prefix.
        if seg and ":" in seg:
            kind = seg.split(":", 1)[0]
            for (m, s), bid_candidate in idx.items():
                if m == metric and s.startswith(f"{kind}:"):
                    bid = bid_candidate
                    break
    if bid is None:
        return None
    return db.get(Baseline, bid)


def match_baseline_id(
    db: Session, metric: str | None, segment: str | None
) -> int | None:
    """Convenience that returns just the id of the matched baseline."""
    b = match_baseline(db, metric, segment)
    return b.id if b is not None else None


def label_for(b: Baseline | None, *, metric: str | None = None, segment: str | None = None) -> str | None:
    """Human-readable label for a baseline. Prefers the row's `label` column;
    falls back to 'metric (segment)' when label is unset. Returns None when
    no baseline anchor is available so the caller can omit the field cleanly.

    Accepts either a Baseline row, or a (metric, segment) tuple for callers
    that already have the strings but no row (e.g. an alert whose baseline_id
    was never stamped)."""
    if b is not None:
        if b.label:
            return b.label
        return f"{b.metric} ({b.segment})"
    if metric:
        return f"{metric} ({segment or 'global'})" if segment else metric
    return None


def resolve_label(db: Session, baseline_id: int | None) -> str | None:
    """Resolve a baseline_id to its display label, or None when missing."""
    if not baseline_id:
        return None
    b = db.get(Baseline, baseline_id)
    return label_for(b)


# ──────────────────────────────────────────────────────────────────────────
# Feedback baseline derivation. Feedback rows do not have a single
# canonical baseline — a thumbs-down on the intake stage might speak to
# intent_classification_accuracy, language_detection_accuracy, or any
# customer-specific baseline. This helper attempts a best-effort derivation
# from the row's stage + data payload + linked pipeline. Used at write time
# to stamp `baseline_id` when a confident match exists, and at read time to
# expose `derived_baseline_id` to the API even when the column is null.
# ──────────────────────────────────────────────────────────────────────────

_STAGE_TO_DEFAULT_METRIC: dict[str, str] = {
    "intake": "intent_classification_accuracy",
    "extract": "extraction_completeness",
    "reconcile": "customer_match_rate",
    "decide": "autonomy_l4_rate",
    "execute": "reply_send_success_rate",
    "communicate": "reply_send_success_rate",
    "hitl": "hitl_resolution_p95_hours",
}


def derive_feedback_baseline_id(db: Session, feedback) -> int | None:
    """Heuristic derivation of a baseline anchor for a Feedback row.

    Resolution order:
      1. If the data payload carries an explicit intent (e.g. an intent edit
         from `from_intent` / `to_intent`), prefer the per-intent baseline
         for the stage's default metric.
      2. Otherwise resolve the stage to its default metric and look up the
         segment from the linked pipeline (language for language-detection,
         intent for intent-classification, customer for customer-match).
      3. Fall back to the metric's global baseline.

    Returns the baseline_id, or None when no metric mapping applies.
    """
    if feedback is None:
        return None
    stage = (getattr(feedback, "stage", None) or "").lower()
    metric = _STAGE_TO_DEFAULT_METRIC.get(stage)
    if not metric:
        return None
    data = feedback.data if isinstance(getattr(feedback, "data", None), dict) else {}
    # Intent edits carry the target intent as `to_intent` or `corrected_intent`.
    target_intent = data.get("to_intent") or data.get("corrected_intent") or data.get("intent")
    if stage == "intake" and target_intent:
        bid = match_baseline_id(db, metric, f"intent:{target_intent}")
        if bid:
            return bid
    # Language signal: language-stage feedback or any feedback whose data
    # block names a language.
    lang = data.get("language") or data.get("to_language")
    if lang:
        bid = match_baseline_id(db, "language_detection_accuracy", f"language:{lang}")
        if bid:
            return bid
    # Pipeline-scoped derivation: pull intent / language / customer from the
    # linked pipeline when the payload is sparse.
    pipeline_id = getattr(feedback, "pipeline_id", None)
    if pipeline_id:
        from ..models import Pipeline
        p = db.get(Pipeline, pipeline_id)
        if p is not None:
            if stage == "intake" and p.intent:
                bid = match_baseline_id(db, metric, f"intent:{p.intent}")
                if bid:
                    return bid
            if metric == "language_detection_accuracy" and p.language:
                bid = match_baseline_id(db, metric, f"language:{p.language}")
                if bid:
                    return bid
            if metric == "customer_match_rate":
                code = (p.customer_match or {}).get("matched_customer_code") if isinstance(p.customer_match, dict) else None
                if code:
                    bid = match_baseline_id(db, metric, f"customer:{code}")
                    if bid:
                        return bid
    # Global fallback for the metric.
    return match_baseline_id(db, metric, "global")


# ──────────────────────────────────────────────────────────────────────────
# One-shot backfill. Runs at startup after seed_defaults. Walks each of
# the five signal tables and fills any NULL baseline_id by joining on
# (metric, segment). Idempotent — only touches NULL rows so admin edits
# survive subsequent restarts.
# ──────────────────────────────────────────────────────────────────────────

def backfill_baseline_ids(db: Session) -> dict[str, int]:
    """Idempotent backfill of baseline_id across DriftAlert,
    LearningOpportunity, ABExperiment, RCATicket, Feedback.

    Returns a per-table count of rows updated. Safe to call repeatedly; only
    NULL columns are touched.
    """
    from ..models import (
        ABExperiment,
        DriftAlert,
        Feedback,
        LearningOpportunity,
        RCATicket,
    )

    # Force a fresh index in case baselines were just seeded.
    invalidate_baseline_index()
    out = {
        "drift_alerts": 0,
        "learning_opportunities": 0,
        "ab_experiments": 0,
        "rca_tickets": 0,
        "feedback": 0,
    }

    # DriftAlert: metric + segment are stamped on the row directly.
    for r in db.query(DriftAlert).filter(DriftAlert.baseline_id.is_(None)).all():
        bid = match_baseline_id(db, r.metric, r.segment)
        if bid:
            r.baseline_id = bid
            out["drift_alerts"] += 1

    # LearningOpportunity: prefer the linked DriftAlert's anchor; fall back to
    # parsing the segment when no link is available.
    for r in db.query(LearningOpportunity).filter(LearningOpportunity.baseline_id.is_(None)).all():
        bid: int | None = None
        if r.linked_drift_alert_id:
            alert = db.get(DriftAlert, r.linked_drift_alert_id)
            if alert is not None and alert.baseline_id:
                bid = alert.baseline_id
            elif alert is not None:
                bid = match_baseline_id(db, alert.metric, alert.segment)
        if bid is None:
            # Opportunity carries only segment; metric is implicit. Try every
            # known metric for this segment and prefer the most specific.
            seg = r.segment or "global"
            idx = _ensure_index(db)
            for (m, s), candidate_id in idx.items():
                if s == seg:
                    bid = candidate_id
                    break
        if bid:
            r.baseline_id = bid
            out["learning_opportunities"] += 1

    # ABExperiment: copy from the linked opportunity when present.
    for r in db.query(ABExperiment).filter(ABExperiment.baseline_id.is_(None)).all():
        bid = None
        if r.linked_opportunity_id:
            opp = db.get(LearningOpportunity, r.linked_opportunity_id)
            if opp is not None and opp.baseline_id:
                bid = opp.baseline_id
        if bid is None:
            seg = r.segment or "global"
            idx = _ensure_index(db)
            for (m, s), candidate_id in idx.items():
                if s == seg:
                    bid = candidate_id
                    break
        if bid:
            r.baseline_id = bid
            out["ab_experiments"] += 1

    # RCATicket: metric + segment available directly on the row.
    for r in db.query(RCATicket).filter(RCATicket.baseline_id.is_(None)).all():
        bid = match_baseline_id(db, r.metric, r.segment)
        if not bid and r.source_kind == "drift_alert" and r.source_id:
            alert = db.get(DriftAlert, r.source_id)
            if alert is not None and alert.baseline_id:
                bid = alert.baseline_id
        if bid:
            r.baseline_id = bid
            out["rca_tickets"] += 1

    # Feedback: derive heuristically since these rows don't have a metric on
    # them directly.
    for r in db.query(Feedback).filter(Feedback.baseline_id.is_(None)).all():
        bid = derive_feedback_baseline_id(db, r)
        if bid:
            r.baseline_id = bid
            out["feedback"] += 1

    if any(out.values()):
        db.commit()
        log.info(
            "baselines: backfilled anchors — alerts=%d opps=%d exps=%d rca=%d feedback=%d",
            out["drift_alerts"], out["learning_opportunities"], out["ab_experiments"],
            out["rca_tickets"], out["feedback"],
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Concept-baseline consolidation. The prior shape carried one Baseline row
# per (metric, segment) pair. The consolidated shape carries one row per
# concept at segment="global" and rolls up per-segment evidence at
# evaluation time. This migration collapses any leftover per-segment rows
# into the concept row for the same metric, re-stamping every dependent
# signal (drift alerts, opportunities, experiments, RCA tickets, feedback)
# to point at the concept row.
# ──────────────────────────────────────────────────────────────────────────

def consolidate_to_concept_baselines(db: Session) -> dict[str, int]:
    """Collapse legacy per-segment baselines into the concept baseline for
    the same metric and re-stamp every dependent signal anchor.

    The seed file defines the canonical concept-level metric vocabulary at
    segment="global". This migration:
      * collapses every per-segment row into the concept row for its
        matching metric,
      * remaps legacy metric names that have been retired into the
        closest concept replacement (for example `classification_accuracy`
        rolls into `intent_classification_accuracy`,
        `sla_adherence_p95_ms` rolls into `p95_stage_latency_ms`),
      * removes redundant global rows whose concept is covered by a
        different metric (for example `hitl_rate` and `hitl_queue_depth`
        roll into `hitl_resolution_p95_hours`).

    Idempotent. When all rows already sit at the concept vocabulary the
    function is a no-op and returns zeros across the board.

    Returns counts: {legacy_rows_removed, drift_alerts, learning_opportunities,
                     ab_experiments, rca_tickets, feedback}.
    """
    from ..models import (
        ABExperiment,
        Baseline,
        DriftAlert,
        Feedback,
        LearningOpportunity,
        RCATicket,
    )

    # Retired metric vocabulary mapped onto the concept replacement. Any
    # baseline carrying one of these legacy metric names is rolled into
    # the concept baseline for the mapped metric. Keep this list small;
    # use it only for genuine consolidations.
    _RETIRED_METRIC_MAP = {
        "classification_accuracy": "intent_classification_accuracy",
        "sla_adherence_p95_ms": "p95_stage_latency_ms",
        "hitl_rate": "hitl_resolution_p95_hours",
        "hitl_queue_depth": "hitl_resolution_p95_hours",
        "stage_hitl_fire_rate": "hitl_resolution_p95_hours",
        "stage_queue_depth": "p95_stage_latency_ms",
        "aioa_fail_rate": "aioa_handoff_success_rate",
    }

    out = {
        "legacy_rows_removed": 0,
        "drift_alerts": 0,
        "learning_opportunities": 0,
        "ab_experiments": 0,
        "rca_tickets": 0,
        "feedback": 0,
    }

    # Build a metric -> concept baseline id map. The concept row is the
    # one at segment="global". When no global row exists for a metric we
    # leave the legacy row in place rather than orphaning its signals.
    concept_by_metric: dict[str, int] = {}
    for b in db.query(Baseline).filter(Baseline.segment == "global").all():
        concept_by_metric[b.metric] = b.id

    # Locate every baseline that is not a canonical concept row. This
    # covers per-segment rows AND legacy global rows whose metric has
    # been retired in favour of a concept replacement.
    candidates: list[Baseline] = []
    for r in db.query(Baseline).all():
        if r.segment != "global":
            candidates.append(r)
            continue
        if r.metric in _RETIRED_METRIC_MAP:
            candidates.append(r)

    # Collapse any duplicate open alerts sharing the same concept
    # fingerprint. The detector keeps a single open row per fingerprint;
    # legacy data may carry several so we resolve the older ones in
    # favour of the most recently updated row. Idempotent.
    from sqlalchemy import func as _sql_func
    duplicate_groups = (
        db.query(
            DriftAlert.fingerprint,
            _sql_func.count(DriftAlert.id).label("n"),
        )
        .filter(DriftAlert.fingerprint.like("baseline:%"))
        .filter(DriftAlert.status == "open")
        .group_by(DriftAlert.fingerprint)
        .having(_sql_func.count(DriftAlert.id) > 1)
        .all()
    )
    for fp, _n in duplicate_groups:
        members = (
            db.query(DriftAlert)
            .filter(DriftAlert.fingerprint == fp)
            .filter(DriftAlert.status == "open")
            .order_by(DriftAlert.updated_at.desc(), DriftAlert.id.desc())
            .all()
        )
        keeper = members[0]
        for older in members[1:]:
            older.status = "resolved"
            older.resolved_at = datetime.utcnow()
            older.resolved_by = "system:concept_consolidation"
            older.note = (
                f"auto-resolved: superseded by concept-baseline alert "
                f"#{keeper.id}"
            )

    # Realign any drift alert whose anchor already points at a concept
    # row but whose fingerprint still carries the legacy per-segment
    # form. Without this, the next detector pass writes a fresh alert at
    # the concept fingerprint and the legacy alert sits open forever.
    # Idempotent: alerts already at the concept fingerprint are skipped.
    concept_baselines = {
        b.id: b for b in db.query(Baseline).filter(Baseline.segment == "global").all()
    }
    open_legacy_alerts = (
        db.query(DriftAlert)
        .filter(DriftAlert.fingerprint.like("baseline:%"))
        .filter(DriftAlert.status == "open")
        .all()
    )
    for a in open_legacy_alerts:
        concept = concept_baselines.get(a.baseline_id) if a.baseline_id else None
        if concept is None:
            continue
        expected_fp = f"baseline:{concept.metric}:{concept.segment}"
        # Populate top_contributors from the concept baseline's freshest
        # per-segment evidence so realigned alerts carry a meaningful
        # breakdown even between detector passes.
        if not a.top_contributors and concept.segments_observed:
            scoped = [
                s for s in (concept.segments_observed or [])
                if isinstance(s, dict) and s.get("segment") and s["segment"] != "global"
            ]
            direction = (concept.direction or "min").lower()

            def _worst_key(c):
                observed = c.get("observed")
                if observed is None:
                    return float("inf") if direction == "min" else float("-inf")
                return float(observed) if direction == "min" else -float(observed)

            a.top_contributors = sorted(scoped, key=_worst_key)[:5]
        if a.fingerprint == expected_fp:
            continue
        # Collapse into any existing alert at the concept fingerprint.
        duplicate = (
            db.query(DriftAlert)
            .filter(
                DriftAlert.fingerprint == expected_fp,
                DriftAlert.id != a.id,
                DriftAlert.status == "open",
            )
            .first()
        )
        if duplicate is not None:
            a.status = "resolved"
            a.resolved_at = datetime.utcnow()
            a.resolved_by = "system:concept_consolidation"
            a.note = "auto-resolved: superseded by concept-baseline alert"
        else:
            a.fingerprint = expected_fp
            a.metric = concept.metric

    # Sync the seed definition onto the concept rows so the refactor's
    # design table (target_value, severity, rationale, rollup_strategy,
    # label, drift_pct) lands authoritatively even when the row predated
    # the refactor. Idempotent: replays produce the same end state.
    from ..kb_seeds.baselines import all_baselines as _seed_rows
    for row in _seed_rows():
        b = (
            db.query(Baseline)
            .filter(Baseline.metric == row["metric"], Baseline.segment == row["segment"])
            .first()
        )
        if not b:
            continue
        b.target_value = float(row["target_value"])
        b.drift_pct = float(row.get("drift_pct", 5.0))
        b.severity = row.get("severity", "warn")
        b.direction = row["direction"]
        b.source = row.get("source", b.source)
        b.unit = row.get("unit", b.unit)
        b.label = row.get("label", b.label)
        b.rationale = row.get("rationale", b.rationale)
        b.rollup_strategy = row.get("rollup_strategy", "weighted_avg")
        b.updated_by = "system_consolidation"

    if not candidates:
        db.commit()
        return out

    legacy_id_to_concept_id: dict[int, int] = {}
    legacy_ids_to_delete: list[int] = []
    for r in candidates:
        target_metric = _RETIRED_METRIC_MAP.get(r.metric, r.metric)
        target_id = concept_by_metric.get(target_metric)
        if target_id is None:
            # No concept row to absorb this signal; leave the legacy row
            # untouched so its history is preserved.
            continue
        if target_id == r.id:
            # Concept row already; nothing to do.
            continue
        legacy_id_to_concept_id[r.id] = target_id
        legacy_ids_to_delete.append(r.id)

    if not legacy_id_to_concept_id:
        return out

    # Re-stamp every dependent signal table. The legacy row id moves to
    # the concept row id so the existing drill-through, timeline, and
    # promotion-gate queries keep working without further joins. For
    # DriftAlert specifically we also realign the fingerprint and segment
    # onto the concept row so subsequent detector passes idempotently
    # update the same alert instead of orphaning it next to a fresh one.
    legacy_to_concept_baseline = {
        bid: db.get(Baseline, cid)
        for bid, cid in legacy_id_to_concept_id.items()
    }
    for r in db.query(DriftAlert).filter(DriftAlert.baseline_id.in_(legacy_ids_to_delete)).all():
        concept = legacy_to_concept_baseline.get(r.baseline_id)
        r.baseline_id = legacy_id_to_concept_id[r.baseline_id]
        if concept is not None:
            new_fp = f"baseline:{concept.metric}:{concept.segment}"
            # When an open alert already exists at the concept fingerprint
            # we collapse the legacy alert into it: mark legacy resolved
            # with a note. This avoids two parallel open rows for the
            # same baseline.
            from sqlalchemy import and_
            duplicate = (
                db.query(DriftAlert)
                .filter(
                    DriftAlert.fingerprint == new_fp,
                    DriftAlert.id != r.id,
                    DriftAlert.status == "open",
                )
                .first()
            )
            if duplicate is not None and (r.status or "").lower() == "open":
                r.status = "resolved"
                r.resolved_at = datetime.utcnow()
                r.resolved_by = "system:concept_consolidation"
                r.note = "auto-resolved: superseded by concept-baseline alert"
            else:
                r.fingerprint = new_fp
                r.metric = concept.metric
                # Preserve the legacy segment string on the alert so the
                # historical context (which per-segment row first
                # surfaced this) stays visible in the timeline.
        out["drift_alerts"] += 1

    for r in db.query(LearningOpportunity).filter(LearningOpportunity.baseline_id.in_(legacy_ids_to_delete)).all():
        r.baseline_id = legacy_id_to_concept_id[r.baseline_id]
        out["learning_opportunities"] += 1

    for r in db.query(ABExperiment).filter(ABExperiment.baseline_id.in_(legacy_ids_to_delete)).all():
        r.baseline_id = legacy_id_to_concept_id[r.baseline_id]
        out["ab_experiments"] += 1

    for r in db.query(RCATicket).filter(RCATicket.baseline_id.in_(legacy_ids_to_delete)).all():
        r.baseline_id = legacy_id_to_concept_id[r.baseline_id]
        out["rca_tickets"] += 1

    for r in db.query(Feedback).filter(Feedback.baseline_id.in_(legacy_ids_to_delete)).all():
        r.baseline_id = legacy_id_to_concept_id[r.baseline_id]
        out["feedback"] += 1

    # Delete the legacy per-segment rows. Done after re-stamping so any
    # in-flight read sees a consistent FK target.
    if legacy_ids_to_delete:
        db.query(Baseline).filter(Baseline.id.in_(legacy_ids_to_delete)).delete(
            synchronize_session=False
        )
        out["legacy_rows_removed"] = len(legacy_ids_to_delete)

    db.commit()
    invalidate_baseline_index()
    log.info(
        "baselines: consolidated to concept-level. removed=%d alerts=%d opps=%d exps=%d rca=%d feedback=%d",
        out["legacy_rows_removed"], out["drift_alerts"], out["learning_opportunities"],
        out["ab_experiments"], out["rca_tickets"], out["feedback"],
    )
    return out
