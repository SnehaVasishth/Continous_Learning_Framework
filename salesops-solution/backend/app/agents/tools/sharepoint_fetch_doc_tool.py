"""Fetch documents from SharePoint Online via Microsoft Graph.

This is a graceful stub: if `SHAREPOINT_TENANT_ID` + `SHAREPOINT_CLIENT_ID` +
`SHAREPOINT_CLIENT_SECRET` + `SHAREPOINT_SITE_ID` are not configured, the tool
returns ok=True with `count=0` and a note explaining it's not configured.

When credentials are present, it does the OAuth client-credentials flow against
Microsoft identity, then uses the Graph driveItem search to find files matching
a customer code or name and downloads them into UPLOADS for OCR.

Reference:
  https://learn.microsoft.com/graph/api/driveitem-search
  https://learn.microsoft.com/graph/auth-v2-service
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import requests

from ...config import UPLOADS
from ..base import AgentContext, Tool, ToolResult

log = logging.getLogger("sharepoint_fetch_doc_tool")


_SAFE_CHAR = re.compile(r"[^A-Za-z0-9._\-]")


def _safe_filename(name: str) -> str:
    name = (name or "attachment.bin").strip().replace("\\", "_").replace("/", "_")
    return _SAFE_CHAR.sub("_", name)[:120] or "attachment.bin"


def _credentials_present() -> bool:
    return all(
        os.environ.get(k, "").strip()
        for k in ("SHAREPOINT_TENANT_ID", "SHAREPOINT_CLIENT_ID", "SHAREPOINT_CLIENT_SECRET", "SHAREPOINT_SITE_ID")
    )


def _get_token() -> tuple[str | None, str | None]:
    tenant = os.environ["SHAREPOINT_TENANT_ID"].strip()
    client_id = os.environ["SHAREPOINT_CLIENT_ID"].strip()
    client_secret = os.environ["SHAREPOINT_CLIENT_SECRET"].strip()
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        resp = requests.post(url, data=data, timeout=30)
    except requests.RequestException as e:
        return None, f"network: {e}"
    if resp.status_code != 200:
        return None, f"http_{resp.status_code}: {resp.text[:200]}"
    try:
        return resp.json().get("access_token"), None
    except Exception as e:
        return None, f"parse: {type(e).__name__}: {e}"


class SharePointFetchDocTool(Tool):
    """Search a SharePoint document library for files matching a query and download matches for OCR."""

    name = "sharepoint_fetch_doc"
    description = "Search SharePoint and download matching docs for OCR. Stub when credentials absent."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            query = inputs.get("query") or inputs.get("customer_code") or ""
            max_files = int(inputs.get("max_files") or 5)
            if not _credentials_present():
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data={"query": query, "fetched": [], "count": 0, "configured": False},
                    notes=["sharepoint_not_configured (set SHAREPOINT_TENANT_ID + SHAREPOINT_CLIENT_ID + SHAREPOINT_CLIENT_SECRET + SHAREPOINT_SITE_ID)"],
                )
            if not query:
                return ToolResult(name=self.name, ok=False, error="missing query")

            token, err = _get_token()
            if not token:
                return ToolResult(name=self.name, ok=False, error=f"sharepoint_auth_failed: {err}")

            site_id = os.environ["SHAREPOINT_SITE_ID"].strip()
            search_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root/search(q='{query[:50]}')"
            headers = {"Authorization": f"Bearer {token}"}
            try:
                sresp = requests.get(search_url, headers=headers, timeout=30)
            except requests.RequestException as e:
                return ToolResult(name=self.name, ok=False, error=f"sharepoint_search_network: {e}")
            if sresp.status_code != 200:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"sharepoint_search_http_{sresp.status_code}: {sresp.text[:200]}",
                )

            items = (sresp.json() or {}).get("value") or []
            files = [it for it in items if "file" in it][:max_files]
            if not files:
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data={"query": query, "fetched": [], "count": 0, "configured": True},
                    notes=["no_files_matching_query"],
                )

            fetched: list[dict] = []
            skipped: list[dict] = []
            for item in files:
                title = item.get("name") or "untitled"
                download_url = item.get("@microsoft.graph.downloadUrl")
                if not download_url:
                    skipped.append({"title": title, "reason": "no_download_url"})
                    continue
                try:
                    blob_resp = requests.get(download_url, timeout=60, stream=True)
                except requests.RequestException as e:
                    skipped.append({"title": title, "reason": f"download_network: {e}"})
                    continue
                if blob_resp.status_code != 200:
                    skipped.append({"title": title, "reason": f"download_http_{blob_resp.status_code}"})
                    continue

                stamped = f"sp_{uuid.uuid4().hex[:8]}_{_safe_filename(title)}"
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
                    "size_bytes": bytes_written,
                    "sha256": hasher.hexdigest(),
                    "sharepoint_id": item.get("id"),
                    "web_url": item.get("webUrl"),
                })

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "query": query,
                    "fetched": fetched,
                    "skipped": skipped,
                    "count": len(fetched),
                    "configured": True,
                },
                notes=[f"fetched {len(fetched)} of {len(files)} matching files"] if files else [],
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
