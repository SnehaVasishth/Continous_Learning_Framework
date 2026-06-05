"""Stage 4 — Salesforce WorkOrder writes.

Native SF WorkOrder writes for Stage-4 actions (create_work_order,
update_work_order). The org's WorkOrder object requires Field Service Lightning;
when FSL isn't enabled we surface that as `feature_not_enabled_in_org` rather
than raising, so the demo continues without erroring out.
"""
from __future__ import annotations

import logging
import random
from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceError

from ..models import SalesforceConnection
from . import salesforce as sf_svc

log = logging.getLogger("salesforce_workorders")


_FSL_NOT_ENABLED_HINTS = (
    "INVALID_TYPE",
    "sObject type 'WorkOrder' is not supported",
    "Entity 'WorkOrder' is not supported",
)


def _esc(s: str) -> str:
    return (s or "").replace("'", "\\'")


def _looks_like_fsl_disabled(err: Exception) -> bool:
    msg = str(err)
    return any(h in msg for h in _FSL_NOT_ENABLED_HINTS)


def _generate_wo_number(customer_code: str | None) -> str:
    suffix = random.randint(10000, 99999)
    base = (customer_code or "WO").replace(" ", "")[:10]
    return f"WO-{base}-{suffix}"


def create_sf_work_order(
    conn: SalesforceConnection,
    *,
    account_id: str,
    customer_code: str | None,
    asset_serial: str,
    asset_sku: str | None,
    service_type: str,
    region: str,
    technician: str | None = None,
    document_url: str | None = None,
    wo_number: str | None = None,
) -> dict[str, Any]:
    """Create an SF WorkOrder under the matched Account, populating the custom
    fields seeded by salesforce_seed (WO_Number__c, Customer_Code__c,
    Asset_Serial__c, Asset_SKU__c, Type__c, Region__c, Technician__c,
    Document_Url__c). Returns `feature_not_enabled_in_org` if FSL is off."""
    if not account_id:
        return {"applied": False, "reason": "missing account_id"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        log.warning("create_sf_work_order: SF connect failed: %s", e)
        return {"applied": False, "reason": f"sf_connect_failed: {type(e).__name__}: {e}"[:300]}

    wo_num = wo_number or _generate_wo_number(customer_code)
    asset_id = _resolve_asset_id(sf, account_id=account_id, serial=asset_serial)

    payload: dict[str, Any] = {
        "AccountId": account_id,
        "Subject": f"{service_type} — {asset_serial}"[:255],
        "Description": f"Created by ZBrain agent fabric · service_type={service_type}",
        "Status": "New",
        "Priority": "Medium",
        "WO_Number__c": wo_num,
        "Customer_Code__c": customer_code,
        "Asset_Serial__c": asset_serial,
        "Asset_SKU__c": asset_sku,
        "Type__c": service_type,
        "Region__c": region,
        "Technician__c": technician,
        "Document_Url__c": document_url,
    }
    if asset_id:
        payload["AssetId"] = asset_id

    try:
        res = sf.WorkOrder.create({k: v for k, v in payload.items() if v is not None})
    except SalesforceError as e:
        if _looks_like_fsl_disabled(e):
            return {"applied": False, "reason": "feature_not_enabled_in_org", "feature": "FieldServiceLightning"}
        log.warning("create_sf_work_order failed for %s: %s", wo_num, e)
        return {"applied": False, "reason": f"workorder_create_failed: {e}"[:300]}
    except Exception as e:
        if _looks_like_fsl_disabled(e):
            return {"applied": False, "reason": "feature_not_enabled_in_org", "feature": "FieldServiceLightning"}
        log.warning("create_sf_work_order unexpected error for %s: %s", wo_num, e)
        return {"applied": False, "reason": f"workorder_create_failed: {type(e).__name__}: {e}"[:300]}

    if not res.get("success"):
        return {"applied": False, "reason": "WorkOrder.create returned non-success", "raw": res}

    instance_url = (conn.instance_url or "").rstrip("/")
    return {
        "applied": True,
        "salesforce_workorder_id": res["id"],
        "wo_number": wo_num,
        "asset_serial": asset_serial,
        "asset_sku": asset_sku,
        "type": service_type,
        "region": region,
        "salesforce_url": f"{instance_url}/lightning/r/WorkOrder/{res['id']}/view",
        "asset_id": asset_id,
    }


def _resolve_asset_id(sf: Salesforce, *, account_id: str, serial: str | None) -> str | None:
    if not serial or not account_id:
        return None
    soql = (
        "SELECT Id FROM Asset "
        f"WHERE AccountId = '{_esc(account_id)}' AND SerialNumber = '{_esc(serial)}' "
        "LIMIT 1"
    )
    try:
        res = sf.query(soql)
        recs = res.get("records") or []
        return recs[0]["Id"] if recs else None
    except Exception as e:
        log.debug("asset lookup failed for %s/%s: %s", account_id, serial, e)
        return None


def update_sf_work_order(
    conn: SalesforceConnection,
    *,
    wo_number: str,
    add_note: str | None = None,
    add_task: str | None = None,
) -> dict[str, Any]:
    """Find an SF WorkOrder by WO_Number__c and append a note/task to its
    Description. Returns `feature_not_enabled_in_org` if FSL is off, or
    `not_found` if no row matches."""
    if not wo_number:
        return {"applied": False, "reason": "missing wo_number"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        log.warning("update_sf_work_order: SF connect failed: %s", e)
        return {"applied": False, "reason": f"sf_connect_failed: {type(e).__name__}: {e}"[:300]}

    soql = (
        "SELECT Id, Description, WO_Number__c, Status "
        "FROM WorkOrder "
        f"WHERE WO_Number__c = '{_esc(wo_number)}' "
        "LIMIT 1"
    )
    try:
        res = sf.query(soql)
    except SalesforceError as e:
        if _looks_like_fsl_disabled(e):
            return {"applied": False, "reason": "feature_not_enabled_in_org", "feature": "FieldServiceLightning"}
        log.warning("update_sf_work_order query failed for %s: %s", wo_number, e)
        return {"applied": False, "reason": f"workorder_query_failed: {e}"[:300]}
    except Exception as e:
        if _looks_like_fsl_disabled(e):
            return {"applied": False, "reason": "feature_not_enabled_in_org", "feature": "FieldServiceLightning"}
        return {"applied": False, "reason": f"workorder_query_failed: {type(e).__name__}: {e}"[:300]}

    recs = res.get("records") or []
    if not recs:
        return {"applied": False, "reason": f"workorder {wo_number} not found in Salesforce"}

    wo = {k: v for k, v in recs[0].items() if k != "attributes"}
    existing = wo.get("Description") or ""
    parts = [p for p in [existing, add_note or "", ("task: " + add_task) if add_task else ""] if p]
    new_description = " · ".join(parts)

    try:
        sf.WorkOrder.update(wo["Id"], {"Description": new_description})
    except SalesforceError as e:
        log.warning("update_sf_work_order failed for %s: %s", wo_number, e)
        return {"applied": False, "reason": f"workorder_update_failed: {e}"[:300]}

    return {
        "applied": True,
        "salesforce_workorder_id": wo["Id"],
        "wo_number": wo.get("WO_Number__c"),
        "added_note": bool(add_note),
        "added_task": bool(add_task),
        "description_length": len(new_description),
    }


def list_open_sf_work_orders(
    conn: SalesforceConnection,
    *,
    account_id: str,
) -> list[dict[str, Any]]:
    """Read open WorkOrders for an account. Used by the report_wo_status action."""
    if not account_id:
        return []
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        log.warning("list_open_sf_work_orders: SF connect failed: %s", e)
        return []
    soql = (
        "SELECT Id, WO_Number__c, Type__c, Status, Region__c, Technician__c, "
        "Asset_Serial__c, StartDate "
        "FROM WorkOrder "
        f"WHERE AccountId = '{_esc(account_id)}' AND Status != 'Closed' "
        "ORDER BY CreatedDate DESC"
    )
    try:
        res = sf.query_all(soql)
    except SalesforceError as e:
        if _looks_like_fsl_disabled(e):
            return []
        log.warning("list_open_sf_work_orders failed for %s: %s", account_id, e)
        return []
    except Exception as e:
        if _looks_like_fsl_disabled(e):
            return []
        return []
    out: list[dict[str, Any]] = []
    for r in res.get("records") or []:
        r = {k: v for k, v in r.items() if k != "attributes"}
        out.append({
            "wo_number": r.get("WO_Number__c"),
            "type": r.get("Type__c"),
            "status": r.get("Status"),
            "team": r.get("Region__c"),
            "scheduled_date": r.get("StartDate"),
            "asset_serial": r.get("Asset_Serial__c"),
            "technician": r.get("Technician__c"),
            "salesforce_workorder_id": r.get("Id"),
        })
    return out
