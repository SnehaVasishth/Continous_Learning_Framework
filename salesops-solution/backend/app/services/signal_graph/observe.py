
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...models import SignalObservation

MIN_WINDOWS = 2


def record_observation(
    db: Session,
    *,
    domain: str,
    signal_key: str,
    value: Optional[float],
    window_start: datetime,
    window_end: datetime,
    sample_size: int,
    source_stream: str,
    segment: str = "global",
    autonomy_tier: Optional[str] = None,
    meta: Optional[dict] = None,
) -> SignalObservation:
    
    obs = SignalObservation(
        domain=domain,
        signal_key=signal_key,
        segment=segment,
        window_start=window_start,
        window_end=window_end,
        value=value,
        sample_size=sample_size,
        source_stream=source_stream,
        autonomy_tier=autonomy_tier,
        meta=meta or {},
    )
    db.add(obs)
    return obs


def observation_series(
    db: Session,
    domain: str,
    signal_key: str,
    segment: str = "global",
) -> list[SignalObservation]:
    
    return (
        db.query(SignalObservation)
        .filter(
            SignalObservation.domain == domain,
            SignalObservation.signal_key == signal_key,
            SignalObservation.segment == segment,
        )
        .order_by(SignalObservation.window_start.asc())
        .all()
    )


def data_status(
    db: Session,
    domain: str,
    signal_key: str,
    segment: str = "global",
) -> str:
   
    rows = observation_series(db, domain, signal_key, segment)
    if not rows:
        return "no_data"
    distinct_windows = {r.window_start for r in rows if r.value is not None}
    if len(distinct_windows) < MIN_WINDOWS:
        return "insufficient_data"
    return "ok"


def ingest_for_domain(db: Session, domain: str) -> dict:   
 
    return {"domain": domain, "ingested": 0, "reason": "no_source"}
