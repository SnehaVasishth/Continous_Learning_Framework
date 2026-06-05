"""LLM spam / phishing check on translated email content.

Runs at Stage 1 sub-step 1.6 — AFTER translation, so it sees the email in English
regardless of source language. Catches sophisticated phishing that the regex
heuristic misses (formal-sounding social engineering, urgency framing without
emoji, fake invoice attachments, etc.).
"""
from __future__ import annotations

from typing import Any

from ...services import openai_client
from ..base import AgentContext, Tool, ToolResult
from ..llm import ask_llm_traced


_LLM_SPAM_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_spam", "confidence", "reasoning", "category"],
    "properties": {
        "is_spam": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "description": "Short string citing specific cues"},
        "category": {
            "type": "string",
            "enum": ["legitimate", "promotional", "phishing", "payment_redirect", "social_engineering", "other"],
        },
    },
}


_SYSTEM = (
    "You are a phishing / wire-fraud classifier for an enterprise B2B SalesOps inbox at Keysight Technologies. "
    "Your only job is to flag MALICIOUS or DECEPTIVE email, not promotional or transactional content from "
    "legitimate senders. Set is_spam=True ONLY when the email shows signs of: credential phishing "
    "('verify your account', 'your mailbox is full'), payment-redirect / wire-fraud setups "
    "('our banking details have changed'), lookalike-domain attacks (faux-keysight.com), 419/advance-fee "
    "scams, or unsolicited promo blasts from UNKNOWN/unverified senders. "
    "\n\n"
    "DO NOT flag is_spam=True for legitimate non-customer-business email. Examples that are NOT spam:\n"
    "  - Forwarded marketing newsletters from known brands (Google, Microsoft, AWS, LinkedIn)\n"
    "  - Account-security notifications from known providers (Google, Microsoft)\n"
    "  - Internal HR / IT / payroll announcements\n"
    "  - Calendar invites, out-of-office auto-replies\n"
    "  - Vendor receipts, billing notifications from known vendors\n"
    "These are 'out_of_scope' (handled by the intent classifier, not by you). Set is_spam=False for these. "
    "the intent classifier downstream will categorize them. Use category='promotional' or 'legitimate' "
    "with is_spam=False when the email is non-customer-business but from a known/legit sender. "
    "\n\n"
    "CRITICAL: DOMAIN UNFAMILIARITY ALONE IS NOT SPAM. "
    "Keysight is a B2B vendor with thousands of enterprise customers worldwide. Most legitimate sender "
    "domains will be UNFAMILIAR to you (raytheon-elseg.com, tesserasemiconductor.com.tw, "
    "auroraauto.com, meridiancomms.es, sakurasemi.co.jp, nordstern-telecom.de, etc.). These look "
    "unfamiliar but they are real customers' actual corporate domains. "
    "\n\n"
    "When the BODY CONTENT is a coherent customer business request (purchase order, quote-to-order "
    "conversion, ship-date change, hold release, calibration / repair / work-order request, service "
    "contract / renewal / cal-plan / PM-plan inquiry, or status question on an existing order/WO), "
    "the email is NOT spam, regardless of how unfamiliar the sender's domain looks to you. Set "
    "is_spam=False with category='legitimate' in those cases. "
    "\n\n"
    "Real lookalike-domain phishing requires BOTH (a) a domain that's clearly impersonating a known "
    "trusted brand (e.g., faux-keysight.com mimicking keysight.com, suspicious capital letters or "
    "homoglyphs, IP literal in URL) AND (b) a phishing pattern in the BODY (credential prompt, banking "
    "details change, urgent action click, executive-impersonation wire request, fake-invoice attachment "
    "from an unfamiliar sender). One signal alone (domain unfamiliarity OR business urgency) is "
    "NEVER sufficient. Both must be present. "
    "\n\n"
    "Return strict JSON: "
    "{\"is_spam\": bool, \"confidence\": float 0..1, \"reasoning\": short string citing specific cues, "
    "\"category\": one of [legitimate, promotional, phishing, payment_redirect, social_engineering, other]}."
)


class LlmSpamCheckTool(Tool):
    """LLM-powered spam check that runs after translate (sees English text always)."""

    name = "llm_spam_check"
    description = "LLM spam/phishing detection on translated email; complements the regex heuristic."
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            subject = inputs.get("subject") or email.get("subject") or ""
            sender = inputs.get("sender") or email.get("from") or ""
            body = inputs.get("body_english")
            if not body:
                body = ctx.intake.get("translated_body") or email.get("body") or ""

            if not subject and not body:
                return ToolResult(name=self.name, ok=False, error="empty subject and body")

            input_preview = (
                f"From: {sender[:120]}\n"
                f"Subject: {subject[:200]}\n"
                f"Body (translated): {body[:1500]}"
                + ("…" if len(body) > 1500 else "")
            )
            user_prompt = (
                f"FROM: {sender}\n"
                f"SUBJECT: {subject}\n"
                f"BODY (translated to English):\n{body[:6000]}\n\n"
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
                        schema=_LLM_SPAM_SCHEMA,
                        schema_name="llm_spam_check",
                        stage_hint="llm_spam_check",
                    )
                    if parsed is not None:
                        meta = {**meta, "provider": f"OpenAI {meta.get('model')}"}
                if parsed is None:
                    parsed, raw, meta = ask_llm_traced(system=_SYSTEM, user=user_prompt, json_only=True)
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=f"llm_call_failed: {type(e).__name__}: {str(e)[:200]}",
                )

            out = parsed or {}
            is_spam = bool(out.get("is_spam"))
            conf = float(out.get("confidence") or 0.0)
            reasoning = out.get("reasoning") or ""
            category = out.get("category") or "legitimate"

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "is_spam": is_spam,
                    "confidence": round(conf, 3),
                    "reasoning": reasoning,
                    "category": category,
                    "input_preview": input_preview,
                    "input_chars": len(user_prompt),
                    "output_summary": f"{'SPAM' if is_spam else 'clean'} ({category}, {conf:.0%} confidence)",
                    "processing_method": "llm",
                    "provider": meta["provider"],
                    "prompt_system": meta["system_prompt"],
                    "prompt_user": meta["user_prompt"],
                    "provider_response_raw": raw,
                    "kb_namespaces_consulted": [],
                },
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
