"""Intent classification via OpenAI with strict JSON Schema enforcement.

Stage 1 sub-step 1.7. Uses OpenAI's `response_format=json_schema` (strict mode)
so the API itself rejects malformed output — no normalizer hacks, no shape
drift. The legacy `_normalize()` path stays as a defensive fallback for the
edge case where OpenAI is unconfigured and we have to use Claude.

Captures the full system+user prompt, the JSON schema, and raw LLM response
for the Stage 1 drill-down UI.
"""
from __future__ import annotations

from typing import Any

from ... import kb
from ...config import INTENTS, LANGUAGES
from ...services import openai_client
from ..base import AgentContext, Tool, ToolResult
from ..intake import build_system_prompt, build_user_prompt
from ..llm import ask_llm_traced


def _build_classify_schema() -> dict[str, Any]:
    """Build the strict JSON Schema. The intent_confidence_breakdown items use the
    live rubric's rule keys as the enum, so an operator-edited KB rubric immediately
    flows into schema enforcement on the next pipeline."""
    try:
        rubric = kb.intent_confidence_rubric()
        rubric_keys = [r["id"] for r in rubric.get("rules") or []]
    except Exception:
        rubric_keys = []
    if not rubric_keys:
        rubric_keys = ["subject_explicit_signal", "body_action_verb_match", "referenced_id_present",
                       "no_multi_intent_ambiguity", "attachment_consistent",
                       "multi_intent_ambiguity", "vague_or_generic_body", "contradictory_attachment"]

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "language",
            "language_reasoning",
            "intent",
            "intent_confidence",
            "intent_confidence_base",
            "intent_confidence_breakdown",
            "intent_reasoning",
            "secondary_intents",
            "spam",
            "spam_reason",
            "summary",
            "track_hint",
        ],
        "properties": {
            "language": {
                "type": "string",
                "enum": LANGUAGES + ["other"],
                "description": "ISO 639-1 code from the canonical list",
            },
            "language_reasoning": {
                "type": "string",
                "description": "1 sentence explaining the language cue (script, vocabulary, idiom)",
            },
            "intent": {
                "type": "string",
                "enum": list(INTENTS),
                "description": "Single canonical intent value. Never an array, never invented.",
            },
            "intent_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Final confidence after applying the rubric, clamped to [0, 1]. MUST equal base + sum of matched deltas.",
            },
            "intent_confidence_base": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "The starting prior from the KB rubric (typically 0.50). Echo it back as-is.",
            },
            "intent_confidence_breakdown": {
                "type": "array",
                "description": (
                    "Per-rule breakdown of how the confidence was scored. "
                    "EMIT ONE ENTRY FOR EVERY RUBRIC RULE. Even rules that didn't match. "
                    "Order: triggers first, then clearance, then penalties."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["rule_key", "matched", "delta", "evidence"],
                    "properties": {
                        "rule_key": {
                            "type": "string",
                            "enum": rubric_keys,
                            "description": "Identifier of the rubric rule being scored",
                        },
                        "matched": {
                            "type": "boolean",
                            "description": "True if the email satisfies this rule",
                        },
                        "delta": {
                            "type": "number",
                            "description": "Contribution to confidence: the rule's effective delta (0.0 when matched=false)",
                        },
                        "evidence": {
                            "type": "string",
                            "description": "Short quote from the email or attachment that justifies matched=true; empty string when matched=false",
                        },
                    },
                },
            },
            "intent_reasoning": {
                "type": "string",
                "description": "1–2 sentences citing exact words from the email subject or body",
            },
            "secondary_intents": {
                "type": "array",
                "items": {"type": "string", "enum": list(INTENTS)},
                "description": "Other plausible intents beyond the primary; empty array if none",
            },
            "spam": {
                "type": "boolean",
                "description": "True iff the email is spam/phishing/promotional",
            },
            "spam_reason": {
                "type": "string",
                "description": "Why it's spam; empty string if not spam",
            },
            "summary": {
                "type": "string",
                "description": "One English sentence summarizing the primary request",
            },
            "track_hint": {
                "type": "string",
                "enum": ["trade", "som", "service_contract", "none"],
                "description": "Workflow track: trade=orders/PO/holds; som=work-orders/cal/repair; service_contract=cal-plan/PM-plan; none=general/spam",
            },
        },
    }


# Static schema retained for callers that still import it; the live request uses the
# fresh per-call schema returned by `_build_classify_schema()` so a freshly-edited KB
# rubric flows in without restarting the backend.
CLASSIFY_INTENT_SCHEMA: dict[str, Any] = _build_classify_schema()


_TRACK_HINT_VALUES = {"trade", "som", "service_contract", "none"}

_INTENT_ALIASES = {
    # po_intake variants
    "po_submission": "po_intake",
    "po_acknowledgment": "po_intake",
    "po_acknowledgement": "po_intake",
    "purchase_order_acknowledgment": "po_intake",
    "purchase_order_acknowledgement": "po_intake",
    "purchase_order_intake": "po_intake",
    "acknowledge_po": "po_intake",
    "po_received": "po_intake",
    "po_receipt": "po_intake",
    "new_purchase_order": "po_intake",
    "new_po": "po_intake",
    "po": "po_intake",
    "purchase_order": "po_intake",
    "soa_request": "po_intake",
    "soa_generation": "po_intake",
    "order_acknowledgment": "po_intake",
    "order_request": "po_intake",
    "order_intake": "po_intake",
    "po_processing": "po_intake",
    # quote_to_order variants
    "q2o": "quote_to_order",
    "convert_quote": "quote_to_order",
    "quote_conversion": "quote_to_order",
    "quote_acceptance": "quote_to_order",
    "accept_quote": "quote_to_order",
    "convert_to_order": "quote_to_order",
    "quote_order": "quote_to_order",
    # trade_change_order variants
    "change_order": "trade_change_order",
    "order_change": "trade_change_order",
    "modify_order": "trade_change_order",
    "order_modification": "trade_change_order",
    "amend_order": "trade_change_order",
    "co_request": "trade_change_order",
    # ssd_change_request variants
    "ssd": "ssd_change_request",
    "ssd_change": "ssd_change_request",
    "ship_date_change": "ssd_change_request",
    "shipping_date_change": "ssd_change_request",
    "reschedule_shipment": "ssd_change_request",
    "ship_schedule": "ssd_change_request",
    # delivery_change variants
    "reschedule_delivery": "delivery_change",
    "delivery_reschedule": "delivery_change",
    # hold_release variants
    "release_hold": "hold_release",
    "credit_hold_release": "hold_release",
    "remove_hold": "hold_release",
    # service_order variants
    "wo_create": "service_order",
    "som_create": "service_order",
    "calibration_request": "service_order",
    "cal_request": "service_order",
    "repair_request": "service_order",
    "field_service": "service_order",
    "service_request": "service_order",
    "new_work_order": "service_order",
    "create_work_order": "service_order",
    # wo_update_request variants
    "wo_update": "wo_update_request",
    "update_work_order": "wo_update_request",
    "modify_work_order": "wo_update_request",
    "amend_work_order": "wo_update_request",
    # wo_status_inquiry variants
    "wo_status": "wo_status_inquiry",
    "work_order_status": "wo_status_inquiry",
    "status_check": "wo_status_inquiry",
    "wo_inquiry": "wo_status_inquiry",
    # service_contract_request variants
    "service_contract": "service_contract_request",
    "service_agreement": "service_contract_request",
    "support_agreement": "service_contract_request",
    "cal_plan": "service_contract_request",
    "calibration_contract": "service_contract_request",
    "pm_plan": "service_contract_request",
    "service_plan_request": "service_contract_request",
    # general_inquiry variants
    "general": "general_inquiry",
    "inquiry": "general_inquiry",
    "question": "general_inquiry",
    "info_request": "general_inquiry",
    "lead_time_inquiry": "general_inquiry",
    "product_info": "general_inquiry",
    # spam variants
    "phishing": "spam",
    "promo": "spam",
    "promotional": "spam",
    "marketing": "spam",
    "junk": "spam",
    "advertisement": "spam",
}


class ClassifyIntentTool(Tool):
    """Run intake LLM classifier, then normalize field-name and value drift."""

    name = "classify_intent"
    description = "Classify email intent via the intake agent and normalize LLM output drift."
    kb_namespaces = ["intent"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            if not email:
                return ToolResult(name=self.name, ok=False, error="missing email")

            # Load the live confidence rubric from the KB and inject into the prompt.
            try:
                rubric = kb.intent_confidence_rubric()
            except Exception:
                rubric = {"base": 0.50, "rules": []}

            # Load thread context if this email is part of a multi-message conversation.
            # Per SOLUTION_OVERVIEW §7b: the ROOT message drives intent classification;
            # subsequent replies are clarifying context that disambiguate the latest envelope.
            thread_summary: str | None = None
            try:
                from ...models import Email as _EmailModel, Pipeline as _PipelineModel
                from ...services.email_thread import walk_thread, thread_summary_for_prompt
                seed_id = None
                if ctx.pipeline_id:
                    pipe_row = ctx.db.get(_PipelineModel, ctx.pipeline_id)
                    seed_id = pipe_row.email_id if pipe_row else None
                if seed_id:
                    seed_email = ctx.db.get(_EmailModel, seed_id)
                    if seed_email:
                        chain = walk_thread(ctx.db, seed_email)
                        if chain and len(chain) > 1:
                            thread_summary = thread_summary_for_prompt(chain)
            except Exception:
                # Thread loading is best-effort — fall back to single-email classification.
                thread_summary = None

            # === v1.1 TASK-6 START === resolve mailbox region for region-filtered intent menu.
            account_region: str | None = None
            try:
                from ...models import Email as _EmailModel, EmailAccount as _Acct
                if ctx.pipeline_id:
                    from ...models import Pipeline as _Pipe
                    pipe_row = ctx.db.get(_Pipe, ctx.pipeline_id)
                    seed_id = pipe_row.email_id if pipe_row else None
                    if seed_id:
                        seed_email = ctx.db.get(_EmailModel, seed_id)
                        if seed_email and seed_email.account_id:
                            acct = ctx.db.get(_Acct, seed_email.account_id)
                            if acct:
                                account_region = (acct.region or "GLOBAL").upper()
            except Exception:
                account_region = None
            # === v1.1 TASK-6 END ===

            system_prompt = build_system_prompt(account_region=account_region) + "\n\n" + _format_rubric_for_prompt(rubric)
            user_prompt = build_user_prompt(email, thread_summary=thread_summary)

            # Build the schema with the live rubric's rule_keys as the enum so a
            # KB-edited rubric flows into schema enforcement on the next call.
            live_schema = _build_classify_schema()

            parsed: dict | None = None
            raw_text: str = ""
            meta: dict[str, Any] = {}
            provider_used = "unknown"
            schema_enforced = False

            if openai_client.is_configured():
                parsed, raw_text, meta = openai_client.ask_openai_json(
                    system=system_prompt,
                    user=user_prompt,
                    schema=live_schema,
                    schema_name="classify_intent",
                    stage_hint="classify_intent",
                )
                if parsed is not None:
                    provider_used = f"OpenAI {meta.get('model') or 'unknown'}"
                    schema_enforced = True

            # Fallback to Claude (legacy path) if OpenAI unavailable or failed
            if parsed is None:
                try:
                    parsed_claude, raw_claude, meta_claude = ask_llm_traced(
                        system=system_prompt, user=user_prompt, json_only=True
                    )
                    if parsed_claude is not None:
                        parsed = parsed_claude
                        raw_text = raw_claude
                        meta = meta_claude
                        provider_used = meta.get("provider", "ZBrain LLM (Claude Opus 4.7)")
                except Exception as e:
                    return ToolResult(
                        name=self.name,
                        ok=False,
                        error=f"llm_call_failed: {type(e).__name__}: {str(e)[:300]}",
                    )

            if parsed is None:
                parsed = {
                    "language": email.get("language_hint") or "en",
                    "intent": "general_inquiry",
                    "intent_confidence": 0.0,
                    "secondary_intents": [],
                    "spam": False,
                    "spam_reason": "",
                    "summary": "(intake parse failed — defaulting to manual review)",
                }
                provider_used = f"FALLBACK (default) — {meta.get('error', 'unknown')}"

            if not isinstance(parsed.get("secondary_intents"), list):
                parsed["secondary_intents"] = []

            # Normalizer is a defensive safety net — it should be a no-op when
            # OpenAI strict-mode succeeded. We still run it so the legacy Claude
            # fallback path stays correct.
            normalized, notes = _normalize(parsed)

            # Server-side recompute of confidence from the breakdown, with
            # per-intent overrides applied. The LLM's `intent_confidence` is
            # cross-checked; if it disagrees with the rubric math by more than
            # 0.05 we trust the math and log a guardrail.
            chosen_intent = normalized.get("intent") or "general_inquiry"
            breakdown_raw = normalized.get("intent_confidence_breakdown") or []
            breakdown_norm, computed_conf, breakdown_notes = _apply_rubric(
                rubric=rubric,
                intent=chosen_intent,
                breakdown_in=breakdown_raw if isinstance(breakdown_raw, list) else [],
            )
            notes.extend(breakdown_notes)

            llm_reported_conf = float(normalized.get("intent_confidence") or 0.0)
            if abs(llm_reported_conf - computed_conf) > 0.05:
                notes.append(
                    f"confidence_recomputed_from_rubric: llm={llm_reported_conf:.3f} "
                    f"→ rubric={computed_conf:.3f}"
                )
            normalized["intent_confidence"] = computed_conf
            normalized["intent_confidence_breakdown"] = breakdown_norm
            normalized["intent_confidence_base"] = float(rubric.get("base") or 0.50)

            try:
                kb_rules = list(kb.intake_intent_rules().keys())
            except Exception:
                kb_rules = []

            normalized.update(
                {
                    "input_preview": user_prompt[:400] + ("…" if len(user_prompt) > 400 else ""),
                    "input_chars": len(user_prompt),
                    "output_summary": (
                        f"intent={normalized.get('intent')} "
                        f"({(normalized.get('intent_confidence') or 0) * 100:.0f}% confidence) "
                        f"[{'schema-enforced' if schema_enforced else 'normalized'}]"
                    ),
                    "processing_method": "openai_json_schema_strict" if schema_enforced else "llm_normalized",
                    "provider": provider_used,
                    "prompt_system": system_prompt,
                    "prompt_user": user_prompt,
                    "provider_response_raw": raw_text,
                    "response_schema": live_schema,
                    "schema_enforced": schema_enforced,
                    "kb_namespaces_consulted": ["intent", "intent_confidence_rubric"],
                    "kb_rules_used": kb_rules,
                    "rubric_rules_used": [r["id"] for r in rubric.get("rules") or []],
                    "normalizer_corrections_applied": list(notes),
                }
            )

            return ToolResult(name=self.name, ok=True, data=normalized, notes=notes)
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _format_rubric_for_prompt(rubric: dict) -> str:
    """Render the KB rubric into prompt-ready text the LLM can apply."""
    base = rubric.get("base", 0.50)
    rules = rubric.get("rules") or []
    if not rules:
        return ""
    lines: list[str] = [
        "INTENT-CONFIDENCE RUBRIC (apply this to score the chosen intent):",
        f"  Start with base = {base:.2f} (uninformed prior).",
        "  Then EVALUATE EACH RULE BELOW against this email and decide matched=true|false.",
        "  Final intent_confidence = base + sum(delta where matched=true), clamped to [0.0, 1.0].",
        "  EMIT one entry in `intent_confidence_breakdown` for EVERY rule below, even rules that don't match (matched=false, delta=0.0, evidence=\"\").",
        "  When matched=true, set delta to the rule's weight for the chosen intent (use per-intent override if present, otherwise default_delta) and put a SHORT quote from the email in `evidence`.",
        "",
    ]
    for r in rules:
        kind = r.get("kind") or "trigger"
        default_delta = r.get("default_delta") or 0.0
        per_intent = r.get("per_intent_overrides") or {}
        examples = r.get("examples")
        ex_str = ""
        if isinstance(examples, dict) and examples:
            sample_intent = next(iter(examples.keys()))
            ex_str = f" e.g., for {sample_intent}: {', '.join(map(str, list(examples[sample_intent])[:3]))}"
        elif isinstance(examples, list) and examples:
            ex_str = f" e.g., {', '.join(map(str, examples[:3]))}"
        override_str = ""
        if per_intent:
            override_str = (
                " (per-intent overrides: "
                + ", ".join(f"{k}={v:+.2f}" for k, v in list(per_intent.items())[:6])
                + ")"
            )
        lines.append(
            f"  • {r['id']} [{kind}, default {default_delta:+.2f}]{override_str}: {r.get('description', '')}{ex_str}"
        )
    return "\n".join(lines)


def _apply_rubric(
    *, rubric: dict, intent: str, breakdown_in: list,
) -> tuple[list[dict], float, list[str]]:
    """Reconcile the LLM's breakdown with the KB rubric and recompute confidence.

    Guarantees:
      - One entry per active rubric rule (missing entries from the LLM are
        filled with matched=false / delta=0).
      - Each entry's effective delta uses the per-intent override if present,
        else the rule's default_delta — for rows the LLM marked matched=true.
      - Final confidence = base + sum(matched deltas), clamped to [0, 1].

    Returns (normalized_breakdown_list, final_confidence_float, normalizer_notes).
    """
    base = float(rubric.get("base") or 0.50)
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
        per_intent = r.get("per_intent_overrides") or {}
        # Effective delta for THIS rule on THIS intent
        effective_delta = float(per_intent.get(intent, r.get("default_delta") or 0.0))
        e = by_key_in.get(rid)
        matched = bool((e or {}).get("matched", False))
        evidence = str((e or {}).get("evidence") or "")
        if e is None:
            notes.append(f"rubric_entry_missing_filled_unmatched:{rid}")
        # If the LLM marked matched=true we use the rule's effective delta;
        # if matched=false we contribute 0 regardless of what the LLM put there.
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


def _normalize(raw: dict) -> tuple[dict, list[str]]:
    notes: list[str] = []
    out = dict(raw or {})

    nested_intent: str | None = None
    nested_confidence: float | None = None
    nested_reasoning: str | None = None
    if isinstance(out.get("intents"), list) and out["intents"]:
        first = out["intents"][0]
        if isinstance(first, dict):
            nested_intent = first.get("intent") or first.get("name") or first.get("type")
            for k in ("confidence", "intent_confidence", "score", "intent_score"):
                if k in first:
                    try:
                        nested_confidence = float(first[k])
                    except Exception:
                        pass
                    break
            nested_reasoning = first.get("reasoning") or first.get("notes") or first.get("rationale")
        elif isinstance(first, str):
            nested_intent = first

    if "primary_intent" in out and "intent" not in out:
        out["intent"] = out.pop("primary_intent")
        notes.append("normalized: primary_intent -> intent")
    if "intent_type" in out and "intent" not in out:
        out["intent"] = out.pop("intent_type")
        notes.append("normalized: intent_type -> intent")

    if "intent" not in out and nested_intent:
        out["intent"] = nested_intent
        notes.append("normalized: intents[0].intent -> intent")
    out.pop("intents", None)

    if "is_spam" in out and "spam" not in out:
        out["spam"] = bool(out.pop("is_spam"))
        notes.append("normalized: is_spam -> spam")

    if "confidence" in out and "intent_confidence" not in out:
        out["intent_confidence"] = out.pop("confidence")
        notes.append("normalized: confidence -> intent_confidence")
    if "intent_score" in out and "intent_confidence" not in out:
        out["intent_confidence"] = out.pop("intent_score")
        notes.append("normalized: intent_score -> intent_confidence")
    if "intent_confidence" not in out and nested_confidence is not None:
        out["intent_confidence"] = nested_confidence
        notes.append("normalized: intents[0].confidence -> intent_confidence")

    if not out.get("intent_reasoning"):
        if isinstance(out.get("notes"), str):
            out["intent_reasoning"] = out.pop("notes")
            notes.append("normalized: notes -> intent_reasoning")
        elif nested_reasoning:
            out["intent_reasoning"] = nested_reasoning
            notes.append("normalized: intents[0].reasoning -> intent_reasoning")
    if not out.get("summary") and out.get("intent_reasoning"):
        out["summary"] = out["intent_reasoning"]
        notes.append("normalized: intent_reasoning -> summary (summary missing)")

    intent = out.get("intent")
    if isinstance(intent, str):
        key = intent.strip().lower()
        if key in _INTENT_ALIASES:
            out["intent"] = _INTENT_ALIASES[key]
            notes.append(f"normalized intent alias: {key} -> {out['intent']}")
        else:
            out["intent"] = key

    track = out.get("track_hint")
    if isinstance(track, str):
        tk = track.strip().lower()
        if tk == "spam":
            out["spam"] = True
            out["track_hint"] = "none"
            notes.append("normalized: track_hint=spam -> spam=True + track_hint=none")
        elif tk not in _TRACK_HINT_VALUES:
            out["track_hint"] = "none"
            notes.append(f"normalized: track_hint '{tk}' not canonical -> 'none' (LLM emitted non-canonical track value)")

    if out.get("intent") not in INTENTS:
        notes.append(f"intent '{out.get('intent')}' not in canonical list -> general_inquiry")
        out["intent"] = "general_inquiry"

    from ..intake import _INTENT_TRACKS
    canonical_track = _INTENT_TRACKS.get(out.get("intent"), "none")
    if out.get("track_hint") in ("none", None, "") and canonical_track != "none":
        out["track_hint"] = canonical_track
        notes.append(f"derived: track_hint='{canonical_track}' from intent='{out['intent']}'")

    if not isinstance(out.get("secondary_intents"), list):
        out["secondary_intents"] = []

    try:
        out["intent_confidence"] = float(out.get("intent_confidence") or 0.0)
    except Exception:
        out["intent_confidence"] = 0.0

    out.setdefault("language", "en")
    out.setdefault("spam", False)
    out.setdefault("spam_reason", "")
    out.setdefault("summary", "")
    out.setdefault("track_hint", "none")

    return out, notes
