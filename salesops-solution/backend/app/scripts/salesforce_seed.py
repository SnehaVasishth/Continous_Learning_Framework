"""Salesforce wipe-and-seed.

One-shot script to populate the connected Salesforce org with the same
customer/product master data the synthetic demo uses, so the rest of the app
can later switch from SQLite reads to live Salesforce reads.

Phases:
    --create-fields    Add custom fields to Account + Product2 via Tooling API
    --wipe             Delete demo-relevant records (Account, Contact, Product2,
                       PricebookEntry, plus dependents Asset/Order*/Quote*/Case)
    --seed-master      Insert Accounts, Contacts, Products, PricebookEntries
    --all              Run all three phases in order

Usage:
    python -m app.scripts.salesforce_seed --all
    python -m app.scripts.salesforce_seed --wipe --seed-master
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any, Iterable

import requests
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceMalformedRequest, SalesforceResourceNotFound
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import (
    Asset,
    Contact,
    Customer,
    Order,
    Product,
    Quote,
    ServiceContract,
    WorkOrder,
)
from ..services import salesforce as sf_svc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("salesforce_seed")


# ---------------------------------------------------------------------------
# Custom field definitions — Tooling API
# ---------------------------------------------------------------------------

# Each entry becomes a CustomField metadata record. Tooling API takes JSON.
ACCOUNT_FIELDS: list[dict[str, Any]] = [
    {
        "FullName": "Account.Customer_Code__c",
        "Metadata": {
            "label": "Customer Code",
            "type": "Text",
            "length": 30,
            "externalId": True,
            "unique": True,
            "required": False,
            "description": "Internal customer code from the SalesOps platform.",
        },
    },
    {
        "FullName": "Account.Region__c",
        "Metadata": {"label": "Region", "type": "Text", "length": 10},
    },
    {
        "FullName": "Account.Vertical__c",
        "Metadata": {"label": "Vertical", "type": "Text", "length": 50},
    },
    {
        "FullName": "Account.SLA_Tier__c",
        "Metadata": {"label": "SLA Tier", "type": "Text", "length": 30},
    },
    {
        "FullName": "Account.DUNS__c",
        "Metadata": {"label": "DUNS", "type": "Text", "length": 20},
    },
    {
        "FullName": "Account.Compliance_Flags__c",
        "Metadata": {"label": "Compliance Flags", "type": "LongTextArea", "length": 5000, "visibleLines": 3},
    },
    {
        "FullName": "Account.Payment_Terms__c",
        "Metadata": {"label": "Payment Terms", "type": "Text", "length": 30},
    },
    {
        "FullName": "Account.Credit_Limit__c",
        "Metadata": {"label": "Credit Limit", "type": "Currency", "precision": 18, "scale": 2},
    },
    {
        "FullName": "Account.Annual_Revenue_USD__c",
        "Metadata": {"label": "Annual Revenue (USD)", "type": "Currency", "precision": 18, "scale": 2},
    },
    {
        "FullName": "Account.Default_Currency__c",
        "Metadata": {"label": "Default Currency", "type": "Text", "length": 5},
    },
    {
        "FullName": "Account.Default_Incoterms__c",
        "Metadata": {"label": "Default Incoterms", "type": "Text", "length": 30},
    },
    {
        "FullName": "Account.Language__c",
        "Metadata": {"label": "Preferred Language", "type": "Text", "length": 5},
    },
]


PRODUCT_FIELDS: list[dict[str, Any]] = [
    {
        "FullName": "Product2.Lifecycle_Status__c",
        "Metadata": {
            "label": "Lifecycle Status",
            "type": "Picklist",
            "valueSet": {
                "valueSetDefinition": {
                    "sorted": False,
                    "value": [
                        {"fullName": "active", "default": True, "label": "Active"},
                        {"fullName": "mature", "default": False, "label": "Mature"},
                        {"fullName": "eol", "default": False, "label": "End of Life"},
                        {"fullName": "npi", "default": False, "label": "New Product Introduction"},
                    ],
                }
            },
        },
    },
    {"FullName": "Product2.EOL_Date__c", "Metadata": {"label": "EOL Date", "type": "Date"}},
    {"FullName": "Product2.Successor_SKU__c", "Metadata": {"label": "Successor SKU", "type": "Text", "length": 40}},
    {"FullName": "Product2.ECCN__c", "Metadata": {"label": "ECCN", "type": "Text", "length": 20}},
    {"FullName": "Product2.HS_Code__c", "Metadata": {"label": "HS Code", "type": "Text", "length": 20}},
    {
        "FullName": "Product2.Lead_Time_Weeks__c",
        "Metadata": {"label": "Lead Time (weeks)", "type": "Number", "precision": 4, "scale": 0},
    },
    {
        "FullName": "Product2.Calibration_Interval_Months__c",
        "Metadata": {"label": "Calibration Interval (months)", "type": "Number", "precision": 4, "scale": 0},
    },
    {
        "FullName": "Product2.Country_Of_Origin__c",
        "Metadata": {"label": "Country of Origin", "type": "Text", "length": 10},
    },
    {"FullName": "Product2.MPN__c", "Metadata": {"label": "Manufacturer Part Number", "type": "Text", "length": 60}},
    {"FullName": "Product2.List_Price_USD__c", "Metadata": {"label": "List Price (USD)", "type": "Currency", "precision": 18, "scale": 2}},
]


CONTACT_FIELDS: list[dict[str, Any]] = [
    {
        "FullName": "Contact.Role__c",
        "Metadata": {"label": "Buyer Role", "type": "Text", "length": 50},
    },
    {
        "FullName": "Contact.Language__c",
        "Metadata": {"label": "Preferred Language", "type": "Text", "length": 5},
    },
    {
        "FullName": "Contact.Is_Primary__c",
        "Metadata": {"label": "Primary Buyer", "type": "Checkbox", "defaultValue": "false"},
    },
]


# Each `*_Url__c` field stores the SharePoint webUrl for the associated PDF
# (Quote PDF, Work-Order PDF, Service-Contract PDF, Calibration certificate, etc.).
# The Phase-3 SharePoint stamping script walks `outputs/`, uploads each PDF,
# and writes the resulting webUrl back into these fields.

ASSET_FIELDS: list[dict[str, Any]] = [
    {"FullName": "Asset.Last_Cal_Date__c", "Metadata": {"label": "Last Calibration Date", "type": "Date"}},
    {"FullName": "Asset.Calibration_Due_Date__c", "Metadata": {"label": "Calibration Due Date", "type": "Date"}},
    {"FullName": "Asset.Cal_Interval_Months__c", "Metadata": {"label": "Calibration Interval (months)", "type": "Number", "precision": 4, "scale": 0}},
    {"FullName": "Asset.Asset_Location__c", "Metadata": {"label": "Asset Location", "type": "Text", "length": 100}},
    {"FullName": "Asset.Cal_Cert_Url__c", "Metadata": {"label": "Latest Cal Cert (SharePoint URL)", "type": "Url"}},
    {"FullName": "Asset.Document_Url__c", "Metadata": {"label": "Asset Doc (SharePoint URL)", "type": "Url"}},
]

QUOTE_FIELDS: list[dict[str, Any]] = [
    {"FullName": "Quote.Customer_Code__c", "Metadata": {"label": "Customer Code", "type": "Text", "length": 30}},
    {"FullName": "Quote.Sales_Rep__c", "Metadata": {"label": "Sales Rep", "type": "Text", "length": 80}},
    {"FullName": "Quote.Sales_Engineer__c", "Metadata": {"label": "Sales Engineer", "type": "Text", "length": 80}},
    {"FullName": "Quote.Pricing_Terms__c", "Metadata": {"label": "Pricing Terms", "type": "Text", "length": 30}},
    {"FullName": "Quote.Document_Url__c", "Metadata": {"label": "Quote PDF (SharePoint URL)", "type": "Url"}},
]

WORKORDER_FIELDS: list[dict[str, Any]] = [
    {"FullName": "WorkOrder.WO_Number__c", "Metadata": {"label": "WO Number", "type": "Text", "length": 30, "externalId": True}},
    {"FullName": "WorkOrder.Customer_Code__c", "Metadata": {"label": "Customer Code", "type": "Text", "length": 30}},
    {"FullName": "WorkOrder.Asset_Serial__c", "Metadata": {"label": "Asset Serial", "type": "Text", "length": 60}},
    {"FullName": "WorkOrder.Asset_SKU__c", "Metadata": {"label": "Asset SKU", "type": "Text", "length": 60}},
    {"FullName": "WorkOrder.Type__c", "Metadata": {"label": "Service Type", "type": "Text", "length": 40}},
    {"FullName": "WorkOrder.Region__c", "Metadata": {"label": "Region", "type": "Text", "length": 10}},
    {"FullName": "WorkOrder.Technician__c", "Metadata": {"label": "Technician", "type": "Text", "length": 80}},
    {"FullName": "WorkOrder.Cert_Number__c", "Metadata": {"label": "Cert Number", "type": "Text", "length": 60}},
    {"FullName": "WorkOrder.Standards_Referenced__c", "Metadata": {"label": "Standards Referenced", "type": "LongTextArea", "length": 2000, "visibleLines": 3}},
    {"FullName": "WorkOrder.Signoff_Status__c", "Metadata": {"label": "Sign-off Status", "type": "Text", "length": 30}},
    {"FullName": "WorkOrder.Cost_USD__c", "Metadata": {"label": "Cost (USD)", "type": "Currency", "precision": 18, "scale": 2}},
    {"FullName": "WorkOrder.Document_Url__c", "Metadata": {"label": "WO PDF (SharePoint URL)", "type": "Url"}},
]

ORDER_FIELDS: list[dict[str, Any]] = [
    {"FullName": "Order.Requested_Ship_Date__c", "Metadata": {"label": "Requested Ship Date", "type": "Date"}},
]

SERVICE_CONTRACT_FIELDS: list[dict[str, Any]] = [
    {"FullName": "ServiceContract.Contract_Number__c", "Metadata": {"label": "Contract Number", "type": "Text", "length": 30, "externalId": True, "unique": True}},
    {"FullName": "ServiceContract.Customer_Code__c", "Metadata": {"label": "Customer Code", "type": "Text", "length": 30}},
    {"FullName": "ServiceContract.Coverage_Type__c", "Metadata": {"label": "Coverage Type", "type": "Text", "length": 40}},
    {"FullName": "ServiceContract.SLA_Response_Hours__c", "Metadata": {"label": "SLA Response (hrs)", "type": "Number", "precision": 4, "scale": 0}},
    {"FullName": "ServiceContract.SLA_Resolution_Hours__c", "Metadata": {"label": "SLA Resolution (hrs)", "type": "Number", "precision": 4, "scale": 0}},
    {"FullName": "ServiceContract.Annual_Value_USD__c", "Metadata": {"label": "Annual Value (USD)", "type": "Currency", "precision": 18, "scale": 2}},
    {"FullName": "ServiceContract.Included_Assets__c", "Metadata": {"label": "Included Assets", "type": "LongTextArea", "length": 5000, "visibleLines": 4}},
    {"FullName": "ServiceContract.Document_Url__c", "Metadata": {"label": "Contract PDF (SharePoint URL)", "type": "Url"}},
]

# Case fields — Cases are now driven by inbound emails (the RFP CCCRequest concept).
# Request_Number__c is our local request_number used as external id for idempotent upsert.
CASE_FIELDS: list[dict[str, Any]] = [
    {"FullName": "Case.Request_Number__c", "Metadata": {"label": "Request Number", "type": "Text", "length": 30, "externalId": True, "unique": True}},
    {"FullName": "Case.Customer_Code__c", "Metadata": {"label": "Customer Code", "type": "Text", "length": 30}},
    {"FullName": "Case.Category__c", "Metadata": {"label": "Category", "type": "Text", "length": 50}},
    {"FullName": "Case.Request_Type__c", "Metadata": {"label": "Request Type", "type": "Text", "length": 50}},
    {"FullName": "Case.Sub_Type__c", "Metadata": {"label": "Sub Type", "type": "Text", "length": 50}},
    {"FullName": "Case.Track__c", "Metadata": {"label": "Track", "type": "Text", "length": 30}},
    {"FullName": "Case.Stage__c", "Metadata": {"label": "Stage", "type": "Text", "length": 50}},
    {"FullName": "Case.Owner_Label__c", "Metadata": {"label": "Owner Label", "type": "Text", "length": 80}},
    {"FullName": "Case.Fallout_Reason__c", "Metadata": {"label": "Fallout Reason", "type": "Text", "length": 80}},
    {"FullName": "Case.Pipeline_Id__c", "Metadata": {"label": "Pipeline Id", "type": "Text", "length": 30}},
    {"FullName": "Case.Email_Id__c", "Metadata": {"label": "Email Id", "type": "Text", "length": 30}},
]


# ---------------------------------------------------------------------------
# Tooling API helpers
# ---------------------------------------------------------------------------


def tooling_post(sf: Salesforce, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST to the Tooling API. simple-salesforce's `restful` doesn't expose tooling cleanly."""
    url = f"https://{sf.sf_instance}/services/data/v{sf.sf_version}/tooling/{path}"
    headers = {
        "Authorization": f"Bearer {sf.session_id}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"tooling POST {path} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.text else {}


def tooling_query(sf: Salesforce, soql: str) -> dict[str, Any]:
    url = f"https://{sf.sf_instance}/services/data/v{sf.sf_version}/tooling/query/?q={requests.utils.quote(soql)}"
    headers = {"Authorization": f"Bearer {sf.session_id}"}
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"tooling query -> {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def existing_custom_fields(sf: Salesforce, sobject: str) -> set[str]:
    res = tooling_query(
        sf,
        f"SELECT DeveloperName FROM CustomField WHERE TableEnumOrId = '{sobject}' OR EntityDefinition.QualifiedApiName = '{sobject}'",
    )
    return {f"{r['DeveloperName']}__c" for r in (res.get("records") or [])}


def create_field(sf: Salesforce, field: dict[str, Any]) -> tuple[bool, str]:
    """Create a single CustomField via Tooling API. Returns (created, message)."""
    full_name = field["FullName"]
    sobject, api_name = full_name.split(".", 1)
    existing = existing_custom_fields(sf, sobject)
    if api_name in existing:
        return False, f"already exists: {full_name}"
    try:
        tooling_post(sf, "sobjects/CustomField", field)
        return True, f"created {full_name}"
    except RuntimeError as e:
        return False, f"failed {full_name}: {e}"


ALL_CUSTOM_FIELDS: list[dict[str, Any]] = (
    ACCOUNT_FIELDS
    + PRODUCT_FIELDS
    + CONTACT_FIELDS
    + ASSET_FIELDS
    + QUOTE_FIELDS
    + WORKORDER_FIELDS
    + SERVICE_CONTRACT_FIELDS
    + ORDER_FIELDS
    + CASE_FIELDS
)


def _quote_enabled(sf: Salesforce) -> bool:
    """Quotes is gated by the Quote Settings feature. Probe by issuing a SOQL."""
    try:
        sf.query("SELECT Id FROM Quote LIMIT 1")
        return True
    except Exception:
        return False


def create_all_fields(sf: Salesforce) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"created": [], "skipped": [], "failed": []}
    quote_on = _quote_enabled(sf)
    if not quote_on:
        log.info("Quotes feature is OFF in this org — skipping Quote.* custom fields")
    all_fields = [f for f in ALL_CUSTOM_FIELDS if quote_on or not f["FullName"].startswith("Quote.")]
    for f in all_fields:
        created, msg = create_field(sf, f)
        if created:
            out["created"].append(msg)
            log.info(msg)
        elif "already exists" in msg:
            out["skipped"].append(msg)
        else:
            out["failed"].append(msg)
            log.warning(msg)
    return out


# ---------------------------------------------------------------------------
# Field-Level Security — grant the running user access to fields we just created
# ---------------------------------------------------------------------------

PERMISSION_SET_NAME = "ZBrain_Seeder_Access"


def _current_user_id(sf: Salesforce) -> str:
    """Get the User Id of the running-as user (via UserInfo)."""
    info = sf.restful("chatter/users/me", method="GET") or {}
    user_id = info.get("id", "")
    if isinstance(user_id, str) and user_id.startswith("https"):
        return user_id.rstrip("/").split("/")[-1]
    return str(user_id)


def _ensure_permission_set(sf: Salesforce) -> str:
    """Find or create the ZBrain seeder PermissionSet. Returns its Id."""
    res = sf.query(f"SELECT Id FROM PermissionSet WHERE Name = '{PERMISSION_SET_NAME}' LIMIT 1")
    if res.get("records"):
        return res["records"][0]["Id"]
    res = sf.PermissionSet.create({
        "Name": PERMISSION_SET_NAME,
        "Label": "ZBrain Seeder Access",
        "Description": "Grants the running user FLS on custom fields seeded by ZBrain.",
    })
    return res["id"]


def _assign_permission_set(sf: Salesforce, perm_set_id: str, user_id: str) -> None:
    res = sf.query(
        f"SELECT Id FROM PermissionSetAssignment WHERE PermissionSetId = '{perm_set_id}' AND AssigneeId = '{user_id}' LIMIT 1"
    )
    if res.get("records"):
        return
    sf.PermissionSetAssignment.create({"PermissionSetId": perm_set_id, "AssigneeId": user_id})


def grant_field_access(sf: Salesforce, field_full_names: list[str]) -> int:
    """Ensure the running-as user can read+edit each given field.
    Idempotent — skips fields already granted."""
    user_id = _current_user_id(sf)
    perm_set_id = _ensure_permission_set(sf)
    _assign_permission_set(sf, perm_set_id, user_id)

    granted = 0
    for full_name in field_full_names:
        sobject, _ = full_name.split(".", 1)
        existing = sf.query(
            f"SELECT Id FROM FieldPermissions WHERE ParentId = '{perm_set_id}' AND Field = '{full_name}' LIMIT 1"
        )
        if existing.get("records"):
            continue
        try:
            sf.FieldPermissions.create({
                "ParentId": perm_set_id,
                "SobjectType": sobject,
                "Field": full_name,
                "PermissionsRead": True,
                "PermissionsEdit": True,
            })
            granted += 1
        except Exception as e:
            log.warning("FLS grant failed for %s: %s", full_name, e)
    return granted


# ---------------------------------------------------------------------------
# Wipe
# ---------------------------------------------------------------------------


WIPE_OBJECTS = [
    "Case",
    "WorkOrder",
    "ServiceContract",
    "Asset",
    "OrderItem",
    "Order",
    "QuoteLineItem",
    "Quote",
    "Contact",
    "PricebookEntry",
    "Account",
    "Product2",
]


def _delete_all(sf: Salesforce, sobject: str) -> int:
    """Bulk delete every record of an sobject. PricebookEntries on the Standard pricebook
    require deletion of products first, hence wipe order matters."""
    total = 0
    while True:
        try:
            res = sf.query_all(f"SELECT Id FROM {sobject}")
        except Exception as e:
            log.warning("query failed on %s: %s — skipping", sobject, e)
            return total
        ids = [r["Id"] for r in (res.get("records") or [])]
        if not ids:
            break
        # Salesforce bulk delete max is 200 per call
        for chunk in _chunks(ids, 200):
            payload = [{"id": rid} for rid in chunk]
            try:
                getattr(sf.bulk, sobject).delete(payload, batch_size=200)
            except Exception as e:
                log.warning("bulk delete %s chunk failed: %s — falling back to per-record", sobject, e)
                for rid in chunk:
                    try:
                        getattr(sf, sobject).delete(rid)
                    except Exception as e2:
                        log.debug("could not delete %s/%s: %s", sobject, rid, e2)
        total += len(ids)
        if len(ids) < 200:
            break
    return total


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def wipe_org(sf: Salesforce) -> dict[str, int]:
    counts = {}
    for sobject in WIPE_OBJECTS:
        n = _delete_all(sf, sobject)
        counts[sobject] = n
        log.info("wiped %d %s", n, sobject)
    return counts


# ---------------------------------------------------------------------------
# Seed master data from local SQLite
# ---------------------------------------------------------------------------


_COUNTRY_CODES = {
    "US": "US", "USA": "US", "United States": "US",
    "DE": "DE", "Germany": "DE",
    "JP": "JP", "Japan": "JP",
    "ES": "ES", "Spain": "ES",
    "GB": "GB", "UK": "GB", "United Kingdom": "GB",
    "FR": "FR", "France": "FR",
    "IT": "IT", "Italy": "IT",
    "CN": "CN", "China": "CN",
    "KR": "KR", "South Korea": "KR",
    "IN": "IN", "India": "IN",
    "CA": "CA", "Canada": "CA",
    "MX": "MX", "Mexico": "MX",
    "BR": "BR", "Brazil": "BR",
    "TW": "TW", "Taiwan": "TW",
}


def _account_payload(c: Customer) -> dict[str, Any]:
    addr_hq = next((a for a in (c.addresses or []) if a.get("type") == "headquarters"), None) or (c.addresses or [{}])[0]
    if not isinstance(addr_hq, dict):
        addr_hq = {}
    country_code = _COUNTRY_CODES.get((addr_hq.get("country") or "").strip())
    payload = {
        "Name": c.name,
        "Customer_Code__c": c.code,
        "Region__c": c.region,
        "Vertical__c": c.vertical,
        "SLA_Tier__c": c.sla_tier,
        "DUNS__c": c.duns,
        "Language__c": c.language,
        "Compliance_Flags__c": ", ".join(c.compliance or []) if c.compliance else None,
        "Payment_Terms__c": c.payment_terms,
        "Credit_Limit__c": c.credit_limit,
        "Annual_Revenue_USD__c": c.annual_revenue_usd,
        "Default_Currency__c": c.default_currency,
        "Default_Incoterms__c": c.default_incoterms,
        "Industry": c.industry,
        "NumberOfEmployees": c.employees,
        "BillingStreet": addr_hq.get("line1"),
        "BillingCity": addr_hq.get("city"),
        "BillingPostalCode": addr_hq.get("postal"),
        "Description": f"{c.legal_entity or c.name} — vertical: {c.vertical or 'n/a'}",
    }
    if country_code:
        payload["BillingCountryCode"] = country_code
        # State picklists need codes too if enabled. Pass as-is and Salesforce will validate.
        if addr_hq.get("region") and country_code == "US":
            payload["BillingStateCode"] = addr_hq.get("region")
    return payload


def _contact_payload(ct: Contact, account_id: str) -> dict[str, Any]:
    parts = (ct.name or "").split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else "."
    return {
        "AccountId": account_id,
        "FirstName": first,
        "LastName": last,
        "Title": ct.title,
        "Email": ct.email,
        "Phone": ct.phone,
        "Role__c": ct.role,
        "Language__c": ct.language,
        "Is_Primary__c": bool(ct.is_primary),
    }


def _product_payload(p: Product) -> dict[str, Any]:
    eol = p.lifecycle_eol_date.date().isoformat() if p.lifecycle_eol_date else None
    return {
        "Name": p.description[:80],
        "ProductCode": p.sku,
        "Description": p.description,
        "Family": p.family,
        "IsActive": True,
        "Lifecycle_Status__c": p.lifecycle_status,
        "EOL_Date__c": eol,
        "Successor_SKU__c": p.successor_sku,
        "ECCN__c": p.eccn,
        "HS_Code__c": p.hs_code,
        "Lead_Time_Weeks__c": p.lead_time_weeks,
        "Calibration_Interval_Months__c": p.calibration_interval_months,
        "Country_Of_Origin__c": p.country_of_origin,
        "MPN__c": p.mpn,
        "List_Price_USD__c": p.list_price,
    }


def _iso_date(d) -> str | None:
    if not d:
        return None
    try:
        return d.date().isoformat()
    except AttributeError:
        return d.isoformat()


def _iso_dt(d) -> str | None:
    if not d:
        return None
    try:
        return d.isoformat() if d.tzinfo else d.replace(tzinfo=None).isoformat()
    except Exception:
        return None


def _placeholder_url(kind: str, key: str) -> str:
    """Phase-3 backfill replaces these with real SharePoint webUrls."""
    return f"https://sharepoint.placeholder/SalesOps-Demo/{kind}/{key}.pdf"


def _asset_payload(a: Asset, account_id: str, product_id: str | None) -> dict[str, Any]:
    payload = {
        "AccountId": account_id,
        "Name": (a.description or a.sku or a.serial)[:80],
        "SerialNumber": a.serial,
        "Status": (a.status or "Installed").replace("_", " ").title(),
        "InstallDate": _iso_date(a.install_date),
        "Last_Cal_Date__c": _iso_date(a.last_cal_date),
        "Calibration_Due_Date__c": _iso_date(a.calibration_due_date),
        "Cal_Interval_Months__c": a.cal_interval_months,
        "Asset_Location__c": a.location,
        "Cal_Cert_Url__c": _placeholder_url("calibration", a.serial),
        "Document_Url__c": _placeholder_url("asset", a.serial),
    }
    if product_id:
        payload["Product2Id"] = product_id
    return payload


def _quote_payload(q: Quote, account_id: str, code: str | None) -> dict[str, Any]:
    return {
        "Name": q.quote_number,
        "AccountId": account_id,
        "Status": (q.status or "Draft").title(),
        "ExpirationDate": _iso_date(q.valid_until),
        "GrandTotal": q.total,
        "Subtotal": q.subtotal,
        "Discount": q.discount_pct,
        "ShippingHandling": q.freight,
        "Tax": q.tax,
        "Customer_Code__c": code,
        "Sales_Rep__c": q.sales_rep,
        "Sales_Engineer__c": q.engineer,
        "Pricing_Terms__c": q.pricing_terms,
        "Document_Url__c": _placeholder_url("quote", q.quote_number),
    }


def _workorder_payload(w: WorkOrder, account_id: str, asset_id: str | None, code: str | None) -> dict[str, Any]:
    payload = {
        "AccountId": account_id,
        "Subject": (w.description or w.type or w.wo_number)[:255],
        "Description": w.description,
        "Status": (w.status or "New").replace("_", " ").title(),
        "Priority": "Medium",
        "StartDate": _iso_dt(w.scheduled_date),
        "EndDate": _iso_dt(w.completed_date),
        "WO_Number__c": w.wo_number,
        "Customer_Code__c": code,
        "Asset_Serial__c": w.asset_serial,
        "Asset_SKU__c": w.asset_sku,
        "Type__c": w.type,
        "Region__c": w.region,
        "Technician__c": w.technician,
        "Cert_Number__c": w.cert_number,
        "Standards_Referenced__c": ", ".join(w.standards_referenced or []) if w.standards_referenced else None,
        "Signoff_Status__c": w.signoff_status,
        "Cost_USD__c": w.cost_usd,
        "Document_Url__c": _placeholder_url("workorder", w.wo_number),
    }
    if asset_id:
        payload["AssetId"] = asset_id
    return payload


def _service_contract_payload(s: ServiceContract, account_id: str, code: str | None) -> dict[str, Any]:
    return {
        "Name": s.contract_number,
        "AccountId": account_id,
        "StartDate": _iso_date(s.starts_on),
        "EndDate": _iso_date(s.expires_on),
        "Term": (
            (s.expires_on - s.starts_on).days // 30
            if (s.starts_on and s.expires_on)
            else 12
        ),
        "Description": s.notes,
        "Contract_Number__c": s.contract_number,
        "Customer_Code__c": code,
        "Coverage_Type__c": s.type,
        "SLA_Response_Hours__c": s.sla_response_hours,
        "SLA_Resolution_Hours__c": s.sla_resolution_hours,
        "Annual_Value_USD__c": s.annual_value_usd,
        "Included_Assets__c": ", ".join(str(x) for x in (s.included_assets or [])) if s.included_assets else None,
        "Document_Url__c": _placeholder_url("service-contract", s.contract_number),
    }


def _order_payload(o: Order, account_id: str, code: str | None) -> dict[str, Any]:
    # Standard SF Order picklist only allows Draft / Activated. Any in-flight
    # status from our mock ERP collapses to Draft so the trace can still see
    # the row; the original status is preserved in Description for audit.
    raw_status = (o.status or "draft").lower()
    sf_status = "Activated" if raw_status in {"completed", "shipped", "invoiced"} else "Draft"
    # TotalAmount is read-only on Order (rolled up from OrderItem). Stash the
    # demo total in Description so the trace UI still has a number to show.
    return {
        "AccountId": account_id,
        "Status": sf_status,
        "EffectiveDate": _iso_date(o.order_date) or _iso_date(o.created_at),
        "PoNumber": o.customer_po,
        "Description": (
            f"Order {o.order_number} · internal status='{o.status or 'unknown'}' "
            f"· total=${(o.total or 0):,.2f} · cust={code or 'n/a'}"
        ),
    }


def _case_payload_for_account(account_id: str, code: str | None, idx: int) -> dict[str, Any]:
    return {
        "AccountId": account_id,
        "Status": "Closed" if idx % 2 == 0 else "Working",
        "Origin": "Email",
        "Priority": "Medium",
        "Subject": f"Synthetic case {idx} for {code or account_id}",
        "Description": "Seeded for ZBrain SalesOps demo enrichment trace.",
    }


def seed_master(sf: Salesforce, db: Session) -> dict[str, int]:
    counts = {"accounts": 0, "contacts": 0, "products": 0, "pricebook_entries": 0}

    # --- Accounts ---
    customers = db.query(Customer).order_by(Customer.id).all()
    code_to_account_id: dict[str, str] = {}
    for c in customers:
        try:
            res = sf.Account.create(_account_payload(c))
            if res.get("success"):
                code_to_account_id[c.code] = res["id"]
                counts["accounts"] += 1
        except SalesforceMalformedRequest as e:
            log.warning("account create failed for %s: %s", c.code, e)

    # --- Contacts ---
    contacts = db.query(Contact).order_by(Contact.id).all()
    code_lookup = {c.id: c.code for c in customers}
    for ct in contacts:
        code = code_lookup.get(ct.customer_id)
        account_id = code_to_account_id.get(code) if code else None
        if not account_id:
            continue
        try:
            res = sf.Contact.create(_contact_payload(ct, account_id))
            if res.get("success"):
                counts["contacts"] += 1
        except SalesforceMalformedRequest as e:
            log.warning("contact create failed for %s: %s", ct.email, e)

    # --- Products ---
    products = db.query(Product).order_by(Product.id).all()
    sku_to_product_id: dict[str, str] = {}
    for p in products:
        try:
            res = sf.Product2.create(_product_payload(p))
            if res.get("success"):
                sku_to_product_id[p.sku] = res["id"]
                counts["products"] += 1
        except SalesforceMalformedRequest as e:
            log.warning("product create failed for %s: %s", p.sku, e)

    # --- PricebookEntries (Standard Pricebook) ---
    try:
        pb = sf.query("SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1")["records"][0]
        standard_pricebook_id = pb["Id"]
    except Exception as e:
        log.error("could not find standard pricebook: %s", e)
        return counts

    for sku, product_id in sku_to_product_id.items():
        product = next((p for p in products if p.sku == sku), None)
        if not product:
            continue
        try:
            res = sf.PricebookEntry.create({
                "Pricebook2Id": standard_pricebook_id,
                "Product2Id": product_id,
                "UnitPrice": product.list_price,
                "IsActive": True,
            })
            if res.get("success"):
                counts["pricebook_entries"] += 1
        except SalesforceMalformedRequest as e:
            log.warning("pricebook entry create failed for %s: %s", sku, e)

    # --- Assets / Quotes / WorkOrders / ServiceContracts / Cases / Orders ---
    extras = seed_extras(sf, db, code_to_account_id, sku_to_product_id)
    counts.update(extras)

    return counts


def seed_extras(
    sf: Salesforce,
    db: Session,
    code_to_account_id: dict[str, str],
    sku_to_product_id: dict[str, str],
) -> dict[str, int]:
    """Push Asset / Quote / WorkOrder / ServiceContract / Case / Order rows.

    Each operates independently — if a Salesforce feature isn't enabled in the
    target org (FSL, Quotes), the corresponding section logs a warning and
    moves on rather than aborting the whole seed."""
    counts = {
        "assets": 0,
        "quotes": 0,
        "work_orders": 0,
        "service_contracts": 0,
        "cases": 0,
        "orders": 0,
    }

    customers = db.query(Customer).order_by(Customer.id).all()
    cust_id_to_code = {c.id: c.code for c in customers}

    # Assets — keep a per-customer-code → SF Asset Id map for WorkOrder linking
    asset_serial_to_id: dict[str, str] = {}
    log.info("seeding Assets…")
    for a in db.query(Asset).order_by(Asset.id).all():
        code = cust_id_to_code.get(a.customer_id)
        account_id = code_to_account_id.get(code) if code else None
        if not account_id:
            continue
        product_id = sku_to_product_id.get(a.sku)
        try:
            res = sf.Asset.create(_asset_payload(a, account_id, product_id))
            if res.get("success"):
                asset_serial_to_id[a.serial] = res["id"]
                counts["assets"] += 1
        except (SalesforceMalformedRequest, Exception) as e:
            log.warning("asset create failed for serial=%s: %s", a.serial, e)

    # Quotes
    log.info("seeding Quotes…")
    for q in db.query(Quote).order_by(Quote.id).all():
        code = cust_id_to_code.get(q.customer_id)
        account_id = code_to_account_id.get(code) if code else None
        if not account_id:
            continue
        try:
            res = sf.Quote.create(_quote_payload(q, account_id, code))
            if res.get("success"):
                counts["quotes"] += 1
        except SalesforceMalformedRequest as e:
            # Quote object requires "Quotes" feature enabled (Setup → Quote Settings).
            log.warning("quote create failed for %s: %s — skipping (Quotes feature may be off)", q.quote_number, e)
            break
        except Exception as e:
            log.warning("quote create failed for %s: %s", q.quote_number, e)

    # ServiceContracts (native object — no extra license normally)
    log.info("seeding ServiceContracts…")
    for s in db.query(ServiceContract).order_by(ServiceContract.id).all():
        code = cust_id_to_code.get(s.customer_id)
        account_id = code_to_account_id.get(code) if code else None
        if not account_id:
            continue
        try:
            res = sf.ServiceContract.create(_service_contract_payload(s, account_id, code))
            if res.get("success"):
                counts["service_contracts"] += 1
        except (SalesforceMalformedRequest, Exception) as e:
            log.warning("service contract create failed for %s: %s", s.contract_number, e)

    # WorkOrders (Field Service Lightning)
    log.info("seeding WorkOrders…")
    fsl_disabled = False
    for w in db.query(WorkOrder).order_by(WorkOrder.id).all():
        code = cust_id_to_code.get(w.customer_id)
        account_id = code_to_account_id.get(code) if code else None
        if not account_id:
            continue
        asset_id = asset_serial_to_id.get(w.asset_serial)
        try:
            res = sf.WorkOrder.create(_workorder_payload(w, account_id, asset_id, code))
            if res.get("success"):
                counts["work_orders"] += 1
        except SalesforceMalformedRequest as e:
            log.warning("work order create failed for %s: %s — likely FSL not enabled, stopping WorkOrder seed", w.wo_number, e)
            fsl_disabled = True
            break
        except Exception as e:
            log.warning("work order create failed for %s: %s", w.wo_number, e)
    if fsl_disabled:
        log.info("WorkOrder seed aborted — Field Service Lightning may not be enabled in this org")

    # Orders — derived from SQLite Order rows (we'd already wiped Order earlier)
    log.info("seeding Orders…")
    for o in db.query(Order).order_by(Order.id).all():
        code = cust_id_to_code.get(o.customer_id)
        account_id = code_to_account_id.get(code) if code else None
        if not account_id:
            continue
        try:
            res = sf.Order.create(_order_payload(o, account_id, code))
            if res.get("success"):
                counts["orders"] += 1
        except (SalesforceMalformedRequest, Exception) as e:
            log.warning("order create failed for %s: %s", o.order_number, e)

    # Cases — 2 synthetic per account so service-path enrichment has rows to surface
    log.info("seeding Cases (2 per account)…")
    for code, account_id in code_to_account_id.items():
        for idx in range(1, 3):
            try:
                res = sf.Case.create(_case_payload_for_account(account_id, code, idx))
                if res.get("success"):
                    counts["cases"] += 1
            except (SalesforceMalformedRequest, Exception) as e:
                log.warning("case create failed for %s idx=%d: %s", code, idx, e)
                break

    log.info("seed_extras counts: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Salesforce wipe-and-seed for the SalesOps demo.")
    parser.add_argument("--all", action="store_true", help="Run all phases in order")
    parser.add_argument("--create-fields", action="store_true")
    parser.add_argument("--wipe", action="store_true")
    parser.add_argument("--seed-master", action="store_true")
    parser.add_argument("--seed-extras-only", action="store_true",
                        help="Skip Account/Contact/Product/Pricebook seeding — only push Asset/Quote/WorkOrder/ServiceContract/Case rows against existing accounts.")
    parser.add_argument("--field-propagation-wait-sec", type=int, default=15,
                        help="After creating fields, wait this many seconds before seeding so they're queryable")
    args = parser.parse_args()

    if args.all:
        args.create_fields = True
        args.wipe = True
        args.seed_master = True

    if not (args.create_fields or args.wipe or args.seed_master or args.seed_extras_only):
        parser.print_help()
        return 1

    db = SessionLocal()
    try:
        conn = sf_svc.get_active_connection(db)
        if not conn:
            log.error("No active Salesforce connection — connect via /api/integrations/salesforce/connect first")
            return 2
        sf = sf_svc.client_for(conn)
        log.info("connected to %s (%s)", conn.org_name, conn.org_edition)

        if args.create_fields:
            log.info("=== Phase 1 — create custom fields ===")
            res = create_all_fields(sf)
            log.info("fields created: %d, skipped: %d, failed: %d",
                     len(res["created"]), len(res["skipped"]), len(res["failed"]))
            log.info("granting FLS on all custom fields to running user…")
            all_field_names = [f["FullName"] for f in ALL_CUSTOM_FIELDS]
            granted = grant_field_access(sf, all_field_names)
            log.info("FLS granted on %d new field(s)", granted)
            if args.wipe or args.seed_master:
                log.info("waiting %ds for fields + permissions to propagate…", args.field_propagation_wait_sec)
                time.sleep(args.field_propagation_wait_sec)

        if args.wipe:
            log.info("=== Phase 2 — wipe org ===")
            counts = wipe_org(sf)
            log.info("wiped: %s", counts)

        if args.seed_master:
            log.info("=== Phase 3 — seed master data ===")
            # need a fresh session to read the demo data
            counts = seed_master(sf, db)
            log.info("seeded: %s", counts)

        if args.seed_extras_only and not args.seed_master:
            log.info("=== Seed extras only — re-reading existing Account/Product Ids from Salesforce ===")
            code_to_account_id: dict[str, str] = {}
            for r in sf.query_all("SELECT Id, Customer_Code__c FROM Account WHERE Customer_Code__c != null").get("records", []):
                code_to_account_id[r["Customer_Code__c"]] = r["Id"]
            log.info("re-read %d accounts by Customer_Code__c", len(code_to_account_id))
            sku_to_product_id: dict[str, str] = {}
            for r in sf.query_all("SELECT Id, ProductCode FROM Product2 WHERE ProductCode != null").get("records", []):
                sku_to_product_id[r["ProductCode"]] = r["Id"]
            log.info("re-read %d products by ProductCode", len(sku_to_product_id))
            counts = seed_extras(sf, db, code_to_account_id, sku_to_product_id)
            log.info("seeded extras: %s", counts)

        log.info("done.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
