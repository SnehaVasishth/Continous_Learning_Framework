"""Track classification per the RFP use-case diagrams.

Each diagram in `SalesOps - RFP.xlsx → "use case"` shows the pipeline running
on one of six **tracks** (the swimlane in the top-right corner). The track is
the high-level queue / specialist group that owns the case end-to-end:

- FCNV    — Functional Classification & Verification
- AI_OA   — AI Order Acceptance (external app, ZBrain triggers via webhook)
- Trade   — Trade order desk
- SOM     — Service Order Management
- S_AND_A — Service Contracts / Agreements (CTA)
- POB     — Post Order Booking (SSD changes, delivery changes, hold release)

A single case can touch multiple tracks. The "primary_track" is the track
that drives the dashboard tile + CCC owner assignment; the "secondary_tracks"
list every track the case will pass through.

This module is pure-Python with zero side effects: it just maps
(intent, fallout flags) → tracks. Stage 1 (intake) calls it once after
classification and persists the result on the pipeline decision block so
Stage 3 owner assignment and downstream UI can read it.
"""
from __future__ import annotations

from typing import Any


# Every intent the pipeline classifies has at least one primary track.
INTENT_TO_PRIMARY_TRACK: dict[str, str] = {
    "po_intake": "Trade",
    "quote_to_order": "Trade",
    "trade_change_order": "Trade",
    "hold_release": "POB",
    "ssd_change_request": "POB",
    "delivery_change": "POB",
    "service_order": "SOM",
    "wo_update_request": "SOM",
    "wo_status_inquiry": "SOM",
    "service_contract_request": "S_AND_A",
    "general_inquiry": "FCNV",
    "out_of_scope": "FCNV",
    "spam": "FCNV",
}

# Intents that go through the FCNV review gate as part of their happy path.
FCNV_GATED_INTENTS: set[str] = {
    "po_intake",
    "quote_to_order",
    "trade_change_order",
    "service_order",
    "wo_update_request",
    "service_contract_request",
    "ssd_change_request",
}

# Intents whose happy path involves AIOA validation (subset of FCNV-gated).
AIOA_GATED_INTENTS: set[str] = {
    "po_intake",
    "quote_to_order",
    "trade_change_order",
    "wo_update_request",
    "service_contract_request",
}


def classify_tracks(
    *,
    intent: str | None,
    fcnv_review_required: bool = False,
    aioa_outcome: str | None = None,
) -> dict[str, Any]:
    """Return a track block: primary_track, secondary_tracks, all_tracks_touched.

    The primary track drives queue ownership. Secondary tracks are appended
    when the case enters that specialist queue (e.g., FCNV when the FCNV
    review gate caps the tier, AI_OA when AIOA fires).
    """
    intent = intent or "general_inquiry"
    primary = INTENT_TO_PRIMARY_TRACK.get(intent, "FCNV")
    secondary: list[str] = []

    # FCNV is always touched first if the intent is FCNV-gated — the FCNV
    # specialist queue is the catch-all for low-confidence enrichment.
    if intent in FCNV_GATED_INTENTS:
        if "FCNV" != primary and "FCNV" not in secondary:
            secondary.insert(0, "FCNV")

    # AI OA appears as a swimlane any time AIOA could apply, even if it ends
    # up skipped (the diagram still references the track at the top).
    if intent in AIOA_GATED_INTENTS and "AI_OA" not in (primary, *secondary):
        secondary.append("AI_OA")

    # If the FCNV review gate has capped the case, FCNV is the operating
    # queue regardless of what the intent track was.
    if fcnv_review_required:
        if "FCNV" not in secondary and primary != "FCNV":
            secondary.insert(0, "FCNV")

    # If AIOA returned a fail, AI_OA fallout owns the case until CSR works it.
    if (aioa_outcome or "").upper() == "AIOA_FAIL":
        if "AI_OA" not in secondary and primary != "AI_OA":
            secondary.insert(0, "AI_OA")

    all_tracks = [primary] + [t for t in secondary if t != primary]
    return {
        "primary_track": primary,
        "secondary_tracks": secondary,
        "all_tracks_touched": all_tracks,
    }


# Owner assignment per track + tier + fallout state. The RFP diagrams call
# out specific named CSR groups for each step; this is the canonical map.
# Static routing-key resolution. This decides *which* owner_queue applies
# (the keys are stable identifiers); the human-visible label, description,
# Salesforce queue id, etc. are all resolved from the KB at runtime in
# `_enrich_from_kb`.
_TRACK_TO_QUEUE: dict[str, str] = {
    "FCNV": "fcnv_scope",
    "AI_OA": "ai_oa_fallout",
    "Trade": "trade_csr",
    "SOM": "som_csr",
    "S_AND_A": "cta_scope",
    "POB": "post_order_booking",
}


def _route(
    *,
    primary_track: str,
    autonomy_tier: str | None,
    fcnv_review_required: bool,
    aioa_outcome: str | None,
    is_aioa_handoff: bool,
    is_no_reply: bool,
) -> tuple[str, str]:
    """Compute (owner_queue, reason) — pure routing logic, no KB lookup."""
    if fcnv_review_required:
        return "fcnv_scope", "FCNV review gate fired (low extraction confidence or missing parties)"
    if (aioa_outcome or "").upper() == "AIOA_FAIL":
        return "ai_oa_fallout", "AIOA validation failed; case is in AI OA Fallout queue"
    if is_aioa_handoff:
        return "automation_complete", "AIOA accepted the case; downstream order acceptance is owned by AIOA"
    if autonomy_tier and autonomy_tier in ("L3_ONE_CLICK", "L2_HITL"):
        queue = _TRACK_TO_QUEUE.get(primary_track, "fcnv_scope")
        return queue, f"{primary_track} track CSR review for tier={autonomy_tier}"
    if is_no_reply and (autonomy_tier == "L4_AUTO"):
        return "automation_complete", "L4 auto path closes CCC Request without a customer reply"
    return "automation_complete", "L4 auto path; ZBrain completes the action and sends the customer reply"


def _enrich_from_kb(db: Any, owner_queue: str) -> dict[str, Any]:
    """Look up the KB row for this owner_queue. Returns label, description,
    ai_handled, and salesforce.queue_id when populated. Tolerant — falls back
    to sensible defaults if the namespace isn't seeded yet."""
    label = owner_queue.replace("_", " ").title()
    salesforce_owner_id: str | None = None
    salesforce_queue_label: str | None = None
    ai_handled = (owner_queue == "automation_complete")
    if db is None:
        return {"owner_label": label, "salesforce_owner_id": None, "salesforce_queue_label": None, "ai_handled": ai_handled}
    try:
        from ..models import KnowledgeRule
        row = (
            db.query(KnowledgeRule)
            .filter_by(namespace="owner_mapping", key=owner_queue)
            .first()
        )
        if row and row.body:
            body = row.body
            label = body.get("label") or label
            ai_handled = bool(body.get("ai_handled"))
            sf = body.get("salesforce") or {}
            salesforce_owner_id = sf.get("queue_id")
            salesforce_queue_label = sf.get("queue_label")
    except Exception:
        # KB read failure should never break Stage 3.4 — fall back to defaults.
        pass
    return {
        "owner_label": label,
        "salesforce_owner_id": salesforce_owner_id,
        "salesforce_queue_label": salesforce_queue_label,
        "ai_handled": ai_handled,
    }


def assign_ccc_owner(
    *,
    primary_track: str,
    autonomy_tier: str | None,
    fcnv_review_required: bool,
    aioa_outcome: str | None,
    is_aioa_handoff: bool,
    is_no_reply: bool,
    db: Any = None,
) -> dict[str, Any]:
    """Pick the CCC Request owner per the RFP swimlane convention.

    Returns an owner block. The routing is pure code; the human-visible label,
    Salesforce queue id, and ai_handled flag come from the `owner_mapping` KB
    namespace so operators can edit them without code changes.
    """
    owner_queue, reason = _route(
        primary_track=primary_track,
        autonomy_tier=autonomy_tier,
        fcnv_review_required=fcnv_review_required,
        aioa_outcome=aioa_outcome,
        is_aioa_handoff=is_aioa_handoff,
        is_no_reply=is_no_reply,
    )
    enriched = _enrich_from_kb(db, owner_queue)
    return {
        "owner_queue": owner_queue,
        "reason": reason,
        **enriched,
    }


# Friendly track labels for the UI.
TRACK_LABELS: dict[str, str] = {
    "FCNV": "FCNV Track",
    "AI_OA": "AI OA Track",
    "Trade": "Trade Track",
    "SOM": "SOM Track",
    "S_AND_A": "Service Contracts & Agreements Track",
    "POB": "Post Order Booking Track",
}
