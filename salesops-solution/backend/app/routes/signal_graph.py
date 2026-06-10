"""HTTP API for the signal-graph discovery feature.

Flow: discover -> list recommendations -> accept (user sets target) / dismiss
-> view a gate's graph. Everything is scoped by session_id (stored in the
`domain` column). Accepting stores the user's target in the recommendation's
context_stats JSON and flips status to 'accepted' — no separate Baseline row
(keeps it session-scoped, no migration).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BaselineRecommendation, QualityGate, SignalNode, SignalEdge
from ..services.signal_graph.discovery.run import run_discovery
from ..services.signal_graph import analyze
from ..services.signal_graph.seed_demo import seed_demo_observations

router = APIRouter()


# ---- discovery -----------------------------------------------------------

class DiscoverBody(BaseModel):
    tenant_id: str
    session_id: str


@router.post("/discover")
def discover(body: DiscoverBody, db: Session = Depends(get_db)) -> dict:
    """Fetch the client's codebase, run two-pass discovery, persist. Synchronous
    in v1 (small codebases)."""
    return run_discovery(db, tenant_id=body.tenant_id, session_id=body.session_id)


# ---- recommendations (candidates) ----------------------------------------

@router.get("/recommendations")
def recommendations(session_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Open candidate gates for a session (unranked — no data yet)."""
    rows = (
        db.query(BaselineRecommendation)
        .filter(BaselineRecommendation.domain == session_id,
                BaselineRecommendation.status == "open")
        .all()
    )
    # Hide any metric the user has already accepted (it lives in quality_gates
    # now), so an accepted gate is never re-offered as a candidate.
    accepted_metrics = {
        g.metric for g in db.query(QualityGate).filter(QualityGate.domain == session_id).all()
    }
    return [
        {
            "id": r.id,
            "metric": r.metric,
            "segment": r.segment,
            "direction": r.direction,
            "score": r.score,
            "rationale": r.rationale,
            "inputs": (r.subgraph_snapshot or {}).get("inputs", []),
            "compute": (r.subgraph_snapshot or {}).get("compute"),
            # Non-binding hint for the human's target. "insufficient_data" /
            # "no_data" until telemetry exists; the target is still user-set.
            # v1 observations are global; segment is noisy LLM metadata.
            "suggested_range": analyze.suggested_range(db, session_id, r.metric, "global"),
        }
        for r in rows
        if r.metric not in accepted_metrics
    ]


class AcceptBody(BaseModel):
    target_value: float


@router.post("/recommendations/{rec_id}/accept")
def accept(rec_id: int, body: AcceptBody, db: Session = Depends(get_db)) -> dict:
    """User accepts a candidate and sets its target. Upserts a QualityGate (the
    durable, deduplicated final target) and removes the candidate row. The
    target_value comes only from the user (the invariant)."""
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")

    snap = rec.subgraph_snapshot or {}
    # Upsert by (domain, metric) so re-accepting the same metric updates the
    # existing target instead of creating a duplicate.
    gate = (
        db.query(QualityGate)
        .filter(QualityGate.domain == rec.domain,
                QualityGate.metric == rec.metric)
        .first()
    )
    if gate is None:
        # v1: normalize to global (segment is noisy LLM metadata); keeps the
        # gate's observation lookups aligned with how observations are stored.
        gate = QualityGate(domain=rec.domain, metric=rec.metric, segment="global")
        db.add(gate)
    gate.direction = rec.direction
    gate.target_value = body.target_value          # the user's number
    gate.compute = snap.get("compute")
    gate.inputs = snap.get("inputs", [])
    gate.rationale = rec.rationale

    db.delete(rec)                                  # candidate becomes a final gate
    db.commit()
    return {"id": gate.id, "metric": gate.metric, "target_value": gate.target_value, "status": "accepted"}


@router.post("/recommendations/{rec_id}/dismiss")
def dismiss(rec_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")
    rec.status = "dismissed"
    db.commit()
    return {"ok": True}


# ---- analysis: edge weights + drift --------------------------------------

@router.post("/analyze")
def analyze_endpoint(body: DiscoverBody, db: Session = Depends(get_db)) -> dict:
    """Recompute edge weights + drift for a session. Data-conditional: signals
    without enough telemetry stay weight=null and report insufficient_data."""
    return analyze.analyze_domain(db, body.session_id)


@router.get("/baselines")
def baselines(session_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Accepted gates (the user's baseline targets) with their drift status,
    worst severity first."""
    return analyze.accepted_gates(db, session_id)


class SeedBody(BaseModel):
    session_id: str
    windows: int = 8


@router.post("/seed-demo")
def seed_demo(body: SeedBody, db: Session = Depends(get_db)) -> dict:
    """DEMO/TEST ONLY: write synthetic (meta.synthetic=true) observations for a
    discovered session so range/weights/drift can be exercised without real
    telemetry. Idempotent per session."""
    return seed_demo_observations(db, body.session_id, windows=body.windows)


# ---- the gate's signal graph (backtrack) ---------------------------------

@router.get("/recommendations/{rec_id}/graph")
def graph(rec_id: int, db: Session = Depends(get_db)) -> dict:
    """Rebuild the gate's subgraph (signals -> target) from the stored nodes/edges."""
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")

    tnode = (
        db.query(SignalNode)
        .filter(SignalNode.domain == rec.domain, SignalNode.key == f"target:{rec.metric}")
        .first()
    )
    nodes = [{"key": tnode.key, "type": tnode.node_type}] if tnode else []
    edges: list[dict] = []
    if tnode:
        for e in (
            db.query(SignalEdge)
            .filter(SignalEdge.domain == rec.domain, SignalEdge.to_node_id == tnode.id)
            .all()
        ):
            src = db.query(SignalNode).filter(SignalNode.id == e.from_node_id).first()
            if src:
                nodes.append({"key": src.key, "type": src.node_type})
                edges.append({"from": src.key, "to": tnode.key, "weight": e.weight})
    return {"nodes": nodes, "edges": edges}
