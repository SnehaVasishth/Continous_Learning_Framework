"""Document text extraction with three provider adapters in priority order:

1. **Lambda (Azure DocIntel-wrapped via AWS Lambda)** — if `LAMBDA_DOCEXTRACT_URL`
   env is set. POSTs `{"pdf_url": "<url>"}` to the Lambda; returns
   `{"content": "...", "filePath": "<presigned-S3>"}`. Works on URL-accessible
   files (Salesforce / SharePoint presigned URLs, or local files served via
   `APP_BASE_URL/files/uploads/<name>` when APP_BASE_URL is publicly reachable).

2. **Azure Form Recognizer direct** — if `AZURE_DOCINTEL_ENDPOINT` +
   `AZURE_DOCINTEL_KEY` are set. Posts file bytes to Azure
   prebuilt-document model and polls for results.

3. **Local extractors** (pypdf / openpyxl / python-docx) — always available
   as a graceful fallback so the demo runs without any cloud creds.

Stage 1 callers can pass `max_pages=3` to enable light extraction; Stage 2
omits the cap to extract everything.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ...config import UPLOADS
from ..base import AgentContext, Tool, ToolResult
from ..extract import _read_docx_text, _read_pdf_text, _read_xlsx_text
from . import _pdf_convert


class AzureDocIntelligenceTool(Tool):
    """Document text extraction with Lambda > Azure-direct > local extractor priority chain."""

    name = "azure_doc_intelligence"
    description = (
        "Document text extraction with format-aware routing: PDF/image → Azure Document Intelligence; "
        "XLSX → openpyxl; DOCX → python-docx (scanned DOCX is converted to PDF and run through Azure)."
    )
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            url = inputs.get("url")
            name = inputs.get("name") or inputs.get("path")
            max_pages = inputs.get("max_pages")  # None = unlimited; 3 for Stage 1 light extract

            if not url and not name:
                return ToolResult(name=self.name, ok=False, error="missing 'url' or 'name'/'path'")

            # Resolve local path if we have a name
            local_path: Path | None = None
            if name:
                p = Path(name)
                if not p.is_absolute():
                    p = Path(UPLOADS) / p
                if p.exists():
                    local_path = p

            lambda_url = (
                os.environ.get("LAMBDA_DOCEXTRACT_URL", "").strip()
                or "https://5lmviqwda5jtgple2hnad7vibq0qqlnt.lambda-url.us-east-2.on.aws"
            )
            azure_endpoint = os.environ.get("AZURE_DOCINTEL_ENDPOINT", "").strip()
            azure_key = os.environ.get("AZURE_DOCINTEL_KEY", "").strip()
            # Read live env first; if unset (e.g. very early after startup, before
            # the cloudflared reader thread exported it), fall back to the tunnel
            # service's in-process module-level URL. This makes the Lambda branch
            # robust to startup races where stage 2.1 fires within milliseconds of
            # the tunnel coming up.
            app_base_url = os.environ.get("APP_BASE_URL", "").strip()
            if not app_base_url or _is_localhost(app_base_url):
                try:
                    from ...services import tunnel as _tunnel
                    tunnel_url = (_tunnel.current_url() or "").strip()
                    if tunnel_url:
                        app_base_url = tunnel_url
                except Exception:
                    pass

            # ----------------------------------------------------------------
            # Format-aware routing:
            #   .xlsx/.xls  → openpyxl (structured format; no OCR needed)
            #   .docx/.doc  → python-docx; if it returns < 30 non-whitespace chars,
            #                 fall through to convert+Lambda (scanned/legacy DOCX)
            #   .pdf/image  → Lambda (Azure DocIntel)
            # ----------------------------------------------------------------
            ext = local_path.suffix.lower() if local_path else ""

            if local_path and ext in (".xlsx", ".xls"):
                text = _read_xlsx_text(local_path)
                if max_pages and text:
                    lines = text.split("\n")
                    cap = 50 * max_pages
                    if len(lines) > cap:
                        text = "\n".join(lines[:cap]) + f"\n…[truncated to first {max_pages} pages]"
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data={
                        "provider": "openpyxl (structured XLSX reader)",
                        "provider_key": "openpyxl",
                        "filename": local_path.name,
                        "text": text or "",
                        "char_count": len(text or ""),
                        "tables": [],
                        "key_value_pairs": [],
                        "max_pages_requested": max_pages,
                        "routing_rationale": "XLSX is a structured format — openpyxl is the canonical reader; no OCR needed",
                    },
                    notes=[],
                )

            if local_path and ext in (".docx", ".doc"):
                docx_text = _read_docx_text(local_path) or ""
                meaningful_chars = len(docx_text.strip())
                if meaningful_chars >= 30:
                    return ToolResult(
                        name=self.name,
                        ok=True,
                        data={
                            "provider": "python-docx (structured DOCX reader)",
                            "provider_key": "python_docx",
                            "filename": local_path.name,
                            "text": docx_text,
                            "char_count": len(docx_text),
                            "tables": [],
                            "key_value_pairs": [],
                            "max_pages_requested": max_pages,
                            "routing_rationale": "DOCX is a structured format — python-docx returned the document text directly.",
                        },
                        notes=[],
                    )
                # Library returned almost nothing — fall through to convert+Lambda for OCR.

            # Provider 1: Lambda (preferred when configured AND we have a URL OR public APP_BASE_URL)
            if lambda_url:
                public_url = url
                converted_pdf_path: Path | None = None
                converted_from_ext: str | None = None
                # Only convert when we're falling through from an empty-DOCX (sparse) extraction.
                # XLSX never reaches here. PDFs/images skip conversion entirely.
                if local_path and ext in (".docx", ".doc"):
                    try:
                        converted_pdf_path = _pdf_convert.to_pdf(local_path, UPLOADS / "_converted")
                        if converted_pdf_path:
                            converted_from_ext = ext
                    except Exception as e:
                        return ToolResult(
                            name=self.name, ok=False,
                            error=f"docx_to_pdf_failed: {type(e).__name__}: {str(e)[:200]}",
                        )

                if not public_url and app_base_url and not _is_localhost(app_base_url):
                    target = converted_pdf_path or local_path
                    if target:
                        if converted_pdf_path:
                            public_url = f"{app_base_url.rstrip('/')}/files/uploads/_converted/{converted_pdf_path.name}"
                        else:
                            public_url = f"{app_base_url.rstrip('/')}/files/uploads/{target.name}"
                if public_url:
                    res = self._call_lambda(lambda_url, public_url, max_pages)
                    if res.get("ok"):
                        notes = list(res.get("notes") or [])
                        if converted_from_ext:
                            notes.append(
                                f"library extraction returned <30 chars for {converted_from_ext}; "
                                f"DOCX had little extractable text; converted to PDF and ran Azure Document Intelligence."
                            )
                        # Cost: record per-page Azure DocIntel charge against
                        # the current pipeline context. Lambda wraps the same
                        # Layout model, so we charge at the Layout rate.
                        try:
                            from ..llm import record_ocr_cost
                            pages = _count_pdf_pages(converted_pdf_path or local_path) if (converted_pdf_path or local_path) else max_pages or 1
                            record_ocr_cost(
                                model_hint="azure-doc-intelligence-layout",
                                pages=pages,
                                tool="azure_doc_intelligence",
                            )
                        except Exception:
                            pass
                        return ToolResult(
                            name=self.name,
                            ok=True,
                            data={
                                "provider": "AWS Lambda (Azure Document Intelligence)",
                                "provider_key": "lambda_azure",
                                "filename": local_path.name if local_path else _basename_from_url(public_url),
                                "source_url": public_url,
                                "converted_from": converted_from_ext,
                                "text": res.get("text", ""),
                                "char_count": len(res.get("text", "")),
                                "stored_at": res.get("filePath"),
                                "tables": [],
                                "key_value_pairs": [],
                                "max_pages_requested": max_pages,
                                "routing_rationale": (
                                    f"Empty/sparse {converted_from_ext} extraction — converted to PDF and OCRed via Azure DocIntel"
                                    if converted_from_ext
                                    else "PDF/image — Azure Document Intelligence is the canonical OCR + layout extractor"
                                ),
                            },
                            notes=notes,
                        )
                    # fall through to next adapter on Lambda failure
                # If we have no URL and no public APP_BASE_URL, skip Lambda silently and try Azure-direct

            # Provider 2: Azure-direct (needs the actual file bytes; only works on local file)
            if azure_endpoint and azure_key and local_path:
                az = self._call_azure(local_path, azure_endpoint, azure_key)
                if az.get("ok"):
                    # Cost: per-page Azure DocIntel Layout charge.
                    try:
                        from ..llm import record_ocr_cost
                        pages = _count_pdf_pages(local_path)
                        record_ocr_cost(
                            model_hint="azure-doc-intelligence-layout",
                            pages=pages,
                            tool="azure_doc_intelligence",
                        )
                    except Exception:
                        pass
                    return ToolResult(
                        name=self.name,
                        ok=True,
                        data={
                            "provider": "Azure Document Intelligence (direct)",
                            "provider_key": "azure_direct",
                            "filename": local_path.name,
                            "text": az.get("text", ""),
                            "char_count": len(az.get("text", "")),
                            "tables": az.get("tables", []),
                            "key_value_pairs": az.get("key_value_pairs", []),
                            "max_pages_requested": max_pages,
                        },
                        notes=az.get("notes") or [],
                    )

            # Provider 3: local extractor fallback (always available)
            if local_path:
                result = self._fallback(local_path, max_pages)
                # Record a token cost against the in-house OCR rate so the
                # Cost dashboard reflects extraction even when the cloud
                # adapters were unreachable. Per-page rate is set to a tiny
                # number in the rate book (in-house-ocr); the line is
                # primarily for coverage accounting.
                try:
                    from ..llm import record_ocr_cost
                    record_ocr_cost(
                        model_hint="in-house-ocr",
                        pages=_count_pdf_pages(local_path),
                        tool="azure_doc_intelligence",
                    )
                except Exception:
                    pass
                return result

            return ToolResult(
                name=self.name,
                ok=False,
                error="no extraction provider available (Lambda needs URL or public APP_BASE_URL; Azure-direct needs local file; local fallback needs file path)",
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")

    def _call_lambda(self, lambda_url: str, pdf_url: str, max_pages: int | None) -> dict:
        try:
            import requests
        except Exception as e:
            return {"ok": False, "error": f"requests unavailable: {e}"}
        try:
            body: dict[str, Any] = {"pdf_url": pdf_url}
            if max_pages:
                body["max_pages"] = max_pages
            resp = requests.post(
                lambda_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=120,
            )
            if resp.status_code != 200:
                return {"ok": False, "error": f"lambda http {resp.status_code}: {resp.text[:200]}"}
            payload = resp.json() if resp.content else {}
            text = payload.get("content") or ""
            if not text:
                return {"ok": False, "error": "lambda returned empty content"}
            notes: list[str] = []
            if payload.get("filePath"):
                notes.append(f"file mirrored to S3: {payload['filePath'][:100]}…")
            return {"ok": True, "text": text, "filePath": payload.get("filePath"), "notes": notes}
        except Exception as e:
            return {"ok": False, "error": f"lambda_call_failed: {type(e).__name__}: {str(e)[:200]}"}

    def _call_azure(self, path: Path, endpoint: str, key: str) -> dict:
        try:
            import requests
        except Exception as e:
            return {"ok": False, "error": f"requests unavailable: {e}"}
        url = endpoint.rstrip("/") + "/formrecognizer/documentModels/prebuilt-document:analyze?api-version=2023-07-31"
        try:
            with path.open("rb") as fh:
                resp = requests.post(
                    url,
                    headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/octet-stream"},
                    data=fh.read(),
                    timeout=60,
                )
            if resp.status_code not in (200, 202):
                return {"ok": False, "error": f"http {resp.status_code}: {resp.text[:200]}"}
            op_loc = resp.headers.get("Operation-Location") or resp.headers.get("operation-location")
            if not op_loc:
                payload = resp.json() if resp.content else {}
                return self._parse_azure_payload(payload)
            import time as _time
            for _ in range(30):
                _time.sleep(1.0)
                poll = requests.get(op_loc, headers={"Ocp-Apim-Subscription-Key": key}, timeout=30)
                if poll.status_code != 200:
                    return {"ok": False, "error": f"poll http {poll.status_code}"}
                pj = poll.json()
                status = pj.get("status")
                if status == "succeeded":
                    return self._parse_azure_payload(pj.get("analyzeResult") or {})
                if status == "failed":
                    return {"ok": False, "error": json.dumps(pj.get("error") or {})[:200]}
            return {"ok": False, "error": "azure_timeout"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    def _parse_azure_payload(self, payload: dict) -> dict:
        text = payload.get("content") or ""
        tables: list[dict] = []
        for t in payload.get("tables") or []:
            cells = t.get("cells") or []
            row_count = t.get("rowCount") or 0
            col_count = t.get("columnCount") or 0
            grid = [["" for _ in range(col_count)] for _ in range(row_count)]
            for c in cells:
                r = c.get("rowIndex") or 0
                k = c.get("columnIndex") or 0
                if 0 <= r < row_count and 0 <= k < col_count:
                    grid[r][k] = c.get("content") or ""
            tables.append({"row_count": row_count, "col_count": col_count, "rows": grid})
        kv: list[dict] = []
        for pair in payload.get("keyValuePairs") or []:
            k = (pair.get("key") or {}).get("content")
            v = (pair.get("value") or {}).get("content")
            if k:
                kv.append({"key": k, "value": v})
        return {"ok": True, "text": text, "tables": tables, "key_value_pairs": kv}

    def _fallback(self, path: Path, max_pages: int | None) -> ToolResult:
        ext = path.suffix.lower()
        text = ""
        if ext == ".pdf":
            text = _read_pdf_text(path)
            if max_pages and text:
                # Heuristic page-cap: PDF text from pypdf typically separates pages with newlines.
                # Take roughly the first max_pages * 50 lines (~ a 3-page PDF averages 150 lines).
                lines = text.split("\n")
                approx_lines_per_page = max(1, len(lines) // max(1, _count_pdf_pages(path)))
                cap = approx_lines_per_page * max_pages
                if len(lines) > cap:
                    text = "\n".join(lines[:cap]) + f"\n…[truncated to first {max_pages} pages by Stage-1 light extraction]"
        elif ext in (".xlsx", ".xls"):
            text = _read_xlsx_text(path)
        elif ext in (".docx", ".doc"):
            text = _read_docx_text(path)
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
        return ToolResult(
            name=self.name,
            ok=True,
            data={
                "provider": "Local extractor (pypdf / openpyxl / python-docx)",
                "provider_key": "local_fallback",
                "filename": path.name,
                "text": text,
                "char_count": len(text),
                "tables": [],
                "key_value_pairs": [],
                "max_pages_requested": max_pages,
            },
            notes=[
                "Lambda + Azure-direct both unavailable for this attachment "
                "(no public URL reachable, or cloud calls failed); used local "
                "extractor fallback so the pipeline could still proceed."
            ],
        )


def _is_localhost(url: str) -> bool:
    return any(host in url for host in ("localhost", "127.0.0.1", "0.0.0.0"))


def _basename_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0] or "document.pdf"


def _count_pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:
        return 1
