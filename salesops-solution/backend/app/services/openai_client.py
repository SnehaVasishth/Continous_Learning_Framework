"""OpenAI client with strict JSON-Schema response enforcement.

Used by Stage 1 LLM-based tools (classify_intent, detect_language LLM
corroboration, llm_spam_check, translate_to_english) where we need a
guaranteed-shape JSON response. OpenAI's `response_format=json_schema` with
`strict: True` rejects malformed output at the API level — no normalizer
hacks, no schema drift.

Falls back gracefully when OPENAI_API_KEY isn't configured: callers receive
`(None, "", {"error": "openai_not_configured"})` and decide whether to use
their heuristic-only path.

Shape parity with `agents.llm.ask_llm_traced`: returns a 3-tuple of
`(parsed_or_none, raw_text, meta)` so existing tools can swap providers with
minimal call-site changes.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from ..config import DATA

logger = logging.getLogger(__name__)

_TRACE_DIR = Path(os.environ.get("LLM_TRACE_DIR") or (DATA / "llm_trace"))
_TRACE_LOCK = threading.Lock()
LLM_TRACE_ENABLED = os.environ.get("LLM_TRACE", "1") != "0"

_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.2")
_FALLBACK_MODELS = ["gpt-5.2", "gpt-5", "gpt-4.1", "gpt-4o"]

_client = None
_client_lock = threading.Lock()


def _resolve_api_key() -> str:
    """Live OpenAI key. Operator-configured row in llm_provider_configs wins;
    env OPENAI_API_KEY is the fallback."""
    try:
        from ..db import SessionLocal
        from . import llm_provider
        db = SessionLocal()
        try:
            key = llm_provider.resolve_openai_api_key(db)
            if key:
                return key
        finally:
            db.close()
    except Exception:
        pass
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def reset_client() -> None:
    """Drop the cached client so the next call re-reads credentials.
    Called after an operator rotates the key from the Settings UI."""
    global _client
    with _client_lock:
        _client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        api_key = _resolve_api_key()
        if not api_key:
            return None
        try:
            from openai import OpenAI
            _client = OpenAI(api_key=api_key)
            return _client
        except Exception as e:
            logger.warning("OpenAI client init failed: %s", e)
            return None


def _dump_trace(stage_hint: str, system: str, user: str, schema: dict | None,
                raw: str, parsed: Any | None, error: str | None,
                model: str | None) -> None:
    if not LLM_TRACE_ENABLED:
        return
    try:
        with _TRACE_LOCK:
            _TRACE_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = _TRACE_DIR / f"{ts}_openai_{stage_hint}_{uuid.uuid4().hex[:6]}.json"
            payload = {
                "timestamp": ts,
                "provider": "openai",
                "model": model,
                "system_prompt_chars": len(system or ""),
                "user_prompt_chars": len(user or ""),
                "raw_response_chars": len(raw or ""),
                "system": system,
                "user": user,
                "schema": schema,
                "raw_response": raw,
                "parsed": parsed,
                "error": error,
            }
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception:
        logger.exception("openai_trace dump failed")


def is_configured() -> bool:
    return bool(_resolve_api_key())


def ask_openai_text(
    *,
    system: str,
    user: str,
    json_only: bool = False,
    model: str | None = None,
    temperature: float = 0.2,
    max_retries: int = 2,
    stage_hint: str = "openai_text",
) -> tuple[Any, str, dict[str, Any]]:
    """Free-form OpenAI chat. Returns (parsed_or_text, raw_text, meta).

    When json_only=True the response is parsed best-effort with the same
    `_extract_first_json` semantics ask_llm uses, so callers that previously
    pointed at the Claude Code SDK wrapper can be redirected here without
    rewriting their prompt logic. No JSON-schema enforcement (use
    ask_openai_json when you need strict-mode schema validation).

    Designed as the OpenAI replacement for app/agents/llm.py:_query_async so
    Stage 5 reply drafting (and any other free-form LLM call) stops depending
    on the Claude Code CLI dependency. The action-aware fallback templates
    in stage5_communicate_agent.py remain the safety net for when this call
    fails.
    """
    client = _get_client()
    if client is None:
        meta = {
            "provider": "openai",
            "model": None,
            "system_prompt": system,
            "user_prompt": user,
            "error": "openai_not_configured",
            "attempts": 0,
        }
        return None if json_only else "", "", meta

    candidate_models: list[str] = []
    if model:
        candidate_models.append(model)
    if _DEFAULT_MODEL not in candidate_models:
        candidate_models.append(_DEFAULT_MODEL)
    for m in _FALLBACK_MODELS:
        if m not in candidate_models:
            candidate_models.append(m)

    instruction_suffix = (
        "\n\nReturn a single JSON object only. No code fences, no prose, no explanations."
        if json_only
        else ""
    )

    last_error: str | None = None
    attempts = 0
    raw = ""
    model_used: str | None = None
    for m in candidate_models:
        for attempt in range(max_retries):
            attempts += 1
            try:
                resp = client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system or ""},
                        {"role": "user", "content": (user or "") + instruction_suffix},
                    ],
                    temperature=temperature,
                )
                raw = (resp.choices[0].message.content or "").strip()
                model_used = m
                last_error = None
                break
            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:200]}"
                continue
        if model_used:
            break

    parsed: Any
    if json_only and raw:
        try:
            from ..agents.llm import _extract_first_json
            parsed = _extract_first_json(raw)
        except Exception as e:
            parsed = None
            if not last_error:
                last_error = f"json_parse_failed: {e}"
    else:
        parsed = raw

    meta = {
        "provider": "openai",
        "model": model_used,
        "system_prompt": system,
        "user_prompt": user,
        "attempts": attempts,
        "error": last_error,
    }
    _dump_trace(stage_hint, system or "", user or "", None, raw, parsed if json_only else None, last_error, model_used)
    return parsed, raw, meta


def ask_openai_json(
    *,
    system: str,
    user: str,
    schema: dict,
    schema_name: str = "response",
    model: str | None = None,
    temperature: float = 0.0,
    stage_hint: str = "openai_json",
    max_retries: int = 2,
) -> tuple[dict | None, str, dict[str, Any]]:
    """Send a chat completion with strict JSON Schema response enforcement.

    Args:
        system: system message content.
        user: user message content.
        schema: JSON Schema dict for the response. Must follow the 'strict'-mode
                rules: every property listed under additionalProperties=false,
                every property in 'required'. Top-level must be an object.
        schema_name: name embedded in the response_format payload (purely cosmetic).
        model: override the default model. Defaults to OPENAI_MODEL env or gpt-5.2.
        temperature: sampling temperature.
        stage_hint: tag used in the trace filename for grep'ability.
        max_retries: retry on transient errors (e.g. 5xx).

    Returns:
        (parsed_dict_or_None, raw_text, meta) where meta contains:
          provider, model, system_prompt, user_prompt, schema_name,
          response_format, error (if any), attempts.
    """
    client = _get_client()
    if client is None:
        meta = {
            "provider": "openai",
            "model": None,
            "system_prompt": system,
            "user_prompt": user,
            "schema_name": schema_name,
            "error": "openai_not_configured",
            "attempts": 0,
        }
        _dump_trace(stage_hint, system, user, schema, "", None, "openai_not_configured", None)
        return None, "", meta

    candidate_models: list[str] = []
    if model:
        candidate_models.append(model)
    if _DEFAULT_MODEL not in candidate_models:
        candidate_models.append(_DEFAULT_MODEL)
    for m in _FALLBACK_MODELS:
        if m not in candidate_models:
            candidate_models.append(m)

    last_error: str | None = None
    attempts = 0

    for m in candidate_models:
        for attempt in range(max_retries):
            attempts += 1
            try:
                resp = client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "strict": True,
                            "schema": schema,
                        },
                    },
                    temperature=temperature,
                )
                raw = (resp.choices[0].message.content or "").strip()
                try:
                    parsed = json.loads(raw)
                except Exception as e:
                    last_error = f"json_parse_failed_after_strict_mode: {e}"
                    parsed = None
                meta = {
                    "provider": "openai",
                    "model": m,
                    "system_prompt": system,
                    "user_prompt": user,
                    "schema_name": schema_name,
                    "response_format": "json_schema(strict)",
                    "error": None if parsed is not None else last_error,
                    "attempts": attempts,
                    "finish_reason": resp.choices[0].finish_reason,
                    "usage": getattr(resp, "usage", None) and {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                        "total_tokens": resp.usage.total_tokens,
                    },
                }
                _dump_trace(stage_hint, system, user, schema, raw, parsed, meta["error"], m)
                try:
                    from ..agents.llm import record_llm_cost
                    usage = meta.get("usage") or {}
                    record_llm_cost(
                        model_hint=m,
                        tokens_in=usage.get("prompt_tokens"),
                        tokens_out=usage.get("completion_tokens"),
                        system=system,
                        user=user,
                        raw_response=raw,
                        tool=stage_hint or "ask_openai_json",
                    )
                except Exception:
                    logger.exception("openai cost metering failed (stage=%s model=%s)", stage_hint, m)
                return parsed, raw, meta
            except Exception as e:
                msg = str(e)
                last_error = f"{type(e).__name__}: {msg[:300]}"
                # Errors specific to model not existing / not supported — try next model
                if any(needle in msg.lower() for needle in (
                    "model_not_found", "does not exist", "model_does_not_exist",
                    "the model", "is not supported with", "unsupported_value",
                )):
                    logger.info("openai model %s rejected (%s); trying next candidate", m, msg[:120])
                    break  # break inner retry loop, try next model
                # Otherwise, retry on this model
                logger.warning("openai call attempt %d on model %s failed: %s", attempt + 1, m, msg[:200])

    meta = {
        "provider": "openai",
        "model": None,
        "system_prompt": system,
        "user_prompt": user,
        "schema_name": schema_name,
        "error": last_error or "all_models_failed",
        "attempts": attempts,
    }
    _dump_trace(stage_hint, system, user, schema, "", None, meta["error"], None)
    return None, "", meta
