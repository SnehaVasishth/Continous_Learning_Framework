"""Thin sync wrapper around the ZBrain orchestrator's LLM `query()` for one-shot prompts.

Usage:
    text = ask_llm(system="...", user="...", json_only=True)

If json_only=True, the response text is parsed and returned as a dict.
Image attachments can be passed as paths in `image_paths`; ZBrain routes them
through its document-intelligence vision tool for OCR.

Set `LLM_TRACE_DIR=/path` (or rely on the default `backend/data/llm_trace`) to
have every prompt + response dumped to disk for debugging the agent fabric.
"""
from __future__ import annotations

import asyncio
import contextvars
import datetime
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from ..config import DATA


# ----------------------------------------------------------------------
# Per-call cost-attribution context
# ----------------------------------------------------------------------
# Each pipeline stage sets `_cost_ctx` for the duration of its run so that
# every LLM round-trip emitted from inside it can be metered against the
# right pipeline + stage. Without this the Cost dashboard reports 0% coverage
# (no CostEvent rows are ever written).
_cost_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_cost_ctx", default=None
)


def set_cost_context(*, db: Any, pipeline_id: int | None, stage: str, tool: str = "ask_llm") -> Any:
    """Bind the calling pipeline/stage to this async/thread context.

    Returns the contextvars Token so the caller can `reset_cost_context(token)`
    in a finally block — the orchestrator does this around every stage.
    """
    return _cost_ctx.set({"db": db, "pipeline_id": pipeline_id, "stage": stage, "tool": tool})


def reset_cost_context(token: Any) -> None:
    try:
        _cost_ctx.reset(token)
    except Exception:
        pass


def _estimate_tokens(text: str) -> int:
    """Cheap token estimator (chars / 4) used when the SDK does not surface
    real usage. The Cost panel surfaces this as a synthetic-units gauge so
    figures stay directionally honest pending the real usage hook landing."""
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def record_llm_cost(
    *,
    model_hint: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    system: str | None = None,
    user: str | None = None,
    raw_response: str | None = None,
    tool: str | None = None,
) -> bool:
    """Record one LLM round-trip against the active cost context.

    Prefer passing real `tokens_in`/`tokens_out` from the provider's usage
    payload (OpenAI exposes these). When the provider does not surface real
    usage (Claude Agent SDK streaming path), pass the raw prompt/response
    strings and the helper estimates via chars/4. Returns True iff a cost
    event was written.
    """
    ctx = _cost_ctx.get()
    if not ctx:
        logging.getLogger(__name__).debug("record_llm_cost: no cost context bound; skipping")
        return False
    db = ctx.get("db")
    if db is None:
        logging.getLogger(__name__).debug("record_llm_cost: cost context has no db; skipping")
        return False
    try:
        from ..analytics.cost import record_cost  # local to avoid import cycle
        if tokens_in is None:
            tokens_in = _estimate_tokens((system or "") + "\n" + (user or ""))
        if tokens_out is None:
            tokens_out = _estimate_tokens(raw_response or "")
        resolved_tool = tool or ctx.get("tool") or "ask_llm"
        record_cost(
            db,
            pipeline_id=ctx.get("pipeline_id"),
            stage=ctx.get("stage") or "unknown",
            tool=resolved_tool,
            component="llm_input",
            model=model_hint,
            units=tokens_in,
            unit_kind="tokens",
        )
        record_cost(
            db,
            pipeline_id=ctx.get("pipeline_id"),
            stage=ctx.get("stage") or "unknown",
            tool=resolved_tool,
            component="llm_output",
            model=model_hint,
            units=tokens_out,
            unit_kind="tokens",
        )
        db.commit()
        return True
    except Exception:
        logging.getLogger(__name__).exception(
            "record_llm_cost failed (pipeline=%s stage=%s model=%s)",
            ctx.get("pipeline_id"), ctx.get("stage"), model_hint,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _record_llm_cost(*, system: str, user: str, raw_response: str, model_hint: str) -> None:
    record_llm_cost(
        model_hint=model_hint,
        system=system,
        user=user,
        raw_response=raw_response,
    )


def record_ocr_cost(*, model_hint: str, pages: int, tool: str | None = None) -> bool:
    """Record one Azure Document Intelligence (or similar OCR provider) call.

    Pulls pipeline_id + stage from the active cost context the same way
    record_llm_cost does. `model_hint` must match a key in the OCR rate book
    in analytics/cost.py (e.g. 'azure-doc-intelligence', '-layout', '-read').
    """
    ctx = _cost_ctx.get()
    if not ctx:
        logging.getLogger(__name__).debug("record_ocr_cost: no cost context bound; skipping")
        return False
    db = ctx.get("db")
    if db is None:
        return False
    try:
        from ..analytics.cost import record_cost
        resolved_tool = tool or ctx.get("tool") or "azure_doc_intelligence"
        record_cost(
            db,
            pipeline_id=ctx.get("pipeline_id"),
            stage=ctx.get("stage") or "unknown",
            tool=resolved_tool,
            component="ocr",
            model=model_hint,
            units=max(1, int(pages or 1)),
            unit_kind="pages",
        )
        db.commit()
        return True
    except Exception:
        logging.getLogger(__name__).exception(
            "record_ocr_cost failed (pipeline=%s stage=%s model=%s)",
            ctx.get("pipeline_id"), ctx.get("stage"), model_hint,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False

logger = logging.getLogger(__name__)

_TRACE_DIR = Path(os.environ.get("LLM_TRACE_DIR") or (DATA / "llm_trace"))
_TRACE_LOCK = threading.Lock()
LLM_TRACE_ENABLED = os.environ.get("LLM_TRACE", "1") != "0"


def _dump_trace(stage_hint: str, system: str, user: str, raw_response: str, parsed: Any | None, error: str | None) -> None:
    if not LLM_TRACE_ENABLED:
        return
    try:
        with _TRACE_LOCK:
            _TRACE_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = _TRACE_DIR / f"{ts}_{stage_hint}_{uuid.uuid4().hex[:6]}.json"
            payload = {
                "timestamp": ts,
                "system_prompt_chars": len(system or ""),
                "user_prompt_chars": len(user or ""),
                "raw_response_chars": len(raw_response or ""),
                "system": system,
                "user": user,
                "raw_response": raw_response,
                "parsed": parsed,
                "error": error,
            }
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            logger.info("llm_trace written: %s (sys=%d chars, user=%d chars, resp=%d chars)",
                        path.name, len(system or ""), len(user or ""), len(raw_response or ""))
    except Exception:
        logger.exception("llm_trace dump failed")


def _strip_code_fence(text: str) -> str:
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _extract_first_json(text: str) -> Any:
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except Exception:
            pass
    raise ValueError(f"could not parse JSON from response: {text[:300]}")


def _patch_sdk_unknown_types() -> None:
    """SDK 0.1.6 vs CLI 2.1.x compatibility patches:
    1. parse_message — drop unknown message types (e.g. rate_limit_event)
    2. Query.initialize — make the streaming-mode init handshake a no-op
       (CLI 2.1.x doesn't respond to the SDK's control_request 'initialize' so
       the SDK times out at 60s; we skip that step entirely)
    """
    try:
        from claude_agent_sdk._internal import message_parser as mp
    except Exception:
        return
    if getattr(mp, "_patched_for_unknown", False):
        return
    original = mp.parse_message
    from claude_agent_sdk._errors import MessageParseError

    def safe_parse(data):
        try:
            return original(data)
        except MessageParseError:
            return None

    mp.parse_message = safe_parse
    try:
        from claude_agent_sdk._internal import client as _client

        _client.parse_message = safe_parse
    except Exception:
        pass
    mp._patched_for_unknown = True

    try:
        from claude_agent_sdk._internal.query import Query

        async def _noop_initialize(self):
            return {}

        Query.initialize = _noop_initialize
    except Exception:
        pass


async def _query_async(prompt: str, *, system: str | None, allowed_tools: list[str] | None) -> str:
    """Free-form LLM call. Uses OpenAI by default; falls back to the Claude
    Code SDK only when image attachments are explicitly passed (`allowed_tools`
    includes `Read`), since OpenAI text completions can't OCR file paths the
    same way the Claude Code Read tool does.

    The Claude Code SDK path stays in the codebase for the vision case but
    every other call now flows through OpenAI's gpt-5.2 (same client the
    intent classifier, language detector, spam check, and extraction agent
    already use). This removes the Node CLI dependency that was breaking
    Stage 5 reply drafting end-to-end.
    """
    sys_prompt = system or (
        "You are a backend agent invoked from a SalesOps automation pipeline. "
        "Treat every user message as a structured task to execute now. "
        "Never ask clarifying questions. Never describe your tools. "
        "Respond exactly in the format requested. If the request asks for JSON, "
        "respond with JSON only, no prose, no code fences."
    )

    needs_vision = bool(allowed_tools) and "Read" in (allowed_tools or [])
    if not needs_vision:
        from ..services.openai_client import ask_openai_text
        _parsed, raw, meta = await asyncio.to_thread(
            ask_openai_text,
            system=sys_prompt,
            user=prompt,
            json_only=False,
            stage_hint="ask_llm",
        )
        err = meta.get("error")
        if not raw and err:
            raise RuntimeError(f"OpenAI free-form completion failed: {err}")
        return raw or ""

    # Vision path: Claude Code SDK retains the Read tool. If the SDK is not
    # installed in this environment, surface a clean error so the caller's
    # fallback path (e.g. Stage 5's _action_aware_fallback_body) kicks in.
    _patch_sdk_unknown_types()
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except Exception as e:
        raise RuntimeError(
            f"Vision path requires Claude Code SDK which is not installed: {type(e).__name__}: {e}. "
            "Either install with `npm install -g @anthropic-ai/claude-code` or route this prompt through "
            "OpenAI vision instead."
        )

    options_kwargs: dict[str, Any] = {
        "system_prompt": sys_prompt,
        "setting_sources": [],
        "max_turns": 3,
    }
    if allowed_tools is not None:
        options_kwargs["allowed_tools"] = allowed_tools
    options = ClaudeAgentOptions(**options_kwargs)

    async def stream():
        yield {"type": "user", "message": {"role": "user", "content": prompt}}

    last_assistant = ""
    async for msg in query(prompt=stream(), options=options):
        if msg is None:
            continue
        if type(msg).__name__ != "AssistantMessage":
            continue
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        parts: list[str] = []
        for block in content:
            txt = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
            if txt:
                parts.append(txt)
        if parts:
            last_assistant = "".join(parts)
    return last_assistant


def ask_llm(
    *,
    system: str,
    user: str,
    json_only: bool = False,
    image_paths: list[str | Path] | None = None,
) -> Any:
    parsed, _raw, _ = ask_llm_traced(system=system, user=user, json_only=json_only, image_paths=image_paths)
    return parsed


def ask_llm_traced(
    *,
    system: str,
    user: str,
    json_only: bool = False,
    image_paths: list[str | Path] | None = None,
) -> tuple[Any, str, dict[str, Any]]:
    """Like ask_llm but also returns the raw assistant text and a meta dict.

    Returns: (parsed_or_text, raw_text, meta) where meta carries
    {"system_prompt": str, "user_prompt": str, "provider": str, "model_hint": str}.

    Every call passes through the PII redactor before the provider call so
    credit cards, SSNs, passports, IBANs, phone numbers, and API keys are
    replaced with `<REDACTED_KIND_n>` tokens. The redaction summary is
    surfaced in the returned `meta` dict so the calling stage can persist
    a trace event and the verifier can count occurrences for compliance.
    """
    user_prompt = user
    if image_paths:
        user_prompt += (
            "\n\nIMAGE ATTACHMENTS. Read each via the Read tool for OCR:\n"
            + "\n".join(f"- {Path(p).resolve().as_posix()}" for p in image_paths)
        )
    if json_only:
        user_prompt += "\n\nRespond with a single JSON object only. No code fences. No prose before or after."

    # Run PII redaction on BOTH system and user prompts. Body that goes to
    # the LLM is the redacted text; the original is kept in scope only for
    # the cost-record path (which never leaves the process).
    # Honors the DEMO_DISABLE_PII_REDACTION flag from app/config.py so the
    # demo can show customer-facing replies that quote real PO and order
    # numbers without the redactor false-flagging them.
    _empty_meta = {"redacted": False, "counts": {}, "total": 0, "kinds": []}
    try:
        from ..config import DEMO_DISABLE_PII_REDACTION
    except Exception:
        DEMO_DISABLE_PII_REDACTION = False
    if DEMO_DISABLE_PII_REDACTION:
        system_redacted, user_redacted, _redact_meta = system, user_prompt, dict(_empty_meta, disabled_by_demo_flag=True)
    else:
        try:
            from ..services.pii_redactor import redact_for_llm
            system_redacted, user_redacted, _redact_meta = redact_for_llm(system, user_prompt)
        except Exception:
            system_redacted, user_redacted, _redact_meta = system, user_prompt, dict(_empty_meta)

    raw = asyncio.run(_query_async(user_redacted, system=system_redacted, allowed_tools=["Read"] if image_paths else []))
    parsed: Any
    parse_error: str | None = None
    if json_only:
        try:
            parsed = _extract_first_json(raw)
        except Exception as e:
            parsed = None
            parse_error = str(e)[:200]
    else:
        parsed = raw

    _dump_trace("ask_llm", system or "", user_prompt, raw, parsed, parse_error)

    # Provider metadata reflects the real backend: OpenAI for free-form text,
    # Claude Code SDK only when image_paths were provided (vision path).
    if image_paths:
        provider_label = "Claude Code SDK (Read-tool vision)"
        model_hint = "claude-opus-4-7"
    else:
        from ..services.openai_client import _DEFAULT_MODEL as _OPENAI_DEFAULT
        provider_label = "OpenAI Chat Completions"
        model_hint = _OPENAI_DEFAULT
    meta = {
        "system_prompt": system,
        "user_prompt": user_prompt,
        "provider": provider_label,
        "model_hint": model_hint,
        "pii_redaction": _redact_meta,
    }
    _record_llm_cost(system=system or "", user=user_prompt, raw_response=raw, model_hint=meta["model_hint"])
    return parsed, raw, meta
