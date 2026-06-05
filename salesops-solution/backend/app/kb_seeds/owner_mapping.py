"""Owner mapping KB — Case ownership keyed by routing key.

Stage 3.4 (Assign CCC Request owner) emits a routing key based on
(track, tier, fallout, AIOA outcome, no-reply). This namespace turns that
routing key into the actual operator-visible owner: a human label, a CSR
queue description, and the **real Salesforce Queue Id** the orchestrator
writes to Case.OwnerId.

Operators edit these rows in the KB UI like any other namespace; the
"Sync from Salesforce" action populates `salesforce.queue_id` from the live
SF org; the "Provision in Salesforce" action creates a queue if it's missing.
"""
from __future__ import annotations


# Every owner the track classifier can emit, with default Salesforce Queue
# developer names. queue_id starts null and is filled in by the
# `/api/integrations/salesforce/owners/sync` action.
OWNER_MAPPING: list[dict] = [
    {
        "key": "fcnv_scope",
        "label": "FCNV CSR",
        "description": (
            "Functional Classification & Verification specialist queue. Receives any case "
            "where required parties (PO#, line_items, asset list, work_order_number) "
            "couldn't be resolved during enrichment. CSR completes the enrichment by hand "
            "before the case can advance."
        ),
        "default_tracks": ["FCNV"],
        "ai_handled": False,
        "salesforce": {
            "queue_developer_name": "ZBrain_FCNV",
            "queue_label": "ZBrain FCNV Team",
            "queue_id": None,
            "last_synced_at": None,
        },
    },
    {
        "key": "ai_oa_fallout",
        "label": "AI OA CSR",
        "description": (
            "AI Order Acceptance fallout queue. AIOA (the external Keysight app that "
            "validates inbound POs) returned AIOA_FAIL, so the case is worked inside "
            "AIOA's own Fallout Review queue. ZBrain records the handoff and waits."
        ),
        "default_tracks": ["AI_OA"],
        "ai_handled": False,
        "salesforce": {
            "queue_developer_name": "ZBrain_AIOA_Fallout",
            "queue_label": "ZBrain AI OA Fallout Team",
            "queue_id": None,
            "last_synced_at": None,
        },
    },
    {
        "key": "trade_csr",
        "label": "Trade CSR",
        "description": (
            "Trade order desk. Owns L3/L2 cases on the Trade track (PO intake, quote-to-order, "
            "trade change orders) when the AI didn't reach the L4 threshold or when an AIOA-bypass "
            "path needs human confirmation before SF Order write."
        ),
        "default_tracks": ["Trade"],
        "ai_handled": False,
        "salesforce": {
            "queue_developer_name": "ZBrain_Trade_CSR",
            "queue_label": "ZBrain Trade CSR",
            "queue_id": None,
            "last_synced_at": None,
        },
    },
    {
        "key": "som_csr",
        "label": "SOM CSR",
        "description": (
            "Service Order Management specialist queue. Owns L3/L2 cases on the SOM track "
            "(service_order, wo_update_request, wo_status_inquiry) when the AI needs human "
            "review — multi-asset spreadsheets we can't parse, asset disambiguation, etc."
        ),
        "default_tracks": ["SOM"],
        "ai_handled": False,
        "salesforce": {
            "queue_developer_name": "ZBrain_SOM_CSR",
            "queue_label": "ZBrain SOM CSR",
            "queue_id": None,
            "last_synced_at": None,
        },
    },
    {
        "key": "cta_scope",
        "label": "CTA CSR (Contracts & Agreements)",
        "description": (
            "Service Contracts / Agreements specialist queue. Owns cases on the S&A track "
            "(service_contract_request) when CSR pre-AIOA review is required, or when the "
            "contract needs legal / export-control sign-off before AIOA can run."
        ),
        "default_tracks": ["S_AND_A"],
        "ai_handled": False,
        "salesforce": {
            "queue_developer_name": "ZBrain_CTA_Scope",
            "queue_label": "ZBrain CTA (Contracts & Agreements)",
            "queue_id": None,
            "last_synced_at": None,
        },
    },
    {
        "key": "post_order_booking",
        "label": "Sales Order Owner / Direct Inquiries (Oracle)",
        "description": (
            "Post Order Booking queue — Sales Order Owner per the SSD change diagram "
            "(UC7). Owns L3/L2 cases where the SF Sales Order owner needs to coordinate "
            "with the Factory via the CSR dashboard and Oracle."
        ),
        "default_tracks": ["POB"],
        "ai_handled": False,
        "salesforce": {
            "queue_developer_name": "ZBrain_POB_Owner",
            "queue_label": "ZBrain Sales Order Owner / POB",
            "queue_id": None,
            "last_synced_at": None,
        },
    },
    {
        "key": "automation_complete",
        "label": "AI Agent",
        "description": (
            "Automation-complete handler. No human queue — used for L4 happy paths, AIOA "
            "handoffs, and no-reply close paths (UC3 SOM auto-WO, UC4 WO update, UC7 SSD). "
            "Case OwnerId stays on the integration user; no queue assignment."
        ),
        "default_tracks": [],
        "ai_handled": True,
        "salesforce": {
            "queue_developer_name": None,
            "queue_label": None,
            "queue_id": None,
            "last_synced_at": None,
        },
    },
]


def all_rules() -> list[dict]:
    return OWNER_MAPPING
