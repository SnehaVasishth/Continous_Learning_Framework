# === v1.1 TASK-5 START ===
"""Routing-rules KB — distributor partner list + magic-SKU overrides.

Drives the auto-assignment step of Sales PO Agent #3 (page 8-9 of the prior
POC's Sales PO Std Process & Change Order PDF).

Rule precedence (lowest priority number = checked first):
  1. CSR_OVERRIDE       — body contains explicit "route to <name>" instruction
  2. EXPORT_DESTINATION — final destination country != US/CA
  3. SOW_PRODUCT        — order contains an SOW SKU (Z-prefix) or "Statement of Work"
  4. EBIZ_SENDER        — email from Keysight-Used-Equipment-Store (ebiz@keysight.com)
  5. DISTY_PARTNER      — sender's customer matches a disty in the partner list
  6. STANDARD           — default routing by intent + region
"""
from __future__ import annotations


DISTY_PARTNERS_US_CA: list[str] = [
    "RS",
    "Avnet",
    "Continental Resources",
    "ConRes",
    "Electrorent",
    "Gap Wireless",
    "Mouser Electronics Inc",
    "Mouser",
    "Newark",
    "RFMW LTD",
    "RFMW",
    "Tessco",
    "TestEquity",
    "Transcat",
    "TRS",
]

DISTY_PARTNERS_LAR: list[str] = [
    "AQTK Peru S.A.",
    "AQTK S.A.",
    "Complementos Electrónicos S.A.",
    "Element14 S. de R.L. de C.V.",
    "Grupo Prod&Khym, S.A.",
    "Hi-Tech Automatización S.A.S",
    "INCAL Comércio, Importação e Exportação de Instrumentos Ltda.",
    "Inceleris S. de R.L. de C.V.",
    "Interlatin S. de R.L. de C.V.",
    "JMD Produtos Eletrônicos Ltda.",
    "Karimex Componentes Eletrônicos Ltda",
    "Negenex SAS",
    "Nextest Instrumentos e Sistemas Ltda",
    "OHMINI Comercio, Importação e Exportação de Produtos Ltda – EPP",
    "Precision Solutions",
    "Q Wire Inc.",
    "Q-Wire Technologies Inc.",
    "RCBI Instrumentos Ltda.",
    "Servicios Técnicos de Ingeniería S.A. de C.V.",
    "Tecnología y Electrónica S.A.",
    "TestEquity de México S. de R.L. de C.V.",
]

MAGIC_SKUS: dict[str, dict] = {
    "CUSTOM PRODUCT": {
        "description": "Fallback when SKU not in catalog. Also escapes AMFO_Disty/Rental routing for standard customers.",
        "routing_target": "CSR_QUEUE",
    },
    "SOWDUMMY": {
        "description": "Statement of Work — routes to SOW Team.",
        "routing_target": "SOW_TEAM_QUEUE",
    },
    "EXPORTDUMMY": {
        "description": "Non-US/CA destination — routes to Export Team.",
        "routing_target": "EXPORT_TEAM_QUEUE",
    },
}

EBIZ_SENDERS = ["ebiz@keysight.com", "Keysight-Used-Equipment-Store"]


ROUTING_RULES: list[dict] = [
    {
        "key": "routing.csr_override",
        "label": "CSR Manual Override (body instruction)",
        "description": "Honor any explicit CSR-typed routing instruction in the email body.",
        "priority": 1,
        "enabled": True,
        "predicates": [{"kind": "ctx_field", "field": "csr_override.has_override", "value": True}],
        "routing_target": "{{csr_override.target}}",
        "magic_sku": None,
    },
    {
        "key": "routing.export",
        "label": "Export — non-US/CA destination",
        "description": "Customer ships to a country outside US/CA → Export Team queue.",
        "priority": 2,
        "enabled": True,
        "predicates": [
            {"kind": "extracted_country_not_in", "value": ["US", "USA", "CA", "CAN", "Canada", "United States"]},
        ],
        "routing_target": "EXPORT_TEAM_QUEUE",
        "magic_sku": "EXPORTDUMMY",
    },
    {
        "key": "routing.sow",
        "label": "SOW — Statement of Work",
        "description": "Email/order indicates a Statement of Work (Z-prefix SKU, EID#, Custom Solutions).",
        "priority": 3,
        "enabled": True,
        "predicates": [
            {"kind": "subject_or_body_contains", "value": ["Statement of Work", "Cover Letter", "EID #", "Custom Solutions"]},
            {"kind": "any_sku_starts_with", "value": ["Z"]},
        ],
        "routing_target": "SOW_TEAM_QUEUE",
        "magic_sku": "SOWDUMMY",
    },
    {
        "key": "routing.ebiz",
        "label": "eBiz — Keysight Used Equipment Store",
        "description": "Sender or PO# indicates Keysight-Used-Equipment-Store (eBiz_).",
        "priority": 4,
        "enabled": True,
        "predicates": [
            {"kind": "sender_contains", "value": EBIZ_SENDERS},
            {"kind": "po_number_starts_with", "value": ["eBiz_"]},
        ],
        "routing_target": "AMFO_Disty/Rental",
        "magic_sku": None,
    },
    {
        "key": "routing.disty_us_ca",
        "label": "Distributor — US/Canada",
        "description": "Customer name matches a US/CA distributor partner — auto-assign to AMFO_Disty/Rental queue.",
        "priority": 5,
        "enabled": True,
        "predicates": [
            {"kind": "customer_name_in", "value": DISTY_PARTNERS_US_CA},
        ],
        "routing_target": "AMFO_Disty/Rental",
        "magic_sku": None,
    },
    {
        "key": "routing.disty_lar",
        "label": "Distributor — Latin America Region",
        "description": "Customer name matches a LAR distributor partner — auto-assign to AMFO_Disty/Rental_LAR queue.",
        "priority": 6,
        "enabled": True,
        "predicates": [
            {"kind": "customer_name_in", "value": DISTY_PARTNERS_LAR},
        ],
        "routing_target": "AMFO_Disty/Rental_LAR",
        "magic_sku": None,
    },
    # Reference rows (data, not routing rules) so the disty list is editable in /kb.
    {
        "key": "disty_partners.us_ca",
        "label": "US/Canada disty partners (auto-AMFO)",
        "description": "List of distributor names that auto-route to AMFO_Disty/Rental.",
        "priority": 100,
        "enabled": True,
        "is_reference": True,
        "partners": DISTY_PARTNERS_US_CA,
    },
    {
        "key": "disty_partners.lar",
        "label": "LAR disty partners (auto-AMFO)",
        "description": "List of distributor names that auto-route to AMFO_Disty/Rental_LAR.",
        "priority": 101,
        "enabled": True,
        "is_reference": True,
        "partners": DISTY_PARTNERS_LAR,
    },
    {
        "key": "magic_skus",
        "label": "Magic SKUs (override routing)",
        "description": "CUSTOM PRODUCT / SOWDUMMY / EXPORTDUMMY override default routing.",
        "priority": 102,
        "enabled": True,
        "is_reference": True,
        "skus": MAGIC_SKUS,
    },
]


def all_rules() -> list[dict]:
    return ROUTING_RULES
# === v1.1 TASK-5 END ===
