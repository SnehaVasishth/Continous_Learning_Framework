"""Pattern-list candidate generator.

Surfaces a candidate when CSRs repeatedly override the classifier toward a
deterministic-rule intent (kso / collections / portal_admin / brazil_tax /
spam). The hypothesis is that the deterministic pre-AI rule's pattern list
is missing a phrase the CSRs are using to recognise the case.

Signal: feedback rows where stage="intake", kind="edit", and the corrected
intent is one of the terminal redirect intents. Cluster by the corrected
intent; extract candidate phrases from the originating email subjects /
bodies (top noun-bigrams not already in the rule); propose adding the top
unmatched phrase to the rule's keyword list.

Apply path: append phrases to the relevant KB rule's keywords field, leaving
all other fields unchanged. Per-intent fingerprint dedups recurring
suggestions.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ... import kb as kb_module
from ...models import Email, Feedback, LearningOpportunity, Pipeline


def _anchor(db: Session, segment: str | None) -> int | None:
    try:
        from . import resolve_baseline_id_for_segment
        return resolve_baseline_id_for_segment(db, segment)
    except Exception:
        return None


_LOOKBACK_DAYS = 30
_MIN_OVERRIDES = 3
_TERMINAL_INTENTS = {"kso", "collections", "portal_admin", "brazil_tax", "spam"}
_STOPWORDS = {
    "the", "and", "for", "with", "from", "your", "this", "that", "have", "will",
    "are", "was", "were", "been", "you", "our", "we", "to", "of", "in", "on",
    "by", "is", "be", "as", "at", "an", "or", "it", "any", "all", "but",
}


def _fingerprint(target_intent: str) -> str:
    return f"pattern_list:rule:{target_intent}"


def _candidate_phrases(emails: list[Email], existing_keywords: set[str], top_n: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for e in emails:
        text = " ".join([e.subject or "", e.body or ""]).lower()
        tokens = re.findall(r"[a-z0-9][a-z0-9\-/]+", text)
        for i in range(len(tokens) - 1):
            if tokens[i] in _STOPWORDS or tokens[i + 1] in _STOPWORDS:
                continue
            if len(tokens[i]) < 3 or len(tokens[i + 1]) < 3:
                continue
            bigram = f"{tokens[i]} {tokens[i + 1]}"
            if bigram in existing_keywords:
                continue
            counter[bigram] += 1
    return [phrase for phrase, _ in counter.most_common(top_n)]


def generate(db: Session) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    edits = (
        db.query(Feedback)
        .filter(Feedback.stage == "intake")
        .filter(Feedback.kind == "edit")
        .filter(Feedback.created_at >= cutoff)
        .all()
    )
    overrides_to_terminal: dict[str, list[int]] = {}
    for f in edits:
        data = f.data if isinstance(f.data, dict) else {}
        to_intent = (data.get("to_intent") or "").strip()
        if to_intent not in _TERMINAL_INTENTS:
            continue
        if f.pipeline_id is not None:
            overrides_to_terminal.setdefault(to_intent, []).append(int(f.pipeline_id))

    inserted: list[dict[str, Any]] = []
    for target_intent, pipe_ids in overrides_to_terminal.items():
        if len(pipe_ids) < _MIN_OVERRIDES:
            continue
        fp = _fingerprint(target_intent)
        existing = (
            db.query(LearningOpportunity)
            .filter(LearningOpportunity.fingerprint == fp)
            .filter(LearningOpportunity.status.in_(["open", "accepted", "in_ab"]))
            .first()
        )
        if existing is not None:
            continue
        pipes = db.query(Pipeline).filter(Pipeline.id.in_(pipe_ids)).all()
        email_ids = [p.email_id for p in pipes if p.email_id]
        emails = db.query(Email).filter(Email.id.in_(email_ids)).all() if email_ids else []
        if not emails:
            continue
        # Read the existing keyword list from the live rule body so we don't
        # propose adding a phrase that is already there.
        existing_keywords: set[str] = set()
        try:
            for r in kb_module.list_rules(db, "intent"):
                if r.key == target_intent:
                    body = r.body or {}
                    for k in (body.get("keywords") or []):
                        if isinstance(k, str):
                            existing_keywords.add(k.lower().strip())
        except Exception:
            pass
        phrases = _candidate_phrases(emails, existing_keywords)
        if not phrases:
            continue
        opp = LearningOpportunity(
            segment=f"intent:{target_intent}",
            fingerprint=fp,
            proposed_remedy=json.dumps({
                "change_type": "pattern_list",
                "scope": {"namespace": "intent", "key": target_intent, "field": "keywords"},
                "current_keywords_sample": sorted(existing_keywords)[:8],
                "proposed_add": phrases[:5],
                "rationale": (
                    f"{len(pipe_ids)} CSR overrides flipped cases to '{target_intent}' in the "
                    f"last {_LOOKBACK_DAYS} days. The classifier missed these because the "
                    f"deterministic rule's keyword list does not match the phrasing customers used."
                ),
            }),
            expected_lift=f"Catch {len(pipe_ids)} similar cases without CSR action",
            effort="Low",
            risk="Low",
            score=round(min(len(pipe_ids) / 5.0, 10.0), 2),
            status="open",
            source="csr_override_cluster",
            sample_pipeline_ids=sorted(pipe_ids),
            baseline_id=_anchor(db, f"intent:{target_intent}"),
        )
        db.add(opp)
        inserted.append({"target_intent": target_intent, "added_phrases": phrases[:5], "override_count": len(pipe_ids)})
    if inserted:
        db.commit()
    return inserted
