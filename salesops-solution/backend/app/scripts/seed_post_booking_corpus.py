"""Post-Booking & Service-Order test corpus.

Closes the coverage gap identified against the SalesOps RFP. Trade Order Entry
already has a five-case corpus (seed_toe_corpus.py); this script does the same
for the rest of the RFP-named flows that previously had no test seeds:

  HR-001  hold_release       (credit hold cleared by paid-up invoice)
  HR-002  hold_release       (export-compliance hold cleared by BIS approval ID)
  DC-001  delivery_change    (ship-to address change)
  DC-002  delivery_change    (carrier swap to DHL)
  TCO-001 trade_change_order (qty bump on one line)
  TCO-002 trade_change_order (cancel one line, add a new line)
  WSI-001 wo_status_inquiry  (status check on three open WOs, audit-Friday urgency)
  SC-001  service_contract_request (renewal quote)
  SC-002  service_contract_request (new multi-year coverage request)

Run:
    python -m app.scripts.seed_post_booking_corpus

Each email lands in `emails` table with status='new' and the appropriate
intent hint. Trigger via /api/pipelines/run/{email_id} to push each one
through the full pipeline.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Customer, Email
from app.scripts.seed_use_case_paths import _pick_customer

log = logging.getLogger("seed_post_booking_corpus")


def _make_email(
    db: Session,
    *,
    code: str,
    subject: str,
    body: str,
    customer: Customer,
    attachments: list[dict] | None = None,
) -> Email:
    now = datetime.now(timezone.utc)
    msg_id = f"<pb-{code.lower()}-{int(now.timestamp())}@keysight.demo>"
    e = Email(
        subject=f"[{code}] {subject}",
        body=body,
        from_address=getattr(customer, "email", None) or "buyer@example.com",
        received_at=now,
        status="new",
        customer_id=customer.id,
        attachments=attachments or [],
        language_hint="en",
        message_id=msg_id,
    )
    db.add(e)
    db.flush()
    return e


def seed_post_booking_corpus(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    cust = _pick_customer(db, "AURA-AUTO-119") or _pick_customer(db, "MERID-COMM-077")
    if not cust:
        raise RuntimeError("seed prerequisite missing: customer AURA-AUTO-119 / MERID-COMM-077")

    # ────────────────────────────────────────────────────────────────────────
    # HR-001 — Hold Release (credit hold cleared by paid invoice)
    # ────────────────────────────────────────────────────────────────────────
    out["HR-001"] = _make_email(
        db,
        code="HR-001",
        subject="Order SO-AURA-2026-30401 on credit hold — invoice cleared",
        body=(
            "Hi Keysight team,\n\n"
            "Order SO-AURA-2026-30401 (against our PO-AURA-2026-0401) was placed on a "
            "credit hold last week pending payment of invoice INV-2025-099887. Our "
            "accounts team confirmed the wire transfer cleared on 2026-05-12, "
            "reference WIRE-USB-552201. Could you release the hold and ship as soon as "
            "possible? Requested release date is 2026-05-20.\n\n"
            "Thanks,\nProcurement, Aurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # HR-002 — Hold Release (export-compliance, BIS approval received)
    # ────────────────────────────────────────────────────────────────────────
    out["HR-002"] = _make_email(
        db,
        code="HR-002",
        subject="Export hold on SO-AURA-2026-30402 — BIS license approved",
        body=(
            "Keysight Compliance,\n\n"
            "Order SO-AURA-2026-30402 was held for export-compliance review on "
            "ECCN 3A002.f screen. We received the BIS license approval today, "
            "license reference D-1129877-A001-2026 (attached on the customer "
            "portal record). Authorization is from our Trade Compliance Director, "
            "Marian Cole. Please release the hold and proceed with shipment to our "
            "Singapore facility per the original ship date 2026-05-30.\n\n"
            "Aurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # DC-001 — Delivery Change (ship-to address)
    # ────────────────────────────────────────────────────────────────────────
    out["DC-001"] = _make_email(
        db,
        code="DC-001",
        subject="Change ship-to on SO-AURA-2026-30410 — moving facility",
        body=(
            "Hi Keysight,\n\n"
            "We're relocating our test lab next week. Could you update the ship-to "
            "address on order SO-AURA-2026-30410 (PO-AURA-2026-0411) to the new "
            "facility:\n\n"
            "  Aurora Automotive Electronics\n"
            "  4400 Hyland Park Drive, Building 7\n"
            "  Auburn Hills, MI 48326\n"
            "  USA\n\n"
            "Carrier and Incoterm stay the same (FedEx, DAP). Reason: facility "
            "relocation, original ship-to is decommissioned 2026-06-01.\n\n"
            "Thanks,\nAurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # DC-002 — Delivery Change (carrier swap to DHL)
    # ────────────────────────────────────────────────────────────────────────
    out["DC-002"] = _make_email(
        db,
        code="DC-002",
        subject="Switch carrier to DHL on SO-AURA-2026-30412",
        body=(
            "Hi team,\n\n"
            "Could you swap the carrier on order SO-AURA-2026-30412 (PO-AURA-2026-0413) "
            "from FedEx to DHL Express? Our consolidator is offering better rates on "
            "the cross-border lane this quarter. Our DHL account number is "
            "DHL-AURA-118822. Everything else (ship date, ship-to, Incoterm) remains "
            "unchanged.\n\n"
            "Aurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # TCO-001 — Trade Change Order (qty bump)
    # ────────────────────────────────────────────────────────────────────────
    out["TCO-001"] = _make_email(
        db,
        code="TCO-001",
        subject="Increase qty on SO-AURA-2026-30501 — N9020B from 2 to 3",
        body=(
            "Hi Keysight,\n\n"
            "Could you amend order SO-AURA-2026-30501 (against our PO PO-AURA-2026-0501) "
            "and bump the quantity on line item N9020B from 2 units to 3 units? Unit "
            "price stays at the agreed quote rate of $36,400 per the original Q-AURA-2026-0501. "
            "All other line items unchanged. Ship date target stays 2026-06-30.\n\n"
            "Please confirm the updated order total.\n\n"
            "Thanks,\nAurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # TCO-002 — Trade Change Order (remove + add)
    # ────────────────────────────────────────────────────────────────────────
    out["TCO-002"] = _make_email(
        db,
        code="TCO-002",
        subject="Change order on SO-AURA-2026-30503 — drop 16823A, add E36312A",
        body=(
            "Keysight team,\n\n"
            "We need two changes against order SO-AURA-2026-30503 (our PO PO-AURA-2026-0503):\n\n"
            "  1. Remove line item 16823A (Portable Logic Analyzer) — 4 units. We have "
            "     existing capacity and don't need additional units in this cycle.\n"
            "  2. Add line item E36312A (Triple Output Power Supply) — 2 units at "
            "     unit price $1,640.00 per the prior Q-AURA-2026-0503 quote.\n\n"
            "Bill-to and ship-to are unchanged. Please send the revised order total "
            "and updated SOA.\n\n"
            "Aurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # WSI-001 — WO Status Inquiry (audit urgency)
    # ────────────────────────────────────────────────────────────────────────
    out["WSI-001"] = _make_email(
        db,
        code="WSI-001",
        subject="URGENT — status on three open WOs ahead of A2LA audit Friday",
        body=(
            "Hi Keysight Cal Lab,\n\n"
            "We have an A2LA surveillance audit this Friday 2026-05-22 and need a "
            "status check on three open calibration work orders. Could you reply with "
            "the current state, ETA, and as-found data where available:\n\n"
            "  • WO-2026-44721 — N5224B PNA, asset serial MY58020091\n"
            "  • WO-2026-44732 — E36312A Power Supply, asset serial US58410022\n"
            "  • WO-2026-44758 — 53230A Universal Counter, asset serial MY54100887\n\n"
            "If any of these need on-site recall, let us know today so we can plan.\n\n"
            "Thanks,\nMetrology Team, Aurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # SC-001 — Service Contract renewal quote
    # ────────────────────────────────────────────────────────────────────────
    out["SC-001"] = _make_email(
        db,
        code="SC-001",
        subject="Renewal quote — Cal Support contract CS-AURA-2024-0014 expires 2026-08-31",
        body=(
            "Hi Keysight Service team,\n\n"
            "Our existing calibration support contract CS-AURA-2024-0014 expires on "
            "2026-08-31 and we'd like to renew. Coverage is for our metrology fleet "
            "of 47 assets (the same asset list as the prior cycle). We want to keep "
            "annual on-site calibration, ANSI/NCSL Z540.3 compliance, and 24-hour "
            "turnaround on emergency recall.\n\n"
            "Could you put together a renewal quote with a three-year option as well? "
            "Targeting start date 2026-09-01.\n\n"
            "Thanks,\nProcurement, Aurora Automotive Electronics"
        ),
        customer=cust,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # SC-002 — New Service Contract coverage request
    # ────────────────────────────────────────────────────────────────────────
    out["SC-002"] = _make_email(
        db,
        code="SC-002",
        subject="New service contract request — Sigma Communications lab expansion",
        body=(
            "Hi Keysight,\n\n"
            "We're standing up a new RF compliance lab in Phoenix and would like a "
            "service contract covering 22 newly purchased Keysight instruments. "
            "Coverage requirements:\n\n"
            "  • Annual ISO/IEC 17025 calibration on all 22 assets\n"
            "  • A2LA traceability for FCC submissions\n"
            "  • Two emergency recall events per year, 48-hour SLA\n"
            "  • Three-year term starting 2026-07-01\n\n"
            "Please send a quote and the asset onboarding form. We can share the "
            "purchase records (POs) for cross-reference if needed.\n\n"
            "Thanks,\nSigma Communications RF Compliance"
        ),
        customer=cust,
    ).id

    db.commit()
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        result = seed_post_booking_corpus(db)
        print("Post-Booking + Service-Order seed corpus inserted:")
        for code, eid in result.items():
            print(f"  {code:<8}  email_id={eid}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
