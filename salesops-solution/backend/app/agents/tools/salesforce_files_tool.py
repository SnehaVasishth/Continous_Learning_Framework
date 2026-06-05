"""Fetch files attached to a Salesforce record (Account / Order / Opportunity / etc).

Salesforce stores attachments via the Files / ContentDocument framework:
  ContentDocumentLink (LinkedEntityId -> ContentDocument)
  ContentDocument (Title, FileType, ContentSize, LatestPublishedVersionId)
  ContentVersion  (binary blob via /services/data/v60.0/sobjects/ContentVersion/{id}/VersionData)

This tool:
  1. Queries ContentDocumentLink for the parent record
  2. Resolves each ContentDocument's latest ContentVersion
  3. Downloads the binary into UPLOADS so downstream OCR/extract tools can read it
  4. Returns a list of {name, path, size, sha256} that can be appended to the
     email's attachment list for Stage 2 extraction

Cloud-friendly: no SDK shell-out; pure REST via the existing salesforce client.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from simple_salesforce.exceptions import SalesforceError

from ...config import UPLOADS
from ...services import salesforce as sf_svc
from ..base import AgentContext, Tool, ToolResult

log = logging.getLogger("salesforce_files_tool")


_SAFE_CHAR = re.compile(r"[^A-Za-z0-9._\-]")


def _safe_filename(name: str) -> str:
    name = (name or "attachment.bin").strip().replace("\\", "_").replace("/", "_")
    return _SAFE_CHAR.sub("_", name)[:120] or "attachment.bin"


class SalesforceFilesTool(Tool):
    """Pull file attachments off a Salesforce record into the local UPLOADS dir for OCR."""

    name = "salesforce_fetch_files"
    description = "Download files attached to a Salesforce record (via ContentDocumentLink)."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            # Accept either a single parent_id (back-compat) or a list of
            # parent_ids — Stage 2.4 passes the full set of records returned by
            # enrichment (Account + Order + WorkOrder + Asset + Quote + ...).
            raw_parents = (
                inputs.get("parent_ids")
                or inputs.get("parent_id")
                or inputs.get("account_id")
            )
            if isinstance(raw_parents, str):
                parent_ids: list[str] = [raw_parents]
            elif isinstance(raw_parents, list):
                parent_ids = [str(p) for p in raw_parents if p]
            else:
                parent_ids = []
            if not parent_ids:
                return ToolResult(name=self.name, ok=False, error="missing parent_id(s)")
            max_files = int(inputs.get("max_files") or 20)

            conn = sf_svc.get_active_connection(ctx.db)
            if not conn:
                return ToolResult(name=self.name, ok=False, error="no_active_salesforce_connection")
            sf = sf_svc.client_for(conn)

            # Build IN-clause for cross-parent ContentDocumentLink lookup.
            safe_ids = ", ".join(f"'{str(p).replace(chr(39), '')}'" for p in parent_ids)
            link_q = (
                "SELECT LinkedEntityId, ContentDocumentId, ContentDocument.Title, "
                "ContentDocument.FileType, ContentDocument.ContentSize, "
                "ContentDocument.LatestPublishedVersionId "
                f"FROM ContentDocumentLink WHERE LinkedEntityId IN ({safe_ids}) "
                f"ORDER BY ContentDocument.LastModifiedDate DESC LIMIT {max_files}"
            )
            try:
                link_res = sf.query(link_q)
            except SalesforceError as e:
                return ToolResult(name=self.name, ok=False, error=f"sf_query_failed: {str(e)[:200]}")

            records = link_res.get("records") or []
            if not records:
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data={"parent_ids": parent_ids, "fetched": [], "skipped": [], "count": 0},
                    notes=["no_files_on_any_parent_record"],
                )

            instance_url = (conn.instance_url or "").rstrip("/")
            if not instance_url.startswith(("http://", "https://")):
                instance_url = "https://" + instance_url
            api_version = conn.api_version or "60.0"

            fetched: list[dict] = []
            skipped: list[dict] = []
            for rec in records:
                doc = rec.get("ContentDocument") or {}
                version_id = doc.get("LatestPublishedVersionId")
                title = doc.get("Title") or "untitled"
                ext = doc.get("FileType") or ""
                size = doc.get("ContentSize") or 0
                if not version_id:
                    skipped.append({"title": title, "reason": "no_latest_version_id"})
                    continue

                try:
                    blob_url = f"{instance_url}/services/data/v{api_version}/sobjects/ContentVersion/{version_id}/VersionData"
                    headers = {"Authorization": f"Bearer {sf.session_id}"}
                    import requests as _requests
                    blob_resp = _requests.get(blob_url, headers=headers, timeout=60, stream=True)
                except Exception as e:
                    skipped.append({"title": title, "reason": f"network: {type(e).__name__}: {e}"})
                    continue

                if blob_resp.status_code != 200:
                    skipped.append({"title": title, "reason": f"http_{blob_resp.status_code}"})
                    continue

                normalized_ext = (ext or "").lower().strip(".")
                stamped = f"sf_{uuid.uuid4().hex[:8]}_{_safe_filename(title)}"
                if normalized_ext and not stamped.lower().endswith(f".{normalized_ext}"):
                    stamped = f"{stamped}.{normalized_ext}"
                target = Path(UPLOADS) / stamped

                hasher = hashlib.sha256()
                bytes_written = 0
                try:
                    with open(target, "wb") as fh:
                        for chunk in blob_resp.iter_content(chunk_size=65536):
                            if not chunk:
                                continue
                            fh.write(chunk)
                            hasher.update(chunk)
                            bytes_written += len(chunk)
                except Exception as e:
                    skipped.append({"title": title, "reason": f"write_failed: {type(e).__name__}: {e}"})
                    continue

                fetched.append({
                    "name": stamped,
                    "original_name": title,
                    "file_type": ext,
                    "size_bytes": bytes_written or size,
                    "sha256": hasher.hexdigest(),
                    "salesforce_content_document_id": doc.get("LatestPublishedVersionId"),
                    "linked_entity_id": rec.get("LinkedEntityId"),
                })

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "parent_ids": parent_ids,
                    "fetched": fetched,
                    "skipped": skipped,
                    "count": len(fetched),
                },
                notes=[f"fetched {len(fetched)} of {len(records)} files across {len(parent_ids)} parent record(s); {len(skipped)} skipped"] if skipped else [f"fetched {len(fetched)} files across {len(parent_ids)} parent record(s)"],
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
