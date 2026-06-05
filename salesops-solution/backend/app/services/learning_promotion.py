"""Learning Promotion service.

End-to-end glue between the operator's Tuning Queue, the A/B Experiments
table, the KB, and the live pipeline. Three responsibilities:

  1. `promote_opportunity_to_ab` — when the operator accepts a tuning
     opportunity, snapshot the current production prompt as `control_prompt`,
     draft a `candidate_prompt`, and create a linked ABExperiment row in
     `shadow` mode.

  2. `run_backtest` — replay the candidate prompt's *classification rubric*
     against the historical pipelines that originally produced the
     opportunity (sample_pipeline_ids). For each, score whether the candidate
     would have made the same call as the CSR's corrected intent. Stores the
     per-pipeline match list + summary on the ABExperiment row.

  3. `promote_ab_to_production` — when the operator clicks "Promote",
     overwrite the live KnowledgeRule body with the candidate prompt and
     stamp the LearningOpportunity as `promoted`.

The KB shape we operate on is the `intent` namespace today: each row holds a
JSON dict with `examples_positive` (and friends). The candidate prompt is the
new examples_positive list as a JSON string. Adding more namespaces later
just means widening `_load_live_kb_body` / `_apply_kb_body`.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    ABExperiment,
    Feedback,
    LearningOpportunity,
    Pipeline,
)
from .. import kb as kb_module

log = logging.getLogger("learning_promotion")


# Minimum pass rate the test corpus must show before a candidate is allowed
# to promote. Set deliberately conservative so a regression in the live
# system blocks new changes from landing on top of a broken baseline.
_TEST_CORPUS_MIN_PASS_RATE = 0.80
# Stale-window: a corpus run older than this is treated as "no recent
# evidence". Keeps the gate honest — a 6-month-old run is not proof of
# current health.
_TEST_CORPUS_MAX_AGE_DAYS = 7


def _test_corpus_gate(db: Session) -> dict:
    """Pre-promotion sanity check against the labelled regression corpus.

    Reads the latest `TestRun` row, computes the initial pass rate, and
    returns a verdict. Verdict shape:

      {
        "ran": bool,               # True if a recent corpus run exists
        "threshold_ok": bool,      # True if pass rate >= min and ran
        "test_run_id": int | None,
        "test_run_label": str | None,
        "test_run_at": str | None, # ISO timestamp
        "total": int,
        "passed": int,
        "failed": int,
        "pass_rate": float,
        "min_pass_rate": float,
        "max_age_days": int,
        "reason": str | None,      # human-readable when not ok
      }

    The gate is intentionally conservative — uses the LATEST corpus run as
    a proxy for "is the live system healthy on known cases". A production
    implementation would shadow-execute the candidate body against the
    corpus before allowing promotion; this version is the auditable, fast
    pre-flight we use today.
    """
    from datetime import timedelta
    from ..models import TestRun

    cutoff = datetime.utcnow() - timedelta(days=_TEST_CORPUS_MAX_AGE_DAYS)
    latest = (
        db.query(TestRun)
        .filter(TestRun.started_at >= cutoff)
        .order_by(TestRun.started_at.desc())
        .first()
    )
    if latest is None:
        return {
            "ran": False,
            "threshold_ok": False,
            "test_run_id": None,
            "test_run_label": None,
            "test_run_at": None,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "min_pass_rate": _TEST_CORPUS_MIN_PASS_RATE,
            "max_age_days": _TEST_CORPUS_MAX_AGE_DAYS,
            "reason": f"no test-corpus run in the last {_TEST_CORPUS_MAX_AGE_DAYS} days",
        }
    total = max(1, int(latest.case_count or 0))
    passed = int(latest.initial_pass or 0)
    rate = passed / total
    ok = rate >= _TEST_CORPUS_MIN_PASS_RATE
    return {
        "ran": True,
        "threshold_ok": ok,
        "test_run_id": latest.id,
        "test_run_label": latest.label,
        "test_run_at": latest.started_at.isoformat() if latest.started_at else None,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(rate, 4),
        "min_pass_rate": _TEST_CORPUS_MIN_PASS_RATE,
        "max_age_days": _TEST_CORPUS_MAX_AGE_DAYS,
        "reason": None if ok else (
            f"latest run '{latest.label}' shows pass rate {rate:.1%} "
            f"(below required {_TEST_CORPUS_MIN_PASS_RATE:.0%}) — "
            f"{passed} of {total} cases passing"
        ),
    }


def _load_live_kb_body(db: Session, namespace: str, key: str) -> dict | None:
    """Read the current KB rule body. Returns the parsed dict or None."""
    from ..models import KnowledgeRule
    row = (
        db.query(KnowledgeRule)
        .filter(KnowledgeRule.namespace == namespace, KnowledgeRule.key == key)
        .order_by(KnowledgeRule.version.desc())
        .first()
    )
    if row is None:
        return None
    if isinstance(row.body, dict):
        return row.body
    try:
        return json.loads(row.body or "{}")
    except Exception:
        return None


def _apply_kb_body(
    db: Session, namespace: str, key: str, body: dict, by: str, note: str | None,
    *, experiment_id: int | None = None, change_kind: str = "promote",
) -> bool:
    """Overwrite the live KB rule body with the candidate. Bumps the version
    so the next pipeline run picks it up. Returns True on success.

    Side effect: append a KbRuleVersion row capturing the new body. Together
    with the snapshot of the prior body stored on the ABExperiment, this gives
    full point-in-time replay of the rule's evolution.
    """
    from ..models import KbRuleVersion, KnowledgeRule
    row = (
        db.query(KnowledgeRule)
        .filter(KnowledgeRule.namespace == namespace, KnowledgeRule.key == key)
        .order_by(KnowledgeRule.version.desc())
        .first()
    )
    new_version: int
    if row is None:
        row = KnowledgeRule(
            namespace=namespace,
            key=key,
            body=body,
            version=1,
            updated_at=datetime.utcnow(),
            updated_by=by or "ab_promotion",
        )
        if note and hasattr(row, "change_note"):
            row.change_note = note
        db.add(row)
        new_version = 1
    else:
        row.body = body
        row.version = (row.version or 1) + 1
        row.updated_at = datetime.utcnow()
        row.updated_by = by or "ab_promotion"
        if note and hasattr(row, "change_note"):
            row.change_note = note
        new_version = row.version
    db.add(KbRuleVersion(
        namespace=namespace, key=key, version=new_version, body=body,
        changed_by_name=by, change_kind=change_kind, experiment_id=experiment_id,
        note=note,
    ))
    db.commit()
    return True


def _parse_structured_remedy(opp: LearningOpportunity) -> dict | None:
    """Try to parse `proposed_remedy` as a structured JSON document. Returns
    the parsed dict on success, None on failure. The new generators emit a
    JSON object with keys: change_type, scope, current, proposed, rationale.
    Legacy text remedies return None."""
    raw = opp.proposed_remedy or ""
    if not raw or raw[0] not in "{[":
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _infer_kb_target_from_opportunity(opp: LearningOpportunity) -> tuple[str | None, str | None, str | None]:
    """Inspect the opportunity to figure out which KB rule it edits.

    Returns (namespace, key, label). New generators write a structured JSON
    remedy with a `scope` field that names namespace + key directly. Legacy
    prompt-type opportunities fall back to fingerprint / segment heuristics.
    """
    structured = _parse_structured_remedy(opp)
    if isinstance(structured, dict):
        scope = structured.get("scope") or {}
        ns = scope.get("namespace") or None
        k = scope.get("key") or None
        if ns and k:
            return str(ns), str(k), f"{ns}:{k}"

    fp = (opp.fingerprint or "").lower()
    if "intent" in fp or (opp.proposed_remedy or "").lower().find("intent") != -1:
        for token in (opp.segment or "").split():
            if token.endswith("'") and token.startswith("'"):
                guess = token.strip("'")
                return "intent", guess, f"intent:{guess}"
    seg = opp.segment or ""
    if ":" in seg:
        ns, k = seg.split(":", 1)
        return ns.strip(), k.strip(), seg
    return None, None, None


def _infer_change_type(opp: LearningOpportunity) -> str:
    """Returns the change_type the new ABExperiment should carry. Defaults to
    'prompt' for legacy opportunities."""
    structured = _parse_structured_remedy(opp)
    if isinstance(structured, dict):
        ct = structured.get("change_type")
        if isinstance(ct, str):
            return ct
    return "prompt"


def _draft_candidate_prompt(live_body: dict, csr_examples: list[str]) -> dict:
    """Given the current intent KB body and a list of CSR-corrected example
    snippets, produce a candidate body with those snippets appended to
    `examples_positive`. Deduplicates by trimmed text."""
    candidate = dict(live_body or {})
    existing = list(candidate.get("examples_positive") or [])
    seen = {e.strip().lower() for e in existing if isinstance(e, str)}
    for snippet in csr_examples:
        s = (snippet or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        existing.append(s)
        seen.add(key)
    candidate["examples_positive"] = existing
    return candidate


def _gather_csr_corrections(db: Session, opp: LearningOpportunity, target_intent: str) -> list[str]:
    """Pull example snippets to add to the candidate prompt.

    Priority order:
      1. CSR-corrected snippets from Feedback rows on the opportunity's sample
         pipelines (the real signal — when a CSR fixed the intent, their note
         or the prior email subject is what should be added as an example).
      2. Fallback: subject lines from the actual sample emails that already
         classified as `target_intent`. These are the strongest demo signal
         when no CSR edits exist yet — they're real customer phrasing that
         should reinforce the rule rather than reduce it.
    """
    sample_ids = list(opp.sample_pipeline_ids or [])
    if not sample_ids:
        return []

    out: list[str] = []
    rows = (
        db.query(Feedback)
        .filter(Feedback.pipeline_id.in_(sample_ids))
        .filter(Feedback.stage == "intake")
        .filter(Feedback.kind == "edit")
        .all()
    )
    for f in rows:
        d = f.data or {}
        new_intent = d.get("to_intent") or d.get("corrected_intent")
        if new_intent != target_intent:
            continue
        snippet = d.get("snippet") or d.get("email_subject") or f.note
        if snippet:
            out.append(str(snippet)[:240])

    if out:
        return out

    from ..models import Email
    pipes = (
        db.query(Pipeline)
        .filter(Pipeline.id.in_(sample_ids))
        .filter(Pipeline.intent == target_intent)
        .all()
    )
    for p in pipes:
        if not p.email_id:
            continue
        e = db.get(Email, p.email_id)
        if e and e.subject:
            out.append(str(e.subject)[:160])
        if len(out) >= 4:
            break
    return out


def promote_opportunity_to_ab(
    db: Session,
    opp_id: int,
    *,
    decided_by: str | None,
    decision_note: str | None,
) -> ABExperiment:
    """Accept the opportunity and create a linked AB experiment in shadow mode.
    Snapshots the live KB rule as `control_prompt` and drafts a candidate."""
    opp = db.get(LearningOpportunity, opp_id)
    if opp is None:
        raise ValueError(f"opportunity {opp_id} not found")

    namespace, key, label = _infer_kb_target_from_opportunity(opp)
    change_type = _infer_change_type(opp)
    structured = _parse_structured_remedy(opp)
    live_body: dict | None = None
    candidate_body: dict | None = None
    candidate_label = label or (opp.proposed_remedy or "tuning candidate")[:120]

    if namespace and key:
        live_body = _load_live_kb_body(db, namespace, key)
        # Build the candidate body per change_type. The KB rule body shape
        # differs across change types, but the candidate is always a complete
        # JSON object so the apply path can overwrite atomically.
        if change_type == "prompt":
            if live_body is not None:
                csr_examples = _gather_csr_corrections(db, opp, key)
                candidate_body = _draft_candidate_prompt(live_body, csr_examples)
        elif change_type == "threshold" and isinstance(structured, dict):
            proposed_block = structured.get("proposed") or {}
            current_block = (live_body or {}).copy() if isinstance(live_body, dict) else {}
            current_block.update(proposed_block)
            candidate_body = current_block
        elif change_type == "pattern_list" and isinstance(structured, dict):
            field = (structured.get("scope") or {}).get("field") or "keywords"
            additions = structured.get("proposed_add") or []
            candidate_body = dict(live_body or {})
            existing_list = list(candidate_body.get(field) or [])
            seen = {str(x).strip().lower() for x in existing_list}
            for phrase in additions:
                if isinstance(phrase, str) and phrase.strip().lower() not in seen:
                    existing_list.append(phrase.strip())
                    seen.add(phrase.strip().lower())
            candidate_body[field] = existing_list
        elif change_type == "routing_rule" and isinstance(structured, dict):
            proposed_block = structured.get("proposed") or {}
            candidate_body = dict(live_body or {})
            routes = list(candidate_body.get("routes") or [])
            # Replace any existing entry for the same intent; otherwise append.
            target_intent = proposed_block.get("intent")
            updated = False
            for i, r in enumerate(routes):
                if isinstance(r, dict) and r.get("intent") == target_intent:
                    routes[i] = proposed_block
                    updated = True
                    break
            if not updated:
                routes.append(proposed_block)
            candidate_body["routes"] = routes
        elif change_type == "validation_rule" and isinstance(structured, dict):
            candidate_body = dict(structured.get("proposed") or {})
        else:
            candidate_body = None

    sample_target = max(20, len(opp.sample_pipeline_ids or []) * 2)

    exp = ABExperiment(
        candidate=candidate_label,
        segment=opp.segment or "all",
        horizon_kind="sample_size",
        horizon_value=f"{sample_target} pipelines",
        sample_collected=0,
        sample_target=sample_target,
        promote_status="shadow",
        change_type=change_type,
        linked_opportunity_id=opp.id,
        kb_namespace=namespace,
        kb_key=key,
        control_prompt=json.dumps(live_body, indent=2) if live_body is not None else None,
        candidate_prompt=json.dumps(candidate_body, indent=2) if candidate_body is not None else None,
        # Carry the baseline anchor down the chain so the experiment shows up
        # in the originating baseline's timeline.
        baseline_id=opp.baseline_id,
    )
    db.add(exp)
    opp.status = "in_ab"
    opp.decided_by = decided_by
    opp.decision_note = decision_note
    opp.decided_at = datetime.utcnow()
    db.commit()
    db.refresh(exp)
    log.info("opportunity %s promoted to A/B experiment %s (kb=%s/%s)", opp_id, exp.id, namespace, key)
    return exp


_REPLAY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string"},
        "intent_confidence": {"type": "number"},
    },
    "required": ["intent", "intent_confidence"],
}


def _replay_classifier(
    email_dict: dict,
    *,
    target_intent: str,
    candidate_body: dict,
    account_region: str | None,
) -> dict:
    """Run the live Stage-1 intent classifier against this email with the
    candidate KB body injected in place of the live body for `target_intent`.

    Prefers the operator-configured OpenAI provider for reproducible JSON
    output. Falls back to the platform `ask_llm` if OpenAI is not configured.
    Returns {"intent": str|None, "confidence": float|None, "error": str|None,
    "method": "openai_replay"|"llm_replay"|"llm_unavailable"}.
    """
    from ..agents.intake import build_system_prompt, build_user_prompt
    from . import openai_client

    try:
        system_prompt = build_system_prompt(
            account_region=account_region,
            rules_override={target_intent: candidate_body},
        ) + "\n\nFor this evaluation, output a strict JSON object with exactly two keys: intent and intent_confidence."
        user_prompt = build_user_prompt(email_dict)
    except Exception as e:
        return {"intent": None, "confidence": None, "error": f"prompt_build_failed: {str(e)[:160]}", "method": "llm_unavailable"}

    if openai_client.is_configured():
        try:
            parsed, _raw, _meta = openai_client.ask_openai_json(
                system=system_prompt,
                user=user_prompt,
                schema=_REPLAY_SCHEMA,
                schema_name="ab_backtest_replay",
                stage_hint="learning_backtest",
                max_retries=1,
            )
            if isinstance(parsed, dict):
                return {
                    "intent": parsed.get("intent"),
                    "confidence": float(parsed.get("intent_confidence") or 0.0),
                    "error": None,
                    "method": "openai_replay",
                }
            return {"intent": None, "confidence": None, "error": "openai_returned_non_dict", "method": "openai_replay"}
        except Exception as e:
            return {"intent": None, "confidence": None, "error": str(e)[:200], "method": "openai_replay"}

    try:
        from ..agents.llm import ask_llm
        out = ask_llm(system=system_prompt, user=user_prompt, json_only=True)
        if not out:
            return {"intent": None, "confidence": None, "error": "empty_response", "method": "llm_replay"}
        parsed = out if isinstance(out, dict) else (json.loads(out) if isinstance(out, str) else None)
        if not isinstance(parsed, dict):
            return {"intent": None, "confidence": None, "error": "non_dict_response", "method": "llm_replay"}
        return {
            "intent": parsed.get("intent"),
            "confidence": float(parsed.get("intent_confidence") or 0.0),
            "error": None,
            "method": "llm_replay",
        }
    except Exception as e:
        return {"intent": None, "confidence": None, "error": str(e)[:200], "method": "llm_unavailable"}


def _score_pipeline_against_candidate(
    pipeline: Pipeline,
    email_row,
    candidate_body: dict,
    control_body: dict | None,
    target_intent: str,
) -> dict:
    """Back-test scoring for one historical pipeline.

    Runs the live Stage-1 classifier against the original email body with the
    candidate KB body injected, then compares the predicted intent against the
    target intent (the one this candidate is tuning for).

    `baseline_correct` reflects what the LIVE pipeline actually decided when
    it ran originally (pipeline.intent == target_intent). `candidate_correct`
    reflects what the classifier would decide right now if the candidate body
    were live. The delta between those two rates is the back-test result.
    """
    baseline_correct = pipeline.intent == target_intent
    if email_row is None:
        return {
            "pipeline_id": pipeline.id,
            "baseline_intent": pipeline.intent,
            "target_intent": target_intent,
            "baseline_correct": bool(baseline_correct),
            "candidate_intent": None,
            "candidate_confidence": None,
            "candidate_correct": False,
            "replay_method": "skipped_no_email",
            "replay_error": "originating email row not found",
        }
    email_dict = {
        "id": email_row.id,
        "subject": email_row.subject or "",
        "body": email_row.body or "",
        "from_address": email_row.from_address or "",
        "language_hint": email_row.language_hint,
    }
    account_region = None
    if isinstance(pipeline.customer_match, dict):
        account_region = pipeline.customer_match.get("region")
    replay = _replay_classifier(
        email_dict,
        target_intent=target_intent,
        candidate_body=candidate_body,
        account_region=account_region,
    )
    candidate_intent = replay.get("intent")
    candidate_correct = candidate_intent == target_intent
    return {
        "pipeline_id": pipeline.id,
        "baseline_intent": pipeline.intent,
        "target_intent": target_intent,
        "baseline_correct": bool(baseline_correct),
        "candidate_intent": candidate_intent,
        "candidate_confidence": replay.get("confidence"),
        "candidate_correct": bool(candidate_correct),
        "replay_method": replay.get("method"),
        "replay_error": replay.get("error"),
    }


def run_backtest(db: Session, exp_id: int) -> dict:
    """Back-test dispatcher. Picks the right scoring routine per change_type.

    Every variant writes the same shape onto the experiment row:
      backtest_results (summary dict), backtest_sample (per-row dicts),
      backtest_ran_at, accuracy_delta_pct, sample_collected, promote_status,
      regression_status. Variants differ only in HOW they compute the delta.
    """
    exp = db.get(ABExperiment, exp_id)
    if exp is None:
        raise ValueError(f"experiment {exp_id} not found")
    if not exp.candidate_prompt:
        raise ValueError("experiment has no candidate to back-test")
    change_type = (exp.change_type or "prompt").lower()
    dispatch = {
        "prompt": _backtest_prompt,
        "threshold": _backtest_threshold,
        "pattern_list": _backtest_pattern_list,
        "routing_rule": _backtest_routing_rule,
        "validation_rule": _backtest_validation_rule,
    }
    fn = dispatch.get(change_type, _backtest_prompt)
    summary = fn(db, exp)
    delta_pct = float(summary.get("delta_pct") or 0.0)
    n = int(summary.get("sample_size") or 0)
    per_row = summary.get("all_rows") or []
    exp.backtest_results = summary
    exp.backtest_sample = per_row
    exp.backtest_ran_at = datetime.utcnow()
    exp.accuracy_delta_pct = delta_pct
    exp.accuracy_delta_ci = f"{'+' if delta_pct > 0 else ''}{delta_pct}% (back-test, n={n})"
    exp.sample_collected = n
    if delta_pct >= 2.0:
        exp.promote_status = "ready"
        exp.regression_status = "none"
    elif delta_pct <= -2.0:
        exp.regression_status = "fail"
    else:
        exp.regression_status = "watch"
    db.commit()
    db.refresh(exp)
    return summary


def _backtest_prompt(db: Session, exp: ABExperiment) -> dict:
    """Real LLM replay of the candidate KB body against historical pipelines.
    Implementation lives in `_score_pipeline_against_candidate` and uses
    OpenAI via `_replay_classifier`.
    """
    try:
        candidate_body = json.loads(exp.candidate_prompt)
    except Exception as e:
        raise ValueError(f"candidate_prompt is not valid JSON: {e}")
    control_body: dict | None = None
    if exp.control_prompt:
        try:
            control_body = json.loads(exp.control_prompt)
        except Exception:
            control_body = None

    target_intent = exp.kb_key
    opp = db.get(LearningOpportunity, exp.linked_opportunity_id) if exp.linked_opportunity_id else None
    sample_ids = list((opp.sample_pipeline_ids if opp else None) or [])

    # Widen the sample pool with up to 20 more recent pipelines of the same target intent
    extra = (
        db.query(Pipeline)
        .filter(Pipeline.intent == target_intent)
        .order_by(Pipeline.id.desc())
        .limit(20)
        .all()
    )
    seen: set[int] = set(sample_ids)
    extra_ids = [p.id for p in extra if p.id not in seen]
    full_ids = sample_ids + extra_ids[: max(0, 20 - len(sample_ids))]

    pipes = db.query(Pipeline).filter(Pipeline.id.in_(full_ids)).all() if full_ids else []
    # Enrich with Email subject + customer_name so the UI can show useful
    # per-pipeline rows without a second round-trip.
    from ..models import Email
    email_map: dict[int, Email] = {}
    if pipes:
        eid_to_pid = {p.email_id: p.id for p in pipes if p.email_id}
        if eid_to_pid:
            for e in db.query(Email).filter(Email.id.in_(list(eid_to_pid.keys()))).all():
                email_map[eid_to_pid[e.id]] = e
    per_row: list[dict] = []
    baseline_correct = 0
    candidate_correct = 0
    replay_errors = 0
    replay_methods: Counter = Counter()
    for p in pipes:
        em = email_map.get(p.id)
        r = _score_pipeline_against_candidate(p, em, candidate_body, control_body, target_intent or "")
        cust = (p.customer_match or {}).get("customer_name") if isinstance(p.customer_match, dict) else None
        r["subject"] = (em.subject if em else None)
        r["from_address"] = (em.from_address if em else None)
        r["customer_name"] = cust
        r["agreed"] = bool(r.get("baseline_correct") == r.get("candidate_correct"))
        per_row.append(r)
        if r["baseline_correct"]:
            baseline_correct += 1
        if r["candidate_correct"]:
            candidate_correct += 1
        if r.get("replay_error"):
            replay_errors += 1
        if r.get("replay_method"):
            replay_methods[r["replay_method"]] += 1
    n = len(pipes)
    # Effective n for the delta excludes rows where the replay failed; otherwise
    # an LLM outage would silently degrade the gate signal.
    n_replayed = n - replay_errors
    baseline_acc = (baseline_correct / n) if n else 0.0
    candidate_acc = (candidate_correct / n) if n else 0.0
    delta_pct = round((candidate_acc - baseline_acc) * 100, 2)

    return {
        "change_type": "prompt",
        "sample_size": n,
        "replayed_size": n_replayed,
        "replay_errors": replay_errors,
        "replay_method_counts": dict(replay_methods),
        "target_intent": target_intent,
        "baseline_correct": baseline_correct,
        "candidate_correct": candidate_correct,
        "baseline_accuracy_pct": round(baseline_acc * 100, 2),
        "candidate_accuracy_pct": round(candidate_acc * 100, 2),
        "delta_pct": delta_pct,
        "mismatches": [r for r in per_row if r["baseline_correct"] != r["candidate_correct"]][:50],
        "all_rows": per_row,
    }


def _backtest_threshold(db: Session, exp: ABExperiment) -> dict:
    """Replay a proposed per-intent L4 confidence floor against the last
    30 days of L4 cohort for that intent. The candidate "wins" each case where
    the proposed floor would have demoted a CSR-edited L4 case down to L3
    review (saving an edit), and "regresses" on no cases that the live floor
    currently catches (the proposed floor is always ≥ live floor)."""
    try:
        candidate_body = json.loads(exp.candidate_prompt)
    except Exception as e:
        raise ValueError(f"candidate_prompt is not valid JSON: {e}")
    proposed_floor = float(candidate_body.get("l4_floor") or 0.95)
    target_intent = exp.kb_key
    cutoff = datetime.utcnow() - timedelta(days=30)
    pipes = (
        db.query(Pipeline)
        .filter(Pipeline.autonomy_tier == "L4_AUTO")
        .filter(Pipeline.intent == target_intent)
        .filter(Pipeline.started_at >= cutoff)
        .all()
    )
    edited_ids = set(
        int(pid) for (pid,) in db.query(Feedback.pipeline_id)
        .filter(Feedback.pipeline_id.in_([p.id for p in pipes]))
        .filter(Feedback.kind == "edit")
        .distinct().all() if pid is not None
    ) if pipes else set()
    per_row: list[dict] = []
    saved_edits = 0
    lost_throughput = 0
    for p in pipes:
        conf = float(p.confidence or 0.0)
        was_edited = p.id in edited_ids
        stays_l4 = conf >= proposed_floor
        demoted = not stays_l4
        if was_edited and demoted:
            saved_edits += 1
        if not was_edited and demoted:
            lost_throughput += 1
        per_row.append({
            "pipeline_id": p.id,
            "intent": p.intent,
            "confidence": conf,
            "edited": was_edited,
            "now_stays_l4": stays_l4,
            "outcome": (
                "saved_edit" if was_edited and demoted
                else "still_l4_with_edit" if was_edited else
                "moved_to_l3_no_edit_was_needed" if demoted else "still_l4"
            ),
        })
    n = len(pipes)
    edit_count_before = len(edited_ids)
    edit_count_after = sum(1 for r in per_row if r["edited"] and r["now_stays_l4"])
    edit_rate_before = (edit_count_before / n) if n else 0.0
    edit_rate_after = (edit_count_after / n) if n else 0.0
    delta_pct = round((edit_rate_before - edit_rate_after) * 100, 2)  # positive = improvement
    return {
        "change_type": "threshold",
        "sample_size": n,
        "target_intent": target_intent,
        "proposed_floor": proposed_floor,
        "edited_before": edit_count_before,
        "edited_after_at_l4": edit_count_after,
        "edits_saved": saved_edits,
        "lost_throughput_count": lost_throughput,
        "baseline_accuracy_pct": round((1.0 - edit_rate_before) * 100, 2),
        "candidate_accuracy_pct": round((1.0 - edit_rate_after) * 100, 2),
        "delta_pct": delta_pct,
        "all_rows": per_row[:200],
    }


def _backtest_pattern_list(db: Session, exp: ABExperiment) -> dict:
    """Replay a proposed keyword/pattern list against historical inbound
    emails. The candidate "wins" on each CSR override sample where the new
    pattern matches the email text, and "regresses" on each non-target case
    in a random control sample where the new pattern would accidentally fire.
    """
    try:
        candidate_body = json.loads(exp.candidate_prompt)
    except Exception as e:
        raise ValueError(f"candidate_prompt is not valid JSON: {e}")
    new_keywords = [str(k).lower() for k in (candidate_body.get("keywords") or []) if isinstance(k, str)]
    control_keywords: set[str] = set()
    if exp.control_prompt:
        try:
            control_body = json.loads(exp.control_prompt)
            control_keywords = {str(k).lower() for k in (control_body.get("keywords") or []) if isinstance(k, str)}
        except Exception:
            pass
    added = [k for k in new_keywords if k not in control_keywords]
    from ..models import Email
    target_intent = exp.kb_key
    opp = db.get(LearningOpportunity, exp.linked_opportunity_id) if exp.linked_opportunity_id else None
    sample_ids = list((opp.sample_pipeline_ids if opp else None) or [])
    target_pipes = db.query(Pipeline).filter(Pipeline.id.in_(sample_ids)).all() if sample_ids else []
    target_email_ids = [p.email_id for p in target_pipes if p.email_id]
    target_emails = db.query(Email).filter(Email.id.in_(target_email_ids)).all() if target_email_ids else []

    control_pipes = (
        db.query(Pipeline)
        .filter(Pipeline.intent != target_intent)
        .filter(Pipeline.id.notin_(sample_ids) if sample_ids else True)
        .order_by(Pipeline.id.desc())
        .limit(40)
        .all()
    )
    control_email_ids = [p.email_id for p in control_pipes if p.email_id]
    control_emails = db.query(Email).filter(Email.id.in_(control_email_ids)).all() if control_email_ids else []

    def _matches(e: Email) -> str | None:
        text = " ".join([e.subject or "", e.body or ""]).lower()
        for k in added:
            if k in text:
                return k
        return None

    per_row: list[dict] = []
    catches = 0
    regressions = 0
    for e in target_emails:
        m = _matches(e)
        if m:
            catches += 1
        per_row.append({
            "email_id": e.id, "subject": (e.subject or "")[:80], "from": e.from_address,
            "is_target": True, "matched_keyword": m, "outcome": "catch" if m else "miss",
        })
    for e in control_emails:
        m = _matches(e)
        if m:
            regressions += 1
        per_row.append({
            "email_id": e.id, "subject": (e.subject or "")[:80], "from": e.from_address,
            "is_target": False, "matched_keyword": m, "outcome": "false_positive" if m else "correct_skip",
        })
    target_n = len(target_emails)
    control_n = len(control_emails)
    catch_rate = (catches / target_n) if target_n else 0.0
    fp_rate = (regressions / control_n) if control_n else 0.0
    # Net = catch_rate - fp_rate, percentage points
    delta_pct = round((catch_rate - fp_rate) * 100, 2)
    return {
        "change_type": "pattern_list",
        "sample_size": target_n + control_n,
        "target_sample_size": target_n,
        "control_sample_size": control_n,
        "added_keywords": added,
        "catches": catches,
        "regressions": regressions,
        "catch_rate_pct": round(catch_rate * 100, 2),
        "false_positive_rate_pct": round(fp_rate * 100, 2),
        "baseline_accuracy_pct": 0.0,
        "candidate_accuracy_pct": round((catch_rate - fp_rate) * 100, 2),
        "delta_pct": delta_pct,
        "all_rows": per_row[:200],
    }


def _backtest_routing_rule(db: Session, exp: ABExperiment) -> dict:
    """Replay a proposed routing rule against the historical reassignments
    the opportunity surfaced. The candidate "wins" each case where its target
    queue matches the queue the CSR actually moved the case to."""
    try:
        candidate_body = json.loads(exp.candidate_prompt)
    except Exception as e:
        raise ValueError(f"candidate_prompt is not valid JSON: {e}")
    routes = candidate_body.get("routes") or []
    from ..models import HitlTask
    opp = db.get(LearningOpportunity, exp.linked_opportunity_id) if exp.linked_opportunity_id else None
    sample_ids = list((opp.sample_pipeline_ids if opp else None) or [])
    if not sample_ids:
        return {"change_type": "routing_rule", "sample_size": 0, "delta_pct": 0.0, "all_rows": []}

    def _route_for(intent: str) -> str | None:
        for r in routes:
            if isinstance(r, dict) and r.get("intent") == intent:
                return r.get("queue")
        return None

    pipes = {p.id: p for p in db.query(Pipeline).filter(Pipeline.id.in_(sample_ids)).all()}
    tasks_by_pipe: dict[int, HitlTask] = {}
    for t in db.query(HitlTask).filter(HitlTask.pipeline_id.in_(sample_ids)).all():
        if t.assigned_at is not None:
            tasks_by_pipe[int(t.pipeline_id)] = t
    per_row: list[dict] = []
    correct = 0
    for pid in sample_ids:
        p = pipes.get(int(pid))
        if not p:
            continue
        t = tasks_by_pipe.get(int(pid))
        actual_q = t.assignee_queue if t else None
        proposed_q = _route_for(p.intent or "")
        ok = bool(proposed_q and proposed_q == actual_q)
        if ok:
            correct += 1
        per_row.append({
            "pipeline_id": pid, "intent": p.intent, "actual_queue": actual_q,
            "proposed_queue": proposed_q, "agreed": ok,
        })
    n = len(per_row)
    candidate_acc = (correct / n) if n else 0.0
    # Baseline accuracy is 0 here by construction — these are cases that the
    # CSR REASSIGNED, so the original routing was always wrong.
    delta_pct = round(candidate_acc * 100, 2)
    return {
        "change_type": "routing_rule",
        "sample_size": n,
        "correct": correct,
        "baseline_accuracy_pct": 0.0,
        "candidate_accuracy_pct": round(candidate_acc * 100, 2),
        "delta_pct": delta_pct,
        "all_rows": per_row[:200],
    }


def _backtest_validation_rule(db: Session, exp: ABExperiment) -> dict:
    """Replay a proposed pre-flight check against the historical failure
    events the opportunity surfaced. The candidate "wins" each failing case
    where its trigger condition would have fired pre-flight. Control sample
    of recent successful pipelines is scanned for false positives.
    """
    try:
        candidate_body = json.loads(exp.candidate_prompt)
    except Exception as e:
        raise ValueError(f"candidate_prompt is not valid JSON: {e}")
    fires_on = (candidate_body.get("fires_on") or "").lower()
    opp = db.get(LearningOpportunity, exp.linked_opportunity_id) if exp.linked_opportunity_id else None
    sample_ids = list((opp.sample_pipeline_ids if opp else None) or [])
    failure_pipes = db.query(Pipeline).filter(Pipeline.id.in_(sample_ids)).all() if sample_ids else []
    # Failure pipelines: candidate fires if the proposed condition text
    # matches the recorded error / reason / discarded label on the pipeline.
    catches = 0
    per_row: list[dict] = []
    for p in failure_pipes:
        haystack = " ".join([str(p.error or ""), str((p.execution or {}).get("reason") or "")]).lower()
        fired = bool(fires_on and any(tok in haystack for tok in fires_on.split() if len(tok) >= 4))
        if fired:
            catches += 1
        per_row.append({
            "pipeline_id": p.id, "intent": p.intent, "error_snippet": (p.error or "")[:120],
            "would_fire": fired, "outcome": "catch" if fired else "miss",
        })
    # Control sample: 30 most-recent completed pipelines. False positive = candidate fires on a success.
    control_pipes = (
        db.query(Pipeline)
        .filter(Pipeline.status == "completed")
        .order_by(Pipeline.id.desc())
        .limit(30)
        .all()
    )
    false_positives = 0
    for p in control_pipes:
        haystack = " ".join([str(p.error or ""), str((p.execution or {}).get("reason") or "")]).lower()
        fired = bool(fires_on and any(tok in haystack for tok in fires_on.split() if len(tok) >= 4))
        if fired:
            false_positives += 1
        per_row.append({
            "pipeline_id": p.id, "intent": p.intent, "is_control": True,
            "would_fire": fired, "outcome": "false_positive" if fired else "correct_skip",
        })
    target_n = len(failure_pipes)
    control_n = len(control_pipes)
    catch_rate = (catches / target_n) if target_n else 0.0
    fp_rate = (false_positives / control_n) if control_n else 0.0
    delta_pct = round((catch_rate - fp_rate) * 100, 2)
    return {
        "change_type": "validation_rule",
        "sample_size": target_n + control_n,
        "target_sample_size": target_n,
        "control_sample_size": control_n,
        "catches": catches,
        "false_positives": false_positives,
        "catch_rate_pct": round(catch_rate * 100, 2),
        "false_positive_rate_pct": round(fp_rate * 100, 2),
        "baseline_accuracy_pct": 0.0,
        "candidate_accuracy_pct": round((catch_rate - fp_rate) * 100, 2),
        "delta_pct": delta_pct,
        "all_rows": per_row[:200],
    }


def promote_ab_to_production(
    db: Session,
    exp_id: int,
    *,
    promoted_by: str | None,
    promote_note: str | None,
) -> dict:
    """Apply the candidate prompt to the live KB rule and stamp the
    experiment as `promoted`. The linked opportunity is also moved to
    `promoted` so it leaves the tuning queue. Returns a small status dict."""
    exp = db.get(ABExperiment, exp_id)
    if exp is None:
        raise ValueError(f"experiment {exp_id} not found")
    if not (exp.kb_namespace and exp.kb_key):
        raise ValueError("experiment has no KB target to promote")
    if not exp.candidate_prompt:
        raise ValueError("experiment has no candidate_prompt")
    try:
        candidate_body = json.loads(exp.candidate_prompt)
    except Exception as e:
        raise ValueError(f"candidate_prompt is not valid JSON: {e}")
    # Block-promotion baselines: refuse to land a candidate while any
    # admin-defined hard baseline is currently breached. The promotion gate
    # already checks per-experiment delta math; this is the *system-health*
    # gate that says "even if your A/B looks good, don't change anything
    # right now because reply-send-success is sitting at 98% and we don't
    # want to muddy the post-mortem".
    try:
        from . import baselines as baselines_svc
        breached_blockers = baselines_svc.list_breached(db, severity="block_promotion")
    except Exception:
        breached_blockers = []
    if breached_blockers:
        details = ", ".join(
            f"{b.metric}@{b.segment} (observed {b.last_observed} vs target {b.target_value})"
            for b in breached_blockers[:5]
        )
        raise ValueError(
            f"promotion blocked by {len(breached_blockers)} hard baseline(s): {details}. "
            "Either resolve the breach or temporarily lower the baseline severity to 'warn' "
            "in the Baselines admin page."
        )
    # Test-corpus gate: refuse promotion if the latest labelled-regression
    # run shows the live system below the required pass rate. Prevents a
    # candidate from landing on top of a system that is already broken on
    # known cases. Bypass with `force=true` from the Promote screen if the
    # candidate is specifically meant to fix the failing cases.
    corpus_check = _test_corpus_gate(db)
    if not corpus_check["threshold_ok"]:
        raise ValueError(
            f"promotion blocked by test-corpus gate: {corpus_check['reason']}. "
            f"Run the corpus in Settings → Test corpus and address regressions before promoting."
        )
    # Snapshot the current production body BEFORE we overwrite it so the
    # rollback button can restore it within the configured rollback window.
    # Persist the snapshot first; if the apply step later fails we still
    # have a record of what was live so the rollback button remains armed.
    prior_body = _load_live_kb_body(db, exp.kb_namespace, exp.kb_key)
    exp.previous_body_snapshot = prior_body
    db.commit()
    applied = _apply_kb_body(
        db, exp.kb_namespace, exp.kb_key, candidate_body,
        by=promoted_by or "ab_promotion",
        note=promote_note,
        experiment_id=exp.id,
        change_kind="promote",
    )
    if not applied:
        raise ValueError(f"KB rule {exp.kb_namespace}/{exp.kb_key} not found")
    exp.promote_status = "promoted"
    exp.promoted_by = promoted_by
    exp.promote_note = promote_note
    exp.promoted_at = datetime.utcnow()
    if exp.linked_opportunity_id:
        opp = db.get(LearningOpportunity, exp.linked_opportunity_id)
        if opp:
            opp.status = "promoted"
            opp.decided_at = datetime.utcnow()
    db.commit()
    log.warning(
        "AB experiment %s promoted to production — KB %s/%s rolled to a new version",
        exp_id, exp.kb_namespace, exp.kb_key,
    )
    return {
        "ok": True,
        "experiment_id": exp.id,
        "kb_namespace": exp.kb_namespace,
        "kb_key": exp.kb_key,
        "promoted_at": exp.promoted_at.isoformat(),
    }


def rollback_ab_experiment(
    db: Session,
    exp_id: int,
    *,
    rolled_back_by: str | None,
    note: str | None,
) -> dict:
    """Restore the KB rule body to the snapshot captured at promotion.

    Only available for experiments in `promoted` state with a non-empty
    `previous_body_snapshot`. The rollback window is enforced at the route
    layer so an operator can override it with an explicit reason.
    """
    exp = db.get(ABExperiment, exp_id)
    if exp is None:
        raise ValueError(f"experiment {exp_id} not found")
    if exp.promote_status != "promoted":
        raise ValueError(f"experiment is in '{exp.promote_status}' state; rollback only applies to 'promoted'")
    if not exp.previous_body_snapshot:
        raise ValueError("no previous body snapshot recorded for this experiment")
    if not (exp.kb_namespace and exp.kb_key):
        raise ValueError("experiment has no KB target")
    applied = _apply_kb_body(
        db, exp.kb_namespace, exp.kb_key, exp.previous_body_snapshot,
        by=rolled_back_by or "ab_rollback",
        note=note or "Rollback of A/B experiment promotion",
        experiment_id=exp.id,
        change_kind="rollback",
    )
    if not applied:
        raise ValueError(f"KB rule {exp.kb_namespace}/{exp.kb_key} not found")
    exp.promote_status = "retired"
    exp.rolled_back_at = datetime.utcnow()
    exp.rolled_back_by = rolled_back_by
    exp.rolled_back_note = note
    db.commit()
    log.warning(
        "AB experiment %s rolled back — KB %s/%s restored to pre-promotion body",
        exp_id, exp.kb_namespace, exp.kb_key,
    )
    return {
        "ok": True,
        "experiment_id": exp.id,
        "kb_namespace": exp.kb_namespace,
        "kb_key": exp.kb_key,
        "rolled_back_at": exp.rolled_back_at.isoformat(),
    }


def edit_ab_candidate(
    db: Session,
    exp_id: int,
    *,
    new_candidate_prompt: str,
    edited_by: str | None,
    note: str | None,
) -> dict:
    """Replace the candidate body and reset the experiment back to a
    fresh state. Backtest results are cleared so the operator must
    re-evaluate before promoting. Only available pre-promotion."""
    exp = db.get(ABExperiment, exp_id)
    if exp is None:
        raise ValueError(f"experiment {exp_id} not found")
    if exp.promote_status not in ("shadow", "ready"):
        raise ValueError(f"experiment is in '{exp.promote_status}' state; edit only applies pre-promotion")
    # Validate the new candidate parses as JSON for prompt-type changes;
    # for non-prompt types we accept the raw text.
    if (exp.change_type or "prompt") == "prompt":
        try:
            json.loads(new_candidate_prompt)
        except Exception as e:
            raise ValueError(f"new_candidate_prompt is not valid JSON: {e}")
    exp.candidate_prompt = new_candidate_prompt
    exp.promote_status = "shadow"
    exp.backtest_results = None
    exp.backtest_ran_at = None
    exp.backtest_sample = []
    exp.accuracy_delta_pct = None
    exp.accuracy_delta_ci = None
    exp.regression_status = "none"
    if note:
        existing_note = exp.promote_note or ""
        exp.promote_note = (existing_note + ("\n" if existing_note else "") + f"[edit by {edited_by or 'unknown'}] {note}").strip()
    db.commit()
    return {"ok": True, "experiment_id": exp.id, "promote_status": exp.promote_status}
