# === v1.1 TASK-7 START ===
"""Test-corpus regression suite — labelled emails + run-results dashboard.

Mirrors the prior Keysight POC's accuracy report ("Initial Pass / Failed /
Post-Fix Pass / Still Failed" buckets). Operators upload a CSV of labelled
emails, click Run, and the backend iterates each case through the live
pipeline and stores expected-vs-actual.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import (
    Email,
    Pipeline,
    TestCase,
    TestRun,
    TestRunResult,
    now,
)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- shapes ----------

class TestCaseIn(BaseModel):
    name: str
    subject: str
    from_address: str
    body: str
    expected_intent: str
    expected_action: str | None = None
    expected_routing: str | None = None
    expected_keywords: list[str] = []
    notes: str | None = None


def _serialize_case(c: TestCase) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "subject": c.subject,
        "from_address": c.from_address,
        "body": c.body,
        "expected_intent": c.expected_intent,
        "expected_action": c.expected_action,
        "expected_routing": c.expected_routing,
        "expected_keywords": c.expected_keywords or [],
        "notes": c.notes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _serialize_run(r: TestRun) -> dict:
    return {
        "id": r.id,
        "label": r.label,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "case_count": r.case_count,
        "initial_pass": r.initial_pass,
        "initial_fail": r.initial_fail,
        "post_fix_pass": r.post_fix_pass,
        "still_failed": r.still_failed,
        "pass_pct": (round(100 * r.initial_pass / r.case_count, 1) if r.case_count else None),
        "post_fix_pct": (
            round(100 * (r.initial_pass + r.post_fix_pass) / r.case_count, 1)
            if r.case_count else None
        ),
    }


def _serialize_result(r: TestRunResult, c: TestCase) -> dict:
    return {
        "id": r.id,
        "test_case_id": r.test_case_id,
        "case_name": c.name if c else None,
        "case_subject": c.subject if c else None,
        "expected_intent": c.expected_intent if c else None,
        "actual_intent": r.actual_intent,
        "actual_keywords": r.actual_keywords or [],
        "actual_reason": r.actual_reason,
        "pass_initial": bool(r.pass_initial),
        "pass_post_fix": r.pass_post_fix,
        "pipeline_id": r.pipeline_id,
        "diff": r.diff or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# ---------- routes ----------

@router.get("/cases")
def list_cases(db: Session = Depends(get_db)):
    rows = db.query(TestCase).order_by(TestCase.id.desc()).limit(500).all()
    return [_serialize_case(c) for c in rows]


@router.post("/cases")
def add_case(payload: TestCaseIn, db: Session = Depends(get_db)):
    case = TestCase(
        name=payload.name,
        subject=payload.subject,
        from_address=payload.from_address,
        body=payload.body,
        expected_intent=payload.expected_intent,
        expected_action=payload.expected_action,
        expected_routing=payload.expected_routing,
        expected_keywords=payload.expected_keywords,
        notes=payload.notes,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _serialize_case(case)


@router.delete("/cases/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    c = db.get(TestCase, case_id)
    if not c:
        raise HTTPException(404, "case not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/import")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Bulk-upload test cases via CSV.

    Required columns: name, subject, from, body, expected_intent
    Optional: expected_action, expected_routing, expected_keywords (comma-sep), notes
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    inserted = 0
    skipped = 0
    for row in reader:
        name = (row.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        kws_raw = (row.get("expected_keywords") or "").strip()
        kws = [k.strip() for k in kws_raw.split(",") if k.strip()] if kws_raw else []
        case = TestCase(
            name=name,
            subject=(row.get("subject") or "").strip(),
            from_address=(row.get("from") or row.get("from_address") or "").strip(),
            body=(row.get("body") or "").strip(),
            expected_intent=(row.get("expected_intent") or "").strip(),
            expected_action=(row.get("expected_action") or None),
            expected_routing=(row.get("expected_routing") or None),
            expected_keywords=kws,
            notes=(row.get("notes") or None),
        )
        db.add(case)
        inserted += 1
    db.commit()
    return {"inserted": inserted, "skipped": skipped}


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    rows = db.query(TestRun).order_by(TestRun.id.desc()).limit(50).all()
    return [_serialize_run(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(TestRun, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return _serialize_run(run)


@router.get("/runs/{run_id}/results")
def get_run_results(run_id: int, db: Session = Depends(get_db)):
    run = db.get(TestRun, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    out: list[dict] = []
    rows = db.query(TestRunResult).filter_by(test_run_id=run_id).all()
    cases = {c.id: c for c in db.query(TestCase).filter(
        TestCase.id.in_([r.test_case_id for r in rows])
    ).all()}
    for r in rows:
        out.append(_serialize_result(r, cases.get(r.test_case_id)))
    return {"run": _serialize_run(run), "results": out}


class RunOptions(BaseModel):
    label: str | None = None
    case_ids: list[int] | None = None  # None = run all


@router.post("/run")
def trigger_run(opts: RunOptions, db: Session = Depends(get_db)):
    """Trigger a corpus run.

    Picks `case_ids` if provided, else runs all cases. For each case:
      1. Synthesize an Email row + Pipeline row
      2. Invoke the orchestrator inline (we don't background-task here so the
         route returns when the run is done — important for the demo's
         "click Run, see the dashboard update" flow)
      3. Compare actual_intent to expected_intent
      4. Record TestRunResult
    Returns the TestRun summary.
    """
    label = opts.label or f"v1.1 corpus run @ {_now_iso()}"
    if opts.case_ids:
        cases = db.query(TestCase).filter(TestCase.id.in_(opts.case_ids)).all()
    else:
        cases = db.query(TestCase).order_by(TestCase.id).all()
    if not cases:
        raise HTTPException(400, "no test cases to run")

    run = TestRun(label=label, case_count=len(cases))
    db.add(run)
    db.commit()
    db.refresh(run)

    initial_pass = 0
    initial_fail = 0
    from ..agents.orchestrator import run_pipeline as _run_pipeline

    for case in cases:
        e = Email(
            received_at=now(),
            subject=case.subject or f"[corpus] {case.name}",
            from_address=case.from_address or "test@corpus.local",
            body=case.body or "",
            language_hint="en",
            attachments=[],
            status="processing",
        )
        db.add(e)
        db.flush()
        pipe = Pipeline(email_id=e.id, started_at=now())
        db.add(pipe)
        db.flush()
        e.pipeline_id = pipe.id
        db.commit()

        actual_intent = None
        actual_reason = None
        try:
            db_session = SessionLocal()
            try:
                _run_pipeline(db_session, pipeline_id=pipe.id, email_id=e.id)
                final_pipe = db_session.get(Pipeline, pipe.id)
                if final_pipe:
                    actual_intent = final_pipe.intent
                    intake = (final_pipe.decision or {}).get("intake") or {}
                    actual_reason = intake.get("intent_reasoning") if isinstance(intake, dict) else None
            finally:
                db_session.close()
        except Exception as ex:
            actual_reason = f"pipeline_error: {type(ex).__name__}: {str(ex)[:200]}"

        passed = bool(actual_intent and actual_intent == case.expected_intent)
        if passed:
            initial_pass += 1
        else:
            initial_fail += 1

        diff: dict = {}
        if not passed:
            diff = {
                "intent": {"expected": case.expected_intent, "actual": actual_intent},
            }

        result = TestRunResult(
            test_run_id=run.id,
            test_case_id=case.id,
            actual_intent=actual_intent,
            actual_keywords=[],
            actual_reason=actual_reason,
            pass_initial=passed,
            pass_post_fix=None,
            pipeline_id=pipe.id,
            diff=diff,
        )
        db.add(result)
        db.commit()

    run.initial_pass = initial_pass
    run.initial_fail = initial_fail
    run.finished_at = now()
    db.commit()
    db.refresh(run)
    return _serialize_run(run)
# === v1.1 TASK-7 END ===
