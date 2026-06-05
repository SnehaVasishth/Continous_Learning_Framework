"""Seed two coherent end-to-end Continuous Learning stories.

Each story walks the full loop:
    drift signal  →  RCA ticket (immutable bundle)
                  →  learning opportunity (typed candidate with rationale)
                  →  A/B experiment (back-tested, gated, promoted)
                  →  realised-lift measurement (production reconciliation)
                  →  conditional auto-rollback if production trails the back-test

The two scenarios were chosen to demonstrate both halves of the loop:

  STORY A — Japanese extraction drift
    Successful prompt refinement. Back-test shows +6.4%. Production
    realised +5.8%. Inside tolerance, KB rule promoted, no rollback. This
    is the "every measure compounds" outcome.

  STORY B — trade_change_order HITL spike
    Threshold raise that looked great on the back-test (+4%) but trailed
    in production (-2%). The realised-lift watcher catches it,
    auto-rolls-back, and stamps `auto_rolled_back = True`. This is the
    "every change is measured, every promotion can be reverted in one
    click" safety net the deck promises.

Idempotent: re-running deletes any prior seeded rows (matched by
fingerprint prefix) and re-creates them. Safe to call repeatedly during
demo prep.

Invoke:
    python -m app.scripts.seed_learning_stories
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    ABExperiment,
    DriftAlert,
    Feedback,
    LearningOpportunity,
    Pipeline,
    PromotionDecision,
    RCATicket,
)
from app.services.rca_tickets import create_for_drift_alert

log = logging.getLogger("seed_learning_stories")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


_SEED_TAG = "seed_story"


def _wipe_prior(db: Session) -> None:
    """Remove rows that previous runs of this script created. Keyed by the
    fingerprint prefix `seed_story:` and the matching experiment + decision
    + RCA rows. Drift alerts are tagged via the `detail.seeded` flag."""
    seeded_opps = (
        db.query(LearningOpportunity)
        .filter(LearningOpportunity.fingerprint.like(f"{_SEED_TAG}:%"))
        .all()
    )
    seeded_opp_ids = [o.id for o in seeded_opps]
    if seeded_opp_ids:
        exps = (
            db.query(ABExperiment)
            .filter(ABExperiment.linked_opportunity_id.in_(seeded_opp_ids))
            .all()
        )
        exp_ids = [e.id for e in exps]
        if exp_ids:
            db.query(PromotionDecision).filter(PromotionDecision.experiment_id.in_(exp_ids)).delete(synchronize_session=False)
            for e in exps:
                db.delete(e)
        for o in seeded_opps:
            db.delete(o)
    # Drift alerts + RCA tickets tagged seeded.
    rca = db.query(RCATicket).filter(RCATicket.summary.like("[SEED]%")).all()
    rca_ids = [t.id for t in rca]
    for t in rca:
        db.delete(t)
    alerts = (
        db.query(DriftAlert)
        .filter(DriftAlert.note.like("[SEED]%"))
        .all()
    )
    for a in alerts:
        db.delete(a)
    # Feedback rows we wrote for the realised-lift watcher.
    db.query(Feedback).filter(Feedback.note.like("[SEED]%")).delete(synchronize_session=False)
    db.commit()
    log.info(
        "wiped prior seed: opps=%d exps=%d rca=%d",
        len(seeded_opp_ids), len(exp_ids if seeded_opp_ids else []), len(rca_ids),
    )


def _ensure_sample_pipelines(db: Session, intent: str | None, language: str | None, count: int = 30) -> list[int]:
    """Pull pipeline ids that match the segment. Falls back to recent
    pipelines so the seeded stories link to real cases in the demo DB."""
    q = db.query(Pipeline).filter(Pipeline.started_at.isnot(None))
    if intent:
        q = q.filter(Pipeline.intent == intent)
    if language:
        q = q.filter(Pipeline.language == language)
    rows = q.order_by(Pipeline.started_at.desc()).limit(count).all()
    if len(rows) < 4:
        rows = (
            db.query(Pipeline)
            .filter(Pipeline.started_at.isnot(None))
            .order_by(Pipeline.started_at.desc())
            .limit(count)
            .all()
        )
    return [p.id for p in rows]


def _story_a_backtest_rows(pipeline_ids: list[int]) -> list[dict]:
    """Per-pipeline rows the A/B Experiment "Affected pipelines" table reads.

    Renderer expects: pipeline_id, subject, customer_name, baseline_correct,
    baseline_intent, candidate_correct, agreed.
    """
    base = [
        {"subject": "発注書: 部品 SN-12834 出荷指示の追加",                  "customer_name": "Sakura Industrial KK",      "baseline_intent": "po_intake",          "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "緊急: インコタームDDP変更のご確認",                    "customer_name": "Yokohama Precision Ltd.",   "baseline_intent": "delivery_change",    "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "PO 7741 - 納期希望と配送先のご相談",                  "customer_name": "Tohoku Electronics",        "baseline_intent": "delivery_change",    "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "Ref. 88210 — 出荷条件確認",                          "customer_name": "Tokyo Test Systems",        "baseline_intent": "po_intake",          "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "ご注文確認 — 出荷指定 / Asia → North America",        "customer_name": "Kansai Semiconductor",      "baseline_intent": "trade_change_order", "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "PO 9821 — 通常通り",                                "customer_name": "Osaka Photonics",           "baseline_intent": "po_intake",          "baseline_correct": True,  "candidate_correct": True,  "agreed": True},
    ]
    out = []
    for i, row in enumerate(base):
        out.append({"pipeline_id": pipeline_ids[i] if i < len(pipeline_ids) else 0, **row})
    return out


def _story_b_backtest_rows(pipeline_ids: list[int]) -> list[dict]:
    base = [
        {"subject": "PO Amendment 9821 — price update line 3",        "customer_name": "Aurora Instrument Co.",   "baseline_intent": "trade_change_order", "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "Change order — qty + ship-to",                   "customer_name": "Crescent Test Lab",       "baseline_intent": "trade_change_order", "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "Revised PO line 2 — discount applied",           "customer_name": "Vector Defense Systems",  "baseline_intent": "trade_change_order", "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "Amendment — payment terms NET30 → NET45",        "customer_name": "Helix Photonics",         "baseline_intent": "trade_change_order", "baseline_correct": True,  "candidate_correct": True,  "agreed": True},
        {"subject": "Trade change — add SLA addendum",                "customer_name": "Cascade Power",           "baseline_intent": "trade_change_order", "baseline_correct": False, "candidate_correct": True,  "agreed": False},
        {"subject": "PO update — bundle reseller terms",              "customer_name": "Northwind Precision",     "baseline_intent": "trade_change_order", "baseline_correct": True,  "candidate_correct": True,  "agreed": True},
    ]
    out = []
    for i, row in enumerate(base):
        out.append({"pipeline_id": pipeline_ids[i] if i < len(pipeline_ids) else 0, **row})
    return out


def _add_feedback_for_realised_lift(
    db: Session,
    pipeline_ids: list[int],
    promoted_at: datetime,
    *,
    positive_ratio: float,
    note_tag: str,
) -> int:
    """Write post-promotion feedback rows the realised-lift watcher will
    use to compute the realised delta. The mix is split into approve /
    edit / reject by `positive_ratio` so we control the realised number
    precisely for demo storytelling."""
    if not pipeline_ids:
        return 0
    n = min(len(pipeline_ids), 25)
    written = 0
    for i, pid in enumerate(pipeline_ids[:n]):
        # i/n controls the kind so the realised ratio matches the target.
        # positives = approve, partials = edit_and_approve (counts 0.5),
        # negatives = reject.
        frac = i / max(1, n - 1)
        if frac < positive_ratio - 0.1:
            kind = "approve"
        elif frac < positive_ratio + 0.1:
            kind = "edit_and_approve"
        else:
            kind = "reject"
        f = Feedback(
            pipeline_id=pid,
            stage="hitl",
            kind=kind,
            note=f"[SEED] {note_tag} post-promotion sample row #{i+1}",
            created_at=promoted_at + timedelta(minutes=10 + i * 3),
            data={"sample": True, "story": note_tag},
        )
        db.add(f)
        written += 1
    db.commit()
    return written


# ──────────────────────────────────────────────────────────────────────────
# STORY A — Japanese extraction completeness drift, success story.
# ──────────────────────────────────────────────────────────────────────────

def seed_story_a(db: Session) -> dict:
    log.info("STORY A — Japanese extraction completeness drift (success)")

    # Step 1: drift signal.
    now = datetime.utcnow()
    alert = DriftAlert(
        detected_at=now - timedelta(days=7),
        updated_at=now - timedelta(days=7),
        fingerprint=f"{_SEED_TAG}:story_a:extraction_completeness:language:ja",
        segment="language:ja",
        metric="extraction_completeness",
        baseline=0.92,
        current=0.74,
        delta=-0.18,
        delta_pct=-19.6,
        severity="slo_breach",
        circuit_breaker_fired=False,
        status="resolved",
        resolved_at=now - timedelta(days=1),
        resolved_by="Continuous Learning loop",
        note="[SEED] STORY A · Japanese extraction completeness drift",
        detail={"sample_size": 142, "z_score": -3.4, "story_seed": "story_a"},
    )
    db.add(alert)
    db.flush()

    # Step 2: RCA ticket bundle (uses the live snapshot builder).
    ticket = create_for_drift_alert(db, alert)
    ticket.summary = "[SEED] Japanese extraction completeness dropped to 74% (baseline 92%). CSR edits cluster around shipping-instruction phrasing the prompt does not handle."
    ticket.status = "closed"
    ticket.closed_at = now - timedelta(days=1)
    ticket.closed_by = "CL Admin"
    ticket.resolution_note = "Prompt updated; back-tested at +6.4%; promoted on 2026-05-14."
    db.flush()

    # Step 3: learning opportunity (prompt refinement).
    pipeline_ids = _ensure_sample_pipelines(db, intent=None, language="ja")
    opp = LearningOpportunity(
        detected_at=now - timedelta(days=6),
        segment="language:ja",
        fingerprint=f"{_SEED_TAG}:story_a:prompt_refinement:language:ja",
        proposed_remedy=json.dumps({
            "change_type": "prompt_refinement",
            "scope": {"namespace": "agent_prompts", "key": "extract:system"},
            "current": {"observed_drift": "extraction_completeness", "language": "ja"},
            "proposed": {
                "stage": "extract",
                "target_field": "system_prompt",
                "missing_phrases": [
                    "shipping instructions",
                    "incoterm clause",
                    "delivery preference",
                ],
                "edit_sample_count": 18,
                "hint": (
                    "CSR edits show 18 cases over the last 14 days where the Japanese "
                    "extraction missed shipping-instruction blocks. Add an explicit "
                    "instruction to the extract prompt to capture shipping_instructions, "
                    "incoterm, and delivery_preference whenever they appear, then stage "
                    "for back-test."
                ),
            },
            "rationale": (
                "Extraction completeness on language:ja dropped from 0.92 to 0.74. "
                "18 CSR edits in the same window all added back shipping-instruction "
                "context the LLM ignored. Prompt refinement is the targeted remedy."
            ),
            "advisory": False,
            # Evidence: grounded sample cases + counterfactual the operator
            # can verify by hand before accepting.
            "evidence": {
                "headline": "Teach the Japanese extract prompt to capture shipping_instructions, incoterm and delivery_preference",
                "observed_pattern": (
                    "18 Japanese-language emails in the last 14 days had a "
                    "shipping-instruction block in the body or attachment, but the "
                    "extraction agent dropped it every time. CSRs re-added the same "
                    "three fields manually on 16 of those 18 cases."
                ),
                "counterfactual": {
                    "window_days": 30,
                    "total_in_window": 142,
                    "would_change": 32,
                    "metric_label": "+18 fewer HITL parks",
                    "savings_label": "Extraction completeness back to 0.90+",
                },
                "sample_cases": [
                    {"pipeline_id": pipeline_ids[0] if pipeline_ids else 0, "subject": "発注書: 部品 SN-12834 出荷指示の追加", "intent": "po_intake",     "current_outcome": "Missed shipping_instructions",     "proposed_outcome": "Captures shipping_instructions, incoterm", "csr_action": "Edit · added shipping field"},
                    {"pipeline_id": pipeline_ids[1] if len(pipeline_ids) > 1 else 0, "subject": "緊急: インコタームDDP変更のご確認",                "intent": "delivery_change", "current_outcome": "Missed incoterm clause",           "proposed_outcome": "Captures incoterm = DDP",                  "csr_action": "Edit · added incoterm"},
                    {"pipeline_id": pipeline_ids[2] if len(pipeline_ids) > 2 else 0, "subject": "PO 7741 - 納期希望と配送先のご相談",               "intent": "delivery_change", "current_outcome": "Missed delivery_preference",      "proposed_outcome": "Captures delivery_preference window",       "csr_action": "Edit · added preference"},
                    {"pipeline_id": pipeline_ids[3] if len(pipeline_ids) > 3 else 0, "subject": "Ref. 88210 — 出荷条件確認",                       "intent": "po_intake",     "current_outcome": "Parked at HITL",                  "proposed_outcome": "Auto-extracted, no HITL",                   "csr_action": "Approve after edit"},
                    {"pipeline_id": pipeline_ids[4] if len(pipeline_ids) > 4 else 0, "subject": "ご注文確認 — 出荷指定 / Asia → North America",      "intent": "trade_change_order","current_outcome": "Missed shipping_instructions",  "proposed_outcome": "Captures full shipping block",              "csr_action": "Edit · re-added shipping block"},
                ],
            },
        }),
        expected_lift="+6% extraction completeness on language:ja",
        effort="Med",
        risk="Low",
        score=0.85,
        status="promoted",
        source="prompt_refinement",
        decided_by="CL Admin",
        decided_at=now - timedelta(days=5),
        decision_note="Accepted into back-test; matches CSR edit pattern.",
        linked_drift_alert_id=alert.id,
        linked_rca_ticket_id=ticket.id,
        sample_pipeline_ids=pipeline_ids[:8],
    )
    db.add(opp)
    db.flush()

    # Step 4: A/B experiment, back-tested and promoted.
    promoted_at = now - timedelta(days=4)
    exp = ABExperiment(
        started_at=now - timedelta(days=5),
        candidate="extract.system.v8 · adds shipping_instructions / incoterm fields",
        segment="language:ja",
        horizon_kind="sample_size",
        horizon_value="40 emails",
        sample_collected=42,
        sample_target=30,
        accuracy_delta_pct=6.4,
        accuracy_delta_ci="+6.4% (95% CI ±1.8%, n=42)",
        regression_status="none",
        promote_status="promoted",
        promoted_by="CL Admin",
        promoted_at=promoted_at,
        promote_note="Promoting to production. Back-test +6.4% on 42 Japanese emails; "
                     "no regressions on the non-JA control. Rollback snapshot taken.",
        linked_opportunity_id=opp.id,
        kb_namespace="agent_prompts",
        kb_key="extract:system",
        control_prompt="You are an extraction agent. Pull the standard PO fields…",
        candidate_prompt="You are an extraction agent. Pull the standard PO fields PLUS "
                        "shipping_instructions, incoterm, and delivery_preference whenever "
                        "they appear in the email body or attachments…",
        backtest_results={
            "sample_size": 42,
            "control_correct": 30,
            "candidate_correct": 36,
            "delta_pct": 6.4,
            "language": "ja",
        },
        backtest_ran_at=now - timedelta(days=4, hours=4),
        change_type="prompt_refinement",
        previous_body_snapshot={"system": "You are an extraction agent. Pull the standard PO fields…"},
        # Affected pipelines the renderer expects: subject + customer +
        # baseline/candidate verdicts. Without these, the per-row table
        # renders as dashes.
        backtest_sample=_story_a_backtest_rows(pipeline_ids),
        # Realised-lift watcher already ran on this one — it landed within tolerance.
        realised_lift_pct=5.8,
        realised_lift_ci="+5.8% (95% CI ±2.1%, n=24)",
        realised_lift_at=now - timedelta(days=2, hours=12),
        realised_sample_size=24,
        auto_rolled_back=False,
        realised_note="Realised +5.8% vs back-test +6.4% (gap −0.6%, within ±5% tolerance). No rollback fired.",
    )
    db.add(exp)
    db.flush()

    # Step 5: write the audit row.
    pd = PromotionDecision(
        experiment_id=exp.id,
        decided_at=promoted_at,
        decided_by_id="role:cl_admin",
        decided_by_name="CL Admin",
        action="promote",
        gate_enabled=True,
        gate_reasons=[
            {"key": "backtest_ran",        "label": "Back-test has run",            "met": True,  "observed": exp.backtest_ran_at.isoformat(), "threshold": "not null"},
            {"key": "sample_size",         "label": "Sample size meets minimum",    "met": True,  "observed": 42, "threshold": 10},
            {"key": "delta_above_floor",   "label": "Accuracy delta meets minimum", "met": True,  "observed": 6.4, "threshold": 2.0},
            {"key": "shadow_window",       "label": "Shadow window observed",       "met": True,  "observed": "shadow=24h", "threshold": "≥4h"},
            {"key": "not_already_promoted","label": "Experiment not already promoted","met": True,"observed": "ready", "threshold": "not 'promoted'"},
        ],
        sample_size=42,
        delta_pct=6.4,
        outcome="applied",
        outcome_detail="Promoted by CL Admin. Back-test +6.4% across 42 Japanese cases.",
    )
    db.add(pd)

    # Forward-link the RCA ticket.
    ticket.linked_opportunity_id = opp.id
    ticket.linked_experiment_id = exp.id
    db.add(ticket)

    # Step 6: realised-lift watcher fed by post-promotion feedback. We seed
    # both the feedback rows AND the precomputed realised numbers above so
    # the demo shows the result instantly.
    _add_feedback_for_realised_lift(
        db, pipeline_ids, promoted_at,
        positive_ratio=0.78,        # 78% approve, 22% edit/reject ≈ +5.8% realised
        note_tag="story_a_realised_lift_sample",
    )
    db.commit()
    log.info("STORY A done — alert=%s rca=%s opp=%s exp=%s", alert.id, ticket.id, opp.id, exp.id)
    return {"alert_id": alert.id, "rca_id": ticket.id, "opportunity_id": opp.id, "experiment_id": exp.id}


# ──────────────────────────────────────────────────────────────────────────
# STORY B — trade_change_order HITL spike. Auto-rollback safety net.
# ──────────────────────────────────────────────────────────────────────────

def seed_story_b(db: Session) -> dict:
    log.info("STORY B — trade_change_order HITL spike (auto-rollback)")

    now = datetime.utcnow()
    alert = DriftAlert(
        detected_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=10),
        fingerprint=f"{_SEED_TAG}:story_b:hitl_rate:intent:trade_change_order",
        segment="intent:trade_change_order",
        metric="hitl_rate",
        baseline=0.18,
        current=0.34,
        delta=+0.16,
        delta_pct=+88.9,
        severity="warn",
        circuit_breaker_fired=False,
        status="resolved",
        resolved_at=now - timedelta(hours=18),
        resolved_by="Realised-lift watcher",
        note="[SEED] STORY B · trade_change_order HITL spike — auto-rolled-back",
        detail={"sample_size": 96, "story_seed": "story_b"},
    )
    db.add(alert)
    db.flush()

    ticket = create_for_drift_alert(db, alert)
    ticket.summary = "[SEED] HITL rate on trade_change_order climbed from 18% to 34%. Threshold-raise experiment promoted, but production realised lift trailed the back-test and the watcher auto-rolled-back."
    ticket.status = "closed"
    ticket.closed_at = now - timedelta(hours=18)
    ticket.closed_by = "Realised-lift watcher"
    ticket.resolution_note = "Auto-rollback fired after realised lift came in at −2.1% vs back-test +4.0% (gap 6.1%, exceeds 5% tolerance)."
    db.flush()

    pipeline_ids = _ensure_sample_pipelines(db, intent="trade_change_order", language=None)

    opp = LearningOpportunity(
        detected_at=now - timedelta(days=9),
        segment="intent:trade_change_order",
        fingerprint=f"{_SEED_TAG}:story_b:threshold:intent:trade_change_order",
        proposed_remedy=json.dumps({
            "change_type": "threshold",
            "scope": {"namespace": "threshold", "key": "trade_change_order"},
            "current": {"l4_floor": 0.95},
            "proposed": {"l4_floor": 0.97},
            "rationale": (
                "HITL rate on intent:trade_change_order climbed from 0.18 to 0.34. "
                "Raising the L4 floor by 2 points moves marginal cases from full "
                "autonomy into one-click review, which the back-test predicts will "
                "reduce HITL volume by ~4 points."
            ),
            "advisory": False,
            "evidence": {
                "headline": "Raise the trade-change-order auto-close floor from 0.95 to 0.97",
                "observed_pattern": (
                    "Of 96 trade-change-order cases auto-closed at L4 in the last 30 days, "
                    "17 were subsequently edited by a CSR — 14 of those edits were "
                    "concentrated in the 0.95–0.97 confidence band. Raising the floor to "
                    "0.97 would have routed those 14 to L3 one-click review instead of "
                    "L4 auto, which the back-test predicts cuts HITL volume by ~4 points."
                ),
                "counterfactual": {
                    "window_days": 30,
                    "total_in_window": 96,
                    "would_change": 14,
                    "metric_label": "−4 pts HITL rate",
                    "savings_label": "14 fewer post-close CSR edits",
                },
                "sample_cases": [
                    {"pipeline_id": pipeline_ids[0] if pipeline_ids else 0, "subject": "PO Amendment 9821 — price update line 3",                   "intent": "trade_change_order", "current_outcome": "L4 auto-closed @ conf 0.96", "proposed_outcome": "L3 one-click review", "csr_action": "CSR edited price after auto-close"},
                    {"pipeline_id": pipeline_ids[1] if len(pipeline_ids) > 1 else 0, "subject": "Change order — qty + ship-to",                       "intent": "trade_change_order", "current_outcome": "L4 auto-closed @ conf 0.95", "proposed_outcome": "L3 one-click review", "csr_action": "CSR edited ship-to address"},
                    {"pipeline_id": pipeline_ids[2] if len(pipeline_ids) > 2 else 0, "subject": "Revised PO line 2 — discount applied",                "intent": "trade_change_order", "current_outcome": "L4 auto-closed @ conf 0.96", "proposed_outcome": "L3 one-click review", "csr_action": "CSR adjusted discount tier"},
                    {"pipeline_id": pipeline_ids[3] if len(pipeline_ids) > 3 else 0, "subject": "Amendment — payment terms NET30 → NET45",             "intent": "trade_change_order", "current_outcome": "L4 auto-closed @ conf 0.97", "proposed_outcome": "L4 auto-closed (no change)", "csr_action": "Approved; outside band"},
                    {"pipeline_id": pipeline_ids[4] if len(pipeline_ids) > 4 else 0, "subject": "Trade change — add SLA addendum",                    "intent": "trade_change_order", "current_outcome": "L4 auto-closed @ conf 0.96", "proposed_outcome": "L3 one-click review", "csr_action": "CSR edited SLA section"},
                ],
            },
        }),
        expected_lift="+4% lower HITL rate on trade_change_order",
        effort="Low",
        risk="Med",
        score=0.74,
        status="promoted",
        source="threshold",
        decided_by="CL Admin",
        decided_at=now - timedelta(days=8),
        decision_note="Standard threshold raise; back-test should be conclusive in 24h.",
        linked_drift_alert_id=alert.id,
        linked_rca_ticket_id=ticket.id,
        sample_pipeline_ids=pipeline_ids[:8],
    )
    db.add(opp)
    db.flush()

    promoted_at = now - timedelta(days=6)
    exp = ABExperiment(
        started_at=now - timedelta(days=8),
        candidate="threshold.trade_change_order.l4_floor 0.95 → 0.97",
        segment="intent:trade_change_order",
        horizon_kind="time_window",
        horizon_value="48h",
        sample_collected=36,
        sample_target=30,
        accuracy_delta_pct=4.0,
        accuracy_delta_ci="+4.0% (95% CI ±1.5%, n=36)",
        regression_status="watch",
        promote_status="retired",
        promoted_by="CL Admin",
        promoted_at=promoted_at,
        promote_note="Promoting threshold raise. Back-test shows the predicted HITL drop.",
        linked_opportunity_id=opp.id,
        kb_namespace="threshold",
        kb_key="trade_change_order",
        control_prompt=None,
        candidate_prompt=None,
        backtest_results={
            "sample_size": 36,
            "control_correct": 28,
            "candidate_correct": 30,
            "delta_pct": 4.0,
            "metric": "hitl_rate_reduction",
        },
        backtest_ran_at=now - timedelta(days=7, hours=2),
        change_type="threshold",
        previous_body_snapshot={"l4_floor": 0.95},
        backtest_sample=_story_b_backtest_rows(pipeline_ids),
        # Production reality: HITL didn't drop the way the back-test
        # predicted. The watcher caught it 24h after promotion.
        realised_lift_pct=-2.1,
        realised_lift_ci="-2.1% (95% CI ±2.4%, n=28)",
        realised_lift_at=now - timedelta(hours=18),
        realised_sample_size=28,
        auto_rolled_back=True,
        realised_note=(
            "Realised −2.1% vs back-test +4.0% (gap 6.1%, exceeds 5% tolerance). "
            "Auto-rollback fired. Threshold reverted to 0.95."
        ),
        rolled_back_at=now - timedelta(hours=18),
        rolled_back_by="realised_lift_watcher",
        rolled_back_note=(
            "Auto-rollback: realised −2.1% trailed back-test +4.0% by 6.1% "
            "(tolerance 5%). Threshold reverted to 0.95 automatically; "
            "rule owner notified."
        ),
    )
    db.add(exp)
    db.flush()

    pd = PromotionDecision(
        experiment_id=exp.id,
        decided_at=promoted_at,
        decided_by_id="role:cl_admin",
        decided_by_name="CL Admin",
        action="promote",
        gate_enabled=True,
        gate_reasons=[
            {"key": "backtest_ran",        "label": "Back-test has run",            "met": True, "observed": exp.backtest_ran_at.isoformat(), "threshold": "not null"},
            {"key": "sample_size",         "label": "Sample size meets minimum",    "met": True, "observed": 36, "threshold": 10},
            {"key": "delta_above_floor",   "label": "Accuracy delta meets minimum", "met": True, "observed": 4.0, "threshold": 2.0},
            {"key": "shadow_window",       "label": "Shadow window observed",       "met": True, "observed": "shadow=24h", "threshold": "≥4h"},
            {"key": "not_already_promoted","label": "Experiment not already promoted","met": True,"observed": "ready", "threshold": "not 'promoted'"},
        ],
        sample_size=36,
        delta_pct=4.0,
        outcome="applied",
        outcome_detail="Promoted by CL Admin. Back-test +4.0% on 36 trade-change-order cases.",
    )
    db.add(pd)

    # Audit row for the auto-rollback.
    pd_rollback = PromotionDecision(
        experiment_id=exp.id,
        decided_at=now - timedelta(hours=18),
        decided_by_id=None,
        decided_by_name="realised_lift_watcher",
        action="rollback",
        gate_enabled=False,
        gate_reasons=[
            {"key": "realised_within_tolerance", "label": "Realised within tolerance", "met": False, "observed": "-2.1% vs +4.0% (gap 6.1%)", "threshold": "≤5.0%"},
        ],
        sample_size=28,
        delta_pct=-2.1,
        force_reason="Auto-rollback by realised-lift watcher — production trailed back-test by more than the configured tolerance.",
        outcome="applied",
        outcome_detail="Threshold rolled back to 0.95 automatically. Rule owner notified.",
    )
    db.add(pd_rollback)

    ticket.linked_opportunity_id = opp.id
    ticket.linked_experiment_id = exp.id
    db.add(ticket)

    _add_feedback_for_realised_lift(
        db, pipeline_ids, promoted_at,
        positive_ratio=0.42,         # 42% approve → realised ratio drags negative
        note_tag="story_b_realised_lift_sample",
    )
    db.commit()
    log.info("STORY B done — alert=%s rca=%s opp=%s exp=%s", alert.id, ticket.id, opp.id, exp.id)
    return {"alert_id": alert.id, "rca_id": ticket.id, "opportunity_id": opp.id, "experiment_id": exp.id}


def main() -> None:
    db = SessionLocal()
    try:
        _wipe_prior(db)
        a = seed_story_a(db)
        b = seed_story_b(db)
        print(json.dumps({"story_a": a, "story_b": b}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
