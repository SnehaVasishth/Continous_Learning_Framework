"""Stage 2 — Data Extraction & Enrichment (v2 design, 4 sub-steps).

Per ADR-011 in SOLUTION.md:

  2.1  Document extraction (full OCR)        — Azure Doc Intelligence per attachment, NO page cap
  2.2  Schema-driven extraction              — OpenAI gpt-5.2, KB extract_schema for the intent
  2.3  Customer identification (Salesforce)  — SF Account match using extracted JSON
  2.4  Customer enrichment (intent-aware)    — SOQL queries varying by intent + SF/SP file pull

Stage 1 owns "what is this email." Stage 2 owns "what data do we have / need
about this customer." Stage 3 owns "decide what to do."
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..models import Pipeline
from ..trace_log import log_event
from .base import AgentContext, AgentResult, BaseAgent
from .salesforce_lookup import fetch_account_history
from .tools.azure_doc_intelligence_tool import AzureDocIntelligenceTool
from .tools.claude_vision_tool import ClaudeVisionTool
from .tools.entity_resolve_tool import EntityResolveTool
from .tools.read_tool import ReadTool
from .tools.salesforce_files_tool import SalesforceFilesTool
from .tools.salesforce_query_tool import SalesforceQueryTool
from .tools.schema_extract_tool import SchemaExtractTool
from .tools.sharepoint_fetch_doc_tool import SharePointFetchDocTool


_OCR_TYPES = {"pdf", "docx", "xlsx", "xls", "doc"}
_VISION_TYPES = {"image", "png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp", "webp"}
_TEXT_TYPES = {"text", "txt", "csv", "json", "html", "htm"}


def _attachment_kind(attachment: dict) -> str:
    raw = (attachment.get("type") or "").lower()
    if raw:
        if raw in _OCR_TYPES:
            return "ocr"
        if raw in _VISION_TYPES:
            return "vision"
        if raw in _TEXT_TYPES:
            return "text"
    name = attachment.get("name") or attachment.get("path") or ""
    ext = Path(name).suffix.lower().lstrip(".")
    if ext in _OCR_TYPES:
        return "ocr"
    if ext in _VISION_TYPES:
        return "vision"
    if ext in _TEXT_TYPES:
        return "text"
    return "unknown"


# Reusable SOQL fragments — keep one source of truth per object so the Trace UI
# always sees the same column shape regardless of which intent kicked it off.
_Q_RECENT_ORDERS = "SELECT Id, OrderNumber, Status, EffectiveDate, TotalAmount, PoNumber FROM Order WHERE AccountId = '{account_id}' ORDER BY EffectiveDate DESC NULLS LAST LIMIT 10"
_Q_RECENT_OPPS = "SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity WHERE AccountId = '{account_id}' ORDER BY CloseDate DESC NULLS LAST LIMIT 10"
_Q_CONTACTS = "SELECT Id, Name, Email, Title, Phone FROM Contact WHERE AccountId = '{account_id}' ORDER BY LastModifiedDate DESC NULLS LAST LIMIT 10"
_Q_RECENT_CASES = "SELECT Id, CaseNumber, Subject, Status, Priority, CreatedDate FROM Case WHERE AccountId = '{account_id}' ORDER BY CreatedDate DESC NULLS LAST LIMIT 5"
_Q_QUOTES = "SELECT Id, QuoteNumber, Name, Status, ExpirationDate, GrandTotal, Customer_Code__c, Sales_Rep__c, Document_Url__c FROM Quote WHERE AccountId = '{account_id}' ORDER BY LastModifiedDate DESC NULLS LAST LIMIT 10"
_Q_QUOTE_LINES = "SELECT Id, QuoteId, Quote.Name, Product2Id, Product2.ProductCode, Product2.Name, Quantity, UnitPrice, TotalPrice FROM QuoteLineItem WHERE Quote.AccountId = '{account_id}' ORDER BY CreatedDate DESC NULLS LAST LIMIT 50"
_Q_INSTALLED_BASE = "SELECT Id, Name, SerialNumber, Status, InstallDate, Product2Id, Product2.ProductCode, Last_Cal_Date__c, Calibration_Due_Date__c, Cal_Cert_Url__c, Document_Url__c, Asset_Location__c FROM Asset WHERE AccountId = '{account_id}' ORDER BY InstallDate DESC NULLS LAST LIMIT 25"
_Q_WORK_ORDERS = "SELECT Id, WorkOrderNumber, Subject, Status, Priority, StartDate, EndDate, AssetId, WO_Number__c, Asset_Serial__c, Asset_SKU__c, Type__c, Region__c, Technician__c, Cert_Number__c, Document_Url__c FROM WorkOrder WHERE AccountId = '{account_id}' ORDER BY CreatedDate DESC NULLS LAST LIMIT 15"
_Q_SERVICE_CONTRACTS = "SELECT Id, Name, Status, StartDate, EndDate, Term, Contract_Number__c, Coverage_Type__c, SLA_Response_Hours__c, SLA_Resolution_Hours__c, Annual_Value_USD__c, Document_Url__c FROM ServiceContract WHERE AccountId = '{account_id}' ORDER BY StartDate DESC NULLS LAST LIMIT 10"


# Maps each intent to the Salesforce SOQL queries that should be run during enrichment.
# Each entry is (label, soql_template) — the template uses {account_id} as the placeholder.
_ENRICHMENT_QUERIES: dict[str, list[tuple[str, str]]] = {
    "po_intake": [
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_opportunities", _Q_RECENT_OPPS),
        ("contacts", _Q_CONTACTS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "quote_to_order": [
        ("recent_quotes", _Q_QUOTES),
        ("quote_line_items", _Q_QUOTE_LINES),
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_opportunities", _Q_RECENT_OPPS),
        ("contacts", _Q_CONTACTS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "trade_change_order": [
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "ssd_change_request": [
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "delivery_change": [
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "hold_release": [
        # On-hold orders. This SF org's Order.Status picklist only carries
        # Draft / Activated, so we encode the hold state by tagging
        # OrderReferenceNumber with a "HOLD-<reason>" prefix and filter on
        # that string field. The Description carries the human-readable
        # hold reason for the LLM to quote in the customer reply. A
        # production tenant with a custom Status value or Hold__c flag
        # would swap the WHERE clause accordingly.
        ("orders_on_hold", "SELECT Id, OrderNumber, Status, EffectiveDate, EndDate, TotalAmount, PoNumber, OrderReferenceNumber, Description FROM Order WHERE AccountId = '{account_id}' AND OrderReferenceNumber LIKE 'HOLD-%' ORDER BY EffectiveDate DESC NULLS LAST LIMIT 10"),
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "service_order": [
        ("installed_base", _Q_INSTALLED_BASE),
        ("active_service_contracts", _Q_SERVICE_CONTRACTS),
        ("recent_work_orders", _Q_WORK_ORDERS),
        ("contacts", _Q_CONTACTS),
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "wo_update_request": [
        ("recent_work_orders", _Q_WORK_ORDERS),
        ("installed_base", _Q_INSTALLED_BASE),
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "wo_status_inquiry": [
        ("recent_work_orders", _Q_WORK_ORDERS),
        ("installed_base", _Q_INSTALLED_BASE),
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "service_contract_request": [
        ("active_service_contracts", _Q_SERVICE_CONTRACTS),
        ("installed_base", _Q_INSTALLED_BASE),
        ("recent_opportunities", _Q_RECENT_OPPS),
        ("contacts", _Q_CONTACTS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
    "general_inquiry": [
        ("contacts", _Q_CONTACTS),
        ("recent_orders", _Q_RECENT_ORDERS),
        ("recent_cases", _Q_RECENT_CASES),
    ],
}

# Default queries when an intent isn't explicitly mapped above.
_DEFAULT_ENRICHMENT_QUERIES: list[tuple[str, str]] = [
    ("recent_orders", _Q_RECENT_ORDERS),
    ("recent_opportunities", _Q_RECENT_OPPS),
    ("recent_cases", _Q_RECENT_CASES),
]


class Stage2ExtractAgent(BaseAgent):
    """Stage 2: 4-substep flow — OCR → schema extract → customer ID → enrichment."""

    stage_key = "extract"
    # Stage labels are canonical in analytics.subprocess_taxonomy.STAGE_META.
    # Keep this in sync so the trace UI, governance, and analytics views all
    # show the same agent name.
    stage_label = "Extraction & Enrichment"
    tools = [
        ReadTool(),
        AzureDocIntelligenceTool(),
        ClaudeVisionTool(),
        SalesforceFilesTool(),
        SharePointFetchDocTool(),
        SchemaExtractTool(),
        EntityResolveTool(),
        SalesforceQueryTool(),
    ]

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        tool_results: list[Any] = []
        guardrails: list[str] = []
        try:
            # ------------------------------------------------------------------
            # 2.1  Document extraction (full OCR — no page cap)
            # ------------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_start",
                "2.1 Document extraction — full OCR via Azure Document Intelligence (no page cap)",
                data={"substep": "2.1", "label": "Document extraction"},
            )
            attachment_text_parts: list[str] = []
            attachments = list((ctx.email or {}).get("attachments") or [])
            for att in attachments:
                kind = _attachment_kind(att)
                name = att.get("name") or att.get("path") or "<unnamed>"
                if kind == "ocr":
                    res = self.invoke_tool(
                        ctx, "azure_doc_intelligence",
                        name=att.get("path") or name,
                    )
                    tool_results.append(res)
                    if res.ok:
                        text = res.data.get("text") or ""
                        if text:
                            attachment_text_parts.append(f"--- {name} (full OCR) ---\n{text}")
                elif kind == "vision":
                    res = self.invoke_tool(ctx, "vision_ocr", image_paths=[att.get("path") or name])
                    tool_results.append(res)
                    if res.ok:
                        text = res.data.get("text") or ""
                        if text:
                            attachment_text_parts.append(f"--- {name} (image OCR) ---\n{text}")
                elif kind == "text":
                    res = self.invoke_tool(ctx, "read_attachment", name=att.get("path") or name)
                    tool_results.append(res)
                    if res.ok:
                        text = res.data.get("content") or ""
                        if text:
                            attachment_text_parts.append(f"--- {name} (text) ---\n{text}")
                else:
                    guardrails.append(f"unknown_attachment_type: {name}")

            attachment_text = "\n\n".join(attachment_text_parts)
            ctx.intake["attachment_text_full"] = attachment_text
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_done",
                f"2.1 Document extraction done — {len(attachments)} attachment(s), {len(attachment_text)} chars total",
                data={
                    "substep": "2.1",
                    "attachments_count": len(attachments),
                    "total_chars": len(attachment_text),
                },
            )

            # ------------------------------------------------------------------
            # 2.2  Schema-driven extraction (OpenAI gpt-5.2 + KB extract_schema)
            # ------------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_start",
                f"2.2 Schema-driven extraction — using KB extract_schema for intent='{ctx.intake.get('intent')}'",
                data={
                    "substep": "2.2",
                    "label": "Schema-driven extraction",
                    "intent": ctx.intake.get("intent"),
                },
            )
            extract_res = self.invoke_tool(ctx, "schema_extract", email=ctx.email, intake=ctx.intake)
            tool_results.append(extract_res)
            if extract_res.ok:
                ctx.extracted = {k: v for k, v in extract_res.data.items() if not k.startswith("_") and k not in (
                    "provider", "provider_meta", "prompt_system", "prompt_user", "provider_response_raw",
                    "kb_namespaces_consulted", "kb_schema_key_used", "kb_schema_intent",
                    "kb_schema_field_count", "kb_schema_required_count", "kb_schema_required_populated",
                    "kb_schema_fields", "extracted_fields", "validation_notes",
                    "input_preview", "input_chars", "output_summary", "processing_method",
                )}
                ctx.extracted["_intent"] = ctx.intake.get("intent")
            else:
                ctx.extracted = {"_extract_error": extract_res.error}
                guardrails.append(f"schema_extract_failed: {extract_res.error}")
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_done",
                f"2.2 Schema-driven extraction done — {len(ctx.extracted)} fields",
                data={
                    "substep": "2.2",
                    "fields_extracted": [k for k in ctx.extracted.keys() if not k.startswith("_")],
                    "provider": (extract_res.data or {}).get("provider") if extract_res.ok else None,
                },
            )

            # ------------------------------------------------------------------
            # 2.3  Customer identification — Salesforce Account match
            # ------------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_start",
                "2.3 Customer identification — matching to Salesforce Account using extracted fields + email sender",
                data={"substep": "2.3", "label": "Customer identification"},
            )
            resolve_res = self.invoke_tool(
                ctx, "entity_resolve_customer", email=ctx.email, extracted=ctx.extracted,
            )
            tool_results.append(resolve_res)

            sf_match_failed = False
            sf_match_reason: str | None = None

            if not resolve_res.ok:
                # Hard fail (e.g. salesforce_not_configured).
                sf_match_failed = True
                sf_match_reason = resolve_res.error or "salesforce_lookup_failed"
                ctx.customer_match = {
                    "salesforce_account_id": None,
                    "customer_code": None,
                    "customer_name": None,
                    "score": 0.0,
                    "basis": (resolve_res.data or {}).get("basis", "salesforce_error"),
                    "source": "none",
                    "error": sf_match_reason,
                    "attempted_lookups": (resolve_res.data or {}).get("attempted_lookups", []),
                }
                guardrails.append(f"sf_match_failed: {sf_match_reason}")
            else:
                ctx.customer_match = dict(resolve_res.data)
                if ctx.customer_match.get("salesforce_account_id"):
                    sf_account = (resolve_res.data or {}).get("account") or {}
                    if sf_account:
                        ctx.customer_match.setdefault("salesforce", {})["account"] = sf_account
                        log_event(
                            ctx.db, ctx.pipeline_id, "extract", "salesforce_account_fetched",
                            f"Salesforce Account fetched live: {sf_account.get('Name')} (Id={sf_account.get('Id')}) via {ctx.customer_match.get('basis')}",
                            data={
                                "substep": "2.3",
                                "salesforce_account_id": sf_account.get("Id"),
                                "name": sf_account.get("Name"),
                                "customer_code": sf_account.get("Customer_Code__c"),
                                "region": sf_account.get("Region__c"),
                                "vertical": sf_account.get("Vertical__c"),
                                "sla_tier": sf_account.get("SLA_Tier__c"),
                                "compliance_flags": sf_account.get("Compliance_Flags__c"),
                                "matched_via": ctx.customer_match.get("basis"),
                            },
                        )
                else:
                    sf_match_failed = True
                    sf_match_reason = "no_salesforce_match"
                    guardrails.append(
                        "sf_match_no_hit: extracted customer is not in Salesforce — "
                        "tag the account in SF or review by hand"
                    )

            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_done",
                (
                    f"2.3 Customer identification done — "
                    f"matched={ctx.customer_match.get('customer_name') or '(none)'} "
                    f"score={ctx.customer_match.get('score', 0):.2f} "
                    f"basis={ctx.customer_match.get('basis')}"
                ),
                data={
                    "substep": "2.3",
                    "customer_name": ctx.customer_match.get("customer_name"),
                    "customer_code": ctx.customer_match.get("customer_code"),
                    "score": ctx.customer_match.get("score"),
                    "basis": ctx.customer_match.get("basis"),
                    "source": ctx.customer_match.get("source"),
                    "salesforce_account_id": ctx.customer_match.get("salesforce_account_id"),
                    "attempted_lookups": ctx.customer_match.get("attempted_lookups", []),
                    "error": ctx.customer_match.get("error"),
                },
            )

            if sf_match_failed:
                # CMD activation — when the inbound customer is not yet in
                # Salesforce, trigger the standard Keysight CMD (Customer Master
                # Data) activation request, matching the AS-IS pattern. The
                # event is surfaced on the Activity / Trace view and on the
                # HITL queue so the CSR can confirm the CMD request was sent
                # and resume the pipeline once the account is provisioned.
                if sf_match_reason == "no_salesforce_match":
                    extracted_customer_name = (
                        (ctx.extracted or {}).get("customer_name")
                        or (ctx.email or {}).get("sender_name")
                        or "(unknown)"
                    )
                    cmd_payload = {
                        "requested_customer_name": extracted_customer_name,
                        "sender_email": (ctx.email or {}).get("sender_email"),
                        "intent": ctx.intake.get("intent"),
                        "extracted_addresses": {
                            "bill_to": (ctx.extracted or {}).get("bill_to"),
                            "ship_to": (ctx.extracted or {}).get("ship_to"),
                        },
                        "attempted_lookups": ctx.customer_match.get("attempted_lookups", []),
                        "request_id": f"CMD-{ctx.pipeline_id:08d}",
                        "status": "requested",
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "extract", "cmd_activation_requested",
                        (
                            f"CMD activation request triggered — '{extracted_customer_name}' not found "
                            f"in Salesforce, request_id={cmd_payload['request_id']}"
                        ),
                        data={
                            "substep": "2.3.1",
                            "cmd_activation": cmd_payload,
                        },
                    )
                    guardrails.append(f"cmd_activation_requested:{cmd_payload['request_id']}")
                # Stop here — sub-step 2.4 enrichment requires a Salesforce account.
                # Surface the failure as a guardrail so the orchestrator routes
                # this pipeline to HITL with a clear "unknown customer" reason.
                self._persist(ctx)
                log_event(
                    ctx.db, ctx.pipeline_id, "extract", "stage_blocked",
                    (
                        f"Stage 2 blocked: {sf_match_reason}. Skipping 2.4 enrichment. "
                        "Pipeline routed to HITL — a human needs to identify the customer "
                        "in Salesforce before automation can continue."
                    ),
                    data={
                        "reason": sf_match_reason,
                        "extracted": ctx.extracted,
                        "customer_match": ctx.customer_match,
                    },
                )
                output = {
                    "extracted": ctx.extracted,
                    "customer_match": ctx.customer_match,
                    "attachment_chars": len(attachment_text),
                    "_sf_match_failed": True,
                    "_sf_match_reason": sf_match_reason,
                }
                return AgentResult(
                    stage=self.stage_key,
                    output=output,
                    tool_results=tool_results,
                    guardrails_fired=guardrails,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            # ------------------------------------------------------------------
            # 2.4  Customer enrichment — intent-aware Salesforce queries
            # ------------------------------------------------------------------
            intent = ctx.intake.get("intent") or "general_inquiry"
            queries = _ENRICHMENT_QUERIES.get(intent, _DEFAULT_ENRICHMENT_QUERIES)
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_start",
                f"2.4 Customer enrichment — running {len(queries)} intent-aware SOQL queries for intent='{intent}'",
                data={
                    "substep": "2.4",
                    "label": "Customer enrichment",
                    "intent": intent,
                    "query_labels": [q[0] for q in queries],
                },
            )
            sf_account_id = ctx.customer_match.get("salesforce_account_id")
            if sf_account_id:
                sf_block = ctx.customer_match.get("salesforce") or {}
                escaped = str(sf_account_id).replace("'", "\\'")
                for label, template in queries:
                    soql = template.replace("{account_id}", escaped)
                    sf_res = self.invoke_tool(ctx, "salesforce_soql", soql=soql, label=label)
                    tool_results.append(sf_res)
                    if sf_res.ok:
                        sf_block[label] = sf_res.data.get("records") or []
                    else:
                        # Soft-skip: feature-not-enabled (e.g., FSL/Quotes off in this org)
                        # logs a guardrail but keeps the rest of the enrichment running.
                        guardrails.append(f"sf_query_failed[{label}]: {sf_res.error}")

                # Collect every record Id surfaced by enrichment so the Files
                # tool can pull ContentDocumentLink rows across all of them
                # (Account + Order + WO + Asset + Quote + ServiceContract).
                parent_ids: list[str] = [sf_account_id]
                for label, rows in sf_block.items():
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if isinstance(row, dict) and row.get("Id"):
                            parent_ids.append(row["Id"])
                files_res = self.invoke_tool(ctx, "salesforce_fetch_files", parent_ids=parent_ids)
                tool_results.append(files_res)
                if files_res.ok:
                    sf_block["attached_files"] = files_res.data.get("fetched") or []

                ctx.customer_match["salesforce"] = sf_block

                # Optional: SharePoint pull when we have the customer code.
                if ctx.customer_match.get("customer_code"):
                    sp_res = self.invoke_tool(
                        ctx, "sharepoint_fetch_doc",
                        query=ctx.customer_match["customer_code"],
                    )
                    tool_results.append(sp_res)
                    if sp_res.ok:
                        sf_block["sharepoint_files"] = sp_res.data.get("fetched") or []
                        ctx.customer_match["salesforce"] = sf_block

                # Best-effort: pull account history if a helper is exposed (mirrors the old orchestrator path).
                try:
                    history_sf = fetch_account_history(sf_account_id)
                    if history_sf:
                        sf_block["history_summary"] = history_sf
                        ctx.customer_match["salesforce"] = sf_block
                except Exception:
                    pass
            else:
                guardrails.append("enrichment_skipped: no salesforce_account_id")
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_done",
                f"2.4 Customer enrichment done — {sum(1 for _ in queries) if sf_account_id else 0} SOQL query(ies) executed",
                data={
                    "substep": "2.4",
                    "enrichment_keys": list((ctx.customer_match.get("salesforce") or {}).keys()),
                },
            )

            # ------------------------------------------------------------------
            # 2.5  Cross-system validation — reconcile_checks vs matched quote
            # ------------------------------------------------------------------
            intent_for_reconcile = ctx.intake.get("intent") or ""
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_start",
                "2.5 Cross-system validation — running reconcile_checks against the matched quote and account",
                data={
                    "substep": "2.5",
                    "label": "Cross-system validation",
                    "kb_namespace": "reconcile_checks",
                    "intent": intent_for_reconcile,
                },
            )
            from .reconcile import reconcile
            recon = reconcile(
                ctx.db,
                intent=intent_for_reconcile,
                extracted=ctx.extracted,
                customer_id=ctx.customer_id,
                customer_match=ctx.customer_match,
            )
            ctx.reconcile = recon
            checks_evaluated = recon.get("checks_evaluated") or []
            recon_issues = recon.get("issues") or []
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_done",
                (
                    f"2.5 Cross-system validation done — {len(recon_issues)} issue(s) "
                    f"across {len(checks_evaluated)} check(s)"
                ),
                data={
                    "substep": "2.5",
                    "kb_namespace": "reconcile_checks",
                    "checks_evaluated_count": len(checks_evaluated),
                    "issues_count": len(recon_issues),
                    "matched_quote": recon.get("matched_quote"),
                    "checked": recon.get("checked", False),
                    "notes": recon.get("notes") or [],
                },
            )

            # ------------------------------------------------------------------
            # 2.6  FCNV Review gate (per RFP use-case diagrams)
            # ------------------------------------------------------------------
            # Most happy paths in the RFP diagrams pass through a "Human in
            # Loop FCNV Review (optional)" step that fallouts to "FCNV Scope"
            # when classification or enrichment is too thin to proceed. We
            # mirror that gate here: if the case is FCNV-gated and either
            # (a) extraction confidence is low, or (b) required parties are
            # missing, we mark fcnv_review_required=True and emit the FCNV
            # Scope fallout label so Stage 3 owner assignment routes the
            # case to the FCNV queue.
            from .track_classifier import (
                classify_tracks,
                FCNV_GATED_INTENTS,
            )
            intent_now = (ctx.intake or {}).get("intent") or ""
            extracted_now = ctx.extracted or {}
            match_now = ctx.customer_match or {}
            cust_score = float(match_now.get("score") or 0.0)
            line_items_now = extracted_now.get("line_items") or []
            if not isinstance(line_items_now, list):
                line_items_now = []
            missing_parties: list[str] = []
            if not match_now.get("salesforce_account_id") and not match_now.get("customer_code"):
                missing_parties.append("customer_account")
            if intent_now in {"po_intake", "quote_to_order", "trade_change_order"}:
                if not extracted_now.get("po_number"):
                    missing_parties.append("po_number")
                if not line_items_now:
                    missing_parties.append("line_items")
            if intent_now == "service_order":
                if not (extracted_now.get("add_assets") or extracted_now.get("assets")):
                    missing_parties.append("assets")
            if intent_now in {"wo_update_request", "wo_status_inquiry"}:
                if not (extracted_now.get("work_order_number") or extracted_now.get("wo_number")):
                    missing_parties.append("work_order_number")
            fcnv_review_required = (
                intent_now in FCNV_GATED_INTENTS
                and (bool(missing_parties) or cust_score < 0.5)
            )
            fcnv_fallout_label = "fcnv_scope" if fcnv_review_required else None
            tracks_block = classify_tracks(
                intent=intent_now,
                fcnv_review_required=fcnv_review_required,
                aioa_outcome=None,  # AIOA runs in Stage 3; refreshed there
            )
            log_event(
                ctx.db, ctx.pipeline_id, "extract", "substep_done",
                (
                    f"2.6 FCNV review gate — {'fallout to FCNV Scope' if fcnv_review_required else 'pass (no FCNV review needed)'}"
                    + (f" · missing: {', '.join(missing_parties)}" if missing_parties else "")
                ),
                data={
                    "substep": "2.6",
                    "label": "FCNV review gate",
                    "fcnv_review_required": fcnv_review_required,
                    "fallout_label": fcnv_fallout_label,
                    "missing_parties": missing_parties,
                    "customer_match_score": cust_score,
                    "primary_track": tracks_block.get("primary_track"),
                    "secondary_tracks": tracks_block.get("secondary_tracks"),
                    "all_tracks_touched": tracks_block.get("all_tracks_touched"),
                },
            )
            # Persist on the intake block so Stage 3 / 4 / orchestrator pick up
            ctx.intake["track"] = tracks_block.get("primary_track")
            ctx.intake["tracks_touched"] = tracks_block.get("all_tracks_touched") or []
            ctx.intake["fcnv_review_required"] = fcnv_review_required
            ctx.intake["fcnv_missing_parties"] = missing_parties
            if fcnv_fallout_label:
                ctx.intake["fcnv_fallout_label"] = fcnv_fallout_label

            self._persist(ctx)
            output = {
                "extracted": ctx.extracted,
                "customer_match": ctx.customer_match,
                "attachment_chars": len(attachment_text),
                "reconcile": recon,
                "track": tracks_block.get("primary_track"),
                "fcnv_review_required": fcnv_review_required,
                "fcnv_missing_parties": missing_parties,
            }
            return AgentResult(
                stage=self.stage_key,
                output=output,
                tool_results=tool_results,
                guardrails_fired=guardrails,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:
            return AgentResult(
                stage=self.stage_key,
                output={},
                tool_results=tool_results,
                guardrails_fired=[*guardrails, f"stage_error: {type(e).__name__}: {str(e)[:300]}"],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _persist(self, ctx: AgentContext) -> None:
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        pipe.extracted = ctx.extracted
        pipe.customer_match = ctx.customer_match
        if ctx.reconcile:
            pipe.reconcile = ctx.reconcile
        ctx.db.commit()
