"""Schema-driven structured extraction (Stage 2 sub-step 2.2).

Renamed from `llm_extract` per user feedback — the original name was opaque.
This is the step where the LLM, driven by the intent's KB extract_schema rule,
produces the structured JSON used by Stages 3-5 (PO fields, work-order fields,
SSD change details, etc.).

Provider chain inside `run_extract`: OpenAI gpt-5.2 with json_object mode →
Claude legacy fallback. Result is then validated and coerced against the KB
schema's field types (string/int/number/date/list/bool) so Stages 3+ get
correctly-typed values.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ... import kb
from ..base import AgentContext, Tool, ToolResult
from ..extract import run_extract


_INT_TYPES = {"int", "integer", "number_int"}
_FLOAT_TYPES = {"number", "float", "decimal"}
_DATE_TYPES = {"iso date", "iso_date", "date"}
_LIST_TYPES = {"list", "array"}


class SchemaExtractTool(Tool):
    """Schema-driven extraction: LLM call, KB-schema validation + coercion.

    Surfaces every field the trace UI needs:
      - input_preview, prompt_system, prompt_user, provider_response_raw
      - kb_schema_used (the rule key + the field list driving this run)
      - extracted_fields (the structured output, with private _-prefixed keys stripped for display)
      - validation_notes (which fields were coerced or flagged)
    """

    name = "schema_extract"
    description = (
        "Schema-driven LLM extraction: pulls structured fields from the email + attachments using "
        "the intent-specific KB schema (extract_schema namespace). OpenAI gpt-5.2 with strict JSON output."
    )
    kb_namespaces = ["extract_schema"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            intake = inputs.get("intake") or ctx.intake or {}
            if not email:
                return ToolResult(name=self.name, ok=False, error="missing email")

            # Best-effort load thread context so extraction sees the full conversation
            # (e.g. a revised qty in message 5 of an 8-message PO thread).
            thread_summary: str | None = None
            try:
                from ...models import Email as _EmailModel, Pipeline as _PipelineModel
                from ...services.email_thread import walk_thread, thread_summary_for_prompt
                if ctx.pipeline_id:
                    pipe_row = ctx.db.get(_PipelineModel, ctx.pipeline_id)
                    if pipe_row and pipe_row.email_id:
                        seed = ctx.db.get(_EmailModel, pipe_row.email_id)
                        if seed:
                            chain = walk_thread(ctx.db, seed)
                            if chain and len(chain) > 1:
                                thread_summary = thread_summary_for_prompt(chain)
            except Exception:
                thread_summary = None

            extracted = run_extract(email=email, intake=intake, thread_summary=thread_summary)

            provider = extracted.pop("_provider", None) if isinstance(extracted, dict) else None
            provider_meta = extracted.pop("_provider_meta", {}) if isinstance(extracted, dict) else {}
            prompt_system = extracted.pop("_prompt_system", "") if isinstance(extracted, dict) else ""
            prompt_user = extracted.pop("_prompt_user", "") if isinstance(extracted, dict) else ""
            provider_response_raw = extracted.pop("_provider_response_raw", "") if isinstance(extracted, dict) else ""

            if isinstance(extracted, dict) and "_extract_error" in extracted:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"extract_failed: {extracted['_extract_error']}",
                    data={
                        **extracted,
                        "provider": provider,
                        "provider_meta": provider_meta,
                        "prompt_system": prompt_system,
                        "prompt_user": prompt_user,
                        "provider_response_raw": provider_response_raw,
                    },
                )

            intent = intake.get("intent") or "general_inquiry"
            schema_body = kb.extract_schema_for(intent) or {}
            schema_key = _kb_schema_key_for(intent)
            coerced, notes = _validate_and_coerce(extracted, schema_body)
            coerced["_intent"] = intent

            field_count = len((schema_body or {}).get("fields") or [])
            required_count = sum(1 for f in (schema_body or {}).get("fields") or [] if f.get("required"))
            populated_required = sum(
                1
                for f in (schema_body or {}).get("fields") or []
                if f.get("required") and (coerced.get(f.get("name")) not in (None, ""))
            )
            display_fields = {k: v for k, v in coerced.items() if not k.startswith("_")}

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    **coerced,
                    "provider": provider,
                    "provider_meta": provider_meta,
                    "prompt_system": prompt_system,
                    "prompt_user": prompt_user,
                    "provider_response_raw": provider_response_raw,
                    "kb_namespaces_consulted": ["extract_schema"],
                    "kb_schema_key_used": schema_key,
                    "kb_schema_intent": intent,
                    "kb_schema_field_count": field_count,
                    "kb_schema_required_count": required_count,
                    "kb_schema_required_populated": populated_required,
                    "kb_schema_fields": (schema_body or {}).get("fields") or [],
                    "extracted_fields": display_fields,
                    "validation_notes": notes,
                    "input_preview": (prompt_user[:400] + "…") if len(prompt_user) > 400 else prompt_user,
                    "input_chars": len(prompt_user),
                    "output_summary": (
                        f"{len(display_fields)} fields extracted "
                        f"({populated_required}/{required_count} required populated) "
                        f"via {provider or 'unknown provider'}"
                    ),
                    "processing_method": "openai_json_object" if provider and "OpenAI" in provider else "llm_validate_coerce",
                },
                notes=notes,
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _kb_schema_key_for(intent: str) -> str | None:
    """Return the KB rule key whose extract_schema covers this intent (best effort)."""
    try:
        from ...db import SessionLocal
        from ... import kb as _kb
        db = SessionLocal()
        try:
            for r in _kb.list_rules(db, "extract_schema"):
                applies = (r.body or {}).get("applies_to_intents") or []
                if intent in applies:
                    return r.key
        finally:
            db.close()
    except Exception:
        pass
    return None


def _validate_and_coerce(extracted: dict, schema_body: dict) -> tuple[dict, list[str]]:
    out = dict(extracted or {})
    notes: list[str] = []
    fields = (schema_body or {}).get("fields") or []
    if not fields:
        return out, notes

    for f in fields:
        name = f.get("name")
        if not name:
            continue
        ftype = (f.get("type") or "any").lower()
        required = bool(f.get("required"))
        val = out.get(name)

        if val is None or val == "":
            if required:
                notes.append(f"missing required field: {name}")
            continue

        coerced, note = _coerce(val, ftype, name)
        if note:
            notes.append(note)
        out[name] = coerced

    return out, notes


def _coerce(val: Any, ftype: str, name: str) -> tuple[Any, str | None]:
    t = ftype.lower().strip()
    try:
        if t in _INT_TYPES:
            if isinstance(val, bool):
                return int(val), None
            if isinstance(val, int):
                return val, None
            return int(float(str(val))), f"coerced {name}: {type(val).__name__} -> int"
        if t in _FLOAT_TYPES:
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return float(val), None
            return float(str(val)), f"coerced {name}: {type(val).__name__} -> float"
        if t in _DATE_TYPES:
            if isinstance(val, str):
                try:
                    parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    iso = parsed.date().isoformat()
                    if iso == val[: len(iso)]:
                        return val, None
                    return iso, f"coerced {name}: normalized date -> {iso}"
                except Exception:
                    return val, f"date_unparseable: {name}={val!r}"
            return val, f"date_unparseable: {name}={val!r}"
        if t == "bool":
            if isinstance(val, bool):
                return val, None
            if isinstance(val, str):
                return val.strip().lower() in ("true", "1", "yes", "y"), f"coerced {name}: str -> bool"
            return bool(val), f"coerced {name}: -> bool"
        if t in _LIST_TYPES or t.startswith("list"):
            if isinstance(val, list):
                return val, None
            return [val], f"coerced {name}: scalar -> list"
        return val, None
    except Exception as e:
        return val, f"coerce_failed: {name} ({ftype}): {type(e).__name__}"


# Backwards-compat alias so any code still importing LlmExtractTool keeps working.
LlmExtractTool = SchemaExtractTool
