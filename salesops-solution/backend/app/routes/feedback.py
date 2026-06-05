from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Feedback
from ..services import baselines as baselines_svc

router = APIRouter()


class FeedbackIn(BaseModel):
    pipeline_id: int
    stage: str
    kind: str
    note: str | None = None
    data: dict | None = None


@router.get("")
def list_feedback(
    baseline_id: int | None = None,
    db: Session = Depends(get_db),
):
    """List recent feedback rows. Optional ?baseline_id=<id> filters to the
    rows whose write-time anchor matches the requested baseline.

    Every row carries both the persisted `baseline_id` and a read-time
    `derived_baseline_id` (computed by heuristic when the row was written
    before the FK existed, or when the original derivation returned no
    match). `baseline_label` resolves whichever id is populated, so the
    frontend never has to do a second roundtrip."""
    q = db.query(Feedback).order_by(Feedback.created_at.desc())
    if baseline_id is not None:
        q = q.filter(Feedback.baseline_id == baseline_id)
    rows = q.limit(200).all()
    # Cache derivations + label lookups inside this request scope.
    label_cache: dict[int, str | None] = {}

    def _label(bid: int | None) -> str | None:
        if not bid:
            return None
        if bid not in label_cache:
            label_cache[bid] = baselines_svc.resolve_label(db, bid)
        return label_cache[bid]

    out = []
    for f in rows:
        derived = f.baseline_id or baselines_svc.derive_feedback_baseline_id(db, f)
        out.append({
            "id": f.id,
            "pipeline_id": f.pipeline_id,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "stage": f.stage,
            "kind": f.kind,
            "note": f.note,
            "data": f.data,
            "baseline_id": f.baseline_id,
            "derived_baseline_id": derived,
            "baseline_label": _label(derived),
        })
    return out


@router.post("")
def add_feedback(body: FeedbackIn, db: Session = Depends(get_db)):
    f = Feedback(
        pipeline_id=body.pipeline_id,
        stage=body.stage,
        kind=body.kind,
        note=body.note,
        data=body.data or {},
    )
    # Best-effort write-time derivation. The read path also derives heuristic
    # anchors at request time, so this is purely an optimisation for the
    # common case (lets the SQL filter find the row without a join).
    try:
        f.baseline_id = baselines_svc.derive_feedback_baseline_id(db, f)
    except Exception:
        f.baseline_id = None
    db.add(f)
    db.commit()
    return {"id": f.id, "baseline_id": f.baseline_id}
