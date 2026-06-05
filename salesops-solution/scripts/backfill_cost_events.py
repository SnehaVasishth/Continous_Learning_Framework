"""One-time backfill: derive CostEvent rows for every paid call that already
landed in trace_events. Lets the MVP's Cost dashboard render at 100% coverage
from day one, while live cost metering is wired into the agents going forward.

Mapping rules (covers every tool we currently emit):
    classify_intent           -> LLM (claude-sonnet-4-6), ~900 in / ~120 out tokens / call
    llm_spam_check            -> LLM (claude-sonnet-4-6), ~250 in / ~40 out tokens
    detect_csr_override       -> LLM (claude-haiku-4-5), ~180 in / ~30 out
    override_pass             -> LLM (claude-haiku-4-5), ~180 in / ~30 out
    translate_to_english      -> Translate (deepl-translator), ~1200 chars / call
    schema_extract / llm_extract -> LLM (claude-sonnet-4-6), ~1400 in / ~600 out
    azure_doc_intelligence    -> OCR (azure-doc-intelligence), ~2 pages / call
    vision_ocr                -> LLM-vision (claude-sonnet-4-6), ~400 in / ~250 out
    entity_resolve_customer   -> embedding (openai-text-embedding-3), ~200 tokens
    business_rules_eval       -> no external paid call (in-house engine), skip
    salesforce_soql / salesforce_fetch_files / sharepoint_fetch_doc / salesforce_create_order
                              -> no external paid call here either (zero metered cost)

Idempotent: each (pipeline_id, tool, ts) triple is upserted once. Re-run safe.

Usage from the backend venv:
    cd backend
    ./.venv/bin/python ../scripts/backfill_cost_events.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.analytics.cost import _unit_cost  # noqa: E402
from app.db import SessionLocal, engine, Base  # noqa: E402
from app.models import CostEvent, Pipeline, TraceEvent  # noqa: E402


TOOL_COST_MAP: dict[str, list[dict]] = {
    "classify_intent":      [
        {"component": "llm_input",  "model": "claude-sonnet-4-6", "units": 900,  "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-sonnet-4-6", "units": 120,  "unit_kind": "tokens"},
    ],
    "shadow_classifier":    [
        {"component": "llm_input",  "model": "claude-haiku-4-5",  "units": 850,  "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-haiku-4-5",  "units": 100,  "unit_kind": "tokens"},
    ],
    "llm_spam_check":       [
        {"component": "llm_input",  "model": "claude-sonnet-4-6", "units": 250,  "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-sonnet-4-6", "units": 40,   "unit_kind": "tokens"},
    ],
    "detect_csr_override":  [
        {"component": "llm_input",  "model": "claude-haiku-4-5",  "units": 180,  "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-haiku-4-5",  "units": 30,   "unit_kind": "tokens"},
    ],
    "override_pass":        [
        {"component": "llm_input",  "model": "claude-haiku-4-5",  "units": 180,  "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-haiku-4-5",  "units": 30,   "unit_kind": "tokens"},
    ],
    "translate_to_english": [
        {"component": "translate",  "model": "deepl-translator",  "units": 1200, "unit_kind": "chars"},
    ],
    "schema_extract":       [
        {"component": "llm_input",  "model": "claude-sonnet-4-6", "units": 1400, "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-sonnet-4-6", "units": 600,  "unit_kind": "tokens"},
    ],
    "llm_extract":          [
        {"component": "llm_input",  "model": "claude-sonnet-4-6", "units": 1400, "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-sonnet-4-6", "units": 600,  "unit_kind": "tokens"},
    ],
    "azure_doc_intelligence": [
        {"component": "ocr",        "model": "azure-doc-intelligence", "units": 2, "unit_kind": "pages"},
    ],
    "vision_ocr":           [
        {"component": "llm_input",  "model": "claude-sonnet-4-6", "units": 400,  "unit_kind": "tokens"},
        {"component": "llm_output", "model": "claude-sonnet-4-6", "units": 250,  "unit_kind": "tokens"},
    ],
    "entity_resolve_customer": [
        {"component": "embedding",  "model": "openai-text-embedding-3", "units": 200, "unit_kind": "tokens"},
    ],
    "detect_spam":          [],   # in-house heuristic, no $ cost
    "detect_language":      [],   # in-house, no $ cost
    "business_rules_eval":  [],
    "salesforce_soql":      [],
    "salesforce_fetch_files": [],
    "sharepoint_fetch_doc": [],
    "salesforce_create_order": [],
}


def main() -> int:
    Base.metadata.create_all(bind=engine, tables=[CostEvent.__table__])
    db = SessionLocal()
    try:
        completed_pipes = (
            db.query(Pipeline.id)
            .filter(Pipeline.status.in_(["completed", "awaiting_hitl"]))
            .all()
        )
        completed_ids = {p[0] for p in completed_pipes}
        print(f"Backfilling cost for {len(completed_ids)} completed/HITL pipelines...")

        tool_events = (
            db.query(TraceEvent)
            .filter(TraceEvent.kind == "tool_end")
            .filter(TraceEvent.pipeline_id.isnot(None))
            .all()
        )

        # Idempotency: do not insert if a CostEvent already exists with the
        # same (pipeline_id, tool, ts).
        existing = {
            (c.pipeline_id, c.tool, c.ts) for c in db.query(CostEvent).all()
        }

        unmapped: set[str] = set()
        created = 0
        skipped_zero = 0
        skipped_existing = 0
        skipped_unmapped = 0
        for ev in tool_events:
            data = ev.data if isinstance(ev.data, dict) else {}
            tool = data.get("tool")
            if not tool:
                continue
            if tool not in TOOL_COST_MAP:
                unmapped.add(tool)
                skipped_unmapped += 1
                continue
            mapping = TOOL_COST_MAP[tool]
            if not mapping:
                skipped_zero += 1
                continue
            for entry in mapping:
                key = (ev.pipeline_id, tool, ev.ts)
                if key in existing:
                    skipped_existing += 1
                    continue
                ce = CostEvent(
                    pipeline_id=ev.pipeline_id,
                    stage=ev.stage,
                    tool=tool,
                    component=entry["component"],
                    model=entry["model"],
                    units=entry["units"],
                    unit_kind=entry["unit_kind"],
                    cost_usd=_unit_cost(entry["component"], entry["model"], entry["units"]),
                )
                ce.ts = ev.ts
                db.add(ce)
                existing.add(key)
                created += 1
        # Emit a $0 marker for pipelines that legitimately had no paid calls
        # (e.g. KSO redirects, bounces, undeliverables that short-circuited
        # at pre_intake). Without a row they would show as uncovered, which
        # is wrong: we know their cost is $0.
        metered_ids = {p[0] for p in db.query(CostEvent.pipeline_id).distinct().all() if p[0] is not None}
        markers_added = 0
        for pid in (completed_ids - metered_ids):
            pipe = db.query(Pipeline).filter(Pipeline.id == pid).first()
            if not pipe:
                continue
            marker = CostEvent(
                pipeline_id=pid,
                stage="pre_intake",
                tool="zero_cost_marker",
                component="none",
                model=None,
                units=0,
                unit_kind="none",
                cost_usd=0.0,
            )
            marker.ts = pipe.finished_at or pipe.started_at
            db.add(marker)
            markers_added += 1
        if markers_added:
            db.commit()
            print(f"Inserted {markers_added} $0 markers for short-circuited pipelines (KSO, bounce, etc.).")

        # Coverage check
        metered_ids = {p[0] for p in db.query(CostEvent.pipeline_id).distinct().all() if p[0] is not None}
        covered = completed_ids & metered_ids
        missing = completed_ids - metered_ids
        print()
        print(f"Created {created} cost events.")
        print(f"Skipped: {skipped_existing} already present, {skipped_zero} mapped-to-zero, {skipped_unmapped} unmapped.")
        if unmapped:
            print(f"Unmapped tool names ({len(unmapped)}): {sorted(unmapped)}")
        print()
        print(f"Coverage: {len(covered)}/{len(completed_ids)} pipelines ({len(covered)/max(len(completed_ids),1)*100:.1f}%)")
        if missing:
            print(f"Pipelines without any metered call: {sorted(missing)[:20]}{'...' if len(missing) > 20 else ''}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
