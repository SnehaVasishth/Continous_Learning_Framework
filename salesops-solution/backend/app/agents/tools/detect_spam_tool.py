"""Heuristic spam pre-screen — KB-driven (namespace=spam_heuristic).

Rules are sourced from Apache SpamAssassin (Apache 2.0), SwiftFilter (MIT) and
custom additions; see backend/app/kb_seeds/spam_heuristic_rules.py for source
attribution. Rules are user-editable through the KB Settings UI.

Each rule is a dict with: id, category, description, regex, field
(subject|body|sender|from_domain), flags, severity (low|medium|high),
source, score_weight.
"""
from __future__ import annotations

import re
from typing import Any

from ... import kb
from ..base import AgentContext, Tool, ToolResult


_SPAM_THRESHOLD = 3.0


def _compile(pattern: str, flag_str: str) -> re.Pattern | None:
    flags = re.IGNORECASE if "i" in (flag_str or "").lower() else 0
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def _extract_field(field: str, *, subject: str, body: str, sender: str, from_domain: str) -> str:
    return {
        "subject": subject,
        "body": body,
        "sender": sender,
        "from_domain": from_domain,
    }.get(field, "")


class DetectSpamTool(Tool):
    """KB-driven heuristic spam pre-screen (~50 rules from SpamAssassin/SwiftFilter)."""

    name = "detect_spam"
    description = "Heuristic spam pre-screen — KB-driven regex over subject/body/sender (SpamAssassin + SwiftFilter rules)."
    kb_namespaces = ["spam_heuristic"]

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            subject = email.get("subject") or inputs.get("subject") or ""
            body = email.get("body") or inputs.get("body") or ""
            sender = email.get("from") or inputs.get("sender") or ""
            from_domain = sender.split("@", 1)[1] if "@" in sender else ""

            try:
                rules = kb.spam_heuristic_rules() or []
            except Exception:
                rules = []

            rules_evaluated: list[dict[str, Any]] = []
            score = 0.0
            rules_matched: list[dict[str, Any]] = []
            categories_hit: set[str] = set()

            for rule in rules:
                pat = _compile(rule.get("regex") or "", rule.get("flags") or "")
                if pat is None:
                    rules_evaluated.append({
                        "id": rule.get("id"),
                        "field": rule.get("field"),
                        "regex": rule.get("regex"),
                        "category": rule.get("category"),
                        "severity": rule.get("severity"),
                        "score_weight": rule.get("score_weight"),
                        "source": rule.get("source"),
                        "matched": False,
                        "error": "regex_compile_failed",
                    })
                    continue
                target = _extract_field(
                    rule.get("field") or "",
                    subject=subject, body=body, sender=sender, from_domain=from_domain,
                )
                matched = bool(pat.search(target)) if target else False
                evaluated = {
                    "id": rule.get("id"),
                    "field": rule.get("field"),
                    "regex": rule.get("regex"),
                    "category": rule.get("category"),
                    "description": rule.get("description"),
                    "severity": rule.get("severity"),
                    "score_weight": rule.get("score_weight"),
                    "source": rule.get("source"),
                    "matched": matched,
                }
                rules_evaluated.append(evaluated)
                if matched:
                    score += float(rule.get("score_weight") or 0.0)
                    rules_matched.append(evaluated)
                    cat = rule.get("category")
                    if cat:
                        categories_hit.add(cat)

            is_spam = score >= _SPAM_THRESHOLD
            score_pct = min(1.0, score / max(_SPAM_THRESHOLD * 2, 0.001))

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "is_spam": is_spam,
                    "score": round(score, 2),
                    "score_normalized": round(score_pct, 3),
                    "threshold": _SPAM_THRESHOLD,
                    "reasons": [r["id"] for r in rules_matched],
                    "categories_hit": sorted(categories_hit),
                    "rules_total": len(rules_evaluated),
                    "rules_evaluated": rules_evaluated,
                    "rules_matched": rules_matched,
                    "checked_subject": subject[:200],
                    "checked_sender": sender[:200],
                    "input_preview": f"subject={subject[:120]} | from={sender[:80]} | body={(body or '')[:120]}",
                    "output_summary": (
                        f"{'SPAM' if is_spam else 'clean'} "
                        f"(score={score:.1f}/{_SPAM_THRESHOLD}, "
                        f"{len(rules_matched)} of {len(rules_evaluated)} rules matched"
                        f"{', categories=' + ', '.join(sorted(categories_hit)) if categories_hit else ''})"
                    ),
                    "processing_method": "regex_heuristic_kb_driven",
                    "provider": "SpamAssassin + SwiftFilter ruleset (KB namespace=spam_heuristic)",
                    "kb_namespaces_consulted": ["spam_heuristic"],
                },
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
