"""Live Salesforce lookups used by Stage 2c (Cross-system Enrichment).

Queries Salesforce REST in real time — never caches. Read-only.
Returns None silently if no active connection is configured, so the agent
falls back gracefully to the local seed data on disconnected runs.
"""
from __future__ import annotations

import logging
from typing import Any

from simple_salesforce.exceptions import SalesforceError

from ..db import SessionLocal
from ..services import salesforce as sf_svc

log = logging.getLogger("salesforce_lookup")


def _escape(s: str) -> str:
    return (s or "").replace("'", "\\'")


def has_active_connection() -> bool:
    """Quick read-only probe: does the running backend have an active SF connection?"""
    db = SessionLocal()
    try:
        return sf_svc.get_active_connection(db) is not None
    except Exception:
        return False
    finally:
        db.close()


def _get_sf_client():
    """Return a simple_salesforce client if a connection is active, else None."""
    db = SessionLocal()
    try:
        conn = sf_svc.get_active_connection(db)
        if not conn:
            return None
        try:
            return sf_svc.client_for(conn)
        except Exception:
            return None
    finally:
        db.close()


ACCOUNT_FIELDS = [
    "Id",
    "Name",
    "Customer_Code__c",
    "Region__c",
    "Vertical__c",
    "SLA_Tier__c",
    "Compliance_Flags__c",
    "Payment_Terms__c",
    "Credit_Limit__c",
    "Annual_Revenue_USD__c",
    "Default_Currency__c",
    "Default_Incoterms__c",
    "Industry",
    "BillingCity",
    "BillingCountryCode",
    "Language__c",
]


def fetch_account_by_code(customer_code: str) -> dict[str, Any] | None:
    """Look up Salesforce Account by our Customer_Code__c. Returns None on any failure."""
    if not customer_code:
        return None
    db = SessionLocal()
    try:
        conn = sf_svc.get_active_connection(db)
        if not conn:
            return None
        try:
            sf = sf_svc.client_for(conn)
            soql = (
                f"SELECT {', '.join(ACCOUNT_FIELDS)} "
                f"FROM Account "
                f"WHERE Customer_Code__c = '{_escape(customer_code)}' "
                f"LIMIT 1"
            )
            res = sf.query(soql)
            recs = res.get("records") or []
            if not recs:
                return None
            return _strip_attrs(recs[0])
        except (SalesforceError, RuntimeError, Exception) as e:
            log.warning("Salesforce lookup failed for %s: %s", customer_code, e)
            return None
    finally:
        db.close()


def fetch_account_by_email(email: str) -> dict[str, Any] | None:
    """Look up Salesforce Account by traversing Contact.Email -> Account. None on any failure."""
    if not email:
        return None
    db = SessionLocal()
    try:
        conn = sf_svc.get_active_connection(db)
        if not conn:
            return None
        try:
            sf = sf_svc.client_for(conn)
            soql = (
                "SELECT Id, AccountId, Email, Name, "
                "Account.Id, Account.Name, Account.Customer_Code__c, "
                "Account.Region__c, Account.Vertical__c, Account.SLA_Tier__c, "
                "Account.Compliance_Flags__c, Account.Payment_Terms__c, "
                "Account.Credit_Limit__c, Account.Industry, Account.BillingCity, "
                "Account.BillingCountryCode "
                "FROM Contact "
                f"WHERE Email = '{_escape(email)}' "
                "LIMIT 1"
            )
            res = sf.query(soql)
            recs = res.get("records") or []
            if not recs:
                return None
            row = recs[0]
            account = _strip_attrs(row.get("Account") or {})
            account["_matched_via_contact"] = {
                "id": row.get("Id"),
                "email": row.get("Email"),
                "name": row.get("Name"),
            }
            return account
        except (SalesforceError, RuntimeError, Exception) as e:
            log.warning("Salesforce contact lookup failed for %s: %s", email, e)
            return None
    finally:
        db.close()


def fetch_account_history(account_id: str) -> dict[str, int]:
    """Pull aggregate counts. Empty dict on any failure."""
    if not account_id:
        return {}
    db = SessionLocal()
    try:
        conn = sf_svc.get_active_connection(db)
        if not conn:
            return {}
        try:
            sf = sf_svc.client_for(conn)
            out: dict[str, int] = {}
            for label, soql in [
                ("contacts", f"SELECT COUNT() FROM Contact WHERE AccountId = '{_escape(account_id)}'"),
                ("orders", f"SELECT COUNT() FROM Order WHERE AccountId = '{_escape(account_id)}'"),
                ("opportunities", f"SELECT COUNT() FROM Opportunity WHERE AccountId = '{_escape(account_id)}'"),
            ]:
                try:
                    res = sf.query(soql)
                    out[label] = int(res.get("totalSize") or 0)
                except (SalesforceError, Exception):
                    out[label] = 0
            return out
        except (RuntimeError, Exception) as e:
            log.warning("Salesforce history fetch failed: %s", e)
            return {}
    finally:
        db.close()


def _strip_attrs(rec: dict) -> dict:
    """Salesforce REST adds an `attributes` key to every record. Drop it for clean trace output."""
    return {k: v for k, v in rec.items() if k != "attributes"}
