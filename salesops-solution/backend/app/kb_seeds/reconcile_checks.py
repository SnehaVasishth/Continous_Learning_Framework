"""Seed rules for the `reconcile_checks` KB namespace.

Stage 2.5 (Cross-system validation) walks this rubric to flag mismatches between
the inbound PO/Q2O document and the matched quote + customer record. Each check
emits a structured `checks_evaluated[]` entry the trace UI can render, plus a
backwards-compatible `issues[]` entry whose `kind` Stage 3's decide.py keys
off of.

Three rule kinds:

  • `per_line` — evaluated once per PO line item. The predicate sees `po_line`
    + `quote_line` (when a SKU match exists) + the shared eval context. If
    no quote line matched the SKU, the predicate is bypassed and the rule's
    no-match branch produces a fuzzy-pick or sku_not_quoted issue (handled
    by reconcile.py for the SKU-existence checks).

  • `per_total` — evaluated once per reconcile pass against the full quote
    + extracted document. Predicate sees `extracted`, `quote_total`, etc.

  • `severity` — vocabulary:
        hard — blocking issue, decide.py caps confidence at 0.70
        soft — non-blocking discrepancy, caps at 0.88
        warn — reported as a trace event but doesn't move confidence

The default seed reproduces today's hardcoded reconcile.py behavior bit-for-bit
on the four legacy line-level checks (sku_exists / unit_price / qty / typo)
plus the missing-quoted-line cross-check, AND adds seven new total/header
checks the RFP §37 cross-validation requirement asks for: total amount sum,
total vs quote total, payment terms, currency, bill-to address, incoterms,
duplicate-PO detection.

Each rule's `description` follows the same "What it does / How to optimize"
pattern as `intent_confidence_rubric.py` — operators read this in the KB UI
when they tune the rules.
"""
from __future__ import annotations

from typing import Any


RECONCILE_CHECKS_RULES: list[dict[str, Any]] = [
    # ----------------------------------------------------------------------
    # PER-LINE CHECKS (one evaluation per PO line item)
    # ----------------------------------------------------------------------
    {
        "id": "line_sku_exists_in_quote",
        "label": "PO line SKU must exist in the matched quote",
        "kind": "rule",
        "scope": "per_line",
        "predicate": "po_line.sku in quote_skus",
        "fires_when": "predicate_false",
        "severity": "warn",
        "issue_kind": "sku_not_quoted",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: for each PO line, checks the SKU appears in the matched "
            "quote's line items. If absent AND no fuzzy match found (see "
            "line_sku_typo_fuzzy below), emits a `sku_not_quoted` issue and a warn-"
            "level trace event. Today this produces a soft cap at 0.88 in decide.py.\n\n"
            "How to optimize:\n"
            "  • Raise to severity=`soft` if your buyers regularly add unquoted line "
            "    items (consumables, freight) and you want those auto-routed to "
            "    one-click review rather than just trace-warned.\n"
            "  • Deactivate (active=false) for rare contract-pricing flows where the "
            "    customer's PO is allowed to add line items the quote didn't enumerate."
        ),
    },
    {
        "id": "line_unit_price_matches_quote",
        "label": "PO line unit price matches quoted unit price (±$0.01)",
        "kind": "rule",
        "scope": "per_line",
        "predicate": "abs(po_line.unit_price - quote_line.unit_price) <= 0.01",
        "fires_when": "predicate_false",
        "severity": "hard",
        "issue_kind": "price_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: when the PO and the quote both have a unit_price for the "
            "same SKU, they must agree to the cent. Mismatch fires a `price_mismatch` "
            "issue and a hard-severity trace event — Stage 3 caps confidence at 0.70 "
            "and routes to L2 full HITL.\n\n"
            "How to optimize:\n"
            "  • Loosen the tolerance (e.g. `abs(...) <= 1.00`) for high-value POs "
            "    where rounding noise on $50k+ unit prices is normal — a $1 difference "
            "    on a $52,300 instrument doesn't justify HITL.\n"
            "  • Tighten to severity=`soft` (cap 0.88) if your team prefers one-click "
            "    approve rather than full review on small price deltas.\n"
            "  • This is the main protector against billing disputes — don't disable."
        ),
    },
    {
        "id": "line_qty_matches_quote",
        "label": "PO line quantity matches quoted quantity",
        "kind": "rule",
        "scope": "per_line",
        "predicate": "po_line.qty == quote_line.qty",
        "fires_when": "predicate_false",
        "severity": "hard",
        "issue_kind": "qty_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: when the PO and the quote both have a qty for the same "
            "SKU, they must match. Mismatch fires a `qty_mismatch` issue (hard "
            "severity → cap at 0.70 in decide.py).\n\n"
            "How to optimize:\n"
            "  • Drop to severity=`soft` if your buyers commonly increase qty on the "
            "    PO (after the quote was issued) and CSRs are happy to one-click "
            "    approve those.\n"
            "  • Keep `hard` for regulated industries (defense, aerospace) where qty "
            "    discrepancies indicate either a buyer error or a rev change that "
            "    needs a quote refresh."
        ),
    },
    {
        "id": "line_sku_typo_fuzzy",
        "label": "Unmatched SKU has a fuzzy match (≥ 0.7) — likely typo",
        "kind": "rule",
        "scope": "per_line",
        "predicate": "fuzzy_match_score >= fuzzy_match_threshold",
        "fires_when": "predicate_true",
        "severity": "soft",
        "issue_kind": "sku_typo",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "fuzzy_match_threshold": 0.7,
        "description": (
            "What it does: when a PO line's SKU isn't an exact match in the quote, "
            "but a SequenceMatcher score against the quote's SKUs is ≥0.7, treats "
            "it as a probable typo. Fires a `sku_typo` issue (soft → cap at 0.88).\n\n"
            "How to optimize:\n"
            "  • Raise the threshold (e.g. 0.85) if you're seeing false positives "
            "    where two unrelated SKUs have similar-looking model numbers.\n"
            "  • Lower (e.g. 0.6) if your buyers regularly mistype Keysight SKUs and "
            "    you want the system to catch more of those.\n"
            "  • Deactivate if you've moved to strict-match — every typo just goes "
            "    to `sku_not_quoted` instead."
        ),
    },

    # ----------------------------------------------------------------------
    # PER-TOTAL CHECKS (one evaluation per reconcile pass)
    # ----------------------------------------------------------------------
    {
        "id": "quote_line_missing_in_po",
        "label": "Every quote line should appear in the PO",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "len(quote_skus - po_skus) == 0",
        "fires_when": "predicate_false",
        "severity": "soft",
        "issue_kind": "missing_quoted_line",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: walks the quote's line items and flags any SKU that's "
            "absent from the PO. Each missing SKU produces one `missing_quoted_line` "
            "issue. Soft severity → cap at 0.88 in decide.py.\n\n"
            "How to optimize:\n"
            "  • Drop to severity=`warn` for partial-fulfillment workflows where the "
            "    customer often issues a PO covering only some of the quoted lines.\n"
            "  • Tighten to severity=`hard` only if your business rules require POs "
            "    to fulfill the entire quote (rare)."
        ),
    },
    {
        "id": "total_amount_sum_matches_lines",
        "label": "PO grand total equals sum of (qty × unit_price) (±$0.01)",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "abs(extracted_total - line_items_sum) <= 0.01",
        "fires_when": "predicate_false",
        "severity": "warn",
        "issue_kind": "total_sum_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: arithmetic sanity check — the PO's grand total should "
            "equal the sum of (qty × unit_price) across all line items. A mismatch "
            "usually means the extractor missed a line, picked up a freight/tax row "
            "as a line item, or the PO itself has an arithmetic error.\n\n"
            "How to optimize:\n"
            "  • Loosen tolerance (e.g. ≤ $5.00) if your POs include freight or tax "
            "    lines that the extractor lumps into total but doesn't itemize.\n"
            "  • Tighten to severity=`soft` (cap 0.88) if you're seeing false-positive "
            "    line-item extraction that should be human-reviewed every time.\n"
            "  • If this fires often on legitimate PDFs, the fix is upstream in the "
            "    extract_schema, not here."
        ),
    },
    {
        "id": "total_matches_quote_total",
        "label": "PO grand total matches quote grand total (±$0.01)",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "abs(extracted_total - quote_total) <= 0.01",
        "fires_when": "predicate_false",
        "severity": "hard",
        "issue_kind": "total_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: the PO's grand total should match the matched quote's "
            "grand total to the cent. Mismatch is HARD severity → cap at 0.70 in "
            "decide.py because it means the customer is paying a different number "
            "than was quoted, which is a billing-dispute risk.\n\n"
            "How to optimize:\n"
            "  • Loosen tolerance for accounts where freight is added on the PO but "
            "    not the quote — but prefer fixing the quote workflow rather than "
            "    relaxing this rule.\n"
            "  • Drop to `soft` only if you trust the line-level price/qty checks "
            "    above to catch every real discrepancy and just want a sanity warn."
        ),
    },
    {
        "id": "payment_terms_matches_quote",
        "label": "PO payment terms match the quote's payment terms",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "extracted_payment_terms == '' or quote_payment_terms == '' or extracted_payment_terms == quote_payment_terms",
        "fires_when": "predicate_false",
        "severity": "warn",
        "issue_kind": "terms_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: if both PO and quote specify payment terms (Net 30, Net "
            "45, etc.), they should agree. Empty-on-either-side is treated as a "
            "match (the buyer didn't override the standard terms). Surfaces RFP §37 "
            "'detect mismatches in terms' requirement.\n\n"
            "How to optimize:\n"
            "  • Tighten to severity=`soft` (cap 0.88) for finance-sensitive accounts "
            "    where any terms drift should land in one-click review.\n"
            "  • Add a per-customer override list (e.g. via a new whitelist KB rule) "
            "    if certain accounts have negotiated non-standard terms outside the "
            "    quote — those false-positives are noisy."
        ),
    },
    {
        "id": "currency_matches_quote",
        "label": "PO currency matches quote currency",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "extracted_currency == '' or quote_currency == '' or extracted_currency == quote_currency",
        "fires_when": "predicate_false",
        "severity": "hard",
        "issue_kind": "currency_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: PO currency must match quote currency. Mismatch is HARD "
            "severity (cap at 0.70) because executing in the wrong currency creates "
            "a real billing/AR mess that's hard to unwind.\n\n"
            "How to optimize:\n"
            "  • Don't loosen this. A USD quote auto-executed against a EUR PO will "
            "    invoice ~10% wrong and require a credit memo + re-issue.\n"
            "  • If you support multi-currency quotes for the same line items, "
            "    rework the quoting pipeline upstream rather than relaxing this rule."
        ),
    },
    {
        "id": "bill_to_matches_account_billing",
        "label": "PO bill-to address overlaps with account's billing address",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "extracted_bill_to == '' or account_billing_combined == '' or any(token in account_billing_combined for token in extracted_bill_to_tokens)",
        "fires_when": "predicate_false",
        "severity": "warn",
        "issue_kind": "bill_to_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: cross-checks the PO's bill-to text against the matched "
            "Salesforce Account's BillingStreet/BillingCity. Looks for any "
            "substring overlap of meaningful tokens (city or street segment) — a "
            "loose match because addresses are formatted dozens of ways.\n\n"
            "How to optimize:\n"
            "  • Tighten to severity=`soft` (cap 0.88) for invoice-fraud-sensitive "
            "    deployments — a wrong bill-to that goes unnoticed = wire-redirect risk.\n"
            "  • Loosen to a non-firing rule (active=false) if your Salesforce "
            "    Account.BillingAddress is consistently empty/stale and the false-"
            "    positive rate is unbearable."
        ),
    },
    {
        "id": "incoterms_matches_quote",
        "label": "PO incoterms match quote incoterms (or both empty)",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "extracted_incoterms == '' or quote_incoterms == '' or extracted_incoterms == quote_incoterms",
        "fires_when": "predicate_false",
        "severity": "warn",
        "issue_kind": "incoterms_mismatch",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: if both PO and quote specify incoterms (FOB Origin, DDP, "
            "EXW, etc.), they should agree. Mismatch implies the buyer expects a "
            "different freight/risk allocation than the quote priced in.\n\n"
            "How to optimize:\n"
            "  • Tighten to severity=`soft` for international shipments where "
            "    incoterms shifts have real cost-of-goods implications.\n"
            "  • Pair with a freight-cost cross-check rule downstream if you want "
            "    end-to-end incoterms enforcement."
        ),
    },
    {
        "id": "duplicate_po_in_recent_orders",
        "label": "PO number already exists on a recent Salesforce Order",
        "kind": "rule",
        "scope": "per_total",
        "predicate": "extracted_po_number == '' or extracted_po_number not in recent_order_po_numbers",
        "fires_when": "predicate_false",
        "severity": "hard",
        "issue_kind": "duplicate_po",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
        "description": (
            "What it does: scans the matched account's recent Salesforce Orders for "
            "an existing record with the same PoNumber. A hit means we've already "
            "ingested this PO — fires a `duplicate_po` issue (hard → cap at 0.70). "
            "Stops the L4 auto-path from creating a duplicate Order in SF.\n\n"
            "How to optimize:\n"
            "  • Don't lower severity. Duplicate orders are a real problem — they "
            "    confuse accounting, double-allocate inventory, and create reconciliation "
            "    headaches downstream.\n"
            "  • If your buyers legitimately re-issue POs with the same PoNumber under "
            "    a revision (PO-123 rev B), extend reconcile.py to compare revision "
            "    numbers and only fire on duplicate (po_number, revision)."
        ),
    },
]


def all_rules() -> list[dict[str, Any]]:
    return RECONCILE_CHECKS_RULES
