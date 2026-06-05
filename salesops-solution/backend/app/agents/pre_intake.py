# === v1.1 TASK-2 START ===
"""Pre-Intake (Stage 0) — deterministic Outlook-rule short-circuit.

Runs BEFORE Stage 1 Intake. If any KB `outlook_rules` rule matches, the
pipeline short-circuits and routes to the rule's redirect destination
(via the orchestrator's terminal-intent branch). NO LLM CALL IS MADE for
matched emails — saves tokens AND mirrors the prior Keysight POC's existing
deterministic Outlook layer exactly.

The rule predicates are pure string / regex matching. The actionable-exception
guard is the one piece of LLM-style heuristic — it's a quick string scan for
'directive' verbs (please, kindly, find attached, requesting, ship, cancel,
update, process, release, schedule, expedite). When found in the same body
the rule matched on, the rule is suppressed and the pipeline continues to
Stage 1 (which will figure out the actual intent).

Hard-block rules (severity="hard_block", e.g. UNDELIVERABLE / KSO) ignore
the actionable exception — these are too sensitive to risk a heuristic miss.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from .. import kb
from ..models import Email

log = logging.getLogger(__name__)


_DIRECTIVE_PATTERNS = re.compile(
    r"\b(please|kindly|find\s+attached|requesting|request\s+to|ship|cancel|"
    r"update|process|release|schedule|expedite|approve|book|confirm|"
    r"acknowledge|issue\s+(soa|order)|return|exchange|repair|calibrate)\b",
    re.IGNORECASE,
)


def _check_directive(text: str) -> bool:
    return bool(_DIRECTIVE_PATTERNS.search(text or ""))


def _domain(addr: str) -> str:
    addr = (addr or "").lower()
    m = re.search(r"@([\w.-]+)", addr)
    return m.group(1) if m else ""


def _match_predicate(pred: dict, *, subject: str, body: str, sender: str) -> bool:
    kind = pred.get("kind", "")
    values = pred.get("value", [])
    if isinstance(values, str):
        values = [values]
    cs = pred.get("case_sensitive", False)
    if not cs:
        subj_l = (subject or "").lower()
        body_l = (body or "").lower()
        sender_l = (sender or "").lower()
        values = [(v or "").lower() for v in values]
    else:
        subj_l = subject or ""
        body_l = body or ""
        sender_l = sender or ""

    if kind == "subject_contains":
        return any(v in subj_l for v in values)
    if kind == "subject_equals":
        return subj_l.strip() in [v.strip() for v in values]
    if kind == "body_contains":
        return any(v in body_l for v in values)
    if kind == "sender_equals":
        return sender_l.strip() in [v.strip() for v in values]
    if kind == "sender_contains":
        return any(v in sender_l for v in values)
    if kind == "sender_domain":
        d = _domain(sender_l)
        return any(d == v.strip() or d.endswith("." + v.strip()) for v in values)
    if kind == "regex_subject":
        return any(re.search(v, subject or "", 0 if cs else re.IGNORECASE) for v in values)
    if kind == "regex_body":
        return any(re.search(v, body or "", 0 if cs else re.IGNORECASE) for v in values)
    return False


def evaluate(email: Email) -> dict[str, Any] | None:
    """Walk KB outlook_rules in priority order. First match wins.

    Returns a dict on match:
      {
        "matched": True,
        "rule_key": "outlook.kso",
        "rule_label": "KSO — Government / Defense / Federal-Prime",
        "intent": "kso",
        "redirect_to": "keysightorders@keysight.com",
        "predicate_kind": "sender_domain",
        "matched_value": "boeing.com",
        "actionable_exception_suppressed": False,
        "reason": "Pre-intake rule outlook.kso matched on sender_domain",
      }

    Returns None if no rule matches.
    """
    rules = kb.outlook_rules()
    subject = email.subject or ""
    body = email.body or ""
    sender = email.from_address or ""
    has_directive = _check_directive(body)

    for rule in rules:
        preds = rule.get("predicates") or []
        matched_pred = None
        for p in preds:
            if _match_predicate(p, subject=subject, body=body, sender=sender):
                matched_pred = p
                break
        if matched_pred is None:
            continue

        # Actionable exception — only honored for non-hard-block rules.
        # Hard-block rules (KSO, UNDELIVERABLE) fire even with a directive.
        severity = (rule.get("severity") or "warn").lower()
        if (
            rule.get("actionable_exception", False)
            and has_directive
            and severity != "hard_block"
        ):
            log.info(
                "pre_intake suppressed rule %s due to actionable directive in body",
                rule.get("id"),
            )
            continue

        return {
            "matched": True,
            "rule_key": rule.get("id"),
            "rule_label": rule.get("label"),
            "intent": rule.get("intent"),
            "redirect_to": rule.get("redirect_to"),
            "severity": severity,
            "predicate_kind": matched_pred.get("kind"),
            "matched_value": matched_pred.get("value"),
            "actionable_exception_suppressed": False,
            "reason": (
                f"Pre-intake rule {rule.get('id')} matched on "
                f"{matched_pred.get('kind')} ({rule.get('label')})"
            ),
        }

    return None
# === v1.1 TASK-2 END ===
