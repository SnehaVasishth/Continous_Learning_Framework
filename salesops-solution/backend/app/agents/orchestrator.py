"""Top-level pipeline orchestrator (agent-shape).

Each stage is a `BaseAgent` subclass with its own tool belt. The orchestrator
builds a shared `AgentContext`, invokes each stage in sequence, and lets each
agent emit per-tool trace events. Stage agents persist their own updates
to the Pipeline row via `_persist()` — the orchestrator handles cross-stage
concerns (Salesforce Case lifecycle, HITL task creation, CommunicationLog,
Customer match resolution).
"""
from __future__ import annotations

import logging
import traceback

from sqlalchemy.orm import Session

from ..config import TERMINAL_INTENTS
from ..models import (
    CommunicationLog,
    Customer,
    Email,
    HitlTask,
    Order,
    Pipeline,
    Quote,
    WorkOrder,
    now,
)
from ..services import imap_back_stamp, salesforce_cases as sf_cases
from ..trace_log import log_event, stage_timer
from .base import AgentContext
from .stage1_intake_agent import Stage1IntakeAgent
from .stage2_extract_agent import Stage2ExtractAgent
from .stage3_decide_agent import Stage3DecideAgent
from .stage4_execute_agent import Stage4ExecuteAgent
from .stage5_communicate_agent import Stage5CommunicateAgent

logger = logging.getLogger(__name__)


def run_pipeline(db: Session, *, pipeline_id: int, email_id: int) -> None:
    pipe = db.get(Pipeline, pipeline_id)
    if not pipe:
        return
    try:
        email_row = db.get(Email, email_id)
        email = _email_to_dict(email_row)

        # CCC Request lifecycle: we DO NOT mint a Salesforce Case here. The
        # request needs to be resolved against existing SF Cases first (PO# /
        # WO# / customer dedup) and minted with a meaningful category, request
        # type, track, and owner — none of which are known until intake +
        # extract have run. The Stage 3 decide agent owns the lookup-or-create
        # decision; until then, `case_state` is just an in-memory builder.
        request_number = f"CCC-{datetime_stamp()}-{pipeline_id:05d}"
        case_state: dict = {
            "request_number": request_number,
            "email_id": email_id,
            "pipeline_id": pipeline_id,
            "customer_id": email_row.customer_id,
            "status": "new",
            "stage": "automation_in_progress",
            "owner_label": "ai_agent",
            "category": None,
            "request_type": None,
            "sub_type": None,
            "track": None,
            "fallout_reason": None,
        }
        pipe.salesforce_case_id = None
        db.commit()

        ctx = AgentContext(db=db, pipeline_id=pipeline_id, email=email)
        ctx.customer_id = email_row.customer_id

        # === v1.1 TASK-2 START === Pre-Intake (Stage 0) — deterministic Outlook rules.
        # Runs BEFORE Stage 1 so bounce / OOO / KSO / Brazil-tax / collections /
        # portal-admin emails NEVER hit the LLM classifier. Pure string/regex
        # matching from KB-tunable rules. If a rule matches, set intake.intent
        # directly and skip Stage 1 entirely — the existing terminal-intent
        # branch below handles the short-circuit + redirect logging.
        with stage_timer(db, pipeline_id, "pre_intake", "Pre-AI Outlook rules"):
            from . import pre_intake
            pre_match = pre_intake.evaluate(email_row)
            if pre_match:
                log_event(
                    db, pipeline_id, "pre_intake", "rule_matched",
                    f"{pre_match['rule_label']} → {pre_match['intent']} "
                    f"(no LLM call — deterministic short-circuit)",
                    data=pre_match,
                )
                ctx.intake = {
                    "intent": pre_match["intent"],
                    "intent_confidence": 1.0,
                    "intent_reasoning": pre_match["reason"],
                    "summary": pre_match["rule_label"],
                    "language": email.get("language_hint") or "en",
                    "track_hint": "none",
                    "spam": False,
                    "spam_reason": "",
                    "secondary_intents": [],
                    "pre_intake_match": pre_match,
                }
            else:
                log_event(
                    db, pipeline_id, "pre_intake", "no_match",
                    "no Outlook rule matched — falling through to Stage 1 LLM classifier",
                    data={"rules_evaluated": "outlook_rules namespace"},
                )
        db.commit()
        # === v1.1 TASK-2 END ===

        # ---- Stage 1: Intake & Classification ------------------------------
        # === v1.1 TASK-2 === Skip Stage 1 LLM if Pre-Intake already classified.
        if pre_match:
            log_event(
                db, pipeline_id, "intake", "skipped",
                "Stage 1 LLM classifier skipped — Pre-Intake matched a deterministic rule",
                data={"matched_rule": pre_match.get("rule_key")},
            )
            r1 = None
        else:
            with stage_timer(db, pipeline_id, "intake", "Intake & classification"):
                r1 = Stage1IntakeAgent().run(ctx)
                log_event(db, pipeline_id, "intake", "result", "classification done", data=ctx.intake)
        # Case-state updates run for BOTH branches (pre_intake fills ctx.intake too).
        # SF write is deferred: case_state is a builder; the Stage 3 lookup-or-
        # create decides whether to adopt an existing Case or mint a new one
        # with the full state in hand.
        case_state["category"] = _category_from_intent(ctx.intake.get("intent"))
        case_state["request_type"] = ctx.intake.get("intent")
        case_state["track"] = ctx.intake.get("track_hint")
        db.commit()
        intake = ctx.intake

        # ---- Short-circuit: terminal intents (spam / out_of_scope / redirected) ---------
        # Skip Stages 2-6 entirely. No CRM lookup, no extraction, no decision,
        # no execution, no reply drafted. Just close the CCC, mark email
        # discarded (or redirected for the 4 routing intents), and log why
        # each stage was skipped.
        terminal_intent = intake.get("intent") if intake.get("intent") in TERMINAL_INTENTS else None
        if terminal_intent:
            # === v1.1 TASK-1 START === per-intent terminal-handling matrix
            from ..config import INTENT_REDIRECT_TARGETS
            redirect_to = INTENT_REDIRECT_TARGETS.get(terminal_intent)
            is_redirect = terminal_intent in {"kso", "collections", "portal_admin", "brazil_tax"}
            if is_redirect:
                reason = f"{terminal_intent}_redirected"
                human_label = f"redirect to {redirect_to}"
                pipe_status = "completed"
                email_status = "redirected"
            elif terminal_intent == "undeliverable":
                reason = "undeliverable_discarded"
                human_label = "bounce / DSN — discard"
                pipe_status = "discarded"
                email_status = "discarded"
            elif terminal_intent == "out_of_scope":
                reason = "out_of_scope_discarded"
                human_label = "out-of-scope (automated notification, internal admin, etc.)"
                pipe_status = "discarded"
                email_status = "discarded"
            else:  # spam
                reason = "spam_discarded"
                human_label = "spam / phishing / promotional"
                pipe_status = "discarded"
                email_status = "discarded"
            # === v1.1 TASK-1 END ===
            log_event(
                db, pipeline_id, "intake", "short_circuit",
                f"intent='{terminal_intent}' is terminal — skipping Stages 2-6 ({human_label})",
                data={
                    "intent": terminal_intent,
                    "reason": reason,
                    "skipped_stages": ["enrichment", "extract", "reconcile", "decide", "execute", "communicate"],
                    "intent_reasoning": intake.get("intent_reasoning"),
                    "summary": intake.get("summary"),
                    "would_route_to": redirect_to,  # === v1.1 TASK-1 ===
                },
            )
            # === v1.1 TASK-1 START === record the would-be redirect in CommunicationLog
            # so the trace UI surfaces the action even though DEMO_TRANSMIT_LOCKED
            # blocks the actual SMTP forward.
            if is_redirect and redirect_to:
                log_event(
                    db, pipeline_id, "pre_intake", "redirect",
                    f"would forward to {redirect_to} (demo lock — no SMTP send)",
                    data={
                        "intent": terminal_intent,
                        "would_route_to": redirect_to,
                        "delivery_status": "blocked_by_demo_lock",
                    },
                )
                comm = CommunicationLog(
                    customer_id=email_row.customer_id,
                    pipeline_id=pipe.id,
                    direction="outbound",
                    channel="email",
                    subject=f"[Redirect] {email.get('subject') or ''}",
                    body=f"Would forward this email to {redirect_to}.\n\nIntent: {terminal_intent}\nReason: {human_label}",
                    intent=terminal_intent,
                    autonomy_tier="L4_AUTO",
                    sent_by=f"AI redirect ({terminal_intent})",
                    csr_action=None,
                )
                db.add(comm)
            # === v1.1 TASK-1 END ===
            pipe.intent = terminal_intent
            pipe.language = intake.get("language") or pipe.language
            pipe.confidence = float(intake.get("intent_confidence") or 0.0)
            pipe.status = pipe_status  # === v1.1 TASK-1 === was always "discarded"
            case_state["status"] = "closed"
            case_state["stage"] = "automation_complete"
            case_state["fallout_reason"] = reason
            _sf_case_update(
                db,
                pipeline_id,
                pipe.salesforce_case_id,
                case_state,
                status="closed",
                stage="automation_complete",
                fallout_reason=reason,
            )
            pipe.finished_at = now()
            if email_row.status == "processing":
                email_row.status = email_status  # === v1.1 TASK-1 === was always "discarded"
            db.commit()
            log_event(db, pipeline_id, "activity", "done", f"Activity {pipe_status} ({reason})")
            db.commit()
            _back_stamp_safe(db, pipeline_id)
            return

        # ---- Stage 2: Data Extraction & Enrichment -------------------------
        # Stage 2 owns: full OCR (2.1), schema-driven extraction (2.2), full
        # SF customer match using extracted JSON (2.3), and intent-aware
        # enrichment SOQL (2.4). See stage2_extract_agent.py for sub-steps.
        with stage_timer(db, pipeline_id, "extract", "Document extraction"):
            r2 = Stage2ExtractAgent().run(ctx)
            log_event(db, pipeline_id, "extract", "result", "extraction done", data=ctx.extracted)
        db.commit()
        extracted = ctx.extracted
        match_data = ctx.customer_match or {}
        sf_account_id = match_data.get("salesforce_account_id")
        customer_code = match_data.get("customer_code")
        if pipe.salesforce_case_id and (sf_account_id or customer_code):
            _sf_case_patch_raw(
                db,
                pipeline_id,
                pipe.salesforce_case_id,
                {
                    **({"AccountId": sf_account_id} if sf_account_id else {}),
                    **({"Customer_Code__c": customer_code} if customer_code else {}),
                },
            )

        # ---- Stage 2 short-circuit: SF match failed → HITL --------------
        if (r2.output or {}).get("_sf_match_failed"):
            sf_reason = (r2.output or {}).get("_sf_match_reason", "no_salesforce_match")
            hitl = HitlTask(
                pipeline_id=pipeline_id,
                reason="unknown_customer_in_salesforce",
                payload={
                    "intake": intake,
                    "extracted": extracted,
                    "customer_match": match_data,
                    "sf_match_reason": sf_reason,
                },
            )
            db.add(hitl)
            pipe.status = "awaiting_hitl"
            case_state["status"] = "assigned"
            case_state["stage"] = "review_required"
            case_state["owner_label"] = "csr_review"
            case_state["fallout_reason"] = (
                "salesforce_not_configured"
                if "not_configured" in sf_reason
                else "unknown_customer_in_salesforce"
            )
            _sf_case_update(
                db,
                pipeline_id,
                pipe.salesforce_case_id,
                case_state,
                status="assigned",
                stage="review_required",
                owner_label="csr_review",
                fallout_reason=case_state["fallout_reason"],
            )
            pipe.finished_at = now()
            # Stage 2 customer-match failure always requires a human, so the
            # tier must read L2_HITL — never L4. Decide hasn't run yet for
            # this path, so there is no upstream confidence to preserve.
            pipe.autonomy_tier = "L2_HITL"
            # Customer-match failure is detected at Stage 2 reconcile and the
            # pipeline halts there. Stage 3 (Decide) and Stage 4 (Execute) do
            # NOT run for this path, so the HITL task is logged against the
            # reconcile sub-step to make that obvious in the trace.
            log_event(
                db, pipeline_id, "reconcile", "hitl_created",
                f"HITL task created at Stage 2.5 reconcile: Salesforce customer match failed ({sf_reason}). Pipeline parked here; Decide and Execute did not run.",
                data={
                    "reason": "unknown_customer_in_salesforce",
                    "sf_match_reason": sf_reason,
                    "tier_downgraded_to": "L2_HITL",
                    "parked_at_stage": "reconcile",
                    "stages_not_run": ["decide", "execute", "communicate"],
                },
            )
            if email_row.status == "processing":
                email_row.status = "awaiting_hitl"
            db.commit()
            log_event(db, pipeline_id, "activity", "done", f"Activity awaiting_hitl ({case_state['fallout_reason']})")
            db.commit()
            _back_stamp_safe(db, pipeline_id)
            return

        # Stage 2.5 (Cross-system validation / reconcile) runs inside the
        # Stage 2 agent now — see stage2_extract_agent.py. ctx.reconcile and
        # pipe.reconcile are populated there before we reach Stage 3.
        recon = ctx.reconcile or {}
        if recon:
            pipe.reconcile = recon
            log_event(db, pipeline_id, "reconcile", "result", _recon_message(recon), data=recon)
            db.commit()

        # ---- Stage 3: Decision & Confidence Scoring ------------------------
        with stage_timer(db, pipeline_id, "decide", "Confidence scoring & autonomy"):
            r3 = Stage3DecideAgent().run(ctx)
            log_event(db, pipeline_id, "decide", "result", "decision made", data=ctx.decision)
        db.commit()
        decision = ctx.decision

        # ---- AIOA pause point ----------------------------------------------
        # If the Decide Agent enqueued an AIOA request, the pipeline is now
        # parked in `awaiting_aioa`. Stage 4+ run only after the callback
        # arrives, and that resume is owned by the Order Acceptance service,
        # not by this orchestrator pass. Return here.
        if isinstance(decision, dict) and (decision.get("aioa") or {}).get("status") == "awaiting_response":
            db.refresh(pipe)
            if pipe.status != "awaiting_aioa":
                pipe.status = "awaiting_aioa"
            if email_row.status == "processing":
                email_row.status = "awaiting_aioa"
            log_event(
                db, pipeline_id, "activity", "done",
                f"Activity awaiting_aioa (correlation_id={(decision.get('aioa') or {}).get('correlation_id')})",
            )
            db.commit()
            _back_stamp_safe(db, pipeline_id)
            return

        # ---- Stage 4: Workflow Execution -----------------------------------
        with stage_timer(db, pipeline_id, "execute", "Workflow execution"):
            r4 = Stage4ExecuteAgent().run(ctx)
            execution = ctx.execution
            log_event(db, pipeline_id, "execute", "result", f"execution {execution.get('status')}", data=execution)
            sf_block = (execution.get("applied") or {}).get("salesforce") or execution.get("draft")
            if execution.get("idempotent_skip"):
                idem = execution["idempotent_skip"]
                log_event(
                    db,
                    pipeline_id,
                    "execute",
                    "salesforce_order_idempotent",
                    f"Salesforce Order {idem.get('OrderNumber')} already exists for this PO — skipping duplicate write",
                    data=idem,
                )
            elif sf_block and sf_block.get("applied"):
                status_label = sf_block.get("salesforce_status") or sf_block.get("requested_status") or "Draft"
                kind = "salesforce_order_activated" if status_label == "Activated" else "salesforce_order_drafted"
                log_event(
                    db,
                    pipeline_id,
                    "execute",
                    kind,
                    f"Salesforce Order {sf_block.get('salesforce_order_number') or sf_block.get('salesforce_order_id')} {status_label.lower()} — {sf_block.get('line_items_created')} line items",
                    data=sf_block,
                )

            if execution.get("status") in ("awaiting_hitl", "awaiting_one_click"):
                generic = execution["status"]
                # Promote the specific reason (no_salesforce_connection,
                # salesforce_write_failed, hard_block, etc.) into the HitlTask
                # so the queue shows *why* the case is parked, not just the
                # generic gating status.
                applied_block = execution.get("applied") if isinstance(execution.get("applied"), dict) else None
                specific = (
                    execution.get("reason")
                    or (applied_block.get("reason") if applied_block else None)
                )
                reason = specific or generic
                hitl = HitlTask(
                    pipeline_id=pipeline_id,
                    reason=reason,
                    payload={
                        "intake": intake,
                        "extracted": extracted,
                        "reconcile": recon,
                        "decision": decision,
                        "preview": execution.get("preview"),
                        "customer_id": ctx.customer_id,
                        "customer_match": match_data,
                        "gate_status": generic,
                    },
                )
                db.add(hitl)
                # Tier reflects the actual outcome, not the upstream confidence
                # score. A pipeline that parks for human action at Execute is
                # not L4 — L4 means "closed without a human." Downgrade now so
                # the dashboards and trace badge reflect reality.
                pipe.autonomy_tier = (
                    "L3_ONE_CLICK" if generic == "awaiting_one_click" else "L2_HITL"
                )
                log_event(
                    db, pipeline_id, "execute", "hitl_created",
                    f"HITL task created — {reason}",
                    data={"reason": reason, "gate_status": generic, "tier_downgraded_to": pipe.autonomy_tier},
                )
                # Publish a notification for the new HITL row so the bell
                # surfaces it immediately. Stable kind so re-running the same
                # pipeline doesn't double-emit; resolved when the CSR works it.
                try:
                    from ..services import notifications as _notif
                    _notif.publish(
                        db,
                        kind=f"hitl_pending_{pipeline_id}",
                        category="queue",
                        severity="warning",
                        title=f"New HITL task — {reason.replace('_', ' ')}",
                        body=(intake.get("summary") or pipe.email_id and f"Pipeline #{pipeline_id} needs CSR review.") or f"Pipeline #{pipeline_id} needs CSR review.",
                        action_url=f"/hitl?pipeline={pipeline_id}",
                        action_label="Open task",
                        meta={"pipeline_id": pipeline_id, "reason": reason},
                    )
                except Exception:
                    pass
        db.commit()

        # ---- Stage 5: Communication & Closeout -----------------------------
        # When Execute parks the case for HITL we still draft the reply so the
        # operator has something to review on the HITL queue. Transmission is
        # gated on operator approval — the draft is marked transmit_blocked
        # until the resolve endpoint sends it. Previously this stage was
        # entirely deferred, which left the HITL detail view with no reply to
        # show even when the proposed action explicitly required a customer
        # reply (release_hold, draft_reply, change_delivery, etc.).
        exec_status_pre_comm = (ctx.execution or {}).get("status")
        if exec_status_pre_comm == "duplicate_handed_off":
            # Stage 4 short-circuited because Stage 3.0.a' detected a true
            # re-send (LLM matched a prior in-flight Case on the same
            # account). The PRIOR pipeline already owns the workflow,
            # the HITL task, and the customer reply — we do NOT draft
            # another reply here.
            log_event(
                db, pipeline_id, "communicate", "skipped_duplicate",
                "Stage 5 skipped — pipeline is a duplicate of a prior Case; the prior pipeline owns the reply.",
                data={
                    "reason": "duplicate_handed_off",
                    "existing_case_id": (ctx.execution or {}).get("existing_case_id"),
                    "existing_case_number": (ctx.execution or {}).get("existing_case_number"),
                    "llm_confidence": (ctx.execution or {}).get("llm_confidence"),
                    "salesforce_case_url": (ctx.execution or {}).get("salesforce_case_url"),
                },
            )
            db.commit()
        elif exec_status_pre_comm in ("awaiting_hitl", "awaiting_one_click"):
            with stage_timer(db, pipeline_id, "communicate", "Customer reply draft (HITL preview)"):
                try:
                    Stage5CommunicateAgent().run(ctx)
                    if isinstance(ctx.reply, dict):
                        ctx.reply["transmit_blocked"] = exec_status_pre_comm
                        ctx.reply["preview_only"] = True
                    log_event(
                        db, pipeline_id, "communicate", "preview_drafted",
                        "Reply drafted for HITL preview — no transmit until operator approves",
                        data={"reason": exec_status_pre_comm, "parked_at": "execute", "reply": ctx.reply},
                    )
                except Exception as e:
                    log_event(
                        db, pipeline_id, "communicate", "preview_draft_failed",
                        f"HITL preview draft failed: {type(e).__name__}: {str(e)[:200]}",
                        data={"reason": exec_status_pre_comm},
                    )
            db.commit()
        else:
            with stage_timer(db, pipeline_id, "communicate", "Customer reply draft"):
                r5 = Stage5CommunicateAgent().run(ctx)
                reply = ctx.reply
                log_event(db, pipeline_id, "communicate", "result", "reply drafted", data=reply)
            db.commit()

        # NOTE: Continuous Learning is no longer a per-pipeline stage. Feedback
        # collection happens automatically via the /api/feedback endpoint when
        # CSRs leave 👍/👎 + edits in the trace UI. Aggregation, drift detection,
        # and KB tuning suggestions live on the `/learning` dashboard page —
        # they're cross-cutting / organizational, not per-email work.

        # ---- Final pipeline + Case lifecycle -------------------------------
        exec_status = execution.get("status")
        is_aioa_pass = exec_status == "handed_off_to_aioa"
        is_aioa_fail = exec_status == "aioa_fallout_queue"
        is_no_reply_close = exec_status == "applied_no_reply"
        is_duplicate_handoff = exec_status == "duplicate_handed_off"

        # Duplicate short-circuit closes THIS pipeline without touching the
        # underlying Case state (the prior pipeline owns it). Done before the
        # branching block below so we don't accidentally re-close the Case.
        if is_duplicate_handoff:
            from datetime import datetime as _dt
            pipe.status = "completed"
            pipe.finished_at = pipe.finished_at or _dt.utcnow()
            log_event(
                db, pipeline_id, "activity", "duplicate_completed",
                f"Case closed — attached to existing Case "
                f"{execution.get('existing_case_number') or execution.get('existing_case_id')}",
                data={
                    "result_status": "duplicate_handed_off",
                    "action": "attach_to_existing_case",
                    "existing_case_id": execution.get("existing_case_id"),
                    "existing_case_number": execution.get("existing_case_number"),
                    "salesforce_case_url": execution.get("salesforce_case_url"),
                    "llm_confidence": execution.get("llm_confidence"),
                    "llm_reason": execution.get("llm_reason"),
                },
            )
            db.commit()
            return
        # Propagate the track + owner + fcnv fallout from Stage 3 onto the SF
        # Case state so the case lifecycle reflects the RFP swimlane.
        owner_block = (decision or {}).get("owner") or {}
        case_state["owner_label"] = owner_block.get("owner_label") or case_state.get("owner_label")
        case_state["owner_id"] = owner_block.get("salesforce_owner_id")
        case_state["track"] = (decision or {}).get("track")
        if (intake or {}).get("fcnv_fallout_label"):
            case_state["fallout_reason"] = case_state.get("fallout_reason") or (intake or {}).get("fcnv_fallout_label")
        if exec_status == "applied" or is_aioa_pass or is_aioa_fail or is_no_reply_close:
            pipe.status = "completed"
            case_state["status"] = "closed"
            case_state["stage"] = "automation_complete"
            if is_aioa_fail:
                case_state["fallout_reason"] = (
                    (execution.get("aioa") or {}).get("fallout_reason") or "aioa_fallout"
                )
            _sf_case_update(
                db,
                pipeline_id,
                pipe.salesforce_case_id,
                case_state,
                status="closed",
                stage="automation_complete",
                fallout_reason=case_state.get("fallout_reason"),
                owner_label=case_state.get("owner_label"),
                owner_id=case_state.get("owner_id"),
                track=case_state.get("track"),
            )
            applied = (execution.get("applied") or {}) if isinstance(execution.get("applied"), dict) else {}
            order_ref = applied.get("order_number") or extracted.get("order_number")
            wo_ref = applied.get("wo_number") or extracted.get("work_order_number")
            order_row = db.query(Order).filter_by(order_number=order_ref).first() if order_ref else None
            wo_row = db.query(WorkOrder).filter_by(wo_number=wo_ref).first() if wo_ref else None
            # AIOA-handed-off cases are owned by AIOA end-to-end — ZBrain
            # does NOT write a CommunicationLog row for them. The handoff is
            # already recorded in the trace (4.0 AIOA handoff substep) and on
            # the Salesforce Case (stage=automation_complete, owner=AI OA CSR
            # on FAIL or the integration user on PASS). Writing an outbound
            # CommunicationLog here would falsely suggest ZBrain sent the
            # customer a reply — AIOA owns those comms.
            if is_aioa_pass or is_aioa_fail:
                log_event(
                    db, pipeline_id, "communicate", "no_comm_log",
                    f"No CommunicationLog written — AIOA owns customer comms "
                    f"({'AIOA_PASS handoff' if is_aioa_pass else 'AIOA_FAIL fallout queue'})",
                    data={"reason": "aioa_handoff_owns_comms", "aioa_outcome": "AIOA_PASS" if is_aioa_pass else "AIOA_FAIL"},
                )
            elif is_no_reply_close:
                # SOM auto-WO, WO update, SSD factory handoff — close without
                # a CommunicationLog row. The work is recorded in the trace
                # + the SF WO / Case state. No customer email goes out.
                log_event(
                    db, pipeline_id, "communicate", "no_comm_log",
                    "No CommunicationLog written — no-reply close per RFP use-case flow",
                    data={"reason": "no_reply_close", "intent": pipe.intent},
                )
            else:
                sent_by_label = f"AI L4 auto ({decision.get('action')})"
                # Build attachments as dicts so the CSR / trace UI can deep-link to
                # the canonical SharePoint filing. Falls back to plain filename for
                # the local-outputs-only path.
                sp_filed_block = (reply or {}).get("sharepoint_filed") or {}
                soa_name = (reply or {}).get("soa_attachment")
                attachments_payload = []
                if soa_name:
                    entry: dict = {"name": soa_name, "kind": "SOA"}
                    if isinstance(sp_filed_block, dict):
                        if sp_filed_block.get("web_url"):
                            entry["sharepoint_url"] = sp_filed_block["web_url"]
                            entry["sharepoint_folder"] = sp_filed_block.get("folder")
                            entry["source"] = sp_filed_block.get("store") or "SharePoint"
                        elif sp_filed_block.get("simulated"):
                            entry["source"] = "local outputs/ (SharePoint not connected)"
                            entry["local_path"] = sp_filed_block.get("local_path")
                    attachments_payload.append(entry)
                comm = CommunicationLog(
                    customer_id=ctx.customer_id,
                    pipeline_id=pipe.id,
                    order_id=order_row.id if order_row else None,
                    work_order_id=wo_row.id if wo_row else None,
                    direction="outbound",
                    channel="email",
                    subject=(reply or {}).get("subject"),
                    body=(reply or {}).get("body"),
                    language=(reply or {}).get("language") or pipe.language,
                    intent=pipe.intent,
                    autonomy_tier=pipe.autonomy_tier,
                    sent_by=sent_by_label,
                    csr_action=None,
                    attachments=attachments_payload,
                )
                db.add(comm)
                log_event(
                    db, pipeline_id, "communicate", "comm_log",
                    "CommunicationLog written",
                    data={
                        "attachments": attachments_payload,
                        "sharepoint_filed": sp_filed_block,
                    },
                )
        elif execution.get("status") == "discarded":
            pipe.status = "discarded"
            case_state["status"] = "closed"
            case_state["stage"] = "automation_complete"
            case_state["fallout_reason"] = "spam_discarded"
            _sf_case_update(
                db,
                pipeline_id,
                pipe.salesforce_case_id,
                case_state,
                status="closed",
                stage="automation_complete",
                fallout_reason="spam_discarded",
            )
        else:
            pipe.status = "awaiting_hitl"
            case_state["status"] = "assigned"
            case_state["stage"] = "review_required"
            # Prefer the owner the Stage 3.4 classifier resolved (FCNV CSR /
            # SOM CSR / Trade CSR / CTA CSR / AI OA CSR / Sales Order Owner)
            # over the generic "csr_review" placeholder.
            resolved_owner_label = owner_block.get("owner_label") if isinstance(owner_block, dict) else None
            resolved_owner_id = owner_block.get("salesforce_owner_id") if isinstance(owner_block, dict) else None
            case_state["owner_label"] = resolved_owner_label or "csr_review"
            case_state["owner_id"] = resolved_owner_id
            if execution.get("status") == "awaiting_one_click":
                case_state["fallout_reason"] = "low_confidence_one_click"
            else:
                case_state["fallout_reason"] = "low_confidence_full_review"
            _sf_case_update(
                db,
                pipeline_id,
                pipe.salesforce_case_id,
                case_state,
                status="assigned",
                stage="review_required",
                owner_label=case_state["owner_label"],
                owner_id=case_state.get("owner_id"),
                track=case_state.get("track"),
                fallout_reason=case_state["fallout_reason"],
            )
        pipe.finished_at = now()

        # Pipeline verifier — final invariant check across the whole pipeline.
        # Applies corrective actions if any block-severity rule fails.
        try:
            from .pipeline_verifier import verify_final, VerifierHaltError
            verify_final(db, pipe)
        except VerifierHaltError as ve:
            pipe.status = "error"
            pipe.error = f"verifier halt: {ve}"
            log_event(db, pipeline_id, "verification", "halted", str(ve), data={"rule_key": ve.rule_key})
            db.commit()
        except Exception:
            import logging as _log
            _log.getLogger("orchestrator").exception("final verifier failed for pipeline %s", pipeline_id)

        # Shadow A/B execution — replay every active shadow candidate against
        # this case and record agreement. Best-effort; never raise.
        try:
            from ..services.shadow_executor import run_for_pipeline as _run_shadow
            n = _run_shadow(db, pipe)
            if n:
                log_event(db, pipeline_id, "learning", "shadow_replayed",
                          f"{n} shadow candidate(s) replayed against this case",
                          data={"shadow_results": n})
        except Exception:
            import logging as _log
            _log.getLogger("orchestrator").exception("shadow_executor failed for pipeline %s", pipeline_id)

        # Sync email status to the terminal pipeline state. The older
        # `== processing` guard left emails stranded as "new" if the
        # orchestrator entered without flipping that flag first; the inbox
        # then over-reported under "New" and operators clicked into items
        # that were already in HITL.
        if pipe.status == "completed":
            email_row.status = "processed"
        elif pipe.status == "discarded":
            email_row.status = "discarded"
        elif pipe.status in ("awaiting_hitl", "awaiting_one_click"):
            email_row.status = "awaiting_hitl"
        elif pipe.status == "awaiting_aioa":
            email_row.status = "awaiting_aioa"
        elif pipe.status == "error":
            # Errored pipelines never delivered; leave the email actionable
            # so the operator can re-run from the inbox.
            email_row.status = "new"
        db.commit()
        log_event(db, pipeline_id, "activity", "done", f"Activity {pipe.status}")
        db.commit()
        _back_stamp_safe(db, pipeline_id)

    except Exception as e:
        tb = traceback.format_exc()
        # Rollback any aborted transaction from the failing stage so subsequent
        # writes (pipe.status update, log_event) succeed instead of hanging.
        try:
            db.rollback()
        except Exception:
            pass
        try:
            pipe.status = "error"
            pipe.error = f"{e}\n\n{tb}"
            pipe.finished_at = now()
            log_event(db, pipeline_id, "activity", "error", str(e), data={"trace": tb})
            db.commit()
            # Publish a notification so the bell surfaces the pipeline error.
            try:
                from ..services import notifications as _notif
                _notif.publish(
                    db,
                    kind=f"pipeline_error_{pipeline_id}",
                    category="workflow",
                    severity="critical",
                    title=f"Pipeline #{pipeline_id} errored",
                    body=str(e)[:240],
                    action_url=f"/trace/{pipeline_id}",
                    action_label="Open trace",
                    meta={"pipeline_id": pipeline_id, "stage": "unknown"},
                )
            except Exception:
                pass
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        logger.exception("pipeline failed")


def _back_stamp_safe(db: Session, pipeline_id: int) -> None:
    """Fire-and-forget IMAP back-stamp. Never raises; logs success/failure as
    a trace event so the demo UI shows the move happened (mirrors the Outlook
    Graph move on Keysight's POC)."""
    try:
        res = imap_back_stamp.back_stamp_pipeline_email(db, pipeline_id)
        if res.get("simulated"):
            log_event(
                db,
                pipeline_id,
                "back_stamp",
                "would_move",
                f"would move to {res.get('would_move_to')} (demo lock — mailbox unchanged)",
                data=res,
            )
        elif res.get("ok"):
            log_event(
                db,
                pipeline_id,
                "back_stamp",
                "done",
                f"moved to {res.get('moved_to')}",
                data=res,
            )
        else:
            log_event(
                db,
                pipeline_id,
                "back_stamp",
                "skipped",
                f"back-stamp skipped: {res.get('error')}",
                data=res,
            )
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            log_event(
                db,
                pipeline_id,
                "back_stamp",
                "error",
                f"back-stamp failed: {e}",
                data={"error": str(e)[:300]},
            )
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass


def datetime_stamp() -> str:
    return now().strftime("%Y%m%d")


def _category_from_intent(intent: str | None) -> str | None:
    if not intent:
        return None
    return {
        "po_intake": "Trade Order",
        "quote_to_order": "Trade Order",
        "trade_change_order": "Change Order Request",
        "ssd_change_request": "Trade Order Modification",
        "delivery_change": "Trade Order Modification",
        "hold_release": "Trade Order",
        "service_order": "Work Order Create",
        "wo_update_request": "Update Work Order",
        "wo_status_inquiry": "WO Status / Inquiry",
        "service_contract_request": "Service Contracts/Agreements",
        "general_inquiry": "General Inquiry",
        "out_of_scope": "Out of Scope",
        "spam": "Spam",
    }.get(intent, intent)


def _recon_message(r: dict) -> str:
    if not r.get("checked"):
        return "skipped — not a PO/Q2O intent"
    issues = r.get("issues") or []
    if not issues:
        q = (r.get("matched_quote") or {}).get("quote_number")
        return f"clean — matches {q}" if q else "clean — no matching quote"
    return f"{len(issues)} mismatch(es) detected"


def _email_to_dict(e: Email) -> dict:
    return {
        "id": e.id,
        "from": e.from_address,
        "subject": e.subject,
        "body": e.body,
        "language_hint": e.language_hint,
        "attachments": e.attachments or [],
        "customer_id": e.customer_id,
    }


def _sf_case_create(db: Session, pipeline_id: int, case_state: dict) -> str | None:
    """Create the Salesforce Case for this pipeline. Returns case_id or None
    on failure — we never let SF errors abort the pipeline; we just log and
    continue so the demo stays robust when the org is offline / mis-seeded."""
    try:
        res = sf_cases.create_case(
            db,
            account_id=None,
            email_id=case_state.get("email_id"),
            pipeline_id=case_state.get("pipeline_id"),
            request_number=case_state["request_number"],
            category=case_state.get("category"),
            request_type=case_state.get("request_type"),
            sub_type=case_state.get("sub_type"),
            track=case_state.get("track"),
            status=case_state.get("status") or "new",
            stage=case_state.get("stage") or "automation_in_progress",
            owner_label=case_state.get("owner_label"),
            fallout_reason=case_state.get("fallout_reason"),
        )
    except Exception as e:
        log_event(
            db, pipeline_id, "ccc", "sf_error",
            f"Salesforce Case create failed: {e}",
            data={"reason": str(e)[:300], "request_number": case_state.get("request_number")},
        )
        return None
    if not res.get("ok"):
        log_event(
            db, pipeline_id, "ccc", "sf_error",
            f"Salesforce Case create failed: {res.get('reason')}",
            data=res,
        )
        return None
    return res.get("case_id")


def _sf_case_update(
    db: Session,
    pipeline_id: int,
    case_id: str | None,
    case_state: dict,
    **fields,
) -> None:
    """Patch the SF Case. If the Case wasn't created yet (case_id None),
    create it now using the latest case_state — this covers the short-circuit
    paths (terminal intents, Stage 2 SF-match-failed HITL) where the pipeline
    never reaches Stage 3's lookup-or-create gate.

    On the happy path the Case is created in Stage 3 by the existing-CCC
    resolution substep, so this auto-create only fires for short-circuits."""
    if not case_id:
        new_id = _sf_case_create(db, pipeline_id, case_state)
        if new_id:
            pipe = db.get(Pipeline, pipeline_id)
            if pipe:
                pipe.salesforce_case_id = new_id
            log_event(
                db, pipeline_id, "ccc", "created",
                f"Salesforce Case {case_state.get('request_number')} created "
                f"(short-circuit path — status={case_state.get('status')})",
                data={
                    "request_number": case_state.get("request_number"),
                    "status": case_state.get("status"),
                    "stage": case_state.get("stage"),
                    "salesforce_case_id": new_id,
                    "trigger": "short_circuit_auto_create",
                },
            )
        return
    try:
        sf_cases.update_case(db, case_id=case_id, **fields)
    except Exception as e:
        log_event(
            db, pipeline_id, "ccc", "sf_error",
            f"Salesforce Case update failed: {e}",
            data={"case_id": case_id, "fields": list(fields.keys())},
        )


def _sf_case_patch_raw(db: Session, pipeline_id: int, case_id: str, raw_fields: dict) -> None:
    """Patch with native SF API field names (e.g. AccountId). Used to attach
    the resolved Account once Stage 2 customer-match completes."""
    if not case_id or not raw_fields:
        return
    try:
        from ..services import salesforce as sf_svc
        conn = sf_svc.get_active_connection(db)
        if not conn:
            return
        sf = sf_svc.client_for(conn)
        sf.Case.update(case_id, raw_fields)
    except Exception as e:
        log_event(
            db, pipeline_id, "ccc", "sf_error",
            f"Salesforce Case patch failed: {e}",
            data={"case_id": case_id, "fields": list(raw_fields.keys())},
        )
