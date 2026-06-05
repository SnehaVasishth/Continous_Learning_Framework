"""Read-only access to the synthetic CRM/ERP records.
Powers the Data viewer page so reviewers can see what the agents are matching
inbound emails against.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Asset,
    CalibrationCert,
    CommunicationLog,
    Contact,
    Customer,
    Invoice,
    Order,
    Product,
    Quote,
    ServiceContract,
    Shipment,
    WorkOrder,
)
from ..services import salesforce as sf_svc
from ..services import salesforce_data as sf_data

router = APIRouter()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/customers")
def customers(db: Session = Depends(get_db)):
    sf_conn = sf_svc.get_active_connection(db)
    if sf_conn:
        try:
            return sf_data.list_customers(sf_conn)
        except Exception as e:
            # Fall through to SQLite if Salesforce is briefly unreachable
            import logging
            logging.getLogger("data.customers").warning("salesforce list_customers failed, falling back: %s", e)

    rows = db.query(Customer).order_by(Customer.code).all()
    out = []
    for c in rows:
        quote_count = db.query(Quote).filter(Quote.customer_id == c.id).count()
        order_count = db.query(Order).filter(Order.customer_id == c.id).count()
        wo_count = db.query(WorkOrder).filter(WorkOrder.customer_id == c.id).count()
        out.append(
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "email": c.email,
                "region": c.region,
                "language": c.language,
                "vertical": c.vertical,
                "compliance": c.compliance or [],
                "history": {"quotes": quote_count, "orders": order_count, "work_orders": wo_count},
                "_source": "sqlite",
            }
        )
    return out


@router.get("/products")
def products(db: Session = Depends(get_db)):
    rows = db.query(Product).order_by(Product.family, Product.sku).all()
    return [
        {
            "id": p.id,
            "sku": p.sku,
            "mpn": p.mpn,
            "description": p.description,
            "list_price": p.list_price,
            "family": p.family,
            "category": p.category,
            "lifecycle_status": p.lifecycle_status,
            "lifecycle_eol_date": p.lifecycle_eol_date.isoformat() if p.lifecycle_eol_date else None,
            "successor_sku": p.successor_sku,
            "lead_time_weeks": p.lead_time_weeks,
            "calibration_interval_months": p.calibration_interval_months,
            "country_of_origin": p.country_of_origin,
            "eccn": p.eccn,
            "hs_code": p.hs_code,
            "warranty_months": p.warranty_months,
            "moq": p.moq,
            "hazmat": p.hazmat,
            "weight_kg": p.weight_kg,
        }
        for p in rows
    ]


@router.get("/quotes")
def quotes(db: Session = Depends(get_db)):
    rows = db.query(Quote).order_by(Quote.id.desc()).all()
    out = []
    for q in rows:
        cust = db.get(Customer, q.customer_id)
        out.append(
            {
                "id": q.id,
                "quote_number": q.quote_number,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                "total": q.total,
                "status": q.status,
                "line_count": len(q.line_items or []),
                "line_items": q.line_items or [],
            }
        )
    return out


@router.get("/orders")
def orders(db: Session = Depends(get_db)):
    rows = db.query(Order).order_by(Order.id.desc()).all()
    out = []
    for o in rows:
        cust = db.get(Customer, o.customer_id)
        out.append(
            {
                "id": o.id,
                "order_number": o.order_number,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "status": o.status,
                "hold_reason": o.hold_reason,
                "requested_ship_date": o.requested_ship_date.isoformat() if o.requested_ship_date else None,
                "total": o.total,
                "line_count": len(o.line_items or []),
                "line_items": o.line_items or [],
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
        )
    return out


@router.get("/work-orders")
def work_orders(db: Session = Depends(get_db)):
    rows = db.query(WorkOrder).order_by(WorkOrder.id.desc()).all()
    out = []
    for w in rows:
        cust = db.get(Customer, w.customer_id)
        out.append(
            {
                "id": w.id,
                "wo_number": w.wo_number,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "asset_serial": w.asset_serial,
                "asset_sku": w.asset_sku,
                "type": w.type,
                "status": w.status,
                "region": w.region,
                "assigned_team": w.assigned_team,
                "technician": w.technician,
                "service_contract_id": w.service_contract_id,
                "scheduled_date": w.scheduled_date.isoformat() if w.scheduled_date else None,
                "sla_target_date": w.sla_target_date.isoformat() if w.sla_target_date else None,
                "completed_date": w.completed_date.isoformat() if w.completed_date else None,
                "standards_referenced": w.standards_referenced or [],
                "labor_hours": w.labor_hours,
                "signoff_status": w.signoff_status,
                "cert_number": w.cert_number,
                "cost_usd": w.cost_usd,
                "pdf_url": f"/files/outputs/{w.pdf_filename}" if w.pdf_filename else None,
                "pdf_filename": w.pdf_filename,
            }
        )
    return out


@router.get("/contacts")
def contacts(db: Session = Depends(get_db)):
    rows = db.query(Contact).order_by(Contact.id.desc()).all()
    out = []
    for c in rows:
        cust = db.get(Customer, c.customer_id)
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "title": c.title,
                "role": c.role,
                "email": c.email,
                "phone": c.phone,
                "language": c.language,
                "is_primary": c.is_primary,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
            }
        )
    return out


@router.get("/assets")
def assets(db: Session = Depends(get_db)):
    rows = db.query(Asset).order_by(Asset.id.desc()).all()
    now = _now_utc()
    out = []
    for a in rows:
        cust = db.get(Customer, a.customer_id)
        cal_due = _aware(a.calibration_due_date)
        if cal_due is None:
            cal_status = "unknown"
        elif cal_due < now:
            cal_status = "overdue"
        elif (cal_due - now).days <= 30:
            cal_status = "due_soon"
        else:
            cal_status = "current"
        out.append(
            {
                "id": a.id,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "sku": a.sku,
                "description": a.description,
                "serial": a.serial,
                "install_date": a.install_date.isoformat() if a.install_date else None,
                "location": a.location,
                "last_cal_date": a.last_cal_date.isoformat() if a.last_cal_date else None,
                "calibration_due_date": a.calibration_due_date.isoformat() if a.calibration_due_date else None,
                "cal_interval_months": a.cal_interval_months,
                "cal_status": cal_status,
                "status": a.status,
                "warranty_expires": a.warranty_expires.isoformat() if a.warranty_expires else None,
                "notes": a.notes,
            }
        )
    return out


@router.get("/service-contracts")
def service_contracts(db: Session = Depends(get_db)):
    rows = db.query(ServiceContract).order_by(ServiceContract.id.desc()).all()
    now = _now_utc()
    out = []
    for s in rows:
        cust = db.get(Customer, s.customer_id)
        expires = _aware(s.expires_on)
        days_until_expiry = (expires - now).days if expires else None
        out.append(
            {
                "id": s.id,
                "contract_number": s.contract_number,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "type": s.type,
                "starts_on": s.starts_on.isoformat() if s.starts_on else None,
                "expires_on": s.expires_on.isoformat() if s.expires_on else None,
                "days_until_expiry": days_until_expiry,
                "sla_response_hours": s.sla_response_hours,
                "sla_resolution_hours": s.sla_resolution_hours,
                "included_assets": s.included_assets or [],
                "annual_value_usd": s.annual_value_usd,
                "status": s.status,
                "notes": s.notes,
            }
        )
    return out


@router.get("/cal-certs")
def cal_certs(db: Session = Depends(get_db)):
    rows = db.query(CalibrationCert).order_by(CalibrationCert.id.desc()).all()
    out = []
    for c in rows:
        cust = db.get(Customer, c.customer_id)
        asset = db.get(Asset, c.asset_id) if c.asset_id else None
        wo = db.get(WorkOrder, c.work_order_id) if c.work_order_id else None
        out.append(
            {
                "id": c.id,
                "cert_number": c.cert_number,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "asset_id": c.asset_id,
                "asset_serial": asset.serial if asset else None,
                "asset_sku": asset.sku if asset else None,
                "work_order_id": c.work_order_id,
                "work_order_number": wo.wo_number if wo else None,
                "issued_date": c.issued_date.isoformat() if c.issued_date else None,
                "expires_date": c.expires_date.isoformat() if c.expires_date else None,
                "traceability": c.traceability,
                "lab_id": c.lab_id,
                "technician": c.technician,
                "out_of_tolerance": c.out_of_tolerance,
                "as_found_summary": c.as_found_summary,
                "as_left_summary": c.as_left_summary,
                "pdf_url": f"/files/outputs/{c.pdf_filename}" if c.pdf_filename else None,
                "pdf_filename": c.pdf_filename,
            }
        )
    return out


@router.get("/shipments")
def shipments(db: Session = Depends(get_db)):
    rows = db.query(Shipment).order_by(Shipment.id.desc()).all()
    out = []
    for s in rows:
        order = db.get(Order, s.order_id) if s.order_id else None
        cust = db.get(Customer, order.customer_id) if order else None
        out.append(
            {
                "id": s.id,
                "order_id": s.order_id,
                "order_number": order.order_number if order else None,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "carrier": s.carrier,
                "tracking_number": s.tracking_number,
                "ship_date": s.ship_date.isoformat() if s.ship_date else None,
                "eta_date": s.eta_date.isoformat() if s.eta_date else None,
                "delivered_date": s.delivered_date.isoformat() if s.delivered_date else None,
                "status": s.status,
                "weight_lbs": s.weight_lbs,
                "incoterms": s.incoterms,
            }
        )
    return out


@router.get("/invoices")
def invoices(db: Session = Depends(get_db)):
    rows = db.query(Invoice).order_by(Invoice.id.desc()).all()
    now = _now_utc()
    out = []
    for inv in rows:
        order = db.get(Order, inv.order_id) if inv.order_id else None
        cust = db.get(Customer, inv.customer_id) if inv.customer_id else None
        due = _aware(inv.due_date)
        if due and inv.status != "paid":
            days_overdue = (now - due).days
        else:
            days_overdue = 0
        out.append(
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "order_id": inv.order_id,
                "order_number": order.order_number if order else None,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "currency": inv.currency,
                "amount": inv.amount,
                "paid_amount": inv.paid_amount,
                "status": inv.status,
                "days_overdue": max(0, days_overdue),
                "pdf_url": f"/files/outputs/{inv.pdf_filename}" if inv.pdf_filename else None,
                "pdf_filename": inv.pdf_filename,
            }
        )
    return out


@router.get("/customers/{customer_id}")
def customer_detail(customer_id: str, db: Session = Depends(get_db)):
    # Salesforce 18-char Account Ids start with '001'; SQLite ids are ints.
    if isinstance(customer_id, str) and customer_id.startswith("001") and not customer_id.isdigit():
        sf_conn = sf_svc.get_active_connection(db)
        if sf_conn:
            try:
                detail = sf_data.customer_detail(sf_conn, db, customer_id)
                if not detail:
                    raise HTTPException(404)
                return detail
            except HTTPException:
                raise
            except Exception as e:
                import logging
                logging.getLogger("data.customer_detail").warning("salesforce detail failed: %s", e)
                raise HTTPException(502, f"Salesforce detail fetch failed: {e}")

    try:
        cid_int = int(customer_id)
    except ValueError:
        raise HTTPException(404, "customer not found")
    c = db.get(Customer, cid_int)
    if not c:
        raise HTTPException(404)
    customer_id = c.id  # type: ignore

    contacts = [
        {
            "id": ct.id,
            "name": ct.name,
            "title": ct.title,
            "role": ct.role,
            "email": ct.email,
            "phone": ct.phone,
            "language": ct.language,
            "is_primary": ct.is_primary,
        }
        for ct in db.query(Contact).filter(Contact.customer_id == customer_id).all()
    ]
    quotes = [
        {
            "id": q.id,
            "quote_number": q.quote_number,
            "total": q.total,
            "status": q.status,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
            "sales_rep": q.sales_rep,
            "opportunity_id": q.opportunity_id,
        }
        for q in db.query(Quote).filter(Quote.customer_id == customer_id).order_by(Quote.id.desc()).all()
    ]
    orders = [
        {
            "id": o.id,
            "order_number": o.order_number,
            "status": o.status,
            "hold_reason": o.hold_reason,
            "requested_ship_date": o.requested_ship_date.isoformat() if o.requested_ship_date else None,
            "total": o.total,
            "tracking_number": o.tracking_number,
            "csr_owner": o.csr_owner,
        }
        for o in db.query(Order).filter(Order.customer_id == customer_id).order_by(Order.id.desc()).all()
    ]
    work_orders = [
        {
            "id": w.id,
            "wo_number": w.wo_number,
            "type": w.type,
            "status": w.status,
            "asset_serial": w.asset_serial,
            "scheduled_date": w.scheduled_date.isoformat() if w.scheduled_date else None,
            "technician": w.technician,
        }
        for w in db.query(WorkOrder).filter(WorkOrder.customer_id == customer_id).order_by(WorkOrder.id.desc()).all()
    ]
    assets = [
        {
            "id": a.id,
            "serial": a.serial,
            "sku": a.sku,
            "description": a.description,
            "location": a.location,
            "calibration_due_date": a.calibration_due_date.isoformat() if a.calibration_due_date else None,
            "status": a.status,
        }
        for a in db.query(Asset).filter(Asset.customer_id == customer_id).order_by(Asset.id.desc()).all()
    ]
    contracts = [
        {
            "id": sc.id,
            "contract_number": sc.contract_number,
            "type": sc.type,
            "starts_on": sc.starts_on.isoformat() if sc.starts_on else None,
            "expires_on": sc.expires_on.isoformat() if sc.expires_on else None,
            "annual_value_usd": sc.annual_value_usd,
            "status": sc.status,
        }
        for sc in db.query(ServiceContract).filter(ServiceContract.customer_id == customer_id).order_by(ServiceContract.id.desc()).all()
    ]
    invoices = [
        {
            "id": iv.id,
            "invoice_number": iv.invoice_number,
            "invoice_date": iv.invoice_date.isoformat() if iv.invoice_date else None,
            "due_date": iv.due_date.isoformat() if iv.due_date else None,
            "amount": iv.amount,
            "paid_amount": iv.paid_amount,
            "status": iv.status,
            "currency": iv.currency,
        }
        for iv in db.query(Invoice).filter(Invoice.customer_id == customer_id).order_by(Invoice.id.desc()).all()
    ]
    cal_certs = [
        {
            "id": cc.id,
            "cert_number": cc.cert_number,
            "issued_date": cc.issued_date.isoformat() if cc.issued_date else None,
            "expires_date": cc.expires_date.isoformat() if cc.expires_date else None,
            "traceability": cc.traceability,
            "out_of_tolerance": cc.out_of_tolerance,
            "asset_id": cc.asset_id,
        }
        for cc in db.query(CalibrationCert).filter(CalibrationCert.customer_id == customer_id).order_by(CalibrationCert.id.desc()).all()
    ]
    comm_logs = [
        {
            "id": cl.id,
            "occurred_at": cl.occurred_at.isoformat() if cl.occurred_at else None,
            "direction": cl.direction,
            "channel": cl.channel,
            "subject": cl.subject,
            "language": cl.language,
            "intent": cl.intent,
            "autonomy_tier": cl.autonomy_tier,
            "sent_by": cl.sent_by,
            "csr_action": cl.csr_action,
            "pipeline_id": cl.pipeline_id,
            "order_id": cl.order_id,
            "work_order_id": cl.work_order_id,
            "body_preview": (cl.body or "")[:240],
        }
        for cl in (
            db.query(CommunicationLog)
            .filter(CommunicationLog.customer_id == customer_id)
            .order_by(CommunicationLog.id.desc())
            .limit(50)
            .all()
        )
    ]

    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "legal_entity": c.legal_entity,
        "email": c.email,
        "region": c.region,
        "language": c.language,
        "vertical": c.vertical,
        "compliance": c.compliance or [],
        "industry": c.industry,
        "naics": c.naics,
        "annual_revenue_usd": c.annual_revenue_usd,
        "employees": c.employees,
        "account_manager": c.account_manager,
        "sales_engineer": c.sales_engineer,
        "customer_since": c.customer_since.isoformat() if c.customer_since else None,
        "status": c.status,
        "sla_tier": c.sla_tier,
        "duns": c.duns,
        "tax_id": c.tax_id,
        "payment_terms": c.payment_terms,
        "credit_limit": c.credit_limit,
        "default_currency": c.default_currency,
        "default_incoterms": c.default_incoterms,
        "addresses": c.addresses or [],
        "contacts": contacts,
        "quotes": quotes,
        "orders": orders,
        "work_orders": work_orders,
        "assets": assets,
        "contracts": contracts,
        "invoices": invoices,
        "cal_certs": cal_certs,
        "communication_log": comm_logs,
    }


@router.get("/communication-logs")
def communication_logs(db: Session = Depends(get_db), limit: int = 200):
    rows = (
        db.query(CommunicationLog)
        .order_by(CommunicationLog.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for cl in rows:
        cust = db.get(Customer, cl.customer_id) if cl.customer_id else None
        out.append(
            {
                "id": cl.id,
                "customer_id": cl.customer_id,
                "customer_code": cust.code if cust else None,
                "customer_name": cust.name if cust else None,
                "occurred_at": cl.occurred_at.isoformat() if cl.occurred_at else None,
                "direction": cl.direction,
                "channel": cl.channel,
                "subject": cl.subject,
                "body_preview": (cl.body or "")[:240],
                "language": cl.language,
                "intent": cl.intent,
                "autonomy_tier": cl.autonomy_tier,
                "sent_by": cl.sent_by,
                "csr_action": cl.csr_action,
                "pipeline_id": cl.pipeline_id,
                "order_id": cl.order_id,
                "work_order_id": cl.work_order_id,
                "attachments": cl.attachments or [],
            }
        )
    return out
