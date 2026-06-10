"""Observation ingestion + reading for the signal graph.

This module is the ONE place that writes and reads `signal_observations`
(the per-signal, per-window time series). Everything downstream — suggested
range, edge weights, drift — asks this module "what values has this signal
taken over time?" and "is there enough data to compute anything?".

Design principle (per product guidance): all analysis is DATA-CONDITIONAL.
A client solution zip never carries telemetry, so an imported client has no
observations and every calculation must degrade to "insufficient data"
instead of inventing a number. When a real data source DOES exist for a
client (e.g. Keysight's own trace_events), we ingest from it and the
calculations light up automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...models import SignalObservation

# A metric needs at least this many distinct time windows before drift or an
# edge weight (correlation) can be computed. One point is a snapshot, not a
# series.
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
    """Insert one observation (one signal's value over one time window).

    This is the single write primitive. Real client feeds and the Keysight
    demo adapter both go through here, so storage stays consistent.
    """
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
    """All observations for one signal, oldest window first.

    The chronological order matters: drift compares the latest window to
    earlier ones, and edge-weight correlation pairs values window-by-window.
    """
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
    """The data-conditional switch every calculation checks first.

    Returns one of:
      "no_data"          - no observations at all (e.g. a fresh imported client)
      "insufficient_data"- some, but fewer than MIN_WINDOWS distinct windows
      "ok"               - enough to compute range / drift / weights
    """
    rows = observation_series(db, domain, signal_key, segment)
    if not rows:
        return "no_data"
    distinct_windows = {r.window_start for r in rows if r.value is not None}
    if len(distinct_windows) < MIN_WINDOWS:
        return "insufficient_data"
    return "ok"


def ingest_for_domain(db: Session, domain: str) -> dict:
    """Best-effort ingestion entry point for a client.

    If a real telemetry source exists for this client, populate observations
    from it and return how many rows were written. v1 has no live client feed
    for imported solution zips, so this honestly reports "no_source" for them.
    The Keysight demo adapter (separate step) is what actually produces rows
    for the demo, derived from real trace_events.
    """
    # Hook point: a future real-client adapter plugs in here, keyed by domain.
    return {"domain": domain, "ingested": 0, "reason": "no_source"}
