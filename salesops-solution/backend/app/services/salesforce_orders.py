"""Stage 4 — Salesforce Order writes.

Creates a real Salesforce Order linked to the matched Account, with OrderItems
resolved against the seeded Pricebook entries. Used for PO intake / quote-to-order
auto-decisions.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceError

from ..models import Quote, SalesforceConnection
from sqlalchemy.orm import Session

from . import salesforce as sf_svc

log = logging.getLogger("salesforce_orders")


def _standard_pricebook_id(sf: Salesforce) -> str | None:
    res = sf.query("SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1")
    recs = res.get("records") or []
    return recs[0]["Id"] if recs else None


def _resolve_pricebook_entries(sf: Salesforce, pricebook_id: str, skus: list[str]) -> dict[str, dict]:
    """Returns {sku: {pricebook_entry_id, list_price}}."""
    if not skus or not pricebook_id:
        return {}
    skus = [s for s in skus if s]
    chunked: dict[str, dict] = {}
    sku_clause = ", ".join(f"'{s.replace(chr(39), chr(39)+chr(39))}'" for s in skus)
    soql = (
        "SELECT Id, UnitPrice, Product2.ProductCode, Product2Id "
        "FROM PricebookEntry "
        f"WHERE Pricebook2Id = '{pricebook_id}' AND Product2.ProductCode IN ({sku_clause}) AND IsActive = true"
    )
    try:
        res = sf.query(soql)
        for r in res.get("records") or []:
            sku = (r.get("Product2") or {}).get("ProductCode")
            if sku:
                chunked[sku] = {
                    "pricebook_entry_id": r.get("Id"),
                    "product_id": r.get("Product2Id"),
                    "list_price": r.get("UnitPrice"),
                }
    except SalesforceError as e:
        log.warning("pricebook lookup failed: %s", e)
    return chunked


def _normalize_line_items(extracted: dict) -> list[dict]:
    items = extracted.get("line_items") or []
    if not isinstance(items, list):
        return []
    out = []
    for li in items:
        if not isinstance(li, dict):
            continue
        sku = li.get("sku") or li.get("part_number") or li.get("product_code")
        qty = li.get("qty") or li.get("quantity") or 1
        unit = li.get("unit_price") or li.get("price")
        try:
            qty = int(qty) if qty else 1
        except Exception:
            qty = 1
        try:
            unit = float(unit) if unit else None
        except Exception:
            unit = None
        if sku:
            out.append({"sku": str(sku).strip(), "qty": qty, "unit_price": unit})
    return out


def create_order_for_account(
    conn: SalesforceConnection,
    *,
    account_id: str,
    extracted: dict,
    intent: str,
    order_status: str = "Draft",
) -> dict[str, Any]:
    """Create a Salesforce Order with line items.

    `order_status`:
        "Draft"     — used on L3 (one-click) to stage pending CSR confirmation
        "Activated" — used on L4 (auto) to write a fully-confirmed order

    Salesforce requires Pricebook2Id only on Draft orders; once Activated, the
    pricebook can't be added/changed. So if order_status="Activated" we activate
    AFTER OrderItems are created.
    """
    sf = sf_svc.client_for(conn)

    standard_pb = _standard_pricebook_id(sf)
    if not standard_pb:
        return {"applied": False, "reason": "no standard pricebook found"}

    line_items = _normalize_line_items(extracted)
    skus = [li["sku"] for li in line_items]
    pb_entries = _resolve_pricebook_entries(sf, standard_pb, skus)

    effective_date = (date.today() + timedelta(days=14)).isoformat()
    po_number = (extracted.get("po_number") or "")[:30]

    # Always start as Draft so we can attach line items + pricebook; activate later if requested
    order_payload = {
        "AccountId": account_id,
        "Status": "Draft",
        "EffectiveDate": effective_date,
        "Pricebook2Id": standard_pb,
        "PoNumber": po_number or None,
        "Description": f"Created by ZBrain agent fabric · intent={intent}",
    }

    try:
        order_res = sf.Order.create(order_payload)
    except SalesforceError as e:
        return {"applied": False, "reason": f"Order.create failed: {e}"}

    if not order_res.get("success"):
        return {"applied": False, "reason": "Order.create returned non-success", "raw": order_res}

    order_id = order_res["id"]
    items_created = 0
    items_skipped: list[dict] = []
    for li in line_items:
        entry = pb_entries.get(li["sku"])
        if not entry:
            items_skipped.append({"sku": li["sku"], "reason": "no PricebookEntry"})
            continue
        unit_price = li.get("unit_price")
        if unit_price is None:
            unit_price = entry.get("list_price")
        try:
            sf.OrderItem.create({
                "OrderId": order_id,
                "PricebookEntryId": entry["pricebook_entry_id"],
                "Quantity": li["qty"],
                "UnitPrice": unit_price,
            })
            items_created += 1
        except SalesforceError as e:
            items_skipped.append({"sku": li["sku"], "reason": str(e)[:200]})

    # Optionally activate the order (L4 path)
    final_status = "Draft"
    activation_error: str | None = None
    if order_status == "Activated" and items_created > 0:
        try:
            sf.Order.update(order_id, {"Status": "Activated"})
            final_status = "Activated"
        except SalesforceError as e:
            activation_error = str(e)[:300]
            log.warning("Order activation failed for %s: %s", order_id, e)

    # Read back the created order for OrderNumber
    try:
        result = sf.Order.get(order_id)
        order_number = result.get("OrderNumber")
        final_status = result.get("Status") or final_status
    except Exception:
        order_number = None

    instance_url = (conn.instance_url or "").rstrip("/")
    return {
        "applied": True,
        "salesforce_order_id": order_id,
        "salesforce_order_number": order_number,
        "salesforce_status": final_status,
        "requested_status": order_status,
        "activation_error": activation_error,
        "salesforce_url": f"{instance_url}/lightning/r/Order/{order_id}/view",
        "account_id": account_id,
        "po_number": po_number,
        "effective_date": effective_date,
        "line_items_total": len(line_items),
        "line_items_created": items_created,
        "line_items_skipped": items_skipped,
    }


# ---------------------------------------------------------------------------
# Stage 4 SF write helpers — replace the SQLite mocks in mocks/erp.py for
# Stage-4 actions (release_hold, reschedule_order, convert_quote_to_order,
# apply_change_order). Mocks remain for non-Stage-4 paths.
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    return (s or "").replace("'", "\\'")


def _find_order_by_number(sf: Salesforce, order_number: str) -> dict | None:
    """Locate an SF Order by either its native OrderNumber or its PoNumber.

    Stage-4 emails reference 'order numbers' that, in our domain, are sometimes
    actually customer PO numbers — try both so demo flows succeed regardless of
    which the buyer cited.
    """
    safe = _esc(order_number)
    soql = (
        "SELECT Id, OrderNumber, Status, PoNumber, AccountId, EffectiveDate "
        "FROM Order "
        f"WHERE OrderNumber = '{safe}' OR PoNumber = '{safe}' "
        "ORDER BY CreatedDate DESC LIMIT 1"
    )
    try:
        res = sf.query(soql)
        recs = res.get("records") or []
        if not recs:
            return None
        return {k: v for k, v in recs[0].items() if k != "attributes"}
    except SalesforceError as e:
        log.warning("order lookup failed for %s: %s", order_number, e)
        return None


def _order_status_picklist(sf: Salesforce) -> list[str]:
    """Read the Order.Status picklist values for the running user. Cheap & idempotent."""
    try:
        meta = sf.Order.describe()
        for f in meta.get("fields", []):
            if f.get("name") == "Status":
                return [v.get("value") for v in (f.get("picklistValues") or []) if v.get("value")]
    except Exception as e:
        log.debug("order describe failed: %s", e)
    return []


def convert_quote_to_sf_order(
    conn: SalesforceConnection,
    *,
    db: Session,
    account_id: str,
    quote_id: int,
    intent: str = "convert_quote_to_order",
    order_status: str = "Activated",
) -> dict[str, Any]:
    """Read the source Quote from SQLite (still authoritative for the demo's quote
    catalog), then write an Order + OrderItems into Salesforce via the existing
    `create_order_for_account` helper.
    """
    q = db.get(Quote, quote_id)
    if not q:
        return {"applied": False, "reason": "quote not found"}
    extracted = {
        "quote_number": q.quote_number,
        "po_number": f"FROM-{q.quote_number}"[:30],
        "line_items": list(q.line_items or []),
    }
    return create_order_for_account(
        conn,
        account_id=account_id,
        extracted=extracted,
        intent=intent or "convert_quote_to_order",
        order_status=order_status,
    )


def release_hold_in_sf(
    conn: SalesforceConnection,
    *,
    order_number: str,
) -> dict[str, Any]:
    """Find an SF Order by OrderNumber/PoNumber and flip its Status to the
    'released' picklist value (Activated when available, else the first non-Draft
    value in the picklist)."""
    if not order_number:
        return {"applied": False, "reason": "missing order_number"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        log.warning("release_hold_in_sf: SF connect failed: %s", e)
        return {"applied": False, "reason": f"sf_connect_failed: {type(e).__name__}: {e}"[:300]}

    order = _find_order_by_number(sf, order_number)
    if not order:
        return {"applied": False, "reason": f"order {order_number} not found in Salesforce"}

    picklist = _order_status_picklist(sf)
    target_status = "Activated" if "Activated" in picklist else next(
        (v for v in picklist if v and v.lower() != "draft"), None
    )
    if not target_status:
        return {"applied": False, "reason": "no released-state picklist value available on Order.Status"}

    # Build the update payload. We always flip Status, and additionally clear
    # the `HOLD-*` marker on OrderReferenceNumber when present (this is how
    # the SalesOps stage-2 enrichment detects on-hold orders — without
    # clearing it, the Stage 2 query would still surface the order as held).
    update_payload: dict[str, Any] = {"Status": target_status}
    prior_ref = None
    hold_marker_cleared = False
    try:
        # Re-read OrderReferenceNumber explicitly (the small select in
        # _find_order_by_number does not include it).
        safe_id = order["Id"].replace("'", "\\'")
        ref_q = sf.query(f"SELECT OrderReferenceNumber FROM Order WHERE Id = '{safe_id}' LIMIT 1")
        recs = (ref_q or {}).get("records") or []
        if recs:
            prior_ref = (recs[0] or {}).get("OrderReferenceNumber")
        if isinstance(prior_ref, str) and prior_ref.startswith("HOLD-"):
            # Replace HOLD-<reason> with RELEASED-<reason> so the audit trail
            # still shows why the hold was placed, while the marker no longer
            # matches the orders_on_hold SOQL filter.
            update_payload["OrderReferenceNumber"] = prior_ref.replace("HOLD-", "RELEASED-", 1)
            hold_marker_cleared = True
    except Exception as e:
        log.info("release_hold_in_sf: could not read OrderReferenceNumber for %s: %s", order_number, e)

    try:
        sf.Order.update(order["Id"], update_payload)
    except SalesforceError as e:
        log.warning("release_hold_in_sf failed for %s: %s", order_number, e)
        return {"applied": False, "reason": f"order_update_failed: {e}"[:300]}

    return {
        "applied": True,
        "salesforce_order_id": order["Id"],
        "order_number": order.get("OrderNumber"),
        "po_number": order.get("PoNumber"),
        "previous_status": order.get("Status"),
        "new_status": target_status,
        "hold_marker_previous": prior_ref,
        "hold_marker_new": update_payload.get("OrderReferenceNumber"),
        "hold_marker_cleared": hold_marker_cleared,
    }


def reschedule_sf_order(
    conn: SalesforceConnection,
    *,
    order_number: str,
    new_ship_date: datetime | date,
) -> dict[str, Any]:
    """Patch the Order's ship date. Prefers the custom Requested_Ship_Date__c
    field (added by salesforce_seed) so the audit-visible business date is
    distinct from EffectiveDate. Falls back to EffectiveDate if the custom field
    isn't present in the org."""
    if not order_number:
        return {"applied": False, "reason": "missing order_number"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        log.warning("reschedule_sf_order: SF connect failed: %s", e)
        return {"applied": False, "reason": f"sf_connect_failed: {type(e).__name__}: {e}"[:300]}

    order = _find_order_by_number(sf, order_number)
    if not order:
        return {"applied": False, "reason": f"order {order_number} not found in Salesforce"}

    iso_date = new_ship_date.date().isoformat() if isinstance(new_ship_date, datetime) else new_ship_date.isoformat()

    patch = {"Requested_Ship_Date__c": iso_date}
    field_used = "Requested_Ship_Date__c"
    try:
        sf.Order.update(order["Id"], patch)
    except SalesforceError as e:
        msg = str(e)
        if "INVALID_FIELD" in msg or "No such column" in msg or "Requested_Ship_Date__c" in msg:
            try:
                sf.Order.update(order["Id"], {"EffectiveDate": iso_date})
                field_used = "EffectiveDate"
            except SalesforceError as e2:
                log.warning("reschedule_sf_order EffectiveDate fallback failed for %s: %s", order_number, e2)
                return {"applied": False, "reason": f"order_update_failed: {e2}"[:300]}
        else:
            log.warning("reschedule_sf_order failed for %s: %s", order_number, e)
            return {"applied": False, "reason": f"order_update_failed: {e}"[:300]}

    return {
        "applied": True,
        "salesforce_order_id": order["Id"],
        "order_number": order.get("OrderNumber"),
        "po_number": order.get("PoNumber"),
        "field_updated": field_used,
        "new_ship_date": iso_date,
    }


def _list_order_items(sf: Salesforce, order_id: str) -> list[dict]:
    soql = (
        "SELECT Id, OrderId, Product2Id, PricebookEntryId, Quantity, UnitPrice, "
        "Product2.ProductCode "
        f"FROM OrderItem WHERE OrderId = '{_esc(order_id)}'"
    )
    try:
        res = sf.query(soql)
        out: list[dict] = []
        for r in res.get("records") or []:
            r = {k: v for k, v in r.items() if k != "attributes"}
            sku = (r.get("Product2") or {}).get("ProductCode")
            r["__sku"] = sku
            out.append(r)
        return out
    except SalesforceError as e:
        log.warning("order item query failed for %s: %s", order_id, e)
        return []


def apply_change_order_in_sf(
    conn: SalesforceConnection,
    *,
    order_number: str,
    line_changes: list[dict],
) -> dict[str, Any]:
    """Apply qty/price/swap/add/remove line changes against an SF Order's OrderItems.

    'add' creates a new OrderItem (resolves PricebookEntry against the order's
    Pricebook). 'swap' is implemented as delete-old + add-new because OrderItem
    doesn't allow Product2/PricebookEntry edits in place.
    Salesforce requires an Order to be in Draft status to mutate OrderItems —
    if the Order is Activated, the helper records that as a guardrail rather
    than failing silently."""
    if not order_number:
        return {"applied": False, "reason": "missing order_number"}
    if not line_changes:
        return {"applied": False, "reason": "no line_changes to apply"}
    try:
        sf = sf_svc.client_for(conn)
    except Exception as e:
        log.warning("apply_change_order_in_sf: SF connect failed: %s", e)
        return {"applied": False, "reason": f"sf_connect_failed: {type(e).__name__}: {e}"[:300]}

    order = _find_order_by_number(sf, order_number)
    if not order:
        return {"applied": False, "reason": f"order {order_number} not found in Salesforce"}

    # Capture full order details for pricebook id (used for new lines)
    try:
        full_order = sf.Order.get(order["Id"])
    except Exception as e:
        log.warning("Order.get failed for %s: %s", order["Id"], e)
        return {"applied": False, "reason": f"order_get_failed: {type(e).__name__}: {e}"[:300]}

    pricebook_id = full_order.get("Pricebook2Id") or _standard_pricebook_id(sf)
    items = _list_order_items(sf, order["Id"])
    sku_to_item = {it.get("__sku"): it for it in items if it.get("__sku")}

    applied_changes: list[dict] = []
    failures: list[dict] = []

    add_skus = [
        ch.get("new_sku") or ch.get("sku")
        for ch in line_changes
        if ch.get("change_kind") in ("add", "swap")
        and (ch.get("new_sku") or ch.get("sku"))
    ]
    pb_entries = _resolve_pricebook_entries(sf, pricebook_id, [s for s in add_skus if s]) if pricebook_id and add_skus else {}

    for ch in line_changes:
        kind = ch.get("change_kind")
        sku = ch.get("sku")
        try:
            if kind == "qty" and sku and ch.get("new_qty") is not None:
                target = sku_to_item.get(sku)
                if not target:
                    failures.append({"kind": kind, "sku": sku, "reason": "line not found"})
                    continue
                sf.OrderItem.update(target["Id"], {"Quantity": ch["new_qty"]})
                applied_changes.append({"kind": "qty", "sku": sku, "qty": ch["new_qty"]})
            elif kind == "price" and sku and ch.get("new_unit_price") is not None:
                target = sku_to_item.get(sku)
                if not target:
                    failures.append({"kind": kind, "sku": sku, "reason": "line not found"})
                    continue
                sf.OrderItem.update(target["Id"], {"UnitPrice": ch["new_unit_price"]})
                applied_changes.append({"kind": "price", "sku": sku, "unit_price": ch["new_unit_price"]})
            elif kind == "remove" and sku:
                target = sku_to_item.get(sku)
                if not target:
                    failures.append({"kind": kind, "sku": sku, "reason": "line not found"})
                    continue
                sf.OrderItem.delete(target["Id"])
                sku_to_item.pop(sku, None)
                applied_changes.append({"kind": "remove", "sku": sku})
            elif kind == "add":
                add_sku = ch.get("new_sku") or sku
                if not add_sku:
                    failures.append({"kind": kind, "reason": "no sku"})
                    continue
                entry = pb_entries.get(add_sku)
                if not entry:
                    failures.append({"kind": kind, "sku": add_sku, "reason": "no PricebookEntry for sku"})
                    continue
                qty = ch.get("new_qty") or 1
                unit_price = ch.get("new_unit_price") if ch.get("new_unit_price") is not None else entry.get("list_price")
                res = sf.OrderItem.create({
                    "OrderId": order["Id"],
                    "PricebookEntryId": entry["pricebook_entry_id"],
                    "Quantity": qty,
                    "UnitPrice": unit_price,
                })
                if res.get("success"):
                    applied_changes.append({"kind": "add", "sku": add_sku, "qty": qty, "unit_price": unit_price})
                else:
                    failures.append({"kind": kind, "sku": add_sku, "reason": "OrderItem.create returned non-success"})
            elif kind == "swap" and sku and ch.get("new_sku"):
                old_target = sku_to_item.get(sku)
                if not old_target:
                    failures.append({"kind": kind, "sku": sku, "reason": "old line not found"})
                    continue
                new_sku = ch["new_sku"]
                entry = pb_entries.get(new_sku)
                if not entry:
                    failures.append({"kind": kind, "sku": new_sku, "reason": "no PricebookEntry for new sku"})
                    continue
                qty = old_target.get("Quantity") or 1
                unit_price = ch.get("new_unit_price") if ch.get("new_unit_price") is not None else entry.get("list_price")
                sf.OrderItem.delete(old_target["Id"])
                sku_to_item.pop(sku, None)
                res = sf.OrderItem.create({
                    "OrderId": order["Id"],
                    "PricebookEntryId": entry["pricebook_entry_id"],
                    "Quantity": qty,
                    "UnitPrice": unit_price,
                })
                if res.get("success"):
                    applied_changes.append({"kind": "swap", "from_sku": sku, "to_sku": new_sku})
                else:
                    failures.append({"kind": kind, "from_sku": sku, "to_sku": new_sku, "reason": "OrderItem.create returned non-success"})
            else:
                failures.append({"kind": kind, "sku": sku, "reason": "unsupported or incomplete change"})
        except SalesforceError as e:
            msg = str(e)
            if "Activated" in msg or "INVALID_OPERATION" in msg or "cannot be modified" in msg.lower():
                return {
                    "applied": False,
                    "reason": "salesforce_order_locked: order must be Draft to modify line items",
                    "salesforce_order_id": order["Id"],
                    "order_status": full_order.get("Status"),
                    "detail": msg[:300],
                }
            log.warning("apply_change_order_in_sf change failed (%s/%s): %s", kind, sku, e)
            failures.append({"kind": kind, "sku": sku, "reason": str(e)[:200]})

    return {
        "applied": True,
        "salesforce_order_id": order["Id"],
        "order_number": order.get("OrderNumber"),
        "po_number": order.get("PoNumber"),
        "changes_applied": len(applied_changes),
        "changes": applied_changes,
        "failures": failures,
    }
