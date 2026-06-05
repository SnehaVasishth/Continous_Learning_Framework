"""SharePoint Online connector — Microsoft Graph + OAuth client_credentials.

Same shape as `salesforce.py` / `servicenow.py`: whoami, test_connection, serialize,
get_active_connection, upsert_connection, refresh_status. On top of that we expose
list/upload/download/delete helpers that the orchestrator uses to push generated
SOAs/invoices into the configured library and pull customer-supplied PDFs back.

Design notes:
- Token cache is an in-memory dict keyed by client_id, with TTL minus 60s slack.
  Tokens are 60-min lived; we refresh well before expiry so concurrent requests
  don't all hit /token at once.
- folder_path is stored relative to the drive root (e.g. "/Salesops"). The
  Graph addressing for that is `/drive/root:/Salesops`.
- We never log the client_secret. `serialize` returns metadata only.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

import requests
from sqlalchemy.orm import Session

from ..models import SharePointConnection
from .secrets import decrypt, encrypt

log = logging.getLogger("sharepoint")

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"

_token_cache: dict[str, tuple[str, float]] = {}  # client_id -> (token, expires_at)


def _normalize_folder(p: str | None) -> str:
    p = (p or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def _path_segment(folder_path: str, name: str | None = None) -> str:
    fp = _normalize_folder(folder_path).lstrip("/")
    if name:
        rel = f"{fp}/{name}".strip("/") if fp else name
    else:
        rel = fp
    return quote(rel, safe="/")


# ---------- token ----------


def get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    cache_key = f"{tenant_id}:{client_id}"
    now = time.time()
    cached = _token_cache.get(cache_key)
    if cached and cached[1] - 60 > now:
        return cached[0]
    r = requests.post(
        f"{LOGIN}/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"oauth_token_failed: HTTP {r.status_code} {r.text[:300]}")
    payload = r.json()
    token = payload["access_token"]
    expires_at = now + int(payload.get("expires_in", 3600))
    _token_cache[cache_key] = (token, expires_at)
    return token


def _invalidate_token(tenant_id: str, client_id: str) -> None:
    _token_cache.pop(f"{tenant_id}:{client_id}", None)


def _headers(token: str, extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if extra:
        h.update(extra)
    return h


# ---------- whoami / test ----------


@dataclass
class WhoAmI:
    site_id: str
    site_display_name: str | None
    site_web_url: str | None
    drive_id: str | None
    drive_name: str | None
    folder_path: str
    item_count: int | None


def _resolve_drive(token: str, site_id: str, drive_id: str | None) -> tuple[str | None, str | None]:
    if drive_id:
        r = requests.get(f"{GRAPH}/sites/{site_id}/drives/{drive_id}", headers=_headers(token), timeout=30)
        if r.status_code == 200:
            d = r.json()
            return d.get("id"), d.get("name")
        return drive_id, None
    r = requests.get(f"{GRAPH}/sites/{site_id}/drive", headers=_headers(token), timeout=30)
    if r.status_code == 200:
        d = r.json()
        return d.get("id"), d.get("name")
    return None, None


def _list_at(token: str, site_id: str, folder_path: str) -> list[dict]:
    seg = _path_segment(folder_path)
    if seg in ("", "/"):
        url = f"{GRAPH}/sites/{site_id}/drive/root/children"
    else:
        url = f"{GRAPH}/sites/{site_id}/drive/root:/{seg}:/children"
    r = requests.get(url, headers=_headers(token), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"list_failed: HTTP {r.status_code} {r.text[:300]}")
    return (r.json() or {}).get("value", [])


def whoami(
    *, tenant_id: str, client_id: str, client_secret: str, site_id: str,
    drive_id: str | None = None, folder_path: str = "/",
) -> WhoAmI:
    token = get_access_token(tenant_id, client_id, client_secret)

    r = requests.get(f"{GRAPH}/sites/{site_id}", headers=_headers(token), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"site_not_reachable: HTTP {r.status_code} {r.text[:300]}")
    site = r.json()
    resolved_drive_id, drive_name = _resolve_drive(token, site_id, drive_id)

    folder_path = _normalize_folder(folder_path)
    items = _list_at(token, site_id, folder_path)
    return WhoAmI(
        site_id=site_id,
        site_display_name=site.get("displayName"),
        site_web_url=site.get("webUrl"),
        drive_id=resolved_drive_id,
        drive_name=drive_name,
        folder_path=folder_path,
        item_count=len(items),
    )


def test_connection(
    *, tenant_id: str, client_id: str, client_secret: str, site_id: str,
    drive_id: str | None = None, folder_path: str = "/",
) -> tuple[bool, str, dict | None]:
    try:
        info = whoami(
            tenant_id=tenant_id, client_id=client_id, client_secret=client_secret,
            site_id=site_id, drive_id=drive_id, folder_path=folder_path,
        )
        return True, "ok", {
            "site_id": info.site_id,
            "site_display_name": info.site_display_name,
            "site_web_url": info.site_web_url,
            "drive_id": info.drive_id,
            "drive_name": info.drive_name,
            "folder_path": info.folder_path,
            "item_count": info.item_count,
        }
    except RuntimeError as e:
        return False, str(e), None
    except requests.RequestException as e:
        return False, f"network_error: {e}", None
    except Exception as e:
        log.exception("test_connection failed")
        return False, f"unexpected: {type(e).__name__}: {e}", None


# ---------- serialize / db ----------


def serialize(conn: SharePointConnection) -> dict[str, Any]:
    return {
        "id": conn.id,
        "label": conn.label,
        "tenant_id": conn.tenant_id,
        "client_id": conn.client_id,
        "site_id": conn.site_id,
        "drive_id": conn.drive_id,
        "folder_path": conn.folder_path,
        "is_active": conn.is_active,
        "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        "last_error": conn.last_error,
        "last_error_at": conn.last_error_at.isoformat() if conn.last_error_at else None,
        "site_display_name": conn.site_display_name,
        "site_web_url": conn.site_web_url,
        "drive_name": conn.drive_name,
        "item_count": conn.item_count,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
    }


def get_active_connection(db: Session) -> SharePointConnection | None:
    return (
        db.query(SharePointConnection)
        .filter_by(is_active=True)
        .order_by(SharePointConnection.id.desc())
        .first()
    )


def file_url(item: dict | None) -> str | None:
    """Best-effort deep-link to a SharePoint file. Reads `web_url` / `webUrl`
    from an upload-result dict. Returns None when no URL is resolvable."""
    if not item or not isinstance(item, dict):
        return None
    return item.get("web_url") or item.get("webUrl")


def site_link(db: Session) -> str | None:
    """Returns the active SharePoint site's web URL (root of the document
    library). Useful when no specific file URL is available but the operator
    still wants a 'see in SharePoint' link."""
    conn = get_active_connection(db)
    if conn and conn.site_web_url:
        return conn.site_web_url
    return None


def upsert_connection(
    db: Session, *,
    tenant_id: str, client_id: str, client_secret: str, site_id: str,
    drive_id: str | None = None, folder_path: str = "/",
    label: str = "Production site",
) -> SharePointConnection:
    info = whoami(
        tenant_id=tenant_id, client_id=client_id, client_secret=client_secret,
        site_id=site_id, drive_id=drive_id, folder_path=folder_path,
    )

    db.query(SharePointConnection).update({"is_active": False})
    row = SharePointConnection(
        label=label,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret_enc=encrypt(client_secret),
        site_id=site_id,
        drive_id=info.drive_id,
        folder_path=info.folder_path,
        is_active=True,
        last_tested_at=datetime.now(timezone.utc),
        site_display_name=info.site_display_name,
        site_web_url=info.site_web_url,
        drive_name=info.drive_name,
        item_count=info.item_count,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def refresh_status(db: Session, conn: SharePointConnection) -> SharePointConnection:
    try:
        secret = decrypt(conn.client_secret_enc)
        info = whoami(
            tenant_id=conn.tenant_id, client_id=conn.client_id, client_secret=secret,
            site_id=conn.site_id, drive_id=conn.drive_id, folder_path=conn.folder_path,
        )
        conn.last_tested_at = datetime.now(timezone.utc)
        conn.last_error = None
        conn.last_error_at = None
        conn.site_display_name = info.site_display_name
        conn.site_web_url = info.site_web_url
        conn.drive_name = info.drive_name
        conn.item_count = info.item_count
    except Exception as e:
        _invalidate_token(conn.tenant_id, conn.client_id)
        conn.last_error = str(e)[:500]
        conn.last_error_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conn)
    return conn


# ---------- file ops (used by routes + tool bridge) ----------


def _conn_token(conn: SharePointConnection) -> str:
    return get_access_token(conn.tenant_id, conn.client_id, decrypt(conn.client_secret_enc))


def list_files(conn: SharePointConnection, *, subfolder: str | None = None) -> list[dict]:
    token = _conn_token(conn)
    target_folder = conn.folder_path or "/"
    if subfolder:
        target_folder = (target_folder.rstrip("/") + "/" + subfolder.lstrip("/"))
    items = _list_at(token, conn.site_id, target_folder)
    out = []
    for it in items:
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "kind": "folder" if "folder" in it else "file",
            "size": it.get("size"),
            "web_url": it.get("webUrl"),
            "last_modified": it.get("lastModifiedDateTime"),
            "mime_type": (it.get("file") or {}).get("mimeType"),
            "download_url": it.get("@microsoft.graph.downloadUrl"),
        })
    return out


def upload_file(
    conn: SharePointConnection, *,
    name: str, content: bytes, content_type: str = "application/octet-stream",
    subfolder: str | None = None, overwrite: bool = True,
) -> dict:
    token = _conn_token(conn)
    target_folder = conn.folder_path or "/"
    if subfolder:
        target_folder = (target_folder.rstrip("/") + "/" + subfolder.lstrip("/"))
    seg = _path_segment(target_folder, name)
    url = f"{GRAPH}/sites/{conn.site_id}/drive/root:/{seg}:/content"
    if not overwrite:
        url += "?@microsoft.graph.conflictBehavior=fail"
    r = requests.put(url, headers=_headers(token, {"Content-Type": content_type}), data=content, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload_failed: HTTP {r.status_code} {r.text[:300]}")
    item = r.json()
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "size": item.get("size"),
        "web_url": item.get("webUrl"),
        "etag": item.get("eTag"),
    }


def download_file(conn: SharePointConnection, *, item_id: str) -> tuple[bytes, str | None, str | None]:
    """Returns (bytes, name, mime_type). Streams via the Graph driveItem/content endpoint."""
    token = _conn_token(conn)
    meta = requests.get(f"{GRAPH}/sites/{conn.site_id}/drive/items/{item_id}", headers=_headers(token), timeout=30)
    if meta.status_code != 200:
        raise RuntimeError(f"item_lookup_failed: HTTP {meta.status_code} {meta.text[:300]}")
    m = meta.json()
    name = m.get("name")
    mime = (m.get("file") or {}).get("mimeType")
    r = requests.get(
        f"{GRAPH}/sites/{conn.site_id}/drive/items/{item_id}/content",
        headers=_headers(token), timeout=120, allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"download_failed: HTTP {r.status_code} {r.text[:300]}")
    return r.content, name, mime


def delete_file(conn: SharePointConnection, *, item_id: str) -> None:
    token = _conn_token(conn)
    r = requests.delete(f"{GRAPH}/sites/{conn.site_id}/drive/items/{item_id}", headers=_headers(token), timeout=30)
    if r.status_code not in (204, 200):
        raise RuntimeError(f"delete_failed: HTTP {r.status_code} {r.text[:300]}")


# ---------- bridge for the agent tool ----------


def current_credentials(db: Session) -> dict | None:
    """Return creds dict for the active SharePoint connection, or None.

    Lets the existing `sharepoint_fetch_doc` tool read from DB instead of os.environ.
    Coordinated with Session A — the tool will call this if available, else fall back
    to env vars (no-op for users who haven't connected yet).
    """
    conn = get_active_connection(db)
    if not conn:
        return None
    try:
        secret = decrypt(conn.client_secret_enc)
    except Exception:
        return None
    return {
        "tenant_id": conn.tenant_id,
        "client_id": conn.client_id,
        "client_secret": secret,
        "site_id": conn.site_id,
        "drive_id": conn.drive_id,
        "folder_path": conn.folder_path,
    }
