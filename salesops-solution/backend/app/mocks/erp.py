"""Mock ERP — order, hold, delivery, work-order operations against SQLite."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Order, Quote, WorkOrder


def create_order_from_quote(db: Session, *, quote_id: int) -> Order:
    q = db.get(Quote, quote_id)
    if not q:
        raise ValueError("quote not found")
    # Idempotency: if an Order was already created for this quote, return it
    # instead of inserting a duplicate. Prevents UNIQUE-constraint violations
    # when the same email is re-processed (test runs, demo re-runs, retries).
    existing = db.query(Order).filter(Order.quote_id == q.id).first()
    if existing is not None:
        return existing
    o = Order(
        order_number=f"SO-{q.quote_number.replace('Q-', '')}-{random.randint(1000,9999)}",
        quote_id=q.id,
        customer_id=q.customer_id,
        status="open",
        requested_ship_date=datetime.now(timezone.utc) + timedelta(days=14),
        total=q.total,
        line_items=q.line_items,
    )
    q.status = "converted"
    db.add(o)
    db.flush()
    return o


def release_hold(db: Session, *, order_number: str) -> Order:
    o = db.query(Order).filter(Order.order_number == order_number).first()
    if not o:
        raise ValueError("order not found")
    o.status = "open"
    o.hold_reason = None
    db.flush()
    return o


def reschedule_order(db: Session, *, order_number: str, new_ship_date: datetime) -> Order:
    o = db.query(Order).filter(Order.order_number == order_number).first()
    if not o:
        raise ValueError("order not found")
    o.requested_ship_date = new_ship_date
    db.flush()
    return o


def create_work_order(
    db: Session,
    *,
    customer_id: int,
    asset_serial: str,
    type_: str,
    region: str,
) -> WorkOrder:
    wo = WorkOrder(
        wo_number=f"WO-{customer_id}-{random.randint(10000,99999)}",
        customer_id=customer_id,
        asset_serial=asset_serial,
        type=type_,
        status="scheduled",
        region=region,
        assigned_team=f"{region}-Field-{random.randint(1,3)}",
    )
    db.add(wo)
    db.flush()
    return wo


def list_open_work_orders(db: Session, *, customer_id: int) -> list[WorkOrder]:
    return (
        db.query(WorkOrder)
        .filter(WorkOrder.customer_id == customer_id)
        .filter(WorkOrder.status != "closed")
        .all()
    )
