"""Integration management — Salesforce / ServiceNow / SharePoint connect + status.

Each integration has the same shape:
- POST /test  → validate credentials, return ok/err + diagnostic info
- POST /connect → save (replace) the active connection
- GET /status → return whether currently connected + last test timestamp + org info
- DELETE /disconnect → mark inactive (keeps row for audit)
"""
from __future__ import annotations

import mimetypes
import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import salesforce as sf_svc
from ..services import servicenow as sn_svc
from ..services import sharepoint as sp_svc

router = APIRouter()


# ---------- Salesforce ----------


class SalesforceCredentials(BaseModel):
    instance_url: str
    consumer_key: str
    consumer_secret: str
    flow: str = Field(default="client_credentials")
    username: str | None = None
    password: str | None = None
    security_token: str | None = None
    domain: str = Field(default="login")
    api_version: str = Field(default="60.0")
    label: str = Field(default="Production org")


@router.post("/salesforce/test")
def salesforce_test(body: SalesforceCredentials):
    ok, msg, info = sf_svc.test_connection(
        instance_url=body.instance_url,
        consumer_key=body.consumer_key,
        consumer_secret=body.consumer_secret,
        flow=body.flow,
        username=body.username,
        password=body.password,
        security_token=body.security_token,
        domain=body.domain,
        api_version=body.api_version,
    )
    return {"ok": ok, "message": msg, "whoami": info}


@router.post("/salesforce/connect")
def salesforce_connect(body: SalesforceCredentials, db: Session = Depends(get_db)):
    try:
        row = sf_svc.upsert_connection(
            db,
            instance_url=body.instance_url,
            consumer_key=body.consumer_key,
            consumer_secret=body.consumer_secret,
            flow=body.flow,
            username=body.username,
            password=body.password,
            security_token=body.security_token,
            domain=body.domain,
            api_version=body.api_version,
            label=body.label,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")
    return sf_svc.serialize(row)


@router.get("/salesforce/status")
def salesforce_status(db: Session = Depends(get_db)):
    conn = sf_svc.get_active_connection(db)
    if not conn:
        return {"connected": False}
    return {"connected": True, **sf_svc.serialize(conn)}


@router.post("/salesforce/refresh")
def salesforce_refresh(db: Session = Depends(get_db)):
    conn = sf_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    conn = sf_svc.refresh_status(db, conn)
    return sf_svc.serialize(conn)


@router.delete("/salesforce/disconnect")
def salesforce_disconnect(db: Session = Depends(get_db)):
    conn = sf_svc.get_active_connection(db)
    if not conn:
        return {"ok": True, "message": "no connection"}
    conn.is_active = False
    db.commit()
    return {"ok": True}


# --- Salesforce case-owner queues (provision + sync) ----------------------


class OwnerProvisionBody(BaseModel):
    only_keys: list[str] | None = None  # if set, restrict to these owner_queue keys


@router.post("/salesforce/owners/provision")
def salesforce_owners_provision(body: OwnerProvisionBody, db: Session = Depends(get_db)):
    """Create missing SF Queues for every owner_mapping KB row.

    Idempotent — re-running adopts existing queues by DeveloperName rather
    than creating duplicates. Returns counts of created / skipped / errored.
    """
    conn = sf_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(412, "no active Salesforce connection")
    from ..services import salesforce_queues as sfq
    try:
        result = sfq.provision_owner_queues(db, conn, only_keys=body.only_keys)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")
    return result


@router.post("/salesforce/owners/sync")
def salesforce_owners_sync(db: Session = Depends(get_db)):
    """Sync KB owner_mapping rows from live SF queues. Pulls every
    Case-eligible Queue and updates queue_id / queue_label / last_synced_at
    where the DeveloperName matches."""
    conn = sf_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(412, "no active Salesforce connection")
    from ..services import salesforce_queues as sfq
    try:
        return sfq.sync_owner_queues(db, conn)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")


@router.get("/salesforce/details")
def salesforce_details(db: Session = Depends(get_db)):
    """Read-only dashboard data for the Salesforce settings view: queues
    we created, users assigned to each queue, account / case / order
    headline counts, and direct deep-links into SF for every record.

    Single SOQL round-trip per resource. Results are unwrapped to a small,
    UI-friendly shape so the front-end has nothing to compute."""
    conn = sf_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(412, "no active Salesforce connection")
    try:
        sf = sf_svc.client_for(conn)
        instance = (conn.instance_url or "").rstrip("/")
        if instance and not instance.startswith(("http://", "https://")):
            instance = "https://" + instance

        def _url(record_id: str | None) -> str | None:
            if not record_id:
                return None
            return f"{instance}/lightning/r/{record_id}/view" if instance else None

        # Queues with members. Restrict to ZBrain-named queues so we don't
        # leak unrelated SF org content.
        q_rows = sf.query_all(
            "SELECT Id, Name, DeveloperName FROM Group "
            "WHERE Type='Queue' AND DeveloperName LIKE 'ZBrain_%' ORDER BY Name"
        )
        queue_ids = [q["Id"] for q in q_rows["records"]]
        members_by_queue: dict[str, list[dict]] = {qid: [] for qid in queue_ids}
        if queue_ids:
            quoted = ",".join(f"'{qid}'" for qid in queue_ids)
            mres = sf.query_all(
                f"SELECT Id, GroupId, UserOrGroupId FROM GroupMember WHERE GroupId IN ({quoted})"
            )
            user_ids = sorted({m["UserOrGroupId"] for m in mres["records"]})
            user_map: dict[str, dict] = {}
            if user_ids:
                uquoted = ",".join(f"'{uid}'" for uid in user_ids)
                ures = sf.query_all(
                    "SELECT Id, Name, FirstName, LastName, Username, Email, IsActive "
                    f"FROM User WHERE Id IN ({uquoted})"
                )
                for u in ures["records"]:
                    user_map[u["Id"]] = {
                        "id": u["Id"],
                        "name": u["Name"],
                        "first_name": u.get("FirstName"),
                        "last_name": u.get("LastName"),
                        "username": u["Username"],
                        "email": u.get("Email"),
                        "is_active": bool(u.get("IsActive")),
                        "profile_url": _url(u["Id"]),
                    }
            for m in mres["records"]:
                uid = m["UserOrGroupId"]
                if uid in user_map:
                    members_by_queue.setdefault(m["GroupId"], []).append(user_map[uid])

        queues = [
            {
                "id": q["Id"],
                "name": q["Name"],
                "developer_name": q["DeveloperName"],
                "queue_url": _url(q["Id"]),
                "members": members_by_queue.get(q["Id"], []),
                "member_count": len(members_by_queue.get(q["Id"], [])),
            }
            for q in q_rows["records"]
        ]

        # Headline counts.
        def _count(soql: str) -> int:
            try:
                r = sf.query(soql)
                return int(r.get("totalSize") or 0)
            except Exception:
                return 0

        counts = {
            "accounts": _count("SELECT Id FROM Account"),
            "cases_open": _count("SELECT Id FROM Case WHERE IsClosed = false"),
            "cases_total": _count("SELECT Id FROM Case"),
            "orders": _count("SELECT Id FROM Order"),
            "work_orders": _count("SELECT Id FROM WorkOrder"),
            "service_contracts": _count("SELECT Id FROM ServiceContract"),
        }

        # Recent records, limited to keep payload tight.
        recent_cases_q = sf.query_all(
            "SELECT Id, CaseNumber, Subject, Status, CreatedDate, Account.Name "
            "FROM Case ORDER BY CreatedDate DESC LIMIT 10"
        )
        recent_cases = [
            {
                "id": c["Id"],
                "case_number": c["CaseNumber"],
                "subject": c.get("Subject"),
                "status": c.get("Status"),
                "created_at": c.get("CreatedDate"),
                "account_name": (c.get("Account") or {}).get("Name") if c.get("Account") else None,
                "url": _url(c["Id"]),
            }
            for c in recent_cases_q["records"]
        ]
        recent_accounts_q = sf.query_all(
            "SELECT Id, Name, Industry, CreatedDate FROM Account ORDER BY CreatedDate DESC LIMIT 10"
        )
        recent_accounts = [
            {
                "id": a["Id"],
                "name": a.get("Name"),
                "industry": a.get("Industry"),
                "created_at": a.get("CreatedDate"),
                "url": _url(a["Id"]),
            }
            for a in recent_accounts_q["records"]
        ]

        return {
            "instance_url": instance,
            "org_name": conn.org_name,
            "queues": queues,
            "counts": counts,
            "recent_cases": recent_cases,
            "recent_accounts": recent_accounts,
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")


# ---------- ServiceNow ----------


class ServiceNowCredentials(BaseModel):
    instance_url: str
    username: str
    password: str
    case_table: str = Field(default="incident")
    label: str = Field(default="Production instance")


@router.post("/servicenow/test")
def servicenow_test(body: ServiceNowCredentials):
    ok, msg, info = sn_svc.test_connection(
        instance_url=body.instance_url,
        username=body.username,
        password=body.password,
        case_table=body.case_table,
    )
    return {"ok": ok, "message": msg, "whoami": info}


@router.post("/servicenow/connect")
def servicenow_connect(body: ServiceNowCredentials, db: Session = Depends(get_db)):
    try:
        row = sn_svc.upsert_connection(
            db,
            instance_url=body.instance_url,
            username=body.username,
            password=body.password,
            case_table=body.case_table,
            label=body.label,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")
    return sn_svc.serialize(row)


@router.get("/servicenow/status")
def servicenow_status(db: Session = Depends(get_db)):
    conn = sn_svc.get_active_connection(db)
    if not conn:
        return {"connected": False}
    return {"connected": True, **sn_svc.serialize(conn)}


@router.post("/servicenow/refresh")
def servicenow_refresh(db: Session = Depends(get_db)):
    conn = sn_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    conn = sn_svc.refresh_status(db, conn)
    return sn_svc.serialize(conn)


@router.delete("/servicenow/disconnect")
def servicenow_disconnect(db: Session = Depends(get_db)):
    conn = sn_svc.get_active_connection(db)
    if not conn:
        return {"ok": True, "message": "no connection"}
    conn.is_active = False
    db.commit()
    return {"ok": True}


# ---------- SharePoint ----------


class SharePointCredentials(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str
    site_id: str
    drive_id: str | None = None
    folder_path: str = Field(default="/")
    label: str = Field(default="Production site")


class SharePointUpdate(BaseModel):
    folder_path: str | None = None
    drive_id: str | None = None
    label: str | None = None


@router.post("/sharepoint/test")
def sharepoint_test(body: SharePointCredentials):
    ok, msg, info = sp_svc.test_connection(
        tenant_id=body.tenant_id,
        client_id=body.client_id,
        client_secret=body.client_secret,
        site_id=body.site_id,
        drive_id=body.drive_id,
        folder_path=body.folder_path,
    )
    return {"ok": ok, "message": msg, "whoami": info}


@router.post("/sharepoint/connect")
def sharepoint_connect(body: SharePointCredentials, db: Session = Depends(get_db)):
    try:
        row = sp_svc.upsert_connection(
            db,
            tenant_id=body.tenant_id,
            client_id=body.client_id,
            client_secret=body.client_secret,
            site_id=body.site_id,
            drive_id=body.drive_id,
            folder_path=body.folder_path,
            label=body.label,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")
    return sp_svc.serialize(row)


@router.get("/sharepoint/status")
def sharepoint_status(db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        return {"connected": False}
    return {"connected": True, **sp_svc.serialize(conn)}


@router.post("/sharepoint/refresh")
def sharepoint_refresh(db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    conn = sp_svc.refresh_status(db, conn)
    return sp_svc.serialize(conn)


@router.delete("/sharepoint/disconnect")
def sharepoint_disconnect(db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        return {"ok": True, "message": "no connection"}
    conn.is_active = False
    db.commit()
    return {"ok": True}


@router.patch("/sharepoint/settings")
def sharepoint_settings(body: SharePointUpdate, db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    if body.folder_path is not None:
        conn.folder_path = body.folder_path
    if body.drive_id is not None:
        conn.drive_id = body.drive_id or None
    if body.label is not None:
        conn.label = body.label
    db.commit()
    db.refresh(conn)
    sp_svc.refresh_status(db, conn)
    return sp_svc.serialize(conn)


@router.get("/sharepoint/files")
def sharepoint_list(subfolder: str | None = None, db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    try:
        items = sp_svc.list_files(conn, subfolder=subfolder)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"folder": conn.folder_path, "subfolder": subfolder, "items": items, "count": len(items)}


@router.post("/sharepoint/files/upload")
def sharepoint_upload(
    file: UploadFile = File(...),
    subfolder: str | None = None,
    db: Session = Depends(get_db),
):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    content = file.file.read()
    ctype = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    try:
        result = sp_svc.upload_file(
            conn,
            name=file.filename or "upload.bin",
            content=content,
            content_type=ctype,
            subfolder=subfolder,
            overwrite=True,
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return result


@router.get("/sharepoint/files/{item_id}/download")
def sharepoint_download(item_id: str, db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    try:
        data, name, mime = sp_svc.download_file(conn, item_id=item_id)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    headers = {"Content-Disposition": f'attachment; filename="{name or item_id}"'}
    return Response(content=data, media_type=mime or "application/octet-stream", headers=headers)


@router.delete("/sharepoint/files/{item_id}")
def sharepoint_delete(item_id: str, db: Session = Depends(get_db)):
    conn = sp_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(404, "no active connection")
    try:
        sp_svc.delete_file(conn, item_id=item_id)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


# ---------- Placeholder integrations (Jitterbit, DocuNet) ----------
#
# These are middleware bridges Keysight owns. ZBrain doesn't talk to them
# directly today — Jitterbit fronts Oracle EBS and DocuNet, and is enabled
# from this surface once the operator has the credentials. Until enabled the
# routes return a clear "upcoming" envelope; once enabled the trace UI tags
# downstream actions as routed-through-jitterbit (handoff, ZBrain doesn't
# execute them itself).
from datetime import datetime as _dt
from ..models import IntegrationPlaceholder


_PLACEHOLDER_PROVIDERS: dict[str, dict[str, str]] = {
    "jitterbit": {
        "label": "Jitterbit (middleware bridge)",
        "kind": "Middleware",
        "description": "Keysight-provided middleware channel for Oracle EBS and DocuNet. Once enabled, AI Order Acceptance writes route through Jitterbit instead of the local mock.",
    },
    "docunet": {
        "label": "DocuNet (document classification overlay)",
        "kind": "Document",
        "description": "Keysight's internal document store reached through Jitterbit. Documents file with Doc type = FCNV per Keysight's existing convention. SharePoint is the active document store today; enable DocuNet to dual-write once the Jitterbit bridge is provisioned.",
    },
}


class PlaceholderConfig(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    note: str | None = None


def _placeholder_payload(provider: str, row: IntegrationPlaceholder | None) -> dict[str, Any]:
    meta = _PLACEHOLDER_PROVIDERS.get(provider, {})
    if row is None:
        return {
            "provider": provider,
            "label": meta.get("label", provider),
            "kind": meta.get("kind"),
            "description": meta.get("description"),
            "enabled": False,
            "config": {},
            "last_enabled_at": None,
            "last_disabled_at": None,
            "note": None,
        }
    return {
        "provider": row.provider,
        "label": row.label or meta.get("label", row.provider),
        "kind": meta.get("kind"),
        "description": meta.get("description"),
        "enabled": bool(row.enabled),
        "config": row.config or {},
        "last_enabled_at": row.last_enabled_at.isoformat() if row.last_enabled_at else None,
        "last_disabled_at": row.last_disabled_at.isoformat() if row.last_disabled_at else None,
        "note": row.note,
    }


@router.get("/placeholders")
def placeholders_list(db: Session = Depends(get_db)):
    out = []
    for provider in _PLACEHOLDER_PROVIDERS:
        row = db.query(IntegrationPlaceholder).filter_by(provider=provider).first()
        out.append(_placeholder_payload(provider, row))
    return {"items": out}


@router.get("/placeholders/{provider}")
def placeholders_get(provider: str, db: Session = Depends(get_db)):
    if provider not in _PLACEHOLDER_PROVIDERS:
        raise HTTPException(404, f"unknown integration: {provider}")
    row = db.query(IntegrationPlaceholder).filter_by(provider=provider).first()
    return _placeholder_payload(provider, row)


@router.post("/placeholders/{provider}")
def placeholders_upsert(provider: str, body: PlaceholderConfig, db: Session = Depends(get_db)):
    if provider not in _PLACEHOLDER_PROVIDERS:
        raise HTTPException(404, f"unknown integration: {provider}")
    meta = _PLACEHOLDER_PROVIDERS[provider]
    row = db.query(IntegrationPlaceholder).filter_by(provider=provider).first()
    if row is None:
        row = IntegrationPlaceholder(provider=provider, label=meta["label"], enabled=False, config={})
        db.add(row)
    if body.config is not None:
        row.config = body.config
    if body.note is not None:
        row.note = body.note
    if body.enabled is not None:
        prev = bool(row.enabled)
        row.enabled = bool(body.enabled)
        if row.enabled and not prev:
            row.last_enabled_at = _dt.utcnow()
        elif (not row.enabled) and prev:
            row.last_disabled_at = _dt.utcnow()
    db.commit()
    db.refresh(row)
    return _placeholder_payload(provider, row)


# ============================================================================
# OpenAI / LLM provider integration
# ============================================================================

from .. services import llm_provider as _llm_svc
from .. services import openai_client as _openai_client


class OpenAIConnectBody(BaseModel):
    api_key: str
    model: str | None = None
    is_active: bool = True


def _llm_status_payload(db: Session) -> dict:
    row = _llm_svc.get_config(db, _llm_svc.PROVIDER_OPENAI)
    env_fallback = bool((os.environ.get("OPENAI_API_KEY") or "").strip())
    return _llm_svc.serialize(row, env_fallback_active=env_fallback and row is None)


@router.get("/openai/status")
def openai_status(db: Session = Depends(get_db)) -> dict:
    return _llm_status_payload(db)


@router.post("/openai/test")
def openai_test(body: OpenAIConnectBody) -> dict:
    """Validate the API key by listing models. Does not save the key."""
    return _llm_svc.test_api_key(body.api_key, body.model)


@router.post("/openai/connect")
def openai_connect(body: OpenAIConnectBody, db: Session = Depends(get_db)) -> dict:
    """Save the API key (encrypted) and the preferred model. Drops the cached
    OpenAI client so the next pipeline call re-reads the new credentials."""
    result = _llm_svc.test_api_key(body.api_key, body.model)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=f"openai_test_failed: {result.get('message')}")
    _llm_svc.upsert_openai_config(
        db,
        api_key=body.api_key,
        model=body.model,
        is_active=body.is_active,
    )
    _openai_client.reset_client()
    return _llm_status_payload(db)


@router.delete("/openai/disconnect")
def openai_disconnect(db: Session = Depends(get_db)) -> dict:
    _llm_svc.disconnect_openai(db)
    _openai_client.reset_client()
    return {"ok": True}
