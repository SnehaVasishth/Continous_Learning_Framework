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

from ...models import Baseline, DriftAlert, SignalEdge, SignalNode, now
from ..baselines import evaluate_status
from . import confirm
from .observe import observation_series, data_status, MIN_WINDOWS


def _values(db: Session, domain: str, signal_key: str, segment: str) -> list[float]:
    """The non-null observed values for one signal, oldest window first."""
    return [r.value for r in observation_series(db, domain, signal_key, segment) if r.value is not None]


def consolidated_series(db: Session, domain: str, metric: str, segment: str = "global") -> tuple[list[float], bool]:
    """Consolidate telemetry + feedback into one value per window (Task 2,
    'dual-input drift').

    Telemetry covers EVERY case but the AI may grade itself optimistically;
    human feedback is ground truth on the REVIEWED subset. So per window we
    blend: the more of the population humans reviewed, the more feedback is
    trusted. alpha = feedback_samples / telemetry_samples (capped at 1).

        consolidated = (1 - alpha) * telemetry + alpha * feedback

    Returns (values oldest-first, had_feedback). Windows with only telemetry
    pass through unchanged; this naturally degrades to telemetry-only for
    clients with no feedback stream (e.g. a plain CRUD app).
    """
    tel: dict = {}
    fb: dict = {}
    for r in observation_series(db, domain, metric, segment):
        if r.value is None:
            continue
        (tel if r.source_stream == "telemetry" else fb)[r.window_start] = (r.value, r.sample_size or 0)

    out: list[float] = []
    had_feedback = False
    for ws in sorted(set(tel) | set(fb)):
        tv, tn = tel.get(ws, (None, 0))
        fv, fn = fb.get(ws, (None, 0))
        if fv is not None and tv is not None:
            alpha = min(1.0, fn / tn) if tn else 1.0
            out.append((1 - alpha) * tv + alpha * fv)
            had_feedback = True
        elif fv is not None:
            out.append(fv)
            had_feedback = True
        else:
            out.append(tv)
    return out, had_feedback


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


def _gate_drift(db: Session, domain: str, gate: QualityGate) -> dict:
    """Pure (no-write) drift summary for one accepted gate vs its user target."""
    target = gate.target_value
    base = {"metric": gate.metric, "segment": gate.segment, "direction": gate.direction,
            "target_value": target}
    if target is None:
        return {**base, "status": "no_target"}

    # Dual-input: drift runs on the telemetry+feedback consolidated series.
    values, had_feedback = consolidated_series(db, domain, gate.metric, gate.segment)
    if not values:
        return {**base, "status": "no_data"}
    if len(values) < MIN_WINDOWS:
        return {**base, "status": "insufficient_data"}

    current = values[-1]
    delta = current - target
    delta_pct = (delta / target) if target else None
    # Breach depends on direction: 'min' = higher-is-better (breach when below),
    # 'max' = lower-is-better (breach when above).
    breached = (gate.direction == "min" and current < target) or (
        gate.direction == "max" and current > target
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
            "delta_pct": delta_pct, "psi": psi, "breached": breached, "severity": severity,
            "streams": "telemetry+feedback" if had_feedback else "telemetry"}


def compute_drift(db: Session, domain: str) -> list[dict]:
    """Compute drift for every accepted gate (a discovered Baseline) and upsert
    a DriftAlert per gate with enough data. Also mirrors the consolidated value
    + status onto the Baseline row so the existing CL Baselines UI shows it."""
    gates = db.query(Baseline).filter(Baseline.domain == domain).all()
    results: list[dict] = []
    for gate in gates:
        d = _gate_drift(db, domain, gate)
        results.append(d)
        if d.get("status") != "ok":
            continue
        # Mirror onto the Baseline row -> existing CL heatmap shows healthy/
        # drifting/breached for this discovered gate.
        gate.last_observed = d["current"]
        gate.last_observed_at = now()
        gate.last_status = evaluate_status(gate, d["current"])
        fp = f"sg:{domain}:{gate.metric}:{gate.segment}"        # idempotency key
        alert = (
            db.query(DriftAlert)
            .filter(DriftAlert.fingerprint == fp, DriftAlert.status != "resolved")
            .first()
        )
        if alert is None:
            alert = DriftAlert(fingerprint=fp, status="open")
            db.add(alert)
        alert.detected_at = now()
        alert.segment = gate.segment
        alert.metric = gate.metric
        alert.baseline = gate.target_value
        alert.current = d["current"]
        alert.delta = d["delta"]
        alert.delta_pct = d["delta_pct"]
        alert.severity = d["severity"]
        alert.detail = {"source": "signal_graph", "domain": domain,
                        "psi": d["psi"], "direction": gate.direction, "breached": d["breached"]}
    db.commit()
    return results


def accepted_gates(db: Session, domain: str) -> list[dict]:
    """Accepted gates (discovered Baselines) with their (read-only) drift,
    worst severity first."""
    gates = db.query(Baseline).filter(Baseline.domain == domain).all()
    rows = [_gate_drift(db, domain, gate) for gate in gates]
    rank = {"high": 0, "medium": 1, "info": 2, "insufficient_data": 3, "no_data": 4, "no_target": 5}
    rows.sort(key=lambda r: rank.get(r.get("severity") or r.get("status"), 9))
    return rows


def analyze_domain(db: Session, domain: str) -> dict:
    """Run both analyses for a session and return a small summary."""
    weights = recompute_edge_weights(db, domain)
    drift = compute_drift(db, domain)
    return {"domain": domain, "edges_updated": weights, "gates_analyzed": len(drift)}
