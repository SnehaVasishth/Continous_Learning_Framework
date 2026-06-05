"""Stage 4 — Workflow Execution.

Auto-execute (L4) actions hit Salesforce directly. L3 stages a 'pending one-click'
preview. L2 stages full HITL review. Spam is discarded.

Stage-4 writes are routed to Salesforce via the helpers in `services/salesforce_*`
— the SQLite mocks in `mocks/erp.py` are no longer called from this stage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Customer, Order, WorkOrder
from ..services import salesforce as sf_svc
from ..services import salesforce_orders as sf_orders
from ..services import salesforce_workorders as sf_wos

log = logging.getLogger("execute")


def run_execute(
    db: Session,
    *,
    intake: dict,
    extracted: dict,
    decision: dict,
    customer_id: int | None,
    salesforce_account_id: str | None = None,
    intent: str | None = None,
) -> dict:
    tier = decision.get("autonomy_tier")
    action = decision.get("action")

    if action == "discard":
        return {"status": "discarded", "reason": "spam"}

    preview = _build_preview(action, extracted, customer_id)

    if tier == "L4_AUTO":
        applied = _apply(
            db,
            action=action,
            extracted=extracted,
            customer_id=customer_id,
            salesforce_account_id=salesforce_account_id,
            intent=intent or "",
            order_status="Activated",
        )
        return {"status": "applied", "action": action, "preview": preview, "applied": applied}

    if tier == "L3_ONE_CLICK":
        # Stage a Draft Salesforce Order pending CSR one-click confirmation
        draft = _stage_l3_draft(
            db,
            action=action,
            extracted=extracted,
            salesforce_account_id=salesforce_account_id,
            intent=intent or "",
        )
        return {"status": "awaiting_one_click", "action": action, "preview": preview, "draft": draft}

    return {"status": "awaiting_hitl", "action": action, "preview": preview}


def _stage_l3_draft(
    db: Session,
    *,
    action: str,
    extracted: dict,
    salesforce_account_id: str | None,
    intent: str,
) -> dict | None:
    if action != "create_order_acknowledgment":
        return None
    if not salesforce_account_id:
        return None
    sf_conn = sf_svc.get_active_connection(db)
    if not sf_conn:
        return None
    try:
        return sf_orders.create_order_for_account(
            sf_conn,
            account_id=salesforce_account_id,
            extracted=extracted,
            intent=intent or "po_intake",
            order_status="Draft",
        )
    except Exception as e:
        log.warning("L3 draft Salesforce order create failed: %s", e)
        return {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}


def _build_preview(action: str, extracted: dict, customer_id: int | None) -> dict:
    return {
        "action": action,
        "customer_id": customer_id,
        "extracted": extracted,
        "action_required": _build_action_required(action, extracted),
    }


# ----------------------------------------------------------------------
# Structured action_required block (consumed by the HITL UI)
# ----------------------------------------------------------------------
# For every action ZBrain might propose we produce a block the CSR can use
# without scrolling through the raw extracted JSON: action_type, one-line
# summary, the prefilled fields they should verify, the downstream systems
# that will receive the write on approval, and a next-steps checklist. The
# block is non-binding (just guidance) — the actual write still goes through
# the same _apply() path.

_ACTION_LABELS: dict[str, dict[str, str]] = {
    "create_order_acknowledgment": {
        "label": "Create Sales Order Acknowledgment",
        "summary": "Acknowledge inbound PO, create Salesforce Order, generate SOA PDF.",
    },
    "convert_quote_to_order": {
        "label": "Convert quote to order",
        "summary": "Promote the matched quote to an active Salesforce Order.",
    },
    "release_hold": {
        "label": "Release order hold",
        "summary": "Lift the credit / inventory hold on the existing Salesforce Order.",
    },
    "reschedule_order": {
        "label": "Reschedule order ship date",
        "summary": "Update the requested ship date on the existing Salesforce Order.",
    },
    "create_work_order": {
        "label": "Create field-service work order",
        "summary": "Open a Salesforce Service WorkOrder for the requested calibration / service.",
    },
    "update_work_order": {
        "label": "Update existing work order",
        "summary": "Append the customer-supplied instruction to the existing Salesforce WorkOrder.",
    },
    "answer_wo_status": {
        "label": "Reply with WO status",
        "summary": "Send the customer the current WorkOrder status with a friendly KSP reassurance.",
    },
    "create_service_contract": {
        "label": "Create service contract",
        "summary": "Open the service contract draft in Salesforce for finance review.",
    },
    "trade_change_order": {
        "label": "Open trade change order",
        "summary": "Clone the closed Case and stage a Trade Change Order against the new requirements.",
    },
}


def _build_action_required(action: str | None, extracted: dict) -> dict:
    if not action:
        return {}
    meta = _ACTION_LABELS.get(action, {"label": action, "summary": ""})
    prefilled, systems, checklist = _action_specifics(action, extracted or {})
    return {
        "action_type": action,
        "label": meta["label"],
        "summary": meta["summary"],
        "prefilled_fields": prefilled,
        "downstream_systems": systems,
        "next_steps": checklist,
    }


def _action_specifics(action: str, ex: dict) -> tuple[dict, list[str], list[str]]:
    """Return (prefilled_fields, downstream_systems, next_steps) for a given
    action + extracted payload. Returns empty defaults for unknown actions so
    the UI never blows up on a new action key."""
    if action == "create_order_acknowledgment":
        return (
            {
                "customer_name": ex.get("customer_name"),
                "po_number": ex.get("po_number"),
                "quote_number": ex.get("quote_number"),
                "currency": ex.get("currency"),
                "total": ex.get("total"),
                "line_item_count": len(ex.get("line_items") or []),
                "requested_ship_date": ex.get("requested_ship_date"),
                "ship_to": (ex.get("ship_to") or {}).get("city") if isinstance(ex.get("ship_to"), dict) else ex.get("ship_to"),
            },
            ["Salesforce Order", "SOA PDF (SharePoint)", "Customer email reply"],
            [
                "Verify the matched quote and the line-item totals against the PO PDF.",
                "Confirm the requested ship date is feasible for this customer's region.",
                "Click Approve to create the Salesforce Order (status: Activated) and send the SOA.",
            ],
        )
    if action == "convert_quote_to_order":
        return (
            {
                "customer_name": ex.get("customer_name"),
                "quote_number": ex.get("quote_number"),
                "currency": ex.get("currency"),
                "total": ex.get("total"),
            },
            ["Salesforce Order", "Customer email reply"],
            [
                "Verify the customer's intent to convert (look for explicit confirmation in the email body).",
                "Click Approve to promote the matched quote to an active Salesforce Order.",
            ],
        )
    if action == "release_hold":
        return (
            {
                "order_number": ex.get("order_number"),
                "hold_type": ex.get("hold_type"),
                "release_reason": ex.get("release_reason"),
            },
            ["Salesforce Order (Status update)", "Customer email reply"],
            [
                "Confirm the hold reason has been cleared (credit/inventory check).",
                "Click Approve to release the hold and notify the customer.",
            ],
        )
    if action == "reschedule_order":
        return (
            {
                "order_number": ex.get("order_number"),
                "new_ship_date": ex.get("new_ship_date") or ex.get("requested_ship_date"),
                "reason": ex.get("reason"),
            },
            ["Salesforce Order (Ship date update)", "Customer email reply"],
            [
                "Verify the new ship date with the planning team if it crosses a quarter boundary.",
                "Click Approve to update the Salesforce Order and confirm with the customer.",
            ],
        )
    if action == "create_work_order":
        assets = ex.get("add_assets") or ex.get("assets") or []
        return (
            {
                "customer_name": ex.get("customer_name"),
                "service_type": ex.get("service_type") or ex.get("requested_service"),
                "site_location": ex.get("site_location") or (ex.get("ship_to") or {}).get("city") if isinstance(ex.get("ship_to"), dict) else None,
                "asset_count": len(assets) if isinstance(assets, list) else None,
                "requested_completion_date": ex.get("requested_completion_date") or ex.get("requested_date"),
                "po_reference": ex.get("po_number") or ex.get("customer_po"),
            },
            ["Salesforce Service WorkOrder", "Field service dispatch (Keysight)", "Customer email reply"],
            [
                "Verify the asset list (Model / Serial) resolves on the customer's installed base.",
                "Confirm the requested completion date is achievable for the customer's region.",
                "Click Approve to create the Salesforce WorkOrder and start the field-service dispatch flow.",
            ],
        )
    if action == "update_work_order":
        return (
            {
                "work_order_number": ex.get("work_order_number") or ex.get("wo_number"),
                "update_instruction": (ex.get("instruction") or ex.get("notes") or "")[:280],
            },
            ["Salesforce WorkOrder (comment append)", "Customer email reply"],
            [
                "Confirm the WorkOrder is still in an editable state (not closed).",
                "Click Approve to append the customer's update and notify the field-service owner.",
            ],
        )
    if action == "answer_wo_status":
        return (
            {
                "work_order_number": ex.get("work_order_number") or ex.get("wo_number"),
                "current_status": ex.get("wo_status"),
            },
            ["Customer email reply"],
            [
                "Check the WorkOrder status one more time before sending.",
                "Click Approve to send the status reply (no Salesforce write needed).",
            ],
        )
    if action == "create_service_contract":
        return (
            {
                "customer_name": ex.get("customer_name"),
                "contract_term_years": ex.get("contract_term_years") or ex.get("term_years"),
                "annual_value": ex.get("annual_value") or ex.get("total"),
                "currency": ex.get("currency"),
                "coverage_summary": ex.get("coverage_summary"),
            },
            ["Salesforce Service Contract draft", "Finance review queue", "Customer email reply"],
            [
                "Verify the contract term and the annual value against the customer's quote.",
                "Click Approve to create the draft contract and route it for finance approval.",
            ],
        )
    if action == "trade_change_order":
        return (
            {
                "source_case_id": ex.get("source_case_id"),
                "change_summary": ex.get("change_summary") or (ex.get("instruction") or "")[:280],
                "po_reference": ex.get("po_number"),
            },
            ["Salesforce Case clone", "Salesforce Order (Change Order)", "Customer email reply"],
            [
                "Confirm the change is in-scope versus the original order.",
                "Click Approve to clone the source case and open the change-order workflow.",
            ],
        )
    return ({}, [], [])


def _apply(
    db: Session,
    *,
    action: str,
    extracted: dict,
    customer_id: int | None,
    salesforce_account_id: str | None = None,
    intent: str = "",
    order_status: str = "Activated",
) -> dict:
    if action == "create_order_acknowledgment":
        result: dict = {"acknowledged": True, "po_number": extracted.get("po_number")}
        sf_conn = sf_svc.get_active_connection(db)
        if sf_conn and salesforce_account_id:
            try:
                sf_result = sf_orders.create_order_for_account(
                    sf_conn,
                    account_id=salesforce_account_id,
                    extracted=extracted,
                    intent=intent or "po_intake",
                    order_status=order_status,
                )
                result["salesforce"] = sf_result
            except Exception as e:
                log.warning("Salesforce Order create failed: %s", e)
                result["salesforce"] = {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        return result

    if action == "convert_quote_to_order":
        from ..mocks import crm

        quote = crm.find_quote(db, customer_id=customer_id, quote_number=extracted.get("quote_number"))
        if not quote:
            return {"applied": False, "reason": "quote not found"}
        sf_conn = sf_svc.get_active_connection(db)
        if not sf_conn:
            return {"applied": False, "reason": "no active Salesforce connection"}
        if not salesforce_account_id:
            return {"applied": False, "reason": "no Salesforce account match for write"}
        try:
            sf_result = sf_orders.convert_quote_to_sf_order(
                sf_conn,
                db=db,
                account_id=salesforce_account_id,
                quote_id=quote.id,
                intent=intent or "convert_quote_to_order",
                order_status=order_status,
            )
        except Exception as e:
            log.warning("convert_quote_to_sf_order failed: %s", e)
            return {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        if not sf_result.get("applied"):
            return sf_result
        return {
            "applied": True,
            "order_number": sf_result.get("salesforce_order_number"),
            "salesforce": sf_result,
            "source_quote_number": quote.quote_number,
        }

    if action == "release_hold":
        # The buyer's email frequently cites their own PO number rather than
        # the Keysight OrderNumber. _find_order_by_number already searches by
        # either, so fall back to customer_po / po_number when the extractor
        # did not populate order_number. Without this fallback the hold
        # release would bail with "missing order_number" even when the PO
        # was clearly identified in the email.
        order_ref = (
            extracted.get("order_number")
            or extracted.get("sales_order_number")
            or extracted.get("customer_po")
            or extracted.get("po_number")
        )
        if not order_ref:
            return {"applied": False, "reason": "missing order_number"}
        sf_conn = sf_svc.get_active_connection(db)
        if not sf_conn:
            return {"applied": False, "reason": "no active Salesforce connection"}
        try:
            sf_result = sf_orders.release_hold_in_sf(sf_conn, order_number=order_ref)
        except Exception as e:
            log.warning("release_hold_in_sf failed: %s", e)
            return {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        if not sf_result.get("applied"):
            return sf_result
        return {
            "applied": True,
            "order_number": sf_result.get("order_number") or order_ref,
            "po_number": sf_result.get("po_number"),
            "previous_status": sf_result.get("previous_status"),
            "new_status": sf_result.get("new_status"),
            "hold_marker_cleared": sf_result.get("hold_marker_cleared"),
            "salesforce": sf_result,
        }

    if action == "reschedule_order":
        order_num = extracted.get("order_number")
        new_date = extracted.get("new_ship_date")
        # Fall back to the customer's most recent SQLite Order number if none cited;
        # the SF helper itself looks up by OrderNumber/PoNumber.
        if not order_num and customer_id:
            o = (
                db.query(Order)
                .filter(Order.customer_id == customer_id)
                .order_by(Order.created_at.desc())
                .first()
            )
            if o:
                order_num = o.order_number
        if not order_num:
            return {"applied": False, "reason": "no order to reschedule"}
        new_dt = _parse_date(new_date) or datetime.now(timezone.utc) + timedelta(days=14)
        sf_conn = sf_svc.get_active_connection(db)
        if not sf_conn:
            return {"applied": False, "reason": "no active Salesforce connection"}
        try:
            sf_result = sf_orders.reschedule_sf_order(
                sf_conn, order_number=order_num, new_ship_date=new_dt,
            )
        except Exception as e:
            log.warning("reschedule_sf_order failed: %s", e)
            return {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        if not sf_result.get("applied"):
            return sf_result
        return {
            "applied": True,
            "order_number": sf_result.get("order_number") or order_num,
            "new_ship_date": sf_result.get("new_ship_date"),
            "field_updated": sf_result.get("field_updated"),
            "salesforce": sf_result,
        }

    if action == "create_work_order":
        if not customer_id:
            return {"applied": False, "reason": "no customer_id"}
        cust = db.get(Customer, customer_id)
        region = cust.region if cust else "AMS"
        customer_code = cust.code if cust else None
        service_type = extracted.get("service_type") or "calibration"
        assets = extracted.get("assets") or []
        if not isinstance(assets, list):
            assets = []
        if not assets:
            assets = [{"asset_serial": extracted.get("asset_serial") or "TBD", "sku": None}]
        sf_conn = sf_svc.get_active_connection(db)
        if not sf_conn:
            return {"applied": False, "reason": "no active Salesforce connection"}
        if not salesforce_account_id:
            return {"applied": False, "reason": "no Salesforce account match for write"}
        created: list[dict] = []
        skipped: list[dict] = []
        feature_disabled = False
        for a in assets:
            try:
                sf_result = sf_wos.create_sf_work_order(
                    sf_conn,
                    account_id=salesforce_account_id,
                    customer_code=customer_code,
                    asset_serial=a.get("asset_serial") or "TBD",
                    asset_sku=a.get("sku"),
                    service_type=service_type,
                    region=region,
                )
            except Exception as e:
                log.warning("create_sf_work_order failed: %s", e)
                skipped.append({"asset_serial": a.get("asset_serial"), "reason": f"{type(e).__name__}: {e}"[:200]})
                continue
            if sf_result.get("applied"):
                created.append({
                    "wo_number": sf_result.get("wo_number"),
                    "asset_serial": sf_result.get("asset_serial"),
                    "type": sf_result.get("type"),
                    "salesforce_workorder_id": sf_result.get("salesforce_workorder_id"),
                })
            else:
                if sf_result.get("reason") == "feature_not_enabled_in_org":
                    feature_disabled = True
                skipped.append({
                    "asset_serial": a.get("asset_serial"),
                    "reason": sf_result.get("reason"),
                })
        if not created and feature_disabled:
            return {
                "applied": False,
                "reason": "feature_not_enabled_in_org",
                "feature": "FieldServiceLightning",
                "skipped": skipped,
            }
        return {
            "applied": bool(created),
            "wo_count": len(created),
            "work_orders": created,
            "skipped": skipped,
            "multi_asset": len(created) > 1,
        }

    if action == "update_work_order":
        wo_num = extracted.get("work_order_number")
        # If the email didn't cite a WO number, fall back to the most recent
        # local WorkOrder row for this customer (mocked-data path still seeds these).
        if not wo_num and customer_id:
            row = (
                db.query(WorkOrder)
                .filter(WorkOrder.customer_id == customer_id)
                .filter(WorkOrder.status != "closed")
                .order_by(WorkOrder.id.desc())
                .first()
            )
            wo_num = row.wo_number if row else None
        if not wo_num:
            return {"applied": False, "reason": "no work_order_number"}
        sf_conn = sf_svc.get_active_connection(db)
        if not sf_conn:
            return {"applied": False, "reason": "no active Salesforce connection"}
        try:
            sf_result = sf_wos.update_sf_work_order(
                sf_conn,
                wo_number=wo_num,
                add_note=extracted.get("add_note") or "",
                add_task=extracted.get("add_task") or "",
            )
        except Exception as e:
            log.warning("update_sf_work_order failed: %s", e)
            return {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        if not sf_result.get("applied"):
            return sf_result
        return {
            "applied": True,
            "wo_number": sf_result.get("wo_number") or wo_num,
            "added_note": sf_result.get("added_note"),
            "added_task": sf_result.get("added_task"),
            "added_assets": len(extracted.get("add_assets") or []),
            "salesforce": sf_result,
        }

    if action == "report_wo_status":
        sf_conn = sf_svc.get_active_connection(db)
        if sf_conn and salesforce_account_id:
            try:
                wos = sf_wos.list_open_sf_work_orders(sf_conn, account_id=salesforce_account_id)
                return {"applied": True, "work_orders": wos, "_source": "salesforce"}
            except Exception as e:
                log.warning("list_open_sf_work_orders failed: %s", e)
                # Fall through to local lookup; status reply is always sendable.
        # Local fallback: pull open WOs for this customer from the local DB so
        # the L4 happy path (auto-reply with WO status) still completes when
        # no SF connection is wired in for the demo. Reply-only actions never
        # block on system-of-record availability.
        local_wos = []
        if customer_id:
            try:
                local_wos = [
                    {
                        "wo_number": w.wo_number,
                        "status": w.status,
                        "type": getattr(w, "type", None) or getattr(w, "work_order_type", None),
                        "team": getattr(w, "owner_team", None) or getattr(w, "team", None),
                        "scheduled_date": w.scheduled_date.isoformat() if getattr(w, "scheduled_date", None) else None,
                    }
                    for w in db.query(WorkOrder).filter_by(customer_id=customer_id).order_by(WorkOrder.id.desc()).limit(5).all()
                ]
            except Exception:
                local_wos = []
        return {
            "applied": True,
            "work_orders": local_wos,
            "_source": "local_db_fallback" if local_wos else "no_record",
            "note": "Reply-only action; no Salesforce write needed.",
        }

    if action == "apply_change_order":
        order_num = extracted.get("order_number")
        if not order_num:
            return {"applied": False, "reason": "missing order_number"}
        line_changes = extracted.get("line_changes") or []
        if not line_changes:
            return {"applied": False, "reason": "no line_changes to apply"}
        sf_conn = sf_svc.get_active_connection(db)
        if not sf_conn:
            return {"applied": False, "reason": "no active Salesforce connection"}
        try:
            sf_result = sf_orders.apply_change_order_in_sf(
                sf_conn, order_number=order_num, line_changes=line_changes,
            )
        except Exception as e:
            log.warning("apply_change_order_in_sf failed: %s", e)
            return {"applied": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        if not sf_result.get("applied"):
            return sf_result
        return {
            "applied": True,
            "order_number": sf_result.get("order_number") or order_num,
            "changes_applied": sf_result.get("changes_applied"),
            "changes": sf_result.get("changes"),
            "failures": sf_result.get("failures"),
            "salesforce": sf_result,
        }

    if action == "draft_service_contract_quote":
        skus = extracted.get("included_skus") or []
        return {
            "applied": True,
            "drafted": True,
            "contract_type": extracted.get("contract_type"),
            "term_months": extracted.get("term_months"),
            "asset_count": len(extracted.get("asset_serials") or []) or extracted.get("asset_count_estimate"),
            "included_skus": skus,
        }

    if action == "draft_reply":
        return {"applied": True, "drafted": True}

    if action == "route_to_csr":
        return {"applied": True, "routed": "csr"}

    return {"applied": False, "reason": f"no handler for {action}"}


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
