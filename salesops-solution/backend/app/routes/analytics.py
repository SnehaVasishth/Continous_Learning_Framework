import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import INTENTS
from ..db import get_db
from ..models import (
    AIOARequest,
    CommunicationLog,
    Customer,
    Email,
    EmailAccount,
    Feedback,
    HitlTask,
    Pipeline,
    TraceEvent,
)

router = APIRouter()


# Mirrors the Keysight POC's 9-class taxonomy on the Activepieces sheet.
# Every internal pipeline intent maps to exactly one front-office category.
_INTENT_TO_CATEGORY: dict[str, str] = {
    "po_intake": "SALES_PO",
    "quote_to_order": "SALES_PO",
    "trade_change_order": "SALES_PO",
    "hold_release": "SALES_PO",
    "ssd_change_request": "OTHERS",
    "delivery_change": "OTHERS",
    "service_order": "ISC_WO_RTK",
    "wo_update_request": "ISC_WO_RTK",
    "wo_status_inquiry": "ISC_WO_RTK",
    "service_contract_request": "ISC_WO_RTK",
    "general_inquiry": "OTHERS",
    "out_of_scope": "AUTO_REPLY",
    "spam": "OTHERS",
}


def _category_for_intent(intent: str | None) -> str:
    if not intent:
        return "OTHERS"
    return _INTENT_TO_CATEGORY.get(intent, "OTHERS")


def _by_owner(pipes) -> dict[str, int]:
    """Roll pipelines up by their decision.owner.owner_label so the Analytics
    page can render a by-owner doughnut. Pipelines without an owner show as
    'Unassigned' so the operator sees what's slipping through."""
    out: dict[str, int] = {}
    for p in pipes:
        owner = (((p.decision or {}).get("owner") or {}).get("owner_label")) or "Unassigned"
        out[owner] = out.get(owner, 0) + 1
    return out


def _ops_status_from_pipeline(status: str | None) -> str:
    if status in ("completed", "discarded"):
        return "Success"
    if status == "awaiting_hitl":
        return "Pending"
    if status in ("failed", "error"):
        return "Fail"
    if status == "running":
        return "Pending"
    return ""


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@router.get("/summary")
def summary(since_hours: int = 0, db: Session = Depends(get_db)):
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=since_hours)
        if since_hours and since_hours > 0
        else None
    )
    pipe_q = db.query(Pipeline)
    if cutoff is not None:
        pipe_q = pipe_q.filter(Pipeline.started_at >= cutoff)
    pipes = pipe_q.all()

    # In-funnel pipelines are those that emitted at least one stage_end event
    # for a Stage 1+ stage (intake, extract, decide, execute, communicate).
    # Pipelines that only triggered pre_intake events (mailbox-door redirects,
    # spam, KSO routing, Brazil tax, collections, undeliverable, portal admin)
    # are excluded so the funnel-top count matches the per-stage funnel
    # rendered downstream. The pre-intake-terminated count is exposed
    # separately on the totals dict for visibility.
    _FUNNEL_STAGES = ("intake", "extract", "decide", "execute", "communicate")
    funnel_q = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.kind == "stage_end")
        .filter(TraceEvent.stage.in_(_FUNNEL_STAGES))
        .distinct()
    )
    funnel_pipe_ids: set[int] = {int(r[0]) for r in funnel_q.all() if r[0] is not None}
    in_funnel_pipes = [p for p in pipes if p.id in funnel_pipe_ids]
    pre_intake_terminated = len(pipes) - len(in_funnel_pipes)

    total = len(in_funnel_pipes)
    completed = sum(1 for p in in_funnel_pipes if p.status == "completed")
    rejected = sum(1 for p in in_funnel_pipes if p.status == "rejected")
    running = sum(1 for p in in_funnel_pipes if p.status == "running")
    errored = sum(1 for p in in_funnel_pipes if p.status == "error")
    awaiting_aioa = sum(1 for p in in_funnel_pipes if p.status == "awaiting_aioa")

    auto_count = sum(1 for p in pipes if p.autonomy_tier == "L4_AUTO")
    one_click = sum(1 for p in pipes if p.autonomy_tier == "L3_ONE_CLICK")
    full_hitl = sum(1 for p in pipes if p.autonomy_tier == "L2_HITL")

    hitl_q = db.query(HitlTask).filter(HitlTask.status == "pending")
    fb_q = db.query(Feedback)
    if cutoff is not None:
        hitl_q = hitl_q.filter(HitlTask.created_at >= cutoff)
        fb_q = fb_q.filter(Feedback.created_at >= cutoff)
    pending_hitl = hitl_q.count()
    feedback_count = fb_q.count()
    edits = fb_q.filter(Feedback.kind == "edit_and_approve").count()
    rejects = fb_q.filter(Feedback.kind == "reject").count()

    # Latency metrics only count pipelines that completed cleanly and finished
    # within a sane wall-clock window. Errored pipelines and any run whose
    # duration is suspiciously long (>30 min) are excluded — those are almost
    # always backend-restart victims where started_at is real but finished_at
    # was stamped by the zombie sweep, which would otherwise drag the average
    # into hours.
    _MAX_REAL_PIPELINE_MS = 30 * 60 * 1000
    durations = []
    for p in pipes:
        if p.status != "completed":
            continue
        if not (p.finished_at and p.started_at):
            continue
        dur_ms = int((p.finished_at - p.started_at).total_seconds() * 1000)
        if dur_ms < 0 or dur_ms > _MAX_REAL_PIPELINE_MS:
            continue
        durations.append(dur_ms)
    avg_ms = int(sum(durations) / len(durations)) if durations else 0

    # Intent / language / flow distributions are scoped to the in-funnel set
    # so the Dashboard "Intent mix" doughnut sums to `totals.pipelines`. The
    # pre-intake-terminated pipelines (mailbox-door redirects, spam, KSO,
    # Brazil tax, collections, undeliverable, portal admin) are surfaced
    # separately on the Mailbox-triage tile and must not bleed into the
    # funnel-scoped doughnut, or the slices would exceed the meta count.
    intents = Counter(p.intent for p in in_funnel_pipes if p.intent)
    langs = Counter(p.language for p in in_funnel_pipes if p.language)
    flows = Counter((p.decision or {}).get("flow") for p in in_funnel_pipes if (p.decision or {}).get("flow"))

    mismatch_kinds: Counter = Counter()
    multi_intent_count = 0
    misroute_count = 0
    for p in pipes:
        recon = p.reconcile or {}
        for issue in recon.get("issues") or []:
            kind = issue.get("kind")
            if kind:
                mismatch_kinds[kind] += 1
        intake_data = next((e.data for e in (p.events if hasattr(p, "events") else []) if e.kind == "result"), None)
        if (p.decision or {}).get("misroute"):
            misroute_count += 1

    intake_results = (
        db.query(TraceEvent)
        .filter_by(stage="intake", kind="result")
        .all()
    )
    pipe_ids = {p.id for p in pipes}
    for ev in intake_results:
        if ev.pipeline_id not in pipe_ids:
            continue
        secondary = (ev.data or {}).get("secondary_intents") or []
        if isinstance(secondary, list) and len(secondary) > 0:
            multi_intent_count += 1

    email_q = db.query(Email)
    if cutoff is not None:
        email_q = email_q.filter(Email.received_at >= cutoff)
    # Total ingested excludes stale unworkable mail. Those rows stay in the
    # DB for audit but never surface on operator-facing tiles. Counting them
    # in "ingested" would inflate the number the operator sees and divorce
    # it from the actionable queue.
    inbox_total = email_q.filter(Email.status != "expired_unworkable").count()
    # "New" must mean genuinely untouched. An email whose pipeline has moved
    # past `running` (awaiting_hitl, awaiting_aioa, completed, discarded,
    # error) has already been processed even if Email.status was never
    # synced back. Derive the count from the live pipeline join so it can't
    # drift from reality.
    started_email_ids_q = (
        db.query(Pipeline.email_id)
        .filter(Pipeline.email_id.isnot(None))
        .filter(Pipeline.status != "running")
        .distinct()
    )
    inbox_unprocessed = (
        email_q.filter(Email.status == "new")
        .filter(~Email.id.in_(started_email_ids_q))
        .count()
    )

    comm_q = db.query(CommunicationLog)
    if cutoff is not None:
        comm_q = comm_q.filter(CommunicationLog.occurred_at >= cutoff)
    comm_total = comm_q.count()
    comm_l4 = comm_q.filter(CommunicationLog.autonomy_tier == "L4_AUTO").count()
    comm_hitl = comm_total - comm_l4

    # Automation rate denominator: tiered pipelines only (those that reached
    # Decide and got an autonomy_tier stamp). Pipelines that never got a tier
    # were either pre-pipeline short-circuits (spam, KSO redirect, Brazil tax,
    # collections, portal admin, undeliverable) or errored before Decide.
    # Neither was ever eligible for L4_AUTO, so including them in the
    # denominator artificially deflates the rate. The "closed without a
    # human" label on the Dashboard reads L4_AUTO only.
    tiered = auto_count + one_click + full_hitl
    automation_rate = (auto_count / tiered) if tiered else 0.0
    # One-click rate: L3 is still operator-touched, but minimally. Surface
    # it separately so the UI can show "L4 auto + L3 one-click" if useful.
    one_click_rate = (one_click / tiered) if tiered else 0.0
    accuracy_proxy = ((completed - edits) / completed) if completed else 0.0

    # ------------------------------------------------------------------
    # Mailbox-door triage (Stage 0 deterministic pre-intake)
    # Per-filter counts for the Dashboard tile: spam, KSO, Brazil tax,
    # portal admin, collections, undeliverable, out-of-scope, plus any
    # other rule key the operator added to the outlook_rules namespace.
    # ------------------------------------------------------------------
    triage_q = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "pre_intake")
        .filter(TraceEvent.kind == "rule_matched")
    )
    if cutoff is not None:
        triage_q = triage_q.filter(TraceEvent.ts >= cutoff)
    triage_events = triage_q.all()
    triage_events = [e for e in triage_events if e.pipeline_id in pipe_ids]
    triage_filter_counts: Counter = Counter()
    for ev in triage_events:
        data = ev.data or {}
        intent = (data.get("intent") or "unknown").lower()
        triage_filter_counts[intent] += 1
    # Also surface the count of emails that fell through to the LLM
    # classifier (no deterministic rule matched).
    triage_fallthrough_q = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "pre_intake")
        .filter(TraceEvent.kind == "no_match")
    )
    if cutoff is not None:
        triage_fallthrough_q = triage_fallthrough_q.filter(TraceEvent.ts >= cutoff)
    triage_fallthrough_events = [
        e for e in triage_fallthrough_q.all() if e.pipeline_id in pipe_ids
    ]
    triage_total_evaluated = len(triage_events) + len(triage_fallthrough_events)

    # ------------------------------------------------------------------
    # AIOA outcomes (substep 3.0c — Trade Order Entry / SOM WO Update /
    # Service Contract flows). The trace event includes outcome and the
    # request_id so the Fallout queue can be linked back to the original
    # AIOA response.
    # ------------------------------------------------------------------
    aioa_q = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "decide")
        .filter(TraceEvent.kind == "substep_done")
    )
    if cutoff is not None:
        aioa_q = aioa_q.filter(TraceEvent.ts >= cutoff)
    aioa_pass = 0
    aioa_fail = 0
    aioa_skipped = 0
    for ev in aioa_q.all():
        if ev.pipeline_id not in pipe_ids:
            continue
        data = ev.data or {}
        if data.get("substep") != "3.0c":
            continue
        if data.get("applies") is False:
            aioa_skipped += 1
            continue
        outcome = ((data.get("aioa_response") or {}).get("outcome") or "").upper()
        if outcome == "AIOA_PASS":
            aioa_pass += 1
        elif outcome == "AIOA_FAIL":
            aioa_fail += 1

    # AIOA timeouts are tracked on the AIOARequest row (the timeout sweep
    # marks status='timed_out'). They are an operationally distinct outcome
    # from pass/fail/skipped: the AIOA provider never responded, the
    # pipeline was advanced to the HITL queue for manual handling. Keep
    # the bucket separate so the Dashboard tile can show pass/fail/skipped
    # next to a dedicated timed_out count without losing semantic fidelity.
    aioa_timed_out_q = db.query(AIOARequest).filter(AIOARequest.status == "timed_out")
    if cutoff is not None:
        aioa_timed_out_q = aioa_timed_out_q.filter(AIOARequest.created_at >= cutoff)
    aioa_timed_out = sum(
        1 for r in aioa_timed_out_q.all() if r.pipeline_id in pipe_ids
    )

    # ------------------------------------------------------------------
    # CMD activation requests (substep 2.3.1) — fired when extract Stage 2
    # cannot resolve the customer against Salesforce and the standard
    # Keysight CMD activation pattern is triggered.
    # ------------------------------------------------------------------
    cmd_q = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "extract")
        .filter(TraceEvent.kind == "cmd_activation_requested")
    )
    if cutoff is not None:
        cmd_q = cmd_q.filter(TraceEvent.ts >= cutoff)
    cmd_activation_count = sum(1 for e in cmd_q.all() if e.pipeline_id in pipe_ids)

    # ------------------------------------------------------------------
    # Throughput tiles (G3 scale view) — p50/p95/p99 pipeline latency,
    # emails per minute, queue depth. Drives the Dashboard scale tiles
    # that the 2,000 emails/day commitment hangs on.
    # ------------------------------------------------------------------
    p50_ms = _percentile(durations, 0.5)
    p95_ms = _percentile(durations, 0.95)
    p99_ms = _percentile(durations, 0.99)
    minutes_window = (since_hours * 60) if since_hours and since_hours > 0 else max(1, _engagement_window_minutes(pipes))
    emails_per_minute = round(total / minutes_window, 2) if minutes_window else 0.0
    # Queue depth = mail still to triage + currently running. `running` is the
    # live count from this snapshot (zombies are swept on startup) so this is
    # the operator's true backlog.
    queue_depth = max(0, inbox_unprocessed + running)

    return {
        "since_hours": since_hours or 0,
        "totals": {
            "pipelines": total,
            "completed": completed,
            "rejected": rejected,
            "running": running,
            "errored": errored,
            "awaiting_aioa": awaiting_aioa,
            "pending_hitl": pending_hitl,
            "inbox_total": inbox_total,
            "inbox_unprocessed": inbox_unprocessed,
            "pre_intake_terminated": pre_intake_terminated,
        },
        "autonomy": {
            "L4_AUTO": auto_count,
            "L3_ONE_CLICK": one_click,
            "L2_HITL": full_hitl,
            "tiered_total": tiered,
            "automation_rate": round(automation_rate, 4),
            "one_click_rate": round(one_click_rate, 4),
        },
        "feedback": {
            "total": feedback_count,
            "edits": edits,
            "rejects": rejects,
        },
        "quality": {
            "accuracy_proxy": round(accuracy_proxy, 4),
            "avg_processing_ms": avg_ms,
        },
        "throughput": {
            "emails_per_minute": emails_per_minute,
            "queue_depth": queue_depth,
            "p50_ms": p50_ms,
            "p95_ms": p95_ms,
            "p99_ms": p99_ms,
        },
        "mailbox_door_triage": {
            "total_evaluated": triage_total_evaluated,
            "matched_by_rule": len(triage_events),
            "fell_through_to_llm": len(triage_fallthrough_events),
            "by_filter": dict(triage_filter_counts),
        },
        "aioa": {
            "pass": aioa_pass,
            "fail": aioa_fail,
            "skipped_not_applicable": aioa_skipped,
            "timed_out": aioa_timed_out,
        },
        "cmd_activation": {
            "requested": cmd_activation_count,
        },
        "by_intent": dict(intents),
        "by_language": dict(langs),
        "by_flow": dict(flows),
        "by_owner": _by_owner(pipes),
        "mismatch_kinds": dict(mismatch_kinds),
        "multi_intent_pipelines": multi_intent_count,
        "misroute_pipelines": misroute_count,
        "intent_taxonomy_size": len(INTENTS),
        "communications": {
            "total": comm_total,
            "auto_sent": comm_l4,
            "csr_approved": comm_hitl,
        },
    }


def _engagement_window_minutes(pipes: list) -> int:
    """Approximate the time window between the earliest pipeline start and now.
    Handles naive and tz-aware datetimes by coercing both to UTC-aware."""
    if not pipes:
        return 1
    started = [p.started_at for p in pipes if p.started_at]
    if not started:
        return 1
    earliest = min(started)
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - earliest
    return max(1, int(delta.total_seconds() // 60))


_FABRIC_STAGES = ["intake", "extract", "decide", "execute", "communicate", "learning"]
_NORMALIZE_RE = re.compile(r"normalized(?: intent alias)?:\s*([^\s]+)\s*->\s*([^\s]+)")


def _percentile(values: list[int], pct: float) -> int:
    """Linear-interpolation percentile over a list of ints; 0 if empty."""
    if not values:
        return 0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return int(s[lo] + (s[hi] - s[lo]) * frac)


from ..analytics.cost import cost_coverage, cost_rollup
from ..analytics.process_flow import process_flow
from ..analytics.stage_detail import stage_detail
from ..analytics.subprocess_taxonomy import STAGE_META, stages_in_order


@router.get("/stages")
def list_stages() -> list[dict]:
    """The canonical stage ordering + metadata. Front of every stage UI."""
    return stages_in_order()


@router.get("/stage/{stage_key}")
def stage_detail_endpoint(
    stage_key: str,
    window_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    """Per-stage detail rollup, taxonomy-driven."""
    if stage_key not in STAGE_META:
        raise HTTPException(404, f"unknown stage {stage_key!r}")
    return stage_detail(db, stage_key, window_days=window_days)


@router.get("/cost")
def cost_endpoint(
    window_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    """Cost rollup with a coverage check. The UI must verify
    coverage.fully_covered == true before rendering dollar figures."""
    return {
        "rollup": cost_rollup(db, window_days=window_days),
        "coverage": cost_coverage(db, window_days=window_days),
    }


@router.get("/process_flow")
def process_flow_endpoint(
    window_days: int = Query(30, ge=1, le=365),
    stage: str | None = Query(None),
    min_edge_cases: int = Query(2, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    """Nodes + edges for the case-flow process map. Optional stage filter
    scopes the graph to a single stage."""
    if stage and stage not in STAGE_META:
        raise HTTPException(404, f"unknown stage {stage!r}")
    return process_flow(db, window_days=window_days, stage=stage, min_edge_cases=min_edge_cases)


@router.get("/cases")
def list_cases(
    stage: str | None = Query(None, description="Optional processing stage to filter by"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List one row per pipeline run (a case), joined with its email metadata.

    Each pipeline is one case. The stage filter scopes the list to pipelines that
    completed the named stage (sourced from `stage_end` trace events for
    intake/extract/decide/execute/communicate, and from captured Feedback for
    learning). When no stage filter is supplied, all pipelines are returned.
    """
    # Pipeline IDs in the requested stage, if any
    stage_pipeline_ids: set[int] | None = None
    if stage:
        if stage == "learning":
            stage_pipeline_ids = {
                int(pid)
                for (pid,) in db.query(Feedback.pipeline_id)
                .filter(Feedback.pipeline_id.isnot(None))
                .distinct()
                .all()
                if pid is not None
            }
        elif stage in _FABRIC_STAGES:
            stage_pipeline_ids = {
                int(pid)
                for (pid,) in db.query(TraceEvent.pipeline_id)
                .filter(TraceEvent.kind == "stage_end")
                .filter(TraceEvent.stage == stage)
                .filter(TraceEvent.pipeline_id.isnot(None))
                .distinct()
                .all()
                if pid is not None
            }
        else:
            return []
        if not stage_pipeline_ids:
            return []

    q = (
        db.query(Pipeline, Email)
        .join(Email, Email.id == Pipeline.email_id)
        .order_by(Pipeline.started_at.desc())
    )
    if stage_pipeline_ids is not None:
        q = q.filter(Pipeline.id.in_(stage_pipeline_ids))

    pairs = q.all()
    cust_ids = {email.customer_id for _, email in pairs if email.customer_id}
    customers = {
        c.id: c.name
        for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()
    } if cust_ids else {}

    rows: list[dict] = []
    for pipe, email in pairs:
        rows.append({
            "pipeline_id": int(pipe.id),
            "email_id": int(email.id),
            "subject": email.subject,
            "from": email.from_address,
            "received_at": _iso(email.received_at),
            "language_hint": email.language_hint,
            "customer_name": customers.get(email.customer_id) if email.customer_id else None,
            "status": pipe.status,
            "intent": pipe.intent,
            "language": pipe.language,
            "confidence": float(pipe.confidence) if pipe.confidence is not None else None,
            "autonomy_tier": pipe.autonomy_tier,
            "started_at": _iso(pipe.started_at),
        })
    return rows


@router.get("/agent_fabric")
def agent_fabric(db: Session = Depends(get_db)):
    """Aggregate trace events into per-stage, per-tool, and KB-rule metrics for the fabric dashboard."""
    pipes = db.query(Pipeline).all()
    pipe_ids = {p.id for p in pipes}

    stage_buckets: dict[str, list[int]] = {s: [] for s in _FABRIC_STAGES}
    stage_pipe_sets: dict[str, set[int]] = {s: set() for s in _FABRIC_STAGES}
    stage_end_events = (
        db.query(TraceEvent)
        .filter(TraceEvent.kind == "stage_end")
        .all()
    )
    for ev in stage_end_events:
        if ev.stage not in stage_buckets:
            continue
        if ev.duration_ms is None:
            continue
        stage_buckets[ev.stage].append(int(ev.duration_ms))
        if ev.pipeline_id is not None:
            stage_pipe_sets[ev.stage].add(int(ev.pipeline_id))

    # Continuous Learning is a real cycle, not a placeholder. A case is "at
    # Continuous Learning" only if it has at least one captured Feedback
    # record (CSR thumbs-up / thumbs-down / edit) or a drift signal logged
    # against it. The Stage-6 agent stub that recorded zero-feedback events
    # on early pipelines is ignored here so the count reflects real signals.
    from ..models import Feedback  # local import to avoid widening top-of-file imports
    feedback_pipe_ids: set[int] = {
        int(pid)
        for (pid,) in db.query(Feedback.pipeline_id).filter(Feedback.pipeline_id.isnot(None)).distinct().all()
        if pid is not None
    }
    stage_pipe_sets["learning"] = feedback_pipe_ids
    # Reset learning duration bucket so its p50/p95 timing reflects only
    # pipelines that actually carry feedback. With no real signals, this is
    # empty and reads as zero, which is the honest answer.
    stage_buckets["learning"] = []

    # Per-stage auto vs HITL is derived from actual stage-level gate events,
    # NOT the pipeline's terminal autonomy_tier. A pipeline that ultimately
    # required HITL at Execute was still flowing autonomously through Intake
    # and Extract — those upstream stages did not pause for a human.
    # HITL signals per stage:
    #   execute  → "hitl_created" trace events (operator review tasks)
    #   extract  → "stage_blocked" trace events (CMD activation deferrals)
    # Decide stamps the tier for the pipeline as a whole but doesn't itself
    # pause for a human, so Decide reads as auto here. Intake and
    # Communicate have no human gates in the current pipeline.
    hitl_events = db.query(TraceEvent.stage, TraceEvent.pipeline_id).filter(
        TraceEvent.kind.in_(("hitl_created", "stage_blocked"))
    ).all()
    hitl_per_stage: dict[str, set[int]] = defaultdict(set)
    for st, pid in hitl_events:
        if pid is None or st not in stage_pipe_sets:
            continue
        hitl_per_stage[st].add(int(pid))

    # Per-pipeline autonomy_tier lookup is kept for the tier_l4/tier_l3/tier_l2
    # context fields (used by tooltips). It does not drive the auto_pct/hitl_pct
    # split per stage.
    all_stage_pipe_ids: set[int] = set()
    for s in stage_pipe_sets.values():
        all_stage_pipe_ids.update(s)
    tier_by_pipeline: dict[int, str] = {}
    if all_stage_pipe_ids:
        for pid, tier in db.query(Pipeline.id, Pipeline.autonomy_tier).filter(
            Pipeline.id.in_(all_stage_pipe_ids)
        ).all():
            if tier:
                tier_by_pipeline[int(pid)] = str(tier)

    # Stages at-or-after Execute carry the cumulative human touch from the
    # Execute gate: L4 cases flow through autonomously, L3 cases required a
    # one-click approval (human action), L2 cases required full review. By
    # Communicate (closeout) and Learning, that human work has already
    # happened, so only L4 should read as "auto" at those stages.
    # Upstream of Execute no human gate has fired yet (except CMD activation
    # deferrals at Extract), so the split there comes from real stage-level
    # gate events.
    _POST_EXECUTE = {"execute", "communicate", "learning"}

    def _stage_tier_split(stage_name: str, stage_pipe_ids: set[int]) -> dict[str, int]:
        l4 = l3 = l2 = unknown = 0
        for pid in stage_pipe_ids:
            t = tier_by_pipeline.get(int(pid))
            if t == "L4_AUTO":
                l4 += 1
            elif t == "L3_ONE_CLICK":
                l3 += 1
            elif t == "L2_HITL":
                l2 += 1
            else:
                unknown += 1
        total = len(stage_pipe_ids)
        if stage_name == "learning":
            # The Continuous Learning loop cannot close end-to-end without a
            # human: candidate experiments require Promote approval, drift
            # signals require investigation, and rollback is operator-driven.
            # Every case that contributes a learning signal carries a human
            # touchpoint by design, so Learning reads as 0% auto.
            auto_at_stage = 0
            hitl_at_stage = total
            auto_pct = 0.0
            hitl_pct = 100.0 if total else 0.0
        elif stage_name in _POST_EXECUTE:
            tiered = l4 + l3 + l2
            auto_at_stage = l4
            hitl_at_stage = l3 + l2
            auto_pct = round((auto_at_stage / tiered) * 100, 1) if tiered else 0.0
            hitl_pct = round((hitl_at_stage / tiered) * 100, 1) if tiered else 0.0
        else:
            gated_ids = hitl_per_stage.get(stage_name, set()) & stage_pipe_ids
            hitl_at_stage = len(gated_ids)
            auto_at_stage = total - hitl_at_stage
            auto_pct = round((auto_at_stage / total) * 100, 1) if total else 0.0
            hitl_pct = round((hitl_at_stage / total) * 100, 1) if total else 0.0
        return {
            "tier_l4": l4,
            "tier_l3": l3,
            "tier_l2": l2,
            "tier_unknown": unknown,
            "auto_count": auto_at_stage,
            "hitl_count": hitl_at_stage,
            "auto_pct": auto_pct,
            "hitl_pct": hitl_pct,
        }

    stage_timing: dict[str, dict[str, object]] = {}
    for stage, durations in stage_buckets.items():
        stage_timing[stage] = {
            "p50_ms": _percentile(durations, 0.5),
            "p95_ms": _percentile(durations, 0.95),
            "count": len(durations),
            "pipeline_ids": sorted(stage_pipe_sets[stage]),
            "pipeline_count": len(stage_pipe_sets[stage]),
            **_stage_tier_split(stage, stage_pipe_sets[stage]),
        }
    stage_timing["learning"]["count"] = len(stage_pipe_sets["learning"])

    tool_end_events = (
        db.query(TraceEvent)
        .filter(TraceEvent.kind == "tool_end")
        .all()
    )

    tool_buckets: dict[str, dict[str, list]] = defaultdict(lambda: {"durations": [], "ok": 0, "total": 0})
    fired_rule_counts: Counter = Counter()
    fired_rule_severity: dict[str, str] = {}
    fired_rule_last_ts: dict[str, datetime] = {}

    norm_total = 0
    norm_pipes_with_correction: set[int] = set()
    norm_pairs: Counter = Counter()

    provider_mix: Counter = Counter()

    for ev in tool_end_events:
        data = ev.data or {}
        tool_name = data.get("tool")
        if not tool_name:
            continue
        b = tool_buckets[tool_name]
        b["total"] += 1
        if data.get("ok"):
            b["ok"] += 1
        dur = data.get("duration_ms")
        if dur is None:
            dur = ev.duration_ms
        if dur is not None:
            b["durations"].append(int(dur))

        if tool_name == "business_rules_eval" and ev.stage == "decide" and data.get("ok"):
            inner = data.get("data") or {}
            fired = inner.get("fired") or inner.get("fired_rules") or []
            if isinstance(fired, list):
                for r in fired:
                    if not isinstance(r, dict):
                        continue
                    key = r.get("key") or r.get("rule_key")
                    if not key:
                        continue
                    fired_rule_counts[key] += 1
                    fired_rule_severity[key] = r.get("severity") or fired_rule_severity.get(key) or "warn"
                    if ev.ts and (key not in fired_rule_last_ts or ev.ts > fired_rule_last_ts[key]):
                        fired_rule_last_ts[key] = ev.ts

        if tool_name == "classify_intent" and ev.stage == "intake" and ev.pipeline_id in pipe_ids:
            norm_total += 1
            notes = data.get("notes") or []
            if isinstance(notes, list) and notes:
                norm_pipes_with_correction.add(ev.pipeline_id)
                for n in notes:
                    if not isinstance(n, str):
                        continue
                    m = _NORMALIZE_RE.search(n)
                    if m:
                        frm = m.group(1).rstrip(":,")
                        to = m.group(2).rstrip(":,")
                        norm_pairs[(frm, to)] += 1

        if tool_name == "translate_to_english" and data.get("ok"):
            inner = data.get("data") or {}
            provider = inner.get("provider") or "llm"
            provider_mix[provider] += 1

    tool_invocations = []
    for name, b in tool_buckets.items():
        durations = b["durations"]
        tool_invocations.append({
            "tool": name,
            "count": b["total"],
            "ok_count": b["ok"],
            "p50_ms": _percentile(durations, 0.5),
            "p95_ms": _percentile(durations, 0.95),
        })
    tool_invocations.sort(key=lambda r: r["count"], reverse=True)

    kb_rule_fires = []
    for key, fires in fired_rule_counts.most_common():
        last = fired_rule_last_ts.get(key)
        kb_rule_fires.append({
            "rule_key": key,
            "fires": fires,
            "severity": fired_rule_severity.get(key, "warn"),
            "last_fired_at": last.isoformat() if last else None,
        })

    top_corrections = [
        {"from": frm, "to": to, "count": cnt}
        for (frm, to), cnt in norm_pairs.most_common(5)
    ]
    correction_rate = (
        len(norm_pipes_with_correction) / norm_total if norm_total else 0.0
    )

    spam_combo = {"llm_only": 0, "heuristic_only": 0, "both": 0, "neither": 0}
    intake_results = (
        db.query(TraceEvent)
        .filter(TraceEvent.stage == "intake", TraceEvent.kind == "result")
        .order_by(TraceEvent.ts.desc())
        .all()
    )
    seen_pipes: set[int] = set()
    for ev in intake_results:
        if ev.pipeline_id in seen_pipes or ev.pipeline_id not in pipe_ids:
            continue
        seen_pipes.add(ev.pipeline_id)
        signals = ((ev.data or {}).get("spam_signals")) or {}
        llm = bool(signals.get("llm"))
        heur = bool(signals.get("heuristic"))
        if llm and heur:
            spam_combo["both"] += 1
        elif llm:
            spam_combo["llm_only"] += 1
        elif heur:
            spam_combo["heuristic_only"] += 1
        else:
            spam_combo["neither"] += 1
    total_spam_obs = sum(spam_combo.values())
    agreement = (
        (spam_combo["both"] + spam_combo["neither"]) / total_spam_obs if total_spam_obs else 0.0
    )

    autonomy_funnel: dict[str, dict[str, int]] = {}
    for p in pipes:
        intent = p.intent or "unknown"
        tier = p.autonomy_tier
        bucket = autonomy_funnel.setdefault(
            intent, {"L4_AUTO": 0, "L3_ONE_CLICK": 0, "L2_HITL": 0, "total": 0}
        )
        if tier in ("L4_AUTO", "L3_ONE_CLICK", "L2_HITL"):
            bucket[tier] += 1
        bucket["total"] += 1

    for provider in ("llm", "azure", "deepl", "google"):
        if provider not in provider_mix:
            provider_mix[provider] = 0

    return {
        "stage_timing": stage_timing,
        "tool_invocations": tool_invocations,
        "kb_rule_fires": kb_rule_fires,
        "normalizer_corrections": {
            "total_classifications": norm_total,
            "corrected": len(norm_pipes_with_correction),
            "correction_rate": round(correction_rate, 4),
            "top_corrections": top_corrections,
        },
        "spam_signals": {
            **spam_combo,
            "agreement_rate": round(agreement, 4),
        },
        "autonomy_funnel_by_intent": autonomy_funnel,
        "translation_provider_mix": dict(provider_mix),
    }


# Columns mirror the Keysight POC's Google Sheet
# (sheet 1jIpjfyRkK1EAxd9CVzl2CRKKC42yIyEAIQBBPObTxrY) so the dashboard reads
# 1:1 with what their front-office ops team uses today.
_OPS_LOG_COLUMNS: list[str] = [
    "currentId",
    "inboxTime",
    "agentTime",
    "subject",
    "fromAddress",
    "category",
    "intent",
    "status",
    "startTime",
    "endTime",
    "duration_ms",
    "senderEmail",
    "keywords",
    "reason",
    "overrideCategory",
    "overrideReason",
    "autonomyTier",
    "confidence",
    "hitlStatus",
    "mailbox",
]


def _build_ops_log_rows(
    db: Session,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    category: str | None,
    status: str | None,
    mailbox: int | None,
    q: str | None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    pipe_q = db.query(Pipeline).order_by(Pipeline.id.desc())
    if date_from is not None:
        pipe_q = pipe_q.filter(Pipeline.started_at >= date_from)
    if date_to is not None:
        pipe_q = pipe_q.filter(Pipeline.started_at <= date_to)
    pipe_q = pipe_q.limit(max(1, min(limit, 5000)))
    pipes: list[Pipeline] = pipe_q.all()
    if not pipes:
        return []

    email_ids = {p.email_id for p in pipes if p.email_id}
    pipe_ids = [p.id for p in pipes]

    emails_by_id: dict[int, Email] = {}
    if email_ids:
        for em in db.query(Email).filter(Email.id.in_(email_ids)).all():
            emails_by_id[em.id] = em

    if mailbox is not None:
        emails_by_id = {eid: e for eid, e in emails_by_id.items() if e.account_id == mailbox}

    account_ids = {e.account_id for e in emails_by_id.values() if e.account_id}
    accounts_by_id: dict[int, str] = {}
    if account_ids:
        for acc in db.query(EmailAccount).filter(EmailAccount.id.in_(account_ids)).all():
            accounts_by_id[acc.id] = acc.email_address or ""

    # HITL status — any pending task surfaces "Awaiting CSR"; otherwise the
    # most recent resolution wins. Pipelines with no HITL stay blank.
    hitl_by_pipe: dict[int, str] = {}
    if pipe_ids:
        for h in (
            db.query(HitlTask)
            .filter(HitlTask.pipeline_id.in_(pipe_ids))
            .order_by(HitlTask.created_at.desc())
            .all()
        ):
            existing = hitl_by_pipe.get(h.pipeline_id)
            if h.status == "pending":
                hitl_by_pipe[h.pipeline_id] = "Awaiting CSR"
            elif existing != "Awaiting CSR":
                hitl_by_pipe[h.pipeline_id] = "Resolved"

    # Pull intake classify_intent results so we can surface keywords (when the
    # classifier emits them — placeholder until B3's two-stage classifier).
    keywords_by_pipe: dict[int, str] = {}
    if pipe_ids:
        intake_evts = (
            db.query(TraceEvent)
            .filter(
                TraceEvent.pipeline_id.in_(pipe_ids),
                TraceEvent.stage == "intake",
                TraceEvent.kind == "result",
            )
            .all()
        )
        for ev in intake_evts:
            data = ev.data or {}
            kws = data.get("keywords")
            if isinstance(kws, list):
                keywords_by_pipe[ev.pipeline_id] = ", ".join(str(k) for k in kws if k)
            elif isinstance(kws, str) and kws:
                keywords_by_pipe[ev.pipeline_id] = kws

    rows: list[dict[str, Any]] = []
    for p in pipes:
        email = emails_by_id.get(p.email_id) if p.email_id else None
        if mailbox is not None and email is None:
            continue

        pipe_status = _ops_status_from_pipeline(p.status)
        cat = _category_for_intent(p.intent)

        if category and cat != category:
            continue
        if status and pipe_status != status:
            continue

        subject = email.subject if email else None
        from_addr = email.from_address if email else None

        if q:
            needle = q.lower()
            hay = " ".join(filter(None, [
                subject or "",
                from_addr or "",
                p.intent or "",
            ])).lower()
            if needle not in hay:
                continue

        duration_ms: int | None = None
        if p.finished_at and p.started_at:
            duration_ms = int((p.finished_at - p.started_at).total_seconds() * 1000)

        decision = p.decision or {}
        reason = decision.get("reasoning_summary") or decision.get("reason") or p.intent or ""

        mailbox_label = ""
        if email and email.account_id and email.account_id in accounts_by_id:
            mailbox_label = accounts_by_id[email.account_id]

        row = {
            "currentId": f"ZBR-{p.id:06d}",
            "inboxTime": _iso(email.received_at) if email else None,
            "agentTime": _iso(p.started_at),
            "subject": subject,
            "fromAddress": from_addr,
            "category": cat,
            "intent": p.intent,
            "status": pipe_status,
            "startTime": _iso(p.started_at),
            "endTime": _iso(p.finished_at),
            "duration_ms": duration_ms,
            "senderEmail": from_addr,
            "keywords": keywords_by_pipe.get(p.id, ""),
            "reason": reason if isinstance(reason, str) else str(reason),
            "overrideCategory": "",
            "overrideReason": "",
            "autonomyTier": p.autonomy_tier,
            "confidence": p.confidence,
            "hitlStatus": hitl_by_pipe.get(p.id, ""),
            "mailbox": mailbox_label,
        }
        rows.append(row)

    return rows


@router.get("/ops_log")
def ops_log(
    db: Session = Depends(get_db),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    category: str | None = None,
    status: str | None = None,
    mailbox: int | None = None,
    q: str | None = None,
):
    """One-row-per-email parity with the Keysight POC's Activepieces sheet."""
    rows = _build_ops_log_rows(
        db,
        date_from=_parse_iso(date_from),
        date_to=_parse_iso(date_to),
        category=category,
        status=status,
        mailbox=mailbox,
        q=q,
    )
    return {
        "rows": rows,
        "total": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ops_log.csv")
def ops_log_csv(
    db: Session = Depends(get_db),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    category: str | None = None,
    status: str | None = None,
    mailbox: int | None = None,
    q: str | None = None,
):
    rows = _build_ops_log_rows(
        db,
        date_from=_parse_iso(date_from),
        date_to=_parse_iso(date_to),
        category=category,
        status=status,
        mailbox=mailbox,
        q=q,
    )

    def iter_csv():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_OPS_LOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for r in rows:
            writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in _OPS_LOG_COLUMNS})
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"ops-log-{stamp}.csv"
    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
