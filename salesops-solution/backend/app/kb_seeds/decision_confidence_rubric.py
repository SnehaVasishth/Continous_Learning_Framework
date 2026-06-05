"""Seed rules for the `decision_confidence_rubric` KB namespace.

Stage 3 sub-step 3.1 emits a final `confidence` score that drives the autonomy
tier (L4 auto / L3 one-click / L2 full HITL). Today that score comes from a
hardcoded weighted formula + hardcoded floor caps in `decide.py` — operators
can't tune the math without a code change. This rubric moves the math into the
KB, mirroring the design we already shipped for Stage 1.4 (language) and 1.7
(intent).

Two rule kinds:

  • `weighted_signal` — contributes `weight × signal_value` to the running
    confidence sum. The three core signals (intent, extraction, customer-match)
    are seeded as weighted_signal rules. An operator who wants to rebalance
    the formula (e.g., make customer-match more important) edits the weights
    here; the next pipeline picks them up.

  • `floor_cap` — when the rule's predicate evaluates true, confidence is
    forced down to the rule's `cap` value (no-op if the running sum is already
    below `cap`). Caps are how the rubric encodes "we cannot auto-act when X
    is true, no matter how high the weighted sum is."

Each rule emits a `confidence_breakdown[]` entry:
    {rule_key, kind, matched, contribution, evidence}

so the trace UI shows exactly how the final number was derived. Auditors can
point at every applied rule and read its plain-English `description`.

Default seed reproduces today's hardcoded behavior bit-for-bit. From there,
operators can:
  - Re-weight signals (e.g., "for our org, customer-match should be 0.30")
  - Add new caps (e.g., "L4 only when customer_match_score == 1.0")
  - Deactivate caps that don't apply (e.g., "we don't sell to APAC, drop the
    APAC threshold cap")
  - Add per-intent overrides (e.g., "for service_order, drop the missing-PO
    cap because there's no PO involved")
"""
from __future__ import annotations

from typing import Any


# Confidence starts at 0.0 — unlike Stage 1.7 where the LLM has read the email
# and brings a Beta(1,1) prior, Stage 3 confidence is a pure aggregator of
# upstream signals. Starting from 0.0 forces every signal to be earned.
DECISION_CONFIDENCE_BASE = 0.0


DECISION_CONFIDENCE_RUBRIC_RULES: list[dict[str, Any]] = [
    # ---- meta: starting prior ---------------------------------------------
    {
        "id": "_base",
        "label": "Base confidence (default 0.0 — pure aggregator)",
        "description": (
            "Stage 3 confidence is a pure aggregator of upstream signals — "
            "intent classification quality, extraction completeness, customer "
            "match score, reconcile result, and business-rule caps. Unlike "
            "the Stage 1.7 intent_confidence_rubric (where 0.50 reflects the "
            "LLM's pretrained prior knowledge), Stage 3 has no semantic prior "
            "of its own; it just sums what upstream stages produced.\n\n"
            "Final confidence = base + Σ(matched weighted_signal contributions), "
            "then clamped to [0.0, 1.0] and stepped through every floor_cap rule.\n\n"
            "How to optimize: leave at 0.0 unless calibration data shows the "
            "system is systematically too low across all intents (which would "
            "indicate signals are under-weighted, not that the prior is wrong)."
        ),
        "kind": "base",
        "value": DECISION_CONFIDENCE_BASE,
        "active": True,
    },

    # ---- weighted signals (the formula) -----------------------------------

    {
        "id": "intent_confidence_signal",
        "label": "Intent confidence signal — weight 0.45",
        "description": (
            "What it does: contributes `0.45 × intent_confidence` to the "
            "running sum, where intent_confidence is the Stage 1.7 score. "
            "This is the largest weight because if we don't know what the "
            "customer is asking for, no amount of clean extraction or "
            "customer matching can rescue the decision.\n\n"
            "How to optimize:\n"
            "  • Raise the weight (e.g. 0.50) if real-world calibration shows "
            "    intent classification is your bottleneck — when intent is "
            "    right, downstream usually is too.\n"
            "  • Lower the weight (e.g. 0.40) if extraction completeness is "
            "    the bigger predictor of HITL escalation in your data.\n"
            "  • The three weighted_signal rules' weights should typically "
            "    sum to 1.0 (they do in the default: 0.45+0.35+0.20=1.0). "
            "    Sums above 1.0 are valid but the result then needs the "
            "    [0,1] clamp at the end to behave."
        ),
        "kind": "weighted_signal",
        "weight": 0.45,
        "signal_var": "intent_confidence",
        "active": True,
    },

    {
        "id": "extraction_completeness_signal",
        "label": "Extraction completeness signal — weight 0.35",
        "description": (
            "What it does: contributes `0.35 × extraction_completeness` to "
            "the running sum. extraction_completeness is the fraction of the "
            "intent's required fields that Stage 2.2 successfully extracted. "
            "For PO-style intents that's `populated_required / total_required` "
            "across {po_number, customer_name, line_items, total}. Each intent "
            "has its own completeness function in `decide.py::score_extraction_"
            "completeness()`.\n\n"
            "How to optimize:\n"
            "  • Raise to 0.40 if you're seeing pipelines auto-act on emails "
            "    where extraction was sparse but intent was clear — extraction "
            "    being noisy means execution will fail anyway.\n"
            "  • Lower to 0.30 if your extractor is highly reliable and you "
            "    want intent confidence to dominate.\n"
            "  • If you start adding new intents, also extend `score_extraction"
            "_completeness()` to score them — otherwise their default 0.6 will "
            "    silently dominate."
        ),
        "kind": "weighted_signal",
        "weight": 0.35,
        "signal_var": "extraction_completeness",
        "active": True,
    },

    {
        "id": "customer_match_signal",
        "label": "Customer match signal — weight 0.20",
        "description": (
            "What it does: contributes `0.20 × customer_match_score` to the "
            "running sum. customer_match_score is 1.0 on an exact match (via "
            "Customer_Code__c or Contact.Email), and lower for fuzzy "
            "Account.Name matches. The weight is intentionally smaller than "
            "intent or extraction because the existence-gate at Stage 2.3 "
            "already enforces 'no match → no Stage 3' — by the time Stage 3 "
            "runs, we know the customer exists; this signal only differentiates "
            "exact-match from fuzzy-match.\n\n"
            "How to optimize:\n"
            "  • Raise to 0.25 or 0.30 in regulated industries where wrong-"
            "    customer auto-action is expensive (defense, ITAR, financial "
            "    services). The customer_match_low_cap and exact_match_required"
            "_for_l4 caps below already do this in code; the signal weight "
            "    reinforces it in the formula.\n"
            "  • Lower to 0.15 if customer-matching is highly reliable in your "
            "    deployment and you want extraction quality to dominate.\n"
            "  • Don't drop below 0.10 — even with a perfect existence gate, "
            "    fuzzy matches deserve some confidence pressure."
        ),
        "kind": "weighted_signal",
        "weight": 0.20,
        "signal_var": "customer_match_score",
        "active": True,
    },

    # ---- floor caps (predicate -> max confidence) -------------------------

    {
        "id": "exact_match_required_for_l4",
        "label": "L4 auto requires exact customer match (cap at 0.85 for fuzzy)",
        "description": (
            "What it does: when the customer was matched via fuzzy Account.Name "
            "(score < 0.95) rather than an exact Customer_Code__c or Contact.Email "
            "match, caps confidence at 0.85 — guaranteeing the pipeline lands at "
            "L3 (one-click human approval) or below. We never want to auto-execute "
            "an order against a fuzzy-matched customer.\n\n"
            "How to optimize:\n"
            "  • Lower the cap (e.g. 0.75) in regulated/compliance-sensitive "
            "    deployments — forces L2 full HITL on any non-exact match.\n"
            "  • Raise to 0.92 only if your name-matcher is very tight (e.g. "
            "    proprietary entity-resolution layer with high precision) — "
            "    most demos should keep this at 0.85.\n"
            "  • Tune the threshold (currently 0.95) — if your fuzzy matcher "
            "    is very conservative, you may have legitimate exact matches "
            "    landing at 0.90."
        ),
        "kind": "floor_cap",
        "cap": 0.85,
        "predicate": "customer_match_score < 0.95",
        "applies_to_intents": [],
        "active": True,
    },

    {
        "id": "customer_match_low_cap",
        "label": "Customer match below 0.5 → cap at 0.55",
        "description": (
            "What it does: when customer-match score is below 0.5 (very weak "
            "fuzzy match — e.g., one word matches in a long company name), "
            "caps confidence at 0.55. Forces L2 full HITL because we likely "
            "matched the wrong customer.\n\n"
            "Why it exists separately from the weighted signal: the weighted "
            "signal contributes `0.20 × 0.4 = 0.08` to the sum, which is too "
            "small to keep an otherwise-clean email out of L4. A cap is "
            "categorical — it says 'no, we just won't do this'.\n\n"
            "How to optimize:\n"
            "  • Lower the cap (e.g. 0.40) to force these emails into L2 not "
            "    L3 — useful if your CSRs prefer to fully investigate weak "
            "    matches rather than one-click approve.\n"
            "  • Tighten the threshold (e.g. < 0.6 instead of < 0.5) if you "
            "    see incorrect auto-actions on borderline matches."
        ),
        "kind": "floor_cap",
        "cap": 0.55,
        "predicate": "customer_match_score < 0.5",
        "applies_to_intents": [],
        "active": True,
    },

    {
        "id": "customer_match_med_cap",
        "label": "Customer match below 0.7 → cap at 0.70",
        "description": (
            "What it does: when customer-match score is between 0.5 and 0.7 "
            "(reasonable fuzzy match but not great), caps confidence at 0.70 — "
            "forces L2 full HITL (since L3 starts at 0.80).\n\n"
            "Companion to customer_match_low_cap. Both layers exist because "
            "weak/medium customer matches need stronger pressure than the "
            "0.20-weighted signal alone provides.\n\n"
            "How to optimize:\n"
            "  • Combine with customer_match_low_cap into a single graduated cap "
            "    if you prefer one rule over two.\n"
            "  • Lower threshold (< 0.8 instead of < 0.7) to force more "
            "    borderline matches into HITL."
        ),
        "kind": "floor_cap",
        "cap": 0.70,
        "predicate": "customer_match_score < 0.7 and customer_match_score >= 0.5",
        "applies_to_intents": [],
        "active": True,
    },

    {
        "id": "missing_po_number_cap",
        "label": "Missing PO number on PO/Q2O intent → cap at 0.40",
        "description": (
            "What it does: when intent is po_intake or quote_to_order but no "
            "po_number was extracted, caps confidence at 0.40 — forces L2 full "
            "HITL because a PO without a PO number can't be created in SF "
            "(PoNumber is required by every Order workflow).\n\n"
            "How to optimize:\n"
            "  • Don't lower this cap. A missing PO number is hard-blocking — "
            "    Stage 4 would fail anyway.\n"
            "  • Add additional intents to applies_to_intents if you grow the "
            "    intent vocabulary (e.g., a future 'standing_order_release' "
            "    intent would also need a PO).\n"
            "  • If you're seeing this fire on legitimate emails where the PO "
            "    number was in the attachment but extraction missed it, the "
            "    fix is upstream in the extraction schema, not here."
        ),
        "kind": "floor_cap",
        "cap": 0.40,
        "predicate": "intent in ['po_intake', 'quote_to_order'] and not po_number",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
    },

    {
        "id": "empty_line_items_cap",
        "label": "Empty line items on PO/Q2O intent → cap at 0.40",
        "description": (
            "What it does: when intent is po_intake or quote_to_order but no "
            "line items were extracted, caps confidence at 0.40 — forces L2 "
            "full HITL. Without line items, we don't know what's being "
            "ordered; Stage 4 cannot create OrderItems.\n\n"
            "How to optimize:\n"
            "  • Same as missing_po_number_cap — don't lower; it's hard-"
            "    blocking on the execute side.\n"
            "  • If false-positives (emails that had line items but extraction "
            "    missed them), tune the extract_schema's line_items field "
            "    description, don't relax this cap."
        ),
        "kind": "floor_cap",
        "cap": 0.40,
        "predicate": "intent in ['po_intake', 'quote_to_order'] and line_count == 0",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
    },

    {
        "id": "blocking_mismatch_cap",
        "label": "Reconcile blocking mismatch → cap at 0.70",
        "description": (
            "What it does: when Stage 2.5 (reconcile) reports a hard mismatch "
            "vs the matched quote — price_mismatch, qty_mismatch, or sku_not_"
            "quoted — caps confidence at 0.70. Forces L2 full HITL because "
            "the customer's PO disagrees with what Sales quoted them; auto-"
            "executing would either create the wrong order or invite a "
            "billing dispute.\n\n"
            "How to optimize:\n"
            "  • Lower the cap (e.g. 0.50) to force these into deeper review "
            "    — useful for high-touch / high-value accounts.\n"
            "  • Add or remove issue kinds in the predicate as your reconcile_"
            "    checks rubric grows."
        ),
        "kind": "floor_cap",
        "cap": 0.70,
        "predicate": "reconcile_blocking_count > 0",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
    },

    {
        "id": "soft_mismatch_cap",
        "label": "Reconcile soft mismatch → cap at 0.88",
        "description": (
            "What it does: when Stage 2.5 reports a soft mismatch — sku_typo, "
            "missing_quoted_line, missing_sku — caps confidence at 0.88. "
            "Forces L3 one-click review (because L4 starts at 0.95). Soft "
            "mismatches usually indicate a buyer-side data-entry error that "
            "a CSR can quickly approve once they eyeball the diff.\n\n"
            "How to optimize:\n"
            "  • Lower (0.80) if you want soft mismatches to be auto-routed "
            "    to L2 deep review instead of L3 one-click.\n"
            "  • Add new soft issue kinds as your reconcile rubric grows."
        ),
        "kind": "floor_cap",
        "cap": 0.88,
        "predicate": "reconcile_soft_count > 0",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "active": True,
    },
]


def all_rules() -> list[dict[str, Any]]:
    return DECISION_CONFIDENCE_RUBRIC_RULES
