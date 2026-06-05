"""Trade Order Entry end-to-end test corpus.

Seeds 5 customer emails covering every distinct path in the TOE workflow:

  TOE-001 · Happy path (L4 auto)
      Clean PO with matched quote; AIOA passes; SF Order written; SOA filed;
      Case → Booked / automation_complete.

  TOE-002 · AIOA fallout (CSR review)
      PO with export-control flag (ECCN restricted item) → AIOA_FAIL → routed
      to AI OA Fallout queue; Stage 5 drafts a clarification email for CSR.

  TOE-003 · Quote-to-PO delta (Quote Update + Q2O)
      PO with quantity revision vs referenced quote; 4.3a Quote Update fires
      with delta CaseComment; 4.3b Q2O Conversion records the promotion.

  TOE-004 · Existing CCC adoption (Step 7 update branch)
      Customer reply to a prior PO thread; In-Reply-To header points at the
      parent message. Stage 3.0 picks up the thread parent, adopts existing
      Case; Stage 4.0a posts attach+chatter+status-flip.

  TOE-005 · Ambiguous CCC match (HITL gate)
      PO# referenced in the email matches multiple recent open Cases.
      Stage 3.0 detects ambiguity, caps feasibility at 0.65, drops tier to
      L3/L2, queues for CSR review with clarification draft.

Run:
    python -m app.scripts.seed_toe_corpus

Outputs the email_id → seed-code map. Each email can then be submitted to
the pipeline pool via POST /api/pipelines/run/{email_id}.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `app.*` importable when run as a script.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Customer, Email

log = logging.getLogger("seed_toe_corpus")

# Reuse the synthetic PO maker from the existing seed script so attachments
# look identical to the rest of the demo corpus.
from app.scripts.seed_use_case_paths import _make_po_pdf_for, _pick_customer


def _make_email(
    db: Session, *,
    code: str,
    subject: str,
    body: str,
    customer: Customer,
    attachments: list[dict] | None = None,
    in_reply_to: str | None = None,
    email_references: str | None = None,
) -> Email:
    now = datetime.now(timezone.utc)
    msg_id = f"<toe-{code.lower()}-{int(now.timestamp())}@keysight.demo>"
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
        in_reply_to=in_reply_to,
        email_references=email_references,
    )
    db.add(e)
    db.flush()
    return e


def seed_toe_corpus(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    cust = _pick_customer(db, "AURA-AUTO-119") or _pick_customer(db, "MERID-COMM-077")
    if not cust:
        raise RuntimeError("seed prerequisite missing: customer AURA-AUTO-119 / MERID-COMM-077")

    # ────────────────────────────────────────────────────────────────────────
    # TOE-001 — Happy path
    # ────────────────────────────────────────────────────────────────────────
    po1 = _make_po_pdf_for(
        code="TOE-001",
        po_number="PO-TOE001-2026-2001",
        customer=cust,
        line_items=[
            {"sku": "N9020B", "description": "MXA Signal Analyzer", "qty": 2, "unit_price": 36400.00},
            {"sku": "16823A", "description": "Portable Logic Analyzer", "qty": 4, "unit_price": 14200.00},
        ],
        quote_reference="Q-AURA-2026-2001",
        payment_terms="Net 30",
        ship_date="2026-06-15",
    )
    out["TOE-001"] = _make_email(
        db, code="TOE-001",
        subject="PO-TOE001-2026-2001 — happy-path acknowledgement",
        body=(
            "Hello Keysight team,\n\n"
            "Please find our purchase order PO-TOE001-2026-2001 attached. Quote reference "
            "Q-AURA-2026-2001. Net 30 terms. Requested ship 2026-06-15.\n\n"
            "Please acknowledge and send the SOA at your earliest.\n\nThanks."
        ),
        customer=cust,
        attachments=[po1],
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # TOE-002 — AIOA fallout (ECCN restricted item)
    # ────────────────────────────────────────────────────────────────────────
    po2 = _make_po_pdf_for(
        code="TOE-002",
        po_number="PO-TOE002-2026-2002",
        customer=cust,
        line_items=[
            {"sku": "N9030B-EXPORT-ECCN3A002", "description": "PXA Signal Analyzer · ECCN 3A002 restricted", "qty": 1, "unit_price": 89500.00},
        ],
        quote_reference="Q-AURA-2026-2002",
        payment_terms="Net 30",
        ship_date="2026-06-22",
    )
    out["TOE-002"] = _make_email(
        db, code="TOE-002",
        subject="PO-TOE002-2026-2002 — PXA Signal Analyzer (ECCN-flagged)",
        body=(
            "Hi Keysight,\n\nPO-TOE002-2026-2002 for one PXA Signal Analyzer. End-use is "
            "automotive radar development. Please process and confirm ship date.\n\nThanks."
        ),
        customer=cust,
        attachments=[po2],
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # TOE-003 — Quote-to-PO delta (qty + price changes vs original quote)
    # ────────────────────────────────────────────────────────────────────────
    po3 = _make_po_pdf_for(
        code="TOE-003",
        po_number="PO-TOE003-2026-2003",
        customer=cust,
        line_items=[
            # Quote had qty=2, PO has qty=3; same SKU
            {"sku": "N9020B", "description": "MXA Signal Analyzer · revised qty", "qty": 3, "unit_price": 36400.00},
            # Quote had qty=4 at $14,200; PO has qty=4 at $13,800 (negotiated)
            {"sku": "16823A", "description": "Portable Logic Analyzer · negotiated unit_price", "qty": 4, "unit_price": 13800.00},
        ],
        quote_reference="Q-AURA-2026-0501",  # references same quote as TOE-001 — system should detect deltas
        payment_terms="Net 45",
        ship_date="2026-07-01",
    )
    out["TOE-003"] = _make_email(
        db, code="TOE-003",
        subject="PO-TOE003-2026-2003 — Q-AURA-2026-0501 acceptance with revisions",
        body=(
            "Hi team,\n\nWe're accepting quote Q-AURA-2026-0501 with two changes:\n"
            "  • N9020B qty 2 → 3\n  • 16823A unit_price 14,200 → 13,800 (negotiated)\n\n"
            "Net 45. Ship 2026-07-01. PO-TOE003-2026-2003 attached."
        ),
        customer=cust,
        attachments=[po3],
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # TOE-004 — Existing CCC adoption (thread reply to TOE-001's message-id)
    # ────────────────────────────────────────────────────────────────────────
    parent_msg_id = None
    if out.get("TOE-001"):
        parent = db.get(Email, out["TOE-001"])
        parent_msg_id = parent.message_id if parent else None
    out["TOE-004"] = _make_email(
        db, code="TOE-004",
        subject="Re: PO-TOE001-2026-2001 — corrected ship-to address",
        body=(
            "Hi Keysight,\n\nQuick correction on PO-TOE001-2026-2001 we sent earlier today: "
            "please use this ship-to instead:\n\n"
            "Aurora Automotive Electronics · Warehouse B\n"
            "9100 Industrial Pkwy, Detroit MI 48201\n\n"
            "Everything else on the PO stays the same. Thanks for adjusting before SOA generation."
        ),
        customer=cust,
        in_reply_to=parent_msg_id,
        email_references=parent_msg_id,
    ).id

    # ────────────────────────────────────────────────────────────────────────
    # TOE-005 — Ambiguous CCC match (PO# similar to multiple recent cases)
    # ────────────────────────────────────────────────────────────────────────
    po5 = _make_po_pdf_for(
        code="TOE-005",
        po_number="PO-UCA1-2026-1001",  # collides with the long-standing UC1-A1 PO# already in SF
        customer=cust,
        line_items=[
            {"sku": "N9020B", "description": "MXA Signal Analyzer", "qty": 1, "unit_price": 36400.00},
        ],
        quote_reference="Q-AURA-2026-AMBIGUOUS",
        payment_terms="Net 30",
        ship_date="2026-06-30",
    )
    out["TOE-005"] = _make_email(
        db, code="TOE-005",
        subject="PO-UCA1-2026-1001 — duplicate reference to test dedup",
        body=(
            "Hello team,\n\nResending PO-UCA1-2026-1001 for the MXA Signal Analyzer. "
            "Please process or merge with the prior request if it's already in flight.\n\nThanks."
        ),
        customer=cust,
        attachments=[po5],
    ).id

    db.commit()
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db = SessionLocal()
    try:
        ids = seed_toe_corpus(db)
        print("Trade Order Entry seed corpus inserted:")
        for code, email_id in ids.items():
            print(f"  {code}  email_id={email_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
