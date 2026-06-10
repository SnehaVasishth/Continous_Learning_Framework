"""Data-driven analysis over the signal graph: suggested range (Task 12),
edge weights + drift (Task 13).

Every function here is DATA-CONDITIONAL: it asks observe.data_status first and
returns an explicit "insufficient_data" verdict rather than inventing numbers
when a client has no telemetry. The maths is reused from `confirm`.
"""
from __future__ import annotations

import math

import numpy as np
from sqlalchemy.orm import Session

from ...models import BaselineRecommendation, DriftAlert, SignalEdge, SignalNode, now
from . import confirm
from .observe import observation_series, data_status, MIN_WINDOWS


def _values(db: Session, domain: str, signal_key: str, segment: str) -> list[float]:
    """The non-null observed values for one signal, oldest window first."""
    return [r.value for r in observation_series(db, domain, signal_key, segment) if r.value is not None]


def suggested_range(db: Session, domain: str, metric: str, segment: str = "global") -> dict:
    """A non-binding hint for the human's target: where the metric has sat.

    Returns {"status": "ok", "median", "p10", "p90", "n"} when enough data
    exists, else {"status": "no_data" | "insufficient_data"}. The target value
    is NEVER derived from this — it only informs the human.
    """
    status = data_status(db, domain, metric, segment)
    if status != "ok":
        return {"status": status}
    values = _values(db, domain, metric, segment)
    dist = confirm.context_distribution(values)   # {median, p10, p90}
    return {"status": "ok", "n": len(values), **dist}


# ---- Task 13: edge weights + drift ---------------------------------------

def _psi(reference: list[float], current: list[float], buckets: int = 10) -> float | None:
    """Population Stability Index between an earlier and a recent value set.

    PSI ~0 = stable, ~0.1-0.25 = moderate shift, >0.25 = large shift. Returns
    None when either side is too small to bucket meaningfully.
    """
    if len(reference) < 2 or len(current) < 2:
        return None
    lo, hi = min(min(reference), min(current)), max(max(reference), max(current))
    if hi == lo:
        return 0.0
    edges = np.linspace(lo, hi, buckets + 1)
    ref_pct = np.histogram(reference, bins=edges)[0] / len(reference)
    cur_pct = np.histogram(current, bins=edges)[0] / len(current)
    eps = 1e-6
    psi = 0.0
    for r, c in zip(ref_pct, cur_pct):
        r, c = max(float(r), eps), max(float(c), eps)
        psi += (c - r) * math.log(c / r)
    return float(psi)


def recompute_edge_weights(db: Session, domain: str) -> int:
    """Set each edge's weight = |Pearson| of its signal series vs the target's
    metric series. Edges stay weight=None (null) when there isn't enough data,
    so the graph shows '–' rather than a misleading number. Returns #updated."""
    edges = db.query(SignalEdge).filter(SignalEdge.domain == domain).all()
    updated = 0
    for e in edges:
        src = db.query(SignalNode).filter(SignalNode.id == e.from_node_id).first()
        tgt = db.query(SignalNode).filter(SignalNode.id == e.to_node_id).first()
        if not src or not tgt:
            continue
        metric = tgt.key.replace("target:", "", 1)          # target node key -> metric
        sig_series = _values(db, domain, src.key, "global")
        met_series = _values(db, domain, metric, "global")
        weight = confirm.edge_weight(sig_series, met_series)  # None below sample floor
        if weight != e.weight:
            e.weight = weight
            updated += 1
    db.commit()
    return updated


def _gate_drift(db: Session, domain: str, rec: BaselineRecommendation) -> dict:
    """Pure (no-write) drift summary for one accepted gate vs its user target."""
    target = (rec.context_stats or {}).get("target_value")
    base = {"metric": rec.metric, "segment": rec.segment, "direction": rec.direction,
            "target_value": target}
    if target is None:
        return {**base, "status": "no_target"}

    status = data_status(db, domain, rec.metric, rec.segment)
    if status != "ok":
        return {**base, "status": status}

    values = _values(db, domain, rec.metric, rec.segment)
    current = values[-1]
    delta = current - target
    delta_pct = (delta / target) if target else None
    # Breach depends on direction: 'min' = higher-is-better (breach when below),
    # 'max' = lower-is-better (breach when above).
    breached = (rec.direction == "min" and current < target) or (
        rec.direction == "max" and current > target
    )
    mid = len(values) // 2
    psi = _psi(values[:mid], values[mid:]) if len(values) >= 2 * MIN_WINDOWS else None

    if breached:
        severity = "high"
    elif psi is not None and psi >= 0.2:
        severity = "medium"
    else:
        severity = "info"

    return {**base, "status": "ok", "current": current, "delta": delta,
            "delta_pct": delta_pct, "psi": psi, "breached": breached, "severity": severity}


def compute_drift(db: Session, domain: str) -> list[dict]:
    """Compute drift for every accepted gate and upsert a DriftAlert row per
    gate that has enough data, so it surfaces in the existing drift UI."""
    accepted = (
        db.query(BaselineRecommendation)
        .filter(BaselineRecommendation.domain == domain,
                BaselineRecommendation.status == "accepted")
        .all()
    )
    results: list[dict] = []
    for rec in accepted:
        d = _gate_drift(db, domain, rec)
        results.append(d)
        if d.get("status") != "ok":
            continue
        fp = f"sg:{domain}:{rec.metric}:{rec.segment}"          # idempotency key
        alert = (
            db.query(DriftAlert)
            .filter(DriftAlert.fingerprint == fp, DriftAlert.status != "resolved")
            .first()
        )
        if alert is None:
            alert = DriftAlert(fingerprint=fp, status="open")
            db.add(alert)
        alert.detected_at = now()
        alert.segment = rec.segment
        alert.metric = rec.metric
        alert.baseline = rec.context_stats.get("target_value")
        alert.current = d["current"]
        alert.delta = d["delta"]
        alert.delta_pct = d["delta_pct"]
        alert.severity = d["severity"]
        alert.detail = {"source": "signal_graph", "domain": domain,
                        "psi": d["psi"], "direction": rec.direction, "breached": d["breached"]}
    db.commit()
    return results


def accepted_gates(db: Session, domain: str) -> list[dict]:
    """Accepted gates with their (read-only) drift, worst severity first."""
    accepted = (
        db.query(BaselineRecommendation)
        .filter(BaselineRecommendation.domain == domain,
                BaselineRecommendation.status == "accepted")
        .all()
    )
    rows = [_gate_drift(db, domain, rec) for rec in accepted]
    rank = {"high": 0, "medium": 1, "info": 2, "insufficient_data": 3, "no_data": 4, "no_target": 5}
    rows.sort(key=lambda r: rank.get(r.get("severity") or r.get("status"), 9))
    return rows


def analyze_domain(db: Session, domain: str) -> dict:
    """Run both analyses for a session and return a small summary."""
    weights = recompute_edge_weights(db, domain)
    drift = compute_drift(db, domain)
    return {"domain": domain, "edges_updated": weights, "gates_analyzed": len(drift)}
