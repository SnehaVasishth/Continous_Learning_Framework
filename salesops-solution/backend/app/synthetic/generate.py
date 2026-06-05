"""Build a Keysight-authentic demo dataset across all 6 RFP use cases.

Emphasizes:
- Real Keysight product portfolio (PNA-X, MXG, FieldFox, Infiniium UXR, BERT, SMU)
- Authentic CSR voice + industry vocabulary (DUT, ISO 17025, Z540.3, ECCN/ITAR,
  5G NR FR2, S-parameter, OOT, NPI, anechoic chamber, etc.)
- Edge cases that exercise HITL (low-info), L3 one-click (price/qty mismatch),
  and discard (spam/phishing) paths — not just clean L4 auto.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import OUTPUTS, UPLOADS
from ..models import (
    Asset,
    CalibrationCert,
    CCCRequest,
    Customer,
    Email,
    Feedback,
    HitlTask,
    Invoice,
    Order,
    Pipeline,
    Product,
    Quote,
    ServiceContract,
    Shipment,
    TraceEvent,
    WorkOrder,
)
from ..models import Contact
from .attachments import (
    make_bom_xlsx,
    make_calibration_cert_pdf,
    make_invoice_pdf,
    make_po_pdf,
    make_scanned_po_png,
    make_spec_docx,
    make_work_order_pdf,
)
from .catalog import CUSTOMERS, PRODUCTS, VERTICAL_LABELS


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None

random.seed(42)


def _wipe(db: Session) -> None:
    for cls in (
        Feedback,
        HitlTask,
        TraceEvent,
        Pipeline,
        CCCRequest,
        Email,
        Invoice,
        Shipment,
        CalibrationCert,
        ServiceContract,
        Asset,
        WorkOrder,
        Order,
        Quote,
        Contact,
        Product,
        Customer,
    ):
        db.query(cls).delete()
    db.commit()
    for f in UPLOADS.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    for pat in ("INV_*.pdf", "WO_*.pdf", "CERT_*.pdf"):
        for f in OUTPUTS.glob(pat):
            try:
                f.unlink()
            except Exception:
                pass


def seed_all(db: Session, *, wipe: bool) -> dict:
    if wipe:
        _wipe(db)

    customers = []
    contacts_per_code: dict[str, list[dict]] = {}
    for c in CUSTOMERS:
        clean = {k: v for k, v in c.items() if k not in ("contacts",)}
        clean["customer_since"] = _parse_date(clean.get("customer_since"))
        contacts_per_code[c["code"]] = c.get("contacts") or []
        cust = Customer(**clean)
        db.add(cust)
        customers.append(cust)
    products = []
    for p in PRODUCTS:
        clean = {k: v for k, v in p.items()}
        clean["lifecycle_eol_date"] = _parse_date(clean.get("lifecycle_eol_date"))
        prod = Product(**clean)
        db.add(prod)
        products.append(prod)
    db.flush()

    for cust in customers:
        for contact in contacts_per_code.get(cust.code, []):
            db.add(Contact(customer_id=cust.id, **contact))
    db.flush()

    by_code = {c.code: c for c in customers}
    by_sku = {p.sku: p for p in products}
    today = datetime.now(timezone.utc)

    quotes_by_cust: dict[int, list[Quote]] = {}
    for cust in customers:
        for i in range(random.randint(1, 2)):
            items = _pick_lines(products, k=random.randint(2, 3))
            total = sum(li["qty"] * li["unit_price"] for li in items)
            q = Quote(
                quote_number=f"Q-{cust.code}-{1000 + i}",
                customer_id=cust.id,
                valid_until=today + timedelta(days=random.randint(15, 60)),
                total=round(total, 2),
                status="open",
                line_items=items,
            )
            db.add(q)
            quotes_by_cust.setdefault(cust.id, []).append(q)

    targeted_quotes: dict[str, dict] = {}
    targeted_quotes["RTHN-AERO-014"] = _make_targeted_quote(
        customers_by_code=by_code,
        cust_code="RTHN-AERO-014",
        skus=["N5247B-419", "85052D", "CAL-Z540-1Y"],
        products_by_sku=by_sku,
        today=today,
    )
    targeted_quotes["TSMC-FAB-308"] = _make_targeted_quote(
        customers_by_code=by_code,
        cust_code="TSMC-FAB-308",
        skus=["UXR0334A", "M8040A", "WARR-EXT-3Y"],
        products_by_sku=by_sku,
        today=today,
    )
    targeted_quotes["MERID-COMM-077"] = _make_targeted_quote(
        customers_by_code=by_code,
        cust_code="MERID-COMM-077",
        skus=["M9384B-04F", "N9040B-550", "CAL-A2LA-1Y"],
        products_by_sku=by_sku,
        today=today,
    )
    targeted_quotes["AURA-AUTO-119"] = _make_targeted_quote(
        customers_by_code=by_code,
        cust_code="AURA-AUTO-119",
        skus=["MSOS804A", "B2902B", "CAL-A2LA-1Y"],
        products_by_sku=by_sku,
        today=today,
    )
    for tq in targeted_quotes.values():
        db.add(tq["quote"])
    db.flush()

    orders_by_cust: dict[int, list[Order]] = {}
    cust_for_holds = [by_code["BLUEH-DEF-021"], by_code["FINOLA-EU-061"], by_code["NORDS-TELCO-045"]]
    hold_reasons = ["credit_review", "export_compliance_review", "open_invoice"]
    for cust, reason in zip(cust_for_holds, hold_reasons):
        items = _pick_lines(products, k=2)
        o = Order(
            order_number=f"SO-{cust.code}-{2000 + cust.id}",
            customer_id=cust.id,
            status="on_hold",
            hold_reason=reason,
            requested_ship_date=today + timedelta(days=random.randint(5, 14)),
            total=round(sum(li["qty"] * li["unit_price"] for li in items), 2),
            line_items=items,
        )
        db.add(o)
        orders_by_cust.setdefault(cust.id, []).append(o)

    for cust in [by_code["RTHN-AERO-014"], by_code["TSMC-FAB-308"], by_code["AURA-AUTO-119"]]:
        items = _pick_lines(products, k=2)
        o = Order(
            order_number=f"SO-{cust.code}-{2500 + cust.id}",
            customer_id=cust.id,
            status="open",
            requested_ship_date=today + timedelta(days=random.randint(7, 35)),
            total=round(sum(li["qty"] * li["unit_price"] for li in items), 2),
            line_items=items,
        )
        db.add(o)
        orders_by_cust.setdefault(cust.id, []).append(o)
    db.flush()

    wo_specs = [
        ("RTHN-AERO-014", "calibration", "scheduled", "AMS-Field-2"),
        ("TSMC-FAB-308", "calibration", "in_progress", "APAC-Field-1"),
        ("MERID-COMM-077", "repair", "open", "EMEA-Field-3"),
        ("AURA-AUTO-119", "installation", "scheduled", "AMS-Field-1"),
        ("FINOLA-EU-061", "calibration", "in_progress", "EMEA-Field-2"),
        ("SAKURA-SEMI-101", "calibration", "scheduled", "APAC-Field-2"),
    ]
    wo_descriptions = {
        "calibration": (
            "On-site calibration of customer instrument per ANSI/NCSL Z540.3 with full as-found / as-left "
            "documentation, uncertainty budgets, and traceability statement. Verification across documented "
            "measurement points; adjustments performed only when out-of-tolerance."
        ),
        "repair": (
            "Diagnostic and repair of reported fault. Functional verification against published specification, "
            "post-repair calibration where applicable, and FRU replacement using OEM-specified parts."
        ),
        "installation": (
            "Installation, alignment, and acceptance test of new instrument at customer site. Includes rack "
            "integration, firmware update, baseline calibration, and operator handover."
        ),
    }
    wo_standards = {
        "calibration": [
            "ANSI/NCSL Z540.3 — Calibration of Measuring & Test Equipment",
            "ISO/IEC 17025:2017 — Testing & calibration laboratories",
            "Keysight Cal Procedure CP-{family}-001",
        ],
        "repair": [
            "Keysight Service Note KSN-{family}-FRU",
            "ESD-S20.20 ANSI/ESD handling protocol",
            "ISO 9001:2015 — QMS requirements",
        ],
        "installation": [
            "Keysight Installation & Acceptance Test Procedure",
            "ISO 9001:2015 — QMS requirements",
            "Customer Site Acceptance Spec (SAT)",
        ],
    }
    parts_pool = [
        {"part_number": "08720-60001", "description": "RF cable assembly, 3.5 mm (m-m), 36 in", "qty": 1, "unit_cost": 285.00},
        {"part_number": "85052-60007", "description": "3.5 mm calibration kit short/open/load, replacement", "qty": 1, "unit_cost": 1240.00},
        {"part_number": "5061-5311", "description": "Instrument fan assembly, 12 VDC", "qty": 1, "unit_cost": 165.00},
        {"part_number": "08753-60003", "description": "Front-panel encoder assembly", "qty": 1, "unit_cost": 320.00},
        {"part_number": "10833B", "description": "GPIB cable, 2 m", "qty": 1, "unit_cost": 95.00},
        {"part_number": "11878A", "description": "RF adapter kit, type-N to 3.5 mm", "qty": 1, "unit_cost": 540.00},
    ]
    for code, type_, status, team in wo_specs:
        cust = by_code[code]
        wo_num = f"WO-{code}-{3000 + cust.id}"
        asset_serial = f"SN-{random.randint(100000,999999)}-KS"
        asset_sku = random.choice(list(by_sku.keys()))
        scheduled = today + timedelta(days=random.randint(2, 18))
        sla_target = scheduled + timedelta(days=random.randint(3, 10))
        technician = random.choice(_TECHNICIANS)
        labor_hours = round(random.uniform(2.5, 9.5), 1)
        if type_ == "calibration":
            parts = []
        else:
            parts = random.sample(parts_pool, k=random.randint(1, 3))
        parts_cost = sum(p["qty"] * p["unit_cost"] for p in parts)
        labor_cost = labor_hours * 185.0
        cost_usd = round(parts_cost + labor_cost, 2)
        signoff = "signed" if status in ("in_progress",) else "pending"
        root_cause = None
        if type_ == "repair":
            root_cause = random.choice([
                "Worn front-panel encoder caused intermittent setting changes; replaced encoder assembly.",
                "Cooling fan bearing failure triggered thermal shutdowns; replaced fan and verified airflow.",
                "RF cable connector showed return-loss degradation; replaced cable and re-verified S-parameters.",
            ])
        family_hint = (by_sku.get(asset_sku).family if asset_sku in by_sku else "INST") or "INST"
        standards = [s.replace("{family}", family_hint) for s in wo_standards[type_]]
        contract_id = f"SC-{cust.code}-{random.randint(1000, 9999)}"
        description = wo_descriptions[type_]

        pdf_name = f"WO_{wo_num}.pdf"
        try:
            make_work_order_pdf(
                OUTPUTS / pdf_name,
                wo_number=wo_num,
                customer_name=cust.name,
                asset_serial=asset_serial,
                asset_sku=asset_sku,
                type=type_,
                scheduled_date=scheduled,
                sla_target_date=sla_target,
                technician=technician,
                region=cust.region,
                assigned_team=team,
                description=description,
                standards_referenced=standards,
                parts_used=parts,
                labor_hours=labor_hours,
                cost_usd=cost_usd,
                signoff_status=signoff,
                root_cause=root_cause,
                service_contract_id=contract_id,
            )
        except Exception:
            pdf_name = None

        wo = WorkOrder(
            wo_number=wo_num,
            customer_id=cust.id,
            asset_serial=asset_serial,
            asset_sku=asset_sku,
            type=type_,
            description=description,
            status=status,
            region=cust.region,
            assigned_team=team,
            technician=technician,
            service_contract_id=contract_id,
            scheduled_date=scheduled,
            sla_target_date=sla_target,
            standards_referenced=standards,
            labor_hours=labor_hours,
            parts_used=parts,
            signoff_status=signoff,
            root_cause=root_cause,
            cost_usd=cost_usd,
            pdf_filename=pdf_name,
        )
        db.add(wo)
    db.flush()

    # Scale orders, work orders and CCC requests across the procedurally
    # expanded customer pool so demo volume aligns with the RFP commitment
    # (650 FTE / 880k emails / 10-status Existing-CCC matrix). Hand-crafted
    # scenarios above stay intact; this only ADDS volume.
    bulk_volume = _seed_bulk_volume(
        db,
        customers=customers,
        products=products,
        by_sku=by_sku,
        orders_by_cust=orders_by_cust,
        quotes_by_cust=quotes_by_cust,
        today=today,
    )
    db.flush()

    emails_added = _seed_emails(
        db,
        by_code=by_code,
        by_sku=by_sku,
        targeted_quotes=targeted_quotes,
        orders_by_cust=orders_by_cust,
    )

    assets_by_cust = _seed_assets(db, customers=customers, by_sku=by_sku, today=today)
    db.flush()

    contracts_added = _seed_service_contracts(
        db, customers=customers, assets_by_cust=assets_by_cust, today=today
    )
    db.flush()

    certs_added = _seed_calibration_certs(
        db, assets_by_cust=assets_by_cust, by_code=by_code, today=today
    )
    shipments_added = _seed_shipments(db, orders_by_cust=orders_by_cust, today=today)
    invoices_added = _seed_invoices(
        db, orders_by_cust=orders_by_cust, by_code=by_code, today=today
    )

    db.commit()
    return {
        "customers": len(customers),
        "products": len(products),
        "quotes": db.query(Quote).count(),
        "orders": db.query(Order).count(),
        "work_orders": db.query(WorkOrder).count(),
        "ccc_requests": db.query(CCCRequest).count(),
        "emails": emails_added,
        "assets": sum(len(v) for v in assets_by_cust.values()),
        "service_contracts": contracts_added,
        "cal_certs": certs_added,
        "shipments": shipments_added,
        "invoices": invoices_added,
        "bulk_volume": bulk_volume,
    }


def _seed_bulk_volume(
    db: Session,
    *,
    customers: list,
    products: list,
    by_sku: dict,
    orders_by_cust: dict,
    quotes_by_cust: dict,
    today: datetime,
) -> dict:
    """Scale orders / work orders / CCC requests across the procedurally
    expanded customer pool so the demo can stand behind the RFP volume
    commitments. Targeted scenarios above stay anchored on hand-crafted
    customers; this function only seeds GEN-* customers."""

    extra_custs = [c for c in customers if c.code.startswith("GEN-")]
    if not extra_custs:
        return {"orders": 0, "work_orders": 0, "ccc_requests": 0, "service_contracts": 0}

    # ---- Orders across diverse statuses (the Existing-CCC matrix) --------
    order_status_pool = [
        ("open", 0.22),
        ("on_hold", 0.10),
        ("in_fulfillment", 0.18),
        ("shipped", 0.18),
        ("invoiced", 0.14),
        ("delivered", 0.10),
        ("cancelled", 0.04),
        ("returned", 0.02),
        ("backordered", 0.02),
    ]
    hold_reason_pool = [
        "credit_review", "export_compliance_review", "open_invoice",
        "pricing_discrepancy", "spec_clarification_required", "quote_expired",
    ]
    incoterm_pool = ["DDP", "FCA", "EXW", "FOB Destination", "FOB Origin", "DAP"]
    statuses_weighted = []
    for status, weight in order_status_pool:
        statuses_weighted.extend([status] * int(weight * 100))

    bulk_orders = 0
    sample_for_orders = random.sample(extra_custs, k=min(len(extra_custs), 110))
    for cust in sample_for_orders:
        for i in range(random.randint(1, 3)):
            items = _pick_lines(products, k=random.randint(2, 4))
            status = random.choice(statuses_weighted)
            hold_reason = random.choice(hold_reason_pool) if status == "on_hold" else None
            requested_ship = today + timedelta(days=random.randint(-30, 60))
            order_num = f"SO-{cust.code}-{4000 + cust.id * 7 + i}"
            o = Order(
                order_number=order_num,
                customer_id=cust.id,
                status=status,
                hold_reason=hold_reason,
                requested_ship_date=requested_ship,
                total=round(sum(li["qty"] * li["unit_price"] for li in items), 2),
                line_items=items,
            )
            db.add(o)
            orders_by_cust.setdefault(cust.id, []).append(o)
            bulk_orders += 1

    # ---- Work orders across types and states ----------------------------
    wo_type_pool = ["calibration", "repair", "installation", "decommission"]
    wo_status_pool = ["open", "scheduled", "in_progress", "completed", "cancelled"]
    field_team_pool = {
        "AMS": ["AMS-Field-1", "AMS-Field-2", "AMS-Field-3"],
        "EMEA": ["EMEA-Field-1", "EMEA-Field-2", "EMEA-Field-3"],
        "APAC": ["APAC-Field-1", "APAC-Field-2"],
        "JP": ["JP-Field-1", "JP-Field-2"],
    }

    bulk_wos = 0
    sample_for_wos = random.sample(extra_custs, k=min(len(extra_custs), 70))
    for cust in sample_for_wos:
        for i in range(random.randint(1, 2)):
            asset_sku = random.choice(list(by_sku.keys()))
            wo_type = random.choice(wo_type_pool)
            wo_status = random.choice(wo_status_pool)
            scheduled = today + timedelta(days=random.randint(-20, 45))
            team_pool = field_team_pool.get(cust.region, field_team_pool["AMS"])
            wo = WorkOrder(
                wo_number=f"WO-{cust.code}-{5000 + cust.id * 11 + i}",
                customer_id=cust.id,
                asset_serial=f"SN-{random.randint(100000, 999999)}-KS",
                asset_sku=asset_sku,
                type=wo_type,
                status=wo_status,
                region=cust.region,
                assigned_team=random.choice(team_pool),
                scheduled_date=scheduled,
                sla_target_date=scheduled + timedelta(days=random.randint(3, 14)),
                labor_hours=round(random.uniform(1.5, 12.0), 1),
                cost_usd=round(random.uniform(450.0, 8500.0), 2),
                signoff_status="signed" if wo_status == "completed" else "pending",
            )
            db.add(wo)
            bulk_wos += 1

    # ---- CCC requests across all 10 STATUS x STAGE combinations --------
    # RFP flow has STATUS in {new, assigned, in_progress, closed} and STAGE in
    # {automation_in_progress, review_required, automation_complete}.
    ccc_combos = [
        ("new", "automation_in_progress"),
        ("new", "review_required"),
        ("assigned", "automation_in_progress"),
        ("assigned", "review_required"),
        ("in_progress", "automation_in_progress"),
        ("in_progress", "review_required"),
        ("in_progress", "automation_complete"),
        ("closed", "automation_complete"),
        ("closed", "review_required"),
        ("closed", "automation_in_progress"),  # post-close re-review
    ]
    ccc_request_types = [
        "po_intake", "quote_to_order", "wo_update_request", "wo_status_inquiry",
        "service_contract_request", "hold_release", "delivery_change",
        "trade_change_order", "ssd_change_request", "general_inquiry",
    ]
    ccc_sub_types = [
        "standard", "expedited", "compliance_review", "credit_review",
        "spec_clarification", "missing_data", "multi_asset_fan_out",
    ]
    ccc_tracks = ["SALES_PO", "ISC_WO_RTK", "KSO", "SERVICE_CONTRACTS", "OTHERS"]
    fallout_reasons = [
        "low_classification_confidence", "missing_required_field",
        "salesforce_customer_not_found", "salesforce_quote_mismatch",
        "magic_sku_engineering_quote", "magic_sku_sow_team",
        "magic_sku_export_control", "duplicate_request_suspected",
    ]

    bulk_ccc = 0
    sample_for_ccc = random.sample(extra_custs, k=min(len(extra_custs), 90))
    for idx, cust in enumerate(sample_for_ccc):
        # Cycle through combos so every status x stage gets seeded
        status, stage = ccc_combos[idx % len(ccc_combos)]
        created = today - timedelta(days=random.randint(0, 60))
        closed = created + timedelta(days=random.randint(1, 14)) if status == "closed" else None
        req = CCCRequest(
            request_number=f"CCC-{cust.code}-{6000 + cust.id * 13}",
            customer_id=cust.id,
            category=random.choice(["Sales", "Service", "Trade", "Returns"]),
            request_type=random.choice(ccc_request_types),
            sub_type=random.choice(ccc_sub_types),
            track=random.choice(ccc_tracks),
            status=status,
            stage=stage,
            owner=f"csr.{random.choice(['mgomez', 'jpark', 'rkumar', 'klee', 'aforbes', 'sbose'])}",
            fallout_reason=random.choice(fallout_reasons) if stage == "review_required" else None,
            created_at=created,
            updated_at=created + timedelta(hours=random.randint(1, 72)),
            closed_at=closed,
            notes=None,
        )
        db.add(req)
        bulk_ccc += 1

    # ---- Service contracts across the new customer base -----------------
    sc_type_pool = ["Calibration_Annual", "Maintenance_Bronze", "Maintenance_Silver", "Maintenance_Gold"]
    bulk_sc = 0
    sample_for_sc = random.sample(extra_custs, k=min(len(extra_custs), 40))
    for cust in sample_for_sc:
        sc_type = random.choice(sc_type_pool)
        start = today - timedelta(days=random.randint(30, 730))
        term_months = random.choice([12, 24, 36])
        expires = start + timedelta(days=term_months * 30)
        status = "active" if expires > today else "expired"
        sc = ServiceContract(
            contract_number=f"SC-{cust.code}-{7000 + cust.id * 17}",
            customer_id=cust.id,
            type=sc_type,
            starts_on=start,
            expires_on=expires,
            sla_response_hours=random.choice([4, 8, 24, 48]),
            sla_resolution_hours=random.choice([24, 48, 72, 168]),
            annual_value_usd=round(random.uniform(8500.0, 145000.0), 2),
            status=status,
            notes=None,
        )
        db.add(sc)
        bulk_sc += 1

    return {
        "orders": bulk_orders,
        "work_orders": bulk_wos,
        "ccc_requests": bulk_ccc,
        "service_contracts": bulk_sc,
    }


def _pick_lines(products: list[Product], k: int) -> list[dict]:
    chosen = random.sample(products, k=min(k, len(products)))
    out = []
    for p in chosen:
        qty = random.choice([1, 1, 1, 2])
        out.append({"sku": p.sku, "description": p.description, "qty": qty, "unit_price": p.list_price})
    return out


def _make_targeted_quote(
    *,
    customers_by_code: dict,
    cust_code: str,
    skus: list[str],
    products_by_sku: dict,
    today: datetime,
) -> dict:
    cust = customers_by_code[cust_code]
    items = []
    for sku in skus:
        p = products_by_sku[sku]
        items.append({"sku": sku, "description": p.description, "qty": 1, "unit_price": p.list_price})
    total = sum(li["qty"] * li["unit_price"] for li in items)
    q = Quote(
        quote_number=f"QT-{cust_code}-DEMO",
        customer_id=cust.id,
        valid_until=today + timedelta(days=45),
        total=round(total, 2),
        status="open",
        line_items=items,
    )
    return {"quote": q, "items": items, "customer": cust, "total": round(total, 2)}


def _seed_emails(
    db: Session,
    *,
    by_code: dict[str, Customer],
    by_sku: dict[str, Product],
    targeted_quotes: dict[str, dict],
    orders_by_cust: dict[int, list[Order]],
) -> int:
    samples: list[dict] = []

    samples.append(_clean_po(by_code["BLUEH-DEF-021"], by_sku, sku="N9020B-526", with_cal=True, signer="Aaron Brewer, Calibration Lab Supervisor"))
    samples.append(_clean_po(by_code["FINOLA-EU-061"], by_sku, sku="DSOX3024T", signer="Linda Voss, Procurement"))
    samples.append(_clean_po_es(by_code["NORDS-TELCO-045"], by_sku, sku="N9912A-345"))
    samples.append(_clean_po_ja(by_code["OZEKI-T&M-088"], by_sku, sku="33622A"))
    samples.append(_clean_po(by_code["VERTEX-Q-053"], by_sku, sku="B2902B", signer="Dr. Priya Iyer, Lab PI"))

    samples.append(_image_scan_po_ja(by_code["SAKURA-SEMI-101"], by_sku, sku="N9040B-550"))

    samples.append(
        _q2o_with_mismatch(
            by_code["RTHN-AERO-014"],
            targeted=targeted_quotes["RTHN-AERO-014"],
            mismatch_kind="price",
        )
    )
    samples.append(
        _q2o_with_mismatch(
            by_code["TSMC-FAB-308"],
            targeted=targeted_quotes["TSMC-FAB-308"],
            mismatch_kind="qty",
        )
    )
    samples.append(
        _q2o_with_mismatch(
            by_code["MERID-COMM-077"],
            targeted=targeted_quotes["MERID-COMM-077"],
            mismatch_kind="extra_sku",
        )
    )
    samples.append(_q2o_clean(by_code["AURA-AUTO-119"], targeted=targeted_quotes["AURA-AUTO-119"]))

    for code in ("BLUEH-DEF-021", "FINOLA-EU-061", "NORDS-TELCO-045"):
        cust = by_code[code]
        held = [o for o in orders_by_cust.get(cust.id, []) if o.status == "on_hold"]
        if held:
            samples.append(_hold_release(cust, held[0]))

    samples.append(_export_compliance_hold(by_code["RTHN-AERO-014"]))

    for code in ("RTHN-AERO-014", "TSMC-FAB-308", "AURA-AUTO-119"):
        cust = by_code[code]
        opens = [o for o in orders_by_cust.get(cust.id, []) if o.status == "open"]
        if opens:
            samples.append(_delivery_reschedule(cust, opens[0]))

    samples.append(_pull_in_request(by_code["TSMC-FAB-308"]))

    samples.append(_cal_request_iso17025(by_code["FINOLA-EU-061"]))
    samples.append(_cal_request_z540(by_code["RTHN-AERO-014"]))
    samples.append(_cal_request_es(by_code["MERID-COMM-077"]))
    samples.append(_repair_request_ja(by_code["SAKURA-SEMI-101"]))

    samples.append(_wo_status(by_code["TSMC-FAB-308"], urgency="high"))
    samples.append(_wo_status(by_code["AURA-AUTO-119"], urgency="normal"))
    samples.append(_wo_status_ja(by_code["OZEKI-T&M-088"]))

    samples.append(_eol_inquiry(by_code["VERTEX-Q-053"]))
    samples.append(_cross_sell_inquiry(by_code["BLUEH-DEF-021"]))

    samples.append(_phish_email())
    samples.append(_promo_spam())

    samples.append(_ambiguous_short(by_code["FINOLA-EU-061"]))

    samples.append(_forwarded_thread(by_code["AURA-AUTO-119"]))

    for code in ("RTHN-AERO-014", "AURA-AUTO-119"):
        cust = by_code[code]
        opens = [o for o in orders_by_cust.get(cust.id, []) if o.status == "open"]
        if opens:
            samples.append(_trade_change_order(cust, opens[0]))

    samples.append(_ssd_change_request(by_code["TSMC-FAB-308"], orders_by_cust))
    samples.append(_ssd_change_request_partial(by_code["AURA-AUTO-119"], orders_by_cust))

    samples.append(_wo_update_request(by_code["MERID-COMM-077"]))
    samples.append(_wo_update_add_assets(by_code["FINOLA-EU-061"]))

    samples.append(_service_contract_quote(by_code["BLUEH-DEF-021"]))
    samples.append(_service_contract_renewal(by_code["RTHN-AERO-014"]))
    samples.append(_service_contract_es(by_code["NORDS-TELCO-045"]))

    samples.append(_multi_asset_cal_request(by_code["TSMC-FAB-308"]))

    samples.append(_misrouted_email(by_code["VERTEX-Q-053"]))

    base_time = datetime.now(timezone.utc) - timedelta(hours=len(samples))
    for idx, s in enumerate(samples):
        cust = by_code.get(s.get("customer_code")) if s.get("customer_code") else None
        if cust is None and s.get("customer_id"):
            cust = next((c for c in by_code.values() if c.id == s["customer_id"]), None)
        enriched_body = _enrich_email_body(s, customer=cust)
        e = Email(
            received_at=base_time + timedelta(minutes=18 * idx),
            from_address=s["from"],
            subject=s["subject"],
            body=enriched_body,
            language_hint=s["language_hint"],
            customer_id=s.get("customer_id"),
            attachments=s.get("attachments") or [],
            status="new",
        )
        db.add(e)
    db.flush()
    return len(samples)


def _enrich_email_body(spec: dict, *, customer: Customer | None) -> str:
    """Wrap a generator-produced email body in a realistic enterprise envelope.

    Real customer mail carries headers and footers around the substantive ask:
      - Sometimes a CAUTION external-email banner at the top
      - A signature block with name, title, company, phone, and disclaimer
      - A footer for confidentiality / export notice

    The generator functions above produce the substantive core (greeting +
    request paragraphs + brief sign-off). This wrapper appends the surrounding
    chrome so emails look like what a sender's MUA actually emits, not
    stripped-down test fixtures.

    Skipped entirely for spam / promo emails (already shaped that way on purpose)
    and for emails that already include a CAUTION banner (some hand-written
    long threads do this themselves).
    """
    body = spec.get("body") or ""
    lang = spec.get("language_hint") or "en"
    subject_l = (spec.get("subject") or "").lower()
    # Don't enrich spam / phishing fixtures — they're meant to look unstructured.
    if "phish" in subject_l or "win a" in subject_l or "free trial" in subject_l:
        return body
    if "CAUTION:" in body or "EXTERNAL" in body[:200]:
        return body

    pieces: list[str] = []

    # External-mail banner (50% of cases, matches Keysight's Outlook posture)
    if hash(spec.get("subject", "") + lang) % 2 == 0:
        if lang == "es":
            pieces.append("[ADVERTENCIA EXTERNA: Este correo proviene de fuera de la organización. No haga clic en enlaces ni abra adjuntos a menos que reconozca al remitente.]\n")
        elif lang == "ja":
            pieces.append("[警告: 外部からのメールです。送信者を確認の上、添付ファイルやリンクをご利用ください。]\n")
        else:
            pieces.append("[EXTERNAL EMAIL] CAUTION: This message originated outside your organisation. Do not click links or open attachments unless you recognise the sender.\n")

    pieces.append(body.strip())

    # Signature block enrichment if not already substantial
    if body.count("\n") < 6 and customer is not None:
        if lang == "es":
            footer = (
                f"\n\n--\n{customer.name}\n"
                f"Equipo de Operaciones Comerciales · {customer.account_manager or 'Carmen Ruiz'}\n"
                f"www.{(customer.email or '').split('@')[-1] or 'customer.example'}\n"
                "Aviso de confidencialidad: el contenido de este correo y sus adjuntos es confidencial y está dirigido exclusivamente al destinatario."
            )
        elif lang == "ja":
            footer = (
                f"\n\n--\n{customer.name}\n"
                f"購買部 / Procurement\n"
                f"www.{(customer.email or '').split('@')[-1] or 'customer.example'}\n"
                "本メールおよび添付ファイルは機密情報を含む場合があります。誤って受信された場合はご連絡の上、削除してください。"
            )
        else:
            footer = (
                f"\n\n--\n{customer.name}\n"
                f"Account: {customer.code}  ·  SLA tier: {customer.sla_tier or 'Gold'}\n"
                f"Reply chain reference: {(spec.get('thread_root_message_id') or 'inline')}\n"
                "This email and any attachments are intended solely for the addressed recipient and may contain confidential, "
                "proprietary, or privileged information. If you received this message in error, please notify the sender immediately and delete all copies."
            )
        pieces.append(footer)

    return "\n".join(pieces)


def _po_pdf(
    *,
    cust: Customer,
    po_num: str,
    items: list[dict],
    note: str = "",
    quote_reference: str | None = None,
    buyer_contact: str | None = None,
) -> dict:
    pdf_name = f"PO_{po_num}.pdf"
    pdf_path = UPLOADS / pdf_name
    vertical_label = VERTICAL_LABELS.get(cust.vertical or "", "Test & Measurement")
    region_label = {"AMS": "Americas", "EMEA": "EMEA", "APAC": "Asia-Pacific"}.get(cust.region, cust.region)
    addr = f"{vertical_label} · {region_label} Operations<br/>Procurement & Lab Operations"
    make_po_pdf(
        pdf_path,
        customer_name=cust.name,
        customer_addr=addr,
        po_number=po_num,
        issue_date=datetime.now().date(),
        line_items=items,
        payment_terms=random.choice(["Net 30", "Net 45", "Net 60"]),
        requested_ship=(datetime.now().date() + timedelta(days=random.randint(14, 35))).isoformat(),
        ship_to=f"{cust.name}<br/>Receiving Dock — {region_label}<br/>Attn: Lab Operations",
        bill_to=f"{cust.name}<br/>Accounts Payable — {region_label}<br/>{cust.email}",
        note=note,
        quote_reference=quote_reference,
        buyer_contact=buyer_contact,
    )
    return {"name": pdf_name, "type": "pdf", "path": str(pdf_path)}


def _clean_po(cust: Customer, by_sku: dict, *, sku: str, with_cal: bool = False, signer: str = "Procurement") -> dict:
    p = by_sku[sku]
    items = [{"sku": sku, "description": p.description, "qty": 1, "unit_price": p.list_price}]
    if with_cal:
        cal = by_sku["CAL-A2LA-1Y"]
        items.append({"sku": cal.sku, "description": cal.description, "qty": 1, "unit_price": cal.list_price})
    po_num = f"PO-{cust.code}-{random.randint(50000, 59999)}"
    pdf = _po_pdf(cust=cust, po_num=po_num, items=items, note="Please confirm SOA and ship date.")
    body = (
        f"Hi Keysight Sales Ops team,\n\n"
        f"Please find attached our purchase order {po_num} for the {p.description.split(',')[0]}.\n"
        f"This is being deployed in our {_lab_context(cust)} for {_use_case_for(cust)}. "
        f"Kindly issue the Sales Order Acknowledgment (SOA) and confirm the requested ship date.\n\n"
        f"Note: please coordinate any export documentation through our Trade Compliance team — copy on this thread.\n\n"
        f"Regards,\n{signer}\n{cust.name}\n{cust.email}"
    )
    return {
        "from": cust.email,
        "subject": f"PO {po_num} — {p.description.split(',')[0]} — please acknowledge",
        "body": body,
        "language_hint": cust.language,
        "customer_id": cust.id,
        "attachments": [pdf],
    }


def _clean_po_es(cust: Customer, by_sku: dict, *, sku: str) -> dict:
    p = by_sku[sku]
    items = [{"sku": sku, "description": p.description, "qty": 1, "unit_price": p.list_price}]
    po_num = f"PO-{cust.code}-{random.randint(50000, 59999)}"
    pdf = _po_pdf(cust=cust, po_num=po_num, items=items, note="Confirmar acuse de recibo y fecha de envío.")
    body = (
        f"Hola equipo de Keysight,\n\n"
        f"Adjunto la orden de compra {po_num} para el {p.description.split(',')[0]} "
        f"que será desplegado en nuestro laboratorio de pre-cumplimiento 5G NR FR1/FR2. "
        f"Por favor confirmen la recepción, emitan el SOA y la fecha de envío solicitada.\n\n"
        f"Saludos,\nCarlos Iglesias, Lab Operations Lead\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"OC {po_num} — {p.description.split(',')[0]} — favor de procesar",
        "body": body,
        "language_hint": "es",
        "customer_id": cust.id,
        "attachments": [pdf],
    }


def _clean_po_ja(cust: Customer, by_sku: dict, *, sku: str) -> dict:
    p = by_sku[sku]
    items = [{"sku": sku, "description": p.description, "qty": 1, "unit_price": p.list_price}]
    po_num = f"PO-{cust.code}-{random.randint(50000, 59999)}"
    pdf = _po_pdf(cust=cust, po_num=po_num, items=items, note="受領確認と出荷予定日のご連絡をお願いします。")
    body = (
        f"Keysight 営業ご担当者様\n\n"
        f"自動車向け Ethernet (100BASE-T1) 評価ベンチ用に、{p.description.split(',')[0]} の発注書 {po_num} を添付いたします。"
        f"受領確認と SOA 発行、希望出荷日の確定をお願いいたします。\n\n"
        f"輸出管理 (ECCN) に関する書類が必要な場合は、別途ご連絡ください。\n\n"
        f"よろしくお願いいたします。\n渡辺 健司 / 購買部\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"発注書 {po_num} のご連絡 — SOA 発行依頼",
        "body": body,
        "language_hint": "ja",
        "customer_id": cust.id,
        "attachments": [pdf],
    }


def _image_scan_po_ja(cust: Customer, by_sku: dict, *, sku: str) -> dict:
    p = by_sku[sku]
    items = [{"sku": sku, "description": p.description, "qty": 1, "unit_price": p.list_price}]
    po_num = f"PO-{cust.code}-{random.randint(60000, 69999)}"
    img_name = f"PO_{po_num}_scan.png"
    img_path = UPLOADS / img_name
    region_label = {"AMS": "Americas", "EMEA": "EMEA", "APAC": "Asia-Pacific"}.get(cust.region, cust.region)
    make_scanned_po_png(
        img_path,
        customer_name=cust.name,
        customer_addr=f"{VERTICAL_LABELS.get(cust.vertical or '', 'T&M')} · {region_label} Operations",
        po_number=po_num,
        issue_date=datetime.now().date().isoformat(),
        line_items=items,
        payment_terms="Net 45",
        requested_ship=(datetime.now().date() + timedelta(days=21)).isoformat(),
    )
    body = (
        f"Keysight 御中\n\n"
        f"半導体テスト向け 5G NR FR2 評価ラインで使用予定の {p.description.split(',')[0]} の発注書 ({po_num}) を、"
        f"承認スタンプ付きスキャン画像で送付いたします。OCR にて内容をご確認いただき、SOA を発行してください。\n\n"
        f"なお、ISO/IEC 17025 に準拠した校正サービスも別途お見積もり依頼予定です。\n\n"
        f"佐藤 美咲 / 計測機器調達\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"スキャン PO {po_num} の送付（OCR ご対応願います）",
        "body": body,
        "language_hint": "ja",
        "customer_id": cust.id,
        "attachments": [{"name": img_name, "type": "image", "path": str(img_path)}],
    }


def _q2o_clean(cust: Customer, *, targeted: dict) -> dict:
    quote = targeted["quote"]
    items = list(targeted["items"])
    po_num = f"PO-{cust.code}-Q2O-{random.randint(70000, 79999)}"
    bom_name = f"BOM_{po_num}.xlsx"
    bom_path = UPLOADS / bom_name
    make_bom_xlsx(bom_path, customer_name=cust.name, quote_number=quote.quote_number, line_items=items)

    pdf = _po_pdf(
        cust=cust,
        po_num=po_num,
        items=items,
        note=f"Issued against quote {quote.quote_number}. Acceptance test plan attached.",
        quote_reference=quote.quote_number,
        buyer_contact="Buyer: Danielle Park, Engineering Procurement",
    )

    spec = make_spec_docx(
        UPLOADS / f"SPEC_{po_num}.docx",
        title=f"Acceptance test plan — {cust.name}",
        sections=[
            ("Scope", f"Acceptance testing for {len(items)} units against quote {quote.quote_number}."),
            ("DUT", "/".join([li["sku"] for li in items])),
            ("Compliance", "Cal certs delivered with as-found data per ANSI/NCSL Z540."),
            ("Standards referenced", "ISO/IEC 17025, IEC 61000, MIL-STD-810."),
        ],
    )

    body = (
        f"Hello team,\n\n"
        f"Please convert quote {quote.quote_number} into an order using the attached PO {po_num}, "
        f"BOM workbook, and acceptance test plan. The instruments will support our "
        f"{_use_case_for(cust)} program with delivery into our {_lab_context(cust)}.\n\n"
        f"Send SOA, projected ship date, and confirm cal certs will be A2LA-traceable as quoted.\n\n"
        f"Thanks,\nDanielle Park, Engineering Procurement\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"Convert quote {quote.quote_number} → order — PO + BOM + ATP attached",
        "body": body,
        "language_hint": cust.language,
        "customer_id": cust.id,
        "attachments": [
            pdf,
            {"name": bom_name, "type": "xlsx", "path": str(bom_path)},
            {"name": spec.name, "type": "docx", "path": str(spec)},
        ],
    }


def _q2o_with_mismatch(cust: Customer, *, targeted: dict, mismatch_kind: str) -> dict:
    quote = targeted["quote"]
    quoted_items = list(targeted["items"])
    items = [dict(li) for li in quoted_items]

    if mismatch_kind == "price":
        items[0]["unit_price"] = round(items[0]["unit_price"] * 0.92, 2)
        intro_note = "Requesting the discounted unit price agreed verbally with our account executive on the first line item. Please confirm or escalate for sales-ops approval."
    elif mismatch_kind == "qty":
        items[0]["qty"] = quoted_items[0]["qty"] + 1
        intro_note = "Increased the quantity on the first line to cover a second test bench. If acceptable at the same unit price, please proceed; otherwise advise on a revised quote."
    elif mismatch_kind == "extra_sku":
        items.append({"sku": "85052D", "description": "3.5 mm Economy Calibration Kit, DC to 26.5 GHz", "qty": 1, "unit_price": 4750.0})
        intro_note = "Added a cal kit (85052D) that was not on the original quote. Please include in the order if pricing is in line; otherwise let us know and we will issue a revised PO."
    else:
        intro_note = ""

    po_num = f"PO-{cust.code}-Q2O-{random.randint(70000, 79999)}"
    pdf = _po_pdf(
        cust=cust,
        po_num=po_num,
        items=items,
        note=intro_note,
        quote_reference=quote.quote_number,
        buyer_contact="Procurement contact: see email signature for buyer details.",
    )

    bom_name = f"BOM_{po_num}.xlsx"
    bom_path = UPLOADS / bom_name
    make_bom_xlsx(bom_path, customer_name=cust.name, quote_number=quote.quote_number, line_items=items)

    bodies = {
        "en": (
            f"Hi Keysight Sales,\n\n"
            f"Please find PO {po_num} converting quote {quote.quote_number}. "
            f"{intro_note}\n\n"
            f"Issue the SOA and let me know if the variance needs sales-ops approval.\n\n"
            f"Thanks,\nMatt Holloway, Senior Buyer\n{cust.name}"
        ),
        "es": (
            f"Hola,\n\nAdjunto OC {po_num} para convertir la cotización {quote.quote_number}. "
            f"{intro_note}\n\nEmitan el SOA o avísenme si la variación requiere aprobación de Sales Ops.\n\n"
            f"Saludos,\nMariela Solís, Compras Técnicas\n{cust.name}"
        ),
        "ja": (
            f"Keysight 営業ご担当者様\n\n見積 {quote.quote_number} を発注に切り替えるため、PO {po_num} を添付いたします。\n"
            f"{intro_note}\n\nSOA の発行と差異の承認要否をご連絡ください。\n\n"
            f"よろしくお願いいたします。\n中村 一郎 / 購買\n{cust.name}"
        ),
    }
    return {
        "from": cust.email,
        "subject": f"Q2O {quote.quote_number} — PO {po_num} attached (variance noted)",
        "body": bodies.get(cust.language, bodies["en"]),
        "language_hint": cust.language,
        "customer_id": cust.id,
        "attachments": [pdf, {"name": bom_name, "type": "xlsx", "path": str(bom_path)}],
    }


def _hold_release(cust: Customer, order: Order) -> dict:
    reason = order.hold_reason or "credit_review"
    pretty = {
        "credit_review": ("credit hold", "Our AP team has cleared the outstanding invoice."),
        "open_invoice": ("payment hold", "The open invoice has been wired this morning — confirmation #WT-7732."),
        "export_compliance_review": ("export-control hold", "Trade compliance has approved the EAR99 classification."),
    }.get(reason, ("hold", "The hold reason has been resolved on our side."))
    body_en = (
        f"Hi Keysight team,\n\n"
        f"Order {order.order_number} is currently flagged as {pretty[0]}. {pretty[1]} "
        f"Please release the order so it can ship — our calibration backlog is dependent on this delivery.\n\n"
        f"Thanks,\nElaine Park, AP & Procurement\n{cust.name}"
    )
    body_es = (
        f"Hola,\n\n"
        f"El pedido {order.order_number} está actualmente en {pretty[0]}. {pretty[1]} "
        f"Por favor libérenlo para que pueda enviarse — nuestro plan de calibración depende de esta entrega.\n\n"
        f"Saludos,\nLucía Méndez, AP\n{cust.name}"
    )
    body_ja = (
        f"Keysight ご担当者様\n\n"
        f"注文 {order.order_number} は現在 {pretty[0]} 状態となっております。{pretty[1]} "
        f"出荷可能な状態への変更をお願いいたします。校正バックログの解消に必要な機材です。\n\n"
        f"佐藤 経理 / 調達\n{cust.name}"
    )
    body = {"en": body_en, "es": body_es, "ja": body_ja}.get(cust.language, body_en)
    return {
        "from": cust.email,
        "subject": f"Release {order.order_number} — {reason.replace('_', ' ')} cleared",
        "body": body,
        "language_hint": cust.language,
        "customer_id": cust.id,
        "attachments": [],
    }


def _export_compliance_hold(cust: Customer) -> dict:
    body = (
        f"Hi Keysight Trade & Sales Ops,\n\n"
        f"We received notice that an order recently placed under PO RTNH-2026-COMPLY-0042 is on an export-control hold. "
        f"Trade compliance on our end has now confirmed the end-use is non-ITAR (cleared as EAR99 with ECCN 3A002.f). "
        f"BIS license isn't required for this destination. Please clear the hold and proceed with shipment.\n\n"
        f"Reference: RTNH-Compliance-#3315 (attached letter to follow if requested).\n\n"
        f"Best,\nMike Ferraro, Trade Compliance\n{cust.name}"
    )
    return {
        "from": "trade.compliance@raytheon-elseg.com",
        "subject": "Cleared for export — please release PO RTNH-2026-COMPLY-0042",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _delivery_reschedule(cust: Customer, order: Order) -> dict:
    new_iso = (datetime.now().date() + timedelta(days=21)).isoformat()
    body_en = (
        f"Hello,\n\n"
        f"Could you push the requested ship date for {order.order_number} out to {new_iso}? "
        f"Our anechoic chamber installation has slipped and we won't be ready to receive the instruments before then.\n\n"
        f"Please confirm impact on the cal-cycle SLA if any.\n\n"
        f"Regards,\nIsaac Tran, Test Lab Manager\n{cust.name}"
    )
    body_es = (
        f"Hola,\n\n"
        f"¿Pueden mover la fecha de envío de {order.order_number} a {new_iso}? "
        f"Tenemos un retraso en la instalación de la cámara anecoica y no podremos recibir los equipos antes.\n\n"
        f"Confirmen impacto en la garantía de calibración si lo hubiera.\n\n"
        f"Saludos,\n{cust.name}"
    )
    body_ja = (
        f"ご担当者様\n\n"
        f"注文 {order.order_number} の出荷予定日を {new_iso} に変更可能でしょうか。"
        f"電波暗室の据付スケジュールが後ろ倒しになり、機器の受け入れが間に合わない見込みです。校正サイクル SLA への影響有無もご教示ください。\n\n"
        f"{cust.name}"
    )
    body = {"en": body_en, "es": body_es, "ja": body_ja}.get(cust.language, body_en)
    return {
        "from": cust.email,
        "subject": f"Reschedule shipment {order.order_number} → {new_iso}",
        "body": body,
        "language_hint": cust.language,
        "customer_id": cust.id,
        "attachments": [],
    }


def _pull_in_request(cust: Customer) -> dict:
    body = (
        f"Hi team,\n\n"
        f"We have an NPI tape-out gating slot opening earlier than planned and need to pull in our recent UXR-series order by 10 business days. "
        f"Could you check inventory in APAC and confirm if expedited shipping is feasible? Willing to absorb the freight uplift if needed.\n\n"
        f"Best,\nDr. Jen Liu, Sr. Test Engineering Manager\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Pull-in request — UXR scope order, NPI gating",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _cal_request_iso17025(cust: Customer) -> dict:
    body = (
        f"Hello Keysight Service,\n\n"
        f"We need to schedule annual calibration for the following assets at our {_lab_context(cust)}:\n\n"
        f"  - MXA Signal Analyzer N9020B (S/N: KS-MXA-441298) — last cal 2025-05-12, OOT verification needed.\n"
        f"  - InfiniiVision DSOX3024T (S/N: KS-DSOX-882011) — interval-of-use due.\n\n"
        f"Please open work orders with ISO/IEC 17025 / A2LA-traceable certs and confirm the next available on-site slot. "
        f"As-found data is required for our quality records.\n\n"
        f"Thanks,\nLinda Voss, Calibration Lab Lead\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Annual cal request — ISO 17025 / A2LA traceable, 2 assets",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _cal_request_z540(cust: Customer) -> dict:
    body = (
        f"Hi Keysight Service team,\n\n"
        f"Per our defense program quality plan we need ANSI/NCSL Z540.3 calibration with as-found / as-left data on:\n\n"
        f"  - PNA-X N5247B (S/N: KS-PNAX-100442) — RF/microwave bench.\n"
        f"  - 3.5mm cal kit 85052D (S/N: KS-CAL-552219) — full S-parameter verification.\n\n"
        f"This work supports a MIL-STD-810 qualification campaign — please prioritize and confirm the cert package will include uncertainty budgets.\n\n"
        f"Aaron Brewer, Calibration Lab Supervisor\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Z540.3 cal request — PNA-X + cal kit, MIL-STD program",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _cal_request_es(cust: Customer) -> dict:
    body = (
        f"Hola Servicios Keysight,\n\n"
        f"Solicitamos calibración con trazabilidad A2LA para nuestro generador de señales vectoriales VXG (M9384B, S/N: KS-VXG-330117). "
        f"Lo utilizamos en nuestro banco de pre-cumplimiento 5G NR FR2 — necesitamos certificado con datos as-found para QA.\n\n"
        f"Por favor confirmen disponibilidad on-site en EMEA y costo.\n\n"
        f"Saludos,\nMariela Solís, Compras Técnicas\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Solicitud de calibración A2LA — VXG M9384B (5G NR FR2)",
        "body": body,
        "language_hint": "es",
        "customer_id": cust.id,
        "attachments": [],
    }


def _repair_request_ja(cust: Customer) -> dict:
    body = (
        f"Keysight サービス御中\n\n"
        f"Infiniium UXR0334A (S/N: KS-UXR-770283) のチャンネル 3 でトリガが掛からなくなる事象が発生しております。"
        f"DUT 側の問題は切り分け済みです。出張修理または交換機の手配をご検討ください。"
        f"FOSI として優先対応をお願いできれば幸いです。\n\n"
        f"よろしくお願いいたします。\n大野 / 評価部\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "修理依頼 — Infiniium UXR0334A Ch3 トリガ不具合（FOSI 申請）",
        "body": body,
        "language_hint": "ja",
        "customer_id": cust.id,
        "attachments": [],
    }


def _wo_status(cust: Customer, *, urgency: str) -> dict:
    if urgency == "high":
        body = (
            f"Hi team,\n\n"
            f"Could I get an urgent status update on our open work orders? The cal-due assets are blocking a customer audit on Friday. "
            f"Specifically need ETA on the in-progress UXR job and confirmation that the as-found data will be in the cert package.\n\n"
            f"Thanks,\nDr. Jen Liu, Sr. Test Engineering Manager\n{cust.name}"
        )
        subj = "URGENT: WO status needed — customer audit Friday"
    else:
        body = (
            f"Hi,\n\n"
            f"What's the latest status on our open work orders? "
            f"Looking for projected completion dates and any flagged out-of-tolerance items.\n\n"
            f"Thanks,\n{cust.name}"
        )
        subj = "WO status update"
    return {
        "from": cust.email,
        "subject": subj,
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _wo_status_ja(cust: Customer) -> dict:
    body = (
        f"お世話になっております。\n\n"
        f"弊社オープン状態の作業指示書のステータスと完了見込みをご教示ください。"
        f"特に校正対象アセットについて、OOT 項目の有無もあわせてご連絡いただけますでしょうか。\n\n"
        f"{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "作業指示のステータス確認 (校正対象 OOT 含む)",
        "body": body,
        "language_hint": "ja",
        "customer_id": cust.id,
        "attachments": [],
    }


def _eol_inquiry(cust: Customer) -> dict:
    body = (
        f"Hi Keysight,\n\n"
        f"We're planning our 2027 lab refresh and need your roadmap on the E5071C ENA family — specifically EOL/EOS dates and the recommended migration path. "
        f"Is the E5080B-2H285 the supported successor, and can you share the lifecycle policy doc and any migration credits available for installed-base customers?\n\n"
        f"Best,\nDr. Priya Iyer, Lab PI\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "E5071C lifecycle / EOL roadmap + migration path question",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _cross_sell_inquiry(cust: Customer) -> dict:
    body = (
        f"Hi sales team,\n\n"
        f"For an upcoming defense radar program we'll need 67 GHz S-parameter capability and high-power signal generation up to 44 GHz. "
        f"The PNA-X N5247B + VXG M9384B combo looks right — can you send a customer-spec'd proposal with cal kits and Z540.3 calibration bundles? "
        f"Also confirm typical lead time for ITAR-flagged orders.\n\n"
        f"Thanks,\nMike Ferraro\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Proposal request — PNA-X 67 GHz + VXG 44 GHz, ITAR program",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _phish_email() -> dict:
    return {
        "from": "treasury.dept@trustedbank-secure-verify.net",
        "subject": "URGENT: account verification required to release pending wire",
        "body": (
            "Dear customer,\n\nWe have detected a pending wire transfer of $2,450,000 USD that requires immediate "
            "verification. To prevent forfeiture, please reply with your full bank account number, IBAN/SWIFT, "
            "and a copy of your CFO's signature. Failure to respond within 24 hours will result in cancellation.\n\n"
            "Treasury Operations"
        ),
        "language_hint": "en",
        "customer_id": None,
        "attachments": [],
    }


def _promo_spam() -> dict:
    return {
        "from": "deals@instrument-discounts-deals.com",
        "subject": "🎉 70% OFF lab instruments — TODAY ONLY — Click now",
        "body": (
            "Hi friend!!! Massive blowout sale on premium lab instruments — oscilloscopes, signal generators, "
            "VNAs all 70% off TODAY ONLY!!! Click here >>> http://shady-deals-promo.com/click <<< to claim "
            "your discount before stock runs out. Free shipping with promo code WIN2026."
        ),
        "language_hint": "en",
        "customer_id": None,
        "attachments": [],
    }


def _ambiguous_short(cust: Customer) -> dict:
    return {
        "from": cust.email,
        "subject": "status?",
        "body": "any update?",
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _forwarded_thread(cust: Customer) -> dict:
    body = (
        "---------- Forwarded message ---------\n"
        "From: Aurora EE Lead <ee.lead@auroraauto.com>\n"
        "To: ee.procurement@auroraauto.com\n"
        "Subject: Re: SO update\n\n"
        "Procurement — please follow up with Keysight on the open SO. "
        "We've been waiting two weeks on the SOA and the bench install is gated.\n\n"
        "Tom\n\n"
        "---------- Original ---------\n"
        f"Hi Keysight,\n\nFollowing up on our recent automotive Ethernet bench order (SO not yet acknowledged). "
        f"Could you confirm the SOA was processed and share the current ETA? "
        f"Our 100BASE-T1 conformance schedule is at risk.\n\n"
        f"Thanks,\nAurora EE Procurement\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Fwd: Re: SO update — automotive Ethernet bench",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _trade_change_order(cust: Customer, order: Order) -> dict:
    body = (
        f"Hi Keysight Sales Ops,\n\n"
        f"We need to make the following changes to our existing booked order {order.order_number}:\n\n"
        f"  • Increase qty on the first line item by 1 (we need a second test bench).\n"
        f"  • Add a 3.5 mm cal kit (SKU 85052D) to the order — this was missed on the original PO.\n"
        f"  • Update the bill-to address to our new AP office: PO Box 11337, Waltham, MA 02454.\n\n"
        f"Customer PO ref will follow as a revision (we'll send PO-{order.order_number}-R02 once finance signs off). "
        f"Please confirm receipt and let me know if any of these need a sales-ops approval given the order is already booked.\n\n"
        f"Thanks,\nMatt Holloway, Senior Buyer\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"Change order — {order.order_number} — qty bump + add cal kit + bill-to update",
        "body": body,
        "language_hint": cust.language,
        "customer_id": cust.id,
        "attachments": [],
    }


def _ssd_change_request(cust: Customer, orders_by_cust: dict[int, list[Order]]) -> dict:
    opens = [o for o in (orders_by_cust.get(cust.id) or []) if o.status == "open"]
    order = opens[0] if opens else None
    new_iso = (datetime.now().date() + timedelta(days=10)).isoformat()
    body = (
        f"Hi team,\n\n"
        f"Requesting a Ship Schedule Date (SSD) **pull-in** on order {order.order_number if order else '(see attached)'}: "
        f"can we move the requested ship date earlier to {new_iso}? "
        f"Our NPI tape-out gating slot opened up sooner than expected and we want to use the UXR scope on first silicon. "
        f"Willing to absorb expedited freight if needed.\n\n"
        f"Per our service contract, this should fall inside our Platinum SLA window — please advise on feasibility.\n\n"
        f"Best,\nDr. Jen Liu, Sr. Test Engineering Manager\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"SSD pull-in request — {order.order_number if order else '(unknown)'} — NPI gating",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _ssd_change_request_partial(cust: Customer, orders_by_cust: dict[int, list[Order]]) -> dict:
    opens = [o for o in (orders_by_cust.get(cust.id) or []) if o.status == "open"]
    order = opens[0] if opens else None
    new_iso = (datetime.now().date() + timedelta(days=21)).isoformat()
    body = (
        f"Hi,\n\n"
        f"On order {order.order_number if order else '(see PO ref)'}: please split the shipment — "
        f"send the oscilloscope on the original requested ship date, but push out the SMU and cal-kit lines to {new_iso}. "
        f"Our 100BASE-T1 conformance bench can use the scope first; the SMU bench install is delayed.\n\n"
        f"Direction: partial. Let me know if this requires a separate PO revision or can be handled on the original.\n\n"
        f"Tom Reilly, EE Test Lead\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": f"SSD change — partial split shipment on {order.order_number if order else '(unknown)'}",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _wo_update_request(cust: Customer) -> dict:
    body = (
        f"Hola Keysight Service team,\n\n"
        f"Necesitamos actualizar nuestra orden de trabajo abierta (WO de reparación del UXR0334A). "
        f"Por favor agregar la siguiente nota: 'Cliente confirma que el problema se reproduce intermitentemente en Ch3 entre 12-15 GHz, no continuo. Adjuntar capturas si es posible.' "
        f"Y agregar una task: 'Ejecutar verificación de S-parameters as-found ANTES de cualquier ajuste, para nuestro audit log.'\n\n"
        f"Gracias,\nCarlos Iglesias, Lab Operations Lead\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "WO update — UXR repair · agregar nota + task de verificación as-found",
        "body": body,
        "language_hint": "es",
        "customer_id": cust.id,
        "attachments": [],
    }


def _wo_update_add_assets(cust: Customer) -> dict:
    body = (
        f"Hi Service team,\n\n"
        f"On our open calibration WO, please add 2 more assets to the same job — these came back from the field and need to ride on the same on-site visit:\n\n"
        f"  • N9020B MXA Signal Analyzer · S/N KS-MXA-441298 · normal cal interval\n"
        f"  • DSOX3024T Oscilloscope · S/N KS-DSOX-882011 · normal cal interval\n\n"
        f"They should be covered under our active service contract. Please coordinate the schedule so all assets are calibrated in one technician visit.\n\n"
        f"Linda Voss, Calibration Lab Lead\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "WO update — add 2 more assets to the open cal job",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _service_contract_quote(cust: Customer) -> dict:
    body = (
        f"Hi Keysight,\n\n"
        f"We're standing up a new instrumentation lab in Q3 and need a quote for a 3-year **Calibration Plan** "
        f"covering 12 instruments — primarily PNA-X, MXG signal generators, and a couple of UXR oscilloscopes. "
        f"Please include ANSI/NCSL Z540.3 traceability with as-found data, on-site service option, and Platinum SLA "
        f"(4h response / 24h resolution).\n\n"
        f"Asset list with serials will follow next week — for now we just need ballpark pricing for budgeting.\n\n"
        f"Thanks,\nMarisol Tang, Procurement Manager\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Service contract quote request — 3-yr Cal Plan, 12 assets, Z540.3 + on-site",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _service_contract_renewal(cust: Customer) -> dict:
    body = (
        f"Hi Keysight Service Contracts team,\n\n"
        f"Our existing service contract is approaching expiry and we'd like to **renew** for another 12 months at the same coverage level (Platinum tier). "
        f"Our defense program quality plan continues to require Z540.3 cal with full uncertainty budgets.\n\n"
        f"If there's any pricing concession for multi-year renewal, we'd consider extending to 24 or 36 months. "
        f"Please send the renewal quote with start date aligning to current contract end date.\n\n"
        f"Aaron Brewer, Calibration Lab Supervisor\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Service contract renewal — Z540.3 cal plan, Platinum SLA",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _service_contract_es(cust: Customer) -> dict:
    body = (
        f"Hola Keysight,\n\n"
        f"Solicito información sobre planes de mantenimiento preventivo (PM) para nuestra cámara anecoica y banco "
        f"de pre-cumplimiento 5G. Buscamos un plan **PM** con visita semestral, calibración trazable A2LA, "
        f"y SLA Gold (8h response / 48h resolution).\n\n"
        f"Aproximadamente 8 instrumentos en cobertura. ¿Pueden enviar una cotización inicial y los términos del contrato?\n\n"
        f"Saludos,\nLucía Méndez, AP & Procurement\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Solicitud — Plan PM con cal A2LA, SLA Gold, ~8 instrumentos",
        "body": body,
        "language_hint": "es",
        "customer_id": cust.id,
        "attachments": [],
    }


def _multi_asset_cal_request(cust: Customer) -> dict:
    body = (
        f"Hi Keysight Service,\n\n"
        f"We need to schedule annual calibration on **6 instruments** at our Hsinchu Foundry-4 metrology bay. "
        f"All are due this quarter per our QMS schedule and need to be done as a single on-site visit to minimize bay downtime.\n\n"
        f"Asset list:\n"
        f"  1. UXR0334A Real-Time Scope · S/N KS-UXR-441288\n"
        f"  2. PNA-X N5247B 67 GHz VNA · S/N KS-PNAX-330917\n"
        f"  3. MXA N9020B Signal Analyzer · S/N KS-MXA-882103\n"
        f"  4. VXG M9384B Vector Sig Gen · S/N KS-VXG-118822\n"
        f"  5. M8040A 64 GBaud BERT · S/N KS-BERT-998811\n"
        f"  6. B2902B Precision SMU · S/N KS-SMU-771044\n\n"
        f"All require ISO/IEC 17025 cert with A2LA traceability and as-found data per our quality records. "
        f"Please confirm earliest available 1-week on-site window and quote.\n\n"
        f"Daniel Wu, Metrology Procurement Lead\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Multi-asset cal request — 6 instruments, on-site, ISO 17025 / A2LA",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _misrouted_email(cust: Customer) -> dict:
    body = (
        f"Hello,\n\n"
        f"Quick question on the open work order for our SMU — did the as-found data come back in spec? "
        f"Also, while you're looking, can you check whether our last invoice (INV-2007-3) has been paid? "
        f"My AP team flagged it but I want to verify on your side before I push back.\n\n"
        f"Dr. Priya Iyer, Lab PI\n{cust.name}"
    )
    return {
        "from": cust.email,
        "subject": "Quick: WO as-found status + invoice INV-2007-3 paid?",
        "body": body,
        "language_hint": "en",
        "customer_id": cust.id,
        "attachments": [],
    }


def _lab_context(cust: Customer) -> str:
    return {
        "aerospace_defense": "RF/microwave electronic warfare lab",
        "semiconductor": "wafer-level metrology bench",
        "wireless_5g6g": "5G NR FR1/FR2 conformance lab",
        "automotive": "automotive Ethernet / 100BASE-T1 conformance bench",
        "research": "quantum control electronics rack",
        "industrial": "production T&M cal lab",
        "test_systems_integrator": "ATE integration cell",
    }.get(cust.vertical or "", "production T&M lab")


def _use_case_for(cust: Customer) -> str:
    return {
        "aerospace_defense": "MIL-STD-461 EMI/EMC pre-compliance",
        "semiconductor": "5G NR FR2 transceiver validation and signal integrity at 67 GHz",
        "wireless_5g6g": "OTA EVM measurements for 5G NR FR2",
        "automotive": "automotive Ethernet 100BASE-T1 conformance + ISO 26262 functional safety",
        "research": "qubit control characterization at mK temperatures",
        "industrial": "production line incoming-inspection",
        "test_systems_integrator": "ATE platform integration for Tier-1 OEM",
    }.get(cust.vertical or "", "general T&M bench")


_VERTICAL_PRODUCT_FAMILIES: dict[str, list[str]] = {
    "aerospace_defense": ["VNA", "SA", "SG", "FieldFox", "ACC"],
    "semiconductor": ["OSC", "BERT", "SA", "SG", "SMU"],
    "wireless_5g6g": ["SA", "SG", "VNA", "FieldFox"],
    "automotive": ["OSC", "SMU", "DC", "AWG", "LA"],
    "research": ["SMU", "AWG", "DC", "SG"],
    "industrial": ["OSC", "SA", "DC", "SMU", "FieldFox"],
    "test_systems_integrator": ["AWG", "OSC", "SMU", "LA", "DC"],
}

_LOCATION_TEMPLATES: dict[str, list[str]] = {
    "AMS": [
        "RF Bench {n} / Bldg E2 / El Segundo Lab",
        "Cal Lab Rack {n} / Auburn Hills EE Lab",
        "Q-Lab 7 / Boulder Innovation Way",
        "Calibration Bay {n} / Arlington Bldg 12",
    ],
    "EMEA": [
        "Anechoic Chamber {n} / Stuttgart Lab",
        "Cámara Anecoica {n} / Alcobendas Nave 22",
        "Industriepark Halle 4 / Köln",
    ],
    "APAC": [
        "Foundry 4 Metrology Bay {n} / Hsinchu",
        "R&D 受入 Bench {n} / Yokohama",
        "ATE Cell {n} / Tokyo Gotanda",
    ],
}

_TECHNICIANS = [
    "K. Watanabe",
    "L. Ortega",
    "S. Patel",
    "A. Brewer",
    "H. Krüger",
    "M. Olsen",
    "P. Esteban",
    "D. Park",
    "R. Chandra",
    "T. Kondo",
]


def _family_to_serial_prefix(family: str | None) -> str:
    return {
        "VNA": "VNA",
        "SA": "SA",
        "SG": "SG",
        "OSC": "SCOPE",
        "FieldFox": "FFX",
        "BERT": "BERT",
        "SMU": "SMU",
        "DC": "DCPA",
        "AWG": "AWG",
        "LA": "LA",
        "ACC": "CAL",
    }.get(family or "", "INST")


def _seed_assets(
    db: Session,
    *,
    customers: list[Customer],
    by_sku: dict[str, Product],
    today: datetime,
) -> dict[int, list[Asset]]:
    assets_by_cust: dict[int, list[Asset]] = {}
    serial_seen: set[str] = set()
    region_to_customer = {c.id: c.region for c in customers}

    for cust in customers:
        families = _VERTICAL_PRODUCT_FAMILIES.get(cust.vertical or "", ["OSC", "SA", "SG"])
        candidate_skus = [
            sku for sku, p in by_sku.items()
            if p.family in families and p.category != "Service"
        ]
        if not candidate_skus:
            candidate_skus = [sku for sku, p in by_sku.items() if p.category != "Service"]
        n_assets = random.randint(3, 6)
        chosen_skus = random.sample(candidate_skus, k=min(n_assets, len(candidate_skus)))

        for sku in chosen_skus:
            p = by_sku[sku]
            prefix = _family_to_serial_prefix(p.family)
            for _ in range(20):
                sn = f"KS-{prefix}-{random.randint(100000, 999999)}"
                if sn not in serial_seen:
                    serial_seen.add(sn)
                    break
            install_days = random.randint(365, 365 * 4)
            install_date = today - timedelta(days=install_days)
            cal_interval = p.calibration_interval_months or 12
            last_cal_offset = random.randint(180, 540)
            last_cal_date = today - timedelta(days=last_cal_offset)
            cal_due = last_cal_date + timedelta(days=cal_interval * 30)
            warranty_months = p.warranty_months or 12
            warranty_expires = install_date + timedelta(days=warranty_months * 30)

            loc_pool = _LOCATION_TEMPLATES.get(region_to_customer[cust.id], _LOCATION_TEMPLATES["AMS"])
            location = random.choice(loc_pool).replace("{n}", str(random.randint(1, 9)))

            status = random.choices(
                ["in_service", "in_service", "in_service", "in_service", "out_for_cal", "decommissioned"],
                k=1,
            )[0]

            notes = None
            if cal_due < today:
                notes = "Cal overdue — flagged for next on-site visit."
            elif (cal_due - today).days < 30:
                notes = f"Cal due in {(cal_due - today).days}d — schedule with {random.choice(_TECHNICIANS)}."

            asset = Asset(
                customer_id=cust.id,
                sku=sku,
                description=p.description,
                serial=sn,
                install_date=install_date,
                location=location,
                last_cal_date=last_cal_date,
                calibration_due_date=cal_due,
                cal_interval_months=cal_interval,
                status=status,
                warranty_expires=warranty_expires,
                notes=notes,
            )
            db.add(asset)
            assets_by_cust.setdefault(cust.id, []).append(asset)
    return assets_by_cust


_TIER_SLA = {
    "Platinum": (4, 24),
    "Gold": (8, 48),
    "Silver": (24, 72),
}


def _seed_service_contracts(
    db: Session,
    *,
    customers: list[Customer],
    assets_by_cust: dict[int, list[Asset]],
    today: datetime,
) -> int:
    contract_types = ["Calibration Plan", "Onsite Service Plan", "PM (Preventive Maintenance)"]
    selected = random.sample(customers, k=min(8, len(customers)))
    count = 0
    for cust in selected:
        cust_assets = assets_by_cust.get(cust.id, [])
        if not cust_assets:
            continue
        n_contracts = random.randint(1, 2)
        types_picked = random.sample(contract_types, k=n_contracts)
        for idx, ctype in enumerate(types_picked):
            tier = cust.sla_tier or "Gold"
            response_h, resolution_h = _TIER_SLA.get(tier, (8, 48))
            starts_on = today - timedelta(days=random.randint(60, 720))
            expires_on = starts_on + timedelta(days=365)
            covered = random.sample(
                cust_assets,
                k=min(random.randint(2, max(2, len(cust_assets) - 1)), len(cust_assets)),
            )
            included_serials = [a.serial for a in covered]
            annual_value = round(random.uniform(50_000, 500_000), 2)
            status = "active" if expires_on > today else "expired"
            contract = ServiceContract(
                customer_id=cust.id,
                contract_number=f"SC-{cust.code}-{1000 + idx + count}",
                type=ctype,
                starts_on=starts_on,
                expires_on=expires_on,
                sla_response_hours=response_h,
                sla_resolution_hours=resolution_h,
                included_assets=included_serials,
                annual_value_usd=annual_value,
                status=status,
                notes=f"{tier} tier · {len(included_serials)} assets covered · {ctype}",
            )
            db.add(contract)
            count += 1
    return count


def _seed_calibration_certs(
    db: Session,
    *,
    assets_by_cust: dict[int, list[Asset]],
    by_code: dict[str, Customer],
    today: datetime,
) -> int:
    flat_assets: list[tuple[Customer, Asset]] = []
    for cust in by_code.values():
        for a in assets_by_cust.get(cust.id, []):
            if a.last_cal_date is not None:
                flat_assets.append((cust, a))

    sample_size = min(22, len(flat_assets))
    chosen = random.sample(flat_assets, k=sample_size)
    traceability_options = ["ISO_17025_A2LA", "ANSI_NCSL_Z540", "Z540.3"]
    lab_ids = ["KS-LAB-AMS-3", "KS-LAB-EMEA-1", "KS-LAB-APAC-2", "KS-LAB-AMS-7"]

    oot_summaries = [
        "OOT on channel 3 power: -1.2 dB at 18 GHz, returned to spec after adjustment.",
        "Phase noise OOT at 10 kHz offset (+3 dBc/Hz vs spec); realigned LO and verified within tolerance.",
        "OOT on time-base accuracy (+2.1 ppm); recalibrated 10 MHz reference, as-left within ±0.5 ppm.",
        "Channel 2 vertical gain OOT (-0.8% FS); ADC trim adjusted, as-left passes Z540.3 guard banding.",
    ]

    count = 0
    for idx, (cust, asset) in enumerate(chosen):
        issued = asset.last_cal_date
        expires = (issued + timedelta(days=365)) if issued else None
        is_oot = (idx % 7 == 0)
        as_found = random.choice(oot_summaries) if is_oot else "All measurement points within published spec; no adjustments required."
        as_left = "All as-left points within ANSI/NCSL Z540.3 guard banding; cert package issued with uncertainty budgets."
        cert_number = f"CAL-{cust.code}-{100000 + idx + count:06d}"
        traceability = random.choice(traceability_options)
        lab_id = random.choice(lab_ids)
        technician = random.choice(_TECHNICIANS)

        pdf_name = f"CERT_{cert_number}.pdf"
        try:
            make_calibration_cert_pdf(
                OUTPUTS / pdf_name,
                cert_number=cert_number,
                customer_name=cust.name,
                asset_sku=asset.sku,
                asset_serial=asset.serial,
                asset_description=asset.description,
                traceability=traceability,
                lab_id=lab_id,
                technician=technician,
                issued_date=issued,
                expires_date=expires,
                out_of_tolerance=is_oot,
                as_found_summary=as_found,
                as_left_summary=as_left,
            )
        except Exception:
            pdf_name = None

        cert = CalibrationCert(
            cert_number=cert_number,
            asset_id=asset.id,
            customer_id=cust.id,
            issued_date=issued,
            expires_date=expires,
            traceability=traceability,
            lab_id=lab_id,
            technician=technician,
            out_of_tolerance=is_oot,
            as_found_summary=as_found,
            as_left_summary=as_left,
            pdf_filename=pdf_name,
        )
        db.add(cert)
        count += 1
    return count


def _seed_shipments(
    db: Session,
    *,
    orders_by_cust: dict[int, list[Order]],
    today: datetime,
) -> int:
    region_to_carrier = {
        "AMS": ["FedEx Priority", "UPS Ground"],
        "EMEA": ["DHL Express", "FedEx Priority"],
        "APAC": ["DHL Express", "FedEx Priority"],
    }
    count = 0
    for orders in orders_by_cust.values():
        for o in orders:
            cust = db.get(Customer, o.customer_id)
            region = cust.region if cust else "AMS"
            carrier = random.choice(region_to_carrier.get(region, ["FedEx Priority"]))
            tracking = f"{carrier.split()[0].upper()}-{random.randint(10**11, 10**12 - 1)}"

            requested = o.requested_ship_date or (today + timedelta(days=14))
            if o.status == "open":
                ship_date = today - timedelta(days=random.randint(1, 5))
                eta_date = ship_date + timedelta(days=random.randint(3, 9))
                delivered = None
                status = "in_transit"
            elif o.status == "on_hold":
                ship_date = None
                eta_date = requested
                delivered = None
                status = "prepared"
            else:
                ship_date = today - timedelta(days=random.randint(7, 21))
                eta_date = ship_date + timedelta(days=random.randint(2, 6))
                delivered = eta_date
                status = "delivered"

            weight = round(random.uniform(8, 95), 1)
            incoterms = (cust.default_incoterms if cust else None) or "FOB Origin"

            db.add(
                Shipment(
                    order_id=o.id,
                    carrier=carrier,
                    tracking_number=tracking,
                    ship_date=ship_date,
                    eta_date=eta_date,
                    delivered_date=delivered,
                    status=status,
                    weight_lbs=weight,
                    incoterms=incoterms,
                )
            )
            count += 1
    return count


def _seed_invoices(
    db: Session,
    *,
    orders_by_cust: dict[int, list[Order]],
    by_code: dict[str, Customer],
    today: datetime,
) -> int:
    bluehawk = by_code.get("BLUEH-DEF-021")
    bluehawk_id = bluehawk.id if bluehawk else None
    count = 0
    for orders in orders_by_cust.values():
        for o in orders:
            if o.status not in ("open", "on_hold"):
                continue
            terms_days = 45
            cust = db.get(Customer, o.customer_id)
            if cust and cust.payment_terms:
                try:
                    terms_days = int(str(cust.payment_terms).replace("Net", "").strip())
                except ValueError:
                    terms_days = 45
            invoice_date = (o.created_at or today) - timedelta(days=random.randint(0, 5))
            if invoice_date.tzinfo is None:
                invoice_date = invoice_date.replace(tzinfo=timezone.utc)
            due_date = invoice_date + timedelta(days=terms_days)
            tail = (o.order_number or f"SO-{o.id}").split("-")[-1]
            inv_num = f"INV-{tail}-{count + 1}"

            if o.customer_id == bluehawk_id and o.status == "on_hold":
                status = "overdue"
                invoice_date = today - timedelta(days=terms_days + random.randint(15, 45))
                due_date = invoice_date + timedelta(days=terms_days)
                paid = 0.0
            elif o.status == "on_hold":
                status = random.choice(["issued", "overdue"])
                if status == "overdue":
                    invoice_date = today - timedelta(days=terms_days + random.randint(5, 20))
                    due_date = invoice_date + timedelta(days=terms_days)
                paid = 0.0
            else:
                status = random.choice(["issued", "paid", "issued"])
                paid = (o.total or 0.0) if status == "paid" else 0.0

            currency = (cust.default_currency if cust else "USD") or "USD"
            line_items = list(o.line_items or [])
            if not line_items:
                line_items = [{"sku": "MISC", "description": "Miscellaneous items per order", "qty": 1, "unit_price": o.total or 0.0}]
            subtotal = round(sum(li["qty"] * li["unit_price"] for li in line_items), 2)
            target_total = round(o.total or subtotal, 2)
            tax = round(max(0.0, target_total - subtotal), 2)

            payment_terms = (cust.payment_terms if cust and cust.payment_terms else "Net 45")
            customer_addr = "-"
            bill_to_text = cust.name if cust else "-"
            ship_to_text = cust.name if cust else "-"
            if cust and cust.addresses:
                addrs = cust.addresses if isinstance(cust.addresses, list) else []
                bill_addr = next((a for a in addrs if (a.get("type") == "billing" or a.get("kind") == "billing")), addrs[0] if addrs else None)
                ship_addr = next((a for a in addrs if (a.get("type") == "shipping" or a.get("kind") == "shipping")), bill_addr)

                def _fmt(a):
                    if not a:
                        return cust.name
                    parts = [
                        cust.name,
                        a.get("attention") or a.get("attn"),
                        a.get("street") or a.get("line1"),
                        a.get("line2"),
                        ", ".join([p for p in [a.get("city"), a.get("region") or a.get("state"), a.get("postal_code") or a.get("zip")] if p]),
                        a.get("country"),
                    ]
                    return "<br/>".join(p for p in parts if p)

                bill_to_text = _fmt(bill_addr)
                ship_to_text = _fmt(ship_addr)
                customer_addr = bill_to_text
            elif cust:
                customer_addr = f"{cust.name}<br/>{cust.region} Operations"

            pdf_name = f"INV_{inv_num}.pdf"
            try:
                make_invoice_pdf(
                    OUTPUTS / pdf_name,
                    invoice_number=inv_num,
                    invoice_date=invoice_date,
                    due_date=due_date,
                    customer_name=cust.name if cust else "Customer",
                    customer_addr=customer_addr,
                    bill_to=bill_to_text,
                    ship_to=ship_to_text,
                    line_items=line_items,
                    subtotal=subtotal,
                    tax=tax,
                    total=target_total,
                    currency=currency,
                    payment_terms=payment_terms,
                    notes=None,
                    status=status,
                )
            except Exception:
                pdf_name = None

            db.add(
                Invoice(
                    order_id=o.id,
                    customer_id=o.customer_id,
                    invoice_number=inv_num,
                    invoice_date=invoice_date,
                    due_date=due_date,
                    currency=currency,
                    amount=o.total or 0.0,
                    paid_amount=paid,
                    status=status,
                    pdf_filename=pdf_name,
                )
            )
            count += 1
    return count
