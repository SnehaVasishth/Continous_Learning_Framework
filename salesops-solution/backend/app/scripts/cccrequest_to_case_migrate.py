"""One-shot migration — local SQLite CCCRequest rows -> Salesforce Cases.

Walks every existing CCCRequest, resolves the matching Salesforce Account by
the customer's Customer_Code__c, and creates a Case on it. Uses
Request_Number__c as an external id so re-runs are idempotent.

Usage:
    python -m app.scripts.cccrequest_to_case_migrate
    python -m app.scripts.cccrequest_to_case_migrate --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import CCCRequest, Customer, Pipeline
from ..services import salesforce as sf_svc
from ..services import salesforce_cases as sf_cases

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cccrequest_to_case_migrate")


def _build_account_index(sf) -> dict[str, str]:
    code_to_id: dict[str, str] = {}
    for rec in sf.query_all("SELECT Id, Customer_Code__c FROM Account WHERE Customer_Code__c != null").get("records", []):
        code = rec.get("Customer_Code__c")
        if code:
            code_to_id[code] = rec["Id"]
    return code_to_id


def migrate(db: Session, *, dry_run: bool = False) -> dict[str, int]:
    counts = {"total": 0, "created": 0, "updated": 0, "skipped_no_account": 0, "failed": 0}

    conn = sf_svc.get_active_connection(db)
    if not conn:
        log.error("No active Salesforce connection — connect first via /api/integrations/salesforce/connect")
        return counts
    sf = sf_svc.client_for(conn)

    code_to_account_id = _build_account_index(sf)
    log.info("indexed %d Salesforce accounts by Customer_Code__c", len(code_to_account_id))

    customer_code_by_id = {c.id: c.code for c in db.query(Customer).all()}

    rows = db.query(CCCRequest).order_by(CCCRequest.id).all()
    counts["total"] = len(rows)
    log.info("found %d CCCRequest rows to migrate", len(rows))

    pipeline_by_ccc_id: dict[int, Pipeline] = {}
    for p in db.query(Pipeline).filter(Pipeline.ccc_request_id.isnot(None)).all():
        pipeline_by_ccc_id[p.ccc_request_id] = p

    for ccc in rows:
        cust_code = customer_code_by_id.get(ccc.customer_id) if ccc.customer_id else None
        account_id = code_to_account_id.get(cust_code) if cust_code else None
        pipe = pipeline_by_ccc_id.get(ccc.id)
        pipeline_id = pipe.id if pipe else None

        if dry_run:
            log.info(
                "DRY RUN — would upsert Case req=%s account=%s status=%s stage=%s",
                ccc.request_number, account_id, ccc.status, ccc.stage,
            )
            continue

        try:
            res = sf_cases.create_case(
                db,
                account_id=account_id,
                email_id=ccc.email_id,
                pipeline_id=pipeline_id,
                request_number=ccc.request_number,
                category=ccc.category,
                request_type=ccc.request_type,
                sub_type=ccc.sub_type,
                track=ccc.track,
                status=ccc.status,
                stage=ccc.stage,
                owner_label=ccc.owner,
                fallout_reason=ccc.fallout_reason,
                notes=ccc.notes,
                customer_code=cust_code,
            )
        except Exception as e:
            log.warning("create_case failed for %s: %s", ccc.request_number, e)
            counts["failed"] += 1
            continue

        if not res.get("ok"):
            log.warning("create_case not ok for %s: %s", ccc.request_number, res.get("reason"))
            counts["failed"] += 1
            continue

        if res.get("upserted"):
            counts["updated"] += 1
        else:
            counts["created"] += 1

        if pipe and res.get("case_id") and not pipe.salesforce_case_id:
            pipe.salesforce_case_id = res["case_id"]

        if not account_id:
            counts["skipped_no_account"] += 1

    if not dry_run:
        db.commit()

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite CCCRequest rows to Salesforce Cases.")
    parser.add_argument("--dry-run", action="store_true", help="Plan but don't write to Salesforce")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        counts = migrate(db, dry_run=args.dry_run)
        log.info("migration counts: %s", counts)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
