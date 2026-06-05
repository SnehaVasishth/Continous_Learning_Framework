"""Stage 3 — Decision & Confidence Scoring.

Confidence math is KB-driven via the `decision_confidence_rubric` namespace.
Each pipeline run loads the rubric, evaluates every rule against the upstream
signals + reconcile result, and produces a structured `confidence_breakdown[]`
that the trace UI renders as a math table — auditors can read which rules
contributed and why.

Two rule kinds drive the math:
  - weighted_signal: contributes `weight × signal_var` to the running sum
  - floor_cap: when its predicate evaluates true, caps the running sum at
    a fixed value (no-op if running sum is already below the cap)
"""
from __future__ import annotations

from .. import kb
from ..config import CONFIDENCE_TIERS, INTENT_TO_FLOW
from .tools.business_rules_eval_tool import _evaluate_predicate

TRACK_FLOWS = {
    "trade": {"trade_order_entry", "trade_change_order", "ssd_change"},
    "som": {"som_create", "som_update", "som_inquiry"},
    "service_contract": {"service_contract"},
}

def score_extraction_completeness(intent: str, extracted: dict) -> float:
    """Required-field completeness for the intent, driven by the KB.

    Reads the active extract_schema for the intent and computes:
        score = (number of required fields populated) / (number of required fields)

    Operators tune required-vs-optional in the KB UI; the next pipeline picks it
    up without code change. Falls back to a neutral 0.6 if no schema is
    registered for the intent (e.g., out_of_scope, spam, kso operational classes
    that don't carry structured fields)."""
    if not extracted:
        return 0.0
    schema = kb.expected_fields_for_intent(intent)
    required = schema.get("required") or []
    if not required:
        return 0.6
    present = 0
    for name in required:
        value = extracted.get(name)
        # list-typed fields (line_items, line_changes, assets, ...) must be
        # both present AND a non-empty list to count as populated; the schema
        # itself flags these as list types but here we just check truthiness.
        if isinstance(value, list):
            if value:
                present += 1
        elif value not in (None, "", [], {}):
            present += 1
    return round(present / len(required), 3)


def tier_for(confidence: float, *, l4_floor: float | None = None, l3_floor: float | None = None) -> str:
    """Map a composite confidence to an autonomy tier.

    `l4_floor` / `l3_floor` default to the global `CONFIDENCE_TIERS`. Callers
    that have a per-intent override (loaded from the `threshold` KB
    namespace) pass them in to drive tiering from admin-edited floors.
    """
    l4 = l4_floor if l4_floor is not None else CONFIDENCE_TIERS["L4_AUTO"]
    l3 = l3_floor if l3_floor is not None else CONFIDENCE_TIERS["L3_ONE_CLICK"]
    if confidence >= l4:
        return "L4_AUTO"
    if confidence >= l3:
        return "L3_ONE_CLICK"
    return "L2_HITL"


def _build_4_gate_confidence(
    *,
    intent: str,
    intent_conf: float,
    extract_score: float,
    customer_score: float,
    extracted: dict,
    reconcile_result: dict | None,
    blocking_issues: set,
    aioa_result: dict | None = None,
    ccc_resolution: dict | None = None,
) -> dict:
    """Compute the 4 confidence gates the Keysight RFP Q&A call described.

    Returns:
      {
        "classification":     {score: 0.92, label: "high",   reason: "...", threshold: 0.80},
        "extraction":         {score: 0.75, label: "medium", reason: "..."},
        "entity_resolution":  {score: 1.00, label: "matched", binary: true,  reason: "..."},
        "action_feasibility": {score: 0.50, label: "blocked", reason: "..."},
        "composite": 0.71,
        "tier_driver": "action_feasibility",  # which gate is the lowest
      }

    The trace UI + HITL surfaces these independently. `tier_driver` tells the
    operator which gate dragged the composite down."""
    def _label(score: float) -> str:
        if score >= 0.85: return "high"
        if score >= 0.60: return "medium"
        return "low"

    # Gate 1 — Classification: directly from intake's intent_confidence.
    classification = {
        "score": round(intent_conf, 3),
        "label": _label(intent_conf),
        "reason": (
            f"Stage 1 classified as {intent!r} with intent_confidence={intent_conf:.2f}."
            if intent
            else "No intent assigned."
        ),
        "threshold": 0.80,
    }

    # Gate 2 — Extraction: schema completeness for the intent.
    extraction = {
        "score": round(extract_score, 3),
        "label": _label(extract_score),
        "reason": (
            f"Required-field completeness {extract_score:.0%} for intent {intent!r}."
            if intent
            else "Extraction not scored."
        ),
        "threshold": 0.70,
    }

    # Gate 3 — Entity Resolution: binary did-we-find-the-customer-in-SF.
    # Cap at 1.0 only when customer_score == 1.0 (exact code/email match);
    # fuzzy name match (< 1.0) treated as resolved=true but score reflects the
    # match quality.
    er_binary = customer_score >= 0.5
    entity_resolution = {
        "score": round(customer_score, 3),
        "label": "matched" if customer_score >= 0.95 else "fuzzy" if er_binary else "unmatched",
        "binary": er_binary,
        "reason": (
            f"Salesforce match score {customer_score:.2f} "
            + ("(exact)" if customer_score >= 0.95 else "(fuzzy)" if er_binary else "(no match)")
        ),
        "threshold": 0.95,
    }

    # Gate 4 — Action Feasibility: can the Stage 4 action actually execute?
    # Walks the KB-defined required-field list for the intent (single source of
    # truth, edited by operators in the KB UI). For each missing required field
    # the score is capped at a level that drops the composite below the L4
    # autonomy threshold, forcing the case into L3 or L2 for human review.
    # Reconcile mismatches and Q2O quote-resolution add additional caps.
    feasibility_score = 1.0
    feasibility_reasons: list[str] = []
    missing_required: list[str] = []
    schema_summary = kb.expected_fields_for_intent(intent)
    required_fields = schema_summary.get("required") or []
    for fname in required_fields:
        value = extracted.get(fname)
        is_empty = (
            value in (None, "", [], {})
            or (isinstance(value, list) and not value)
            or (isinstance(value, dict) and not value)
        )
        if is_empty:
            missing_required.append(fname)
    if missing_required:
        # One missing field caps at 0.55 (still autonomy-blocking); two or more
        # caps tighter at 0.35 so HITL surfaces it as a clear blocking gap.
        cap = 0.55 if len(missing_required) == 1 else 0.35
        feasibility_score = min(feasibility_score, cap)
        feasibility_reasons.append(
            f"missing required field(s): {', '.join(missing_required)} (per KB schema)"
        )
    if intent == "quote_to_order" and not extracted.get("quote_number"):
        feasibility_score = min(feasibility_score, 0.50)
        if "quote_number" not in missing_required:
            feasibility_reasons.append(
                "Q2O without quote_number — Stage 4 cannot resolve source quote"
            )
    if blocking_issues:
        feasibility_score = min(feasibility_score, 0.55)
        feasibility_reasons.append(
            f"blocking reconcile mismatches: {', '.join(sorted(blocking_issues))}"
        )
    # AIOA outcome (external Keysight AI Order Acceptance app). When the AIOA
    # step ran for this intent and returned AIOA_FAIL, drop Action Feasibility
    # to 0.40 and surface the fallout reason — matching the AS-IS pattern
    # where AIOA Fail routes the case to the AI OA Fallout queue for CSR review.
    if aioa_result:
        outcome = (aioa_result.get("outcome") or "").upper()
        if outcome == "AIOA_FAIL":
            feasibility_score = min(feasibility_score, 0.40)
            feasibility_reasons.append(
                f"AIOA fallout: {aioa_result.get('fallout_reason') or 'PO validation failed'}"
            )
        elif outcome == "AIOA_PASS":
            feasibility_reasons.append("AIOA pass — external PO validation cleared")

    # CCC resolution ambiguity penalty — when Stage 3.0 couldn't pick a
    # confident parent Case (multiple candidates >= 0.50, or top score in
    # 0.40-0.69), cap feasibility so the case goes to L3 or L2 for review.
    if ccc_resolution:
        if ccc_resolution.get("ambiguous"):
            cap = float(ccc_resolution.get("feasibility_penalty") or 0.65)
            feasibility_score = min(feasibility_score, cap)
            n = ccc_resolution.get("ambiguity_count") or 0
            feasibility_reasons.append(
                f"CCC resolution ambiguous — {n} candidate Case(s) ≥ 0.50; manual review recommended"
            )
        elif ccc_resolution.get("decision") in ("update", "clone_change_order"):
            sel = ccc_resolution.get("selected") or {}
            feasibility_reasons.append(
                f"CCC resolution confident — adopting Case {sel.get('case_number') or sel.get('case_id')} (score={sel.get('score')})"
            )
        elif ccc_resolution.get("decision") == "new":
            feasibility_reasons.append("CCC resolution — creating new Case (no parent match)")

    action_feasibility = {
        "score": round(feasibility_score, 3),
        "label": _label(feasibility_score) if feasibility_score >= 0.85 else "blocked",
        "reason": "; ".join(feasibility_reasons) or "All required inputs present for Stage 4 action.",
        "threshold": 0.70,
        "missing_required_fields": missing_required,
        "kb_required_fields": required_fields,
        "aioa_outcome": (aioa_result or {}).get("outcome"),
        "aioa_fallout_reason": (aioa_result or {}).get("fallout_reason"),
        "ccc_resolution_decision": (ccc_resolution or {}).get("decision"),
        "ccc_resolution_ambiguous": bool((ccc_resolution or {}).get("ambiguous")),
        "ccc_resolution_candidate_count": len((ccc_resolution or {}).get("candidates") or []),
    }

    gates = {
        "classification": classification,
        "extraction": extraction,
        "entity_resolution": entity_resolution,
        "action_feasibility": action_feasibility,
    }
    # Identify which gate is dragging the composite down.
    lowest = min(gates.items(), key=lambda kv: kv[1]["score"])
    gates["composite"] = round(min(g["score"] for g in gates.values() if isinstance(g, dict)), 3)
    gates["tier_driver"] = lowest[0]
    return gates


def _build_decision_eval_vars(
    *, intent: str, intent_conf: float, extract_score: float,
    customer_score: float, extracted: dict, reconcile_blocking_count: int,
    reconcile_soft_count: int,
) -> dict:
    """Variables visible to floor_cap predicates. Mirrors the business_rules
    eval-context but scoped to what's relevant to the decision rubric."""
    line_items = extracted.get("line_items") or []
    if not isinstance(line_items, list):
        line_items = []
    return {
        "intent": intent or "",
        "intent_confidence": float(intent_conf or 0.0),
        "extraction_completeness": float(extract_score or 0.0),
        "customer_match_score": float(customer_score or 0.0),
        "po_number": extracted.get("po_number") or "",
        "line_items": line_items,
        "line_count": len(line_items),
        "quote_number": extracted.get("quote_number") or "",
        "reconcile_blocking_count": int(reconcile_blocking_count or 0),
        "reconcile_soft_count": int(reconcile_soft_count or 0),
    }


def _apply_decision_rubric(
    *, intent: str, intent_conf: float, extract_score: float,
    customer_score: float, extracted: dict, blocking_issues: set,
    soft_issues: set,
) -> tuple[float, list[dict]]:
    """Walk the KB rubric, build the confidence_breakdown[], return (confidence, breakdown).

    Behavior is functionally identical to the old hardcoded formula — every
    default rule reproduces the previous numeric behavior exactly. The
    advantage is that operators can now tune weights and caps from the KB UI
    without a code change.
    """
    try:
        rubric = kb.decision_confidence_rubric()
    except Exception:
        rubric = {"base": 0.0, "rules": [], "signals": [], "caps": []}

    breakdown: list[dict] = []

    base = float(rubric.get("base") or 0.0)
    breakdown.append({
        "rule_key": "_base",
        "kind": "base",
        "matched": True,
        "contribution": base,
        "running": base,
        "evidence": "Stage 3 confidence is a pure aggregator of upstream signals.",
    })

    eval_vars = _build_decision_eval_vars(
        intent=intent,
        intent_conf=intent_conf,
        extract_score=extract_score,
        customer_score=customer_score,
        extracted=extracted,
        reconcile_blocking_count=len(blocking_issues),
        reconcile_soft_count=len(soft_issues),
    )

    running = base
    for sig in rubric.get("signals") or []:
        weight = float(sig.get("weight") or 0.0)
        signal_var = sig.get("signal_var") or ""
        signal_value = float(eval_vars.get(signal_var) or 0.0)
        contribution = weight * signal_value
        running = running + contribution
        breakdown.append({
            "rule_key": sig.get("id") or "",
            "kind": "weighted_signal",
            "matched": True,
            "contribution": round(contribution, 4),
            "running": round(running, 4),
            "weight": weight,
            "signal_var": signal_var,
            "signal_value": round(signal_value, 4),
            "evidence": f"{weight:.2f} × {signal_var}({signal_value:.3f}) = {contribution:.3f}",
        })

    # Clamp post-signals before applying caps.
    running = max(0.0, min(1.0, running))
    breakdown.append({
        "rule_key": "_post_signals_clamp",
        "kind": "clamp",
        "matched": True,
        "contribution": 0.0,
        "running": round(running, 4),
        "evidence": "Sum clamped to [0.0, 1.0] before caps.",
    })

    for cap_rule in rubric.get("caps") or []:
        cap_id = cap_rule.get("id") or ""
        cap_value = float(cap_rule.get("cap") or 1.0)
        applies_to_intents = cap_rule.get("applies_to_intents") or []
        if applies_to_intents and intent and intent not in applies_to_intents:
            breakdown.append({
                "rule_key": cap_id,
                "kind": "floor_cap",
                "matched": False,
                "contribution": 0.0,
                "running": round(running, 4),
                "cap": cap_value,
                "evidence": f"Skipped — applies_to_intents={applies_to_intents}, current intent={intent!r}",
            })
            continue
        predicate = cap_rule.get("predicate") or ""
        ok, err = _evaluate_predicate(predicate, eval_vars) if predicate else (False, "no predicate")
        if err:
            breakdown.append({
                "rule_key": cap_id,
                "kind": "floor_cap",
                "matched": False,
                "contribution": 0.0,
                "running": round(running, 4),
                "cap": cap_value,
                "evidence": f"predicate_error: {err}",
            })
            continue
        if not ok:
            breakdown.append({
                "rule_key": cap_id,
                "kind": "floor_cap",
                "matched": False,
                "contribution": 0.0,
                "running": round(running, 4),
                "cap": cap_value,
                "evidence": f"predicate not matched: {predicate}",
            })
            continue
        # Predicate matched — apply cap if it's lower than current running value.
        new_running = min(running, cap_value)
        contribution = new_running - running  # negative or zero
        running = new_running
        breakdown.append({
            "rule_key": cap_id,
            "kind": "floor_cap",
            "matched": True,
            "contribution": round(contribution, 4),
            "running": round(running, 4),
            "cap": cap_value,
            "evidence": f"Capped at {cap_value:.2f} — predicate matched: {predicate}",
        })

    confidence = round(max(0.0, min(1.0, running)), 3)
    return confidence, breakdown


def run_decide(
    *,
    intake: dict,
    extracted: dict,
    customer_match_score: float,
    reconcile_result: dict | None = None,
    aioa_result: dict | None = None,
    ccc_resolution: dict | None = None,
    db=None,
) -> dict:
    if intake.get("spam"):
        return {
            "confidence": 0.99,
            "autonomy_tier": "L4_AUTO",
            "action": "discard",
            "reason": intake.get("spam_reason") or "spam detected",
            "signals": {"spam": True},
            "confidence_breakdown": [
                {"rule_key": "_spam_shortcut", "kind": "shortcut", "matched": True,
                 "contribution": 0.99, "running": 0.99,
                 "evidence": "Stage 1 flagged this as spam — Stage 3 confidence skipped, action=discard."}
            ],
        }

    intent = intake.get("intent") or ""
    intent_conf = float(intake.get("intent_confidence") or 0.0)
    extract_score = score_extraction_completeness(intent, extracted)
    customer_score = float(customer_match_score or 0.0)

    issues = (reconcile_result or {}).get("issues") or []
    issue_kinds = {i.get("kind") for i in issues}
    # Hard mismatches → cap at 0.70 in the rubric. Includes the legacy four
    # plus the new total / currency / duplicate-PO checks added in Phase B.
    blocking_issues = issue_kinds & {
        "price_mismatch",
        "qty_mismatch",
        "sku_not_quoted",
        "total_mismatch",
        "currency_mismatch",
        "duplicate_po",
    }
    # Soft mismatches → cap at 0.88. Includes legacy three plus header-level
    # checks (terms / bill-to / incoterms / line-sum).
    soft_issues = issue_kinds & {
        "sku_typo",
        "missing_quoted_line",
        "missing_sku",
        "terms_mismatch",
        "bill_to_mismatch",
        "incoterms_mismatch",
        "total_sum_mismatch",
    }

    confidence, breakdown = _apply_decision_rubric(
        intent=intent,
        intent_conf=intent_conf,
        extract_score=extract_score,
        customer_score=customer_score,
        extracted=extracted,
        blocking_issues=blocking_issues,
        soft_issues=soft_issues,
    )
    # Per-intent threshold KB override — Continuous-Learning promotions write
    # admin-tuned `l4_floor` / `l3_floor` to `threshold/<intent>`. If a row
    # exists for this intent, use it; otherwise fall back to the global
    # CONFIDENCE_TIERS. The source meta is returned so the trace UI can show
    # whether the tier came from a promoted threshold or the default.
    from .kb_prompts import get_intent_thresholds
    kb_floors, kb_threshold_source = get_intent_thresholds(db, intent)
    if kb_floors is not None:
        tier = tier_for(confidence, l4_floor=kb_floors["l4_floor"], l3_floor=kb_floors["l3_floor"])
    else:
        tier = tier_for(confidence)

    # Per the Keysight RFP Q&A call (5/8): the customer thinks of confidence as
    # FOUR distinct gates, not one weighted average. Surface each gate
    # independently so the trace UI + HITL can render gate-by-gate. The
    # composite `confidence` above stays as the tier-driving number; these
    # four gate scores are advisory metadata for the UI.
    #
    #   Gate 1 — Classification: did we identify the intent?
    #   Gate 2 — Extraction: did we extract all required fields per schema?
    #   Gate 3 — Entity Resolution: did we find the matching SF record? (binary)
    #   Gate 4 — Action Feasibility: can we actually execute the action with what we have?
    gates = _build_4_gate_confidence(
        intent=intent,
        intent_conf=intent_conf,
        extract_score=extract_score,
        customer_score=customer_score,
        extracted=extracted,
        reconcile_result=reconcile_result,
        blocking_issues=blocking_issues,
        ccc_resolution=ccc_resolution,
        aioa_result=aioa_result,
    )

    intent = intake.get("intent")
    action_map = {
        "po_intake": "create_order_acknowledgment",
        "quote_to_order": "convert_quote_to_order",
        "trade_change_order": "apply_change_order",
        "ssd_change_request": "reschedule_order",
        "hold_release": "release_hold",
        "delivery_change": "reschedule_order",
        "service_order": "create_work_order",
        "wo_update_request": "update_work_order",
        "wo_status_inquiry": "report_wo_status",
        "service_contract_request": "draft_service_contract_quote",
        "general_inquiry": "draft_reply",
    }
    action = action_map.get(intent, "route_to_csr")

    track_hint = intake.get("track_hint")
    flow = INTENT_TO_FLOW.get(intent or "", "general")
    misroute = False
    misroute_reason = None
    if track_hint and track_hint in TRACK_FLOWS and flow not in TRACK_FLOWS[track_hint]:
        misroute = True
        misroute_reason = f"track_hint={track_hint} but selected flow={flow}"

    parts: list[str] = []
    parts.append(
        f"Intent confidence {intent_conf:.2f} (×0.45 = {0.45*intent_conf:.3f})"
    )
    parts.append(
        f"extraction completeness {extract_score:.2f} (×0.35 = {0.35*extract_score:.3f})"
    )
    parts.append(
        f"customer match {customer_score:.2f} (×0.20 = {0.20*customer_score:.3f})"
    )
    if blocking_issues:
        parts.append(
            f"capped at 0.70 due to blocking mismatches: {', '.join(sorted(blocking_issues))}"
        )
    elif soft_issues:
        parts.append(
            f"capped at 0.88 due to soft mismatches: {', '.join(sorted(soft_issues))}"
        )
    if misroute and misroute_reason:
        parts.append(f"misroute flagged ({misroute_reason})")
    parts.append(
        f"final confidence {confidence:.3f} → {tier} ("
        + (
            "auto-execute"
            if tier == "L4_AUTO"
            else "one-click human approval"
            if tier == "L3_ONE_CLICK"
            else "full human review"
        )
        + ")"
    )
    reasoning_summary = " · ".join(parts)

    return {
        "confidence": confidence,
        "autonomy_tier": tier,
        "action": action,
        "flow": flow,
        "track_hint": track_hint,
        "misroute": misroute,
        "misroute_reason": misroute_reason,
        "reasoning_summary": reasoning_summary,
        "confidence_breakdown": breakdown,
        "confidence_gates": gates,
        "kb_thresholds_source": kb_threshold_source,
        "signals": {
            "intent_confidence": intent_conf,
            "extraction_completeness": extract_score,
            "customer_match": customer_score,
            "blocking_mismatches": sorted(blocking_issues),
            "soft_mismatches": sorted(soft_issues),
            "track_hint_match": not misroute,
        },
    }
