"""End-to-end Continuous-Learning demo seed.

Steps:
  1. Spread pipeline timestamps across the last `--days` days so drift detection
     and the timeline view have meaningful history.
  2. Move the existing Feedback rows to match each pipeline's backdated time
     and enrich a subset with intent-edit data so the tuning-suggestions
     workflow auto-derives candidates.
  3. Seed DriftAlert rows that look like real per-segment alerts (a mix of
     warn / SLO breach, open / resolved, with circuit-breaker events).
  4. Seed LearningOpportunity rows linked to drift alerts and to real
     pipeline IDs as supporting samples.
  5. Seed ABExperiment rows linked to opportunities, with a mix of shadow,
     ready-to-promote, promoted, and retired statuses.

The script is idempotent enough to re-run safely: opportunity/AB rows seeded
from the bundled catalog are upserted by their semantic key so a second run
does not duplicate them.

Usage from the backend venv:
    cd backend
    ./.venv/bin/python ../scripts/seed_learning_full.py [--days 30]
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal, engine, Base  # noqa: E402
from app.models import (  # noqa: E402
    ABExperiment,
    DriftAlert,
    Feedback,
    LearningOpportunity,
    Pipeline,
    TraceEvent,
)


# ----------------------------------------------------------------------------
# Static catalog of realistic seed data (Keysight SalesOps domain).

DRIFT_CATALOG: list[dict] = [
    {
        "segment": "intent:quote_to_order",
        "metric": "confidence",
        "baseline": 0.94, "current": 0.83, "delta_pct": -11.7,
        "severity": "warn", "circuit_breaker_fired": False, "status": "in_review",
        "note": "Confidence drift on Quote-to-Order intent against the 30-day baseline. Driven by new distributor email patterns in EMEA.",
        "days_ago": 2,
    },
    {
        "segment": "language:ja",
        "metric": "extraction_accuracy",
        "baseline": 0.91, "current": 0.78, "delta_pct": -14.3,
        "severity": "slo_breach", "circuit_breaker_fired": True, "status": "open",
        "note": "Ship-to extraction accuracy on Japanese stamped POs dropped below SLO floor. Auto-action paused for ja segment; cases routing to CSR review.",
        "days_ago": 1,
    },
    {
        "segment": "intent:wo_status_inquiry",
        "metric": "hitl_rate",
        "baseline": 0.18, "current": 0.34, "delta_pct": 88.9,
        "severity": "warn", "circuit_breaker_fired": False, "status": "open",
        "note": "HITL rate on WO Status & Inquiry rose week over week. Pattern matches multi-WO emails where the reply drafter is omitting the second WO.",
        "days_ago": 3,
    },
    {
        "segment": "mailbox:apac-trade-orders",
        "metric": "sla",
        "baseline": 0.96, "current": 0.81, "delta_pct": -15.6,
        "severity": "warn", "circuit_breaker_fired": False, "status": "resolved",
        "note": "APAC mailbox SLA adherence recovered after the Friday quarter-end burst. Worker pool elastic-scaling absorbed the queue depth.",
        "days_ago": 7, "resolved_days_ago": 5, "resolved_by": "ops-oncall",
    },
    {
        "segment": "intent:hold_release",
        "metric": "confidence",
        "baseline": 0.88, "current": 0.78, "delta_pct": -11.4,
        "severity": "warn", "circuit_breaker_fired": False, "status": "in_review",
        "note": "Hold-release confidence drifting on cases with multi-line credit checks. CSR corrections clustering around Action Feasibility gate.",
        "days_ago": 4,
    },
    {
        "segment": "language:pt-BR",
        "metric": "confidence",
        "baseline": 0.92, "current": 0.80, "delta_pct": -13.0,
        "severity": "warn", "circuit_breaker_fired": False, "status": "open",
        "note": "Brazilian Portuguese classifier confidence dipping on emails from four named distributors. Routing exception under A/B test.",
        "days_ago": 6,
    },
    {
        "segment": "intent:service_order",
        "metric": "extraction_accuracy",
        "baseline": 0.95, "current": 0.88, "delta_pct": -7.4,
        "severity": "info", "circuit_breaker_fired": False, "status": "resolved",
        "note": "Service Order extraction edged below baseline last weekend. New KB exemplars promoted Monday; signal recovered within 24h.",
        "days_ago": 10, "resolved_days_ago": 8, "resolved_by": "rule-owner-jp",
    },
    {
        "segment": "intent:trade_change_order",
        "metric": "hitl_rate",
        "baseline": 0.22, "current": 0.31, "delta_pct": 40.9,
        "severity": "info", "circuit_breaker_fired": False, "status": "open",
        "note": "Trade Change Order HITL rate trending up on cases where currency differs from the original PO. Currency-equality precondition proposed as Opportunity.",
        "days_ago": 5,
    },
]

OPPORTUNITY_CATALOG: list[dict] = [
    {
        "segment": "pt-BR PO emails from 4 distributors",
        "fingerprint": "PO emails from 4 distributors in Brazilian Portuguese are misclassifying as KSO 8% of the time over the last 14 days.",
        "proposed_remedy": "Add sender-pattern exceptions to the distributor routing rule; lower KSO threshold for these senders by 0.08.",
        "expected_lift": "~140 emails/week routed to the correct queue",
        "effort": "Low", "risk": "Low", "score": 9.2, "status": "in_ab",
        "linked_drift_segment": "language:pt-BR",
        "days_ago": 12,
    },
    {
        "segment": "Japanese stamped POs (image-only)",
        "fingerprint": "Extraction gate fails on Ship-to field at 22% on Japanese stamped PDFs vs 4% on native-digital.",
        "proposed_remedy": "Bind the Japanese stamped-form retriever to a higher-resolution OCR profile in the KB; raise extraction-gate threshold to force review where the stamp field falls below confidence.",
        "expected_lift": "~30 cases/week move from L2 to L3",
        "effort": "Med", "risk": "Med", "score": 7.8, "status": "in_ab",
        "linked_drift_segment": "language:ja",
        "days_ago": 9,
    },
    {
        "segment": "WO status inquiries with multiple WO references",
        "fingerprint": "Multi-WO status emails get a single-WO reply ~12% of the time; the second WO is dropped during extraction.",
        "proposed_remedy": "Add a multi-WO exemplar set to the WO-status intent in the KB; update reply template to iterate per WO.",
        "expected_lift": "~55 emails/week get correct multi-WO replies",
        "effort": "Low", "risk": "Low", "score": 9.5, "status": "promoted",
        "linked_drift_segment": "intent:wo_status_inquiry",
        "days_ago": 14,
        "decided_by": "rule-owner-emea", "decision_note": "Approved on weekly call; A/B promoted to production on day 11.",
    },
    {
        "segment": "Trade Change Order — currency mismatch",
        "fingerprint": "Change-Order delta calculation skips currency on 2.3% of clones; CSR catches it but it slows review.",
        "proposed_remedy": "Add currency-equality precondition to the Change-Order clone rule in the KB.",
        "expected_lift": "~8 cases/week avoid CSR rework",
        "effort": "Low", "risk": "Low", "score": 8.7, "status": "accepted",
        "linked_drift_segment": "intent:trade_change_order",
        "days_ago": 5,
        "decided_by": "rule-owner-amer", "decision_note": "Accept; queue for A/B promotion this week.",
    },
    {
        "segment": "Hold-release on cases with multi-line credit checks",
        "fingerprint": "Hold-release Action Feasibility gate fires false-positive on cases where credit check splits across multiple invoices.",
        "proposed_remedy": "Adjust Action Feasibility gate to roll up multi-invoice credit checks before scoring; lower threshold by 0.04 on hold-release intent.",
        "expected_lift": "~15 cases/week clear without CSR review",
        "effort": "Med", "risk": "Med", "score": 6.4, "status": "open",
        "linked_drift_segment": "intent:hold_release",
        "days_ago": 4,
    },
    {
        "segment": "Service Contract attached-PO validation",
        "fingerprint": "Service Contract cases with attached PO fail AIOA validation 6% of the time due to currency mismatch on renewal lines.",
        "proposed_remedy": "Add renewal-currency-inheritance rule to AIOA validation step; extend extraction schema with renewal-line currency field.",
        "expected_lift": "~12 cases/week skip the AIOA fallout queue",
        "effort": "Med", "risk": "Low", "score": 7.1, "status": "open",
        "days_ago": 3,
    },
    {
        "segment": "Outlook pre-filter — bounce attachments",
        "fingerprint": "Bounce-back emails with attached delivery reports are leaking past the Outlook pre-filter ~3% of the time and triggering full classification.",
        "proposed_remedy": "Extend Outlook rule to include three additional bounce subject patterns identified in last week's leaked cases.",
        "expected_lift": "~25 emails/week never reach intake",
        "effort": "Low", "risk": "Low", "score": 8.9, "status": "promoted",
        "days_ago": 18,
        "decided_by": "rule-owner-emea", "decision_note": "Promoted to production on day 16; signal flat since.",
    },
    {
        "segment": "Distributor list — Asia-Pac new partners",
        "fingerprint": "Three new APAC distributors added in last 30 days are not in the distributor list; routing falls back to default and CSR has to reroute.",
        "proposed_remedy": "Add three named distributors and their magic-SKU mappings to the distributor list in the KB.",
        "expected_lift": "~18 cases/week routed correctly first pass",
        "effort": "Low", "risk": "Low", "score": 9.0, "status": "accepted",
        "days_ago": 6,
        "decided_by": "rule-owner-apac", "decision_note": "Accept; KB edit scheduled for next release window.",
    },
    {
        "segment": "Korean translation glossary — SOA acknowledgement",
        "fingerprint": "Korean SOA replies use a literal translation of 'acknowledged' that customers report as overly formal; CSRs are editing 14% of Korean replies for tone.",
        "proposed_remedy": "Update Korean glossary with two preferred Keysight terms for SOA acknowledgement; add tone instruction for Korean replies.",
        "expected_lift": "Korean reply edit rate drops from 14% to ~4%",
        "effort": "Low", "risk": "Low", "score": 8.2, "status": "in_ab",
        "days_ago": 8,
    },
    {
        "segment": "Multi-asset WO fan-out — inconsistent ship-to",
        "fingerprint": "Multi-asset WO requests with inconsistent ship-to are being fanned out automatically when they should route to SOM CSR for manual split.",
        "proposed_remedy": "Tighten consistency check on multi-asset fan-out: include ship-to city, ship-to country, and customer billing match as preconditions.",
        "expected_lift": "~9 cases/week prevented from incorrect fan-out",
        "effort": "Med", "risk": "Med", "score": 6.8, "status": "deferred",
        "days_ago": 11,
        "decided_by": "rule-owner-amer", "decision_note": "Defer to next sprint; need rule-owner sign-off on consistency definition.",
    },
    {
        "segment": "Spanish PO Ship-to state/region parsing",
        "fingerprint": "Spanish-language POs from ES and MX subsidiaries mis-parse the state/region in Ship-to at 9% rate; CSRs are editing the address line before the case clears extraction.",
        "proposed_remedy": "Add Spanish regional-format examples to the extraction schema; include ES and MX state-code mapping in the Knowledge Base address dictionary.",
        "expected_lift": "~22 cases/week extracted cleanly without CSR edit",
        "effort": "Low", "risk": "Low", "score": 7.5, "status": "open",
        "days_ago": 2,
    },
    {
        "segment": "Confidence calibration — high-confidence misclassifications",
        "fingerprint": "Three cases this week were classified as KSO at >=0.9 confidence but were actually quote-to-order. Audit shows shared sender keyword pattern.",
        "proposed_remedy": "Add keyword counter-example to KSO intent rule; lower KSO classification threshold when shared keyword is present alongside quote-reference signal.",
        "expected_lift": "Eliminate the high-confidence false-positive pattern (~3 cases/week)",
        "effort": "Med", "risk": "Med", "score": 5.9, "status": "rejected",
        "days_ago": 7,
        "decided_by": "rule-owner-emea", "decision_note": "Reject; the keyword pattern is shared with legitimate KSO senders. Re-open if recurrence rate increases.",
    },
]

AB_CATALOG: list[dict] = [
    {
        "candidate": "Distributor pt-BR routing exception",
        "segment": "pt-BR PO emails from 4 named distributors",
        "horizon_kind": "time_window", "horizon_value": "10 days",
        "sample_target": 1000, "sample_collected": 412,
        "accuracy_delta_pct": 6.4, "accuracy_delta_ci": "+6.4% (95% CI)",
        "regression_status": "none", "promote_status": "shadow",
        "linked_opportunity_segment": "pt-BR PO emails from 4 distributors",
        "days_ago_started": 4,
    },
    {
        "candidate": "Japanese stamped-form OCR profile",
        "segment": "ja PO image-only attachments",
        "horizon_kind": "time_window", "horizon_value": "14 days",
        "sample_target": 500, "sample_collected": 188,
        "accuracy_delta_pct": 11.2, "accuracy_delta_ci": "+11.2% on Ship-to field",
        "regression_status": "watch", "promote_status": "shadow",
        "linked_opportunity_segment": "Japanese stamped POs (image-only)",
        "days_ago_started": 6,
    },
    {
        "candidate": "Multi-WO reply template",
        "segment": "WO-status with ≥2 WO references",
        "horizon_kind": "sample_size", "horizon_value": "1000 emails",
        "sample_target": 1000, "sample_collected": 1100,
        "accuracy_delta_pct": 9.8, "accuracy_delta_ci": "+9.8% (95% CI)",
        "regression_status": "none", "promote_status": "promoted",
        "linked_opportunity_segment": "WO status inquiries with multiple WO references",
        "days_ago_started": 14, "days_ago_promoted": 11,
        "promoted_by": "rule-owner-emea", "promote_note": "All success criteria met; promoted with one-click rollback enabled.",
    },
    {
        "candidate": "Korean glossary SOA tone update",
        "segment": "ko outbound SOA replies",
        "horizon_kind": "sample_size", "horizon_value": "200 emails",
        "sample_target": 200, "sample_collected": 175,
        "accuracy_delta_pct": 8.6, "accuracy_delta_ci": "tone-edit rate drop 14% -> 4.8%",
        "regression_status": "none", "promote_status": "ready",
        "linked_opportunity_segment": "Korean translation glossary — SOA acknowledgement",
        "days_ago_started": 8,
    },
    {
        "candidate": "Outlook pre-filter bounce patterns v3",
        "segment": "inbound bounce-with-attachment emails",
        "horizon_kind": "time_window", "horizon_value": "5 days",
        "sample_target": 300, "sample_collected": 300,
        "accuracy_delta_pct": 12.3, "accuracy_delta_ci": "leak rate 3% -> 0.4%",
        "regression_status": "none", "promote_status": "promoted",
        "linked_opportunity_segment": "Outlook pre-filter — bounce attachments",
        "days_ago_started": 18, "days_ago_promoted": 16,
        "promoted_by": "rule-owner-emea", "promote_note": "Promoted on day 16; leakage has stayed below 1% since.",
    },
    {
        "candidate": "Currency-equality precondition on Change Order clones",
        "segment": "Trade Change Order — currency-mismatch cases",
        "horizon_kind": "time_window", "horizon_value": "7 days",
        "sample_target": 250, "sample_collected": 28,
        "accuracy_delta_pct": None, "accuracy_delta_ci": "early signal; insufficient sample",
        "regression_status": "none", "promote_status": "shadow",
        "linked_opportunity_segment": "Trade Change Order — currency mismatch",
        "days_ago_started": 1,
    },
    {
        "candidate": "Service Contract AIOA renewal currency inheritance",
        "segment": "Service Contract cases with attached renewal PO",
        "horizon_kind": "time_window", "horizon_value": "10 days",
        "sample_target": 200, "sample_collected": 0,
        "accuracy_delta_pct": None, "accuracy_delta_ci": "candidate pending shadow start",
        "regression_status": "none", "promote_status": "shadow",
        "linked_opportunity_segment": "Service Contract attached-PO validation",
        "days_ago_started": 0,
    },
    {
        "candidate": "Confidence-floor keyword counter-example for KSO",
        "segment": "KSO classifier on shared-keyword cases",
        "horizon_kind": "sample_size", "horizon_value": "500 emails",
        "sample_target": 500, "sample_collected": 320,
        "accuracy_delta_pct": -1.8, "accuracy_delta_ci": "-1.8% on legitimate KSO recall",
        "regression_status": "fail", "promote_status": "retired",
        "linked_opportunity_segment": "Confidence calibration — high-confidence misclassifications",
        "days_ago_started": 9, "days_ago_promoted": 4,
        "promoted_by": "rule-owner-emea", "promote_note": "Retired after regression on legitimate KSO recall; opportunity marked rejected.",
    },
]

INTENT_EDIT_PAIRS: list[tuple[str, str, str]] = [
    ("kso", "quote_to_order", "Customer is in a non-restricted segment for this product family. Re-classified as Q2O."),
    ("kso", "quote_to_order", "Sender domain matches the KSO list but the email body is a legitimate quote follow-up."),
    ("wo_status_inquiry", "service_order", "Email asked for a status update but also requested a new service line — should be Service Order."),
    ("po_intake", "trade_change_order", "PO referenced existing CCC; this is a Change Order against an open order, not a new PO."),
    ("general_inquiry", "quote_to_order", "Customer asked for pricing on N5194A and wants to convert to order. Q2O is the right intent."),
    ("po_intake", "service_contract_request", "PO is a renewal of an existing Service Contract; routed via S+R, not Trade."),
    ("brazil_tax", "po_intake", "Email subject matched the Brazil Tax filter but the attached PDF is a legitimate PO."),
    ("hold_release", "general_inquiry", "Customer was asking why the order is on hold, not requesting release. General inquiry."),
]


# ----------------------------------------------------------------------------
# Helpers

def now_minus(days: float = 0, hours: float = 0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours)


def backdate_pipelines(db, days_window: int, rng: random.Random) -> None:
    """Spread pipeline.started_at across the last `days_window` days, weighted
    so recent days carry more cases (matches realistic volume curve)."""
    pipes = db.query(Pipeline).order_by(Pipeline.id.asc()).all()
    if not pipes:
        return
    print(f"Backdating {len(pipes)} pipelines across the last {days_window} days...")

    # Weighted: more cases recently, fewer further back.
    weights = []
    for d in range(days_window + 1):
        # exponential decay favouring last 7 days
        weights.append(1.0 + max(0.0, 6.0 - 0.6 * d) if d < 7 else 0.4)

    for p in pipes:
        d = rng.choices(range(days_window + 1), weights=weights, k=1)[0]
        h = rng.randint(7, 19)
        m = rng.randint(0, 59)
        ts = datetime.utcnow() - timedelta(days=d, hours=24 - h, minutes=60 - m)
        p.started_at = ts
        if p.status in ("completed", "awaiting_hitl"):
            p.finished_at = ts + timedelta(minutes=rng.randint(1, 9))
        else:
            p.finished_at = None
    db.commit()


def align_feedback_timestamps(db) -> None:
    """Set feedback.created_at to a few minutes after the parent pipeline's
    finished_at so the timeline reads correctly."""
    feedbacks = db.query(Feedback).all()
    pipes_by_id = {p.id: p for p in db.query(Pipeline).all()}
    for f in feedbacks:
        if not f.pipeline_id:
            continue
        p = pipes_by_id.get(f.pipeline_id)
        if not p:
            continue
        base = p.finished_at or p.started_at
        if base is None:
            continue
        f.created_at = base + timedelta(minutes=15 + (f.id % 11))
    db.commit()


def add_intent_edit_feedback(db, rng: random.Random, target_count: int = 18) -> int:
    """Add intent-edit feedback rows on existing intake events so the
    auto-derived tuning-suggestions cluster has data to work with."""
    existing_intent_edits = (
        db.query(Feedback)
        .filter(Feedback.stage == "intake", Feedback.kind == "edit")
        .all()
    )
    have = sum(1 for f in existing_intent_edits if (f.data or {}).get("from_intent"))
    if have >= target_count:
        print(f"Skip intent-edit seed: {have} already present.")
        return 0

    # Pick pipelines that already have feedback so we keep the same set of
    # 'cases at Learning' rather than expanding it.
    pipes_with_fb = (
        db.query(Pipeline)
        .join(Feedback, Feedback.pipeline_id == Pipeline.id)
        .filter(Pipeline.status.in_(["completed", "awaiting_hitl"]))
        .distinct()
        .all()
    )
    rng.shuffle(pipes_with_fb)

    created = 0
    pair_iter = (INTENT_EDIT_PAIRS * 4)
    rng.shuffle(pair_iter)
    for p in pipes_with_fb:
        if created >= (target_count - have):
            break
        pair = pair_iter[created % len(pair_iter)]
        from_intent, to_intent, note = pair
        base = p.finished_at or p.started_at or datetime.utcnow()
        fb = Feedback(
            pipeline_id=p.id,
            stage="intake",
            kind="edit",
            note=note,
            data={
                "source": "seed",
                "from_intent": from_intent,
                "to_intent": to_intent,
                "classifier_intent": from_intent,
                "corrected_intent": to_intent,
            },
        )
        fb.created_at = base + timedelta(minutes=22 + (created * 4))
        db.add(fb)
        created += 1
    db.commit()
    print(f"Added {created} intent-edit feedback rows.")
    return created


def seed_drift_alerts(db) -> dict[str, int]:
    """Insert drift alerts from the catalog. Idempotent by (segment, metric)."""
    seg_metric_to_id: dict[tuple[str, str], int] = {}
    for d in DRIFT_CATALOG:
        existing = (
            db.query(DriftAlert)
            .filter(DriftAlert.segment == d["segment"], DriftAlert.metric == d["metric"])
            .first()
        )
        if existing:
            seg_metric_to_id[(d["segment"], d["metric"])] = existing.id
            continue
        a = DriftAlert(
            segment=d["segment"],
            metric=d["metric"],
            baseline=d["baseline"],
            current=d["current"],
            delta_pct=d["delta_pct"],
            severity=d["severity"],
            circuit_breaker_fired=d.get("circuit_breaker_fired", False),
            status=d["status"],
            note=d["note"],
        )
        a.detected_at = now_minus(d["days_ago"])
        if d.get("status") == "resolved":
            a.resolved_at = now_minus(d.get("resolved_days_ago", 0))
            a.resolved_by = d.get("resolved_by")
        db.add(a)
        db.flush()
        seg_metric_to_id[(d["segment"], d["metric"])] = a.id
    db.commit()
    return {f"{s}|{m}": pid for (s, m), pid in seg_metric_to_id.items()}


def seed_opportunities(db, drift_index: dict[str, int], rng: random.Random) -> dict[str, int]:
    """Insert learning opportunities. Idempotent by `segment`."""
    seg_to_id: dict[str, int] = {}
    pipe_ids = [p.id for p in db.query(Pipeline.id).limit(89).all()]
    for o in OPPORTUNITY_CATALOG:
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.segment == o["segment"])
            .first()
        )
        if existing:
            seg_to_id[o["segment"]] = existing.id
            continue
        opp = LearningOpportunity(
            segment=o["segment"],
            fingerprint=o["fingerprint"],
            proposed_remedy=o["proposed_remedy"],
            expected_lift=o.get("expected_lift"),
            effort=o.get("effort", "Med"),
            risk=o.get("risk", "Med"),
            score=o.get("score", 5.0),
            status=o.get("status", "open"),
            source="drift_signal" if o.get("linked_drift_segment") else "csr_correction_cluster",
            decided_by=o.get("decided_by"),
            decision_note=o.get("decision_note"),
            sample_pipeline_ids=rng.sample(pipe_ids, k=min(3, len(pipe_ids))),
        )
        opp.detected_at = now_minus(o["days_ago"])
        if o.get("decided_by"):
            opp.decided_at = opp.detected_at + timedelta(days=1)
        # link drift alert if any
        if o.get("linked_drift_segment"):
            for k, pid in drift_index.items():
                if k.startswith(o["linked_drift_segment"] + "|"):
                    opp.linked_drift_alert_id = pid
                    break
        db.add(opp)
        db.flush()
        seg_to_id[o["segment"]] = opp.id
    db.commit()
    return seg_to_id


def seed_ab_experiments(db, opp_index: dict[str, int]) -> int:
    """Insert A/B experiments. Idempotent by `candidate`."""
    created = 0
    for x in AB_CATALOG:
        existing = (
            db.query(ABExperiment)
            .filter(ABExperiment.candidate == x["candidate"])
            .first()
        )
        if existing:
            continue
        exp = ABExperiment(
            candidate=x["candidate"],
            segment=x["segment"],
            horizon_kind=x["horizon_kind"],
            horizon_value=x["horizon_value"],
            sample_target=x.get("sample_target", 0),
            sample_collected=x.get("sample_collected", 0),
            accuracy_delta_pct=x.get("accuracy_delta_pct"),
            accuracy_delta_ci=x.get("accuracy_delta_ci"),
            regression_status=x.get("regression_status", "none"),
            promote_status=x.get("promote_status", "shadow"),
            promoted_by=x.get("promoted_by"),
            promote_note=x.get("promote_note"),
            linked_opportunity_id=opp_index.get(x.get("linked_opportunity_segment", "")),
        )
        exp.started_at = now_minus(x["days_ago_started"])
        if x.get("days_ago_promoted") is not None:
            exp.promoted_at = now_minus(x["days_ago_promoted"])
        db.add(exp)
        created += 1
    db.commit()
    return created


# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30,
                        help="Backdate window in days (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    # Make sure new tables exist
    Base.metadata.create_all(bind=engine, tables=[
        DriftAlert.__table__,
        LearningOpportunity.__table__,
        ABExperiment.__table__,
    ])

    rng = random.Random(args.seed)
    db = SessionLocal()
    try:
        backdate_pipelines(db, args.days, rng)
        align_feedback_timestamps(db)
        edits = add_intent_edit_feedback(db, rng, target_count=18)
        drift_index = seed_drift_alerts(db)
        opp_index = seed_opportunities(db, drift_index, rng)
        ab_count = seed_ab_experiments(db, opp_index)

        # report
        print("\n--- Seed summary ---")
        print(f"  drift alerts:      {db.query(DriftAlert).count()}  (open={db.query(DriftAlert).filter(DriftAlert.status=='open').count()}  resolved={db.query(DriftAlert).filter(DriftAlert.status=='resolved').count()}  slo_breach={db.query(DriftAlert).filter(DriftAlert.severity=='slo_breach').count()})")
        print(f"  opportunities:     {db.query(LearningOpportunity).count()}  (open={db.query(LearningOpportunity).filter(LearningOpportunity.status=='open').count()}  in_ab={db.query(LearningOpportunity).filter(LearningOpportunity.status=='in_ab').count()}  promoted={db.query(LearningOpportunity).filter(LearningOpportunity.status=='promoted').count()})")
        print(f"  ab experiments:    {db.query(ABExperiment).count()}  (shadow={db.query(ABExperiment).filter(ABExperiment.promote_status=='shadow').count()}  ready={db.query(ABExperiment).filter(ABExperiment.promote_status=='ready').count()}  promoted={db.query(ABExperiment).filter(ABExperiment.promote_status=='promoted').count()}  retired={db.query(ABExperiment).filter(ABExperiment.promote_status=='retired').count()})")
        print(f"  intent-edit feedback added this run: {edits}")
        distinct_fb_pipes = db.query(Feedback.pipeline_id).filter(Feedback.pipeline_id.isnot(None)).distinct().count()
        print(f"  distinct pipelines carrying feedback (Continuous Learning count): {distinct_fb_pipes}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
