"""Per-stage detail rollups computed live from trace_events + the taxonomy.

Single entry point: `stage_detail(db, stage_key)` returns a dict ready for
the Analytics per-stage detail page. Every per-sub-process count, latency
and split is computed against the taxonomy declared in subprocess_taxonomy;
this module never hard-codes a sub-process aggregation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    ABExperiment,
    DriftAlert,
    Feedback,
    LearningOpportunity,
    Pipeline,
    TraceEvent,
)
from .subprocess_taxonomy import STAGE_META, subprocesses_for


def _event_matches(ev: TraceEvent, predicate: dict) -> bool:
    """Return True iff a trace event matches a sub-process predicate."""
    data = ev.data if isinstance(ev.data, dict) else {}
    # tools: tool_end events with data["tool"] in the list
    tools = predicate.get("tools")
    if tools and ev.kind == "tool_end" and data.get("tool") in tools:
        # Optional `stages` further restricts the match (e.g. translate_to_english appears in both intake and communicate).
        allowed_stages = predicate.get("stages")
        if not allowed_stages or ev.stage in allowed_stages:
            return True
    # substeps: substep_done events with data["substep"] in the list
    substeps = predicate.get("substeps")
    if substeps and ev.kind == "substep_done" and data.get("substep") in substeps:
        return True
    # kinds: bare event kinds (e.g. rule_matched, redirect)
    kinds = predicate.get("kinds")
    if kinds and ev.kind in kinds:
        allowed_stages = predicate.get("stages")
        if not allowed_stages or ev.stage in allowed_stages:
            return True
    return False


def _bucket_for_pipeline(p: Pipeline, stage_key: str | None = None) -> str:
    """Classify a pipeline run as auto / hitl / fail for sub-process rollups.

    Continuous Learning is gated by human Promote (and human-driven rollback /
    drift triage), so every case that reaches a learning sub-process carries
    a human touchpoint by design — those buckets are forced to `hitl` even
    when the parent pipeline closed L4_AUTO."""
    if p.status == "discarded" or (p.error or "").strip():
        return "fail"
    if stage_key == "learning":
        return "hitl"
    if p.autonomy_tier == "L4_AUTO":
        return "auto"
    return "hitl"


def stage_detail(db: Session, stage_key: str, window_days: int = 30) -> dict[str, Any]:
    """Aggregate everything the per-stage page needs in one query pass."""
    if stage_key not in STAGE_META:
        raise ValueError(f"unknown stage {stage_key!r}")

    cutoff = datetime.utcnow() - timedelta(days=window_days)
    meta = STAGE_META[stage_key]
    subs = subprocesses_for(stage_key)

    # --- Stage-level KPIs from stage_end events + pipelines ------------------
    stage_end_rows = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == stage_key)
        .filter(TraceEvent.kind == "stage_end")
        .filter(TraceEvent.ts >= cutoff)
        .all()
    )
    pipe_ids_in_stage = {ev.pipeline_id for ev in stage_end_rows if ev.pipeline_id is not None}
    if stage_key == "learning":
        # Continuous Learning does not emit stage_end trace events; its real
        # population is "pipelines that contributed at least one Feedback
        # signal." Use the same source the Dashboard funnel uses so the page
        # actually reflects work.
        learning_pipe_ids = {
            int(pid)
            for (pid,) in db.query(Feedback.pipeline_id)
            .filter(Feedback.pipeline_id.isnot(None))
            .filter(Feedback.created_at >= cutoff)
            .distinct()
            .all()
            if pid is not None
        }
        pipe_ids_in_stage = learning_pipe_ids
    pipes_in_stage: dict[int, Pipeline] = {
        p.id: p
        for p in db.query(Pipeline).filter(Pipeline.id.in_(pipe_ids_in_stage)).all()
    }
    fail_n = sum(1 for p in pipes_in_stage.values() if p.status == "discarded" or (p.error or "").strip())
    if stage_key == "learning":
        # Continuous Learning never closes end-to-end without a human (Promote
        # gate, drift triage, rollback). Force the totals to reflect that.
        auto_n = 0
        hitl_n = sum(1 for p in pipes_in_stage.values() if not (p.status == "discarded" or (p.error or "").strip()))
    else:
        auto_n = sum(1 for p in pipes_in_stage.values() if p.autonomy_tier == "L4_AUTO")
        hitl_n = sum(1 for p in pipes_in_stage.values() if p.autonomy_tier in ("L3_ONE_CLICK", "L2_HITL"))

    durations = [int(ev.duration_ms) for ev in stage_end_rows if ev.duration_ms is not None]
    avg_latency_ms = int(sum(durations) / len(durations)) if durations else 0
    p95_latency_ms = sorted(durations)[max(0, int(len(durations) * 0.95) - 1)] if durations else 0

    # --- Pull every event in the window once and classify per sub-process ----
    # Sub-process events live across several stage names (intake sub-processes
    # can use pre_intake events too), so we collect over the full list of
    # stages referenced by this stage's predicates.
    relevant_stages: set[str] = {stage_key}
    for sp in subs:
        for s in sp["match"].get("stages", []) or []:
            relevant_stages.add(s)
        # outlook_prefilter for intake reaches into pre_intake stage
    if stage_key == "intake":
        relevant_stages.add("pre_intake")

    candidate_events = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage.in_(relevant_stages))
        .filter(TraceEvent.ts >= cutoff)
        .all()
    )

    # Sub-process rollups -----------------------------------------------------
    subprocess_rollups: list[dict] = []
    for sp in subs:
        pred = sp["match"]
        pipe_set: set[int] = set()
        durations_sp: list[int] = []
        if pred.get("_source"):
            # Learning sub-processes draw from the ledger tables.
            n, rows_for_split = _ledger_count_for(db, pred["_source"], cutoff)
            subprocess_rollups.append({
                "key": sp["key"],
                "label": sp["label"],
                "description": sp["description"],
                "volume": n,
                "auto": 0, "hitl": 0, "fail": 0,
                "auto_pct": 0.0, "hitl_pct": 0.0, "fail_pct": 0.0,
                "avg_latency_ms": 0,
                "source": pred["_source"],
                "ledger_rows": rows_for_split,
            })
            continue

        matched_events: list[TraceEvent] = []
        for ev in candidate_events:
            if _event_matches(ev, pred):
                matched_events.append(ev)
                if ev.pipeline_id is not None:
                    pipe_set.add(int(ev.pipeline_id))
                if ev.duration_ms is not None:
                    durations_sp.append(int(ev.duration_ms))

        # auto/hitl/fail split: pick the parent pipeline's bucket
        bucket_counts = {"auto": 0, "hitl": 0, "fail": 0}
        if pipe_set:
            pipes = db.query(Pipeline).filter(Pipeline.id.in_(pipe_set)).all()
            for p in pipes:
                bucket_counts[_bucket_for_pipeline(p, stage_key)] += 1

        vol = len(pipe_set)
        total = bucket_counts["auto"] + bucket_counts["hitl"] + bucket_counts["fail"] or 1
        avg_lat = int(sum(durations_sp) / len(durations_sp)) if durations_sp else 0

        subprocess_rollups.append({
            "key": sp["key"],
            "label": sp["label"],
            "description": sp["description"],
            "volume": vol,
            "auto": bucket_counts["auto"],
            "hitl": bucket_counts["hitl"],
            "fail": bucket_counts["fail"],
            "auto_pct": round(bucket_counts["auto"] / total * 100, 1),
            "hitl_pct": round(bucket_counts["hitl"] / total * 100, 1),
            "fail_pct": round(bucket_counts["fail"] / total * 100, 1),
            "avg_latency_ms": avg_lat,
            "source": "trace_events",
        })

    # --- Opportunities tied to this stage ------------------------------------
    stage_segment_substrs = [stage_key, meta["label"].split()[0]]
    opps_q = db.query(LearningOpportunity).filter(
        LearningOpportunity.status.in_(["open", "accepted", "in_ab", "promoted", "deferred"])
    )
    stage_opps = [
        {
            "id": o.id,
            "segment": o.segment,
            "fingerprint": o.fingerprint,
            "proposed_remedy": o.proposed_remedy,
            "expected_lift": o.expected_lift,
            "effort": o.effort, "risk": o.risk, "score": o.score,
            "status": o.status,
        }
        for o in opps_q.all()
    ]

    return {
        "stage_key": stage_key,
        "stage_id": meta["id"],
        "stage_label": meta["label"],
        "tagline": meta["tagline"],
        "window_days": window_days,
        "totals": {
            "pipelines": len(pipe_ids_in_stage),
            "auto": auto_n,
            "hitl": hitl_n,
            "fail": fail_n,
            "avg_latency_ms": avg_latency_ms,
            "p95_latency_ms": p95_latency_ms,
        },
        "subprocesses": subprocess_rollups,
        "opportunities": stage_opps,
    }


def _ledger_count_for(db: Session, source: str, cutoff: datetime) -> tuple[int, int]:
    if source == "feedback_table":
        n = db.query(func.count(func.distinct(Feedback.pipeline_id))).filter(Feedback.created_at >= cutoff).scalar() or 0
        rows = db.query(func.count(Feedback.id)).filter(Feedback.created_at >= cutoff).scalar() or 0
        return int(n), int(rows)
    if source == "drift_alerts_table":
        n = db.query(func.count(DriftAlert.id)).filter(DriftAlert.detected_at >= cutoff).scalar() or 0
        return int(n), int(n)
    if source == "learning_opportunities_table":
        n = db.query(func.count(LearningOpportunity.id)).filter(LearningOpportunity.detected_at >= cutoff).scalar() or 0
        return int(n), int(n)
    if source == "ab_experiments_table":
        n = db.query(func.count(ABExperiment.id)).filter(ABExperiment.started_at >= cutoff).scalar() or 0
        return int(n), int(n)
    return 0, 0
