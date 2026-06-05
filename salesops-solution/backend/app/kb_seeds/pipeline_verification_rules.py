"""Pipeline verification rules KB seed.

These are declarative invariants the verifier evaluates at every stage_end
and once at orchestrator close. Each rule has:

  key                — stable identifier (used to de-duplicate notifications)
  label              — short human-readable name (shown in KB editor + Trace)
  description        — why this invariant matters; what bug it catches
  enabled            — toggled by operators; disabled rules are skipped
  mode               — 'shadow' (log only, no enforcement) or 'active'
  severity           — 'block', 'warn', or 'audit'
                       block: emits notification + applies corrective_action
                       warn : emits notification only
                       audit: trace-event only, no notification
  applies_when       — predicate expression (string evaluated against ctx).
                       Truthy result means the rule applies; falsy skips.
                       Variables in scope:
                         intent, tier, status, action,
                         aioa_outcome (None | 'AIOA_PASS' | 'AIOA_FAIL'),
                         aioa_fired (bool),
                         fcnv_review_required (bool),
                         no_reply (bool), is_no_reply (alias),
                         exec_status (str),
                         owner_label, owner_queue, ai_handled,
                         track,
                         assets_count, has_po_number, has_line_items,
                         has_wo_number,
                         reply_body, reply_subject, reply_sent,
                         has_soa_attachment, has_sharepoint_url,
                         confidence,
                         pipeline (the raw Pipeline row),
                         decision, execution, intake, extracted, reply
  invariant          — predicate expression; truthy = pass, falsy = fail.
                       Same scope as applies_when.
  corrective_action  — for block-severity rules only:
                       'halt'             : do not let the pipeline complete
                       'force_no_reply'   : set execution.no_reply = true
                                            and resume (rerun Stage 5 short-circuit)
                       'force_tier_L2'    : cap autonomy_tier to L2_HITL
                       'flag_for_review'  : record a HITL flag but allow through
                       'none'             : record only (same as warn)
  evaluate_at        — list of pipeline stages where this rule runs.
                       Defaults to ['final']. Use 'stage_end:decide' for the
                       moment Stage 3 ends, etc. ('final' = orchestrator close)

Notation for predicate strings: Python expressions, restricted scope. The
verifier compiles them once with `compile()` and evaluates against a
read-only dict. NO function calls allowed beyond the safe whitelist (and,
or, not, ==, !=, <, <=, >, >=, in, len, any, all, type checks).
"""
from __future__ import annotations


VERIFICATION_RULES: list[dict] = [
    {
        "key": "aioa_fail_no_reply",
        "label": "AIOA_FAIL must not draft a customer reply",
        "description": (
            "When AIOA returns AIOA_FAIL the case is in AIOA's Fallout queue — "
            "AI OA CSR handles all customer comms. Stage 5 must not draft a reply."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "aioa_outcome == 'AIOA_FAIL'",
        "invariant": "no_reply == True and not reply_body",
        "corrective_action": "force_no_reply",
        "evaluate_at": ["stage_end:execute", "final"],
    },
    {
        "key": "aioa_pass_no_zbrain_write",
        "label": "AIOA_PASS must not produce a ZBrain SF Order write",
        "description": (
            "When AIOA returns AIOA_PASS, AIOA owns the order acceptance and the "
            "downstream Oracle EBS write. ZBrain must not also create a SF Order."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "aioa_outcome == 'AIOA_PASS'",
        "invariant": (
            "exec_status == 'handed_off_to_aioa' and "
            "no_reply == True and "
            "not (execution.get('applied') or {}).get('salesforce_order_id')"
        ),
        "corrective_action": "force_no_reply",
        "evaluate_at": ["stage_end:execute", "final"],
    },
    {
        "key": "fcnv_review_caps_tier",
        "label": "FCNV review gate must cap tier to L2_HITL",
        "description": (
            "Per the RFP use-case diagrams, the FCNV review fallout is an explicit "
            "Human-in-Loop branch. When 2.6 flags fcnv_review_required, tier must drop to L2."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "fcnv_review_required == True",
        "invariant": "tier == 'L2_HITL'",
        "corrective_action": "force_tier_L2",
        "evaluate_at": ["stage_end:decide", "final"],
    },
    {
        "key": "service_order_multi_no_reply",
        "label": "service_order multi-asset auto-WO must be no-reply",
        "description": (
            "UC3 SOM auto-WO path (≥2 assets) creates one WO per asset and closes "
            "the CCC Request without a customer email; SOM CSR confirms separately."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "intent == 'service_order' and tier == 'L4_AUTO' and assets_count >= 2",
        "invariant": "no_reply == True and exec_status == 'applied_no_reply'",
        "corrective_action": "force_no_reply",
        "evaluate_at": ["stage_end:execute", "final"],
    },
    {
        "key": "wo_update_no_reply",
        "label": "wo_update_request L4 auto must be no-reply",
        "description": (
            "UC4 SOM WO update — when the AI updates a WO directly, the case closes "
            "with no customer email. CSR reviews the WO and reply separately."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "intent == 'wo_update_request' and tier == 'L4_AUTO'",
        "invariant": "no_reply == True and exec_status == 'applied_no_reply'",
        "corrective_action": "force_no_reply",
        "evaluate_at": ["stage_end:execute", "final"],
    },
    {
        "key": "ssd_factory_handoff",
        "label": "SSD change request L4 auto must trigger factory handoff",
        "description": (
            "UC7 SSD — when the AI handles an SSD change autonomously, it must add "
            "the SSD to the CSR dashboard, notify factories, and auto-close (no reply)."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "intent == 'ssd_change_request' and tier == 'L4_AUTO'",
        "invariant": (
            "no_reply == True and "
            "(execution.get('applied') or {}).get('ssd_factory_handoff') == True"
        ),
        "corrective_action": "flag_for_review",
        "evaluate_at": ["stage_end:execute", "final"],
    },
    {
        "key": "wo_status_must_reply",
        "label": "wo_status_inquiry L4 must produce a customer reply",
        "description": (
            "UC5 WO status — the L4 happy path always sends an auto-reply with "
            "the WO status and KSP reassurance. A reply with empty body is a bug."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "warn",
        "applies_when": "intent == 'wo_status_inquiry' and tier == 'L4_AUTO'",
        "invariant": "reply_body and len(reply_body or '') > 30",
        "corrective_action": "flag_for_review",
        "evaluate_at": ["stage_end:communicate", "final"],
    },
    {
        "key": "po_intake_l4_must_have_soa",
        "label": "po_intake L4 must produce an SOA attachment",
        "description": (
            "UC1 trade order entry happy path — the L4 outbound includes a Sales "
            "Order Acknowledgment PDF, filed in SharePoint and attached to the CCC."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "warn",
        "applies_when": (
            "intent in ('po_intake', 'quote_to_order', 'trade_change_order') and "
            "tier == 'L4_AUTO' and aioa_outcome != 'AIOA_PASS' and aioa_outcome != 'AIOA_FAIL'"
        ),
        "invariant": "has_soa_attachment == True",
        "corrective_action": "flag_for_review",
        "evaluate_at": ["stage_end:communicate", "final"],
    },
    {
        "key": "owner_required_terminal",
        "label": "Every terminal pipeline must have a CCC owner assigned",
        "description": (
            "Every pipeline that reaches a terminal status (completed / awaiting_hitl / "
            "discarded) must have decision.owner.owner_label set so the case lands in "
            "the right SF queue."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "warn",
        "applies_when": "status in ('completed', 'awaiting_hitl', 'discarded')",
        "invariant": "owner_label is not None and owner_label != ''",
        "corrective_action": "flag_for_review",
        "evaluate_at": ["final"],
    },
    {
        "key": "automation_complete_ai_handled",
        "label": "automation_complete queue must be ai_handled",
        "description": (
            "The 'automation_complete' owner_queue is by definition not a human queue. "
            "Any case landing there must have ai_handled=true; otherwise the owner_mapping "
            "KB row is misconfigured."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "owner_queue == 'automation_complete'",
        "invariant": "ai_handled == True",
        "corrective_action": "flag_for_review",
        "evaluate_at": ["stage_end:decide", "final"],
    },
    {
        "key": "aioa_only_applicable_intents",
        "label": "AIOA may only fire on AIOA-eligible intents",
        "description": (
            "AIOA validation is preserved only for intents that produce PO data: "
            "po_intake, quote_to_order, trade_change_order, wo_update_request, "
            "service_contract_request. Any other intent firing AIOA is a misroute."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "aioa_fired == True",
        "invariant": (
            "intent in ('po_intake', 'quote_to_order', 'trade_change_order', "
            "'wo_update_request', 'service_contract_request')"
        ),
        "corrective_action": "flag_for_review",
        "evaluate_at": ["stage_end:decide", "final"],
    },
    {
        "key": "discarded_no_external_write",
        "label": "Discarded cases must have no external writes",
        "description": (
            "Spam / out_of_scope / undeliverable cases short-circuit at Stage 1. They "
            "must not produce any SF / SharePoint write or customer reply."
        ),
        "enabled": True,
        "mode": "active",
        "severity": "block",
        "applies_when": "status == 'discarded'",
        "invariant": (
            "not (execution.get('applied') or {}).get('salesforce_order_id') and "
            "reply_sent == False"
        ),
        "corrective_action": "halt",
        "evaluate_at": ["final"],
    },
    {
        "key": "tier_threshold_consistency",
        "label": "Final tier must match confidence thresholds",
        "description": (
            "L4_AUTO ≥ 0.95, L3_ONE_CLICK 0.80–0.94, L2_HITL < 0.80. Any deviation "
            "(unless a hard_block / fcnv_review cap fired) is a rubric inconsistency."
        ),
        "enabled": True,
        "mode": "shadow",  # start in shadow — cap-driven deviations may need exemptions
        "severity": "audit",
        "applies_when": "tier in ('L4_AUTO', 'L3_ONE_CLICK', 'L2_HITL') and confidence is not None",
        "invariant": (
            "(tier == 'L4_AUTO' and confidence >= 0.95) or "
            "(tier == 'L3_ONE_CLICK' and confidence >= 0.80 and confidence < 0.95) or "
            "(tier == 'L2_HITL' and confidence < 0.80) or "
            "fcnv_review_required == True"
        ),
        "corrective_action": "none",
        "evaluate_at": ["final"],
    },
]


def all_rules() -> list[dict]:
    return VERIFICATION_RULES
