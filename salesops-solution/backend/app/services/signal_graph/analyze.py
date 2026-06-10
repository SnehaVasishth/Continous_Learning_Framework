"""Data-driven analysis over the signal graph: suggested range (Task 12),
edge weights + drift (Task 13).

Every function here is DATA-CONDITIONAL: it asks observe.data_status first and
returns an explicit "insufficient_data" verdict rather than inventing numbers
when a client has no telemetry. The maths is reused from `confirm`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import confirm
from .observe import observation_series, data_status


def _values(db: Session, domain: str, signal_key: str, segment: str) -> list[float]:
    """The non-null observed values for one signal, oldest window first."""
    return [r.value for r in observation_series(db, domain, signal_key, segment) if r.value is not None]


def suggested_range(db: Session, domain: str, metric: str, segment: str = "global") -> dict:
    """A non-binding hint for the human's target: where the metric has sat.

    Returns {"status": "ok", "median", "p10", "p90", "n"} when enough data
    exists, else {"status": "no_data" | "insufficient_data"}. The target value
    is NEVER derived from this — it only informs the human.
    """
    status = data_status(db, domain, metric, segment)
    if status != "ok":
        return {"status": status}
    values = _values(db, domain, metric, segment)
    dist = confirm.context_distribution(values)   # {median, p10, p90}
    return {"status": "ok", "n": len(values), **dist}
