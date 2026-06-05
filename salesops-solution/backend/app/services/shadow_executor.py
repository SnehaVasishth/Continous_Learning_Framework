"""Shadow A/B execution.

After a pipeline completes, every active shadow experiment whose change
applies to a stage that just ran gets replayed against the candidate body.
The candidate output is compared to the production output and persisted as
an `ABShadowResult` row. Realised-lift then reads agreement rate from this
table for a real side-by-side comparison instead of relying on CSR thumbs.

Supported change_types:
  - prompt + namespace="intent"        → uses `_replay_classifier`
  - prompt + namespace="agent_prompts" → uses `_replay_classifier` against
                                          the intake stage when the key is
                                          `intake:system`; recorded as
                                          unsupported for other stages
  - threshold                          → replays the tier decision with the
                                          candidate floors

Failures never raise — a shadow run is best-effort. Errors are recorded on
the row so the UI can show "shadow run errored" without breaking the
pipeline.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from ..models import ABExperiment, ABShadowResult, Email, Pipeline

log = logging.getLogger("shadow_executor")


def _active_shadow_experiments(db: Session) -> list[ABExperiment]:
    return (
        db.query(ABExperiment)
        .filter(ABExperiment.promote_status.in_(["shadow", "ready"]))
        .all()
    )


def _shadow_intent_classifier(db: Session, exp: ABExperiment, pipe: Pipeline) -> dict | None:
    """Replay Stage-1 intent classifier with the candidate body. Returns a
    dict suitable for ABShadowResult insertion, or None if the experiment
    is not eligible for an intent shadow run."""
    from .learning_promotion import _replay_classifier

    if not exp.candidate_prompt or not exp.kb_namespace or not exp.kb_key:
        return None
    if exp.kb_namespace not in ("intent", "agent_prompts"):
        return None
    if exp.kb_namespace == "agent_prompts" and exp.kb_key != "intake:system":
        # Other stage prompts not yet supported by the shadow executor.
        return {
            "agreement": False,
            "production_value": pipe.intent,
            "candidate_value": None,
            "divergence_note": f"shadow not implemented for agent_prompts/{exp.kb_key}",
            "method": "unsupported_stage",
            "latency_ms": 0,
            "field": "intent",
            "stage": "intake",
        }
    try:
        candidate_body = json.loads(exp.candidate_prompt) if exp.candidate_prompt else {}
    except Exception:
        candidate_body = {}
    email = db.get(Email, pipe.email_id) if pipe.email_id else None
    if email is None:
        return None
    email_dict = {
        "subject": email.subject or "",
        "body": email.body or "",
        "from": email.from_address or "",
        "attachments": email.attachments or [],
    }
    target_intent = exp.kb_key if exp.kb_namespace == "intent" else (pipe.intent or "po_intake")
    region = (pipe.customer_match or {}).get("region") if isinstance(pipe.customer_match, dict) else None
    started = time.perf_counter()
    out = _replay_classifier(
        email_dict,
        target_intent=target_intent,
        candidate_body=candidate_body if exp.kb_namespace == "intent" else {target_intent: candidate_body},
        account_region=region,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if out.get("error"):
        return {
            "agreement": False,
            "production_value": pipe.intent,
            "candidate_value": None,
            "divergence_note": out["error"],
            "method": out.get("method") or "llm_unavailable",
            "latency_ms": elapsed_ms,
            "field": "intent",
            "stage": "intake",
        }
    cand_intent = out.get("intent")
    prod_intent = pipe.intent
    return {
        "agreement": bool(cand_intent and cand_intent == prod_intent),
        "production_value": prod_intent,
        "candidate_value": cand_intent,
        "divergence_note": None if cand_intent == prod_intent else (
            f"production={prod_intent or 'none'}, candidate={cand_intent or 'none'}"
        ),
        "method": out.get("method") or "llm_replay",
        "latency_ms": elapsed_ms,
        "field": "intent",
        "stage": "intake",
    }


def _shadow_threshold(db: Session, exp: ABExperiment, pipe: Pipeline) -> dict | None:
    """Replay the autonomy tiering with the candidate per-intent floors."""
    if (exp.change_type or "").lower() != "threshold":
        return None
    if not exp.candidate_prompt:
        return None
    try:
        candidate = json.loads(exp.candidate_prompt) if isinstance(exp.candidate_prompt, str) else (exp.candidate_prompt or {})
    except Exception:
        return None
    l4 = candidate.get("l4_floor")
    l3 = candidate.get("l3_floor")
    if not (isinstance(l4, (int, float)) and isinstance(l3, (int, float))):
        return None
    confidence = pipe.confidence
    if confidence is None:
        return None
    from ..agents.decide import tier_for
    cand_tier = tier_for(float(confidence), l4_floor=float(l4), l3_floor=float(l3))
    prod_tier = pipe.autonomy_tier
    return {
        "agreement": cand_tier == prod_tier,
        "production_value": prod_tier,
        "candidate_value": cand_tier,
        "divergence_note": None if cand_tier == prod_tier else (
            f"with candidate floors l4={l4} l3={l3}, tier would be {cand_tier} vs production {prod_tier}"
        ),
        "method": "tier_recompute",
        "latency_ms": 1,
        "field": "tier",
        "stage": "decide",
    }


def run_for_pipeline(db: Session, pipe: Pipeline) -> int:
    """Run every applicable shadow experiment against this pipeline. Returns
    the number of ABShadowResult rows written. Never raises."""
    if pipe is None:
        return 0
    written = 0
    for exp in _active_shadow_experiments(db):
        try:
            result: dict | None = None
            ct = (exp.change_type or "").lower()
            if ct == "prompt":
                result = _shadow_intent_classifier(db, exp, pipe)
            elif ct == "threshold":
                result = _shadow_threshold(db, exp, pipe)
            else:
                # Other change types (pattern_list, routing_rule,
                # validation_rule) don't yet have a shadow runner. Skip.
                continue
            if result is None:
                continue
            row = ABShadowResult(
                experiment_id=exp.id,
                pipeline_id=pipe.id,
                stage=result.get("stage"),
                field=result.get("field"),
                agreement=bool(result.get("agreement")),
                production_value=str(result.get("production_value")) if result.get("production_value") is not None else None,
                candidate_value=str(result.get("candidate_value")) if result.get("candidate_value") is not None else None,
                divergence_note=result.get("divergence_note"),
                latency_ms=result.get("latency_ms"),
                method=result.get("method"),
            )
            db.add(row)
            db.commit()
            written += 1
        except Exception:
            log.exception("shadow_executor: experiment %s failed against pipeline %s", exp.id, pipe.id)
            try:
                db.rollback()
            except Exception:
                pass
    return written


def agreement_rate(db: Session, exp_id: int, window: int = 100) -> dict:
    """Compute the rolling agreement rate for an experiment over the last
    `window` shadow results."""
    rows = (
        db.query(ABShadowResult)
        .filter(ABShadowResult.experiment_id == exp_id)
        .order_by(ABShadowResult.created_at.desc())
        .limit(window)
        .all()
    )
    total = len(rows)
    if not total:
        return {"experiment_id": exp_id, "total": 0, "agreed": 0, "agreement_rate": None, "window": window}
    agreed = sum(1 for r in rows if r.agreement)
    return {
        "experiment_id": exp_id,
        "total": total,
        "agreed": agreed,
        "disagreed": total - agreed,
        "agreement_rate": round(agreed / total, 4),
        "window": window,
    }
