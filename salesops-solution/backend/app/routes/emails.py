from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, Email, Pipeline

router = APIRouter()

# Single source of truth for the statuses surfaced in the Inbox dropdown.
# Keep this aligned with what orchestrator.py / hitl.py write to Email.status.
KNOWN_STATUSES = [
    "new", "processing", "awaiting_hitl", "processed", "discarded", "rejected",
    "redirected",  # === v1.1 TASK-1 === redirect short-circuit (KSO/COLLECTIONS/PORTAL_ADMIN/BRAZIL_TAX)
]

# Stale-mail status applied by app.services.email_sweeper when an email sits
# in 'new' past the stale-age threshold without ever starting a pipeline.
# These rows stay in the DB for audit but are completely hidden from the
# platform UI: list endpoints exclude them, count endpoints exclude them,
# the Inbox filter dropdown does not offer them. Operators who need the
# audit trail can still find these via direct DB inspection.
_HIDDEN_STATUSES = ("expired_unworkable",)


def _latest_pipeline_subquery(db: Session):
    """Latest Pipeline per Email, addressed by Pipeline.email_id (which is reliably set).

    The Email.pipeline_id back-pointer is only populated by some orchestrator paths,
    so we can't depend on it for filtering or display.
    """
    return (
        db.query(Pipeline.email_id.label("email_id"), func.max(Pipeline.id).label("pipeline_id"))
        .filter(Pipeline.email_id.isnot(None))
        .group_by(Pipeline.email_id)
        .subquery()
    )


@router.get("")
def list_emails(
    status: str | None = None,
    intent: str | None = None,
    language: str | None = None,
    autonomy_tier: str | None = None,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List inbox emails. Supports cursor-style paging via `offset` + `limit`.

    The Inbox surface fetches the entire active window by default (limit=500),
    matching the current corpus footprint of ~219 rows. Operators or callers
    that need to scroll deeper can advance `offset` in pages of `limit`.
    """
    q = db.query(Email).order_by(Email.received_at.desc())
    if status:
        q = q.filter(Email.status == status)
    else:
        q = q.filter(~Email.status.in_(_HIDDEN_STATUSES))
    if language:
        q = q.filter(Email.language_hint == language)
    if intent or autonomy_tier:
        latest = _latest_pipeline_subquery(db)
        q = (
            q.join(latest, latest.c.email_id == Email.id)
            .join(Pipeline, Pipeline.id == latest.c.pipeline_id)
        )
        if intent:
            q = q.filter(Pipeline.intent == intent)
        if autonomy_tier:
            q = q.filter(Pipeline.autonomy_tier == autonomy_tier)
    rows = q.offset(offset).limit(limit).all()
    latest_pipes = _build_latest_pipe_map(db, [e.id for e in rows])
    return [_email_summary(db, e, latest_pipes.get(e.id)) for e in rows]


@router.get("/counts")
def status_counts(db: Session = Depends(get_db)):
    """Per-status counts so the Inbox dropdown can show 'Processed (0)' etc.

    Anything that drifts off KNOWN_STATUSES still appears under its own key,
    so a typo in upstream status writes is visible rather than silent.
    """
    raw = dict(db.query(Email.status, func.count(Email.id)).group_by(Email.status).all())
    # Drop hidden statuses (e.g. expired_unworkable) from per-status keys and
    # the "all" rollup so the Inbox dropdown matches what list_emails returns.
    for hidden in _HIDDEN_STATUSES:
        raw.pop(hidden, None)
    out = {s: int(raw.get(s, 0)) for s in KNOWN_STATUSES}
    for s, c in raw.items():
        if s not in out:
            out[s] = int(c)
    out["all"] = int(sum(raw.values()))
    return out


@router.get("/{email_id}")
def get_email(email_id: int, db: Session = Depends(get_db)):
    e = db.get(Email, email_id)
    if not e:
        raise HTTPException(404)
    cust = db.get(Customer, e.customer_id) if e.customer_id else None
    pipe = _latest_pipeline_for(db, e.id)

    # Assemble the full thread chain so the inbox detail view can render the
    # whole conversation, not just this single message. When the email isn't
    # part of a thread, the chain is just [e] and the UI hides the thread block.
    from ..services.email_thread import walk_thread, normalize_subject
    chain = walk_thread(db, e)
    thread_payload = None
    if chain:
        root = chain[0]
        thread_payload = {
            "thread_root_message_id": root.message_id,
            "thread_normalized_subject": normalize_subject(root.subject),
            "message_count": len(chain),
            "messages": [
                {
                    "id": m.id,
                    "is_root": m.id == root.id,
                    "is_self": m.id == e.id,
                    "position": idx + 1,
                    "from": m.from_address,
                    "subject": m.subject,
                    "received_at": m.received_at.isoformat() if m.received_at else None,
                    "body": m.body or "",
                    "attachments": m.attachments or [],
                    "language_hint": m.language_hint,
                    "pipeline_id": m.pipeline_id,
                }
                for idx, m in enumerate(chain)
            ],
        }

    return {
        "id": e.id,
        "received_at": e.received_at.isoformat() if e.received_at else None,
        "from": e.from_address,
        "subject": e.subject,
        "body": e.body,
        "language_hint": e.language_hint,
        "attachments": e.attachments or [],
        "status": e.status,
        "customer": _cust_summary(cust),
        "pipeline_id": pipe.id if pipe else None,
        "thread": thread_payload,
    }


def _build_latest_pipe_map(db: Session, email_ids: list[int]) -> dict[int, Pipeline]:
    if not email_ids:
        return {}
    rows = (
        db.query(Pipeline.email_id, func.max(Pipeline.id).label("pipeline_id"))
        .filter(Pipeline.email_id.in_(email_ids))
        .group_by(Pipeline.email_id)
        .all()
    )
    if not rows:
        return {}
    pipe_ids = [r.pipeline_id for r in rows]
    pipes = {p.id: p for p in db.query(Pipeline).filter(Pipeline.id.in_(pipe_ids)).all()}
    return {r.email_id: pipes[r.pipeline_id] for r in rows if r.pipeline_id in pipes}


def _latest_pipeline_for(db: Session, email_id: int) -> Pipeline | None:
    return (
        db.query(Pipeline)
        .filter(Pipeline.email_id == email_id)
        .order_by(Pipeline.id.desc())
        .first()
    )


def _email_summary(db: Session, e: Email, pipe: Pipeline | None) -> dict:
    cust = db.get(Customer, e.customer_id) if e.customer_id else None
    return {
        "id": e.id,
        "received_at": e.received_at.isoformat() if e.received_at else None,
        "from": e.from_address,
        "subject": e.subject,
        "language_hint": e.language_hint,
        "attachments": [a.get("name") for a in (e.attachments or [])],
        "status": e.status,
        "customer_name": cust.name if cust else None,
        "pipeline": _pipe_summary(pipe),
    }


def _cust_summary(c: Customer | None) -> dict | None:
    if not c:
        return None
    return {"id": c.id, "code": c.code, "name": c.name, "region": c.region, "language": c.language}


def _pipe_summary(p: Pipeline | None) -> dict | None:
    if not p:
        return None
    return {
        "id": p.id,
        "status": p.status,
        "intent": p.intent,
        "language": p.language,
        "confidence": p.confidence,
        "autonomy_tier": p.autonomy_tier,
    }
