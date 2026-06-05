# === v1.1 TASK-9 START ===
"""Shadow classifier — third LLM pass that runs alongside Context+Override.

Output is NOT consumed by downstream stages. It's logged-only so operators
can roll out a new prompt in shadow mode, compare agreement rate against
production, then promote when confident. Mirrors prior Keysight POC's "New
Rules Test" pass.

Toggled via the KB rule `shadow_classifier.enabled = true`. The shadow
prompt is also operator-tunable in the KB body.
"""
from __future__ import annotations

from typing import Any

from ... import kb
from ...config import INTENTS
from ...services import openai_client
from ..base import AgentContext, Tool, ToolResult


_DEFAULT_SHADOW_SYSTEM = (
    "You are the SHADOW classifier (Keysight POC 'New Rules Test' equivalent). "
    "Your output is NOT used by downstream stages. It is logged side-by-side "
    "with the primary classifier's output so operators can measure agreement "
    "and validate prompt changes before promoting them.\n\n"
    "Classify the email's intent strictly from the canonical list. Return "
    "one JSON object with: intent, intent_confidence, intent_reasoning, "
    "summary."
)


_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "intent_confidence", "intent_reasoning", "summary"],
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "intent_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "intent_reasoning": {"type": "string"},
        "summary": {"type": "string"},
    },
}


def _shadow_config() -> dict:
    """Returns the shadow classifier config from KB. Never raises."""
    try:
        from ...db import SessionLocal
        from ...models import KnowledgeRule
        db = SessionLocal()
        try:
            row = db.query(KnowledgeRule).filter_by(
                namespace="shadow_classifier", key="config",
            ).first()
            if row:
                return dict(row.body or {})
        finally:
            db.close()
    except Exception:
        pass
    return {}


class ShadowClassifierTool(Tool):
    """Logged-only third classifier slot for prompt A/B rollouts."""

    name = "shadow_classifier"
    description = "Shadow third-pass classifier — logged-only, not consumed by downstream stages."
    kb_namespaces: list[str] = ["shadow_classifier"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            cfg = _shadow_config()
            if not cfg.get("enabled", False):
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data={"skipped": True, "reason": "shadow_classifier.enabled=false"},
                )
            email = inputs.get("email") or ctx.email or {}
            primary_intent = inputs.get("primary_intent") or ctx.intake.get("intent") or ""
            body = inputs.get("body_english")
            if not body:
                body = ctx.intake.get("translated_body") or email.get("body") or ""
            subject = email.get("subject") or ""
            sender = email.get("from") or ""

            if not body:
                return ToolResult(
                    name=self.name, ok=True,
                    data={"skipped": True, "reason": "empty body"},
                )

            system_prompt = (cfg.get("system_prompt") or _DEFAULT_SHADOW_SYSTEM)
            user_prompt = (
                f"FROM: {sender}\n"
                f"SUBJECT: {subject}\n"
                f"PRIMARY CLASSIFIER INTENT (for agreement-rate measurement): {primary_intent}\n"
                "BODY:\n"
                f"{body[:6000]}\n\n"
                "Return JSON only."
            )

            parsed: dict | None = None
            raw: str = ""
            meta: dict[str, Any] = {}
            try:
                if openai_client.is_configured():
                    parsed, raw, meta = openai_client.ask_openai_json(
                        system=system_prompt,
                        user=user_prompt,
                        schema=_SCHEMA,
                        schema_name="shadow_classifier",
                        stage_hint="shadow_classifier",
                    )
            except Exception as e:
                return ToolResult(
                    name=self.name, ok=False,
                    error=f"shadow_call_failed: {type(e).__name__}: {str(e)[:200]}",
                )
            if parsed is None:
                return ToolResult(
                    name=self.name, ok=True,
                    data={"skipped": True, "reason": "OpenAI not configured or parse failed"},
                )

            shadow_intent = parsed.get("intent") or ""
            agreement = bool(primary_intent and shadow_intent == primary_intent)
            data = {
                "intent": shadow_intent,
                "intent_confidence": float(parsed.get("intent_confidence") or 0.0),
                "intent_reasoning": parsed.get("intent_reasoning") or "",
                "summary": parsed.get("summary") or "",
                "primary_intent": primary_intent,
                "agreement_with_primary": agreement,
                "input_chars": len(user_prompt),
                "output_summary": (
                    f"shadow={shadow_intent} primary={primary_intent} "
                    f"({'agree' if agreement else 'DISAGREE'})"
                ),
                "processing_method": "llm_json_schema_strict",
                "provider": meta.get("provider", f"OpenAI {meta.get('model','')}"),
                "prompt_system": system_prompt,
                "prompt_user": user_prompt,
                "provider_response_raw": raw,
                "response_schema": _SCHEMA,
                "schema_enforced": True,
                "kb_namespaces_consulted": ["shadow_classifier"],
            }
            return ToolResult(name=self.name, ok=True, data=data)
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
# === v1.1 TASK-9 END ===
