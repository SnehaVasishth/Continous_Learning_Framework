"""Candidate-validity gate for Continuous Learning.

Every LearningOpportunity must pass three checks before it can be accepted
into an A/B experiment:

  1. PRECONDITION  — the candidate names an input pattern the system can
     evaluate from data IT ALREADY HAS (extracted fields, intent, customer
     attributes, sender domain). Failure descriptions of past events are
     observations, not preconditions.

  2. ACTIONABILITY — the candidate proposes a behaviour that is different
     from the default fallback. The platform's default for uncertain or
     blocked cases is HITL. A candidate whose action is "halt and route to
     HITL" against a precondition the system cannot detect is not a tuning,
     it is the default behaviour. Such candidates are rejected.

  3. SANITY      — the candidate is a tuning, not an infrastructure alert.
     Infrastructure failures (sf_error, sp_error, network_error, db_error,
     verifier_halt without a specific rule_key) are owned by the Monitor
     service / ops alerting. They do not belong in the learning loop.

The validate() function returns (ok, reasons). When ok is False, the
endpoint that accepts opportunities (PATCH /opportunities/{id} with
status=accepted) returns 422 with the reasons. The generator code is also
free to call validate() pre-emptively to avoid emitting bad candidates.
"""
from __future__ import annotations

import json
from typing import Any

from ..models import LearningOpportunity


_INFRASTRUCTURE_SIGNATURES = {
    "sf_error", "sp_error", "sn_error", "salesforce_write_failed",
    "verifier_halt_unspecified", "network_error", "timeout", "db_error",
    "no_active_salesforce_connection", "no_active_sharepoint_connection",
    "no_active_servicenow_connection",
}

_DEFAULT_FALLBACK_ACTIONS = {
    "halt_pipeline_and_route_to_hitl", "halt", "route_to_hitl",
    "skip", "ignore",
}


def _parse_remedy(opp: LearningOpportunity) -> dict | None:
    raw = opp.proposed_remedy or ""
    if not raw or raw[0] not in "{[":
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def validate(opp: LearningOpportunity) -> tuple[bool, list[str]]:
    """Run the three validity checks against an opportunity. Returns
    (ok, reasons). reasons is the list of failures (empty when ok)."""
    reasons: list[str] = []
    remedy = _parse_remedy(opp)
    change_type = (remedy or {}).get("change_type") or "prompt"

    # Prompt / pattern_list / threshold / routing_rule candidates are
    # validated structurally — they always describe a real precondition by
    # the shape of their generator. They do not need the same check as
    # validation_rule candidates, which are the class most prone to the
    # infrastructure-alert antipattern.
    if change_type != "validation_rule":
        return True, []

    proposed = (remedy or {}).get("proposed") or {}
    fires_on = str(proposed.get("fires_on") or "").lower()
    action = str(proposed.get("action") or "").lower()
    rule_id = str(proposed.get("rule_id") or "")

    # 1) Precondition — must reference a piece of state we can evaluate
    # before the side effect. Acceptable shapes mention `intent=`, `extracted.`,
    # `customer.`, `sender.`. Failure-event descriptions ("event kind 'sf_error'")
    # are not preconditions.
    has_eval_shape = any(token in fires_on for token in ("intent=", "extracted.", "customer.", "sender.", "abs("))
    if not has_eval_shape:
        reasons.append(
            "precondition_not_evaluable: fires_on must reference evaluable state "
            "(intent= / extracted.* / customer.* / sender.*). Got: "
            f"{fires_on[:120]!r}"
        )

    # Infrastructure signatures are forbidden in the rule body.
    if any(sig in fires_on for sig in _INFRASTRUCTURE_SIGNATURES):
        reasons.append(
            "infrastructure_signal_not_a_candidate: fires_on references an "
            "infrastructure failure pattern. These belong to the Monitor service / "
            "ops alerting, not the learning loop."
        )

    # 2) Actionability — must do something other than the default fallback.
    if action in _DEFAULT_FALLBACK_ACTIONS:
        reasons.append(
            "action_is_default_fallback: candidate's action is the same as the "
            f"platform default ({action!r}). A real candidate proposes a different "
            "behaviour (request_enrichment:<field>, route_to_track:<track>, "
            "require_review_against_<criterion>, etc.)."
        )

    # 3) Sanity — the rule_id should not pattern-match an infrastructure label.
    if rule_id and any(rule_id.startswith(f"preflight_{sig}") or rule_id.startswith(f"flag_{sig}") for sig in _INFRASTRUCTURE_SIGNATURES):
        reasons.append(
            f"rule_id_is_infrastructure_label: rule_id={rule_id!r} maps to an "
            "infrastructure signature."
        )

    return len(reasons) == 0, reasons


def validate_dict(remedy: dict[str, Any]) -> tuple[bool, list[str]]:
    """Sibling helper that operates on a parsed remedy dict directly,
    without an Opportunity row. Used by generators that want to check
    a candidate before persisting it.
    """
    # Build a throwaway opp-like object.
    class _Shim:
        proposed_remedy = json.dumps(remedy)
    return validate(_Shim())  # type: ignore[arg-type]
