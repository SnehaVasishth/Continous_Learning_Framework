"""HTTP routes for the Order Acceptance (AIOA) service.

Three surfaces:
  - Provider config: GET/POST/PATCH /api/aioa/providers
  - Queue listing:   GET /api/aioa/requests + GET /api/aioa/requests/{id}
  - Inbound callback: POST /api/aioa/callback/{provider_slug}
  - Manual replay (for testing without a real AIOA): POST /api/aioa/requests/{id}/replay
"""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AIOAProvider, AIOARequest, Pipeline
from ..services import aioa_service

router = APIRouter()


# --------------------------------------------------------------------------
# Provider config
# --------------------------------------------------------------------------


class ProviderOut(BaseModel):
    id: int
    slug: str
    name: str
    outbound_url: str
    outbound_auth_scheme: str
    timeout_seconds: int
    retry_max: int
    retry_backoff_seconds: int
    is_active: bool
    last_send_at: str | None = None
    last_callback_at: str | None = None
    callback_url: str
    has_outbound_auth_value: bool
    inbound_secret: str  # shown so operator can configure AIOA's side


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    outbound_url: str = Field(default="", max_length=500)
    outbound_auth_scheme: str = Field(default="none", pattern="^(none|bearer|api_key)$")
    outbound_auth_value: str | None = None
    timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    retry_max: int = Field(default=3, ge=0, le=20)
    retry_backoff_seconds: int = Field(default=30, ge=1, le=3600)
    is_active: bool = True


def _provider_out(p: AIOAProvider) -> dict:
    cb_url = aioa_service._build_callback_url(p)
    return {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "outbound_url": p.outbound_url,
        "outbound_auth_scheme": p.outbound_auth_scheme or "none",
        "timeout_seconds": p.timeout_seconds or 1800,
        "retry_max": p.retry_max or 3,
        "retry_backoff_seconds": p.retry_backoff_seconds or 30,
        "is_active": bool(p.is_active),
        "last_send_at": p.last_send_at.isoformat() if p.last_send_at else None,
        "last_callback_at": p.last_callback_at.isoformat() if p.last_callback_at else None,
        "callback_url": cb_url,
        "callback_url_configured": bool(cb_url),
        "has_outbound_auth_value": bool(p.outbound_auth_value),
        "inbound_secret": p.inbound_secret or "",
    }


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)) -> list[dict]:
    # Ensure at least one row exists so the UI has something to show.
    aioa_service.ensure_default_provider(db)
    rows = db.query(AIOAProvider).order_by(AIOAProvider.id.asc()).all()
    return [_provider_out(p) for p in rows]


@router.get("/providers/{provider_id}")
def get_provider(provider_id: int, db: Session = Depends(get_db)) -> dict:
    p = db.query(AIOAProvider).filter(AIOAProvider.id == provider_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _provider_out(p)


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderIn, db: Session = Depends(get_db)) -> dict:
    p = db.query(AIOAProvider).filter(AIOAProvider.id == provider_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    p.name = body.name
    p.outbound_url = body.outbound_url
    p.outbound_auth_scheme = body.outbound_auth_scheme
    if body.outbound_auth_value is not None and body.outbound_auth_value != "":
        p.outbound_auth_value = body.outbound_auth_value
    p.timeout_seconds = body.timeout_seconds
    p.retry_max = body.retry_max
    p.retry_backoff_seconds = body.retry_backoff_seconds
    p.is_active = body.is_active
    db.commit()
    db.refresh(p)
    return _provider_out(p)


class TestProbeIn(BaseModel):
    outbound_url: str | None = None


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, body: TestProbeIn | None = None, db: Session = Depends(get_db)) -> dict:
    """Send a small probe POST to the configured outbound URL to confirm
    it accepts requests. Does not create an AIOARequest row."""
    import httpx

    p = db.query(AIOAProvider).filter(AIOAProvider.id == provider_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    url = (body.outbound_url if body and body.outbound_url else p.outbound_url) or p.outbound_url
    headers = {"Content-Type": "application/json"}
    if p.outbound_auth_scheme == "bearer" and p.outbound_auth_value:
        headers["Authorization"] = f"Bearer {p.outbound_auth_value}"
    elif p.outbound_auth_scheme == "api_key" and p.outbound_auth_value:
        headers["X-API-Key"] = p.outbound_auth_value
    payload = {"probe": True, "from": "ZBrain SalesOps", "callback_url": aioa_service._build_callback_url(p)}
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(url, headers=headers, json=payload)
        return {"ok": 200 <= r.status_code < 300, "http_status": r.status_code, "body_preview": (r.text or "")[:300]}
    except Exception as ex:
        return {"ok": False, "http_status": 0, "error": f"{type(ex).__name__}: {str(ex)[:200]}"}


# --------------------------------------------------------------------------
# Queue listing
# --------------------------------------------------------------------------


def _request_out(r: AIOARequest, provider: AIOAProvider | None = None, *, with_payloads: bool = False) -> dict:
    # Collapse legacy 'error' status to 'pending_send' for UI; the queue
    # surfaces only waiting / sent / response_received / processed / timed_out.
    display_status = r.status if r.status != "error" else "pending_send"
    out = {
        "id": r.id,
        "correlation_id": r.correlation_id,
        "pipeline_id": r.pipeline_id,
        "provider_id": r.provider_id,
        "provider_name": provider.name if provider else None,
        "status": display_status,
        "decision": r.decision,
        "fallout_reasons": r.fallout_reasons or [],
        "retry_count": r.retry_count or 0,
        "last_error": None,  # internal diagnostic, not surfaced
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "response_received_at": r.response_received_at.isoformat() if r.response_received_at else None,
        "processed_at": r.processed_at.isoformat() if r.processed_at else None,
        "csr_draft_subject": (r.csr_draft or {}).get("subject"),
    }
    if with_payloads:
        out["request_payload"] = r.request_payload or {}
        out["response_payload"] = r.response_payload or {}
        out["csr_draft"] = r.csr_draft or {}
    return out


@router.get("/requests")
def list_requests(
    status: str | None = None,
    pipeline_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(AIOARequest)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        q = q.filter(AIOARequest.status.in_(statuses))
    if pipeline_id is not None:
        q = q.filter(AIOARequest.pipeline_id == pipeline_id)
    rows = q.order_by(desc(AIOARequest.id)).limit(max(1, min(limit, 500))).all()
    # batch-fetch providers
    pids = {r.provider_id for r in rows if r.provider_id is not None}
    pmap: dict[int, AIOAProvider] = {}
    if pids:
        for p in db.query(AIOAProvider).filter(AIOAProvider.id.in_(pids)).all():
            pmap[p.id] = p
    counts_q = db.query(AIOARequest.status, AIOARequest.id).all()
    counts: dict[str, int] = {}
    for s, _id in counts_q:
        counts[s] = counts.get(s, 0) + 1
    return {
        "items": [_request_out(r, pmap.get(r.provider_id)) for r in rows],
        "counts_by_status": counts,
    }


@router.get("/requests/{req_id}")
def get_request(req_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.query(AIOARequest).filter(AIOARequest.id == req_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found")
    p = db.query(AIOAProvider).filter(AIOAProvider.id == r.provider_id).first() if r.provider_id else None
    return _request_out(r, p, with_payloads=True)


# --------------------------------------------------------------------------
# Inbound callback (the URL AIOA POSTs back to)
# --------------------------------------------------------------------------


@router.post("/callback/{provider_slug}")
async def aioa_callback(provider_slug: str, request: Request, db: Session = Depends(get_db)) -> dict:
    body = await request.json()
    # Optional signature verification — the provider's inbound_secret is
    # sent by AIOA in the X-AIOA-Signature header (raw shared secret). We
    # accept either the header match OR a secret in the body for flexibility.
    p = db.query(AIOAProvider).filter(AIOAProvider.slug == provider_slug).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Unknown AIOA provider slug")
    presented = request.headers.get("x-aioa-signature") or request.headers.get("X-AIOA-Signature") or (body or {}).get("secret") or ""
    if p.inbound_secret and not hmac.compare_digest(presented, p.inbound_secret):
        raise HTTPException(status_code=401, detail="Invalid AIOA callback secret")
    try:
        req = aioa_service.receive_callback(db, provider_slug=provider_slug, body=body, headers=dict(request.headers))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"ok": True, "correlation_id": req.correlation_id, "status": req.status}


# --------------------------------------------------------------------------
# Manual replay — useful while the AIOA side isn't wired
# --------------------------------------------------------------------------


class ReplayIn(BaseModel):
    decision: str = Field(pattern="^(PASS|FAIL)$")
    fallout_reasons: list[Any] = Field(default_factory=list)
    evidence: dict | None = None


@router.post("/requests/{req_id}/replay")
def replay(req_id: int, body: ReplayIn, db: Session = Depends(get_db)) -> dict:
    """Operator-driven replay — synthesize a callback for this request so
    the rest of the flow runs without AIOA needing to be wired. Useful for
    QA and live demos."""
    r = db.query(AIOARequest).filter(AIOARequest.id == req_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if r.status not in ("sent", "pending_send", "timed_out", "error"):
        raise HTTPException(status_code=409, detail=f"Cannot replay a request in status '{r.status}'")
    p = db.query(AIOAProvider).filter(AIOAProvider.id == r.provider_id).first() if r.provider_id else None
    fake_body = {
        "correlation_id": r.correlation_id,
        "decision": body.decision,
        "fallout_reasons": body.fallout_reasons,
        "evidence": body.evidence or {},
        "source": "operator_replay",
    }
    try:
        req = aioa_service.receive_callback(
            db,
            provider_slug=(p.slug if p else "default"),
            body=fake_body,
            headers={},
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"ok": True, "correlation_id": req.correlation_id, "status": req.status}


# --------------------------------------------------------------------------
# Resend — push a `sent` row back to `pending_send` so the sender retries.
# --------------------------------------------------------------------------


@router.post("/requests/{req_id}/resend")
def resend(req_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.query(AIOARequest).filter(AIOARequest.id == req_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if r.status in ("processed",):
        raise HTTPException(status_code=409, detail="Already processed — open a new pipeline if you need to re-validate")
    r.status = "pending_send"
    r.retry_count = 0
    r.last_error = None
    db.commit()
    return {"ok": True, "correlation_id": r.correlation_id, "status": r.status}
