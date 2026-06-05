"""One-shot cleanup for the bad pipeline-369 state.

Pipeline 369 incorrectly minted a fresh SF Case (00001505 / 500dM00003JMeTnQAL)
because the duplicate-detection logic only looked at PO/Quote identifiers and
didn't catch the same-account, same-intent hold_release that pipeline 368 had
just completed. This script:

  1. Deletes SF Case 00001505 in Salesforce (best-effort; logs if it fails).
  2. Deletes the pipeline 369 row + trace events + hitl tasks.
  3. Resets email 501 (the duplicate hold-release email) so it can be
     re-processed through the now-fixed Stage 3 LLM duplicate matcher.

Run from the backend dir:
    .venv/bin/python scripts/cleanup_pipeline_369.py
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Email, HitlTask, Pipeline, TraceEvent  # noqa: E402
from app.services import salesforce_cases as sf_cases  # noqa: E402
from app.services import salesforce as sf_svc  # noqa: E402


PID = 369
SF_CASE_ID = "500dM00003JMeTnQAL"
EMAIL_ID = 501


def main() -> None:
    db = SessionLocal()
    try:
        pipe = db.get(Pipeline, PID)
        if not pipe:
            print(f"pipeline {PID}: not found (already cleaned up?)")
        else:
            print(f"pipeline {PID}: status={pipe.status} sf_case_id={pipe.salesforce_case_id}")

        # Step 1: delete SF Case (best-effort).
        try:
            conn = sf_svc.get_active_connection(db)
            if conn:
                sf = sf_svc.client_for(conn)
                sf.Case.delete(SF_CASE_ID)
                print(f"SF Case {SF_CASE_ID}: deleted")
            else:
                print(f"SF Case {SF_CASE_ID}: SKIP (no active SF connection)")
        except Exception as e:
            print(f"SF Case {SF_CASE_ID}: delete failed: {type(e).__name__}: {str(e)[:200]}")

        # Step 2: drop trace events, hitl tasks, pipeline row.
        te_count = db.query(TraceEvent).filter(TraceEvent.pipeline_id == PID).delete()
        ht_count = db.query(HitlTask).filter(HitlTask.pipeline_id == PID).delete()
        if pipe:
            db.delete(pipe)
        db.commit()
        print(f"trace_events deleted: {te_count}")
        print(f"hitl_tasks deleted: {ht_count}")
        print(f"pipeline {PID}: deleted")

        # Step 3: reset email 501 so it can be re-processed.
        e = db.get(Email, EMAIL_ID)
        if e:
            e.pipeline_id = None
            e.status = "pending"
            db.commit()
            print(f"email {EMAIL_ID}: reset to pending")
        else:
            print(f"email {EMAIL_ID}: not found")

        print("DONE — cleanup successful. Now POST /api/pipelines/run/501 to re-process.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
