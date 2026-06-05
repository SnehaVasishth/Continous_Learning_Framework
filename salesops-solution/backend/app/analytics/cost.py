"""Real cost metering for every paid external call.

Public surface:
    record_cost(db, pipeline_id, stage, tool, component, model, units, unit_kind)
        Write a CostEvent and compute USD from the unit price book.

    cost_rollup(db, window_days)
        Aggregate by stage / by component / by model. Returns enough for the
        Analytics > Cost panel and the per-stage cost embed.

    cost_coverage(db, window_days)
        Returns the fraction of pipeline runs that have at least one cost
        event recorded against them. The Cost UI requires this to be 1.0
        before rendering dollar figures (per the locked rule: "coverage
        needs to be 100%, can't be 87%").
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import CostEvent, Pipeline, TraceEvent


# Unit prices in USD. Edit this single file to reflect contracted rates.
# All token figures are per 1,000 tokens; OCR is per page; translation per
# 1,000 characters; embeddings per 1,000 tokens.
UNIT_PRICES_USD: dict[tuple[str, str], float] = {
    # Claude family (per 1k tokens, public list pricing as of MVP build)
    ("llm_input",  "claude-sonnet-4-6"):       0.003,
    ("llm_output", "claude-sonnet-4-6"):       0.015,
    ("llm_input",  "claude-haiku-4-5"):        0.0008,
    ("llm_output", "claude-haiku-4-5"):        0.004,
    ("llm_input",  "claude-opus-4-7"):         0.015,
    ("llm_output", "claude-opus-4-7"):         0.075,
    # OpenAI family (per 1k tokens, list pricing)
    ("llm_input",  "gpt-5.2"):                 0.005,
    ("llm_output", "gpt-5.2"):                 0.015,
    ("llm_input",  "gpt-5"):                   0.005,
    ("llm_output", "gpt-5"):                   0.015,
    ("llm_input",  "gpt-4.1"):                 0.003,
    ("llm_output", "gpt-4.1"):                 0.012,
    ("llm_input",  "gpt-4o"):                  0.0025,
    ("llm_output", "gpt-4o"):                  0.010,
    # OCR / vision — Azure AI Document Intelligence, PAYG S0 tier, US-East list
    # rates. Per-page. Three model tiers map to three rates: Read (text-only
    # OCR), Layout (text + tables + structure, what we use for PO/quote PDFs),
    # and Custom (trained extraction models).
    ("ocr",        "azure-doc-intelligence-read"):    0.0015,   # $1.50 / 1k pages
    ("ocr",        "azure-doc-intelligence-layout"):  0.010,    # $10 / 1k pages
    ("ocr",        "azure-doc-intelligence-custom"):  0.050,    # $50 / 1k pages
    # Backwards-compat: the bare "azure-doc-intelligence" model id maps to the
    # Layout rate because that is what stage1/stage2 actually invoke.
    ("ocr",        "azure-doc-intelligence"):         0.010,
    ("ocr",        "in-house-ocr"):                   0.0001,
    # Translation
    ("translate",  "deepl-translator"):        0.025,     # per 1k chars
    ("translate",  "azure-translator"):        0.010,
    # Embeddings
    ("embedding",  "openai-text-embedding-3"): 0.00013,   # per 1k tokens
}


def _unit_cost(component: str, model: str | None, units: int) -> float:
    if not model:
        return 0.0
    rate = UNIT_PRICES_USD.get((component, model))
    if rate is None:
        # An unknown component/model pair returns 0 and the audit script
        # surfaces it as a coverage gap on the next dashboard load.
        return 0.0
    return round(rate * (units / 1000.0), 6) if component != "ocr" else round(rate * units, 6)


def record_cost(
    db: Session,
    *,
    pipeline_id: int | None,
    stage: str,
    tool: str,
    component: str,
    model: str | None,
    units: int,
    unit_kind: str,
) -> CostEvent:
    """Record one cost event. Call this immediately after the paid call returns."""
    ev = CostEvent(
        pipeline_id=pipeline_id,
        stage=stage,
        tool=tool,
        component=component,
        model=model,
        units=units,
        unit_kind=unit_kind,
        cost_usd=_unit_cost(component, model, units),
    )
    db.add(ev)
    db.flush()
    return ev


def cost_rollup(db: Session, window_days: int = 30) -> dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    rows = db.query(CostEvent).filter(CostEvent.ts >= cutoff).all()
    total = sum(r.cost_usd for r in rows)

    by_stage: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0.0, "tokens_in": 0, "tokens_out": 0, "pages": 0, "chars": 0})
    by_component: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)

    for r in rows:
        b = by_stage[r.stage]
        b["total"] += r.cost_usd
        if r.component == "llm_input":
            b["tokens_in"] += r.units
        elif r.component == "llm_output":
            b["tokens_out"] += r.units
        elif r.component == "ocr":
            b["pages"] += r.units
        elif r.component == "translate":
            b["chars"] += r.units
        by_component[r.component] += r.cost_usd
        if r.model:
            by_model[r.model] += r.cost_usd

    # cost per case = total / distinct pipelines metered
    metered_pipes = db.query(CostEvent.pipeline_id).filter(CostEvent.ts >= cutoff).distinct().count()
    cost_per_case = round(total / metered_pipes, 4) if metered_pipes else 0.0

    return {
        "window_days": window_days,
        "total_usd": round(total, 2),
        "cost_per_case": cost_per_case,
        "metered_pipelines": metered_pipes,
        "by_stage": {
            k: {
                "total_usd": round(v["total"], 2),
                "tokens_in": v["tokens_in"],
                "tokens_out": v["tokens_out"],
                "pages": v["pages"],
                "chars": v["chars"],
            }
            for k, v in by_stage.items()
        },
        "by_component": [{"component": k, "cost_usd": round(v, 2)} for k, v in sorted(by_component.items(), key=lambda kv: -kv[1])],
        "by_model": [{"model": k, "cost_usd": round(v, 2)} for k, v in sorted(by_model.items(), key=lambda kv: -kv[1])],
    }


def cost_coverage(db: Session, window_days: int = 30) -> dict[str, Any]:
    """Cost coverage for the Analytics Cost panel.

    Coverage = (pipelines with at least one CostEvent) / (terminal pipelines
    that incurred any paid work in the window). Terminal means completed,
    awaiting_hitl, awaiting_aioa, discarded, or error.

    Pipelines that legitimately incurred zero paid work — Pre-Intake
    deterministic short-circuits (KSO Government/Defense redirects, spam
    heuristic rejects, etc.) that never reach the LLM stages — are excluded
    from the denominator. Counting them as "missing cost data" would be
    incorrect: there is no paid call to meter.

    A `pre_metering_excluded` count is still returned for visibility: those
    are pipelines that DID incur paid work but ran before the metering hook
    existed (true coverage gaps that the backfill script can close).
    """
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    terminal_states = ("completed", "awaiting_hitl", "awaiting_aioa", "discarded", "error")
    terminal_pipes = (
        db.query(Pipeline.id)
        .filter(Pipeline.started_at >= cutoff)
        .filter(Pipeline.status.in_(terminal_states))
        .all()
    )
    terminal_ids = {p[0] for p in terminal_pipes}
    metered_ids = {
        p[0]
        for p in db.query(CostEvent.pipeline_id).filter(CostEvent.ts >= cutoff).distinct().all()
        if p[0] is not None
    }
    # Pipelines that never reached a paid stage don't count against coverage.
    # Two sub-cases:
    #   (1) Deterministic short-circuits: pre-intake rule matches (KSO
    #       Government/Defense, spam heuristics) emit a `short_circuit` or
    #       `rule_matched` event and skip the LLM entirely. Cost-free by design.
    #   (2) Errored-before-paid: a pipeline that errored at pre-intake or
    #       verification (before any intake/extract/decide/execute/communicate
    #       trace event) had no opportunity to make a paid call.
    short_circuit_rows = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.kind.in_(("short_circuit", "rule_matched")))
        .filter(TraceEvent.stage.in_(("intake", "pre_intake")))
        .filter(TraceEvent.ts >= cutoff)
        .distinct()
        .all()
    )
    short_circuit_ids = {r[0] for r in short_circuit_rows if r[0] is not None}
    paid_stage_rows = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.stage.in_(("intake", "extract", "decide", "execute", "communicate")))
        .filter(TraceEvent.kind.in_(("tool_start", "tool_end", "llm_call", "stage_start")))
        .filter(TraceEvent.ts >= cutoff)
        .distinct()
        .all()
    )
    reached_paid_stage_ids = {r[0] for r in paid_stage_rows if r[0] is not None}
    errored_before_paid_ids = {
        p[0] for p in db.query(Pipeline.id)
        .filter(Pipeline.started_at >= cutoff)
        .filter(Pipeline.status == "error")
        .all()
    } - reached_paid_stage_ids
    # Only count a pipeline as "no paid work" if it ALSO has no cost events;
    # a pipeline that triggered metering DID incur paid work.
    no_paid_work_ids = ((short_circuit_ids | errored_before_paid_ids) & terminal_ids) - metered_ids

    in_scope = terminal_ids - no_paid_work_ids
    metered = in_scope & metered_ids
    pre_metering_excluded = in_scope - metered_ids
    pct = (len(metered) / len(in_scope)) if in_scope else 1.0
    return {
        "window_days": window_days,
        "completed_pipelines": len(in_scope),
        "in_scope_pipelines": len(in_scope),
        "metered_pipelines": len(metered),
        "pre_metering_excluded": len(pre_metering_excluded),
        "no_paid_work_excluded": len(no_paid_work_ids),
        "coverage_pct": round(pct * 100, 1),
        "fully_covered": pct >= 0.999,
        "missing_pipeline_ids": sorted(pre_metering_excluded)[:50],
        "note": (
            f"{len(pre_metering_excluded)} of {len(in_scope)} paid pipeline(s) in this window have no cost event. "
            "Run the cost backfill script to close historical gaps; future runs auto-record cost at every paid call."
            if pre_metering_excluded else
            f"All {len(in_scope)} paid pipeline(s) metered"
            + (f"; {len(no_paid_work_ids)} short-circuit(s) excluded (no paid call)." if no_paid_work_ids else ".")
        ),
    }
