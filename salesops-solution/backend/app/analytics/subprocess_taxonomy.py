"""Sub-process taxonomy for the Analytics per-stage detail view.

This is the single contract that maps human-readable sub-processes to the
real trace-event signatures the orchestrator emits. Every per-sub-process
rollup (volume, auto / HITL / fail split, latency) is computed live against
this taxonomy plus the `trace_events` table; no per-sub-process aggregation
is hard-coded anywhere else.

Matching rules per sub-process (any field is optional, OR-ed together):
    substeps: list[str]   -> data["substep"] in this list
    tools:    list[str]   -> kind == "tool_end" and data["tool"] in this list
    kinds:    list[str]   -> kind in this list

A trace event matches a sub-process if any predicate evaluates true.
A pipeline is counted toward a sub-process when at least one of its events
matches; latency is averaged across matching events that carry duration.

When the orchestrator adds a new tool or substep that no taxonomy entry
covers, the audit script in `scripts/check_subprocess_taxonomy.py`
surfaces it as "Unclassified", forcing this file to stay in sync.
"""

from __future__ import annotations

STAGE_ORDER: list[str] = ["intake", "extract", "decide", "execute", "communicate", "learning"]

# Stage-level metadata. The pre_intake stage is treated as a deterministic
# pre-filter and surfaced inside the Intake stage UI rather than as a top
# level entry, because no business outcome attaches to it on its own.
STAGE_META: dict[str, dict] = {
    "intake":      {"id": 1, "label": "Intake & Classification",     "tagline": "Read inbound mail, detect language, classify intent across mailboxes."},
    "extract":     {"id": 2, "label": "Extraction & Enrichment",      "tagline": "OCR, schema-driven extraction, entity resolution against Salesforce."},
    "decide":      {"id": 3, "label": "Decision & Confidence Scoring", "tagline": "Four-gate confidence model, tiered autonomy, routing."},
    "execute":     {"id": 4, "label": "Workflow Execution",            "tagline": "CCC writes to Salesforce today. Oracle EBS / DocuNet via Jitterbit is upcoming."},
    "communicate": {"id": 5, "label": "Communication & Close-out",     "tagline": "Drafts in customer language, attaches SOA, files in SharePoint."},
    "learning":    {"id": 6, "label": "Continuous Learning",           "tagline": "CSR corrections, drift detection, Knowledge Base updates."},
}

# Sub-process definitions per stage. The `match` predicates are OR-ed.
SUBPROCESS_TAXONOMY: list[dict] = [
    # --- Stage 1: Intake & Classification -------------------------------------
    {
        "stage": "intake",
        "subprocesses": [
            {
                "key": "outlook_prefilter",
                "label": "Outlook pre-filter rules",
                "description": "Deterministic Outlook rules redirect bounces, KSO traffic, tax filings, portal codes, and collections before any AI reads the body.",
                "match": {"kinds": ["rule_matched", "redirect", "no_match"], "stages": ["pre_intake"]},
            },
            {
                "key": "spam_phishing",
                "label": "Spam & phishing screen",
                "description": "Two independent screens (heuristic + LLM) confirm before discarding suspicious mail.",
                "match": {"tools": ["detect_spam", "llm_spam_check"]},
            },
            {
                "key": "language_detect",
                "label": "Language detection",
                "description": "Per-source detection on the body and each attachment so an English cover + Spanish PO is handled correctly.",
                "match": {"tools": ["detect_language"]},
            },
            {
                "key": "attachment_ocr",
                "label": "Attachment OCR / vision",
                "description": "Layered OCR (Azure Document Intelligence) and vision-capable model for image-only PDFs and scans.",
                "match": {"tools": ["azure_doc_intelligence", "vision_ocr"]},
            },
            {
                "key": "inbound_translate",
                "label": "Inbound translation",
                "description": "Translate non-English content to English so downstream stages reason consistently.",
                "match": {"tools": ["translate_to_english"], "stages": ["intake"]},
            },
            {
                "key": "intent_classify",
                "label": "Two-pass intent classifier",
                "description": "First pass proposes intent; second pass cross-checks against the operational rule book and either confirms or overrides.",
                "match": {"tools": ["classify_intent", "shadow_classifier"]},
            },
            {
                "key": "csr_override",
                "label": "CSR routing-override detection",
                "description": "Detects Keysight staff routing instructions inside the email body and supersedes default routing.",
                "match": {"tools": ["detect_csr_override", "override_pass"]},
            },
        ],
    },

    # --- Stage 2: Extraction & Enrichment ------------------------------------
    {
        "stage": "extract",
        "subprocesses": [
            {
                "key": "doc_extraction",
                "label": "Document extraction (OCR / vision)",
                "description": "Walk every attachment, run OCR or vision-capable extraction, hand the structured text to schema-driven extraction.",
                "match": {"substeps": ["2.1"], "tools": ["azure_doc_intelligence", "vision_ocr"], "stages": ["extract"]},
            },
            {
                "key": "schema_extraction",
                "label": "Schema-driven field extraction",
                "description": "Per-intent schema pulls PO number, ship-to, line items, currency, payment terms, and the rest.",
                "match": {"substeps": ["2.2"], "tools": ["schema_extract", "llm_extract"]},
            },
            {
                "key": "customer_identify",
                "label": "Customer identification",
                "description": "Fuzzy match sender domain and account name against the customer master.",
                "match": {"substeps": ["2.3"], "tools": ["entity_resolve_customer"]},
            },
            {
                "key": "customer_enrich",
                "label": "Customer enrichment",
                "description": "Hydrate Salesforce account, contacts, recent orders, attached files via Jitterbit.",
                "match": {"substeps": ["2.4"], "tools": ["salesforce_soql", "salesforce_fetch_files", "sharepoint_fetch_doc"]},
            },
            {
                "key": "cross_validate",
                "label": "Cross-system validation",
                "description": "Reconcile PO line items against the matched quote; flag price, quantity, terms mismatches.",
                "match": {"substeps": ["2.5"]},
            },
        ],
    },

    # --- Stage 3: Decision & Confidence Scoring -------------------------------
    {
        "stage": "decide",
        "subprocesses": [
            {
                "key": "existing_ccc_lookup",
                "label": "Existing-CCC matrix lookup",
                "description": "Look up the inbound PO or WO number against open CCCs to drive new / update / change-order routing.",
                "match": {"substeps": ["3.0"]},
            },
            {
                "key": "routing_resolver",
                "label": "Routing resolver",
                "description": "Apply distributor list, magic-SKU table, FE/CSR overrides, region overlays, citizenship-based KSO routing.",
                "match": {"substeps": ["3.0b"]},
            },
            {
                "key": "confidence_formula",
                "label": "Confidence formula",
                "description": "Combine classification, extraction, entity-resolution, and action-feasibility signals into the four-gate score.",
                "match": {"substeps": ["3.1"]},
            },
            {
                "key": "business_rules",
                "label": "Business rules evaluation",
                "description": "Evaluate operational predicates (dollar caps, export controls, customer flags) that can cap autonomy or hard-block.",
                "match": {"substeps": ["3.2"], "tools": ["business_rules_eval"]},
            },
            {
                "key": "final_tier_decision",
                "label": "Final tier decision",
                "description": "Set the autonomy tier (L4 auto / L3 one-click / L2 full review) based on the lowest gate score.",
                "match": {"substeps": ["3.3"]},
            },
            {
                "key": "action_selection",
                "label": "Action selection",
                "description": "Pick the downstream workflow action based on the tier and the resolved intent (Q2O, hold release, change order, status reply, and so on).",
                "match": {"substeps": ["3.4"]},
            },
        ],
    },

    # --- Stage 4: Workflow Execution ------------------------------------------
    {
        "stage": "execute",
        "subprocesses": [
            {
                "key": "customer_guardrail",
                "label": "Customer-match guardrail",
                "description": "Refuse to write to Salesforce when the customer match is below threshold or ambiguous.",
                "match": {"substeps": ["4.1"]},
            },
            {
                "key": "idempotency_check",
                "label": "Idempotency check",
                "description": "Detect duplicate PO submissions in the same thread, skip the duplicate write.",
                "match": {"substeps": ["4.2"]},
            },
            {
                "key": "workflow_action",
                "label": "Workflow action execution",
                "description": "Salesforce CCC / WorkOrder / Case writes today. Oracle EBS / DocuNet filing via Jitterbit is upcoming once the bridge is enabled.",
                "match": {"substeps": ["4.3"], "tools": ["salesforce_create_order"]},
            },
        ],
    },

    # --- Stage 5: Communication & Close-out -----------------------------------
    {
        "stage": "communicate",
        "subprocesses": [
            {
                "key": "draft_reply",
                "label": "Draft customer reply",
                "description": "Compose the customer-facing reply in English against the per-intent template.",
                "match": {"substeps": ["5.1"]},
            },
            {
                "key": "translate_outbound",
                "label": "Translate to customer language",
                "description": "Translate the draft into the customer's detected language with the per-language glossary applied.",
                "match": {"substeps": ["5.2"], "tools": ["translate_to_english"], "stages": ["communicate"]},
            },
            {
                "key": "attach_documents",
                "label": "Attach SOA / generated documents",
                "description": "Generate SOA / acknowledgement PDFs and attach them to the outbound message.",
                "match": {"substeps": ["5.3"]},
            },
            {
                "key": "comm_log",
                "label": "Communication log",
                "description": "Persist the outbound message into the audit log with the per-email reference.",
                "match": {"substeps": ["5.4"]},
            },
        ],
    },

    # --- Stage 6: Continuous Learning -----------------------------------------
    # Learning has no per-pipeline trace events at the sub-process level today;
    # the sub-processes correspond to records in the learning ledger tables.
    {
        "stage": "learning",
        "subprocesses": [
            {
                "key": "feedback_capture",
                "label": "CSR feedback capture",
                "description": "Every CSR action (re-classification, edit, rejection, override) lands in the Learning Store.",
                "match": {"_source": "feedback_table"},
            },
            {
                "key": "drift_detection",
                "label": "Drift detection",
                "description": "Rolling-baseline detector raises an alert when accuracy, HITL rate, or per-language extraction drifts.",
                "match": {"_source": "drift_alerts_table"},
            },
            {
                "key": "opportunity_review",
                "label": "Opportunity review",
                "description": "Weekly batch clusters signals into ranked opportunities for rule-owner decision.",
                "match": {"_source": "learning_opportunities_table"},
            },
            {
                "key": "ab_promotion",
                "label": "A/B promotion",
                "description": "Accepted opportunities run as shadow changes alongside production until success criteria gate promotion.",
                "match": {"_source": "ab_experiments_table"},
            },
        ],
    },
]


def stages_in_order() -> list[dict]:
    """Return STAGE_META as an ordered list with stage_key included."""
    out = []
    for s in STAGE_ORDER:
        meta = STAGE_META[s]
        out.append({"stage_key": s, **meta})
    return out


def subprocesses_for(stage: str) -> list[dict]:
    """Return the sub-process list for a given stage key."""
    for entry in SUBPROCESS_TAXONOMY:
        if entry["stage"] == stage:
            return entry["subprocesses"]
    return []
