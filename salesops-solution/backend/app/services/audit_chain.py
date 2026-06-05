"""Tamper-evident hash chain over the Continuous-Learning audit log.

Every `PromotionDecision` row carries an `entry_hash` computed over its
canonical payload plus the `entry_hash` of the row immediately before it
(by `decided_at` / `id` order). A verifier walks the chain top-to-bottom
and detects any row that was edited after the fact, deleted, or inserted
out of order.

Two entry points:

  append_decision(db, decision) — call this AFTER db.add(decision) and
  db.flush() (so the row has an id), but BEFORE the final commit. Sets
  `prev_hash` from the previous row, computes `entry_hash`, leaves the
  row ready to be committed.

  verify_chain(db) — read every PromotionDecision in canonical order,
  recompute each hash, and report any breaks.

The hash domain is the canonical JSON of the row's core audit fields. We
deliberately exclude db-managed columns like `id` so the chain's integrity
is over the SEMANTIC content, not the row's storage identity.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import PromotionDecision

# Fields that participate in the hash. Editing any of these silently
# invalidates the chain past that row. `prev_hash` is INCLUDED so a swap of
# two rows is also detected.
_HASH_FIELDS = (
    "experiment_id",
    "decided_at",
    "decided_by_id",
    "decided_by_name",
    "decided_by_role",
    "decided_by_role_source",
    "action",
    "gate_enabled",
    "gate_reasons",
    "sample_size",
    "delta_pct",
    "force_reason",
    "outcome",
    "outcome_detail",
    "prev_hash",
)


def _serialize_for_hash(d: PromotionDecision) -> str:
    payload: dict[str, Any] = {}
    for field in _HASH_FIELDS:
        v = getattr(d, field, None)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        payload[field] = v
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(d: PromotionDecision) -> str:
    body = _serialize_for_hash(d)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _previous_entry_hash(db: Session, before_id: int | None = None) -> str | None:
    """Return the entry_hash of the most recent row strictly before the row
    we're about to seal. `before_id` is used when sealing a row we just
    added to the session; passing None returns the chain head."""
    q = db.query(PromotionDecision).filter(PromotionDecision.entry_hash.isnot(None))
    if before_id is not None:
        q = q.filter(PromotionDecision.id != before_id)
    row = q.order_by(PromotionDecision.decided_at.desc(), PromotionDecision.id.desc()).first()
    return row.entry_hash if row else None


def append_decision(db: Session, decision: PromotionDecision) -> PromotionDecision:
    """Seal `decision` into the chain. Call after `db.add()` + `db.flush()`
    so the row has its id and timestamps; do not call before flush.
    Returns the same decision with `prev_hash` + `entry_hash` populated."""
    decision.prev_hash = _previous_entry_hash(db, before_id=decision.id)
    decision.entry_hash = _compute_hash(decision)
    return decision


def verify_chain(db: Session) -> dict[str, Any]:
    """Walk the chain top-to-bottom, recompute each hash, report breaks.

    Returns:
      { total, verified_ok, breaks: [ {id, decided_at, reason, expected, actual} ],
        head_id, head_hash }
    """
    rows = (
        db.query(PromotionDecision)
        .order_by(PromotionDecision.decided_at.asc(), PromotionDecision.id.asc())
        .all()
    )
    breaks: list[dict[str, Any]] = []
    prev = None
    for r in rows:
        # 1. prev_hash must match the running pointer.
        expected_prev = prev
        if (r.prev_hash or None) != (expected_prev or None):
            breaks.append({
                "id": r.id,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "reason": "prev_hash_mismatch",
                "expected": expected_prev,
                "actual": r.prev_hash,
            })
        # 2. Recompute the entry hash from current values.
        if r.entry_hash is None:
            breaks.append({
                "id": r.id,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "reason": "missing_entry_hash",
                "expected": None,
                "actual": None,
            })
        else:
            expected = _compute_hash(r)
            if expected != r.entry_hash:
                breaks.append({
                    "id": r.id,
                    "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                    "reason": "entry_hash_mismatch",
                    "expected": expected,
                    "actual": r.entry_hash,
                })
        prev = r.entry_hash
    head = rows[-1] if rows else None
    return {
        "total": len(rows),
        "verified_ok": len(breaks) == 0,
        "breaks": breaks,
        "head_id": head.id if head else None,
        "head_hash": head.entry_hash if head else None,
    }


def backfill_chain(db: Session, *, force: bool = False) -> int:
    """Compute hashes for audit rows.

    Default mode skips rows that already have an `entry_hash` — useful on
    first install to seal pre-existing history without disturbing rows that
    were sealed at insert time.

    `force=True` re-seals EVERY row from scratch. Use this when the hash
    domain has changed (i.e. you added a new field to `_HASH_FIELDS` so
    the old hashes no longer recompute equal). It is destructive of any
    PREVIOUS chain head pointer but produces a fresh, internally
    consistent chain over the current schema.
    """
    rows = (
        db.query(PromotionDecision)
        .order_by(PromotionDecision.decided_at.asc(), PromotionDecision.id.asc())
        .all()
    )
    sealed = 0
    prev = None
    for r in rows:
        if r.entry_hash and not force:
            prev = r.entry_hash
            continue
        r.prev_hash = prev
        r.entry_hash = _compute_hash(r)
        prev = r.entry_hash
        sealed += 1
    if sealed:
        db.commit()
    return sealed
