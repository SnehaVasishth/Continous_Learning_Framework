"""One-shot Salesforce seeding for the SalesOps demo.

Pushes the synthetic SQLite catalogue (Products, Quotes, Orders, Assets,
Service Contracts, Work Orders, Contacts) into the connected dev org so the
Stage 2.4 enrichment SOQL queries return rich results during demos.

Idempotent — running twice will not create duplicates. Persists a
`local_id -> salesforce_id` map at `backend/data/sf_mapping.json` so the
running app can use these IDs for Stage 5 writes.

Run from `backend/`:
    python -m scripts.seed_salesforce
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Allow running as `python -m scripts.seed_salesforce` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simple_salesforce import Salesforce  # noqa: E402
from simple_salesforce.exceptions import SalesforceError  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Asset,
    Contact,
    Customer,
    Order,
    Product,
    Quote,
    ServiceContract,
    WorkOrder,
)
from app.services import salesforce as sf_svc  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_salesforce")

MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "sf_mapping.json"


# ---------------------------------------------------------------------------
# Mapping persistence
# ---------------------------------------------------------------------------


def load_mapping() -> dict[str, dict[str, str]]:
    if MAPPING_PATH.exists():
        try:
            return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("could not load existing %s: %s — starting fresh", MAPPING_PATH, e)
    return {}


def save_mapping(mapping: dict[str, dict[str, str]]) -> None:
    MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAPPING_PATH.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Counter
# ---------------------------------------------------------------------------


class StepStats:
    def __init__(self, sobject: str):
        self.sobject = sobject
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.errored = 0
        self.errors: list[str] = []
        self.feature_disabled = False
        self.disabled_reason: str | None = None

    def err(self, msg: str) -> None:
        self.errored += 1
        if len(self.errors) < 5:
            self.errors.append(msg[:200])

    def __str__(self) -> str:
        if self.feature_disabled:
            return f"{self.sobject}: SKIPPED (feature disabled: {self.disabled_reason})"
        return (
            f"{self.sobject}: created={self.created} updated={self.updated} "
            f"skipped={self.skipped} errored={self.errored}"
        )


# ---------------------------------------------------------------------------
# SF helpers
# ---------------------------------------------------------------------------


def sobject_exists(sf: Salesforce, name: str) -> bool:
    try:
        getattr(sf, name).describe()
        return True
    except Exception:
        return False


def field_exists(sf: Salesforce, sobject: str, field_api_name: str) -> bool:
    try:
        meta = getattr(sf, sobject).describe()
        return any(f["name"] == field_api_name for f in meta.get("fields", []))
    except Exception:
        return False


def soql_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def soql_in(values: list[str]) -> str:
    return ", ".join(f"'{soql_escape(v)}'" for v in values if v is not None)


def safe_create(sf_action: Callable[[dict], Any], payload: dict, stats: StepStats) -> str | None:
    """Create with fallback on validation errors. Returns SF Id or None."""
    try:
        res = sf_action(payload)
        if isinstance(res, dict) and res.get("success"):
            stats.created += 1
            return res["id"]
        stats.err(f"create non-success: {res}")
        return None
    except SalesforceError as e:
        stats.err(f"create failed: {e}")
        return None
    except Exception as e:
        stats.err(f"create exception: {type(e).__name__}: {e}")
        return None


def safe_update(sf_action: Callable[[str, dict], Any], record_id: str, payload: dict, stats: StepStats) -> bool:
    try:
        sf_action(record_id, payload)
        stats.updated += 1
        return True
    except SalesforceError as e:
        stats.err(f"update failed for {record_id}: {e}")
        return False
    except Exception as e:
        stats.err(f"update exception for {record_id}: {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------------------
# Step 1 — preload Account map (DO NOT seed accounts)
# ---------------------------------------------------------------------------


def load_account_map(sf: Salesforce, customers: list[Customer]) -> dict[int, str]:
    """customer.id -> Salesforce Account.Id, looked up by Customer_Code__c."""
    if not field_exists(sf, "Account", "Customer_Code__c"):
        log.error("Account.Customer_Code__c does not exist in this org. Cannot resolve Accounts. Aborting Account-dependent steps.")
        return {}
    codes = [c.code for c in customers if c.code]
    if not codes:
        return {}
    out: dict[int, str] = {}
    code_to_id: dict[str, str] = {}
    for chunk_start in range(0, len(codes), 200):
        chunk = codes[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, Customer_Code__c FROM Account WHERE Customer_Code__c IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
        except SalesforceError as e:
            log.warning("account lookup chunk failed: %s", e)
            continue
        for r in res.get("records") or []:
            code = r.get("Customer_Code__c")
            if code:
                code_to_id[code] = r["Id"]
    for c in customers:
        sf_id = code_to_id.get(c.code)
        if sf_id:
            out[c.id] = sf_id
    log.info("resolved %d/%d Account ids by Customer_Code__c", len(out), len(customers))
    return out


# ---------------------------------------------------------------------------
# Step 2 — Products (Product2)
# ---------------------------------------------------------------------------


def seed_products(sf: Salesforce, products: list[Product], mapping: dict[str, str]) -> StepStats:
    stats = StepStats("Product2")
    if not products:
        return stats

    # Pre-fetch existing products by ProductCode for idempotency
    skus = [p.sku for p in products if p.sku]
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(skus), 200):
        chunk = skus[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, ProductCode FROM Product2 WHERE ProductCode IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                if r.get("ProductCode"):
                    existing[r["ProductCode"]] = r["Id"]
        except SalesforceError as e:
            log.warning("Product2 prefetch failed: %s", e)

    has_eol = field_exists(sf, "Product2", "EOL_Date__c")
    has_lifecycle = field_exists(sf, "Product2", "Lifecycle_Status__c")

    for p in products:
        if not p.sku:
            stats.skipped += 1
            continue
        payload: dict[str, Any] = {
            "Name": (p.description or p.sku)[:80],
            "ProductCode": p.sku,
            "Description": p.description,
            "Family": p.family,
            "IsActive": True,
        }
        if has_eol and p.lifecycle_eol_date:
            payload["EOL_Date__c"] = p.lifecycle_eol_date.date().isoformat()
        if has_lifecycle and p.lifecycle_status:
            payload["Lifecycle_Status__c"] = p.lifecycle_status

        sf_id = existing.get(p.sku)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k != "ProductCode"}
            if safe_update(sf.Product2.update, sf_id, update_payload, stats):
                mapping[str(p.id)] = sf_id
        else:
            new_id = safe_create(sf.Product2.create, payload, stats)
            if new_id:
                mapping[str(p.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Step 3 — PricebookEntries on the standard Pricebook
# ---------------------------------------------------------------------------


def seed_pricebook_entries(
    sf: Salesforce, products: list[Product], product_map: dict[str, str]
) -> StepStats:
    stats = StepStats("PricebookEntry")
    res = sf.query("SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1")
    recs = res.get("records") or []
    if not recs:
        stats.feature_disabled = True
        stats.disabled_reason = "no standard Pricebook2 found"
        return stats
    pb_id = recs[0]["Id"]

    product_ids = list(product_map.values())
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(product_ids), 200):
        chunk = product_ids[chunk_start : chunk_start + 200]
        soql = (
            f"SELECT Id, Product2Id FROM PricebookEntry "
            f"WHERE Pricebook2Id = '{pb_id}' AND Product2Id IN ({soql_in(chunk)})"
        )
        try:
            qres = sf.query_all(soql)
            for r in qres.get("records") or []:
                existing[r["Product2Id"]] = r["Id"]
        except SalesforceError as e:
            log.warning("PricebookEntry prefetch failed: %s", e)

    for p in products:
        sf_product_id = product_map.get(str(p.id))
        if not sf_product_id:
            stats.skipped += 1
            continue
        if sf_product_id in existing:
            entry_id = existing[sf_product_id]
            safe_update(
                sf.PricebookEntry.update,
                entry_id,
                {"UnitPrice": p.list_price or 0.0, "IsActive": True},
                stats,
            )
        else:
            payload = {
                "Pricebook2Id": pb_id,
                "Product2Id": sf_product_id,
                "UnitPrice": p.list_price or 0.0,
                "IsActive": True,
                "UseStandardPrice": False,
            }
            safe_create(sf.PricebookEntry.create, payload, stats)
    return stats


# ---------------------------------------------------------------------------
# Step 4 — Contacts
# ---------------------------------------------------------------------------


def seed_contacts(
    sf: Salesforce, contacts: list[Contact], account_map: dict[int, str], mapping: dict[str, str]
) -> StepStats:
    stats = StepStats("Contact")
    if not contacts:
        return stats
    if not account_map:
        stats.feature_disabled = True
        stats.disabled_reason = "no Account ids resolved"
        return stats

    emails = [c.email for c in contacts if c.email]
    existing: dict[tuple[str, str], str] = {}
    for chunk_start in range(0, len(emails), 200):
        chunk = emails[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, Email, AccountId FROM Contact WHERE Email IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                key = ((r.get("Email") or "").lower(), r.get("AccountId") or "")
                existing[key] = r["Id"]
        except SalesforceError as e:
            log.warning("Contact prefetch failed: %s", e)

    for ct in contacts:
        account_id = account_map.get(ct.customer_id)
        if not account_id:
            stats.skipped += 1
            continue
        if not ct.email:
            stats.skipped += 1
            continue
        parts = (ct.name or "").split(" ", 1)
        first = parts[0] or ""
        last = parts[1] if len(parts) > 1 else "."
        payload: dict[str, Any] = {
            "AccountId": account_id,
            "FirstName": first,
            "LastName": last or ".",
            "Title": ct.title,
            "Email": ct.email,
            "Phone": ct.phone,
        }
        key = (ct.email.lower(), account_id)
        sf_id = existing.get(key)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k != "AccountId"}
            if safe_update(sf.Contact.update, sf_id, update_payload, stats):
                mapping[str(ct.id)] = sf_id
        else:
            new_id = safe_create(sf.Contact.create, payload, stats)
            if new_id:
                mapping[str(ct.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Step 5 — Opportunities (one per Quote)
# ---------------------------------------------------------------------------


def seed_opportunities(
    sf: Salesforce,
    quotes: list[Quote],
    customers_by_id: dict[int, Customer],
    account_map: dict[int, str],
    mapping: dict[str, str],
) -> StepStats:
    stats = StepStats("Opportunity")
    if not quotes:
        return stats
    if not account_map:
        stats.feature_disabled = True
        stats.disabled_reason = "no Account ids resolved"
        return stats

    names: list[str] = []
    quote_to_name: dict[int, str] = {}
    for q in quotes:
        cust = customers_by_id.get(q.customer_id)
        if not cust:
            continue
        name = f"Demo Opp - {cust.code} - {q.quote_number}"[:120]
        quote_to_name[q.id] = name
        names.append(name)

    existing: dict[str, str] = {}
    for chunk_start in range(0, len(names), 200):
        chunk = names[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, Name FROM Opportunity WHERE Name IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                existing[r["Name"]] = r["Id"]
        except SalesforceError as e:
            log.warning("Opportunity prefetch failed: %s", e)

    for q in quotes:
        cust = customers_by_id.get(q.customer_id)
        account_id = account_map.get(q.customer_id) if cust else None
        if not account_id:
            stats.skipped += 1
            continue
        name = quote_to_name.get(q.id)
        if not name:
            stats.skipped += 1
            continue
        close_date = (q.valid_until or q.quote_date or datetime.utcnow()).date().isoformat()
        payload = {
            "Name": name,
            "AccountId": account_id,
            "StageName": "Qualification",
            "CloseDate": close_date,
            "Amount": q.total or q.subtotal or 0.0,
            "Description": f"Auto-seeded from local quote {q.quote_number}",
        }
        sf_id = existing.get(name)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k not in ("Name", "AccountId")}
            if safe_update(sf.Opportunity.update, sf_id, update_payload, stats):
                mapping[str(q.id)] = sf_id
        else:
            new_id = safe_create(sf.Opportunity.create, payload, stats)
            if new_id:
                mapping[str(q.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Step 6 — Quotes (standard SObject; requires Quotes feature)
# ---------------------------------------------------------------------------


def seed_quotes(
    sf: Salesforce,
    quotes: list[Quote],
    opp_map: dict[str, str],
    mapping: dict[str, str],
) -> StepStats:
    stats = StepStats("Quote")
    if not sobject_exists(sf, "Quote"):
        stats.feature_disabled = True
        stats.disabled_reason = "Quotes feature not enabled in org"
        return stats
    if not quotes:
        return stats

    quote_numbers = [q.quote_number for q in quotes if q.quote_number]
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(quote_numbers), 200):
        chunk = quote_numbers[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, QuoteNumber, Name FROM Quote WHERE Name IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                if r.get("Name"):
                    existing[r["Name"]] = r["Id"]
        except SalesforceError as e:
            log.warning("Quote prefetch failed: %s", e)

    for q in quotes:
        opp_id = opp_map.get(str(q.id))
        if not opp_id:
            stats.skipped += 1
            continue
        payload = {
            "Name": q.quote_number,
            "OpportunityId": opp_id,
            "Status": "Draft",
            "ExpirationDate": (q.valid_until.date().isoformat() if q.valid_until else None),
            "Description": f"Auto-seeded — revision {q.revision}",
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        sf_id = existing.get(q.quote_number)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k not in ("Name", "OpportunityId")}
            if safe_update(sf.Quote.update, sf_id, update_payload, stats):
                mapping[str(q.id)] = sf_id
        else:
            new_id = safe_create(sf.Quote.create, payload, stats)
            if new_id:
                mapping[str(q.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Step 7 — QuoteLineItems
# ---------------------------------------------------------------------------


def _resolve_pricebook_entries(sf: Salesforce, pricebook_id: str, skus: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    skus = [s for s in skus if s]
    if not skus:
        return out
    for chunk_start in range(0, len(skus), 200):
        chunk = skus[chunk_start : chunk_start + 200]
        soql = (
            "SELECT Id, UnitPrice, Product2.ProductCode, Product2Id "
            "FROM PricebookEntry "
            f"WHERE Pricebook2Id = '{pricebook_id}' AND Product2.ProductCode IN ({soql_in(chunk)}) AND IsActive = true"
        )
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                sku = (r.get("Product2") or {}).get("ProductCode")
                if sku:
                    out[sku] = {
                        "pricebook_entry_id": r["Id"],
                        "product_id": r.get("Product2Id"),
                        "list_price": r.get("UnitPrice"),
                    }
        except SalesforceError as e:
            log.warning("PricebookEntry resolve failed: %s", e)
    return out


def seed_quote_line_items(
    sf: Salesforce, quotes: list[Quote], quote_sf_map: dict[str, str]
) -> StepStats:
    stats = StepStats("QuoteLineItem")
    if not sobject_exists(sf, "QuoteLineItem"):
        stats.feature_disabled = True
        stats.disabled_reason = "Quotes feature not enabled"
        return stats
    if not quote_sf_map:
        return stats

    pb_res = sf.query("SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1")
    pb_recs = pb_res.get("records") or []
    if not pb_recs:
        stats.feature_disabled = True
        stats.disabled_reason = "no standard Pricebook2"
        return stats
    pb_id = pb_recs[0]["Id"]

    all_skus: set[str] = set()
    for q in quotes:
        for li in (q.line_items or []):
            sku = (li or {}).get("sku")
            if sku:
                all_skus.add(sku)
    pb_entries = _resolve_pricebook_entries(sf, pb_id, list(all_skus))

    sf_quote_ids = list(quote_sf_map.values())
    existing_keys: set[tuple[str, str]] = set()
    for chunk_start in range(0, len(sf_quote_ids), 200):
        chunk = sf_quote_ids[chunk_start : chunk_start + 200]
        soql = (
            "SELECT QuoteId, PricebookEntryId FROM QuoteLineItem "
            f"WHERE QuoteId IN ({soql_in(chunk)})"
        )
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                existing_keys.add((r["QuoteId"], r["PricebookEntryId"]))
        except SalesforceError as e:
            log.warning("QuoteLineItem prefetch failed: %s", e)

    for q in quotes:
        sf_quote_id = quote_sf_map.get(str(q.id))
        if not sf_quote_id:
            continue
        for li in (q.line_items or []):
            li = li or {}
            sku = li.get("sku")
            if not sku:
                stats.skipped += 1
                continue
            entry = pb_entries.get(sku)
            if not entry:
                stats.skipped += 1
                continue
            if (sf_quote_id, entry["pricebook_entry_id"]) in existing_keys:
                stats.skipped += 1
                continue
            payload = {
                "QuoteId": sf_quote_id,
                "PricebookEntryId": entry["pricebook_entry_id"],
                "Product2Id": entry["product_id"],
                "Quantity": li.get("qty") or 1,
                "UnitPrice": li.get("unit_price") if li.get("unit_price") is not None else entry.get("list_price"),
            }
            safe_create(sf.QuoteLineItem.create, payload, stats)
    return stats


# ---------------------------------------------------------------------------
# Step 8 — Orders + OrderItems
# ---------------------------------------------------------------------------


def seed_orders(
    sf: Salesforce,
    orders: list[Order],
    account_map: dict[int, str],
    mapping: dict[str, str],
) -> StepStats:
    stats = StepStats("Order")
    if not orders:
        return stats
    if not account_map:
        stats.feature_disabled = True
        stats.disabled_reason = "no Account ids resolved"
        return stats

    pb_res = sf.query("SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1")
    pb_recs = pb_res.get("records") or []
    pb_id = pb_recs[0]["Id"] if pb_recs else None

    descriptions = [f"SeededOrder:{o.order_number}" for o in orders if o.order_number]
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(descriptions), 200):
        chunk = descriptions[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, Description FROM Order WHERE Description IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                existing[r.get("Description") or ""] = r["Id"]
        except SalesforceError as e:
            log.warning("Order prefetch failed: %s", e)

    for o in orders:
        account_id = account_map.get(o.customer_id)
        if not account_id:
            stats.skipped += 1
            continue
        marker = f"SeededOrder:{o.order_number}"
        effective = (o.order_date or datetime.utcnow()).date().isoformat()
        payload: dict[str, Any] = {
            "AccountId": account_id,
            "Status": "Draft",
            "EffectiveDate": effective,
            "PoNumber": (o.customer_po or "")[:30] or None,
            "Description": marker,
        }
        if pb_id:
            payload["Pricebook2Id"] = pb_id
        payload = {k: v for k, v in payload.items() if v is not None}

        sf_id = existing.get(marker)
        if sf_id:
            update_payload = {
                k: v for k, v in payload.items() if k not in ("AccountId", "Pricebook2Id")
            }
            if safe_update(sf.Order.update, sf_id, update_payload, stats):
                mapping[str(o.id)] = sf_id
        else:
            new_id = safe_create(sf.Order.create, payload, stats)
            if new_id:
                mapping[str(o.id)] = new_id
    return stats


def seed_order_items(
    sf: Salesforce, orders: list[Order], order_sf_map: dict[str, str]
) -> StepStats:
    stats = StepStats("OrderItem")
    if not order_sf_map:
        return stats

    pb_res = sf.query("SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1")
    pb_recs = pb_res.get("records") or []
    if not pb_recs:
        stats.feature_disabled = True
        stats.disabled_reason = "no standard Pricebook2"
        return stats
    pb_id = pb_recs[0]["Id"]

    all_skus: set[str] = set()
    for o in orders:
        for li in (o.line_items or []):
            sku = (li or {}).get("sku")
            if sku:
                all_skus.add(sku)
    pb_entries = _resolve_pricebook_entries(sf, pb_id, list(all_skus))

    sf_order_ids = list(order_sf_map.values())
    existing_keys: set[tuple[str, str]] = set()
    for chunk_start in range(0, len(sf_order_ids), 200):
        chunk = sf_order_ids[chunk_start : chunk_start + 200]
        soql = (
            "SELECT OrderId, PricebookEntryId FROM OrderItem "
            f"WHERE OrderId IN ({soql_in(chunk)})"
        )
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                existing_keys.add((r["OrderId"], r["PricebookEntryId"]))
        except SalesforceError as e:
            log.warning("OrderItem prefetch failed: %s", e)

    for o in orders:
        sf_order_id = order_sf_map.get(str(o.id))
        if not sf_order_id:
            continue
        for li in (o.line_items or []):
            li = li or {}
            sku = li.get("sku")
            if not sku:
                stats.skipped += 1
                continue
            entry = pb_entries.get(sku)
            if not entry:
                stats.skipped += 1
                continue
            if (sf_order_id, entry["pricebook_entry_id"]) in existing_keys:
                stats.skipped += 1
                continue
            payload = {
                "OrderId": sf_order_id,
                "PricebookEntryId": entry["pricebook_entry_id"],
                "Product2Id": entry["product_id"],
                "Quantity": li.get("qty") or 1,
                "UnitPrice": li.get("unit_price") if li.get("unit_price") is not None else entry.get("list_price"),
            }
            safe_create(sf.OrderItem.create, payload, stats)
    return stats


# ---------------------------------------------------------------------------
# Step 9 — Assets
# ---------------------------------------------------------------------------


def seed_assets(
    sf: Salesforce,
    assets: list[Asset],
    products: list[Product],
    product_sf_map: dict[str, str],
    account_map: dict[int, str],
    mapping: dict[str, str],
) -> StepStats:
    stats = StepStats("Asset")
    if not sobject_exists(sf, "Asset"):
        stats.feature_disabled = True
        stats.disabled_reason = "Asset SObject not available"
        return stats
    if not assets:
        return stats

    sku_to_local_id = {p.sku: p.id for p in products if p.sku}

    serials = [a.serial for a in assets if a.serial]
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(serials), 200):
        chunk = serials[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, SerialNumber FROM Asset WHERE SerialNumber IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                if r.get("SerialNumber"):
                    existing[r["SerialNumber"]] = r["Id"]
        except SalesforceError as e:
            log.warning("Asset prefetch failed: %s", e)

    for a in assets:
        account_id = account_map.get(a.customer_id)
        if not account_id or not a.serial:
            stats.skipped += 1
            continue
        local_product_id = sku_to_local_id.get(a.sku)
        sf_product_id = product_sf_map.get(str(local_product_id)) if local_product_id else None
        payload: dict[str, Any] = {
            "AccountId": account_id,
            "Name": (a.description or a.sku or a.serial)[:120],
            "SerialNumber": a.serial,
            "Status": "Installed",
        }
        if sf_product_id:
            payload["Product2Id"] = sf_product_id
        if a.install_date:
            payload["InstallDate"] = a.install_date.date().isoformat()

        sf_id = existing.get(a.serial)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k != "SerialNumber"}
            if safe_update(sf.Asset.update, sf_id, update_payload, stats):
                mapping[str(a.id)] = sf_id
        else:
            new_id = safe_create(sf.Asset.create, payload, stats)
            if new_id:
                mapping[str(a.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Step 10 — Service Contracts
# ---------------------------------------------------------------------------


def seed_service_contracts(
    sf: Salesforce,
    contracts: list[ServiceContract],
    account_map: dict[int, str],
    mapping: dict[str, str],
) -> StepStats:
    stats = StepStats("ServiceContract")
    if not sobject_exists(sf, "ServiceContract"):
        stats.feature_disabled = True
        stats.disabled_reason = "ServiceContract SObject not available (Service Cloud / FSL)"
        return stats
    if not contracts:
        return stats

    numbers = [sc.contract_number for sc in contracts if sc.contract_number]
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(numbers), 200):
        chunk = numbers[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, ContractNumber FROM ServiceContract WHERE ContractNumber IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                if r.get("ContractNumber"):
                    existing[r["ContractNumber"]] = r["Id"]
        except SalesforceError as e:
            log.warning("ServiceContract prefetch (by ContractNumber) failed: %s — falling back to Name", e)
            try:
                soql2 = f"SELECT Id, Name FROM ServiceContract WHERE Name IN ({soql_in(chunk)})"
                res = sf.query_all(soql2)
                for r in res.get("records") or []:
                    if r.get("Name"):
                        existing[r["Name"]] = r["Id"]
            except SalesforceError as e2:
                log.warning("ServiceContract prefetch fallback failed: %s", e2)

    for sc in contracts:
        account_id = account_map.get(sc.customer_id)
        if not account_id:
            stats.skipped += 1
            continue
        term_months = None
        if sc.starts_on and sc.expires_on:
            delta = sc.expires_on - sc.starts_on
            term_months = max(1, int(delta.days / 30))
        payload: dict[str, Any] = {
            "Name": sc.contract_number,
            "AccountId": account_id,
            "ContractTerm": term_months,
            "Status": "Active" if (sc.status or "").lower() == "active" else "Inactive",
        }
        if sc.starts_on:
            payload["StartDate"] = sc.starts_on.date().isoformat()
        payload = {k: v for k, v in payload.items() if v is not None}

        sf_id = existing.get(sc.contract_number)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k not in ("Name", "AccountId")}
            if safe_update(sf.ServiceContract.update, sf_id, update_payload, stats):
                mapping[str(sc.id)] = sf_id
        else:
            new_id = safe_create(sf.ServiceContract.create, payload, stats)
            if new_id:
                mapping[str(sc.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Step 11 — Work Orders (FSL)
# ---------------------------------------------------------------------------


WO_STATUS_MAP = {
    "open": "New",
    "new": "New",
    "in_progress": "In Progress",
    "scheduled": "New",
    "on_hold": "On Hold",
    "complete": "Completed",
    "completed": "Completed",
    "closed": "Closed",
    "cancelled": "Canceled",
    "canceled": "Canceled",
}


def seed_work_orders(
    sf: Salesforce,
    work_orders: list[WorkOrder],
    account_map: dict[int, str],
    asset_map: dict[str, str],
    mapping: dict[str, str],
) -> StepStats:
    stats = StepStats("WorkOrder")
    if not sobject_exists(sf, "WorkOrder"):
        stats.feature_disabled = True
        stats.disabled_reason = "WorkOrder SObject not available (Field Service Lightning)"
        return stats
    if not work_orders:
        return stats

    numbers = [wo.wo_number for wo in work_orders if wo.wo_number]
    existing: dict[str, str] = {}
    for chunk_start in range(0, len(numbers), 200):
        chunk = numbers[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, WorkOrderNumber, Subject FROM WorkOrder WHERE WorkOrderNumber IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                if r.get("WorkOrderNumber"):
                    existing[r["WorkOrderNumber"]] = r["Id"]
        except SalesforceError as e:
            log.warning("WorkOrder prefetch failed: %s", e)

    # Fallback: also lookup by Subject marker for prior-runs we created (no WorkOrderNumber control)
    markers = [f"SeededWO:{wo.wo_number}" for wo in work_orders if wo.wo_number]
    by_subject: dict[str, str] = {}
    for chunk_start in range(0, len(markers), 200):
        chunk = markers[chunk_start : chunk_start + 200]
        soql = f"SELECT Id, Subject FROM WorkOrder WHERE Subject IN ({soql_in(chunk)})"
        try:
            res = sf.query_all(soql)
            for r in res.get("records") or []:
                if r.get("Subject"):
                    by_subject[r["Subject"]] = r["Id"]
        except SalesforceError as e:
            log.warning("WorkOrder Subject prefetch failed: %s", e)

    for wo in work_orders:
        account_id = account_map.get(wo.customer_id)
        if not account_id:
            stats.skipped += 1
            continue
        asset_sf_id = asset_map.get(str(wo.asset_id)) if wo.asset_id else None
        marker = f"SeededWO:{wo.wo_number}"
        sf_status = WO_STATUS_MAP.get((wo.status or "").lower(), "New")
        payload: dict[str, Any] = {
            "Subject": marker,
            "Description": wo.description or marker,
            "AccountId": account_id,
            "Status": sf_status,
        }
        if asset_sf_id:
            payload["AssetId"] = asset_sf_id

        sf_id = by_subject.get(marker)
        if sf_id:
            update_payload = {k: v for k, v in payload.items() if k != "AccountId"}
            if safe_update(sf.WorkOrder.update, sf_id, update_payload, stats):
                mapping[str(wo.id)] = sf_id
        else:
            new_id = safe_create(sf.WorkOrder.create, payload, stats)
            if new_id:
                mapping[str(wo.id)] = new_id
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    db = SessionLocal()
    try:
        conn = sf_svc.get_active_connection(db)
        if not conn:
            log.error("No active Salesforce connection. Configure one via /api/integrations/salesforce/connect first.")
            return 2
        sf = sf_svc.client_for(conn)
        log.info("connected to %s (%s) as %s", conn.org_name, conn.org_edition, conn.user_display_name)

        customers = db.query(Customer).order_by(Customer.id).all()
        contacts = db.query(Contact).order_by(Contact.id).all()
        products = db.query(Product).order_by(Product.id).all()
        quotes = db.query(Quote).order_by(Quote.id).all()
        orders = db.query(Order).order_by(Order.id).all()
        assets = db.query(Asset).order_by(Asset.id).all()
        contracts = db.query(ServiceContract).order_by(ServiceContract.id).all()
        work_orders = db.query(WorkOrder).order_by(WorkOrder.id).all()

        customers_by_id = {c.id: c for c in customers}

        mapping = load_mapping()
        for k in (
            "Product2",
            "Contact",
            "Opportunity",
            "Quote",
            "Order",
            "Asset",
            "ServiceContract",
            "WorkOrder",
            "Account",
        ):
            mapping.setdefault(k, {})

        all_stats: list[StepStats] = []

        # Step 1 — Account map (read-only)
        log.info("[Step 1/11] Resolving Accounts by Customer_Code__c...")
        account_map = load_account_map(sf, customers)
        for cust_id, sf_id in account_map.items():
            mapping["Account"][str(cust_id)] = sf_id

        # Step 2 — Products
        log.info("[Step 2/11] Pushing %d Products...", len(products))
        s = seed_products(sf, products, mapping["Product2"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 3 — PricebookEntries
        log.info("[Step 3/11] Pushing PricebookEntries on standard pricebook...")
        s = seed_pricebook_entries(sf, products, mapping["Product2"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 4 — Contacts
        log.info("[Step 4/11] Pushing %d Contacts...", len(contacts))
        s = seed_contacts(sf, contacts, account_map, mapping["Contact"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 5 — Opportunities (one per Quote)
        log.info("[Step 5/11] Pushing %d Opportunities (one per Quote)...", len(quotes))
        s = seed_opportunities(sf, quotes, customers_by_id, account_map, mapping["Opportunity"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 6 — Quotes
        log.info("[Step 6/11] Pushing %d Quotes...", len(quotes))
        s = seed_quotes(sf, quotes, mapping["Opportunity"], mapping["Quote"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 7 — QuoteLineItems
        log.info("[Step 7/11] Pushing QuoteLineItems...")
        s = seed_quote_line_items(sf, quotes, mapping["Quote"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 8 — Orders + OrderItems
        log.info("[Step 8/11] Pushing %d Orders...", len(orders))
        s = seed_orders(sf, orders, account_map, mapping["Order"])
        log.info("   %s", s)
        all_stats.append(s)

        log.info("[Step 9/11] Pushing OrderItems...")
        s = seed_order_items(sf, orders, mapping["Order"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 10 — Assets
        log.info("[Step 10/11] Pushing %d Assets...", len(assets))
        s = seed_assets(sf, assets, products, mapping["Product2"], account_map, mapping["Asset"])
        log.info("   %s", s)
        all_stats.append(s)

        # Step 11 — ServiceContracts + WorkOrders
        log.info("[Step 11a/11] Pushing %d ServiceContracts...", len(contracts))
        s = seed_service_contracts(sf, contracts, account_map, mapping["ServiceContract"])
        log.info("   %s", s)
        all_stats.append(s)

        log.info("[Step 11b/11] Pushing %d WorkOrders...", len(work_orders))
        s = seed_work_orders(sf, work_orders, account_map, mapping["Asset"], mapping["WorkOrder"])
        log.info("   %s", s)
        all_stats.append(s)

        save_mapping(mapping)
        log.info("mapping persisted to %s", MAPPING_PATH)

        # Final summary
        print("\n" + "=" * 72)
        print("FINAL SUMMARY".center(72))
        print("=" * 72)
        print(f"{'SObject':<20} {'created':>8} {'updated':>8} {'skipped':>8} {'errored':>8}  status")
        print("-" * 72)
        skipped_features: list[str] = []
        for st in all_stats:
            if st.feature_disabled:
                print(f"{st.sobject:<20} {'-':>8} {'-':>8} {'-':>8} {'-':>8}  SKIPPED ({st.disabled_reason})")
                skipped_features.append(f"{st.sobject} ({st.disabled_reason})")
            else:
                print(
                    f"{st.sobject:<20} {st.created:>8} {st.updated:>8} {st.skipped:>8} {st.errored:>8}  ok"
                )
                if st.errors:
                    for e in st.errors:
                        print(f"   ! {e}")
        print("=" * 72)
        if skipped_features:
            print("\nFeatures NOT enabled in this org (these SObjects were skipped):")
            for f in skipped_features:
                print(f"  - {f}")
        print(f"\nMapping persisted to: {MAPPING_PATH}")
        return 0
    except Exception as e:
        log.error("fatal error: %s\n%s", e, traceback.format_exc())
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
