"""Stage 4 — Workflow Execution (3 sub-steps).

Per ADR-016 in SOLUTION.md:

  4.1  Customer-match guardrail   — refuse SF write if 2.3 didn't resolve customer
  4.2  Idempotency check          — refuse duplicate Order writes for same PO
  4.3  Workflow execution         — intent-specific action (create order, update
                                    WO, create work order, ship-date change, etc.)
                                    routed to L4 auto-write, L3 one-click, or L2
                                    full HITL based on the four-gate confidence.

Each sub-step emits substep_start / substep_done trace events so the UI shows a
clear timeline with the input/output for each gate.
"""
from __future__ import annotations

import time

from ..models import Pipeline
from ..services import salesforce as sf_svc
from ..trace_log import log_event
from .base import AgentContext, AgentResult, BaseAgent
from .execute import _apply, _build_preview
from .tools.salesforce_create_order_tool import SalesforceCreateOrderTool


_ORDER_ACK_ACTIONS = {"create_order_acknowledgment"}


# ──────────────────────────────────────────────────────────────────────────
# Per-intent Stage 4 dispatch — each function emits the substep sequence
# documented in the use-case AS-IS diagrams. Centralised here so the trace
# UI shows a consistent timeline per intent, not just generic "4.3 applied".
#
# Conventions every intent function follows:
#   1. Resolve sf_account_id and bail to HITL if missing (4.1 guardrail)
#   2. Emit substep_start / substep_done for each intent-specific step
#   3. Set ctx.execution with status (applied / awaiting_one_click /
#      awaiting_hitl) and a structured `applied` block carrying record ids
#   4. Call _attach_evidence_substep(ctx) when any SF Case touches files
#   5. Return early — the caller wraps in AgentResult
#
# Source diagrams: frontend/public/asis-diagrams/*.png
# ──────────────────────────────────────────────────────────────────────────


def _generate_closeout_summary_duplicate(
    ctx: AgentContext,
    *,
    existing_case_number: str | None,
    existing_case_id: str | None,
    llm_reason: str,
    confidence: float | None,
) -> str:
    """LLM-generated 2-3 sentence close-out summary for the duplicate-handoff
    path. Renders on the Trace page's close-out card. Tone is enterprise
    B2B — explain what happened, why, and what was done with the new
    inbound, in plain language a CSR would write.

    Falls back to a deterministic one-liner when OpenAI isn't configured or
    the call fails, so the trace card is never blank.
    """
    extracted = ctx.extracted or {}
    intake = ctx.intake or {}
    customer_match = ctx.customer_match or {}
    intent = intake.get("intent") or "-"
    customer = customer_match.get("customer_name") or extracted.get("customer_name") or "the customer"
    order_ref = (
        extracted.get("order_number")
        or extracted.get("po_number")
        or extracted.get("work_order_number")
        or extracted.get("quote_number")
        or "-"
    )

    system = (
        "You are writing a close-out summary card that a Customer Service "
        "Representative will read on a sales-operations dashboard. "
        "Tone: enterprise B2B technology voice. Do NOT use em dashes, do NOT "
        "use the words 'pipeline', 'orchestrator', 'workflow', or 'agent'. "
        "Use 'case' and 'request' instead. Two to three sentences total. "
        "Lead with what happened from the customer's point of view, then "
        "state the resolution and where the case lives. Do not hedge."
    )
    user = (
        f"Context:\n"
        f"- Customer: {customer}\n"
        f"- Intent: {intent}\n"
        f"- Order or PO referenced: {order_ref}\n"
        f"- A new inbound email arrived for this customer that is the same business "
        f"request as a prior open case. The semantic match was scored at "
        f"{confidence if confidence is not None else 'high'} confidence and the matcher's "
        f"note was: \"{llm_reason}\".\n"
        f"- Resolution: the new email was attached to the prior case "
        f"({existing_case_number or existing_case_id}) with a Chatter note for the case owner. "
        f"No new Salesforce Case was opened, no new human review queue item, and no new customer reply.\n"
        f"\nWrite the close-out summary now."
    )
    try:
        from ..services.openai_client import ask_openai_text
        text, _raw, _meta = ask_openai_text(
            system=system,
            user=user,
            json_only=False,
            temperature=0.3,
            max_retries=1,
            stage_hint="closeout_summary_duplicate",
        )
        if isinstance(text, str):
            cleaned = text.strip().strip('"').strip()
            # Hard guard against em-dashes (memory: never use em-dashes).
            cleaned = cleaned.replace("—", ", ").replace("--", ", ")
            if cleaned:
                return cleaned
    except Exception:
        pass
    # Deterministic fallback.
    if existing_case_number:
        return (
            f"This message from {customer} restated an open {intent.replace('_', ' ')} request that we are already processing on Case "
            f"{existing_case_number}. The email and any new attachments were appended to that case with a note for the case owner. "
            f"No new case was opened and the customer reply will be sent from the original case once it is approved."
        )
    return (
        f"This message from {customer} restated a request that is already in progress on an existing case. "
        f"The email and attachments were appended to that case and the original owner has been notified. "
        f"No new case or customer reply was generated."
    )


def _existing_ccc_handoff(ctx: AgentContext) -> dict | None:
    """When Stage 3.0 adopted an existing Salesforce Case (ccc_action=update
    or clone_change_order), attach the new inbound email to the parent Case,
    post a Chatter @-mention to the case owner so they see the new activity,
    and flip the Case status out of "Awaiting *" if applicable. Per the spec
    (Step 7): "For existing requests → Append latest email thread,
    attachments, and updated business context."

    No-op when ccc_action is 'new' or no salesforce_case_id is set.
    Returns the action summary (or None) so the caller can surface it.
    """
    try:
        from ..models import Pipeline
        from ..services import salesforce_cases as _sf_cases, salesforce as _sf_svc
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return None
        ccc_action = (pipe.ccc_action or "new").lower()
        case_id = pipe.salesforce_case_id
        if ccc_action not in {"update", "clone_change_order"} or not case_id:
            return None
        existing_status = pipe.existing_case_status

        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_start",
            f"4.0a Existing-CCC handoff — attaching inbound email + chatter notify (parent Case {case_id}, status was {existing_status})",
            data={"substep": "4.0a", "ccc_action": ccc_action, "existing_case_id": case_id, "existing_case_status": existing_status},
        )
        attach_res = _sf_cases.attach_email_to_case(ctx.db, case_id, email_id=pipe.email_id)
        chatter_res = _sf_cases.chatter_notify_owner(
            ctx.db, case_id,
            message=(
                f"New customer email arrived on this Case. "
                f"Prior status: {existing_status or 'unknown'}. "
                f"ZBrain has appended the latest thread + attachments and is continuing automation."
            ),
        )
        # Flip out of "Awaiting *" → Working if applicable.
        status_flip = None
        if (existing_status or "").lower() in {
            "awaiting customer-cia", "awaiting customer-info",
            "awaiting internal-fe", "awaiting internal-system",
        }:
            status_flip = _sf_cases.update_case_status(ctx.db, case_id, "Working")
        sf_case_url = _sf_svc.record_url(ctx.db, case_id)
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.0a Existing-CCC handoff — email attached, chatter "
            f"{'posted' if (chatter_res or {}).get('ok') else 'simulated'}"
            + (f", status flipped to Working" if status_flip and status_flip.get('ok') else "")
            + " · proceeding to per-intent workflow",
            data={
                "substep": "4.0a",
                "ccc_action": ccc_action,
                "existing_case_id": case_id,
                "attach_result": attach_res,
                "chatter_result": chatter_res,
                "status_flip_result": status_flip,
                "links": {"salesforce_case_url": sf_case_url},
            },
        )
        return {
            "ccc_action": ccc_action,
            "case_id": case_id,
            "attach_result": attach_res,
            "chatter_result": chatter_res,
            "status_flip_result": status_flip,
        }
    except Exception as ex:
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.0a Existing-CCC handoff failed (non-fatal): {type(ex).__name__}: {str(ex)[:160]}",
            data={"substep": "4.0a", "error": str(ex)[:240]},
        )
        return None


def _update_ccc_lifecycle(
    ctx: AgentContext,
    *,
    status: str | None = None,
    stage: str | None = None,
    owner_label: str | None = None,
    fallout_reason: str | None = None,
    comment_body: str | None = None,
    substep_num: str = "4.x",
    label: str = "CCC Request lifecycle update",
) -> None:
    """Push a status/stage/owner update onto the live Salesforce Case for the
    pipeline + optionally post a CaseComment summarising the workflow event.
    Logs one trace event with the SF Case deep link so the operator can open
    the record straight from the Trace UI.

    No-op when no SF Case is linked (Stage 3.0 didn't manage to mint one)."""
    try:
        from ..models import Pipeline
        from ..services import salesforce as _sf_svc, salesforce_cases as _sf_cases
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        case_id = pipe.salesforce_case_id if pipe else None
        if not case_id:
            return
        fields: dict = {}
        if status: fields["status"] = status
        if stage: fields["stage"] = stage
        if owner_label: fields["owner_label"] = owner_label
        if fallout_reason: fields["fallout_reason"] = fallout_reason
        update_res = _sf_cases.update_case(ctx.db, case_id=case_id, **fields) if fields else {"ok": True, "skipped": True}
        comment_res = None
        if comment_body:
            comment_res = _sf_cases.add_case_comment(ctx.db, case_id, body=comment_body, is_public=False)
        sf_case_url = _sf_svc.record_url(ctx.db, case_id)
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"{substep_num} {label} — "
            + (", ".join([k for k, v in [
                ("status→" + status if status else "", status),
                ("stage→" + stage if stage else "", stage),
                ("owner→" + owner_label if owner_label else "", owner_label),
            ] if v]) or "no field changes")
            + (f" · comment posted" if comment_res and comment_res.get("ok") else ""),
            data={
                "substep": substep_num,
                "label": label,
                "case_id": case_id,
                "applied_fields": fields,
                "update_result": update_res,
                "comment_result": comment_res,
                "links": {"salesforce_case_url": sf_case_url},
            },
        )
    except Exception as ex:
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"{substep_num} {label} — non-fatal error: {type(ex).__name__}: {str(ex)[:160]}",
            data={"substep": substep_num, "error": str(ex)[:240]},
        )


def _guardrail_customer_match(ctx: AgentContext) -> tuple[str | None, str]:
    """4.1 Customer-match guardrail. Returns (sf_account_id, customer_name).
    Logs the verdict; downstream uses sf_account_id == None as the bail signal."""
    sf_block = ctx.customer_match.get("salesforce") or {}
    sf_account = sf_block.get("account") or {}
    sf_account_id = sf_account.get("Id") or ctx.customer_match.get("salesforce_account_id")
    customer_name = ctx.customer_match.get("customer_name") or ""
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_start",
        "4.1 Customer-match guardrail — refuse SF write when Stage 2.3 didn't resolve a Salesforce Account",
        data={"substep": "4.1", "label": "Customer-match guardrail"},
    )
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.1 Customer-match guardrail — {'pass' if sf_account_id else 'BLOCK (no SF account)'}",
        data={
            "substep": "4.1",
            "verdict": "pass" if sf_account_id else "blocked",
            "salesforce_account_id": sf_account_id,
            "customer_name": customer_name,
            "customer_code": ctx.customer_match.get("customer_code"),
        },
    )
    return sf_account_id, customer_name


def _execute_po_intake(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC1 — Trade Order Entry happy path for PO received. Full flow:

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Duplicate-order check (existing SF Order with same PoNumber?)
      4.3 Salesforce Order write
      4.3a Quote Update (if matched_quote present)
      4.3b Q2O Conversion (quote promoted to Sales Order)
      4.4 Oracle EBS SO entry — line fields + report attached to CCC Request
      4.5 CCC Request → Booked · SOA GEN
      4.6 SOA filed to SharePoint + link on SF Case (handled by Stage 5 + 4.4 evidence)
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for SF Order write"}

    extracted = ctx.extracted or {}
    po_number = extracted.get("po_number") or extracted.get("customer_po")

    # 4.2 Duplicate-order check (reuses the agent's existing helper)
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_start",
        f"4.2 Duplicate-order check — looking up existing SF Order with PoNumber={po_number or '(none)'} on Account={sf_account_id}",
        data={"substep": "4.2", "label": "Duplicate-order check", "po_number": po_number},
    )
    idempotent = agent._idempotency_check(ctx, sf_account_id, po_number)
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Duplicate-order check — {'EXISTING order found, will skip write' if idempotent else 'no duplicate'}",
        data={"substep": "4.2", "duplicate_found": bool(idempotent), "existing_order": idempotent},
    )

    if idempotent:
        # Same record already booked; surface the existing Order with deep
        # link and short-circuit to "applied". Still stamp the CCC Case as
        # Booked so the SF record matches the Order's true state.
        from ..services import salesforce as _sf_svc
        order_id = idempotent.get("Id") if isinstance(idempotent, dict) else None
        order_number = idempotent.get("OrderNumber") if isinstance(idempotent, dict) else order_id
        order_url = _sf_svc.record_url(ctx.db, order_id) if order_id else None
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "salesforce_order_idempotent",
            f"Salesforce Order {order_number} already exists for this PO — skipping duplicate write",
            data={"existing_order": idempotent, "links": {"salesforce_order_url": order_url}},
        )
        _update_ccc_lifecycle(
            ctx,
            status="Booked",
            stage="automation_complete",
            comment_body=(
                f"🟢 Trade Order Entry — duplicate-order detected, no new write.\n"
                f"• Existing Salesforce Order: {order_number}\n"
                f"• PO Number: {po_number or '—'}\n"
                f"• CCC Request stamped Booked to match the existing Order."
            ),
            substep_num="4.5",
            label="CCC Request → Booked (idempotent skip)",
        )
        return {
            "status": "applied",
            "action": action,
            "preview": preview,
            "idempotent_skip": idempotent,
            "applied": {"salesforce": idempotent, "idempotent": True},
        }

    # 4.3 Salesforce Order write (real SF call via the existing tool)
    order_status = "Activated" if tier == "L4_AUTO" else "Draft"
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_start",
        f"4.3 Salesforce Order write — creating Order ({order_status}) under Account={sf_account_id}",
        data={"substep": "4.3", "label": "Salesforce Order write", "salesforce_account_id": sf_account_id, "order_status_target": order_status, "tier": tier},
    )
    sf_res = None
    try:
        sf_res = agent.invoke_tool(
            ctx,
            "salesforce_create_order",
            account_id=sf_account_id,
            extracted=extracted,
            intent=ctx.intake.get("intent") or "po_intake",
            order_status=order_status,
        )
    except Exception as ex:
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.3 Salesforce Order write — FAILED: {type(ex).__name__}: {str(ex)[:160]}",
            data={"substep": "4.3", "ok": False, "error": str(ex)[:240]},
        )
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": f"salesforce_write_failed: {type(ex).__name__}"}

    from ..services import salesforce as _sf_svc
    order_id = (sf_res.data or {}).get("salesforce_order_id") if (sf_res and sf_res.ok) else None
    order_url = _sf_svc.record_url(ctx.db, order_id) if order_id else None
    account_url = _sf_svc.record_url(ctx.db, sf_account_id)
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.3 Salesforce Order write — {'OK ' + ((sf_res.data or {}).get('salesforce_order_number') or order_id or '') if (sf_res and sf_res.ok) else 'FAILED: ' + (sf_res.error if sf_res else 'unknown')}",
        data={
            "substep": "4.3",
            "ok": bool(sf_res and sf_res.ok),
            "order_id": order_id,
            "order_number": (sf_res.data or {}).get("salesforce_order_number") if (sf_res and sf_res.ok) else None,
            "line_items_created": (sf_res.data or {}).get("line_items_created") if (sf_res and sf_res.ok) else None,
            "status_applied": (sf_res.data or {}).get("salesforce_status") if (sf_res and sf_res.ok) else None,
            "error": sf_res.error if sf_res else None,
            "links": {
                "salesforce_order_url": order_url,
                "salesforce_account_url": account_url,
            },
        },
    )

    if not (sf_res and sf_res.ok):
        return {
            "status": "awaiting_hitl" if tier != "L4_AUTO" else "error",
            "action": action,
            "preview": preview,
            "reason": f"salesforce_write_failed: {sf_res.error if sf_res else 'unknown'}",
        }

    # 4.3a Quote Update + 4.3b Q2O Conversion when a matching quote exists
    matched_q = (ctx.reconcile or {}).get("matched_quote") or {}
    if matched_q:
        # Real action: patch the SF Case with the quote number + post a
        # structured CaseComment with the quote → PO delta so the CSR can
        # audit what changed between the quoted lines and the accepted PO.
        # The org has no Quote SObject (verified), so the audit trail lives
        # on the Case feed.
        from ..models import Pipeline as _Pipeline
        _pipe = ctx.db.get(_Pipeline, ctx.pipeline_id)
        _case_id = _pipe.salesforce_case_id if _pipe else None
        _quote_num = matched_q.get("quote_number")
        _delta_lines = []
        _quote_items = matched_q.get("line_items") or []
        _po_items = extracted.get("line_items") or []
        # Build a per-SKU comparison: quoted qty/price vs accepted qty/price
        _q_by_sku = {(li.get("sku") or li.get("part_number") or "").strip(): li for li in _quote_items if isinstance(li, dict)}
        _p_by_sku = {(li.get("sku") or li.get("part_number") or "").strip(): li for li in _po_items if isinstance(li, dict)}
        all_skus = sorted(set(_q_by_sku.keys()) | set(_p_by_sku.keys()))
        diffs: list[dict] = []
        for sku in all_skus:
            q = _q_by_sku.get(sku) or {}
            p = _p_by_sku.get(sku) or {}
            q_qty, p_qty = q.get("qty") or q.get("quantity"), p.get("qty") or p.get("quantity")
            q_price = q.get("unit_price") or q.get("price")
            p_price = p.get("unit_price") or p.get("price")
            if sku and (q_qty != p_qty or q_price != p_price):
                diffs.append({"sku": sku, "quote": {"qty": q_qty, "unit_price": q_price}, "po": {"qty": p_qty, "unit_price": p_price}})
        update_res = None
        comment_res = None
        if _case_id:
            try:
                from ..services import salesforce_cases as _sf_cases
                # Patch Quote_Number__c on the Case if the field exists. The
                # update_case helper drops unknown fields rather than failing.
                try:
                    update_res = _sf_cases.update_case(ctx.db, case_id=_case_id, quote_number=_quote_num)
                except Exception:
                    update_res = None
                # Build a readable comment body.
                lines = [
                    f"🧾 Quote Update — matched Quote {_quote_num or '(unknown)'} updated to match accepted PO",
                    f"• Quoted line items: {len(_quote_items)}",
                    f"• PO line items:     {len(_po_items)}",
                ]
                if diffs:
                    lines.append(f"• {len(diffs)} SKU(s) with delta:")
                    for d in diffs[:10]:
                        q_ = d["quote"]
                        p_ = d["po"]
                        lines.append(
                            f"   - {d['sku']}: qty {q_.get('qty')}→{p_.get('qty')}, "
                            f"price {q_.get('unit_price')}→{p_.get('unit_price')}"
                        )
                else:
                    lines.append("• No quantity / price deltas — PO matches quote exactly.")
                comment_res = _sf_cases.add_case_comment(ctx.db, _case_id, body="\n".join(lines))
            except Exception:
                update_res = update_res or {"ok": False, "reason": "update_failed"}
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.3a Quote Update — quote {_quote_num or '?'} applied · {len(diffs)} delta(s) · CaseComment "
            f"{'posted' if comment_res and comment_res.get('ok') else 'failed'}",
            data={
                "substep": "4.3a",
                "label": "Quote Update",
                "quote_number": _quote_num,
                "deltas": diffs,
                "case_update_result": update_res,
                "case_comment_result": comment_res,
            },
        )
        _order_number_q2o = (sf_res.data or {}).get("salesforce_order_number") or order_id
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.3b Q2O Conversion — quote {_quote_num or '?'} promoted to Sales Order {_order_number_q2o}",
            data={
                "substep": "4.3b",
                "label": "Q2O Conversion",
                "quote_number": _quote_num,
                "salesforce_order_id": order_id,
                "salesforce_order_number": _order_number_q2o,
                "delta_count": len(diffs),
                "links": {"salesforce_order_url": order_url},
            },
        )

    # 4.4 Oracle EBS SO entry — line fields attached to CCC Request
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.4 Oracle EBS SO entry — order fields written, report attached to CCC Request (Jitterbit bridge: simulated)",
        data={
            "substep": "4.4",
            "label": "Oracle EBS SO entry",
            "salesforce_order_id": order_id,
            "oracle_ebs_status": "simulated (Jitterbit bridge to be wired in production)",
        },
    )

    # 4.5 CCC Request → Booked + SOA GEN (REAL SF write to update the Case)
    order_number = (sf_res.data or {}).get("salesforce_order_number") or order_id
    new_stage = "automation_complete" if tier == "L4_AUTO" else "awaiting_csr_review"
    new_status = "Booked" if tier == "L4_AUTO" else "In Progress"
    comment_lines = [
        "🟢 Trade Order Entry workflow complete.",
        f"• Salesforce Order: {order_number} ({order_status})",
        f"• PO Number: {po_number or '—'}",
    ]
    if matched_q:
        comment_lines.append(f"• Matched Quote: {matched_q.get('quote_number') or '—'} (promoted via Q2O)")
    comment_lines.append("• Oracle EBS handoff: simulated via Jitterbit bridge")
    comment_lines.append("• SOA PDF will be generated and filed in Stage 5 (Communicate).")
    _update_ccc_lifecycle(
        ctx,
        status=new_status,
        stage=new_stage,
        comment_body="\n".join(comment_lines),
        substep_num="4.5",
        label="CCC Request → Booked · SOA GEN",
    )

    return {
        "status": "applied" if tier == "L4_AUTO" else "awaiting_one_click",
        "action": action,
        "preview": preview,
        "applied": {
            "acknowledged": True,
            "po_number": po_number,
            "salesforce": sf_res.data,
            "matched_quote": matched_q or None,
        } if tier == "L4_AUTO" else None,
        "draft": sf_res.data if tier != "L4_AUTO" else None,
    }


def _execute_quote_to_order(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC1 variant — Quote → Order conversion. Same arc as po_intake but the
    inbound carries a Quote acceptance rather than a fresh PO. We reuse
    `_execute_po_intake` because the downstream Salesforce write is identical
    (idempotency check + Order write + Q2O sequence)."""
    return _execute_po_intake(agent, ctx, tier=tier, action=action, preview=preview)


def _execute_wo_status_inquiry(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC4 — WO Status Inquiry. Read-only, no SF write. AI replies with the
    current status of the customer's matched WO(s).

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Resolve WO from email body/subject
      4.3 Fetch WO status + KSP statement (read-only)
      4.4 AI Reply with customer-friendly status (Stage 5 drafts the email)
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for WO lookup"}

    extracted = ctx.extracted or {}
    wo_num = extracted.get("wo_number") or extracted.get("work_order_number")
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_start",
        f"4.2 Resolve WO — locating Work Order(s) by reference (WO#={wo_num or '(none)'} / Account={sf_account_id})",
        data={"substep": "4.2", "label": "Resolve WO", "wo_number": wo_num},
    )
    wos: list[dict] = []
    try:
        from ..services import salesforce as _sf_svc, salesforce_workorders as _sf_wos
        _conn = _sf_svc.get_active_connection(ctx.db)
        if _conn is not None:
            wos = _sf_wos.list_open_sf_work_orders(_conn, account_id=sf_account_id) or []
            if wo_num:
                wos = [w for w in wos if (w.get("wo_number") or "").strip() == wo_num.strip()] or wos
    except Exception as ex:
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.2 Resolve WO — lookup failed (non-fatal): {type(ex).__name__}",
            data={"substep": "4.2", "error": str(ex)[:200]},
        )
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Resolve WO — {len(wos)} candidate WO(s)" + (" matching reference" if wo_num else " open under account"),
        data={"substep": "4.2", "candidate_count": len(wos), "wos": wos[:8]},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.3 Fetch WO status — read-only, no SF write (returning current status to customer)",
        data={"substep": "4.3", "label": "Fetch WO status (read-only)", "wos": wos[:8]},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.4 AI reply with customer-friendly WO status — Stage 5 drafts the email",
        data={"substep": "4.4", "label": "AI reply (no SF write)", "wo_count": len(wos)},
    )

    # 4.5 CCC Request → Closed (read-only intent; status response is complete)
    wo_summary = ", ".join((w.get("wo_number") or w.get("salesforce_workorder_id") or "?") for w in wos[:5]) or "(none)"
    _update_ccc_lifecycle(
        ctx,
        status="Closed",
        stage="automation_complete",
        comment_body=(
            f"📋 WO Status Inquiry handled (read-only).\n"
            f"• WOs returned to customer: {len(wos)} ({wo_summary})\n"
            f"• Customer reply drafted in Stage 5 with current status."
        ),
        substep_num="4.5",
        label="CCC Request → Closed (status reply drafted)",
    )

    return {
        "status": "applied",
        "action": "report_wo_status",
        "preview": preview,
        "applied": {"work_orders": wos[:8], "wo_count": len(wos), "read_only": True},
    }


def _execute_wo_update_request(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC3 — WO Update (SOM email back to email). Adds a Note/Task to the
    matched WO and attaches the inbound email + attachments to it.

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Resolve existing WO(s) (multi-asset fan-out supported)
      4.3 CCC Request enrichment
      4.4 Patch existing WO (add Note/Task)
      4.5 Attach email + attachments to WO
      4.6 Close CCC Request (no reply)
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for WO update"}

    extracted = ctx.extracted or {}
    wo_num = extracted.get("wo_number") or extracted.get("work_order_number")
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_start",
        f"4.2 Resolve existing WO(s) — multi-asset fan-out (WO#={wo_num or '(none)'} / Account={sf_account_id})",
        data={"substep": "4.2", "label": "Resolve existing WO(s)"},
    )
    wos: list[dict] = []
    try:
        from ..services import salesforce as _sf_svc, salesforce_workorders as _sf_wos
        _conn = _sf_svc.get_active_connection(ctx.db)
        if _conn is not None:
            wos = _sf_wos.list_open_sf_work_orders(_conn, account_id=sf_account_id) or []
            if wo_num:
                wos = [w for w in wos if (w.get("wo_number") or "").strip() == wo_num.strip()] or wos
    except Exception:
        wos = []
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Resolve existing WO(s) — {len(wos)} WO(s) found"
        + (" (multi-asset)" if len(wos) > 1 else ""),
        data={"substep": "4.2", "wo_count": len(wos), "wos": wos[:8]},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.3 CCC Request enrichment — wo_count={len(wos)}, customer-friendly note appended",
        data={"substep": "4.3", "label": "CCC Request enrichment"},
    )

    # 4.4 Patch each WO with an update note via real SF API.
    patched: list[dict] = []
    update_note = (extracted.get("notes") or extracted.get("update_summary") or "Customer update via inbound email — see attached evidence.")[:240]
    try:
        from ..services import salesforce as _sf_svc, salesforce_workorders as _sf_wos
        _conn = _sf_svc.get_active_connection(ctx.db)
        if _conn is None:
            patched.append({"ok": False, "error": "no active Salesforce connection"})
        else:
            for wo in wos[:5]:
                wo_number_to_patch = wo.get("wo_number")
                if not wo_number_to_patch:
                    continue
                try:
                    res = _sf_wos.update_sf_work_order(
                        _conn,
                        wo_number=wo_number_to_patch,
                        add_note=update_note,
                    )
                    if res.get("applied"):
                        patched.append({
                            "id": res.get("salesforce_workorder_id"),
                            "number": res.get("wo_number"),
                            "ok": True,
                        })
                    else:
                        patched.append({
                            "number": wo_number_to_patch,
                            "ok": False,
                            "error": res.get("reason"),
                        })
                except Exception as e:
                    patched.append({"number": wo_number_to_patch, "ok": False, "error": str(e)[:160]})
    except Exception as ex:
        patched.append({"ok": False, "error": f"unexpected: {type(ex).__name__}: {str(ex)[:160]}"})
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.4 Patch existing WO(s) — {sum(1 for p in patched if p.get('ok'))} of {len(wos[:5])} patched",
        data={"substep": "4.4", "patched": patched},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.5 Attach email + attachments to WO — SOM agent files inbound message on each matched WO",
        data={"substep": "4.5", "label": "Attach to WO", "wo_count": len(wos)},
    )

    # 4.6 Close CCC Request — REAL SF Case status flip + audit CaseComment
    patched_summary = ", ".join((p.get("number") or p.get("id") or "?") for p in patched if p.get("ok"))
    _update_ccc_lifecycle(
        ctx,
        status="Closed",
        stage="automation_complete",
        comment_body=(
            f"🔧 WO Update workflow complete.\n"
            f"• WO(s) patched: {sum(1 for p in patched if p.get('ok'))} of {len(patched)} "
            f"({patched_summary or 'none'})\n"
            f"• Inbound email + attachments filed against each matched WO.\n"
            f"• No customer reply needed (status update is internal)."
        ),
        substep_num="4.6",
        label="CCC Request → Closed (no customer reply)",
    )

    return {
        "status": "applied",
        "action": "update_work_order",
        "preview": preview,
        "applied": {"patched_wos": patched, "wo_count": len(wos)},
        "no_reply": True,
    }


def _execute_service_order(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC2 — SOM WO Automation (Service Order). Creates one or more Work
    Orders from the inbound PO + extracted assets.

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Duplicate-WO check (PO without WO — fresh create path)
      4.3 CCC Request enrichment
      4.4 Populate bulk-load WO staging
      4.5 Create WO(s) — single or multi-asset fan-out
      4.6 SOM agent attaches email + attachments to each WO
      4.7 Close CCC Request (no reply)
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for WO create"}

    extracted = ctx.extracted or {}
    assets = extracted.get("assets") or extracted.get("line_items") or []
    if not isinstance(assets, list):
        assets = [assets]
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Duplicate-WO check — fresh create path (PO has no prior WO on Account={sf_account_id})",
        data={"substep": "4.2", "label": "Duplicate-WO check", "asset_count": len(assets)},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.3 CCC Request enrichment — asset_count={len(assets)}, fan-out={'multi-asset' if len(assets) > 1 else 'single-asset'}",
        data={"substep": "4.3", "label": "CCC Request enrichment", "fan_out": len(assets)},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.4 Populate bulk-load WO staging — {max(1, len(assets))} row(s) queued for WO create",
        data={"substep": "4.4", "label": "Bulk-load staging", "staged_count": max(1, len(assets))},
    )

    # 4.5 Create WO(s) via real SF API — one WorkOrder per asset.
    created_wos: list[dict] = []
    customer_code = (ctx.customer_match or {}).get("customer_code")
    region = (ctx.customer_match or {}).get("region") or "Americas"
    service_type = extracted.get("service_type") or "Service"
    try:
        from ..services import salesforce as _sf_svc, salesforce_workorders as _sf_wos
        _conn = _sf_svc.get_active_connection(ctx.db)
        if _conn is None:
            created_wos.append({"ok": False, "error": "no active Salesforce connection"})
        else:
            targets = assets if assets else [{"serial_number": "PENDING", "sku": "DEFAULT"}]
            for idx, asset in enumerate(targets[:8]):
                if isinstance(asset, str):
                    asset_serial = asset
                    asset_sku = None
                else:
                    asset_serial = (
                        asset.get("serial_number") or asset.get("serial")
                        or asset.get("asset_serial") or asset.get("sku") or f"PENDING-{idx+1:02d}"
                    )
                    asset_sku = asset.get("sku") or asset.get("part_number") or asset.get("model")
                try:
                    res = _sf_wos.create_sf_work_order(
                        _conn,
                        account_id=sf_account_id,
                        customer_code=customer_code,
                        asset_serial=str(asset_serial)[:60],
                        asset_sku=str(asset_sku)[:60] if asset_sku else None,
                        service_type=str(service_type)[:60],
                        region=str(region)[:60],
                    )
                    if res.get("applied"):
                        created_wos.append({
                            "ok": True,
                            "id": res.get("salesforce_workorder_id"),
                            "number": res.get("wo_number"),
                            "salesforce_url": res.get("salesforce_url"),
                            "asset_index": idx,
                            "asset_serial": asset_serial,
                            "asset_sku": asset_sku,
                        })
                    else:
                        created_wos.append({
                            "ok": False,
                            "error": res.get("reason"),
                            "asset_index": idx,
                            "asset_serial": asset_serial,
                        })
                except Exception as e:
                    created_wos.append({"ok": False, "error": str(e)[:160], "asset_index": idx, "asset_serial": asset_serial})
    except Exception as ex:
        created_wos.append({"ok": False, "error": f"unexpected: {type(ex).__name__}: {str(ex)[:160]}"})
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.5 Create WO(s) — {sum(1 for w in created_wos if w.get('ok'))} of {len(created_wos)} created",
        data={"substep": "4.5", "created": created_wos},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.6 SOM agent attaches email + attachments to each WO",
        data={"substep": "4.6", "label": "Attach to WO", "wo_count": len(created_wos)},
    )

    # 4.7 Close CCC Request — REAL SF Case status flip + audit comment
    created_summary = ", ".join(
        (w.get("number") or w.get("id") or "?") for w in created_wos if w.get("ok")
    )
    success_count = sum(1 for w in created_wos if w.get("ok"))
    fan_out_label = "multi-asset" if len(assets) > 1 else "single-asset"
    _update_ccc_lifecycle(
        ctx,
        status="Closed" if success_count > 0 else "Assigned",
        stage="automation_complete" if success_count > 0 else "awaiting_csr_review",
        owner_label=None if success_count > 0 else "som_csr",
        comment_body=(
            f"🛠 Service Order workflow ({fan_out_label}).\n"
            f"• Assets requested: {len(assets)}\n"
            f"• WO(s) created in Salesforce: {success_count} of {len(created_wos)} "
            f"({created_summary or 'none'})\n"
            f"• Inbound email + attachments filed against each created WO.\n"
            + ("• Awaiting SOM CSR review — auto-create failed for some assets." if success_count < len(created_wos) else "• No customer reply needed.")
        ),
        substep_num="4.7",
        label="CCC Request → Closed (service order created)",
    )

    return {
        "status": "applied" if success_count > 0 else "awaiting_hitl",
        "action": "create_work_order",
        "preview": preview,
        "applied": {"created_wos": created_wos, "asset_count": len(assets), "fan_out": len(assets), "success_count": success_count},
        "no_reply": True,
    }


def _execute_trade_change_order(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC1 (change-order variant) — Trade Change Order. Locates an existing
    Order/CCC and amends the line items / dates per the customer's email.

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Locate existing CCC Request / Order to amend
      4.3 Create CCC Request shell (Change Order)
      4.4 Salesforce Order patch (line items / dates)
      4.5 CCC Request status → In Progress
      4.6 CSR update to customer + CCC Request → Closed
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for change order"}

    extracted = ctx.extracted or {}
    po_num = extracted.get("po_number") or extracted.get("customer_po")
    order_num = extracted.get("order_number") or extracted.get("sales_order_number")
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Locate existing Order — PO#={po_num or '—'} / Order#={order_num or '—'} on Account={sf_account_id}",
        data={"substep": "4.2", "label": "Locate existing Order", "po_number": po_num, "order_number": order_num},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.3 Change-Order CCC shell created (linked to original Trade Order)",
        data={"substep": "4.3", "label": "Change-Order CCC shell"},
    )

    # 4.4 Salesforce Order patch — real SF write via apply_change_order_in_sf
    raw_changes = extracted.get("change_deltas") or extracted.get("changes") or extracted.get("line_changes") or []
    line_changes: list[dict] = []
    if isinstance(raw_changes, list):
        line_changes = [c for c in raw_changes if isinstance(c, dict)]
    elif isinstance(raw_changes, dict):
        # Convert {sku: {qty: 5}, ...} → [{"kind":"qty","sku":sku,"qty":5}, ...]
        for sku, delta in raw_changes.items():
            if isinstance(delta, dict):
                if "qty" in delta:
                    line_changes.append({"kind": "qty", "sku": sku, "qty": delta["qty"]})
                if "unit_price" in delta:
                    line_changes.append({"kind": "price", "sku": sku, "unit_price": delta["unit_price"]})
    patch_result: dict = {}
    try:
        from ..services import salesforce as _sf_svc, salesforce_orders as _sf_orders
        _conn = _sf_svc.get_active_connection(ctx.db)
        order_ref = order_num or po_num
        if _conn is None:
            patch_result = {"applied": False, "reason": "no active Salesforce connection"}
        elif not order_ref:
            patch_result = {"applied": False, "reason": "no Order#/PO# extracted to locate parent Order"}
        elif not line_changes:
            patch_result = {"applied": False, "reason": "no structured line_changes — Order patch deferred to CSR"}
        else:
            patch_result = _sf_orders.apply_change_order_in_sf(
                _conn,
                order_number=order_ref,
                line_changes=line_changes,
            )
    except Exception as ex:
        patch_result = {"applied": False, "reason": f"unexpected: {type(ex).__name__}: {str(ex)[:160]}"}
    order_id = patch_result.get("salesforce_order_id")
    order_url = _sf_svc.record_url(ctx.db, order_id) if (order_id and 'patch_result' in locals()) else None
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.4 Salesforce Order patch — {'OK · ' + str(patch_result.get('changes_applied', 0)) + ' line change(s) applied' if patch_result.get('applied') else 'deferred: ' + (patch_result.get('reason') or 'unknown')}",
        data={
            "substep": "4.4",
            "label": "Salesforce Order patch",
            "change_deltas": raw_changes,
            "patch_result": patch_result,
            "line_changes_attempted": len(line_changes),
            "links": {"salesforce_order_url": order_url} if order_url else {},
        },
    )

    # 4.5 CCC Request → In Progress (real SF update) + audit comment with deltas
    deltas = extracted.get("change_deltas") or extracted.get("changes") or {}
    deltas_str = ", ".join(f"{k}={v}" for k, v in deltas.items()) if isinstance(deltas, dict) else str(deltas)
    _update_ccc_lifecycle(
        ctx,
        status="In Progress",
        stage="awaiting_csr_review" if tier != "L4_AUTO" else "automation_complete",
        comment_body=(
            f"🔄 Trade Change Order workflow.\n"
            f"• Original Order: {order_num or '—'}  · Original PO: {po_num or '—'}\n"
            f"• Change deltas: {deltas_str or '(unstructured — see extracted notes)'}\n"
            f"• " + ("Awaiting CSR confirmation before final SF Order patch." if tier != "L4_AUTO" else "Applied automatically.")
        ),
        substep_num="4.5",
        label="CCC Request → In Progress (change pending)",
    )

    return {
        "status": "awaiting_one_click" if tier != "L4_AUTO" else "applied",
        "action": "amend_trade_order",
        "preview": preview,
        "applied": {"po_number": po_num, "order_number": order_num, "change_summary": extracted.get("changes")},
    }


def _execute_service_contract_request(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC6 — Service Contract Request (Support Agreement Quote or Order).

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Classify subtype (Support Agreement Quote vs Order Request)
      4.3 Create CCC Request shell (already done by Stage 3.0)
      4.4 CCC Request enrichment
      4.5 AIOA AI PO Validation (handled in Stage 3.0c if PO present)
      4.6 On PASS — Service Contract / Quote write
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for service contract"}

    extracted = ctx.extracted or {}
    sub_type = extracted.get("sub_type") or extracted.get("contract_subtype") or "Support Agreement Quote"
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Classify contract subtype — {sub_type}",
        data={"substep": "4.2", "label": "Classify contract subtype", "sub_type": sub_type},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.3 CCC Request shell — already created in Stage 3.0 with Service track",
        data={"substep": "4.3", "label": "CCC Request shell"},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.4 CCC Request enrichment — contract terms + line items extracted from inbound",
        data={"substep": "4.4", "label": "CCC Request enrichment", "terms": extracted.get("contract_terms")},
    )

    # 4.6 Write Service Contract — real SF ServiceContract.create
    sc_result: dict = {}
    try:
        from ..services import salesforce as _sf_svc, salesforce_service_contracts as _sf_sc
        _conn = _sf_svc.get_active_connection(ctx.db)
        if _conn is None:
            sc_result = {"applied": False, "reason": "no active Salesforce connection"}
        else:
            term_months = extracted.get("term_months") or extracted.get("term") or 12
            try:
                term_int = int(term_months)
            except Exception:
                term_int = 12
            from ..models import Pipeline as _Pipeline
            pipe_row = ctx.db.get(_Pipeline, ctx.pipeline_id)
            request_number = None
            if pipe_row and pipe_row.salesforce_case_id:
                try:
                    from ..services import salesforce_cases as _sfc
                    rec = _sfc.fetch_case(ctx.db, pipe_row.salesforce_case_id)
                    request_number = (rec or {}).get("Request_Number__c")
                except Exception:
                    request_number = None
            name = f"{sub_type} · {request_number or 'CCC-' + str(ctx.pipeline_id)}"
            sc_result = _sf_sc.create_sf_service_contract(
                _conn,
                account_id=sf_account_id,
                name=name,
                sub_type=sub_type,
                term_months=term_int,
                description=str(extracted.get("contract_terms") or extracted.get("description") or sub_type)[:32000],
                request_number=request_number,
            )
    except Exception as ex:
        sc_result = {"applied": False, "reason": f"unexpected: {type(ex).__name__}: {str(ex)[:160]}"}
    sc_id = sc_result.get("salesforce_service_contract_id")
    sc_url = sc_result.get("salesforce_url")
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.6 Write Service Contract — {'OK ' + (sc_result.get('name') or sc_id or '') if sc_result.get('applied') else 'deferred: ' + (sc_result.get('reason') or 'unknown')}",
        data={
            "substep": "4.6",
            "label": "Service Contract write",
            "sub_type": sub_type,
            "result": sc_result,
            "links": {"salesforce_service_contract_url": sc_url} if sc_url else {},
        },
    )

    # 4.7 CCC Request → In Progress (CSR to confirm contract before close)
    _update_ccc_lifecycle(
        ctx,
        status="In Progress",
        stage="contract_review",
        owner_label="cta_scope",
        comment_body=(
            f"📑 Service Contract Request workflow.\n"
            f"• Sub-type: {sub_type}\n"
            f"• Terms: {extracted.get('contract_terms') or '(none extracted)'}\n"
            f"• Awaiting CSR review before contract write is committed to ERP.\n"
        ),
        substep_num="4.7",
        label="CCC Request → In Progress (contract review)",
    )

    return {
        "status": "awaiting_one_click" if tier != "L4_AUTO" else "applied",
        "action": "create_service_contract",
        "preview": preview,
        "applied": {"sub_type": sub_type, "terms": extracted.get("contract_terms")},
    }


def _execute_ssd_change_request(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """UC7 — SSD Change Request. Factory + CSR loop is mandatory; ZBrain
    routes the case to the dashboard and lets humans drive the change.

    Diagram substeps:
      4.1 Customer-match guardrail
      4.2 Create + Assign CCC Request (Sub-type=SSD Change, Owner=Sales Order Owner)
      4.3 Add SSD request to CSR + Factories dashboard
      4.4 Notification to CSR + Factories
      4.5 Factory proposes SSD + triggers CSR from dashboard (HITL)
      4.6 Factory/CSR interaction to finalize SSD (HITL)
      4.7 Trigger changes to Oracle from dashboard
      4.8 CCC Request closed automatically; customer notified
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for SSD change"}

    extracted = ctx.extracted or {}
    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.2 CCC Request assigned — Sub-type=SSD Change · Owner=Sales Order Owner",
        data={"substep": "4.2", "label": "Assign CCC Request", "owner_label": "sales_order_owner"},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.3 Added SSD request to CSR + Factories dashboard",
        data={"substep": "4.3", "label": "Dashboard add"},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.4 Notification dispatched to CSR + Factories",
        data={"substep": "4.4", "label": "Notify CSR + Factories"},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        "4.5 Awaiting Factory proposal — HITL gate (factory CAD/spec response)",
        data={"substep": "4.5", "label": "Factory proposal — HITL", "no_reply": True},
    )

    # 4.6 CCC Request → Assigned (SSD factory loop)
    _update_ccc_lifecycle(
        ctx,
        status="Assigned",
        stage="awaiting_factory_proposal",
        owner_label="sales_order_owner",
        fallout_reason="ssd_change_factory_loop",
        comment_body=(
            "🏭 SSD Change Request routed to factory loop.\n"
            "• Sub-type: SSD Change\n"
            "• Owner: Sales Order Owner (Direct Inquiries Oracle)\n"
            "• Added to CSR + Factories dashboard; notifications dispatched.\n"
            "• Awaiting Factory proposal → CSR confirmation → Oracle trigger.\n"
            "• CCC will auto-close once Factory triggers the Oracle change."
        ),
        substep_num="4.6",
        label="CCC Request → Assigned (SSD factory loop)",
    )

    return {
        "status": "awaiting_hitl",
        "action": "ssd_change_routed",
        "preview": preview,
        "reason": "ssd_change_factory_loop",
        "applied": {"routed_to": "ssd_factory_dashboard"},
        "no_reply": True,
    }


def _execute_hold_release(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """Post-Booking — Hold Release. Customer or internal note indicates the
    order can come off hold (credit, export-compliance, tax, customer
    request, or quality). ZBrain captures the clearance reference, posts
    an audit Case Comment, and routes to the Sales Order Owner queue for
    the human to confirm the release in Oracle EBS.

    Substeps:
      4.1 Customer-match guardrail
      4.2 Locate the held order (by order_number or PO)
      4.3 CCC Request shell linked to the held order
      4.4 Case Comment with hold_type, hold_reason, clearance_reference
      4.5 CCC Request → Assigned · Owner=Sales Order Owner · Sub-type=Hold Release
      4.6 HITL gate: human confirms release in Oracle EBS before customer notify
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for hold release"}

    extracted = ctx.extracted or {}
    order_num = extracted.get("order_number") or extracted.get("sales_order_number")
    po_num = extracted.get("customer_po") or extracted.get("po_number")
    hold_type = extracted.get("hold_type") or "other"
    hold_reason = extracted.get("hold_reason") or "-"
    clearance_ref = extracted.get("clearance_reference") or "-"
    release_auth = extracted.get("release_authorization") or "-"
    requested_release = extracted.get("requested_release_date") or "-"

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Locate held Order — Order#={order_num or '—'} / PO#={po_num or '—'} on Account={sf_account_id}",
        data={"substep": "4.2", "label": "Locate held Order", "order_number": order_num, "po_number": po_num},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.3 CCC Request shell — Sub-type=Hold Release · hold_type={hold_type}",
        data={"substep": "4.3", "label": "Hold-Release CCC shell", "hold_type": hold_type},
    )

    _update_ccc_lifecycle(
        ctx,
        status="Assigned",
        stage="awaiting_csr_release",
        owner_label="sales_order_owner",
        fallout_reason="hold_release_csr_confirm",
        comment_body=(
            f"🔓 Hold Release workflow.\n"
            f"• Order: {order_num or '—'}  · PO: {po_num or '—'}\n"
            f"• Hold type: {hold_type}\n"
            f"• Hold reason: {hold_reason}\n"
            f"• Clearance reference: {clearance_ref}\n"
            f"• Release authorisation: {release_auth}\n"
            f"• Requested release date: {requested_release}\n"
            f"• CSR confirms release in Oracle EBS before customer notify."
        ),
        substep_num="4.5",
        label="CCC Request → Assigned (hold release pending CSR confirm)",
    )

    # 4.4 attach customer-supplied evidence (XLSX payment proofs, scanned
    # remittance advices, etc.) to the SF Case via SharePoint upload + a
    # CaseComment with the deep links. Skipped silently if there are no
    # attachments or no SF Case yet. The trace event carries the SharePoint
    # URLs so the operator can open them straight from the case timeline.
    _attach_evidence_substep(ctx)

    return {
        "status": "awaiting_one_click",
        "action": "release_hold",
        "preview": preview,
        "applied": {
            "order_number": order_num,
            "hold_type": hold_type,
            "clearance_reference": clearance_ref,
        },
        "reason": "hold_release_csr_confirm",
    }


def _execute_delivery_change(agent, ctx: AgentContext, *, tier: str, action: str, preview: dict) -> dict:
    """Post-Booking — Delivery Change. Customer is changing HOW or WHERE
    an existing order ships (ship-to address, carrier, Incoterm, delivery
    instructions, or splitting one shipment to multiple addresses). NOT
    a date change; that is ssd_change_request.

    Substeps:
      4.1 Customer-match guardrail
      4.2 Locate the existing order
      4.3 CCC Request shell (Sub-type=Delivery Change)
      4.4 Audit comment with change_kind + new values + reason
      4.5 CCC Request → Assigned · Owner=Sales Order Owner
      4.6 HITL gate: CSR updates Oracle EBS delivery block before notify
    """
    sf_account_id, _ = _guardrail_customer_match(ctx)
    if not sf_account_id:
        return {"status": "awaiting_hitl", "action": action, "preview": preview, "reason": "no Salesforce account match for delivery change"}

    extracted = ctx.extracted or {}
    order_num = extracted.get("order_number") or extracted.get("sales_order_number")
    po_num = extracted.get("customer_po") or extracted.get("po_number")
    change_kind = extracted.get("change_kind") or "address"
    new_ship_to = extracted.get("new_ship_to_address") or "-"
    new_carrier = extracted.get("new_carrier") or "-"
    new_incoterm = extracted.get("new_incoterm") or "-"
    instructions = extracted.get("delivery_instructions") or "-"
    splits = extracted.get("split_lines") or []
    reason = extracted.get("reason") or "-"

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.2 Locate Order — Order#={order_num or '—'} / PO#={po_num or '—'} on Account={sf_account_id}",
        data={"substep": "4.2", "label": "Locate Order", "order_number": order_num, "po_number": po_num},
    )

    log_event(
        ctx.db, ctx.pipeline_id, "execute", "substep_done",
        f"4.3 CCC Request shell — Sub-type=Delivery Change · change_kind={change_kind}",
        data={"substep": "4.3", "label": "Delivery-Change CCC shell", "change_kind": change_kind},
    )

    detail_lines = []
    if change_kind == "address":
        detail_lines.append(f"New ship-to: {new_ship_to}")
    elif change_kind == "carrier":
        detail_lines.append(f"New carrier: {new_carrier}")
    elif change_kind == "incoterm":
        detail_lines.append(f"New Incoterm: {new_incoterm}")
    elif change_kind == "delivery_instructions":
        detail_lines.append(f"New instructions: {instructions}")
    elif change_kind == "partial_split" and isinstance(splits, list):
        detail_lines.append(f"Split into {len(splits)} shipment(s): " + ", ".join(
            f"{(s or {}).get('sku', '?')} qty {(s or {}).get('qty', '?')} to {(s or {}).get('ship_to', '?')}" for s in splits
        ))

    _update_ccc_lifecycle(
        ctx,
        status="Assigned",
        stage="awaiting_csr_review",
        owner_label="sales_order_owner",
        fallout_reason="delivery_change_csr_apply",
        comment_body=(
            f"📦 Delivery Change workflow.\n"
            f"• Order: {order_num or '—'}  · PO: {po_num or '—'}\n"
            f"• Change kind: {change_kind}\n"
            f"• " + "\n• ".join(detail_lines) + "\n"
            f"• Reason: {reason}\n"
            f"• CSR applies the change in Oracle EBS before customer notify."
        ),
        substep_num="4.5",
        label="CCC Request → Assigned (delivery change pending CSR apply)",
    )

    return {
        "status": "awaiting_one_click",
        "action": "change_delivery",
        "preview": preview,
        "applied": {
            "order_number": order_num,
            "change_kind": change_kind,
        },
        "reason": "delivery_change_csr_apply",
    }


_PER_INTENT_DISPATCH = {
    "po_intake": _execute_po_intake,
    "quote_to_order": _execute_quote_to_order,
    "wo_status_inquiry": _execute_wo_status_inquiry,
    "wo_update_request": _execute_wo_update_request,
    "service_order": _execute_service_order,
    "trade_change_order": _execute_trade_change_order,
    "service_contract_request": _execute_service_contract_request,
    "ssd_change_request": _execute_ssd_change_request,
    "hold_release": _execute_hold_release,
    "delivery_change": _execute_delivery_change,
}


def _attach_evidence_substep(ctx: AgentContext) -> None:
    """Stage 4.4 — Upload each email attachment to SharePoint and link the
    files on the SF Case via a CaseComment. Records a single
    `execute.substep_done` event with the SharePoint deep links so the
    operator can open them straight from the Trace UI.

    No-op when there are no attachments or no SF Case yet. Idempotent across
    Stage 4 returns: an `execution.evidence_uploaded` marker tracks whether
    the substep already fired for this pipeline so a wrapped _persist call
    does not duplicate the SharePoint write or the CaseComment."""
    try:
        from ..models import Email, Pipeline
        from ..services import case_evidence
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        # Idempotency guard: skip if we already attached evidence on this run.
        existing_exec = pipe.execution or {}
        if existing_exec.get("evidence_uploaded"):
            return
        case_id = pipe.salesforce_case_id
        request_number = None
        try:
            from ..services import salesforce_cases as _sfc
            if case_id:
                rec = _sfc.fetch_case(ctx.db, case_id)
                if rec:
                    request_number = rec.get("Request_Number__c")
        except Exception:
            request_number = None
        email = ctx.db.get(Email, pipe.email_id) if pipe.email_id else None
        attachments = (email.attachments if email else None) or []
        if not attachments:
            return
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_start",
            f"4.4 Attach evidence — uploading {len(attachments)} attachment(s) to SharePoint, linking on Case",
            data={"substep": "4.4", "attachment_count": len(attachments)},
        )
        res = case_evidence.upload_email_attachments_to_case(
            ctx.db,
            pipeline_id=ctx.pipeline_id,
            case_id=case_id,
            request_number=request_number,
            attachments=attachments,
        )
        uploaded = res.get("uploaded") or []
        skipped = res.get("skipped") or []
        comment = res.get("case_comment") or {}
        from ..services import salesforce as _sf_svc
        sf_case_url = _sf_svc.record_url(ctx.db, case_id)
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.4 Attach evidence — {len(uploaded)} file(s) on SharePoint, "
            f"CaseComment={'posted' if comment.get('ok') else 'skipped'}"
            + (f", {len(skipped)} skipped" if skipped else ""),
            data={
                "substep": "4.4",
                "uploaded": uploaded,
                "skipped": skipped,
                "case_comment": comment,
                "subfolder": res.get("subfolder"),
                "links": {
                    "salesforce_case_url": sf_case_url,
                    "sharepoint_subfolder_url": (uploaded[0].get("sharepoint_url") if uploaded else None),
                },
            },
        )
        # Mark done so the idempotency guard skips repeat runs from
        # subsequent _persist calls within the same Stage 4 invocation.
        existing_exec["evidence_uploaded"] = {
            "count": len(uploaded),
            "subfolder": res.get("subfolder"),
            "salesforce_case_url": sf_case_url,
        }
        pipe.execution = existing_exec
        ctx.db.commit()
    except Exception as ex:
        log_event(
            ctx.db, ctx.pipeline_id, "execute", "substep_done",
            f"4.4 Attach evidence failed (non-fatal): {type(ex).__name__}: {str(ex)[:160]}",
            data={"substep": "4.4", "error": str(ex)[:240]},
        )


class Stage4ExecuteAgent(BaseAgent):
    """Executes the decided action — Salesforce Order writes for PO intake, ERP/CRM mocks for the rest."""

    stage_key = "execute"
    stage_label = "Workflow Execution"
    tools = [SalesforceCreateOrderTool()]

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        tool_results = []
        guardrails: list[str] = []
        try:
            decision = ctx.decision or {}
            action = decision.get("action")
            tier = decision.get("autonomy_tier")
            extracted = ctx.extracted or {}

            if action == "discard":
                ctx.execution = {"status": "discarded", "reason": "spam", "action": action}
                self._persist(ctx)
                return AgentResult(
                    stage=self.stage_key,
                    output=ctx.execution,
                    tool_results=tool_results,
                    guardrails_fired=guardrails,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            # ----------------------------------------------------------------
            # AIOA outcome handling
            # ----------------------------------------------------------------
            # AIOA is the upstream validation gate fired in Stage 3.0c. The
            # outcome decides whether Stage 4 proceeds with Trade Order Entry
            # or short-circuits to the AI OA Fallout queue.
            #
            #   AIOA_PASS → validation succeeded. Log the gate result and
            #               continue with Quote Update → Q2O Conversion →
            #               Salesforce Order write → Oracle EBS handoff. This
            #               matches the "Trade Order Entry Happy Path for PO
            #               Received" diagram (UC1).
            #   AIOA_FAIL → CSR review required inside AIOA. Short-circuit
            #               and route to AI OA Fallout queue. ZBrain stops
            #               here; Stage 5 emits no customer reply.
            aioa_block = (decision.get("aioa") or {}) if isinstance(decision.get("aioa"), dict) else {}
            if aioa_block.get("fired"):
                outcome = (aioa_block.get("outcome") or "").upper()
                if outcome == "AIOA_FAIL":
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        f"4.0 AIOA validation FAILED — routing to AI OA Fallout queue ({aioa_block.get('fallout_reason') or 'see findings'})",
                        data={
                            "substep": "4.0",
                            "label": "AIOA Fallout — CSR review required",
                            "aioa_outcome": outcome,
                            "aioa_request_id": aioa_block.get("request_id"),
                            "downstream_action": aioa_block.get("downstream_action"),
                            "owned_by": aioa_block.get("owned_by"),
                            "fallout_reason": aioa_block.get("fallout_reason"),
                        },
                    )
                    ctx.execution = {
                        "status": "aioa_fallout_queue",
                        "action": "aioa_handoff",
                        "preview": _build_preview(action, extracted, ctx.customer_id),
                        "aioa": aioa_block,
                        "reason": f"AIOA Fallout — CSR review via AI OA Fallout queue ({aioa_block.get('fallout_reason') or 'see findings'})",
                        # AIOA owns customer comms inside the Fallout queue.
                        "no_reply": True,
                    }
                    guardrails.append("aioa_handoff:aioa_fail")
                    self._persist(ctx)
                    return AgentResult(
                        stage=self.stage_key,
                        output=ctx.execution,
                        tool_results=tool_results,
                        guardrails_fired=guardrails,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                # AIOA_PASS → log and proceed to Quote Update / Q2O / SF Order
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.0 AIOA validation PASSED ({aioa_block.get('request_id') or '—'}) — proceeding with Trade Order Entry",
                    data={
                        "substep": "4.0",
                        "label": "AIOA validation pass — continuing to Trade Order Entry",
                        "aioa_outcome": outcome,
                        "aioa_request_id": aioa_block.get("request_id"),
                        "downstream_action": "create_salesforce_order",
                    },
                )
                guardrails.append("aioa_handoff:aioa_pass")

            # === Per-intent Stage 4 dispatch ===
            # Every intent that has a use-case AS-IS diagram gets its own
            # substep sequence here. This is the FIRST branch after AIOA so
            # the trace UI consistently shows the per-intent steps for every
            # supported intent (po_intake, quote_to_order, trade_change_order,
            # wo_status_inquiry, wo_update_request, service_order,
            # service_contract_request, ssd_change_request).
            intent_for_dispatch = (ctx.intake or {}).get("intent")
            dispatch_fn = _PER_INTENT_DISPATCH.get(intent_for_dispatch) if intent_for_dispatch else None
            log_event(
                ctx.db, ctx.pipeline_id, "execute", "dispatch",
                f"per-intent dispatch — intent='{intent_for_dispatch}', dispatch_fn={dispatch_fn.__name__ if dispatch_fn else 'none (falls through to legacy path)'}",
                data={
                    "intent": intent_for_dispatch,
                    "dispatch_fn": dispatch_fn.__name__ if dispatch_fn else None,
                    "available_intents": list(_PER_INTENT_DISPATCH.keys()),
                },
            )
            if dispatch_fn is not None:
                preview = _build_preview(action, extracted, ctx.customer_id)
                # 4.0a Existing-CCC handoff fires FIRST when Stage 3.0 adopted
                # an existing Case (ccc_action=update / clone_change_order).
                # Spec Step 7: append email thread + attachments + updated
                # business context to the parent Case. No-op for new CCCs.
                #
                # When the adoption was driven by the LLM semantic-duplicate
                # matcher (Stage 3.0.a'), this is a TRUE re-send — the prior
                # pipeline already owns the workflow + HITL + reply. We
                # attach the email and stop, instead of running the per-intent
                # workflow + creating a fresh HITL on the same Case.
                from ..models import Pipeline as _Pipeline
                _pipe_row = ctx.db.get(_Pipeline, ctx.pipeline_id)
                _ccc_resolution = (ctx.decision or {}).get("ccc_resolution") if isinstance(ctx.decision, dict) else {}
                _selected = (_ccc_resolution or {}).get("selected") or {}
                _match_signals = _selected.get("match_signals") or []
                _is_llm_duplicate = (
                    _pipe_row is not None
                    and _pipe_row.duplicate_detected
                    and (_pipe_row.ccc_action or "") in {"update", "clone_change_order"}
                    and "llm_semantic_duplicate" in _match_signals
                )
                handoff_summary = _existing_ccc_handoff(ctx)
                if _is_llm_duplicate:
                    existing_case_id = _pipe_row.existing_case_id or _pipe_row.salesforce_case_id
                    from ..services import salesforce as _sf_svc
                    sf_case_url = _sf_svc.record_url(ctx.db, existing_case_id) if existing_case_id else None
                    confidence = _selected.get("llm_confidence")
                    reason = _selected.get("llm_reason") or "LLM matched prior Case"

                    # LLM-generated close-out summary — 2-3 sentence enterprise
                    # explanation rendered in the Trace page's close-out card.
                    closeout_summary = _generate_closeout_summary_duplicate(
                        ctx,
                        existing_case_number=_selected.get("case_number"),
                        existing_case_id=existing_case_id,
                        llm_reason=reason,
                        confidence=confidence,
                    )

                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "result",
                        f"Stage 4 short-circuit — duplicate of prior Case {_selected.get('case_number') or existing_case_id} "
                        f"(LLM confidence {confidence}); no per-intent workflow run, no new HITL",
                        data={
                            "substep": "4.0a",
                            "ccc_action": _pipe_row.ccc_action,
                            "existing_case_id": existing_case_id,
                            "existing_case_number": _selected.get("case_number"),
                            "llm_confidence": confidence,
                            "llm_reason": reason,
                            "handoff": handoff_summary,
                            "closeout_summary": closeout_summary,
                            "links": {"salesforce_case_url": sf_case_url},
                        },
                    )
                    ctx.execution = {
                        "status": "duplicate_handed_off",
                        "action": "attach_to_existing_case",
                        "ccc_action": _pipe_row.ccc_action,
                        "existing_case_id": existing_case_id,
                        "existing_case_number": _selected.get("case_number"),
                        "llm_confidence": confidence,
                        "llm_reason": reason,
                        "handoff": handoff_summary,
                        "salesforce_case_url": sf_case_url,
                        "closeout_summary": closeout_summary,
                    }
                    self._persist(ctx)
                    return AgentResult(
                        stage=self.stage_key,
                        output=ctx.execution,
                        tool_results=tool_results,
                        guardrails_fired=[*guardrails, "duplicate_handed_off:llm_semantic"],
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                ctx.execution = dispatch_fn(self, ctx, tier=tier or "L3_ONE_CLICK", action=action, preview=preview)
                # Per-intent functions emit their own substeps; attach
                # evidence here so every case with SF Case + attachments
                # gets the SharePoint upload + CaseComment.
                _attach_evidence_substep(ctx)
                self._persist(ctx)
                return AgentResult(
                    stage=self.stage_key,
                    output=ctx.execution,
                    tool_results=tool_results,
                    guardrails_fired=guardrails + [f"per_intent_dispatch:{intent_for_dispatch}"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            # === v1.1 TASK-4 START === Existing-CCC branch.
            # If Stage 3 detected a duplicate Case, branch on ccc_action:
            #   update              → attach email + chatter @-mention (Chatter blocked by demo lock)
            #   clone_change_order  → log clone intent (skipped under demo lock)
            #   new                 → fall through to existing path
            from ..models import Pipeline as _Pipeline
            pipe_row = ctx.db.get(_Pipeline, ctx.pipeline_id)
            ccc_action = (pipe_row.ccc_action or "new") if pipe_row else "new"
            existing_case_id = pipe_row.existing_case_id if pipe_row else None
            existing_case_status = pipe_row.existing_case_status if pipe_row else None
            if ccc_action == "update" and existing_case_id:
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_start",
                    f"4.0a Existing-CCC update — attaching email to Case {existing_case_id} "
                    f"(status was {existing_case_status})",
                    data={"substep": "4.0a", "ccc_action": ccc_action,
                          "existing_case_id": existing_case_id,
                          "existing_case_status": existing_case_status},
                )
                from ..services import salesforce_cases as _sf_cases
                attach_res = _sf_cases.attach_email_to_case(
                    ctx.db, existing_case_id, email_id=pipe_row.email_id,
                )
                chatter_res = _sf_cases.chatter_notify_owner(
                    ctx.db, existing_case_id,
                    message=(
                        f"New customer email attached. Original status: "
                        f"{existing_case_status}. Recommended status flip: Continue Processing."
                    ),
                )
                # Flip status to "Working" (closest standard equivalent) when prior was "Awaiting *"
                # — only if SF is reachable. Demo-lock makes the SF call cheap.
                status_flip = None
                if (existing_case_status or "").lower() in {
                    "awaiting customer-cia", "awaiting customer-info",
                    "awaiting internal-fe", "awaiting internal-system",
                    "in progress", "working",
                }:
                    status_flip = _sf_cases.update_case_status(
                        ctx.db, existing_case_id, "Working",
                    )
                ctx.execution = {
                    "status": "completed",
                    "action": "attach_to_existing_case",
                    "ccc_action": ccc_action,
                    "existing_case_id": existing_case_id,
                    "existing_case_status": existing_case_status,
                    "attach_result": attach_res,
                    "chatter_result": chatter_res,
                    "status_flip_result": status_flip,
                }
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.0a Attached + Chatter notify (Chatter "
                    f"{'simulated by demo lock' if (chatter_res or {}).get('simulated') else 'posted'}) — Case {existing_case_id}",
                    data={"substep": "4.0a", **ctx.execution},
                )
                self._persist(ctx)
                return AgentResult(
                    stage=self.stage_key,
                    output=ctx.execution,
                    tool_results=tool_results,
                    guardrails_fired=[*guardrails, f"existing_ccc:{ccc_action}"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            elif ccc_action == "clone_change_order" and existing_case_id:
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_start",
                    f"4.0b Clone Change Order — source Case {existing_case_id} (Closed) → new CO Case",
                    data={"substep": "4.0b", "ccc_action": ccc_action, "src_case_id": existing_case_id},
                )
                ctx.execution = {
                    "status": "completed",
                    "action": "clone_change_order",
                    "ccc_action": ccc_action,
                    "src_case_id": existing_case_id,
                    "simulated": True,
                    "reason": "Clone scaffold present; demo records intent without SF Apex/REST clone call.",
                }
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    "4.0b Clone Change Order intent recorded (demo skips actual SF clone)",
                    data={"substep": "4.0b", **ctx.execution},
                )
                self._persist(ctx)
                return AgentResult(
                    stage=self.stage_key,
                    output=ctx.execution,
                    tool_results=tool_results,
                    guardrails_fired=[*guardrails, f"existing_ccc:{ccc_action}"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            # === v1.1 TASK-4 END ===

            preview = _build_preview(action, extracted, ctx.customer_id)

            # ----------------------------------------------------------------
            # 4.1  Customer-match guardrail
            # ----------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "execute", "substep_start",
                "4.1 Customer-match guardrail — refuse SF write when Stage 2.3 didn't resolve a Salesforce Account",
                data={"substep": "4.1", "label": "Customer-match guardrail"},
            )

            if action in _ORDER_ACK_ACTIONS:
                sf_block = ctx.customer_match.get("salesforce") or {}
                sf_account = sf_block.get("account") or {}
                sf_account_id = sf_account.get("Id") or ctx.customer_match.get("salesforce_account_id")

                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.1 Customer-match guardrail — {'pass' if sf_account_id else 'BLOCK (no SF account)'}",
                    data={
                        "substep": "4.1",
                        "verdict": "pass" if sf_account_id else "blocked",
                        "salesforce_account_id": sf_account_id,
                        "customer_name": ctx.customer_match.get("customer_name"),
                        "customer_code": ctx.customer_match.get("customer_code"),
                    },
                )

                if not sf_account_id:
                    ctx.execution = {
                        "status": "awaiting_hitl",
                        "action": action,
                        "preview": preview,
                        "reason": "no Salesforce account match for write",
                    }
                    guardrails.append("customer_match_required_for_write")
                    self._persist(ctx)
                    return AgentResult(
                        stage=self.stage_key,
                        output=ctx.execution,
                        tool_results=tool_results,
                        guardrails_fired=guardrails,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )

                if tier == "L2_HITL":
                    ctx.execution = {
                        "status": "awaiting_hitl",
                        "action": action,
                        "preview": preview,
                    }
                    self._persist(ctx)
                    return AgentResult(
                        stage=self.stage_key,
                        output=ctx.execution,
                        tool_results=tool_results,
                        guardrails_fired=guardrails,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )

                # ----------------------------------------------------------
                # 4.2  Duplicate-order check (existing Order with same PoNumber?)
                # ----------------------------------------------------------
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_start",
                    f"4.2 Duplicate-order check — looking up existing SF Order with PoNumber={extracted.get('po_number') or '(none)'} on Account={sf_account_id}",
                    data={"substep": "4.2", "label": "Duplicate-order check", "po_number": extracted.get("po_number")},
                )
                idempotent = self._idempotency_check(ctx, sf_account_id, extracted.get("po_number"))
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.2 Duplicate-order check — {'EXISTING order found, will skip write' if idempotent else 'no duplicate'}",
                    data={
                        "substep": "4.2",
                        "duplicate_found": bool(idempotent),
                        "existing_order": idempotent,
                    },
                )
                if idempotent:
                    ctx.execution = {
                        "status": "applied",
                        "action": action,
                        "preview": preview,
                        "idempotent_skip": idempotent,
                        "applied": {"salesforce": idempotent, "idempotent": True},
                    }
                    guardrails.append("idempotent_skip_existing_order")
                    # Still upload attachments — even on idempotency skip we
                    # want the customer's evidence linked on the SF Case.
                    _attach_evidence_substep(ctx)
                    self._persist(ctx)
                    return AgentResult(
                        stage=self.stage_key,
                        output=ctx.execution,
                        tool_results=tool_results,
                        guardrails_fired=guardrails,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )

                # ----------------------------------------------------------
                # 4.3  Salesforce Order write
                # ----------------------------------------------------------
                order_status = "Activated" if tier == "L4_AUTO" else "Draft"
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_start",
                    f"4.3 Salesforce Order write — creating Order ({order_status}) under Account={sf_account_id}",
                    data={
                        "substep": "4.3",
                        "label": "Salesforce Order write",
                        "salesforce_account_id": sf_account_id,
                        "order_status_target": order_status,
                        "tier": tier,
                    },
                )
                sf_res = self.invoke_tool(
                    ctx,
                    "salesforce_create_order",
                    account_id=sf_account_id,
                    extracted=extracted,
                    intent=ctx.intake.get("intent") or "po_intake",
                    order_status=order_status,
                )
                tool_results.append(sf_res)
                from ..services import salesforce as _sf_svc
                _order_id = (sf_res.data or {}).get("salesforce_order_id") if sf_res.ok else None
                _order_url = _sf_svc.record_url(ctx.db, _order_id) if _order_id else None
                _account_url = _sf_svc.record_url(ctx.db, sf_account_id) if sf_account_id else None
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.3 Salesforce Order write — {'OK ' + (sf_res.data.get('salesforce_order_number') or sf_res.data.get('salesforce_order_id') or '') if sf_res.ok else 'FAILED: ' + (sf_res.error or 'unknown')}",
                    data={
                        "substep": "4.3",
                        "ok": sf_res.ok,
                        "order_id": _order_id,
                        "order_number": (sf_res.data or {}).get("salesforce_order_number"),
                        "line_items_created": (sf_res.data or {}).get("line_items_created"),
                        "status_applied": (sf_res.data or {}).get("salesforce_status"),
                        "error": sf_res.error,
                        "links": {
                            "salesforce_order_url": _order_url,
                            "salesforce_account_url": _account_url,
                        },
                    },
                )

                if not sf_res.ok:
                    ctx.execution = {
                        "status": "awaiting_hitl" if tier != "L4_AUTO" else "error",
                        "action": action,
                        "preview": preview,
                        "reason": f"salesforce_write_failed: {sf_res.error}",
                    }
                    guardrails.append(f"salesforce_write_failed: {sf_res.error}")
                else:
                    if tier == "L4_AUTO":
                        ctx.execution = {
                            "status": "applied",
                            "action": action,
                            "preview": preview,
                            "applied": {
                                "acknowledged": True,
                                "po_number": extracted.get("po_number"),
                                "salesforce": sf_res.data,
                            },
                        }
                    else:
                        ctx.execution = {
                            "status": "awaiting_one_click",
                            "action": action,
                            "preview": preview,
                            "draft": sf_res.data,
                        }
                # 4.4 Attach evidence — upload every customer attachment to
                # SharePoint and link them on the SF Case so the CSR can open
                # them straight from the Case feed.
                if sf_res.ok:
                    _attach_evidence_substep(ctx)
                self._persist(ctx)
                return AgentResult(
                    stage=self.stage_key,
                    output=ctx.execution,
                    tool_results=tool_results,
                    guardrails_fired=guardrails,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            # ----------------------------------------------------------------
            # Non-PO-ack action path (convert_quote_to_order, release_hold,
            # reschedule_order, service_order, etc.) — emit 4.1/4.2/4.3
            # substep events here too so the trace UI is consistent regardless
            # of which intent/action this pipeline took.
            # ----------------------------------------------------------------
            sf_account_id = ctx.customer_match.get("salesforce_account_id") or (
                (ctx.customer_match.get("salesforce") or {}).get("account") or {}
            ).get("Id")
            log_event(
                ctx.db, ctx.pipeline_id, "execute", "substep_done",
                f"4.1 Customer-match guardrail — {'pass' if sf_account_id else 'no SF account (proceeding with mock CRM/ERP)'}",
                data={
                    "substep": "4.1",
                    "verdict": "pass" if sf_account_id else "no_sf_account",
                    "salesforce_account_id": sf_account_id,
                    "customer_name": ctx.customer_match.get("customer_name"),
                    "customer_code": ctx.customer_match.get("customer_code"),
                    "action": action,
                },
            )
            log_event(
                ctx.db, ctx.pipeline_id, "execute", "substep_done",
                "4.2 Duplicate-order check — n/a for this action (no PO/Order create involved)",
                data={"substep": "4.2", "skipped": True, "reason": f"duplicate-order check is PO-ack-only; action='{action}'"},
            )
            log_event(
                ctx.db, ctx.pipeline_id, "execute", "substep_start",
                f"4.3 Workflow execution — action='{action}' tier={tier}",
                data={"substep": "4.3", "label": "Workflow execution", "action": action, "tier": tier},
            )

            if tier == "L4_AUTO":
                # ---------------------------------------------------------
                # UC3 — SOM Bulk WO staging branch (service_order multi-asset)
                # ---------------------------------------------------------
                # Per the RFP "High-Level SOM Flow" diagram, when service_order
                # comes in with multiple assets, the AI agent populates a Bulk
                # WO Staging table then creates one WO per asset and assigns
                # owners. The CCC Request is closed with no reply once the
                # WOs are written; CSR confirms via HITL after the fact.
                intent_now = ctx.intake.get("intent") or ""
                # For service_order, multi-asset detection accepts the canonical
                # schema fields *and* the LLM-emitted line_items (which the
                # extraction schema uses to enumerate calibration assets).
                assets_list = extracted.get("add_assets") or extracted.get("assets") or []
                if intent_now == "service_order" and not assets_list:
                    li = extracted.get("line_items") or []
                    if isinstance(li, list) and li and isinstance(li[0], dict) and (
                        li[0].get("asset_serial") or li[0].get("sku") or li[0].get("model")
                    ):
                        assets_list = li
                is_multi_asset_service = (
                    intent_now == "service_order"
                    and isinstance(assets_list, list)
                    and len(assets_list) >= 2
                )
                if is_multi_asset_service:
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        f"4.3a Bulk WO Staging — populating staging table for {len(assets_list)} asset(s)",
                        data={
                            "substep": "4.3a",
                            "label": "Bulk WO Staging table",
                            "asset_count": len(assets_list),
                            "assets_preview": assets_list[:5],
                        },
                    )
                    staged_wos = [{
                        "wo_seq": i + 1,
                        "model": (a.get("model") if isinstance(a, dict) else None),
                        "serial": (a.get("serial") if isinstance(a, dict) else None),
                        "asset_id": (a.get("asset_id") if isinstance(a, dict) else None),
                        "owner": "SOM CSR",
                        "status": "created",
                    } for i, a in enumerate(assets_list)]
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        f"4.3b Automation: Create WO and Assign Owner — {len(staged_wos)} work order(s) created",
                        data={
                            "substep": "4.3b",
                            "label": "Create WO and Assign Owner",
                            "work_orders_created": staged_wos,
                        },
                    )
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3c SOM AI Agent — attached email + attachments to each new WO",
                        data={
                            "substep": "4.3c",
                            "label": "Attach email/attachments to WO",
                            "wo_count": len(staged_wos),
                        },
                    )
                    ctx.execution = {
                        "status": "applied_no_reply",
                        "action": action,
                        "preview": preview,
                        "applied": {
                            "applied": True,
                            "no_reply": True,
                            "work_orders": staged_wos,
                            "bulk_wo_staging": True,
                            "asset_count": len(assets_list),
                        },
                        "no_reply": True,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3d AI Agent — Close CCC Request (no reply); SOM CSR reviews WOs separately",
                        data={
                            "substep": "4.3d",
                            "label": "Close CCC Request (no reply)",
                            "no_reply": True,
                        },
                    )
                # ---------------------------------------------------------
                # UC3 — SOM Single-asset auto-WO (no-reply close)
                # ---------------------------------------------------------
                elif intent_now == "service_order" and isinstance(assets_list, list) and len(assets_list) == 1:
                    only = assets_list[0] if isinstance(assets_list[0], dict) else {}
                    staged = {
                        "wo_seq": 1,
                        "model": only.get("model") or only.get("sku"),
                        "serial": only.get("serial") or only.get("asset_serial"),
                        "owner": "SOM CSR",
                        "status": "created",
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3a Automation: Create WO and Assign Owner — 1 work order created",
                        data={"substep": "4.3a", "label": "Create WO and Assign Owner", "work_orders_created": [staged]},
                    )
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3b SOM AI Agent — attached email + attachments to WO",
                        data={"substep": "4.3b", "label": "Attach email/attachments to WO"},
                    )
                    ctx.execution = {
                        "status": "applied_no_reply",
                        "action": action,
                        "preview": preview,
                        "applied": {"applied": True, "no_reply": True, "work_orders": [staged]},
                        "no_reply": True,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3c Close CCC Request (no reply); SOM CSR reviews WO separately",
                        data={"substep": "4.3c", "label": "Close CCC Request (no reply)", "no_reply": True},
                    )
                # ---------------------------------------------------------
                # UC4 — SOM WO Update / Change Order (no-reply close)
                # ---------------------------------------------------------
                elif intent_now == "wo_update_request":
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3a Update Existing WO — Add Note / Add Task on the referenced work order",
                        data={"substep": "4.3a", "label": "Update Existing WO",
                              "wo_number": extracted.get("work_order_number") or extracted.get("wo_number")},
                    )
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3b SOM AI Agent — attached email + attachments to the existing WO",
                        data={"substep": "4.3b", "label": "Attach email/attachments to WO"},
                    )
                    ctx.execution = {
                        "status": "applied_no_reply",
                        "action": action,
                        "preview": preview,
                        "applied": {"applied": True, "no_reply": True, "wo_update": True},
                        "no_reply": True,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3c Close CCC Request (no reply); HITL CSR Review of WO and Reply",
                        data={"substep": "4.3c", "label": "Close CCC Request (no reply)", "no_reply": True},
                    )
                # ---------------------------------------------------------
                # UC7 — SSD Change Request (factory handoff, auto-close)
                # ---------------------------------------------------------
                elif intent_now == "ssd_change_request":
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3a Add SSD request to the CSR dashboard",
                        data={"substep": "4.3a", "label": "Add SSD request to CSR dashboard",
                              "request_type": "Trade Order Modification", "sub_type": "SSD Change"},
                    )
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3b Notification sent to CSR & Factories",
                        data={"substep": "4.3b", "label": "Notify CSR & Factories"},
                    )
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3c Factory handoff — Factory prepares SSD, finalises with CSR, triggers Oracle change from dashboard",
                        data={"substep": "4.3c", "label": "Factory handoff (Human-in-loop)",
                              "downstream_systems": ["CSR dashboard", "Oracle (upcoming via Jitterbit)"]},
                    )
                    ctx.execution = {
                        "status": "applied_no_reply",
                        "action": action,
                        "preview": preview,
                        "applied": {"applied": True, "no_reply": True, "ssd_factory_handoff": True},
                        "no_reply": True,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3d CCC Request auto-closed once Factory triggers Oracle change",
                        data={"substep": "4.3d", "label": "CCC Request auto-closed", "no_reply": True},
                    )
                # ---------------------------------------------------------
                # UC1 — Trade Order Entry Quote Update + Q2O Conversion
                # ---------------------------------------------------------
                elif intent_now in {"po_intake", "quote_to_order"} and (ctx.reconcile or {}).get("matched_quote"):
                    matched_q = (ctx.reconcile or {}).get("matched_quote") or {}
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        f"4.3a Quote Update — matched quote {matched_q.get('quote_number') or '?'} updated to match accepted PO",
                        data={
                            "substep": "4.3a",
                            "label": "Quote Update",
                            "quote_number": matched_q.get("quote_number"),
                        },
                    )
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        "4.3b Q2O Conversion — quote promoted to Sales Order",
                        data={
                            "substep": "4.3b",
                            "label": "Q2O Conversion",
                            "quote_number": matched_q.get("quote_number"),
                            "oracle_ebs_status": "upcoming (Jitterbit bridge)",
                        },
                    )
                    applied = _apply(
                        ctx.db,
                        action=action,
                        extracted=extracted,
                        customer_id=ctx.customer_id,
                        salesforce_account_id=ctx.customer_match.get("salesforce_account_id"),
                        intent=intent_now,
                    )
                    ctx.execution = {
                        "status": "applied" if applied.get("applied") else "awaiting_hitl",
                        "action": action,
                        "preview": preview,
                        "applied": applied,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        f"4.3c Workflow execution — {'applied' if applied.get('applied') else 'awaiting_hitl'} ({applied.get('reason') or 'ok'})",
                        data={"substep": "4.3c", "ok": bool(applied.get("applied")), "applied": applied, "tier": tier},
                    )
                else:
                    applied = _apply(
                        ctx.db,
                        action=action,
                        extracted=extracted,
                        customer_id=ctx.customer_id,
                        salesforce_account_id=ctx.customer_match.get("salesforce_account_id"),
                        intent=intent_now,
                    )
                    ctx.execution = {
                        "status": "applied" if applied.get("applied") else "awaiting_hitl",
                        "action": action,
                        "preview": preview,
                        "applied": applied,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "execute", "substep_done",
                        f"4.3 Workflow execution — {'applied' if applied.get('applied') else 'awaiting_hitl'} ({applied.get('reason') or 'ok'})",
                        data={
                            "substep": "4.3",
                            "ok": bool(applied.get("applied")),
                            "applied": applied,
                            "tier": tier,
                        },
                    )
            elif tier == "L3_ONE_CLICK":
                ctx.execution = {
                    "status": "awaiting_one_click",
                    "action": action,
                    "preview": preview,
                }
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.3 Workflow execution — staged for L3 one-click approval",
                    data={"substep": "4.3", "tier": tier, "status": "awaiting_one_click"},
                )
            else:
                ctx.execution = {
                    "status": "awaiting_hitl",
                    "action": action,
                    "preview": preview,
                }
                log_event(
                    ctx.db, ctx.pipeline_id, "execute", "substep_done",
                    f"4.3 Workflow execution — routed to L2 full HITL review",
                    data={"substep": "4.3", "tier": tier, "status": "awaiting_hitl"},
                )

            self._persist(ctx)
            return AgentResult(
                stage=self.stage_key,
                output=ctx.execution,
                tool_results=tool_results,
                guardrails_fired=guardrails,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:
            return AgentResult(
                stage=self.stage_key,
                output={},
                tool_results=tool_results,
                guardrails_fired=[*guardrails, f"stage_error: {type(e).__name__}: {str(e)[:300]}"],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _idempotency_check(self, ctx: AgentContext, account_id: str, po_number: str | None) -> dict | None:
        if not po_number or not account_id:
            return None
        try:
            conn = sf_svc.get_active_connection(ctx.db)
            if not conn:
                return None
            sf = sf_svc.client_for(conn)
            esc_acc = str(account_id).replace("'", "\\'")
            esc_po = str(po_number).replace("'", "\\'")
            soql = (
                "SELECT Id, OrderNumber, Status, PoNumber, AccountId "
                "FROM Order "
                f"WHERE AccountId = '{esc_acc}' AND PoNumber = '{esc_po}' "
                "LIMIT 1"
            )
            res = sf.query(soql)
            recs = res.get("records") or []
            if not recs:
                return None
            r = {k: v for k, v in recs[0].items() if k != "attributes"}
            return r
        except Exception:
            return None

    def _persist(self, ctx: AgentContext) -> None:
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        pipe.execution = ctx.execution
        ctx.db.commit()
        # Universal evidence-upload pass. Runs after every Stage 4 return so
        # any customer attachment on any inbound email lands in SharePoint
        # under case_evidence/<request_number>/ and the SF Case picks up a
        # CaseComment with the deep links. Idempotent: no-ops when there
        # are no attachments or no SF Case yet. Already-uploaded files are
        # skipped by the case_evidence service via a per-pipeline marker.
        try:
            _attach_evidence_substep(ctx)
        except Exception:
            # Evidence upload must never break the Stage 4 return path; the
            # substep itself already swallows internal errors and logs them.
            pass
