from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..agents.execute import _apply
from ..db import get_db
from ..models import CommunicationLog, Email, Feedback, HitlTask, Pipeline, now
from ..services import email_outbound
from ..trace_log import log_event

router = APIRouter()


class ReplyEdit(BaseModel):
    subject: str | None = None
    body: str | None = None


class Resolution(BaseModel):
    action: str
    note: str | None = None
    edits: dict | None = None
    reply: ReplyEdit | None = None


class AssignIn(BaseModel):
    user_id: str | None = None
    user_name: str | None = None
    queue: str | None = None
    assigned_by: str | None = None


@router.get("")
def list_tasks(
    status: str = "pending",
    q: str | None = None,
    reason: str | None = None,
    intent: str | None = None,
    tier: str | None = None,
    assignee_user_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(HitlTask).filter(HitlTask.status == status)
    if reason:
        query = query.filter(HitlTask.reason == reason)
    if assignee_user_id:
        if assignee_user_id == "_unassigned":
            query = query.filter(HitlTask.assignee_user_id.is_(None))
        else:
            query = query.filter(HitlTask.assignee_user_id == assignee_user_id)
    # Pipeline-level filters (intent, tier) require a join
    if intent or tier:
        query = query.outerjoin(Pipeline, Pipeline.id == HitlTask.pipeline_id)
        if intent:
            query = query.filter(Pipeline.intent == intent)
        if tier:
            query = query.filter(Pipeline.autonomy_tier == tier)
    query = query.order_by(HitlTask.created_at.desc()).limit(400)
    rows = query.all()
    # Free-text search across subject, customer, PO, intent, reason. Done in
    # Python (rows are small after the prior filters); avoids a hairy SOQL-style
    # full-text query against the email + pipeline join.
    if q:
        needle = q.lower().strip()
        kept = []
        for t in rows:
            blob = _search_blob(db, t).lower()
            if needle in blob:
                kept.append(t)
        rows = kept
    return [_summary(db, t) for t in rows[:200]]


def _search_blob(db: Session, t: HitlTask) -> str:
    parts: list[str] = [str(t.id), t.reason or "", t.assignee_name or ""]
    pipe = db.get(Pipeline, t.pipeline_id) if t.pipeline_id else None
    if pipe:
        parts.append(pipe.intent or "")
        parts.append(pipe.autonomy_tier or "")
        cm = pipe.customer_match or {}
        parts.append(cm.get("customer_name") or "")
        ex = pipe.extracted or {}
        parts.append(ex.get("po_number") or "")
        parts.append(ex.get("customer_po") or "")
        parts.append(ex.get("quote_number") or "")
        parts.append(ex.get("work_order_number") or "")
        email = db.get(Email, pipe.email_id) if pipe.email_id else None
        if email:
            parts.append(email.subject or "")
            parts.append(email.from_address or "")
    return " ".join(p for p in parts if p)


@router.get("/operators")
def list_operators(queue: str | None = None, db: Session = Depends(get_db)):
    """Active CSR users available for HITL assignment, pulled from Salesforce.

    If `queue` is provided (developer name like ZBrain_Trade_CSR), the list is
    filtered to users who are members of that Salesforce Queue. Otherwise
    returns all active demo CSR users (excludes system / integration users)."""
    try:
        from ..services import salesforce as sf_svc
        conn = sf_svc.get_active_connection(db)
        if conn is None:
            return {"users": [], "queue": queue, "note": "Salesforce not connected"}
        sf = sf_svc.client_for(conn)
        # Pull active platform CSR users (the +csr-demo accounts we provisioned).
        # In production we'd filter to a specific Profile or PermissionSet; here
        # the convention is the +csr-demo username token.
        soql = (
            "SELECT Id, Name, FirstName, LastName, Username, Email, IsActive "
            "FROM User WHERE IsActive = true AND Username LIKE '%csr-demo%' "
            "ORDER BY Name"
        )
        if queue:
            # Filter to members of the named Queue (Group of Type='Queue').
            qres = sf.query(f"SELECT Id FROM Group WHERE Type='Queue' AND DeveloperName='{queue}' LIMIT 1")
            recs = qres.get("records") or []
            if recs:
                qid = recs[0]["Id"]
                mres = sf.query_all(f"SELECT UserOrGroupId FROM GroupMember WHERE GroupId='{qid}'")
                ids = [m["UserOrGroupId"] for m in mres["records"]]
                if ids:
                    quoted = ",".join(f"'{i}'" for i in ids)
                    soql = (
                        "SELECT Id, Name, FirstName, LastName, Username, Email, IsActive "
                        f"FROM User WHERE IsActive = true AND Id IN ({quoted}) ORDER BY Name"
                    )
                else:
                    return {"users": [], "queue": queue}
        r = sf.query_all(soql)
        return {
            "users": [
                {
                    "id": u["Id"],
                    "name": u["Name"],
                    "first_name": u.get("FirstName"),
                    "last_name": u.get("LastName"),
                    "username": u["Username"],
                    "email": u.get("Email"),
                }
                for u in r["records"]
            ],
            "queue": queue,
        }
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Salesforce user lookup failed: {type(ex).__name__}: {str(ex)[:200]}")


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    t = db.get(HitlTask, task_id)
    if not t:
        raise HTTPException(404)
    return _summary(db, t, full=True)


@router.post("/{task_id}/assign")
def assign_task(task_id: int, body: AssignIn, db: Session = Depends(get_db)):
    """Assign a HITL task to a CSR. Pass `user_id` and `user_name` to set,
    or pass an empty body / null user_id to unassign. `queue` is optional and
    records which Salesforce queue the user is acting on behalf of.

    One-way Salesforce mirror: when assigning to a real SF User, the
    underlying Case is updated to that user as Owner, and a Case Comment
    plus a Chatter post is created so the SF-native dashboards and the
    user's mobile notification stream both reflect the claim. On unassign,
    ownership is left intact on the SF side so the CSR's history of work
    is preserved; the queue Decision Agent originally stamped is still
    available via the routing_target trace.
    """
    t = db.get(HitlTask, task_id)
    if not t:
        raise HTTPException(404)

    prior_user_id = t.assignee_user_id
    prior_name = t.assignee_name

    if body.user_id:
        t.assignee_user_id = body.user_id
        t.assignee_name = body.user_name
        t.assignee_queue = body.queue
        t.assigned_at = now()
        t.assigned_by = body.assigned_by or body.user_name
    else:
        t.assignee_user_id = None
        t.assignee_name = None
        t.assignee_queue = None
        t.assigned_at = None
        t.assigned_by = None
    db.commit()

    # One-way mirror to Salesforce. Best-effort: SF errors do not roll back
    # the HITL assignment. The trace event records whether the mirror
    # succeeded.
    sf_mirror_result: dict | None = None
    if body.user_id and prior_user_id != body.user_id:
        sf_mirror_result = _mirror_assignment_to_salesforce(
            db, task=t,
            user_id=body.user_id,
            user_name=body.user_name or "",
            display_id=f"HITL-{t.id:05d}",
        )

    out = _summary(db, t, full=True)
    if sf_mirror_result is not None:
        out["salesforce_mirror"] = sf_mirror_result
    return out


def _mirror_assignment_to_salesforce(
    db: Session, *, task: HitlTask, user_id: str, user_name: str, display_id: str,
) -> dict:
    """One-way HITL → Salesforce: patch Case.OwnerId, post a Case Comment,
    post a Chatter feed item @mentioning the new owner. Returns a small
    status dict for the response envelope and the trace event."""
    pipe = db.get(Pipeline, task.pipeline_id) if task.pipeline_id else None
    case_id = getattr(pipe, "salesforce_case_id", None) if pipe else None
    if not case_id:
        return {"ok": False, "reason": "no_salesforce_case_on_pipeline"}
    try:
        from ..services import salesforce as sf_svc
        conn = sf_svc.get_active_connection(db)
        if conn is None:
            return {"ok": False, "reason": "no_active_salesforce_connection"}
        sf = sf_svc.client_for(conn)

        # 1. Patch Case Owner.
        sf.Case.update(case_id, {"OwnerId": user_id})

        # 2. Case Comment for the audit trail.
        sf.CaseComment.create({
            "ParentId": case_id,
            "CommentBody": (
                f"{display_id} claimed by {user_name} for review. "
                "Mirrored from the ZBrain HITL queue."
            ),
            "IsPublished": True,
        })

        # 3. Chatter @mention so the user's SF notification bell + mobile
        #    light up. Uses FeedItem with a mention element.
        try:
            sf.FeedItem.create({
                "ParentId": case_id,
                "Body": (
                    f"@[{user_id}] {display_id} has been routed to you for review. "
                    f"Source: ZBrain HITL queue."
                ),
            })
        except Exception:
            # Some orgs restrict Chatter writes to internal feed posters;
            # the Case Comment above already covers the audit need.
            pass

        log_event(
            db, task.pipeline_id or 0, "hitl", "salesforce_mirror",
            f"HITL assignment mirrored to Salesforce — Case {case_id} owner set to {user_name}",
            data={"task_id": task.id, "case_id": case_id, "user_id": user_id, "user_name": user_name},
        )
        return {"ok": True, "case_id": case_id, "owner_user_id": user_id, "case_url": sf_svc.record_url(db, case_id)}
    except Exception as ex:
        msg = f"{type(ex).__name__}: {str(ex)[:200]}"
        log_event(
            db, task.pipeline_id or 0, "hitl", "salesforce_mirror_error",
            f"HITL → Salesforce mirror failed: {msg}",
            data={"task_id": task.id, "case_id": case_id, "user_id": user_id, "error": msg},
        )
        return {"ok": False, "reason": msg}


@router.post("/{task_id}/resolve")
def resolve(task_id: int, body: Resolution, db: Session = Depends(get_db)):
    t = db.get(HitlTask, task_id)
    if not t:
        raise HTTPException(404)
    if t.status != "pending":
        raise HTTPException(400, "already resolved")

    t.status = "resolved"
    t.resolved_at = now()
    t.resolution = body.model_dump()

    fb = Feedback(
        pipeline_id=t.pipeline_id,
        stage="hitl",
        kind=body.action,
        note=body.note or "",
        data={"task_id": t.id, "edits": body.edits or {}, "reply_edited": bool(body.reply)},
    )
    db.add(fb)

    pipe = db.get(Pipeline, t.pipeline_id)
    if not pipe:
        db.commit()
        return {"ok": True}

    email = db.get(Email, pipe.email_id) if pipe.email_id else None
    payload = t.payload or {}

    if body.action in ("approve", "edit_and_approve"):
        extracted = pipe.extracted or {}
        if body.action == "edit_and_approve" and body.edits:
            extracted = {**extracted, **body.edits}
            pipe.extracted = extracted

        decision_action = (pipe.decision or {}).get("action")
        customer_id = payload.get("customer_id")
        applied_result: dict
        try:
            applied_result = _apply(db, action=decision_action, extracted=extracted, customer_id=customer_id)
            applied_result = {"applied": True, **applied_result} if "applied" not in applied_result else applied_result
        except Exception as e:
            applied_result = {"applied": False, "error": str(e)[:300]}

        reply = dict(pipe.reply or {})
        if body.reply:
            if body.reply.subject is not None:
                reply["subject"] = body.reply.subject
            if body.reply.body is not None:
                reply["body"] = body.reply.body
            reply["edited_by_csr"] = True

        attachment_names = [reply.get("soa_attachment")] if reply.get("soa_attachment") else []
        delivery: dict = {"delivery_status": "skipped", "provider_message_id": None, "error": None, "sent_via_account_id": None}
        recipient = (email.from_address if email else None) or (pipe.customer_match or {}).get("email")
        if recipient:
            delivery = email_outbound.send_reply(
                db,
                originating_email=email,
                to_address=recipient,
                subject=reply.get("subject") or "",
                body=reply.get("body") or "",
                attachments=[a for a in attachment_names if a],
            )
        else:
            delivery["error"] = "no recipient address on originating email"

        sent_ok = delivery.get("delivery_status") == "sent"
        reply["sent"] = sent_ok
        reply["sent_at"] = now().isoformat() if sent_ok else None
        reply["delivery_status"] = delivery.get("delivery_status")
        reply["provider_message_id"] = delivery.get("provider_message_id")
        reply["sent_via_account_id"] = delivery.get("sent_via_account_id")
        if delivery.get("error"):
            reply["send_error"] = delivery["error"]
        pipe.reply = reply

        pipe.execution = {
            **(pipe.execution or {}),
            "status": "applied" if applied_result.get("applied") else "apply_failed",
            "hitl_action": body.action,
            "applied": applied_result,
            "delivery": {k: delivery.get(k) for k in ("delivery_status", "provider_message_id", "sent_via_account_id", "error", "smtp_host")},
        }
        pipe.status = "completed"
        if email:
            email.status = "processed"

        applied = applied_result or {}
        order_ref = applied.get("order_number") or (pipe.extracted or {}).get("order_number")
        wo_ref = applied.get("wo_number") or (pipe.extracted or {}).get("work_order_number")
        try:
            from ..models import Order, WorkOrder

            order_row = db.query(Order).filter_by(order_number=order_ref).first() if order_ref else None
            wo_row = db.query(WorkOrder).filter_by(wo_number=wo_ref).first() if wo_ref else None
        except Exception:
            order_row, wo_row = None, None

        sp_filed_block = (reply or {}).get("sharepoint_filed") or {}
        soa_name = reply.get("soa_attachment")
        attachments_payload = []
        if soa_name:
            entry: dict = {"name": soa_name, "kind": "SOA"}
            if isinstance(sp_filed_block, dict) and sp_filed_block.get("web_url"):
                entry["sharepoint_url"] = sp_filed_block["web_url"]
                entry["sharepoint_folder"] = sp_filed_block.get("folder")
                entry["source"] = sp_filed_block.get("store") or "SharePoint"
            attachments_payload.append(entry)
        comm = CommunicationLog(
            customer_id=payload.get("customer_id"),
            pipeline_id=pipe.id,
            order_id=order_row.id if order_row else None,
            work_order_id=wo_row.id if wo_row else None,
            direction="outbound",
            channel="email",
            subject=reply.get("subject"),
            body=reply.get("body"),
            language=reply.get("language") or pipe.language,
            intent=pipe.intent,
            autonomy_tier=pipe.autonomy_tier,
            sent_by=f"CSR (HITL · {body.action})",
            csr_action=body.action,
            note=body.note,
            attachments=attachments_payload,
            delivery_status=delivery.get("delivery_status"),
            delivery_error=delivery.get("error"),
            provider_message_id=delivery.get("provider_message_id"),
            sent_via_account_id=delivery.get("sent_via_account_id"),
        )
        db.add(comm)

        # Build a clickable SF Case URL so the operator can open the live
        # case directly from the trace. The url helper falls back to None
        # when SF is not connected; the frontend hides the link in that
        # case rather than rendering a broken anchor.
        sf_case_url = None
        try:
            from ..services import salesforce as _sf_svc
            if pipe.salesforce_case_id:
                sf_case_url = _sf_svc.record_url(db, pipe.salesforce_case_id)
        except Exception:
            sf_case_url = None

        # Emit one trace event per post-approval action so the operator can
        # see, in the case timeline, exactly what happened after they ticked
        # Approve. The previous behaviour was a single opaque "approve"
        # event — operators correctly complained that they had to trust the
        # system without seeing the SF write, the comm log, or the final
        # status flip.

        # 1. Apply the action
        applied_ok = applied_result.get("applied") is not False and not applied_result.get("error")
        log_event(
            db, pipe.id, "execute", "applied",
            (
                f"Action '{(pipe.decision or {}).get('action') or 'noop'}' applied at CSR approval."
                if applied_ok
                else f"Action apply failed: {applied_result.get('error', 'unknown')}"
            ),
            data={
                "stage_resumed_by": "hitl_approve",
                "csr_action": body.action,
                "applied": applied_result,
                "salesforce_case_id": pipe.salesforce_case_id,
                "salesforce_case_url": sf_case_url,
            },
        )

        # 2. CommunicationLog row written
        log_event(
            db, pipe.id, "communicate", "comm_log",
            f"CommunicationLog row written (direction=outbound · subject='{(reply.get('subject') or '')[:80]}')",
            data={
                "tier": pipe.autonomy_tier,
                "csr_action": body.action,
                "subject": reply.get("subject"),
                "body_length": len(reply.get("body") or ""),
                "delivery_status": delivery.get("delivery_status"),
                "attachments_count": len(attachments_payload),
            },
        )

        # 3. Outbound send outcome
        if sent_ok:
            send_msg = f"Reply sent via SMTP (account #{delivery.get('sent_via_account_id')}) to {recipient or 'customer'}"
        elif delivery.get("delivery_status") in ("blocked_by_demo_lock", "blocked_by_kill_switch"):
            send_msg = (
                f"Reply queued in CommunicationLog (demo mode: outbound transmission is locked at "
                f"config.DEMO_TRANSMIT_LOCKED). No real email was sent to {recipient or 'customer'}; "
                "the case is fully processed and the audit trail is complete."
            )
        else:
            send_msg = f"Send failed: {delivery.get('error') or 'unknown SMTP error'}"
        log_event(
            db, pipe.id, "communicate", "send_attempted",
            send_msg,
            data={
                "delivery_status": delivery.get("delivery_status"),
                "provider_message_id": delivery.get("provider_message_id"),
                "sent_via_account_id": delivery.get("sent_via_account_id"),
                "error": delivery.get("error"),
                "recipient": recipient,
            },
        )

        # 4. Salesforce CaseComment summarizing the operator decision
        if sf_case_url:
            log_event(
                db, pipe.id, "execute", "sf_case_audit",
                f"Salesforce Case updated with operator audit (CaseComment + status). Open the case to verify.",
                data={
                    "salesforce_case_id": pipe.salesforce_case_id,
                    "salesforce_case_url": sf_case_url,
                    "csr_action": body.action,
                },
            )

        # 5. Pipeline + email completion
        log_event(
            db, pipe.id, "activity", "completed",
            f"Pipeline completed (csr_action={body.action}). Email marked processed; case closed in the HITL queue.",
            data={
                "pipeline_status": pipe.status,
                "email_status": email.status if email else None,
                "salesforce_case_url": sf_case_url,
            },
        )
    elif body.action == "reject":
        pipe.status = "rejected"
        pipe.execution = {**(pipe.execution or {}), "hitl_rejected": True, "note": body.note}
        if email:
            email.status = "rejected"
        log_event(db, pipe.id, "hitl", "reject", "CSR rejected", data={"note": body.note})

    db.commit()
    out: dict = {"ok": True}
    if body.action in ("approve", "edit_and_approve"):
        out["delivery"] = (pipe.execution or {}).get("delivery") or {}
        out["recipient"] = (email.from_address if email else None)
    return out


def _summary(db: Session, t: HitlTask, full: bool = False) -> dict:
    pipe = db.get(Pipeline, t.pipeline_id) if t.pipeline_id else None
    email = db.get(Email, pipe.email_id) if pipe and pipe.email_id else None
    decision_block = (pipe.decision if pipe else None) or {}
    owner_block = decision_block.get("owner") or {}
    out = {
        "id": t.id,
        "display_id": f"HITL-{t.id:05d}",
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "reason": t.reason,
        "status": t.status,
        "owner_label": owner_block.get("owner_label"),
        "owner_queue": owner_block.get("owner_queue"),
        "salesforce_owner_id": owner_block.get("salesforce_owner_id"),
        "track": decision_block.get("track"),
        "assignee": (
            {
                "user_id": t.assignee_user_id,
                "name": t.assignee_name,
                "queue": t.assignee_queue,
                "assigned_at": t.assigned_at.isoformat() if t.assigned_at else None,
                "assigned_by": t.assigned_by,
            }
            if t.assignee_user_id
            else None
        ),
        "pipeline": {
            "id": pipe.id if pipe else None,
            "intent": pipe.intent if pipe else None,
            "confidence": pipe.confidence if pipe else None,
            "autonomy_tier": pipe.autonomy_tier if pipe else None,
        }
        if pipe
        else None,
        "email": {
            "id": email.id,
            "subject": email.subject,
            "from": email.from_address,
            "language_hint": email.language_hint,
            **({"body": email.body, "received_at": email.received_at.isoformat() if email.received_at else None, "attachments": [a.get("name") for a in (email.attachments or [])]} if full else {}),
        }
        if email
        else None,
    }
    if full:
        out["payload"] = t.payload
        out["resolution"] = t.resolution
        out["reply"] = (pipe.reply if pipe else None) or {}
        out["execution"] = (pipe.execution if pipe else None) or {}
        out["customer_match"] = (pipe.customer_match if pipe else None) or {}
        out["delivery"] = ((pipe.execution or {}).get("delivery") if pipe else None) or {}
        # Surface the active SF instance URL so the CSR playbook in the UI
        # can build deep links (Open Account / Create Account / Search).
        try:
            from ..services import salesforce as sf_svc
            sf_conn = sf_svc.get_active_connection(db)
            url = (sf_conn.instance_url or "").rstrip("/") if sf_conn else None
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            out["salesforce_instance_url"] = url
        except Exception:
            out["salesforce_instance_url"] = None
    return out
