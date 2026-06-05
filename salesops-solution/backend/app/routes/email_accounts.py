"""Email-account CRUD + manual refresh + SSE event stream."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..db import get_db
from ..models import EmailAccount
from ..services import email_outbound, email_sync
from ..services.imap_back_stamp import DEFAULT_FOLDER_MAP
from ..services.imap_client import PROVIDER_PRESETS, test_connection
from ..services.secrets import encrypt

router = APIRouter()


class AccountIn(BaseModel):
    provider: str = Field(default="imap")
    email_address: str
    password: str
    label: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    folder: str = "INBOX"
    username: str | None = None
    sync_interval_sec: int = 60


class TestIn(BaseModel):
    provider: str = "imap"
    email_address: str
    password: str
    imap_host: str | None = None
    imap_port: int | None = None
    folder: str = "INBOX"
    username: str | None = None


class FolderMapIn(BaseModel):
    category_folder_map: dict[str, str]


def _resolve_host(provider: str, supplied_host: str | None, supplied_port: int | None) -> tuple[str, int, str]:
    preset = PROVIDER_PRESETS.get(provider) or PROVIDER_PRESETS["imap"]
    host = (supplied_host or preset["imap_host"]).strip()
    port = int(supplied_port or preset["imap_port"])
    folder = preset["folder"]
    if not host:
        raise HTTPException(400, "imap_host is required for provider=imap")
    return host, port, folder


def _serialize(a: EmailAccount) -> dict[str, Any]:
    return {
        "id": a.id,
        "provider": a.provider,
        "email_address": a.email_address,
        "label": a.label,
        "imap_host": a.imap_host,
        "imap_port": a.imap_port,
        "folder": a.folder,
        "sync_interval_sec": a.sync_interval_sec,
        "is_active": a.is_active,
        "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
        "last_error": a.last_error,
        "last_error_at": a.last_error_at.isoformat() if a.last_error_at else None,
        "messages_imported": a.messages_imported,
        "category_folder_map": dict(a.category_folder_map or {}),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/providers")
def providers():
    return [{"key": k, **v} for k, v in PROVIDER_PRESETS.items()]


@router.get("")
def list_accounts(db: Session = Depends(get_db)):
    return [_serialize(a) for a in db.query(EmailAccount).order_by(EmailAccount.id.desc()).all()]


@router.post("/test")
def test(body: TestIn):
    host, port, folder_default = _resolve_host(body.provider, body.imap_host, body.imap_port)
    folder = body.folder or folder_default
    username = body.username or body.email_address
    ok, msg = test_connection(host, port, username, body.password, folder)
    return {"ok": ok, "message": msg, "imap_host": host, "imap_port": port, "folder": folder}


@router.post("")
def create_account(body: AccountIn, db: Session = Depends(get_db)):
    if db.query(EmailAccount).filter_by(email_address=body.email_address).first():
        raise HTTPException(409, "email_address already configured")
    host, port, folder_default = _resolve_host(body.provider, body.imap_host, body.imap_port)
    folder = body.folder or folder_default
    username = body.username or body.email_address
    ok, msg = test_connection(host, port, username, body.password, folder)
    if not ok:
        raise HTTPException(400, f"connection test failed: {msg}")

    row = EmailAccount(
        provider=body.provider,
        email_address=body.email_address,
        label=body.label,
        imap_host=host,
        imap_port=port,
        folder=folder,
        username=username,
        password_enc=encrypt(body.password),
        sync_interval_sec=max(15, int(body.sync_interval_sec or 60)),
        is_active=True,
        category_folder_map=dict(DEFAULT_FOLDER_MAP),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db)):
    row = db.get(EmailAccount, account_id)
    if not row:
        raise HTTPException(404)
    return _serialize(row)


@router.patch("/{account_id}/folder-map")
def update_folder_map(account_id: int, body: FolderMapIn, db: Session = Depends(get_db)):
    row = db.get(EmailAccount, account_id)
    if not row:
        raise HTTPException(404)
    cleaned: dict[str, str] = {}
    for category, folder in (body.category_folder_map or {}).items():
        if not isinstance(category, str) or not category.strip():
            raise HTTPException(400, "category keys must be non-empty strings")
        if not isinstance(folder, str) or not folder.strip():
            raise HTTPException(400, f"folder for {category} must be a non-empty string")
        cleaned[category.strip()] = folder.strip()
    row.category_folder_map = cleaned
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    row = db.get(EmailAccount, account_id)
    if not row:
        raise HTTPException(404)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{account_id}/toggle")
def toggle_account(account_id: int, db: Session = Depends(get_db)):
    row = db.get(EmailAccount, account_id)
    if not row:
        raise HTTPException(404)
    row.is_active = not bool(row.is_active)
    db.commit()
    return _serialize(row)


@router.post("/{account_id}/refresh")
async def refresh_account(account_id: int, db: Session = Depends(get_db)):
    row = db.get(EmailAccount, account_id)
    if not row:
        raise HTTPException(404)
    new_ids, err = await email_sync.sync_one(account_id)
    db.refresh(row)
    return {"ok": err is None, "new_email_ids": new_ids, "error": err, "account": _serialize(row)}


@router.post("/{account_id}/test-smtp")
def test_smtp(account_id: int, db: Session = Depends(get_db)):
    row = db.get(EmailAccount, account_id)
    if not row:
        raise HTTPException(404)
    ok, msg = email_outbound.test_smtp(row)
    return {"ok": ok, "message": msg}


@router.post("/refresh-all")
async def refresh_all(db: Session = Depends(get_db)):
    rows = db.query(EmailAccount).filter_by(is_active=True).all()
    results: list[dict] = []
    for row in rows:
        new_ids, err = await email_sync.sync_one(row.id)
        results.append({"account_id": row.id, "email_address": row.email_address, "new": len(new_ids), "error": err})
    return {"results": results}


@router.get("/events")
async def events():
    """SSE stream — frontend subscribes to know when new mail has landed."""
    queue = email_sync.subscribe()

    async def gen():
        try:
            yield {"event": "ping", "data": json.dumps({"type": "hello"})}
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield {"event": "message", "data": json.dumps(msg)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": json.dumps({"type": "keepalive"})}
        finally:
            email_sync.unsubscribe(queue)

    return EventSourceResponse(gen())
