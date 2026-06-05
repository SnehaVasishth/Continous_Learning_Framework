"""Seed synthetic CSR feedback against completed cases so the Continuous Learning
stage shows real data in the funnel and Activity list.

Picks the N most recent completed (or awaiting_hitl) pipelines and attaches 1-2
Feedback records per pipeline. Each record is a realistic CSR feedback note
against a specific processing stage. Idempotent: existing feedback for the
selected pipelines is left untouched; only pipelines with zero feedback get
new records.

Usage from the backend venv:
    cd backend
    ./.venv/bin/python ../scripts/seed_learning_feedback.py [--count 30]
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal  # noqa: E402
from app.models import Feedback, Pipeline  # noqa: E402

# (stage, kind, note) tuples grouped by stage. The seeder samples 1 or 2 of
# these per chosen pipeline. Notes are written in the same enterprise voice
# a real CSR would use in the HITL portal.
FEEDBACK_TEMPLATES: list[tuple[str, str, str]] = [
    # Intake
    ("intake", "thumbs_up", "Intent classification matched. Sender pattern was an obvious distributor signal."),
    ("intake", "thumbs_up", "Multi-intent email correctly split. Primary intent picked the actionable Q2O."),
    ("intake", "thumbs_up", "Language detection accurate, routed via the Japan overlay as expected."),
    ("intake", "thumbs_down", "Re-classified to Quote-to-Order. The PO number was a quote reference, not a confirmed PO."),
    ("intake", "thumbs_down", "Misrouted as Service Order. Email body referenced WO maintenance but the attached PO was a new sales order."),
    ("intake", "edit", "Adjusted intent to General Inquiry. Customer was asking about lead-time before placing an order."),
    ("intake", "edit", "Forced classification to Brazil Tax. Outlook pre-filter should have caught this earlier."),
    # Extract
    ("extract", "thumbs_up", "All six line items parsed correctly from the multi-asset PO attachment."),
    ("extract", "thumbs_up", "Ship-to and Bill-to disambiguated cleanly from the embedded PDF."),
    ("extract", "thumbs_up", "Currency, payment terms, and final destination country all picked up first pass."),
    ("extract", "thumbs_down", "Picked Bill-to address as Ship-to. Customer always uses separate ship-to per location."),
    ("extract", "thumbs_down", "Missed the Model and Serial pair on page 3 of the scanned PDF."),
    ("extract", "edit", "Corrected PO amount. Discount line was not applied during extraction."),
    ("extract", "edit", "Replaced extracted SKU with magic-SKU CUSTOM PRODUCT, original code is unresolved."),
    # Decide
    ("decide", "thumbs_up", "Four-gate calibration held. Auto-action was the right call."),
    ("decide", "thumbs_up", "Held for CSR review on Action Feasibility gate. Customer is on credit hold."),
    ("decide", "thumbs_down", "Confidence over-stated. This should have routed to HITL given the multi-intent signal."),
    ("decide", "edit", "Forced to HITL. Account is flagged for compliance review this quarter."),
    # Execute
    ("execute", "thumbs_up", "CCC Request created cleanly. Owner assignment matched the routing rules."),
    ("execute", "thumbs_up", "Linked existing CCC for the Change Order. Delta amount computed correctly."),
    ("execute", "thumbs_down", "Wrong CCC linked. The PO referenced a closed case from last quarter."),
    ("execute", "edit", "Reassigned to SOM CSR queue. Multi-asset case needed manual fan-out."),
    # Communicate
    ("communicate", "thumbs_up", "Reply tone matched the customer escalation level. Translation glossary picked up the Keysight terminology."),
    ("communicate", "thumbs_up", "KSP pointer included for self-service follow-up. Spanish phrasing reads naturally."),
    ("communicate", "thumbs_down", "Tone was too formal. This customer prefers concise replies without standard pleasantries."),
    ("communicate", "edit", "Added missing line confirming the requested ship date. Customer had asked for it in the original email."),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30,
                        help="Number of pipelines to seed feedback against (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable seeding")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    db = SessionLocal()
    try:
        candidates = (
            db.query(Pipeline)
            .filter(Pipeline.status.in_(["completed", "awaiting_hitl"]))
            .order_by(Pipeline.started_at.desc())
            .all()
        )
        existing_feedback_pipe_ids = {
            pid for (pid,) in db.query(Feedback.pipeline_id).filter(Feedback.pipeline_id.isnot(None)).distinct().all()
        }
        eligible = [p for p in candidates if p.id not in existing_feedback_pipe_ids]
        if not eligible:
            print("All completed pipelines already have feedback. Nothing to do.")
            return 0

        target = min(args.count, len(eligible))
        selected = eligible[:target]
        print(f"Seeding feedback against {target} pipelines (of {len(eligible)} eligible).")

        created = 0
        by_kind: dict[str, int] = {"thumbs_up": 0, "thumbs_down": 0, "edit": 0}
        by_stage: dict[str, int] = {}
        for p in selected:
            n_records = rng.choices([1, 2], weights=[3, 2], k=1)[0]
            templates = rng.sample(FEEDBACK_TEMPLATES, k=n_records)
            base_ts = p.finished_at or p.started_at
            for i, (stage, kind, note) in enumerate(templates):
                ts = (base_ts + timedelta(minutes=15 + i * 7)) if base_ts else None
                fb = Feedback(
                    pipeline_id=p.id,
                    stage=stage,
                    kind=kind,
                    note=note,
                    data={"source": "seed", "seed_version": 1},
                )
                if ts is not None:
                    fb.created_at = ts
                db.add(fb)
                created += 1
                by_kind[kind] = by_kind.get(kind, 0) + 1
                by_stage[stage] = by_stage.get(stage, 0) + 1

        db.commit()
        print(f"\nCreated {created} feedback rows across {target} distinct pipelines.")
        print(f"  by kind:  {by_kind}")
        print(f"  by stage: {by_stage}")

        distinct = (
            db.query(Feedback.pipeline_id)
            .filter(Feedback.pipeline_id.isnot(None))
            .distinct()
            .count()
        )
        print(f"  total distinct pipelines now carrying feedback (Continuous Learning count): {distinct}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
