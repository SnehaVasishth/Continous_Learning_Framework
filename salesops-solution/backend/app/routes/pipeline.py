from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.orchestrator import run_pipeline
from ..agents.suggest_fix import run_suggest_fix
from ..config import OUTPUTS
from ..db import SessionLocal, get_db
from ..models import Email, Pipeline, TraceEvent
from ..services import salesforce_cases as sf_cases
from ..services.pipeline_pool import get_pool
from ..services.readiness import ReadinessBlocked, require_ready
from ..trace_log import log_event

router = APIRouter()


@router.post("/run/{email_id}")
def run(email_id: int, db: Session = Depends(get_db)):
    """Submit one email to the pipeline worker pool. Returns immediately with
    the assigned pipeline_id; the run executes concurrently.

    Enterprise readiness is enforced here: if Salesforce / SharePoint /
    mailbox is not connected, the call returns HTTP 412 Precondition Failed
    with the full readiness payload so the operator knows exactly what to
    reconnect. The pipeline never starts when a required dep is missing.
    """
    try:
        require_ready(db)
    except ReadinessBlocked as rb:
        raise HTTPException(status_code=412, detail=rb.report.to_dict())
    e = db.get(Email, email_id)
    if not e:
        raise HTTPException(404, "email not found")
    pipe = Pipeline(email_id=email_id)
    db.add(pipe)
    db.flush()
    e.pipeline_id = pipe.id
    e.status = "processing"
    db.commit()
    pipeline_id = pipe.id
    get_pool().submit(pipeline_id=pipeline_id, email_id=email_id)
    return {"pipeline_id": pipeline_id}


class _BatchRunIn(BaseModel):
    email_ids: List[int]


@router.post("/run-batch")
def run_batch(payload: _BatchRunIn, db: Session = Depends(get_db)):
    """Submit many emails to the worker pool at once. The pool executes them
    concurrently up to its bounded worker count (PIPELINE_POOL_WORKERS env
    var, default 8). Returns the list of assigned pipeline_ids and the queue
    snapshot at submission time so the caller can watch progress on
    /api/pipelines/queue-status.

    Each Pipeline insert is committed individually so the batch endpoint
    never holds a long write transaction. This minimises SQLite write-lock
    contention with the worker pool threads that are concurrently writing
    trace events; on Postgres this loop can be a single transaction."""
    if not payload.email_ids:
        raise HTTPException(400, "email_ids is required and must be non-empty")
    try:
        require_ready(db)
    except ReadinessBlocked as rb:
        raise HTTPException(status_code=412, detail=rb.report.to_dict())
    pool = get_pool()
    submitted: list[dict] = []
    rejected: list[dict] = []
    for email_id in payload.email_ids:
        try:
            e = db.get(Email, email_id)
            if not e:
                rejected.append({"email_id": email_id, "reason": "email_not_found"})
                continue
            pipe = Pipeline(email_id=email_id)
            db.add(pipe)
            db.flush()
            e.pipeline_id = pipe.id
            e.status = "processing"
            db.commit()
            submitted.append({"email_id": email_id, "pipeline_id": pipe.id})
        except Exception as ex:
            db.rollback()
            rejected.append({"email_id": email_id, "reason": f"db_error:{type(ex).__name__}"})
    for s in submitted:
        pool.submit(pipeline_id=s["pipeline_id"], email_id=s["email_id"])
    return {
        "submitted": submitted,
        "rejected": rejected,
        "queue_snapshot": pool.status(),
    }


@router.get("/queue-status")
def queue_status():
    """Live worker-pool status (in-flight, completed, errored, p50/p95/p99
    latency). The Dashboard uses this to render the throughput tile."""
    return get_pool().status()


# NOTE: /errors and /retry-batch must be registered BEFORE /{pipeline_id} so
# FastAPI doesn't treat the literal "errors" / "retry-batch" path segments
# as pipeline_id values.
@router.get("/errors")
def list_errored_pipelines(limit: int = 100, db: Session = Depends(get_db)):
    """List pipelines in `error` state with their email + reason. Powers the
    operator-facing 'Errors' view so failed runs can be triaged and retried
    in one place instead of clicking into each Trace one at a time."""
    q = (
        db.query(Pipeline)
        .filter(Pipeline.status == "error")
        .order_by(Pipeline.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    rows = q.all()
    out: list[dict] = []
    for p in rows:
        email = db.get(Email, p.email_id) if p.email_id else None
        err = p.error or ""
        if "process_killed_during_run" in err:
            reason_class = "restart_killed"
        elif "database is locked" in err:
            reason_class = "db_locked"
        elif "transaction has been rolled back" in err:
            reason_class = "txn_rolled_back"
        else:
            reason_class = "other"
        out.append({
            "pipeline_id": p.id,
            "email_id": p.email_id,
            "email_subject": email.subject if email else None,
            "email_from": email.from_address if email else None,
            "intent": p.intent,
            "started_at": p.started_at.isoformat() if p.started_at else None,
            "finished_at": p.finished_at.isoformat() if p.finished_at else None,
            "error": (err[:240] + "…") if len(err) > 240 else err,
            "reason_class": reason_class,
        })
    by_reason: dict[str, int] = {}
    for r in out:
        by_reason[r["reason_class"]] = by_reason.get(r["reason_class"], 0) + 1
    return {"items": out, "total": len(out), "by_reason": by_reason}


class _RetryBatchIn(BaseModel):
    pipeline_ids: List[int] | None = None
    retry_all_errored: bool = False


@router.post("/retry-batch")
def retry_batch(payload: _RetryBatchIn, db: Session = Depends(get_db)):
    """Retry many errored pipelines at once. Either pass explicit `pipeline_ids`
    or set `retry_all_errored: true` to retry every pipeline currently in
    `error` state. Each retry clears the stale HITL / cost / trace rows for
    that pipeline_id so the next run starts clean (same semantics as the
    single-pipeline /retry endpoint)."""
    try:
        require_ready(db)
    except ReadinessBlocked as rb:
        raise HTTPException(status_code=412, detail=rb.report.to_dict())
    if payload.retry_all_errored:
        ids = [
            pid for (pid,) in db.query(Pipeline.id).filter(Pipeline.status == "error").all()
        ]
    else:
        ids = list(payload.pipeline_ids or [])
    if not ids:
        raise HTTPException(400, "no pipeline_ids supplied and retry_all_errored=false")

    from ..models import HitlTask, CommunicationLog, CostEvent
    submitted: list[int] = []
    rejected: list[dict] = []
    pool = get_pool()
    for pid in ids:
        try:
            p = db.get(Pipeline, pid)
            if p is None:
                rejected.append({"pipeline_id": pid, "reason": "not_found"})
                continue
            if p.status not in ("error", "discarded"):
                rejected.append({"pipeline_id": pid, "reason": f"not_retryable:{p.status}"})
                continue
            p.status = "running"
            p.error = None
            p.intent = None
            p.language = None
            p.confidence = None
            p.autonomy_tier = None
            p.extracted = {}
            p.reconcile = {}
            p.decision = {}
            p.execution = {}
            p.reply = {}
            p.finished_at = None
            db.query(HitlTask).filter(HitlTask.pipeline_id == pid).delete()
            db.query(CommunicationLog).filter(CommunicationLog.pipeline_id == pid).delete()
            db.query(CostEvent).filter(CostEvent.pipeline_id == pid).delete()
            db.query(TraceEvent).filter(TraceEvent.pipeline_id == pid).delete()
            db.commit()
            pool.submit(pipeline_id=pid, email_id=p.email_id)
            submitted.append(pid)
        except Exception as ex:
            db.rollback()
            rejected.append({"pipeline_id": pid, "reason": f"db_error:{type(ex).__name__}:{str(ex)[:120]}"})
    return {"submitted": submitted, "rejected": rejected, "queue_snapshot": pool.status()}


def _load_case_summary(db: Session, p: Pipeline) -> dict | None:
    """Source the CCC-Request shape from Salesforce Case. Looks up by Pipeline_Id__c
    so it works even if the Case Id wasn't persisted on the Pipeline row."""
    rec = None
    if p.salesforce_case_id:
        try:
            rec = sf_cases.fetch_case(db, p.salesforce_case_id)
        except Exception:
            rec = None
    if not rec:
        try:
            rec = sf_cases.find_case_by_pipeline_id(db, p.id)
        except Exception:
            rec = None
    if not rec:
        return None
    created = rec.get("CreatedDate")
    closed = rec.get("ClosedDate")
    return {
        "id": rec.get("Id"),
        "case_number": rec.get("CaseNumber"),
        "request_number": rec.get("Request_Number__c"),
        "category": rec.get("Category__c"),
        "request_type": rec.get("Request_Type__c"),
        "sub_type": rec.get("Sub_Type__c"),
        "track": rec.get("Track__c"),
        "status": rec.get("Status"),
        "stage": rec.get("Stage__c"),
        "owner": rec.get("Owner_Label__c"),
        "fallout_reason": rec.get("Fallout_Reason__c"),
        "created_at": created,
        "closed_at": closed,
        "_source": "salesforce",
    }


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: int, db: Session = Depends(get_db)):
    p = db.get(Pipeline, pipeline_id)
    if not p:
        raise HTTPException(404)
    events = (
        db.query(TraceEvent)
        .filter(TraceEvent.pipeline_id == pipeline_id)
        .order_by(TraceEvent.id)
        .all()
    )
    email = db.get(Email, p.email_id) if p.email_id else None
    ccc = _load_case_summary(db, p)
    soa_url = None
    soa_sharepoint = None
    if (p.reply or {}).get("soa_path"):
        try:
            soa_url = f"/files/outputs/{Path(p.reply['soa_path']).name}"
        except Exception:
            soa_url = None
    # When the SOA was uploaded to SharePoint, prefer the SharePoint URL so the
    # case view pulls the canonical filed copy (not the local outputs copy).
    sp_filed = (p.reply or {}).get("sharepoint_filed") or {}
    if isinstance(sp_filed, dict) and sp_filed.get("web_url"):
        soa_sharepoint = {
            "store": sp_filed.get("store") or "SharePoint",
            "name": sp_filed.get("name"),
            "web_url": sp_filed.get("web_url"),
            "folder": sp_filed.get("folder"),
            "size": sp_filed.get("size"),
        }
        # Promote SharePoint URL to the primary SOA link
        soa_url = sp_filed.get("web_url") or soa_url

    return {
        "id": p.id,
        "email_id": p.email_id,
        "email_subject": email.subject if email else None,
        "email_from": email.from_address if email else None,
        "email_body": email.body if email else None,
        "email_language_hint": email.language_hint if email else None,
        "email_received_at": email.received_at.isoformat() if email and email.received_at else None,
        # Return full attachment dicts so the Trace UI can build the right
        # download URL (including the `path` field for files saved into a
        # sub-folder like `use_case_seeds/`). The frontend tolerates both
        # shapes (string vs dict) — see attachmentUrl() in PreviewModal.tsx.
        "email_attachments": (
            [
                (
                    {
                        "name": a.get("name"),
                        "path": a.get("path") or a.get("name"),
                        "kind": a.get("kind"),
                        "type": a.get("type"),
                    }
                    if isinstance(a, dict)
                    else {"name": str(a)}
                )
                for a in (email.attachments or [])
            ]
            if email
            else []
        ),
        "started_at": p.started_at.isoformat() if p.started_at else None,
        "finished_at": p.finished_at.isoformat() if p.finished_at else None,
        "status": p.status,
        "intent": p.intent,
        "language": p.language,
        "confidence": p.confidence,
        "autonomy_tier": p.autonomy_tier,
        "ccc_request": ccc,
        "customer_match": p.customer_match or {},
        "extracted": p.extracted,
        "reconcile": p.reconcile,
        "decision": p.decision,
        "execution": p.execution,
        "reply": p.reply,
        "suggested_fix": p.suggested_fix or {},
        "soa_url": soa_url,
        "soa_sharepoint": soa_sharepoint,
        "error": p.error,
        # === v1.1 TASK-4 / TASK-5 / TASK-9 ===
        "existing_case_id": getattr(p, "existing_case_id", None),
        "existing_case_status": getattr(p, "existing_case_status", None),
        "ccc_action": getattr(p, "ccc_action", None),
        "duplicate_detected": bool(getattr(p, "duplicate_detected", False)),
        "routing_target": getattr(p, "routing_target", None),
        "routing_basis": getattr(p, "routing_basis", None),
        "shadow_classification": getattr(p, "shadow_classification", None),
        "events": [
            {
                "id": ev.id,
                "ts": ev.ts.isoformat(),
                "stage": ev.stage,
                "kind": ev.kind,
                "message": ev.message,
                "data": ev.data,
                "duration_ms": ev.duration_ms,
            }
            for ev in events
        ],
    }


@router.post("/{pipeline_id}/suggest-fix")
def suggest_fix(pipeline_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.get(Pipeline, pipeline_id)
    if not p:
        raise HTTPException(404)
    if not (p.reconcile or {}).get("issues"):
        raise HTTPException(400, "no mismatches to address")
    p.suggested_fix = {"status": "drafting"}
    db.commit()
    background.add_task(_run_suggest_in_thread, pipeline_id)
    return {"ok": True}


def _run_suggest_in_thread(pipeline_id: int) -> None:
    db = SessionLocal()
    try:
        p = db.get(Pipeline, pipeline_id)
        if not p:
            return
        email = db.get(Email, p.email_id)
        if not email:
            return
        try:
            result = run_suggest_fix(
                email={
                    "from": email.from_address,
                    "subject": email.subject,
                    "body": email.body,
                },
                intake={"language": p.language, "intent": p.intent},
                extracted=p.extracted or {},
                reconcile_result=p.reconcile or {},
            )
            p.suggested_fix = {"status": "ready", **result}
            log_event(db, pipeline_id, "suggest_fix", "drafted", "Corrective email drafted", data=result)
        except Exception as e:
            p.suggested_fix = {"status": "error", "error": str(e)[:300]}
            log_event(db, pipeline_id, "suggest_fix", "error", f"draft failed: {e}")
        db.commit()
    finally:
        db.close()


@router.post("/{pipeline_id}/retry")
def retry_pipeline(pipeline_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        require_ready(db)
    except ReadinessBlocked as rb:
        raise HTTPException(status_code=412, detail=rb.report.to_dict())
    p = db.get(Pipeline, pipeline_id)
    if not p:
        raise HTTPException(404)
    p.status = "running"
    p.error = None
    p.intent = None
    p.language = None
    p.confidence = None
    p.autonomy_tier = None
    p.extracted = {}
    p.reconcile = {}
    p.decision = {}
    p.execution = {}
    p.reply = {}
    p.finished_at = None
    # Also clear HITL tasks, cost events, communication logs from the
    # previous run so the retry starts clean.
    from ..models import HitlTask, CommunicationLog, CostEvent
    db.query(HitlTask).filter(HitlTask.pipeline_id == pipeline_id).delete()
    db.query(CommunicationLog).filter(CommunicationLog.pipeline_id == pipeline_id).delete()
    db.query(CostEvent).filter(CostEvent.pipeline_id == pipeline_id).delete()
    db.query(TraceEvent).filter(TraceEvent.pipeline_id == pipeline_id).delete()
    db.commit()
    email_id = p.email_id
    get_pool().submit(pipeline_id=pipeline_id, email_id=email_id)
    return {"ok": True, "pipeline_id": pipeline_id}
