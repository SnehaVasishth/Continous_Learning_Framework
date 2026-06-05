"""Evaluate KB `business_rules` predicates against the AgentContext."""
from __future__ import annotations

import ast
import operator
import re
from datetime import date, datetime
from typing import Any

from ... import kb
from ..base import AgentContext, Tool, ToolResult


_VALID_SEVERITIES = {"hard_block", "cap_at_0.70", "cap_at_0.88", "warn"}


def _coerce_date(s: Any) -> date | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    txt = str(s).strip()
    if not txt:
        return None
    # Strip trailing time / timezone if present.
    txt = txt.split("T")[0].split(" ")[0]
    try:
        return date.fromisoformat(txt)
    except Exception:
        return None


def _fn_days_until(s: Any) -> int:
    d = _coerce_date(s)
    if d is None:
        return 0
    return (d - date.today()).days


def _fn_days_since(s: Any) -> int:
    d = _coerce_date(s)
    if d is None:
        return 0
    return (date.today() - d).days


def _fn_regex_match(s: Any, pattern: Any) -> bool:
    if s is None or pattern is None:
        return False
    try:
        return re.search(str(pattern), str(s)) is not None
    except re.error:
        return False


def _fn_endswith(s: Any, suffix: Any) -> bool:
    if s is None or suffix is None:
        return False
    return str(s).endswith(str(suffix))


def _fn_startswith(s: Any, prefix: Any) -> bool:
    if s is None or prefix is None:
        return False
    return str(s).startswith(str(prefix))


def _fn_contains(s: Any, sub: Any) -> bool:
    if s is None or sub is None:
        return False
    try:
        return str(sub) in str(s)
    except Exception:
        return False


# Whitelisted helper functions callable from predicate strings. Keep this
# tightly scoped — the safe-eval explicitly rejects any name not in here.
_ALLOWED_FUNCTIONS: dict[str, Any] = {
    # custom helpers
    "days_until": _fn_days_until,
    "days_since": _fn_days_since,
    "regex_match": _fn_regex_match,
    "endswith": _fn_endswith,
    "startswith": _fn_startswith,
    "contains": _fn_contains,
    # safe built-ins (no I/O, no eval, no reflection)
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
    "round": round,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
}


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BOOL_OPS = {
    ast.And: all,
    ast.Or: any,
}

_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Not: operator.not_,
}


class _SafeEvalError(Exception):
    pass


def _safe_eval(node: ast.AST, vars_: dict) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, vars_)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in vars_:
            return vars_[node.id]
        if node.id in ("None", "True", "False"):
            return {"None": None, "True": True, "False": False}[node.id]
        raise _SafeEvalError(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp):
        op_t = type(node.op)
        if op_t not in _BIN_OPS:
            raise _SafeEvalError(f"binop not allowed: {op_t.__name__}")
        return _BIN_OPS[op_t](_safe_eval(node.left, vars_), _safe_eval(node.right, vars_))
    if isinstance(node, ast.UnaryOp):
        op_t = type(node.op)
        if op_t not in _UNARY_OPS:
            raise _SafeEvalError(f"unaryop not allowed: {op_t.__name__}")
        return _UNARY_OPS[op_t](_safe_eval(node.operand, vars_))
    if isinstance(node, ast.BoolOp):
        op_t = type(node.op)
        if op_t not in _BOOL_OPS:
            raise _SafeEvalError(f"boolop not allowed: {op_t.__name__}")
        vals = [_safe_eval(v, vars_) for v in node.values]
        return _BOOL_OPS[op_t](vals)
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, vars_)
        for op, comparator in zip(node.ops, node.comparators):
            op_t = type(op)
            if op_t not in _CMP_OPS:
                raise _SafeEvalError(f"cmpop not allowed: {op_t.__name__}")
            right = _safe_eval(comparator, vars_)
            if not _CMP_OPS[op_t](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.List):
        return [_safe_eval(e, vars_) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(e, vars_) for e in node.elts)
    if isinstance(node, ast.Set):
        return {_safe_eval(e, vars_) for e in node.elts}
    if isinstance(node, ast.Subscript):
        target = _safe_eval(node.value, vars_)
        idx = _safe_eval(node.slice, vars_)
        try:
            return target[idx]
        except Exception:
            return None
    if isinstance(node, ast.Attribute):
        target = _safe_eval(node.value, vars_)
        if isinstance(target, dict):
            return target.get(node.attr)
        # Fall through to attribute access on objects (e.g. SF record wrappers,
        # reconcile per-line wrappers). We never expose modules, functions, or
        # arbitrary objects to predicates — only the eval-context vars dict —
        # so any attribute resolved here is something the caller chose to pass.
        try:
            return getattr(target, node.attr)
        except Exception:
            return None
    if isinstance(node, ast.Call):
        # Only direct calls to whitelisted function names — no method calls,
        # no calls to vars that happen to be callable.
        if not isinstance(node.func, ast.Name):
            raise _SafeEvalError("only direct calls to whitelisted helpers are allowed")
        fname = node.func.id
        if fname not in _ALLOWED_FUNCTIONS:
            raise _SafeEvalError(f"function not allowed: {fname}")
        if node.keywords:
            raise _SafeEvalError("keyword arguments not allowed in predicates")
        args = [_safe_eval(a, vars_) for a in node.args]
        try:
            return _ALLOWED_FUNCTIONS[fname](*args)
        except Exception as e:
            raise _SafeEvalError(f"call_error[{fname}]: {type(e).__name__}: {str(e)[:120]}")
    if isinstance(node, ast.GeneratorExp):
        # Single-comprehension only: e.g. `any(a.foo > 0 for a in xs)` /
        # `any(a in ys for a in xs)`. Multi-clause `for x in xs for y in ys`
        # not allowed because they explode the eval surface.
        if len(node.generators) != 1:
            raise _SafeEvalError("only single-clause generator expressions are allowed")
        gen = node.generators[0]
        if gen.is_async:
            raise _SafeEvalError("async generator expressions not allowed")
        iterable = _safe_eval(gen.iter, vars_)
        if not isinstance(gen.target, ast.Name):
            raise _SafeEvalError("only simple loop variables allowed in generators")
        var_name = gen.target.id
        results = []
        for item in iterable or []:
            inner_vars = dict(vars_)
            inner_vars[var_name] = item
            keep = True
            for cond in gen.ifs:
                if not _safe_eval(cond, inner_vars):
                    keep = False
                    break
            if keep:
                results.append(_safe_eval(node.elt, inner_vars))
        return iter(results)
    if isinstance(node, ast.ListComp):
        if len(node.generators) != 1:
            raise _SafeEvalError("only single-clause list comprehensions are allowed")
        gen = node.generators[0]
        if gen.is_async:
            raise _SafeEvalError("async comprehensions not allowed")
        iterable = _safe_eval(gen.iter, vars_)
        if not isinstance(gen.target, ast.Name):
            raise _SafeEvalError("only simple loop variables allowed in comprehensions")
        var_name = gen.target.id
        out: list = []
        for item in iterable or []:
            inner_vars = dict(vars_)
            inner_vars[var_name] = item
            keep = True
            for cond in gen.ifs:
                if not _safe_eval(cond, inner_vars):
                    keep = False
                    break
            if keep:
                out.append(_safe_eval(node.elt, inner_vars))
        return out
    raise _SafeEvalError(f"unsupported node: {type(node).__name__}")


def _evaluate_predicate(expr: str, vars_: dict) -> tuple[bool, str | None]:
    try:
        tree = ast.parse(expr, mode="eval")
        return bool(_safe_eval(tree, vars_)), None
    except _SafeEvalError as e:
        return False, f"unsupported_expr: {e}"
    except SyntaxError as e:
        return False, f"syntax_error: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def _build_vars(ctx: AgentContext) -> dict:
    extracted = ctx.extracted or {}
    intake = ctx.intake or {}
    customer_match = ctx.customer_match or {}
    decision = ctx.decision or {}
    email = ctx.email or {}

    # The SF Account dict can live in two slightly-different places depending
    # on which stage path populated it — fall through both.
    account = customer_match.get("account") or {}
    if not account:
        account = (customer_match.get("salesforce") or {}).get("account") or {}

    compliance_flags = account.get("Compliance_Flags__c") or ""
    compliance = [c.strip() for c in compliance_flags.split(";") if c.strip()] if compliance_flags else []

    line_items = extracted.get("line_items") or []
    if not isinstance(line_items, list):
        line_items = []

    total = extracted.get("total")
    try:
        total = float(total) if total is not None else 0.0
    except Exception:
        total = 0.0

    region = account.get("Region__c") or ""
    sla = account.get("SLA_Tier__c") or ""
    vertical = account.get("Vertical__c") or ""
    customer_code = (
        account.get("Customer_Code__c")
        or customer_match.get("customer_code")
        or ""
    )

    # Phase D5: enrichment vars — installed base / asset matching, credit
    # utilization, after-hours scoring, ship-to country, EAR/ITAR.
    sf = customer_match.get("salesforce") or {}
    installed_base = sf.get("installed_base") or []
    if not isinstance(installed_base, list):
        installed_base = []

    extracted_assets = extracted.get("assets") or []
    if not isinstance(extracted_assets, list):
        extracted_assets = []

    # Set of serials that already belong to this account — used by the
    # asset_not_on_account rule.
    account_known_serials: set = set()
    for a in installed_base:
        if isinstance(a, dict):
            sn = a.get("SerialNumber") or a.get("serial")
            if sn:
                account_known_serials.add(str(sn))

    credit_limit = _safe_float(account.get("Credit_Limit_USD__c"))
    if credit_limit > 0:
        credit_utilization_pct = round(total / credit_limit, 4)
    else:
        credit_utilization_pct = 0.0

    received_hour_utc = _email_received_hour_utc(email.get("received_at") or email.get("received_iso"))

    ship_to = extracted.get("ship_to") or {}
    if isinstance(ship_to, dict):
        ship_to_country = (ship_to.get("country") or ship_to.get("Country") or "").strip().upper()
    else:
        ship_to_country = ""

    payment_terms = (extracted.get("payment_terms") or "").strip()

    vars_ = {
        "intent": intake.get("intent") or "",
        "language": intake.get("language") or "",
        "spam": bool(intake.get("spam")),
        "intent_confidence": float(intake.get("intent_confidence") or 0.0),
        "track_hint": intake.get("track_hint") or "",
        "total": total,
        "order_amount": total,
        "line_items": line_items,
        "line_count": len(line_items),
        "po_number": extracted.get("po_number") or "",
        "quote_number": extracted.get("quote_number") or "",
        "customer_name": extracted.get("customer_name") or "",
        "customer_code": customer_code,
        "payment_terms": payment_terms,
        "compliance": compliance,
        "compliance_flags": compliance_flags,
        "region": region,
        "sla_tier": sla,
        "vertical": vertical,
        "salesforce_account_id": customer_match.get("salesforce_account_id"),
        "customer_match_score": float(customer_match.get("score") or 0.0),
        "autonomy_tier": decision.get("autonomy_tier") or "",
        "confidence": float(decision.get("confidence") or 0.0),
        # Phase D5 vars
        "installed_base": installed_base,
        "extracted_assets": extracted_assets,
        "account_known_serials": account_known_serials,
        "credit_limit": credit_limit,
        "credit_utilization_pct": credit_utilization_pct,
        "received_hour_utc": received_hour_utc,
        "ship_to_country": ship_to_country,
    }
    return vars_


def _safe_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


def _email_received_hour_utc(received: Any) -> int:
    """Best-effort: pull the UTC hour out of an email.received_at value.
    Returns -1 when unavailable so predicates that compare with `>=` / `<`
    don't accidentally fire on unknown timestamps."""
    if received is None:
        return -1
    if isinstance(received, datetime):
        return received.hour
    txt = str(received).strip()
    if not txt:
        return -1
    # Accept ISO with optional Z / offset; fall back to bare date.
    try:
        # datetime.fromisoformat doesn't support 'Z' until 3.11; strip it.
        s = txt.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.hour
    except Exception:
        pass
    try:
        d = date.fromisoformat(txt.split("T")[0])
        # Bare-date input — no usable hour, return -1 so after-hours rule no-ops.
        _ = d
        return -1
    except Exception:
        return -1


class BusinessRulesEvalTool(Tool):
    """Evaluate every KB `business_rules` predicate against ctx; return fired rules."""

    name = "business_rules_eval"
    description = "Evaluate KB business_rules predicates against the AgentContext."
    kb_namespaces = ["business_rules"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            try:
                rules = kb.list_rules(ctx.db, "business_rules")
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    ok=True,
                    data={"fired": [], "evaluated": 0, "errors": [f"kb_unavailable: {e}"]},
                )

            vars_ = _build_vars(ctx)
            intent = vars_["intent"]
            region = vars_["region"]
            sla_tier = vars_["sla_tier"]
            vertical = vars_["vertical"]
            fired: list[dict] = []
            errors: list[str] = []
            evaluated = 0

            for r in rules:
                body = r.body or {}
                if body.get("active") is False:
                    continue
                predicate = body.get("predicate") or ""
                if not predicate:
                    continue
                applies = body.get("applies_to_intents") or []
                if applies and intent and intent not in applies:
                    continue
                regions = body.get("region") or []
                if regions and region and region not in regions:
                    continue
                # Phase D2: sla_tier + vertical filters mirror region semantics.
                sla_tiers = body.get("sla_tier") or []
                if sla_tiers and sla_tier and sla_tier not in sla_tiers:
                    continue
                verticals = body.get("vertical") or []
                if verticals and vertical and vertical not in verticals:
                    continue

                evaluated += 1
                ok, err = _evaluate_predicate(predicate, vars_)
                if err:
                    errors.append(f"{r.key}: {err}")
                    continue
                if ok:
                    severity = body.get("severity") or "warn"
                    # Phase D3: severity may now be a numeric str/float OR an
                    # enum from _VALID_SEVERITIES. Pass through as-is — the
                    # decide-stage's _resolve_cap() handles both.
                    if isinstance(severity, str) and severity not in _VALID_SEVERITIES:
                        # numeric-string severities like "0.65" are valid; only
                        # reject genuinely-unknown enums.
                        try:
                            float(severity.strip())
                        except (TypeError, ValueError):
                            severity = "warn"
                    fired.append({
                        "key": r.key,
                        "label": r.label or r.key,
                        "severity": severity,
                        "cap_at": body.get("cap_at"),
                        "dry_run": bool(body.get("dry_run")),
                        "message": body.get("message") or "",
                        "predicate": predicate,
                    })
                    ctx.kb_rules_consulted.append(f"business_rules/{r.key}")

            return ToolResult(
                name=self.name,
                ok=True,
                data={"fired": fired, "evaluated": evaluated, "errors": errors},
                notes=[f"{len(fired)} rule(s) fired"] if fired else [],
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
