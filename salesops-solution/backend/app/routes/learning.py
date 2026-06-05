"""Continuous Learning dashboard — aggregates Feedback + Pipeline data into:
  - per-stage thumbs counts (success / failure heatmap)
  - drift signals (rolling confidence baseline vs recent)
  - intent-misclassification candidates (when CSR edits the intent)
  - KB tuning suggestions (one-click apply)

Continuous Learning is NOT a pipeline stage. It runs cross-cuttingly on the
data already collected by the running system (every CSR thumbs-up/down/edit
in the trace UI lands in the `feedback` table; every pipeline run lands in
the `pipelines` table). This route slices that history into actionable
signals that operators can review and apply without redeploying.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    ABExperiment, DriftAlert, Feedback, LearningOpportunity, Pipeline,
    RCATicket, TraceEvent,
)
from ..services.rbac import (
    ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN, require_role,
)

router = APIRouter()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _label_resolver(db: Session):
    """Returns a closure that resolves baseline_id → label, memoising per
    request so a list endpoint with N rows touches the baselines table at
    most M times (M = distinct baseline_ids in the response)."""
    from ..services import baselines as baselines_svc
    cache: dict[int, str | None] = {}

    def _resolve(baseline_id: int | None) -> str | None:
        if not baseline_id:
            return None
        if baseline_id not in cache:
            cache[baseline_id] = baselines_svc.resolve_label(db, baseline_id)
        return cache[baseline_id]

    return _resolve


@router.get("/drift_alerts")
def list_drift_alerts(
    baseline_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    """List drift alerts. Pass `?baseline_id=<id>` to filter to the alerts
    anchored to a specific Baseline Quality Target."""
    q = db.query(DriftAlert).order_by(DriftAlert.detected_at.desc())
    if baseline_id is not None:
        q = q.filter(DriftAlert.baseline_id == baseline_id)
    rows = q.all()
    label_of = _label_resolver(db)
    return [
        {
            "id": r.id,
            "detected_at": _iso(r.detected_at),
            "updated_at": _iso(getattr(r, "updated_at", None)),
            "fingerprint": getattr(r, "fingerprint", None),
            "segment": r.segment,
            "metric": r.metric,
            "baseline": r.baseline,
            "current": r.current,
            "delta": getattr(r, "delta", None),
            "delta_pct": r.delta_pct,
            "severity": r.severity,
            "circuit_breaker_fired": r.circuit_breaker_fired,
            "status": r.status,
            "resolved_at": _iso(r.resolved_at),
            "resolved_by": r.resolved_by,
            "note": r.note,
            "detail": getattr(r, "detail", None) or {},
            "baseline_id": r.baseline_id,
            "baseline_label": label_of(r.baseline_id) or f"{r.metric} ({r.segment})",
            # Concept-baseline contributor breakdown. Ordered worst-first,
            # capped at the top 5. Empty list when the alert is not anchored
            # to a concept baseline (e.g. one of the seven other detectors).
            "top_contributors": list(getattr(r, "top_contributors", None) or []),
        }
        for r in rows
    ]


@router.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(LearningOpportunity, opp_id)
    if not r:
        raise HTTPException(404, "opportunity not found")
    label_of = _label_resolver(db)
    return {
        "id": r.id,
        "detected_at": _iso(r.detected_at),
        "segment": r.segment,
        "fingerprint": r.fingerprint,
        "proposed_remedy": r.proposed_remedy,
        "expected_lift": r.expected_lift,
        "effort": r.effort,
        "risk": r.risk,
        "score": r.score,
        "status": r.status,
        "source": r.source,
        "decided_by": r.decided_by,
        "decided_at": _iso(r.decided_at),
        "decision_note": r.decision_note,
        "linked_drift_alert_id": r.linked_drift_alert_id,
        "linked_rca_ticket_id": r.linked_rca_ticket_id,
        "sample_pipeline_ids": list(r.sample_pipeline_ids or []),
        "baseline_id": r.baseline_id,
        "baseline_label": label_of(r.baseline_id) or r.segment,
    }


@router.get("/opportunities")
def list_opportunities(
    baseline_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    """List learning opportunities. Pass `?baseline_id=<id>` to filter to
    the opportunities anchored to a specific Baseline Quality Target."""
    q = (
        db.query(LearningOpportunity)
        .order_by(LearningOpportunity.score.desc(), LearningOpportunity.detected_at.desc())
    )
    if baseline_id is not None:
        q = q.filter(LearningOpportunity.baseline_id == baseline_id)
    rows = q.all()
    label_of = _label_resolver(db)
    return [
        {
            "id": r.id,
            "detected_at": _iso(r.detected_at),
            "segment": r.segment,
            "fingerprint": r.fingerprint,
            "proposed_remedy": r.proposed_remedy,
            "expected_lift": r.expected_lift,
            "effort": r.effort,
            "risk": r.risk,
            "score": r.score,
            "status": r.status,
            "source": r.source,
            "decided_by": r.decided_by,
            "decided_at": _iso(r.decided_at),
            "decision_note": r.decision_note,
            "linked_drift_alert_id": r.linked_drift_alert_id,
            "sample_pipeline_ids": list(r.sample_pipeline_ids or []),
            "baseline_id": r.baseline_id,
            "baseline_label": label_of(r.baseline_id) or r.segment,
        }
        for r in rows
    ]


class OpportunityDecisionIn(BaseModel):
    status: str  # 'accepted' | 'deferred' | 'rejected' | 'in_ab' | 'promoted' | 'retired'
    decided_by: str | None = None
    decision_note: str | None = None


@router.patch("/opportunities/{opp_id}")
def update_opportunity(opp_id: int, body: OpportunityDecisionIn, db: Session = Depends(get_db)) -> dict:
    if body.status not in {"open", "accepted", "deferred", "rejected", "in_ab", "promoted", "retired"}:
        raise HTTPException(400, "invalid status")
    o = db.get(LearningOpportunity, opp_id)
    if not o:
        raise HTTPException(404, "opportunity not found")
    # Accepting an opportunity automatically promotes it to an A/B experiment
    # so the operator's next click lands them in the AB tab with a live row.
    if body.status == "accepted":
        # Validity gate — block infrastructure-only candidates, default-
        # fallback actions, and unevaluable preconditions before they become
        # A/B experiments. Generators are expected to emit only valid shapes,
        # but operator-edited or legacy rows are checked here too.
        from ..services.learning_validity import validate as _validate_candidate
        ok, reasons = _validate_candidate(o)
        if not ok:
            raise HTTPException(
                422,
                "candidate_invalid: " + "; ".join(reasons),
            )
        from ..services.learning_promotion import promote_opportunity_to_ab
        try:
            exp = promote_opportunity_to_ab(
                db, opp_id,
                decided_by=body.decided_by,
                decision_note=body.decision_note,
            )
        except Exception as e:
            raise HTTPException(500, f"could not create A/B experiment: {e}")
        return {
            "ok": True,
            "id": o.id,
            "status": o.status,
            "ab_experiment_id": exp.id,
        }
    o.status = body.status
    o.decided_by = body.decided_by
    o.decision_note = body.decision_note
    o.decided_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": o.id, "status": o.status}


_PROMOTE_GATE_DELTA_PCT = 2.0
_PROMOTE_GATE_SAMPLE_MIN = 10
_ROLLBACK_WINDOW_DAYS = 7


def _active_freeze_window() -> dict | None:
    """Return the active promotion freeze window dict, or None if no freeze
    is in effect. Reads from config.LEARNING_PROMOTION_FREEZE_WINDOWS."""
    try:
        from ..config import LEARNING_PROMOTION_FREEZE_WINDOWS
    except Exception:
        return None
    now = datetime.utcnow()
    for w in LEARNING_PROMOTION_FREEZE_WINDOWS or []:
        try:
            start = datetime.fromisoformat(str(w["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(w["end"]).replace("Z", "+00:00"))
            if start.tzinfo is not None:
                start = start.replace(tzinfo=None)
            if end.tzinfo is not None:
                end = end.replace(tzinfo=None)
            if start <= now <= end:
                return {"start": start.isoformat(), "end": end.isoformat(), "reason": w.get("reason") or "Promotion freeze in effect"}
        except Exception:
            continue
    return None


def _require_not_frozen(action: str) -> None:
    """Raise 423 LOCKED if a freeze window is active. Used by promote /
    force-promote / rollback / retire endpoints."""
    w = _active_freeze_window()
    if w is None:
        return
    raise HTTPException(
        423,
        f"{action}_blocked: promotion freeze in effect "
        f"({w['start']} → {w['end']}). Reason: {w.get('reason') or 'see Continuous Learning settings'}.",
    )


@router.get("/freeze_window")
def get_freeze_window() -> dict:
    """Surface the active freeze window (if any) so the Promote button on the
    UI can show a banner instead of relying on the operator to discover the
    block at click time."""
    w = _active_freeze_window()
    return {"frozen": w is not None, "window": w}


def _require_rule_owner(db: Session, *, sf_user_id: str | None, action: str) -> tuple[str, str]:
    """Enforce the Continuous Learning rule-owner allow-list. Resolves the
    Salesforce user Id against the live `/api/sf-users` directory and checks
    the `is_rule_owner` flag (driven by config.LEARNING_RULE_OWNERS).

    Returns `(sf_user_id, display_name)` on success; raises HTTPException
    otherwise. Read endpoints stay open; this guard is for promote /
    force_promote / rollback / retire only.
    """
    if not sf_user_id:
        raise HTTPException(400, f"{action}_blocked: actor_sf_user_id is required")
    try:
        from .sf_users import list_sf_users
        users = list_sf_users(db=db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"{action}_blocked: could not resolve actor identity ({e})")
    for u in users:
        if u["id"] == sf_user_id:
            if not u.get("is_rule_owner"):
                raise HTTPException(
                    403,
                    f"{action}_blocked: {u.get('name')} is not on the rule-owner allow-list. "
                    f"Ask a Continuous Learning rule owner to perform this action.",
                )
            return sf_user_id, u.get("name") or sf_user_id
    raise HTTPException(403, f"{action}_blocked: actor not found in active Salesforce queues")


def _derive_state(r: ABExperiment) -> str:
    """Plain-language state for the UI. Maps the internal promote_status to a
    progression chip: Proposed -> Backtested -> Ready -> Promoted -> Retired."""
    if r.promote_status == "promoted":
        return "Promoted"
    if r.promote_status == "retired":
        return "Retired"
    if r.promote_status == "ready":
        return "Ready"
    if r.backtest_ran_at is not None:
        return "Backtested"
    return "Proposed"


def _rollback_available(r: ABExperiment) -> dict:
    """Window logic for the Rollback button on the UI."""
    if r.promote_status != "promoted":
        return {"available": False, "reason": "not_promoted"}
    if not r.previous_body_snapshot:
        return {"available": False, "reason": "no_snapshot"}
    if r.promoted_at is None:
        return {"available": False, "reason": "no_promotion_timestamp"}
    elapsed = (datetime.utcnow() - r.promoted_at).total_seconds() / 86400.0
    if elapsed > _ROLLBACK_WINDOW_DAYS:
        return {"available": False, "reason": "window_expired", "days_since_promotion": round(elapsed, 1)}
    return {"available": True, "days_remaining": round(_ROLLBACK_WINDOW_DAYS - elapsed, 1)}


def _shadow_window_satisfied(r: ABExperiment) -> tuple[bool, str | None, float | None]:
    """A new experiment must observe a configured shadow-window before its
    back-test counts toward the promote gate. Returns
    (satisfied, observed_hours, required_hours)."""
    try:
        from ..config import LEARNING_SHADOW_HOURS
    except Exception:
        return True, None, None
    required = float(LEARNING_SHADOW_HOURS or 0)
    if required <= 0:
        return True, None, 0.0
    if r.started_at is None:
        return False, None, required
    elapsed = (datetime.utcnow() - r.started_at).total_seconds() / 3600.0
    return elapsed >= required, round(elapsed, 2), required


def _approver_count_met(db: Session, r: ABExperiment) -> tuple[bool, int, int]:
    """Multi-approver gate. Returns (met, distinct_approvers, required).
    Reads from config.LEARNING_APPROVER_COUNT_BY_TYPE keyed by change_type."""
    from ..config import LEARNING_APPROVER_COUNT_BY_TYPE
    from ..models import PromotionDecision
    required = int(LEARNING_APPROVER_COUNT_BY_TYPE.get((r.change_type or "prompt"), 1))
    if required <= 1:
        return True, 1, required
    rows = (
        db.query(PromotionDecision)
        .filter(PromotionDecision.experiment_id == r.id)
        .filter(PromotionDecision.action == "approve")
        .all()
    )
    distinct = len({row.decided_by_id for row in rows if row.decided_by_id})
    return distinct >= required, distinct, required


def _evaluate_promote_gate(r: ABExperiment, db: Session | None = None) -> dict:
    """Evaluate every promotion-gate condition and return the per-condition
    detail. Used both to render the disabled-button tooltip on the UI and to
    record what the gate said at the moment a promotion was attempted.

    Returns:
      {
        "enabled": bool,
        "reasons": [
          {"key": str, "label": str, "met": bool, "observed": Any, "threshold": Any}
        ],
        "first_blocker": str | None,
      }
    """
    reasons: list[dict] = []
    delta = r.accuracy_delta_pct
    n = r.sample_collected or 0
    backtest_ran = r.backtest_ran_at is not None
    not_already_promoted = r.promote_status != "promoted"

    reasons.append({
        "key": "not_already_promoted",
        "label": "Experiment not already promoted",
        "met": bool(not_already_promoted),
        "observed": r.promote_status,
        "threshold": "not 'promoted'",
    })
    reasons.append({
        "key": "backtest_ran",
        "label": "Back-test has run",
        "met": bool(backtest_ran),
        "observed": r.backtest_ran_at.isoformat() if r.backtest_ran_at else None,
        "threshold": "not null",
    })
    reasons.append({
        "key": "sample_size",
        "label": "Sample size meets minimum",
        "met": bool(n >= _PROMOTE_GATE_SAMPLE_MIN),
        "observed": n,
        "threshold": _PROMOTE_GATE_SAMPLE_MIN,
    })
    reasons.append({
        "key": "delta_above_floor",
        "label": "Accuracy delta meets minimum",
        "met": bool(delta is not None and delta >= _PROMOTE_GATE_DELTA_PCT),
        "observed": delta,
        "threshold": _PROMOTE_GATE_DELTA_PCT,
    })
    sat, obs_h, req_h = _shadow_window_satisfied(r)
    reasons.append({
        "key": "shadow_window",
        "label": "Shadow window observed",
        "met": bool(sat),
        "observed": f"{obs_h}h" if obs_h is not None else "n/a",
        "threshold": f"{req_h}h" if req_h else "0h",
    })
    if db is not None:
        ok, distinct, required = _approver_count_met(db, r)
        reasons.append({
            "key": "approver_count",
            "label": "Multi-approver requirement",
            "met": bool(ok),
            "observed": distinct,
            "threshold": required,
        })

    enabled = all(c["met"] for c in reasons)
    first_blocker = next((c["key"] for c in reasons if not c["met"]), None)
    return {"enabled": enabled, "reasons": reasons, "first_blocker": first_blocker}


def _promote_gate(r: ABExperiment, db: Session | None = None) -> dict:
    """Back-compat shape kept for the existing UI. Wraps the new structured
    evaluation and lets the legacy `reason` key continue to drive the
    grey-out tooltip while the redesigned UI consumes `reasons` directly.
    """
    g = _evaluate_promote_gate(r, db=db)
    return {
        "enabled": g["enabled"],
        "reason": g.get("first_blocker"),
        "reasons": g["reasons"],
    }


def _serialize_ab(r: ABExperiment, db: Session | None = None) -> dict:
    baseline_label: str | None = None
    if db is not None and r.baseline_id:
        from ..services import baselines as baselines_svc
        baseline_label = baselines_svc.resolve_label(db, r.baseline_id)
    return {
        "id": r.id,
        "started_at": _iso(r.started_at),
        "candidate": r.candidate,
        "segment": r.segment,
        "horizon_kind": r.horizon_kind,
        "horizon_value": r.horizon_value,
        "sample_collected": r.sample_collected,
        "sample_target": r.sample_target,
        "accuracy_delta_pct": r.accuracy_delta_pct,
        "accuracy_delta_ci": r.accuracy_delta_ci,
        "regression_status": r.regression_status,
        "promote_status": r.promote_status,
        "state": _derive_state(r),
        "promoted_by": r.promoted_by,
        "promoted_at": _iso(r.promoted_at),
        "promote_note": r.promote_note,
        "linked_opportunity_id": r.linked_opportunity_id,
        "kb_namespace": getattr(r, "kb_namespace", None),
        "kb_key": getattr(r, "kb_key", None),
        "control_prompt": getattr(r, "control_prompt", None),
        "candidate_prompt": getattr(r, "candidate_prompt", None),
        "backtest_results": getattr(r, "backtest_results", None),
        "backtest_ran_at": _iso(getattr(r, "backtest_ran_at", None)),
        "baseline_id": r.baseline_id,
        "baseline_label": baseline_label or r.segment,
        # New fields backing the redesigned UI.
        "change_type": getattr(r, "change_type", None) or "prompt",
        "backtest_sample": getattr(r, "backtest_sample", None) or [],
        "previous_body_snapshot": getattr(r, "previous_body_snapshot", None),
        "rolled_back_at": _iso(getattr(r, "rolled_back_at", None)),
        "rolled_back_by": getattr(r, "rolled_back_by", None),
        "rolled_back_note": getattr(r, "rolled_back_note", None),
        # Realised-lift watcher fields — production reconciliation of the
        # promoted change. Surfaced on the Promote tab.
        "realised_lift_pct": getattr(r, "realised_lift_pct", None),
        "realised_lift_ci": getattr(r, "realised_lift_ci", None),
        "realised_lift_at": _iso(getattr(r, "realised_lift_at", None)),
        "realised_sample_size": getattr(r, "realised_sample_size", None),
        "realised_note": getattr(r, "realised_note", None),
        "auto_rolled_back": bool(getattr(r, "auto_rolled_back", False)),
        "promote_gate": _promote_gate(r, db=db),
        "rollback": _rollback_available(r),
    }


@router.get("/ab_experiments")
def list_ab_experiments(
    baseline_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    """List A/B experiments. Pass `?baseline_id=<id>` to filter to the
    experiments anchored to a specific Baseline Quality Target."""
    q = db.query(ABExperiment).order_by(ABExperiment.started_at.desc())
    if baseline_id is not None:
        q = q.filter(ABExperiment.baseline_id == baseline_id)
    rows = q.all()
    return [_serialize_ab(r, db=db) for r in rows]


@router.get("/ab_experiments/{exp_id}")
def get_ab_experiment(exp_id: int, db: Session = Depends(get_db)) -> dict:
    x = db.get(ABExperiment, exp_id)
    if not x:
        raise HTTPException(404, "ab experiment not found")
    return _serialize_ab(x, db=db)


@router.post("/ab_experiments/{exp_id}/backtest")
def backtest_ab_experiment(exp_id: int, db: Session = Depends(get_db)) -> dict:
    """Replay the candidate prompt against historical pipelines tied to this
    experiment's source opportunity. Stores the per-pipeline match list +
    accuracy delta on the experiment row, and flips promote_status to 'ready'
    when the delta crosses a +2pp gate."""
    from ..services.learning_promotion import run_backtest
    try:
        summary = run_backtest(db, exp_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    x = db.get(ABExperiment, exp_id)
    return {"ok": True, "summary": summary, "experiment": _serialize_ab(x, db=db)}


def _record_promotion_decision(
    db: Session,
    *,
    experiment: ABExperiment,
    action: str,
    decided_by_id: str | None,
    decided_by_name: str | None,
    force_reason: str | None,
    outcome: str,
    outcome_detail: str | None = None,
) -> None:
    """Append an audit row capturing the gate evaluation that was in force
    when this action was taken. Never raises — audit failures must not block
    the operator's action."""
    try:
        from ..models import PromotionDecision
        from ..services.audit_chain import append_decision
        from ..services import sf_identity
        # Resolve the actor's RBAC role + source at decision time so the
        # audit chain captures their authority as it stood RIGHT NOW, not
        # whatever their Salesforce permission set looks like next week.
        decided_by_role: str | None = None
        decided_by_role_source: str | None = None
        if decided_by_id:
            try:
                role, src = sf_identity.resolve_role_for_sf_user(decided_by_id)
                decided_by_role = role
                decided_by_role_source = (src or {}).get("source")
            except Exception:
                decided_by_role = None
                decided_by_role_source = None
        gate = _evaluate_promote_gate(experiment)
        row = PromotionDecision(
            experiment_id=experiment.id,
            decided_by_id=decided_by_id,
            decided_by_name=decided_by_name,
            decided_by_role=decided_by_role,
            decided_by_role_source=decided_by_role_source,
            action=action,
            gate_enabled=bool(gate.get("enabled")),
            gate_reasons=gate.get("reasons") or [],
            sample_size=experiment.sample_collected,
            delta_pct=experiment.accuracy_delta_pct,
            force_reason=force_reason,
            outcome=outcome,
            outcome_detail=outcome_detail,
        )
        db.add(row)
        db.flush()
        # Seal into the tamper-evident hash chain BEFORE the final commit so
        # every audit row carries a verifiable signature on insert.
        append_decision(db, row)
        db.commit()
    except Exception:
        # Audit must never block the user's primary action.
        try:
            db.rollback()
        except Exception:
            pass


@router.post("/refresh_tuning_queue")
def refresh_tuning_queue(db: Session = Depends(get_db)) -> dict:
    """Run every Continuous Learning candidate generator and report how many
    new opportunities each emitted. Idempotent: each generator dedupes by
    fingerprint against the existing open / accepted / in_ab rows.

    Manual trigger from the Tuning queue header refresh button; also called
    by the daily scheduler when wired."""
    from ..services.learning_generators import run_all_generators
    return {"emitted": run_all_generators(db)}


@router.post("/refresh_monitor")
def refresh_monitor(db: Session = Depends(get_db)) -> dict:
    """Run every anomaly detector now and return the per-detector emit count.
    The detectors are also wired into a background tick (every 15 minutes)
    in main.py; this endpoint is the manual refresh from the Drift tab."""
    from ..services.monitor import run_all_detectors
    return {"emitted": run_all_detectors(db)}


@router.get("/audit_log.csv")
def export_audit_log_csv(db: Session = Depends(get_db)):
    """Stream the full Continuous Learning audit log as CSV. Covers every
    promote / force-promote / rollback / retire decision recorded across all
    experiments. Suitable for compliance evidence and Splunk ingestion.

    Columns: id, decided_at, action, experiment_id, decided_by_id,
    decided_by_name, gate_enabled, sample_size, delta_pct, force_reason,
    outcome, outcome_detail, gate_reason_summary."""
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from ..models import PromotionDecision

    rows = (
        db.query(PromotionDecision)
        .order_by(PromotionDecision.decided_at.desc())
        .all()
    )

    def _gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "id", "decided_at", "action", "experiment_id",
            "decided_by_id", "decided_by_name",
            "gate_enabled", "sample_size", "delta_pct",
            "force_reason", "outcome", "outcome_detail", "gate_reason_summary",
        ])
        yield buf.getvalue()
        for r in rows:
            buf.seek(0); buf.truncate(0)
            reasons = r.gate_reasons or []
            reason_summary = "; ".join(
                f"{c.get('label')}={c.get('observed')} (req {c.get('threshold')})"
                for c in reasons if isinstance(c, dict)
            )[:500]
            w.writerow([
                r.id,
                r.decided_at.isoformat() if r.decided_at else "",
                r.action,
                r.experiment_id,
                r.decided_by_id or "",
                r.decided_by_name or "",
                "yes" if r.gate_enabled else "no",
                r.sample_size if r.sample_size is not None else "",
                r.delta_pct if r.delta_pct is not None else "",
                (r.force_reason or "")[:300],
                r.outcome,
                (r.outcome_detail or "")[:300],
                reason_summary,
            ])
            yield buf.getvalue()

    headers = {"Content-Disposition": 'attachment; filename="continuous_learning_audit_log.csv"'}
    return StreamingResponse(_gen(), media_type="text/csv", headers=headers)


@router.post("/run_autorollback_watchdog")
def run_autorollback_watchdog(db: Session = Depends(get_db)) -> dict:
    """Watchdog sweep: detect promoted experiments whose live post-promotion
    metric has regressed past the configured threshold and roll them back
    automatically. Idempotent; rerunning is safe.

    Returns the list of rollbacks performed in this pass."""
    from ..services.monitor import check_autorollback_watchdog
    return {"rolled_back": check_autorollback_watchdog(db)}


@router.get("/circuit_breakers")
def list_circuit_breakers(db: Session = Depends(get_db)) -> dict:
    """Return the segments currently under a fired circuit breaker. The
    orchestrator reads this list when assigning autonomy tier; affected
    segments are forced to L2 review until the alert is resolved."""
    from ..services.monitor import segments_with_circuit_breaker_armed
    return {"armed_segments": sorted(segments_with_circuit_breaker_armed(db))}


@router.get("/ab_experiments/{exp_id}/decisions")
def list_promotion_decisions(exp_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Audit trail of every promote/force-promote/rollback/retire on this
    experiment. Surfaces the gate evaluation at the moment each action was
    taken, who acted, and the outcome."""
    from ..models import PromotionDecision
    rows = (
        db.query(PromotionDecision)
        .filter(PromotionDecision.experiment_id == exp_id)
        .order_by(PromotionDecision.decided_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "decided_at": _iso(r.decided_at),
            "decided_by_id": r.decided_by_id,
            "decided_by_name": r.decided_by_name,
            "action": r.action,
            "gate_enabled": r.gate_enabled,
            "gate_reasons": r.gate_reasons or [],
            "sample_size": r.sample_size,
            "delta_pct": r.delta_pct,
            "force_reason": r.force_reason,
            "outcome": r.outcome,
            "outcome_detail": r.outcome_detail,
        }
        for r in rows
    ]


class ABPromotionIn(BaseModel):
    promote_status: str  # 'shadow' | 'ready' | 'promoted' | 'retired'
    promoted_by: str | None = None
    promoted_by_id: str | None = None
    promote_note: str | None = None


@router.patch(
    "/ab_experiments/{exp_id}",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def update_ab_experiment(exp_id: int, body: ABPromotionIn, db: Session = Depends(get_db)) -> dict:
    if body.promote_status not in {"shadow", "ready", "promoted", "retired"}:
        raise HTTPException(400, "invalid promote_status")
    x = db.get(ABExperiment, exp_id)
    if not x:
        raise HTTPException(404, "ab experiment not found")
    # Promoting to production triggers the KB swap. The service layer also
    # marks the linked opportunity as `promoted` so it leaves the tuning queue.
    if body.promote_status == "promoted":
        gate = _evaluate_promote_gate(x)
        note_text = (body.promote_note or "").strip()
        force_phrase = bool(note_text and "force" in note_text.lower())
        action_label = "force_promote" if (force_phrase and not gate["enabled"]) else "promote"
        _require_not_frozen(action_label)
        # Identity gate: must be a rule owner on the live SF allow-list.
        actor_id, actor_name = _require_rule_owner(db, sf_user_id=body.promoted_by_id, action=action_label)
        if not gate["enabled"] and not force_phrase:
            _record_promotion_decision(
                db, experiment=x, action="promote",
                decided_by_id=actor_id,
                decided_by_name=actor_name,
                force_reason=None, outcome="blocked",
                outcome_detail=f"gate_blocked:{gate.get('first_blocker')}",
            )
            raise HTTPException(
                400,
                f"promote_gate_blocked: {gate.get('first_blocker')}. "
                f"Run a backtest first, or override with a promote_note containing the word 'force' "
                f"and a reasoning sentence."
            )
        # Force-promotion ledger: when the gate is bypassed, the operator
        # MUST provide a meaningful reason. Five characters of "force" is not
        # enough; we require at least 24 characters of justification beyond
        # the trigger word so the audit ledger captures a real why.
        if action_label == "force_promote":
            justification = note_text.lower().replace("force", "").strip()
            if len(justification) < 24:
                _record_promotion_decision(
                    db, experiment=x, action="force_promote",
                    decided_by_id=actor_id,
                    decided_by_name=actor_name,
                    force_reason=note_text, outcome="blocked",
                    outcome_detail="force_reason_too_short",
                )
                raise HTTPException(
                    400,
                    "force_reason_required: gate is not green and a force-promote was attempted. "
                    "Provide at least 24 characters of justification in promote_note explaining "
                    "why the gate is being bypassed (e.g. 'force: production emergency, manual "
                    "back-test on staging shows +8% on the affected segment')."
                )
        from ..services.learning_promotion import promote_ab_to_production
        try:
            res = promote_ab_to_production(
                db, exp_id,
                promoted_by=actor_name,
                promote_note=body.promote_note,
            )
        except ValueError as e:
            _record_promotion_decision(
                db, experiment=x, action=action_label,
                decided_by_id=actor_id,
                decided_by_name=actor_name,
                force_reason=body.promote_note if action_label == "force_promote" else None,
                outcome="errored", outcome_detail=str(e)[:200],
            )
            raise HTTPException(400, str(e))
        db.refresh(x)
        _record_promotion_decision(
            db, experiment=x, action=action_label,
            decided_by_id=actor_id,
            decided_by_name=actor_name,
            force_reason=body.promote_note if action_label == "force_promote" else None,
            outcome="applied",
        )
        return {"ok": True, "id": x.id, "promote_status": "promoted", **res}
    # Retire / shadow / ready transitions: identity check for retire only.
    actor_id_r: str | None = None
    actor_name_r: str | None = body.promoted_by
    if body.promote_status == "retired":
        actor_id_r, actor_name_r = _require_rule_owner(db, sf_user_id=body.promoted_by_id, action="retire")
    x.promote_status = body.promote_status
    x.promoted_by = actor_name_r
    x.promote_note = body.promote_note
    x.promoted_at = datetime.utcnow() if body.promote_status == "retired" else None
    db.commit()
    if body.promote_status == "retired":
        _record_promotion_decision(
            db, experiment=x, action="retire",
            decided_by_id=actor_id_r,
            decided_by_name=actor_name_r,
            force_reason=None, outcome="applied",
            outcome_detail=body.promote_note,
        )
    return {"ok": True, "id": x.id, "promote_status": x.promote_status}


class ABRollbackIn(BaseModel):
    rolled_back_by: str | None = None
    rolled_back_by_id: str | None = None
    note: str | None = None
    force: bool = False  # bypass the 7-day window with an explicit reason note


@router.post(
    "/ab_experiments/{exp_id}/rollback",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def rollback_ab_experiment(exp_id: int, body: ABRollbackIn, db: Session = Depends(get_db)) -> dict:
    """Restore the KB rule body to the snapshot captured at promotion.
    Available within the 7-day rollback window. Use `force=true` with a
    `note` to bypass the window for emergency reverts."""
    x = db.get(ABExperiment, exp_id)
    if not x:
        raise HTTPException(404, "ab experiment not found")
    _require_not_frozen("rollback")
    actor_id, actor_name = _require_rule_owner(db, sf_user_id=body.rolled_back_by_id, action="rollback")
    info = _rollback_available(x)
    if not info["available"] and not body.force:
        _record_promotion_decision(
            db, experiment=x, action="rollback",
            decided_by_id=actor_id,
            decided_by_name=actor_name,
            force_reason=None, outcome="blocked",
            outcome_detail=f"unavailable:{info.get('reason')}",
        )
        raise HTTPException(400, f"rollback_unavailable: {info.get('reason')}. Set force=true with an explanatory note to override.")
    from ..services.learning_promotion import rollback_ab_experiment as _rollback_svc
    try:
        res = _rollback_svc(db, exp_id, rolled_back_by=actor_name, note=body.note)
    except ValueError as e:
        _record_promotion_decision(
            db, experiment=x, action="rollback",
            decided_by_id=actor_id,
            decided_by_name=actor_name,
            force_reason=body.note if body.force else None,
            outcome="errored", outcome_detail=str(e)[:200],
        )
        raise HTTPException(400, str(e))
    db.refresh(x)
    _record_promotion_decision(
        db, experiment=x, action="rollback",
        decided_by_id=actor_id,
        decided_by_name=actor_name,
        force_reason=body.note if body.force else None,
        outcome="applied",
    )
    return res


class ABCandidateEditIn(BaseModel):
    candidate_prompt: str
    edited_by: str | None = None
    note: str | None = None


@router.patch(
    "/ab_experiments/{exp_id}/candidate",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def edit_ab_candidate_route(exp_id: int, body: ABCandidateEditIn, db: Session = Depends(get_db)) -> dict:
    """Revise the candidate body and reset the experiment for a fresh backtest.
    Only valid in shadow / ready states (cannot edit a promoted experiment)."""
    from ..services.learning_promotion import edit_ab_candidate
    try:
        res = edit_ab_candidate(
            db, exp_id,
            new_candidate_prompt=body.candidate_prompt,
            edited_by=body.edited_by,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    x = db.get(ABExperiment, exp_id)
    return {**res, "experiment": _serialize_ab(x, db=db)}


@router.post("/opportunities/synth")
def synthesize_demo_opportunity(target_intent: str = "po_intake", db: Session = Depends(get_db)) -> dict:
    """Create a properly-shaped LearningOpportunity rooted in a real KB rule
    (`intent:<target_intent>`) with sample pipelines that already classify to
    that intent. Used for end-to-end demos of the
    Tuning → A/B → Backtest → Promote flow when the live CSR feedback hasn't
    accumulated enough signal to surface a real opportunity yet."""
    samples = (
        db.query(Pipeline.id)
        .filter(Pipeline.intent == target_intent)
        .order_by(Pipeline.id.desc())
        .limit(8)
        .all()
    )
    sample_ids = [pid for (pid,) in samples]
    if not sample_ids:
        raise HTTPException(404, f"no pipelines with intent={target_intent} to seed an opportunity from")
    opp = LearningOpportunity(
        segment=f"intent:{target_intent}",
        fingerprint=f"CSRs reclassified misroutes onto '{target_intent}' on {len(sample_ids)} recent pipelines.",
        proposed_remedy=f"Add the recurring subject-line patterns from those emails to the '{target_intent}' positive-examples set.",
        expected_lift=f"+{len(sample_ids)*3} correct classifications / week (extrapolated)",
        effort="Low",
        risk="Low",
        score=0.72,
        status="open",
        source="csr_correction_cluster",
        sample_pipeline_ids=sample_ids,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return {"ok": True, "opportunity_id": opp.id, "sample_pipeline_ids": sample_ids}


@router.get("/dashboard")
def dashboard(window_days: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Aggregate signal feed for the /learning page."""
    cutoff = datetime.utcnow() - timedelta(days=window_days)

    # ---- 1. CSR feedback aggregation ---------------------------------------
    feedback_rows = (
        db.query(Feedback)
        .filter(Feedback.created_at >= cutoff)
        .order_by(Feedback.created_at.desc())
        .all()
    )
    # Feedback rows arrive with several `kind` values. The CSR widgets emit
    # `thumbs_up` / `thumbs_down` / `edit`, while the HITL queue emits
    # `approve` / `reject` / `edit_and_approve` when an operator clears a
    # task. Both must roll up into the same positivity tally; otherwise the
    # HITL-driven kinds get dropped into "other" and the Overview shows a
    # 100% positive ratio against an empty denominator. Buckets stay typed
    # as the original three keys so per-stage rendering remains stable.
    _POSITIVE_KINDS = {"thumbs_up", "approve"}
    _NEGATIVE_KINDS = {"thumbs_down", "reject"}
    _EDIT_KINDS = {"edit", "edit_and_approve"}

    per_stage: dict[str, dict[str, int]] = defaultdict(lambda: {"thumbs_up": 0, "thumbs_down": 0, "edit": 0, "other": 0})
    for f in feedback_rows:
        if f.kind in _POSITIVE_KINDS:
            bucket = "thumbs_up"
        elif f.kind in _NEGATIVE_KINDS:
            bucket = "thumbs_down"
        elif f.kind in _EDIT_KINDS:
            bucket = "edit"
        else:
            bucket = "other"
        per_stage[f.stage or "unknown"][bucket] += 1
    feedback_total = len(feedback_rows)
    thumbs_up_total = sum(s["thumbs_up"] for s in per_stage.values())
    thumbs_down_total = sum(s["thumbs_down"] for s in per_stage.values())

    # ---- 2. Drift signals --------------------------------------------------
    # For each (intent, customer_code), compare last 7-day median confidence
    # against the rolling 30-day baseline. Flag when delta < -0.10.
    pipes = (
        db.query(Pipeline)
        .filter(Pipeline.started_at >= cutoff)
        .all()
    )
    by_intent: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for p in pipes:
        if p.intent and p.confidence is not None and p.started_at:
            by_intent[p.intent].append((p.started_at, float(p.confidence)))

    drift_signals: list[dict] = []
    seven_day_cutoff = datetime.utcnow() - timedelta(days=7)
    from ..services import baselines as baselines_svc
    label_of = _label_resolver(db)
    for intent, samples in by_intent.items():
        if len(samples) < 4:
            continue
        recent = [c for ts, c in samples if ts >= seven_day_cutoff]
        baseline_pool = [c for ts, c in samples if ts < seven_day_cutoff]
        if not recent or not baseline_pool:
            continue
        recent_median = _median(recent)
        baseline_median = _median(baseline_pool)
        delta = recent_median - baseline_median
        if delta <= -0.10:
            # Anchor each drift signal to the intent's classification baseline
            # so the operator can click through to the canonical timeline.
            anchor_id = baselines_svc.match_baseline_id(
                db, "intent_classification_accuracy", f"intent:{intent}",
            )
            drift_signals.append({
                "intent": intent,
                "kind": "confidence_drop",
                "recent_median": round(recent_median, 3),
                "baseline_median": round(baseline_median, 3),
                "delta": round(delta, 3),
                "recent_n": len(recent),
                "baseline_n": len(baseline_pool),
                "severity": "high" if delta <= -0.20 else "medium",
                "baseline_id": anchor_id,
                "baseline_label": label_of(anchor_id) or f"intent:{intent}",
            })

    # ---- 3. Intent-misclassification candidates ----------------------------
    # If a CSR's `edit` feedback on the intake stage included an intent change,
    # that's a hint the classifier got it wrong. We surface those as tuning
    # candidates the operator can review and feed back as positive examples.
    intent_misses: list[dict] = []
    for f in feedback_rows:
        if f.stage != "intake" or f.kind != "edit":
            continue
        d = f.data or {}
        old_intent = d.get("from_intent") or d.get("classifier_intent")
        new_intent = d.get("to_intent") or d.get("corrected_intent")
        if old_intent and new_intent and old_intent != new_intent:
            intent_misses.append({
                "pipeline_id": f.pipeline_id,
                "from_intent": old_intent,
                "to_intent": new_intent,
                "note": (f.note or "")[:300],
                "ts": f.created_at.isoformat() if f.created_at else None,
            })

    # ---- 4. KB tuning suggestions -----------------------------------------
    # Aggregate the misclassifications by (from→to) pair. If a pair appears
    # ≥ 2 times, suggest adding a positive example to the `to_intent` rule.
    pair_counts = Counter()
    for m in intent_misses:
        pair_counts[(m["from_intent"], m["to_intent"])] += 1
    suggestions: list[dict] = []
    for (frm, to), n in pair_counts.most_common(20):
        if n < 2:
            continue
        anchor_id = baselines_svc.match_baseline_id(
            db, "intent_classification_accuracy", f"intent:{to}",
        )
        suggestions.append({
            "kind": "intent_positive_example",
            "namespace": "intent",
            "rule_key": to,
            "title": f"Add CSR-corrected examples to '{to}'",
            "rationale": (
                f"CSRs changed the classifier's '{frm}' decision to '{to}' on {n} "
                "emails in this window. Adding these as positive examples on the "
                f"'{to}' rule should reduce future misses."
            ),
            "support": n,
            "baseline_id": anchor_id,
            "baseline_label": label_of(anchor_id) or f"intent:{to}",
        })

    # ---- 5. HITL throughput (recent N hours) -------------------------------
    # Throughput counts only in-funnel pipelines (those that emitted a
    # stage_end event for intake/extract/decide/execute/communicate). The
    # pre-intake-terminated pipelines (mailbox-door redirects, spam, KSO
    # routing) are reported separately on the Mailbox-triage tile and must
    # not double-count against funnel throughput. The same in_funnel filter
    # is applied on /api/analytics/summary so the Dashboard hero and the
    # Governance Overview tile read identical numbers.
    one_day_ago = datetime.utcnow() - timedelta(days=1)
    recent_pipes_all = [p for p in pipes if p.started_at and p.started_at >= one_day_ago]
    _FUNNEL_STAGES = ("intake", "extract", "decide", "execute", "communicate")
    funnel_q = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.kind == "stage_end")
        .filter(TraceEvent.stage.in_(_FUNNEL_STAGES))
        .distinct()
    )
    funnel_pipe_ids: set[int] = {int(r[0]) for r in funnel_q.all() if r[0] is not None}
    recent_pipes = [p for p in recent_pipes_all if p.id in funnel_pipe_ids]
    pre_intake_terminated_24h = len(recent_pipes_all) - len(recent_pipes)
    tier_counts = Counter(p.autonomy_tier for p in recent_pipes if p.autonomy_tier)
    status_counts = Counter(p.status for p in recent_pipes if p.status)

    # ---- 6. Canonical drift + opportunity feeds ----------------------------
    # The legacy heuristic above produces ad-hoc confidence-drop signals and
    # CSR-correction tuning hints. They remain in `legacy_*` for parity with
    # prior consumers, but the headline `drift_signals` / `tuning_suggestions`
    # now mirror the canonical DriftAlert / LearningOpportunity tables that
    # the per-feature endpoints (/api/learning/drift_alerts and
    # /api/learning/opportunities) read from. This keeps the dashboard
    # endpoint self-consistent with the Governance Overview tiles.
    open_drift = (
        db.query(DriftAlert)
        .filter(DriftAlert.status == "open")
        .order_by(DriftAlert.detected_at.desc())
        .limit(50)
        .all()
    )
    canonical_drift_signals = [
        {
            "id": d.id,
            "metric": d.metric,
            "segment": d.segment,
            "severity": d.severity,
            "current": d.current,
            "baseline_value": d.baseline,
            "delta": d.delta,
            "detected_at": d.detected_at.isoformat() if d.detected_at else None,
            "baseline_id": d.baseline_id,
        }
        for d in open_drift
    ]

    open_opps = (
        db.query(LearningOpportunity)
        .filter(LearningOpportunity.status == "open")
        .order_by(LearningOpportunity.score.desc(), LearningOpportunity.detected_at.desc())
        .limit(50)
        .all()
    )
    canonical_tuning_suggestions = [
        {
            "id": o.id,
            "segment": o.segment,
            "fingerprint": o.fingerprint,
            "kind": o.source,
            "support": int(o.score or 0),
            "expected_lift": o.expected_lift,
            "effort": o.effort,
            "risk": o.risk,
            "baseline_id": o.baseline_id,
            "detected_at": o.detected_at.isoformat() if o.detected_at else None,
        }
        for o in open_opps
    ]

    return {
        "window_days": window_days,
        "generated_at": datetime.utcnow().isoformat(),
        "feedback_summary": {
            "total": feedback_total,
            "thumbs_up": thumbs_up_total,
            "thumbs_down": thumbs_down_total,
            "edits": sum(s["edit"] for s in per_stage.values()),
            "ratio_positive": (
                round(thumbs_up_total / max(thumbs_up_total + thumbs_down_total, 1), 3)
            ),
            "per_stage": dict(per_stage),
        },
        "drift_signals": canonical_drift_signals,
        "intent_misclassifications": intent_misses[:50],
        "tuning_suggestions": canonical_tuning_suggestions,
        "legacy_drift_signals": drift_signals,
        "legacy_tuning_suggestions": suggestions,
        "throughput_24h": {
            "pipelines": len(recent_pipes),
            "pre_intake_terminated": pre_intake_terminated_24h,
            "by_tier": dict(tier_counts),
            "by_status": dict(status_counts),
        },
    }


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if not n:
        return 0.0
    if n % 2 == 1:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def _p90(values: list[float]) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    idx = max(0, int(len(s) * 0.9) - 1)
    return s[min(idx, len(s) - 1)]


# ──────────────────────────────────────────────────────────────────────────
# Continuous-Learning hub: 5-cell mini-funnel mirroring the framework deck.
# Capture → Detect → Propose → Validate → Promote.
# ──────────────────────────────────────────────────────────────────────────
@router.get("/funnel")
def learning_funnel(db: Session = Depends(get_db)) -> dict:
    cutoff_7 = datetime.utcnow() - timedelta(days=7)
    cutoff_30 = datetime.utcnow() - timedelta(days=30)

    # Capture: outcome-bearing signals only, tied to in-funnel pipelines.
    # The raw TraceEvent table holds every breadcrumb the orchestrator emits
    # (stage_start, tool_start, tool_end, substep_done, etc.) which is too
    # noisy to surface as an operator metric. We count only the events that
    # represent a real signal: stage completions, terminal results, human
    # gate triggers, triage-rule matches, and triage fall-throughs. We also
    # exclude events tied to pre-intake-terminated pipelines (mailbox-door
    # redirects) so the number reflects the operational funnel rather than
    # mailbox triage volume.
    _SIGNAL_KINDS = ("stage_end", "result", "hitl_created", "rule_matched", "no_match")
    _FUNNEL_STAGES = ("intake", "extract", "decide", "execute", "communicate")
    funnel_pid_subq = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.kind == "stage_end")
        .filter(TraceEvent.stage.in_(_FUNNEL_STAGES))
        .distinct()
        .subquery()
    )
    capture = {
        "trace_events_7d":  (
            db.query(TraceEvent)
            .filter(TraceEvent.ts >= cutoff_7)
            .filter(TraceEvent.kind.in_(_SIGNAL_KINDS))
            .filter(TraceEvent.pipeline_id.in_(db.query(funnel_pid_subq.c.pipeline_id)))
            .count()
        ),
        "feedback_7d":      db.query(Feedback).filter(Feedback.created_at >= cutoff_7).count(),
    }
    # Detect: open drift alerts (signals that crossed a threshold).
    detect = {
        "drift_alerts_open": db.query(DriftAlert).filter(DriftAlert.status == "open").count(),
        "drift_alerts_total_30d": db.query(DriftAlert).filter(DriftAlert.detected_at >= cutoff_30).count(),
        "rca_tickets_open":  db.query(RCATicket).filter(RCATicket.status.in_(("open", "diagnosing"))).count(),
    }
    # Propose: typed candidates in the queue.
    propose = {
        "opportunities_open":   db.query(LearningOpportunity).filter(LearningOpportunity.status == "open").count(),
        "opportunities_accepted": db.query(LearningOpportunity).filter(LearningOpportunity.status == "accepted").count(),
    }
    # Validate: experiments in shadow / back-test / ready.
    validate = {
        "shadow":   db.query(ABExperiment).filter(ABExperiment.promote_status == "shadow").count(),
        "ready":    db.query(ABExperiment).filter(ABExperiment.promote_status == "ready").count(),
        "in_ab":    db.query(LearningOpportunity).filter(LearningOpportunity.status == "in_ab").count(),
    }
    # Promote: live production changes + auto-rollbacks.
    promote = {
        "promoted_30d": (
            db.query(ABExperiment)
            .filter(ABExperiment.promote_status == "promoted")
            .filter(ABExperiment.promoted_at >= cutoff_30)
            .count()
        ),
        "auto_rolled_back_30d": (
            db.query(ABExperiment)
            .filter(ABExperiment.auto_rolled_back == True)  # noqa: E712
            .filter(ABExperiment.rolled_back_at >= cutoff_30)
            .count()
        ),
        "rolled_back_30d": (
            db.query(ABExperiment)
            .filter(ABExperiment.rolled_back_at >= cutoff_30)
            .count()
        ),
    }
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "capture": capture,
        "detect": detect,
        "propose": propose,
        "validate": validate,
        "promote": promote,
    }


# ──────────────────────────────────────────────────────────────────────────
# Signal-to-remedy SLO. The deck promises "days, not quarters" — this is
# the SLO that backs the claim. p50 / p90 elapsed time between an
# opportunity being detected and the linked experiment being promoted.
# ──────────────────────────────────────────────────────────────────────────
@router.get("/sla")
def signal_to_remedy_sla(db: Session = Depends(get_db)) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=90)
    rows = (
        db.query(ABExperiment, LearningOpportunity)
        .join(LearningOpportunity, LearningOpportunity.id == ABExperiment.linked_opportunity_id)
        .filter(ABExperiment.promote_status == "promoted")
        .filter(ABExperiment.promoted_at >= cutoff)
        .all()
    )
    if not rows:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "window_days": 90,
            "target_p90_hours": 120.0,
            "p50_hours": None,
            "p90_hours": None,
            "max_hours": None,
            "samples": 0,
            "met": True,
            "items": [],
        }
    items = []
    durations: list[float] = []
    for exp, opp in rows:
        delta_h = (exp.promoted_at - opp.detected_at).total_seconds() / 3600.0
        durations.append(delta_h)
        items.append({
            "experiment_id": exp.id,
            "opportunity_id": opp.id,
            "segment": opp.segment,
            "change_type": exp.change_type,
            "detected_at": opp.detected_at.isoformat(),
            "promoted_at": exp.promoted_at.isoformat(),
            "hours": round(delta_h, 1),
            "auto_rolled_back": bool(exp.auto_rolled_back),
            "realised_lift_pct": exp.realised_lift_pct,
        })
    p50 = round(_median(durations), 1)
    p90 = round(_p90(durations), 1)
    target = 120.0  # 5 days
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "window_days": 90,
        "target_p90_hours": target,
        "p50_hours": p50,
        "p90_hours": p90,
        "max_hours": round(max(durations), 1),
        "samples": len(durations),
        "met": p90 <= target,
        "items": sorted(items, key=lambda x: -x["hours"])[:30],
    }


# ──────────────────────────────────────────────────────────────────────────
# RCA tickets: list, detail, backfill.
# ──────────────────────────────────────────────────────────────────────────
@router.get("/rca-tickets")
def list_rca_tickets(
    baseline_id: int | None = None,
    db: Session = Depends(get_db),
    limit: int = 50,
) -> list[dict]:
    """List RCA tickets. Pass `?baseline_id=<id>` to filter to the tickets
    anchored to a specific Baseline Quality Target."""
    q = db.query(RCATicket).order_by(RCATicket.created_at.desc())
    if baseline_id is not None:
        q = q.filter(RCATicket.baseline_id == baseline_id)
    rows = q.limit(limit).all()
    label_of = _label_resolver(db)
    return [
        {
            "id": t.id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "source_kind": t.source_kind,
            "source_id": t.source_id,
            "segment": t.segment,
            "metric": t.metric,
            "severity": t.severity,
            "title": t.title,
            "summary": t.summary,
            "status": t.status,
            "owner_name": t.owner_name,
            "linked_opportunity_id": t.linked_opportunity_id,
            "linked_experiment_id": t.linked_experiment_id,
            "solution_version": t.solution_version,
            "sample_pipeline_count": len(t.sample_pipeline_ids or []),
            "audit_chain_head": t.audit_chain_head,
            "baseline_id": t.baseline_id,
            "baseline_label": label_of(t.baseline_id) or (f"{t.metric} ({t.segment})" if t.metric else t.segment),
        }
        for t in rows
    ]


@router.get("/rca-tickets/{ticket_id}")
def get_rca_ticket(ticket_id: int, db: Session = Depends(get_db)) -> dict:
    t = db.get(RCATicket, ticket_id)
    if not t:
        raise HTTPException(404, "rca ticket not found")
    from ..services import baselines as baselines_svc
    return {
        "id": t.id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "source_kind": t.source_kind,
        "source_id": t.source_id,
        "segment": t.segment,
        "metric": t.metric,
        "severity": t.severity,
        "title": t.title,
        "summary": t.summary,
        "status": t.status,
        "owner_id": t.owner_id,
        "owner_name": t.owner_name,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "closed_by": t.closed_by,
        "resolution_note": t.resolution_note,
        "linked_opportunity_id": t.linked_opportunity_id,
        "linked_experiment_id": t.linked_experiment_id,
        "solution_version": t.solution_version,
        "audit_chain_head": t.audit_chain_head,
        "sample_pipeline_ids": t.sample_pipeline_ids or [],
        "prompt_snapshot": t.prompt_snapshot or {},
        "tool_calls_snapshot": t.tool_calls_snapshot or [],
        "model_versions": t.model_versions or {},
        "policy_verdicts": t.policy_verdicts or [],
        "baseline_id": t.baseline_id,
        "baseline_label": baselines_svc.resolve_label(db, t.baseline_id) or (f"{t.metric} ({t.segment})" if t.metric else t.segment),
    }


@router.post("/rca-tickets/backfill")
def backfill_rca_tickets(db: Session = Depends(get_db)) -> dict:
    from ..services.rca_tickets import backfill_for_existing_alerts
    return backfill_for_existing_alerts(db)


# ──────────────────────────────────────────────────────────────────────────
# Realised-lift watcher: manual trigger for the admin button.
# ──────────────────────────────────────────────────────────────────────────
@router.post("/realised-lift/run")
def trigger_realised_lift(db: Session = Depends(get_db)) -> dict:
    from ..services.realised_lift_watcher import tick_now
    n = tick_now(db)
    return {"reconciled": n}


# ──────────────────────────────────────────────────────────────────────────
# Baselines admin: CRUD + manual evaluate. The drift detector reads this
# table on every pass; admins edit thresholds here without a redeploy.
# ──────────────────────────────────────────────────────────────────────────
class BaselineIn(BaseModel):
    metric: str
    segment: str = "global"
    direction: str = "min"          # 'min' | 'max'
    target_value: float
    drift_pct: float = 5.0
    severity: str = "warn"          # 'warn' | 'block_promotion'
    enabled: bool = True
    owner: str = "role:cl_admin"
    rationale: str | None = None
    source: str = "manual"
    unit: str | None = None
    label: str | None = None


class BaselinePatch(BaseModel):
    target_value: float | None = None
    drift_pct: float | None = None
    severity: str | None = None
    enabled: bool | None = None
    owner: str | None = None
    rationale: str | None = None
    source: str | None = None
    unit: str | None = None
    label: str | None = None
    direction: str | None = None
    updated_by: str | None = None


_VALID_DIRECTIONS = {"min", "max"}
_VALID_SEVERITIES = {"warn", "block_promotion"}


@router.get("/baselines")
def list_baselines(db: Session = Depends(get_db)) -> dict:
    """Return every baseline along with a live status summary so the UI can
    render the heatmap without making a second roundtrip."""
    from ..models import Baseline
    from ..services import baselines as baselines_svc

    rows = db.query(Baseline).order_by(Baseline.metric, Baseline.segment).all()
    items = [baselines_svc.to_dict(b) for b in rows]
    summary = {
        "total": len(rows),
        "enabled": sum(1 for b in rows if b.enabled),
        "healthy": sum(1 for b in rows if (b.last_status or "unknown") == "healthy"),
        "drifting": sum(1 for b in rows if (b.last_status or "unknown") == "drifting"),
        "breached": sum(1 for b in rows if (b.last_status or "unknown") == "breached"),
        "unknown": sum(1 for b in rows if (b.last_status or "unknown") == "unknown"),
        "block_promotion_breached": sum(
            1 for b in rows
            if b.severity == "block_promotion" and b.last_status == "breached"
        ),
    }
    return {"items": items, "summary": summary}


@router.post(
    "/baselines",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def create_baseline(payload: BaselineIn, db: Session = Depends(get_db)) -> dict:
    from ..models import Baseline
    from ..services import baselines as baselines_svc

    if payload.direction not in _VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"direction must be one of {_VALID_DIRECTIONS}")
    if payload.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {_VALID_SEVERITIES}")
    existing = (
        db.query(Baseline)
        .filter(Baseline.metric == payload.metric, Baseline.segment == payload.segment)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="baseline for this (metric, segment) already exists")
    b = Baseline(
        metric=payload.metric,
        segment=payload.segment,
        direction=payload.direction,
        target_value=payload.target_value,
        drift_pct=payload.drift_pct,
        severity=payload.severity,
        enabled=payload.enabled,
        owner=payload.owner,
        rationale=payload.rationale,
        source=payload.source,
        unit=payload.unit,
        label=payload.label,
        updated_by="admin",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    # Drop the cached (metric, segment) → id index so subsequent signal
    # writes resolve against the new row.
    baselines_svc.invalidate_baseline_index()
    return baselines_svc.to_dict(b)


@router.patch(
    "/baselines/{baseline_id}",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def update_baseline(baseline_id: int, payload: BaselinePatch, db: Session = Depends(get_db)) -> dict:
    from ..models import Baseline
    from ..services import baselines as baselines_svc

    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="baseline not found")
    if payload.direction is not None:
        if payload.direction not in _VALID_DIRECTIONS:
            raise HTTPException(status_code=400, detail=f"direction must be one of {_VALID_DIRECTIONS}")
        b.direction = payload.direction
    if payload.severity is not None:
        if payload.severity not in _VALID_SEVERITIES:
            raise HTTPException(status_code=400, detail=f"severity must be one of {_VALID_SEVERITIES}")
        b.severity = payload.severity
    for field in ("target_value", "drift_pct", "enabled", "owner", "rationale", "source", "unit", "label"):
        v = getattr(payload, field)
        if v is not None:
            setattr(b, field, v)
    b.updated_by = payload.updated_by or "admin"
    db.commit()
    db.refresh(b)
    return baselines_svc.to_dict(b)


@router.delete(
    "/baselines/{baseline_id}",
    dependencies=[Depends(require_role(ROLE_PLATFORM_ADMIN))],
)
def delete_baseline(baseline_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import Baseline

    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="baseline not found")
    db.delete(b)
    db.commit()
    # Invalidate the (metric, segment) → id cache so detectors and generators
    # do not anchor new signals to the row we just removed.
    from ..services import baselines as baselines_svc
    baselines_svc.invalidate_baseline_index()
    return {"deleted": baseline_id}


@router.post("/baselines/evaluate")
def evaluate_baselines(db: Session = Depends(get_db)) -> dict:
    """Run the baseline detector on demand. Used by the admin's "Refresh"
    button so they can see the impact of an edit immediately rather than
    waiting for the next scheduled tick."""
    from ..services.monitor import detect_baseline_violations
    n = detect_baseline_violations(db)
    return {"fired": n}


@router.get("/baselines/metrics")
def list_known_metrics(db: Session = Depends(get_db)) -> dict:
    """Return the metric vocabulary the detector understands. The UI uses
    this to populate the 'metric' dropdown when an admin adds a new
    baseline so they can't pick a metric the detector won't observe.

    `segments` includes a live list of seeded customers (prefix
    `customer:`) so admins can pin SLO baselines per enterprise account."""
    # Active customers from the local store. Falls back to an empty list if
    # the table doesn't exist yet (fresh DB). Each gets a `customer:<code>`
    # segment so an admin can carve out per-customer baselines.
    customer_segments: list[dict] = []
    try:
        from ..models import Customer
        for c in db.query(Customer).filter(Customer.status == "active").order_by(Customer.code).limit(50).all():
            customer_segments.append({"key": f"customer:{c.code}", "label": f"Customer: {c.name} ({c.code})"})
    except Exception:
        pass
    return {
        "metrics": [
            {"key": "extraction_completeness", "label": "Extraction completeness", "unit": "ratio", "default_direction": "min"},
            {"key": "intent_classification_accuracy", "label": "Intent classification accuracy", "unit": "ratio", "default_direction": "min"},
            {"key": "language_detection_accuracy", "label": "Language detection accuracy", "unit": "ratio", "default_direction": "min"},
            {"key": "customer_match_rate", "label": "Customer match rate", "unit": "ratio", "default_direction": "min"},
            {"key": "p95_stage_latency_ms", "label": "Stage p95 latency", "unit": "ms", "default_direction": "max"},
            {"key": "autonomy_l4_rate", "label": "L4 autonomy rate", "unit": "ratio", "default_direction": "min"},
            {"key": "hitl_resolution_p95_hours", "label": "HITL p95 resolution", "unit": "hours", "default_direction": "max"},
            {"key": "spam_false_positive_rate", "label": "Spam FP rate", "unit": "ratio", "default_direction": "max"},
            {"key": "reply_send_success_rate", "label": "Customer reply send success", "unit": "ratio", "default_direction": "min"},
            {"key": "cost_per_pipeline_usd", "label": "Cost per pipeline (USD)", "unit": "usd", "default_direction": "max"},
            {"key": "aioa_handoff_success_rate", "label": "AIOA handoff success", "unit": "ratio", "default_direction": "min"},
            {"key": "psi_intent", "label": "Intent-mix stability (PSI)", "unit": "ratio", "default_direction": "max"},
        ],
        "segments": [
            {"key": "global", "label": "Global (whole system)"},
            {"key": "intent:po_intake", "label": "Intent: PO intake"},
            {"key": "intent:wo_status_inquiry", "label": "Intent: WO status inquiry"},
            {"key": "intent:wo_update_request", "label": "Intent: WO update request"},
            {"key": "intent:trade_change_order", "label": "Intent: Trade change order"},
            {"key": "stage:intake", "label": "Stage: Intake"},
            {"key": "stage:extract", "label": "Stage: Extract"},
            {"key": "stage:reconcile", "label": "Stage: Reconcile"},
            {"key": "stage:decide", "label": "Stage: Decide"},
            {"key": "stage:execute", "label": "Stage: Execute"},
            {"key": "stage:communicate", "label": "Stage: Communicate"},
            {"key": "language:ja", "label": "Language: Japanese"},
            {"key": "language:de", "label": "Language: German"},
            {"key": "language:zh", "label": "Language: Chinese"},
            *customer_segments,
        ],
        "directions": [
            {"key": "min", "label": "Min: observed must stay at or above target"},
            {"key": "max", "label": "Max: observed must stay at or below target"},
        ],
        "severities": [
            {"key": "warn", "label": "Warn: emit an alert; promotions still proceed"},
            {"key": "block_promotion", "label": "Block promotion: any breach freezes auto-promote"},
        ],
        "sources": ["rfp", "slo", "customer_sla", "empirical_p50", "manual"],
    }


@router.get("/baselines/{baseline_id}/timeline")
def baseline_timeline(baseline_id: int, db: Session = Depends(get_db)) -> dict:
    """Return every Continuous-Learning signal anchored to this Baseline
    Quality Target, grouped by signal type. Powers the frontend drill-through
    on the Baselines page: a single click jumps from "Customer reply send
    success @ global" to the full chain of drift alerts, opportunities,
    experiments, RCA tickets, feedback, and promotion decisions that point
    at that one baseline.

    Each list is capped at 100 rows ordered most-recent-first; the frontend
    can paginate via the per-entity list endpoints with `?baseline_id=`.
    """
    from ..models import (
        Baseline,
        ABExperiment,
        ABShadowResult,
        DriftAlert,
        Feedback,
        KbRuleVersion,
        LearningOpportunity,
        PromotionDecision,
        RCATicket,
    )
    from ..services import baselines as baselines_svc

    b = db.get(Baseline, baseline_id)
    if not b:
        raise HTTPException(404, "baseline not found")

    # Drift alerts anchored to this baseline.
    alerts = (
        db.query(DriftAlert)
        .filter(DriftAlert.baseline_id == baseline_id)
        .order_by(DriftAlert.detected_at.desc())
        .limit(100)
        .all()
    )
    alert_rows = [
        {
            "id": a.id,
            "detected_at": _iso(a.detected_at),
            "updated_at": _iso(getattr(a, "updated_at", None)),
            "segment": a.segment,
            "metric": a.metric,
            "current": a.current,
            "baseline": a.baseline,
            "delta_pct": a.delta_pct,
            "severity": a.severity,
            "status": a.status,
            "fingerprint": a.fingerprint,
            "circuit_breaker_fired": a.circuit_breaker_fired,
            # Concept-baseline contributor breakdown, ordered worst-first.
            "top_contributors": list(getattr(a, "top_contributors", None) or []),
        }
        for a in alerts
    ]

    opps = (
        db.query(LearningOpportunity)
        .filter(LearningOpportunity.baseline_id == baseline_id)
        .order_by(LearningOpportunity.detected_at.desc())
        .limit(100)
        .all()
    )
    opp_rows = [
        {
            "id": o.id,
            "detected_at": _iso(o.detected_at),
            "segment": o.segment,
            "fingerprint": o.fingerprint,
            "expected_lift": o.expected_lift,
            "effort": o.effort,
            "risk": o.risk,
            "score": o.score,
            "status": o.status,
            "source": o.source,
            "linked_drift_alert_id": o.linked_drift_alert_id,
            "linked_rca_ticket_id": o.linked_rca_ticket_id,
        }
        for o in opps
    ]

    exps = (
        db.query(ABExperiment)
        .filter(ABExperiment.baseline_id == baseline_id)
        .order_by(ABExperiment.started_at.desc())
        .limit(100)
        .all()
    )
    exp_rows = [
        {
            "id": e.id,
            "started_at": _iso(e.started_at),
            "candidate": e.candidate,
            "segment": e.segment,
            "change_type": e.change_type,
            "promote_status": e.promote_status,
            "state": _derive_state(e),
            "accuracy_delta_pct": e.accuracy_delta_pct,
            "regression_status": e.regression_status,
            "promoted_at": _iso(e.promoted_at),
            "promoted_by": e.promoted_by,
            "realised_lift_pct": e.realised_lift_pct,
            "auto_rolled_back": bool(e.auto_rolled_back),
            "linked_opportunity_id": e.linked_opportunity_id,
        }
        for e in exps
    ]

    tickets = (
        db.query(RCATicket)
        .filter(RCATicket.baseline_id == baseline_id)
        .order_by(RCATicket.created_at.desc())
        .limit(100)
        .all()
    )
    ticket_rows = [
        {
            "id": t.id,
            "created_at": _iso(t.created_at),
            "source_kind": t.source_kind,
            "source_id": t.source_id,
            "segment": t.segment,
            "metric": t.metric,
            "severity": t.severity,
            "title": t.title,
            "summary": t.summary,
            "status": t.status,
            "owner_name": t.owner_name,
            "linked_opportunity_id": t.linked_opportunity_id,
            "linked_experiment_id": t.linked_experiment_id,
            "solution_version": t.solution_version,
        }
        for t in tickets
    ]

    # Feedback: persisted anchor + read-time heuristic so legacy rows still
    # land in the right baseline's timeline. The persisted column is the
    # authoritative match; the heuristic backfills for rows the write-time
    # derivation missed.
    feedback_rows_persisted = (
        db.query(Feedback)
        .filter(Feedback.baseline_id == baseline_id)
        .order_by(Feedback.created_at.desc())
        .limit(100)
        .all()
    )
    persisted_ids = {f.id for f in feedback_rows_persisted}
    heuristic_pool = (
        db.query(Feedback)
        .filter(Feedback.baseline_id.is_(None))
        .order_by(Feedback.created_at.desc())
        .limit(400)
        .all()
    )
    heuristic_hits: list[Feedback] = []
    for f in heuristic_pool:
        if f.id in persisted_ids:
            continue
        if baselines_svc.derive_feedback_baseline_id(db, f) == baseline_id:
            heuristic_hits.append(f)
        if len(heuristic_hits) >= 50:
            break
    feedback_combined = (feedback_rows_persisted + heuristic_hits)[:100]
    feedback_out = [
        {
            "id": f.id,
            "pipeline_id": f.pipeline_id,
            "created_at": _iso(f.created_at),
            "stage": f.stage,
            "kind": f.kind,
            "note": f.note,
            "anchor_kind": "persisted" if f.id in persisted_ids else "derived",
        }
        for f in feedback_combined
    ]

    # Promotions: every PromotionDecision tied to an experiment anchored to
    # this baseline. Joined in Python so the response can carry per-row
    # context the dashboard needs without a CTE.
    exp_ids = {e.id for e in exps}
    promotions: list[dict] = []
    if exp_ids:
        decisions = (
            db.query(PromotionDecision)
            .filter(PromotionDecision.experiment_id.in_(exp_ids))
            .order_by(PromotionDecision.decided_at.desc())
            .limit(100)
            .all()
        )
        promotions = [
            {
                "id": d.id,
                "experiment_id": d.experiment_id,
                "decided_at": _iso(d.decided_at),
                "decided_by_name": d.decided_by_name,
                "decided_by_role": d.decided_by_role,
                "action": d.action,
                "gate_enabled": d.gate_enabled,
                "sample_size": d.sample_size,
                "delta_pct": d.delta_pct,
                "force_reason": d.force_reason,
                "outcome": d.outcome,
                "outcome_detail": d.outcome_detail,
            }
            for d in decisions
        ]

    # KB rule versions attached to the experiments above. Lets the timeline
    # show the actual prompt / rule changes that landed on top of this
    # baseline so the operator can correlate signal → remedy → live change.
    kb_changes: list[dict] = []
    if exp_ids:
        versions = (
            db.query(KbRuleVersion)
            .filter(KbRuleVersion.experiment_id.in_(exp_ids))
            .order_by(KbRuleVersion.changed_at.desc())
            .limit(100)
            .all()
        )
        kb_changes = [
            {
                "id": v.id,
                "namespace": v.namespace,
                "key": v.key,
                "version": v.version,
                "changed_at": _iso(v.changed_at),
                "changed_by_name": v.changed_by_name,
                "change_kind": v.change_kind,
                "experiment_id": v.experiment_id,
                "note": v.note,
            }
            for v in versions
        ]

    return {
        "baseline": baselines_svc.to_dict(b),
        "counts": {
            "drift_alerts": len(alert_rows),
            "opportunities": len(opp_rows),
            "experiments": len(exp_rows),
            "rca_tickets": len(ticket_rows),
            "feedback": len(feedback_out),
            "promotions": len(promotions),
            "kb_versions": len(kb_changes),
        },
        "drift_alerts": alert_rows,
        "opportunities": opp_rows,
        "experiments": exp_rows,
        "rca_tickets": ticket_rows,
        "feedback": feedback_out,
        "promotions": promotions,
        "kb_versions": kb_changes,
    }


@router.post("/baselines/{baseline_id}/backtest")
def backtest_baseline(baseline_id: int, db: Session = Depends(get_db)) -> dict:
    """Run the baseline against the last 200 pipelines and report how many
    cases would have breached. Lets an admin see the impact of a proposed
    target_value / drift_pct change before saving it.

    Reads the baseline row currently in the DB — to test an unsaved edit
    the UI PATCHes first, calls backtest, then either reverts or keeps the
    change. Keeps this endpoint simple and idempotent.
    """
    from ..models import Baseline
    from ..services import baselines as baselines_svc
    from ..services.monitor import _observe_metric

    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="baseline not found")
    observed = _observe_metric(db, b.metric, b.segment)
    status = baselines_svc.evaluate_status(b, observed)
    return {
        "baseline_id": b.id,
        "metric": b.metric,
        "segment": b.segment,
        "target_value": b.target_value,
        "drift_pct": b.drift_pct,
        "observed": observed,
        "status": status,
        "would_fire_alert": status == "breached",
    }


# ──────────────────────────────────────────────────────────────────────────
# Tamper-evident audit chain over PromotionDecision rows. Walks the chain
# top-to-bottom, recomputes each row's sha256(prev_hash + payload), reports
# any break.
# ──────────────────────────────────────────────────────────────────────────
@router.get("/audit/verify")
def verify_audit_chain(db: Session = Depends(get_db)) -> dict:
    from ..services.audit_chain import verify_chain
    return verify_chain(db)


@router.post("/audit/backfill")
def backfill_audit_chain(force: bool = False, db: Session = Depends(get_db)) -> dict:
    """Seal audit rows into the tamper-evident hash chain.

    Default mode skips rows that already carry an entry_hash. Pass
    `?force=true` to re-seal every row — needed once after a hash-domain
    migration (e.g. when a new column is added to the audit row schema)."""
    from ..services.audit_chain import backfill_chain
    sealed = backfill_chain(db, force=force)
    return {"sealed": sealed, "force": force}


# ──────────────────────────────────────────────────────────────────────────
# Shadow A/B execution — query the side-by-side comparison results between
# candidate and production for any experiment currently in shadow mode.
# ──────────────────────────────────────────────────────────────────────────
@router.get("/shadow-results")
def shadow_results_for_experiment(experiment_id: int, limit: int = 50, db: Session = Depends(get_db)) -> dict:
    from ..models import ABShadowResult
    from ..services.shadow_executor import agreement_rate
    from ..services import baselines as baselines_svc

    rows = (
        db.query(ABShadowResult)
        .filter(ABShadowResult.experiment_id == experiment_id)
        .order_by(ABShadowResult.created_at.desc())
        .limit(limit)
        .all()
    )
    # Per-experiment scope: every result row inherits the parent experiment's
    # baseline anchor. Surface it once on the response so the frontend can
    # show the Baseline column on the shadow-results table without a join.
    exp = db.get(ABExperiment, experiment_id)
    baseline_id = exp.baseline_id if exp is not None else None
    baseline_label = baselines_svc.resolve_label(db, baseline_id) if baseline_id else None
    return {
        "summary": agreement_rate(db, experiment_id, window=max(100, limit)),
        "baseline_id": baseline_id,
        "baseline_label": baseline_label,
        "items": [
            {
                "id": r.id,
                "pipeline_id": r.pipeline_id,
                "ts": r.created_at.isoformat() if r.created_at else None,
                "stage": r.stage,
                "field": r.field,
                "agreement": bool(r.agreement),
                "production_value": r.production_value,
                "candidate_value": r.candidate_value,
                "divergence_note": r.divergence_note,
                "latency_ms": r.latency_ms,
                "method": r.method,
                "baseline_id": baseline_id,
                "baseline_label": baseline_label,
            }
            for r in rows
        ],
    }
