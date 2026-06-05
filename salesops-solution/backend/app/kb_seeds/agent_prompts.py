"""Agent prompt registry — one KB row per agent stage.

Surfaces the live system / user-template prompts each stage agent runs.
Continuous-Learning prompt-refinement experiments target exactly these
rows: a promotion writes the new prompt body into `body.system_prompt` /
`body.user_template`, bumps the version, and stamps a `kb_rule_versions`
row for rollback. Agent code reads the active body from here at run-time
so a promotion is immediately effective without a deploy.
"""
from __future__ import annotations

from typing import Any


_BASE: list[dict[str, Any]] = [
    {
        "key": "intake:system",
        "label": "Intake & Classification · system prompt",
        "description": (
            "System prompt the Intake agent uses to classify intent and language. "
            "Refined via Continuous Learning when classification accuracy drifts."
        ),
        "stage": "intake",
        "agent": "Intake & Classification Agent",
        "system_prompt": (
            "You are the Keysight SalesOps Intake & Classification Agent.\n"
            "Classify every incoming customer email by intent (one of: po_intake, "
            "quote_to_order, trade_change_order, hold_release, delivery_change, "
            "ssd_change_request, service_order, wo_update_request, wo_status_inquiry, "
            "service_contract_request, general_inquiry, kso, collections, spam, "
            "out_of_scope) and detect the language. Return strict JSON. Confidence "
            "must be a calibrated probability between 0 and 1."
        ),
        "user_template": "Subject: {subject}\n\nBody:\n{body}\n\nAttachments listed: {attachments}",
        "examples_positive": [],
        "examples_negative": [],
    },
    {
        "key": "extract:system",
        "label": "Extraction & Enrichment · system prompt",
        "description": (
            "System prompt the Extraction agent uses to pull structured fields from "
            "the email + attachments. Prompt-refinement experiments expand this "
            "block when CSR edits show a recurring missed field."
        ),
        "stage": "extract",
        "agent": "Extraction & Enrichment Agent",
        "system_prompt": (
            "You are the Keysight SalesOps Extraction & Enrichment Agent.\n"
            "Pull the standard PO / Quote fields (customer code, asset serial, "
            "quantities, prices, dates) from the email body and attached PDFs. "
            "Return strict JSON. When a field is not present, omit it — never "
            "guess. Preserve original currency and units."
        ),
        "user_template": "Subject: {subject}\n\nBody:\n{body}\n\nAttachments: {attachments_text}",
        "examples_positive": [],
        "examples_negative": [],
    },
    {
        "key": "decide:system",
        "label": "Decision & Confidence Scoring · system prompt",
        "description": (
            "System prompt the Decision agent uses to choose the next action and "
            "score autonomy confidence. Threshold tuning happens in the `threshold` "
            "namespace; this row holds the natural-language framing."
        ),
        "stage": "decide",
        "agent": "Decision & Confidence Scoring Agent",
        "system_prompt": (
            "You are the Keysight SalesOps Decision Agent.\n"
            "Given the classified intent, extracted fields, and reconcile result, "
            "choose the next action and score confidence. L4 (auto) only when "
            "confidence is high AND all hard-blocks pass. L3 (one-click) for "
            "moderate confidence. L2 (HITL) for anything ambiguous, missing-data, "
            "or compliance-flagged."
        ),
        "user_template": "Intent: {intent}\nExtracted: {extracted_json}\nReconcile: {reconcile_json}",
        "examples_positive": [],
        "examples_negative": [],
    },
    {
        "key": "execute:system",
        "label": "Workflow Execution · system prompt",
        "description": "System prompt the Execute agent uses when staging CRM/ERP writes.",
        "stage": "execute",
        "agent": "Workflow Execution Agent",
        "system_prompt": (
            "You are the Keysight SalesOps Workflow Execution Agent (Ring 0).\n"
            "Execute the approved action against the configured systems of record. "
            "Every write is reversible until human approval. Never act when the "
            "decision tier is below L4."
        ),
        "user_template": "Decision: {decision_json}\nCustomer: {customer_json}",
        "examples_positive": [],
        "examples_negative": [],
    },
    {
        "key": "communicate:system",
        "label": "Communication & Close-out · system prompt",
        "description": (
            "System prompt the Communicate agent uses to draft customer replies + "
            "log the close-out summary. Refined when CSR edits cluster around a "
            "specific reply shape."
        ),
        "stage": "communicate",
        "agent": "Communication & Close-out Agent",
        "system_prompt": (
            "You are the Keysight SalesOps Communication & Close-out Agent.\n"
            "Draft a professional reply to the customer using the executed action "
            "and any system-of-record IDs. Preserve the customer's language. Cite "
            "the originating PO / quote / case number explicitly. Keep the reply "
            "under 220 words unless the case requires more."
        ),
        "user_template": "Action taken: {action}\nCustomer: {customer_name}\nReference: {case_number}",
        "examples_positive": [],
        "examples_negative": [],
    },
]


def all_rules() -> list[dict[str, Any]]:
    return list(_BASE)
