"""Heuristic language detection — KB-driven (namespace=language_heuristic).

Layered ruleset (4 tiers, 13 rules) sourced from stopwords-iso (MIT) and the
rule-based detection design of lingua-py (Apache 2.0); see
backend/app/kb_seeds/language_heuristic_rules.py for the data and full
attribution. Rules are user-editable through the KB Settings UI.

Per ADR-003 we always run BOTH this heuristic AND the LLM detector;
heuristic = corroboration, LLM = canonical.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from ... import kb
from ...services import openai_client
from ..base import AgentContext, Tool, ToolResult
from ..llm import ask_llm_traced


_LLM_SYSTEM = (
    "You are a language-detection agent. Given a short piece of text, decide which "
    "of [en, es, ja, other] the text is in. Then SCORE your confidence by applying "
    "the rubric below and returning a per-rule breakdown (matched true/false, delta, "
    "evidence). The downstream system recomputes confidence from your breakdown; "
    "your `confidence` value should equal base + sum(matched deltas), clamped to [0,1]."
)


def _build_detect_language_schema() -> dict:
    """Build the strict JSON Schema with live rubric rule_keys as the breakdown enum.
    A KB-edited rubric flows into schema enforcement on the next call."""
    try:
        rubric = kb.language_confidence_rubric()
        rubric_keys = [r["id"] for r in rubric.get("rules") or []]
    except Exception:
        rubric_keys = []
    if not rubric_keys:
        rubric_keys = [
            "script_definitive_match", "diacritic_signature", "keyword_density_high",
            "greeting_or_signoff_match", "single_language_throughout",
            "mixed_language_penalty", "too_short_for_signal", "script_signal_disagreement",
        ]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "language", "confidence", "confidence_base", "confidence_breakdown", "reasoning",
        ],
        "properties": {
            "language": {"type": "string", "enum": ["en", "es", "ja", "other"]},
            "confidence": {
                "type": "number", "minimum": 0.0, "maximum": 1.0,
                "description": "Final confidence after applying the rubric, clamped to [0, 1]. MUST equal base + sum of matched deltas.",
            },
            "confidence_base": {
                "type": "number", "minimum": 0.0, "maximum": 1.0,
                "description": "Starting prior from the KB rubric (typically 0.40). Echo as-is.",
            },
            "confidence_breakdown": {
                "type": "array",
                "description": (
                    "Per-rule breakdown of how confidence was scored. EMIT ONE ENTRY FOR "
                    "EVERY RUBRIC RULE. Even rules that didn't match. Order: triggers → "
                    "clearance → penalties."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["rule_key", "matched", "delta", "evidence"],
                    "properties": {
                        "rule_key": {"type": "string", "enum": rubric_keys},
                        "matched": {"type": "boolean"},
                        "delta": {
                            "type": "number",
                            "description": "Effective delta when matched=true (use per-language override if present); 0.0 when matched=false",
                        },
                        "evidence": {
                            "type": "string",
                            "description": "Short quote from the text justifying matched=true; empty when matched=false",
                        },
                    },
                },
            },
            "reasoning": {
                "type": "string",
                "description": "1-sentence explanation of the cue (script, vocabulary, idiom)",
            },
        },
    }


# Static schema (callers that import it). The live request uses _build_detect_language_schema().
_LANGUAGE_DETECT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["language", "confidence", "reasoning"],
    "properties": {
        "language": {"type": "string", "enum": ["en", "es", "ja", "other"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "description": "1 sentence explaining the cue (script, vocabulary, idiom)"},
    },
}

_SEVERITY_ORDER = {"definitive": 4, "high": 3, "medium": 2, "low": 1}

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]+|[぀-ヿ一-鿿]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _count_unicode_block(text: str, block: tuple[int, int],
                         exclude_blocks: list[tuple[int, int]] | None = None) -> int:
    lo, hi = block
    excludes = exclude_blocks or []
    count = 0
    for ch in text:
        cp = ord(ch)
        if lo <= cp <= hi and not any(elo <= cp <= ehi for elo, ehi in excludes):
            count += 1
    return count


def _evaluate_rule(rule: dict[str, Any], text: str) -> int:
    kind = rule.get("kind")
    if kind == "regex":
        flags_val = rule.get("flags") or 0
        try:
            flags = int(flags_val) if isinstance(flags_val, int) else 0
        except Exception:
            flags = 0
        try:
            return len(re.findall(rule.get("pattern") or "", text, flags=flags))
        except Exception:
            return 0
    if kind == "unicode_block":
        block = rule.get("block")
        if not block or len(block) != 2:
            return 0
        excl = rule.get("exclude_blocks")
        excl_tuples = [tuple(b) for b in excl] if excl else None
        return _count_unicode_block(text, tuple(block), excl_tuples)
    if kind == "keyword_density":
        tokens = rule.get("tokens") or []
        if any(any(ord(c) > 0x3000 for c in t) for t in tokens):
            count = 0
            for tok in tokens:
                idx = 0
                while True:
                    nxt = text.find(tok, idx)
                    if nxt < 0:
                        break
                    count += 1
                    idx = nxt + len(tok)
            return count
        toks = _tokenize(text)
        token_set = set(tokens)
        return sum(1 for t in toks if t in token_set)
    return 0


def _heuristic_evaluate(text: str, rules: list[dict[str, Any]]) -> tuple[str, str, str, list[dict]]:
    """Return (language, severity, rule_id, rules_evaluated[]).

    Comparison key is (sev_int, weight_float, idx) — the trailing idx makes the
    tuple totally orderable when two rules share the same severity+weight,
    avoiding the previous TypeError on dict comparison.
    """
    text_norm = unicodedata.normalize("NFC", text)
    rules_evaluated: list[dict] = []
    best: tuple[int, float, int] | None = None  # (sev, weight, idx) — sortable
    best_rule: dict | None = None
    best_count: int = 0

    for tier in (1, 2, 3, 4):
        tier_best_key: tuple[int, float, int] | None = None
        tier_best_rule: dict | None = None
        tier_best_count: int = 0
        for idx, rule in enumerate(rules):
            if rule.get("tier") != tier:
                continue
            count = _evaluate_rule(rule, text_norm)
            threshold = int(rule.get("threshold") or 1)
            matched = count >= threshold
            rules_evaluated.append({
                "id": rule.get("id"),
                "tier": rule.get("tier"),
                "language": rule.get("language"),
                "kind": rule.get("kind"),
                "description": rule.get("description"),
                "severity": rule.get("severity"),
                "threshold": threshold,
                "count": count,
                "matched": matched,
            })
            if matched:
                sev = _SEVERITY_ORDER.get(rule.get("severity") or "low", 1)
                weight = float(rule.get("score_weight") or 0.5)
                cand_key = (sev, weight, idx)
                if tier_best_key is None or cand_key > tier_best_key:
                    tier_best_key = cand_key
                    tier_best_rule = rule
                    tier_best_count = count
        if tier_best_key is not None:
            if best is None or tier_best_key > best:
                best = tier_best_key
                best_rule = tier_best_rule
                best_count = tier_best_count
            if (tier_best_rule or {}).get("severity") == "definitive":
                break

    if best is None or best_rule is None:
        return ("other", "low", "<none>", rules_evaluated)
    return (
        best_rule.get("language") or "other",
        best_rule.get("severity") or "low",
        best_rule.get("id") or "<unknown>",
        rules_evaluated,
    )


class DetectLanguageTool(Tool):
    """KB-driven heuristic + LLM language detection.

    Per ADR-003: heuristic alone leaks errors on mixed-language emails, so we run
    both signals every time and let the LLM be canonical. The heuristic now uses
    a 13-rule, 4-tier KB (script → diacritic → keyword density → greeting)
    sourced from stopwords-iso + lingua-py design.
    """

    name = "detect_language"
    description = "Heuristic (KB-driven, 13 rules) + LLM language detection — both run; LLM is canonical."
    kb_namespaces = ["language_heuristic"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            text = inputs.get("text") or ""
            if not text and ctx.email:
                text = f"{ctx.email.get('subject', '')}\n{ctx.email.get('body', '')}"
            if not text:
                return ToolResult(name=self.name, ok=False, error="empty text")

            sample = text[:1500]
            input_preview = sample[:300] + ("…" if len(sample) > 300 else "")

            try:
                rules = kb.language_heuristic_rules() or []
            except Exception:
                rules = []

            heur_lang, heur_sev, heur_rule_id, rules_evaluated = _heuristic_evaluate(sample, rules)

            # Load the live language-confidence rubric and bake into the system
            # prompt + schema. Operators tune the rubric in /kb; the next call
            # picks up changes — no redeploy.
            try:
                conf_rubric = kb.language_confidence_rubric()
            except Exception:
                conf_rubric = {"base": 0.40, "rules": []}
            rubric_block = _format_rubric_for_prompt(conf_rubric)
            system_with_rubric = _LLM_SYSTEM + ("\n\n" + rubric_block if rubric_block else "")
            user_msg = f"TEXT:\n{sample}\n\nReturn JSON only."

            llm_lang: str | None = None
            llm_conf: float = 0.0
            llm_reasoning = ""
            llm_meta: dict[str, Any] = {}
            llm_raw = ""
            llm_error: str | None = None
            llm_breakdown: list[dict] = []
            llm_base: float = 0.40
            try:
                if openai_client.is_configured():
                    parsed, llm_raw, llm_meta = openai_client.ask_openai_json(
                        system=system_with_rubric,
                        user=user_msg,
                        schema=_build_detect_language_schema(),
                        schema_name="detect_language",
                        stage_hint="detect_language",
                    )
                    if parsed is not None:
                        llm_meta = {
                            **llm_meta,
                            "provider": f"OpenAI {llm_meta.get('model')}",
                        }
                else:
                    parsed, llm_raw, llm_meta = ask_llm_traced(
                        system=system_with_rubric,
                        user=user_msg,
                        json_only=True,
                    )
                llm_lang = ((parsed or {}).get("language") or "").lower() or None
                llm_conf = float((parsed or {}).get("confidence") or 0.0)
                llm_reasoning = (parsed or {}).get("reasoning") or ""
                if isinstance((parsed or {}).get("confidence_breakdown"), list):
                    llm_breakdown = (parsed or {}).get("confidence_breakdown") or []
                if isinstance((parsed or {}).get("confidence_base"), (int, float)):
                    llm_base = float((parsed or {}).get("confidence_base"))
                if llm_meta.get("error"):
                    llm_error = llm_meta["error"]
                    llm_lang = None
            except Exception as e:
                llm_error = f"{type(e).__name__}: {str(e)[:200]}"

            final_lang = llm_lang or heur_lang
            agreement = (llm_lang is not None and llm_lang == heur_lang) or (
                llm_lang is None and llm_error is not None
            )

            # Server-side recompute of confidence from the LLM-emitted breakdown,
            # applying per-language overrides + filling missing entries. Mirrors
            # the intent rubric pattern in classify_intent_tool.py.
            breakdown_norm: list[dict] = []
            computed_conf: float = llm_conf
            rubric_notes: list[str] = []
            if conf_rubric.get("rules") and llm_lang:
                breakdown_norm, computed_conf, rubric_notes = _apply_rubric(
                    rubric=conf_rubric, language=llm_lang, breakdown_in=llm_breakdown,
                )
            final_conf = computed_conf if (llm_lang and breakdown_norm) else (
                0.92 if heur_sev == "definitive" else 0.75
            )

            notes: list[str] = list(rubric_notes)
            method_note = "heuristic_kb+llm_rubric"
            if llm_error:
                notes.append(f"llm_call_failed_using_heuristic_only: {llm_error}")
                method_note = "heuristic_after_llm_fail"
                final_conf = max(final_conf - 0.1, 0.5)
            elif not agreement:
                notes.append(f"heuristic_llm_disagreement: heuristic={heur_lang} llm={llm_lang} → using LLM")
                final_conf = min(final_conf, 0.85)
            if abs(llm_conf - computed_conf) > 0.05 and llm_lang and breakdown_norm:
                notes.append(
                    f"confidence_recomputed_from_rubric: llm={llm_conf:.3f} → rubric={computed_conf:.3f}"
                )

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "language": final_lang,
                    "confidence": round(final_conf, 3),
                    "reasoning": llm_reasoning or f"heuristic-only: rule {heur_rule_id} ({heur_sev})",
                    "method": method_note,
                    "heuristic_language": heur_lang,
                    "heuristic_rule_fired": heur_rule_id,
                    "heuristic_severity": heur_sev,
                    "llm_language": llm_lang,
                    "llm_confidence": round(llm_conf, 3) if llm_lang else None,
                    "llm_reasoning": llm_reasoning or None,
                    "agreement": agreement,
                    "input_preview": input_preview,
                    "input_chars": len(text),
                    "output_summary": (
                        f"language={final_lang} (confidence={final_conf:.0%}; "
                        f"heuristic={heur_lang} via {heur_rule_id} [{heur_sev}], "
                        f"llm={llm_lang or '—'}, "
                        f"{'AGREE' if agreement else 'DISAGREE — deferred to LLM'})"
                    ),
                    "processing_method": method_note,
                    "provider": llm_meta.get("provider", "KB heuristic + LLM"),
                    "prompt_system": llm_meta.get("system_prompt"),
                    "prompt_user": llm_meta.get("user_prompt"),
                    "provider_response_raw": llm_raw,
                    "rules_evaluated": rules_evaluated,
                    "rules_matched": [r for r in rules_evaluated if r["matched"]],
                    "rules_total": len(rules_evaluated),
                    "kb_namespaces_consulted": ["language_heuristic", "language_confidence_rubric"],
                    # Confidence rubric breakdown (LLM-applied, server-recomputed)
                    "language_confidence_base": llm_base,
                    "language_confidence_breakdown": breakdown_norm,
                    "rubric_rules_used": [r["id"] for r in (conf_rubric.get("rules") or [])],
                },
                notes=notes,
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _format_rubric_for_prompt(rubric: dict) -> str:
    base = rubric.get("base", 0.40)
    rules = rubric.get("rules") or []
    if not rules:
        return ""
    lines: list[str] = [
        "LANGUAGE-CONFIDENCE RUBRIC (apply this to score the chosen language):",
        f"  Start with base = {base:.2f} (uninformed prior over [en, es, ja, other]).",
        "  Then EVALUATE EACH RULE BELOW against the text and decide matched=true|false.",
        "  Final confidence = base + sum(delta where matched=true), clamped to [0.0, 1.0].",
        "  EMIT one entry in confidence_breakdown for EVERY rule below, even rules that don't match (matched=false, delta=0.0, evidence=\"\").",
        "  When matched=true, set delta to the rule's weight for the chosen language (per-language override if present, else default_delta) and put a SHORT quote in evidence.",
        "",
    ]
    for r in rules:
        kind = r.get("kind") or "trigger"
        default_delta = r.get("default_delta") or 0.0
        per_lang = r.get("per_language_overrides") or {}
        examples = r.get("examples")
        ex_str = ""
        if isinstance(examples, dict) and examples:
            sample_lang = next(iter(examples.keys()))
            ex_str = f" e.g., for {sample_lang}: {', '.join(map(str, list(examples[sample_lang])[:3]))}"
        elif isinstance(examples, list) and examples:
            ex_str = f" e.g., {', '.join(map(str, examples[:3]))}"
        override_str = ""
        if per_lang:
            override_str = (
                " (per-language: "
                + ", ".join(f"{k}={v:+.2f}" for k, v in list(per_lang.items())[:6])
                + ")"
            )
        lines.append(
            f"  • {r['id']} [{kind}, default {default_delta:+.2f}]{override_str}: {r.get('description', '')}{ex_str}"
        )
    return "\n".join(lines)


def _apply_rubric(
    *, rubric: dict, language: str, breakdown_in: list,
) -> tuple[list[dict], float, list[str]]:
    """Reconcile the LLM's breakdown with the KB rubric and recompute confidence.

    - One entry per active rubric rule (missing entries filled with matched=false / delta=0).
    - Each entry's effective delta uses the per-language override if present, else default_delta.
    - Final confidence = base + sum(matched deltas), clamped to [0, 1].

    Returns (normalized_breakdown_list, final_confidence_float, normalizer_notes).
    """
    base = float(rubric.get("base") or 0.40)
    rules = rubric.get("rules") or []
    by_key_in: dict[str, dict] = {}
    for entry in breakdown_in:
        if not isinstance(entry, dict):
            continue
        k = entry.get("rule_key")
        if isinstance(k, str):
            by_key_in[k] = entry

    notes: list[str] = []
    out: list[dict] = []
    total_delta = 0.0
    for r in rules:
        rid = r["id"]
        per_lang = r.get("per_language_overrides") or {}
        effective_delta = float(per_lang.get(language, r.get("default_delta") or 0.0))
        e = by_key_in.get(rid)
        matched = bool((e or {}).get("matched", False))
        evidence = str((e or {}).get("evidence") or "")
        if e is None:
            notes.append(f"rubric_entry_missing_filled_unmatched:{rid}")
        contribution = effective_delta if matched else 0.0
        out.append({
            "rule_key": rid,
            "kind": r.get("kind"),
            "label": r.get("label") or rid,
            "matched": matched,
            "delta": round(contribution, 3),
            "default_delta": round(float(r.get("default_delta") or 0.0), 3),
            "effective_delta": round(effective_delta, 3),
            "evidence": evidence,
        })
        total_delta += contribution

    final = max(0.0, min(1.0, base + total_delta))
    return out, round(final, 3), notes

