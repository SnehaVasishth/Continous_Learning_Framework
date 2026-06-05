"""Read a file from UPLOADS and return text + content-type."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import UPLOADS
from ..base import AgentContext, Tool, ToolResult
from ..extract import _read_docx_text, _read_pdf_text, _read_xlsx_text


_EXT_TO_TYPE = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".docx": "docx",
    ".doc": "docx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".webp": "image",
    ".txt": "text",
    ".csv": "text",
    ".json": "text",
}


class ReadTool(Tool):
    """Read an attachment from the UPLOADS dir, dispatch to the right extractor."""

    name = "read_attachment"
    description = "Read PDF/XLSX/DOCX/text/image from uploads dir; returns content + type."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            name = inputs.get("name") or inputs.get("path")
            if not name:
                return ToolResult(name=self.name, ok=False, error="missing 'name' or 'path'")
            path = Path(name)
            if not path.is_absolute():
                path = Path(UPLOADS) / path
            if not path.exists():
                return ToolResult(name=self.name, ok=False, error=f"file not found: {path}")

            ext = path.suffix.lower()
            kind = inputs.get("type") or _EXT_TO_TYPE.get(ext) or "unknown"

            content = ""
            if kind == "pdf":
                content = _read_pdf_text(path)
            elif kind == "xlsx":
                content = _read_xlsx_text(path)
            elif kind == "docx":
                content = _read_docx_text(path)
            elif kind == "image":
                content = ""
            elif kind == "text":
                content = path.read_text(encoding="utf-8", errors="replace")
            else:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    content = ""

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "path": str(path.resolve()),
                    "filename": path.name,
                    "content_type": kind,
                    "size_bytes": path.stat().st_size,
                    "content": content,
                    "chars": len(content),
                },
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
