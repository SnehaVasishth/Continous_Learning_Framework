"""Continuous-Learning scheduler.

Runs the drift detectors and candidate generators on a periodic tick so
"Continuous Learning" actually runs continuously, not just when an operator
clicks Refresh in the UI.

Two cadences:
  - Detectors  (monitor.run_all_detectors)        every DETECTOR_INTERVAL_SEC
  - Generators (learning_generators.run_all_…)    every GENERATOR_INTERVAL_SEC

Both run in the same daemon thread. The detector cadence is the heartbeat;
the generator cadence is a multiple of it so the math stays simple. Each
tick opens its own DB session and never re-uses a stale one. Failures in
one detector or generator are logged but never stop the loop.

Off-switch: set env `CL_SCHEDULER_ENABLED=0` at startup. Cadence overrides:
`CL_SCHEDULER_DETECTOR_INTERVAL_SEC` and `CL_SCHEDULER_GENERATOR_INTERVAL_SEC`.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

from ..db import SessionLocal

log = logging.getLogger("cl_scheduler")

_STARTED = False

# Defaults: 30-minute detector tick, hourly generator tick. Baseline status
# previously flipped on every 15-minute tick when a single bad case landed
# inside the rolling window; doubling the cadence dampens that. Operators
# can override via env (CL_SCHEDULER_DETECTOR_INTERVAL_SEC) when an incident
# justifies tighter sampling. Generators stay hourly; they emit candidate
# changes and a single new candidate per hour is plenty.
DETECTOR_INTERVAL_SEC = int(os.environ.get("CL_SCHEDULER_DETECTOR_INTERVAL_SEC", "1800"))
GENERATOR_INTERVAL_SEC = int(os.environ.get("CL_SCHEDULER_GENERATOR_INTERVAL_SEC", "3600"))


def _run_detectors_once() -> None:
    from .monitor import run_all_detectors
    db = SessionLocal()
    try:
        out = run_all_detectors(db)
        total = sum(int(v or 0) for v in out.values())
        log.info("cl_scheduler detector tick — %d alerts updated · %s",
                 total, ", ".join(f"{k}={v}" for k, v in out.items()))
    except Exception:
        log.exception("cl_scheduler detector tick failed")
    finally:
        db.close()


def _run_generators_once() -> None:
    from .learning_generators import run_all_generators
    db = SessionLocal()
    try:
        out = run_all_generators(db)
        total = sum(int(v or 0) for v in out.values())
        log.info("cl_scheduler generator tick — %d candidates emitted · %s",
                 total, ", ".join(f"{k}={v}" for k, v in out.items()))
    except Exception:
        log.exception("cl_scheduler generator tick failed")
    finally:
        db.close()


def start_in_background() -> None:
    """Kick off the scheduler thread. Safe to call multiple times — the
    second call is a no-op."""
    global _STARTED
    if _STARTED:
        return
    if os.environ.get("CL_SCHEDULER_ENABLED", "1") in ("0", "false", "no"):
        log.info("cl_scheduler disabled by CL_SCHEDULER_ENABLED env")
        return
    _STARTED = True

    def _loop() -> None:
        log.info(
            "cl_scheduler started — detector every %ds, generator every %ds",
            DETECTOR_INTERVAL_SEC, GENERATOR_INTERVAL_SEC,
        )
        # Stagger the very first tick by 30s after boot so the rest of the
        # lifespan startup (KB seeding, baseline seeding, zombie sweep) has
        # finished and the DB isn't contended.
        time.sleep(30)
        last_detector_at = 0.0
        last_generator_at = 0.0
        while True:
            now = time.time()
            try:
                if now - last_detector_at >= DETECTOR_INTERVAL_SEC:
                    _run_detectors_once()
                    last_detector_at = now
                if now - last_generator_at >= GENERATOR_INTERVAL_SEC:
                    _run_generators_once()
                    last_generator_at = now
            except Exception:
                log.exception("cl_scheduler loop iteration failed")
            # Sleep just long enough to react to the sooner of the two
            # cadences. Bounded so the thread checks its work at least every
            # 60 seconds even if both intervals are huge.
            sleep_for = max(15, min(60, DETECTOR_INTERVAL_SEC // 4, GENERATOR_INTERVAL_SEC // 4))
            time.sleep(sleep_for)

    t = threading.Thread(target=_loop, name="cl_scheduler", daemon=True)
    t.start()


def status() -> dict:
    """Lightweight introspection for an admin endpoint or health page."""
    return {
        "running": _STARTED,
        "detector_interval_sec": DETECTOR_INTERVAL_SEC,
        "generator_interval_sec": GENERATOR_INTERVAL_SEC,
        "as_of": datetime.utcnow().isoformat(),
    }
