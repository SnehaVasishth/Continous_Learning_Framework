"""PII redaction layer applied to LLM inputs.

Replaces sensitive patterns (credit card, SSN, passport, IBAN, phone, email
address aside from the sender, API keys) with stable placeholders BEFORE
any text leaves the process for an LLM provider. The redaction is
deterministic per-pattern so an LLM still sees a consistent token across
the prompt, but the original value never reaches the provider.

Each pattern detected is also logged so the audit trail records what was
redacted, on which pipeline, and at which stage. The Stage 3.4 verifier
can read these counts when checking compliance invariants.

Strategy:
  - regex match each pattern over the input string
  - replace with `<REDACTED_KIND_n>` where `n` is a per-pattern counter
  - return (redacted_text, redactions_summary)

Counters are local to a single redact() call; correlation across stages
is via the summary dict caller can persist or log.
"""
from __future__ import annotations

import re
from typing import Any


# Order matters — more-specific patterns must run before broader ones so a
# 16-digit card isn't first captured by a phone pattern.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Credit card: 13–19 digits, optional spaces or hyphens. Mod-10 check
    # would reduce false positives but bloats the regex; for the demo we
    # match on shape and let the redaction itself be cheap.
    ("CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    # US SSN: 3-2-4 with hyphens or spaces.
    ("SSN", re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")),
    # IBAN: 2-letter country + 2-digit check + 11–30 alphanumeric.
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    # Passport: 1 letter + 7-8 digits (US/UK shape). Conservative.
    ("PASSPORT", re.compile(r"\b[A-Z]\d{7,8}\b")),
    # Phone: international format. Conservative — must NOT be embedded in an
    # alphanumeric-hyphen identifier (PO-LH-2026-0042, SO-LH-7733, etc.) and
    # must carry at least one phone-specific marker (leading "+", parens
    # around an area code, or three hyphen/space-separated groups starting
    # with a 3+ digit country/area code). Loosening this regex repeatedly
    # masked customer order numbers in reply drafts as "<REDACTED_PHONE_n>".
    ("PHONE", re.compile(
        r"(?<![A-Za-z0-9-])"
        r"(?:"
        r"  \+\d{1,3}[ -]?(?:\(\d{1,4}\)[ -]?)?\d{2,4}[ -]\d{2,4}[ -]?\d{2,4}"  # +1 (415) 555-1234 / +44 20 7946 0958
        r"| \(\d{2,4}\)[ -]?\d{3,4}[ -]?\d{3,4}"                                 # (415) 555-1234
        r"| \d{3,4}[ -]\d{3,4}[ -]\d{3,4}"                                       # 415-555-1234 (groups of 3-4 each)
        r")"
        r"(?![A-Za-z0-9-])",
        re.VERBOSE,
    )),
    # API key or secret-ish blob: prefixes plus 20+ alphanumerics.
    ("APIKEY", re.compile(r"\b(?:sk-|pk-|ak-|api[_-]?key[\":= ]+|secret[\":= ]+)[A-Za-z0-9_-]{20,}\b", re.IGNORECASE)),
    # AWS access key id.
    ("AWSKEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]


def redact(text: str) -> tuple[str, dict[str, Any]]:
    """Return (redacted_text, summary).

    `summary` shape:
      {
        "redacted": bool,                  # True if anything was replaced
        "counts": { kind: n, ... },        # per-kind hit count
        "total": int,                      # sum of counts
        "kinds": [kind, ...],              # ordered list of kinds present
      }

    The original `text` is never returned mutated when no PII is found —
    callers can compare object identity if they need to short-circuit.
    """
    if not text or not isinstance(text, str):
        return text, {"redacted": False, "counts": {}, "total": 0, "kinds": []}
    out = text
    counts: dict[str, int] = {}
    for kind, rx in _PATTERNS:
        n = 0

        def _sub(_m: re.Match[str], _kind: str = kind) -> str:
            nonlocal n
            n += 1
            return f"<REDACTED_{_kind}_{n}>"

        out = rx.sub(_sub, out)
        if n:
            counts[kind] = n
    total = sum(counts.values())
    return out, {
        "redacted": total > 0,
        "counts": counts,
        "total": total,
        "kinds": list(counts.keys()),
    }


def redact_for_llm(system: str | None, user: str | None) -> tuple[str | None, str | None, dict[str, Any]]:
    """Convenience wrapper used by the LLM gateway. Redacts both prompts
    and aggregates their summaries into a single dict suitable for trace
    logging."""
    s_out, s_sum = redact(system) if system else (system, {"redacted": False, "counts": {}, "total": 0, "kinds": []})
    u_out, u_sum = redact(user) if user else (user, {"redacted": False, "counts": {}, "total": 0, "kinds": []})
    merged_counts: dict[str, int] = {}
    for k, v in (s_sum.get("counts") or {}).items():
        merged_counts[k] = merged_counts.get(k, 0) + v
    for k, v in (u_sum.get("counts") or {}).items():
        merged_counts[k] = merged_counts.get(k, 0) + v
    total = sum(merged_counts.values())
    return s_out, u_out, {
        "redacted": total > 0,
        "counts": merged_counts,
        "total": total,
        "kinds": list(merged_counts.keys()),
        "system_redacted_total": s_sum.get("total", 0),
        "user_redacted_total": u_sum.get("total", 0),
    }
