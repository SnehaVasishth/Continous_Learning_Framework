"""Translate text to English. Pluggable provider adapters.

Provider selection (in priority):
  1. `provider` keyword arg passed at invoke time
  2. `TRANSLATION_PROVIDER` env var
  3. default `llm`

Per-provider credentials (env):
  azure  → AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION (default: global),
           AZURE_TRANSLATOR_ENDPOINT (default: api.cognitive.microsofttranslator.com)
  deepl  → DEEPL_API_KEY, DEEPL_PLAN (free | pro, default free)
  google → GOOGLE_TRANSLATE_KEY (Google Cloud API key with Translation API enabled)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from ... import kb
from ...db import SessionLocal
from ..base import AgentContext, Tool, ToolResult
from ..llm import ask_llm_traced

log = logging.getLogger("translate_tool")


_LLM_SYSTEM = (
    "You are a professional translator. Translate the user's text into clear, faithful English. "
    "Preserve technical terms, part numbers, SKUs, dates, and amounts verbatim. "
    "Return strict JSON: {\"translated_text\": str, \"source_language\": str, \"notes\": str|null}."
)

_PROVIDER_LABEL = {
    "llm": "ZBrain LLM (Claude Opus 4.7)",
    "azure": "Azure AI Translator",
    "deepl": "DeepL",
    "google": "Google Cloud Translate v2",
}


def _load_translation_kb(source_language: str | None = None) -> tuple[list[dict], list[str]]:
    """Pull the editable translation KB into (rule_summaries, glossary_lines_for_prompt).

    Two namespaces feed the translator:
      • `translation` — generic preserve-verbatim / tone / format rules
      • `translation_glossary` — Keysight-domain canonical translations per language

    When `source_language` is set (e.g., 'ja' for an inbound JA email), the
    glossary lines are direction-aware: "If you see <ja-term>, translate it
    to <english-term>." For outbound translation (where source_language is
    'en'), the lines flip the other way — see `_load_outbound_glossary`.
    """
    db = SessionLocal()
    try:
        rules = kb.list_rules(db, "translation")
        rule_summaries: list[dict] = []
        glossary: list[str] = []
        for r in rules:
            body = r.body or {}
            kind = body.get("kind") or ""
            rule_summaries.append({
                "key": r.key,
                "label": r.label,
                "kind": kind,
                "description": r.description,
            })
            if kind == "preserve_verbatim":
                terms = body.get("terms") or []
                for t in terms:
                    glossary.append(f"  • Preserve verbatim: {t}")
                pats = body.get("patterns") or []
                for p in pats:
                    glossary.append(f"  • Preserve any token matching pattern: {p}")
            elif kind == "tone_guidance":
                instr = body.get("instruction") or ""
                glossary.append(f"  • Tone: {instr}")
            elif kind == "format_guidance":
                instr = body.get("instruction") or ""
                glossary.append(f"  • Formatting: {instr}")
    finally:
        db.close()

    # Stage 1.5 inbound: source is customer language, target is English.
    # The glossary tells the LLM "if you see <native term>, translate to <EN>."
    if source_language and source_language not in ("en", "unknown"):
        try:
            g = kb.translation_glossary(target_language=source_language, direction="inbound")
            terms = g.get("terms") or []
            verbatim = g.get("preserve_verbatim_terms") or []
            if terms:
                glossary.append("")
                glossary.append(f"  Keysight glossary ({source_language.upper()} → EN). Use these canonical English terms:")
                for t in terms:
                    native = t.get("translation") or ""
                    en = t.get("english") or ""
                    if native and en:
                        glossary.append(f"    · {native} → {en}")
                rule_summaries.append({
                    "key": f"translation_glossary[{source_language}]",
                    "label": f"Keysight glossary ({source_language.upper()})",
                    "kind": "glossary_term",
                    "description": f"{len(terms)} canonical Keysight terms in {source_language.upper()} pinned to their English translations.",
                })
            if verbatim:
                glossary.append(f"  Preserve verbatim acronyms (universal, never localize): {', '.join(verbatim)}")
        except Exception:
            # Glossary is best-effort — don't block translation if it fails.
            pass

    return rule_summaries, glossary


def _load_outbound_glossary(target_language: str) -> tuple[list[dict], list[str]]:
    """Glossary lines for English → customer-language drafting.

    Format: 'When writing in <lang>, use <native term> for <english phrase>.'
    Used by Stage 5.1 (run_communicate) when drafting customer replies.
    """
    if not target_language or target_language == "en":
        return [], []
    rule_summaries: list[dict] = []
    lines: list[str] = []
    try:
        g = kb.translation_glossary(target_language=target_language, direction="outbound")
        terms = g.get("terms") or []
        verbatim = g.get("preserve_verbatim_terms") or []
        if terms:
            lines.append(f"Keysight glossary (EN → {target_language.upper()}). When writing in {target_language.upper()}, use these canonical translations:")
            for t in terms:
                native = t.get("translation") or ""
                en = t.get("english") or ""
                if native and en:
                    lines.append(f"  · {en} → {native}")
            rule_summaries.append({
                "key": f"translation_glossary[{target_language}]",
                "label": f"Keysight glossary ({target_language.upper()})",
                "kind": "glossary_term",
                "description": f"{len(terms)} canonical Keysight terms — write all of these in {target_language.upper()} using the pinned form.",
            })
        if verbatim:
            lines.append(f"Preserve verbatim acronyms (universal, never localize): {', '.join(verbatim)}")
    except Exception:
        pass
    return rule_summaries, lines


class TranslateTool(Tool):
    """Translate to English with pluggable provider; LLM by default."""

    name = "translate_to_english"
    description = "Translate arbitrary text to English. Provider via TRANSLATION_PROVIDER env (llm|azure|deepl|google)."
    kb_namespaces: list[str] = ["translation"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            text = inputs.get("text") or ""
            if not text:
                return ToolResult(name=self.name, ok=False, error="empty text")
            source_hint = (inputs.get("source_language") or "").lower()
            provider = (inputs.get("provider") or os.environ.get("TRANSLATION_PROVIDER") or "llm").lower()

            if provider == "azure":
                result = self._translate_with_azure(text, source_hint)
            elif provider == "deepl":
                result = self._translate_with_deepl(text, source_hint)
            elif provider == "google":
                result = self._translate_with_google(text, source_hint)
            else:
                provider = "llm"
                result = self._translate_with_llm(text, source_hint)

            if not result.get("ok"):
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error=result.get("error") or "translate_failed",
                    data={"provider": provider},
                )

            translated = result["translated_text"]
            label = result.get("provider_label_override") or _PROVIDER_LABEL.get(provider, provider)
            data = {
                "translated_text": translated,
                "translated_text_full": translated,
                "source_language": result.get("source_language") or source_hint or "unknown",
                "provider": provider,
                "input_text_full": text,
                "input_preview": (text[:300] + "…") if len(text) > 300 else text,
                "input_chars": len(text),
                "output_preview": (translated[:300] + "…") if len(translated) > 300 else translated,
                "output_chars": len(translated),
                "output_summary": f"translated {len(text)}→{len(translated)} chars via {label}",
                "processing_method": "external_api" if provider != "llm" else "llm",
                "provider_label": label,
                "kb_namespaces_consulted": ["translation"] if result.get("kb_consulted") else [],
                "kb_rules_used": result.get("kb_rules_used") or [],
            }
            if "prompt_system" in result:
                data["prompt_system"] = result["prompt_system"]
                data["prompt_user"] = result["prompt_user"]
                data["provider_response_raw"] = result.get("provider_response_raw") or ""
            return ToolResult(
                name=self.name,
                ok=True,
                data=data,
                notes=result.get("notes") or [],
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")

    # ------------------------------------------------------------------
    # Adapters
    # ------------------------------------------------------------------

    def _translate_with_llm(self, text: str, source_hint: str) -> dict:
        from ...services import openai_client

        try:
            kb_rules, glossary_lines = _load_translation_kb(source_language=source_hint)
            glossary_block = ""
            if glossary_lines:
                glossary_block = (
                    "\n\nKEYSIGHT TRANSLATION KB. Apply these rules:\n"
                    + "\n".join(glossary_lines)
                )
            system = _LLM_SYSTEM + glossary_block
            user = f"SOURCE_LANGUAGE_HINT: {source_hint or 'unknown'}\nTEXT:\n{text}\n\nReturn JSON only."

            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["translated_text", "source_language", "notes"],
                "properties": {
                    "translated_text": {"type": "string"},
                    "source_language": {"type": "string"},
                    "notes": {"type": "string"},
                },
            }

            parsed = None
            raw = ""
            meta: dict = {}
            provider_label = "ZBrain LLM (Claude Opus 4.7)"
            if openai_client.is_configured():
                parsed, raw, meta = openai_client.ask_openai_json(
                    system=system,
                    user=user,
                    schema=schema,
                    schema_name="translate",
                    stage_hint="translate",
                )
                if parsed is not None:
                    provider_label = f"OpenAI {meta.get('model')}"
            if parsed is None:
                parsed, raw, meta = ask_llm_traced(system=system, user=user, json_only=True)

            out = parsed or {}
            translated_text = out.get("translated_text") or ""
            return {
                "ok": True,
                "translated_text": translated_text,
                "source_language": out.get("source_language") or source_hint,
                "notes": [out["notes"]] if out.get("notes") else [],
                "prompt_system": system,
                "prompt_user": meta.get("user_prompt") or user,
                "provider_response_raw": raw,
                "provider_label_override": provider_label,
                "kb_consulted": bool(kb_rules),
                "kb_rules_used": [r["key"] for r in kb_rules],
                "kb_rule_summaries": kb_rules,
            }
        except Exception as e:
            return {"ok": False, "error": f"llm_translate_failed: {type(e).__name__}: {str(e)[:200]}"}

    def _translate_with_azure(self, text: str, source_hint: str) -> dict:
        """Azure AI Translator — POST /translate?api-version=3.0&to=en
        https://learn.microsoft.com/azure/ai-services/translator/reference/v3-0-translate
        """
        key = os.environ.get("AZURE_TRANSLATOR_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "azure_translator_missing_key (set AZURE_TRANSLATOR_KEY)"}
        region = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip() or "global"
        endpoint = (os.environ.get("AZURE_TRANSLATOR_ENDPOINT") or "https://api.cognitive.microsofttranslator.com").rstrip("/")

        params: dict[str, Any] = {"api-version": "3.0", "to": "en"}
        if source_hint and source_hint != "unknown":
            params["from"] = source_hint
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Ocp-Apim-Subscription-Region": region,
            "Content-Type": "application/json",
        }
        body = [{"Text": text[:50000]}]  # Azure limit per request element

        try:
            resp = requests.post(f"{endpoint}/translate", params=params, headers=headers, json=body, timeout=30)
        except requests.RequestException as e:
            return {"ok": False, "error": f"azure_network: {e}"}

        if resp.status_code != 200:
            return {"ok": False, "error": f"azure_http_{resp.status_code}: {resp.text[:200]}"}

        try:
            payload = resp.json()
            first = (payload or [{}])[0]
            translations = first.get("translations") or []
            if not translations:
                return {"ok": False, "error": "azure_no_translations_in_response"}
            translated = translations[0].get("text") or ""
            detected = (first.get("detectedLanguage") or {}).get("language") or source_hint
            return {"ok": True, "translated_text": translated, "source_language": detected, "notes": []}
        except Exception as e:
            return {"ok": False, "error": f"azure_parse: {type(e).__name__}: {str(e)[:200]}"}

    def _translate_with_deepl(self, text: str, source_hint: str) -> dict:
        """DeepL API — POST /v2/translate
        https://developers.deepl.com/docs/api-reference/translate
        """
        key = os.environ.get("DEEPL_API_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "deepl_missing_key (set DEEPL_API_KEY)"}
        plan = (os.environ.get("DEEPL_PLAN") or "free").strip().lower()
        host = "api-free.deepl.com" if plan == "free" else "api.deepl.com"

        data: dict[str, Any] = {"text": text[:128000], "target_lang": "EN"}
        if source_hint and source_hint != "unknown":
            data["source_lang"] = source_hint.upper()
        headers = {"Authorization": f"DeepL-Auth-Key {key}"}

        try:
            resp = requests.post(f"https://{host}/v2/translate", data=data, headers=headers, timeout=30)
        except requests.RequestException as e:
            return {"ok": False, "error": f"deepl_network: {e}"}

        if resp.status_code != 200:
            return {"ok": False, "error": f"deepl_http_{resp.status_code}: {resp.text[:200]}"}

        try:
            payload = resp.json()
            translations = payload.get("translations") or []
            if not translations:
                return {"ok": False, "error": "deepl_no_translations_in_response"}
            t = translations[0]
            return {
                "ok": True,
                "translated_text": t.get("text") or "",
                "source_language": (t.get("detected_source_language") or "").lower() or source_hint,
                "notes": [],
            }
        except Exception as e:
            return {"ok": False, "error": f"deepl_parse: {type(e).__name__}: {str(e)[:200]}"}

    def _translate_with_google(self, text: str, source_hint: str) -> dict:
        """Google Cloud Translate v2 (REST + API key).
        https://cloud.google.com/translate/docs/reference/rest/v2/translate
        """
        key = os.environ.get("GOOGLE_TRANSLATE_KEY", "").strip()
        if not key:
            return {"ok": False, "error": "google_translate_missing_key (set GOOGLE_TRANSLATE_KEY)"}

        params: dict[str, Any] = {"key": key}
        body: dict[str, Any] = {"q": text[:30000], "target": "en", "format": "text"}
        if source_hint and source_hint != "unknown":
            body["source"] = source_hint

        try:
            resp = requests.post(
                "https://translation.googleapis.com/language/translate/v2",
                params=params,
                json=body,
                timeout=30,
            )
        except requests.RequestException as e:
            return {"ok": False, "error": f"google_network: {e}"}

        if resp.status_code != 200:
            return {"ok": False, "error": f"google_http_{resp.status_code}: {resp.text[:200]}"}

        try:
            payload = resp.json()
            translations = ((payload.get("data") or {}).get("translations")) or []
            if not translations:
                return {"ok": False, "error": "google_no_translations_in_response"}
            t = translations[0]
            return {
                "ok": True,
                "translated_text": t.get("translatedText") or "",
                "source_language": (t.get("detectedSourceLanguage") or "").lower() or source_hint,
                "notes": [],
            }
        except Exception as e:
            return {"ok": False, "error": f"google_parse: {type(e).__name__}: {str(e)[:200]}"}
