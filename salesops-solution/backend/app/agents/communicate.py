"""Stage 5 — Customer Communication.

Drafts a reply in the customer's language. For any PO-bearing case we also
generate a synthetic Sales Order Acknowledgment (SOA) PDF using the enterprise
template shared with PO/Invoice/WO/Cal-Cert documents and surface it as an
attachment on the outbound draft so the CSR (or the L4 autosend) can hand it
off to the customer. SharePoint is the active document store; DocuNet is an
upcoming integration enabled from Settings → Integrations.

This function never raises — every failure path returns a deterministic
fallback draft so the case always lands in HITL with a usable starting point.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import OUTPUTS
from ..synthetic.attachments import make_soa_pdf
from .llm import ask_llm


log = logging.getLogger(__name__)


SYSTEM = (
    "You are a customer-communication agent for Keysight SalesOps. "
    "Draft a short, professional reply addressing the customer's request. "
    "Match the customer's language (en, es, or ja). "
    "Return strict JSON: {\"language\": str, \"subject\": str, \"body\": str (multi-line)}. "
    "AUDIENCE RULE: this reply is the final outbound message the customer will receive once "
    "internal approvals are complete. Write it as if the action has been taken, e.g. "
    "'we have released the credit hold on Order X', 'your order has been acknowledged'. "
    "DO NOT mention internal staging states such as 'pending one-click approval', 'awaiting "
    "review', 'staged for CSR confirm', 'currently pending in our system', or any operational "
    "plumbing. The customer does not see our internal queues. "
    "GROUNDING RULE: when SALESFORCE CONTEXT lists open or recent Orders that match the customer's "
    "question (by PoNumber, OrderNumber, product, or ship-to), quote the dates, status, and ship-to "
    "VERBATIM from those Salesforce rows. NEVER echo a date the customer mentioned in their email "
    "as if it were a Keysight commitment unless that same date also appears in the Salesforce row. "
    "If the customer asked about a PO or order that is NOT present in SALESFORCE CONTEXT, say "
    "explicitly that you do not see that reference on file and ask them to confirm the PO number. "
    "Do not invent commitments; only confirm what is in the Salesforce context or the action result. "
    "If the request is a work-order status inquiry, translate internal status codes into customer-friendly "
    "language and end with a Keysight Standard Procedure (KSP) reassurance. For example: "
    "'in_progress' → 'Our field team has begun the calibration and you can expect a status update by <date>.', "
    "'scheduled' → 'The work is on our schedule for <date>; our team will reach out 48 hours in advance.', "
    "'open' → 'The work order is logged in our system and will be assigned within one business day per our standard SLA.'"
)


# Intents that produce a Sales Order Acknowledgment. We attach the SOA on the
# draft regardless of execution status — for L4 the autosend uses it, for L3
# the click-to-approve preview shows it, for L2 HITL the CSR has it ready.
_SOA_ELIGIBLE_INTENTS = {
    "po_intake",
    "quote_to_order",
    "trade_change_order",
}


def _build_outbound_glossary_block(target_language: str | None) -> str:
    """Inject the Keysight per-language glossary into the reply-drafter system
    prompt so the LLM uses canonical Keysight terminology in the customer-
    language reply (e.g., '校正証明書' for 'calibration certificate' in JA)."""
    if not target_language or target_language == "en":
        return ""
    try:
        from .tools.translate_tool import _load_outbound_glossary
        _, lines = _load_outbound_glossary(target_language)
        if not lines:
            return ""
        return "\n\nKEYSIGHT TRANSLATION GLOSSARY:\n" + "\n".join(lines)
    except Exception:
        return ""


def _template_reply(*, intake: dict, decision: dict, customer_name: str | None) -> dict:
    """Deterministic reply builder used when the LLM call fails or returns
    invalid JSON. Keeps the case shippable to HITL with content the CSR can
    edit instead of a blank draft."""
    lang = intake.get("language") or "en"
    intent = intake.get("intent") or "general_inquiry"
    action = decision.get("action") or "review"
    cust = customer_name or "Customer"
    subject = "Re: your request" if lang == "en" else (
        "Re: su solicitud" if lang == "es" else "Re: お問い合わせの件"
    )
    if lang == "es":
        body = (
            f"Estimado/a {cust},\n\n"
            "Gracias por su mensaje. Nuestro equipo está revisando los detalles y le "
            "responderá en breve con los próximos pasos.\n\n"
            "Atentamente,\nKeysight Sales Operations"
        )
    elif lang == "ja":
        body = (
            f"{cust} 様\n\n"
            "お問い合わせいただきありがとうございます。担当チームが内容を確認しており、"
            "次のステップについて折り返しご連絡いたします。\n\n"
            "Keysight Sales Operations"
        )
    else:
        body = (
            f"Hello {cust},\n\n"
            "Thank you for your message. Our team is reviewing the details and will "
            "respond shortly with the next steps. If anything is time-sensitive, "
            "please reply to this thread and we will pick it up directly.\n\n"
            "Regards,\nKeysight Sales Operations"
        )
    return {
        "language": lang,
        "subject": subject,
        "body": body,
        "_template_fallback": True,
        "_intent": intent,
        "_action": action,
    }


def _coerce_reply_dict(parsed: Any) -> dict | None:
    """`ask_llm(json_only=True)` should return a dict, but harden against
    the SDK returning a string / None / a list."""
    if isinstance(parsed, dict):
        return parsed
    return None


def _build_salesforce_context_block(customer_match: dict | None) -> str:
    """Pull the Stage 2.4 enrichment payload onto the prompt so the LLM can
    ground date and status answers in Salesforce rather than echo the
    customer's own message. Returns an empty string when no SF rows are
    available (so a missing SF connection still produces a usable reply)."""
    cm = customer_match or {}
    sf = (cm.get("salesforce") or {})
    orders = sf.get("recent_orders") or []
    cases = sf.get("recent_cases") or []
    if not orders and not cases:
        return ""
    lines = []
    if orders:
        lines.append("Recent Orders on file:")
        for o in orders[:10]:
            order_no = o.get("OrderNumber") or o.get("order_number")
            po = o.get("PoNumber") or o.get("po_number")
            status = o.get("Status") or o.get("status")
            eff = o.get("EffectiveDate") or o.get("effective_date") or o.get("requested_ship_date")
            end = o.get("EndDate") or o.get("end_date") or o.get("committed_ship_date")
            desc = (o.get("Description") or o.get("description") or "")[:160]
            ship_city = o.get("ShippingCity") or o.get("shipping_city")
            lines.append(
                f"  - OrderNumber={order_no} | PoNumber={po} | Status={status} | "
                f"EffectiveDate={eff} | EndDate={end} | ShipTo={ship_city or '-'} | {desc}".rstrip()
            )
    if cases:
        lines.append("Recent Cases on file:")
        for c in cases[:5]:
            case_no = c.get("CaseNumber") or c.get("case_number")
            subject = (c.get("Subject") or c.get("subject") or "")[:120]
            status = c.get("Status") or c.get("status")
            lines.append(f"  - CaseNumber={case_no} | Status={status} | Subject={subject}")
    return "\n\nSALESFORCE CONTEXT (authoritative — quote VERBATIM when relevant):\n" + "\n".join(lines)


def run_communicate(*, email: dict, intake: dict, extracted: dict, decision: dict, execution: dict, customer_match: dict | None = None, db=None) -> dict:
    if (decision or {}).get("action") == "discard":
        return {"sent": False, "reason": "spam"}

    target_language = (intake or {}).get("language") or "en"
    # Continuous-Learning hook: if a prompt-refinement experiment promoted a
    # new system body to `agent_prompts/communicate:system`, use it; otherwise
    # fall through to the hardcoded SYSTEM constant. Source meta is returned
    # alongside the reply so the trace UI can show which body was live.
    from .kb_prompts import get_stage_system_prompt
    base_system, kb_prompt_source = get_stage_system_prompt(db, "communicate", SYSTEM)
    system_prompt = base_system + _build_outbound_glossary_block(target_language)

    sf_block = _build_salesforce_context_block(customer_match)

    # Sanitize the execution dict so internal staging state (awaiting_one_click,
    # awaiting_hitl, hold_release_csr_confirm, etc.) never reaches the LLM and
    # therefore cannot leak into the customer-facing reply. The reply is the
    # final outbound message that goes out after CSR approval, so the LLM
    # should see the action as completed.
    customer_safe_execution: dict[str, Any] = {}
    if isinstance(execution, dict):
        _redacted_status = {
            "awaiting_one_click": "applied",
            "awaiting_hitl": "applied",
            "pending_one_click": "applied",
            "pending_hitl": "applied",
            "preview": "applied",
        }
        for k, v in execution.items():
            if k == "status":
                customer_safe_execution[k] = _redacted_status.get(v, v)
            elif k in {"reason"} and isinstance(v, str) and (
                "csr_confirm" in v or "awaiting" in v or "pending" in v or "review" in v
            ):
                # Drop internal reason codes that hint at staging.
                continue
            elif k in {"preview", "internal", "staging"}:
                continue
            else:
                customer_safe_execution[k] = v

    user = (
        f"CUSTOMER LANGUAGE: {target_language}\n"
        f"CUSTOMER EMAIL: {(email or {}).get('from')}\n"
        f"ORIGINAL SUBJECT: {(email or {}).get('subject')}\n"
        f"DETECTED INTENT: {(intake or {}).get('intent')}\n"
        f"ACTION: {(decision or {}).get('action')}\n"
        f"EXECUTION RESULT (customer-visible): {customer_safe_execution}\n"
        f"EXTRACTED FIELDS: {extracted}"
        f"{sf_block}\n"
        "\nDraft a courteous, accurate reply that reads as the final outbound "
        "message after all internal approvals are complete. Ground every date "
        "or status in SALESFORCE CONTEXT when present. JSON only."
    )

    # ---- LLM draft (best-effort, never raise) -------------------------------
    reply: dict | None = None
    llm_error: str | None = None
    try:
        parsed = ask_llm(system=system_prompt, user=user, json_only=True)
        reply = _coerce_reply_dict(parsed)
        if reply is None:
            llm_error = "LLM did not return a JSON object"
    except Exception as e:
        llm_error = f"{type(e).__name__}: {str(e)[:200]}"
        log.warning("Stage 5 LLM call failed: %s", llm_error)

    if reply is None or not (reply.get("subject") and reply.get("body")):
        # Build a deterministic template draft so the case isn't blank
        cust_name = (extracted or {}).get("customer_name") or (email or {}).get("from")
        reply = _template_reply(intake=intake or {}, decision=decision or {}, customer_name=cust_name)
        if llm_error:
            reply["_llm_error"] = llm_error

    # ---- SOA generation (always for PO-bearing intents, regardless of tier) -
    soa_path = None
    intent = (intake or {}).get("intent")
    if intent in _SOA_ELIGIBLE_INTENTS and (extracted or {}).get("po_number"):
        try:
            soa_path = _generate_soa(email=email or {}, extracted=extracted or {})
            reply["soa_attachment"] = str(soa_path.name)
        except Exception as e:
            log.warning("SOA generation failed: %s", e)
            reply["_soa_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    return {
        "language": reply.get("language") or target_language,
        "subject": reply.get("subject"),
        "body": reply.get("body"),
        "soa_path": str(soa_path) if soa_path else None,
        "soa_attachment": reply.get("soa_attachment"),
        "sent": True,
        "kb_prompt_source": kb_prompt_source,
        "_template_fallback": bool(reply.get("_template_fallback")),
        "_llm_error": reply.get("_llm_error"),
        "_soa_error": reply.get("_soa_error"),
    }


def _generate_soa(*, email: dict, extracted: dict) -> Path:
    po_num = extracted.get("po_number") or f"UNKNOWN-{int(datetime.now().timestamp())}"
    out = OUTPUTS / f"SOA_{po_num}.pdf"
    soa_number = f"SOA-{po_num.replace('PO-', '')}-{random.randint(100, 999)}"
    today = date.today()
    promised = (today + timedelta(days=21)).isoformat()

    return make_soa_pdf(
        out,
        po_number=po_num,
        soa_number=soa_number,
        acknowledged_date=today,
        customer_name=extracted.get("customer_name") or "Customer",
        bill_to=extracted.get("bill_to"),
        ship_to=extracted.get("ship_to"),
        line_items=extracted.get("line_items") or [],
        payment_terms=extracted.get("payment_terms"),
        requested_ship_date=extracted.get("requested_ship_date"),
        promised_ship_date=promised,
        notes=extracted.get("notes"),
    )
