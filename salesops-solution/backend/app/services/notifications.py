"""Notifications — single feed any subsystem can publish to.

Every operator-facing alert (connection monitor, HITL backlog, AIOA fallout,
pipeline errors, drift, etc.) becomes a Notification row through this module.
The UI consumes one endpoint (`/api/notifications`) and never knows which
producer made the row.

API:
  publish(db, *, kind, category, severity, title, body=..., action_url=...,
          action_label=..., meta=...) -> Notification
        Upsert by `kind`. If an active (un-resolved) row with the same kind
        exists, it is updated (so we don't spam the feed on every poll).
        Otherwise a new row is created.

  resolve(db, *, kind)
        Mark every active row with this kind as resolved. Used by publishers
        when the underlying condition heals (e.g., Salesforce reconnects).

  list_active(db, *, limit=50, include_resolved=False)
        Read the feed for the UI. Sorted newest-first.

  mark_read(db, *, notification_id)        — set read_at
  dismiss(db, *, notification_id)          — set dismissed_at
  mark_all_read(db)                        — set read_at on every undismissed unread row
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..models import Notification


_VALID_CATEGORIES = {"connection", "queue", "workflow", "drift", "system", "learning"}
_VALID_SEVERITIES = {"critical", "warning", "info"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def publish(
    db: Session,
    *,
    kind: str,
    category: str,
    severity: str,
    title: str,
    body: str | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Notification:
    """Publish (or update) a notification. Upsert semantics on `kind`.

    Returns the persisted row. Callers should pass a stable `kind` per
    condition (e.g., "salesforce_disconnected", "hitl_backlog_high") so
    polling publishers don't spam the feed."""
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    if severity not in _VALID_SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}")
    # Upsert on `kind`. We look at the most recent non-resolved row; if it's
    # already dismissed or read, we LEAVE those operator states alone. The
    # publisher should call `resolve(kind=...)` when the condition heals;
    # silent re-publishing of the same condition must not reset operator-
    # managed flags or the bell will never stay clear under steady-state
    # polling.
    existing = (
        db.query(Notification)
        .filter(Notification.kind == kind)
        .filter(Notification.resolved_at.is_(None))
        .order_by(desc(Notification.id))
        .first()
    )
    if existing is not None:
        # Detect a genuine content change (severity escalated, title or body
        # changed). Only then do we surface it again by clearing the
        # dismissal; an identical re-publish stays silent.
        content_changed = (
            (existing.severity or "") != severity
            or (existing.title or "") != title
            or (existing.body or "") != (body or "")
        )
        existing.category = category
        existing.severity = severity
        existing.title = title
        existing.body = body
        existing.action_url = action_url
        existing.action_label = action_label
        existing.meta = meta or {}
        if content_changed:
            existing.dismissed_at = None
            existing.read_at = None
        existing.updated_at = _now_utc()
        db.commit()
        db.refresh(existing)
        return existing
    row = Notification(
        kind=kind,
        category=category,
        severity=severity,
        title=title,
        body=body,
        action_url=action_url,
        action_label=action_label,
        meta=meta or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve(db: Session, *, kind: str) -> int:
    """Mark every active row for `kind` as resolved. Returns count resolved."""
    rows = (
        db.query(Notification)
        .filter(Notification.kind == kind)
        .filter(Notification.resolved_at.is_(None))
        .all()
    )
    now = _now_utc()
    for r in rows:
        r.resolved_at = now
        r.updated_at = now
    if rows:
        db.commit()
    return len(rows)


def list_active(
    db: Session,
    *,
    limit: int = 50,
    include_resolved: bool = False,
    include_dismissed: bool = False,
) -> list[Notification]:
    """Return the operator-visible feed, newest first.

    HITL queue items are excluded from the notification feed because the navbar
    already exposes the live HITL queue depth as a numeric badge — re-listing
    each pending HITL task as a notification is redundant noise. System health
    notifications (connection blockers, workflow halts, drift, learning
    signals) remain in the feed."""
    q = db.query(Notification)
    if not include_resolved:
        q = q.filter(Notification.resolved_at.is_(None))
    if not include_dismissed:
        q = q.filter(Notification.dismissed_at.is_(None))
    q = q.filter(Notification.category != "queue")
    return q.order_by(desc(Notification.created_at)).limit(limit).all()


def mark_read(db: Session, *, notification_id: int) -> Notification | None:
    row = db.get(Notification, notification_id)
    if row is None:
        return None
    if row.read_at is None:
        row.read_at = _now_utc()
        row.updated_at = _now_utc()
        db.commit()
        db.refresh(row)
    return row


def dismiss(db: Session, *, notification_id: int) -> Notification | None:
    row = db.get(Notification, notification_id)
    if row is None:
        return None
    if row.dismissed_at is None:
        row.dismissed_at = _now_utc()
        row.updated_at = _now_utc()
        db.commit()
        db.refresh(row)
    return row


def mark_all_read(db: Session) -> int:
    rows = (
        db.query(Notification)
        .filter(Notification.read_at.is_(None))
        .filter(Notification.dismissed_at.is_(None))
        .filter(Notification.resolved_at.is_(None))
        .all()
    )
    now = _now_utc()
    for r in rows:
        r.read_at = now
        r.updated_at = now
    if rows:
        db.commit()
    return len(rows)


def serialize(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "category": row.category,
        "severity": row.severity,
        "title": row.title,
        "body": row.body,
        "action_url": row.action_url,
        "action_label": row.action_label,
        "meta": row.meta or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "dismissed_at": row.dismissed_at.isoformat() if row.dismissed_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def summary(db: Session) -> dict[str, int]:
    """Counts the UI bell uses for the badge.

    HITL queue items are excluded to match the feed (navbar surfaces those
    separately) so the bell badge reflects system-health notifications only."""
    active = (
        db.query(Notification)
        .filter(Notification.resolved_at.is_(None))
        .filter(Notification.dismissed_at.is_(None))
        .filter(Notification.category != "queue")
        .all()
    )
    by_sev = {"critical": 0, "warning": 0, "info": 0}
    unread = 0
    for r in active:
        if r.severity in by_sev:
            by_sev[r.severity] += 1
        if r.read_at is None:
            unread += 1
    return {
        "active_total": len(active),
        "unread_total": unread,
        "by_severity": by_sev,
    }
