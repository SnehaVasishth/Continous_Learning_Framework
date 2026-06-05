"""Drafts a corrective customer-facing email when the Reconcile stage flagged
mismatches between the customer's PO and the underlying quote. Output is in
the customer's detected language and itemizes each variance with a polite ask
to confirm/revise.
"""
from __future__ import annotations

from .llm import ask_llm

SYSTEM = (
    "You are a Keysight CSR assistant drafting a corrective email back to a customer "
    "whose PO doesn't reconcile cleanly against the originating quote. "
    "Tone: professional, accommodating, concise. Match the customer's language exactly. "
    "Itemize each variance with the quoted vs PO values so the customer can confirm "
    "or send a revised PO. End with a clear ask: confirm acceptance of quoted terms, "
    "issue a revised PO, or get sales-ops approval. "
    "Return strict JSON: {\"language\": str, \"subject\": str, \"body\": str (multi-line)}."
)


def run_suggest_fix(
    *,
    email: dict,
    intake: dict,
    extracted: dict,
    reconcile_result: dict,
) -> dict:
    issues = (reconcile_result or {}).get("issues") or []
    matched = (reconcile_result or {}).get("matched_quote") or {}

    issues_summary = []
    for it in issues:
        if it.get("kind") == "price_mismatch":
            issues_summary.append(
                f"- SKU {it.get('sku')}: PO unit price ${it.get('po_price'):.2f} vs quoted ${it.get('quoted_price'):.2f}"
            )
        elif it.get("kind") == "qty_mismatch":
            issues_summary.append(
                f"- SKU {it.get('sku')}: PO qty {it.get('po_qty')} vs quoted qty {it.get('quoted_qty')}"
            )
        elif it.get("kind") == "sku_not_quoted":
            li = it.get("po_line", {})
            issues_summary.append(
                f"- SKU {li.get('sku')} ({li.get('description')}) is on the PO but was not on the quote"
            )
        elif it.get("kind") == "sku_typo":
            issues_summary.append(
                f"- PO SKU {it.get('po_sku')} appears to be a typo of quoted {it.get('quoted_sku')}"
            )
        elif it.get("kind") == "missing_quoted_line":
            issues_summary.append(f"- Quoted SKU {it.get('sku')} is not on the PO")
        else:
            issues_summary.append(f"- {it.get('kind')}: {it}")

    user = (
        f"CUSTOMER LANGUAGE: {intake.get('language') or 'en'}\n"
        f"CUSTOMER EMAIL: {email['from']}\n"
        f"ORIGINAL SUBJECT: {email['subject']}\n"
        f"DETECTED INTENT: {intake.get('intent')}\n"
        f"PO NUMBER: {extracted.get('po_number')}\n"
        f"QUOTE REFERENCED: {matched.get('quote_number') or '(unknown)'}\n"
        f"\nVARIANCES:\n" + ("\n".join(issues_summary) if issues_summary else "(none)") + "\n"
        f"\nDraft the corrective email. JSON only."
    )
    return ask_llm(system=SYSTEM, user=user, json_only=True)
