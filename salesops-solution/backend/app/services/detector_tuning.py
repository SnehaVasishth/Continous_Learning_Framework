"""Cached resolver for the detector-tuning KB namespace.

Detectors call `get(db, key)` per tick to read their sensitivity knobs.
Lookups are TTL-cached (10s) so a single scheduler tick doesn't hit the
database eight times for a small handful of rows.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeRule


_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TTL_SEC = 10.0


def _load(db: Session, key: str) -> dict[str, Any] | None:
    row = (
        db.query(KnowledgeRule)
        .filter_by(namespace="detector_tuning", key=key)
        .first()
    )
    if row is None:
        return None
    body = row.body if isinstance(row.body, dict) else {}
    if not body:
        return None
    return body


def get(db: Session, key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """Return the tuning body for `key`, falling back to the provided dict
    when the KB row is missing or empty. Cached for 10 seconds."""
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _TTL_SEC:
        return cached[1]
    body = _load(db, key)
    resolved = dict(fallback)
    if body:
        # Shallow merge — KB wins for any key it specifies.
        for k, v in body.items():
            resolved[k] = v
    _CACHE[key] = (now, resolved)
    return resolved


def invalidate(key: str | None = None) -> None:
    """Clear the cache. `None` clears all entries; a key clears just that
    one. Useful in tests or right after an admin edit."""
    if key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(key, None)
