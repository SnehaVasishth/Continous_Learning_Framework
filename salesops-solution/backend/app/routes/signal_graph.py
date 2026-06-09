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
from ..models import BaselineRecommendation, SignalNode, SignalEdge
from ..services.signal_graph.discovery.run import run_discovery

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
        }
        for r in rows
    ]


class AcceptBody(BaseModel):
    target_value: float


@router.post("/recommendations/{rec_id}/accept")
def accept(rec_id: int, body: AcceptBody, db: Session = Depends(get_db)) -> dict:
    """User accepts a candidate and sets its target. The number lives in
    context_stats (no target_value column — the invariant)."""
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")
    stats = dict(rec.context_stats or {})          # new dict so SQLAlchemy sees the change
    stats["target_value"] = body.target_value      # the user's number
    rec.context_stats = stats
    rec.status = "accepted"
    db.commit()
    return {"id": rec.id, "metric": rec.metric, "target_value": body.target_value, "status": "accepted"}


@router.post("/recommendations/{rec_id}/dismiss")
def dismiss(rec_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")
    rec.status = "dismissed"
    db.commit()
    return {"ok": True}


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
