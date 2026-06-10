
from sqlalchemy.orm import Session

from ....models import SignalNode, SignalEdge, BaselineRecommendation
from .fetch_solution import fetch_solution
from .extract_signals import extract_signals
from .propose_gates import propose_gates


def _clear_domain(db: Session, domain: str) -> None:
   
    db.query(SignalEdge).filter(SignalEdge.domain == domain).delete(synchronize_session=False)
    db.query(SignalNode).filter(SignalNode.domain == domain).delete(synchronize_session=False)
    db.query(BaselineRecommendation).filter(
        BaselineRecommendation.domain == domain,
    ).delete(synchronize_session=False)
    db.commit()


def run_discovery(db: Session, *, tenant_id: str, session_id: str) -> dict:
    domain = session_id                              
    code_dir = fetch_solution(tenant_id, session_id)
    root = next(code_dir.iterdir())                 
    signals = extract_signals(root)                 
    gates = propose_gates(signals)                  

    _clear_domain(db, domain)

  
    key_to_node: dict[str, SignalNode] = {}
    for s in signals:
        node = SignalNode(
            domain=domain, key=s.key, node_type="raw_signal",
            source_stream=s.stream, description=s.description,
            meta={"evidence": s.evidence, "observable": s.observable},
        )
        db.add(node)
        db.flush()                                 
        key_to_node[s.key] = node

  
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
