"""Seed long email threads + cross-system fan-out (SF + SP).

For each scenario in THREAD_SCENARIOS, this script:
  1. Inserts every message as an Email row with proper RFC 5322 threading
     (Message-Id, In-Reply-To, References) so `walk_thread()` reconstructs the
     full chain.
  2. Generates any attachments cited in the message bodies (PO PDF, revised
     BOM XLSX, etc.) into `data/outputs/`.
  3. Uploads each generated attachment to SharePoint under
     `/Salesops/<customer_code>/<kind>/`.
  4. (Optional) stamps the resulting webUrl onto the relevant SF record's
     Document_Url__c — only meaningful for objects that have such a field
     (Asset, WorkOrder). Quote / Order / Invoice attachments are upload-only.

Idempotency: re-running is safe — Message-Ids are deterministic per scenario
so the second run finds the same Email rows already inserted and skips them.

Usage:
    python -m app.scripts.seed_threads                 # all scenarios, full fan-out
    python -m app.scripts.seed_threads --dry-run        # plan only, no writes
    python -m app.scripts.seed_threads --scenario aurora_q2o_en
"""
from __future__ import annotations

import argparse
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import OUTPUTS
from ..db import SessionLocal
from ..models import Customer, Email
from ..synthetic.attachments import make_bom_xlsx, make_po_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_threads")


CSR_EMAIL = "orderinbox@leewayhertz.com"
CSR_NAME = "ZBrain Sales Ops Desk"

THREAD_DOMAIN = "salesops-demo.zbrain.ai"


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

# Each scenario is a list of message dicts. Convention:
#   from: "buyer" or "csr"
#   subject: explicit on first message, "Re: <root_subject>" implicit on later
#   body: raw text (will be inserted into Email.body as-is)
#   attachments: optional list of {"kind": "po"|"bom", **kind_specific_params}
#   delay_min: minutes after previous message in the thread
#
# `kind` must be one of the keys in _ATTACHMENT_BUILDERS below.

AURORA_Q2O_EN = {
    "key": "aurora_q2o_en",
    "customer_code": "AURA-AUTO-119",
    "language": "en",
    "subject_root": "Q2O — QT-AURA-AUTO-119-DEMO conversion to PO + qty revision questions",
    "intent_hint": "quote_to_order",
    "messages": [
        # 1 — buyer initial PO request against an existing quote
        {
            "from": "buyer",
            "delay_min": 0,
            "body": (
                "Hi team,\n\n"
                "Please convert quote QT-AURA-AUTO-119-DEMO into a firm order. PO PO-AURA-AUTO-119-Q2O-1001 attached.\n\n"
                "Couple of clarifications before you book it:\n"
                "  • Is the lead time on the SMU still 6 weeks?\n"
                "  • Confirm Net 45 terms — our AP is on a Net 45 cycle this quarter.\n"
                "  • We may revise quantities on line 2 (KS-SCOPE) — will confirm by EOW.\n\n"
                "Thanks,\nMeera"
            ),
            "attachments": [
                {"kind": "po", "po_number": "PO-AURA-AUTO-119-Q2O-1001",
                 "line_items": [
                    {"sku": "KS-SMU-989545", "description": "Precision Source/Measure Unit, 2-Ch", "qty": 4, "unit_price": 18250},
                    {"sku": "KS-SCOPE-666390", "description": "Mixed-signal oscilloscope, 4-Ch", "qty": 6, "unit_price": 12400},
                 ]},
            ],
        },
        # 2 — CSR ack + lead time answer
        {
            "from": "csr",
            "delay_min": 28,
            "body": (
                "Hi Meera,\n\n"
                "Got the PO — kicking off the validation now. Quick answers:\n"
                "  • SMU lead time: 6 weeks ex-works, confirmed.\n"
                "  • Net 45 — that matches your account terms on file. No issue.\n"
                "  • Quantity revision — happy to wait until EOW. If you can let us know by Friday 16:00 Local, we'll lock it in this run; otherwise we'll book at 6 units and amend with a change order.\n\n"
                "I'll send the SOA the moment line items reconcile.\n\n"
                "Best,\nZBrain Sales Ops"
            ),
            "attachments": [],
        },
        # 3 — buyer asks about export classification
        {
            "from": "buyer",
            "delay_min": 142,
            "body": (
                "One more — what's the ECCN classification on the SMU? I need it for our internal export-control sheet.\n\n"
                "Also, can the SOA reference our internal cost center 4421-EE-LAB?\n"
            ),
            "attachments": [],
        },
        # 4 — CSR replies with classification
        {
            "from": "csr",
            "delay_min": 35,
            "body": (
                "ECCN for the SMU (KS-SMU-989545) is 3A292.b. Country of origin: US. HTS: 9030.84.0000. "
                "Happy to drop those onto the SOA cover page.\n\n"
                "Cost center 4421-EE-LAB will go on the SOA reference field, no problem.\n"
            ),
            "attachments": [],
        },
        # 5 — buyer revises qty (with revised BOM xlsx)
        {
            "from": "buyer",
            "delay_min": 1110,  # next day
            "body": (
                "Update from procurement — we've increased line 2 (KS-SCOPE) from 6 to 9 units. Revised BOM attached. "
                "Please re-quote and rebook with the new qty.\n\n"
                "Same delivery and payment terms as above.\n"
            ),
            "attachments": [
                {"kind": "bom", "po_number": "PO-AURA-AUTO-119-Q2O-1001",
                 "line_items": [
                    {"sku": "KS-SMU-989545", "description": "Precision Source/Measure Unit, 2-Ch", "qty": 4, "unit_price": 18250},
                    {"sku": "KS-SCOPE-666390", "description": "Mixed-signal oscilloscope, 4-Ch", "qty": 9, "unit_price": 12400},
                 ]},
            ],
        },
        # 6 — CSR acknowledges, asks about volume discount eligibility
        {
            "from": "csr",
            "delay_min": 22,
            "body": (
                "Got the revised BOM — qty 9 on the scope crosses our volume tier 2 (≥ 8 units), "
                "so unit price drops from $12,400 → $11,800. New line subtotal: $106,200 (was $74,400 at qty 6, $111,600 at qty 9 list).\n\n"
                "Net new order total: $179,200. OK to proceed at the discounted price? "
                "If yes I'll cut the SOA today.\n"
            ),
            "attachments": [],
        },
        # 7 — buyer accepts
        {
            "from": "buyer",
            "delay_min": 18,
            "body": (
                "Yes — proceed at the discounted price. Approved.\n\n"
                "Please also note in the SOA that the scopes ship to our El Segundo lab, attn: Engineering Receiving. "
                "Same address as before.\n"
            ),
            "attachments": [],
        },
        # 8 — CSR confirms booking
        {
            "from": "csr",
            "delay_min": 14,
            "body": (
                "Booked. Order SO-AURA-AUTO-119-Q2O-1001 created against PO-AURA-AUTO-119-Q2O-1001.\n"
                "  • Net total $179,200 (Net 45)\n"
                "  • Ship-to: Aurora Automotive — El Segundo Lab, Engineering Receiving\n"
                "  • SOA + SF Order link will follow within the hour.\n\n"
                "Thanks!\n"
            ),
            "attachments": [],
        },
    ],
}

# Sakura Semiconductor — service order / on-site cal scheduling — 6 messages, JA
SAKURA_SERVICE_JA = {
    "key": "sakura_service_ja",
    "customer_code": "SAKURA-SEMI-101",
    "language": "ja",
    "subject_root": "オンサイト校正のご依頼 — 装置3台 (KS-SMU / KS-SCOPE / KS-SA)",
    "intent_hint": "service_order",
    "messages": [
        {
            "from": "buyer",
            "delay_min": 0,
            "body": (
                "ZBrain Sales Ops 様\n\n"
                "お世話になっております。Sakura Semiconductor の注文担当です。\n\n"
                "下記3台のオンサイト校正を依頼いたします:\n"
                "  • KS-SMU-989545 (シリアル: KS-SMU-989545)\n"
                "  • KS-SCOPE-666390 (シリアル: KS-SCOPE-666390)\n"
                "  • KS-SA-260227 (シリアル: KS-SA-260227)\n\n"
                "標準は ANSI/NCSL Z540.3 で、as-found / as-left の両方を希望します。\n"
                "可能な日程を教えてください。月末までに完了したいです。\n\n"
                "よろしくお願いします。\n注文 (Sakura Semi)"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 31,
            "body": (
                "ご連絡ありがとうございます。\n\n"
                "3台のオンサイト校正、承りました。 ANSI/NCSL Z540.3 + as-found/as-left で進めます。\n"
                "技術者の空き状況を確認し、本日中に候補日を2つご提案します。\n"
                "事前確認: 校正実施場所はメインラボ (3階) でよろしいですか?\n\n"
                "ZBrain Sales Ops Desk"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 95,
            "body": (
                "はい、3階のメインラボでお願いします。\n"
                "アクセス手続きは事前にお伝えください。\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 187,
            "body": (
                "候補日:\n"
                "  • 5月18日 (月) 09:00–17:00\n"
                "  • 5月20日 (水) 09:00–17:00\n\n"
                "技術者: L. 大谷 (主任), K. 佐藤 (補助)\n"
                "アクセス申請書を別途送付します。\n\n"
                "ご都合の良い方をお知らせください。"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 1620,  # next day
            "body": (
                "5月20日 (水) でお願いします。\n"
                "受付は1階総合受付で、内線 4421 (注文担当) までご連絡ください。\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 18,
            "body": (
                "5月20日 (水) で確定しました。 WO番号: WO-SAKURA-SEMI-101-CAL-2026-001\n"
                "技術者: L. 大谷, K. 佐藤\n"
                "完了次第、校正証明書をお送りします (SharePointリンク + PDF)。\n\n"
                "ありがとうございます。"
            ),
            "attachments": [],
        },
    ],
}


# Bluehawk Defense — hold-release on a flagged order — 8 messages, EN, multiple
# compliance/legal back-and-forth
BLUEHAWK_HOLD_EN = {
    "key": "bluehawk_hold_en",
    "customer_code": "BLUEH-DEF-021",
    "language": "en",
    "subject_root": "Order SO-BLUEH-DEF-021-2002 — release request after compliance hold",
    "intent_hint": "hold_release",
    "messages": [
        {
            "from": "buyer",
            "delay_min": 0,
            "body": (
                "Hi team,\n\n"
                "Our order SO-BLUEH-DEF-021-2002 went on compliance hold last week. "
                "What's needed to clear it? We need delivery before May 30.\n\n"
                "Aaron Brewer\nProgram Manager"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 26,
            "body": (
                "Hi Aaron,\n\n"
                "Hold reason on file: ECCN classification mismatch on line 1 (KS-SA-260227). "
                "Our trade compliance flagged that the destination indicated on the PO doesn't match "
                "the BIS license on file for that ECCN.\n\n"
                "To release we'll need either:\n"
                "  • Confirmation that ship-to is the original DD address (Falls Church, VA), or\n"
                "  • A new BIS authorization referencing the alternate destination.\n\n"
                "ZBrain Sales Ops"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 73,
            "body": (
                "Confirmed — ship-to is the original Falls Church VA DD address. There's no destination change. "
                "I'll have our trade compliance officer email you a signed end-use statement today.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 38,
            "body": (
                "Got it. Once we have the signed end-use statement we can release the hold.\n"
                "FYI we'll route this for legal review (24h SLA). I'll confirm release to you the moment that lands.\n"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 240,
            "body": (
                "Trade compliance just sent the end-use statement to your team. Please let me know if anything else is needed.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 12,
            "body": (
                "Received the end-use statement. Forwarded to legal. Will confirm by end of business tomorrow.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 1410,  # next day
            "body": (
                "Update — legal cleared the hold. Releasing SO-BLUEH-DEF-021-2002 now.\n"
                "Updated promised ship date: May 26. Carrier: FedEx Priority Overnight.\n"
                "Tracking will follow once the warehouse picks it.\n"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 8,
            "body": (
                "Thanks — appreciate the fast turn. Standing by for tracking.\n"
            ),
            "attachments": [],
        },
    ],
}


# Finolab — WO update with technician questions — 7 messages, EN+ES mixed
FINOLAB_WO_MIXED = {
    "key": "finolab_wo_mixed",
    "customer_code": "FINOLA-EU-061",
    "language": "en",
    "subject_root": "WO update — WO-FINOLA-EU-061-3010 add 2 more assets to the open cal job",
    "intent_hint": "wo_update_request",
    "messages": [
        {
            "from": "buyer",
            "delay_min": 0,
            "body": (
                "Hi,\n\n"
                "Open WO is WO-FINOLA-EU-061-3010 (on-site calibration). We'd like to add two more assets to "
                "the same visit so the technician handles them in one trip:\n"
                "  • KS-SMU-989545 (S/N: KS-SMU-989545)\n"
                "  • KS-AWG-686075 (S/N: KS-AWG-686075)\n\n"
                "Same standards as the original WO. Please confirm the addendum is feasible for the scheduled date.\n\n"
                "Linda Voss"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 22,
            "body": (
                "Hi Linda,\n\n"
                "Two more assets on the same visit is fine — checked with the technician (L. Ortega). "
                "ETA shifts from 4h to ~6.5h on-site, but same calendar day works.\n\n"
                "I'll add them to the WO description and update the SOW. Cost addendum: +€1,840 for the additional 2 assets.\n"
                "Confirm to proceed?\n"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 41,
            "body": (
                "Confirmed — proceed at +€1,840.\n\n"
                "Una pregunta más: el técnico habla español? Nuestros operadores prefieren la conversación técnica en español.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 14,
            "body": (
                "Sí — L. Ortega es bilingüe, EN/ES. Sin problema para la conversación técnica en español.\n\n"
                "Updated the WO. Rev 2 attached on internal trace. WO-FINOLA-EU-061-3010 now includes the 2 added assets.\n"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 970,  # next day
            "body": (
                "El técnico llegó esta mañana. Una pregunta sobre la verificación as-found del SMU — "
                "el operador notó una desviación en el canal 2. ¿Eso requiere una NCR separada o se documenta en la cert?\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 9,
            "body": (
                "Buenos días — la desviación as-found se documenta en el certificado bajo \"As-Found Summary\". "
                "Si está fuera de tolerancia, también generamos una NCR automática. L. Ortega ya está consciente y "
                "lo está documentando ahora.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 145,
            "body": (
                "Update — calibración completa. Todos los activos as-left dentro de tolerancia. "
                "Cert PDFs en SharePoint + linked en SF Asset records.\n"
                "WO closed. Invoice (€8,420) follows in 24h.\n"
            ),
            "attachments": [],
        },
    ],
}


# Meridian — quote revision (price counter-offer) — 6 messages, ES
MERIDIAN_QUOTE_ES = {
    "key": "meridian_quote_es",
    "customer_code": "MERID-COMM-077",
    "language": "es",
    "subject_root": "Cotización Q-MERID-COMM-077-1001 — contrapropuesta de precio",
    "intent_hint": "quote_revision",
    "messages": [
        {
            "from": "buyer",
            "delay_min": 0,
            "body": (
                "Hola equipo,\n\n"
                "Recibimos la cotización Q-MERID-COMM-077-1001. El precio total ($142,800) está fuera "
                "de nuestro presupuesto autorizado para este proyecto. Necesitaríamos un descuento del 12% "
                "para aprobarlo internamente.\n\n"
                "¿Es posible una revisión? Pago en 30 días si avanzamos esta semana.\n\n"
                "Saludos,\nCarlos Iglesias"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 33,
            "body": (
                "Hola Carlos,\n\n"
                "12% es difícil al volumen actual, pero podemos ofrecer:\n"
                "  • 7% de descuento en línea (precio neto, sin penalización en garantía)\n"
                "  • +24 meses de cobertura de calibración sin cargo (valor ~$3,200)\n\n"
                "Total revisado: $132,804 (era $142,800). ¿Te funciona?\n\n"
                "ZBrain Sales Ops"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 87,
            "body": (
                "El 7% más la cobertura de cal es interesante. Déjame validarlo con finanzas — respuesta antes del cierre del día.\n"
            ),
            "attachments": [],
        },
        {
            "from": "buyer",
            "delay_min": 312,
            "body": (
                "Aprobado por finanzas. Procedamos con la cotización revisada Q-MERID-COMM-077-1001 R2 ($132,804, "
                "incluyendo cobertura de cal extendida). Envíanos la PO conforme.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 12,
            "body": (
                "Perfecto. Generando Q-MERID-COMM-077-1001 R2 ahora — recibirás el PDF de la cotización revisada en los próximos minutos. "
                "Una vez firmen, podemos convertirla a orden directamente.\n"
            ),
            "attachments": [],
        },
        {
            "from": "csr",
            "delay_min": 8,
            "body": (
                "Cotización R2 enviada (PDF en SharePoint, link en el SF Quote record). "
                "Términos: Net 30, FOB Origin, ECCN EAR99 en todas las líneas.\n"
                "Avísame cuando lo firmen y emitimos la orden.\n"
            ),
            "attachments": [],
        },
    ],
}


# More scenarios can be added here following the same shape. Kept as a list so
# --scenario CLI flag can target a specific one.
from .seed_threads_extra import EXTRA_SCENARIOS

SCENARIOS: list[dict[str, Any]] = [
    AURORA_Q2O_EN,
    SAKURA_SERVICE_JA,
    BLUEHAWK_HOLD_EN,
    FINOLAB_WO_MIXED,
    MERIDIAN_QUOTE_ES,
] + EXTRA_SCENARIOS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _customer_addr(c: Customer) -> str:
    addr_hq = next((a for a in (c.addresses or []) if a.get("type") == "headquarters"), None) or (c.addresses or [{}])[0]
    if not isinstance(addr_hq, dict):
        addr_hq = {}
    parts = [addr_hq.get("line1"), addr_hq.get("city"), addr_hq.get("region"), addr_hq.get("country")]
    return ", ".join(p for p in parts if p) or c.name


def _msg_id(scenario_key: str, idx: int) -> str:
    return f"<thread-{scenario_key}-{idx:02d}@{THREAD_DOMAIN}>"


def _stable_path(scenario_key: str, kind: str, idx: int, ext: str) -> Path:
    """Deterministic outputs/ path so re-runs overwrite cleanly."""
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    return OUTPUTS / f"thread_{scenario_key}_{kind}_{idx:02d}.{ext}"


def _build_attachment(scenario_key: str, msg_idx: int, att: dict, customer: Customer, *, dry_run: bool) -> dict | None:
    """Generate the attachment file (PDF/XLSX) and return the Email.attachments entry.

    Email.attachments[i] = {"name": <displayed-filename>, "path": <abs path>, "type": <ext>}
    """
    kind = att["kind"]
    if kind == "po":
        out = _stable_path(scenario_key, "po", msg_idx, "pdf")
        if not dry_run and not out.exists():
            make_po_pdf(
                out,
                customer_name=customer.name,
                customer_addr=_customer_addr(customer),
                po_number=att["po_number"],
                issue_date=datetime.now(timezone.utc).date(),
                line_items=att["line_items"],
                payment_terms=customer.payment_terms or "Net 45",
            )
        return {"name": out.name, "path": str(out), "type": "pdf"}
    if kind == "bom":
        out = _stable_path(scenario_key, "bom", msg_idx, "xlsx")
        if not dry_run and not out.exists():
            make_bom_xlsx(
                out,
                customer_name=customer.name,
                quote_number=att.get("quote_number") or att.get("po_number") or "",
                line_items=att["line_items"],
            )
        return {"name": out.name, "path": str(out), "type": "xlsx"}
    log.warning("unknown attachment kind: %s", kind)
    return None


def _from_addr(role: str, customer: Customer, contact_email: str | None) -> str:
    if role == "buyer":
        return contact_email or customer.email or f"orders@{customer.code.lower()}.example"
    return f"{CSR_NAME} <{CSR_EMAIL}>"


def _to_addr(role: str, customer: Customer, contact_email: str | None) -> str:
    if role == "buyer":
        return CSR_EMAIL
    return contact_email or customer.email or f"orders@{customer.code.lower()}.example"


def _seed_one_thread(
    db: Session,
    scenario: dict[str, Any],
    *,
    base_time: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    key = scenario["key"]
    customer = db.query(Customer).filter_by(code=scenario["customer_code"]).first()
    if not customer:
        return {"ok": False, "scenario": key, "error": f"customer {scenario['customer_code']} not found"}

    # Pick the customer's primary contact email for buyer-side messages.
    from ..models import Contact
    primary = (
        db.query(Contact)
        .filter_by(customer_id=customer.id, is_primary=True)
        .first()
    )
    contact_email = primary.email if primary else customer.email

    summary = {
        "ok": True,
        "scenario": key,
        "customer": customer.code,
        "messages_inserted": 0,
        "messages_skipped_existing": 0,
        "attachments_generated": 0,
    }

    msg_ids: list[str] = []
    cumulative_delay_min = 0

    # Compute the total scenario span up front so we can anchor the timeline
    # backwards from "now" instead of forwards from a fixed base. Long-running
    # scenarios (multi-day investigations) otherwise overflow into the future
    # and the inbox starts showing nonsense like "received 4 months from now".
    total_span_min = sum(int(m.get("delay_min") or 0) for m in scenario["messages"])
    anchor_now = datetime.now(timezone.utc) - timedelta(minutes=15)
    scenario_start = anchor_now - timedelta(minutes=total_span_min)
    # If the upstream caller provided a base_time anchored further in the
    # past, honour the older base; otherwise pull the scenario forward so it
    # always lands at-or-before now.
    effective_base = min(base_time, scenario_start) if total_span_min else base_time

    for idx, msg_spec in enumerate(scenario["messages"], start=1):
        cumulative_delay_min += int(msg_spec.get("delay_min") or 0)
        ts = effective_base + timedelta(minutes=cumulative_delay_min)
        # Hard ceiling: never insert a future-dated email even if the math
        # somehow drifts past now.
        ceiling = datetime.now(timezone.utc) - timedelta(seconds=1)
        if ts > ceiling:
            ts = ceiling

        msg_id = _msg_id(key, idx)
        in_reply_to = msg_ids[-1] if msg_ids else None
        references_chain = " ".join(msg_ids) if msg_ids else None
        msg_ids.append(msg_id)

        # Idempotent: skip if this Message-Id already exists.
        existing = db.query(Email).filter(Email.message_id == msg_id).first()
        if existing:
            summary["messages_skipped_existing"] += 1
            continue

        from_addr = _from_addr(msg_spec["from"], customer, contact_email)
        subject = (
            scenario["subject_root"]
            if idx == 1
            else f"Re: {scenario['subject_root']}"
        )

        attachments_meta: list[dict] = []
        for att in msg_spec.get("attachments") or []:
            built = _build_attachment(key, idx, att, customer, dry_run=dry_run)
            if built:
                attachments_meta.append(built)
                summary["attachments_generated"] += 1

        if dry_run:
            log.info(
                "[DRY] would insert msg %02d/%d: from=%s subj=%s attachments=%d",
                idx, len(scenario["messages"]), from_addr,
                subject[:50], len(attachments_meta),
            )
            continue

        e = Email(
            received_at=ts,
            from_address=from_addr,
            customer_id=customer.id,
            subject=subject,
            body=msg_spec["body"],
            language_hint=scenario.get("language") or customer.language or "en",
            attachments=attachments_meta,
            status="new",
            message_id=msg_id,
            in_reply_to=in_reply_to,
            email_references=references_chain,
        )
        db.add(e)
        summary["messages_inserted"] += 1

    if not dry_run:
        db.commit()
    log.info("scenario=%s summary=%s", key, summary)
    return summary


def seed_all(*, scenario_filter: str | None = None, dry_run: bool = False) -> list[dict[str, Any]]:
    db = SessionLocal()
    base_time = datetime.now(timezone.utc) - timedelta(days=2)
    out: list[dict[str, Any]] = []
    try:
        for scenario in SCENARIOS:
            if scenario_filter and scenario["key"] != scenario_filter:
                continue
            out.append(_seed_one_thread(db, scenario, base_time=base_time, dry_run=dry_run))
            base_time += timedelta(hours=2)  # space scenarios apart
    finally:
        db.close()
    return out


def upload_thread_attachments_to_sp(*, dry_run: bool = False) -> dict[str, Any]:
    """Upload every `thread_*` file we just generated to SharePoint.

    Routed under /Salesops/threads/<scenario_key>/. We don't stamp these into
    SF — they're tied to inbound emails, not master records. The trace UI
    surfaces them as Email.attachments via the existing local file path."""
    from .sharepoint_stamp import upload_to_sharepoint

    db = SessionLocal()
    summary = {"uploaded": 0, "errors": 0, "files": []}
    try:
        for fp in sorted(OUTPUTS.glob("thread_*")):
            scenario_key = fp.stem.split("_", 2)[1] if fp.stem.startswith("thread_") else "misc"
            if dry_run:
                log.info("[DRY] would upload %s -> /threads/%s/", fp.name, scenario_key)
                continue
            res = upload_to_sharepoint(
                db,
                local_path=fp,
                subfolder=f"threads/{scenario_key}",
                overwrite=True,
            )
            if res.get("ok"):
                summary["uploaded"] += 1
                summary["files"].append({"name": fp.name, "url": res.get("sp_url")})
            else:
                summary["errors"] += 1
                log.warning("SP upload failed for %s: %s", fp.name, res.get("error"))
    finally:
        db.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description="Seed long email threads with cross-system fan-out.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scenario", help="Only seed the given scenario key")
    parser.add_argument("--skip-sp", action="store_true", help="Skip SharePoint uploads")
    args = parser.parse_args()

    log.info("=== Seeding email threads (dry_run=%s, scenario=%s) ===", args.dry_run, args.scenario or "ALL")
    results = seed_all(scenario_filter=args.scenario, dry_run=args.dry_run)
    for r in results:
        log.info("RESULT: %s", r)

    if not args.skip_sp:
        log.info("=== Uploading thread attachments to SharePoint ===")
        sp = upload_thread_attachments_to_sp(dry_run=args.dry_run)
        log.info("SP summary: %s", sp)


if __name__ == "__main__":
    main()
