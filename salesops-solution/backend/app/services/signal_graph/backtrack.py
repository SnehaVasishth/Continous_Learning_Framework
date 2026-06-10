from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ...models import Baseline, SignalEdge, SignalNode, now
from . import keys
from .metric_specs import get_spec, has_spec
from .scanner import _structural_subgraph
from . import DEFAULT_DOMAIN

log = logging.getLogger("signal_graph.backtrack")


def _upsert_node(db: Session, domain: str, spec: dict, baseline_id: int | None) -> SignalNode:
    existing = (
        db.query(SignalNode)
        .filter(SignalNode.domain == domain, SignalNode.key == spec["key"])
        .first()
    )
    if existing:
        if baseline_id and spec["node_type"] == "baseline_target":
            existing.baseline_id = baseline_id
        return existing
    node = SignalNode(
        domain=domain,
        node_type=spec["node_type"],
        key=spec["key"],
        source_stream=spec.get("source_stream"),
        spec_ref=spec.get("spec_ref"),
        baseline_id=baseline_id if spec["node_type"] == "baseline_target" else None,
    )
    db.add(node)
    db.flush()
    return node


def _upsert_edge(db: Session, domain: str, from_id: int, to_id: int, origin: str, status: str) -> None:
    existing = (
        db.query(SignalEdge)
        .filter(
            SignalEdge.domain == domain,
            SignalEdge.from_node_id == from_id,
            SignalEdge.to_node_id == to_id,
        )
        .first()
    )
    if existing:
        return
    db.add(SignalEdge(
        domain=domain, from_node_id=from_id, to_node_id=to_id,
        relation="affects", origin=origin, status=status, weight=None, evidence={},
    ))


def backtrack_baseline(db: Session, *, baseline_id: int, domain: str = DEFAULT_DOMAIN) -> dict:
    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise ValueError(f"baseline {baseline_id} not found")

    if has_spec(domain, b.metric):  # Case A
        spec = get_spec(domain, b.metric)
        subgraph = _structural_subgraph(domain, spec, b.segment)
        status = "active"
        origin = "structural"
    else:  # Case B — minimal target node, fallback discovery deferred
        tkey = keys.target_key(b.metric, b.segment)
        subgraph = {"nodes": [{"key": tkey, "node_type": "baseline_target"}], "edges": []}
        status = "suggested"
        origin = "statistical"

    # upsert nodes
    key_to_id: dict[str, int] = {}
    for nspec in subgraph["nodes"]:
        node = _upsert_node(db, domain, nspec, baseline_id)
        key_to_id[nspec["key"]] = node.id
    # upsert edges
    for espec in subgraph["edges"]:
        f = key_to_id.get(espec["from"])
        t = key_to_id.get(espec["to"])
        if f and t:
            _upsert_edge(db, domain, f, t, espec.get("origin", origin), status)
    db.commit()
    return {"baseline_id": baseline_id, "nodes": len(subgraph["nodes"]), "edges": len(subgraph["edges"])}