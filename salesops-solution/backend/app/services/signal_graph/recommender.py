import logging
import math
from datetime import timedelta

from sqlalchemy.orm import Session

from ...models import BaselineRecommendation, Pipeline, now
from . import confirm
from .scanner import scan_candidates

log = logging.getLogger("signal_graph.recommender")


def _segment_volume(db: Session, domain: str, segment: str, since) -> int:
    """How many recent cases this gate's slice covers."""
    q = db.query(Pipeline).filter(Pipeline.started_at >= since)
    if segment.startswith("intent:"):
        q = q.filter(Pipeline.intent == segment.split("intent:", 1)[1])
    return q.count()


def _score(volume: int, var: float, has_signal: bool) -> float:
    """Blend busyness + movement + explainability into one 0..1 number."""
    vol_term = math.log10(volume + 1) / 3.0       # ~1.0 at 1000 cases
    move_term = min(var * 5.0, 1.0)               # wobble, capped
    sig_term = 0.3 if has_signal else 0.0         # explainability bonus
    return round(min(vol_term, 1.0) * 0.5 + move_term * 0.3 + sig_term, 4)


def generate_recommendations(db: Session, *, domain: str, window_days: int = 90) -> list[dict]:
    since = now() - timedelta(days=window_days)
    out: list[dict] = []
    for cand in scan_candidates(db, domain=domain):
        try:
            volume = _segment_volume(db, domain, cand["segment"], since)
            stats = confirm.context_distribution([])  # placeholder until real values wired
            var = 0.0
            has_signal = any(
                n["node_type"] == "raw_signal" for n in cand["subgraph"]["nodes"]
            )
            score = _score(volume, var, has_signal)

            existing = db.query(BaselineRecommendation).filter(
                BaselineRecommendation.domain == domain,
                BaselineRecommendation.metric == cand["metric"],
                BaselineRecommendation.segment == cand["segment"],
            ).first()

            rationale = (
                f"{volume} cases in {window_days}d. "
                + (
                    "Has at least one upstream signal so drift is explainable."
                    if has_signal
                    else "No upstream signal coverage yet."
                )
            )

            if existing:
                if existing.status == "open":
                    existing.score = score
                    existing.rationale = rationale
                    existing.context_stats = stats
                    existing.subgraph_snapshot = cand["subgraph"]
            else:
                db.add(BaselineRecommendation(
                    domain=domain,
                    metric=cand["metric"],
                    segment=cand["segment"],
                    direction=cand["direction"],
                    score=score,
                    rationale=rationale,
                    context_stats=stats,
                    subgraph_snapshot=cand["subgraph"],
                    status="open",
                ))

            out.append({
                "metric": cand["metric"],
                "segment": cand["segment"],
                "score": score,
            })
        except Exception as e:
            log.exception("recommend failed for %s/%s: %s", cand["metric"], cand["segment"], e)

    db.commit()
    return out