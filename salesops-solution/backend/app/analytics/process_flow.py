"""Process-flow aggregation: nodes (sub-processes) and edges (transitions)
across the whole pipeline or for a single stage.

Reads `trace_events`, classifies each event with the taxonomy, and returns:
  - nodes: one per sub-process touched in the window, with volume + auto/HITL/fail counts
  - edges: directed A -> B with case_count + avg_duration_ms
  - virtual START / END nodes so a viewer sees the entry and exit explicitly.

A "transition" is two consecutive matched events for the same pipeline_id
ordered by ts. Self-loops are dropped (no value on the chart). Edges whose
case_count is below `min_edge_cases` are dropped (default 2).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import Pipeline, TraceEvent
from .stage_detail import _event_matches
from .subprocess_taxonomy import STAGE_ORDER, SUBPROCESS_TAXONOMY


def _flat_subprocesses() -> list[dict]:
    """Flatten the taxonomy into [{stage, key, label, predicate, order}, ...]."""
    out: list[dict] = []
    for entry in SUBPROCESS_TAXONOMY:
        stage = entry["stage"]
        for sp in entry["subprocesses"]:
            out.append({
                "stage": stage,
                "stage_order": STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 999,
                "key": sp["key"],
                "label": sp["label"],
                "predicate": sp["match"],
            })
    return out


def process_flow(
    db: Session,
    window_days: int = 30,
    stage: str | None = None,
    min_edge_cases: int = 2,
) -> dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    subs = _flat_subprocesses()
    if stage:
        subs = [s for s in subs if s["stage"] == stage]

    # Build the predicate ↔ key lookup
    keyed = [(s["key"], s["stage"], s["predicate"]) for s in subs]

    # Pull all relevant events
    relevant_stages = sorted({s["stage"] for s in subs} | {"pre_intake"})
    events = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage.in_(relevant_stages))
        .filter(TraceEvent.ts >= cutoff)
        .filter(TraceEvent.pipeline_id.isnot(None))
        .order_by(TraceEvent.pipeline_id.asc(), TraceEvent.ts.asc())
        .all()
    )

    # For each event, find the first matching sub-process key
    def event_key(ev: TraceEvent) -> str | None:
        for key, _stage, pred in keyed:
            if _event_matches(ev, pred):
                return key
        return None

    # Group event sequences by pipeline
    seqs: dict[int, list[tuple[str, datetime, int]]] = defaultdict(list)
    for ev in events:
        k = event_key(ev)
        if not k:
            continue
        # Collapse runs of the same key into one entry to avoid self-loops
        prev = seqs[ev.pipeline_id][-1] if seqs[ev.pipeline_id] else None
        if prev and prev[0] == k:
            continue
        seqs[ev.pipeline_id].append((k, ev.ts, ev.duration_ms or 0))

    # Pipeline tier for auto / HITL / fail bucketing
    pipe_ids = list(seqs.keys())
    pipes = {p.id: p for p in db.query(Pipeline).filter(Pipeline.id.in_(pipe_ids)).all()} if pipe_ids else {}

    # Sub-processes that belong to the Continuous Learning stage are
    # human-gated by design (Promote, rollback, drift triage), so every case
    # that touches them buckets as `hitl` regardless of the parent pipeline's
    # autonomy_tier.
    learning_keys = {s["key"] for s in subs if s["stage"] == "learning"}

    def bucket(pid: int, node_key: str | None = None) -> str:
        p = pipes.get(pid)
        if not p:
            return "auto"
        if p.status == "discarded" or (p.error or "").strip():
            return "fail"
        if node_key in learning_keys:
            return "hitl"
        if p.autonomy_tier == "L4_AUTO":
            return "auto"
        return "hitl"

    # Aggregate nodes and edges
    node_volume: dict[str, set[int]] = defaultdict(set)
    node_bucket: dict[str, dict[str, int]] = defaultdict(lambda: {"auto": 0, "hitl": 0, "fail": 0})
    edge_volume: dict[tuple[str, str], set[int]] = defaultdict(set)
    edge_durations: dict[tuple[str, str], list[int]] = defaultdict(list)
    started_edges: dict[int, bool] = {}

    START, END = "__START__", "__END__"

    for pid, seq in seqs.items():
        if not seq:
            continue
        # virtual START -> first
        first_key = seq[0][0]
        edge_volume[(START, first_key)].add(pid)
        # walk
        for i in range(len(seq) - 1):
            a, ts_a, _ = seq[i]
            b, ts_b, dur_b = seq[i + 1]
            node_volume[a].add(pid)
            edge_volume[(a, b)].add(pid)
            if ts_a and ts_b:
                d_ms = int((ts_b - ts_a).total_seconds() * 1000)
                if d_ms > 0:
                    edge_durations[(a, b)].append(d_ms)
        # last node + END
        last_key = seq[-1][0]
        node_volume[last_key].add(pid)
        edge_volume[(last_key, END)].add(pid)
        # Bucket counts must be per-pipeline-per-node, not per-event. A
        # pipeline that ping-pongs through the same sub-process (A -> B -> A)
        # otherwise gets counted twice in node A's bucket totals, inflating
        # `auto + hitl + fail` above the distinct-pipeline `volume`. Dedupe
        # the visited nodes for this pipeline before incrementing buckets.
        visited_nodes: set[str] = set()
        for k_, _, _ in seq:
            if k_ in visited_nodes:
                continue
            visited_nodes.add(k_)
            node_bucket[k_][bucket(pid, k_)] += 1
        started_edges[pid] = True

    # Label lookup
    label_for = {s["key"]: s["label"] for s in subs}
    stage_for = {s["key"]: s["stage"] for s in subs}

    # Build node + edge lists
    nodes: list[dict] = []
    for key in sorted(node_volume.keys(), key=lambda k: (next((s["stage_order"] for s in subs if s["key"] == k), 999), k)):
        vol = len(node_volume[key])
        b = node_bucket[key]
        total = b["auto"] + b["hitl"] + b["fail"] or 1
        nodes.append({
            "id": key,
            "label": label_for.get(key, key),
            "stage": stage_for.get(key),
            "volume": vol,
            "auto": b["auto"],
            "hitl": b["hitl"],
            "fail": b["fail"],
            "auto_pct": round(b["auto"] / total * 100, 1),
            "hitl_pct": round(b["hitl"] / total * 100, 1),
            "fail_pct": round(b["fail"] / total * 100, 1),
        })
    # virtual nodes
    nodes.insert(0, {"id": START, "label": "Start", "stage": None, "volume": len(seqs), "auto": 0, "hitl": 0, "fail": 0, "auto_pct": 0, "hitl_pct": 0, "fail_pct": 0, "virtual": True})
    nodes.append({"id": END, "label": "End", "stage": None, "volume": len(seqs), "auto": 0, "hitl": 0, "fail": 0, "auto_pct": 0, "hitl_pct": 0, "fail_pct": 0, "virtual": True})

    edges: list[dict] = []
    for (a, b), pid_set in edge_volume.items():
        n = len(pid_set)
        if n < min_edge_cases:
            continue
        durs = edge_durations.get((a, b), [])
        avg_ms = int(sum(durs) / len(durs)) if durs else 0
        edges.append({
            "source": a,
            "target": b,
            "case_count": n,
            "avg_duration_ms": avg_ms,
        })

    return {
        "window_days": window_days,
        "stage": stage,
        "total_cases": len(seqs),
        "nodes": nodes,
        "edges": edges,
        "min_edge_cases": min_edge_cases,
    }
