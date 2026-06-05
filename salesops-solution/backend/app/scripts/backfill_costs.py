"""Backfill cost_events from historical trace data.

The Cost dashboard requires 100% pipeline coverage before it renders any dollar
figures. New cost-recording paths (Azure Document Intelligence inline via
record_ocr_cost; older LLM round-trips that ran before record_llm_cost was
wired) leave gaps for pipelines that ran before those code paths existed.

This script walks every trace event and synthesizes missing cost events:

  - Every `tool_end` event where the tool name matches an LLM call (
    classify_intent, detect_language, llm_spam_check, extract_schema,
    reconcile_summary, summary_for_csr, etc.) that has no matching CostEvent
    against the same (pipeline_id, stage, tool) gets backfilled.
  - Every `tool_end` event for `azure_doc_intelligence` with no matching
    CostEvent gets a per-page row at the Layout rate.

Token counts for LLM events are estimated from the trace event's `data`
payload (input_chars, output_chars, prompt_tokens, completion_tokens when
present) or chars/4 fallback. Page counts for OCR come from the trace
event's `data.pages` field, or from text size (~3000 chars per page) when
absent.

Idempotent: re-running the script does not duplicate rows. Each
backfilled row is tagged with `unit_kind` ending in `_backfilled` so an
operator can audit and re-derive at any time.

Run:
    python -m app.scripts.backfill_costs
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import Session

from app.analytics.cost import _unit_cost
from app.db import SessionLocal
from app.models import CostEvent, TraceEvent

log = logging.getLogger("backfill_costs")


# Tools that round-trip an LLM. Mapped to a default model used by that tool
# in the current build. The cost rate book in analytics/cost.py knows these
# model keys.
LLM_TOOLS_TO_MODEL: dict[str, str] = {
    "classify_intent": "gpt-5.2",
    "detect_language": "gpt-5.2",
    "llm_spam_check": "gpt-5.2",
    "extract_schema": "gpt-5.2",
    "reconcile_summary": "gpt-5.2",
    "summary_for_csr": "gpt-5.2",
    "translate_text": "gpt-5.2",
    "draft_customer_reply": "gpt-5.2",
    "rephrase_for_csr": "gpt-5.2",
    "structured_extract": "gpt-5.2",
    "intent_shadow_check": "gpt-5.2",
    "verifier_review": "gpt-5.2",
}

DOCINTEL_TOOL = "azure_doc_intelligence"


def _estimate_tokens_from_event(ev: TraceEvent, side: str) -> int:
    """Estimate token count for the input ('llm_input') or output ('llm_output')
    side of an LLM round-trip from whatever the trace event happened to
    capture. Prefers explicit token counts, falls back to char/4."""
    data = ev.data or {}
    if side == "llm_input":
        for k in ("prompt_tokens", "input_tokens", "tokens_in"):
            v = data.get(k)
            if isinstance(v, int) and v > 0:
                return v
        for k in ("input_chars", "prompt_chars", "system_chars"):
            v = data.get(k)
            if isinstance(v, int) and v > 0:
                return max(1, v // 4)
        # Fallback: rough size from the message text plus a default 200-token
        # system prompt.
        return 200 + max(1, len(ev.message or "") // 4)
    else:
        for k in ("completion_tokens", "output_tokens", "tokens_out"):
            v = data.get(k)
            if isinstance(v, int) and v > 0:
                return v
        for k in ("output_chars", "response_chars"):
            v = data.get(k)
            if isinstance(v, int) and v > 0:
                return max(1, v // 4)
        # Fallback: small default since most LLM responses in this build are
        # short structured JSON.
        return 120


def _estimate_pages_from_event(ev: TraceEvent) -> int:
    data = ev.data or {}
    for k in ("pages", "page_count", "max_pages_requested"):
        v = data.get(k)
        if isinstance(v, int) and v > 0:
            return v
    # Fallback: estimate from char_count of extracted text (~3000 chars/page).
    char_count = data.get("char_count") or data.get("chars")
    if isinstance(char_count, int) and char_count > 0:
        return max(1, char_count // 3000)
    return 1


def _existing_keys(db: Session) -> set[tuple[int | None, str, str, str]]:
    """Set of (pipeline_id, stage, tool, component) that already have a
    cost row, so we don't double-count on re-runs."""
    out: set[tuple[int | None, str, str, str]] = set()
    rows = db.query(
        CostEvent.pipeline_id, CostEvent.stage, CostEvent.tool, CostEvent.component,
    ).all()
    for r in rows:
        out.add((r[0], r[1], r[2], r[3]))
    return out


def backfill(db: Session) -> dict:
    counts = {"llm_pairs_added": 0, "ocr_rows_added": 0, "skipped_existing": 0, "trace_rows_seen": 0}
    existing = _existing_keys(db)

    q = (
        db.query(TraceEvent)
        .filter(TraceEvent.kind == "tool_end")
        .order_by(TraceEvent.id.asc())
    )
    for ev in q.yield_per(500):
        counts["trace_rows_seen"] += 1
        msg = (ev.message or "").lower()
        tool = (ev.data or {}).get("tool") if isinstance(ev.data, dict) else None
        # Prefer explicit data.tool; fall back to substring of the message.
        if not tool:
            for cand in list(LLM_TOOLS_TO_MODEL.keys()) + [DOCINTEL_TOOL]:
                if cand in msg:
                    tool = cand
                    break
        if not tool:
            continue
        pid = ev.pipeline_id
        stage = ev.stage or "unknown"

        if tool in LLM_TOOLS_TO_MODEL:
            key_in = (pid, stage, tool, "llm_input")
            key_out = (pid, stage, tool, "llm_output")
            if key_in in existing and key_out in existing:
                counts["skipped_existing"] += 1
                continue
            model = LLM_TOOLS_TO_MODEL[tool]
            tokens_in = _estimate_tokens_from_event(ev, "llm_input")
            tokens_out = _estimate_tokens_from_event(ev, "llm_output")
            if key_in not in existing:
                row_in = CostEvent(
                    pipeline_id=pid, stage=stage, tool=tool,
                    component="llm_input", model=model,
                    units=tokens_in, unit_kind="tokens_backfilled",
                    cost_usd=_unit_cost("llm_input", model, tokens_in),
                    ts=ev.ts,
                )
                db.add(row_in)
                existing.add(key_in)
            if key_out not in existing:
                row_out = CostEvent(
                    pipeline_id=pid, stage=stage, tool=tool,
                    component="llm_output", model=model,
                    units=tokens_out, unit_kind="tokens_backfilled",
                    cost_usd=_unit_cost("llm_output", model, tokens_out),
                    ts=ev.ts,
                )
                db.add(row_out)
                existing.add(key_out)
            counts["llm_pairs_added"] += 1
        elif tool == DOCINTEL_TOOL:
            key = (pid, stage, tool, "ocr")
            if key in existing:
                counts["skipped_existing"] += 1
                continue
            pages = _estimate_pages_from_event(ev)
            model = "azure-doc-intelligence-layout"
            row = CostEvent(
                pipeline_id=pid, stage=stage, tool=tool,
                component="ocr", model=model,
                units=pages, unit_kind="pages_backfilled",
                cost_usd=_unit_cost("ocr", model, pages),
                ts=ev.ts,
            )
            db.add(row)
            existing.add(key)
            counts["ocr_rows_added"] += 1

    db.commit()
    return counts


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        result = backfill(db)
        print("Cost backfill complete:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
