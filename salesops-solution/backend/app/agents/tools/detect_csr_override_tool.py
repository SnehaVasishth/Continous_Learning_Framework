"""CSR-instruction override detection (Stage 1 sub-step 1.7b).

Detects when a CSR has forwarded an email with explicit override instructions
that should supersede the auto-classifier. Examples:

  • "Please process this as a hold release, not a new PO."
  • "DO NOT auto-respond — escalate to legal team."
  • "Force HITL — customer escalation, executive review."
  • "Route to service team — wrong inbox."

Output is advisory and surfaced for the trace UI / HITL screen. Stage 1 keeps
the auto-classifier intent as primary, but if `has_override=True` the
orchestrator can downgrade autonomy_tier to L2_HITL or override the intent
based on `override_kind`.
"""
from __future__ import annotations

from typing import Any

from ...config import INTENTS
from ...services import openai_client
from ..base import AgentContext, Tool, ToolResult
from ..llm import ask_llm_traced


_OVERRIDE_KINDS = [
    "none",
    "intent_override",
    "do_not_auto",
    "force_hitl",
    "force_track",
    "route_to_team",
]

_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "has_override",
        "override_kind",
        "override_instruction",
        "override_intent",
        "override_track",
        "override_team",
        "reasoning",
        "confidence",
    ],
    "properties": {
        "has_override": {"type": "boolean"},
        "override_kind": {"type": "string", "enum": _OVERRIDE_KINDS},
        "override_instruction": {
            "type": "string",
            "description": "Verbatim CSR instruction text extracted from the email (empty string if none).",
        },
        "override_intent": {
            "type": "string",
            "enum": list(INTENTS) + [""],
            "description": "If override_kind=intent_override, the canonical intent the CSR named. Empty string otherwise.",
        },
        "override_track": {
            "type": "string",
            "enum": ["trade", "som", "service_contract", "none", ""],
            "description": "If override_kind=force_track, the track the CSR named. Empty string otherwise.",
        },
        "override_team": {
            "type": "string",
            "description": "If override_kind=route_to_team, the named team (e.g., 'legal', 'service', 'credit'). Empty string otherwise.",
        },
        "reasoning": {
            "type": "string",
            "description": "1 sentence quoting the CSR instruction and explaining why it overrides the classifier.",
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


_SYSTEM = (
    "You are a CSR-override detector for an enterprise B2B SalesOps inbox. "
    "Your job is to detect when a Keysight CSR (Customer Service Rep) has "
    "forwarded a customer email with EXPLICIT INSTRUCTIONS that override the "
    "automated intent classifier.\n\n"
    "CSR overrides typically appear in one of these forms:\n"
    "  • An added line at the top of a forwarded email, e.g. `\"FYI - process as hold release, not new PO\"`\n"
    "  • A directive, e.g. `\"Do NOT auto-respond. Escalate to legal team.\"`\n"
    "  • A re-routing instruction, e.g. `\"Wrong inbox, please route to service team.\"`\n"
    "  • An intent correction, e.g. `\"This is actually a service contract renewal, not a quote.\"`\n"
    "  • A force-HITL flag, e.g. `\"Customer is on credit hold, needs CSR review before any reply.\"`\n\n"
    "The CSR is typically internal (sender domain matches the company, or the "
    "instruction sits ABOVE a `From:`/`-----Original Message-----`/`Begin forwarded message:` "
    "delimiter that introduces the original customer mail).\n\n"
    "Distinguish between:\n"
    "  • CSR override (what you flag): internal staff overriding the classifier\n"
    "  • Customer instruction (NOT an override): the customer themselves saying "
    "    'this is urgent' or 'please process as quote conversion'. Customer wording "
    "    is just normal classification signal; the classifier already considers it.\n\n"
    "OUTPUT KINDS:\n"
    "  • `none`: no CSR override present\n"
    "  • `intent_override`: CSR named a specific canonical intent (set override_intent)\n"
    "  • `do_not_auto`: CSR said 'do not auto-respond' / 'no automated reply' / 'manual handling only'\n"
    "  • `force_hitl`: CSR said 'needs review' / 'escalate' / 'flag for CSR' / 'HITL only'\n"
    "  • `force_track`: CSR named a workflow track (trade/som/service_contract)\n"
    "  • `route_to_team`: CSR routed to a named team (legal, credit, service, etc.)\n\n"
    "When in doubt, return `has_override=False` with `override_kind=none`. False positives "
    "here cost the CSR trust; better to miss a soft override than fabricate one. "
    "Only set has_override=True when there is CLEAR INTERNAL CSR LANGUAGE addressing the system.\n\n"
    "Return strict JSON matching the contract."
)


class DetectCsrOverrideTool(Tool):
    """LLM micro-step that flags CSR-typed overrides in forwarded emails."""

    name = "detect_csr_override"
    description = (
        "Detect explicit CSR-typed override instructions in forwarded emails — "
        "intent overrides, do-not-auto flags, force-HITL flags, team routing."
    )
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            subject = inputs.get("subject") or email.get("subject") or ""
            sender = inputs.get("sender") or email.get("from") or ""
            body = inputs.get("body_english")
            if not body:
                body = ctx.intake.get("translated_body") or email.get("body") or ""
            classifier_intent = inputs.get("classifier_intent") or ctx.intake.get("intent") or ""

            if not subject and not body:
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data=_no_override(reason="empty subject and body"),
                )

            input_preview = (
                f"From: {sender[:120]}\n"
                f"Subject: {subject[:200]}\n"
                f"Classifier intent: {classifier_intent}\n"
                f"Body: {body[:1500]}"
                + ("…" if len(body) > 1500 else "")
            )
            user_prompt = (
                f"FROM: {sender}\n"
                f"SUBJECT: {subject}\n"
                f"AUTO-CLASSIFIER PRIMARY INTENT: {classifier_intent or '(none)'}\n"
                "BODY (translated to English):\n"
                f"{body[:6000]}\n\n"
                "Detect whether a CSR has typed override instructions in this email. "
                "Return JSON only."
            )

            parsed: dict | None = None
            raw: str = ""
            meta: dict[str, Any] = {}
            try:
                if openai_client.is_configured():
                    parsed, raw, meta = openai_client.ask_openai_json(
                        system=_SYSTEM,
                        user=user_prompt,
                        schema=_SCHEMA,
                        schema_name="detect_csr_override",
                        stage_hint="detect_csr_override",
                    )
                    if parsed is not None:
                        meta = {**meta, "provider": f"OpenAI {meta.get('model')}"}
                if parsed is None:
                    parsed, raw, meta = ask_llm_traced(
                        system=_SYSTEM, user=user_prompt, json_only=True
                    )
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"llm_call_failed: {type(e).__name__}: {str(e)[:200]}",
                )

            out = parsed or {}
            has_override = bool(out.get("has_override"))
            kind = out.get("override_kind") or "none"
            if kind not in _OVERRIDE_KINDS:
                kind = "none"
            override_intent = (out.get("override_intent") or "").strip()
            if override_intent and override_intent not in INTENTS:
                override_intent = ""
            override_track = (out.get("override_track") or "").strip()
            override_team = (out.get("override_team") or "").strip()
            reasoning = out.get("reasoning") or ""
            confidence = float(out.get("confidence") or 0.0)
            instruction = out.get("override_instruction") or ""

            # Sanity: a kind that demands a target without one isn't really an override.
            if kind == "intent_override" and not override_intent:
                has_override = False
                kind = "none"
            if kind == "force_track" and not override_track:
                has_override = False
                kind = "none"

            data = {
                "has_override": has_override,
                "override_kind": kind,
                "override_instruction": instruction[:1000],
                "override_intent": override_intent,
                "override_track": override_track,
                "override_team": override_team,
                "reasoning": reasoning[:500],
                "confidence": round(confidence, 3),
                "input_preview": input_preview,
                "input_chars": len(user_prompt),
                "output_summary": (
                    f"OVERRIDE: {kind}"
                    + (f" → {override_intent}" if override_intent else "")
                    + (f" → {override_track}" if override_track else "")
                    + (f" → {override_team}" if override_team else "")
                    + f" ({confidence:.0%})"
                ) if has_override else "no override detected",
                "processing_method": "llm_json_schema_strict",
                "provider": meta.get("provider", "unknown"),
                "prompt_system": meta.get("system_prompt", _SYSTEM),
                "prompt_user": meta.get("user_prompt", user_prompt),
                "provider_response_raw": raw,
                "response_schema": _SCHEMA,
                "schema_enforced": True,
                "kb_namespaces_consulted": [],
            }
            return ToolResult(name=self.name, ok=True, data=data)
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _no_override(*, reason: str) -> dict:
    return {
        "has_override": False,
        "override_kind": "none",
        "override_instruction": "",
        "override_intent": "",
        "override_track": "",
        "override_team": "",
        "reasoning": reason,
        "confidence": 1.0,
        "input_preview": "",
        "input_chars": 0,
        "output_summary": f"no override (skipped: {reason})",
        "processing_method": "skipped",
        "provider": "n/a",
        "kb_namespaces_consulted": [],
    }
