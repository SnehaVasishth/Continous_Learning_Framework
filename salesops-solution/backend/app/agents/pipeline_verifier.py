"""Pipeline verifier — declarative invariants evaluated at stage boundaries.

Reads rules from the `pipeline_verification_rules` KB namespace and evaluates
each against the pipeline's current state. Records every evaluation as a
`verification` trace event (pass / fail / shadow_match) and applies the
configured corrective_action when a `block`-severity active rule fails.

The verifier is invoked from two hook points:

  verify_stage_boundary(db, pipe, stage)
      Called right after a stage_end trace event fires. Only evaluates rules
      whose `evaluate_at` list contains `stage_end:<stage>`.

  verify_final(db, pipe)
      Called from the orchestrator right before `pipe.status = completed`.
      Evaluates every rule whose `evaluate_at` contains 'final'.

Corrective actions (when severity=='block' and mode=='active'):
  - 'halt'             : raise VerifierHaltError; orchestrator marks pipe error
  - 'force_no_reply'   : set ctx.execution.no_reply = True (Stage 5 short-circuits)
  - 'force_tier_L2'    : downgrade decision.autonomy_tier to L2_HITL
  - 'flag_for_review'  : add a guardrail flag but allow through
  - 'none'             : record only (same as warn)
"""
from __future__ import annotations

import ast
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeRule, Pipeline
from ..trace_log import log_event

log = logging.getLogger("pipeline_verifier")


# Safe AST node types the predicate compiler will allow. Anything else is
# rejected at parse time — no function calls, no attribute writes, no
# imports, no comprehensions touching `__class__` etc.
_SAFE_NODES = {
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Name, ast.Load, ast.Constant, ast.Subscript, ast.Index, ast.Slice,
    ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Tuple, ast.List, ast.Dict, ast.Set,
    ast.IfExp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
    ast.Call,  # only allowed for whitelisted builtins (len/any/all/type/isinstance)
    ast.Attribute,  # read-only, e.g. for decision.get(...)
}

_SAFE_CALLS = {"len", "any", "all", "type", "isinstance", "bool", "str", "int", "float"}


class VerifierHaltError(Exception):
    """Raised when a block-severity rule with corrective_action='halt' fires."""

    def __init__(self, rule_key: str, message: str):
        self.rule_key = rule_key
        super().__init__(f"verifier halt ({rule_key}): {message}")


def _validate_predicate(expr: str) -> ast.Expression:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if type(node) not in _SAFE_NODES:
            raise ValueError(f"disallowed expression node: {type(node).__name__} in {expr!r}")
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                # Allow safe .get() calls on dict-like values (e.g., execution.get('applied'))
                if func.attr in {"get", "keys", "values", "items"}:
                    continue
            if name and name not in _SAFE_CALLS:
                raise ValueError(f"disallowed function call: {name}")
    return tree


def _eval(expr: str, scope: dict[str, Any]) -> Any:
    tree = _validate_predicate(expr)
    code = compile(tree, "<predicate>", "eval")
    safe_builtins = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
                     for k in _SAFE_CALLS}
    safe_builtins["True"] = True
    safe_builtins["False"] = False
    safe_builtins["None"] = None
    return eval(code, {"__builtins__": safe_builtins}, scope)  # noqa: S307


def _build_scope(pipe: Pipeline) -> dict[str, Any]:
    """Snapshot the pipeline state into a predicate-evaluation scope."""
    decision = pipe.decision or {}
    execution = pipe.execution or {}
    reply = pipe.reply or {}
    extracted = pipe.extracted or {}
    customer_match = pipe.customer_match or {}
    aioa = decision.get("aioa") or {}
    owner = decision.get("owner") or {}
    applied = execution.get("applied") if isinstance(execution.get("applied"), dict) else {}
    intake_block = {
        "fcnv_review_required": bool(decision.get("fcnv_review_required")),
        # other intake fields aren't on Pipeline directly — they're inside decision
    }

    line_items = extracted.get("line_items") or []
    if not isinstance(line_items, list):
        line_items = []
    assets_list = (
        extracted.get("add_assets")
        or extracted.get("assets")
        or (
            line_items
            if isinstance(line_items, list) and line_items and isinstance(line_items[0], dict)
            and (line_items[0].get("asset_serial") or line_items[0].get("model") or line_items[0].get("sku"))
            else []
        )
    )

    reply_body = reply.get("body") or reply.get("body_customer_language")
    soa_block = reply.get("sharepoint_filed") or {}

    return {
        "pipeline": pipe,
        "intent": pipe.intent,
        "tier": pipe.autonomy_tier,
        "status": pipe.status,
        "action": decision.get("action"),
        "confidence": pipe.confidence,
        "aioa_fired": bool(aioa.get("fired")),
        "aioa_outcome": (aioa.get("outcome") or None),
        "fcnv_review_required": bool(decision.get("fcnv_review_required")),
        "no_reply": bool(execution.get("no_reply")) or bool(reply.get("no_reply")),
        "is_no_reply": bool(execution.get("no_reply")) or bool(reply.get("no_reply")),
        "exec_status": execution.get("status"),
        "owner_label": owner.get("owner_label"),
        "owner_queue": owner.get("owner_queue"),
        "ai_handled": bool(owner.get("ai_handled")),
        "track": decision.get("track"),
        "assets_count": len(assets_list) if isinstance(assets_list, list) else 0,
        "has_po_number": bool(extracted.get("po_number")),
        "has_line_items": bool(line_items),
        "has_wo_number": bool(extracted.get("work_order_number") or extracted.get("wo_number")),
        "reply_body": reply_body,
        "reply_subject": reply.get("subject"),
        "reply_sent": bool(reply.get("sent")),
        "has_soa_attachment": bool(reply.get("soa_attachment") or reply.get("soa_path")),
        "has_sharepoint_url": bool(soa_block.get("web_url")),
        "decision": decision,
        "execution": execution,
        "intake": intake_block,
        "extracted": extracted,
        "reply": reply,
        "customer_match": customer_match,
    }


def _load_rules(db: Session) -> list[KnowledgeRule]:
    rows = (
        db.query(KnowledgeRule)
        .filter_by(namespace="pipeline_verification_rules")
        .order_by(KnowledgeRule.id)
        .all()
    )
    return rows


def _rule_applies_at(rule: KnowledgeRule, hook: str) -> bool:
    eval_at = (rule.body or {}).get("evaluate_at") or ["final"]
    if not isinstance(eval_at, list):
        return False
    return hook in eval_at


def _evaluate_one(rule: KnowledgeRule, scope: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one rule. Returns a result dict with verdict + diagnostics.

    Includes the rule's description + the raw applies_when / invariant
    predicates so the Trace UI can render plain-English context and the
    actual expression an admin would edit in the KB.
    """
    body = rule.body or {}
    out = {
        "rule_key": rule.key,
        "label": body.get("label") or rule.label or rule.key,
        "description": rule.description or body.get("description"),
        "severity": body.get("severity") or "audit",
        "mode": body.get("mode") or "shadow",
        "corrective_action": body.get("corrective_action") or "none",
        "applies_when": body.get("applies_when"),
        "invariant": body.get("invariant"),
        "applies": None,
        "verdict": "skipped",
        "error": None,
    }
    applies_when = body.get("applies_when") or "True"
    invariant = body.get("invariant") or "True"
    try:
        out["applies"] = bool(_eval(applies_when, scope))
    except Exception as e:
        out["applies"] = False
        out["error"] = f"applies_when error: {type(e).__name__}: {str(e)[:200]}"
        return out
    if not out["applies"]:
        out["verdict"] = "n/a"
        return out
    try:
        passed = bool(_eval(invariant, scope))
    except Exception as e:
        out["error"] = f"invariant error: {type(e).__name__}: {str(e)[:200]}"
        out["verdict"] = "error"
        return out
    out["verdict"] = "pass" if passed else "fail"
    return out


def _apply_correction(pipe: Pipeline, action: str, db: Session) -> str:
    """Apply a corrective action to the pipeline state. Returns the effect."""
    if action == "force_no_reply":
        execution = dict(pipe.execution or {})
        execution["no_reply"] = True
        pipe.execution = execution
        # Stage 5 has likely already run; clean the auto-send payload while
        # PRESERVING any CSR clarification draft (spec Step 12). The draft is
        # for the CSR to edit + send manually — wiping it would defeat the
        # purpose of the HITL surface.
        reply = dict(pipe.reply or {})
        reply["no_reply"] = True
        reply["sent"] = False
        if reply.get("csr_draft"):
            # Keep subject + body; just mark the auto-send intent off.
            reply["reason"] = "force_no_reply (verifier corrective_action — CSR draft preserved for HITL)"
        else:
            reply["body"] = None
            reply["body_customer_language"] = None
            reply["body_english"] = None
            reply["subject"] = None
            reply["reason"] = "force_no_reply (verifier corrective_action)"
        pipe.reply = reply
        db.commit()
        return "set execution.no_reply=true; CSR draft preserved" if reply.get("csr_draft") else "set execution.no_reply=true and cleared reply body"
    if action == "force_tier_L2":
        decision = dict(pipe.decision or {})
        decision["autonomy_tier"] = "L2_HITL"
        pipe.decision = decision
        pipe.autonomy_tier = "L2_HITL"
        db.commit()
        return "downgraded autonomy_tier to L2_HITL"
    if action == "flag_for_review":
        decision = dict(pipe.decision or {})
        flags = list(decision.get("verifier_flags") or [])
        decision["verifier_flags"] = flags
        pipe.decision = decision
        db.commit()
        return "flagged for review (no state change)"
    if action == "halt":
        raise VerifierHaltError("pipeline_halt", "block rule with halt action fired")
    return "no corrective action applied"


def _verify(
    db: Session,
    pipe: Pipeline,
    hook: str,
) -> dict[str, Any]:
    """Run every enabled rule that applies at this hook. Returns a summary
    and records a `verification` trace event per evaluated rule."""
    scope = _build_scope(pipe)
    rules = _load_rules(db)
    evaluated: list[dict] = []
    failed_blockers: list[dict] = []
    failed_warnings: list[dict] = []
    failed_audits: list[dict] = []
    corrections_applied: list[dict] = []

    for rule in rules:
        body = rule.body or {}
        if not body.get("enabled", True):
            continue
        if not _rule_applies_at(rule, hook):
            continue
        result = _evaluate_one(rule, scope)
        evaluated.append(result)

        if result["verdict"] == "fail" or result["verdict"] == "error":
            mode = result["mode"]
            severity = result["severity"]
            if severity == "block" and mode == "active":
                failed_blockers.append(result)
                # Apply corrective action
                action = result["corrective_action"]
                try:
                    effect = _apply_correction(pipe, action, db)
                    corrections_applied.append({"rule_key": rule.key, "action": action, "effect": effect})
                except VerifierHaltError:
                    raise
                except Exception as e:
                    corrections_applied.append({
                        "rule_key": rule.key,
                        "action": action,
                        "error": f"{type(e).__name__}: {str(e)[:200]}",
                    })
            elif severity == "warn" and mode == "active":
                failed_warnings.append(result)
            elif severity == "audit" or mode == "shadow":
                failed_audits.append(result)

    summary = {
        "hook": hook,
        "evaluated_count": len(evaluated),
        "applied_count": sum(1 for r in evaluated if r["verdict"] in ("pass", "fail", "error")),
        "passed": sum(1 for r in evaluated if r["verdict"] == "pass"),
        "failed_blockers": failed_blockers,
        "failed_warnings": failed_warnings,
        "failed_audits": failed_audits,
        "corrections_applied": corrections_applied,
        "results": evaluated,
    }

    # Log a single trace event per hook with the summary; the UI Verification
    # panel renders per-rule details from the results array.
    try:
        msg = (
            f"Verification {hook} — {summary['applied_count']} rule(s) applied · "
            f"{summary['passed']} pass · {len(failed_blockers)} block · "
            f"{len(failed_warnings)} warn · {len(failed_audits)} audit"
        )
        log_event(db, pipe.id, "verification", "checked", msg, data=summary)
    except Exception:
        # Never let a trace-write failure abort verification.
        pass

    # Publish notifications for active blocker failures.
    if failed_blockers:
        try:
            from ..services import notifications as notif_svc
            for r in failed_blockers:
                notif_svc.publish(
                    db,
                    kind=f"verification_{r['rule_key']}_{pipe.id}",
                    category="workflow",
                    severity="critical",
                    title=f"Verification failed: {r['label']}",
                    body=f"Pipeline #{pipe.id} — {r['rule_key']} invariant violated. Corrective action: {r['corrective_action']}",
                    action_url=f"/trace/{pipe.id}",
                    action_label="Open trace",
                    meta={"pipeline_id": pipe.id, "rule_key": r["rule_key"]},
                )
        except Exception:
            pass

    return summary


def verify_stage_boundary(db: Session, pipe: Pipeline, stage: str) -> dict[str, Any]:
    """Hook called from stage_timer after a stage finishes."""
    if pipe is None:
        return {}
    return _verify(db, pipe, hook=f"stage_end:{stage}")


def verify_final(db: Session, pipe: Pipeline) -> dict[str, Any]:
    """Hook called from the orchestrator right before pipe.status is finalized.

    Optionally runs an LLM second-opinion check (audit-severity, never blocks)
    when ENABLE_LLM_VERIFIER_AUDIT=1 is set in env.
    """
    if pipe is None:
        return {}
    summary = _verify(db, pipe, hook="final")
    _maybe_run_llm_audit(db, pipe)
    return summary


def _load_rfp_rubric(db: Session, intent: str) -> str | None:
    """Read the RFP path rubric for an intent from KB (intent namespace,
    rfp_rubric field on body). Operators edit this in the KB editor like any
    other field. Returns None if the intent row doesn't have one yet."""
    if not intent:
        return None
    try:
        row = (
            db.query(KnowledgeRule)
            .filter_by(namespace="intent", key=intent)
            .first()
        )
        if not row:
            return None
        body = row.body or {}
        rubric = body.get("rfp_rubric")
        if rubric:
            return rubric
        # Fall back to default_body if operator hasn't customised yet.
        default_body = row.default_body or {}
        return default_body.get("rfp_rubric")
    except Exception:
        return None


def _maybe_run_llm_audit(db: Session, pipe: Pipeline) -> None:
    """Optional LLM consistency check — feeds the LLM the pipeline trace and
    the RFP rubric for the resolved intent (loaded from the intent KB row),
    asks 'did this case follow the expected path?'. Records the answer as an
    audit-severity trace event.

    Off by default; flip ENABLE_LLM_VERIFIER_AUDIT=1 in env to enable. Adds
    ~2-3s latency + 1 LLM call per pipeline.
    """
    import os as _os
    if _os.environ.get("ENABLE_LLM_VERIFIER_AUDIT", "0") not in {"1", "true", "yes"}:
        return
    try:
        from .llm import ask_llm
        intent = pipe.intent or "unknown"
        rubric = _load_rfp_rubric(db, intent) or f"Intent {intent!r} has no rfp_rubric defined in KB."
        scope = _build_scope(pipe)
        case_summary = {
            "intent": intent,
            "tier": scope["tier"],
            "status": scope["status"],
            "aioa_outcome": scope["aioa_outcome"],
            "owner_label": scope["owner_label"],
            "owner_queue": scope["owner_queue"],
            "exec_status": scope["exec_status"],
            "no_reply": scope["no_reply"],
            "fcnv_review_required": scope["fcnv_review_required"],
            "has_soa_attachment": scope["has_soa_attachment"],
            "has_sharepoint_url": scope["has_sharepoint_url"],
        }
        prompt = (
            "You are a pipeline-consistency auditor. Below is the resolved state of one inbound "
            "customer email after running through a 6-stage AI automation pipeline. The RFP rubric "
            "for this intent describes the expected end-to-end path. Determine whether the case "
            "followed the expected path. Return strict JSON: "
            "{\"on_path\": bool, \"deviation\": str | null, \"severity\": \"audit\"|\"warn\"|\"block\"}.\n\n"
            f"INTENT: {intent}\n\n"
            f"RFP RUBRIC (from KB intent.{intent}.rfp_rubric):\n{rubric}\n\n"
            f"CASE STATE:\n{case_summary}\n\n"
            "Respond with JSON only."
        )
        parsed = ask_llm(
            system="You audit AI pipelines for adherence to the RFP use-case diagrams.",
            user=prompt,
            json_only=True,
        )
        if isinstance(parsed, dict):
            log_event(
                db, pipe.id, "verification", "llm_audit",
                f"LLM second-opinion: {'on path' if parsed.get('on_path') else 'deviation'} — {parsed.get('deviation') or 'no deviation'}",
                data={"llm_audit_result": parsed, "case_summary": case_summary},
            )
    except Exception:
        # Never let LLM audit failures affect the pipeline.
        log.exception("LLM second-opinion check failed for pipeline %s", pipe.id)
