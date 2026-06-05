# === v1.1 TASK-5 START ===
"""Routing resolver — picks an assignment queue / target from KB routing_rules.

Walks the routing_rules namespace in priority order, evaluates each rule's
predicates against the email + extracted context + customer match, returns
(routing_target, basis_rule_key, magic_sku, evidence) on first match.
Returns (None, "", None, []) when no rule fires — the orchestrator then
falls back to the default queue for the intent.
"""
from __future__ import annotations

from typing import Any

from .. import kb


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).lower().strip()


def _customer_name_in(rule_values: list[str], extracted: dict, customer_match: dict) -> tuple[bool, str]:
    """Match against extracted.customer_name OR customer_match.salesforce_account_name."""
    candidates = [
        extracted.get("customer_name") or "",
        ((customer_match or {}).get("salesforce") or {}).get("account", {}).get("Name") or "",
        (customer_match or {}).get("customer_name") or "",
    ]
    cands_l = [_norm(c) for c in candidates if c]
    for v in rule_values:
        v_l = _norm(v)
        if not v_l:
            continue
        for c in cands_l:
            if v_l in c or c in v_l:
                return True, f"customer={c!r} matched {v!r}"
    return False, ""


def _country_not_in(rule_values: list[str], extracted: dict) -> tuple[bool, str]:
    country = extracted.get("ship_to_country") or extracted.get("destination_country") or extracted.get("country")
    if not country:
        return False, ""
    country_l = _norm(country)
    allowlist = {_norm(v) for v in rule_values}
    if country_l not in allowlist:
        return True, f"ship_to_country={country!r} ∉ {sorted(allowlist)}"
    return False, ""


def _subject_or_body_contains(rule_values: list[str], email: dict) -> tuple[bool, str]:
    blob = (
        (email.get("subject") or "") + "\n" + (email.get("body") or "")
    ).lower()
    for v in rule_values:
        v_l = _norm(v)
        if v_l and v_l in blob:
            return True, f"matched {v!r}"
    return False, ""


def _any_sku_starts_with(rule_values: list[str], extracted: dict) -> tuple[bool, str]:
    line_items = extracted.get("line_items") or []
    if not isinstance(line_items, list):
        return False, ""
    prefixes = [v for v in rule_values if v]
    for li in line_items:
        sku = ((li or {}).get("sku") or "").strip()
        for p in prefixes:
            if sku.startswith(p):
                return True, f"sku={sku!r} starts with {p!r}"
    return False, ""


def _sender_contains(rule_values: list[str], email: dict) -> tuple[bool, str]:
    sender = _norm(email.get("from") or email.get("from_address"))
    for v in rule_values:
        v_l = _norm(v)
        if v_l and v_l in sender:
            return True, f"sender={sender!r} contains {v!r}"
    return False, ""


def _po_number_starts_with(rule_values: list[str], extracted: dict) -> tuple[bool, str]:
    po = (extracted.get("po_number") or "").strip()
    for v in rule_values:
        if v and po.startswith(v):
            return True, f"po_number={po!r} starts with {v!r}"
    return False, ""


def _ctx_field(rule_value: Any, target_value: Any, intake_ctx: dict) -> tuple[bool, str]:
    cur = intake_ctx
    for part in (rule_value or "").split("."):
        if not isinstance(cur, dict):
            return False, ""
        cur = cur.get(part)
    if cur == target_value:
        return True, f"intake.{rule_value} == {target_value!r}"
    return False, ""


def _eval_predicate(pred: dict, *, email: dict, extracted: dict,
                    customer_match: dict, intake_ctx: dict) -> tuple[bool, str]:
    kind = pred.get("kind") or ""
    values = pred.get("value")
    if kind == "ctx_field":
        return _ctx_field(pred.get("field"), pred.get("value"), intake_ctx)
    if not isinstance(values, list):
        values = [values] if values else []
    if kind == "customer_name_in":
        return _customer_name_in(values, extracted, customer_match)
    if kind == "extracted_country_not_in":
        return _country_not_in(values, extracted)
    if kind == "subject_or_body_contains":
        return _subject_or_body_contains(values, email)
    if kind == "any_sku_starts_with":
        return _any_sku_starts_with(values, extracted)
    if kind == "sender_contains":
        return _sender_contains(values, email)
    if kind == "po_number_starts_with":
        return _po_number_starts_with(values, extracted)
    return False, ""


def resolve_routing(*, email: dict, extracted: dict, customer_match: dict,
                    intake_ctx: dict) -> dict:
    """Walk KB routing_rules in priority order. First-match wins.

    Returns:
      {
        "routing_target": "AMFO_Disty/Rental",
        "basis_rule_key": "routing.disty_us_ca",
        "basis_rule_label": "Distributor — US/Canada",
        "magic_sku": None,
        "evidence": ["customer='mouser electronics inc' matched 'Mouser'"],
        "rules_evaluated": 6,
      }
    or {"routing_target": None, ...} when nothing matches.
    """
    rules = kb.routing_rules()
    for rule in rules:
        preds = rule.get("predicates") or []
        for pred in preds:
            ok, evidence = _eval_predicate(
                pred,
                email=email or {},
                extracted=extracted or {},
                customer_match=customer_match or {},
                intake_ctx=intake_ctx or {},
            )
            if ok:
                return {
                    "routing_target": rule.get("routing_target"),
                    "basis_rule_key": rule.get("id"),
                    "basis_rule_label": rule.get("label"),
                    "magic_sku": rule.get("magic_sku"),
                    "predicate_kind": pred.get("kind"),
                    "evidence": [evidence],
                    "rules_evaluated": len(rules),
                }
    return {
        "routing_target": None,
        "basis_rule_key": "",
        "basis_rule_label": "",
        "magic_sku": None,
        "predicate_kind": "",
        "evidence": [],
        "rules_evaluated": len(rules),
    }
# === v1.1 TASK-5 END ===
