"""Seed Leeway Hertz as a customer in BOTH stores:
  1. The local SQLite `customers` table (fallback when Salesforce is offline).
  2. The connected Salesforce org as an Account (if a live SF connection exists).

The customer-match step compares the inbound email's `from_address` and any
domain alias against `customers.email`. We pin LEEWAY-HERTZ-001 to the
`rituraj@leewayhertz.com` sender so the three demo emails always match.

Idempotent: re-running updates the row if present, inserts otherwise.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Customer

log = logging.getLogger("seed_leewayhertz")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


CUSTOMER_CODE = "LEEWAY-HERTZ-001"
CUSTOMER_NAME = "Leeway Hertz"
LEGAL_ENTITY = "Leeway Hertz Pvt. Ltd."
PRIMARY_EMAIL = "rituraj@leewayhertz.com"


def upsert_local(db: Session) -> dict:
    existing = db.query(Customer).filter(Customer.code == CUSTOMER_CODE).first()
    addresses = [
        {
            "kind": "ship_to",
            "label": "Delhi RnD Lab (primary)",
            "street": "Plot 7, Sector 18, Electronic City",
            "city": "New Delhi",
            "postal_code": "110001",
            "country": "IN",
        },
        {
            "kind": "ship_to",
            "label": "Mumbai BKC Lab",
            "street": "RnD Lab, Bandra Kurla Complex",
            "city": "Mumbai",
            "postal_code": "400051",
            "country": "IN",
        },
        {
            "kind": "bill_to",
            "label": "Leeway Hertz Accounts Payable",
            "street": "Plot 7, Sector 18, Electronic City",
            "city": "New Delhi",
            "postal_code": "110001",
            "country": "IN",
            "email": "ap@leewayhertz.com",
        },
    ]
    fields = dict(
        code=CUSTOMER_CODE,
        name=CUSTOMER_NAME,
        legal_entity=LEGAL_ENTITY,
        region="APAC",
        language="en",
        email=PRIMARY_EMAIL,
        vertical="Technology · R&D Services",
        compliance="Standard,KYC-Verified",
        industry="Software / Engineering Services",
        naics="541512",
        annual_revenue_usd=18_500_000,
        employees=520,
        account_manager="Yuki Tanaka",
        sales_engineer="Marcus Rivera",
        customer_since=datetime(2024, 3, 15),
        status="active",
        sla_tier="Standard",
        duns="08-924-1503",
        tax_id="07AAACL1234B1Z5",
        payment_terms="NET 30",
        credit_limit=250_000,
        default_currency="USD",
        default_incoterms="DDP",
        addresses=addresses,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        action = "updated"
        cust = existing
    else:
        cust = Customer(**fields)
        db.add(cust)
        action = "created"
    db.commit()
    return {"action": action, "id": cust.id, "code": cust.code, "email": cust.email}


def upsert_salesforce(db: Session) -> dict:
    """Create or update the matching Salesforce Account if SF is connected."""
    try:
        from app.services import salesforce as sf_svc
    except Exception as e:
        return {"skipped": True, "reason": f"sf import failed: {e}"}
    conn = sf_svc.get_active_connection(db)
    if not conn:
        return {"skipped": True, "reason": "no_active_salesforce_connection"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        return {"skipped": True, "reason": f"sf client init failed: {e}"}

    # Look up by Customer_Code__c if the org has that custom field; otherwise
    # by Name. Some sandboxes don't have the custom field so we tolerate both.
    soql = f"SELECT Id, Name, Customer_Code__c FROM Account WHERE Customer_Code__c = '{CUSTOMER_CODE}' OR Name = '{CUSTOMER_NAME}' LIMIT 1"
    try:
        res = sf.query(soql)
    except Exception:
        # Custom field not present — fall back to Name only.
        res = sf.query(f"SELECT Id, Name FROM Account WHERE Name = '{CUSTOMER_NAME}' LIMIT 1")

    body = {
        "Name": CUSTOMER_NAME,
        "BillingStreet": "Plot 7, Sector 18, Electronic City",
        "BillingCity": "New Delhi",
        "BillingPostalCode": "110001",
        "BillingCountryCode": "IN",
        "Industry": "Technology",
        "Description": (
            "Leeway Hertz Pvt. Ltd. — R&D services customer. Demo account used "
            "for end-to-end SalesOps pipeline showcases. Primary contact: "
            "rituraj@leewayhertz.com."
        ),
        "NumberOfEmployees": 520,
    }
    # Best-effort: include custom fields if the org supports them.
    optional = {
        "Customer_Code__c": CUSTOMER_CODE,
        "Region__c": "APAC",
        "Vertical__c": "Technology / R&D",
        "SLA_Tier__c": "Standard",
        "DUNS__c": "08-924-1503",
        "Compliance_Flags__c": "Standard,KYC-Verified",
        "Payment_Terms__c": "NET 30",
        "Credit_Limit__c": 250000,
        "Annual_Revenue_USD__c": 18_500_000,
        "Default_Currency__c": "USD",
        "Default_Incoterms__c": "DDP",
        "Language__c": "en",
    }
    payload = dict(body)
    payload.update(optional)

    rows = res.get("records") or []
    if rows:
        acc_id = rows[0]["Id"]
        try:
            sf.Account.update(acc_id, payload)
        except Exception:
            # Drop optional fields if the org rejects them and retry.
            sf.Account.update(acc_id, body)
        return {"action": "updated", "id": acc_id}

    try:
        created = sf.Account.create(payload)
    except Exception:
        created = sf.Account.create(body)
    return {"action": "created", "id": created.get("id") if isinstance(created, dict) else None}


def main() -> None:
    db = SessionLocal()
    try:
        local = upsert_local(db)
        log.info("local customers row: %s", local)
        sf = upsert_salesforce(db)
        log.info("salesforce account: %s", sf)
        print({"local": local, "salesforce": sf})
    finally:
        db.close()


if __name__ == "__main__":
    main()
