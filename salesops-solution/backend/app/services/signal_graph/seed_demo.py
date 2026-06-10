"""Demo observation seeder.

Writes a realistic, clearly-labelled (meta.synthetic=true) time series into
signal_observations for an already-discovered session, so the data-conditional
analysis (suggested range, edge weights, drift) can be tested and demoed.

This is a DEMO/TEST tool — not real client telemetry. A real client would feed
observations through observe.record_observation from its own data source; this
just manufactures plausible series for the keys a session already discovered.
"""
from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy.orm import Session

from ...models import Baseline, BaselineRecommendation, SignalNode, now
from .observe import record_observation


# Plausible value band per compute type, so a seeded metric reads in sane units.
_BANDS = {
    "rate": (0.80, 0.99),
    "ratio": (0.80, 0.99),
    "p95": (120.0, 480.0),
    "count": (40.0, 200.0),
    "mean": (0.5, 5.0),
    "psi": (0.0, 0.30),
}


def _band(compute: str | None) -> tuple[float, float]:
    return _BANDS.get(compute or "rate", (0.80, 0.99))


def seed_demo_observations(db: Session, domain: str, *, windows: int = 8) -> dict:
    """(Re)seed synthetic observations for one session. Idempotent: clears this
    domain's observations first, so re-running doesn't pile up duplicates."""
    from ...models import SignalObservation
    db.query(SignalObservation).filter(SignalObservation.domain == domain).delete(synchronize_session=False)

    rng = random.Random(42)                       # deterministic across runs
    base_time = now() - timedelta(days=windows)

    # Gates: metric -> (inputs, compute, accepted_gate_or_None).
    gates: dict[str, dict] = {}
    for r in db.query(BaselineRecommendation).filter(BaselineRecommendation.domain == domain).all():
        snap = r.subgraph_snapshot or {}
        gates[r.metric] = {"inputs": snap.get("inputs", []), "compute": snap.get("compute"), "gate": None}
    # Accepted gates are now discovered Baselines (no inputs/compute columns —
    # we just seed the metric's own series so drift works).
    for b in db.query(Baseline).filter(Baseline.domain == domain, Baseline.source == "discovered").all():
        gates.setdefault(b.metric, {"inputs": [], "compute": None, "gate": None})
        gates[b.metric]["gate"] = b

    def _write(key: str, series: list[float], stream: str = "telemetry", n_lo: int = 40, n_hi: int = 120) -> None:
        for i, val in enumerate(series):
            ws = base_time + timedelta(days=i)
            record_observation(
                db, domain=domain, signal_key=key, value=round(val, 4),
                window_start=ws, window_end=ws + timedelta(days=1),
                sample_size=rng.randint(n_lo, n_hi), source_stream=stream,
                meta={"synthetic": True},
            )

    written = 0
    metric_series: dict[str, list[float]] = {}

    # 1) one trended series per gate metric.
    for idx, (metric, info) in enumerate(gates.items()):
        gate = info["gate"]
        if gate is not None:
            tgt = gate.target_value
            start = tgt * 1.05
            breach = (idx % 2 == 0)               # alternate breached / healthy for a lively demo
            if gate.direction == "min":           # higher is better -> breach = drift below target
                end = tgt * 0.90 if breach else tgt * 1.05
            else:                                  # lower is better -> breach = drift above target
                end = tgt * 1.10 if breach else tgt * 0.95
        else:
            lo, hi = _band(info["compute"])
            start, end = hi, lo + (hi - lo) * 0.5  # gentle downward trend within band

        series = [start + (end - start) * (i / max(1, windows - 1)) + rng.uniform(-0.01, 0.01) * abs(start or 1)
                  for i in range(windows)]
        metric_series[metric] = series
        _write(metric, series)
        written += len(series)

        # Accepted gates also get a FEEDBACK stream: human review on a smaller
        # subset, running a bit below telemetry (the self-blinding gap that
        # dual-input drift is meant to catch).
        if gate is not None:
            fb_series = [v * 0.93 + rng.uniform(-0.01, 0.01) * abs(v or 1) for v in series]
            _write(metric, fb_series, stream="feedback", n_lo=12, n_hi=40)
            written += len(fb_series)

    # 2) input signals correlated with their gate metric (so edge weights are real).
    seeded: set[str] = set()
    for metric, info in gates.items():
        ms = metric_series.get(metric, [])
        for s in info["inputs"]:
            if s in seeded or not ms:
                continue
            seeded.add(s)
            series = [ms[i] * 100 + rng.uniform(-3, 3) for i in range(windows)]  # scaled + noise
            _write(s, series)
            written += len(series)

    # 3) any remaining raw signals get an independent series.
    for n in db.query(SignalNode).filter(SignalNode.domain == domain,
                                          SignalNode.node_type == "raw_signal").all():
        if n.key in seeded or n.key in metric_series:
            continue
        seeded.add(n.key)
        series = [rng.uniform(0.5, 1.0) for _ in range(windows)]
        _write(n.key, series)
        written += len(series)

    db.commit()
    return {"domain": domain, "windows": windows, "observations_written": written,
            "gates": len(gates), "signals_seeded": len(seeded)}
