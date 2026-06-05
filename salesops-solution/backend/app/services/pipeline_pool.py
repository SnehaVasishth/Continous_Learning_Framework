"""Pipeline worker pool — bounded concurrency for parallel pipeline execution.

The demo runs a single FastAPI process, but the RFP commitment is 880k emails
per year (~2,000/day, with 5x quarter-end bursts to ~10,000/day, and a
50x stress test target). To stand behind that commitment in the demo, this
module provides a bounded ThreadPoolExecutor so multiple inbound emails are
processed concurrently rather than serialised through a single worker.

Each submitted job opens its own SQLAlchemy session, runs `run_pipeline`,
records the outcome, and frees the slot. Slot count is configurable via the
PIPELINE_POOL_WORKERS env var (default 8). The pool's live status is exposed
on `/api/pipeline/queue-status` so the Dashboard can render queue depth and
worker utilisation in real time.

Production deployments swap this in-process pool for a real Celery / RQ
backend without touching the agent code — the orchestrator is already
stateless per pipeline_id and idempotent on its writes (see PipelineExecution
table).
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any

from ..db import SessionLocal

log = logging.getLogger("pipeline_pool")


class ReadinessBlockedAtPool(Exception):
    """Raised by `PipelinePool.submit()` when the readiness gate fails.

    A safety net: callers should always gate at the REST/route layer (where
    a structured HTTP 412 is returned), but if they forget, the pool refuses
    so the pipeline never runs with a required dependency disconnected.
    """

    def __init__(self, report):
        self.report = report
        super().__init__(
            f"pipeline pool refused: {len(report.blockers)} blocker(s)"
        )


def _default_workers() -> int:
    """Worker count for the pipeline pool. Defaults to 1 to keep SQLite from
    hitting `database is locked` under concurrent writes from the orchestrator,
    email_sync, aioa_service, and connection_monitor all sharing one file.
    Operators on PostgreSQL or those willing to accept transient contention
    can override via PIPELINE_POOL_WORKERS env."""
    try:
        return max(1, int(os.environ.get("PIPELINE_POOL_WORKERS", "3")))
    except Exception:
        return 1


class PipelinePool:
    """Bounded ThreadPoolExecutor for concurrent pipeline runs."""

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers or _default_workers()
        self.pool = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="pipeline",
        )
        self._in_flight: dict[int, dict] = {}
        self._lock = Lock()
        self._completed = 0
        self._errored = 0
        self._total_submitted = 0
        self._latency_samples_ms: list[int] = []
        # Cap samples so the list doesn't grow unbounded over a long uptime.
        self._max_samples = 1000

    def submit(self, *, pipeline_id: int, email_id: int) -> Future:
        """Submit a pipeline run. Returns the Future so callers can wait if
        they need synchronous semantics; most callers will fire and forget.

        Enterprise readiness safety net: even if a caller forgets to gate at
        the REST layer, the pool itself refuses to start a job when the
        readiness check fails. This guarantees the pipeline cannot run with
        a required dependency disconnected (Salesforce, SharePoint, or
        mailbox), regardless of how the job was queued.
        """
        from .readiness import check_readiness
        db = SessionLocal()
        try:
            report = check_readiness(db)
            if not report.ok:
                raise ReadinessBlockedAtPool(report)
        finally:
            db.close()
        with self._lock:
            self._total_submitted += 1
            self._in_flight[pipeline_id] = {
                "email_id": email_id,
                "submitted_at": time.time(),
            }
        future = self.pool.submit(self._run_job, pipeline_id, email_id)
        future.add_done_callback(lambda f, pid=pipeline_id: self._on_complete(pid, f))
        return future

    def _run_job(self, pipeline_id: int, email_id: int) -> None:
        from ..agents.orchestrator import run_pipeline
        db = SessionLocal()
        try:
            run_pipeline(db, pipeline_id=pipeline_id, email_id=email_id)
        finally:
            db.close()

    def _on_complete(self, pipeline_id: int, future: Future) -> None:
        with self._lock:
            job = self._in_flight.pop(pipeline_id, None)
            elapsed_ms = 0
            if job is not None:
                elapsed_ms = int((time.time() - job["submitted_at"]) * 1000)
                self._latency_samples_ms.append(elapsed_ms)
                if len(self._latency_samples_ms) > self._max_samples:
                    self._latency_samples_ms = self._latency_samples_ms[-self._max_samples:]
            if future.exception() is not None:
                self._errored += 1
                log.warning(
                    "pipeline_pool: job %s errored: %s",
                    pipeline_id,
                    future.exception(),
                )
            else:
                self._completed += 1

    def status(self) -> dict[str, Any]:
        with self._lock:
            in_flight_count = len(self._in_flight)
            samples = list(self._latency_samples_ms)
            completed = self._completed
            errored = self._errored
            submitted = self._total_submitted
        samples_sorted = sorted(samples)
        return {
            "max_workers": self.max_workers,
            "in_flight": in_flight_count,
            "queue_capacity": self.max_workers,
            "utilisation_pct": round(min(100.0, in_flight_count / self.max_workers * 100.0), 1),
            "total_submitted": submitted,
            "completed": completed,
            "errored": errored,
            "latency_ms": {
                "samples": len(samples_sorted),
                "p50": samples_sorted[len(samples_sorted) // 2] if samples_sorted else 0,
                "p95": samples_sorted[int(len(samples_sorted) * 0.95)] if samples_sorted else 0,
                "p99": samples_sorted[int(len(samples_sorted) * 0.99)] if samples_sorted else 0,
            },
        }

    def shutdown(self, wait: bool = True) -> None:
        self.pool.shutdown(wait=wait)


# Module-level singleton. FastAPI workers reuse this across requests so the
# in-flight / completed counters are accurate for the running process.
_pool: PipelinePool | None = None


def get_pool() -> PipelinePool:
    global _pool
    if _pool is None:
        _pool = PipelinePool()
    return _pool
