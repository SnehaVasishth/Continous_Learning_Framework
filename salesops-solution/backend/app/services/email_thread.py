"""Email thread assembly — walks Message-Id / In-Reply-To / References to
return the full chronological chain of an email's conversation.

Threading model (RFC 5322 §3.6.4):
- `Message-Id`     unique id of an individual message
- `In-Reply-To`    parent message-id (set when this message is a reply)
- `References`     space-separated chain of all ancestor message-ids

We use both DB-side fields (`Email.message_id`, `Email.in_reply_to`,
`Email.email_references`) and a subject-similarity fallback (Re:/Fwd: stripped
+ first sender match) for cases where threading headers are missing — common
when a customer replies from a phone client that drops headers.

This module is pure read-only over the Email table. The orchestrator and
prompts call `walk_thread(db, email)` to get a chronological list, identify
the root, and feed the full thread to LLM stages.
"""
from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Email


# ---------- low-level helpers ----------


_RE_FWD_PREFIX = re.compile(r"^\s*((re|fwd?|aw|sv)\s*:\s*)+", re.IGNORECASE)


def normalize_subject(subj: str | None) -> str:
    """Strip 'Re:' / 'Fwd:' chains so subject-based grouping works across replies."""
    if not subj:
        return ""
    out = subj
    while True:
        nxt = _RE_FWD_PREFIX.sub("", out)
        if nxt == out:
            break
        out = nxt
    return out.strip()


def parse_references(references: str | None) -> list[str]:
    """Split the References header into individual message-ids preserving order."""
    if not references:
        return []
    # Message-ids are <foo@bar>; split on whitespace and strip empties.
    parts = [p.strip() for p in references.split()]
    return [p for p in parts if p]


def _ancestor_ids(email: Email) -> list[str]:
    """All ancestor Message-Ids known for this email (References + In-Reply-To, dedup)."""
    seen: set[str] = set()
    out: list[str] = []
    for mid in parse_references(email.email_references):
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    if email.in_reply_to and email.in_reply_to not in seen:
        out.append(email.in_reply_to)
    return out


# ---------- thread walk ----------


def walk_thread(db: Session, email: Email) -> list[Email]:
    """Return every Email in the same thread as `email`, ordered by received_at asc.

    Strategy:
      1. Collect all Message-Ids known to be in the thread:
         - this email's own message_id
         - every entry in this email's References + In-Reply-To
         - every email whose In-Reply-To or References contains any id we've
           collected (transitive closure, capped at 50 iterations)
      2. Subject-similarity backstop: also include emails with the same
         normalized subject AND same customer-side participant (helps when
         headers are stripped by a phone reply client).
      3. Sort the merged set chronologically.
    """
    if not email:
        return []

    known_ids: set[str] = set()
    if email.message_id:
        known_ids.add(email.message_id)
    known_ids.update(_ancestor_ids(email))

    # Iterative closure — fan out from current ids until no new ids appear.
    for _ in range(50):
        before = len(known_ids)
        if not known_ids:
            break

        # Find emails that reference any of our known ids
        # (LIKE is fine for SQLite at demo scale)
        like_clauses = []
        for mid in list(known_ids):
            esc = mid.replace("%", "\\%").replace("_", "\\_")
            like_clauses.append(esc)

        rows = (
            db.query(Email)
            .filter(
                (Email.message_id.in_(list(known_ids)))
                | (Email.in_reply_to.in_(list(known_ids)))
                | _references_contains_any(known_ids)
            )
            .all()
        )

        for r in rows:
            if r.message_id:
                known_ids.add(r.message_id)
            for mid in _ancestor_ids(r):
                known_ids.add(mid)

        if len(known_ids) == before:
            break

    # Final fetch — every email whose message_id, in_reply_to, or references is
    # in the known_ids set. Plus subject-similarity fallback.
    chain_rows: list[Email] = []
    if known_ids:
        chain_rows = (
            db.query(Email)
            .filter(
                (Email.message_id.in_(list(known_ids)))
                | (Email.in_reply_to.in_(list(known_ids)))
                | _references_contains_any(known_ids)
            )
            .all()
        )

    # Subject-similarity fallback (only if we found very few via headers).
    if len(chain_rows) <= 1:
        norm_subj = normalize_subject(email.subject)
        if norm_subj:
            sub_rows = (
                db.query(Email)
                .filter(Email.subject.ilike(f"%{norm_subj[:60]}%"))
                .all()
            )
            # require the same customer/sender appears at least once to avoid
            # cross-customer subject collisions ("Quote update" is generic).
            customer_id = email.customer_id
            account_id = email.account_id
            for r in sub_rows:
                same_customer = (customer_id and r.customer_id == customer_id) or (
                    account_id and r.account_id == account_id
                )
                if same_customer or r.id == email.id:
                    chain_rows.append(r)

    # Always include the seed email itself.
    if email not in chain_rows:
        chain_rows.append(email)

    # Dedupe by id and sort chronologically.
    seen_ids: set[int] = set()
    deduped: list[Email] = []
    for r in chain_rows:
        if r.id in seen_ids:
            continue
        seen_ids.add(r.id)
        deduped.append(r)
    deduped.sort(key=lambda r: (r.received_at or r.id, r.id))
    return deduped


def _references_contains_any(ids: Iterable[str]):
    """Build an OR-chain of LIKE clauses that match if Email.email_references
    contains any of the given message-ids. Returns a SQLAlchemy clause."""
    ids = [i for i in ids if i]
    if not ids:
        # Always-false clause
        return Email.id == -1
    clauses = [Email.email_references.like(f"%{i}%") for i in ids]
    expr = clauses[0]
    for c in clauses[1:]:
        expr = expr | c
    return expr


# ---------- thread shape helpers ----------


def thread_root(emails: list[Email]) -> Email | None:
    """The earliest message — first by received_at."""
    return emails[0] if emails else None


def thread_summary_for_prompt(emails: list[Email], *, max_chars_per_msg: int = 1200) -> str:
    """Render a compact, LLM-readable summary of the chain.

    Keeps headers minimal and truncates each body. Used by Stage 1/2 prompts
    where we want the model to see the full conversation but not blow the
    context window with attachments / quoted-reply chrome."""
    if not emails:
        return ""
    parts: list[str] = []
    for i, e in enumerate(emails, start=1):
        marker = "ROOT (primary intent source)" if i == 1 else f"REPLY {i - 1}"
        ts = e.received_at.isoformat() if e.received_at else "?"
        body = (e.body or "").strip()
        if len(body) > max_chars_per_msg:
            body = body[:max_chars_per_msg] + " …[truncated]"
        parts.append(
            f"--- MESSAGE {i} [{marker}] ---\n"
            f"From: {e.from_address or '?'}\n"
            f"Date: {ts}\n"
            f"Subject: {e.subject or '(no subject)'}\n"
            f"\n{body}"
        )
    return "\n\n".join(parts)


# === v1.1 TASK-3 START === Empty-fragment thread pre-processing.
# Mirrors prior POC's "Empty-fragment skip" override rule: strip messages
# containing only From/To/Subject, CAUTION banners, disclaimers, or
# quoted-only fragments. Walk newest-first to find the FIRST meaningful
# fragment and use that as the primary classification signal.

_BANNER_PATTERNS = [
    re.compile(r"\bCAUTION\s*:.*?external\s+sender", re.IGNORECASE | re.DOTALL),
    re.compile(r"This e-?mail (and any attachments)? is.*confidential", re.IGNORECASE | re.DOTALL),
    re.compile(r"DISCLAIMER\s*:", re.IGNORECASE),
    re.compile(r"This message is intended only for", re.IGNORECASE),
]

_GENERIC_PHRASES = {
    "fyi", "for your information", "just a reminder", "please check below",
    "see previous message", "check earlier email", "sharing for visibility",
    "per our earlier discussion", "looping you in", "forwarding for reference",
    "see below", "see attached",
}

_TRIVIAL_REPLIES = {
    "thanks", "thank you", "noted", "ok", "okay", "fyi", "test", "hello", "hi",
    "received", "got it", "acknowledged", "ack",
}

_FROM_HEADER = re.compile(r"^\s*From:\s+", re.IGNORECASE | re.MULTILINE)


def is_meaningful_fragment(text: str) -> bool:
    """Returns True if the fragment carries user-written or system-generated business content.

    A fragment is NOT meaningful if it contains only:
      - From/To/Subject headers (and nothing else)
      - Banner / disclaimer / CAUTION text
      - Empty forwards (only quoted older content with no new text)
      - Trivial acknowledgements ("Thanks", "Noted", "OK")
      - Generic context-free phrases ("FYI", "see below", "looping you in")
        when the fragment is short
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 30:
        if s.lower() in _TRIVIAL_REPLIES:
            return False
        return False

    cleaned = s
    for pat in _BANNER_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = cleaned.strip()

    no_headers = _FROM_HEADER.sub("", cleaned).strip()
    if len(no_headers) < 30:
        return False

    lower = cleaned.lower()
    if len(cleaned) < 200:
        if any(ph in lower for ph in _GENERIC_PHRASES):
            non_generic = lower
            for ph in _GENERIC_PHRASES:
                non_generic = non_generic.replace(ph, "")
            non_generic = re.sub(r"[\s\-—_:.]+", "", non_generic)
            if len(non_generic) < 30:
                return False

    return True


def split_thread_fragments(body: str) -> list[str]:
    """Split a thread body into per-message fragments using From: as delimiter.

    Returns fragments in CHRONOLOGICAL order with newest first (matches the
    typical Outlook reply-quoting style: latest message at top, oldest at bottom).
    """
    if not body:
        return []
    parts = _FROM_HEADER.split(body)
    fragments = [parts[0]]
    for p in parts[1:]:
        fragments.append(("From: " + p).strip())
    return [f.strip() for f in fragments if f.strip()]


def pick_first_valid_fragment(body: str) -> tuple[str, int]:
    """Walk fragments newest-first, return (fragment, index_from_top).

    Returns ('', -1) if no valid fragment is found in the entire thread.
    """
    fragments = split_thread_fragments(body)
    for i, frag in enumerate(fragments):
        if is_meaningful_fragment(frag):
            return frag, i
    return ("", -1)
# === v1.1 TASK-3 END ===
