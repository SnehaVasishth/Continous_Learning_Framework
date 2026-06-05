"""Knowledge Base — user-editable rules consumed by the agents at request time.

Two namespaces ship today:

* `intent` — one rule per intent in the taxonomy. body shape:
    {
      "description": str,        # the prose definition the LLM sees
      "track_hint": "trade" | "som" | "service_contract" | "none",
      "priority": int,           # ordering hint (lower = checked first)
      "examples_positive": [str],
      "examples_negative": [str],
    }

* `extract_schema` — one rule per extraction schema. body shape:
    {
      "system_prompt": str,
      "applies_to_intents": [str],
      "fields": [
        {"name": str, "type": str, "required": bool, "description": str}
      ]
    }

Agents call `intake_intent_rules()` / `extract_schema_for(intent)` from this module.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .config import INTENT_DESCRIPTIONS
from .db import SessionLocal
from .models import KnowledgeRule


# ---------- defaults ----------

_INTENT_TRACK = {
    "po_intake": "trade",
    "quote_to_order": "trade",
    "trade_change_order": "trade",
    "ssd_change_request": "trade",
    "hold_release": "trade",
    "delivery_change": "trade",
    "service_order": "som",
    "wo_update_request": "som",
    "wo_status_inquiry": "som",
    "service_contract_request": "service_contract",
    "general_inquiry": "none",
    "out_of_scope": "none",
    "spam": "none",
    # === v1.1 TASK-1 START === redirect/discard intents (track="none")
    "kso": "none",
    "collections": "none",
    "portal_admin": "none",
    "brazil_tax": "none",
    "undeliverable": "none",
    # === v1.1 TASK-1 END ===
}

_INTENT_EXAMPLES = {
    "po_intake": {
        "positive": [
            "Please find attached our purchase order PO-XXXX. Kindly issue the SOA.",
            "新規発注書 PO-XXXX を添付いたします。",
        ],
        "negative": [
            "Our PO references existing quote QT-XXX — that's quote_to_order, not po_intake.",
        ],
    },
    "quote_to_order": {
        "positive": [
            "Please convert quote QT-XXX into an order using the attached PO and BOM.",
        ],
        "negative": [
            "A fresh PO with no quote_number is po_intake.",
        ],
    },
    "trade_change_order": {
        "positive": [
            "Increase qty on line 1 of our existing order SO-XXX from 2 to 3 units.",
            "Cancel line item SKU-XYZ on SO-XXX and add a new line for E36312A at the quoted price.",
            "Negotiated unit-price revision on line 2 of SO-XXX.",
        ],
        "negative": [
            "Just changing the ship date on an existing order is ssd_change_request.",
            "Changing the ship-to address, carrier, or Incoterm is delivery_change, NOT trade_change_order.",
            "Releasing an order from credit, compliance, or quality hold is hold_release.",
        ],
    },
    "ssd_change_request": {
        "positive": [
            "Push out the requested ship date for SO-XXX by 2 weeks.",
            "Pull in our recent UXR scope order — NPI gating slot opened earlier.",
        ],
        "negative": [
            "Changing the ship-to address or carrier (not the date) is delivery_change.",
        ],
    },
    "delivery_change": {
        "positive": [
            "Change ship-to address on SO-XXX — we're relocating our test lab.",
            "Switch carrier on SO-XXX from FedEx to DHL Express, our consolidator is offering better rates.",
            "Update Incoterm on SO-XXX from EXW to DAP.",
            "Add dock-door gate codes and hazmat handling instructions to the delivery on SO-XXX.",
            "Split shipment of SO-XXX — half the lines to Auburn Hills, half to Phoenix.",
        ],
        "negative": [
            "Moving the ship DATE earlier or later is ssd_change_request, not delivery_change.",
            "Changing line item quantities, prices, or SKUs is trade_change_order.",
        ],
    },
    "hold_release": {
        "positive": [
            "AP team confirmed the credit hold on SO-XXX has been resolved. Please release.",
            "Trade compliance has approved the EAR99 classification. Please clear the hold.",
            "Invoice INV-XXXX cleared, please release the hold on SO-XXX and ship.",
            "BIS license approval received — please release the export hold on SO-XXX.",
        ],
        "negative": [
            "Changing the ship date on an existing order is ssd_change_request.",
            "Changing the ship-to or carrier is delivery_change.",
        ],
    },
    "service_order": {
        "positive": [
            "Annual cal request — ISO 17025 / A2LA traceable, 2 assets.",
            "Multi-asset cal request — 6 instruments, on-site, ISO 17025 / A2LA.",
        ],
        "negative": [
            "Asking about an EXISTING work order is wo_update_request or wo_status_inquiry.",
        ],
    },
    "wo_update_request": {
        "positive": [
            "Add 2 more assets to the open cal job (WO-XXX).",
        ],
        "negative": [],
    },
    "wo_status_inquiry": {
        "positive": [
            "URGENT: WO status needed — customer audit Friday.",
            "作業指示のステータス確認 (校正対象 OOT 含む)",
        ],
        "negative": [],
    },
    "service_contract_request": {
        "positive": [
            "Service contract quote request — 3-yr Cal Plan, 12 assets, Z540.3 + on-site.",
            "Plan PM con cal A2LA, SLA Gold, ~8 instrumentos.",
        ],
        "negative": [
            "Single one-off cal request is service_order, not service_contract_request.",
        ],
    },
    "general_inquiry": {
        "positive": [
            "What's the EOL roadmap for the E5071C?",
        ],
        "negative": [],
    },
    "out_of_scope": {
        "positive": [
            "Google account-security notification: 'App password created to sign in to your account'.",
            "Forwarded marketing newsletter from a known sender — 'Work faster with AI built into Google Workspace, try free for 14 days'.",
            "LinkedIn invitation: 'X wants to connect with you on LinkedIn'.",
            "Internal HR reminder: 'Open enrollment closes Friday — log into Workday'.",
            "AWS billing notification: 'Your AWS invoice is now available'.",
            "GitHub PR notification: 'New review requested on pull request #1234'.",
            "Calendar invite from a Keysight teammate.",
            "Out-of-office auto-reply from a customer contact.",
        ],
        "negative": [
            "Customer asking a real product question (lead time, EOL roadmap, product info) is general_inquiry, not out_of_scope.",
            "Phishing / unknown-sender wire-fraud / lookalike-domain credential traps are spam, not out_of_scope.",
        ],
    },
    "spam": {
        "positive": [
            "URGENT: account verification required to release pending wire — phishing.",
            "Lookalike-domain payment-redirect: 'Our banking details have changed, please update remit-to'.",
            "Promotional blast from an unknown sender: '🎉 70% OFF lab instruments — TODAY ONLY'.",
        ],
        "negative": [
            "Promotional emails from KNOWN/legit brands (Google, Microsoft, AWS, LinkedIn) are out_of_scope, not spam.",
            "Forwarded newsletters from established providers are out_of_scope.",
            "Account-security notifications from known providers (Google, MS) are out_of_scope.",
        ],
    },
}


def _intent_default(intent: str) -> dict:
    """Build the default body for an intent KB rule.

    When the v2 schema-driven definition exists for this intent (in
    `kb_seeds/intent_definitions_v2.py`), merge those richer fields in:
    `category` (9-class POC alignment), `keywords`, `sender_patterns`,
    `regions`, `exceptions` (verbatim excerpts from the prior POC's 25KB
    override book), `exclusions`. Otherwise fall back to the v1 shape so
    older intents stay compatible.
    """
    ex = _INTENT_EXAMPLES.get(intent, {})
    base = {
        "description": INTENT_DESCRIPTIONS.get(intent, ""),
        "track_hint": _INTENT_TRACK.get(intent, "none"),
        "priority": 5,
        "examples_positive": ex.get("positive") or [],
        "examples_negative": ex.get("negative") or [],
    }
    try:
        # all_definitions() merges in the rfp_rubric field from the seed so
        # the verifier's LLM second-opinion check can pull it at runtime.
        from .kb_seeds.intent_definitions_v2 import all_definitions
        v2 = all_definitions().get(intent)
        if v2:
            for k, v in v2.items():
                base[k] = v
    except Exception:
        pass
    return base


_PO_FIELDS = [
    {"name": "po_number", "type": "string", "required": True, "description": "PO identifier from email or attachment header"},
    {"name": "quote_number", "type": "string", "required": False, "description": "Referenced quote ID (Q-… / QT-… / QUOTE-…) — pull from email body, BOM, or PO header"},
    {"name": "customer_name", "type": "string", "required": True, "description": "Customer legal entity name as printed on the PO"},
    {"name": "requested_ship_date", "type": "ISO date", "required": False, "description": "Customer's requested ship date"},
    {"name": "payment_terms", "type": "string", "required": False, "description": "Net 30 / Net 45 / Net 60 / etc."},
    {"name": "bill_to", "type": "string", "required": False, "description": "Bill-to address"},
    {"name": "ship_to", "type": "string", "required": False, "description": "Ship-to address"},
    {"name": "line_items", "type": "list", "required": True, "description": "Array of {sku, description, qty, unit_price}"},
    {"name": "total", "type": "number", "required": True, "description": "PO grand total"},
    {"name": "notes", "type": "string", "required": False, "description": "Free-text notes from the PO or email"},
]

_OPS_FIELDS = [
    {"name": "order_number", "type": "string", "required": False, "description": "Existing order ID (SO-…)"},
    {"name": "quote_number", "type": "string", "required": False, "description": "Referenced quote ID"},
    {"name": "work_order_number", "type": "string", "required": False, "description": "Existing WO ID"},
    {"name": "asset_serial", "type": "string", "required": False, "description": "Customer asset serial number"},
    {"name": "requested_action", "type": "string", "required": True, "description": "Short imperative phrase describing what the customer wants"},
    {"name": "new_ship_date", "type": "ISO date", "required": False, "description": "Customer-requested new ship date"},
    {"name": "service_type", "type": "string", "required": False, "description": "calibration / repair / installation"},
]

_HOLD_RELEASE_FIELDS = [
    {"name": "order_number", "type": "string", "required": True, "description": "Existing order on hold (SO-…)"},
    {"name": "customer_po", "type": "string", "required": False, "description": "Customer's PO reference"},
    {"name": "hold_type", "type": "enum: credit | export_compliance | tax | customer_request | quality | other", "required": True, "description": "Nature of the hold"},
    {"name": "hold_reason", "type": "string", "required": True, "description": "Free-text reason the order was put on hold, as stated by Keysight or by the customer"},
    {"name": "clearance_reference", "type": "string", "required": False, "description": "Reference to whatever resolved the hold: credit-memo number, ECCN approval ID, tax exemption certificate ID, customer go-ahead email reference, QA sign-off ID"},
    {"name": "release_authorization", "type": "string", "required": False, "description": "Who authorized the release (named individual or team)"},
    {"name": "requested_release_date", "type": "ISO date", "required": False, "description": "When the customer wants the order released"},
    {"name": "notes", "type": "string", "required": False, "description": "Additional context from the email"},
]

_DELIVERY_CHANGE_FIELDS = [
    {"name": "order_number", "type": "string", "required": True, "description": "Existing order whose delivery is changing (SO-…)"},
    {"name": "customer_po", "type": "string", "required": False, "description": "Customer's PO reference"},
    {"name": "change_kind", "type": "enum: address | carrier | incoterm | delivery_instructions | partial_split", "required": True, "description": "What aspect of delivery is changing. Distinct from SSD which is about dates."},
    {"name": "new_ship_to_address", "type": "string", "required": False, "description": "Updated ship-to address"},
    {"name": "new_carrier", "type": "string", "required": False, "description": "Updated carrier preference (FedEx, DHL, UPS, etc.)"},
    {"name": "new_incoterm", "type": "string", "required": False, "description": "Updated Incoterm (EXW, FCA, DAP, etc.)"},
    {"name": "delivery_instructions", "type": "string", "required": False, "description": "New special-handling notes (gate codes, dock hours, hazmat)"},
    {"name": "split_lines", "type": "list", "required": False, "description": "If change_kind=partial_split, an array of {sku, qty, ship_to} per resulting split"},
    {"name": "reason", "type": "string", "required": True, "description": "Customer's stated reason for the change"},
]

_CHANGE_ORDER_FIELDS = [
    {"name": "order_number", "type": "string", "required": True, "description": "Existing order to modify (SO-…)"},
    {"name": "customer_po", "type": "string", "required": False, "description": "Customer's PO reference"},
    {"name": "requested_action", "type": "string", "required": True, "description": "Short imperative summary of all changes"},
    {"name": "line_changes", "type": "list", "required": True, "description": "Array of {sku, change_kind: qty|price|add|remove|swap, new_qty, new_unit_price, new_sku, reason}"},
    {"name": "new_bill_to", "type": "string", "required": False, "description": "Updated bill-to if requested"},
    {"name": "new_ship_to", "type": "string", "required": False, "description": "Updated ship-to if requested"},
]

_SSD_FIELDS = [
    {"name": "order_number", "type": "string", "required": False, "description": "Existing order to reschedule"},
    {"name": "current_ship_date", "type": "ISO date", "required": False, "description": "Current scheduled ship date"},
    {"name": "new_ship_date", "type": "ISO date", "required": True, "description": "Customer-requested new ship date"},
    {"name": "direction", "type": "enum: push_out | pull_in | partial", "required": True, "description": "Whether the change is later, earlier, or splits the shipment"},
    {"name": "reason", "type": "string", "required": True, "description": "Customer's stated reason"},
]

_SOM_CREATE_FIELDS = [
    {"name": "service_type", "type": "enum: calibration | repair | installation | on_site_service | pm", "required": True, "description": "Type of service requested"},
    {"name": "standards_referenced", "type": "list[string]", "required": False, "description": "e.g. [ISO/IEC 17025, ANSI/NCSL Z540.3, A2LA]"},
    {"name": "assets", "type": "list", "required": True, "description": "Array of {asset_serial, sku, description, location, last_cal_date, oot_observed, notes} — ONE entry per asset; multi-asset emails fan out to multiple WOs"},
    {"name": "requested_completion_date", "type": "ISO date", "required": False, "description": "When the customer needs the work done"},
    {"name": "on_site_required", "type": "bool", "required": True, "description": "True if customer requested on-site / field service"},
    {"name": "po_reference", "type": "string", "required": False, "description": "Customer's PO covering this service"},
    {"name": "contract_reference", "type": "string", "required": False, "description": "Service contract this falls under"},
]

_SOM_UPDATE_FIELDS = [
    {"name": "work_order_number", "type": "string", "required": False, "description": "Existing WO to update"},
    {"name": "order_number", "type": "string", "required": False, "description": "Related order if customer references it instead"},
    {"name": "requested_action", "type": "string", "required": True, "description": "Short imperative summary"},
    {"name": "add_assets", "type": "list", "required": False, "description": "Additional assets to attach to the WO"},
    {"name": "add_note", "type": "string", "required": False, "description": "Free-text note to append to the WO"},
    {"name": "add_task", "type": "string", "required": False, "description": "New task to add"},
]

_SOM_INQUIRY_FIELDS = [
    {"name": "work_order_numbers", "type": "list[string]", "required": False, "description": "Specific WO IDs the customer is asking about"},
    {"name": "asset_serials", "type": "list[string]", "required": False, "description": "Asset serials referenced"},
    {"name": "customer_po", "type": "string", "required": False, "description": "Customer PO reference"},
    {"name": "requested_info", "type": "enum: status | eta | as_found_data | cert_expiry | all", "required": True, "description": "Which information the customer wants"},
    {"name": "urgency", "type": "enum: urgent | normal | low", "required": True, "description": "Driven by language like URGENT, ASAP, audit Friday"},
]

_SERVICE_CONTRACT_FIELDS = [
    {"name": "contract_type", "type": "enum: calibration_plan | onsite_service_plan | pm_plan | warranty_extension | unknown", "required": True, "description": "Type of service contract"},
    {"name": "requested_action", "type": "enum: quote | renew | order | info", "required": True, "description": "What the customer is asking for"},
    {"name": "existing_contract_number", "type": "string", "required": False, "description": "If they reference an existing contract"},
    {"name": "asset_count_estimate", "type": "int", "required": False, "description": "Customer's estimate of assets to cover"},
    {"name": "included_skus", "type": "list[string]", "required": False, "description": "SKUs they want covered"},
    {"name": "term_months", "type": "int", "required": False, "description": "Contract term in months"},
    {"name": "sla_tier_requested", "type": "string", "required": False, "description": "Platinum / Gold / Silver"},
    {"name": "start_date", "type": "ISO date", "required": False, "description": "When the contract should begin"},
]


_TRANSLATION_RULES: list[dict] = [
    {
        "key": "preserve_skus_partnumbers",
        "label": "Preserve SKUs and part numbers verbatim",
        "description": "Keysight SKUs (E5071C, MXA, N9020B-526, etc.) must NEVER be translated. Treat as opaque tokens.",
        "body": {
            "kind": "preserve_verbatim",
            "patterns": [
                r"\\b[A-Z]\\d{4,5}[A-Z]?\\b",
                r"\\b[A-Z]{2,4}\\d{2,4}[A-Z]?\\b",
                r"\\bN\\d{4}[A-Z]?(-\\d+[A-Z]?)?\\b",
                r"\\bM\\d{4}[A-Z]\\b",
                r"\\b(MXA|EXA|UXA|UXR|FieldFox|InfiniiVision|Truevolt|Trueform|Streamline)\\b"
            ],
            "rationale": "Translating product codes breaks downstream entity resolution against Salesforce Product2.",
        },
    },
    {
        "key": "preserve_acronyms",
        "label": "Preserve domain acronyms verbatim",
        "description": "SOA, PO, Q2O, SSD, WO, ECCN, EAR, ITAR, A2LA, ISO, Z540.3, MIL-STD, AS9100 — keep as-is.",
        "body": {
            "kind": "preserve_verbatim",
            "terms": ["SOA", "PO", "Q2O", "SSD", "WO", "ECCN", "EAR99", "EAR", "ITAR", "A2LA", "ISO 17025", "Z540.3", "ANSI/NCSL", "MIL-STD-461", "MIL-STD-810", "AS9100", "IATF 16949", "ISO 26262", "BERT", "VNA", "DSO"],
            "rationale": "These are universal industry-standard tokens; translating them creates ambiguity.",
        },
    },
    {
        "key": "preserve_quote_order_ids",
        "label": "Preserve quote / PO / order IDs verbatim",
        "description": "PO-FOO-123, QT-BAR-998, SO-XYZ-456 patterns — never translate.",
        "body": {
            "kind": "preserve_verbatim",
            "patterns": [
                r"\\b(PO|Q|QT|QUOTE|SO|WO|INV|CCC|CC|CR)-[A-Z0-9-]+\\b",
            ],
            "rationale": "Order references are reconciliation keys; translating breaks Stage 3 reconcile against Salesforce Quote.QuoteNumber / Order.OrderNumber / Order.PoNumber.",
        },
    },
    {
        "key": "tone_business_formal",
        "label": "Tone: business formal in target language",
        "description": "Translations should use formal register (vous in French, usted in Spanish, keigo in Japanese).",
        "body": {
            "kind": "tone_guidance",
            "instruction": "Use formal business register. Spanish: usted form. Japanese: keigo (敬語). German: Sie form. French: vous form.",
            "rationale": "Customer-facing replies need to match B2B formality conventions.",
        },
    },
    {
        "key": "currency_localization",
        "label": "Localize currency formatting (preserve amounts)",
        "description": "$1,200 USD → ¥175,000 (formatting), but keep the underlying amount as the original currency unless the customer explicitly asked for FX conversion.",
        "body": {
            "kind": "format_guidance",
            "instruction": "Reformat number grouping per locale (1.000,00 in DE/ES, 1,000.00 in EN). Do NOT convert currency unless explicitly requested.",
            "rationale": "Auto-converting currency creates billing reconciliation problems.",
        },
    },
    {
        "key": "keysight_brand_capitalization",
        "label": "Keysight brand capitalization",
        "description": "Always 'Keysight Technologies' (proper noun). Don't lowercase or translate the company name.",
        "body": {
            "kind": "preserve_verbatim",
            "terms": ["Keysight", "Keysight Technologies"],
            "rationale": "Brand consistency.",
        },
    },
]


_BUSINESS_RULES: list[dict] = [
    {
        "key": "tcv_threshold_500k",
        "label": "TCV threshold — $500k requires HITL",
        "description": "Any order above $500k requires CSR review even with high confidence.",
        "body": {
            "predicate": "total > 500000",
            "severity": "cap_at_0.88",
            "message": "Order TCV exceeds $500k threshold — capping confidence to force one-click review.",
            "applies_to_intents": ["po_intake", "quote_to_order", "trade_change_order"],
            "region": [],
            "priority": 10,
            "active": True,
        },
    },
    {
        "key": "tcv_threshold_2m",
        "label": "TCV threshold — $2M requires full review",
        "description": "Any order above $2M is hard-blocked from auto-action.",
        "body": {
            "predicate": "total > 2000000",
            "severity": "cap_at_0.70",
            "message": "Order TCV exceeds $2M — full HITL review required.",
            "applies_to_intents": ["po_intake", "quote_to_order", "trade_change_order"],
            "region": [],
            "priority": 5,
            "active": True,
        },
    },
    {
        "key": "itar_export_gate",
        "label": "ITAR-flagged customer — manual review",
        "description": "Customers with ITAR compliance flag require export-control review on every order.",
        "body": {
            "predicate": "'ITAR' in compliance",
            "severity": "cap_at_0.88",
            "message": "Customer is ITAR-flagged — export-control review required before fulfillment.",
            "applies_to_intents": ["po_intake", "quote_to_order", "trade_change_order", "service_order"],
            "region": [],
            "priority": 1,
            "active": True,
        },
    },
    {
        "key": "ear_export_gate",
        "label": "EAR-flagged customer — compliance gate",
        "description": "Customers with EAR compliance flag require export classification check.",
        "body": {
            "predicate": "'EAR' in compliance",
            "severity": "warn",
            "message": "Customer is EAR-flagged — verify ECCN classification before shipment.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 2,
            "active": True,
        },
    },
    {
        "key": "credit_hold_block",
        "label": "Customer on credit hold — hard block",
        "description": "Customers on credit hold cannot receive new orders.",
        "body": {
            "predicate": "'CREDIT_HOLD' in compliance",
            "severity": "hard_block",
            "message": "Customer is on credit hold — order must not be auto-created.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 0,
            "active": True,
        },
    },
    {
        "key": "discount_tolerance_5pct",
        "label": "Discount tolerance — >5% requires review",
        "description": "PO unit price more than 5% below quote requires CSR confirmation.",
        "body": {
            "predicate": "discount_pct > 0.05",
            "severity": "cap_at_0.88",
            "message": "Discount exceeds 5% tolerance — verify against quoted pricing.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 8,
            "active": True,
        },
    },
    {
        "key": "payment_terms_whitelist",
        "label": "Payment terms whitelist (Net 30/45/60)",
        "description": "Non-standard payment terms require finance approval.",
        "body": {
            "predicate": "payment_terms not in ['Net 30', 'Net 45', 'Net 60']",
            "severity": "cap_at_0.88",
            "message": "Non-standard payment terms — finance approval required.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 12,
            "active": True,
        },
    },
    {
        "key": "named_account_l2",
        "label": "Named accounts — always HITL",
        "description": "Strategic accounts always go through CSR review regardless of confidence.",
        "body": {
            "predicate": "customer_code in ['RTHN-AERO-014', 'BLUEH-DEF-021']",
            "severity": "cap_at_0.88",
            "message": "Strategic account — CSR review required.",
            "applies_to_intents": ["po_intake", "quote_to_order", "trade_change_order"],
            "region": [],
            "priority": 7,
            "active": True,
        },
    },
    {
        "key": "eol_sku_block",
        "label": "End-of-life SKU — block",
        "description": "Orders containing EOL SKUs cannot be auto-processed.",
        "body": {
            "predicate": "any_eol_sku == True",
            "severity": "cap_at_0.70",
            "message": "Order contains EOL SKU — substitution or quote refresh required.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 6,
            "active": True,
        },
    },
    {
        "key": "apac_strict_threshold",
        "label": "APAC region — stricter threshold ($250k)",
        "description": "APAC trade orders above $250k require regional review.",
        "body": {
            "predicate": "total > 250000",
            "severity": "cap_at_0.88",
            "message": "APAC region threshold ($250k) exceeded — regional review required.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": ["APAC"],
            "priority": 11,
            "active": True,
        },
    },
    # Phase D5 — five new operator-tunable business rules.
    {
        "key": "calibration_overdue_block",
        "label": "Calibration overdue >30 days — service order needs specialist routing",
        "description": (
            "Asset due for calibration overdue by >30 days — service order should not "
            "auto-route to a generic team. Force one-click review so a calibration lead "
            "reviews the technician/team assignment before the WO is created."
        ),
        "body": {
            "predicate": "intent == 'service_order' and any(days_since(a.calibration_due_date) > 30 for a in installed_base)",
            "severity": "cap_at_0.70",
            "message": "Asset calibration overdue >30 days — assign to calibration specialist team.",
            "applies_to_intents": ["service_order", "wo_update_request"],
            "region": [],
            "priority": 4,
            "active": True,
        },
    },
    {
        "key": "credit_utilization_high",
        "label": "Credit utilization >80% — finance review",
        "description": (
            "Customer credit utilization above 80% — order needs finance review even if "
            "all other signals are clean. Computed as order_total / Account.Credit_Limit_USD__c "
            "when both are present; rule no-ops on accounts without a credit_limit set."
        ),
        "body": {
            "predicate": "credit_utilization_pct > 0.80",
            "severity": "cap_at_0.88",
            "message": "Credit utilization >80% of account limit — finance review required.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 9,
            "active": True,
        },
    },
    {
        "key": "asset_not_on_account",
        "label": "Service order references asset not on this account",
        "description": (
            "Service order references an asset serial that doesn't belong to this account "
            "in the installed base. Hard block — could indicate buyer error, account "
            "misidentification, or third-party / gray-market equipment we shouldn't service."
        ),
        "body": {
            "predicate": "intent == 'service_order' and any(a.asset_serial not in account_known_serials for a in extracted_assets)",
            "severity": "hard_block",
            "message": "Asset serial in request is not on this account's installed base — block.",
            "applies_to_intents": ["service_order"],
            "region": [],
            "priority": 3,
            "active": True,
        },
    },
    {
        "key": "after_hours_high_value",
        "label": "After-hours high-value order (>$50k between 22:00–06:00 UTC) — one-click",
        "description": (
            "Orders over $50k arriving outside business hours (22:00–06:00 UTC) get "
            "routed to one-click HITL even if confidence is high. Reduces wire-fraud "
            "and account-takeover risk on high-value transactions submitted during "
            "off-shift windows when fewer humans can sanity-check."
        ),
        "body": {
            "predicate": "total > 50000 and received_hour_utc >= 0 and (received_hour_utc >= 22 or received_hour_utc < 6)",
            "severity": "cap_at_0.88",
            "message": "After-hours order >$50k — one-click human approval required.",
            "applies_to_intents": ["po_intake", "quote_to_order"],
            "region": [],
            "priority": 13,
            "active": True,
        },
    },
    {
        "key": "ear_high_concentration_country",
        "label": "EAR-flagged customer + ship-to in sanctions-watch country — block",
        "description": (
            "EAR-flagged customer with ship-to in a high-concentration sanctions-watch "
            "country (CN, RU, IR) is hard-blocked. Forces export-compliance review "
            "before any auto-action — the combination of the two signals is a much "
            "stronger compliance flag than either signal alone."
        ),
        "body": {
            "predicate": "'EAR' in compliance and ship_to_country in ['CN', 'RU', 'IR']",
            "severity": "hard_block",
            "message": "EAR-flagged customer shipping to high-concentration country — export compliance must approve.",
            "applies_to_intents": ["po_intake", "quote_to_order", "service_order"],
            "region": [],
            "priority": 0,
            "active": True,
        },
    },
]


_EXTRACT_SCHEMAS: list[dict] = [
    {
        "key": "po_schema",
        "label": "Purchase Order schema",
        "description": "Used for new PO intake AND quote-to-order conversions. Reads PDFs, BOMs, scanned images.",
        "applies_to_intents": ["po_intake", "quote_to_order"],
        "system_prompt": (
            "You are a document-intelligence agent. Extract structured PO data from the email body and any provided "
            "attachments (text from PDFs, Excel BOMs, DOCX specs, or images). "
            "Important: quote_number is the referenced quote ID — usually starts with 'Q-', 'QT-', or 'QUOTE-'. "
            "Pull it whether mentioned in the email body, the BOM, or the PO. "
            "If a field is genuinely missing, use null. Do not invent values."
        ),
        "fields": _PO_FIELDS,
    },
    {
        "key": "ops_schema",
        "label": "Generic Ops schema",
        "description": "Fallback for general_inquiry — pulls actionable order/WO/asset references from free text.",
        "applies_to_intents": ["general_inquiry"],
        "system_prompt": (
            "You are an operations-fields extraction agent. Read the customer email and pull out actionable fields. "
            "Use null for any field not present. requested_action should be a short imperative phrase."
        ),
        "fields": _OPS_FIELDS,
    },
    {
        "key": "hold_release_schema",
        "label": "Hold Release schema",
        "description": "Customer or internal note asking to release an order from hold (credit / compliance / tax / customer / quality).",
        "applies_to_intents": ["hold_release"],
        "system_prompt": (
            "You are a Hold Release extraction agent. Identify which existing order is on hold, what kind of hold it is, "
            "and what evidence indicates the hold can be lifted. hold_type values: credit, export_compliance, tax, customer_request, quality, other. "
            "If a reference document or approval ID is mentioned that clears the hold, capture it in clearance_reference."
        ),
        "fields": _HOLD_RELEASE_FIELDS,
    },
    {
        "key": "delivery_change_schema",
        "label": "Delivery Change schema",
        "description": "Customer changing ship-to address, carrier, Incoterm, or delivery instructions on an existing order. Distinct from SSD which moves the date.",
        "applies_to_intents": ["delivery_change"],
        "system_prompt": (
            "You are a Delivery Change extraction agent. The customer is changing HOW or WHERE an existing order ships, NOT WHEN. "
            "change_kind values: address (ship-to change), carrier (FedEx/DHL/UPS swap), incoterm (EXW/FCA/DAP change), delivery_instructions (gate codes, dock hours, hazmat), partial_split (one order shipping to multiple addresses). "
            "If multiple lines are splitting to different addresses, populate split_lines."
        ),
        "fields": _DELIVERY_CHANGE_FIELDS,
    },
    {
        "key": "change_order_schema",
        "label": "Trade Change Order schema",
        "description": "Used when a customer asks to MODIFY an existing booked order (qty / price / line items / billing).",
        "applies_to_intents": ["trade_change_order"],
        "system_prompt": (
            "You are a Trade Sales Change Order extraction agent. Pull every change line-by-line. "
            "change_kind values: qty (quantity change), price (negotiated price change), add (add new line), "
            "remove (cancel line), swap (replace SKU). If the customer doesn't specify the order_number, "
            "leave it null — downstream will fuzzy-match by customer + customer_po."
        ),
        "fields": _CHANGE_ORDER_FIELDS,
    },
    {
        "key": "ssd_schema",
        "label": "Ship Schedule Date schema",
        "description": "Customer asking to push out / pull in / partial-split an existing order's ship date. SSD is about WHEN. Delivery Change is about WHERE / HOW.",
        "applies_to_intents": ["ssd_change_request"],
        "system_prompt": (
            "You are a Ship Schedule Date (SSD) change extraction agent. "
            "direction: push_out (later than current), pull_in (earlier than current), partial (split shipment). "
            "If multiple orders are referenced, choose the primary one for order_number and list affected SKUs in line_skus."
        ),
        "fields": _SSD_FIELDS,
    },
    {
        "key": "som_create_schema",
        "label": "Service Order — Create schema",
        "description": "New work order — calibration, repair, installation, on-site service. Supports MULTI-ASSET emails.",
        "applies_to_intents": ["service_order"],
        "system_prompt": (
            "You are a Service Order Management (SOM) extraction agent for NEW work-order creation requests. "
            "If the customer attaches a spreadsheet listing multiple instruments, return ONE object per asset in the assets[] array. "
            "Pull standards from the email — common references include ISO/IEC 17025, ANSI/NCSL Z540.3, A2LA, MIL-STD-810. "
            "on_site_required: true if they mention on-site / field service / 'come to our lab'."
        ),
        "fields": _SOM_CREATE_FIELDS,
    },
    {
        "key": "som_update_schema",
        "label": "Service Order — Update schema",
        "description": "Customer wants to update an EXISTING work order — add a note, add a task, attach more assets.",
        "applies_to_intents": ["wo_update_request"],
        "system_prompt": "You are a SOM update extraction agent. Customer is asking to update an EXISTING work order.",
        "fields": _SOM_UPDATE_FIELDS,
    },
    {
        "key": "som_inquiry_schema",
        "label": "Service Order — Status Inquiry schema",
        "description": "Customer asking for status / ETA / as-found data on existing work orders.",
        "applies_to_intents": ["wo_status_inquiry"],
        "system_prompt": (
            "You are a SOM status-inquiry extraction agent. Pull every WO number, asset serial, and PO ref the customer is asking about. "
            "urgency: 'urgent' if the email contains words like URGENT, ASAP, audit Friday, escalation; 'normal' otherwise."
        ),
        "fields": _SOM_INQUIRY_FIELDS,
    },
    {
        "key": "service_contract_schema",
        "label": "Service Contract schema",
        "description": "Customer asking about a service plan / cal contract / support agreement.",
        "applies_to_intents": ["service_contract_request"],
        "system_prompt": (
            "You are a service-contract extraction agent. Could be a quote request, renewal, order, or info question."
        ),
        "fields": _SERVICE_CONTRACT_FIELDS,
    },
]


# ---------- seeding ----------

def _seed_namespace_from_list(db: Session, namespace: str, rules: list[dict], seeded: dict) -> None:
    existing = {r.key: r for r in db.query(KnowledgeRule).filter_by(namespace=namespace).all()}
    seeded.setdefault(namespace, 0)
    for rule in rules:
        key = rule.get("id") or rule.get("key")
        if not key:
            continue
        body = dict(rule)
        body.pop("id", None)
        if key in existing:
            # Resync description / label / default_body for system-seeded rules whose body
            # the operator hasn't customized. We never touch `body` here — that's where
            # operator edits live. But description / label / default_body track the seed
            # so updated wording in the source code surfaces in the KB UI without forcing
            # the operator to re-seed manually.
            row = existing[key]
            new_desc = rule.get("description") or ""
            new_label = rule.get("label") or key
            changed = False
            if row.description != new_desc:
                row.description = new_desc
                changed = True
            if row.label != new_label:
                row.label = new_label
                changed = True
            if (row.default_body or {}) != body:
                row.default_body = body
                changed = True
            if changed:
                row.updated_by = "system_resync"
            continue
        db.add(
            KnowledgeRule(
                namespace=namespace,
                key=key,
                label=rule.get("label") or key,
                description=rule.get("description") or "",
                body=body,
                default_body=body,
                version=1,
                updated_by="system",
            )
        )
        seeded[namespace] += 1


def seed_defaults(db: Session) -> dict[str, int]:
    """Populate the KB with defaults if empty. Idempotent — won't overwrite existing rows."""
    seeded = {"intent": 0, "extract_schema": 0}

    from .kb_seeds.spam_heuristic_rules import SPAM_HEURISTIC_RULES
    from .kb_seeds.language_heuristic_rules import LANGUAGE_HEURISTIC_RULES, LANGUAGE_KEYWORD_LISTS
    from .kb_seeds.intent_confidence_rubric import all_rules as _intent_rubric_all_rules
    from .kb_seeds.language_confidence_rubric import all_rules as _lang_rubric_all_rules
    from .kb_seeds.decision_confidence_rubric import all_rules as _decision_rubric_all_rules
    from .kb_seeds.reconcile_checks import all_rules as _reconcile_checks_all_rules
    from .kb_seeds.translation_glossary import all_rules as _glossary_all_rules
    # === v1.1 TASK-2 START ===
    from .kb_seeds.outlook_rules import all_rules as _outlook_rules_all_rules
    # === v1.1 TASK-2 END ===
    # === v1.1 TASK-5 START ===
    from .kb_seeds.routing_rules import all_rules as _routing_rules_all_rules
    # === v1.1 TASK-5 END ===
    from .kb_seeds.owner_mapping import all_rules as _owner_mapping_all_rules
    from .kb_seeds.pipeline_verification_rules import all_rules as _verifier_all_rules
    from .kb_seeds.agent_prompts import all_rules as _agent_prompts_all_rules
    from .kb_seeds.threshold_rules import all_rules as _threshold_all_rules
    from .kb_seeds.detector_tuning import all_rules as _detector_tuning_all_rules
    _seed_namespace_from_list(db, "spam_heuristic", SPAM_HEURISTIC_RULES, seeded)
    _seed_namespace_from_list(db, "language_heuristic", LANGUAGE_HEURISTIC_RULES, seeded)
    _seed_namespace_from_list(db, "intent_confidence_rubric", _intent_rubric_all_rules(), seeded)
    _seed_namespace_from_list(db, "language_confidence_rubric", _lang_rubric_all_rules(), seeded)
    _seed_namespace_from_list(db, "decision_confidence_rubric", _decision_rubric_all_rules(), seeded)
    _seed_namespace_from_list(db, "reconcile_checks", _reconcile_checks_all_rules(), seeded)
    _seed_namespace_from_list(db, "translation_glossary", _glossary_all_rules(), seeded)
    # === v1.1 TASK-2 ===
    _seed_namespace_from_list(db, "outlook_rules", _outlook_rules_all_rules(), seeded)
    # === v1.1 TASK-5 ===
    _seed_namespace_from_list(db, "routing_rules", _routing_rules_all_rules(), seeded)
    # Case ownership — keyed by routing_key (fcnv_scope, som_csr, …). Resolved
    # at runtime by Stage 3.4 to populate decision.owner.salesforce_owner_id.
    _seed_namespace_from_list(db, "owner_mapping", _owner_mapping_all_rules(), seeded)
    # Pipeline verification — declarative invariants evaluated at stage_end +
    # at orchestrator close. Catches "Stage 5 must not draft a reply when AIOA
    # owns the case" and similar end-to-end correctness rules.
    _seed_namespace_from_list(db, "pipeline_verification_rules", _verifier_all_rules(), seeded)
    # === Continuous Learning targets — real KB rows the promote_ab_to_production
    # service writes to when a prompt-refinement or threshold experiment is
    # promoted. Without these the demo would be theatre.
    _seed_namespace_from_list(db, "agent_prompts", _agent_prompts_all_rules(), seeded)
    _seed_namespace_from_list(db, "threshold", _threshold_all_rules(), seeded)
    # Drift-detector sensitivity knobs (z thresholds, relative regressions,
    # PSI floors, minimum sample sizes). Editable by Continuous-Learning
    # admins; read at each detector tick via `services.detector_tuning.get`.
    _seed_namespace_from_list(db, "detector_tuning", _detector_tuning_all_rules(), seeded)
    # === v1.1 TASK-9 START === shadow classifier — DISABLED by default; flip enabled=true to A/B prompts.
    _shadow_seed = [{
        "key": "config",
        "label": "Shadow Classifier — config",
        "description": "Toggle and prompt for the third logged-only classifier pass. Enable when you want to A/B test a new prompt.",
        "enabled": False,
        "system_prompt": "",
        "notes": "Logged-only — output never reaches Decide/Execute. Use to measure agreement rate vs primary classifier before promoting a new prompt.",
    }]
    _seed_namespace_from_list(db, "shadow_classifier", _shadow_seed, seeded)
    # === v1.1 TASK-9 END ===

    existing_intent_rows = {r.key: r for r in db.query(KnowledgeRule).filter_by(namespace="intent").all()}
    for intent in _INTENT_TRACK.keys():
        body = _intent_default(intent)
        if intent in existing_intent_rows:
            # Resync v2 schema fields (category, keywords, sender_patterns,
            # exceptions, etc.) onto existing rows. We keep operator edits to
            # `description` / `examples_*` from the live `body` and only fill
            # in v2 fields that aren't present yet — so re-seeding adds the
            # POC's override-rule excerpts without clobbering tuning.
            row = existing_intent_rows[intent]
            live_body = dict(row.body or {})
            changed = False
            for k in ("category", "keywords", "sender_patterns", "regions", "exceptions", "exclusions", "rfp_rubric"):
                if k in body and live_body.get(k) != body[k]:
                    live_body[k] = body[k]
                    changed = True
            # default_body always reflects the latest seed.
            if (row.default_body or {}) != body:
                row.default_body = body
                changed = True
            if changed:
                row.body = live_body
                row.updated_by = "system_resync"
            continue
        db.add(
            KnowledgeRule(
                namespace="intent",
                key=intent,
                label=intent.replace("_", " ").title(),
                description="Editable definition the intake classifier uses for this intent.",
                body=body,
                default_body=body,
                version=1,
                updated_by="system",
            )
        )
        seeded["intent"] += 1

    existing_translation = {r.key for r in db.query(KnowledgeRule).filter_by(namespace="translation").all()}
    for rule in _TRANSLATION_RULES:
        if rule["key"] in existing_translation:
            continue
        db.add(
            KnowledgeRule(
                namespace="translation",
                key=rule["key"],
                label=rule["label"],
                description=rule["description"],
                body=rule["body"],
                default_body=rule["body"],
                version=1,
                updated_by="system",
            )
        )
        seeded.setdefault("translation", 0)
        seeded["translation"] += 1

    existing_business_rules = {r.key for r in db.query(KnowledgeRule).filter_by(namespace="business_rules").all()}
    for rule in _BUSINESS_RULES:
        if rule["key"] in existing_business_rules:
            continue
        db.add(
            KnowledgeRule(
                namespace="business_rules",
                key=rule["key"],
                label=rule["label"],
                description=rule["description"],
                body=rule["body"],
                default_body=rule["body"],
                version=1,
                updated_by="system",
            )
        )
        seeded.setdefault("business_rules", 0)
        seeded["business_rules"] += 1

    existing_schemas = {r.key for r in db.query(KnowledgeRule).filter_by(namespace="extract_schema").all()}
    for s in _EXTRACT_SCHEMAS:
        if s["key"] in existing_schemas:
            continue
        body = {
            "system_prompt": s["system_prompt"],
            "applies_to_intents": s["applies_to_intents"],
            "fields": s["fields"],
        }
        db.add(
            KnowledgeRule(
                namespace="extract_schema",
                key=s["key"],
                label=s["label"],
                description=s["description"],
                body=body,
                default_body=body,
                version=1,
                updated_by="system",
            )
        )
        seeded["extract_schema"] += 1

    db.commit()
    return seeded


# ---------- read helpers (used by agents at request time) ----------

def list_rules(db: Session, namespace: str) -> list[KnowledgeRule]:
    return db.query(KnowledgeRule).filter_by(namespace=namespace).order_by(KnowledgeRule.key).all()


def get_rule(db: Session, namespace: str, key: str) -> KnowledgeRule | None:
    return db.query(KnowledgeRule).filter_by(namespace=namespace, key=key).first()


def update_rule(
    db: Session, *, namespace: str, key: str, body: dict, label: str | None = None,
    description: str | None = None, updated_by: str = "csr"
) -> KnowledgeRule:
    row = get_rule(db, namespace, key)
    if not row:
        raise ValueError(f"rule not found: {namespace}/{key}")
    row.body = body
    if label is not None:
        row.label = label
    if description is not None:
        row.description = description
    row.version += 1
    row.updated_by = updated_by
    db.flush()
    db.commit()
    return row


def create_rule(
    db: Session, *, namespace: str, key: str, body: dict, label: str | None = None,
    description: str | None = None, updated_by: str = "csr",
) -> KnowledgeRule:
    """Insert a brand-new KB rule. The default_body is set to the supplied
    body so a future reset_rule returns to the operator-supplied baseline
    rather than a seed-time value that does not exist.
    """
    if not key or not key.strip():
        raise ValueError("key is required")
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    row = KnowledgeRule(
        namespace=namespace,
        key=key.strip(),
        label=label or key.strip(),
        description=description or "",
        body=body,
        default_body=body,
        version=1,
        updated_by=updated_by,
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def reset_rule(db: Session, *, namespace: str, key: str, updated_by: str = "csr") -> KnowledgeRule:
    row = get_rule(db, namespace, key)
    if not row:
        raise ValueError(f"rule not found: {namespace}/{key}")
    row.body = row.default_body or {}
    row.version += 1
    row.updated_by = updated_by
    db.flush()
    db.commit()
    return row


# ---------- agent-side accessors (cheap; read fresh per request) ----------

def intake_intent_rules() -> dict[str, dict[str, Any]]:
    """Returns {intent_key: rule_body} — used by intake.py to build SYSTEM."""
    db = SessionLocal()
    try:
        out: dict[str, dict] = {}
        for r in list_rules(db, "intent"):
            out[r.key] = r.body or {}
        return out
    finally:
        db.close()


def spam_heuristic_rules() -> list[dict[str, Any]]:
    """Returns the active spam_heuristic rule list (in deterministic key order)."""
    db = SessionLocal()
    try:
        out: list[dict] = []
        for r in list_rules(db, "spam_heuristic"):
            body = dict(r.body or {})
            body["id"] = r.key
            out.append(body)
        return out
    finally:
        db.close()


# === v1.1 TASK-5 START ===
def routing_rules() -> list[dict[str, Any]]:
    """Returns enabled routing rules sorted by priority (lowest first).

    Excludes reference rows (`is_reference=True` — disty lists, magic-SKU
    catalog) since those are data, not routing predicates.
    """
    db = SessionLocal()
    try:
        out: list[dict] = []
        for r in list_rules(db, "routing_rules"):
            body = dict(r.body or {})
            if not body.get("enabled", True):
                continue
            if body.get("is_reference"):
                continue
            body["id"] = r.key
            body["label"] = r.label
            body["description"] = r.description
            out.append(body)
        out.sort(key=lambda b: int(b.get("priority", 999)))
        return out
    finally:
        db.close()


def routing_reference_data() -> dict[str, Any]:
    """Returns the reference-data rows: disty partner lists + magic SKUs."""
    db = SessionLocal()
    try:
        out: dict[str, Any] = {}
        for r in list_rules(db, "routing_rules"):
            body = dict(r.body or {})
            if body.get("is_reference"):
                out[r.key] = body
        return out
    finally:
        db.close()
# === v1.1 TASK-5 END ===


# === v1.1 TASK-2 START ===
def outlook_rules() -> list[dict[str, Any]]:
    """Returns enabled Outlook pre-AI rules sorted by priority (lowest first).

    Used by `agents/pre_intake.py` to short-circuit the pipeline BEFORE Stage 1
    LLM calls fire. Each entry's body carries `priority`, `enabled`, `intent`,
    `predicates`, `actionable_exception`, `severity`, `redirect_to`.
    """
    db = SessionLocal()
    try:
        out: list[dict] = []
        for r in list_rules(db, "outlook_rules"):
            body = dict(r.body or {})
            if not body.get("enabled", True):
                continue
            body["id"] = r.key
            body["label"] = r.label
            body["description"] = r.description
            out.append(body)
        out.sort(key=lambda b: int(b.get("priority", 999)))
        return out
    finally:
        db.close()
# === v1.1 TASK-2 END ===


def language_heuristic_rules() -> list[dict[str, Any]]:
    """Returns the active language_heuristic rule list (in deterministic key order)."""
    db = SessionLocal()
    try:
        out: list[dict] = []
        for r in list_rules(db, "language_heuristic"):
            body = dict(r.body or {})
            body["id"] = r.key
            out.append(body)
        return out
    finally:
        db.close()


def language_confidence_rubric() -> dict[str, Any]:
    """Returns the language-confidence rubric in a usable shape — same shape as
    intent_confidence_rubric() but with `per_language_overrides` on each rule.

    Output:
      {
        "base": 0.40,
        "rules": [
          {"id": "script_definitive_match", "kind": "trigger", "default_delta": 0.50,
           "per_language_overrides": {"ja": 0.55, "es": 0.30, ...}, "label": ..., "description": ..., "examples": ...},
          ...
        ],
      }

    Triggers come first, then clearance, then penalties — same ordering as the
    intent rubric, so the trace UI renders both with the same template.
    """
    db = SessionLocal()
    try:
        rules = list_rules(db, "language_confidence_rubric")
        base = 0.40
        out_rules: list[dict[str, Any]] = []
        for r in rules:
            body = dict(r.body or {})
            body["id"] = r.key
            body.setdefault("label", r.label or r.key)
            body.setdefault("description", r.description or "")
            if not body.get("active", True):
                continue
            if body.get("kind") == "base" or r.key == "_base":
                base = float(body.get("value") or body.get("default_delta") or 0.40)
                continue
            out_rules.append(body)
        order = {"trigger": 0, "clearance": 1, "penalty": 2}
        out_rules.sort(key=lambda r: (order.get(r.get("kind") or "", 9), r.get("id") or ""))
        return {"base": base, "rules": out_rules}
    finally:
        db.close()


def intent_confidence_rubric() -> dict[str, Any]:
    """Returns the active intent-confidence rubric in a usable shape.

    Output:
      {
        "base": 0.50,                                    # the uninformed prior
        "rules": [                                       # ordered: triggers → clearance → penalties
          {"id": "subject_explicit_signal", "kind": "trigger",
           "default_delta": 0.30, "per_intent_overrides": {...}, "label": "...", "description": "...",
           "examples": {...}},
          ...
        ],
      }

    Operators tune individual rules from the Knowledge Base UI. The classifier
    reads this on every invocation, so changes take effect on the next pipeline.
    """
    db = SessionLocal()
    try:
        rules = list_rules(db, "intent_confidence_rubric")
        base = 0.50
        out_rules: list[dict[str, Any]] = []
        for r in rules:
            body = dict(r.body or {})
            body["id"] = r.key
            body.setdefault("label", r.label or r.key)
            body.setdefault("description", r.description or "")
            if not body.get("active", True):
                continue
            if body.get("kind") == "base" or r.key == "_base":
                base = float(body.get("value") or body.get("default_delta") or 0.50)
                continue
            out_rules.append(body)
        # Stable ordering: triggers first, then clearance, then penalties.
        order = {"trigger": 0, "clearance": 1, "penalty": 2}
        out_rules.sort(key=lambda r: (order.get(r.get("kind") or "", 9), r.get("id") or ""))
        return {"base": base, "rules": out_rules}
    finally:
        db.close()


def decision_confidence_rubric() -> dict[str, Any]:
    """Returns the active Stage-3 decision confidence rubric.

    Output:
      {
        "base": 0.0,
        "rules": [
          # weighted_signal rules (always evaluated, contribute weight × signal_var)
          {"id": "intent_confidence_signal", "kind": "weighted_signal",
           "weight": 0.45, "signal_var": "intent_confidence",
           "label": "...", "description": "...", "active": true},
          ...
          # floor_cap rules (predicate evaluated; cap applied if matched)
          {"id": "missing_po_number_cap", "kind": "floor_cap",
           "cap": 0.40, "predicate": "intent in [...] and not po_number",
           "applies_to_intents": [...], "label": "...", "description": "..."},
          ...
        ],
      }

    Stage 3.1 reads this on every invocation. Operators tune weights and
    caps from the Knowledge Base UI; changes take effect on the next
    pipeline."""
    db = SessionLocal()
    try:
        rules = list_rules(db, "decision_confidence_rubric")
        base = 0.0
        signals: list[dict[str, Any]] = []
        caps: list[dict[str, Any]] = []
        for r in rules:
            body = dict(r.body or {})
            body["id"] = r.key
            body.setdefault("label", r.label or r.key)
            body.setdefault("description", r.description or "")
            if not body.get("active", True):
                continue
            kind = body.get("kind")
            if kind == "base" or r.key == "_base":
                base = float(body.get("value") or 0.0)
                continue
            if kind == "weighted_signal":
                signals.append(body)
            elif kind == "floor_cap":
                caps.append(body)
        # Stable ordering: signals first (so the breakdown reads top-down),
        # then caps in priority order — exact_match_required first because it
        # is the strictest, then customer_match graduated, then intent-specific
        # caps. Operators can also override via an explicit "priority" key.
        signals.sort(key=lambda r: r.get("id") or "")
        caps.sort(key=lambda r: (r.get("priority", 50), r.get("id") or ""))
        return {"base": base, "rules": signals + caps, "signals": signals, "caps": caps}
    finally:
        db.close()


def reconcile_checks() -> dict[str, Any]:
    """Returns the active Stage-2.5 reconcile_checks rubric.

    Output:
      {
        "checks": [
          {"id": "line_unit_price_matches_quote", "kind": "rule",
           "scope": "per_line", "predicate": "abs(...)==0.01", "severity": "hard",
           "issue_kind": "price_mismatch", "fires_when": "predicate_false",
           "applies_to_intents": [...], "label": "...", "description": "..."},
          ...
        ],
      }

    Stage 2.5 reads this on every invocation. Operators tune predicates,
    severities, and active flags from the Knowledge Base UI; changes take
    effect on the next pipeline. Inactive rules are filtered out.
    """
    db = SessionLocal()
    try:
        rules = list_rules(db, "reconcile_checks")
        out: list[dict[str, Any]] = []
        for r in rules:
            body = dict(r.body or {})
            body["id"] = r.key
            body.setdefault("label", r.label or r.key)
            body.setdefault("description", r.description or "")
            if not body.get("active", True):
                continue
            out.append(body)
        # Stable order: per_line first (so trace UI shows line-level checks
        # together), then per_total. Within a scope, preserve seed order via
        # the rule id alphabetic tiebreaker.
        scope_order = {"per_line": 0, "per_total": 1}
        out.sort(key=lambda r: (scope_order.get(r.get("scope") or "", 9), r.get("id") or ""))
        return {"checks": out}
    finally:
        db.close()


def translation_glossary(
    *, target_language: str | None = None, direction: str | None = None
) -> dict[str, Any]:
    """Returns the active translation glossary, optionally filtered for a
    specific target language and direction.

    Args:
        target_language: ISO code ('en', 'es', 'ja'). When set, each returned
            term is paired with its canonical translation in that language.
            When None, the full multi-language map is returned.
        direction: 'inbound' (Stage 1.5: customer-language → English) or
            'outbound' (Stage 5: English → customer-language). When set,
            terms whose `applies_to` excludes that direction are filtered.

    Output:
      {
        "target_language": "ja",                           # echo of input
        "direction": "outbound",                           # echo of input
        "terms": [
          {
            "id": "calibration_certificate",
            "english": "calibration certificate",
            "translation": "校正証明書",                    # for target_language
            "translations": {"es": "...", "ja": "..."},    # full map
            "preserve_acronym": null,
            "domain": "service",
            "label": "Calibration certificate",
            "description": "...",
          }, ...
        ],
        "preserve_verbatim_terms": ["ECCN", "ITAR", ...],  # acronyms to never localize
        "active_count": int,
      }

    Stage 1.5 / 5.x reads this and injects formatted glossary lines into the
    LLM system prompt — see translate_tool::_format_glossary_for_prompt and
    communicate::_glossary_block.
    """
    db = SessionLocal()
    try:
        rules = list_rules(db, "translation_glossary")
        out: list[dict[str, Any]] = []
        verbatim: list[str] = []
        for r in rules:
            body = dict(r.body or {})
            body["id"] = r.key
            body.setdefault("label", r.label or r.key)
            body.setdefault("description", r.description or "")
            if not body.get("active", True):
                continue
            if direction:
                applies = body.get("applies_to") or ["inbound", "outbound"]
                if direction not in applies:
                    continue
            translations = body.get("translations") or {}
            entry = {
                "id": body["id"],
                "label": body["label"],
                "description": body["description"],
                "english": body.get("english") or "",
                "translations": translations,
                "domain": body.get("domain") or "general",
                "preserve_acronym": body.get("preserve_acronym"),
            }
            if target_language and target_language != "en":
                trans = translations.get(target_language)
                if not trans:
                    # No translation for this target — skip the term but
                    # surface its preserve_acronym (still useful as guidance).
                    if body.get("preserve_acronym"):
                        verbatim.append(body["preserve_acronym"])
                    continue
                entry["translation"] = trans
            elif target_language == "en":
                entry["translation"] = body.get("english") or ""
            if body.get("preserve_acronym"):
                verbatim.append(body["preserve_acronym"])
            out.append(entry)
        # Stable order: domain group first (compliance > trade > service > general),
        # then alphabetically by id within group.
        domain_order = {"compliance": 0, "trade": 1, "service": 2, "general": 3}
        out.sort(key=lambda e: (domain_order.get(e.get("domain") or "", 9), e.get("id") or ""))
        # Dedup verbatim while preserving order.
        seen: set[str] = set()
        verbatim_dedup: list[str] = []
        for v in verbatim:
            if v and v not in seen:
                seen.add(v)
                verbatim_dedup.append(v)
        return {
            "target_language": target_language,
            "direction": direction,
            "terms": out,
            "preserve_verbatim_terms": verbatim_dedup,
            "active_count": len(out),
        }
    finally:
        db.close()


def extract_schema_for(intent: str) -> dict[str, Any] | None:
    """Returns the active extract_schema rule body covering this intent, or None.
    If multiple schemas claim the intent, the one ordered first by key wins."""
    db = SessionLocal()
    try:
        for r in list_rules(db, "extract_schema"):
            applies = (r.body or {}).get("applies_to_intents") or []
            if intent in applies:
                return r.body
        return None
    finally:
        db.close()


def expected_fields_for_intent(intent: str) -> dict[str, list[str]]:
    """Resolve the intent's expected-field summary from the active extract_schema.

    Returns a dict like:
        {
          "required": ["po_number", "customer_name", "line_items", "total"],
          "optional": ["quote_number", "requested_ship_date", ...]
        }

    Used in three places that previously hard-coded the field list:
      1. Stage 1 intake classifier prompt — knowing what fields an intent
         typically carries lets the LLM cross-check whether the email actually
         looks like that intent or is closer to a near-miss.
      2. Stage 2 extraction agent — confirmation that all schema fields were
         attempted (the schema itself drives extraction; this helper just
         summarises required / optional for the trace UI).
      3. Stage 3 Action Feasibility gate — verifying every required field is
         present before allowing autonomous (L4) action. The gate dragged the
         composite confidence below the L4 threshold if any required field is
         missing, matching the deliverables' commitment that Action Feasibility
         is one of the four named gates and is enforced on every CRM/ERP write.

    Returns an empty {required: [], optional: []} if no schema is registered
    for the intent. Operators tune required-vs-optional in the KB UI by editing
    the extract_schema row; the next pipeline picks it up without redeploy.
    """
    body = extract_schema_for(intent) or {}
    fields = body.get("fields") or []
    required: list[str] = []
    optional: list[str] = []
    for f in fields:
        name = f.get("name")
        if not name:
            continue
        (required if f.get("required") else optional).append(name)
    return {"required": required, "optional": optional}
