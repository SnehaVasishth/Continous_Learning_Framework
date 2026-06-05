"""Stage 2.5 — Cross-system validation against the matched quote + account.

Walks the `reconcile_checks` KB rubric (one rule per check, operator-editable)
and builds a structured `checks_evaluated[]` for the trace UI plus an
`issues[]` list whose `kind` Stage 3's decide.py keys off of (price_mismatch,
qty_mismatch, sku_not_quoted, sku_typo, missing_quoted_line, missing_sku,
total_mismatch, currency_mismatch, terms_mismatch, bill_to_mismatch,
incoterms_mismatch, duplicate_po, total_sum_mismatch).

The eval-context exposed to predicates:
  po_line                    # current PO line (per_line scope)
  quote_line                 # matching quote line by SKU (per_line scope)
  quote_skus                 # set of all SKUs on the quote
  po_skus                    # set of all SKUs on the PO
  extracted                  # full extracted dict
  extracted_total            # float coercion of extracted.total
  extracted_payment_terms    # str
  extracted_currency         # str
  extracted_incoterms        # str
  extracted_bill_to          # str
  extracted_bill_to_tokens   # list[str] meaningful tokens (>=4 chars)
  extracted_po_number        # str
  line_items_sum             # sum(qty * unit_price) over PO lines
  quote_total                # float
  quote_payment_terms        # str
  quote_currency             # str
  quote_incoterms            # str
  account_billing_combined   # lower-cased BillingStreet+City+State combined
  recent_order_po_numbers    # list[str] of PoNumbers from recent SF Orders
  fuzzy_match_threshold      # 0.7 default
  fuzzy_match_score          # populated when checking each unmatched SKU
"""
from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from .. import kb
from ..mocks import crm
from .tools.business_rules_eval_tool import _evaluate_predicate


def reconcile(
    db: Session,
    *,
    intent: str,
    extracted: dict,
    customer_id: int | None,
    customer_match: dict | None = None,
) -> dict:
    """Cross-validate the extracted document against the matched quote + SF account.

    customer_match: ctx.customer_match dict — used to read the SF account
    (BillingStreet/City for bill_to check) and recent SF Orders (PoNumber
    list for the duplicate-PO check)."""
    if intent not in ("po_intake", "quote_to_order"):
        return {"checked": False, "issues": [], "checks_evaluated": [], "kb_namespace": "reconcile_checks"}

    customer_match = customer_match or {}
    quote_number = extracted.get("quote_number")
    if intent == "po_intake" and not quote_number:
        return {
            "checked": True,
            "matched_quote": None,
            "issues": [],
            "checks_evaluated": [],
            "kb_namespace": "reconcile_checks",
            "notes": ["fresh PO — no referenced quote to cross-check"],
        }

    issues: list[dict] = []
    checks_evaluated: list[dict] = []
    notes: list[str] = []

    quote = crm.find_quote(db, customer_id=customer_id, quote_number=quote_number) if quote_number else None
    if not quote and intent == "quote_to_order":
        quote = crm.find_quote(db, customer_id=customer_id, quote_number=None)
    if not quote:
        notes.append("no matching quote found — pricing cannot be cross-checked")
        return {
            "checked": True,
            "matched_quote": None,
            "issues": issues,
            "checks_evaluated": checks_evaluated,
            "kb_namespace": "reconcile_checks",
            "notes": notes,
        }

    notes.append(f"matched quote {quote.quote_number}")

    # ------------------------------------------------------------------
    # Build the shared per-total eval context.
    # ------------------------------------------------------------------
    quoted_lines = quote.line_items or []
    po_lines = extracted.get("line_items") or []
    if not isinstance(po_lines, list):
        po_lines = []

    quoted_by_sku = {li.get("sku"): li for li in quoted_lines if li.get("sku")}
    quote_skus = set(quoted_by_sku.keys())
    po_skus = {li.get("sku") for li in po_lines if li.get("sku")}

    extracted_total = _to_float(extracted.get("total"))
    line_items_sum = sum(
        _to_float(li.get("qty")) * _to_float(li.get("unit_price"))
        for li in po_lines
        if isinstance(li, dict)
    )

    quote_total = _to_float(getattr(quote, "total", None))
    quote_currency = (getattr(quote, "currency", None) or "").strip()
    extracted_currency = (extracted.get("currency") or "").strip()

    # quote payment_terms / incoterms aren't on the Quote model directly —
    # mirror the customer's defaults via customer_match.account when present.
    sf_account = (customer_match.get("account") or {})
    if not sf_account:
        sf_account = (customer_match.get("salesforce") or {}).get("account") or {}
    quote_payment_terms = (sf_account.get("Payment_Terms__c") or "").strip()
    quote_incoterms = (sf_account.get("Default_Incoterms__c") or "").strip()
    extracted_payment_terms = (extracted.get("payment_terms") or "").strip()
    extracted_incoterms = (extracted.get("incoterms") or "").strip()

    extracted_bill_to = (extracted.get("bill_to") or "").strip()
    extracted_bill_to_tokens = [
        tok.lower() for tok in extracted_bill_to.replace(",", " ").replace("\n", " ").split()
        if len(tok) >= 4
    ]
    account_billing_combined = " ".join(
        str(sf_account.get(k) or "") for k in ("BillingStreet", "BillingCity", "BillingState", "BillingPostalCode")
    ).lower()

    extracted_po_number = (extracted.get("po_number") or "").strip()
    recent_orders = (customer_match.get("salesforce") or {}).get("recent_orders") or []
    recent_order_po_numbers = [
        (r.get("PoNumber") or "").strip()
        for r in recent_orders
        if isinstance(r, dict) and r.get("PoNumber")
    ]

    base_ctx = {
        "extracted": extracted,
        "extracted_total": extracted_total,
        "extracted_payment_terms": extracted_payment_terms,
        "extracted_currency": extracted_currency,
        "extracted_incoterms": extracted_incoterms,
        "extracted_bill_to": extracted_bill_to,
        "extracted_bill_to_tokens": extracted_bill_to_tokens,
        "extracted_po_number": extracted_po_number,
        "line_items_sum": line_items_sum,
        "quote_total": quote_total,
        "quote_payment_terms": quote_payment_terms,
        "quote_currency": quote_currency,
        "quote_incoterms": quote_incoterms,
        "quote_skus": quote_skus,
        "po_skus": po_skus,
        "account": sf_account,
        "account_billing_combined": account_billing_combined,
        "recent_orders": recent_orders,
        "recent_order_po_numbers": recent_order_po_numbers,
    }

    # ------------------------------------------------------------------
    # Load the KB rubric and split per-line vs per-total checks.
    # ------------------------------------------------------------------
    try:
        rubric = kb.reconcile_checks()
    except Exception:
        rubric = {"checks": []}

    rules = rubric.get("checks") or []
    per_line_rules = [r for r in rules if r.get("scope") == "per_line"]
    per_total_rules = [r for r in rules if r.get("scope") == "per_total"]

    fuzzy_threshold_default = 0.7
    for r in per_line_rules:
        if r.get("id") == "line_sku_typo_fuzzy":
            fuzzy_threshold_default = float(r.get("fuzzy_match_threshold") or 0.7)

    # ------------------------------------------------------------------
    # PER-LINE checks. SKU-existence checks have a special data-flow because
    # whether quote_line exists determines which rules can fire.
    # ------------------------------------------------------------------
    rule_ids = {r.get("id") for r in per_line_rules}
    has_sku_exists_rule = "line_sku_exists_in_quote" in rule_ids
    has_sku_typo_rule = "line_sku_typo_fuzzy" in rule_ids
    has_unit_price_rule = "line_unit_price_matches_quote" in rule_ids
    has_qty_rule = "line_qty_matches_quote" in rule_ids

    sku_exists_rule = next((r for r in per_line_rules if r.get("id") == "line_sku_exists_in_quote"), None)
    sku_typo_rule = next((r for r in per_line_rules if r.get("id") == "line_sku_typo_fuzzy"), None)
    unit_price_rule = next((r for r in per_line_rules if r.get("id") == "line_unit_price_matches_quote"), None)
    qty_rule = next((r for r in per_line_rules if r.get("id") == "line_qty_matches_quote"), None)

    for po_li in po_lines:
        if not isinstance(po_li, dict):
            continue
        sku = po_li.get("sku")
        if not sku:
            issues.append({"kind": "missing_sku", "po_line": po_li})
            checks_evaluated.append({
                "id": "line_sku_present",
                "scope": "per_line",
                "matched": False,
                "fired": True,
                "severity": "warn",
                "message": "PO line has no SKU",
                "evidence": {"po_line": po_li},
            })
            continue

        match = quoted_by_sku.get(sku)
        if match is None:
            # SKU not in quote — try fuzzy then emit one of {sku_typo, sku_not_quoted}.
            best, score = _fuzzy_pick(sku, list(quoted_by_sku.keys()))
            line_ctx = _eval_context_for_line(
                base_ctx, po_li=_PoLine(po_li), quote_line=None,
                fuzzy_match_score=score, fuzzy_match_threshold=fuzzy_threshold_default,
            )
            if has_sku_typo_rule and best and score >= fuzzy_threshold_default:
                fired = _eval_rule_fires(sku_typo_rule, line_ctx)
                checks_evaluated.append({
                    "id": "line_sku_typo_fuzzy",
                    "scope": "per_line",
                    "matched": fired,
                    "fired": fired,
                    "severity": (sku_typo_rule or {}).get("severity") or "soft",
                    "message": f"sku '{sku}' fuzzy-matches quoted '{best}' (score={score:.2f})",
                    "evidence": {"po_sku": sku, "quoted_sku": best, "score": round(score, 3)},
                })
                if fired:
                    issues.append({
                        "kind": (sku_typo_rule or {}).get("issue_kind") or "sku_typo",
                        "po_sku": sku, "quoted_sku": best, "po_line": po_li,
                    })
            else:
                # No fuzzy match — emit sku_not_quoted via the existence rule.
                fired = has_sku_exists_rule  # predicate is `po_line.sku in quote_skus` → False → fire
                checks_evaluated.append({
                    "id": "line_sku_exists_in_quote",
                    "scope": "per_line",
                    "matched": False,
                    "fired": fired,
                    "severity": (sku_exists_rule or {}).get("severity") or "warn",
                    "message": f"sku '{sku}' not in quoted SKUs",
                    "evidence": {"po_sku": sku, "quote_skus": sorted(quote_skus)},
                })
                if fired:
                    issues.append({
                        "kind": (sku_exists_rule or {}).get("issue_kind") or "sku_not_quoted",
                        "po_line": po_li,
                    })
            continue

        # SKU matched the quote — exists rule passes silently, then check price + qty.
        if has_sku_exists_rule:
            checks_evaluated.append({
                "id": "line_sku_exists_in_quote",
                "scope": "per_line",
                "matched": True,
                "fired": False,
                "severity": (sku_exists_rule or {}).get("severity") or "warn",
                "message": f"sku '{sku}' present in quote",
                "evidence": {"po_sku": sku},
            })

        line_ctx = _eval_context_for_line(
            base_ctx,
            po_li=_PoLine(po_li),
            quote_line=_QuoteLine(match),
            fuzzy_match_score=0.0,
            fuzzy_match_threshold=fuzzy_threshold_default,
        )

        if has_unit_price_rule and _to_float(po_li.get("unit_price")) and _to_float(match.get("unit_price")):
            fired = _eval_rule_fires(unit_price_rule, line_ctx)
            po_price = _to_float(po_li.get("unit_price"))
            q_price = _to_float(match.get("unit_price"))
            checks_evaluated.append({
                "id": "line_unit_price_matches_quote",
                "scope": "per_line",
                "matched": not fired,
                "fired": fired,
                "severity": (unit_price_rule or {}).get("severity") or "hard",
                "message": (
                    f"sku '{sku}' price {po_price} vs quoted {q_price}"
                    + ("" if not fired else f" — diff={abs(po_price - q_price):.2f}")
                ),
                "evidence": {"sku": sku, "po_price": po_price, "quoted_price": q_price},
            })
            if fired:
                issues.append({
                    "kind": (unit_price_rule or {}).get("issue_kind") or "price_mismatch",
                    "sku": sku, "po_price": po_price, "quoted_price": q_price,
                })

        if has_qty_rule and _to_int(po_li.get("qty")) and _to_int(match.get("qty")):
            fired = _eval_rule_fires(qty_rule, line_ctx)
            po_qty = _to_int(po_li.get("qty"))
            q_qty = _to_int(match.get("qty"))
            checks_evaluated.append({
                "id": "line_qty_matches_quote",
                "scope": "per_line",
                "matched": not fired,
                "fired": fired,
                "severity": (qty_rule or {}).get("severity") or "hard",
                "message": f"sku '{sku}' qty {po_qty} vs quoted {q_qty}",
                "evidence": {"sku": sku, "po_qty": po_qty, "quoted_qty": q_qty},
            })
            if fired:
                issues.append({
                    "kind": (qty_rule or {}).get("issue_kind") or "qty_mismatch",
                    "sku": sku, "po_qty": po_qty, "quoted_qty": q_qty,
                })

    # ------------------------------------------------------------------
    # PER-TOTAL checks.
    # ------------------------------------------------------------------
    for r in per_total_rules:
        rid = r.get("id") or ""
        predicate = r.get("predicate") or ""
        if not predicate:
            continue
        # quote_line_missing_in_po: special — emit one issue per missing SKU.
        if rid == "quote_line_missing_in_po":
            missing = quote_skus - po_skus
            fired = len(missing) > 0
            checks_evaluated.append({
                "id": rid,
                "scope": "per_total",
                "matched": not fired,
                "fired": fired,
                "severity": r.get("severity") or "soft",
                "message": (
                    f"{len(missing)} quoted SKU(s) absent from PO"
                    if fired else "every quoted SKU present in PO"
                ),
                "evidence": {"missing_skus": sorted(missing), "po_skus": sorted(po_skus), "quote_skus": sorted(quote_skus)},
            })
            if fired:
                for sku in sorted(missing):
                    issues.append({"kind": r.get("issue_kind") or "missing_quoted_line", "sku": sku})
            continue

        ok, err = _evaluate_predicate(predicate, base_ctx)
        # `fires_when` defaults to predicate_false (most checks express the
        # PASSING condition, fire when the predicate fails).
        fires_when = r.get("fires_when") or "predicate_false"
        fired = (ok and fires_when == "predicate_true") or ((not ok) and fires_when == "predicate_false")
        if err:
            fired = False
        message = _per_total_message(rid, fired, base_ctx)
        checks_evaluated.append({
            "id": rid,
            "scope": "per_total",
            "matched": not fired,
            "fired": fired,
            "severity": r.get("severity") or "warn",
            "message": message,
            "evidence": _per_total_evidence(rid, base_ctx),
            "predicate": predicate,
            "predicate_error": err,
        })
        if fired:
            issues.append({
                "kind": r.get("issue_kind") or rid,
                "rule_id": rid,
                **_per_total_evidence(rid, base_ctx),
            })

    return {
        "checked": True,
        "matched_quote": {
            "quote_number": quote.quote_number,
            "id": quote.id,
            "total": quote.total,
            "currency": quote.currency,
        },
        "issues": issues,
        "checks_evaluated": checks_evaluated,
        "kb_namespace": "reconcile_checks",
        "notes": notes,
    }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


class _PoLine:
    """Wrapper that exposes po_line.sku / .qty / .unit_price as attributes
    so KB predicates can use the dotted form without needing dict subscripts."""

    __slots__ = ("_d",)

    def __init__(self, d: dict) -> None:
        self._d = d or {}

    def __getattr__(self, name: str):
        v = self._d.get(name)
        if name in ("qty",):
            return _to_int(v)
        if name in ("unit_price",):
            return _to_float(v)
        return v


class _QuoteLine(_PoLine):
    pass


def _eval_context_for_line(
    base_ctx: dict,
    *,
    po_li: _PoLine | None,
    quote_line: _QuoteLine | None,
    fuzzy_match_score: float,
    fuzzy_match_threshold: float,
) -> dict:
    """Per-line eval context — base_ctx + the line-scoped vars."""
    ctx = dict(base_ctx)
    ctx["po_line"] = po_li
    ctx["quote_line"] = quote_line
    ctx["fuzzy_match_score"] = float(fuzzy_match_score or 0.0)
    ctx["fuzzy_match_threshold"] = float(fuzzy_match_threshold or 0.7)
    return ctx


def _eval_rule_fires(rule: dict | None, eval_ctx: dict) -> bool:
    if not rule:
        return False
    predicate = rule.get("predicate") or ""
    if not predicate:
        return False
    fires_when = rule.get("fires_when") or "predicate_false"
    ok, err = _evaluate_predicate(predicate, eval_ctx)
    if err:
        return False
    if fires_when == "predicate_true":
        return bool(ok)
    return not bool(ok)


def _per_total_message(rid: str, fired: bool, ctx: dict) -> str:
    if rid == "total_amount_sum_matches_lines":
        if fired:
            return f"PO total {ctx['extracted_total']:.2f} ≠ Σ(qty×price) {ctx['line_items_sum']:.2f}"
        return f"PO total {ctx['extracted_total']:.2f} matches line-item sum {ctx['line_items_sum']:.2f}"
    if rid == "total_matches_quote_total":
        if fired:
            return f"PO total {ctx['extracted_total']:.2f} ≠ quote total {ctx['quote_total']:.2f}"
        return f"PO total matches quote total ({ctx['quote_total']:.2f})"
    if rid == "payment_terms_matches_quote":
        if fired:
            return f"PO terms '{ctx['extracted_payment_terms']}' ≠ quote terms '{ctx['quote_payment_terms']}'"
        return "payment terms match (or one side blank)"
    if rid == "currency_matches_quote":
        if fired:
            return f"PO currency '{ctx['extracted_currency']}' ≠ quote currency '{ctx['quote_currency']}'"
        return "currency matches (or one side blank)"
    if rid == "bill_to_matches_account_billing":
        if fired:
            return "PO bill-to has no overlap with account billing address"
        return "PO bill-to overlaps with account billing address (or one side blank)"
    if rid == "incoterms_matches_quote":
        if fired:
            return f"PO incoterms '{ctx['extracted_incoterms']}' ≠ quote incoterms '{ctx['quote_incoterms']}'"
        return "incoterms match (or one side blank)"
    if rid == "duplicate_po_in_recent_orders":
        if fired:
            return f"PoNumber '{ctx['extracted_po_number']}' already on a recent SF Order"
        return "PoNumber not duplicated on recent SF Orders"
    return "ok" if not fired else "predicate fired"


def _per_total_evidence(rid: str, ctx: dict) -> dict:
    if rid == "total_amount_sum_matches_lines":
        return {
            "extracted_total": ctx["extracted_total"],
            "line_items_sum": round(ctx["line_items_sum"], 4),
        }
    if rid == "total_matches_quote_total":
        return {"extracted_total": ctx["extracted_total"], "quote_total": ctx["quote_total"]}
    if rid == "payment_terms_matches_quote":
        return {
            "extracted_payment_terms": ctx["extracted_payment_terms"],
            "quote_payment_terms": ctx["quote_payment_terms"],
        }
    if rid == "currency_matches_quote":
        return {
            "extracted_currency": ctx["extracted_currency"],
            "quote_currency": ctx["quote_currency"],
        }
    if rid == "bill_to_matches_account_billing":
        return {
            "extracted_bill_to": ctx["extracted_bill_to"],
            "account_billing": ctx["account_billing_combined"],
        }
    if rid == "incoterms_matches_quote":
        return {
            "extracted_incoterms": ctx["extracted_incoterms"],
            "quote_incoterms": ctx["quote_incoterms"],
        }
    if rid == "duplicate_po_in_recent_orders":
        return {
            "extracted_po_number": ctx["extracted_po_number"],
            "recent_order_po_numbers": ctx["recent_order_po_numbers"],
        }
    return {}


def _to_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _to_int(v) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def _fuzzy_pick(s: str, choices: list[str], threshold: float = 0.0) -> tuple[str | None, float]:
    """Returns (best_choice, score) — caller decides whether score crosses threshold."""
    best, score = None, 0.0
    for c in choices:
        r = SequenceMatcher(None, s or "", c or "").ratio()
        if r > score:
            best, score = c, r
    if score >= threshold:
        return best, score
    return None, score
