"""SharePoint upload + Salesforce URL-stamp helper.

Used by seed-data scripts and one-shot backfill flows. The contract:
  upload_and_stamp(local_path, sf_object, sf_record_id, sf_field, *, subfolder)
    1. Reads local_path
    2. Uploads to SharePoint at /<connected_folder>/<subfolder>/<basename>
    3. Captures the resulting webUrl
    4. Patches sf_object/{sf_record_id} with sf_field = webUrl
    5. Returns {sp_url, sp_item_id, sf_updated}

Operates on the active SharePoint + Salesforce connections from the DB —
no environment vars, no creds in the call signature.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..services import salesforce as sf_svc
from ..services import sharepoint as sp_svc

log = logging.getLogger("sharepoint_stamp")


def _content_type_for(name: str) -> str:
    guess, _ = mimetypes.guess_type(name)
    return guess or "application/octet-stream"


def upload_to_sharepoint(
    db: Session,
    *,
    local_path: str | Path,
    subfolder: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Upload a local file to the active SharePoint connection's folder.

    `subfolder` is appended to the connection's `folder_path` (e.g. "Aurora-Auto/quotes").
    Returns {ok, sp_url, sp_item_id, name, size, error}."""
    local = Path(local_path)
    if not local.exists():
        return {"ok": False, "error": f"local_file_missing: {local}"}

    conn = sp_svc.get_active_connection(db)
    if not conn:
        return {"ok": False, "error": "sharepoint_not_configured"}

    try:
        with open(local, "rb") as fh:
            content = fh.read()
        meta = sp_svc.upload_file(
            conn,
            name=local.name,
            content=content,
            content_type=_content_type_for(local.name),
            subfolder=subfolder,
            overwrite=overwrite,
        )
        return {
            "ok": True,
            "sp_url": meta.get("web_url"),
            "sp_item_id": meta.get("id"),
            "name": meta.get("name"),
            "size": meta.get("size"),
            "subfolder": subfolder,
        }
    except RuntimeError as e:
        log.warning("SP upload failed for %s: %s", local, e)
        return {"ok": False, "error": str(e)[:300]}
    except Exception as e:
        log.warning("SP upload unexpected error for %s: %s", local, e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def stamp_salesforce_url(
    db: Session,
    *,
    sf_object: str,
    sf_record_id: str,
    sf_field: str,
    web_url: str,
) -> dict[str, Any]:
    """PATCH a Salesforce record's URL field with the given SharePoint webUrl."""
    conn = sf_svc.get_active_connection(db)
    if not conn:
        return {"ok": False, "error": "salesforce_not_configured"}
    try:
        sf = sf_svc.client_for(conn)
        sf_obj = getattr(sf, sf_object)
        sf_obj.update(sf_record_id, {sf_field: web_url})
        return {"ok": True, "sf_object": sf_object, "sf_record_id": sf_record_id, "sf_field": sf_field}
    except Exception as e:
        log.warning("SF update failed for %s/%s.%s: %s", sf_object, sf_record_id, sf_field, e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def upload_and_stamp(
    db: Session,
    *,
    local_path: str | Path,
    subfolder: str | None,
    sf_object: str,
    sf_record_id: str,
    sf_field: str,
) -> dict[str, Any]:
    """Compose: upload to SharePoint → stamp the webUrl onto the SF record."""
    up = upload_to_sharepoint(db, local_path=local_path, subfolder=subfolder)
    if not up.get("ok"):
        return {"ok": False, "error": f"upload: {up.get('error')}"}
    sp_url = up["sp_url"]
    stamp = stamp_salesforce_url(
        db,
        sf_object=sf_object,
        sf_record_id=sf_record_id,
        sf_field=sf_field,
        web_url=sp_url,
    )
    return {
        "ok": stamp["ok"],
        "sp_url": sp_url,
        "sp_item_id": up.get("sp_item_id"),
        "sf_updated": stamp.get("ok"),
        "error": stamp.get("error") if not stamp["ok"] else None,
    }
