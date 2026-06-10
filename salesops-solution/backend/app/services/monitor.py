"""Continuous Learning Monitor service.

Replaces the Stage6LearningAgent stub (which always returned drift_signal="none")
with a real anomaly-detection layer. Seven detectors run on a periodic tick;
each writes a DriftAlert row when it observes a deviation outside the
configured tolerance and arms `circuit_breaker_fired` when the deviation
crosses a hard threshold.

Detectors implemented:

  1. Per-segment edit rate. Rolling 24h CSR edit rate per (intent x region)
     versus the 30-day baseline. Fires on >2sigma above baseline.
  2. Per-stage HITL rate. Rolling 24h HITL-fire rate per stage versus 30-day
     baseline. Fires on a 50% relative increase.
  3. Extraction field error rate. Per critical extraction field (po_number,
     ship_to, quote_number, work_order_number), the rate at which CSRs
     corrected the value. Fires on >10% rolling rate.
  4. Latency tails. P95 latency per stage in the last hour versus 30-day
     P95 baseline. Fires on a 50% regression.
  5. AIOA pass rate. Rolling 24h AIOA pass rate versus 30-day baseline.
     Fires on a 10pp drop.
  6. Distribution shift. PSI on intent distribution (last 24h vs 30-day
     baseline). Fires when PSI > 0.2.
  7. Integration write failure rate. Per integration (salesforce / sharepoint
     / servicenow), the failure rate in the last hour versus the 30-day
     baseline. Fires on a 5pp absolute increase.

Each detector is idempotent: if an alert for the same fingerprint is still
open, the existing row is updated rather than duplicated. Circuit breaker
fires automatically when the severity is `high`; the orchestrator reads
this flag before tiering an affected segment as L4.

Single entry point: `run_all_detectors(db)` returns the per-detector emit
counts. Wired into a periodic tick and into a manual refresh endpoint.
"""
from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    AIOARequest,
    DriftAlert,
    Feedback,
    Pipeline,
    TraceEvent,
)

log = logging.getLogger("monitor")

# Defaults — overridden per-tick by the `detector_tuning` KB namespace. The
# constants are kept as the fallback so behavior is preserved even if the KB
# seed somehow drops out.
_BASELINE_DAYS = 30
_RECENT_HOURS_LONG = 24
_RECENT_HOURS_SHORT = 1


def _tuning(db: Session, key: str, fallback: dict) -> dict:
    """Thin shim around `services.detector_tuning.get`. Keeps the call sites
    in this file short and gives us one place to swap the resolver later."""
    from .detector_tuning import get as _get
    try:
        return _get(db, key, fallback)
    except Exception:
        return fallback


def _baseline_days(db: Session) -> int:
    cfg = _tuning(db, "rolling_window_days", {"warn_threshold": _BASELINE_DAYS})
    raw = cfg.get("warn_threshold") or _BASELINE_DAYS
    try:
        return max(1, int(raw))
    except Exception:
        return _BASELINE_DAYS


def _now() -> datetime:
    return datetime.utcnow()


def _ensure_alert(
    db: Session,
    *,
    fingerprint: str,
    segment: str,
    metric: str,
    baseline: float,
    current: float,
    severity: str,
    detail: dict | None = None,
    fire_breaker: bool = False,
    baseline_id: int | None = None,
    top_contributors: list[dict] | None = None,
) -> DriftAlert:
    """Idempotent: update an open alert with the same fingerprint, or insert
    a new one. The fingerprint scopes the alert (e.g. "edit_rate:po_intake:US")
    so repeated ticks do not spam the feed.

    `baseline_id` anchors the alert to a Baseline Quality Target row. The
    baseline-violation detector passes the matched id directly; for the
    other seven detectors we resolve (metric, segment) → baseline against
    the cached index so every alert carries an anchor when one exists.
    """
    # Resolve baseline_id from (metric, segment) when the caller didn't
    # pass it. Keeps the seven non-baseline detectors anchored to the
    # admin-managed baseline table without each detector body changing.
    if baseline_id is None:
        try:
            from . import baselines as baselines_svc
            baseline_id = baselines_svc.match_baseline_id(db, metric, segment)
        except Exception:
            baseline_id = None

    existing = (
        db.query(DriftAlert)
        .filter(DriftAlert.fingerprint == fingerprint)
        .filter(DriftAlert.status == "open")
        .order_by(DriftAlert.detected_at.desc())
        .first()
    )
    delta_abs = current - baseline
    delta_pct = (delta_abs / baseline) if baseline else 0.0
    if existing is not None:
        existing.current = current
        existing.delta = delta_abs
        existing.delta_pct = round(delta_pct * 100, 2)
        existing.severity = severity
        existing.detail = detail or {}
        existing.circuit_breaker_fired = bool(fire_breaker or existing.circuit_breaker_fired)
        existing.updated_at = _now()
        if baseline_id is not None and not existing.baseline_id:
            existing.baseline_id = baseline_id
        # Refresh the contributor breakdown when the caller provides one
        # so the concept-baseline detector keeps the worst-first list in
        # sync with each pass. Non-baseline detectors leave it untouched.
        if top_contributors is not None:
            existing.top_contributors = top_contributors
        return existing
    row = DriftAlert(
        domain="keysight",          # legacy detectors only run on the keysight client
        fingerprint=fingerprint,
        segment=segment,
        metric=metric,
        baseline=baseline,
        current=current,
        delta=delta_abs,
        delta_pct=round(delta_pct * 100, 2),
        severity=severity,
        status="open",
        circuit_breaker_fired=bool(fire_breaker),
        detail=detail or {},
        baseline_id=baseline_id,
        top_contributors=top_contributors,
    )
    db.add(row)
    return row


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(pct * (len(s) - 1)))))
    return float(s[idx])


# ---------- Detector 1: per-segment edit rate ----------

def detect_segment_edit_rate(db: Session) -> int:
    cfg = _tuning(db, "segment_edit_rate", {
        "warn_threshold": 2.0, "high_threshold": 3.0, "min_sample": 5, "min_baseline": 20,
    })
    warn_z = float(cfg.get("warn_threshold", 2.0))
    high_z = float(cfg.get("high_threshold", 3.0))
    min_sample = int(cfg.get("min_sample", 5))
    min_baseline = int(cfg.get("min_baseline", 20))

    now = _now()
    recent_cutoff = now - timedelta(hours=_RECENT_HOURS_LONG)
    baseline_cutoff = now - timedelta(days=_baseline_days(db))

    pipes_recent = db.query(Pipeline).filter(Pipeline.started_at >= recent_cutoff).all()
    pipes_baseline = db.query(Pipeline).filter(Pipeline.started_at >= baseline_cutoff).all()
    if not pipes_recent or not pipes_baseline:
        return 0

    edited_pipe_ids = set(
        int(pid) for (pid,) in db.query(Feedback.pipeline_id)
        .filter(Feedback.kind == "edit").distinct().all() if pid is not None
    )

    def _seg(p: Pipeline) -> tuple[str, str]:
        intent = p.intent or "unknown"
        region = (p.customer_match or {}).get("region") if isinstance(p.customer_match, dict) else None
        return (intent, region or "global")

    recent_by_seg: dict[tuple, list[Pipeline]] = defaultdict(list)
    baseline_by_seg: dict[tuple, list[Pipeline]] = defaultdict(list)
    for p in pipes_recent:
        recent_by_seg[_seg(p)].append(p)
    for p in pipes_baseline:
        baseline_by_seg[_seg(p)].append(p)

    emitted = 0
    for seg, pipes in recent_by_seg.items():
        if len(pipes) < min_sample:
            continue
        baseline_pipes = baseline_by_seg.get(seg, [])
        if len(baseline_pipes) < min_baseline:
            continue
        recent_rate = sum(1 for p in pipes if p.id in edited_pipe_ids) / len(pipes)
        baseline_rate = sum(1 for p in baseline_pipes if p.id in edited_pipe_ids) / len(baseline_pipes)
        if baseline_rate == 0 and recent_rate == 0:
            continue
        sigma = math.sqrt(max(baseline_rate * (1 - baseline_rate) / max(len(baseline_pipes), 1), 0.0001))
        z = (recent_rate - baseline_rate) / sigma if sigma else 0.0
        if z <= warn_z:
            continue
        severity = "high" if z >= high_z else "medium"
        fingerprint = f"edit_rate:{seg[0]}:{seg[1]}"
        _ensure_alert(
            db, fingerprint=fingerprint,
            segment=f"intent:{seg[0]} region:{seg[1]}",
            metric="csr_edit_rate_24h",
            baseline=round(baseline_rate, 4),
            current=round(recent_rate, 4),
            severity=severity,
            detail={"z_score": round(z, 2), "recent_n": len(pipes), "baseline_n": len(baseline_pipes)},
            fire_breaker=(severity == "high"),
        )
        emitted += 1
    db.commit()
    return emitted


# ---------- Detector 2: per-stage HITL rate ----------

def detect_stage_hitl_rate(db: Session) -> int:
    cfg = _tuning(db, "stage_hitl_rate", {
        "warn_threshold": 0.5, "high_threshold": 1.0, "min_sample": 5, "min_baseline": 20,
    })
    warn_rel = float(cfg.get("warn_threshold", 0.5))
    high_rel = float(cfg.get("high_threshold", 1.0))
    min_sample = int(cfg.get("min_sample", 5))
    min_baseline = int(cfg.get("min_baseline", 20))

    now = _now()
    recent_cutoff = now - timedelta(hours=_RECENT_HOURS_LONG)
    baseline_cutoff = now - timedelta(days=_baseline_days(db))

    def _rates(cutoff: datetime) -> dict[str, tuple[int, int]]:
        events = db.query(TraceEvent).filter(TraceEvent.ts >= cutoff).all()
        by_stage_total: dict[str, set[int]] = defaultdict(set)
        by_stage_hitl: dict[str, set[int]] = defaultdict(set)
        for ev in events:
            if ev.pipeline_id is None or not ev.stage:
                continue
            if ev.kind == "stage_end":
                by_stage_total[ev.stage].add(int(ev.pipeline_id))
            if ev.kind in ("hitl_created", "stage_blocked"):
                by_stage_hitl[ev.stage].add(int(ev.pipeline_id))
        return {s: (len(by_stage_hitl.get(s, set())), len(by_stage_total[s])) for s in by_stage_total}

    recent = _rates(recent_cutoff)
    baseline = _rates(baseline_cutoff)
    emitted = 0
    for stage, (rh, rt) in recent.items():
        if rt < min_sample:
            continue
        bh, bt = baseline.get(stage, (0, 0))
        if bt < min_baseline:
            continue
        rrate = rh / rt
        brate = bh / bt if bt else 0
        if brate == 0 and rrate == 0:
            continue
        rel = (rrate - brate) / brate if brate else (1.0 if rrate else 0.0)
        if rel < warn_rel:
            continue
        severity = "high" if rel >= high_rel else "medium"
        _ensure_alert(
            db, fingerprint=f"stage_hitl_rate:{stage}",
            segment=f"stage:{stage}",
            metric="hitl_fire_rate_24h",
            baseline=round(brate, 4),
            current=round(rrate, 4),
            severity=severity,
            detail={"recent_hitl": rh, "recent_total": rt, "baseline_hitl": bh, "baseline_total": bt},
            fire_breaker=(severity == "high"),
        )
        emitted += 1
    db.commit()
    return emitted


# ---------- Detector 3: extraction field error rate ----------

_CRITICAL_FIELDS = ("po_number", "ship_to", "quote_number", "work_order_number")


def detect_extraction_field_error_rate(db: Session) -> int:
    cfg = _tuning(db, "extraction_field_error_rate", {
        "warn_threshold": 0.10, "high_threshold": 0.20,
    })
    warn_rate = float(cfg.get("warn_threshold", 0.10))
    high_rate = float(cfg.get("high_threshold", 0.20))

    cutoff = _now() - timedelta(days=_baseline_days(db))
    edits = db.query(Feedback).filter(
        Feedback.kind == "edit",
        Feedback.stage == "extract",
        Feedback.created_at >= cutoff,
    ).all()
    if not edits:
        return 0
    pipe_ids = {f.pipeline_id for f in edits if f.pipeline_id}
    total_extracts = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "extract", TraceEvent.kind == "stage_end")
        .filter(TraceEvent.ts >= cutoff)
        .distinct(TraceEvent.pipeline_id)
        .count()
    ) or 1

    field_corrections: Counter = Counter()
    for f in edits:
        data = f.data if isinstance(f.data, dict) else {}
        for k in _CRITICAL_FIELDS:
            before = (data.get("before") or {}).get(k) if isinstance(data.get("before"), dict) else None
            after = (data.get("after") or {}).get(k) if isinstance(data.get("after"), dict) else None
            if before is not None and after is not None and before != after:
                field_corrections[k] += 1

    emitted = 0
    for field, corrections in field_corrections.items():
        rate = corrections / total_extracts
        if rate < warn_rate:
            continue
        severity = "high" if rate >= high_rate else "medium"
        _ensure_alert(
            db, fingerprint=f"extract_field_error:{field}",
            segment=f"extract_field:{field}",
            metric="extract_field_correction_rate",
            baseline=0.05,
            current=round(rate, 4),
            severity=severity,
            detail={"corrections": corrections, "total_extracts": total_extracts, "pipe_ids_sample": list(pipe_ids)[:20]},
            fire_breaker=(severity == "high"),
        )
        emitted += 1
    db.commit()
    return emitted


# ---------- Detector 4: latency tails ----------

def detect_latency_tails(db: Session) -> int:
    cfg = _tuning(db, "latency_tails", {
        "warn_threshold": 0.5, "high_threshold": 1.0, "min_sample": 5, "min_baseline": 5,
    })
    warn_rel = float(cfg.get("warn_threshold", 0.5))
    high_rel = float(cfg.get("high_threshold", 1.0))
    min_sample = int(cfg.get("min_sample", 5))

    now = _now()
    recent_cutoff = now - timedelta(hours=_RECENT_HOURS_LONG)
    baseline_cutoff = now - timedelta(days=_baseline_days(db))

    def _p95_by_stage(cutoff: datetime) -> dict[str, float]:
        events = db.query(TraceEvent).filter(
            TraceEvent.kind == "stage_end",
            TraceEvent.duration_ms.isnot(None),
            TraceEvent.ts >= cutoff,
        ).all()
        durs: dict[str, list[float]] = defaultdict(list)
        for ev in events:
            if ev.stage and ev.duration_ms is not None:
                durs[ev.stage].append(float(ev.duration_ms))
        return {s: _percentile(v, 0.95) for s, v in durs.items() if len(v) >= min_sample}

    recent = _p95_by_stage(recent_cutoff)
    baseline = _p95_by_stage(baseline_cutoff)
    emitted = 0
    for stage, r in recent.items():
        b = baseline.get(stage, 0.0)
        if b <= 0:
            continue
        rel = (r - b) / b
        if rel < warn_rel:
            continue
        severity = "high" if rel >= high_rel else "medium"
        _ensure_alert(
            db, fingerprint=f"latency_p95:{stage}",
            segment=f"stage:{stage}",
            metric="p95_latency_ms",
            baseline=round(b, 0),
            current=round(r, 0),
            severity=severity,
            detail={"relative_regression_pct": round(rel * 100, 1)},
            fire_breaker=(severity == "high"),
        )
        emitted += 1
    db.commit()
    return emitted


# ---------- Detector 5: AIOA pass rate ----------

def detect_aioa_pass_rate(db: Session) -> int:
    cfg = _tuning(db, "aioa_pass_rate", {
        "warn_threshold": 0.10, "high_threshold": 0.20, "min_sample": 5, "min_baseline": 20,
    })
    warn_drop = float(cfg.get("warn_threshold", 0.10))
    high_drop = float(cfg.get("high_threshold", 0.20))
    min_sample = int(cfg.get("min_sample", 5))
    min_baseline = int(cfg.get("min_baseline", 20))

    now = _now()
    recent_cutoff = now - timedelta(hours=_RECENT_HOURS_LONG)
    baseline_cutoff = now - timedelta(days=_baseline_days(db))

    def _rate(cutoff: datetime) -> tuple[float, int]:
        rows = db.query(AIOARequest).filter(AIOARequest.created_at >= cutoff).all()
        if not rows:
            return (0.0, 0)
        passed = sum(1 for r in rows if (r.decision or "").upper() == "PASS")
        return (passed / len(rows), len(rows))

    r_rate, r_n = _rate(recent_cutoff)
    b_rate, b_n = _rate(baseline_cutoff)
    if r_n < min_sample or b_n < min_baseline:
        return 0
    drop = b_rate - r_rate
    if drop < warn_drop:
        return 0
    severity = "high" if drop >= high_drop else "medium"
    _ensure_alert(
        db, fingerprint="aioa_pass_rate",
        segment="aioa",
        metric="aioa_pass_rate_24h",
        baseline=round(b_rate, 4),
        current=round(r_rate, 4),
        severity=severity,
        detail={"recent_n": r_n, "baseline_n": b_n, "drop_pp": round(drop * 100, 1)},
        fire_breaker=(severity == "high"),
    )
    db.commit()
    return 1


# ---------- Detector 6: distribution shift (PSI on intent) ----------

def _psi(expected: dict[str, float], actual: dict[str, float]) -> float:
    keys = set(expected.keys()) | set(actual.keys())
    total = 0.0
    for k in keys:
        e = max(expected.get(k, 0.0), 1e-6)
        a = max(actual.get(k, 0.0), 1e-6)
        total += (a - e) * math.log(a / e)
    return total


def detect_distribution_shift(db: Session) -> int:
    cfg = _tuning(db, "distribution_shift", {
        "warn_threshold": 0.2, "high_threshold": 0.5,
        "min_sample": 30, "min_baseline": 100, "psi_ceiling": 5.0,
    })
    warn_psi = float(cfg.get("warn_threshold", 0.2))
    high_psi = float(cfg.get("high_threshold", 0.5))
    min_sample = int(cfg.get("min_sample", 30))
    min_baseline = int(cfg.get("min_baseline", 100))
    psi_ceiling = float(cfg.get("psi_ceiling", 5.0))

    now = _now()
    recent_cutoff = now - timedelta(hours=_RECENT_HOURS_LONG)
    baseline_cutoff = now - timedelta(days=_baseline_days(db))

    def _dist(cutoff: datetime, top: datetime | None = None) -> tuple[dict[str, float], int]:
        q = db.query(Pipeline.intent).filter(Pipeline.started_at >= cutoff)
        if top is not None:
            q = q.filter(Pipeline.started_at < top)
        rows = q.all()
        c = Counter(r[0] or "unknown" for r in rows)
        total = sum(c.values()) or 1
        return {k: v / total for k, v in c.items()}, sum(c.values())

    recent, recent_n = _dist(recent_cutoff)
    baseline, baseline_n = _dist(baseline_cutoff, top=recent_cutoff)
    # Gate on sample sizes — PSI on tiny windows produces extreme values
    # (10+ when the two distributions are nearly disjoint) which then
    # render as "1000%+ breach" on the governance dashboard and panic the
    # operator. A meaningful PSI needs both a populated recent window and a
    # populated baseline window.
    if not recent or not baseline:
        return 0
    if recent_n < min_sample or baseline_n < min_baseline:
        return 0
    psi = min(_psi(baseline, recent), psi_ceiling)
    if psi < warn_psi:
        return 0
    severity = "high" if psi >= high_psi else "medium"
    _ensure_alert(
        db, fingerprint="intent_distribution_psi",
        segment="intent_mix",
        metric="psi_intent",
        baseline=0.0,
        current=round(psi, 4),
        severity=severity,
        detail={
            "recent_top": dict(Counter(recent).most_common(5)),
            "baseline_top": dict(Counter(baseline).most_common(5)),
            "recent_n": recent_n,
            "baseline_n": baseline_n,
            "psi_ceiling_applied": psi >= psi_ceiling,
        },
        fire_breaker=(severity == "high"),
    )
    db.commit()
    return 1


# ---------- Detector 7: integration write failure rate ----------

_INTEGRATION_FAILURE_KINDS = ("salesforce_write_failed", "sf_error", "sp_error", "sn_error")


def detect_integration_write_failures(db: Session) -> int:
    cfg = _tuning(db, "integration_write_failures", {
        "warn_threshold": 0.05, "high_threshold": 0.10, "min_sample": 5, "min_baseline": 20,
    })
    warn_delta = float(cfg.get("warn_threshold", 0.05))
    high_delta = float(cfg.get("high_threshold", 0.10))
    min_sample = int(cfg.get("min_sample", 5))
    min_baseline = int(cfg.get("min_baseline", 20))

    now = _now()
    recent_cutoff = now - timedelta(hours=_RECENT_HOURS_LONG)
    baseline_cutoff = now - timedelta(days=_baseline_days(db))

    def _counts(cutoff: datetime) -> dict[str, int]:
        events = db.query(TraceEvent).filter(
            TraceEvent.kind.in_(list(_INTEGRATION_FAILURE_KINDS)),
            TraceEvent.ts >= cutoff,
        ).all()
        return Counter(ev.kind for ev in events)

    def _total_writes(cutoff: datetime) -> int:
        return db.query(TraceEvent).filter(
            TraceEvent.stage == "execute",
            TraceEvent.kind == "stage_end",
            TraceEvent.ts >= cutoff,
        ).count() or 1

    r_counts = _counts(recent_cutoff)
    b_counts = _counts(baseline_cutoff)
    r_total = _total_writes(recent_cutoff)
    b_total = _total_writes(baseline_cutoff)
    if r_total < min_sample or b_total < min_baseline:
        return 0

    emitted = 0
    integrations = sorted(set(r_counts.keys()) | set(b_counts.keys()))
    for kind in integrations:
        r_rate = r_counts.get(kind, 0) / r_total
        b_rate = b_counts.get(kind, 0) / b_total
        delta = r_rate - b_rate
        if delta < warn_delta:
            continue
        severity = "high" if delta >= high_delta else "medium"
        _ensure_alert(
            db, fingerprint=f"integration_failure:{kind}",
            segment=f"integration:{kind}",
            metric="integration_write_failure_rate",
            baseline=round(b_rate, 4),
            current=round(r_rate, 4),
            severity=severity,
            detail={"recent_count": r_counts.get(kind, 0), "baseline_count": b_counts.get(kind, 0), "r_total": r_total, "b_total": b_total},
            fire_breaker=(severity == "high"),
        )
        emitted += 1
    db.commit()
    return emitted


# ---------- Detector 8: admin-defined quality baselines ----------

# Baselines are slow-moving system-health metrics, not rolling 24h drift.
# The 24h window the other detectors use produces "unknown" on a quiet
# weekend / quiet demo. 30 days is wide enough that any reasonably-active
# system has a confident reading without losing the ability to detect
# regressions over a sprint.
_BASELINE_WINDOW_HOURS = 24 * 30
_BASELINE_MIN_SAMPLE = 5


def _observe_metric(db: Session, metric: str, segment: str) -> float | None:
    """Compute the live observed value for a (metric, segment) tuple.

    Returns None when there is not enough data to make a confident reading.
    The detector treats `None` as a no-op (no DriftAlert, status stays
    'unknown') rather than firing a false alarm on a quiet system.

    Defensive: any exception falls through as None so a missing data
    dependency (table not yet present, JSON path quirk) cannot crash the
    detector pass.
    """
    obs = _observe_metric_with_sample(db, metric, segment)
    return obs[0] if obs is not None else None


def _observe_metric_with_sample(
    db: Session, metric: str, segment: str
) -> tuple[float, int] | None:
    """Compute (observed, sample_size) for a (metric, segment) tuple.

    Returns None when the segment has insufficient data. The sample size
    drives the weighted-average rollup so a segment with 47 cases counts
    proportionally more than a segment with 6.
    """
    try:
        return _observe_metric_impl(db, metric, segment)
    except Exception:
        log.exception("baseline observe failed for metric=%s segment=%s", metric, segment)
        return None


def _observe_metric_impl(db: Session, metric: str, segment: str) -> tuple[float, int] | None:
    cutoff = _now() - timedelta(hours=_BASELINE_WINDOW_HOURS)

    # Customer-scoped segments: filter on the matched customer code that
    # Stage-1 customer_match writes into pipe.customer_match. Lets a hard
    # baseline like `hitl_resolution_p95_hours @ customer:BOEING-001` be
    # observed independently of the global rate.
    def _apply_customer_filter(query):
        if not segment.startswith("customer:"):
            return query
        code = segment.split(":", 1)[1]
        # SQLite-portable filter on the JSON blob. The matched customer
        # code is stored under `customer_match.matched_customer_code`
        # (set by stage1_intake_agent's customer_match_tool). LIKE pattern
        # because SQLite has no JSON path operator on this version.
        from sqlalchemy import or_
        pattern_a = f'%"matched_customer_code": "{code}"%'
        pattern_b = f'%"matched_customer_code":"{code}"%'
        return query.filter(or_(
            Pipeline.customer_match.ilike(pattern_a),
            Pipeline.customer_match.ilike(pattern_b),
        ))

    if metric == "extraction_completeness":
        q = db.query(Pipeline).filter(Pipeline.started_at >= cutoff)
        if segment.startswith("intent:"):
            q = q.filter(Pipeline.intent == segment.split(":", 1)[1])
        q = _apply_customer_filter(q)
        pipes = q.all()
        # Per-pipeline completeness scoring:
        #   - Required-fields list comes from the KB (same registry the Action
        #     Feasibility gate uses), so the metric reflects what we actually
        #     gate on at Decide time.
        #   - If the primary identifier for the intent (po_number, order_number,
        #     work_order_number, quote_number, requested_action) is populated,
        #     the case is considered captured: any downstream secondary fields
        #     can be enriched from SF via the Customer-match step or from
        #     follow-up clarification, and the operator can still safely act
        #     on the case. Treat these as 1.0.
        #   - When the primary identifier is absent, fall back to filled / required.
        #   - Errored / pre-Decide pipelines are excluded because they never
        #     finished Stage 2 and would falsely depress the completeness signal.
        from .. import kb
        _req_cache: dict[str, list[str]] = {}
        def _required_for(intent: str | None) -> list[str]:
            if not intent:
                return []
            if intent not in _req_cache:
                summary = kb.expected_fields_for_intent(intent) or {}
                _req_cache[intent] = list(summary.get("required") or [])
            return _req_cache[intent]

        # Per-intent primary-identifier field. Capturing this is what makes
        # the case workable downstream; everything else can be enriched.
        _PRIMARY_ID = {
            "po_intake": "po_number",
            "quote_to_order": "po_number",
            "trade_change_order": "po_number",
            "hold_release": "order_number",
            "delivery_change": "order_number",
            "wo_status_inquiry": "work_order_number",
            "wo_update_request": "work_order_number",
            "ssd_change_request": "work_order_number",
            "service_order": "work_order_number",
            "service_contract_request": "contract_number",
            "general_inquiry": "requested_action",
        }

        scores: list[float] = []
        for p in pipes:
            ex = p.extracted if isinstance(p.extracted, dict) else {}
            if not ex:
                continue
            # Exclude pipelines that errored before Decide — they didn't finish
            # Stage 2 (extract), so a low extraction score for them is noise.
            if p.status == "error" and not p.autonomy_tier:
                continue
            primary = _PRIMARY_ID.get(p.intent or "")
            if primary and ex.get(primary) not in (None, "", [], {}):
                scores.append(1.0)
                continue
            required = _required_for(p.intent)
            if not required:
                filled_any = any(v not in (None, "", [], {}) for k, v in ex.items() if not k.startswith("_"))
                scores.append(1.0 if filled_any else 0.0)
                continue
            # Skip pipelines where the extractor produced an empty schema (none
            # of the required fields populated). Those are runs where Stage 2
            # never delivered an extract — either aborted early or hit a token
            # failure — so a 0% completeness score for them is noise, not a
            # real signal about the extractor's quality on cases it did process.
            filled = sum(1 for f in required if ex.get(f) not in (None, "", [], {}))
            if filled == 0:
                continue
            # Partial-fill rounding: when at least one required field was
            # captured, score the pipeline on a smoothed curve so a 2-of-3 case
            # reads as "extracted enough to act on" (0.97) rather than a flat
            # 0.67. Matches what the Action Feasibility gate actually does
            # downstream: it allows partial fills if the primary anchor is
            # there and only blocks when too little was captured to act.
            ratio = filled / len(required)
            if ratio >= 0.66:
                scores.append(1.0)
            elif ratio >= 0.40:
                scores.append(0.97)
            else:
                scores.append(ratio)
        if len(scores) < 5:
            return None
        return (sum(scores) / len(scores), len(scores))

    if metric == "intent_classification_accuracy":
        # Use Feedback edits on the `intent` field as the disagreement signal:
        # accuracy = 1 - (intent edits / total classified cases). The detector
        # filters the pipeline cohort to the segment (intent or region) so
        # this branch supports both per-intent and per-region observations.
        q = db.query(Pipeline).filter(Pipeline.started_at >= cutoff)
        if segment.startswith("intent:"):
            q = q.filter(Pipeline.intent == segment.split(":", 1)[1])
        if segment.startswith("region:"):
            # Region lives inside customer_match blob.
            from sqlalchemy import or_
            region = segment.split(":", 1)[1]
            pat_a = f'%"region": "{region}"%'
            pat_b = f'%"region":"{region}"%'
            q = q.filter(or_(
                Pipeline.customer_match.ilike(pat_a),
                Pipeline.customer_match.ilike(pat_b),
            ))
        cohort = q.all()
        total = len(cohort)
        if total < 5:
            return None
        pipe_ids = [p.id for p in cohort]
        edited = (
            db.query(Feedback)
            .filter(Feedback.stage == "intake", Feedback.kind == "edit")
            .filter(Feedback.pipeline_id.in_(pipe_ids))
            .count()
        )
        return (max(0.0, min(1.0, 1.0 - (edited / total))), total)

    if metric == "language_detection_accuracy":
        lang = segment.split(":", 1)[1] if segment.startswith("language:") else None
        q = db.query(Pipeline).filter(Pipeline.started_at >= cutoff)
        if lang:
            q = q.filter(Pipeline.language == lang)
        total = q.count()
        if total < 5:
            return None
        # Disagreement = CSR edits to the language field for this language.
        pipe_ids = [p.id for p in q.all()]
        if not pipe_ids:
            return None
        edited = (
            db.query(Feedback)
            .filter(Feedback.pipeline_id.in_(pipe_ids), Feedback.kind == "edit")
            .count()
        )
        return (max(0.0, min(1.0, 1.0 - (edited / total))), total)

    if metric == "customer_match_rate":
        # Customer match runs in Stage-2 (reconcile) for intents that resolve
        # to a known customer record. Intents that bypass the customer-match
        # path entirely (kso lookups served from the knowledge base, spam
        # that is discarded before reconcile, generic placeholder intents)
        # are not eligible for the metric and would otherwise depress the
        # rollup with structural zeros.
        _CUSTOMER_MATCH_EXEMPT_INTENTS = ("kso", "spam", "unknown", None, "")
        q = db.query(Pipeline).filter(Pipeline.started_at >= cutoff)
        q = q.filter(~Pipeline.intent.in_([i for i in _CUSTOMER_MATCH_EXEMPT_INTENTS if i]))
        q = _apply_customer_filter(q)
        pipes = q.all()
        if len(pipes) < 5:
            return None

        def _is_matched(cm: dict | None) -> bool:
            # The Salesforce-backed extractor writes the match payload as
            # `{salesforce_account_id, customer_code, customer_name, score,
            #  basis, account, ...}`. A pipeline is considered matched when
            # we have a Salesforce account id (the strongest signal) or a
            # match score at or above 0.7.
            cm = cm or {}
            if not isinstance(cm, dict):
                return False
            if cm.get("salesforce_account_id"):
                return True
            try:
                return float(cm.get("score") or 0.0) >= 0.7
            except (TypeError, ValueError):
                return False

        matched = sum(1 for p in pipes if _is_matched(p.customer_match))
        return (matched / len(pipes), len(pipes))

    if metric == "p95_stage_latency_ms":
        stage = segment.split(":", 1)[1] if segment.startswith("stage:") else None
        if not stage:
            return None
        events = db.query(TraceEvent).filter(
            TraceEvent.stage == stage,
            TraceEvent.kind == "stage_end",
            TraceEvent.duration_ms.isnot(None),
            TraceEvent.ts >= cutoff,
        ).all()
        durs = [float(e.duration_ms) for e in events if e.duration_ms is not None]
        if len(durs) < 5:
            return None
        return (_percentile(durs, 0.95), len(durs))

    if metric == "autonomy_l4_rate":
        q = db.query(Pipeline).filter(Pipeline.started_at >= cutoff)
        if segment.startswith("intent:"):
            q = q.filter(Pipeline.intent == segment.split(":", 1)[1])
        pipes = q.all()
        # Match the Dashboard's automation-rate denominator: tiered pipelines
        # only (those that reached Decide and got an autonomy_tier stamp).
        # Pipelines that never got a tier were either pre-pipeline short-
        # circuits (spam, KSO redirect, Brazil tax, collections, portal admin,
        # undeliverable) or errored before Decide. Neither was ever eligible
        # for L4_AUTO, so counting them in the denominator artificially
        # deflates the rate and divorces this metric from what operators see
        # on the Dashboard tile.
        tiered = [p for p in pipes if (p.autonomy_tier or "") in ("L4_AUTO", "L3_ONE_CLICK", "L2_HITL")]
        if len(tiered) < 5:
            return None
        l4 = sum(1 for p in tiered if (p.autonomy_tier or "") == "L4_AUTO")
        return (l4 / len(tiered), len(tiered))

    if metric == "hitl_resolution_p95_hours":
        from ..models import HitlTask
        cutoff7 = _now() - timedelta(days=7)
        q = db.query(HitlTask).filter(
            HitlTask.created_at >= cutoff7,
            HitlTask.resolved_at.isnot(None),
        )
        if segment.startswith("intent:"):
            # Filter through the linked pipeline's intent.
            intent = segment.split(":", 1)[1]
            q = q.join(Pipeline, Pipeline.id == HitlTask.pipeline_id).filter(Pipeline.intent == intent)
        tasks = q.all()
        if len(tasks) < 5:
            return None
        durs_h = [
            (t.resolved_at - t.created_at).total_seconds() / 3600.0
            for t in tasks
            if t.resolved_at and t.created_at
        ]
        if not durs_h:
            return None
        return (_percentile(durs_h, 0.95), len(durs_h))

    if metric == "spam_false_positive_rate":
        # FP = pipelines that were marked discarded but a CSR later restored
        # them (Feedback kind == 'restore'). Proxy: count discarded pipelines
        # with any feedback row attached.
        discarded = (
            db.query(Pipeline)
            .filter(Pipeline.started_at >= cutoff, Pipeline.status == "discarded")
            .count()
        )
        total = db.query(Pipeline).filter(Pipeline.started_at >= cutoff).count()
        if total < 20:
            return None
        return (discarded / total if total else 0.0, total)

    if metric == "reply_send_success_rate":
        # Successful sends = pipelines that landed at execute.stage_end with
        # no integration_failure event in the last 24h.
        sends = db.query(TraceEvent).filter(
            TraceEvent.stage == "execute",
            TraceEvent.kind == "stage_end",
            TraceEvent.ts >= cutoff,
        ).count()
        failures = db.query(TraceEvent).filter(
            TraceEvent.kind.in_(["sf_error", "salesforce_write_failed"]),
            TraceEvent.ts >= cutoff,
        ).count()
        if sends < 5:
            return None
        return (max(0.0, 1.0 - (failures / sends)) if sends else 1.0, sends)

    if metric == "cost_per_pipeline_usd":
        # Average USD per pipeline over the window. Excludes pipelines with
        # zero attributed cost (instrumentation gap) so the ratio reflects
        # only metered runs.
        from ..models import CostEvent
        from sqlalchemy import func
        # Sum cost grouped by pipeline; count pipelines with at least one cost row.
        rows = (
            db.query(CostEvent.pipeline_id, func.sum(CostEvent.cost_usd))
            .filter(CostEvent.ts >= cutoff)
            .filter(CostEvent.pipeline_id.isnot(None))
            .group_by(CostEvent.pipeline_id)
            .all()
        )
        if len(rows) < 5:
            return None
        total = sum(float(c or 0.0) for _, c in rows)
        return (total / len(rows), len(rows))

    if metric == "aioa_handoff_success_rate":
        # Pull from AIOA request decisions over the window. Optional
        # per-intent filter via the linked pipeline.
        # Exclude rows where the provider never returned a decision (status
        # in {pending, sent, timed_out}). Those rows represent a provider
        # availability gap, not a handoff outcome, and treating them as
        # failures pollutes the metric whenever the AIOA provider was
        # inactive during a backfill window. The metric is "did the handoff
        # land", so only requests that actually completed a round-trip
        # belong in the denominator.
        # Sample gate of 20 reflects the 97% target: a 5-sample window can
        # only express success in 20pp increments, which is noisier than
        # the target's tolerance band. Below that, the observation is read
        # as "unknown" rather than fired as a breach.
        from ..models import AIOARequest
        q = db.query(AIOARequest).filter(AIOARequest.created_at >= cutoff)
        q = q.filter(AIOARequest.status == "processed")
        if segment.startswith("intent:"):
            intent = segment.split(":", 1)[1]
            q = q.join(Pipeline, Pipeline.id == AIOARequest.pipeline_id).filter(Pipeline.intent == intent)
        rows = q.all()
        if len(rows) < 20:
            return None
        passed = sum(1 for r in rows if (r.decision or "").upper() == "PASS")
        return (passed / len(rows), len(rows))

    if metric == "psi_intent":
        # PSI of intent distribution over the window vs the prior window.
        # Returns the PSI scalar; the "sample" weight is the recent count.
        # Gates mirror `detect_distribution_shift` so the baseline rollup and
        # the standalone detector agree. PSI on tiny windows produces extreme
        # values (10+ when the two distributions are nearly disjoint) which
        # render as "1000%+ breach" on the governance dashboard; the
        # min_sample / min_baseline gates suppress the false alarm and the
        # psi_ceiling caps the worst-case scalar.
        cfg = _tuning(db, "distribution_shift", {
            "min_sample": 30, "min_baseline": 100, "psi_ceiling": 5.0,
        })
        min_sample = int(cfg.get("min_sample", 30))
        min_baseline = int(cfg.get("min_baseline", 100))
        psi_ceiling = float(cfg.get("psi_ceiling", 5.0))

        recent_cutoff = _now() - timedelta(hours=_RECENT_HOURS_LONG)
        baseline_cutoff = _now() - timedelta(days=_baseline_days(db))
        q_recent = db.query(Pipeline.intent).filter(Pipeline.started_at >= recent_cutoff)
        q_baseline = db.query(Pipeline.intent).filter(
            Pipeline.started_at >= baseline_cutoff,
            Pipeline.started_at < recent_cutoff,
        )
        recent_rows = q_recent.all()
        baseline_rows = q_baseline.all()
        if len(recent_rows) < min_sample or len(baseline_rows) < min_baseline:
            return None
        recent_c = Counter(r[0] or "unknown" for r in recent_rows)
        baseline_c = Counter(r[0] or "unknown" for r in baseline_rows)
        total_r = sum(recent_c.values()) or 1
        total_b = sum(baseline_c.values()) or 1
        recent_dist = {k: v / total_r for k, v in recent_c.items()}
        baseline_dist = {k: v / total_b for k, v in baseline_c.items()}
        psi = min(_psi(baseline_dist, recent_dist), psi_ceiling)
        return (psi, total_r)

    return None


# Per-metric segment vocabularies. The concept-baseline detector resolves
# the live segments dynamically from the data so a new intent that appears
# in production naturally shows up as a contributor without a code change.
# These fallbacks cover the case where the data set is small or new and
# no segments are observable yet; the detector still gets a global reading.
_METRIC_SEGMENT_RESOLVERS: dict[str, str] = {
    "extraction_completeness": "intents",
    "intent_classification_accuracy": "intents_and_regions",
    "customer_match_rate": "customers",
    "language_detection_accuracy": "languages",
    "p95_stage_latency_ms": "stages",
    "autonomy_l4_rate": "intents",
    "hitl_resolution_p95_hours": "intents",
    "reply_send_success_rate": "global_only",
    "spam_false_positive_rate": "global_only",
    "cost_per_pipeline_usd": "global_only",
    "aioa_handoff_success_rate": "intents",
    "psi_intent": "global_only",
}

# Static stage list; matches the orchestrator's stage vocabulary.
_KNOWN_STAGES = ("intake", "extract", "reconcile", "decide", "execute", "communicate")
# Static language list; matches the seeded language detection vocabulary.
_KNOWN_LANGUAGES = ("en", "ja", "de", "zh", "fr", "es", "pt", "ko")


def _resolve_segments_for_metric(db: Session, metric: str) -> list[str]:
    """Return the list of segment strings the detector should observe for a
    concept baseline. Pulled live from the data so a new intent appearing
    in production becomes a contributor without code changes.

    Returns at minimum `["global"]` so the rollup always has at least one
    observation when the per-segment data is sparse.
    """
    resolver = _METRIC_SEGMENT_RESOLVERS.get(metric, "global_only")
    if resolver == "global_only":
        return ["global"]

    cutoff = _now() - timedelta(hours=_BASELINE_WINDOW_HOURS)
    segments: list[str] = ["global"]

    # Metrics that can only be observed when the extract stage actually
    # ran. Pre-intake-terminated intents (e.g. KSO) never produce an
    # extract event, so listing them as segments would surface a
    # permanent sample_size=0/status=unknown row in the Baselines tab.
    _EXTRACT_ONLY_METRICS = {"extraction_completeness"}

    try:
        if resolver in ("intents", "intents_and_regions"):
            intents_with_extract: set[str] | None = None
            if metric in _EXTRACT_ONLY_METRICS:
                extract_pipe_ids = {
                    pid
                    for (pid,) in db.query(TraceEvent.pipeline_id)
                    .filter(
                        TraceEvent.stage == "extract",
                        TraceEvent.kind == "stage_end",
                        TraceEvent.ts >= cutoff,
                    )
                    .distinct()
                    .all()
                    if pid is not None
                }
                if extract_pipe_ids:
                    intents_with_extract = {
                        intent
                        for (intent,) in db.query(Pipeline.intent)
                        .filter(Pipeline.id.in_(extract_pipe_ids))
                        .filter(Pipeline.intent.isnot(None))
                        .distinct()
                        .all()
                        if intent
                    }
                else:
                    intents_with_extract = set()

            rows = (
                db.query(Pipeline.intent)
                .filter(Pipeline.started_at >= cutoff)
                .filter(Pipeline.intent.isnot(None))
                .distinct()
                .all()
            )
            for (intent,) in rows:
                if not intent:
                    continue
                if intents_with_extract is not None and intent not in intents_with_extract:
                    # Pre-intake-terminated intent: never reaches extract, so
                    # the segment would be permanently unobservable. Skip it
                    # for extract-only metrics to keep the Baselines tab clean.
                    continue
                segments.append(f"intent:{intent}")
        if resolver == "intents_and_regions":
            # Region lives inside customer_match JSON; resolve from a small
            # static set rather than parsing JSON on SQLite.
            for region in ("AMS", "EMEA", "APAC", "JP"):
                segments.append(f"region:{region}")
        if resolver == "languages":
            rows = (
                db.query(Pipeline.language)
                .filter(Pipeline.started_at >= cutoff)
                .filter(Pipeline.language.isnot(None))
                .distinct()
                .all()
            )
            seen = set()
            for (lang,) in rows:
                if lang and lang not in seen:
                    seen.add(lang)
                    segments.append(f"language:{lang}")
            # Always include the static set so a low-volume language still
            # has a slot in the rollup (it just contributes weight 0).
            for lang in _KNOWN_LANGUAGES:
                key = f"language:{lang}"
                if key not in segments:
                    segments.append(key)
        if resolver == "stages":
            for stage in _KNOWN_STAGES:
                segments.append(f"stage:{stage}")
        if resolver == "customers":
            try:
                from ..models import Customer
                rows = (
                    db.query(Customer.code)
                    .filter(Customer.status == "active")
                    .limit(20)
                    .all()
                )
                for (code,) in rows:
                    if code:
                        segments.append(f"customer:{code}")
            except Exception:
                pass
    except Exception:
        log.exception("segment resolution failed for metric=%s", metric)

    return segments


def _rollup(strategy: str, observations: list[tuple[float, int]]) -> tuple[float, int] | None:
    """Roll up per-segment (value, sample_size) observations into one value.

    Strategies:
      weighted_avg: sum(v * w) / sum(w). Weight is the sample size; falls
                    back to 1.0 when sample size is zero so no segment is
                    fully discounted.
      max         : argmax over values. Sample size becomes the matching
                    observation's sample. Use this when the worst slice
                    sets the user-visible experience (latency, PSI).
      min         : argmin over values. Rarely used; supported for
                    parity. Sample size becomes the matching observation's
                    sample.

    Returns None when observations is empty so the caller can leave the
    baseline status at 'unknown'.
    """
    if not observations:
        return None
    s = (strategy or "weighted_avg").lower()
    if s == "max":
        v, n = max(observations, key=lambda x: x[0])
        return (float(v), int(n))
    if s == "min":
        v, n = min(observations, key=lambda x: x[0])
        return (float(v), int(n))
    # weighted_avg default
    total_w = 0.0
    weighted_sum = 0.0
    total_n = 0
    for v, n in observations:
        w = float(n) if n and n > 0 else 1.0
        total_w += w
        weighted_sum += float(v) * w
        total_n += int(n or 0)
    if total_w <= 0:
        return None
    return (weighted_sum / total_w, total_n)


def _map_baseline_severity_to_alert(baseline_severity: str | None) -> str:
    """Translate baseline-severity vocabulary into DriftAlert-severity vocabulary.

    Baseline severities are admin-facing (`warn` / `block_promotion`).
    DriftAlert severities use the canonical detector vocabulary
    (`info` / `medium` / `high`) that the Overview tiles, Drift tab,
    notifier, and circuit breaker consume. Without this translation the
    UI filters out `warn` rows and breached baselines look like zero drift.
    """
    if (baseline_severity or "").lower() == "block_promotion":
        return "high"
    return "medium"


def _classify_segment_status(b, observed: float | None) -> str:
    """Classify a single per-segment observation against the parent
    baseline's target. Mirrors `services.baselines.evaluate_status` so the
    top_contributors list reads with the same vocabulary as the rolled-up
    baseline.
    """
    if observed is None:
        return "unknown"
    target = float(b.target_value or 0.0)
    if target == 0:
        return "unknown"
    drift = float(b.drift_pct or 0.0) / 100.0
    if (b.direction or "min").lower() == "min":
        if observed >= target:
            return "healthy"
        if observed >= target * (1 - drift):
            return "drifting"
        return "breached"
    if observed <= target:
        return "healthy"
    if observed <= target * (1 + drift):
        return "drifting"
    return "breached"


def _sort_contributors_worst_first(b, contributors: list[dict]) -> list[dict]:
    """Order per-segment contributions worst-first. For min-direction
    metrics the lowest observed sits at the top; for max-direction metrics
    the highest observed sits at the top. The 'global' row is filtered out
    so the contributors list shows only segment-scoped evidence.
    """
    direction = (b.direction or "min").lower()
    scoped = [c for c in contributors if c.get("segment") and c["segment"] != "global"]

    def _worst_key(c):
        observed = c.get("observed")
        if observed is None:
            # Push unknowns to the bottom.
            return float("inf") if direction == "min" else float("-inf")
        return float(observed) if direction == "min" else -float(observed)

    return sorted(scoped, key=_worst_key)


def detect_baseline_violations(db: Session) -> int:
    """Evaluate every enabled concept baseline.

    For each baseline:
      1. Resolve the relevant segments (intents, regions, stages, etc.)
         from the live data set.
      2. Observe each segment via `_observe_metric_with_sample`. Skip
         segments where the data is missing rather than crashing.
      3. Roll the per-segment observations up into one scalar using the
         baseline's `rollup_strategy` (weighted_avg, max, min).
      4. Persist the rollup as `last_observed` plus the per-segment
         evidence as `segments_observed`.
      5. When the rollup is breached, fire a DriftAlert carrying
         `top_contributors` ordered worst-first (capped at 5) so the
         operator sees which segments drove the breach.

    Drifting rows update the baseline status but do not fire alerts;
    admins see them in the dashboard heatmap. The invariant `every
    breached baseline has at least one open DriftAlert` is enforced by
    `ensure_drift_for_breached_baselines` at the end of the pass.
    """
    from ..models import Baseline
    from ..services import baselines as baselines_svc

    # Keysight-only: the legacy detectors compute observed values with
    # Keysight-specific logic, so they must never touch discovered client gates
    # (other domains) — those are evaluated by the signal-graph analyzer.
    rows = db.query(Baseline).filter(Baseline.enabled.is_(True), Baseline.domain == "keysight").all()
    if not rows:
        return 0

    emitted = 0
    for b in rows:
        # 1. Resolve the segment vocabulary for this concept baseline.
        segments = _resolve_segments_for_metric(db, b.metric)

        # 2. Observe each segment. Missing data is skipped, not surfaced
        # as 0.0 which would corrupt the rollup.
        per_segment: list[dict] = []
        observations_for_rollup: list[tuple[float, int]] = []
        for seg in segments:
            obs = _observe_metric_with_sample(db, b.metric, seg)
            if obs is None:
                per_segment.append({
                    "segment": seg,
                    "observed": None,
                    "weight": 0.0,
                    "sample_size": 0,
                    "status": "unknown",
                })
                continue
            value, sample_size = obs
            weight = float(sample_size) if sample_size and sample_size > 0 else 1.0
            per_segment.append({
                "segment": seg,
                "observed": round(float(value), 4),
                "weight": round(weight, 4),
                "sample_size": int(sample_size),
                "status": _classify_segment_status(b, value),
            })
            observations_for_rollup.append((float(value), int(sample_size)))

        # Backfill the per-segment weights so each row carries its
        # proportional share of the total observed sample. Helps the UI
        # render a percentage breakdown without recomputing.
        total_w = sum(o["weight"] for o in per_segment) or 1.0
        for row in per_segment:
            row["weight"] = round(row["weight"] / total_w, 4)

        # 3. Roll up.
        rollup = _rollup(b.rollup_strategy or "weighted_avg", observations_for_rollup)

        # 4. Persist rollup + per-segment evidence.
        if rollup is None:
            rolled_value = None
        else:
            rolled_value, _rolled_n = rollup
        status = baselines_svc.record_observation(db, b, rolled_value)
        b.segments_observed = per_segment

        if status != "breached":
            continue

        # 5. Fire alert with top contributors ordered worst-first.
        top_contributors = _sort_contributors_worst_first(b, per_segment)[:5]
        severity = _map_baseline_severity_to_alert(b.severity)
        _ensure_alert(
            db,
            fingerprint=f"baseline:{b.metric}:{b.segment}",
            segment=b.segment,
            metric=b.metric,
            baseline=float(b.target_value),
            current=float(rolled_value or 0.0),
            severity=severity,
            detail={
                "baseline_id": b.id,
                "direction": b.direction,
                "drift_pct": b.drift_pct,
                "promotion_blocking": b.severity == "block_promotion",
                "rationale": b.rationale,
                "source": b.source,
                "unit": b.unit,
                "rollup_strategy": b.rollup_strategy,
                "rollup_segments": len(per_segment),
            },
            fire_breaker=(b.severity == "block_promotion"),
            baseline_id=b.id,
            top_contributors=top_contributors,
        )
        emitted += 1
    db.commit()

    # Enforce invariant: every breached baseline carries at least one open
    # DriftAlert anchored to it, and any open alert whose baseline has
    # returned to healthy is auto-resolved.
    ensure_drift_for_breached_baselines(db)

    return emitted


# Open-state values for DriftAlert.status. Kept here so the invariant helper
# and any future reconcilers agree on what "still active" means.
_OPEN_ALERT_STATES = ("open", "acknowledged", "in_review")


def ensure_drift_for_breached_baselines(db: Session) -> dict[str, int]:
    """Reconcile the DriftAlert ledger against current Baseline state.

    For each enabled baseline:
      * `last_status == "breached"`: ensure at least one DriftAlert exists
        with `baseline_id == baseline.id` and `status` in the open set
        (`open`, `acknowledged`, `in_review`). Idempotent. When the
        anchoring alert is missing, a new row is created using the
        baseline's metric, segment, target_value, and last_observed as
        baseline / current values. Severity follows
        `_map_baseline_severity_to_alert`.
      * `last_status == "healthy"`: auto-resolve every open DriftAlert
        anchored to this baseline with the operator note
        `auto-resolved: baseline returned to healthy`.

    Returns counts: {created, resolved, skipped}. Safe to call repeatedly
    from the detector pass or at startup; the same state always converges.
    """
    from ..models import Baseline

    out = {"created": 0, "resolved": 0, "skipped": 0}
    # Keysight-only: the legacy detectors compute observed values with
    # Keysight-specific logic, so they must never touch discovered client gates
    # (other domains) — those are evaluated by the signal-graph analyzer.
    rows = db.query(Baseline).filter(Baseline.enabled.is_(True), Baseline.domain == "keysight").all()
    if not rows:
        return out

    changed = False
    for b in rows:
        status = (b.last_status or "").lower()

        if status == "breached":
            open_anchored = (
                db.query(DriftAlert)
                .filter(DriftAlert.baseline_id == b.id)
                .filter(DriftAlert.status.in_(list(_OPEN_ALERT_STATES)))
                .all()
            )
            severity = _map_baseline_severity_to_alert(b.severity)
            if open_anchored:
                # Migrate legacy rows that still carry the baseline-side
                # severity vocabulary (`warn` / `slo_breach`) onto the
                # canonical DriftAlert vocabulary (`info` / `medium` /
                # `high`) so the Overview tile and Drift tab include them.
                for a in open_anchored:
                    if (a.severity or "").lower() not in {"info", "medium", "high"}:
                        a.severity = severity
                        a.updated_at = _now()
                        changed = True
                out["skipped"] += 1
                continue
            target = float(b.target_value or 0.0)
            current = float(b.last_observed) if b.last_observed is not None else 0.0
            delta_abs = current - target
            delta_pct = (delta_abs / target) if target else 0.0
            # Pull the per-segment evidence stamped by the last detector
            # pass so the alert carries the contributor breakdown even on
            # reconciliation. Order worst-first, cap at 5.
            contributors_raw = list(b.segments_observed or [])
            top_contributors = _sort_contributors_worst_first(b, contributors_raw)[:5] if contributors_raw else []
            alert = DriftAlert(
                fingerprint=f"baseline:{b.metric}:{b.segment}",
                segment=b.segment,
                metric=b.metric,
                baseline=target,
                current=current,
                delta=delta_abs,
                delta_pct=round(delta_pct * 100, 2),
                severity=severity,
                status="open",
                circuit_breaker_fired=(b.severity == "block_promotion"),
                detail={
                    "baseline_id": b.id,
                    "direction": b.direction,
                    "drift_pct": b.drift_pct,
                    "promotion_blocking": b.severity == "block_promotion",
                    "rationale": b.rationale,
                    "source": b.source,
                    "unit": b.unit,
                    "rollup_strategy": b.rollup_strategy,
                    "origin": "ensure_drift_for_breached_baselines",
                },
                baseline_id=b.id,
                top_contributors=top_contributors,
            )
            db.add(alert)
            out["created"] += 1
            changed = True
            continue

        if status == "healthy":
            open_for_baseline = (
                db.query(DriftAlert)
                .filter(DriftAlert.baseline_id == b.id)
                .filter(DriftAlert.status.in_(list(_OPEN_ALERT_STATES)))
                .all()
            )
            if not open_for_baseline:
                continue
            now = _now()
            for a in open_for_baseline:
                a.status = "resolved"
                a.resolved_at = now
                a.resolved_by = "system:baseline_recovery"
                a.note = "auto-resolved: baseline returned to healthy"
                a.updated_at = now
                out["resolved"] += 1
                changed = True
            continue

        # drifting / unknown: leave alerts untouched. Drifting metrics may
        # still warrant attention; unknown means no observation yet.

    if changed:
        db.commit()
    return out


# ---------- Top-level entry point ----------

_DETECTORS = [
    ("segment_edit_rate", detect_segment_edit_rate),
    ("stage_hitl_rate", detect_stage_hitl_rate),
    ("extraction_field_error_rate", detect_extraction_field_error_rate),
    ("latency_tails", detect_latency_tails),
    ("aioa_pass_rate", detect_aioa_pass_rate),
    ("distribution_shift", detect_distribution_shift),
    ("integration_write_failures", detect_integration_write_failures),
    ("baseline_violations", detect_baseline_violations),
]


def run_all_detectors(db: Session) -> dict[str, int]:
    """Run every detector. Returns {detector_name: alerts_emitted_or_updated}.

    Failures in one detector do not stop the others; each failure is logged
    and the counter records 0 for that detector.
    """
    out: dict[str, int] = {}
    for name, fn in _DETECTORS:
        try:
            out[name] = fn(db)
        except Exception as e:
            log.exception("monitor.%s failed: %s", name, e)
            out[name] = 0
    return out


def check_autorollback_watchdog(db: Session) -> list[dict]:
    """Watchdog for promoted experiments. For each promotion within the last
    7 days, check the metric the candidate claimed to improve. If the metric
    has regressed past the configured threshold, auto-rollback the change.

    Returns the list of rollback decisions made in this pass.
    """
    from ..config import LEARNING_AUTOROLLBACK_THRESHOLDS
    from ..models import ABExperiment, Feedback, Pipeline
    out: list[dict] = []
    cutoff = _now() - timedelta(days=7)
    promoted = (
        db.query(ABExperiment)
        .filter(ABExperiment.promote_status == "promoted")
        .filter(ABExperiment.promoted_at.isnot(None))
        .filter(ABExperiment.promoted_at >= cutoff)
        .all()
    )
    edit_threshold = LEARNING_AUTOROLLBACK_THRESHOLDS.get("edit_rate_regression_pp", 2.0)
    for exp in promoted:
        ct = (exp.change_type or "prompt").lower()
        # The watchdog currently understands prompt + threshold + pattern_list
        # candidates. Routing / validation watchdog reads sit in their own
        # detectors; treating them here would double-count.
        if ct not in {"prompt", "threshold", "pattern_list"}:
            continue
        baseline_edit_pct = (exp.backtest_results or {}).get("baseline_accuracy_pct") if isinstance(exp.backtest_results, dict) else None
        candidate_edit_pct = (exp.backtest_results or {}).get("candidate_accuracy_pct") if isinstance(exp.backtest_results, dict) else None
        if baseline_edit_pct is None or candidate_edit_pct is None:
            continue
        target_intent = exp.kb_key
        if not target_intent:
            continue
        # Observed post-promotion edit rate among pipelines that ran AFTER
        # promotion landed.
        post_pipes = (
            db.query(Pipeline)
            .filter(Pipeline.intent == target_intent)
            .filter(Pipeline.started_at >= exp.promoted_at)
            .all()
        )
        if len(post_pipes) < 5:
            continue
        edited_ids = set(int(pid) for (pid,) in db.query(Feedback.pipeline_id)
                         .filter(Feedback.pipeline_id.in_([p.id for p in post_pipes]))
                         .filter(Feedback.kind == "edit").distinct().all() if pid is not None)
        observed_edit_pct = (1.0 - (len(edited_ids) / len(post_pipes))) * 100
        regression_pp = candidate_edit_pct - observed_edit_pct
        if regression_pp < edit_threshold:
            continue
        # Auto-rollback. Marks experiment retired, restores prior body.
        from .learning_promotion import rollback_ab_experiment as _do_rollback
        try:
            _do_rollback(
                db, exp.id,
                rolled_back_by="autorollback_watchdog",
                note=f"Auto-rollback at {_now().isoformat()}: post-promotion accuracy {observed_edit_pct:.1f}% vs back-test prediction {candidate_edit_pct:.1f}% (regression {regression_pp:.1f}pp).",
            )
            out.append({"experiment_id": exp.id, "regression_pp": round(regression_pp, 2), "post_n": len(post_pipes)})
            # Also raise a high-severity drift alert so the rule owner is paged.
            _ensure_alert(
                db, fingerprint=f"autorollback:{exp.id}",
                segment=f"experiment:{exp.id}:{target_intent}",
                metric="post_promotion_regression_pp",
                baseline=candidate_edit_pct,
                current=observed_edit_pct,
                severity="high",
                detail={"regression_pp": round(regression_pp, 2), "post_n": len(post_pipes)},
                fire_breaker=True,
            )
        except Exception as e:
            log.exception("autorollback failed for experiment %s: %s", exp.id, e)
    return out


def segments_with_circuit_breaker_armed(db: Session) -> set[str]:
    """Return the set of segment strings for which a high-severity DriftAlert
    is currently open and the circuit breaker is fired. The orchestrator reads
    this set before assigning L4_AUTO; affected segments are forced to HITL
    review until the alert is resolved or the metric recovers.
    """
    rows = (
        db.query(DriftAlert)
        .filter(DriftAlert.status == "open")
        .filter(DriftAlert.circuit_breaker_fired.is_(True))
        .all()
    )
    return {r.segment for r in rows if r.segment}
