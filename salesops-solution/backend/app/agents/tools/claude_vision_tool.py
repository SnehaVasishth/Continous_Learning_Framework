"""Vision OCR over image attachments via the underlying SDK's vision tool."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import UPLOADS
from ..base import AgentContext, Tool, ToolResult
from ..llm import ask_llm


_DEFAULT_SYSTEM = (
    "You are a document-intelligence vision agent. Read every attached image and return strict JSON: "
    "{\"text\": full extracted text, \"tables\": [{\"caption\": str|null, \"rows\": [[str,...]]}], "
    "\"fields\": {key:value}, \"notes\": str|null}. "
    "Pull every visible field: PO numbers, line items, totals, dates, addresses, signatures. "
    "If the image is a BOM or table, fill the tables[] array. Use null where information is genuinely absent."
)


class ClaudeVisionTool(Tool):
    """Run vision OCR on one or more image attachments and return extracted text + tables."""

    name = "vision_ocr"
    description = "ZBrain vision OCR — extracts text, tables, and fields from image attachments."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            raw_paths = inputs.get("image_paths") or inputs.get("paths") or []
            if isinstance(raw_paths, (str, Path)):
                raw_paths = [raw_paths]
            if not raw_paths:
                return ToolResult(name=self.name, ok=False, error="no image_paths provided")

            resolved: list[Path] = []
            missing: list[str] = []
            for p in raw_paths:
                pth = Path(p)
                if not pth.is_absolute():
                    pth = Path(UPLOADS) / pth
                if pth.exists():
                    resolved.append(pth)
                else:
                    missing.append(str(pth))
            if not resolved:
                return ToolResult(name=self.name, ok=False, error=f"no readable images; missing={missing}")

            system = inputs.get("system") or _DEFAULT_SYSTEM
            user = inputs.get("user") or (
                "Extract all visible text, tables, and structured fields from the attached image(s). JSON only."
            )
            out = ask_llm(
                system=system,
                user=user,
                json_only=True,
                image_paths=[str(p) for p in resolved],
            )
            data = out if isinstance(out, dict) else {"text": str(out)}
            data["_image_count"] = len(resolved)
            data["_images_seen"] = [p.name for p in resolved]
            notes = [f"missing image: {m}" for m in missing]
            return ToolResult(name=self.name, ok=True, data=data, notes=notes)
        except ValueError as e:
            return ToolResult(name=self.name, ok=False, error=f"vision_parse_failed: {str(e)[:300]}")
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
