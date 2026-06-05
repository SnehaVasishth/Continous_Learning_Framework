"""Stage 3 — Decision & Confidence Scoring (3 sub-steps).

Per ADR-015 in SOLUTION.md (revised once Stage 2.5 absorbed reconcile):

  3.1  Confidence formula            — weighted base score
  3.2  Business rules (KB-driven)    — predicates evaluated, caps applied
  3.3  Final tier decision           — L4 / L3 / L2 picked

Reconcile_checks runs in Stage 2.5 (Cross-system validation). Stage 3 reads
ctx.reconcile and feeds the issues into the rubric's blocking/soft caps.

Each sub-step emits substep_start / substep_done trace events so the UI
shows a clear timeline with input/output per step.
"""
from __future__ import annotations

import time

from ..models import Pipeline
from ..trace_log import log_event
from .base import AgentContext, AgentResult, BaseAgent
from .decide import run_decide
from .tools.business_rules_eval_tool import BusinessRulesEvalTool


_PO_INTENTS = {"po_intake", "quote_to_order"}


# Intents that do NOT carry a PO/Quote identifier on the Salesforce Case
# (so the exact-match SOQL queries can't catch a duplicate). For these
# intents the semantic LLM matcher is the only reliable signal that a prior
# Case on the same Account is the same business request.
_LLM_MATCH_INTENTS = {
    "hold_release",
    "delivery_change",
    "order_status",
    "quote_revision",
    "wo_status_inquiry",
    "wo_update_request",
    "ssd_change_request",
    "service_contract_request",
    "general_inquiry",
}


def _llm_match_duplicate_case(
    ctx,
    *,
    intent: str,
    extracted: dict,
    intake: dict,
    candidates: list[dict],
) -> dict | None:
    """Semantic duplicate detector. Asks the LLM whether any of the candidate
    Salesforce Cases pulled from the same Account represents the SAME
    customer request as the inbound email — even when no exact identifier
    matches (the typical hold_release / delivery_change / status-inquiry
    shape, where the Case doesn't carry a PO/Quote field).

    Returns the matched candidate dict with `match_signals` extended to
    include `llm_semantic_duplicate` and an `llm_confidence` field, or None
    if the LLM finds no semantic match.
    """
    if not candidates:
        return None
    # Build a compact, JSON-safe candidate list for the prompt. We cap each
    # field length so the prompt stays bounded even with a Description that
    # contains the full prior email body.
    compact = []
    for idx, c in enumerate(candidates[:8]):
        compact.append({
            "idx": idx,
            "case_id": c.get("case_id"),
            "case_number": c.get("case_number"),
            "status": c.get("status"),
            "stage": c.get("stage"),
            "request_type": c.get("request_type") or c.get("type"),
            "sub_type": c.get("sub_type"),
            "category": c.get("category"),
            "subject": (c.get("subject") or "")[:240],
            "description": (c.get("description") or "")[:1200],
            "po_number": c.get("po_number"),
            "wo_number": c.get("wo_number"),
            "created_at": c.get("created_at"),
            "match_signals": c.get("match_signals") or [],
        })

    # Inbound side — give the model the SAME identifier fields plus the
    # original email subject so it can compare apples-to-apples.
    email = ctx.email if isinstance(ctx.email, dict) else {}
    inbound = {
        "intent": intent,
        "subject": (email.get("subject") or intake.get("subject_clean") or "")[:240],
        "snippet": (email.get("body") or email.get("snippet") or "")[:1500],
        "extracted": {
            k: extracted.get(k)
            for k in (
                "order_number", "po_number", "quote_number",
                "work_order_number", "wo_number",
                "customer_name", "customer_code",
                "requested_action", "change_type", "sub_type",
            )
            if extracted.get(k) is not None
        },
    }

    system = (
        "You are the duplicate-detection step for an enterprise sales-ops "
        "automation pipeline. Decide whether any of the candidate Salesforce "
        "Cases (already on the same customer account) is THE SAME business "
        "request as the inbound email. A request is the same when it concerns "
        "the same underlying record (same order, work order, quote, or "
        "contract) AND the same requested action. Two cases about different "
        "orders, or one about a hold-release and another about a delivery "
        "change on the same order, are NOT duplicates. Resending or "
        "rephrasing the same ask IS a duplicate. Reply strictly with the "
        "specified JSON object."
    )
    user = (
        "Inbound email:\n"
        + __import__("json").dumps(inbound, ensure_ascii=False)
        + "\n\nCandidate Salesforce Cases on the same account:\n"
        + __import__("json").dumps(compact, ensure_ascii=False)
        + "\n\nReturn JSON of the form: "
        + '{"match_idx": <int|null>, "confidence": <0..1>, "reason": "<one short sentence>"}'
        + " where match_idx is the idx of the duplicate Case (or null if none qualify)."
    )

    try:
        from ..services.openai_client import ask_openai_text
        parsed, _raw, _meta = ask_openai_text(
            system=system,
            user=user,
            json_only=True,
            temperature=0.0,
            max_retries=1,
            stage_hint="decide.ccc_duplicate_match",
        )
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    midx = parsed.get("match_idx")
    if midx is None or not isinstance(midx, int) or midx < 0 or midx >= len(compact):
        return None
    confidence = float(parsed.get("confidence") or 0.0)
    if confidence < 0.70:
        return None
    picked = candidates[midx]
    picked = dict(picked)
    sigs = list(picked.get("match_signals") or [])
    if "llm_semantic_duplicate" not in sigs:
        sigs.append("llm_semantic_duplicate")
    picked["match_signals"] = sigs
    picked["llm_confidence"] = confidence
    picked["llm_reason"] = (parsed.get("reason") or "")[:240]
    return picked


def _find_thread_parent_ccc(ctx) -> dict | None:
    """If this email is a reply to a prior message we processed, find the
    parent pipeline's Salesforce Case Id so it can be a candidate.

    Looks at the local `emails` table's `in_reply_to` / `email_references`
    headers (populated by the email_sync poller) and joins back to the
    pipeline that originally handled the parent message_id.
    """
    try:
        from ..models import Email, Pipeline
        from sqlalchemy import or_
        if not ctx.email or not ctx.email.get("from"):
            return None
        # Need the inbound email's headers — pull from DB.
        cur_email = (
            ctx.db.query(Email)
            .filter(Email.id == (ctx.email.get("id") if isinstance(ctx.email.get("id"), int) else None))
            .first()
            if isinstance(ctx.email.get("id"), int)
            else None
        )
        if cur_email is None:
            # Fall back: look up via the pipeline_id.
            pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
            if pipe and pipe.email_id:
                cur_email = ctx.db.get(Email, pipe.email_id)
        if cur_email is None:
            return None
        in_reply_to = getattr(cur_email, "in_reply_to", None)
        references_raw = getattr(cur_email, "email_references", None) or ""
        candidate_ids: list[str] = []
        if in_reply_to:
            candidate_ids.append(in_reply_to.strip())
        if references_raw:
            for r in references_raw.split():
                r = r.strip().strip("<>")
                if r and r not in candidate_ids:
                    candidate_ids.append(r)
        if not candidate_ids:
            return None
        parent_email = (
            ctx.db.query(Email)
            .filter(Email.message_id.in_(candidate_ids))
            .order_by(Email.id.desc())
            .first()
        )
        if parent_email is None or parent_email.pipeline_id is None:
            return None
        parent_pipe = ctx.db.get(Pipeline, parent_email.pipeline_id)
        if parent_pipe is None or not parent_pipe.salesforce_case_id:
            return None
        return {
            "case_id": parent_pipe.salesforce_case_id,
            "case_number": None,
            "request_number": None,
            "status": "In Progress",  # best-effort: thread parent assumed live
            "stage": "automation_in_progress",
            "type": parent_pipe.intent,
            "track": (parent_pipe.decision or {}).get("track") if isinstance(parent_pipe.decision, dict) else None,
            "po_number": None,
            "wo_number": None,
            "account_id": None,
            "created_at": parent_pipe.started_at.isoformat() if parent_pipe.started_at else None,
            "match_signals": [],
        }
    except Exception:
        return None


def _category_from_intent(intent: str | None) -> str | None:
    """Map an intent to its CCC Category. Mirrors orchestrator._category_from_intent."""
    if not intent:
        return None
    mapping = {
        "po_intake": "Trade Order",
        "quote_to_order": "Trade Order",
        "trade_change_order": "Trade Order",
        "hold_release": "Trade Order",
        "service_order": "Service",
        "wo_status_inquiry": "Service",
        "wo_update_request": "Service",
        "ssd_change_request": "Service",
        "service_contract_request": "Service",
        "delivery_change": "Trade Order",
        "general_inquiry": "Inquiry",
    }
    return mapping.get(intent, "Inquiry")


def _create_new_ccc(
    ctx: AgentContext,
    intake: dict,
    extracted: dict,
    customer_match: dict,
    *,
    prior_case: dict | None = None,
) -> None:
    """Create the Salesforce Case for this pipeline NOW that intake + extract
    have produced real fields. Logs a clear `decide.substep_done` event and a
    `ccc.created` event so the operator can see where + how the Case was
    minted in the Trace UI."""
    from ..services import salesforce_cases as _sf_cases
    from ..services import salesforce as _sf_svc
    from datetime import datetime
    pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
    if pipe is None:
        return
    request_number = f"CCC-{datetime.utcnow().strftime('%Y%m%d')}-{ctx.pipeline_id:05d}"
    intent = (intake or {}).get("intent")
    category = _category_from_intent(intent)
    track = (intake or {}).get("track_hint")
    account_id = (customer_match or {}).get("salesforce_account_id")
    sub_type = (extracted or {}).get("sub_type") or (extracted or {}).get("change_type")

    case_state = {
        "request_number": request_number,
        "email_id": pipe.email_id,
        "pipeline_id": ctx.pipeline_id,
        "customer_id": pipe.email_id and ctx.db.get(__import__("app.models", fromlist=["Email"]).Email, pipe.email_id).customer_id if False else None,
        "status": "new",
        "stage": "automation_in_progress",
        "owner_label": "ai_agent",
        "category": category,
        "request_type": intent,
        "sub_type": sub_type,
        "track": track,
        "fallout_reason": None,
    }
    # Best-effort: customer_id from email row
    email_subject = ""
    email_snippet = ""
    try:
        from ..models import Email
        if pipe.email_id:
            e = ctx.db.get(Email, pipe.email_id)
            if e:
                case_state["customer_id"] = e.customer_id
                email_subject = (e.subject or "")[:240]
                email_snippet = ((e.body or "")[:2000]).strip()
    except Exception:
        pass

    # Build a Description that future duplicate-detection passes (the LLM
    # semantic matcher in Stage 3.0.a') can read back. Includes the original
    # customer subject, a body snippet, and the salient extracted identifiers.
    desc_lines: list[str] = []
    if email_subject:
        desc_lines.append(f"Subject: {email_subject}")
    desc_lines.append(f"Intent: {intent or '-'}")
    if track:
        desc_lines.append(f"Track: {track}")
    ident_pairs = []
    for key in ("po_number", "order_number", "quote_number", "work_order_number",
                "wo_number", "customer_po", "requested_action", "change_type"):
        v = (extracted or {}).get(key)
        if isinstance(v, str) and v.strip():
            ident_pairs.append(f"{key}={v.strip()}")
    if ident_pairs:
        desc_lines.append("Identifiers: " + ", ".join(ident_pairs))
    if email_snippet:
        desc_lines.append("")
        desc_lines.append("Email body:")
        desc_lines.append(email_snippet)
    description_notes = "\n".join(desc_lines)[:32000]

    try:
        res = _sf_cases.create_case(
            ctx.db,
            account_id=account_id,
            email_id=case_state.get("email_id"),
            pipeline_id=case_state.get("pipeline_id"),
            request_number=case_state["request_number"],
            category=case_state.get("category"),
            request_type=case_state.get("request_type"),
            sub_type=case_state.get("sub_type"),
            track=case_state.get("track"),
            status="new",
            stage="automation_in_progress",
            owner_label="ai_agent",
            fallout_reason=None,
            notes=description_notes,
        )
    except Exception as e:
        log_event(
            ctx.db, ctx.pipeline_id, "decide", "substep_done",
            f"3.0 CCC Request creation failed: {type(e).__name__}: {str(e)[:140]}",
            data={"substep": "3.0", "error": str(e)[:240], "ccc_action": "new"},
        )
        return
    if not res.get("ok"):
        log_event(
            ctx.db, ctx.pipeline_id, "decide", "substep_done",
            f"3.0 CCC Request creation failed: {res.get('reason')}",
            data={"substep": "3.0", "error": res.get("reason"), "ccc_action": "new"},
        )
        return
    case_id = res.get("case_id")
    pipe.salesforce_case_id = case_id
    ctx.db.commit()
    from ..services import salesforce as _sf_svc
    sf_case_url = _sf_svc.record_url(ctx.db, case_id)
    sf_account_url = _sf_svc.record_url(ctx.db, account_id) if account_id else None
    # Two events: one in `ccc` stage for the audit timeline, one in `decide`
    # substep so the Trace UI's Stage 3 panel shows it as a substep result.
    log_event(
        ctx.db, ctx.pipeline_id, "ccc", "created",
        f"Salesforce Case {request_number} created",
        data={
            "request_number": request_number,
            "status": "new",
            "stage": "automation_in_progress",
            "salesforce_case_id": case_id,
            "category": category,
            "request_type": intent,
            "track": track,
            "account_id": account_id,
            "trigger": "stage3_resolution",
            "replaces_prior_case": prior_case.get("case_id") if prior_case else None,
            "links": {
                "salesforce_case_url": sf_case_url,
                "salesforce_account_url": sf_account_url,
            },
        },
    )
    log_event(
        ctx.db, ctx.pipeline_id, "decide", "substep_done",
        f"3.0 CCC Request created: Case {res.get('case_number') or '-'} "
        f"({request_number}) · category={category} · track={track or '-'}",
        data={
            "substep": "3.0",
            "ccc_action": "new" if not prior_case else "new_after_cancelled",
            "created_case_id": case_id,
            "case_number": res.get("case_number"),
            "request_number": request_number,
            "category": category,
            "request_type": intent,
            "track": track,
            "account_id": account_id,
            "prior_cancelled_case_id": prior_case.get("case_id") if prior_case else None,
            "links": {
                "salesforce_case_url": sf_case_url,
                "salesforce_account_url": sf_account_url,
            },
        },
    )


def _resolve_cap(fired_rule: dict) -> tuple[float | None, str]:
    """Phase D3: derive (cap_value, severity_label) from a fired rule.

    Resolution order:
      1. Explicit numeric `cap_at` field (any float in [0.0, 1.0])
      2. severity field as numeric string ("0.65", "0.85") — same numeric
         interpretation as cap_at
      3. Severity enum:
           "hard_block"   → (0.0, "hard_block")
           "cap_at_0.70"  → (0.70, "cap_at_0.70")
           "cap_at_0.88"  → (0.88, "cap_at_0.88")
           "warn"         → (None, "warn")  # no cap applied, just trace

    Returns (None, label) when the rule should produce a trace entry but
    not move confidence (warn / unknown enum).
    """
    cap_at = fired_rule.get("cap_at")
    if cap_at is not None:
        try:
            v = float(cap_at)
            v = max(0.0, min(1.0, v))
            return v, f"cap_at_{v:.2f}"
        except Exception:
            pass

    sev = fired_rule.get("severity")
    if isinstance(sev, (int, float)):
        v = max(0.0, min(1.0, float(sev)))
        return v, f"cap_at_{v:.2f}"
    if isinstance(sev, str):
        # numeric string e.g. "0.65"
        s = sev.strip()
        try:
            v = float(s)
            v = max(0.0, min(1.0, v))
            return v, f"cap_at_{v:.2f}"
        except ValueError:
            pass
        if s == "hard_block":
            return 0.0, "hard_block"
        if s == "cap_at_0.70":
            return 0.70, "cap_at_0.70"
        if s == "cap_at_0.88":
            return 0.88, "cap_at_0.88"
        if s == "warn":
            return None, "warn"
    return None, "warn"


class Stage3DecideAgent(BaseAgent):
    """Computes confidence + autonomy tier, then applies KB business rules and floor caps."""

    stage_key = "decide"
    stage_label = "Decision & Confidence Scoring"
    tools = [BusinessRulesEvalTool()]

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        tool_results = []
        guardrails: list[str] = []
        try:
            # === CCC Request resolution — multi-signal lookup-or-create ===
            # Gathers candidate Cases by PO#, WO#, Quote#, customer's open
            # recent Cases, and email-thread parent. Scores each and either
            # adopts (>=0.80), flags ambiguity (0.40-0.79, penalty fed to
            # Stage 3.1 feasibility gate), or creates new (<0.40).
            ccc_resolution: dict = {
                "candidates": [],
                "selected": None,
                "ambiguous": False,
                "ambiguity_count": 0,
                "decision": "new",
                "feasibility_penalty": None,
            }
            try:
                from ..services import salesforce_cases as _sf_cases
                from ..models import Pipeline as _Pipeline
                ext = ctx.extracted or {}
                intake = ctx.intake or {}
                cm = ctx.customer_match or {}
                po_num = ext.get("po_number") or ext.get("customer_po")
                wo_num = ext.get("wo_number") or ext.get("work_order_number")
                quote_num = ext.get("quote_number") or ext.get("matched_quote_number")
                account_id = cm.get("salesforce_account_id")
                pipe = ctx.db.get(_Pipeline, ctx.pipeline_id)

                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_start",
                    "3.0.a Collect CCC candidates: querying Salesforce by PO# / WO# / Quote# / customer-open",
                    data={
                        "substep": "3.0.a",
                        "po_number": po_num,
                        "wo_number": wo_num,
                        "quote_number": quote_num,
                        "customer_account_id": account_id,
                    },
                )
                candidates = _sf_cases.find_candidate_ccc_requests(
                    ctx.db,
                    po_number=po_num,
                    wo_number=wo_num,
                    quote_number=quote_num,
                    customer_account_id=account_id,
                )
                # Email-thread parent: look up the prior pipeline for this
                # email's in_reply_to header and pull its SF Case if present.
                thread_parent = _find_thread_parent_ccc(ctx)
                if thread_parent:
                    # Promote/merge thread parent into the candidate list.
                    by_id = {c["case_id"]: c for c in candidates}
                    if thread_parent["case_id"] in by_id:
                        by_id[thread_parent["case_id"]]["match_signals"].append("email_thread_parent")
                    else:
                        thread_parent["match_signals"] = ["email_thread_parent"]
                        candidates.append(thread_parent)

                candidates = _sf_cases.score_ccc_candidates(
                    candidates,
                    extracted_po=po_num,
                    extracted_wo=wo_num,
                    extracted_quote=quote_num,
                    customer_account_id=account_id,
                )
                # Bonus weight for email-thread parent (applied after scoring).
                for c in candidates:
                    if "email_thread_parent" in (c.get("match_signals") or []):
                        c["score"] = round(c.get("score", 0.0) + 0.50, 3)
                        c["score_breakdown"].append(("email_thread_parent", 0.50))

                # === 3.0.a' LLM semantic duplicate match ============================
                # For intents whose Case carries no PO/Quote field (hold_release,
                # delivery_change, *status*, *inquiry*), exact-match SOQL alone
                # can't catch a re-sent customer email. We ask the LLM to scan
                # the same-account candidate set and tell us if any prior Case
                # represents the same business request. A high-confidence match
                # gets a 0.55 score bonus so it crosses the 0.80 adopt floor.
                intent_for_match = (intake or {}).get("intent") or ""
                llm_picked = None
                if intent_for_match in _LLM_MATCH_INTENTS and candidates:
                    try:
                        llm_picked = _llm_match_duplicate_case(
                            ctx,
                            intent=intent_for_match,
                            extracted=ext,
                            intake=intake,
                            candidates=candidates,
                        )
                    except Exception as _lex:
                        log_event(
                            ctx.db, ctx.pipeline_id, "decide", "substep_done",
                            f"3.0.a' LLM duplicate matcher failed (non-fatal): {type(_lex).__name__}",
                            data={"substep": "3.0.a'", "error": str(_lex)[:240]},
                        )
                if llm_picked:
                    # LLM-confident match overrides the numeric scoring path.
                    # We give it a large bonus so it tops the candidate list
                    # AND set a flag so the adopt branch below treats this as
                    # confident regardless of the closed-case penalty.
                    for c in candidates:
                        if c.get("case_id") == llm_picked.get("case_id"):
                            sigs = list(c.get("match_signals") or [])
                            if "llm_semantic_duplicate" not in sigs:
                                sigs.append("llm_semantic_duplicate")
                            c["match_signals"] = sigs
                            c["llm_confidence"] = llm_picked.get("llm_confidence")
                            c["llm_reason"] = llm_picked.get("llm_reason")
                            bonus = 1.20
                            c["score"] = round((c.get("score") or 0.0) + bonus, 3)
                            (c.setdefault("score_breakdown", [])).append(("llm_semantic_duplicate", bonus))
                            c["llm_overrides_status_penalty"] = True
                            break
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0.a' LLM duplicate match: Case {llm_picked.get('case_number') or llm_picked.get('case_id')} "
                        f"(confidence {llm_picked.get('llm_confidence')}) — {llm_picked.get('llm_reason')}",
                        data={
                            "substep": "3.0.a'",
                            "matched_case_id": llm_picked.get("case_id"),
                            "matched_case_number": llm_picked.get("case_number"),
                            "confidence": llm_picked.get("llm_confidence"),
                            "reason": llm_picked.get("llm_reason"),
                            "intent": intent_for_match,
                        },
                    )
                elif intent_for_match in _LLM_MATCH_INTENTS:
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0.a' LLM duplicate match: no semantic duplicate found "
                        f"across {len(candidates)} candidate(s)",
                        data={
                            "substep": "3.0.a'",
                            "matched": False,
                            "candidate_count": len(candidates),
                            "intent": intent_for_match,
                        },
                    )

                candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)

                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_done",
                    f"3.0.a Collected {len(candidates)} CCC candidate(s) "
                    + (f"(top score {candidates[0]['score']})" if candidates else "(no matches)"),
                    data={
                        "substep": "3.0.a",
                        "candidate_count": len(candidates),
                        "candidates": candidates[:10],
                    },
                )

                ccc_resolution["candidates"] = candidates[:10]

                # --- 3.0.b: pick the best / detect ambiguity ---
                AMBIGUOUS_FLOOR = 0.40
                # Per Trade Order Entry spec (Step 6): adopt when ≥ 80%
                CONFIDENT_FLOOR = 0.80
                top = candidates[0] if candidates else None
                ambiguous_set = [c for c in candidates if c.get("score", 0.0) >= 0.50]
                ambiguous = len(ambiguous_set) > 1 or (top is not None and AMBIGUOUS_FLOOR <= top.get("score", 0.0) < CONFIDENT_FLOOR)
                ccc_resolution["ambiguous"] = ambiguous
                ccc_resolution["ambiguity_count"] = len(ambiguous_set)

                if top and top.get("score", 0.0) >= CONFIDENT_FLOOR:
                    # Confident adopt
                    sf_status = (top.get("status") or "").lower()
                    llm_override = bool(top.get("llm_overrides_status_penalty"))
                    if sf_status == "cancelled":
                        ccc_action = "new"
                    elif sf_status == "closed":
                        # LLM-detected semantic duplicate of an already-closed
                        # Case is the "customer re-sent the same request"
                        # pattern — re-attach to the existing Case rather than
                        # cloning, so the audit trail stays consolidated.
                        ccc_action = "update" if llm_override else "clone_change_order"
                    else:
                        ccc_action = "update"
                    ccc_resolution["selected"] = top
                    ccc_resolution["decision"] = ccc_action
                    if ccc_action in {"update", "clone_change_order"} and pipe is not None:
                        pipe.salesforce_case_id = top.get("case_id")
                        pipe.existing_case_id = top.get("case_id")
                        pipe.existing_case_status = top.get("status")
                        pipe.duplicate_detected = True
                        pipe.ccc_action = ccc_action
                        ctx.db.commit()
                        log_event(
                            ctx.db, ctx.pipeline_id, "decide", "substep_done",
                            f"3.0.c CCC Request adopted: Case {top.get('case_number')} "
                            f"(status={top.get('status')}, score={top.get('score')}); ccc_action={ccc_action}",
                            data={
                                "substep": "3.0.c",
                                "ccc_action": ccc_action,
                                "selected": top,
                                "ambiguity_count": len(ambiguous_set),
                            },
                        )
                        guardrails.append(f"existing_ccc_detected:{ccc_action}")
                    else:
                        # Cancelled existing case → mint a fresh one but note the link.
                        if pipe is not None:
                            pipe.existing_case_id = top.get("case_id")
                            pipe.existing_case_status = top.get("status")
                            pipe.duplicate_detected = True
                            pipe.ccc_action = "new"
                            ctx.db.commit()
                        _create_new_ccc(ctx, intake, ext, cm, prior_case=top)
                        guardrails.append("prior_cancelled_ccc_replaced")
                elif top and top.get("score", 0.0) >= AMBIGUOUS_FLOOR:
                    # Ambiguous: pick the top candidate but flag for feasibility penalty
                    ccc_resolution["selected"] = top
                    ccc_resolution["decision"] = "ambiguous_adopt"
                    ccc_resolution["feasibility_penalty"] = 0.65  # cap composite at 0.65
                    if pipe is not None:
                        pipe.salesforce_case_id = top.get("case_id")
                        pipe.existing_case_id = top.get("case_id")
                        pipe.existing_case_status = top.get("status")
                        pipe.duplicate_detected = True
                        pipe.ccc_action = "update"
                        ctx.db.commit()
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0.c CCC Request resolution AMBIGUOUS — picked Case {top.get('case_number')} "
                        f"(score={top.get('score')}), {len(ambiguous_set)} candidate(s) ≥ 0.50 — feasibility capped at 0.65",
                        data={
                            "substep": "3.0.c",
                            "ccc_action": "update",
                            "selected": top,
                            "ambiguity_count": len(ambiguous_set),
                            "feasibility_cap": 0.65,
                        },
                    )
                    guardrails.append("ccc_resolution_ambiguous")
                else:
                    # Below floor → create new
                    ccc_resolution["decision"] = "new"
                    if pipe is not None:
                        pipe.ccc_action = "new"
                        ctx.db.commit()
                    _create_new_ccc(ctx, intake, ext, cm, prior_case=None)

                # Stash the resolution on ctx so Stage 3.1 feasibility gate
                # can read it and apply the cap when ambiguous.
                if isinstance(ctx.decision, dict):
                    ctx.decision["ccc_resolution"] = ccc_resolution
                else:
                    ctx.decision = {"ccc_resolution": ccc_resolution}
            except Exception as _ex:
                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_done",
                    f"3.0 CCC Request resolution failed (non-fatal): {type(_ex).__name__}: {str(_ex)[:160]}",
                    data={"substep": "3.0", "error": str(_ex)[:240], "ccc_action": "new"},
                )

            # === 3.0d Preliminary owner assignment ===
            # Per the Trade Order Entry spec, ownership is assigned BEFORE OA
            # Validation (Step 8 → Step 9). We compute a track-based owner now
            # so the Case has a queue/owner before AIOA fires; the final 3.4
            # refinement may override based on AIOA outcome (e.g. AIOA_FAIL →
            # AI OA Fallout queue). The preliminary owner is written to the SF
            # Case so a CSR opening the Case mid-flight sees a real assignee.
            try:
                from .track_classifier import classify_tracks, assign_ccc_owner
                from ..models import Pipeline as _Pipeline
                _prelim_intent = (ctx.intake or {}).get("intent") or ""
                _prelim_fcnv = bool((ctx.intake or {}).get("fcnv_review_required"))
                _prelim_tracks = classify_tracks(
                    intent=_prelim_intent,
                    fcnv_review_required=_prelim_fcnv,
                    aioa_outcome=None,  # AIOA hasn't run yet
                )
                _prelim_owner = assign_ccc_owner(
                    primary_track=_prelim_tracks["primary_track"],
                    autonomy_tier="L4_AUTO",  # tentative — refined at 3.4
                    fcnv_review_required=_prelim_fcnv,
                    aioa_outcome=None,
                    is_aioa_handoff=False,
                    is_no_reply=False,
                    db=ctx.db,
                )
                if not isinstance(ctx.decision, dict):
                    ctx.decision = {}
                ctx.decision.setdefault("preliminary_owner", _prelim_owner)
                ctx.decision["track"] = _prelim_tracks["primary_track"]
                ctx.decision["tracks_touched"] = _prelim_tracks["all_tracks_touched"]
                # Push preliminary owner to the SF Case so it has a queue/owner
                # BEFORE AIOA fires — matches the spec ordering.
                _prelim_pipe = ctx.db.get(_Pipeline, ctx.pipeline_id)
                if _prelim_pipe and _prelim_pipe.salesforce_case_id and _prelim_owner.get("owner_label"):
                    try:
                        from ..services import salesforce_cases as _sf_cases
                        _sf_cases.update_case(
                            ctx.db,
                            case_id=_prelim_pipe.salesforce_case_id,
                            owner_label=_prelim_owner.get("owner_label"),
                            track=_prelim_tracks["primary_track"],
                        )
                    except Exception:
                        pass
                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_done",
                    f"3.0d Preliminary owner assignment — {_prelim_owner.get('owner_label')} ({_prelim_owner.get('owner_queue') or 'default'}); refined at 3.4 after AIOA",
                    data={
                        "substep": "3.0d",
                        "label": "Preliminary owner assignment (pre-AIOA)",
                        "primary_track": _prelim_tracks["primary_track"],
                        "tracks_touched": _prelim_tracks["all_tracks_touched"],
                        "preliminary_owner": _prelim_owner,
                    },
                )

                # === 3.0e SLA target — when the CCC should close ===
                # Spec Step 18: "Route request to appropriate regional queues
                # and track SLA / completion milestones." We stamp a target
                # close-by datetime based on (intent × tier) and post it as a
                # CaseComment so the CSR sees their deadline. A background
                # monitor can flag breaches later.
                try:
                    from datetime import datetime, timedelta, timezone
                    sla_intent = (ctx.intake or {}).get("intent") or ""
                    sla_hours = {
                        "po_intake": 4,
                        "quote_to_order": 4,
                        "trade_change_order": 8,
                        "service_order": 12,
                        "wo_status_inquiry": 1,
                        "wo_update_request": 8,
                        "service_contract_request": 24,
                        "ssd_change_request": 48,
                    }.get(sla_intent, 24)
                    sla_due_at = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
                    if _prelim_pipe and _prelim_pipe.salesforce_case_id:
                        from ..services import salesforce_cases as _sf_cases
                        _sf_cases.add_case_comment(
                            ctx.db,
                            _prelim_pipe.salesforce_case_id,
                            body=(
                                f"⏱ SLA target: close by {sla_due_at.isoformat(timespec='minutes')} "
                                f"({sla_hours}h from receipt · intent={sla_intent})\n"
                                f"• Region track: {_prelim_tracks['primary_track']}\n"
                                f"• Owner queue:  {_prelim_owner.get('owner_queue') or 'default'}\n"
                                f"• Tier (preliminary): L4_AUTO"
                            ),
                        )
                    ctx.decision["sla"] = {
                        "due_at": sla_due_at.isoformat(),
                        "window_hours": sla_hours,
                        "intent": sla_intent,
                    }
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0e SLA target — close by {sla_due_at.isoformat(timespec='minutes')} ({sla_hours}h window)",
                        data={
                            "substep": "3.0e",
                            "label": "SLA target stamped",
                            "due_at": sla_due_at.isoformat(),
                            "window_hours": sla_hours,
                            "intent": sla_intent,
                        },
                    )
                except Exception as _sla_ex:
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0e SLA target failed (non-fatal): {type(_sla_ex).__name__}",
                        data={"substep": "3.0e", "error": str(_sla_ex)[:200]},
                    )
            except Exception as _ex:
                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_done",
                    f"3.0d Preliminary owner assignment failed (non-fatal): {type(_ex).__name__}",
                    data={"substep": "3.0d", "error": str(_ex)[:200]},
                )

            # === v1.1 TASK-5 START === Routing resolver (disty + magic SKUs).
            try:
                from . import routing_resolver
                from ..models import Pipeline as _Pipeline
                routing = routing_resolver.resolve_routing(
                    email=ctx.email or {},
                    extracted=ctx.extracted or {},
                    customer_match=ctx.customer_match or {},
                    intake_ctx=ctx.intake or {},
                )
                if routing.get("routing_target"):
                    pipe = ctx.db.get(_Pipeline, ctx.pipeline_id)
                    if pipe:
                        pipe.routing_target = routing.get("routing_target")
                        pipe.routing_basis = routing.get("basis_rule_key")
                        ctx.db.commit()
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0b Routing → {routing.get('routing_target')} "
                        f"(rule: {routing.get('basis_rule_label')})",
                        data={"substep": "3.0b", **routing},
                    )
                    guardrails.append(f"routing:{routing.get('basis_rule_key')}")
                else:
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        "3.0b Routing → default queue (no routing rule fired)",
                        data={"substep": "3.0b", **routing},
                    )
            except Exception as _ex:
                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_done",
                    f"3.0b Routing resolver failed (non-fatal): {type(_ex).__name__}",
                    data={"substep": "3.0b", "error": str(_ex)[:200]},
                )
            # === v1.1 TASK-5 END ===

            # ----------------------------------------------------------------
            # 3.0c  AIOA validation — async handoff to the external Keysight
            #       AI Order Acceptance service via the Order Acceptance
            #       service (aioa_service). The pipeline parks in
            #       `awaiting_aioa` and stops; the post-AIOA work (CSR draft
            #       on FAIL, resume on PASS) runs inside aioa_service when
            #       the callback arrives.
            # ----------------------------------------------------------------
            aioa_response: dict | None = None
            # Idempotency gate — if a prior AIOA decision has already been
            # recorded for this pipeline (set by aioa_service._process_one_response
            # when a PASS callback fires), do NOT enqueue a fresh AIOA request.
            # Without this, every resumer-triggered re-run would re-enqueue
            # and park the pipeline at awaiting_aioa again, producing an
            # infinite back-and-forth.
            #
            # Read from the persisted Pipeline.decision row, not ctx.decision —
            # the orchestrator builds ctx with an empty decision dict on each
            # run_pipeline call, so ctx.decision is always empty here on the
            # AIOA-resume re-entry.
            _pipe_for_aioa = ctx.db.get(Pipeline, ctx.pipeline_id)
            persisted_decision = (_pipe_for_aioa.decision or {}) if _pipe_for_aioa else {}
            existing_aioa = persisted_decision.get("aioa") if isinstance(persisted_decision, dict) else None
            # Mirror onto ctx.decision so downstream stages and trace events see it.
            if isinstance(existing_aioa, dict):
                _merged = dict(ctx.decision or {})
                _merged["aioa"] = existing_aioa
                ctx.decision = _merged
            if isinstance(existing_aioa, dict) and (existing_aioa.get("decision") or "").upper() == "PASS":
                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "substep_done",
                    f"3.0c AIOA handoff — skipped (prior PASS decision already recorded, correlation_id={existing_aioa.get('correlation_id')})",
                    data={
                        "substep": "3.0c",
                        "applies": False,
                        "skipped_reason": "prior_aioa_pass_recorded",
                        "prior_decision": "PASS",
                        "correlation_id": existing_aioa.get("correlation_id"),
                    },
                )
                # Skip Stage 3.0c enqueue entirely and continue to Stage 3.1
                # (four-gate confidence) and Stage 3.3 (tier decision).
                pass  # Fall through to Stage 3.1
            else:
                try:
                    from ..services import aioa_mock
                    from ..services import aioa_service
                    aioa_should_call, aioa_reason = aioa_mock.should_call_aioa(
                        intent=ctx.intake.get("intent") or "",
                        extracted=ctx.extracted or {},
                        email_attachments=(ctx.email or {}).get("attachments") or [],
                    )
                    if aioa_should_call:
                        log_event(
                            ctx.db, ctx.pipeline_id, "decide", "substep_start",
                            "3.0c AIOA handoff — building request and enqueuing to Order Acceptance service",
                            data={"substep": "3.0c", "label": "AIOA handoff (async)",
                                  "applies": True, "reason": aioa_reason,
                                  "ownership": "AIOA (external Keysight app)"},
                        )
                        aioa_request = aioa_mock.build_aioa_request(
                            pipeline_id=ctx.pipeline_id,
                            intent=ctx.intake.get("intent") or "",
                            customer_code=(ctx.customer_match or {}).get("customer_code"),
                            extracted=ctx.extracted or {},
                            reconcile_result=ctx.reconcile,
                        )
                        req_row = aioa_service.enqueue(
                            ctx.db,
                            pipeline_id=ctx.pipeline_id,
                            request_payload=aioa_request,
                        )
                        # Stash a marker so the orchestrator knows to halt and
                        # the trace UI can show "awaiting AIOA response".
                        decision_marker = dict(ctx.decision or {})
                        decision_marker["aioa"] = {
                            "status": "awaiting_response",
                            "correlation_id": req_row.correlation_id,
                            "enqueued_at": req_row.created_at.isoformat() if req_row.created_at else None,
                        }
                        ctx.decision = decision_marker
                        # Mark the agent's own output so the orchestrator can
                        # detect the pause without re-querying the DB.
                        self._aioa_paused = True
                        self._aioa_correlation_id = req_row.correlation_id
                        # Return early — no four-gate confidence, no tier yet;
                        # those run after the callback as part of the resume.
                        return AgentResult(
                            stage="decide",
                            output={"decision": ctx.decision},
                            tool_results=tool_results,
                            guardrails_fired=guardrails,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                        )
                    else:
                        log_event(
                            ctx.db, ctx.pipeline_id, "decide", "substep_done",
                            f"3.0c AIOA handoff — not applicable ({aioa_reason})",
                            data={"substep": "3.0c", "applies": False, "reason": aioa_reason},
                        )
                except Exception as _ex:
                    log_event(
                        ctx.db, ctx.pipeline_id, "decide", "substep_done",
                        f"3.0c AIOA enqueue failed (non-fatal): {type(_ex).__name__}",
                        data={"substep": "3.0c", "error": str(_ex)[:200]},
                    )

            # ----------------------------------------------------------------
            # 3.1  Confidence — four-gate model with min(gates) composite
            # ----------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_start",
                "3.1 Four-gate confidence — Classification, Extraction, Entity Resolution, Action Feasibility; composite = min(gates)",
                data={"substep": "3.1", "label": "Four-gate confidence"},
            )
            _prior_ccc_res = (ctx.decision or {}).get("ccc_resolution") if isinstance(ctx.decision, dict) else None
            base_decision = run_decide(
                intake=ctx.intake,
                extracted=ctx.extracted,
                customer_match_score=float(ctx.customer_match.get("score") or 0.0),
                reconcile_result=ctx.reconcile,
                aioa_result=aioa_response,
                ccc_resolution=_prior_ccc_res,
                db=ctx.db,
            )
            # Surface the threshold KB lookup as its own trace event so the
            # Trace UI shows whether tiering ran on the global default or on
            # an admin-promoted per-intent override. Demo-critical: this is
            # how a client sees a Continuous-Learning promotion actually
            # affecting a live case.
            _kb_thr_src = base_decision.get("kb_thresholds_source") or {}
            if _kb_thr_src.get("source") == "kb":
                log_event(
                    ctx.db, ctx.pipeline_id, "decide", "kb_threshold_applied",
                    f"Per-intent threshold loaded from KB threshold/{_kb_thr_src.get('key')} v{_kb_thr_src.get('version')}",
                    data={"substep": "3.1", "kb_thresholds_source": _kb_thr_src},
                )
            confidence = float(base_decision.get("confidence") or 0.0)
            ctx.decision = dict(base_decision)
            # Re-attach the resolution so downstream stages (and the Trace UI)
            # can read it from ctx.decision.
            if _prior_ccc_res:
                ctx.decision["ccc_resolution"] = _prior_ccc_res
            base_signals = base_decision.get("signals") or {}
            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_done",
                f"3.1 Four-gate confidence computed — composite={confidence:.3f} (min of gates)",
                data={
                    "substep": "3.1",
                    "base_confidence": confidence,
                    "signals": base_signals,
                    "gates_named": [
                        "classification",
                        "extraction",
                        "entity_resolution",
                        "action_feasibility",
                    ],
                    "composite_rule": "min(gate scores)",
                },
            )

            # ----------------------------------------------------------------
            # 3.2  Business rules + floor caps (KB-driven)
            # ----------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_start",
                "3.2 Business rules — evaluating KB business_rules predicates against this context",
                data={"substep": "3.2", "label": "Business rules"},
            )
            rules_res = self.invoke_tool(ctx, "business_rules_eval")
            tool_results.append(rules_res)
            fired_rules = (rules_res.data.get("fired") if rules_res.ok else []) or []

            intent = ctx.intake.get("intent") or ""
            extracted = ctx.extracted or {}
            cust_score = float(ctx.customer_match.get("score") or 0.0)
            line_items = extracted.get("line_items") or []
            if not isinstance(line_items, list):
                line_items = []

            applied_caps: list[dict] = []
            confidence_before_caps = confidence

            if intent in _PO_INTENTS and not extracted.get("po_number"):
                if confidence > 0.4:
                    applied_caps.append({"kind": "floor_cap", "from": confidence, "to": 0.4, "reason": "missing po_number on po/q2o intent"})
                    confidence = 0.4
                    guardrails.append("floor_cap_0.40_missing_po_number")
            if intent in _PO_INTENTS and not line_items:
                if confidence > 0.4:
                    applied_caps.append({"kind": "floor_cap", "from": confidence, "to": 0.4, "reason": "empty line_items on po/q2o intent"})
                    confidence = 0.4
                    guardrails.append("floor_cap_0.40_empty_line_items")
            if cust_score < 0.5:
                if confidence > 0.55:
                    applied_caps.append({"kind": "floor_cap", "from": confidence, "to": 0.55, "reason": f"customer_match score {cust_score:.2f} < 0.5"})
                    confidence = 0.55
                    guardrails.append("floor_cap_0.55_customer_match_below_0.5")
            elif cust_score < 0.7:
                if confidence > 0.7:
                    applied_caps.append({"kind": "floor_cap", "from": confidence, "to": 0.7, "reason": f"customer_match score {cust_score:.2f} < 0.7"})
                    confidence = 0.7
                    guardrails.append("floor_cap_0.70_customer_match_below_0.7")

            dry_run_rules: list[dict] = []
            for r in fired_rules:
                key = r.get("key") or "<rule>"
                if r.get("dry_run"):
                    # Phase D4: dry-run rules report only — no cap applied.
                    dry_run_rules.append(r)
                    guardrails.append(f"dry_run:{key}")
                    continue
                cap_value, sev_label = _resolve_cap(r)
                if cap_value is None:
                    # warn / unknown — trace only.
                    guardrails.append(f"{sev_label}:{key}")
                    continue
                if cap_value <= 0.0:
                    # Hard block: rule forces L2 full HITL review regardless of
                    # how the four-gate composite scored. We cap confidence at
                    # 0.30 (deep L2) instead of 0.00 so the dashboard surfaces
                    # the actual reason ("hard_block: <rule>") rather than a
                    # bare 0% that reads as a broken calculator. The block is
                    # absolute — the tier is still L2_HITL via tier_for() —
                    # but the displayed number is honest about why.
                    applied_caps.append({"kind": "rule_cap", "rule": key, "from": confidence, "to": 0.30, "severity": sev_label})
                    confidence = 0.30
                    guardrails.append(f"hard_block:{key}")
                    continue
                if confidence > cap_value:
                    applied_caps.append({"kind": "rule_cap", "rule": key, "from": confidence, "to": cap_value, "severity": sev_label})
                    confidence = cap_value
                guardrails.append(f"{sev_label}:{key}")

            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_done",
                f"3.2 Business rules evaluated — {len(fired_rules)} fired, {len(applied_caps)} cap(s) applied"
                + (f", {len(dry_run_rules)} dry-run" if dry_run_rules else ""),
                data={
                    "substep": "3.2",
                    "rules_evaluated_count": (rules_res.data.get("rules_evaluated_count") if rules_res.ok else None),
                    "fired_count": len(fired_rules),
                    "fired_rules": fired_rules,
                    "applied_caps": applied_caps,
                    "dry_run_rules": dry_run_rules,
                    "confidence_before_caps": confidence_before_caps,
                    "confidence_after_caps": confidence,
                },
            )

            # ----------------------------------------------------------------
            # 3.3  Final tier decision
            # ----------------------------------------------------------------
            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_start",
                "3.3 Final tier decision — picking autonomy tier from final confidence",
                data={"substep": "3.3", "label": "Final tier decision"},
            )
            confidence = round(max(0.0, min(1.0, confidence)), 3)
            from ..config import CONFIDENCE_TIERS
            if confidence >= CONFIDENCE_TIERS["L4_AUTO"]:
                tier = "L4_AUTO"
            elif confidence >= CONFIDENCE_TIERS["L3_ONE_CLICK"]:
                tier = "L3_ONE_CLICK"
            else:
                tier = "L2_HITL"

            # FCNV review gate force-HITL: per the RFP use-case diagrams,
            # any case that needs FCNV review (low extraction confidence or
            # missing parties) must drop to L2_HITL regardless of the four-
            # gate composite. The CSR completes enrichment in the FCNV queue
            # before the case can advance.
            if (ctx.intake or {}).get("fcnv_review_required") and tier != "L2_HITL":
                applied_caps.append({
                    "kind": "fcnv_review",
                    "from_tier": tier,
                    "to_tier": "L2_HITL",
                    "reason": "FCNV review gate forces L2_HITL",
                    "missing_parties": (ctx.intake or {}).get("fcnv_missing_parties") or [],
                })
                tier = "L2_HITL"
                guardrails.append("fcnv_review_forces_hitl")

            # CSR override force-HITL: if Stage 1 detected a CSR-typed
            # do-not-auto / force-HITL / route-to-team instruction, the
            # tier must drop to L2_HITL regardless of computed confidence.
            csr_override = ctx.intake.get("csr_override") or {}
            if csr_override.get("has_override"):
                kind = csr_override.get("override_kind") or "none"
                if kind in {"do_not_auto", "force_hitl", "route_to_team"} and tier != "L2_HITL":
                    applied_caps.append({
                        "kind": "csr_override",
                        "from_tier": tier,
                        "to_tier": "L2_HITL",
                        "override_kind": kind,
                        "instruction": (csr_override.get("override_instruction") or "")[:200],
                        "reason": f"CSR-typed override ({kind}) forces L2_HITL",
                    })
                    tier = "L2_HITL"
                    guardrails.append(f"csr_override_forces_hitl:{kind}")

            # Per-rule SLO floor: each KB rule body may declare an
            # `slo_accuracy_floor` (0..1). When the rule's live measured
            # accuracy in the rolling 7-day window is below this floor, the
            # case must drop to L2 review until the rule recovers. The floor
            # is the rule owner's contract for auto-action.
            try:
                from .. import kb as _kb_mod
                intent_key = (ctx.intake or {}).get("intent") or ""
                rule_body = (_kb_mod.intake_intent_rules() or {}).get(intent_key) or {}
                slo_floor = rule_body.get("slo_accuracy_floor")
                if tier != "L2_HITL" and isinstance(slo_floor, (int, float)) and slo_floor > 0:
                    # Cheap live-accuracy proxy: 1.0 minus the recent edit rate
                    # for this intent over the last 7 days.
                    from datetime import timedelta as _td
                    from ..models import Feedback as _Fb, Pipeline as _P
                    cut = datetime.utcnow() - _td(days=7)
                    pids = [pid for (pid,) in ctx.db.query(_P.id).filter(
                        _P.intent == intent_key, _P.started_at >= cut
                    ).all()]
                    edits = ctx.db.query(_Fb.id).filter(
                        _Fb.kind == "edit", _Fb.pipeline_id.in_(pids)
                    ).count() if pids else 0
                    measured_acc = 1.0 - (edits / len(pids)) if pids else 1.0
                    if measured_acc < float(slo_floor):
                        applied_caps.append({
                            "kind": "slo_floor",
                            "from_tier": tier,
                            "to_tier": "L2_HITL",
                            "rule_floor": slo_floor,
                            "measured": round(measured_acc, 3),
                            "reason": f"Rule SLO floor {slo_floor} not met (measured {measured_acc:.2f})",
                        })
                        tier = "L2_HITL"
                        guardrails.append("slo_floor_forces_hitl")
            except Exception:
                pass

            # Per-customer carveout: a promoted rule can be marked with a
            # `carveouts` list of customer codes that opt out of the new
            # behaviour. While carved out, the case is forced to L2 review
            # so the human applies the prior behaviour for that account.
            try:
                from .. import kb as _kb_mod2
                intent_key2 = (ctx.intake or {}).get("intent") or ""
                rule_body2 = (_kb_mod2.intake_intent_rules() or {}).get(intent_key2) or {}
                carveouts = rule_body2.get("carveouts") or []
                cust_code = ((ctx.customer_match or {}).get("customer_code") or "").strip() if isinstance(ctx.customer_match, dict) else ""
                if tier != "L2_HITL" and cust_code and any(str(c).strip().lower() == cust_code.lower() for c in carveouts):
                    applied_caps.append({
                        "kind": "customer_carveout",
                        "from_tier": tier,
                        "to_tier": "L2_HITL",
                        "customer_code": cust_code,
                        "reason": f"Customer {cust_code} is carved out of this rule",
                    })
                    tier = "L2_HITL"
                    guardrails.append(f"carveout_forces_hitl:{cust_code}")
            except Exception:
                pass

            # Circuit-breaker force-HITL: the Continuous Learning Monitor
            # fires a breaker when a per-segment metric (edit rate, HITL rate,
            # extraction error rate, latency, AIOA pass rate, distribution
            # shift, integration failures) crosses a high-severity threshold.
            # While a breaker is armed for an affected segment, cases in that
            # segment cannot auto-close at L4 even at maximum confidence; they
            # drop to L2 review until the operator acknowledges or the metric
            # recovers.
            if tier != "L2_HITL":
                try:
                    from ..services.monitor import segments_with_circuit_breaker_armed
                    armed = segments_with_circuit_breaker_armed(ctx.db)
                    intent_key = (ctx.intake or {}).get("intent") or ""
                    region_key = ((ctx.intake or {}).get("account_region") or "").strip().upper() or None
                    language_key = ((ctx.intake or {}).get("language") or "").strip().lower() or None
                    candidate_keys = {
                        f"intent:{intent_key}",
                        f"intent:{intent_key} region:{region_key.lower()}" if region_key else "",
                        f"region:{region_key}" if region_key else "",
                        f"language:{language_key}" if language_key else "",
                    }
                    hit = next((s for s in candidate_keys if s and s in armed), None)
                    if hit:
                        applied_caps.append({
                            "kind": "circuit_breaker",
                            "from_tier": tier,
                            "to_tier": "L2_HITL",
                            "matched_segment": hit,
                            "reason": f"Drift circuit breaker armed for '{hit}' — auto-tier suppressed",
                        })
                        tier = "L2_HITL"
                        guardrails.append(f"circuit_breaker_forces_hitl:{hit}")
                except Exception:
                    pass

            ctx.decision["confidence"] = confidence
            ctx.decision["autonomy_tier"] = tier
            ctx.decision["fired_rules"] = fired_rules
            ctx.decision["dry_run_rules"] = dry_run_rules
            ctx.decision["guardrails_applied"] = list(guardrails)
            ctx.decision["applied_caps"] = applied_caps
            if aioa_response is not None:
                ctx.decision["aioa"] = {
                    "fired": True,
                    "outcome": aioa_response.get("outcome"),
                    "request_id": aioa_response.get("request_id"),
                    "fallout_reason": aioa_response.get("fallout_reason"),
                    "downstream_action": aioa_response.get("downstream_action"),
                    "webhook_url": aioa_response.get("webhook_url"),
                    "owned_by": aioa_response.get("owned_by"),
                    "evaluated_at": aioa_response.get("evaluated_at"),
                }

            # ----------------------------------------------------------------
            # 3.4  Assign CCC Request owner (per RFP swimlane)
            # ----------------------------------------------------------------
            # Per the use-case diagrams, every case is assigned to a named
            # CSR queue or to "AI Agent (automation complete)" after the
            # confidence / AIOA / FCNV gates have been resolved. We compute
            # the assignment from the (track + tier + fallout) tuple so
            # downstream UI and Salesforce Case ownership reflect it.
            from .track_classifier import (
                classify_tracks,
                assign_ccc_owner,
            )
            fcnv_required = bool((ctx.intake or {}).get("fcnv_review_required"))
            aioa_outcome = (ctx.decision.get("aioa") or {}).get("outcome")
            # Re-classify tracks now that AIOA outcome is known.
            tracks_block = classify_tracks(
                intent=(ctx.intake or {}).get("intent") or "",
                fcnv_review_required=fcnv_required,
                aioa_outcome=aioa_outcome,
            )
            is_aioa_handoff = bool((ctx.decision.get("aioa") or {}).get("fired") and (aioa_outcome or "").upper() == "AIOA_PASS")
            is_no_reply_intent = (ctx.intake or {}).get("intent") in {"service_order", "wo_update_request", "ssd_change_request"}
            owner_block = assign_ccc_owner(
                primary_track=tracks_block["primary_track"],
                autonomy_tier=tier,
                fcnv_review_required=fcnv_required,
                aioa_outcome=aioa_outcome,
                is_aioa_handoff=is_aioa_handoff,
                is_no_reply=is_no_reply_intent and tier == "L4_AUTO",
                db=ctx.db,
            )
            ctx.decision["track"] = tracks_block["primary_track"]
            ctx.decision["tracks_touched"] = tracks_block["all_tracks_touched"]
            ctx.decision["owner"] = owner_block
            ctx.decision["fcnv_review_required"] = fcnv_required
            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_done",
                f"3.4 Assign CCC Request owner — {owner_block['owner_label']} ({owner_block['owner_queue']})",
                data={
                    "substep": "3.4",
                    "label": "Assign CCC Request owner",
                    "primary_track": tracks_block["primary_track"],
                    "tracks_touched": tracks_block["all_tracks_touched"],
                    "owner": owner_block,
                    "fcnv_review_required": fcnv_required,
                    "aioa_outcome": aioa_outcome,
                },
            )

            log_event(
                ctx.db, ctx.pipeline_id, "decide", "substep_done",
                f"3.3 Final tier: {tier} @ confidence={confidence:.3f} -> action={ctx.decision.get('action') or '-'}",
                data={
                    "substep": "3.3",
                    "tier": tier,
                    "final_confidence": confidence,
                    "action": ctx.decision.get("action"),
                    "flow": ctx.decision.get("flow"),
                    "track_hint": ctx.decision.get("track_hint"),
                    "thresholds": CONFIDENCE_TIERS,
                },
            )

            self._persist(ctx)
            return AgentResult(
                stage=self.stage_key,
                output=ctx.decision,
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

    def _persist(self, ctx: AgentContext) -> None:
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        pipe.decision = ctx.decision
        pipe.confidence = ctx.decision.get("confidence")
        pipe.autonomy_tier = ctx.decision.get("autonomy_tier")
        ctx.db.commit()
