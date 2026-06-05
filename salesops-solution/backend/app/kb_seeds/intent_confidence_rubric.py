"""Seed rules for the `intent_confidence_rubric` KB namespace.

The intake classifier (Stage 1.7) emits an `intent_confidence` score for the
chosen intent. Instead of letting the LLM pick a number from training-data
intuition, we make the score deterministic and auditable: the LLM applies
each rubric rule below to the email and reports a per-rule contribution. The
final number is `intent_confidence_base` (seeded as 0.50) plus every matched
rule's `delta`, clamped to [0.0, 1.0].

Operators tune the rubric in Settings → Knowledge Base → "Intent confidence
rubric" — change a delta, deactivate a rule, add a per-intent override —
without a code change. The next pipeline run picks up the new rubric.

Each rule has:
- `default_delta` — applied to ALL intents unless overridden
- `per_intent_overrides` — `{intent_key: delta}` for per-intent tuning
- `kind` — `trigger` (positive contribution), `clearance` (no-ambiguity reward),
           `penalty` (negative contribution), or `base` (the starting prior)
- `description` — what the LLM looks for to decide if the rule matched
- `examples` — concrete cues the LLM should treat as matches
"""
from __future__ import annotations

from typing import Any

INTENT_CONFIDENCE_BASE = 0.50


INTENT_CONFIDENCE_RUBRIC_RULES: list[dict[str, Any]] = [
    # ---- meta: starting prior ---------------------------------------------
    {
        "id": "_base",
        "label": "Base confidence (calibration prior, default 0.50)",
        "description": (
            "The starting score before any rubric rule is applied. Final intent_confidence "
            "= base + sum(matched rule deltas), clamped to [0.0, 1.0]. "
            "We use 0.50 — a deliberate calibration midpoint between two textbook priors:\n"
            "  • Uniform / max-entropy prior over 13 intents would be 1/13 ≈ 0.08 (Jaynes 1957). "
            "    That's the right value if the model were BLIND to the email — but the LLM has "
            "    already read the subject + body, so 0.08 understates its actual prior knowledge.\n"
            "  • Laplacian neutral / Beta(1,1) over 'is this intent or not' is 0.50 — the standard "
            "    binary-outcome uninformed prior used in Bayesian inference and calibration curves.\n"
            "  We picked the binary-outcome midpoint (0.50) because the LLM brings real pretrained "
            "  knowledge to every classification, but it shouldn't be over-confident before rubric "
            "  evidence fires. Tune this number if real-world calibration data shows the system is "
            "  systematically over- or under-confident — change the value here, no redeploy."
        ),
        "kind": "base",
        "value": INTENT_CONFIDENCE_BASE,
        "default_delta": 0.0,
        "per_intent_overrides": {},
        "active": True,
    },
    # ---- triggers ---------------------------------------------------------
    {
        "id": "subject_explicit_signal",
        "label": "Subject explicit signal",
        "description": (
            "What it does: rewards the chosen intent when the email subject contains "
            "a canonical token that nearly always means this intent — e.g. 'PO PO-…' "
            "for po_intake, 'Convert quote' for quote_to_order, 'cal request' for "
            "service_order. This is the single highest-weighted positive signal "
            "because subject lines are usually unambiguous in B2B mail.\n\n"
            "How to optimize:\n"
            "  • Raise default_delta if the system is too cautious on emails with "
            "    obvious subjects (e.g. confidence stays at 0.6 when subject literally "
            "    says 'PO PO-…').\n"
            "  • Add or adjust a per-intent override when one intent has a stronger / "
            "    weaker subject signal than others (e.g., 'spam' is bumped to +0.40 "
            "    because spam subjects are usually screaming, while 'service_contract_request' "
            "    might keep the default because subjects can be ambiguous).\n"
            "  • Deactivate (active=false) only if you're seeing false positives — "
            "    e.g., legitimate forwarded emails that retain the original subject.\n"
            "  • Don't lower this rule below ~+0.20 — subject is the highest-signal "
            "    field in B2B mail and should dominate the rubric."
        ),
        "kind": "trigger",
        "default_delta": 0.30,
        "per_intent_overrides": {
            "po_intake": 0.32,
            "quote_to_order": 0.32,
            "service_order": 0.32,
            "spam": 0.40,
            "out_of_scope": 0.35,
        },
        "examples": {
            "po_intake": ["PO PO-…", "Purchase Order", "OC PO-…", "発注書"],
            "quote_to_order": ["Convert quote", "Q2O", "convert QT-… to order"],
            "trade_change_order": ["change order", "modify order", "CO request"],
            "ssd_change_request": ["ship date change", "push out ship date", "SSD change"],
            "delivery_change": ["reschedule delivery", "delivery date change"],
            "hold_release": ["release hold", "credit hold release", "export hold release"],
            "service_order": ["calibration request", "cal request", "WO create", "repair request"],
            "wo_update_request": ["update work order", "modify WO", "add asset to WO"],
            "wo_status_inquiry": ["WO status", "work order status", "as-found status"],
            "service_contract_request": ["service contract", "cal plan", "PM plan", "support agreement"],
            "general_inquiry": ["lead time question", "EOL roadmap", "product info"],
            "out_of_scope": ["security alert", "newsletter", "out of office", "calendar invite"],
            "spam": ["70% OFF", "verify your account", "act now"],
        },
        "active": True,
    },
    {
        "id": "body_action_verb_match",
        "label": "Body action-verb match",
        "description": (
            "What it does: rewards the chosen intent when the body uses the verb "
            "phrase the intent expects (po_intake → 'acknowledge', quote_to_order → "
            "'convert', service_order → 'calibrate', hold_release → 'release'). "
            "Captures the customer's stated ask in plain language even when the "
            "subject is generic.\n\n"
            "How to optimize:\n"
            "  • Raise default_delta when subject lines are weak/missing in your real "
            "    inbound mail (some customers never set a meaningful subject).\n"
            "  • Lower it if you're seeing the LLM over-trigger on words that aren't "
            "    really action verbs (e.g. matching 'change' in 'no change to plans').\n"
            "  • Add a per-intent override when one intent's verbs are uniquely strong "
            "    (e.g. 'release' is almost only used in hold_release context).\n"
            "  • Pairs with subject_explicit_signal — together they should put a clean, "
            "    well-stated email above 0.85 even before referenced_id_present fires."
        ),
        "kind": "trigger",
        "default_delta": 0.20,
        "per_intent_overrides": {},
        "examples": {
            "po_intake": ["acknowledge", "issue SOA", "confirm receipt"],
            "quote_to_order": ["convert", "issue order", "book the order"],
            "trade_change_order": ["change", "modify", "amend", "update line"],
            "ssd_change_request": ["push out", "pull in", "split shipment", "reschedule"],
            "hold_release": ["release", "clear", "remove hold"],
            "service_order": ["calibrate", "repair", "install", "open work order"],
            "wo_update_request": ["add", "update", "amend WO"],
            "wo_status_inquiry": ["status", "where are we", "ETA"],
            "service_contract_request": ["renew", "quote", "extend", "support agreement"],
            "general_inquiry": ["question", "info", "lead time", "availability"],
        },
        "active": True,
    },
    {
        "id": "referenced_id_present",
        "label": "Referenced identifier present and well-formed",
        "description": (
            "What it does: rewards the chosen intent when the body or attachments "
            "carry a well-formed ID that matches the intent's expected reference type "
            "— PO numbers (po_intake / quote_to_order), Quote IDs (quote_to_order), "
            "Sales-Order numbers (trade_change_order / ssd_change_request / hold_release), "
            "Work-Order numbers (wo_update_request / wo_status_inquiry), or Service-"
            "Contract numbers (service_contract_request).\n\n"
            "How to optimize:\n"
            "  • For trade intents (po_intake, quote_to_order) raise the per-intent "
            "    override — a PO without a PO# is suspicious; a PO with a clean PO# is "
            "    almost certainly real.\n"
            "  • For information intents (general_inquiry, out_of_scope, spam) keep the "
            "    override at ~0.0 — these don't usually carry IDs and rewarding ID "
            "    presence here would be noise.\n"
            "  • If you're seeing false positives because the LLM matched a partial / "
            "    malformed ID (e.g. 'PO' alone without a number), tighten the upstream "
            "    extraction schema OR lower this rule's delta."
        ),
        "kind": "trigger",
        "default_delta": 0.15,
        "per_intent_overrides": {
            "po_intake": 0.20,
            "quote_to_order": 0.20,
            "trade_change_order": 0.18,
            "ssd_change_request": 0.18,
            "hold_release": 0.18,
            "wo_update_request": 0.18,
            "wo_status_inquiry": 0.20,
            "general_inquiry": 0.05,
            "out_of_scope": 0.0,
            "spam": 0.0,
        },
        "examples": {
            "po_intake": ["PO-XYZ-123-…"],
            "quote_to_order": ["QT-XYZ-…", "QUOTE-…"],
            "trade_change_order": ["SO-…", "Order-…"],
            "ssd_change_request": ["SO-…"],
            "hold_release": ["SO-… on hold"],
            "service_order": ["asset serial KS-…"],
            "wo_update_request": ["WO-…"],
            "wo_status_inquiry": ["WO-…"],
            "service_contract_request": ["SC-… contract"],
        },
        "active": True,
    },
    {
        "id": "no_multi_intent_ambiguity",
        "label": "No multi-intent ambiguity",
        "description": (
            "What it does: rewards clarity. Fires when the email has signals for "
            "exactly ONE canonical intent and no other intent's cues coexist strongly. "
            "Counterpart to multi_intent_ambiguity (the penalty).\n\n"
            "How to optimize:\n"
            "  • If you're seeing the system wrongly fire BOTH this and the "
            "    multi_intent_ambiguity penalty on the same email, the LLM is hedging "
            "    — tighten the prompt or raise this rule's threshold for matched=true.\n"
            "  • Don't raise default_delta beyond ~+0.15 — clearance is corroboration, "
            "    not the main signal. The triggers (subject / verb / id) should do the "
            "    primary work.\n"
            "  • Useful to keep this even at a small +0.05 default, because it gives "
            "    the LLM a way to express 'I see no contradicting signals' as a positive "
            "    rather than just the absence of a penalty."
        ),
        "kind": "clearance",
        "default_delta": 0.10,
        "per_intent_overrides": {},
        "active": True,
    },
    {
        "id": "attachment_consistent",
        "label": "Attachments consistent with intent",
        "description": (
            "What it does: rewards the chosen intent when the attachments match what "
            "that intent normally carries — PO PDF + BOM XLSX + ATP DOCX for a quote_to_"
            "order, asset list XLSX for a service_order, existing-contract PDF for "
            "service_contract_request.\n\n"
            "How to optimize:\n"
            "  • Raise the per-intent override on po_intake / quote_to_order / "
            "    service_order — emails with the right document set are very likely "
            "    real customer requests.\n"
            "  • Keep at 0.0 for wo_status_inquiry, general_inquiry, out_of_scope, "
            "    spam — these typically carry no attachments, and rewarding their "
            "    absence would be noise.\n"
            "  • If you start running synthetic-attachment phishing tests, lower this "
            "    rule's delta or add an upstream rule that looks at the attachment "
            "    sender chain."
        ),
        "kind": "trigger",
        "default_delta": 0.05,
        "per_intent_overrides": {
            "po_intake": 0.10,
            "quote_to_order": 0.10,
            "service_order": 0.07,
            "wo_status_inquiry": 0.0,
            "general_inquiry": 0.0,
            "out_of_scope": 0.0,
            "spam": 0.0,
        },
        "examples": {
            "po_intake": ["PO PDF", "BOM XLSX", "ATP DOCX"],
            "quote_to_order": ["PO PDF (against quote)", "BOM XLSX"],
            "service_order": ["asset list XLSX", "spec PDF"],
            "service_contract_request": ["existing contract PDF"],
        },
        "active": True,
    },
    # ---- penalties --------------------------------------------------------
    {
        "id": "multi_intent_ambiguity",
        "label": "Multi-intent ambiguity penalty",
        "description": (
            "What it does: drops confidence when two or more canonical intents both "
            "score plausibly (e.g., body mentions both 'PO attached' and 'change order' "
            "for an existing order). Forces the pipeline to L2 / L3 HITL so a human "
            "can disambiguate.\n\n"
            "How to optimize:\n"
            "  • Make this MORE negative (e.g. -0.30) if you're seeing the system "
            "    auto-process emails that should have routed to a CSR for clarification.\n"
            "  • Make it LESS negative (e.g. -0.10) if too many genuinely-clear emails "
            "    are being held in HITL because the LLM hedges on multi-intent.\n"
            "  • Pairs with no_multi_intent_ambiguity (the clearance reward). The two "
            "    should be mutually exclusive — if both fire on the same email, your "
            "    LLM is hedging."
        ),
        "kind": "penalty",
        "default_delta": -0.20,
        "per_intent_overrides": {},
        "active": True,
    },
    {
        "id": "vague_or_generic_body",
        "label": "Vague or generic body",
        "description": (
            "What it does: drops confidence when the body is too short / too generic "
            "to safely infer intent (e.g., 'please advise', 'see attached', three-line "
            "follow-ups). Forces longer, vaguer emails through human review.\n\n"
            "How to optimize:\n"
            "  • Lower the magnitude (e.g. -0.05) for general_inquiry / out_of_scope — "
            "    these intents are EXPECTED to have generic bodies, so penalizing them "
            "    makes too many of them go to HITL unnecessarily. The current overrides "
            "    already do this.\n"
            "  • Raise the magnitude (e.g. -0.25) for all other intents if you're seeing "
            "    L4 auto-processing of emails that turned out to be misclassified — "
            "    forcing more HITL on short-body emails will catch those.\n"
            "  • The LLM decides 'matched' — define your bar in the rubric prompt by "
            "    putting examples in the rule's `examples` field."
        ),
        "kind": "penalty",
        "default_delta": -0.15,
        "per_intent_overrides": {
            "general_inquiry": -0.05,
            "out_of_scope": -0.05,
        },
        "active": True,
    },
    {
        "id": "contradictory_attachment",
        "label": "Attachment contradicts the inferred intent",
        "description": (
            "What it does: drops confidence when the attachments are inconsistent "
            "with the chosen intent — quote_to_order intent without a quote "
            "reference in any attachment, PO PDF without line items, service_order "
            "without an asset list. Catches misrouted attachments and badly-scanned "
            "PDFs that confused the extractor.\n\n"
            "How to optimize:\n"
            "  • Make MORE negative (e.g. -0.20) for po_intake / quote_to_order / "
            "    service_order — these MUST have consistent attachments to be "
            "    L4-eligible. The current overrides already bump these to -0.15.\n"
            "  • Keep at the default for inquiries / spam / out_of_scope — they "
            "    don't need attachment consistency.\n"
            "  • If you're seeing this fire on emails where the LLM simply missed "
            "    the reference (it WAS in the body but extraction missed it), the "
            "    fix isn't here — tune the extract_schema rule for that intent."
        ),
        "kind": "penalty",
        "default_delta": -0.10,
        "per_intent_overrides": {
            "po_intake": -0.15,
            "quote_to_order": -0.15,
        },
        "active": True,
    },
]


def all_rules() -> list[dict[str, Any]]:
    """Return all rubric rules — used by the seeder."""
    return INTENT_CONFIDENCE_RUBRIC_RULES
