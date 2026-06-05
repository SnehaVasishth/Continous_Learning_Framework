"""Order Acceptance service — the consolidated owner of the AIOA interaction.

Replaces the previous synchronous in-Decide-Agent AIOA call. Everything
related to an order-acceptance round-trip lives in this one service:

  1. enqueue()           — Decide Agent inserts a request, pipeline parks
                           in `awaiting_aioa`. Returns immediately.
  2. sender background   — picks pending_send rows, POSTs to the
                           configured provider's webhook, marks as sent.
  3. callback receiver   — /api/aioa/callback/<slug> persists the response,
                           marks status=response_received.
  4. resumer background  — picks response_received rows, runs the
                           post-AIOA action inside this same service:
                              FAIL → compose CSR clarification draft,
                                     write HitlTask, flip pipeline to
                                     pending_hitl with the draft attached.
                              PASS → mark pipeline ready to continue
                                     (orchestrator picks it back up).
  5. timeout sweep       — rows in `sent` for longer than the provider's
                           timeout fall to `timed_out` and follow the
                           same fallout path as FAIL.

The pipeline never auto-advances out of `awaiting_aioa` on its own. Only
this service moves it forward.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AIOAProvider, AIOARequest, Email, HitlTask, Pipeline
from ..trace_log import log_event

log = logging.getLogger("aioa_service")


# Background loop cadences. Kept short so the demo feels live.
SENDER_INTERVAL_SEC = int(os.environ.get("AIOA_SENDER_INTERVAL_SEC", "10"))
RESUMER_INTERVAL_SEC = int(os.environ.get("AIOA_RESUMER_INTERVAL_SEC", "5"))
TIMEOUT_SWEEP_INTERVAL_SEC = int(os.environ.get("AIOA_TIMEOUT_INTERVAL_SEC", "60"))

_tasks: list[asyncio.Task] = []


# --------------------------------------------------------------------------
# Provider helpers
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_active_provider(db: Session) -> AIOAProvider | None:
    return db.query(AIOAProvider).filter(AIOAProvider.is_active.is_(True)).order_by(AIOAProvider.id.desc()).first()


def ensure_default_provider(db: Session) -> AIOAProvider:
    """Make sure at least one provider row exists so the queue has a target.

    The row is created unconfigured: empty outbound URL, no auth, default
    timeout. The operator configures the actual endpoint in Settings before
    requests can leave the queue.
    """
    p = db.query(AIOAProvider).order_by(AIOAProvider.id.asc()).first()
    if p is not None:
        return p
    p = AIOAProvider(
        slug="default",
        name="AIOA",
        outbound_url="",
        outbound_auth_scheme="none",
        outbound_auth_value=None,
        inbound_secret=secrets.token_urlsafe(32),
        timeout_seconds=1800,
        retry_max=3,
        retry_backoff_seconds=30,
        is_active=False,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# --------------------------------------------------------------------------
# Enqueue — called by Decide Agent
# --------------------------------------------------------------------------


def enqueue(
    db: Session,
    *,
    pipeline_id: int,
    request_payload: dict[str, Any],
) -> AIOARequest:
    """Insert a new AIOA request and park the pipeline in `awaiting_aioa`.

    Caller is the Decide Agent. After this returns, the pipeline must stop
    executing and the worker thread must release. The sender, callback, and
    resumer handle everything from here onward.
    """
    provider = ensure_default_provider(db)
    correlation_id = f"AIOA-{secrets.token_urlsafe(10)}"
    req = AIOARequest(
        correlation_id=correlation_id,
        pipeline_id=pipeline_id,
        provider_id=provider.id,
        status="pending_send",
        request_payload=request_payload,
    )
    db.add(req)
    # Park the pipeline. This is the contract the rest of the system relies
    # on: while a pipeline is `awaiting_aioa`, no stage advances it; only
    # the AIOA service can flip the status to pending_hitl (FAIL) or back to
    # running (PASS, for the orchestrator to pick up).
    pipe = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if pipe is not None:
        pipe.status = "awaiting_aioa"
    db.commit()
    db.refresh(req)
    log_event(
        db, pipeline_id, "decide", "substep_done",
        f"3.0c AIOA queued — correlation_id={correlation_id}, provider={provider.name}",
        data={
            "substep": "3.0c",
            "label": "AIOA queued",
            "correlation_id": correlation_id,
            "provider_id": provider.id,
            "provider_name": provider.name,
            "outbound_url": provider.outbound_url,
            "timeout_seconds": provider.timeout_seconds,
            "request_preview": _preview(request_payload),
        },
    )
    return req


def _preview(payload: dict, max_chars: int = 400) -> str:
    try:
        s = json.dumps(payload, default=str)
    except Exception:
        s = str(payload)
    return s[:max_chars] + ("..." if len(s) > max_chars else "")


# --------------------------------------------------------------------------
# Sender background loop
# --------------------------------------------------------------------------


def _send_one(db: Session, req: AIOARequest) -> None:
    provider = db.query(AIOAProvider).filter(AIOAProvider.id == req.provider_id).first()
    # If no provider, or provider inactive, or URL unconfigured: leave the
    # row in pending_send. The timeout sweep (measured from created_at)
    # will eventually surface it as timed_out, which produces a clean CSR
    # fallout path. We never set status='error' on the queue UI.
    if provider is None or not provider.is_active or not (provider.outbound_url or "").strip():
        return
    if provider.outbound_url.strip().lower().startswith("http") is False:
        return

    callback_url = _build_callback_url(provider)
    payload = {
        "correlation_id": req.correlation_id,
        "callback_url": callback_url,
        "callback_secret_header": "X-AIOA-Signature",
        "request": req.request_payload,
    }
    headers = {"Content-Type": "application/json"}
    if provider.outbound_auth_scheme == "bearer" and provider.outbound_auth_value:
        headers["Authorization"] = f"Bearer {provider.outbound_auth_value}"
    elif provider.outbound_auth_scheme == "api_key" and provider.outbound_auth_value:
        headers["X-API-Key"] = provider.outbound_auth_value

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(provider.outbound_url, headers=headers, json=payload)
        if 200 <= resp.status_code < 300:
            req.status = "sent"
            req.sent_at = _now()
            req.last_error = None
            req.retry_count = 0
            provider.last_send_at = _now()
            db.commit()
            log_event(
                db, req.pipeline_id, "decide", "substep_done",
                f"3.0c AIOA sent — POST {provider.outbound_url} → HTTP {resp.status_code}",
                data={
                    "substep": "3.0c.sent",
                    "label": "AIOA sent",
                    "correlation_id": req.correlation_id,
                    "outbound_url": provider.outbound_url,
                    "http_status": resp.status_code,
                },
            )
        else:
            # Non-2xx: keep waiting. Note the last response code internally
            # for diagnostics but don't surface it as a queue error.
            req.last_error = f"HTTP {resp.status_code}"
            db.commit()
            log.info("aioa send waiting on retry for %s: HTTP %s", req.correlation_id, resp.status_code)
    except Exception as ex:
        # Network / DNS / TLS errors: keep waiting. The timeout sweep
        # eventually rolls this to timed_out from created_at.
        req.last_error = f"{type(ex).__name__}"
        db.commit()
        log.info("aioa send waiting on retry for %s: %s", req.correlation_id, type(ex).__name__)


def _build_callback_url(provider: AIOAProvider) -> str:
    """Build the public callback URL AIOA should POST to when it returns a
    decision. Resolution order: explicit env override, then the configured
    APP_BASE_URL, then the live cloudflared tunnel URL. We do not fall back
    to 127.0.0.1 because the operator would paste that into AIOA's config
    and the callback would never reach this app from outside the machine.
    """
    public_base = (os.environ.get("AIOA_CALLBACK_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not public_base:
        public_base = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    if not public_base:
        try:
            from . import tunnel as _tunnel
            tunnel_url = (_tunnel.current_url() or "").strip().rstrip("/")
            if tunnel_url:
                public_base = tunnel_url
        except Exception:
            pass
    if not public_base:
        # Nothing public available. Return a marker the UI can detect and
        # render as "configure a public URL first" instead of pasting a
        # private 127.0.0.1 address.
        return ""
    return f"{public_base}/api/aioa/callback/{provider.slug}"


def _sender_pass() -> dict:
    db = SessionLocal()
    out = {"sent": 0, "retried": 0, "errored": 0}
    try:
        pending = db.query(AIOARequest).filter(AIOARequest.status == "pending_send").order_by(AIOARequest.id.asc()).limit(20).all()
        for req in pending:
            before = req.status
            _send_one(db, req)
            if req.status == "sent":
                out["sent"] += 1
            elif req.status == "error":
                out["errored"] += 1
            elif req.status == before:
                out["retried"] += 1
    finally:
        db.close()
    return out


# --------------------------------------------------------------------------
# Callback handling — called by the inbound endpoint
# --------------------------------------------------------------------------


def receive_callback(db: Session, *, provider_slug: str, body: dict, headers: dict) -> AIOARequest:
    """Persist an AIOA callback. The endpoint route does auth verification
    and calls this. We accept, persist, return; resumer picks it up."""
    provider = db.query(AIOAProvider).filter(AIOAProvider.slug == provider_slug).first()
    if provider is None:
        raise ValueError(f"No AIOA provider with slug '{provider_slug}'")
    cid = (body or {}).get("correlation_id")
    if not cid:
        raise ValueError("callback missing correlation_id")
    req = db.query(AIOARequest).filter(AIOARequest.correlation_id == cid).first()
    if req is None:
        raise ValueError(f"No AIOA request found for correlation_id={cid}")
    if req.status in ("processed", "response_received"):
        # Idempotent — just return the existing row.
        return req
    decision = (body.get("decision") or "").upper()
    if decision not in ("PASS", "FAIL"):
        raise ValueError(f"callback decision must be PASS or FAIL, got {decision!r}")
    fallout_reasons = body.get("fallout_reasons") or []
    if not isinstance(fallout_reasons, list):
        fallout_reasons = [str(fallout_reasons)]
    req.response_payload = body
    req.decision = decision
    req.fallout_reasons = fallout_reasons
    req.status = "response_received"
    req.response_received_at = _now()
    provider.last_callback_at = _now()
    db.commit()
    log_event(
        db, req.pipeline_id, "decide", "substep_done",
        f"3.0c AIOA callback received — {decision} ({len(fallout_reasons)} fallout reason{'s' if len(fallout_reasons) != 1 else ''})",
        data={
            "substep": "3.0c.callback",
            "label": "AIOA callback received",
            "correlation_id": cid,
            "decision": decision,
            "fallout_reasons": fallout_reasons,
            "evidence": (body or {}).get("evidence") or {},
            "source": (body or {}).get("source") or "callback",
        },
    )
    # log_event only flushes — explicitly commit so the event is visible on
    # the trace timeline. The FastAPI route handler's get_db closes the
    # session without auto-commit, so without this the AIOA callback row
    # arrives but the corresponding trace event disappears.
    db.commit()
    return req


# --------------------------------------------------------------------------
# CSR clarification draft — runs when FAIL/timeout
# --------------------------------------------------------------------------


# AIOA check codes mapped to a plain-language customer-facing ask. Codes
# NOT in this map are treated as internal-only and are NOT included in any
# customer-facing draft (compliance, credit, ECCN, etc. are handled by the
# appropriate internal team, not by emailing the customer).
_CHECK_TO_CUSTOMER_ASK: dict[str, str] = {
    "schema_completeness": "Could you confirm the missing header field on the purchase order so we can complete acceptance",
    "price_consistency": "Could you confirm the unit prices on the purchase order match the quote you intended to reference",
    "quantity_consistency": "Could you confirm the line-item quantities on the purchase order",
    "partial_or_full_po_detection": "Could you confirm the complete list of line items for this order",
    "authorised_signatory": "Could you confirm the contact who issued this purchase order on your account",
    "payment_terms_match": "Could you confirm the payment terms on this purchase order",
}


def _compose_csr_draft(db: Session, req: AIOARequest, *, timed_out: bool = False) -> dict:
    """Build the CSR-facing artefact when AIOA returns FAIL or times out.

    On timeout: no customer-facing draft is generated. The customer has
    nothing to clarify in a timeout situation; this becomes an internal
    note for the CSR to investigate, retry, or escalate.

    On FAIL: AIOA's fallout reasons are filtered through a check-code map
    so only customer-actionable items become bullets. Compliance, credit,
    ECCN, and similar internal-only reasons are summarized for the CSR in
    a separate internal note inside the draft, but never appear in the
    customer-facing body.
    """
    pipe = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
    extracted = (pipe.extracted if pipe else {}) or {}
    customer_match = (pipe.customer_match if pipe else {}) or {}
    customer_name = customer_match.get("customer_name") or "team"
    intent = (pipe.intent if pipe else "") or "order"
    po = extracted.get("po_number") or extracted.get("customer_po")
    quote_no = extracted.get("quote_number")

    reasons = req.fallout_reasons or []

    if timed_out:
        subject = f"Internal review — order acceptance validation did not return in time"
        if po:
            subject += f" (PO {po})"
        body = (
            f"Order acceptance validation did not return a response for {customer_name}'s order "
            f"within the configured timeout window. CSR action required:\n\n"
            "- Review the inbound and any attached documents for clarity.\n"
            "- Retry the validation if the upstream service is back online.\n"
            "- If retry is not viable, complete the order acceptance manually or escalate.\n\n"
            "No customer-facing message has been drafted; the customer has not been notified. "
            "Reach out to the customer only after the internal review is complete."
        )
        if po:
            body += f"\n\nPO: {po}"
        if quote_no:
            body += f"\nQuote: {quote_no}"
        return {
            "subject": subject[:160],
            "body": body,
            "kind": "aioa_timeout_internal_review",
            "internal_only": True,
            "source": "aioa_service",
            "correlation_id": req.correlation_id,
        }

    # FAIL path: separate customer-actionable from internal-only reasons.
    customer_bullets: list[str] = []
    internal_bullets: list[str] = []
    for r in reasons[:10]:
        if isinstance(r, dict):
            code = (r.get("check") or "").strip().lower()
            detail = (r.get("detail") or "").strip()
            ask = _CHECK_TO_CUSTOMER_ASK.get(code)
            if ask:
                tail = f": {detail}" if detail else ""
                customer_bullets.append(f"- {ask}{tail}.")
            else:
                internal_bullets.append(f"- {code or 'review item'}: {detail}")
        else:
            # Bare strings get treated as internal only; the customer
            # never sees raw fallout strings.
            internal_bullets.append(f"- {str(r)[:200]}")

    if not customer_bullets:
        # Nothing customer-actionable. Internal review note only.
        subject = f"Internal review — order acceptance flagged this {intent.replace('_', ' ')}"
        if po:
            subject += f" (PO {po})"
        body = (
            f"Order acceptance flagged this order for review on grounds that don't have a "
            f"customer-facing ask attached. CSR to investigate internally:\n\n"
            + "\n".join(internal_bullets[:8])
            + "\n\nNo customer-facing message has been drafted. Reach out to the customer only "
            "if the internal review concludes that clarification is needed."
        )
        if po:
            body += f"\n\nPO: {po}"
        if quote_no:
            body += f"\nQuote: {quote_no}"
        return {
            "subject": subject[:160],
            "body": body,
            "kind": "aioa_internal_review",
            "internal_only": True,
            "source": "aioa_service",
            "correlation_id": req.correlation_id,
        }

    # Customer-facing draft.
    opener = (
        f"Hi {customer_name},\n\nThank you for your recent order. Before we can complete "
        "acceptance, we need to confirm a few details on the purchase order:"
    )
    closer = (
        "\n\nCould you please reply with the requested details or send an updated document. "
        "Your order is on hold pending this clarification.\n\n"
        "Thanks,\nKeysight Sales Operations"
    )
    body = opener + "\n\n" + "\n".join(customer_bullets)
    if po:
        body += f"\n\nFor reference, the PO we're working from is {po}."
    if quote_no:
        body += f" The quote referenced is {quote_no}."
    body += closer
    subject = f"Action needed on your {intent.replace('_', ' ')} request"
    if po:
        subject += f" (PO {po})"
    return {
        "subject": subject[:160],
        "body": body,
        "kind": "aioa_fallout_clarification",
        "internal_only": False,
        "internal_notes": internal_bullets if internal_bullets else None,
        "source": "aioa_service",
        "correlation_id": req.correlation_id,
    }


# --------------------------------------------------------------------------
# Resumer background loop
# --------------------------------------------------------------------------


def _process_one_response(db: Session, req: AIOARequest) -> None:
    pipe = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
    if pipe is None:
        req.status = "error"
        req.last_error = "Pipeline not found at resume time"
        db.commit()
        return

    timed_out = (req.status == "timed_out")

    if req.decision == "PASS":
        # PASS — record the decision and re-submit the pipeline to the
        # worker pool so it continues from Stage 3 onward. The orchestrator
        # is idempotent: Stage 3's AIOA gate detects the recorded PASS and
        # skips re-enqueue, falling through to Stage 3.1 (confidence) and
        # Stage 4 (execute). Without an explicit pool.submit the pipeline
        # would sit in `running` with no worker, and the email_sync zombie
        # sweep would mark it as `error` within 10 seconds.
        decision = dict(pipe.decision or {})
        decision["aioa"] = {
            "decision": "PASS",
            "correlation_id": req.correlation_id,
            "received_at": req.response_received_at.isoformat() if req.response_received_at else None,
        }
        pipe.decision = decision
        pipe.status = "running"
        req.status = "processed"
        req.processed_at = _now()
        db.commit()
        log_event(
            db, req.pipeline_id, "decide", "substep_done",
            f"3.0c AIOA PASS — pipeline resumed, re-submitted to worker pool",
            data={
                "substep": "3.0c.resumed",
                "label": "AIOA PASS resume",
                "correlation_id": req.correlation_id,
            },
        )
        db.commit()
        try:
            from .pipeline_pool import get_pool
            get_pool().submit(pipeline_id=req.pipeline_id, email_id=pipe.email_id)
        except Exception as ex:
            log.warning("aioa resumer failed to re-submit pipeline %s: %s", req.pipeline_id, ex)
        return

    # FAIL or TIMEOUT — compose the appropriate artefact and park the
    # pipeline on the HITL queue. Timeout produces an internal-only note;
    # FAIL produces either a customer-facing draft (when there are
    # customer-actionable items) or an internal-only note.
    draft = _compose_csr_draft(db, req, timed_out=timed_out)
    req.csr_draft = draft
    req.status = "processed"
    req.processed_at = _now()

    # Mark the pipeline as awaiting human review with the draft on the
    # pipeline's reply for the trace UI, and write a HitlTask for the
    # HITL page.
    pipe.status = "pending_hitl"
    reply = dict(pipe.reply or {})
    reply["csr_draft"] = draft
    reply["csr_draft_subject"] = draft.get("subject")
    reply["csr_draft_body"] = draft.get("body")
    pipe.reply = reply
    decision = dict(pipe.decision or {})
    decision["aioa"] = {
        "decision": "FAIL",
        "correlation_id": req.correlation_id,
        "fallout_reasons": req.fallout_reasons,
        "received_at": req.response_received_at.isoformat() if req.response_received_at else None,
    }
    pipe.decision = decision

    hitl = HitlTask(
        pipeline_id=req.pipeline_id,
        reason="aioa_fallout",
        payload={
            "correlation_id": req.correlation_id,
            "fallout_reasons": req.fallout_reasons,
            "draft": draft,
        },
        status="pending",
    )
    db.add(hitl)
    db.commit()

    log_event(
        db, req.pipeline_id, "decide", "substep_done",
        f"3.0c AIOA FAIL — CSR clarification draft composed, pipeline parked for HITL",
        data={
            "substep": "3.0c.csr_draft",
            "label": "AIOA FAIL → CSR draft",
            "correlation_id": req.correlation_id,
            "fallout_reasons": req.fallout_reasons,
            "draft_subject": draft.get("subject"),
        },
    )


def _resumer_pass() -> dict:
    db = SessionLocal()
    out = {"resumed_pass": 0, "resumed_fail": 0, "errors": 0}
    try:
        rows = db.query(AIOARequest).filter(AIOARequest.status == "response_received").order_by(AIOARequest.id.asc()).limit(20).all()
        for req in rows:
            try:
                _process_one_response(db, req)
                if req.decision == "PASS":
                    out["resumed_pass"] += 1
                else:
                    out["resumed_fail"] += 1
            except Exception:
                out["errors"] += 1
                log.exception("aioa resumer error for %s", req.correlation_id)
    finally:
        db.close()
    return out


# --------------------------------------------------------------------------
# Timeout sweep
# --------------------------------------------------------------------------


def _timeout_sweep_pass() -> dict:
    """Surface rows that have been waiting longer than the provider's
    timeout, measured from `created_at`. When a row times out we
    advance the parked pipeline into `awaiting_hitl` so the case is
    visible on the HITL queue (matching the AIOAQueue.tsx contract),
    sync the inbound Email status, compose the internal CSR review
    draft, create a HitlTask, and emit a trace event so the timeline
    shows the transition."""
    db = SessionLocal()
    out = {"timed_out": 0, "backfilled": 0}
    try:
        # Two cohorts:
        #   (a) rows still in pending_send/sent that have aged past the
        #       provider's timeout window. These are freshly timing out.
        #   (b) rows already at status=timed_out whose pipeline is still
        #       parked at awaiting_aioa. These are pre-existing timeouts
        #       that landed before the sweep learned how to advance the
        #       pipeline. We forward them through the same path so the
        #       backlog drains without manual intervention.
        rows_active = (
            db.query(AIOARequest)
            .filter(AIOARequest.status.in_(("pending_send", "sent")))
            .order_by(AIOARequest.id.asc())
            .limit(50)
            .all()
        )
        # Backfill cohort: capped to keep each sweep tick bounded.
        rows_backfill = (
            db.query(AIOARequest)
            .join(Pipeline, Pipeline.id == AIOARequest.pipeline_id)
            .filter(AIOARequest.status == "timed_out")
            .filter(Pipeline.status == "awaiting_aioa")
            .order_by(AIOARequest.id.asc())
            .limit(50)
            .all()
        )

        backfill_ids = {r.id for r in rows_backfill}
        for req in rows_active + rows_backfill:
            is_backfill = req.id in backfill_ids
            provider = db.query(AIOAProvider).filter(AIOAProvider.id == req.provider_id).first()
            if provider is None:
                continue
            timeout_secs = provider.timeout_seconds or 1800
            created_at = req.created_at
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed = (_now() - created_at).total_seconds()
            if not is_backfill and elapsed < timeout_secs:
                continue
            req.status = "timed_out"

            # Advance the parked pipeline into the HITL queue so the
            # operator sees the case. Sync the inbound Email row too.
            pipe = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
            prior_pipeline_status = pipe.status if pipe is not None else None
            if pipe is not None and pipe.status == "awaiting_aioa":
                pipe.status = "awaiting_hitl"
                email = (
                    db.query(Email).filter(Email.id == pipe.email_id).first()
                    if pipe.email_id is not None
                    else None
                )
                if email is not None:
                    email.status = "awaiting_hitl"

                # Compose the internal-review CSR draft (timed_out=True
                # produces the internal review variant; no customer-facing
                # message is generated) and write a HitlTask so the case
                # surfaces on the HITL queue too. This mirrors the FAIL
                # path that the resumer takes when AIOA responds with FAIL,
                # which is what AIOAQueue.tsx promises on timeout.
                try:
                    draft = _compose_csr_draft(db, req, timed_out=True)
                except Exception:
                    draft = {}
                req.csr_draft = draft or {}
                req.processed_at = _now()

                # Surface the draft on the pipeline reply blob for the
                # trace UI, and stamp the AIOA outcome on the decision
                # blob so the timeline shows the timeout.
                reply = dict(pipe.reply or {})
                if draft:
                    reply["csr_draft"] = draft
                    reply["csr_draft_subject"] = draft.get("subject")
                    reply["csr_draft_body"] = draft.get("body")
                pipe.reply = reply
                decision = dict(pipe.decision or {})
                decision["aioa"] = {
                    "decision": None,
                    "outcome": "timed_out",
                    "correlation_id": req.correlation_id,
                    "elapsed_seconds": int(elapsed),
                    "timeout_seconds": timeout_secs,
                }
                pipe.decision = decision

                # Idempotency guard: do not double-write a HitlTask if a
                # prior sweep already created one for this AIOA correlation.
                existing_hitl = (
                    db.query(HitlTask)
                    .filter(HitlTask.pipeline_id == req.pipeline_id)
                    .filter(HitlTask.reason == "aioa_timeout")
                    .filter(HitlTask.status == "pending")
                    .first()
                )
                if existing_hitl is None:
                    hitl = HitlTask(
                        pipeline_id=req.pipeline_id,
                        reason="aioa_timeout",
                        payload={
                            "correlation_id": req.correlation_id,
                            "elapsed_seconds": int(elapsed),
                            "timeout_seconds": timeout_secs,
                            "draft": draft,
                        },
                        status="pending",
                    )
                    db.add(hitl)
            db.commit()

            # Resolve provider readiness so the trace event carries the
            # actual reason the AIOA call could not complete. The operator
            # reads this directly at the parking stage rather than chasing
            # a banner on a side page. When the provider is offline or
            # mis-configured, the message says so explicitly; when the
            # provider is healthy but slow, the message reflects that.
            provider_readiness: dict = {}
            try:
                from ..models import AIOAProvider
                p = db.query(AIOAProvider).filter(AIOAProvider.is_active.is_(True)).first()
                if p is None:
                    provider_readiness = {
                        "configured_provider": None,
                        "is_active": False,
                        "outbound_url": None,
                        "fix": "Activate an AIOA provider in Governance > Integrations so future cases can complete order acceptance.",
                    }
                else:
                    provider_readiness = {
                        "configured_provider": p.name,
                        "is_active": True,
                        "outbound_url": p.outbound_url or None,
                        "fix": (
                            "Provider is active but outbound_url is empty. Set the AIOA outbound URL in Governance > Integrations to resume validations."
                            if not (p.outbound_url or "").strip()
                            else "Provider is active and configured. The remote AIOA service did not respond within the timeout window. Investigate the AIOA endpoint health, then replay this request from the HITL task or re-enqueue."
                        ),
                    }
            except Exception as ex:
                provider_readiness = {"resolution_error": str(ex)[:200]}

            stopped_reason_human = (
                "AIOA provider is not configured. Pipeline stopped at substep 3.0c (Order Acceptance handoff) because there is no active provider to call. Operator action: activate the provider, then replay the HITL task."
                if not provider_readiness.get("is_active")
                else (
                    "AIOA provider is configured but the outbound URL is empty. Pipeline stopped at substep 3.0c because the request had no endpoint to reach. Operator action: set the outbound URL in Integrations, then replay."
                    if provider_readiness.get("is_active") and not provider_readiness.get("outbound_url")
                    else f"AIOA call did not respond within {timeout_secs}s. Pipeline stopped at substep 3.0c. Operator action: investigate the AIOA endpoint, then replay the HITL task."
                )
            )

            log_event(
                db, req.pipeline_id, "decide", "stage_blocked",
                f"Stopped at substep 3.0c (Order Acceptance handoff): {stopped_reason_human}",
                data={
                    "substep": "3.0c.timeout",
                    "stopped_at_substep": "3.0c",
                    "stopped_reason": stopped_reason_human,
                    "provider_readiness": provider_readiness,
                    "correlation_id": req.correlation_id,
                    "elapsed_seconds": int(elapsed),
                    "timeout_seconds": timeout_secs,
                    "prior_pipeline_status": prior_pipeline_status,
                    "new_pipeline_status": pipe.status if pipe is not None else None,
                    "resumed_via": "hitl",
                    "stages_not_run": ["execute", "communicate"],
                },
            )
            if is_backfill:
                out["backfilled"] += 1
            else:
                out["timed_out"] += 1
    finally:
        db.close()
    return out


# --------------------------------------------------------------------------
# Background task wiring
# --------------------------------------------------------------------------


async def _sender_loop() -> None:
    log.info("aioa_sender started — tick every %ss", SENDER_INTERVAL_SEC)
    await asyncio.sleep(3)
    while True:
        try:
            r = await asyncio.to_thread(_sender_pass)
            if r.get("sent") or r.get("errored"):
                log.info("aioa_sender tick: %s", r)
        except Exception:
            log.exception("aioa_sender tick crashed")
        await asyncio.sleep(SENDER_INTERVAL_SEC)


async def _resumer_loop() -> None:
    log.info("aioa_resumer started — tick every %ss", RESUMER_INTERVAL_SEC)
    await asyncio.sleep(4)
    while True:
        try:
            r = await asyncio.to_thread(_resumer_pass)
            if r.get("resumed_pass") or r.get("resumed_fail") or r.get("errors"):
                log.info("aioa_resumer tick: %s", r)
        except Exception:
            log.exception("aioa_resumer tick crashed")
        await asyncio.sleep(RESUMER_INTERVAL_SEC)


async def _timeout_loop() -> None:
    log.info("aioa_timeout_sweep started — tick every %ss", TIMEOUT_SWEEP_INTERVAL_SEC)
    await asyncio.sleep(30)
    while True:
        try:
            r = await asyncio.to_thread(_timeout_sweep_pass)
            if r.get("timed_out") or r.get("backfilled"):
                log.info("aioa_timeout_sweep tick: %s", r)
        except Exception:
            log.exception("aioa_timeout_sweep tick crashed")
        await asyncio.sleep(TIMEOUT_SWEEP_INTERVAL_SEC)


def start() -> list[asyncio.Task]:
    global _tasks
    _tasks = [
        asyncio.create_task(_sender_loop()),
        asyncio.create_task(_resumer_loop()),
        asyncio.create_task(_timeout_loop()),
    ]
    return _tasks


def stop() -> None:
    global _tasks
    for t in _tasks:
        try:
            t.cancel()
        except Exception:
            pass
    _tasks = []
