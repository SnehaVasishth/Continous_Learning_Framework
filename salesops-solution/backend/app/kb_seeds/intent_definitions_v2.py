"""Schema-driven intent definitions — v2 (KB-rule-body-as-schema).

This replaces the v1 intent KB (which had only `description` + a couple of
example arrays) with a richer per-intent schema that the classify-intent
prompt is GENERATED FROM at request time. The classifier reads:

  - category          → 9-class taxonomy alignment with the prior Keysight POC
                        (KSO / ISC_WO_RTK / SALES_PO / UNDELIVERABLE /
                         COLLECTIONS / PORTAL_ADMIN / BRAZIL_TAX /
                         AUTO_REPLY / OTHERS)
  - track_hint        → workflow lane (trade / som / service_contract /
                                       discarded / general / none)
  - priority          → ordering hint (lower = checked first)
  - regions           → applicability (AMS / EMEA / APAC / JP / GLOBAL)
  - description       → prose definition (LLM rationale fodder)
  - keywords          → high-signal phrases the LLM treats as triggers
  - sender_patterns   → sender-domain or address patterns that bias toward
                        this intent
  - examples_positive → "yes-this-is-this-intent" worked examples
  - examples_negative → "no-this-is-NOT-this-intent" near-misses
  - exceptions        → operational rules from the prior POC's 25KB override
                        book that disqualify this intent or push to another
  - exclusions        → other disqualifying conditions

Operators tune any field in /kb without touching code; the next pipeline
picks up the new definition. The classify_intent prompt is regenerated from
the live KB on every request — no recompile, no redeploy.

The exceptions arrays incorporate verbatim summaries of the prior POC's
override-book rules (Rule 3, 3A, 7, 9, 13, 18A/B, 19, 20, 25 in particular)
so the classifier matches the operational logic Keysight already runs in
production.
"""
from __future__ import annotations

from typing import Any


# 9-class category alignment with the prior Keysight POC's taxonomy.
# Each fine-grained intent here maps into ONE of these top-level categories,
# which downstream surfaces (Ops dashboard, IMAP back-stamping folder map)
# group on.
INTENT_TO_CATEGORY: dict[str, str] = {
    "po_intake": "SALES_PO",
    "quote_to_order": "SALES_PO",
    "trade_change_order": "SALES_PO",
    "hold_release": "SALES_PO",
    "ssd_change_request": "OTHERS",
    "delivery_change": "OTHERS",
    "service_order": "ISC_WO_RTK",
    "wo_update_request": "ISC_WO_RTK",
    "wo_status_inquiry": "ISC_WO_RTK",
    "service_contract_request": "ISC_WO_RTK",
    "general_inquiry": "OTHERS",
    "out_of_scope": "AUTO_REPLY",
    "spam": "OTHERS",
    # === v1.1 TASK-1 START === 5 first-class intents per prior-POC 9-class taxonomy
    "kso": "KSO",
    "collections": "COLLECTIONS",
    "portal_admin": "PORTAL_ADMIN",
    "brazil_tax": "BRAZIL_TAX",
    "undeliverable": "UNDELIVERABLE",
    # === v1.1 TASK-1 END ===
}


INTENT_DEFINITIONS_V2: dict[str, dict[str, Any]] = {
    # -----------------------------------------------------------------
    # SALES_PO category
    # -----------------------------------------------------------------
    "po_intake": {
        "category": "SALES_PO",
        "track_hint": "trade",
        "priority": 1,
        "regions": ["GLOBAL"],
        "description": (
            "Customer sends a fresh purchase order with no prior quote referenced. "
            "Subject or body identifies a PO# and the customer expects acknowledgment + booking."
        ),
        "keywords": [
            "PO PO-",
            "purchase order",
            "kindly process",
            "please process the attached PO",
            "issue SOA",
            "acknowledge",
            "新規発注書",
            "OC PO-",
        ],
        "sender_patterns": ["procurement@", "buying@", "purchasing@", "orders@"],
        "examples_positive": [
            "Please find attached our purchase order PO-XXXX. Kindly issue the SOA.",
            "新規発注書 PO-XXXX を添付いたします。",
            "Approved – book under resale (Rule 18: conditional approval still SALES_PO)",
        ],
        "examples_negative": [
            "Our PO references existing quote QT-XXX — that's quote_to_order, not po_intake.",
            "PO# only appears inside an attachment named 'Sales Order Acknowledgement' — NOT a real PO (Rule 25).",
            "Email mentions 'PO' but with WO/Repair/Cal context — that's ISC_WO_RTK (Rule 3).",
        ],
        "exceptions": [
            "Rule 3 — PO mentioned alongside WO/Repair/Cal directives → classify as ISC_WO_RTK, not SALES_PO.",
            "Rule 3A — PO with `cal cert` / `factory calibration` / `with calibration` of a NEW unit → still SALES_PO (factory cal of new product is part of the order, not RTK service).",
            "Rule 19 — Passive 'any update?' / 'is this okay?' on a PO# without a directive → OTHERS, NOT SALES_PO. Exception 19a: line-item cancellation requests still classify as SALES_PO.",
            "Rule 25 — If a PO# appears ONLY inside an attachment named 'Sales Order Acknowledgement', this is a system-generated SOA back to the customer, not a real PO.",
            "Rule 18 — Conditional approvals like 'Approved – book under resale' or 'PO is approved for release upon tax confirmation' still classify as SALES_PO.",
        ],
        "exclusions": [
            "If body contains a quote reference (Q-XXX, QT-XXX, QUOTE-XXX) → quote_to_order, not po_intake.",
            "If extracted PO# already matches an existing booked Order → trade_change_order, not po_intake.",
        ],
    },
    "quote_to_order": {
        "category": "SALES_PO",
        "track_hint": "trade",
        "priority": 1,
        "regions": ["GLOBAL"],
        "description": (
            "Customer asks to convert an existing quote into a sales order. PO# may or may not be attached; "
            "the defining signal is an explicit quote reference + a 'convert / book / issue order' directive."
        ),
        "keywords": [
            "convert quote",
            "convert QT-",
            "book the order",
            "issue an order against",
            "PO against quote",
            "Q2O",
            "release order",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Please convert quote QT-XXX into an order using the attached PO and BOM.",
            "We accept quote Q-XXX. Please book the order and send the SOA.",
        ],
        "examples_negative": [
            "A fresh PO with no quote_number is po_intake.",
            "If the body mentions PO# but no quote reference, classify as po_intake.",
        ],
        "exceptions": [
            "If the customer quotes the QUOTE NUMBER but the directive is 'cancel that quote' → trade_change_order.",
            "Rule 25 — If quote# only appears in an attached SOA filename, ignore that signal.",
        ],
        "exclusions": [
            "If no explicit quote reference (no QT- / Q- / QUOTE-) → po_intake.",
        ],
    },
    "trade_change_order": {
        "category": "SALES_PO",
        "track_hint": "trade",
        "priority": 2,
        "regions": ["GLOBAL"],
        "description": (
            "Customer requests LINE-LEVEL or BILLING changes to an EXISTING booked sales order: quantity bump or cut, "
            "unit-price revision, line add or remove, SKU swap, billing-address change, or whole-order cancellation. "
            "NOT for ship-date moves (ssd_change_request), NOT for ship-to or carrier or Incoterm changes (delivery_change), "
            "NOT for hold releases (hold_release)."
        ),
        "keywords": [
            "change qty",
            "modify order",
            "amend",
            "update line item",
            "add a line",
            "remove from order",
            "cancel line",
            "cancel the order",
            "swap SKU",
            "update bill-to",
            "negotiated unit price",
            "revised price",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Increase qty on line 1 of order SO-XXX from 2 to 3 units.",
            "Cancel line item SKU-XYZ on SO-XXX and add a new line for E36312A at the quoted price.",
            "Negotiated unit-price revision on line 2 of SO-XXX.",
            "Update bill-to on order SO-XXX to our new entity.",
            "Cancel the entire order SO-XXX.",
        ],
        "examples_negative": [
            "Just changing the ship date on an existing order is ssd_change_request.",
            "Changing the ship-to address, carrier, Incoterm, or delivery instructions is delivery_change, NOT trade_change_order.",
            "Releasing an order from credit, compliance, or quality hold is hold_release.",
        ],
        "exceptions": [
            "Rule 19 Exception — Even on a passive 'any update?' email, line-item CANCELLATION is still SALES_PO / trade_change_order.",
        ],
        "exclusions": [
            "If the change is purely a ship-date push/pull → ssd_change_request.",
            "If the change is purely the ship-to address, carrier, Incoterm, or delivery instructions → delivery_change.",
        ],
    },
    "hold_release": {
        "category": "SALES_PO",
        "track_hint": "trade",
        "priority": 2,
        "regions": ["GLOBAL"],
        "description": (
            "Customer asks to release an order from a hold — credit, export-compliance, payment, or other. "
            "Body usually includes 'release', 'clear', 'remove hold', or evidence the hold-cause is resolved."
        ),
        "keywords": [
            "release the hold",
            "release order",
            "clear the hold",
            "remove hold",
            "hold has been resolved",
            "credit cleared",
            "trade compliance approved",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "AP team confirmed the credit hold on SO-XXX has been resolved. Please release.",
            "Trade compliance has approved the EAR99 classification. Please clear the hold.",
        ],
        "examples_negative": [],
        "exceptions": [],
        "exclusions": [
            "If the email is just informing the customer THAT a hold exists (outbound CSR notification quoted in a thread) → not actionable; treat as OTHERS.",
        ],
    },
    "ssd_change_request": {
        "category": "OTHERS",
        "track_hint": "trade",
        "priority": 3,
        "regions": ["GLOBAL"],
        "description": (
            "Customer requests a Ship Schedule Date (SSD) change on an existing order — push out, pull in, or partial split. "
            "Distinct from delivery_change (which is a one-off carrier reschedule); SSD is the formal ERP date field."
        ),
        "keywords": [
            "push out",
            "pull in",
            "split shipment",
            "ship schedule date",
            "SSD change",
            "reschedule shipment",
            "delay delivery",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Push out the requested ship date for SO-XXX by 2 weeks.",
            "Pull in our recent UXR scope order — NPI gating slot opened earlier.",
        ],
        "examples_negative": [
            "Modifying line items / qty is trade_change_order.",
            "One-time carrier change (FedEx → UPS) without changing the date is delivery_change.",
        ],
        "exceptions": [],
        "exclusions": [],
    },
    "delivery_change": {
        "category": "SALES_PO",
        "track_hint": "trade",
        "priority": 3,
        "regions": ["GLOBAL"],
        "description": (
            "Customer is changing HOW or WHERE an existing order ships, NOT WHEN. "
            "Ship-to address change, carrier swap (FedEx to DHL, etc.), Incoterm change (EXW to DAP, etc.), "
            "delivery-instruction updates (gate codes, dock hours, hazmat), or partial-split of one shipment to multiple addresses. "
            "Distinct from trade_change_order (which is about line items / prices / billing) and ssd_change_request (which is about the date)."
        ),
        "keywords": [
            "change ship-to",
            "update ship-to",
            "ship to a different address",
            "relocating",
            "change carrier",
            "switch carrier",
            "redirect shipment",
            "alternate ship-to",
            "change Incoterm",
            "delivery instructions",
            "gate codes",
            "dock hours",
            "hazmat",
            "split shipment",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Change ship-to address on SO-XXX, we're relocating our test lab.",
            "Switch the carrier on SO-XXX from FedEx to DHL Express.",
            "Update Incoterm on SO-XXX from EXW to DAP.",
            "Add dock-door gate codes and hazmat handling instructions to the delivery on SO-XXX.",
            "Split shipment of SO-XXX, half the lines to Auburn Hills, half to Phoenix.",
        ],
        "examples_negative": [
            "Moving the ship DATE earlier or later is ssd_change_request, not delivery_change.",
            "Changing line item quantities, prices, or SKUs is trade_change_order.",
            "Updating bill-to is trade_change_order, not delivery_change.",
        ],
        "exceptions": [],
        "exclusions": [
            "If only the ship date is moving → ssd_change_request.",
            "If line items, prices, or billing are changing → trade_change_order.",
        ],
    },
    # -----------------------------------------------------------------
    # ISC_WO_RTK category
    # -----------------------------------------------------------------
    "service_order": {
        "category": "ISC_WO_RTK",
        "track_hint": "som",
        "priority": 1,
        "regions": ["GLOBAL"],
        "description": (
            "New request to create a work order — calibration, repair, installation, on-site service. "
            "May be multi-asset (one CCC per asset per Keysight policy). Distinct from service_contract_request "
            "(which asks for a CONTRACT, not a one-off WO)."
        ),
        "keywords": [
            "calibration request",
            "cal request",
            "open a WO",
            "create work order",
            "RTK",
            "return to Keysight",
            "ISO 17025",
            "Z540.3",
            "A2LA",
            "校正",
            "repair request",
            "on-site service",
        ],
        "sender_patterns": ["lab.ops@", "metrology@", "calibration@"],
        "examples_positive": [
            "Annual cal request — ISO 17025 / A2LA traceable, 2 assets.",
            "Multi-asset cal request — 6 instruments, on-site, ISO 17025 / A2LA.",
            "Please send shipping label for RMA — DUT failed at 3.5 GHz.",
        ],
        "examples_negative": [
            "Asking about an EXISTING work order is wo_update_request or wo_status_inquiry.",
            "Asking for a SERVICE CONTRACT QUOTE is service_contract_request.",
            "Rule 13/20 — keyword-only mention of 'WO' / 'Repair' WITHOUT a service directive → OTHERS, not service_order.",
        ],
        "exceptions": [
            "Multi-asset rule — when ≥2 assets, generate ONE CCC PER ASSET (clone first CCC; address-update per clone).",
            "Custom-product fallback — if the asset SKU isn't in Salesforce, set 'CUSTOM PRODUCT' + put model+serial in FE Comments.",
            "Rule 3A — PO with cal-cert / factory-calibration of a NEW unit is SALES_PO, NOT service_order (factory cal of new product is part of the order).",
        ],
        "exclusions": [
            "If body mentions 'service contract', 'cal plan', 'PM plan', 'support agreement' → service_contract_request.",
        ],
    },
    "wo_update_request": {
        "category": "ISC_WO_RTK",
        "track_hint": "som",
        "priority": 2,
        "regions": ["GLOBAL"],
        "description": (
            "Customer asks to update or modify an EXISTING work order — add notes, add tasks, add assets to a scheduled visit, "
            "amend the SOW. Body typically references a specific WO# and a change directive."
        ),
        "keywords": [
            "update work order",
            "modify WO",
            "add asset to WO",
            "add a task",
            "amend WO",
            "update SOW",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Add 2 more assets to the open cal job (WO-XXX).",
            "Update WO-XXX — please add a verification step on channel 2.",
        ],
        "examples_negative": [
            "Just asking 'where are we on WO-XXX?' is wo_status_inquiry.",
        ],
        "exceptions": [],
        "exclusions": [],
    },
    "wo_status_inquiry": {
        "category": "ISC_WO_RTK",
        "track_hint": "som",
        "priority": 3,
        "regions": ["GLOBAL"],
        "description": (
            "Customer asks for the status of an existing work order or open WOs. No change directive — purely informational."
        ),
        "keywords": [
            "WO status",
            "work order status",
            "as-found status",
            "where are we on",
            "ETA",
            "what's the status",
            "作業指示のステータス",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "URGENT: WO status needed — customer audit Friday.",
            "作業指示のステータス確認 (校正対象 OOT 含む)",
        ],
        "examples_negative": [
            "Rule 19 — passive WO mentions without a status request go to OTHERS.",
        ],
        "exceptions": [
            "Rule 20 — if the WO is mentioned only as keyword without a 'status', 'where', 'ETA' directive → OTHERS.",
        ],
        "exclusions": [],
    },
    "service_contract_request": {
        "category": "ISC_WO_RTK",
        "track_hint": "service_contract",
        "priority": 4,
        "regions": ["GLOBAL"],
        "description": (
            "Customer asks for a service contract — Cal Plan, PM Plan, Support Agreement. Multi-year, multi-asset, "
            "with SLA tiers. Distinct from service_order (one-off WO)."
        ),
        "keywords": [
            "service contract",
            "cal plan",
            "PM plan",
            "support agreement",
            "renew contract",
            "extend coverage",
            "calibration plan",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Service contract quote request — 3-yr Cal Plan, 12 assets, Z540.3 + on-site.",
            "Plan PM con cal A2LA, SLA Gold, ~8 instrumentos.",
        ],
        "examples_negative": [
            "Single one-off cal request is service_order, not service_contract_request.",
        ],
        "exceptions": [],
        "exclusions": [],
    },
    # -----------------------------------------------------------------
    # OTHERS / discarded categories
    # -----------------------------------------------------------------
    "general_inquiry": {
        "category": "OTHERS",
        "track_hint": "general",
        "priority": 5,
        "regions": ["GLOBAL"],
        "description": (
            "Other legitimate business question — EOL roadmap, product info, lead-time questions, generic technical inquiries."
        ),
        "keywords": [
            "lead time",
            "EOL roadmap",
            "product info",
            "datasheet",
            "is this still available",
            "what's the price on",
            "any update?",
            "is this okay?",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "What's the EOL roadmap for the E5071C?",
            "Any update on PO-XXX? (passive — Rule 19 routes to OTHERS).",
        ],
        "examples_negative": [],
        "exceptions": [
            "Rule 19 — Passive PO mentions ('any update?', 'is this okay?') route here, NOT to po_intake / trade_change_order.",
            "Rule 13/20 — Keyword-only WO/Repair mentions without a directive route here.",
        ],
        "exclusions": [],
    },
    "out_of_scope": {
        "category": "AUTO_REPLY",
        "track_hint": "discarded",
        "priority": 6,
        "regions": ["GLOBAL"],
        "description": (
            "Legitimate but non-customer-business — automated notifications (Google/Microsoft security, AWS, GitHub), "
            "social-network alerts (LinkedIn), newsletter forwards, internal admin (HR, IT, payroll), out-of-office "
            "auto-replies, calendar invites, vendor receipts. Not spam, but not actionable in the SalesOps queue."
        ),
        "keywords": [
            "out of office",
            "automatic reply",
            "I am away",
            "no longer with",
            "kindly contact",
            "OOO",
        ],
        "sender_patterns": [
            "noreply@",
            "no-reply@",
            "notifications@",
            "billing@aws.amazon.com",
            "linkedin.com",
            "calendar-notification@",
        ],
        "examples_positive": [
            "Google account-security notification: 'App password created to sign in to your account'.",
            "LinkedIn invitation: 'X wants to connect with you on LinkedIn'.",
            "Out-of-office auto-reply from a customer contact.",
        ],
        "examples_negative": [
            "Customer asking a real product question (lead time, EOL roadmap) is general_inquiry, not out_of_scope.",
            "Phishing / wire-fraud / lookalike-domain credential traps are spam, not out_of_scope.",
        ],
        "exceptions": [
            "Rule 7 — Auto-replies WITH a question/PO/WO instruction inside ('I'm out, please contact X for our PO') escalate UP — re-classify the inner intent.",
        ],
        "exclusions": [],
    },
    "spam": {
        "category": "OTHERS",
        "track_hint": "discarded",
        "priority": 7,
        "regions": ["GLOBAL"],
        "description": (
            "Unsolicited or malicious — phishing, wire-fraud, lookalike-domain credential traps, off-topic promotional "
            "from unknown senders. Distinguished from out_of_scope by sender unfamiliarity OR clearly malicious intent."
        ),
        "keywords": [
            "verify your account",
            "click here",
            "act now",
            "70% OFF",
            "wire details have changed",
            "remit-to update",
            "URGENT",
            "limited time",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "URGENT: account verification required to release pending wire — phishing.",
            "Lookalike-domain payment-redirect: 'Our banking details have changed, please update remit-to'.",
        ],
        "examples_negative": [
            "Promotional emails from KNOWN brands (Google, Microsoft, AWS, LinkedIn) are out_of_scope, NOT spam.",
            "Forwarded newsletters from established providers are out_of_scope.",
        ],
        "exceptions": [],
        "exclusions": [],
    },
    # === v1.1 TASK-1 START === 5 first-class intents per prior-POC 9-class taxonomy
    "kso": {
        "category": "KSO",
        "track_hint": "discarded",
        "priority": 0,
        "regions": ["GLOBAL"],
        "description": (
            "Government / defense / federal-prime customer email. Handled by a "
            "different team for compliance reasons (ITAR/EAR/DFARS). Agent "
            "does NOT auto-respond — redirects to keysightorders@keysight.com."
        ),
        "keywords": [
            "N5194A", "N5193A", "N5192A", "N5191A",
            "Boeing", "Sandia", "Tevet", "Peraton",
            "Vallen", "Leidos", "Raytheon", "Pratt Whitney",
            "Cobham", "General Dynamics",
        ],
        "sender_patterns": [
            "@lmco.com", "@fastx.com", "@l3harris.com", "@us.af.mil",
            "@caci.com", "@boeing.com", "@ngc.com", "@gov.in",
            "@testmart.com", "@nasa.gov", "@baesystems.com", "@tevet.com",
        ],
        "examples_positive": [
            "From: orders@boeing.com — please quote N5194A for our defense lab.",
            "Email body mentions 'Raytheon' and 'Peraton' as end customers.",
        ],
        "examples_negative": [
            "Email mentions 'Raytheon' only inside the email signature footer — NOT KSO.",
        ],
        "exceptions": [
            "Override-prompt KSO Rule — strict string/keyword match only. Do NOT infer "
            "intent based on tone or industry. If a KSO domain or keyword is matched, "
            "classify as KSO regardless of any other rule that might match.",
        ],
        "exclusions": [],
        "redirect_to": "keysightorders@keysight.com",
    },
    "collections": {
        "category": "COLLECTIONS",
        "track_hint": "discarded",
        "priority": 4,
        "regions": ["GLOBAL"],
        "description": (
            "Payment / remittance / banking notification email. Handled by the "
            "Collections team. Agent does not process — redirects to "
            "collections.pdl-americas@keysight.com + usar_keysight@keysight.com."
        ),
        "keywords": [
            "Remittance Advice",
            "Payment Advice",
            "Payment Remittance Advice",
            "Notice of new scheduled payment",
            "Notice of new Remittance Advice",
            "ACH Payment Remittance Advice",
            "You got paid by Energy Medical Systems",
            "early payment opportunity",
            "GOOGLE PAYMENT NOTIFICATION",
            "Your invoice(s) have been received and may require additional attention",
            "ACH setup",
            "test deposit",
            "bank verification",
            "account summary",
            "statement request",
            "authorization letter",
            "zero balance",
            "accounts receivable",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Subject: Remittance Advice — payment of $24,000.00 made via ACH on 2026-05-08.",
            "Subject: ACH Payment Remittance Advice — payment confirmation for invoices listed.",
        ],
        "examples_negative": [
            "Email mentions 'Net 30 payment terms' only in the disclaimer footer — NOT collections.",
        ],
        "exceptions": [
            "Override Rule 4 — payment terms appearing only in disclaimers/footers/signatures "
            "do NOT trigger COLLECTIONS.",
            "Override Rule 21A — payment-method or bank-account verification (ACH test deposit, "
            "payment onboarding) takes precedence over PORTAL_ADMIN.",
        ],
        "exclusions": [],
        "redirect_to": "collections.pdl-americas@keysight.com,usar_keysight@keysight.com",
    },
    "portal_admin": {
        "category": "PORTAL_ADMIN",
        "track_hint": "discarded",
        "priority": 5,
        "regions": ["GLOBAL"],
        "description": (
            "Portal / SSO / login-verification system message — password reset, "
            "OTP, verification code. Agent doesn't act — redirects to "
            "portal-admin.pdl-ccc-americas@keysight.com."
        ),
        "keywords": [
            "Password",
            "validation code",
            "verification code",
            "one-time password",
            "OTP",
            "authentication code",
            "login code",
            "password reset link",
            "reset your password",
            "account activation",
            "verify your email",
            "email confirmation",
            "Use this code to log in",
            "access the portal with",
        ],
        "sender_patterns": [],
        "examples_positive": [
            "Subject: Your verification code is 123456 — valid for 10 minutes.",
            "Body: Click here to reset your password — link expires in 1 hour.",
        ],
        "examples_negative": [
            "Subject: ACH test deposit verification (this is COLLECTIONS via Rule 21A, not PORTAL_ADMIN).",
        ],
        "exceptions": [
            "Override Rule 21A — if the verification context is about payment / bank account / "
            "ACH setup, classify as COLLECTIONS instead.",
        ],
        "exclusions": [],
        "redirect_to": "portal-admin.pdl-ccc-americas@keysight.com",
    },
    "brazil_tax": {
        "category": "BRAZIL_TAX",
        "track_hint": "discarded",
        "priority": 3,
        "regions": ["AMS"],
        "description": (
            "Brazilian tax document email (Nota Fiscal, NF-e, ICMS, CFOP). "
            "Handled by LAR Orders team. Agent doesn't process — redirects to "
            "lar_orders@keysight.com."
        ),
        "keywords": [
            "Brazil Tax",
            "TMF Group",
            "Nota Fiscal",
            "NF-e",
            "NFe",
            "CNPJ",
            "ICMS",
            "CFOP",
        ],
        "sender_patterns": [
            "keysight.bra-tax@tmf-group.com",
        ],
        "examples_positive": [
            "From: keysight.bra-tax@tmf-group.com — Subject: NF-e 12345 emitida.",
            "Body contains: CNPJ 12.345.678/0001-90 — ICMS calculation attached.",
        ],
        "examples_negative": [
            "From: collections@third-party.com mentions 'Remittance Advice' — that's COLLECTIONS not BRAZIL_TAX.",
        ],
        "exceptions": [
            "Override Rule 3 (BRAZIL_TAX) — if email is clearly about general remittance/payment "
            "advice, classify as COLLECTIONS instead.",
        ],
        "exclusions": [],
        "redirect_to": "lar_orders@keysight.com",
    },
    "undeliverable": {
        "category": "UNDELIVERABLE",
        "track_hint": "discarded",
        "priority": 1,
        "regions": ["GLOBAL"],
        "description": (
            "Bounce / DSN / mail-delivery-failure notification. Discarded — no "
            "customer-facing reply needed. Stored for audit, moved to "
            "Undeliverable folder."
        ),
        "keywords": [
            "Undeliverable",
            "Mail Delivery Failure",
            "Delivery Failure",
            "Returned Mail",
            "Delivery Status Notification",
            "Non-Delivery Report",
            "Failed Delivery",
            "Undelivered Mail Returned to Sender",
            "[Postmaster] Email Delivery Failure",
            "Mail Delivery Failed",
            "Delivery Delayed",
            "DELIVERY FAILURE",
            "5.1.1 User unknown",
            "550 5.",
            "Diagnostic-Code: smtp;",
            "Action: failed",
        ],
        "sender_patterns": [
            "mailer-daemon",
            "noreply@keysight.com",
            "postmaster@",
            "MAILER-DAEMON@",
        ],
        "examples_positive": [
            "From: mailer-daemon@gmail.com — Subject: Delivery Status Notification (Failure).",
            "From: noreply@keysight.com — Subject: Mail Delivery Failed.",
        ],
        "examples_negative": [
            "Email forwarded by a customer that quotes a bounce notification but contains a "
            "user-written business request — classify on the business request, NOT UNDELIVERABLE.",
        ],
        "exceptions": [
            "Override Rule 6 — UNDELIVERABLE only when the latest senderEmail is exactly "
            "noreply@keysight.com or mailer-daemon. Do not match on quoted/forwarded sender info.",
            "Override 'Actionable Content Exception' — if the same fragment includes a clear "
            "business instruction or user request, do NOT classify as UNDELIVERABLE.",
        ],
        "exclusions": [],
        "redirect_to": None,
    },
    # === v1.1 TASK-1 END ===
}


# Global override-rule excerpts that apply ACROSS intents — these are the
# operational rules from the prior POC's 25KB override prompt that are not
# specific to one intent. Surfaced as a global section in the classify prompt.
GLOBAL_OVERRIDE_RULES: list[str] = [
    "Empty-fragment skip — strip messages that contain only From/To/Subject, CAUTION banners, "
    "disclaimers, or quoted threads. Only classify on the FIRST non-empty fragment in the body array.",

    "Internal Keysight-to-Keysight detection — emails between Keysight employees route to OTHERS "
    "UNLESS keysight.ai-front-office@keysight.com is in To:.",

    "Generic-phrase handling — 'FYI', 'see below', 'looping you in' alone do NOT immediately mark "
    "OTHERS. Walk back through the thread first to find earlier valid content fragments.",

    "Strict per-rule stop-at-first-match scan order: UNDELIVERABLE → AUTO_REPLY → BRAZIL_TAX → "
    "PORTAL_ADMIN → COLLECTION → KSO → ISC_WO_RTK → SALES_PO → OTHERS.",

    "CSR-instruction override — any specific FE/CSR routing instruction in the email body "
    "supersedes system routing. If body says 'route this to <queue> per <CSR name>', honor it.",

    "Acknowledgement-only thread (Rule 25) — if a PO# / WO# / order# only appears inside an "
    "attachment named 'Sales Order Acknowledgement', do NOT treat as a real customer ask. "
    "It's a system-generated SOA being forwarded.",

    "Conditional approval detection (Rule 18) — phrases like 'Approved – book under resale', "
    "'PO is approved for release upon tax confirmation' classify as SALES_PO (po_intake).",

    "Forwarded blocks with structured data — when an email forwards a block containing a WO#, "
    "model details, calibration info, etc., extract the inner intent from the FORWARDED block, "
    "not from the wrapper text.",

    "Auto-reply with business context (Rule 7/9) — 'I'm no longer with', 'Please contact', "
    "'Kindly reach out' → AUTO_REPLY UNLESS they include a question / PO# / WO# instruction "
    "(in which case escalate to the inner intent).",
]


# Per-intent RFP path rubric — the canonical end-to-end flow per the 7
# use-case diagrams (use case sheet of SalesOps - RFP.xlsx). Consumed by the
# pipeline verifier's optional LLM second-opinion check. Operators edit
# the rubric in the KB UI just like every other intent field.
RFP_RUBRICS: dict[str, str] = {
    "po_intake": (
        "Trade Order Entry (UC1). Happy path: Email Received → Email Classify → "
        "Create CCC Request (shell) → CCC Request enrichment (AI, no parties) → "
        "Human-in-Loop FCNV Review (optional, fallout to FCNV Scope) → "
        "Assign CCC Request owner → Human-in-Loop CSR Review (optional) → "
        "AIOA PO Validation → on AIOA_PASS: Quote Update → Q2O Conversion → "
        "Oracle EBS SO entered → CCC Request updated to Booked → SOA generated "
        "and filed in SharePoint → Customer reply with SOA. "
        "On AIOA_FAIL: case routes to AI OA Fallout queue inside AIOA, "
        "ZBrain does NOT draft a customer reply. "
        "On AIOA handoff (PASS or FAIL): ZBrain stops at Stage 4; AIOA owns "
        "all downstream customer comms."
    ),
    "quote_to_order": (
        "UC1 variant. Identical to po_intake except the inbound starts from a "
        "quote acceptance with a PO that references an active Keysight quote. "
        "Same AIOA handoff semantics."
    ),
    "trade_change_order": (
        "UC2 — Trade Sales Change Order. Happy path: Email Received → Classify → "
        "Create CCC Request (Change Order Rcvd) → CCC enrichment → "
        "Human-in-Loop FCNV Review (optional, fallout to FCNV Scope) → "
        "Assign CCC Request owner → CSR completes CCC entry if needed → "
        "CSR updates CCC status to In Progress → CSR provides Existing Order → "
        "CSR provides Update to Customer → CSR updates CCC status to Closed. "
        "No SOA unless the change adds a PO and AIOA is required."
    ),
    "service_order": (
        "UC3 — SOM Work Order Automation. Happy path (single asset): Email → "
        "Classify → Create CCC (shell) → CCC enrichment → AI Agent creates 1 WO → "
        "SOM AI Agent attaches email + attachments to WO → AI Agent closes CCC "
        "(no reply). Happy path (multi-asset ≥2): same flow but populate Bulk WO "
        "Staging table → create one WO per asset → close CCC (no reply). "
        "PO-without-existing-WO triggers CMD Interface fallout (customer-master "
        "activation request). SOM CSR reviews the auto-created WOs separately."
    ),
    "wo_update_request": (
        "UC4 — SOM WO Update / Change Order. Happy path: Email → Classify → "
        "Create CCC (shell) → CCC enrichment → Update Existing WO (Add Note / "
        "Add Task) → SOM AI Agent attaches email/attachments to WO → "
        "if PO is attached, PO triggers AIOA Validation → Close CCC (no reply). "
        "HITL CSR review of WO and reply happens separately."
    ),
    "wo_status_inquiry": (
        "UC5 — WO Status / Inquiry. Happy path: Email → Classify/Reply → "
        "AI Reply with WO customer-friendly status + KSP reassurance. End. "
        "Fallouts: FCNV Scope (cannot classify), CCC Request created and "
        "assigned to CSR (when status cannot be inferred). No CCC create or "
        "external write on the happy path."
    ),
    "service_contract_request": (
        "UC6 — Service Contracts. Happy path: Email → Classify → Create CCC "
        "(shell) → CCC enrichment → Human-in-Loop FCNV Review (optional, "
        "fallout to FCNV Scope) → Assign CCC owner → Human-in-Loop CSR Review "
        "(optional, fallout to CTA Scope) → AIOA PO Validation → "
        "on AIOA_PASS: case moves to S&A specialist for contract workflow. "
        "On AIOA_FAIL: AI OA Fallout queue. ZBrain stops at Stage 4 on AIOA handoff."
    ),
    "ssd_change_request": (
        "UC7 — SSD Change Request. Happy path: Email → Classify → "
        "Human-in-Loop FCNV Review (optional) → Create & Assign CCC owner "
        "(Sales Order Owner / Direct Inquiries in Oracle) → Add SSD request to "
        "CSR dashboard → Notification to CSR & Factories → Factory prepares SSD "
        "and triggers CSR from dashboard → Factory: CSR interaction to finalize "
        "SSD from dashboard → Factory triggers changes to Oracle from dashboard "
        "→ CCC auto-closed → Customer gets notified by factory. ZBrain does NOT "
        "draft a customer reply on the happy path; the factory closes the loop."
    ),
    "hold_release": (
        "Post-order: customer requests release of an existing order hold. "
        "Happy path: Email → Classify → CCC enrichment → release_hold action "
        "on the existing Salesforce Order → customer reply confirming the release."
    ),
    "delivery_change": (
        "Post-order: customer requests a delivery date change. Happy path: "
        "Email → Classify → CCC enrichment → reschedule_order action on the "
        "existing Salesforce Order → customer reply confirming new ship date."
    ),
    "general_inquiry": (
        "Catch-all for non-actionable customer questions. Happy path: Email → "
        "Classify → draft a courteous reply or route to the right team. "
        "No CCC enrichment or external write required."
    ),
    "out_of_scope": (
        "Out-of-scope / automated notification / internal admin. Terminal — "
        "discard at Pre-Intake or Stage 1. No CCC create, no reply, no write."
    ),
    "spam": (
        "Spam / phishing / promotional. Terminal — discard at Pre-Intake or "
        "Stage 1. No CCC create, no reply, no write."
    ),
    "kso": (
        "Keysight Strategic Operations — Government / Defense / Federal-Prime "
        "customer mail. Terminal redirect to keysightorders@keysight.com — "
        "no AI processing per export-compliance restrictions."
    ),
}


def rfp_rubric_for(intent: str) -> str | None:
    """Returns the RFP path rubric for an intent, or None if not defined."""
    return RFP_RUBRICS.get(intent)


def all_definitions() -> dict[str, dict[str, Any]]:
    """Returns the full {intent_id: schema_body} map. Used by kb.seed_defaults.
    Each definition is merged with its rfp_rubric so the field flows into the
    KB row's body + default_body and operators can edit it from the UI."""
    out: dict[str, dict[str, Any]] = {}
    for intent, body in INTENT_DEFINITIONS_V2.items():
        merged = dict(body)
        rubric = RFP_RUBRICS.get(intent)
        if rubric:
            merged["rfp_rubric"] = rubric
        out[intent] = merged
    return out


def category_for(intent: str) -> str:
    """Maps a fine-grained intent to its 9-class POC category."""
    return INTENT_TO_CATEGORY.get(intent) or "OTHERS"
