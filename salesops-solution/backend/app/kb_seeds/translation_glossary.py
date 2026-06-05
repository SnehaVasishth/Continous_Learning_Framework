"""Seed rules for the per-language Keysight translation glossary.

The translator (Stage 1.5 inbound, Stage 5.1 reply drafting, Stage 5.2 audit
preview) reads this glossary and is instructed to use the canonical
translation for every Keysight-domain term, in both directions:

  • Inbound  (customer language → English): if you see  校正証明書 → translate as
    'calibration certificate' (not 'calibration license' or any other variant).
  • Outbound (English → customer language): when writing about the calibration
    certificate, use 校正証明書 — never an unauthorized synonym.

This matters for Keysight specifically because:
  - Service / Calibration vocabulary is regulated (Z540.3 / ISO 17025) — using
    the wrong target-language term in a reply can make the customer think the
    cert is non-conforming.
  - Trade compliance terminology (ECCN, ITAR, EAR) MUST stay in English even
    in non-English correspondence — that's what regulators expect.
  - Acronyms (PO, SOA, QT, WO, BOM, OOT, SLA, SKU, NPI, EOL) stay verbatim
    while the surrounding noun phrase is localized: ja: '受注確認書 (SOA)'.

Each rule represents ONE Keysight concept with its canonical translations
across every supported customer language. Operators add a new language by
adding the language code to every rule's `translations` dict — there's no
need to clone rules per language.

The rule body shape:
  {
    "kind": "glossary_term",
    "english": "calibration certificate",        # canonical EN
    "translations": {                            # canonical per-language
      "es": "certificado de calibración",
      "ja": "校正証明書"
    },
    "applies_to": ["inbound", "outbound"],       # which stages
    "domain": "service" | "trade" | "compliance" | "general",
    "preserve_acronym": "SOA" | None,            # optional verbatim acronym
    "active": true
  }
"""
from __future__ import annotations

from typing import Any


def _term(
    *,
    id: str,
    label: str,
    english: str,
    es: str | None = None,
    ja: str | None = None,
    domain: str = "general",
    description: str = "",
    applies_to: list[str] | None = None,
    preserve_acronym: str | None = None,
    active: bool = True,
) -> dict[str, Any]:
    translations: dict[str, str] = {}
    if es is not None:
        translations["es"] = es
    if ja is not None:
        translations["ja"] = ja
    return {
        "id": id,
        "label": label,
        "description": description,
        "kind": "glossary_term",
        "english": english,
        "translations": translations,
        "applies_to": applies_to or ["inbound", "outbound"],
        "domain": domain,
        "preserve_acronym": preserve_acronym,
        "active": active,
    }


TRANSLATION_GLOSSARY_RULES: list[dict[str, Any]] = [
    # ---- Service / Calibration domain ----------------------------------
    _term(
        id="calibration_certificate",
        label="Calibration certificate",
        english="calibration certificate",
        es="certificado de calibración",
        ja="校正証明書",
        domain="service",
        description=(
            "What it does: pins the canonical translation of 'calibration certificate' across all languages. "
            "Cal certs are regulated (ISO 17025 / A2LA / ANSI-NCSL Z540.3) so using a non-canonical synonym "
            "in a customer reply can trigger a compliance objection.\n\n"
            "How to optimize: do not change once calibrated to your regional Keysight Service vocabulary. "
            "If a regional team uses an alternate (e.g. ja: '校正証' shortened form), add a per-language override "
            "in `translations` rather than changing the canonical here."
        ),
    ),
    _term(
        id="work_order",
        label="Work order (WO)",
        english="work order",
        es="orden de trabajo",
        ja="作業指示",
        domain="service",
        preserve_acronym="WO",
        description=(
            "What it does: standard term for a service-side work order. Acronym 'WO' stays verbatim "
            "in all languages. ja: '作業指示書' (with 書 for the document form) is also acceptable; "
            "default leaves off 書 to match the WO-as-task vs WO-as-document distinction.\n\n"
            "How to optimize: if your service-management tool localizes WO to a different term, "
            "update `translations` accordingly. Don't translate 'WO' itself — every region keeps it."
        ),
    ),
    _term(
        id="service_contract",
        label="Service contract",
        english="service contract",
        es="contrato de servicio",
        ja="サービス契約",
        domain="service",
    ),
    _term(
        id="out_of_tolerance",
        label="Out of tolerance (OOT)",
        english="out of tolerance",
        es="fuera de tolerancia",
        ja="公差外",
        domain="service",
        preserve_acronym="OOT",
        description=(
            "Calibration as-found state. ja: '公差外' (literally 'outside tolerance') is the standard term; "
            "do not use '許容範囲外' (allowable-range-outside) which carries a different connotation in JA QC."
        ),
    ),
    _term(
        id="as_found",
        label="As-found state",
        english="as-found",
        es="estado inicial (as-found)",
        ja="校正前 (as-found)",
        domain="service",
        description=(
            "Calibration measurement BEFORE adjustment. We localize the noun phrase but keep "
            "'as-found' in parentheses so the JA / ES technician recognizes the standard term."
        ),
    ),
    _term(
        id="as_left",
        label="As-left state",
        english="as-left",
        es="estado final (as-left)",
        ja="校正後 (as-left)",
        domain="service",
        description="Calibration measurement AFTER adjustment. Mirror as-found localization.",
    ),
    _term(
        id="z540_3",
        label="ANSI/NCSL Z540.3 standard",
        english="ANSI/NCSL Z540.3",
        es="ANSI/NCSL Z540.3",
        ja="ANSI/NCSL Z540.3",
        domain="compliance",
        description="Standard identifier — never localize. Keysight contracts cite the exact code.",
    ),
    _term(
        id="iso_17025",
        label="ISO 17025 accreditation",
        english="ISO 17025",
        es="ISO 17025",
        ja="ISO 17025",
        domain="compliance",
        description="Standard identifier — never localize.",
    ),

    # ---- Trade domain --------------------------------------------------
    _term(
        id="purchase_order",
        label="Purchase order (PO)",
        english="purchase order",
        es="orden de compra",
        ja="発注書",
        domain="trade",
        preserve_acronym="PO",
        description=(
            "Acronym 'PO' stays English in all languages — universal in B2B trade. "
            "ja: '発注書' is the standard form; '注文書' is also acceptable but less formal."
        ),
    ),
    _term(
        id="sales_order_acknowledgment",
        label="Sales Order Acknowledgment (SOA)",
        english="sales order acknowledgment",
        es="acuse de recibo de pedido (SOA)",
        ja="受注確認書 (SOA)",
        domain="trade",
        preserve_acronym="SOA",
        description=(
            "Outbound document confirming order receipt. Acronym SOA stays in parentheses — "
            "it appears on the actual generated PDF and customers reference it that way."
        ),
    ),
    _term(
        id="quote",
        label="Quote / quotation (QT)",
        english="quote",
        es="cotización",
        ja="見積書",
        domain="trade",
        preserve_acronym="QT",
    ),
    _term(
        id="bill_of_materials",
        label="Bill of materials (BOM)",
        english="bill of materials",
        es="lista de materiales (BOM)",
        ja="部品表 (BOM)",
        domain="trade",
        preserve_acronym="BOM",
    ),
    _term(
        id="lead_time",
        label="Lead time",
        english="lead time",
        es="plazo de entrega",
        ja="納期",
        domain="trade",
    ),
    _term(
        id="bill_to",
        label="Bill-to address",
        english="bill-to",
        es="facturar a",
        ja="請求先",
        domain="trade",
    ),
    _term(
        id="ship_to",
        label="Ship-to address",
        english="ship-to",
        es="enviar a",
        ja="配送先",
        domain="trade",
    ),
    _term(
        id="payment_terms",
        label="Payment terms",
        english="payment terms",
        es="términos de pago",
        ja="支払条件",
        domain="trade",
        description=(
            "The TERM 'payment terms' is localized; specific term VALUES (Net 30 / Net 45 / Net 60) "
            "stay verbatim — they're contractual identifiers, not natural-language phrases."
        ),
    ),
    _term(
        id="net_30_45_60",
        label="Net 30 / Net 45 / Net 60 — preserve verbatim",
        english="Net 30",
        es="Net 30",
        ja="Net 30",
        domain="trade",
        description=(
            "Specific payment-term identifiers. Never localize — they appear on contracts and "
            "POs in English regardless of regional language. Same rule applies to Net 45, Net 60, "
            "FOB Origin, FOB Destination, Ex Works, etc."
        ),
    ),

    # ---- Order lifecycle ----------------------------------------------
    _term(
        id="hold",
        label="Hold (status)",
        english="hold",
        es="retención",
        ja="保留",
        domain="trade",
        description=(
            "Order on hold — credit hold, compliance hold, etc. Localize the noun. "
            "Specific kinds (e.g. 'credit hold') translate component-wise: ES 'retención de crédito', "
            "JA 'クレジット保留' — but the verb 'release the hold' uses the canonical 'release_hold'."
        ),
    ),
    _term(
        id="release_hold",
        label="Release hold",
        english="release the hold",
        es="liberar la retención",
        ja="保留解除",
        domain="trade",
    ),
    _term(
        id="credit_hold",
        label="Credit hold",
        english="credit hold",
        es="retención de crédito",
        ja="クレジット保留",
        domain="trade",
    ),
    _term(
        id="compliance_hold",
        label="Compliance hold",
        english="compliance hold",
        es="retención por cumplimiento",
        ja="コンプライアンス保留",
        domain="compliance",
    ),
    _term(
        id="end_use_statement",
        label="End-use statement",
        english="end-use statement",
        es="declaración de uso final",
        ja="最終用途声明書",
        domain="compliance",
        description="Trade-compliance document — declares how a controlled item will be used.",
    ),

    # ---- Compliance / Export control ----------------------------------
    _term(
        id="eccn_code",
        label="ECCN — preserve verbatim",
        english="ECCN",
        es="ECCN",
        ja="ECCN",
        domain="compliance",
        description=(
            "Export Control Classification Number. NEVER localize — regulators (BIS, JETRO, "
            "European Commission) all reference the US-form code regardless of the customer's language."
        ),
    ),
    _term(
        id="itar",
        label="ITAR — preserve verbatim",
        english="ITAR",
        es="ITAR",
        ja="ITAR",
        domain="compliance",
        description="International Traffic in Arms Regulations. Never localize.",
    ),
    _term(
        id="ear",
        label="EAR — preserve verbatim",
        english="EAR",
        es="EAR",
        ja="EAR",
        domain="compliance",
        description="Export Administration Regulations. Never localize.",
    ),
    _term(
        id="hs_code",
        label="HS code — preserve verbatim",
        english="HS code",
        es="código HS",
        ja="HSコード",
        domain="compliance",
    ),

    # ---- Product / Catalog --------------------------------------------
    _term(
        id="sku",
        label="SKU — preserve verbatim",
        english="SKU",
        es="SKU",
        ja="SKU",
        domain="trade",
        description=(
            "Stock-keeping unit identifier. The noun 'SKU' stays English; specific SKU values "
            "(e.g. KS-SCOPE-666390) ALWAYS stay verbatim regardless of language — they're catalog keys."
        ),
    ),
    _term(
        id="part_number",
        label="Part number / MPN",
        english="part number",
        es="número de parte",
        ja="部品番号",
        domain="trade",
        preserve_acronym="MPN",
    ),
    _term(
        id="end_of_life",
        label="End of life (EOL)",
        english="end of life",
        es="fin de vida útil (EOL)",
        ja="製造終了 (EOL)",
        domain="trade",
        preserve_acronym="EOL",
    ),
    _term(
        id="new_product_introduction",
        label="New product introduction (NPI)",
        english="new product introduction",
        es="introducción de nuevo producto (NPI)",
        ja="新製品導入 (NPI)",
        domain="trade",
        preserve_acronym="NPI",
    ),

    # ---- SLA / Service entitlement ------------------------------------
    _term(
        id="sla",
        label="SLA — preserve verbatim",
        english="SLA",
        es="SLA",
        ja="SLA",
        domain="service",
        description="Service-level agreement abbreviation. Universal acronym; never localize.",
    ),
    _term(
        id="response_time",
        label="Response time (SLA metric)",
        english="response time",
        es="tiempo de respuesta",
        ja="応答時間",
        domain="service",
    ),
    _term(
        id="resolution_time",
        label="Resolution time (SLA metric)",
        english="resolution time",
        es="tiempo de resolución",
        ja="解決時間",
        domain="service",
    ),
    _term(
        id="on_site_service",
        label="On-site service",
        english="on-site service",
        es="servicio en el sitio",
        ja="オンサイトサービス",
        domain="service",
    ),

    # ---- Brand / Company (NEVER translate) ----------------------------
    _term(
        id="keysight_brand",
        label="Keysight Technologies — preserve verbatim",
        english="Keysight Technologies",
        es="Keysight Technologies",
        ja="Keysight Technologies",
        domain="general",
        description=(
            "Company brand. NEVER localize, NEVER lowercase, NEVER abbreviate to 'KT'. "
            "Same rule applies to product family names (UXR, EXR, FieldFox, InfiniiVision, etc.) — "
            "those are catalog-canonical and stay English in every language."
        ),
    ),
]


def all_rules() -> list[dict[str, Any]]:
    return TRANSLATION_GLOSSARY_RULES
