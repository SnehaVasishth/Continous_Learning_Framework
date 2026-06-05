"""Seed synthetic emails covering every path in the 7 RFP use-case diagrams.

Produces 24 distinct emails — one per named path:
  - UC1 (Trade Order Entry):   A1 happy, A2 FCNV fallout, A3 AIOA fallout, A4 Q2O reconcile fallout
  - UC2 (Trade Change Order):  B1 happy, B2 FCNV fallout
  - UC3 (SOM auto-WO):         C1 single-asset, C2 multi-asset, C3 PO-without-WO, C4 system errored, C5 multi-asset SOM-CSR
  - UC4 (SOM WO update):       D1 update-no-PO, D2 update-with-PO-AIOA, D3 FCNV fallout, D4 multi-asset
  - UC5 (WO status):           E1 happy auto-reply, E2 FCNV fallout, E3 assign-to-CSR
  - UC6 (Service Contracts):   F1 happy, F2 FCNV fallout, F3 CTA Scope, F4 AI OA fallout
  - UC7 (SSD Change):          G1 happy factory handoff, G2 FCNV fallout

Each email carries a path tag in the subject line (e.g. "[UC1-A1] …") so the
test runner can match it back to the expected path.

For every email that references an attachment, the actual file is generated
on disk via the existing ReportLab / openpyxl templates so the case looks
like real enterprise inbound mail — PO PDFs with line items + T&Cs, quote
PDFs, asset-list spreadsheets, etc.

Email bodies are wrapped with the enterprise envelope (CAUTION external-email
banner on ~50%, signature block, confidentiality footer) before save.
"""
from __future__ import annotations

import argparse
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import UPLOADS
from app.db import SessionLocal
from app.models import Customer, Email
from app.synthetic.attachments import make_bom_xlsx, make_po_pdf


# Same wrapper the bulk seeder uses — kept in this module so the script
# stands alone without depending on the larger generate.py.
_CAUTION = (
    "**[CAUTION: This email originated from outside Keysight. Do not click "
    "links or open attachments unless you recognise the sender and know the "
    "content is safe.]**\n\n"
)

_SIG_TPL = (
    "\n\n--\n{name}\n{title}\n{company}\n{phone}\n\n"
    "----------------------------------------------------------------------\n"
    "This message and any attachments may contain confidential information "
    "intended only for the addressee. If you are not the intended recipient, "
    "please notify the sender and delete this message.\n"
    "----------------------------------------------------------------------"
)


def _wrap_envelope(body: str, *, customer_name: str, region_lang: str = "en") -> str:
    """Wrap a body string with the enterprise email envelope."""
    out = body
    if random.random() < 0.55:
        out = _CAUTION + out
    sig = _SIG_TPL.format(
        name=f"Procurement Team",
        title="Purchasing & Operations",
        company=customer_name or "Customer",
        phone="+1 555 0100",
    )
    return out + sig


def _pick_customer(db: Session, code: str | None = None) -> Customer | None:
    if code:
        c = db.query(Customer).filter_by(code=code).first()
        if c:
            return c
    return db.query(Customer).order_by(Customer.id).first()


def _make_po_pdf_for(
    *,
    code: str,
    po_number: str,
    customer: Customer | None,
    line_items: list[dict],
    quote_reference: str | None = None,
    payment_terms: str = "Net 45",
    ship_date: str | None = None,
    note: str | None = None,
) -> dict:
    """Materialise a PO PDF on disk under UPLOADS/use_case_seeds/ and return
    the attachment dict (name + kind + path) for the Email row."""
    out_dir = UPLOADS / "use_case_seeds"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{code}_{po_number}.pdf"
    out_path = out_dir / fname
    customer_name = (customer.name if customer else "Customer")
    customer_addr = ((customer.addresses or [{}])[0] if customer and customer.addresses else {}).get("street", "") if customer else ""
    if customer and customer.addresses:
        a0 = customer.addresses[0]
        customer_addr = ", ".join(filter(None, [a0.get("street", ""), a0.get("city", ""), a0.get("state", ""), a0.get("postal_code", "")]))
    try:
        make_po_pdf(
            out_path,
            customer_name=customer_name,
            customer_addr=customer_addr or "Address on file",
            po_number=po_number,
            issue_date=date.today(),
            line_items=line_items,
            payment_terms=payment_terms,
            requested_ship=ship_date,
            quote_reference=quote_reference,
            note=note,
            buyer_contact=(customer.email if customer else None) or "buyer@example.com",
        )
    except Exception as e:
        # Fall back to a placeholder file so the seed run doesn't crash.
        out_path.write_text(f"[stub PO {po_number} for {code}: PDF render failed: {e}]")
    return {
        "name": fname,
        "kind": "purchase_order",
        "path": f"use_case_seeds/{fname}",
        "size": out_path.stat().st_size if out_path.exists() else 0,
    }


def _make_xlsx_for(*, code: str, label: str) -> dict:
    """Make a small XLSX so the SOM multi-asset emails have a real attachment."""
    out_dir = UPLOADS / "use_case_seeds"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{code}_{label}.xlsx"
    out_path = out_dir / fname
    rows = [
        ["asset_id", "model", "serial", "location", "service_type", "requested_date"],
        ["A-001", "E5071C", "KEY-2202-0011", "Pasadena lab", "annual calibration", "2026-07-15"],
        ["A-002", "N5247B", "KEY-2202-0034", "Pasadena lab", "annual calibration", "2026-07-15"],
        ["A-003", "8975A", "KEY-2202-0099", "Pasadena lab", "annual calibration", "2026-07-15"],
    ]
    try:
        make_bom_xlsx(out_path, rows=rows)
    except Exception:
        # Trivial CSV fallback so the file exists.
        import csv
        with open(out_path.with_suffix(".csv"), "w") as f:
            csv.writer(f).writerows(rows)
        fname = fname.replace(".xlsx", ".csv")
        out_path = out_path.with_suffix(".csv")
    return {
        "name": fname,
        "kind": "asset_list",
        "path": f"use_case_seeds/{fname}",
        "size": out_path.stat().st_size if out_path.exists() else 0,
    }


def _e(db: Session, *, code: str, subject: str, body: str, lang: str = "en",
       customer: Customer | None = None, attachments: list[dict] | None = None) -> Email:
    if customer is None:
        customer = _pick_customer(db)
    from_addr = (customer.email if customer else "buyer@example.com") or "buyer@example.com"
    wrapped = _wrap_envelope(body, customer_name=(customer.name if customer else None) or "Customer")
    e = Email(
        received_at=datetime.now(timezone.utc),
        from_address=from_addr,
        subject=f"[{code}] {subject}",
        body=wrapped,
        language_hint=lang,
        customer_id=(customer.id if customer else None),
        attachments=attachments or [],
        status="new",
    )
    db.add(e)
    db.flush()
    return e


def seed(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    # Use real customer codes from the seeded data set. Avoid defense
    # accounts (Raytheon, Bluehawk) since the KSO Outlook rule short-circuits
    # those at Pre-Intake, which would mis-classify every test case.
    cust_aurora = _pick_customer(db, "AURA-AUTO-119") or _pick_customer(db, "TSMC-FAB-308")
    cust_meridian = _pick_customer(db, "MERID-COMM-077") or _pick_customer(db, "TSMC-FAB-308")
    cust_vertex = _pick_customer(db, "VERTEX-Q-053") or _pick_customer(db, "TSMC-FAB-308")
    base_cust = cust_aurora or _pick_customer(db, "TSMC-FAB-308")

    # ==================================================================
    # UC1 — Trade Order Entry
    # ==================================================================
    a1_po = _make_po_pdf_for(
        code="UC1-A1",
        po_number="PO-UCA1-2026-1001",
        customer=cust_aurora,
        line_items=[
            {"sku": "N9020B", "description": "MXA Signal Analyzer", "qty": 2, "unit_price": 36400.00},
            {"sku": "16823A", "description": "Portable Logic Analyzer", "qty": 4, "unit_price": 14200.00},
        ],
        quote_reference="Q-AURA-2026-0501",
        payment_terms="Net 30",
        ship_date="2026-06-15",
    )
    out["UC1-A1"] = _e(db, code="UC1-A1",
        subject="PO-UCA1-2026-1001 — N9020B 4-channel spectrum analyzer",
        body=(
            "Hello Keysight team,\n\n"
            "Please find our purchase order PO-UCA1-2026-1001 attached. Line items:\n"
            " - 2 × N9020B MXA Signal Analyzer, $36,400 each\n"
            " - 4 × 16823A Portable Logic Analyzer, $14,200 each\n"
            "Quote reference: Q-AURA-2026-0501. Payment terms Net 30. Requested ship 2026-06-15.\n"
            "Bill-to and Ship-to: Aurora Automotive Electronics, 4501 Pine, Detroit MI.\n\n"
            "Please acknowledge receipt and send the Sales Order Acknowledgment at your earliest."
        ),
        customer=cust_aurora,
        attachments=[a1_po],
    ).id

    out["UC1-A2"] = _e(db, code="UC1-A2",
        subject="PO request — partial details, full BoM to follow",
        body=(
            "Hi team,\n\n"
            "We want to issue a PO today but I do not have the full BoM handy. "
            "Can you open the case while I track down the line items? I'll forward the PO once "
            "engineering signs off — should be later this week.\n\n"
            "Thanks for your patience."
        ),
        customer=cust_aurora,
    ).id

    a3_po = _make_po_pdf_for(
        code="UC1-A3",
        po_number="PO-UCA3-2026-9904",
        customer=base_cust,
        line_items=[
            {"sku": "EXPORTDUMMY", "description": "ECCN 3A002.f restricted spectrum analyzer", "qty": 1, "unit_price": 92000.00},
        ],
        quote_reference="Q-IRAN-0001",
        payment_terms="Net 30",
        note="End-user country: Iran. Please confirm export approval.",
    )
    out["UC1-A3"] = _e(db, code="UC1-A3",
        subject="PO-UCA3-2026-9904 — export-restricted SKU, please proceed",
        body=(
            "Issuing PO PO-UCA3-2026-9904 for ECCN 3A002.f restricted spectrum analyzer.\n"
            "End-user country: Iran. Quote Q-IRAN-0001 attached.\n\n"
            "Standard payment terms. Please acknowledge."
        ),
        customer=base_cust,
        attachments=[a3_po],
    ).id

    a4_po = _make_po_pdf_for(
        code="UC1-A4",
        po_number="PO-UCA4-2026-7777",
        customer=cust_aurora,
        line_items=[
            {"sku": "N9020B", "description": "MXA Signal Analyzer (PRICE MISMATCH vs quote)", "qty": 2, "unit_price": 30000.00},
        ],
        quote_reference="Q-AURA-2026-0501",
        payment_terms="Net 30",
        ship_date="2026-07-01",
        note="PO unit price differs from accepted quote ($36,400). Please clarify before processing.",
    )
    out["UC1-A4"] = _e(db, code="UC1-A4",
        subject="PO-UCA4-2026-7777 — price mismatch vs quote Q-AURA-2026-0501",
        body=(
            "Issuing PO PO-UCA4-2026-7777 against Q-AURA-2026-0501. Our PO lists 2 × N9020B at $30,000 each, "
            "but the quote was $36,400. Please reconfirm pricing — we can update the PO if needed.\n\n"
            "Requested ship 2026-07-01."
        ),
        customer=cust_aurora,
        attachments=[a4_po],
    ).id

    # ==================================================================
    # UC2 — Trade Sales Change Order
    # ==================================================================
    out["UC2-B1"] = _e(db, code="UC2-B1",
        subject="Change Order — quantity revision on Order SO-AURA-2026-0405",
        body=(
            "Hi Trade desk,\n\n"
            "We need a change-order against SO-AURA-2026-0405. Please revise line 2 (16823A "
            "Portable Logic Analyzer) from quantity 4 to quantity 6. Same unit price, same "
            "requested ship date. Total adjustment +2 × $14,200 = +$28,400.\n\n"
            "Please confirm so we can update our internal ledger."
        ),
        customer=cust_aurora,
    ).id

    out["UC2-B2"] = _e(db, code="UC2-B2",
        subject="Change order on something — details to follow",
        body=(
            "Hi,\n\n"
            "We need to change something on an order. I'll forward the order number and the "
            "specifics once procurement sends them over. Please start the case in the meantime."
        ),
        customer=cust_aurora,
    ).id

    # ==================================================================
    # UC3 — SOM Auto-WO (single + multi)
    # ==================================================================
    out["UC3-C1"] = _e(db, code="UC3-C1",
        subject="Service Order — annual calibration for 1 instrument",
        body=(
            "Hi Service team,\n\n"
            "Please schedule annual calibration for the following asset at our Detroit lab "
            "by 2026-06-30:\n"
            "  Model: N9020B   Serial: MY58020001   Location: Detroit lab (Pasadena room A-2)\n\n"
            "Field service preferred. Our site contact is Jordan Lee, lab manager."
        ),
        customer=cust_aurora,
    ).id

    c2_xlsx = _make_xlsx_for(code="UC3-C2", label="asset_list")
    out["UC3-C2"] = _e(db, code="UC3-C2",
        subject="Service request — multi-asset calibration (3 instruments)",
        body=(
            "Hi Service team,\n\n"
            "Please calibrate the following instruments at our Pasadena anechoic chamber by 2026-07-15:\n"
            "  - Model E5071C  Serial KEY-2202-0011\n"
            "  - Model N5247B  Serial KEY-2202-0034\n"
            "  - Model 8975A   Serial KEY-2202-0099\n"
            "Same site for all three; field service preferred. Spreadsheet attached for your records."
        ),
        customer=cust_meridian,
        attachments=[c2_xlsx],
    ).id

    c3_po = _make_po_pdf_for(
        code="UC3-C3",
        po_number="PO-UCC3-2026-3333",
        customer=cust_vertex,
        line_items=[
            {"sku": "FIELD-CAL-SVC", "description": "Field calibration service — new install (no existing WO)", "qty": 1, "unit_price": 18000.00},
        ],
        note="No existing work order — please use this PO to create one.",
    )
    out["UC3-C3"] = _e(db, code="UC3-C3",
        subject="PO PO-UCC3-2026-3333 for new field calibration — no WO yet",
        body=(
            "We are issuing PO PO-UCC3-2026-3333 for field calibration service on a new install. "
            "We have not opened a work order yet — please use this PO to create the WO and assign field service."
        ),
        customer=cust_vertex,
        attachments=[c3_po],
    ).id

    out["UC3-C4"] = _e(db, code="UC3-C4",
        subject="Service order — system erred earlier, please retry",
        body=(
            "Hi Service,\n\n"
            "My previous submission errored out (we got a system bounce). Same request as before: "
            "calibration for Model 33500B Serial MY-2026-4001 at our QA bench by end of month."
        ),
        customer=base_cust,
    ).id

    c5_xlsx = _make_xlsx_for(code="UC3-C5", label="multi_asset_summary")
    out["UC3-C5"] = _e(db, code="UC3-C5",
        subject="Multi-asset service — one body, AI may not understand",
        body=(
            "Hi Service team,\n\n"
            "Please calibrate the 5 instruments on the attached spreadsheet. They are all on the same "
            "dock and need to be done together. I cannot split them out — please assign to SOM CSR for "
            "manual handling."
        ),
        customer=base_cust,
        attachments=[c5_xlsx],
    ).id

    # ==================================================================
    # UC4 — SOM WO Update
    # ==================================================================
    out["UC4-D1"] = _e(db, code="UC4-D1",
        subject="Update WO WO-2026-0101 — add note about lab access",
        body=(
            "On Work Order WO-2026-0101, please add this note for the field engineer:\n\n"
            "  \"Customer lab access only Mon–Wed 09:00–16:00 PT. Security check-in at gate B.\"\n\n"
            "No PO needed for this update."
        ),
        customer=cust_aurora,
    ).id

    d2_po = _make_po_pdf_for(
        code="UC4-D2",
        po_number="PO-UCD2-2026-2222",
        customer=cust_aurora,
        line_items=[
            {"sku": "EXT-SVC-ACTIVATION", "description": "Extended service contract activation", "qty": 1, "unit_price": 12000.00},
        ],
        quote_reference="Q-AURA-2026-0505",
    )
    out["UC4-D2"] = _e(db, code="UC4-D2",
        subject="WO update with PO PO-UCD2-2026-2222 — please attach",
        body=(
            "On WO-2026-0102, please attach the enclosed PO (PO-UCD2-2026-2222) to the work order. "
            "Line: 1 × extended service contract activation, $12,000, against quote Q-AURA-2026-0505.\n\n"
            "AIOA validation is required since a PO is attached."
        ),
        customer=cust_aurora,
        attachments=[d2_po],
    ).id

    out["UC4-D3"] = _e(db, code="UC4-D3",
        subject="Need to update a WO — number to follow",
        body="Please update the work order — I'll forward the WO number shortly.",
        customer=cust_aurora,
    ).id

    d4_xlsx = _make_xlsx_for(code="UC4-D4", label="wo_updates")
    out["UC4-D4"] = _e(db, code="UC4-D4",
        subject="Multiple WO updates — see attached spreadsheet",
        body=(
            "Hi Service team,\n\n"
            "Multiple WO updates listed in the attached spreadsheet. Please assign to SOM CSR."
        ),
        customer=base_cust,
        attachments=[d4_xlsx],
    ).id

    # ==================================================================
    # UC5 — WO Status / Inquiry
    # ==================================================================
    out["UC5-E1"] = _e(db, code="UC5-E1",
        subject="Status check on WO-2026-0101",
        body=(
            "Hello,\n\nWhat is the current status on WO-2026-0101? Customer asked for an update — "
            "expected completion date and current activity would help. Thanks."
        ),
        customer=cust_aurora,
    ).id

    out["UC5-E2"] = _e(db, code="UC5-E2",
        subject="Status update please",
        body="Hi — can you check the status on one of our work orders? I forget the number, sorry.",
        customer=cust_aurora,
    ).id

    out["UC5-E3"] = _e(db, code="UC5-E3",
        subject="WO-2026-9999 — strange situation, please escalate to CSR",
        body=(
            "Hi,\n\nLast we heard WO-2026-9999 was on credit hold, but our field engineer says it's "
            "already in transit. Something is out of sync — can a CSR look into it and reconcile?"
        ),
        customer=cust_aurora,
    ).id

    # ==================================================================
    # UC6 — Service Contracts
    # ==================================================================
    f1_po = _make_po_pdf_for(
        code="UC6-F1",
        po_number="Q-AURA-CTA-0010",
        customer=cust_aurora,
        line_items=[
            {"sku": "SERVICE-CONTRACT-3YR", "description": "3-year service contract — preventive maintenance + 24h onsite", "qty": 1, "unit_price": 144000.00},
        ],
        note="3-year coverage on lab instruments. Annual value $48,000.",
    )
    out["UC6-F1"] = _e(db, code="UC6-F1",
        subject="Service contract quote — 3-year coverage on lab instruments",
        body=(
            "Hi,\n\nWe would like to add a 3-year service contract on the equipment list below.\n"
            "Annual value $48,000. Coverage: preventive maintenance + 24-hour onsite response.\n"
            "Quote # Q-AURA-CTA-0010 attached."
        ),
        customer=cust_aurora,
        attachments=[f1_po],
    ).id

    out["UC6-F2"] = _e(db, code="UC6-F2",
        subject="Service agreement — quick question",
        body="Hi, we want some kind of support contract — what do you offer? Send us your options.",
        customer=cust_aurora,
    ).id

    out["UC6-F3"] = _e(db, code="UC6-F3",
        subject="Renewal — contract CTA-AURA-9001",
        body=(
            "Hi CTA team,\n\nRenewing CTA-AURA-9001 — same scope, but legal needs to verify the "
            "export-control clause before this can advance. Please have CSR pre-review and route to CTA "
            "specialist."
        ),
        customer=cust_aurora,
    ).id

    f4_po = _make_po_pdf_for(
        code="UC6-F4",
        po_number="PO-UCF4-2026-4444",
        customer=cust_aurora,
        line_items=[
            {"sku": "SERVICE-CONTRACT-RENEW", "description": "Service contract renewal (ECCN review pending)", "qty": 1, "unit_price": 96000.00},
        ],
        note="End-user country: Iran. ECCN review may apply.",
    )
    out["UC6-F4"] = _e(db, code="UC6-F4",
        subject="Service contract PO PO-UCF4-2026-4444 — sanctioned end-user concern",
        body=(
            "Hi,\n\nIssuing PO PO-UCF4-2026-4444 for service contract renewal. End-user country: Iran. "
            "ECCN may apply — please run through AIOA validation."
        ),
        customer=cust_aurora,
        attachments=[f4_po],
    ).id

    # ==================================================================
    # UC7 — SSD Change Request
    # ==================================================================
    out["UC7-G1"] = _e(db, code="UC7-G1",
        subject="SSD change on Order SO-AURA-2026-0405 — push ship +2 weeks",
        body=(
            "Hi POB,\n\nPlease change the SSD on order SO-AURA-2026-0405 from 2026-06-30 to "
            "2026-07-14. Sales Order Owner Aisha Khan can coordinate with the factory. No price "
            "change."
        ),
        customer=cust_aurora,
    ).id

    out["UC7-G2"] = _e(db, code="UC7-G2",
        subject="SSD update needed — SO# to follow",
        body=(
            "Hi,\n\nWe need a date change on an order — I'll send the SO# shortly. Please open the "
            "case and assign to Sales Order Owner."
        ),
        customer=cust_aurora,
    ).id

    db.flush()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-only", action="store_true", help="Show what would be seeded; don't commit")
    args = ap.parse_args()
    with SessionLocal() as db:
        if args.show_only:
            ids = seed(db)
            db.rollback()
            print("Would seed", len(ids), "emails:")
            for code, eid in ids.items():
                print(f"  {code} -> email#{eid}")
            return
        ids = seed(db)
        db.commit()
        print(f"Seeded {len(ids)} use-case path emails with real attachments + enterprise body envelopes:")
        for code, eid in ids.items():
            print(f"  {code} -> email_id={eid}")


if __name__ == "__main__":
    main()
