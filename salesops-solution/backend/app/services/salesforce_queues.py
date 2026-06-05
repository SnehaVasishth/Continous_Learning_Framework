"""Salesforce queue provisioning + sync for the owner_mapping KB namespace.

Two operations:

  provision_owner_queues(db, conn, only_keys=None)
      For every row in the `owner_mapping` KB namespace whose
      `salesforce.queue_developer_name` is set and `queue_id` is null,
      create a Salesforce Group (Type='Queue') with that DeveloperName + a
      QueueSObject(SObjectType='Case') binding so the queue can own Cases.
      Idempotent: if a Group with the same DeveloperName already exists in
      the org, we adopt its Id instead of creating a duplicate.

  sync_owner_queues(db, conn)
      Pull every Case-eligible Queue (`Group.Type='Queue'` with a
      QueueSObject row for SObjectType='Case') from SF. Match by
      DeveloperName against the KB rows and update `salesforce.queue_id`,
      `salesforce.queue_label`, `salesforce.last_synced_at`. Operators run
      this after editing queues in the SF UI directly.

Both operations update the KB rows in-place and bump version + updated_by.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeRule, SalesforceConnection
from . import salesforce as sf_svc

log = logging.getLogger("salesforce_queues")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kb_rows(db: Session, only_keys: list[str] | None = None) -> list[KnowledgeRule]:
    q = db.query(KnowledgeRule).filter_by(namespace="owner_mapping")
    if only_keys:
        q = q.filter(KnowledgeRule.key.in_(only_keys))
    return q.all()


def _save(db: Session, row: KnowledgeRule, *, by: str) -> None:
    row.version = (row.version or 1) + 1
    row.updated_by = by
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def provision_owner_queues(
    db: Session,
    conn: SalesforceConnection,
    *,
    only_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Create missing Group(Type='Queue') + QueueSObject(Case) for every
    KB owner_mapping row with a developer name. Returns a summary."""
    sf = sf_svc.client_for(conn)

    rows = _kb_rows(db, only_keys=only_keys)
    created: list[dict] = []
    skipped: list[dict] = []
    errored: list[dict] = []

    for row in rows:
        body = dict(row.body or {})
        sf_block = dict(body.get("salesforce") or {})
        dev_name = sf_block.get("queue_developer_name")
        if not dev_name:
            skipped.append({"key": row.key, "reason": "no queue_developer_name (ai_handled or unprovisioned)"})
            continue
        if sf_block.get("queue_id"):
            skipped.append({"key": row.key, "reason": "already provisioned", "queue_id": sf_block["queue_id"]})
            continue
        try:
            # Look for an existing Group with this DeveloperName so re-runs
            # don't double-create. Salesforce SOQL on Group: id, name, type,
            # developer_name. Note: DeveloperName field on Group is
            # Type-segmented; queues use a unique name across the org.
            esc = dev_name.replace("'", "\\'")
            existing = sf.query(
                f"SELECT Id, Name, DeveloperName FROM Group WHERE Type='Queue' AND DeveloperName='{esc}' LIMIT 1"
            )
            recs = existing.get("records") or []
            if recs:
                queue_id = recs[0]["Id"]
                queue_label = recs[0]["Name"]
                # Ensure QueueSObject row exists for Case.
                qsobj = sf.query(
                    f"SELECT Id FROM QueueSObject WHERE QueueId='{queue_id}' AND SObjectType='Case' LIMIT 1"
                )
                if not (qsobj.get("records") or []):
                    sf.QueueSObject.create({"QueueId": queue_id, "SObjectType": "Case"})
                created.append({
                    "key": row.key,
                    "queue_id": queue_id,
                    "queue_label": queue_label,
                    "developer_name": dev_name,
                    "action": "adopted_existing",
                })
            else:
                label = sf_block.get("queue_label") or row.label or dev_name
                grp_create = sf.Group.create({
                    "Name": label,
                    "DeveloperName": dev_name,
                    "Type": "Queue",
                })
                if not grp_create.get("success"):
                    raise RuntimeError(f"Group.create failed: {grp_create}")
                queue_id = grp_create["id"]
                queue_label = label
                qsobj_create = sf.QueueSObject.create({
                    "QueueId": queue_id,
                    "SObjectType": "Case",
                })
                if not qsobj_create.get("success"):
                    raise RuntimeError(f"QueueSObject.create failed: {qsobj_create}")
                created.append({
                    "key": row.key,
                    "queue_id": queue_id,
                    "queue_label": queue_label,
                    "developer_name": dev_name,
                    "action": "created",
                })
            # Persist into KB
            sf_block["queue_id"] = queue_id
            sf_block["queue_label"] = queue_label
            sf_block["last_synced_at"] = _now_iso()
            body["salesforce"] = sf_block
            row.body = body
            _save(db, row, by="salesforce_queues_provision")
        except Exception as e:
            log.warning("provision queue failed for %s: %s", row.key, e)
            errored.append({"key": row.key, "developer_name": dev_name, "error": f"{type(e).__name__}: {str(e)[:300]}"})

    return {
        "checked": len(rows),
        "created": created,
        "skipped": skipped,
        "errored": errored,
    }


def sync_owner_queues(db: Session, conn: SalesforceConnection) -> dict[str, Any]:
    """Pull every Case-eligible Queue from SF and update KB rows that match
    by DeveloperName. Surfaces rows that don't yet have a queue in SF so the
    UI can prompt the operator to Provision."""
    sf = sf_svc.client_for(conn)
    # All Case-eligible queues (joined via QueueSObject)
    soql = (
        "SELECT QueueId, Queue.DeveloperName, Queue.Name "
        "FROM QueueSObject WHERE SObjectType='Case' LIMIT 200"
    )
    res = sf.query(soql)
    sf_queues_by_dev: dict[str, dict] = {}
    for r in res.get("records") or []:
        qid = r.get("QueueId")
        q = r.get("Queue") or {}
        dev = q.get("DeveloperName")
        name = q.get("Name")
        if dev:
            sf_queues_by_dev[dev] = {"id": qid, "name": name}

    rows = _kb_rows(db)
    synced: list[dict] = []
    not_in_sf: list[dict] = []
    for row in rows:
        body = dict(row.body or {})
        sf_block = dict(body.get("salesforce") or {})
        dev_name = sf_block.get("queue_developer_name")
        if not dev_name:
            continue
        if dev_name in sf_queues_by_dev:
            entry = sf_queues_by_dev[dev_name]
            sf_block["queue_id"] = entry["id"]
            sf_block["queue_label"] = entry["name"]
            sf_block["last_synced_at"] = _now_iso()
            body["salesforce"] = sf_block
            row.body = body
            _save(db, row, by="salesforce_queues_sync")
            synced.append({
                "key": row.key,
                "queue_id": entry["id"],
                "queue_label": entry["name"],
                "developer_name": dev_name,
            })
        else:
            not_in_sf.append({"key": row.key, "developer_name": dev_name})

    return {
        "case_queues_in_sf": len(sf_queues_by_dev),
        "synced": synced,
        "not_in_sf": not_in_sf,
    }
