"""ServiceNow connector — Basic Auth REST.

Uses the ServiceNow Table API (`/api/now/table/{table}`) for case CRUD.
Case table defaults to `incident`; CSM-enabled instances can switch to
`sn_customerservice_case`.

State mapping for `incident`:
    1 = New, 2 = In Progress, 3 = On Hold, 6 = Resolved, 7 = Closed, 8 = Canceled

Used by Stage 4 of the agent fabric: every inbound customer request becomes
an Incident, status transitions are written through this connector, and
closure happens when the agent finishes the workflow.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth
from sqlalchemy.orm import Session

from ..models import ServiceNowConnection
from .secrets import decrypt, encrypt

log = logging.getLogger("servicenow")


@dataclass
class WhoAmI:
    instance_url: str
    instance_version: str | None
    case_table: str
    incident_count: int | None
    csm_active: bool


def _normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # strip any UI path the user might have pasted
    for tail in ("/now/nav/ui/classic", "/now/nav/ui", "/now"):
        if url.endswith(tail):
            url = url[: -len(tail)]
    return url


def _get(instance_url: str, username: str, password: str, path: str, params: dict | None = None) -> requests.Response:
    return requests.get(
        f"{_normalize_url(instance_url)}{path}",
        auth=HTTPBasicAuth(username, password),
        params=params or {},
        timeout=30,
    )


def _post(instance_url: str, username: str, password: str, path: str, body: dict) -> requests.Response:
    return requests.post(
        f"{_normalize_url(instance_url)}{path}",
        auth=HTTPBasicAuth(username, password),
        json=body,
        timeout=30,
    )


def _patch(instance_url: str, username: str, password: str, path: str, body: dict) -> requests.Response:
    return requests.patch(
        f"{_normalize_url(instance_url)}{path}",
        auth=HTTPBasicAuth(username, password),
        json=body,
        timeout=30,
    )


def whoami(instance_url: str, username: str, password: str, case_table: str = "incident") -> WhoAmI:
    # 1. Verify auth + read access to the chosen case table
    r = _get(instance_url, username, password, f"/api/now/table/{case_table}", {"sysparm_limit": 1})
    if r.status_code != 200:
        raise RuntimeError(f"table access failed: HTTP {r.status_code} {r.text[:200]}")
    # 2. Probe CSM availability (best-effort, ignore failure)
    csm_ok = False
    try:
        r2 = _get(instance_url, username, password, "/api/now/table/sn_customerservice_case", {"sysparm_limit": 1})
        csm_ok = r2.status_code == 200
    except Exception:
        pass
    # 3. Try to read instance version (admin-only on some PDIs)
    version: str | None = None
    try:
        r3 = _get(
            instance_url,
            username,
            password,
            "/api/now/table/sys_properties",
            {"sysparm_query": "name=glide.product.version", "sysparm_fields": "value", "sysparm_limit": 1},
        )
        if r3.status_code == 200:
            recs = r3.json().get("result") or []
            if recs:
                version = recs[0].get("value")
    except Exception:
        pass
    # 4. Count incidents
    count: int | None = None
    try:
        r4 = _get(instance_url, username, password, f"/api/now/stats/{case_table}", {"sysparm_count": "true"})
        if r4.status_code == 200:
            stats = r4.json().get("result", {}).get("stats", {})
            count = int(stats.get("count")) if stats.get("count") is not None else None
    except Exception:
        pass
    return WhoAmI(
        instance_url=_normalize_url(instance_url),
        instance_version=version,
        case_table=case_table,
        incident_count=count,
        csm_active=csm_ok,
    )


def test_connection(
    *,
    instance_url: str,
    username: str,
    password: str,
    case_table: str = "incident",
) -> tuple[bool, str, dict | None]:
    try:
        info = whoami(instance_url, username, password, case_table)
        return True, "ok", {
            "instance_url": info.instance_url,
            "instance_version": info.instance_version,
            "case_table": info.case_table,
            "incident_count": info.incident_count,
            "csm_active": info.csm_active,
        }
    except RuntimeError as e:
        return False, str(e), None
    except requests.RequestException as e:
        return False, f"network_error: {e}", None
    except Exception as e:
        log.exception("test_connection failed")
        return False, f"unexpected: {type(e).__name__}: {e}", None


def serialize(conn: ServiceNowConnection) -> dict[str, Any]:
    return {
        "id": conn.id,
        "label": conn.label,
        "instance_url": conn.instance_url,
        "username": conn.username,
        "case_table": conn.case_table,
        "is_active": conn.is_active,
        "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        "last_error": conn.last_error,
        "last_error_at": conn.last_error_at.isoformat() if conn.last_error_at else None,
        "instance_version": conn.instance_version,
        "incident_count": conn.incident_count,
        "csm_active": conn.csm_active,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
    }


def get_active_connection(db: Session) -> ServiceNowConnection | None:
    return db.query(ServiceNowConnection).filter_by(is_active=True).order_by(ServiceNowConnection.id.desc()).first()


def upsert_connection(
    db: Session,
    *,
    instance_url: str,
    username: str,
    password: str,
    case_table: str = "incident",
    label: str = "Production instance",
) -> ServiceNowConnection:
    info = whoami(instance_url, username, password, case_table)

    db.query(ServiceNowConnection).update({"is_active": False})
    row = ServiceNowConnection(
        label=label,
        instance_url=info.instance_url,
        username=username,
        password_enc=encrypt(password),
        case_table=info.case_table,
        is_active=True,
        last_tested_at=datetime.now(timezone.utc),
        instance_version=info.instance_version,
        incident_count=info.incident_count,
        csm_active=info.csm_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def refresh_status(db: Session, conn: ServiceNowConnection) -> ServiceNowConnection:
    try:
        info = whoami(conn.instance_url, conn.username, decrypt(conn.password_enc), conn.case_table)
        conn.last_tested_at = datetime.now(timezone.utc)
        conn.last_error = None
        conn.last_error_at = None
        conn.instance_version = info.instance_version
        conn.incident_count = info.incident_count
        conn.csm_active = info.csm_active
    except Exception as e:
        conn.last_error = str(e)[:500]
        conn.last_error_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conn)
    return conn


# ---------------------------------------------------------------------------
# Case lifecycle helpers — used by Stage 4 of the agent fabric
# ---------------------------------------------------------------------------

# Incident state values
INCIDENT_STATE = {
    "new": "1",
    "in_progress": "2",
    "on_hold": "3",
    "resolved": "6",
    "closed": "7",
    "canceled": "8",
}


def create_case(
    conn: ServiceNowConnection,
    *,
    short_description: str,
    description: str,
    caller_email: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    priority: int = 3,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new incident. Returns the ServiceNow record with sys_id + number."""
    body: dict[str, Any] = {
        "short_description": short_description[:160] if short_description else "",
        "description": description or "",
        "state": INCIDENT_STATE["new"],
        "priority": str(priority),
    }
    if caller_email:
        body["caller_id"] = caller_email
        body["u_caller_email"] = caller_email
    if category:
        body["category"] = category
    if subcategory:
        body["subcategory"] = subcategory
    if extra_fields:
        body.update(extra_fields)

    password = decrypt(conn.password_enc)
    r = _post(conn.instance_url, conn.username, password, f"/api/now/table/{conn.case_table}", body)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_case failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json().get("result") or {}


def update_case_state(
    conn: ServiceNowConnection,
    *,
    sys_id: str,
    state: str,
    work_notes: str | None = None,
    close_code: str | None = None,
    close_notes: str | None = None,
) -> dict[str, Any]:
    """Move a case forward in its lifecycle. `state` is a key from INCIDENT_STATE."""
    state_value = INCIDENT_STATE.get(state, state)
    body: dict[str, Any] = {"state": state_value}
    if work_notes:
        body["work_notes"] = work_notes
    if state in ("resolved", "closed"):
        body["close_code"] = close_code or "Solved (Permanently)"
        body["close_notes"] = close_notes or "Resolved by ZBrain agent fabric."
    password = decrypt(conn.password_enc)
    r = _patch(conn.instance_url, conn.username, password, f"/api/now/table/{conn.case_table}/{sys_id}", body)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"update_case failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json().get("result") or {}
