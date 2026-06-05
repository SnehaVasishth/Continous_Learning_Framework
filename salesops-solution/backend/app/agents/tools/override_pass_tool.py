"""Override-pass — second classification stage that applies the prior POC's
25KB override book verbatim.

Mirrors the prior Keysight POC's two-stage classifier:

  Stage 1 (Context-pass)  — `classify_intent` LLM pass with full email body +
                            thread + KB intent definitions. (Already runs.)
  Stage 2 (Override-pass) — THIS tool. Takes the Context-pass intent and asks
                            a SECOND LLM call: "Do any global override rules
                            apply? If yes, what's the corrected intent /
                            track / category?"
  Stage 3 (Test-pass)     — shadow regression on canonical Test cases. (Run
                            on demand from /learning, not per-pipeline.)

The Override-pass output is advisory: if it produces a high-confidence revised
intent that disagrees with the Context-pass, we honor the override and log
which rule fired. Otherwise the Context-pass intent stays.
"""
from __future__ import annotations

from typing import Any

from ...config import INTENTS
from ...services import openai_client
from ..base import AgentContext, Tool, ToolResult
from ..llm import ask_llm_traced


_TRACK_VALUES = ["trade", "som", "service_contract", "none", ""]
_CATEGORIES = [
    "KSO", "ISC_WO_RTK", "SALES_PO", "UNDELIVERABLE", "COLLECTIONS",
    "PORTAL_ADMIN", "BRAZIL_TAX", "AUTO_REPLY", "OTHERS", "",
]


_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "rules_fired",
        "rules_evaluated",
        "context_pass_intent",
        "revised_intent",
        "revised_track",
        "revised_category",
        "should_override",
        "override_confidence",
        "reasoning",
    ],
    "properties": {
        "rules_fired": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["rule_id", "rule_text", "evidence"],
                "properties": {
                    "rule_id": {"type": "string"},
                    "rule_text": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "rules_evaluated": {"type": "integer"},
        "context_pass_intent": {"type": "string", "enum": list(INTENTS) + [""]},
        "revised_intent": {"type": "string", "enum": list(INTENTS) + [""]},
        "revised_track": {"type": "string", "enum": _TRACK_VALUES},
        "revised_category": {"type": "string", "enum": _CATEGORIES},
        "should_override": {"type": "boolean"},
        "override_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string"},
    },
}


_SYSTEM_TEMPLATE = (
    "You are the Override-pass classifier for Keysight SalesOps. The Context-pass "
    "classifier has already chosen an intent based on the email body. Your job is "
    "to apply the GLOBAL OVERRIDE BOOK (verbatim from the prior Keysight POC) and "
    "decide whether any rule overrides the Context-pass result.\n\n"
    "GLOBAL OVERRIDE RULES. Evaluate each rule and report which fired:\n"
    "{global_rules_block}\n\n"
    "Behavior:\n"
    "  • For each rule, decide matched=true|false against this specific email.\n"
    "  • A rule that matched=true and disagrees with the Context-pass intent should "
    "    set should_override=true and produce a revised_intent.\n"
    "  • A rule that matches but agrees with the Context-pass result still appears "
    "    in rules_fired (audit trail), but should_override stays false.\n"
    "  • If NO rule matches, return should_override=false, revised_intent=context_pass_intent, "
    "    rules_fired=[].\n"
    "  • If multiple rules conflict, prefer the rule that appears EARLIER in the override book "
    "    (priority order: UNDELIVERABLE → AUTO_REPLY → BRAZIL_TAX → PORTAL_ADMIN → "
    "    COLLECTION → KSO → ISC_WO_RTK → SALES_PO → OTHERS).\n"
    "  • override_confidence is YOUR confidence in the override decision, 0..1.\n\n"
    "Be CONSERVATIVE. The Context-pass classifier has rich KB definitions and worked "
    "examples; you only override when a global rule clearly fires. Default to "
    "should_override=false when uncertain.\n\n"
    "Return strict JSON matching the contract."
)


def _build_system_prompt() -> str:
    """Compose the Override-pass system prompt from the live override-book list."""
    try:
        from ...kb_seeds.intent_definitions_v2 import GLOBAL_OVERRIDE_RULES
        rules = list(GLOBAL_OVERRIDE_RULES)
    except Exception:
        rules = []
    if not rules:
        global_rules_block = "  (no global override rules loaded)"
    else:
        lines: list[str] = []
        for i, r in enumerate(rules, start=1):
            lines.append(f"  R{i:02d}. {r}")
        global_rules_block = "\n".join(lines)
    return _SYSTEM_TEMPLATE.format(global_rules_block=global_rules_block)


class OverridePassTool(Tool):
    """Second classification pass — applies the global override book."""

    name = "override_pass"
    description = (
        "Override-pass classifier — applies the global override book to the "
        "Context-pass intent and reports which rules fired."
    )
    kb_namespaces: list[str] = ["intent"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            subject = inputs.get("subject") or email.get("subject") or ""
            sender = inputs.get("sender") or email.get("from") or ""
            body = inputs.get("body_english")
            if not body:
                body = ctx.intake.get("translated_body") or email.get("body") or ""
            context_pass_intent = inputs.get("context_pass_intent") or ctx.intake.get("intent") or ""

            if not body:
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data=_no_override_payload(context_pass_intent, "empty body"),
                )

            system_prompt = _build_system_prompt()
            input_preview = (
                f"From: {sender[:120]}\n"
                f"Subject: {subject[:200]}\n"
                f"Context-pass intent: {context_pass_intent}\n"
                f"Body: {body[:1500]}" + ("…" if len(body) > 1500 else "")
            )
            user_prompt = (
                f"FROM: {sender}\n"
                f"SUBJECT: {subject}\n"
                f"CONTEXT-PASS INTENT (from primary classifier): {context_pass_intent or '(none)'}\n"
                "BODY (translated to English):\n"
                f"{body[:6000]}\n\n"
                "Apply the global override book. Return JSON only."
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
                        schema_name="override_pass",
                        stage_hint="override_pass",
                    )
                    if parsed is not None:
                        meta = {**meta, "provider": f"OpenAI {meta.get('model')}"}
                if parsed is None:
                    parsed, raw, meta = ask_llm_traced(
                        system=system_prompt, user=user_prompt, json_only=True
                    )
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"llm_call_failed: {type(e).__name__}: {str(e)[:200]}",
                )

            out = parsed or {}
            rules_fired = out.get("rules_fired") or []
            if not isinstance(rules_fired, list):
                rules_fired = []
            should_override = bool(out.get("should_override"))
            revised_intent = (out.get("revised_intent") or "").strip()
            if revised_intent and revised_intent not in INTENTS:
                revised_intent = ""
            revised_track = (out.get("revised_track") or "").strip()
            revised_category = (out.get("revised_category") or "").strip()
            override_confidence = float(out.get("override_confidence") or 0.0)
            reasoning = out.get("reasoning") or ""

            # Sanity: should_override demands a revised_intent that differs from context_pass
            if should_override and (not revised_intent or revised_intent == context_pass_intent):
                should_override = False

            data = {
                "context_pass_intent": context_pass_intent,
                "rules_fired": rules_fired,
                "rules_evaluated": int(out.get("rules_evaluated") or len(rules_fired)),
                "revised_intent": revised_intent or context_pass_intent,
                "revised_track": revised_track,
                "revised_category": revised_category,
                "should_override": should_override,
                "override_confidence": round(override_confidence, 3),
                "reasoning": reasoning[:500],
                "input_preview": input_preview,
                "input_chars": len(user_prompt),
                "output_summary": (
                    f"OVERRIDE: {context_pass_intent} → {revised_intent} "
                    f"({len(rules_fired)} rules fired @ {override_confidence:.0%})"
                ) if should_override else (
                    f"no override ({len(rules_fired)} rules audited, {context_pass_intent} stands)"
                ),
                "processing_method": "llm_json_schema_strict",
                "provider": meta.get("provider", "unknown"),
                "prompt_system": meta.get("system_prompt", system_prompt),
                "prompt_user": meta.get("user_prompt", user_prompt),
                "provider_response_raw": raw,
                "response_schema": _SCHEMA,
                "schema_enforced": True,
                "kb_namespaces_consulted": ["intent"],
            }
            return ToolResult(name=self.name, ok=True, data=data)
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _no_override_payload(context_pass_intent: str, reason: str) -> dict:
    return {
        "context_pass_intent": context_pass_intent,
        "rules_fired": [],
        "rules_evaluated": 0,
        "revised_intent": context_pass_intent,
        "revised_track": "",
        "revised_category": "",
        "should_override": False,
        "override_confidence": 1.0,
        "reasoning": reason,
        "input_preview": "",
        "input_chars": 0,
        "output_summary": f"override_pass skipped: {reason}",
        "processing_method": "skipped",
        "provider": "n/a",
        "kb_namespaces_consulted": ["intent"],
    }
