"""Mock for the Keysight AIOA (AI Order Acceptance) webhook integration.

AIOA is a separate AI application owned by Keysight. ZBrain does NOT run the
validation or downstream order acceptance work itself for these flows — when
the trigger conditions match, ZBrain fires a webhook into AIOA with the
extracted PO context. AIOA owns:

  - the operational rule book validation
  - the AIOA Pass → STATUS=Assigned, STAGE=Automation Complete (downstream
    fulfilment proceeds inside AIOA)
  - the AIOA Fail → STATUS=Assigned, STAGE=Review Required (the case appears
    in Keysight's AI OA Fallout queue for the CSR to action)

This module simulates the webhook handoff locally so the demo can show the
full handoff round-trip without a network dependency. The real production
deployment replaces `trigger_aioa_webhook()` with a thin HTTP POST to the
Keysight AIOA endpoint and surfaces AIOA's asynchronous callback in the same
shape returned here.

Trigger conditions (applied in stage3_decide_agent):
  - intent in {po_intake, quote_to_order, trade_change_order, wo_update_request,
               service_contract_request}
  - extracted has a po_number AND line_items (the AIOA pattern applies only
    when there is actual PO data for AIOA to validate)
"""
from __future__ import annotations

import hashlib
import os
import random
import time
from typing import Any


AIOA_TRIGGER_INTENTS: set[str] = {
    "po_intake",
    "quote_to_order",
    "trade_change_order",
    "wo_update_request",
    "service_contract_request",
}


# The configured webhook endpoint. In production this points at Keysight's
# AIOA receiver. In the demo it's a placeholder shown in the trace so the
# reviewer can see exactly what URL would have been POSTed to.
AIOA_WEBHOOK_URL = os.environ.get(
    "AIOA_WEBHOOK_URL",
    "https://aioa.keysight.local/api/v1/order-acceptance/inbound",
)


# Check categories AIOA runs against the inbound PO. Mirrors the operational
# rule book Keysight applies in production. The list is informational — AIOA
# (not ZBrain) executes these checks.
AIOA_CHECKS: tuple[tuple[str, str], ...] = (
    ("schema_completeness", "All AIOA-required PO fields populated and within expected type/format"),
    ("price_consistency", "Unit prices on the PO match the active quote within the negotiated tolerance"),
    ("quantity_consistency", "Quantities on the PO match the quote or are explicitly approved as a delta"),
    ("sku_validity", "Every line-item SKU resolves to an active product in the Keysight catalog"),
    ("export_compliance", "Destination country and end-user pass the export control screen"),
    ("payment_terms_match", "Customer-stated payment terms match the account master record"),
    ("customer_credit", "Customer account is in good standing (no open invoice / credit hold)"),
    ("partial_or_full_po_detection", "PO data covers all line items (no missing-line indication detected)"),
    ("authorised_signatory", "PO signed or issued by an authorised contact on file for the account"),
    ("compliance_flags", "No ITAR, ECCN, DFARS, or country-specific compliance flags raised"),
)


def should_call_aioa(*, intent: str, extracted: dict, email_attachments: list | None = None) -> tuple[bool, str]:
    """Return (yes_fire_webhook, reason) for whether the AIOA handoff applies.

    The pattern fires when the intent is AIOA-eligible and there is PO context.
    PO context is either (a) extracted.po_number with line_items, or (b) an
    attachment of kind=purchase_order on the inbound email (the LLM may have
    missed the PO# in body extraction but the operator-visible PO is still
    attached). The webhook payload uses whichever is available.
    """
    if intent not in AIOA_TRIGGER_INTENTS:
        return False, f"AIOA pattern not applicable to intent '{intent}'"
    po_number = (extracted or {}).get("po_number")
    line_items = (extracted or {}).get("line_items") or []
    has_extracted_po = bool(po_number) and isinstance(line_items, list) and bool(line_items)
    has_po_attachment = bool(email_attachments) and any(
        (isinstance(a, dict) and (a.get("kind") == "purchase_order" or "po" in (a.get("name") or "").lower()))
        for a in (email_attachments or [])
    )
    if has_extracted_po:
        return True, "AIOA pattern applies (intent + extracted PO data present)"
    if has_po_attachment:
        return True, "AIOA pattern applies (intent + PO attachment present even if extraction missed po_number)"
    return False, "AIOA pattern needs a PO (extracted po_number+line_items or PO attachment); none present"


def build_aioa_request(
    *,
    pipeline_id: int,
    intent: str,
    customer_code: str | None,
    extracted: dict,
    reconcile_result: dict | None,
) -> dict[str, Any]:
    """Assemble the webhook payload posted to the external AIOA app.

    Mirrors what the Keysight AIOA endpoint expects: stable case identifiers,
    the resolved customer reference, the extracted PO header and line items,
    and any reconcile findings ZBrain already produced so AIOA can layer its
    own checks on top before deciding Pass / Fail."""
    return {
        "case_ref": f"ZBR-{pipeline_id:08d}",
        "intent": intent,
        "customer_code": customer_code or None,
        "po": {
            "po_number": extracted.get("po_number"),
            "quote_number": extracted.get("quote_number"),
            "customer_po": extracted.get("customer_po"),
            "payment_terms": extracted.get("payment_terms"),
            "ship_to": extracted.get("ship_to"),
            "bill_to": extracted.get("bill_to"),
            "requested_ship_date": extracted.get("requested_ship_date"),
            "total": extracted.get("total"),
            "currency": extracted.get("currency"),
            "line_items": extracted.get("line_items") or [],
        },
        "wo": {
            "work_order_number": extracted.get("work_order_number"),
            "order_number": extracted.get("order_number"),
            "add_assets": extracted.get("add_assets") or [],
        },
        "reconcile_findings": (reconcile_result or {}).get("findings") or [],
        "checks_requested": [code for code, _ in AIOA_CHECKS],
        "callback": {
            "mode": "async_webhook",
            "url": "https://zbrain.keysight.local/api/aioa/callback",
            "secret_header": "X-AIOA-Signature",
        },
    }


def trigger_aioa_webhook(request_payload: dict[str, Any]) -> dict[str, Any]:
    """Simulate firing the webhook into AIOA.

    Real production: HTTP POST to AIOA_WEBHOOK_URL, then AIOA processes the
    payload and calls back ZBrain with Pass / Fail + per-check findings. The
    mock telescopes the round-trip into a single deterministic function so the
    demo can show the full handoff in one trace event.

    Returns the AIOA decision envelope. ZBrain does NOT execute these checks;
    AIOA does. Pass/Fail is deterministic per case_ref + po_number so reruns
    are stable. The decision is driven by:
      - Missing fields in the PO header (caps result at Fail)
      - Empty line items (caps result at Fail)
      - Reconcile findings of severity 'blocking' (caps result at Fail)
      - A small randomised compliance/credit risk that flips ~12% to Fail
        even when fields are clean (so the demo also shows the AI OA Fallout
        queue path on otherwise-valid inbound POs)
    """
    start = time.perf_counter()
    po = request_payload.get("po") or {}
    case_ref = request_payload.get("case_ref") or "ZBR-UNKNOWN"

    # Deterministic randomness from case_ref so reruns are stable.
    seed_material = f"{case_ref}|{po.get('po_number')}"
    rng = random.Random(int(hashlib.sha256(seed_material.encode()).hexdigest(), 16) % (2**32))

    findings: list[dict[str, Any]] = []
    missing = [k for k in ("po_number", "total", "line_items") if not po.get(k)]
    if missing:
        findings.append({
            "check": "schema_completeness",
            "result": "fail",
            "detail": f"Missing required PO header field(s): {', '.join(missing)}",
        })
    else:
        findings.append({"check": "schema_completeness", "result": "pass", "detail": "All required PO header fields present"})

    li = po.get("line_items") or []
    if not isinstance(li, list) or not li:
        findings.append({"check": "quantity_consistency", "result": "fail", "detail": "No line items on PO; cannot validate quantities"})
    else:
        findings.append({"check": "quantity_consistency", "result": "pass", "detail": f"{len(li)} line item(s) present, quantities within tolerance"})

    magic_skus = {"CUSTOM-PRODUCT", "SOWDUMMY", "EXPORTDUMMY"}
    magic_present = [item.get("sku") for item in li if isinstance(item, dict) and item.get("sku") in magic_skus]
    if magic_present:
        findings.append({
            "check": "sku_validity",
            "result": "warn",
            "detail": f"Magic SKU(s) detected on the PO: {', '.join(magic_present)} — special routing applies",
        })
    else:
        findings.append({"check": "sku_validity", "result": "pass", "detail": "All line-item SKUs resolved against active catalog"})

    rec_findings = request_payload.get("reconcile_findings") or []
    blocking = [f for f in rec_findings if (isinstance(f, dict) and f.get("severity") == "blocking")]
    if blocking:
        findings.append({
            "check": "price_consistency",
            "result": "fail",
            "detail": f"ZBrain reconcile raised {len(blocking)} blocking finding(s); AIOA confirms PO does not match the source quote",
        })
    else:
        findings.append({"check": "price_consistency", "result": "pass", "detail": "PO prices match the resolved quote within tolerance"})

    risk_roll = rng.random()
    if risk_roll < 0.07:
        findings.append({
            "check": "export_compliance",
            "result": "fail",
            "detail": "Destination country requires additional export-control review (ECCN 3A002.f, BIS license check pending)",
        })
    elif risk_roll < 0.12:
        findings.append({
            "check": "customer_credit",
            "result": "fail",
            "detail": "Customer has an open invoice exceeding 90 days; finance hold pending Treasury review",
        })
    else:
        findings.append({"check": "export_compliance", "result": "pass", "detail": "No export-control flags raised"})
        findings.append({"check": "customer_credit", "result": "pass", "detail": "Customer account in good standing"})

    any_fail = any(f["result"] == "fail" for f in findings)
    outcome = "AIOA_FAIL" if any_fail else "AIOA_PASS"
    fallout_reason = None
    if any_fail:
        first_fail = next(f for f in findings if f["result"] == "fail")
        fallout_reason = f"{first_fail['check']}: {first_fail['detail']}"

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "request_id": f"AIOA-{hashlib.sha1(seed_material.encode()).hexdigest()[:12].upper()}",
        "outcome": outcome,
        "case_ref": case_ref,
        "po_number": po.get("po_number"),
        "findings": findings,
        "fallout_reason": fallout_reason,
        "elapsed_ms": elapsed_ms,
        "version": "aioa-mock-1.0",
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "webhook_url": AIOA_WEBHOOK_URL,
        "handoff_mode": "webhook",
        "owned_by": "AIOA (external Keysight app)",
        "downstream_action": (
            "AIOA proceeds with order acceptance and Oracle EBS write"
            if outcome == "AIOA_PASS"
            else "AIOA routes case to AI OA Fallout queue for CSR review"
        ),
    }


# Backwards-compat: older code paths still call `call_aioa`. Route through
# the new webhook semantics so all callers get the new envelope.
def call_aioa(request_payload: dict[str, Any]) -> dict[str, Any]:
    return trigger_aioa_webhook(request_payload)
