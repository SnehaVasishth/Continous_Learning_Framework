"""Knowledge Base — list / get / update / reset rules."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import kb
from ..db import get_db

router = APIRouter()


class RuleUpdate(BaseModel):
    body: dict
    label: str | None = None
    description: str | None = None


class RuleCreate(BaseModel):
    key: str
    body: dict
    label: str | None = None
    description: str | None = None


def _serialize(r) -> dict:
    return {
        "id": r.id,
        "namespace": r.namespace,
        "key": r.key,
        "label": r.label,
        "description": r.description,
        "body": r.body or {},
        "default_body": r.default_body or {},
        "version": r.version,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "updated_by": r.updated_by,
        "is_modified": (r.body or {}) != (r.default_body or {}),
    }


@router.get("/{namespace}")
def list_namespace(namespace: str, db: Session = Depends(get_db)):
    return [_serialize(r) for r in kb.list_rules(db, namespace)]


@router.get("/{namespace}/{key}")
def get_rule(namespace: str, key: str, db: Session = Depends(get_db)):
    r = kb.get_rule(db, namespace, key)
    if not r:
        raise HTTPException(404, "rule not found")
    return _serialize(r)


@router.post("/{namespace}")
def create_rule(namespace: str, payload: RuleCreate, db: Session = Depends(get_db)):
    """Create a new KB rule in `namespace`. Rejects if the key already exists
    (use PUT to update). Use this when a non-technical operator needs to add a
    glossary term, a new outlook rule, or any other KB row from the UI.
    """
    if kb.get_rule(db, namespace, payload.key):
        raise HTTPException(409, f"rule already exists: {namespace}/{payload.key}")
    try:
        r = kb.create_rule(
            db,
            namespace=namespace,
            key=payload.key,
            body=payload.body,
            label=payload.label,
            description=payload.description,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _serialize(r)


@router.put("/{namespace}/{key}")
def update_rule(namespace: str, key: str, body: RuleUpdate, db: Session = Depends(get_db)):
    try:
        r = kb.update_rule(
            db,
            namespace=namespace,
            key=key,
            body=body.body,
            label=body.label,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _serialize(r)


@router.post("/{namespace}/{key}/reset")
def reset_rule(namespace: str, key: str, db: Session = Depends(get_db)):
    try:
        r = kb.reset_rule(db, namespace=namespace, key=key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _serialize(r)


@router.post("/seed")
def seed(db: Session = Depends(get_db)):
    """Idempotent — seeds defaults for any namespaces/keys that don't exist yet."""
    counts = kb.seed_defaults(db)
    return {"ok": True, "seeded": counts}


# --- Verification-rule simulator -----------------------------------------


class SimulateRuleBody(BaseModel):
    body: dict          # the rule body to test (applies_when + invariant + meta)
    limit: int = 200    # max pipelines to back-test against (newest-first)


@router.post("/pipeline_verification_rules/_simulate")
def simulate_verification_rule(body: SimulateRuleBody, db: Session = Depends(get_db)):
    """Run a draft verification rule against the last N pipelines and return
    match/fail/pass counts plus a per-pipeline result list.

    The operator uses this from the KB editor (Run against last N pipelines)
    to test a new rule before promoting it from shadow to active."""
    from ..models import Pipeline, KnowledgeRule
    from ..agents.pipeline_verifier import _build_scope, _evaluate_one  # type: ignore

    # Build a transient KnowledgeRule-like object the evaluator can use.
    class _Stub:
        def __init__(self, b: dict):
            self.key = b.get("key") or "__draft__"
            self.label = b.get("label") or "draft rule"
            self.body = b

    rule = _Stub(body.body)

    rows = (
        db.query(Pipeline)
        .order_by(Pipeline.id.desc())
        .limit(max(1, min(1000, body.limit)))
        .all()
    )
    results: list[dict] = []
    n_applied = 0
    n_pass = 0
    n_fail = 0
    n_error = 0
    for p in rows:
        scope = _build_scope(p)
        r = _evaluate_one(rule, scope)
        r["pipeline_id"] = p.id
        r["intent"] = p.intent
        r["tier"] = p.autonomy_tier
        r["status"] = p.status
        results.append(r)
        if r["verdict"] == "pass":
            n_applied += 1
            n_pass += 1
        elif r["verdict"] == "fail":
            n_applied += 1
            n_fail += 1
        elif r["verdict"] == "error":
            n_applied += 1
            n_error += 1
    return {
        "checked_pipelines": len(rows),
        "rule_applied_count": n_applied,
        "rule_passed_count": n_pass,
        "rule_failed_count": n_fail,
        "rule_error_count": n_error,
        "match_rate_pct": round((n_applied / len(rows) * 100), 1) if rows else 0.0,
        "fail_rate_pct": round((n_fail / max(1, n_applied) * 100), 1) if n_applied else 0.0,
        "results": results[:limit_results(rows)],
    }


def limit_results(rows):
    """Cap the per-pipeline detail list at 100 to keep response small."""
    return min(100, len(rows))
