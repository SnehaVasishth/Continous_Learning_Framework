"""Live read of admin-editable prompts + thresholds from the KB.

When a Continuous-Learning promotion writes a new prompt body to
`agent_prompts/<stage>:system` or new floors to `threshold/<intent>`, the
next pipeline run picks them up here — no deploy needed. Each lookup
returns the resolved value plus a `source` meta dict so the Trace UI can
show whether a stage ran on the hardcoded fallback or on a KB-promoted
override (and, if KB, which row + version).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeRule


def get_stage_system_prompt(db: Session | None, stage: str, fallback: str) -> tuple[str, dict[str, Any]]:
    """Read `agent_prompts/<stage>:system`.

    Returns a tuple `(prompt, source_meta)`. `source_meta` is always shaped
    for direct inclusion in a trace event:
      { source: "kb"|"fallback",
        namespace: "agent_prompts",
        key: "<stage>:system",
        version, updated_at, updated_by, reason? }
    """
    meta: dict[str, Any] = {
        "source": "fallback",
        "namespace": "agent_prompts",
        "key": f"{stage}:system",
    }
    if db is None:
        meta["reason"] = "no_db"
        return fallback, meta
    try:
        row = (
            db.query(KnowledgeRule)
            .filter_by(namespace="agent_prompts", key=f"{stage}:system")
            .first()
        )
    except Exception as e:
        meta["reason"] = f"kb_query_failed:{type(e).__name__}"
        return fallback, meta
    if row is None:
        meta["reason"] = "no_row"
        return fallback, meta
    body = row.body if isinstance(row.body, dict) else {}
    prompt = (body.get("system_prompt") or "").strip()
    if not prompt:
        meta["reason"] = "empty_body"
        return fallback, meta
    meta.update({
        "source": "kb",
        "version": row.version,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
        "chars": len(prompt),
    })
    return prompt, meta


def get_intent_thresholds(db: Session | None, intent: str) -> tuple[dict[str, float] | None, dict[str, Any]]:
    """Read `threshold/<intent>`.

    Returns `(thresholds, source_meta)` where `thresholds` is
    `{l4_floor: float, l3_floor: float}` or `None` if the KB row is absent
    or malformed. Callers should fall back to global CONFIDENCE_TIERS when
    `thresholds is None`.
    """
    meta: dict[str, Any] = {
        "source": "fallback",
        "namespace": "threshold",
        "key": intent,
    }
    if db is None or not intent:
        meta["reason"] = "no_db_or_intent"
        return None, meta
    try:
        row = (
            db.query(KnowledgeRule)
            .filter_by(namespace="threshold", key=intent)
            .first()
        )
    except Exception as e:
        meta["reason"] = f"kb_query_failed:{type(e).__name__}"
        return None, meta
    if row is None:
        meta["reason"] = "no_row"
        return None, meta
    body = row.body if isinstance(row.body, dict) else {}
    l4 = body.get("l4_floor")
    l3 = body.get("l3_floor")
    if not (isinstance(l4, (int, float)) and isinstance(l3, (int, float))):
        meta["reason"] = "missing_floors"
        return None, meta
    meta.update({
        "source": "kb",
        "version": row.version,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    })
    return {"l4_floor": float(l4), "l3_floor": float(l3)}, meta
