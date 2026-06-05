"""Stage 5 — Communication & Close-out (4 sub-steps).

Per ADR-017 in SOLUTION.md:

  5.1  Draft customer reply (LLM, English)         — intent-aware reply drafter
  5.2  Translate to customer language               — only if customer != en
  5.3  Attach SOA / generated documents             — ReportLab PDF generation
  5.4  Communication log written                    — SMTP send + CommLog row (L4 only)

Each sub-step emits substep_start / substep_done trace events so the UI shows a
clear timeline with input/output and full draft text per step.
"""
from __future__ import annotations

import time

from ..models import Pipeline
from ..trace_log import log_event
from .base import AgentContext, AgentResult, BaseAgent
from .communicate import run_communicate
from .tools.translate_tool import TranslateTool


def _draft_fallout_clarification(ctx: AgentContext, exec_status: str | None) -> dict:
    """Build a CSR-ready clarification email when Stage 4 sent the case to a
    fallout / awaiting-HITL state. Per spec Step 12: surface a draft Step-1
    email in the HITL loop so the CSR has a starting point. Returns a dict
    with subject + body + kind. NOT auto-sent."""
    intake = ctx.intake or {}
    extracted = ctx.extracted or {}
    execution = ctx.execution or {}
    customer_name = (ctx.customer_match or {}).get("customer_name") or "team"
    intent = intake.get("intent") or "order"

    aioa = execution.get("aioa") or {}
    fallout_reason = (
        aioa.get("fallout_reason")
        or execution.get("reason")
        or (execution.get("applied") or {}).get("reason")
        or "additional information required"
    )

    if exec_status == "aioa_fallout_queue":
        kind = "aioa_fallout_clarification"
        subject_prefix = "Action needed"
        opener = (
            f"Hi {customer_name},\n\nThank you for your recent order request. "
            "Before we can proceed with order acceptance, we need to clarify a few items "
            "flagged during our automated validation:"
        )
    else:
        kind = "hitl_clarification"
        subject_prefix = "Quick clarification"
        opener = (
            f"Hi {customer_name},\n\nThanks for your order request. "
            "While preparing the acknowledgement, a few items need your confirmation:"
        )

    findings = aioa.get("findings") or []
    bullets: list[str] = []
    if isinstance(findings, list) and findings:
        for f in findings[:5]:
            if isinstance(f, dict):
                bullets.append(f"• {f.get('label') or f.get('rule') or 'review item'} — {f.get('detail') or ''}".rstrip(" —"))
            else:
                bullets.append(f"• {str(f)[:200]}")
    if not bullets:
        bullets.append(f"• {fallout_reason}")
    po = extracted.get("po_number") or extracted.get("customer_po")
    if po:
        bullets.append(f"• PO Number we're working from: {po}")
    if extracted.get("quote_number"):
        bullets.append(f"• Quote referenced: {extracted.get('quote_number')}")

    closer = (
        "\n\nCould you please respond with the missing details or a corrected document so we can complete "
        "the acceptance? Your order is on hold pending this clarification.\n\n"
        "Thanks,\nZBrain Sales Ops · Keysight"
    )
    body = opener + "\n\n" + "\n".join(bullets) + closer
    subject = f"{subject_prefix} on your {intent.replace('_', ' ')} request" + (f" — PO {po}" if po else "")
    return {"subject": subject[:140], "body": body, "kind": kind}


def _action_aware_fallback_body(*, cust_name: str, intent: str, action: str, extracted: dict) -> str:
    """Build a customer-facing reply body that reflects the action the CSR is
    about to approve. Used as the Stage 5 fallback when the primary LLM
    drafter is unavailable. A generic "we are reviewing" template would
    contradict the action the CSR sees on the HITL screen, so each known
    action gets a short, customer-appropriate template that names the
    operation. The CSR can edit before sending.
    """
    name = cust_name or "Customer"
    e = extracted or {}
    order = e.get("order_number") or e.get("po_number") or e.get("customer_po") or "your order"
    po = e.get("po_number") or e.get("customer_po") or ""
    quote = e.get("quote_number") or ""
    wire = e.get("payment_reference") or e.get("bank_reference") or ""
    ship_date = e.get("requested_ship_date") or e.get("new_ship_date") or ""
    sig = "Regards,\nKeysight Sales Operations"

    if action == "release_hold" or intent == "hold_release":
        wire_line = f" The payment reference {wire} has been recorded against the order." if wire else ""
        return (
            f"Hello {name},\n\n"
            f"We have reviewed your hold-release request on order {order} and lifted the credit hold."
            f"{wire_line} The order will continue through to ship per the requested schedule.\n\n"
            "If you do not see the status update on your portal within the next business day, "
            "please reply to this thread and we will follow up.\n\n"
            f"{sig}"
        )
    if action == "create_order_acknowledgment" or intent in ("po_intake", "quote_to_order"):
        po_line = f" against PO {po}" if po else ""
        quote_line = f" referencing quote {quote}" if quote else ""
        ship_line = f" The estimated ship date is {ship_date}." if ship_date else ""
        return (
            f"Hello {name},\n\n"
            f"Thank you for your order{po_line}{quote_line}. We have acknowledged it in our order system "
            f"and the Sales Order Acknowledgement is attached for your records.{ship_line}\n\n"
            "Please reply if you need any changes before fulfilment.\n\n"
            f"{sig}"
        )
    if action == "convert_quote_to_order":
        return (
            f"Hello {name},\n\n"
            f"Your quote {quote or '(reference)'} has been converted to a firm order"
            f"{(' under PO ' + po) if po else ''}. The Sales Order Acknowledgement is attached.\n\n"
            f"{sig}"
        )
    if action == "change_delivery" or intent == "delivery_change":
        return (
            f"Hello {name},\n\n"
            f"We have updated the delivery details on order {order}"
            f"{(' to ship on ' + ship_date) if ship_date else ''}. "
            "You will receive a tracking update once the carrier confirms.\n\n"
            f"{sig}"
        )
    if action == "create_work_order" or intent in ("service_order", "wo_update_request"):
        wo = e.get("work_order_number") or e.get("wo_number") or ""
        wo_line = f" Work order {wo} has been created." if wo else ""
        return (
            f"Hello {name},\n\n"
            f"We have received your service request and routed it to our service operations team.{wo_line} "
            "You will receive scheduling details from the assigned technician shortly.\n\n"
            f"{sig}"
        )
    if intent == "wo_status_inquiry":
        return (
            f"Hello {name},\n\n"
            f"Thanks for the status check on {order}. A team member will reply with the current work-order status shortly.\n\n"
            f"{sig}"
        )
    if intent == "service_contract_request":
        return (
            f"Hello {name},\n\n"
            "We have received your service contract request and routed it to the contracts desk for review and quote.\n\n"
            f"{sig}"
        )
    # General fallback. Still better than "we are reviewing" because it
    # acknowledges that an internal action is being taken.
    return (
        f"Hello {name},\n\n"
        "Thank you for your message. We have routed it to the appropriate team and will follow up shortly with the next steps.\n\n"
        f"{sig}"
    )


class Stage5CommunicateAgent(BaseAgent):
    """Drafts a reply in the customer's language and produces an English preview for non-English drafts."""

    stage_key = "communicate"
    # Stage labels are canonical in analytics.subprocess_taxonomy.STAGE_META.
    # Keep this in sync so the trace UI, governance, and analytics views all
    # show the same agent name.
    stage_label = "Communication & Close-out"
    tools = [TranslateTool()]

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        tool_results = []
        guardrails: list[str] = []
        try:
            # No-reply close — Stage 5 short-circuits and the case completes
            # without ZBrain drafting an outbound customer email. Triggered by:
            #   - AIOA handoff (PASS or FAIL): AIOA owns all customer comms.
            #     ZBrain stops at Stage 4; the AI OA team replies (FAIL) or
            #     AIOA auto-acknowledges (PASS).
            #   - SOM auto-WO (UC3) / WO update (UC4) / SSD change (UC7): the
            #     case completes inside the system; no customer email per the
            #     RFP use-case flow.
            if (ctx.execution or {}).get("no_reply"):
                exec_status = (ctx.execution or {}).get("status")
                if exec_status == "aioa_fallout_queue":
                    label = "5.0 No-reply close — AIOA owns this case (AIOA_FAIL); AI OA CSR handles customer comms inside AIOA"
                elif exec_status == "handed_off_to_aioa":
                    label = "5.0 No-reply close — AIOA accepted the order; downstream comms (incl. SOA) are owned by AIOA"
                else:
                    label = "5.0 No-reply close — case completed inside system per RFP use-case flow; no customer reply drafted"
                log_event(
                    ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                    label,
                    data={
                        "substep": "5.0",
                        "label": "No-reply close",
                        "reason": exec_status,
                        "intent": (ctx.intake or {}).get("intent"),
                        "aioa_outcome": ((ctx.execution or {}).get("aioa") or {}).get("outcome"),
                    },
                )
                # 5.0a Fallout-clarification draft (spec Step 12 — "Communication
                # Triggers - Share Draft Step 1 new mail in loop"). When AIOA
                # fallout or any HITL-required state fires, draft a "we need
                # more info" email for the CSR so they have a starting point
                # in the HITL queue. The draft is NOT auto-sent (`sent=False`,
                # `no_reply=True`).
                fallout_draft = _draft_fallout_clarification(ctx, exec_status)
                ctx.reply = {
                    "subject": fallout_draft.get("subject"),
                    "body": fallout_draft.get("body"),
                    "body_customer_language": fallout_draft.get("body"),
                    "body_english": fallout_draft.get("body"),
                    "language": (ctx.intake or {}).get("language") or "en",
                    "attachments": [],
                    "soa_attachment": None,
                    "soa_path": None,
                    "sent": False,
                    "no_reply": True,
                    "reason": "no_reply_close (per RFP use-case flow)",
                    "csr_draft": True,
                    "csr_draft_kind": fallout_draft.get("kind"),
                }
                if fallout_draft.get("subject"):
                    log_event(
                        ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                        f"5.0a CSR clarification draft — '{(fallout_draft.get('subject') or '')[:60]}' "
                        f"({fallout_draft.get('kind')}). Surfaced in HITL queue for CSR to edit + send.",
                        data={
                            "substep": "5.0a",
                            "label": "CSR clarification draft",
                            "subject": fallout_draft.get("subject"),
                            "body_preview": (fallout_draft.get("body") or "")[:400],
                            "kind": fallout_draft.get("kind"),
                            "auto_sent": False,
                        },
                    )
                self._persist(ctx)
                return AgentResult(
                    stage=self.stage_key,
                    output=ctx.reply,
                    tool_results=tool_results,
                    guardrails_fired=[*guardrails, "no_reply_close"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            # ----------------------------------------------------------------
            # 5.1  Draft customer reply (LLM, English first)
            # ----------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "communicate", "substep_start",
                f"5.1 Draft customer reply — LLM drafting reply for intent='{ctx.intake.get('intent') or '?'}', "
                f"customer={ctx.customer_match.get('customer_name') or '—'}",
                data={"substep": "5.1", "label": "Draft customer reply", "intent": ctx.intake.get("intent")},
            )
            reply = run_communicate(
                email=ctx.email or {},
                intake=ctx.intake or {},
                extracted=ctx.extracted or {},
                decision=ctx.decision or {},
                execution=ctx.execution or {},
                customer_match=ctx.customer_match or {},
                db=ctx.db,
            ) or {}
            # Surface the system-prompt KB lookup so a Continuous-Learning
            # prompt promotion is visible in the trace. Demo-critical:
            # without this event, "we promoted a new reply prompt" is
            # invisible to a watching client.
            _kb_src = reply.get("kb_prompt_source") or {}
            if _kb_src.get("source") == "kb":
                log_event(
                    ctx.db, ctx.pipeline_id, "communicate", "kb_prompt_applied",
                    f"Reply system prompt loaded from KB agent_prompts/{_kb_src.get('key')} v{_kb_src.get('version')}",
                    data={"substep": "5.1", "kb_prompt_source": _kb_src},
                )

            language = reply.get("language") or ctx.intake.get("language") or "en"
            customer_body = reply.get("body") or ""
            english_body = customer_body if language == "en" else None
            llm_error = reply.get("_llm_error")
            template_fallback = bool(reply.get("_template_fallback"))
            if llm_error:
                guardrails.append(f"stage5_llm_fallback: {llm_error}")
            log_event(
                ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                f"5.1 Draft drafted — {len(customer_body)} chars · subject='{(reply.get('subject') or '')[:60]}'"
                + (" · template-fallback" if template_fallback else ""),
                data={
                    "substep": "5.1",
                    "subject": reply.get("subject"),
                    "body_chars": len(customer_body),
                    "draft_language": language,
                    "body_preview": customer_body[:400],
                    "template_fallback": template_fallback,
                    "llm_error": llm_error,
                },
            )

            # ----------------------------------------------------------------
            # 5.2  Translate to customer language (skip if en)
            # ----------------------------------------------------------------
            attachments: list[str] = []
            if reply.get("soa_attachment"):
                attachments.append(reply["soa_attachment"])

            if language and language != "en" and customer_body:
                log_event(
                    ctx.db, ctx.pipeline_id, "communicate", "substep_start",
                    f"5.2 Translate to customer language — en → {language}",
                    data={"substep": "5.2", "label": "Translate to customer language", "target_language": language},
                )
                tr_res = self.invoke_tool(
                    ctx, "translate_to_english", text=customer_body, source_language=language
                )
                tool_results.append(tr_res)
                if tr_res.ok:
                    english_body = tr_res.data.get("translated_text") or ""
                else:
                    guardrails.append(f"reply_translation_failed: {tr_res.error}")
                log_event(
                    ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                    f"5.2 Translation complete — {(tr_res.data or {}).get('output_chars') or 0} chars EN",
                    data={
                        "substep": "5.2",
                        "ok": tr_res.ok,
                        "english_chars": len(english_body or ""),
                        "provider": (tr_res.data or {}).get("provider_label"),
                    },
                )
            else:
                log_event(
                    ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                    "5.2 Translate — skipped (customer language is English)",
                    data={"substep": "5.2", "skipped": True, "reason": "customer_language_is_en"},
                )

            # ----------------------------------------------------------------
            # 5.3  Attach SOA / generated documents (+ file in SharePoint)
            # ----------------------------------------------------------------
            sharepoint_filed: dict | None = None
            soa_path = reply.get("soa_path")
            if soa_path:
                try:
                    from ..services import sharepoint as sp_svc
                    sp_conn = sp_svc.get_active_connection(ctx.db)
                except Exception:
                    sp_conn = None
                if sp_conn:
                    try:
                        from pathlib import Path as _P
                        sp_file = _P(soa_path)
                        if sp_file.exists():
                            with open(sp_file, "rb") as fh:
                                meta = sp_svc.upload_file(
                                    sp_conn,
                                    name=sp_file.name,
                                    content=fh.read(),
                                    content_type="application/pdf",
                                    subfolder="SalesOps/SOA",
                                    overwrite=True,
                                )
                            sharepoint_filed = {
                                "store": "SharePoint",
                                "name": meta.get("name"),
                                "web_url": meta.get("web_url"),
                                "size": meta.get("size"),
                                "folder": "SalesOps/SOA",
                            }
                        else:
                            sharepoint_filed = {
                                "store": "SharePoint",
                                "error": f"SOA file missing on disk at {soa_path}",
                            }
                    except Exception as _e:
                        sharepoint_filed = {"store": "SharePoint", "error": f"{type(_e).__name__}: {str(_e)[:200]}"}
                else:
                    # Enterprise behaviour: SharePoint is required for SOA
                    # filing. The readiness gate stops new pipelines at the
                    # ingress, but if a pre-readiness pipeline reached this
                    # step we fail Stage 5 loudly so the case is flagged
                    # rather than silently saved to local disk. Demo mode
                    # restores the simulated-local-fallback path.
                    from ..services.readiness import is_demo_mode
                    if is_demo_mode():
                        sharepoint_filed = {
                            "store": "SharePoint",
                            "simulated": True,
                            "reason": "demo mode (ENABLE_DEMO_FALLBACKS=1) — file kept in local outputs/",
                            "local_path": soa_path,
                        }
                    else:
                        sharepoint_filed = {
                            "store": "SharePoint",
                            "error": (
                                "SharePoint not connected — SOA cannot be filed. "
                                "Reconnect in Settings → Integrations."
                            ),
                            "blocker": True,
                        }
                        guardrails.append("sharepoint_not_connected")

                # DocuNet (upcoming): if the operator has enabled the
                # placeholder integration in Settings, mark that the same file
                # would be filed there via Jitterbit alongside SharePoint.
                docunet_filed: dict | None = None
                try:
                    from ..models import IntegrationPlaceholder
                    row = ctx.db.query(IntegrationPlaceholder).filter_by(provider="docunet", enabled=True).first()
                    if row:
                        docunet_filed = {
                            "store": "DocuNet (via Jitterbit)",
                            "simulated": True,
                            "doc_type": (row.config or {}).get("doc_type") or "FCNV",
                            "endpoint": (row.config or {}).get("endpoint_url"),
                            "reason": "placeholder integration enabled; live POST not wired",
                        }
                except Exception:
                    docunet_filed = None
            else:
                docunet_filed = None

            log_event(
                ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                f"5.3 Attach SOA / file in SharePoint — {len(attachments)} attachment(s)"
                + (" · uploaded to SharePoint" if sharepoint_filed and not sharepoint_filed.get("simulated") and not sharepoint_filed.get("error") else "")
                + (" · DocuNet handoff queued" if docunet_filed else ""),
                data={
                    "substep": "5.3",
                    "label": "Attach SOA / file in SharePoint",
                    "attachments": attachments,
                    "soa_path": reply.get("soa_path"),
                    "sharepoint": sharepoint_filed,
                    "docunet": docunet_filed,
                    "soa_error": reply.get("_soa_error"),
                },
            )

            # 5.3a Link the SOA back on the SF Case so a CSR opening the Case
            # sees the SOA SharePoint URL inline in the feed. Spec Step 16:
            # "Generate SOA communication ... attached to CCC request."
            if sharepoint_filed and sharepoint_filed.get("web_url"):
                try:
                    from ..models import Pipeline as _P
                    from ..services import salesforce_cases as _sf_cases, salesforce as _sf_svc
                    _pipe = ctx.db.get(_P, ctx.pipeline_id)
                    _case_id = _pipe.salesforce_case_id if _pipe else None
                    if _case_id:
                        soa_url = sharepoint_filed.get("web_url")
                        soa_name = sharepoint_filed.get("name") or "SOA.pdf"
                        body = (
                            f"📄 Statement of Acknowledgement (SOA) generated and filed.\n\n"
                            f"• File: {soa_name}\n"
                            f"• SharePoint: {soa_url}\n"
                            f"• Filed by: ZBrain Sales Ops automation"
                        )
                        _cc = _sf_cases.add_case_comment(ctx.db, _case_id, body=body, is_public=False)
                        log_event(
                            ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                            f"5.3a SOA linked on SF Case — CaseComment "
                            f"{'posted' if (_cc or {}).get('ok') else 'failed'}",
                            data={
                                "substep": "5.3a",
                                "label": "Link SOA on SF Case",
                                "case_id": _case_id,
                                "soa_url": soa_url,
                                "comment_result": _cc,
                                "links": {
                                    "salesforce_case_url": _sf_svc.record_url(ctx.db, _case_id),
                                    "sharepoint_soa_url": soa_url,
                                },
                            },
                        )
                except Exception as _ex_link:
                    log_event(
                        ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                        f"5.3a Link SOA on SF Case — failed (non-fatal): {type(_ex_link).__name__}: {str(_ex_link)[:160]}",
                        data={"substep": "5.3a", "error": str(_ex_link)[:240]},
                    )

            # ----------------------------------------------------------------
            # 5.4  Communication log (CommLog row + outbound SMTP send happens
            #      in the orchestrator post-stage, on L4 auto only — we log the
            #      intent here so the UI can show what's planned)
            # ----------------------------------------------------------------
            tier = (ctx.decision or {}).get("autonomy_tier")
            log_event(
                ctx.db, ctx.pipeline_id, "communicate", "substep_done",
                f"5.4 Communication log — tier={tier or '—'} · sent_status pending orchestrator finalization",
                data={
                    "substep": "5.4",
                    "label": "Communication log",
                    "tier": tier,
                    "auto_send_eligible": tier == "L4_AUTO",
                },
            )

            ctx.reply = {
                "subject": reply.get("subject"),
                "body_customer_language": customer_body,
                "body_english": english_body,
                "language": language,
                "attachments": attachments,
                "body": customer_body,
                "soa_attachment": reply.get("soa_attachment"),
                "soa_path": reply.get("soa_path"),
                "sharepoint_filed": sharepoint_filed,
                "docunet_filed": docunet_filed,
                "template_fallback": template_fallback,
                "llm_error": llm_error,
                "sent": reply.get("sent", False),
                "reason": reply.get("reason"),
            }

            self._persist(ctx)
            return AgentResult(
                stage=self.stage_key,
                output=ctx.reply,
                tool_results=tool_results,
                guardrails_fired=guardrails,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:
            # Stage 5 failures should never leave the case without a draft —
            # the CSR HITL view still needs SOMETHING to review. Build an
            # action-aware fallback draft from the intake / extracted context
            # so the case lands in HITL with a draft that reflects what the
            # case is about, not a generic "we are reviewing" stub that
            # contradicts the action the CSR is about to approve.
            err_label = f"{type(e).__name__}: {str(e)[:300]}"
            intent = (ctx.intake or {}).get("intent") or "general_inquiry"
            cust_name = (ctx.customer_match or {}).get("customer_name") or "Customer"
            lang = (ctx.intake or {}).get("language") or "en"
            ex = ctx.extracted or {}
            decision = ctx.decision or {}
            action = decision.get("action") or ""
            email_subj = ((ctx.email or {}).get("subject") or "your request")
            fallback_subject = f"Re: {email_subj}"
            fallback_body = _action_aware_fallback_body(
                cust_name=cust_name, intent=intent, action=action, extracted=ex,
            )
            ctx.reply = {
                "subject": fallback_subject,
                "body_customer_language": fallback_body,
                "body_english": fallback_body if lang == "en" else None,
                "language": lang,
                "attachments": [],
                "body": fallback_body,
                "soa_attachment": None,
                "soa_path": None,
                "sent": False,
                "reason": f"fallback_draft_after_stage5_error: {err_label}",
                "_intent": intent,
                "_is_fallback": True,
            }
            self._persist(ctx)
            log_event(
                ctx.db, ctx.pipeline_id, "communicate", "fallback_draft",
                f"Stage 5 errored — generated minimal fallback draft for CSR review ({err_label})",
                data={"reason": err_label, "subject": fallback_subject},
            )
            return AgentResult(
                stage=self.stage_key,
                output=ctx.reply,
                tool_results=tool_results,
                guardrails_fired=[*guardrails, f"stage_error: {err_label}"],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _persist(self, ctx: AgentContext) -> None:
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        pipe.reply = ctx.reply
        ctx.db.commit()
