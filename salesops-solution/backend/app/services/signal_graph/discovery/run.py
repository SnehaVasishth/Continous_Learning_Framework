"""Orchestrate discovery: fetch -> Pass 1 -> Pass 2 -> persist.

Persists the Solution Model directly (no approval gate in v1), scoped by
`session_id` stored in the existing `domain` column. Re-running a session is
idempotent: prior discovery output for that domain is cleared first.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ....models import SignalNode, SignalEdge, BaselineRecommendation
from .fetch_solution import fetch_solution
from .extract_signals import extract_signals
from .propose_gates import propose_gates


def _clear_domain(db: Session, domain: str) -> None:
    """Remove prior discovery rows for this session so re-running is clean.
    (Edges first — they reference nodes via FK. Only 'open' recommendations are
    cleared, so accepted gates are never wiped.)"""
    db.query(SignalEdge).filter(SignalEdge.domain == domain).delete(synchronize_session=False)
    db.query(SignalNode).filter(SignalNode.domain == domain).delete(synchronize_session=False)
    db.query(BaselineRecommendation).filter(
        BaselineRecommendation.domain == domain,
        BaselineRecommendation.status == "open",
    ).delete(synchronize_session=False)
    db.commit()


def run_discovery(db: Session, *, tenant_id: str, session_id: str) -> dict:
    domain = session_id                              # v1: session_id is our scope key
    code_dir = fetch_solution(tenant_id, session_id)
    root = next(code_dir.iterdir())                  # the single extracted top folder
    signals = extract_signals(root)                  # Pass 1
    gates = propose_gates(signals)                   # Pass 2

    _clear_domain(db, domain)

    # 1) persist each signal as a raw_signal node, remembering key -> node
    key_to_node: dict[str, SignalNode] = {}
    for s in signals:
        node = SignalNode(
            domain=domain, key=s.key, node_type="raw_signal",
            source_stream=s.stream, description=s.description,
            meta={"evidence": s.evidence, "observable": s.observable},
        )
        db.add(node)
        db.flush()                                   # assigns node.id before we link edges
        key_to_node[s.key] = node

    # 2) persist each gate: a target node + an open recommendation + edges signal->target
    for g in gates:
        tnode = SignalNode(
            domain=domain, key=f"target:{g.key}", node_type="baseline_target",
            description=g.description,
            meta={"rationale": g.rationale, "compute": g.compute},
        )
        db.add(tnode)
        db.flush()
        db.add(BaselineRecommendation(
            domain=domain, metric=g.key, segment=g.segment_dimension,
            direction=g.direction, score=0.0, rationale=g.rationale,
            context_stats={}, subgraph_snapshot={"inputs": g.inputs, "compute": g.compute},
            status="open",
        ))
        for sk in g.inputs:
            src = key_to_node.get(sk)
            if src:
                db.add(SignalEdge(
                    domain=domain, from_node_id=src.id, to_node_id=tnode.id,
                    relation="affects", origin="discovered", status="active",
                    weight=None, evidence={},
                ))

    db.commit()
    return {"session_id": session_id, "signals": len(signals), "gates": len(gates)}
