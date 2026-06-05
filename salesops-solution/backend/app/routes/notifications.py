"""Notifications feed — single API surface for any operator-visible alert.

The frontend bell calls `GET /api/notifications` every few seconds and renders
the rows. Marking read, dismissing, and bulk mark-all-read are the only state
changes the operator can perform; resolving happens automatically when the
underlying condition heals (each publisher resolves its own kind)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import notifications as svc

router = APIRouter()


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    include_resolved: bool = False,
    include_dismissed: bool = False,
    limit: int = 50,
):
    """Return the operator-visible notification feed plus a summary block.

    The bell uses `summary.unread_total` for the badge count and shows the
    full `items` list when opened. Resolved + dismissed rows are excluded by
    default; pass `?include_resolved=true` to fetch the history view."""
    # Trigger a readiness check so connection notifications are kept fresh
    # without the frontend having to poll a separate endpoint. Side-effect:
    # publish/resolve notifications as needed before we list them.
    try:
        from ..services.readiness import check_readiness
        check_readiness(db)
    except Exception:
        pass
    rows = svc.list_active(
        db,
        limit=limit,
        include_resolved=include_resolved,
        include_dismissed=include_dismissed,
    )
    return {
        "items": [svc.serialize(r) for r in rows],
        "summary": svc.summary(db),
    }


@router.post("/{notification_id}/read")
def post_read(notification_id: int, db: Session = Depends(get_db)):
    row = svc.mark_read(db, notification_id=notification_id)
    if row is None:
        raise HTTPException(404)
    return svc.serialize(row)


@router.post("/{notification_id}/dismiss")
def post_dismiss(notification_id: int, db: Session = Depends(get_db)):
    row = svc.dismiss(db, notification_id=notification_id)
    if row is None:
        raise HTTPException(404)
    return svc.serialize(row)


@router.post("/mark-all-read")
def post_mark_all_read(db: Session = Depends(get_db)):
    n = svc.mark_all_read(db)
    return {"marked_read": n}
