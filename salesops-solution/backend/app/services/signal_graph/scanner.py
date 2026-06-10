from __future__ import annotations

from sqlalchemy.orm import Session

from . import keys
from .domain_config import all_intents, required_fields_for_intent, stage_order
from .metric_specs import MetricSpec, all_specs


def _segments_for(db: Session, domain: str, spec: MetricSpec) -> list[str]:
    if spec.segment_dimension == "intent":
        return [f"intent:{i}" for i in all_intents(domain)] or ["global"]
    if spec.segment_dimension == "global":
        return ["global"]
    # language/customer/stage dimensions resolve to global until per-dimension
    # enumeration is wired; a single global candidate is still valid.
    return ["global"]


def _structural_subgraph(domain: str, spec: MetricSpec, segment: str) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []

    def add_node(key: str, node_type: str, **extra) -> None:
        if all(n["key"] != key for n in nodes):
            nodes.append({"key": key, "node_type": node_type, **extra})

    # --- spine: stage -> metric -> target ---
    tkey = keys.target_key(spec.key, segment)
    mkey = keys.metric_key(spec.key)
    skey = keys.stage_key(spec.stage)
    add_node(tkey, "baseline_target")
    add_node(mkey, "metric", spec_ref=spec.key)
    add_node(skey, "stage_outcome")
    edges.append({"from": mkey, "to": tkey, "origin": "structural"})
    edges.append({"from": skey, "to": mkey, "origin": "structural"})

    # --- expand declared inputs into raw-signal nodes ---
    intent = segment.split("intent:", 1)[1] if segment.startswith("intent:") else None
    for inp in spec.inputs:
        if "{required_field}" in inp.key_template:
            for fld in required_fields_for_intent(domain, intent):
                rk = keys.raw_field_key(fld)
                add_node(rk, "raw_signal", source_stream=inp.stream, role=inp.role)
                edges.append({"from": rk, "to": skey, "origin": "structural"})
        else:
            rk = inp.key_template
            add_node(rk, "raw_signal", source_stream=inp.stream, role=inp.role)
            target = mkey if inp.stream == "feedback" else skey
            edges.append({"from": rk, "to": target, "origin": "structural"})

    # --- cross-stage upstream link: the stage feeding this one ---
    order = stage_order(domain)
    if spec.stage in order:
        idx = order.index(spec.stage)
        if idx > 0:
            upstream = keys.stage_key(order[idx - 1])
            add_node(upstream, "stage_outcome")
            edges.append({"from": upstream, "to": skey, "origin": "structural"})

    return {"nodes": nodes, "edges": edges}


def scan_candidates(db: Session, *, domain: str) -> list[dict]:
    out: list[dict] = []
    for spec in all_specs(domain):
        for segment in _segments_for(db, domain, spec):
            out.append({
                "metric": spec.key,
                "segment": segment,
                "direction": spec.direction,
                "subgraph": _structural_subgraph(domain, spec, segment),
            })
    return out