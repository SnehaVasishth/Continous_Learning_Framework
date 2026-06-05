"""RCA-ticket bundler.

Builds the immutable snapshot the deck promises: at the moment a drift /
regression signal is raised, capture the live prompt body, the model id,
the tool calls observed in the affected pipelines, the policy verdicts
that fired, the head of the audit hash chain, and the solution version.
All of that is written into a single `rca_tickets` row so a future
engineer reading the ticket sees exactly the state the system was in when
the signal occurred, not whatever it looks like now.

Two entry points:
  - `create_for_drift_alert(db, alert)`  — called from the drift detector
    when a new alert is raised
  - `backfill_for_existing_alerts(db)`   — admin endpoint that walks the
    `drift_alerts` table and creates tickets for any alert that doesn't
    have one yet (idempotent)
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from ..config import SOLUTION_VERSION
from ..models import (
    DriftAlert,
    KnowledgeRule,
    Pipeline,
    RCATicket,
    TraceEvent,
)

log = logging.getLogger("rca_tickets")


def _segment_to_pipeline_filter(segment: str) -> dict[str, str | None]:
    """Parse 'intent:po_intake' / 'language:ja' / 'region:EMEA' into a filter."""
    if ":" not in segment:
        return {}
    kind, value = segment.split(":", 1)
    return {kind.strip(): value.strip()}


def _sample_pipelines(db: Session, segment: str, limit: int = 8) -> list[Pipeline]:
    flt = _segment_to_pipeline_filter(segment)
    q = db.query(Pipeline).filter(Pipeline.started_at.isnot(None))
    if flt.get("intent"):
        q = q.filter(Pipeline.intent == flt["intent"])
    if flt.get("language"):
        q = q.filter(Pipeline.language == flt["language"])
    return q.order_by(Pipeline.started_at.desc()).limit(limit).all()


def _snapshot_tool_calls(db: Session, pipeline_ids: list[int]) -> list[dict[str, Any]]:
    """Top tool invocations across the sampled pipelines + their outcomes."""
    if not pipeline_ids:
        return []
    rows = (
        db.query(TraceEvent)
        .filter(TraceEvent.pipeline_id.in_(pipeline_ids))
        .filter(TraceEvent.kind.in_(("tool_start", "tool_end", "tool_blocked")))
        .order_by(TraceEvent.id.desc())
        .limit(150)
        .all()
    )
    bucket: dict[str, dict[str, Any]] = {}
    for ev in rows:
        data = ev.data or {}
        tool = data.get("tool") or ev.message or ev.kind
        if not tool:
            continue
        b = bucket.setdefault(tool, {"tool": tool, "count": 0, "blocked": 0, "errored": 0, "stages": Counter()})
        b["count"] += 1
        if ev.kind == "tool_blocked":
            b["blocked"] += 1
        if ev.kind == "tool_end" and data.get("ok") is False:
            b["errored"] += 1
        if ev.stage:
            b["stages"][ev.stage] += 1
    out = []
    for v in bucket.values():
        v["stages"] = dict(v["stages"].most_common(4))
        out.append(v)
    return sorted(out, key=lambda x: -x["count"])[:12]


def _snapshot_policy_verdicts(db: Session, pipeline_ids: list[int]) -> list[dict[str, Any]]:
    """Policy rules that fired in the sample, grouped by rule + action."""
    if not pipeline_ids:
        return []
    rows = (
        db.query(TraceEvent)
        .filter(TraceEvent.pipeline_id.in_(pipeline_ids))
        .filter(TraceEvent.kind.in_(("policy_decision", "policy_eval", "rule_match", "rule_fired")))
        .all()
    )
    bucket: dict[str, dict[str, Any]] = {}
    for ev in rows:
        data = ev.data or {}
        rule = data.get("rule_key") or data.get("rule_id") or data.get("matched_rule") or ev.message or "-"
        action = data.get("action") or data.get("policy_decision") or "-"
        k = f"{rule}|{action}"
        b = bucket.setdefault(k, {"rule": rule, "action": action, "fired_count": 0})
        b["fired_count"] += 1
    return sorted(bucket.values(), key=lambda x: -x["fired_count"])[:12]


def _snapshot_prompts(db: Session, stages: list[str]) -> dict[str, Any]:
    """Capture current KB-rule body for every stage hint we received.

    The KB stores prompt fragments / rule bodies keyed by (namespace, key).
    We snapshot whatever rule bodies the relevant stages reference today so
    that even if someone edits the rule tomorrow, the ticket remembers what
    the system was running when the signal fired.
    """
    if not stages:
        return {}
    rules = (
        db.query(KnowledgeRule)
        .filter(KnowledgeRule.namespace.in_(stages))
        .all()
    )
    out: dict[str, Any] = {}
    for r in rules:
        ns_key = f"{r.namespace}:{r.key}"
        out[ns_key] = {
            "version": r.version,
            "label": r.label,
            "body": r.body,
            "captured_at": r.updated_at.isoformat() if r.updated_at else None,
        }
    return out


def _audit_chain_head(db: Session) -> str | None:
    """Latest tamper-evident audit hash. Falls back to trace-event id high water mark."""
    last = (
        db.query(TraceEvent)
        .filter(TraceEvent.kind.in_(("policy_decision", "tool_blocked", "tool_end")))
        .order_by(TraceEvent.id.desc())
        .first()
    )
    if not last:
        return None
    data = last.data or {}
    return data.get("audit_hash") or data.get("hash") or f"trace#{last.id}"


def create_for_drift_alert(db: Session, alert: DriftAlert) -> RCATicket:
    """Bundle the live state at alert time and persist as an RCA ticket."""
    samples = _sample_pipelines(db, alert.segment or "")
    sample_ids = [p.id for p in samples]
    tool_calls = _snapshot_tool_calls(db, sample_ids)
    policy = _snapshot_policy_verdicts(db, sample_ids)
    # Stages we care about for prompt snapshots. The KB stores per-stage
    # rule bodies; we capture every stage at the moment of the alert.
    stages = ["intake", "extract", "decide", "execute", "communicate", "verification_rule", "spam_heuristic", "business_rules"]
    prompts = _snapshot_prompts(db, stages)
    chain_head = _audit_chain_head(db)
    model_versions: dict[str, str] = {}
    # Best-effort model snapshot from any LLM provider config available.
    try:
        from ..models import LLMProviderConfig
        for row in db.query(LLMProviderConfig).all():
            model_versions[row.provider] = row.model_id or ""
    except Exception:
        pass

    severity_label = (alert.severity or "info").lower()
    title = f"{(alert.metric or 'metric').replace('_', ' ').title()} drift on {alert.segment}"
    summary = (
        f"{alert.metric} on {alert.segment}: current={alert.current} vs baseline={alert.baseline} "
        f"(severity={severity_label})."
    )

    # Anchor the ticket to the same Baseline Quality Target the alert is
    # anchored to. Falls back to a (metric, segment) match when the alert
    # itself is missing the FK (legacy data path).
    baseline_anchor: int | None = alert.baseline_id
    if not baseline_anchor:
        try:
            from . import baselines as baselines_svc
            baseline_anchor = baselines_svc.match_baseline_id(db, alert.metric, alert.segment)
        except Exception:
            baseline_anchor = None

    ticket = RCATicket(
        source_kind="drift_alert",
        source_id=alert.id,
        segment=alert.segment or "unknown",
        metric=alert.metric,
        severity=severity_label,
        title=title,
        summary=summary,
        sample_pipeline_ids=sample_ids,
        prompt_snapshot=prompts,
        tool_calls_snapshot=tool_calls,
        model_versions=model_versions,
        policy_verdicts=policy,
        audit_chain_head=chain_head,
        solution_version=SOLUTION_VERSION,
        status="open",
        baseline_id=baseline_anchor,
    )
    db.add(ticket)
    db.flush()
    log.info("RCA ticket created: id=%s segment=%s sample_size=%d", ticket.id, ticket.segment, len(sample_ids))
    return ticket


def backfill_for_existing_alerts(db: Session) -> dict[str, int]:
    """Walk every drift alert that doesn't have a ticket and create one.

    Idempotent: keyed by (source_kind='drift_alert', source_id=alert.id).
    """
    existing_ids = {
        t.source_id for t in db.query(RCATicket).filter(RCATicket.source_kind == "drift_alert").all() if t.source_id
    }
    created = 0
    for a in db.query(DriftAlert).all():
        if a.id in existing_ids:
            continue
        try:
            create_for_drift_alert(db, a)
            created += 1
        except Exception:
            log.exception("backfill RCA: failed for alert id=%s", a.id)
            db.rollback()
            continue
    db.commit()
    return {"created": created, "already_existed": len(existing_ids)}
