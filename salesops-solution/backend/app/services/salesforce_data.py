"""Adapters that turn Salesforce records into the shapes the existing
/api/data/* endpoints already produce, so the frontend doesn't need to
distinguish between SQLite-sourced and SF-sourced records (other than the
`_source` flag we tag per record).
"""
from __future__ import annotations

import logging
from typing import Any

from simple_salesforce import Salesforce
from sqlalchemy.orm import Session

from ..models import CommunicationLog, SalesforceConnection
from . import salesforce as sf_svc

log = logging.getLogger("salesforce_data")


CUSTOMER_FIELDS = [
    "Id",
    "Name",
    "Customer_Code__c",
    "Region__c",
    "Vertical__c",
    "SLA_Tier__c",
    "DUNS__c",
    "Compliance_Flags__c",
    "Payment_Terms__c",
    "Credit_Limit__c",
    "Annual_Revenue_USD__c",
    "Default_Currency__c",
    "Default_Incoterms__c",
    "Industry",
    "Language__c",
    "BillingStreet",
    "BillingCity",
    "BillingPostalCode",
    "BillingCountryCode",
    "NumberOfEmployees",
    "Description",
]


def _strip_attrs(rec: dict) -> dict:
    return {k: v for k, v in (rec or {}).items() if k != "attributes"}


def _split_compliance(s: str | None) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _customer_summary(account: dict) -> dict[str, Any]:
    """Map a Salesforce Account record to the existing CustomerRecord shape."""
    return {
        "id": account.get("Id"),
        "code": account.get("Customer_Code__c"),
        "name": account.get("Name"),
        "email": None,  # Account doesn't carry email; primary contact would
        "region": account.get("Region__c"),
        "language": account.get("Language__c") or "en",
        "vertical": account.get("Vertical__c"),
        "compliance": _split_compliance(account.get("Compliance_Flags__c")),
        "history": {"quotes": 0, "orders": 0, "work_orders": 0},
        "_source": "salesforce",
        "_sf_account_id": account.get("Id"),
    }


def list_customers(conn: SalesforceConnection) -> list[dict[str, Any]]:
    sf = sf_svc.client_for(conn)
    soql = (
        f"SELECT {', '.join(CUSTOMER_FIELDS)} "
        f"FROM Account "
        f"WHERE Customer_Code__c != null "
        f"ORDER BY Customer_Code__c"
    )
    res = sf.query_all(soql)
    rows = [_strip_attrs(r) for r in res.get("records", [])]

    # Aggregate counts per account in two SOQL roundtrips total
    account_ids = [r["Id"] for r in rows if r.get("Id")]
    if not account_ids:
        return [_customer_summary(r) for r in rows]
    contact_counts = _count_by_account(sf, "Contact", account_ids)
    order_counts = _count_by_account(sf, "Order", account_ids)
    out = []
    for r in rows:
        summary = _customer_summary(r)
        summary["history"] = {
            "quotes": 0,
            "orders": order_counts.get(r["Id"], 0),
            "work_orders": 0,
            "contacts": contact_counts.get(r["Id"], 0),
        }
        out.append(summary)
    return out


def _count_by_account(sf: Salesforce, sobject: str, account_ids: list[str]) -> dict[str, int]:
    """One COUNT/groupBy aggregate query — cheap."""
    if not account_ids:
        return {}
    ids_clause = ",".join(f"'{aid}'" for aid in account_ids)
    try:
        soql = (
            f"SELECT AccountId, COUNT(Id) recCount "
            f"FROM {sobject} "
            f"WHERE AccountId IN ({ids_clause}) "
            f"GROUP BY AccountId"
        )
        res = sf.query(soql)
        return {r["AccountId"]: int(r.get("recCount") or 0) for r in (res.get("records") or [])}
    except Exception as e:
        log.debug("count_by_account(%s) failed: %s", sobject, e)
        return {}


def customer_detail(conn: SalesforceConnection, db: Session, account_id: str) -> dict[str, Any] | None:
    """Build the Customer 360 detail payload from Salesforce + local communication-log
    (the agent's own outbound history isn't stored in Salesforce yet)."""
    sf = sf_svc.client_for(conn)
    safe_id = (account_id or "").replace("'", "")
    res = sf.query(
        f"SELECT {', '.join(CUSTOMER_FIELDS)} FROM Account WHERE Id = '{safe_id}' LIMIT 1"
    )
    recs = res.get("records") or []
    if not recs:
        return None
    account = _strip_attrs(recs[0])

    contacts = _list_contacts(sf, account_id)
    orders = _list_orders(sf, account_id)
    products_from_pricebook = _list_products_via_pricebook(sf, account_id)

    # Communication log is our agent's output — pull from SQLite by customer_code
    code = account.get("Customer_Code__c")
    comm_log: list[dict] = []
    if code:
        rows = (
            db.query(CommunicationLog)
            .order_by(CommunicationLog.id.desc())
            .limit(50)
            .all()
        )
        for r in rows:
            try:
                ext = r.extra or {}
                if ext.get("customer_code") == code:
                    comm_log.append({
                        "id": r.id,
                        "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                        "direction": r.direction,
                        "channel": r.channel,
                        "subject": r.subject,
                        "language": r.language,
                        "intent": r.intent,
                        "autonomy_tier": r.autonomy_tier,
                        "sent_by": r.sent_by,
                        "csr_action": r.csr_action,
                        "pipeline_id": r.pipeline_id,
                        "order_id": r.order_id,
                        "work_order_id": r.work_order_id,
                        "body_preview": (r.body or "")[:200],
                    })
            except Exception:
                continue

    addresses = []
    if account.get("BillingStreet") or account.get("BillingCity"):
        addresses.append(
            {
                "type": "headquarters",
                "line1": account.get("BillingStreet"),
                "city": account.get("BillingCity"),
                "country": account.get("BillingCountryCode"),
                "postal": account.get("BillingPostalCode"),
            }
        )

    return {
        "id": account.get("Id"),
        "code": account.get("Customer_Code__c"),
        "name": account.get("Name"),
        "legal_entity": account.get("Description"),
        "email": None,
        "region": account.get("Region__c"),
        "language": account.get("Language__c") or "en",
        "vertical": account.get("Vertical__c"),
        "compliance": _split_compliance(account.get("Compliance_Flags__c")),
        "industry": account.get("Industry"),
        "naics": None,
        "annual_revenue_usd": account.get("Annual_Revenue_USD__c"),
        "employees": account.get("NumberOfEmployees"),
        "account_manager": None,
        "sales_engineer": None,
        "customer_since": None,
        "status": "active",
        "sla_tier": account.get("SLA_Tier__c"),
        "duns": account.get("DUNS__c"),
        "tax_id": None,
        "payment_terms": account.get("Payment_Terms__c") or "Net 30",
        "credit_limit": account.get("Credit_Limit__c") or 0,
        "default_currency": account.get("Default_Currency__c") or "USD",
        "default_incoterms": account.get("Default_Incoterms__c") or "FOB Origin",
        "addresses": addresses,
        "contacts": contacts,
        "quotes": [],
        "orders": orders,
        "work_orders": [],
        "assets": [],
        "contracts": [],
        "invoices": [],
        "cal_certs": [],
        "communication_log": comm_log,
        "history": {
            "quotes": 0,
            "orders": len(orders),
            "work_orders": 0,
            "contacts": len(contacts),
        },
        "_source": "salesforce",
        "_sf_account_id": account.get("Id"),
        "_sf_instance_url": conn.instance_url,
    }


def _list_contacts(sf: Salesforce, account_id: str) -> list[dict]:
    safe = (account_id or "").replace("'", "")
    soql = (
        "SELECT Id, FirstName, LastName, Title, Email, Phone, Role__c, Language__c, Is_Primary__c "
        f"FROM Contact WHERE AccountId = '{safe}' ORDER BY Is_Primary__c DESC, LastName"
    )
    try:
        res = sf.query_all(soql)
        out: list[dict] = []
        for r in res.get("records", []):
            r = _strip_attrs(r)
            full_name = " ".join([p for p in [r.get("FirstName"), r.get("LastName")] if p])
            out.append({
                "id": r.get("Id"),
                "name": full_name.strip(),
                "title": r.get("Title"),
                "role": r.get("Role__c"),
                "email": r.get("Email"),
                "phone": r.get("Phone"),
                "language": r.get("Language__c") or "en",
                "is_primary": bool(r.get("Is_Primary__c")),
            })
        return out
    except Exception as e:
        log.debug("contacts query failed: %s", e)
        return []


def _list_orders(sf: Salesforce, account_id: str) -> list[dict]:
    safe = (account_id or "").replace("'", "")
    try:
        res = sf.query_all(
            "SELECT Id, OrderNumber, Status, EffectiveDate, TotalAmount, PoNumber "
            f"FROM Order WHERE AccountId = '{safe}' ORDER BY CreatedDate DESC LIMIT 50"
        )
        out: list[dict] = []
        for r in res.get("records", []):
            r = _strip_attrs(r)
            out.append({
                "id": r.get("Id"),
                "order_number": r.get("OrderNumber"),
                "status": r.get("Status"),
                "hold_reason": None,
                "requested_ship_date": r.get("EffectiveDate"),
                "total": r.get("TotalAmount") or 0,
                "tracking_number": None,
                "csr_owner": None,
            })
        return out
    except Exception as e:
        log.debug("orders query failed: %s", e)
        return []


def _list_products_via_pricebook(sf: Salesforce, account_id: str) -> list[dict]:
    """Reserved for later — products bought aren't on Account directly; left as no-op for now."""
    return []
