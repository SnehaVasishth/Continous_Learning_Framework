"""Case evidence uploader — Stage 4's "Attach evidence" substep.

For every email attachment on a pipeline:
  1. Upload to the active SharePoint site (under `case_evidence/<request_number>/`).
  2. Collect the SharePoint `web_url` for each upload.
  3. Post a single CaseComment on the SF Case listing the uploaded files
     with their SharePoint links — so a CSR opening the Case sees the
     evidence inline with a click-through to SharePoint.
  4. Return a summary dict (file count, urls, comment_id) that the orchestrator
     records in a trace event with full deep links.

Best-effort: if SharePoint is offline / SF is not connected, we log what
would have happened and continue — the demo never crashes a pipeline on
infra issues.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import UPLOADS
from . import salesforce_cases as sf_cases
from . import sharepoint as sp_svc

log = logging.getLogger("case_evidence")


def _resolve_attachment_paths(attachments: list[dict | str]) -> list[tuple[str, Path]]:
    """Map each attachment dict/string to (display_name, local_path).
    The orchestrator writes attachments as dicts {name, path, kind, type} —
    we look the file up under UPLOADS using the path field."""
    out: list[tuple[str, Path]] = []
    for a in attachments or []:
        if isinstance(a, str):
            name = a
            rel = a
        elif isinstance(a, dict):
            name = a.get("name") or "attachment"
            rel = a.get("path") or a.get("name") or ""
        else:
            continue
        if not rel:
            continue
        p = Path(rel)
        if not p.is_absolute():
            p = UPLOADS / rel
        if p.exists() and p.is_file():
            out.append((name, p))
    return out


def upload_email_attachments_to_case(
    db: Session,
    *,
    pipeline_id: int,
    case_id: str | None,
    request_number: str | None,
    attachments: list[dict | str],
) -> dict:
    """Upload every resolvable attachment to SharePoint under a per-case
    subfolder, then write one CaseComment summarising the links. Returns:

        {
          "ok": bool,
          "uploaded": [{"name", "size", "sharepoint_url"}, ...],
          "skipped": [{"name", "reason"}, ...],
          "case_comment": {"ok", "comment_id"} | None,
          "subfolder": str | None,
        }
    """
    resolved = _resolve_attachment_paths(attachments)
    if not resolved:
        return {"ok": True, "uploaded": [], "skipped": [], "case_comment": None, "subfolder": None}

    conn = sp_svc.get_active_connection(db)
    if not conn:
        return {
            "ok": False,
            "uploaded": [],
            "skipped": [{"name": name, "reason": "sharepoint_not_connected"} for name, _ in resolved],
            "case_comment": None,
            "subfolder": None,
            "reason": "sharepoint_not_connected",
        }

    safe_req = (request_number or f"pipeline_{pipeline_id}").replace("/", "_")
    subfolder = f"case_evidence/{safe_req}"

    uploaded: list[dict] = []
    skipped: list[dict] = []
    for name, path in resolved:
        try:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            content = path.read_bytes()
            res = sp_svc.upload_file(
                conn,
                name=name,
                content=content,
                content_type=mime,
                subfolder=subfolder,
            )
            uploaded.append({
                "name": res.get("name") or name,
                "size": res.get("size") or len(content),
                "sharepoint_url": res.get("web_url"),
                "sharepoint_item_id": res.get("id"),
            })
        except Exception as ex:
            log.info("attachment upload failed (%s): %s", name, str(ex)[:200])
            skipped.append({"name": name, "reason": f"{type(ex).__name__}: {str(ex)[:160]}"})

    # Post a single CaseComment with the link list so the CSR sees evidence
    # in the Case feed.
    case_comment_res: dict | None = None
    if case_id and uploaded:
        lines = [
            f"📎 ZBrain attached {len(uploaded)} customer document(s) to SharePoint:",
            "",
        ]
        for item in uploaded:
            url = item.get("sharepoint_url") or "(no link)"
            lines.append(f"• {item['name']} — {url}")
        body = "\n".join(lines)
        case_comment_res = sf_cases.add_case_comment(db, case_id, body=body, is_public=False)

    return {
        "ok": True,
        "uploaded": uploaded,
        "skipped": skipped,
        "case_comment": case_comment_res,
        "subfolder": subfolder,
    }
