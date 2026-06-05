"""Stage 4 — Salesforce ServiceContract writes.

Native SF ServiceContract create + patch for the `service_contract_request`
intent. Records the inbound Support Agreement Quote or Order request as a
real SF ServiceContract row under the matched Account so the CSR can pick
it up in Lightning. Falls back to a clear `feature_not_enabled_in_org`
when the object isn't provisioned.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceError

from ..models import SalesforceConnection
from . import salesforce as sf_svc

log = logging.getLogger("salesforce_service_contracts")


_NOT_ENABLED_HINTS = (
    "INVALID_TYPE",
    "sObject type 'ServiceContract' is not supported",
    "Entity 'ServiceContract' is not supported",
)


def _looks_not_enabled(err: Exception) -> bool:
    msg = str(err)
    return any(h in msg for h in _NOT_ENABLED_HINTS)


def create_sf_service_contract(
    conn: SalesforceConnection,
    *,
    account_id: str,
    name: str,
    sub_type: str | None = None,
    term_months: int = 12,
    description: str | None = None,
    request_number: str | None = None,
) -> dict[str, Any]:
    """Create a ServiceContract under the matched Account. Reasonable
    defaults: StartDate=today, EndDate=today+term_months, Status='Draft'.
    Returns `applied: True` with the SF deep-link URL on success."""
    if not account_id:
        return {"applied": False, "reason": "missing account_id"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        return {"applied": False, "reason": f"sf_connect_failed: {type(e).__name__}: {e}"[:300]}

    start_dt = date.today()
    end_dt = start_dt + timedelta(days=int(max(1, term_months) * 30))
    payload: dict[str, Any] = {
        "AccountId": account_id,
        "Name": name[:80],
        "StartDate": start_dt.isoformat(),
        "EndDate": end_dt.isoformat(),
        "Status": "Draft",
        "Term": int(max(1, term_months)),
        "Description": (description or f"Created by ZBrain agent fabric · {sub_type or 'Service Contract'}")[:32000],
    }
    try:
        res = sf.ServiceContract.create({k: v for k, v in payload.items() if v is not None})
    except SalesforceError as e:
        if _looks_not_enabled(e):
            return {"applied": False, "reason": "feature_not_enabled_in_org", "feature": "ServiceContract"}
        log.warning("create_sf_service_contract failed: %s", e)
        # Some orgs require specific picklist values for Status; retry without it.
        if "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST" in str(e) or "INVALID_FIELD" in str(e):
            try:
                payload.pop("Status", None)
                res = sf.ServiceContract.create({k: v for k, v in payload.items() if v is not None})
            except Exception as e2:
                return {"applied": False, "reason": f"service_contract_create_failed: {e2}"[:300]}
        else:
            return {"applied": False, "reason": f"service_contract_create_failed: {e}"[:300]}
    except Exception as e:
        if _looks_not_enabled(e):
            return {"applied": False, "reason": "feature_not_enabled_in_org", "feature": "ServiceContract"}
        return {"applied": False, "reason": f"service_contract_create_failed: {type(e).__name__}: {e}"[:300]}

    if not res.get("success"):
        return {"applied": False, "reason": "ServiceContract.create returned non-success", "raw": res}

    instance_url = (conn.instance_url or "").rstrip("/")
    if instance_url and not instance_url.startswith(("http://", "https://")):
        instance_url = "https://" + instance_url
    sc_id = res["id"]
    return {
        "applied": True,
        "salesforce_service_contract_id": sc_id,
        "name": payload["Name"],
        "start_date": payload["StartDate"],
        "end_date": payload["EndDate"],
        "term_months": payload["Term"],
        "salesforce_url": f"{instance_url}/lightning/r/ServiceContract/{sc_id}/view" if instance_url else None,
    }
