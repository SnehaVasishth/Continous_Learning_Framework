from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.stats import pearsonr


def context_distribution(values: list[float]) -> dict:
    if not values:
        return {"median": None, "p10": None, "p90": None}
    arr = np.asarray(values, dtype=float)
    return {
        "median": float(np.percentile(arr, 50)),
        "p10": float(np.percentile(arr, 10)),
        "p90": float(np.percentile(arr, 90)),
    }


def variability(values: list[float]) -> float:
    """Population standard deviation; 0 for constant or empty."""
    if len(values) < 2:
        return 0.0
    return float(np.std(values))  # ddof=0 -> population std


def edge_weight(
    signal: list[float], metric: list[float], *, min_samples: int = 3,
) -> Optional[float]:
    """Absolute Pearson correlation as edge weight in [0, 1]. Returns None
    below the sample floor (so the edge stays structural with weight=null
    rather than a misleading 'weak'). Zero-variance series -> 0.0."""
    n = min(len(signal), len(metric))
    if n < min_samples:
        return None
    x = np.asarray(signal[:n], dtype=float)
    y = np.asarray(metric[:n], dtype=float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    r, _ = pearsonr(x, y)
    if np.isnan(r):
        return 0.0
    return float(abs(max(-1.0, min(1.0, r))))