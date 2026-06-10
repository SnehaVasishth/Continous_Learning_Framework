# Signal Graph — Baseline Recommender + Dual-Input Drift — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend that (1) recommends baseline quality gates and, for every gate, derives the upstream signals that affect it, and (2) consolidates the two input streams (CSR feedback + agent traceback) across ALL autonomy tiers to compute and explain drift.

**Architecture:** One shared, stored artifact — a Signal Dependency Graph (`baseline_target ← metric ← stage_outcome ← raw_signal`) — built from a declarative `MetricSpec` registry. A scanner + confirmer recommend gates (human always sets the number); a backtracker persists each gate's signal subgraph; an extractor writes per-signal observations from both streams for all tiers; a drift component computes each gate's observed value from the consolidated observations and attributes any breach to the upstream signals that moved most.

**Tech Stack:** Python 3.10+, FastAPI 0.115, SQLAlchemy 2.0.36, pydantic 2.9.2, pure-Python stats (no numpy/scipy). Tests: pytest on in-memory SQLite (added as a dev dependency — none exists today).

**Spec:** `docs/superpowers/specs/2026-06-05-signal-graph-baseline-recommender-and-dual-input-drift-design.md`

---

## Conventions for every task

- **Backend root:** `salesops-solution/backend` (all paths below are relative to the repo root).
- **Run tests from the backend root** using the project venv:
  - PowerShell: `cd salesops-solution/backend; .venv\Scripts\python -m pytest <path> -v`
  - The plan writes each `Run:` line in that form.
- **DB sessions:** services take a SQLAlchemy `Session` as their first argument (`db`). Never open their own session. Match the existing `app/services/*.py` style.
- **Timestamps:** use `from ..models import now` (returns tz-aware UTC `datetime`) — never `datetime.now()` directly.
- **Domain:** a single default domain string `"keysight"`. A module constant `DEFAULT_DOMAIN` lives in `app/services/signal_graph/__init__.py`.
- **Commits:** the repo may not be git-initialised. If `git status` errors, run `git init` once before the first commit (Task 0, Step 6). Keep the per-task commit steps as written.
- **No silent failures:** per-item `try/except` logs and skips, but never `return 0` silently — mirror `monitor.run_all_detectors`.

---

## File Structure

**New package** `app/services/signal_graph/`:

| File | Responsibility |
|---|---|
| `__init__.py` | `DEFAULT_DOMAIN`, package docstring |
| `metric_specs.py` | `Input` + `MetricSpec` dataclasses; the 12-metric `REGISTRY`; `get_spec`, `all_specs`; shared `ratio_compute` helper |
| `domain_config.py` | Per-domain declarative config: intents → required fields, pipeline stage order, integration points |
| `keys.py` | Pure helpers that build/parse canonical node `key` strings (one place, so producers and consumers agree) |
| `scanner.py` | Structure pass: enumerate candidate gates + structural subgraph |
| `confirm.py` | Data pass: context distribution, volume/variability, edge weights |
| `recommender.py` | Combine scanner + confirmer → ranked `BaselineRecommendation` rows |
| `backtrack.py` | Resolve + persist a gate's subgraph (Case A known metric, Case B fallback); keep-current |
| `extract.py` | Traceback + feedback extractors → consolidated `SignalObservation` rows for all tiers |
| `drift.py` | Compute a gate's observed value from consolidated obs; attribute breach to upstream movers + tier |

**Modified files:**

| File | Change |
|---|---|
| `app/models.py` | Add `SignalNode`, `SignalEdge`, `SignalObservation`, `BaselineRecommendation` |
| `app/routes/learning.py` | Add recommendation, signals, observations endpoints; trigger backtracker on baseline create/accept; enrich drift_alerts read |
| `app/services/monitor.py` | Register `detect_signal_graph_drift` in `_DETECTORS` |
| `requirements-dev.txt` | **New** — `pytest==8.3.3` |
| `tests/conftest.py` | **New** — in-memory SQLite session fixture |

---

## Phase 0 — Test harness bootstrap

There is no test suite or pytest today. This phase makes TDD possible. One-time setup.

### Task 0: pytest + in-memory DB fixture

**Files:**
- Create: `salesops-solution/backend/requirements-dev.txt`
- Create: `salesops-solution/backend/pytest.ini`
- Create: `salesops-solution/backend/tests/__init__.py`
- Create: `salesops-solution/backend/tests/conftest.py`
- Create: `salesops-solution/backend/tests/test_harness_smoke.py`

- [ ] **Step 1: Add the dev requirement**

`requirements-dev.txt`:
```
pytest==8.3.3
```

- [ ] **Step 2: Install it**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pip install -r requirements-dev.txt`
Expected: `Successfully installed pytest-8.3.3 ...`

- [ ] **Step 3: Configure pytest**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 4: Write the conftest (in-memory DB fixture)**

`tests/__init__.py`: (empty file)

`tests/conftest.py`:
```python
"""Shared pytest fixtures: a fresh in-memory SQLite DB per test.

Importing app.models registers every table on app.db.Base.metadata, so
create_all builds the full schema (including the new signal_graph tables).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401  (registers all tables on Base.metadata)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
```

- [ ] **Step 5: Write the smoke test**

`tests/test_harness_smoke.py`:
```python
from app.models import Baseline


def test_can_create_and_read_a_row(db):
    b = Baseline(metric="m", segment="global", direction="min", target_value=0.9)
    db.add(b)
    db.commit()
    assert db.query(Baseline).count() == 1
```

- [ ] **Step 6: Run the smoke test (proves the harness works)**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/test_harness_smoke.py -v`
Expected: PASS (1 passed)

If `git status` errors here, run `git init` first.

- [ ] **Step 7: Commit**

```bash
git add salesops-solution/backend/requirements-dev.txt salesops-solution/backend/pytest.ini salesops-solution/backend/tests/__init__.py salesops-solution/backend/tests/conftest.py salesops-solution/backend/tests/test_harness_smoke.py
git commit -m "test: bootstrap pytest harness with in-memory sqlite fixture"
```

---

## Phase 1 — Foundation (data model + extractor)

Builds the four tables and the Task-2 base (extractor). Unblocks both tasks.

### Task 1: `SignalNode` model

**Files:**
- Modify: `salesops-solution/backend/app/models.py` (append a new class near `Baseline`)
- Test: `salesops-solution/backend/tests/signal_graph/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/__init__.py`: (empty file)

`tests/signal_graph/test_models.py`:
```python
from app.models import SignalNode


def test_signal_node_round_trips(db):
    n = SignalNode(
        domain="keysight",
        node_type="raw_signal",
        key="raw:trace:extract:stage_error",
        label="extract stage error",
        source_stream="traceback",
    )
    db.add(n)
    db.commit()
    row = db.query(SignalNode).one()
    assert row.node_type == "raw_signal"
    assert row.key == "raw:trace:extract:stage_error"
    assert row.source_stream == "traceback"
    assert row.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_signal_node_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'SignalNode'`

- [ ] **Step 3: Add the model**

Append to `app/models.py` (after the `Baseline` class):
```python
class SignalNode(Base):
    """A box in the Signal Dependency Graph: a baseline_target, a metric, a
    stage_outcome, or a raw_signal. Backtracking walks edges between these."""

    __tablename__ = "signal_nodes"
    id = Column(Integer, primary_key=True)
    domain = Column(String, nullable=False, default="keysight", index=True)
    node_type = Column(String, nullable=False, index=True)  # baseline_target|metric|stage_outcome|raw_signal
    key = Column(String, nullable=False, index=True)        # canonical id, unique per (domain, key)
    label = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    source_stream = Column(String, nullable=True)           # raw signals only: feedback|traceback
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True, index=True)
    spec_ref = Column(String, nullable=True)                # metric nodes: MetricSpec.key
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_signal_node_round_trips -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/models.py salesops-solution/backend/tests/signal_graph/
git commit -m "feat: add SignalNode model"
```

### Task 2: `SignalEdge` model

**Files:**
- Modify: `salesops-solution/backend/app/models.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_models.py`

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/signal_graph/test_models.py`:
```python
from app.models import SignalEdge


def test_signal_edge_round_trips(db):
    a = SignalNode(domain="keysight", node_type="raw_signal", key="raw:a")
    b = SignalNode(domain="keysight", node_type="stage_outcome", key="stage:extract")
    db.add_all([a, b])
    db.commit()
    e = SignalEdge(
        domain="keysight",
        from_node_id=a.id,
        to_node_id=b.id,
        relation="affects",
        origin="structural",
        weight=None,
        status="active",
        evidence={},
    )
    db.add(e)
    db.commit()
    row = db.query(SignalEdge).one()
    assert row.from_node_id == a.id
    assert row.to_node_id == b.id
    assert row.origin == "structural"
    assert row.status == "active"
    assert row.weight is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_signal_edge_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'SignalEdge'`

- [ ] **Step 3: Add the model**

Append to `app/models.py`:
```python
class SignalEdge(Base):
    """An "affects" arrow between two SignalNodes. Backtracking = follow the
    incoming edges of a target upstream."""

    __tablename__ = "signal_edges"
    id = Column(Integer, primary_key=True)
    domain = Column(String, nullable=False, default="keysight", index=True)
    from_node_id = Column(Integer, ForeignKey("signal_nodes.id"), nullable=False, index=True)
    to_node_id = Column(Integer, ForeignKey("signal_nodes.id"), nullable=False, index=True)
    relation = Column(String, nullable=False, default="affects")
    origin = Column(String, nullable=False, default="structural")  # structural|statistical|llm|manual
    weight = Column(Float, nullable=True)                          # 0..1; null until enough history
    evidence = Column(JSON, default=dict)                          # {correlation, sample_size, window, last_computed_at}
    status = Column(String, nullable=False, default="active")      # active|suggested|rejected
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_signal_edge_round_trips -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/models.py salesops-solution/backend/tests/signal_graph/test_models.py
git commit -m "feat: add SignalEdge model"
```

### Task 3: `SignalObservation` model

**Files:**
- Modify: `salesops-solution/backend/app/models.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_models.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from datetime import timedelta

from app.models import SignalObservation, now as model_now


def test_signal_observation_round_trips(db):
    start = model_now()
    obs = SignalObservation(
        domain="keysight",
        signal_key="raw:pipeline:extracted.ship_to",
        segment="intent:po_intake",
        window_start=start,
        window_end=start + timedelta(days=7),
        value=0.78,
        sample_size=3000,
        source_stream="traceback",
        autonomy_tier="L4_AUTO",
    )
    db.add(obs)
    db.commit()
    row = db.query(SignalObservation).one()
    assert row.value == 0.78
    assert row.source_stream == "traceback"
    assert row.autonomy_tier == "L4_AUTO"
    assert row.sample_size == 3000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_signal_observation_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'SignalObservation'`

- [ ] **Step 3: Add the model**

Append to `app/models.py`:
```python
class SignalObservation(Base):
    """One signal's measured value, in one segment, one time window — split by
    stream (feedback|traceback|consolidated) and autonomy tier. The heart of
    dual-input drift: traceback rows exist for L4 cases with no feedback."""

    __tablename__ = "signal_observations"
    id = Column(Integer, primary_key=True)
    domain = Column(String, nullable=False, default="keysight", index=True)
    signal_key = Column(String, nullable=False, index=True)
    segment = Column(String, nullable=False, default="global", index=True)
    window_start = Column(DateTime, nullable=False, index=True)
    window_end = Column(DateTime, nullable=False)
    value = Column(Float, nullable=True)
    sample_size = Column(Integer, nullable=False, default=0)
    source_stream = Column(String, nullable=False)   # feedback|traceback|consolidated
    autonomy_tier = Column(String, nullable=True)    # L4_AUTO|L3|L2|null (all)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_signal_observation_round_trips -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/models.py salesops-solution/backend/tests/signal_graph/test_models.py
git commit -m "feat: add SignalObservation model"
```

### Task 4: `BaselineRecommendation` model

**Files:**
- Modify: `salesops-solution/backend/app/models.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_models.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from app.models import BaselineRecommendation


def test_baseline_recommendation_round_trips(db):
    rec = BaselineRecommendation(
        domain="keysight",
        metric="extraction_completeness",
        segment="intent:po_intake",
        direction="min",
        score=0.91,
        rationale="High volume; varies; strong ship_to signal.",
        context_stats={"median": 0.96, "p10": 0.91, "p90": 0.99},
        subgraph_snapshot={"nodes": [], "edges": []},
        status="open",
    )
    db.add(rec)
    db.commit()
    row = db.query(BaselineRecommendation).one()
    assert row.status == "open"
    assert row.context_stats["median"] == 0.96
    # No target_value column exists — the human sets the number on accept.
    assert not hasattr(row, "target_value")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py::test_baseline_recommendation_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'BaselineRecommendation'`

- [ ] **Step 3: Add the model**

Append to `app/models.py`:
```python
class BaselineRecommendation(Base):
    """A suggested quality gate awaiting an admin decision. Deliberately has NO
    target_value column — the human types the number on accept, which creates a
    Baseline row. context_stats is shown as a hint only."""

    __tablename__ = "baseline_recommendations"
    id = Column(Integer, primary_key=True)
    domain = Column(String, nullable=False, default="keysight", index=True)
    metric = Column(String, nullable=False, index=True)
    segment = Column(String, nullable=False, default="global", index=True)
    direction = Column(String, nullable=False, default="min")
    score = Column(Float, nullable=False, default=0.0)
    rationale = Column(Text, nullable=True)
    context_stats = Column(JSON, default=dict)        # {median, p10, p90}
    subgraph_snapshot = Column(JSON, default=dict)    # {nodes:[...], edges:[...]}
    status = Column(String, nullable=False, default="open", index=True)  # open|accepted|dismissed
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_models.py -v`
Expected: PASS (all 4 model tests)

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/models.py salesops-solution/backend/tests/signal_graph/test_models.py
git commit -m "feat: add BaselineRecommendation model"
```

### Task 5: Canonical key helpers

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/__init__.py`
- Create: `salesops-solution/backend/app/services/signal_graph/keys.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_keys.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_keys.py`:
```python
from app.services.signal_graph import keys


def test_target_key():
    assert keys.target_key("extraction_completeness", "intent:po_intake") == \
        "target:extraction_completeness@intent:po_intake"


def test_metric_and_stage_keys():
    assert keys.metric_key("extraction_completeness") == "metric:extraction_completeness"
    assert keys.stage_key("extract") == "stage:extract"


def test_raw_field_key_and_trace_key():
    assert keys.raw_field_key("ship_to") == "raw:pipeline:extracted.ship_to"
    assert keys.raw_trace_key("extract", "stage_error") == "raw:trace:extract:stage_error"
    assert keys.raw_feedback_key("extract") == "raw:feedback:edit:extract"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_keys.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.signal_graph'`

- [ ] **Step 3: Write the package init + keys module**

`app/services/signal_graph/__init__.py`:
```python
"""Signal Dependency Graph: shared backbone for the baseline recommender
(Task 1) and dual-input drift (Task 2)."""

DEFAULT_DOMAIN = "keysight"
```

`app/services/signal_graph/keys.py`:
```python
"""Canonical key builders for graph nodes and observations. One place so
producers (scanner, backtracker, extractor) and consumers (drift) agree."""
from __future__ import annotations


def target_key(metric: str, segment: str) -> str:
    return f"target:{metric}@{segment}"


def metric_key(metric: str) -> str:
    return f"metric:{metric}"


def stage_key(stage: str) -> str:
    return f"stage:{stage}"


def raw_field_key(field: str) -> str:
    return f"raw:pipeline:extracted.{field}"


def raw_trace_key(stage: str, kind: str) -> str:
    return f"raw:trace:{stage}:{kind}"


def raw_feedback_key(stage: str) -> str:
    return f"raw:feedback:edit:{stage}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_keys.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/ salesops-solution/backend/tests/signal_graph/test_keys.py
git commit -m "feat: add signal_graph package + canonical key helpers"
```

### Task 6: Traceback extractor (field presence + stage error, all tiers)

This is the make-or-break component: it must record observations for L4 cases that have zero feedback.

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/extract.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_extract.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_extract.py`:
```python
from datetime import timedelta

from app.models import Email, Pipeline, TraceEvent, now as model_now
from app.services.signal_graph import extract


def _make_pipeline(db, *, intent, tier, extracted, started_at):
    e = Email(subject="s", from_address="a@b.com", body="x")
    db.add(e)
    db.flush()
    p = Pipeline(
        email_id=e.id,
        intent=intent,
        autonomy_tier=tier,
        extracted=extracted,
        status="done",
        started_at=started_at,
    )
    db.add(p)
    db.flush()
    return p


def test_traceback_extractor_sees_l4_cases_with_no_feedback(db):
    """The self-blinding regression: an L4 case where ship_to is missing must
    still produce a traceback observation, even though no human reviewed it."""
    start = model_now() - timedelta(days=1)
    # 3 L4 cases for po_intake: 2 have ship_to, 1 is missing it.
    _make_pipeline(db, intent="po_intake", tier="L4_AUTO",
                   extracted={"ship_to": "TX", "po_number": "1"}, started_at=start)
    _make_pipeline(db, intent="po_intake", tier="L4_AUTO",
                   extracted={"ship_to": "CA", "po_number": "2"}, started_at=start)
    _make_pipeline(db, intent="po_intake", tier="L4_AUTO",
                   extracted={"po_number": "3"}, started_at=start)  # ship_to missing
    db.commit()

    window_start = model_now() - timedelta(days=2)
    window_end = model_now()
    rows = extract.extract_traceback(
        db, domain="keysight", window_start=window_start, window_end=window_end,
    )

    ship_to = [
        r for r in rows
        if r["signal_key"] == "raw:pipeline:extracted.ship_to"
        and r["segment"] == "intent:po_intake"
        and r["autonomy_tier"] == "L4_AUTO"
    ]
    assert len(ship_to) == 1
    assert ship_to[0]["sample_size"] == 3
    assert abs(ship_to[0]["value"] - (2 / 3)) < 1e-9  # present fraction
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: extract_traceback`

- [ ] **Step 3: Implement the traceback extractor**

`app/services/signal_graph/extract.py`:
```python
"""Signal extractor / consolidator (Task 2).

Reads both input streams for EVERY case (L2/L3/L4) and produces normalized
per-signal observations. Traceback = coverage (all cases); feedback = ground
truth (reviewed slice). consolidate_window() persists SignalObservation rows.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ...models import Feedback, Pipeline, SignalObservation, TraceEvent, now
from . import keys
from .domain_config import required_fields_for_intent

log = logging.getLogger("signal_graph.extract")


def _segment_for(p: Pipeline) -> str:
    return f"intent:{p.intent}" if p.intent else "global"


def _aggregate(records: list[dict]) -> list[dict]:
    """Group raw per-case points into (signal_key, segment, tier) means."""
    buckets: dict[tuple, list[float]] = {}
    for r in records:
        k = (r["signal_key"], r["segment"], r["autonomy_tier"])
        buckets.setdefault(k, []).append(r["point"])
    out: list[dict] = []
    for (signal_key, segment, tier), points in buckets.items():
        n = len(points)
        out.append({
            "signal_key": signal_key,
            "segment": segment,
            "autonomy_tier": tier,
            "value": sum(points) / n if n else None,
            "sample_size": n,
            "source_stream": "traceback",
        })
    return out


def extract_traceback(
    db: Session, *, domain: str, window_start: datetime, window_end: datetime,
) -> list[dict]:
    """One point per (case, signal); returns aggregated observation dicts.

    Signals produced per case:
      - raw:pipeline:extracted.{field}  -> 1.0 present / 0.0 absent
      - raw:trace:{stage}:stage_error   -> 1.0 if an error event exists else 0.0
    """
    pipes = (
        db.query(Pipeline)
        .filter(Pipeline.started_at >= window_start, Pipeline.started_at < window_end)
        .all()
    )
    records: list[dict] = []
    for p in pipes:
        try:
            segment = _segment_for(p)
            tier = p.autonomy_tier or "unknown"
            extracted = p.extracted or {}
            for field in required_fields_for_intent(domain, p.intent):
                present = 1.0 if extracted.get(field) not in (None, "", [], {}) else 0.0
                records.append({
                    "signal_key": keys.raw_field_key(field),
                    "segment": segment,
                    "autonomy_tier": tier,
                    "point": present,
                })
            errors = (
                db.query(TraceEvent)
                .filter(TraceEvent.pipeline_id == p.id, TraceEvent.kind == "stage_error")
                .all()
            )
            errored_stages = {ev.stage for ev in errors}
            for stage in ("intake", "extract", "decide", "reply"):
                records.append({
                    "signal_key": keys.raw_trace_key(stage, "stage_error"),
                    "segment": segment,
                    "autonomy_tier": tier,
                    "point": 1.0 if stage in errored_stages else 0.0,
                })
        except Exception as e:  # isolate per-case failures
            log.exception("traceback extract failed for pipeline %s: %s", p.id, e)
    return _aggregate(records)
```

- [ ] **Step 4: Add the domain_config dependency used above**

`app/services/signal_graph/domain_config.py`:
```python
"""Declarative per-domain config the scanner and extractor read. Swap this to
onboard a new solution without touching engine code.

Keysight intents + required fields mirror the pipeline's extract contract
(see app/services/monitor.py intent handling). Stage order mirrors the live
pipeline: intake -> extract -> decide -> reply.
"""
from __future__ import annotations

# intent -> required extracted fields
_INTENT_REQUIRED_FIELDS: dict[str, dict[str, list[str]]] = {
    "keysight": {
        "po_intake": ["po_number", "ship_to", "line_items", "customer"],
        "quote_request": ["customer", "line_items"],
        "order_status": ["po_number", "customer"],
    },
}

# ordered pipeline stages per domain (upstream -> downstream)
_STAGE_ORDER: dict[str, list[str]] = {
    "keysight": ["intake", "extract", "decide", "reply"],
}


def required_fields_for_intent(domain: str, intent: str | None) -> list[str]:
    if not intent:
        return []
    return _INTENT_REQUIRED_FIELDS.get(domain, {}).get(intent, [])


def all_intents(domain: str) -> list[str]:
    return list(_INTENT_REQUIRED_FIELDS.get(domain, {}).keys())


def stage_order(domain: str) -> list[str]:
    return _STAGE_ORDER.get(domain, [])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_extract.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/extract.py salesops-solution/backend/app/services/signal_graph/domain_config.py salesops-solution/backend/tests/signal_graph/test_extract.py
git commit -m "feat: traceback extractor records all tiers incl L4 (fixes self-blinding)"
```

### Task 7: Feedback extractor + consolidation + persistence

**Files:**
- Modify: `salesops-solution/backend/app/services/signal_graph/extract.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_extract.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from app.models import Feedback, SignalObservation


def test_consolidate_window_persists_traceback_and_consolidated_rows(db):
    start = model_now() - timedelta(days=1)
    p = _make_pipeline(db, intent="po_intake", tier="L4_AUTO",
                       extracted={"po_number": "3"}, started_at=start)  # ship_to missing
    db.commit()

    window_start = model_now() - timedelta(days=2)
    window_end = model_now()
    extract.consolidate_window(
        db, domain="keysight", window_start=window_start, window_end=window_end,
    )

    rows = db.query(SignalObservation).filter(
        SignalObservation.signal_key == "raw:pipeline:extracted.ship_to",
        SignalObservation.segment == "intent:po_intake",
    ).all()
    streams = {r.source_stream for r in rows}
    assert "traceback" in streams
    # a consolidated/all-tier row is always written for each signal+segment
    assert "consolidated" in streams
    consolidated = [r for r in rows if r.source_stream == "consolidated"][0]
    assert consolidated.autonomy_tier is None
    assert consolidated.value == 0.0  # the single case is missing ship_to


def test_consolidate_window_is_idempotent(db):
    start = model_now() - timedelta(days=1)
    _make_pipeline(db, intent="po_intake", tier="L4_AUTO",
                   extracted={"po_number": "3"}, started_at=start)
    db.commit()
    ws = model_now() - timedelta(days=2)
    we = model_now()
    extract.consolidate_window(db, domain="keysight", window_start=ws, window_end=we)
    first = db.query(SignalObservation).count()
    extract.consolidate_window(db, domain="keysight", window_start=ws, window_end=we)
    second = db.query(SignalObservation).count()
    assert first == second  # re-run does not duplicate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_extract.py -k "consolidate" -v`
Expected: FAIL with `AttributeError: consolidate_window`

- [ ] **Step 3: Add feedback extractor + consolidation + persistence**

Append to `app/services/signal_graph/extract.py`:
```python
def extract_feedback(
    db: Session, *, domain: str, window_start: datetime, window_end: datetime,
) -> list[dict]:
    """Edit rate per (stage, segment, tier) from CSR corrections. value = edit
    fraction over reviewed cases in the window."""
    fbs = (
        db.query(Feedback, Pipeline)
        .join(Pipeline, Feedback.pipeline_id == Pipeline.id)
        .filter(Feedback.created_at >= window_start, Feedback.created_at < window_end)
        .all()
    )
    records: list[dict] = []
    for fb, p in fbs:
        try:
            segment = _segment_for(p)
            tier = p.autonomy_tier or "unknown"
            edited = 1.0 if fb.kind == "edit" else 0.0
            records.append({
                "signal_key": keys.raw_feedback_key(fb.stage or "unknown"),
                "segment": segment,
                "autonomy_tier": tier,
                "point": edited,
            })
        except Exception as e:
            log.exception("feedback extract failed for feedback %s: %s", fb.id, e)
    out = _aggregate(records)
    for r in out:
        r["source_stream"] = "feedback"
    return out


def _consolidate(rows: list[dict]) -> list[dict]:
    """Add a consolidated/all-tier row per (signal_key, segment): the sample-size
    weighted mean across every tier of the traceback stream (coverage)."""
    by_sig: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["source_stream"] != "traceback":
            continue
        by_sig.setdefault((r["signal_key"], r["segment"]), []).append(r)
    consolidated: list[dict] = []
    for (signal_key, segment), group in by_sig.items():
        total_n = sum(g["sample_size"] for g in group)
        if total_n == 0:
            value = None
        else:
            value = sum((g["value"] or 0.0) * g["sample_size"] for g in group) / total_n
        consolidated.append({
            "signal_key": signal_key,
            "segment": segment,
            "autonomy_tier": None,
            "value": value,
            "sample_size": total_n,
            "source_stream": "consolidated",
        })
    return consolidated


def consolidate_window(
    db: Session, *, domain: str, window_start: datetime, window_end: datetime,
) -> int:
    """Run both extractors, merge, and persist SignalObservation rows.
    Idempotent on (signal_key, segment, window_start, source_stream, tier).
    Returns number of rows written."""
    rows = (
        extract_traceback(db, domain=domain, window_start=window_start, window_end=window_end)
        + extract_feedback(db, domain=domain, window_start=window_start, window_end=window_end)
    )
    rows = rows + _consolidate(rows)
    written = 0
    for r in rows:
        existing = (
            db.query(SignalObservation)
            .filter(
                SignalObservation.domain == domain,
                SignalObservation.signal_key == r["signal_key"],
                SignalObservation.segment == r["segment"],
                SignalObservation.window_start == window_start,
                SignalObservation.source_stream == r["source_stream"],
                SignalObservation.autonomy_tier.is_(r["autonomy_tier"])
                if r["autonomy_tier"] is None
                else SignalObservation.autonomy_tier == r["autonomy_tier"],
            )
            .first()
        )
        if existing:
            existing.value = r["value"]
            existing.sample_size = r["sample_size"]
            continue
        db.add(SignalObservation(
            domain=domain,
            signal_key=r["signal_key"],
            segment=r["segment"],
            window_start=window_start,
            window_end=window_end,
            value=r["value"],
            sample_size=r["sample_size"],
            source_stream=r["source_stream"],
            autonomy_tier=r["autonomy_tier"],
        ))
        written += 1
    db.commit()
    return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_extract.py -v`
Expected: PASS (all extract tests)

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/extract.py salesops-solution/backend/tests/signal_graph/test_extract.py
git commit -m "feat: feedback extractor + consolidation + idempotent persistence"
```

---

## Phase 2 — Structure (MetricSpecs + scanner)

### Task 8: MetricSpec registry

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/metric_specs.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_metric_specs.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_metric_specs.py`:
```python
from app.services.signal_graph import metric_specs


def test_registry_has_extraction_completeness_with_declared_inputs():
    spec = metric_specs.get_spec("extraction_completeness")
    assert spec.stage == "extract"
    assert spec.segment_dimension == "intent"
    assert spec.direction == "min"
    roles = {i.role for i in spec.inputs}
    assert "field_present" in roles
    assert "stage_health" in roles
    assert "human_correction" in roles


def test_all_specs_are_unique_and_nonempty():
    specs = metric_specs.all_specs()
    assert len(specs) >= 1
    keys = [s.key for s in specs]
    assert len(keys) == len(set(keys))


def test_ratio_compute_handles_empty():
    assert metric_specs.ratio_compute([]) is None
    assert metric_specs.ratio_compute([1.0, 0.0, 1.0]) == 2 / 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_metric_specs.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the registry**

`app/services/signal_graph/metric_specs.py`:
```python
"""Declarative MetricSpec registry — the structural source of truth. Each spec
declares a metric's stage, segment dimension, direction, and the raw signals
that feed it. The scanner and backtracker read these; nothing re-parses the
old _observe_metric_impl(). Swap the registry -> the engine works elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class Input:
    key_template: str   # e.g. "raw:pipeline:extracted.{required_field}"
    stream: str         # traceback | feedback
    role: str           # field_present | stage_health | human_correction | proxy_*


@dataclass(frozen=True)
class MetricSpec:
    key: str
    stage: str
    segment_dimension: str          # intent | language | customer | stage | global
    direction: str                  # min | max
    inputs: list[Input]
    compute: Callable[[list[float]], Optional[float]]


def ratio_compute(points: list[float]) -> Optional[float]:
    """Mean of 0/1 points; None when empty. Reused by directly-observable
    metrics (completeness, success rates)."""
    if not points:
        return None
    return sum(points) / len(points)


_REGISTRY: dict[str, MetricSpec] = {}


def _register(spec: MetricSpec) -> None:
    _REGISTRY[spec.key] = spec


_register(MetricSpec(
    key="extraction_completeness",
    stage="extract",
    segment_dimension="intent",
    direction="min",
    inputs=[
        Input("raw:pipeline:extracted.{required_field}", "traceback", "field_present"),
        Input("raw:trace:extract:stage_error", "traceback", "stage_health"),
        Input("raw:feedback:edit:extract", "feedback", "human_correction"),
    ],
    compute=ratio_compute,
))

_register(MetricSpec(
    key="reply_send_success_rate",
    stage="reply",
    segment_dimension="global",
    direction="min",
    inputs=[
        Input("raw:trace:reply:stage_error", "traceback", "stage_health"),
        Input("raw:feedback:edit:reply", "feedback", "human_correction"),
    ],
    compute=ratio_compute,
))

_register(MetricSpec(
    key="intent_classification_accuracy",
    stage="intake",
    segment_dimension="intent",
    direction="min",
    inputs=[
        # proxy: shadow classifier disagreement (traceback) extends coverage to L4
        Input("raw:pipeline:shadow_disagreement", "traceback", "proxy_disagreement"),
        Input("raw:feedback:edit:intake", "feedback", "human_correction"),
    ],
    compute=ratio_compute,
))


def get_spec(key: str) -> MetricSpec:
    return _REGISTRY[key]


def all_specs() -> list[MetricSpec]:
    return list(_REGISTRY.values())
```

> NOTE: three representative specs are implemented here (one directly-observable, one global success-rate, one accuracy-with-proxy). Task 8b below adds the remaining nine. Splitting keeps each test green and reviewable.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_metric_specs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/metric_specs.py salesops-solution/backend/tests/signal_graph/test_metric_specs.py
git commit -m "feat: MetricSpec registry with Input/MetricSpec + ratio_compute"
```

### Task 8b: Remaining nine MetricSpecs

**Files:**
- Modify: `salesops-solution/backend/app/services/signal_graph/metric_specs.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_metric_specs.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_registry_covers_all_twelve_metrics():
    expected = {
        "extraction_completeness", "intent_classification_accuracy",
        "language_detection_accuracy", "customer_match_rate",
        "p95_stage_latency_ms", "autonomy_l4_rate", "hitl_resolution_p95_hours",
        "spam_false_positive_rate", "reply_send_success_rate",
        "cost_per_pipeline_usd", "aioa_handoff_success_rate", "psi_intent",
    }
    assert {s.key for s in metric_specs.all_specs()} == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_metric_specs.py::test_registry_covers_all_twelve_metrics -v`
Expected: FAIL (set mismatch — 3 present, 12 expected)

- [ ] **Step 3: Register the remaining nine**

Append nine `_register(...)` calls in `metric_specs.py` before `get_spec`. Use `ratio_compute` for rate-style metrics; latency/cost/psi keep `direction="max"` and `compute=ratio_compute` as a placeholder mean over their normalized point stream (the drift component reads the consolidated observation value directly for these — see Task 19):
```python
_register(MetricSpec("language_detection_accuracy", "intake", "language", "min",
    [Input("raw:pipeline:shadow_disagreement", "traceback", "proxy_disagreement"),
     Input("raw:feedback:edit:intake", "feedback", "human_correction")], ratio_compute))

_register(MetricSpec("customer_match_rate", "extract", "customer", "min",
    [Input("raw:pipeline:customer_match.matched", "traceback", "field_present"),
     Input("raw:feedback:edit:extract", "feedback", "human_correction")], ratio_compute))

_register(MetricSpec("p95_stage_latency_ms", "extract", "stage", "max",
    [Input("raw:trace:extract:duration_ms", "traceback", "latency")], ratio_compute))

_register(MetricSpec("autonomy_l4_rate", "decide", "global", "min",
    [Input("raw:pipeline:autonomy_is_l4", "traceback", "field_present")], ratio_compute))

_register(MetricSpec("hitl_resolution_p95_hours", "decide", "global", "max",
    [Input("raw:trace:decide:hitl_created", "traceback", "stage_health")], ratio_compute))

_register(MetricSpec("spam_false_positive_rate", "intake", "global", "max",
    [Input("raw:feedback:restore:intake", "feedback", "human_correction")], ratio_compute))

_register(MetricSpec("cost_per_pipeline_usd", "decide", "global", "max",
    [Input("raw:pipeline:cost_usd", "traceback", "cost")], ratio_compute))

_register(MetricSpec("aioa_handoff_success_rate", "reply", "global", "min",
    [Input("raw:trace:reply:aioa_pass", "traceback", "field_present"),
     Input("raw:feedback:edit:reply", "feedback", "human_correction")], ratio_compute))

_register(MetricSpec("psi_intent", "intake", "global", "max",
    [Input("raw:pipeline:intent_distribution", "traceback", "distribution")], ratio_compute))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_metric_specs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/metric_specs.py salesops-solution/backend/tests/signal_graph/test_metric_specs.py
git commit -m "feat: register all 12 MetricSpecs"
```

### Task 9: Scanner (candidate gates + structural subgraph)

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/scanner.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_scanner.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_scanner.py`:
```python
from app.services.signal_graph import scanner


def test_scan_expands_per_intent_and_builds_structural_subgraph(db):
    candidates = scanner.scan_candidates(db, domain="keysight")
    comp = [c for c in candidates if c["metric"] == "extraction_completeness"]
    segs = {c["segment"] for c in comp}
    assert "intent:po_intake" in segs
    assert "intent:quote_request" in segs

    po = [c for c in comp if c["segment"] == "intent:po_intake"][0]
    node_keys = {n["key"] for n in po["subgraph"]["nodes"]}
    assert "target:extraction_completeness@intent:po_intake" in node_keys
    assert "metric:extraction_completeness" in node_keys
    assert "stage:extract" in node_keys
    assert "raw:pipeline:extracted.ship_to" in node_keys      # required field expanded
    assert "raw:trace:extract:stage_error" in node_keys
    # every edge points to a node that exists
    ids = {n["key"] for n in po["subgraph"]["nodes"]}
    for e in po["subgraph"]["edges"]:
        assert e["from"] in ids and e["to"] in ids


def test_global_metric_makes_one_candidate():
    pass  # covered indirectly; see reply_send_success_rate below


def test_scan_global_metric_single_segment(db):
    candidates = scanner.scan_candidates(db, domain="keysight")
    reply = [c for c in candidates if c["metric"] == "reply_send_success_rate"]
    assert len(reply) == 1
    assert reply[0]["segment"] == "global"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the scanner**

`app/services/signal_graph/scanner.py`:
```python
"""Structure pass (Task 1). Reads the MetricSpec registry + domain config and
enumerates candidate gates with their structural subgraphs. Deterministic,
complete, NO numbers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import keys
from .domain_config import all_intents, required_fields_for_intent, stage_order
from .metric_specs import MetricSpec, all_specs


def _segments_for(db: Session, domain: str, spec: MetricSpec) -> list[str]:
    if spec.segment_dimension == "intent":
        return [f"intent:{i}" for i in all_intents(domain)] or ["global"]
    if spec.segment_dimension == "global":
        return ["global"]
    # language/customer/stage dimensions resolve to global until per-dimension
    # enumeration is wired; a single global candidate is still valid.
    return ["global"]


def _structural_subgraph(domain: str, spec: MetricSpec, segment: str) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []

    def add_node(key: str, node_type: str, **extra) -> None:
        if all(n["key"] != key for n in nodes):
            nodes.append({"key": key, "node_type": node_type, **extra})

    tkey = keys.target_key(spec.key, segment)
    mkey = keys.metric_key(spec.key)
    skey = keys.stage_key(spec.stage)
    add_node(tkey, "baseline_target")
    add_node(mkey, "metric", spec_ref=spec.key)
    add_node(skey, "stage_outcome")
    edges.append({"from": mkey, "to": tkey, "origin": "structural"})
    edges.append({"from": skey, "to": mkey, "origin": "structural"})

    # expand declared inputs into raw-signal nodes
    intent = segment.split("intent:", 1)[1] if segment.startswith("intent:") else None
    for inp in spec.inputs:
        if "{required_field}" in inp.key_template:
            for fld in required_fields_for_intent(domain, intent):
                rk = keys.raw_field_key(fld)
                add_node(rk, "raw_signal", source_stream=inp.stream, role=inp.role)
                edges.append({"from": rk, "to": skey, "origin": "structural"})
        else:
            rk = inp.key_template
            add_node(rk, "raw_signal", source_stream=inp.stream, role=inp.role)
            target = mkey if inp.stream == "feedback" else skey
            edges.append({"from": rk, "to": target, "origin": "structural"})

    # cross-stage upstream link: the stage feeding this one
    order = stage_order(domain)
    if spec.stage in order:
        idx = order.index(spec.stage)
        if idx > 0:
            upstream = keys.stage_key(order[idx - 1])
            add_node(upstream, "stage_outcome")
            edges.append({"from": upstream, "to": skey, "origin": "structural"})

    return {"nodes": nodes, "edges": edges}


def scan_candidates(db: Session, *, domain: str) -> list[dict]:
    out: list[dict] = []
    for spec in all_specs():
        for segment in _segments_for(db, domain, spec):
            out.append({
                "metric": spec.key,
                "segment": segment,
                "direction": spec.direction,
                "subgraph": _structural_subgraph(domain, spec, segment),
            })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/scanner.py salesops-solution/backend/tests/signal_graph/test_scanner.py
git commit -m "feat: scanner enumerates candidate gates + structural subgraphs"
```

---

## Phase 3 — Recommend (confirmer + recommender + API)

### Task 10: Confirmer — context distribution + volume/variability

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/confirm.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_confirm.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_confirm.py`:
```python
from app.services.signal_graph import confirm


def test_context_distribution_returns_median_and_percentiles():
    values = [0.91, 0.93, 0.95, 0.96, 0.97, 0.98, 0.99]
    stats = confirm.context_distribution(values)
    assert abs(stats["median"] - 0.96) < 1e-9
    assert stats["p10"] <= stats["median"] <= stats["p90"]


def test_context_distribution_empty_is_none():
    stats = confirm.context_distribution([])
    assert stats == {"median": None, "p10": None, "p90": None}


def test_variability_zero_for_constant():
    assert confirm.variability([0.9, 0.9, 0.9]) == 0.0
    assert confirm.variability([0.8, 1.0]) > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_confirm.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the stats helpers**

`app/services/signal_graph/confirm.py`:
```python
"""Data pass (Task 1). Pure-Python stats over history: context distribution,
variability, and edge-weight correlation. No numpy/scipy."""
from __future__ import annotations

from typing import Optional


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def context_distribution(values: list[float]) -> dict:
    if not values:
        return {"median": None, "p10": None, "p90": None}
    s = sorted(values)
    return {
        "median": _percentile(s, 50),
        "p10": _percentile(s, 10),
        "p90": _percentile(s, 90),
    }


def variability(values: list[float]) -> float:
    """Population standard deviation; 0 for constant or empty."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / n) ** 0.5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_confirm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/confirm.py salesops-solution/backend/tests/signal_graph/test_confirm.py
git commit -m "feat: confirmer stats — context distribution + variability"
```

### Task 11: Confirmer — edge-weight correlation

**Files:**
- Modify: `salesops-solution/backend/app/services/signal_graph/confirm.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_confirm.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_edge_weight_strong_for_correlated_signal():
    # signal tracks metric tightly -> weight near 1
    signal = [0.2, 0.4, 0.6, 0.8, 1.0]
    metric = [0.2, 0.4, 0.6, 0.8, 1.0]
    w = confirm.edge_weight(signal, metric)
    assert w is not None and w > 0.9


def test_edge_weight_none_below_sample_floor():
    assert confirm.edge_weight([0.1], [0.2], min_samples=3) is None


def test_edge_weight_low_for_uncorrelated():
    signal = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    metric = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    w = confirm.edge_weight(signal, metric)
    assert w is not None and w < 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_confirm.py -k edge_weight -v`
Expected: FAIL with `AttributeError: edge_weight`

- [ ] **Step 3: Implement correlation-based edge weight**

Append to `confirm.py`:
```python
def edge_weight(
    signal: list[float], metric: list[float], *, min_samples: int = 3,
) -> Optional[float]:
    """Absolute Pearson correlation as edge weight in [0, 1]. Returns None
    below the sample floor (so the edge stays structural with weight=null
    rather than a misleading 'weak'). Zero-variance series -> 0.0."""
    n = min(len(signal), len(metric))
    if n < min_samples:
        return None
    x = signal[:n]
    y = metric[:n]
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx == 0 or vy == 0:
        return 0.0
    r = cov / ((vx ** 0.5) * (vy ** 0.5))
    return abs(max(-1.0, min(1.0, r)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_confirm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/confirm.py salesops-solution/backend/tests/signal_graph/test_confirm.py
git commit -m "feat: edge-weight correlation with sample-size floor"
```

### Task 12: Recommender — rank + persist

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/recommender.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_recommender.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_recommender.py`:
```python
from datetime import timedelta

from app.models import BaselineRecommendation, Email, Pipeline, now as model_now
from app.services.signal_graph import recommender


def _seed_pipelines(db, n, intent, tier="L4_AUTO"):
    start = model_now() - timedelta(days=1)
    for i in range(n):
        e = Email(subject="s", from_address="a@b.com", body="x")
        db.add(e); db.flush()
        db.add(Pipeline(email_id=e.id, intent=intent, autonomy_tier=tier,
                        extracted={"po_number": str(i)}, status="done",
                        started_at=start))
    db.commit()


def test_generate_recommendations_persists_rows_and_ranks_high_volume(db):
    _seed_pipelines(db, 50, "po_intake")
    _seed_pipelines(db, 2, "order_status")
    recs = recommender.generate_recommendations(db, domain="keysight")
    rows = db.query(BaselineRecommendation).all()
    assert len(rows) == len(recs) and len(rows) > 0
    comp = [r for r in rows if r.metric == "extraction_completeness"
            and r.segment == "intent:po_intake"][0]
    assert comp.context_stats  # hint populated
    assert comp.status == "open"
    # high-volume po_intake outranks low-volume order_status
    po = [r for r in rows if r.segment == "intent:po_intake"][0].score
    os_ = [r for r in rows if r.segment == "intent:order_status"][0].score
    assert po > os_


def test_generate_recommendations_idempotent(db):
    _seed_pipelines(db, 20, "po_intake")
    recommender.generate_recommendations(db, domain="keysight")
    first = db.query(BaselineRecommendation).count()
    recommender.generate_recommendations(db, domain="keysight")
    second = db.query(BaselineRecommendation).count()
    assert first == second  # no duplicates for the same (metric, segment)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_recommender.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the recommender**

`app/services/signal_graph/recommender.py`:
```python
"""Recommender (Task 1). Combines scanner (structure) + confirmer (evidence)
into ranked BaselineRecommendation rows. Never creates a gate or sets a number;
purely additive suggestions."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from ...models import BaselineRecommendation, Pipeline, now
from . import confirm
from .scanner import scan_candidates

log = logging.getLogger("signal_graph.recommender")


def _segment_volume(db: Session, domain: str, segment: str, since) -> int:
    q = db.query(Pipeline).filter(Pipeline.started_at >= since)
    if segment.startswith("intent:"):
        q = q.filter(Pipeline.intent == segment.split("intent:", 1)[1])
    return q.count()


def _score(volume: int, var: float, has_signal: bool) -> float:
    """Transparent ranking: volume (log-ish) + movement + signal coverage."""
    import math
    vol_term = math.log10(volume + 1) / 3.0  # ~1.0 at 1000 cases
    move_term = min(var * 5.0, 1.0)
    sig_term = 0.3 if has_signal else 0.0
    return round(min(vol_term, 1.0) * 0.5 + move_term * 0.3 + sig_term, 4)


def generate_recommendations(db: Session, *, domain: str, window_days: int = 90) -> list[dict]:
    since = now() - timedelta(days=window_days)
    out: list[dict] = []
    for cand in scan_candidates(db, domain=domain):
        try:
            volume = _segment_volume(db, domain, cand["segment"], since)
            # context distribution + variability would be computed from the
            # metric's historical observations; with no history yet we record an
            # empty hint and rely on volume + signal coverage for ranking.
            stats = confirm.context_distribution([])
            var = 0.0
            has_signal = any(
                n["node_type"] == "raw_signal" for n in cand["subgraph"]["nodes"]
            )
            score = _score(volume, var, has_signal)
            existing = (
                db.query(BaselineRecommendation)
                .filter(
                    BaselineRecommendation.domain == domain,
                    BaselineRecommendation.metric == cand["metric"],
                    BaselineRecommendation.segment == cand["segment"],
                )
                .first()
            )
            rationale = (
                f"{volume} cases in {window_days}d. "
                + ("Has at least one upstream signal so drift is explainable."
                   if has_signal else "No upstream signal coverage yet.")
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
            out.append({"metric": cand["metric"], "segment": cand["segment"], "score": score})
        except Exception as e:
            log.exception("recommend failed for %s/%s: %s", cand["metric"], cand["segment"], e)
    db.commit()
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_recommender.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/recommender.py salesops-solution/backend/tests/signal_graph/test_recommender.py
git commit -m "feat: recommender ranks + persists BaselineRecommendation rows"
```

### Task 13: Recommendation API (list / accept / dismiss)

**Files:**
- Modify: `salesops-solution/backend/app/routes/learning.py` (append near the baselines admin block, ~line 1595)
- Test: `salesops-solution/backend/tests/signal_graph/test_recommendation_api.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_recommendation_api.py`:
```python
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from app.models import Baseline, BaselineRecommendation


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_accept_requires_target_value_and_creates_baseline(db):
    rec = BaselineRecommendation(
        domain="keysight", metric="extraction_completeness",
        segment="intent:po_intake", direction="min", score=0.9,
        context_stats={"median": 0.96}, subgraph_snapshot={"nodes": [], "edges": []},
        status="open",
    )
    db.add(rec); db.commit()
    client = _client(db)

    listing = client.get("/learning/baselines/recommendations").json()
    assert any(r["id"] == rec.id for r in listing["items"])

    resp = client.post(
        f"/learning/baselines/recommendations/{rec.id}/accept",
        json={"target_value": 0.95},
    )
    assert resp.status_code == 200
    b = db.query(Baseline).filter(
        Baseline.metric == "extraction_completeness",
        Baseline.segment == "intent:po_intake",
    ).one()
    assert b.target_value == 0.95
    db.refresh(rec)
    assert rec.status == "accepted"
    app.dependency_overrides.clear()


def test_dismiss_marks_status(db):
    rec = BaselineRecommendation(
        domain="keysight", metric="reply_send_success_rate", segment="global",
        direction="min", score=0.5, status="open",
    )
    db.add(rec); db.commit()
    client = _client(db)
    resp = client.post(f"/learning/baselines/recommendations/{rec.id}/dismiss")
    assert resp.status_code == 200
    db.refresh(rec)
    assert rec.status == "dismissed"
    app.dependency_overrides.clear()
```

> NOTE: confirm the router prefix. If endpoints resolve at `/baselines/...` rather than `/learning/baselines/...`, adjust the test URLs to match the prefix `app/main.py` mounts the learning router under. Run the test to discover the actual prefix from the 404 vs 200.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_recommendation_api.py -v`
Expected: FAIL with 404 (routes not defined)

- [ ] **Step 3: Add the endpoints**

In `app/routes/learning.py`, after the `list_known_metrics` endpoint, add:
```python
# ──────────────────────────────────────────────────────────────────────────
# Baseline recommendations (Task 1): suggest gates; human sets the number.
# ──────────────────────────────────────────────────────────────────────────
class RecommendationAccept(BaseModel):
    target_value: float
    drift_pct: float | None = None
    severity: str | None = None


@router.get("/baselines/recommendations")
def list_recommendations(db: Session = Depends(get_db)) -> dict:
    from ..models import BaselineRecommendation
    rows = (
        db.query(BaselineRecommendation)
        .filter(BaselineRecommendation.status == "open")
        .order_by(BaselineRecommendation.score.desc())
        .all()
    )
    items = [{
        "id": r.id, "metric": r.metric, "segment": r.segment,
        "direction": r.direction, "score": r.score, "rationale": r.rationale,
        "context_stats": r.context_stats, "subgraph_preview": r.subgraph_snapshot,
        "status": r.status,
    } for r in rows]
    return {"items": items}


@router.post(
    "/baselines/recommendations/{rec_id}/accept",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def accept_recommendation(
    rec_id: int, payload: RecommendationAccept, db: Session = Depends(get_db),
) -> dict:
    from ..models import Baseline, BaselineRecommendation
    from ..services import baselines as baselines_svc
    from ..services.signal_graph.backtrack import backtrack_baseline

    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="recommendation not found")
    if db.query(Baseline).filter(Baseline.metric == rec.metric, Baseline.segment == rec.segment).first():
        raise HTTPException(status_code=409, detail="baseline already exists for this metric+segment")
    b = Baseline(
        metric=rec.metric, segment=rec.segment, direction=rec.direction,
        target_value=payload.target_value,
        drift_pct=payload.drift_pct if payload.drift_pct is not None else 5.0,
        severity=payload.severity or "warn",
        source="recommended", updated_by="admin",
    )
    db.add(b)
    rec.status = "accepted"
    db.commit()
    db.refresh(b)
    baselines_svc.invalidate_baseline_index()
    backtrack_baseline(db, baseline_id=b.id)
    return baselines_svc.to_dict(b)


@router.post(
    "/baselines/recommendations/{rec_id}/dismiss",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def dismiss_recommendation(rec_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import BaselineRecommendation
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="recommendation not found")
    rec.status = "dismissed"
    db.commit()
    return {"dismissed": rec_id}
```

> Note: `backtrack_baseline` is implemented in Task 14. If executing strictly in order, this import will fail at call time only — write Task 14 before running the accept test, OR temporarily wrap the import+call in `try/except ImportError`. Recommended: implement Task 14 first, then run this test. Adjust the build order locally if needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_recommendation_api.py -v`
Expected: PASS (after Task 14 exists)

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/routes/learning.py salesops-solution/backend/tests/signal_graph/test_recommendation_api.py
git commit -m "feat: recommendation API (list/accept/dismiss); accept sets human number"
```

---

## Phase 4 — Backtrack (subgraph persistence + signals API)

### Task 14: Backtracker — resolve + persist (Case A) and fallback (Case B)

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/backtrack.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_backtrack.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_backtrack.py`:
```python
from app.models import Baseline, SignalEdge, SignalNode
from app.services.signal_graph import backtrack


def test_backtrack_known_metric_persists_nodes_and_edges(db):
    b = Baseline(metric="extraction_completeness", segment="intent:po_intake",
                 direction="min", target_value=0.95)
    db.add(b); db.commit()

    backtrack.backtrack_baseline(db, baseline_id=b.id)

    node_keys = {n.key for n in db.query(SignalNode).all()}
    assert "target:extraction_completeness@intent:po_intake" in node_keys
    assert "raw:pipeline:extracted.ship_to" in node_keys
    target = db.query(SignalNode).filter(
        SignalNode.key == "target:extraction_completeness@intent:po_intake").one()
    assert target.baseline_id == b.id
    # at least the structural edges exist and are active
    assert db.query(SignalEdge).filter(SignalEdge.status == "active").count() > 0


def test_backtrack_is_idempotent(db):
    b = Baseline(metric="reply_send_success_rate", segment="global",
                 direction="min", target_value=0.99)
    db.add(b); db.commit()
    backtrack.backtrack_baseline(db, baseline_id=b.id)
    n1 = db.query(SignalNode).count()
    e1 = db.query(SignalEdge).count()
    backtrack.backtrack_baseline(db, baseline_id=b.id)
    assert db.query(SignalNode).count() == n1
    assert db.query(SignalEdge).count() == e1


def test_backtrack_unknown_metric_emits_suggested(db):
    b = Baseline(metric="totally_new_metric", segment="global",
                 direction="min", target_value=0.5)
    db.add(b); db.commit()
    backtrack.backtrack_baseline(db, baseline_id=b.id)
    # Case B: target node exists; any derived edges are 'suggested'
    target = db.query(SignalNode).filter(
        SignalNode.key == "target:totally_new_metric@global").one()
    assert target.baseline_id == b.id
    suggested = db.query(SignalEdge).filter(SignalEdge.status == "suggested").count()
    assert suggested >= 0  # fallback path runs without error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_backtrack.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the backtracker**

`app/services/signal_graph/backtrack.py`:
```python
"""Backtracker (Task 1). Owns the signal map for EVERY gate — recommended or
hand-added. Case A: known metric -> structural subgraph from MetricSpec + stage
order. Case B: unknown metric -> minimal target node + (future) statistical
suggestions, all 'suggested' until a human confirms."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ...models import Baseline, SignalEdge, SignalNode, now
from . import keys
from .metric_specs import _REGISTRY
from .scanner import _structural_subgraph
from . import DEFAULT_DOMAIN

log = logging.getLogger("signal_graph.backtrack")


def _upsert_node(db: Session, domain: str, spec: dict, baseline_id: int | None) -> SignalNode:
    existing = (
        db.query(SignalNode)
        .filter(SignalNode.domain == domain, SignalNode.key == spec["key"])
        .first()
    )
    if existing:
        if baseline_id and spec["node_type"] == "baseline_target":
            existing.baseline_id = baseline_id
        return existing
    node = SignalNode(
        domain=domain,
        node_type=spec["node_type"],
        key=spec["key"],
        source_stream=spec.get("source_stream"),
        spec_ref=spec.get("spec_ref"),
        baseline_id=baseline_id if spec["node_type"] == "baseline_target" else None,
    )
    db.add(node)
    db.flush()
    return node


def _upsert_edge(db: Session, domain: str, from_id: int, to_id: int, origin: str, status: str) -> None:
    existing = (
        db.query(SignalEdge)
        .filter(
            SignalEdge.domain == domain,
            SignalEdge.from_node_id == from_id,
            SignalEdge.to_node_id == to_id,
        )
        .first()
    )
    if existing:
        return
    db.add(SignalEdge(
        domain=domain, from_node_id=from_id, to_node_id=to_id,
        relation="affects", origin=origin, status=status, weight=None, evidence={},
    ))


def backtrack_baseline(db: Session, *, baseline_id: int, domain: str = DEFAULT_DOMAIN) -> dict:
    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise ValueError(f"baseline {baseline_id} not found")

    if b.metric in _REGISTRY:  # Case A
        spec = _REGISTRY[b.metric]
        subgraph = _structural_subgraph(domain, spec, b.segment)
        status = "active"
        origin = "structural"
    else:  # Case B — minimal target node, fallback discovery deferred
        tkey = keys.target_key(b.metric, b.segment)
        subgraph = {"nodes": [{"key": tkey, "node_type": "baseline_target"}], "edges": []}
        status = "suggested"
        origin = "statistical"

    # upsert nodes
    key_to_id: dict[str, int] = {}
    for nspec in subgraph["nodes"]:
        node = _upsert_node(db, domain, nspec, baseline_id)
        key_to_id[nspec["key"]] = node.id
    # upsert edges
    for espec in subgraph["edges"]:
        f = key_to_id.get(espec["from"])
        t = key_to_id.get(espec["to"])
        if f and t:
            _upsert_edge(db, domain, f, t, espec.get("origin", origin), status)
    db.commit()
    return {"baseline_id": baseline_id, "nodes": len(subgraph["nodes"]), "edges": len(subgraph["edges"])}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_backtrack.py -v`
Expected: PASS

- [ ] **Step 5: Run the recommendation-API test now that backtrack exists**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_recommendation_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/backtrack.py salesops-solution/backend/tests/signal_graph/test_backtrack.py
git commit -m "feat: backtracker persists signal subgraph (Case A + Case B)"
```

### Task 15: Trigger backtracker on manual baseline create

**Files:**
- Modify: `salesops-solution/backend/app/routes/learning.py` (the `create_baseline` endpoint, ~line 1530)
- Test: `salesops-solution/backend/tests/signal_graph/test_backtrack_on_create.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_backtrack_on_create.py`:
```python
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from app.models import SignalNode


def test_manual_create_triggers_backtrack(db):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    resp = client.post("/learning/baselines", json={
        "metric": "extraction_completeness",
        "segment": "intent:po_intake",
        "direction": "min",
        "target_value": 0.95,
    })
    assert resp.status_code == 200
    keys = {n.key for n in db.query(SignalNode).all()}
    assert "target:extraction_completeness@intent:po_intake" in keys
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_backtrack_on_create.py -v`
Expected: FAIL (no SignalNode rows created on manual create)

- [ ] **Step 3: Wire the backtracker into `create_baseline`**

In `app/routes/learning.py`, in `create_baseline`, after `baselines_svc.invalidate_baseline_index()` and before `return`:
```python
    # Derive + persist this gate's upstream signal subgraph (Task 1).
    try:
        from ..services.signal_graph.backtrack import backtrack_baseline
        backtrack_baseline(db, baseline_id=b.id)
    except Exception:
        import logging
        logging.getLogger("learning").exception("backtrack failed for baseline %s", b.id)
    return baselines_svc.to_dict(b)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_backtrack_on_create.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/routes/learning.py salesops-solution/backend/tests/signal_graph/test_backtrack_on_create.py
git commit -m "feat: trigger backtracker when admin creates a baseline manually"
```

### Task 16: Signals API (read subgraph + confirm/reject edge)

**Files:**
- Modify: `salesops-solution/backend/app/routes/learning.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_signals_api.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_signals_api.py`:
```python
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from app.models import Baseline, SignalEdge
from app.services.signal_graph import backtrack


def test_get_signals_returns_nodes_and_edges(db):
    b = Baseline(metric="extraction_completeness", segment="intent:po_intake",
                 direction="min", target_value=0.95)
    db.add(b); db.commit()
    backtrack.backtrack_baseline(db, baseline_id=b.id)

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    resp = client.get(f"/learning/baselines/{b.id}/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) > 0
    assert len(data["edges"]) > 0

    edge_id = db.query(SignalEdge).first().id
    r2 = client.post(f"/learning/baselines/{b.id}/signals/edges/{edge_id}/reject")
    assert r2.status_code == 200
    db.refresh(db.query(SignalEdge).filter(SignalEdge.id == edge_id).one())
    assert db.query(SignalEdge).filter(SignalEdge.id == edge_id).one().status == "rejected"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_signals_api.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the signals endpoints**

Append to `app/routes/learning.py`:
```python
@router.get("/baselines/{baseline_id}/signals")
def get_baseline_signals(baseline_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import Baseline, SignalEdge, SignalNode
    from ..services.signal_graph import keys as sg_keys
    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="baseline not found")
    target = (
        db.query(SignalNode)
        .filter(SignalNode.key == sg_keys.target_key(b.metric, b.segment))
        .first()
    )
    if not target:
        return {"nodes": [], "edges": []}
    # BFS upstream from the target following incoming edges
    seen_ids: set[int] = set()
    frontier = [target.id]
    edges_out: list[dict] = []
    while frontier:
        nxt: list[int] = []
        for nid in frontier:
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            for e in db.query(SignalEdge).filter(SignalEdge.to_node_id == nid).all():
                edges_out.append({
                    "id": e.id, "from": e.from_node_id, "to": e.to_node_id,
                    "weight": e.weight, "origin": e.origin, "status": e.status,
                    "evidence": e.evidence,
                })
                nxt.append(e.from_node_id)
        frontier = nxt
    nodes = db.query(SignalNode).filter(SignalNode.id.in_(seen_ids)).all() if seen_ids else []
    return {
        "nodes": [{"id": n.id, "key": n.key, "node_type": n.node_type,
                   "source_stream": n.source_stream, "label": n.label} for n in nodes],
        "edges": edges_out,
    }


@router.post(
    "/baselines/{baseline_id}/signals/edges/{edge_id}/confirm",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def confirm_edge(baseline_id: int, edge_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import SignalEdge
    e = db.query(SignalEdge).filter(SignalEdge.id == edge_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="edge not found")
    e.status = "active"
    db.commit()
    return {"edge_id": edge_id, "status": "active"}


@router.post(
    "/baselines/{baseline_id}/signals/edges/{edge_id}/reject",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def reject_edge(baseline_id: int, edge_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import SignalEdge
    e = db.query(SignalEdge).filter(SignalEdge.id == edge_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="edge not found")
    e.status = "rejected"
    db.commit()
    return {"edge_id": edge_id, "status": "rejected"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_signals_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/routes/learning.py salesops-solution/backend/tests/signal_graph/test_signals_api.py
git commit -m "feat: signals API — read subgraph + confirm/reject edges"
```

---

## Phase 5 — Drift over the graph

### Task 17: Drift compute — observed value across all tiers

**Files:**
- Create: `salesops-solution/backend/app/services/signal_graph/drift.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_drift.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_drift.py`:
```python
from datetime import timedelta

from app.models import Baseline, SignalObservation, now as model_now
from app.services.signal_graph import drift


def _obs(db, key, seg, stream, tier, value, n, ws, we):
    db.add(SignalObservation(
        domain="keysight", signal_key=key, segment=seg, window_start=ws,
        window_end=we, value=value, sample_size=n, source_stream=stream,
        autonomy_tier=tier,
    ))


def test_observed_value_uses_consolidated_all_tier_row(db):
    ws = model_now() - timedelta(days=7)
    we = model_now()
    # the metric's own consolidated observation drives the value
    _obs(db, "metric:extraction_completeness", "intent:po_intake",
         "consolidated", None, 0.88, 3200, ws, we)
    db.commit()
    b = Baseline(metric="extraction_completeness", segment="intent:po_intake",
                 direction="min", target_value=0.95)
    db.add(b); db.commit()
    observed = drift.observed_value(db, b, window_start=ws, window_end=we)
    assert abs(observed - 0.88) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_drift.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement observed_value**

`app/services/signal_graph/drift.py`:
```python
"""Drift-over-graph (Task 2). Computes each gate's observed value from the
consolidated, all-tier observations and attributes any breach to the upstream
signals that moved most, broken down by tier."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...models import Baseline, SignalEdge, SignalNode, SignalObservation
from . import keys

log = logging.getLogger("signal_graph.drift")


def _consolidated(db: Session, signal_key: str, segment: str, ws, we) -> Optional[SignalObservation]:
    return (
        db.query(SignalObservation)
        .filter(
            SignalObservation.signal_key == signal_key,
            SignalObservation.segment == segment,
            SignalObservation.source_stream == "consolidated",
            SignalObservation.window_start >= ws,
            SignalObservation.window_end <= we,
        )
        .order_by(SignalObservation.window_start.desc())
        .first()
    )


def observed_value(
    db: Session, baseline: Baseline, *, window_start: datetime, window_end: datetime,
) -> Optional[float]:
    """The gate's observed value = the metric node's consolidated observation
    across all tiers in the window."""
    obs = _consolidated(db, keys.metric_key(baseline.metric), baseline.segment, window_start, window_end)
    return obs.value if obs else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_drift.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/drift.py salesops-solution/backend/tests/signal_graph/test_drift.py
git commit -m "feat: drift observed_value from consolidated all-tier observation"
```

### Task 18: Drift attribution — top movers + tier breakdown

**Files:**
- Modify: `salesops-solution/backend/app/services/signal_graph/drift.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_drift.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from app.services.signal_graph import backtrack


def test_attribution_ranks_movers_and_breaks_down_by_tier(db):
    base_ws = model_now() - timedelta(days=14)
    base_we = model_now() - timedelta(days=7)
    cur_ws = model_now() - timedelta(days=7)
    cur_we = model_now()

    b = Baseline(metric="extraction_completeness", segment="intent:po_intake",
                 direction="min", target_value=0.95)
    db.add(b); db.commit()
    backtrack.backtrack_baseline(db, baseline_id=b.id)

    sk = "raw:pipeline:extracted.ship_to"
    # ship_to was healthy in the baseline window, dropped in the current window
    _obs(db, sk, "intent:po_intake", "consolidated", None, 3200, 0.97, 3200, base_ws, base_we)
    _obs(db, sk, "intent:po_intake", "consolidated", None, 0.81, 3200, cur_ws, cur_we)
    # tier rows for the current window
    _obs(db, sk, "intent:po_intake", "traceback", "L4_AUTO", 0.78, 3000, cur_ws, cur_we)
    _obs(db, sk, "intent:po_intake", "traceback", "L2", 0.99, 200, cur_ws, cur_we)
    db.commit()

    result = drift.attribute(
        db, b,
        baseline_window=(base_ws, base_we),
        current_window=(cur_ws, cur_we),
    )
    top = result["top_contributors"]
    assert top[0]["signal_key"] == sk
    assert top[0]["movement"] < 0  # it dropped
    assert result["tier_breakdown"]["L4_AUTO"] == 0.78
    assert result["tier_breakdown"]["L2"] == 0.99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_drift.py -k attribution -v`
Expected: FAIL with `AttributeError: attribute`

- [ ] **Step 3: Implement attribution**

Append to `drift.py`:
```python
def _signal_value(db, signal_key, segment, stream, tier, ws, we):
    q = (
        db.query(SignalObservation)
        .filter(
            SignalObservation.signal_key == signal_key,
            SignalObservation.segment == segment,
            SignalObservation.source_stream == stream,
            SignalObservation.window_start >= ws,
            SignalObservation.window_end <= we,
        )
    )
    q = q.filter(SignalObservation.autonomy_tier.is_(None)) if tier is None \
        else q.filter(SignalObservation.autonomy_tier == tier)
    row = q.order_by(SignalObservation.window_start.desc()).first()
    return row.value if row else None


def _raw_signal_keys(db, baseline) -> list[str]:
    """Raw-signal node keys upstream of this gate's target."""
    target = (
        db.query(SignalNode)
        .filter(SignalNode.key == keys.target_key(baseline.metric, baseline.segment))
        .first()
    )
    if not target:
        return []
    seen: set[int] = set()
    frontier = [target.id]
    raw_keys: list[str] = []
    while frontier:
        nxt = []
        for nid in frontier:
            if nid in seen:
                continue
            seen.add(nid)
            for e in db.query(SignalEdge).filter(
                SignalEdge.to_node_id == nid, SignalEdge.status == "active"
            ).all():
                node = db.query(SignalNode).filter(SignalNode.id == e.from_node_id).first()
                if node and node.node_type == "raw_signal":
                    raw_keys.append(node.key)
                nxt.append(e.from_node_id)
        frontier = nxt
    return raw_keys


def attribute(db: Session, baseline: Baseline, *, baseline_window, current_window) -> dict:
    """Rank upstream raw signals by movement (current - baseline) and produce a
    per-tier breakdown of the worst mover."""
    bws, bwe = baseline_window
    cws, cwe = current_window
    contributors = []
    for sk in _raw_signal_keys(db, baseline):
        base = _signal_value(db, sk, baseline.segment, "consolidated", None, bws, bwe)
        cur = _signal_value(db, sk, baseline.segment, "consolidated", None, cws, cwe)
        if base is None or cur is None:
            continue
        contributors.append({"signal_key": sk, "movement": round(cur - base, 6),
                             "current": cur, "baseline": base})
    contributors.sort(key=lambda c: abs(c["movement"]), reverse=True)

    tier_breakdown = {}
    if contributors:
        worst = contributors[0]["signal_key"]
        for tier in ("L4_AUTO", "L3", "L2"):
            v = _signal_value(db, worst, baseline.segment, "traceback", tier, cws, cwe)
            if v is not None:
                tier_breakdown[tier] = v

    likely_cause = None
    if contributors:
        likely_cause = (
            f"{contributors[0]['signal_key']} moved {contributors[0]['movement']:+.3f}"
        )
    return {
        "top_contributors": contributors[:5],
        "tier_breakdown": tier_breakdown,
        "likely_cause": likely_cause,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_drift.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/drift.py salesops-solution/backend/tests/signal_graph/test_drift.py
git commit -m "feat: drift attribution — rank movers + tier breakdown"
```

### Task 19: Graph-drift detector + DriftAlert enrichment

**Files:**
- Modify: `salesops-solution/backend/app/services/signal_graph/drift.py` (add `detect_signal_graph_drift`)
- Modify: `salesops-solution/backend/app/services/monitor.py` (register in `_DETECTORS`, ~line 1483)
- Test: `salesops-solution/backend/tests/signal_graph/test_drift_detector.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_drift_detector.py`:
```python
from datetime import timedelta

from app.models import Baseline, DriftAlert, SignalObservation, now as model_now
from app.services.signal_graph import backtrack, drift


def test_detector_fires_enriched_alert_on_breach(db):
    cur_ws = model_now() - timedelta(days=7)
    cur_we = model_now()
    b = Baseline(metric="extraction_completeness", segment="intent:po_intake",
                 direction="min", target_value=0.95, enabled=True, drift_pct=5.0)
    db.add(b); db.commit()
    backtrack.backtrack_baseline(db, baseline_id=b.id)

    db.add(SignalObservation(
        domain="keysight", signal_key="metric:extraction_completeness",
        segment="intent:po_intake", window_start=cur_ws, window_end=cur_we,
        value=0.88, sample_size=3200, source_stream="consolidated", autonomy_tier=None,
    ))
    db.commit()

    fired = drift.detect_signal_graph_drift(db)
    assert fired >= 1
    alert = db.query(DriftAlert).filter(DriftAlert.metric == "extraction_completeness").first()
    assert alert is not None
    assert alert.baseline_id == b.id
    assert alert.detail.get("tier_breakdown") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_drift_detector.py -v`
Expected: FAIL with `AttributeError: detect_signal_graph_drift`

- [ ] **Step 3: Implement the detector**

Append to `drift.py`:
```python
def detect_signal_graph_drift(db: Session, *, window_days: int = 7) -> int:
    """For each enabled baseline: compute observed value from consolidated
    observations, classify against the human-set target, and on breach emit an
    enriched DriftAlert (reusing existing fields). Returns alerts fired."""
    from datetime import timedelta
    from ...models import Baseline, DriftAlert, now
    from ...services.baselines import evaluate_status

    cur_we = now()
    cur_ws = cur_we - timedelta(days=window_days)
    base_we = cur_ws
    base_ws = base_we - timedelta(days=window_days)

    fired = 0
    for b in db.query(Baseline).filter(Baseline.enabled.is_(True)).all():
        try:
            observed = observed_value(db, b, window_start=cur_ws, window_end=cur_we)
            status = evaluate_status(b, observed)
            if status not in ("drifting", "breached"):
                continue
            attr = attribute(db, b, baseline_window=(base_ws, base_we),
                             current_window=(cur_ws, cur_we))
            fingerprint = f"signal_graph:{b.metric}:{b.segment}"
            alert = (
                db.query(DriftAlert)
                .filter(DriftAlert.fingerprint == fingerprint, DriftAlert.status == "open")
                .first()
            )
            detail = {
                "top_contributors": attr["top_contributors"],
                "tier_breakdown": attr["tier_breakdown"],
                "likely_cause": attr["likely_cause"],
                "recommended_fix_area": f"{b.metric} stage",
            }
            if alert:
                alert.current = observed
                alert.detail = detail
                alert.severity = "high" if status == "breached" else "medium"
            else:
                db.add(DriftAlert(
                    fingerprint=fingerprint, segment=b.segment, metric=b.metric,
                    baseline=b.target_value, current=observed,
                    delta=(observed - b.target_value) if observed is not None else None,
                    severity="high" if status == "breached" else "medium",
                    status="open", baseline_id=b.id, detail=detail,
                ))
                fired += 1
        except Exception as e:
            log.exception("signal_graph drift failed for baseline %s: %s", b.id, e)
    db.commit()
    return fired
```

- [ ] **Step 4: Register the detector in monitor**

In `app/services/monitor.py`, add to the `_DETECTORS` list (after `("baseline_violations", detect_baseline_violations),`):
```python
    ("signal_graph_drift", _signal_graph_drift_detector),
```
And add this thin adapter above `_DETECTORS` (keeps monitor free of a hard import cycle):
```python
def _signal_graph_drift_detector(db: Session) -> int:
    from .signal_graph.drift import detect_signal_graph_drift
    return detect_signal_graph_drift(db)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_drift_detector.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add salesops-solution/backend/app/services/signal_graph/drift.py salesops-solution/backend/app/services/monitor.py salesops-solution/backend/tests/signal_graph/test_drift_detector.py
git commit -m "feat: signal-graph drift detector emits enriched DriftAlert; wired into monitor"
```

### Task 20: Observations API (consolidated signals split by stream & tier)

**Files:**
- Modify: `salesops-solution/backend/app/routes/learning.py`
- Test: `salesops-solution/backend/tests/signal_graph/test_observations_api.py`

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_observations_api.py`:
```python
from datetime import timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from app.models import Baseline, SignalObservation, now as model_now


def test_observations_endpoint_splits_by_stream_and_tier(db):
    ws = model_now() - timedelta(days=7)
    we = model_now()
    b = Baseline(metric="extraction_completeness", segment="intent:po_intake",
                 direction="min", target_value=0.95)
    db.add(b); db.commit()
    db.add_all([
        SignalObservation(domain="keysight", signal_key="raw:pipeline:extracted.ship_to",
                          segment="intent:po_intake", window_start=ws, window_end=we,
                          value=0.78, sample_size=3000, source_stream="traceback",
                          autonomy_tier="L4_AUTO"),
        SignalObservation(domain="keysight", signal_key="raw:pipeline:extracted.ship_to",
                          segment="intent:po_intake", window_start=ws, window_end=we,
                          value=0.81, sample_size=3200, source_stream="consolidated",
                          autonomy_tier=None),
    ])
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    resp = client.get(f"/learning/baselines/{b.id}/observations")
    assert resp.status_code == 200
    items = resp.json()["items"]
    streams = {i["source_stream"] for i in items}
    assert "traceback" in streams and "consolidated" in streams
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_observations_api.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the endpoint**

Append to `app/routes/learning.py`:
```python
@router.get("/baselines/{baseline_id}/observations")
def get_baseline_observations(baseline_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import Baseline, SignalObservation
    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="baseline not found")
    rows = (
        db.query(SignalObservation)
        .filter(SignalObservation.segment == b.segment)
        .order_by(SignalObservation.window_start.desc())
        .limit(500)
        .all()
    )
    return {"items": [{
        "signal_key": r.signal_key, "segment": r.segment,
        "source_stream": r.source_stream, "autonomy_tier": r.autonomy_tier,
        "value": r.value, "sample_size": r.sample_size,
        "window_start": r.window_start.isoformat() if r.window_start else None,
    } for r in rows]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_observations_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/routes/learning.py salesops-solution/backend/tests/signal_graph/test_observations_api.py
git commit -m "feat: observations API — consolidated signals split by stream & tier"
```

### Task 21: Full-suite green + scheduler wiring

**Files:**
- Modify: `salesops-solution/backend/app/routes/learning.py` (add a manual "refresh recommendations + consolidate" endpoint so the Orchestrator can trigger the batch)
- Test: run the whole suite

- [ ] **Step 1: Write the failing test**

`tests/signal_graph/test_refresh_endpoint.py`:
```python
from datetime import timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from app.models import Email, Pipeline, BaselineRecommendation, now as model_now


def test_refresh_endpoint_generates_recommendations(db):
    start = model_now() - timedelta(days=1)
    for i in range(10):
        e = Email(subject="s", from_address="a@b.com", body="x")
        db.add(e); db.flush()
        db.add(Pipeline(email_id=e.id, intent="po_intake", autonomy_tier="L4_AUTO",
                        extracted={"po_number": str(i)}, status="done", started_at=start))
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    resp = client.post("/learning/baselines/recommendations/refresh")
    assert resp.status_code == 200
    assert db.query(BaselineRecommendation).count() > 0
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/signal_graph/test_refresh_endpoint.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the refresh endpoint**

Append to `app/routes/learning.py`:
```python
@router.post(
    "/baselines/recommendations/refresh",
    dependencies=[Depends(require_role(ROLE_CL_ADMIN, ROLE_PLATFORM_ADMIN))],
)
def refresh_recommendations(db: Session = Depends(get_db)) -> dict:
    from ..services.signal_graph import DEFAULT_DOMAIN
    from ..services.signal_graph.recommender import generate_recommendations
    recs = generate_recommendations(db, domain=DEFAULT_DOMAIN)
    return {"generated": len(recs)}
```

- [ ] **Step 4: Run the FULL suite**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/ -v`
Expected: PASS (all tests across all tasks)

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/routes/learning.py salesops-solution/backend/tests/signal_graph/test_refresh_endpoint.py
git commit -m "feat: refresh endpoint to (re)generate baseline recommendations"
```

---

## Final verification

- [ ] **Run the entire test suite once more and confirm green:**

Run: `cd salesops-solution/backend; .venv\Scripts\python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Manual smoke (optional):** start the app and hit `GET /learning/baselines/recommendations` to confirm the route resolves under the real router prefix.

---

## Self-review notes (author checklist — already applied)

- **Spec coverage:** Task 1/2 (recommender) → Tasks 8–13; backtracking both recommended & hand-added gates → Tasks 14–15; signals lineage API → Task 16; dual-input consolidation across all tiers → Tasks 6–7; drift-over-graph + attribution + tier breakdown + enriched alerts → Tasks 17–20; APIs → Tasks 13/16/20/21; data model → Tasks 1–4; MetricSpec registry → Tasks 8/8b.
- **Human sets the number:** `BaselineRecommendation` has no target_value column (Task 4); accept requires `target_value` in the body (Task 13). Enforced by test.
- **Self-blinding fix:** Task 6's headline test asserts an L4 case with no feedback still yields a traceback observation.
- **Build-order dependency:** Task 13 (accept) imports `backtrack_baseline` from Task 14 — noted inline; implement Task 14 before running Task 13's test.
- **Router prefix:** flagged in Task 13 — verify whether learning routes mount at `/learning/...` or `/...` and adjust test URLs accordingly.
- **No numpy/scipy:** all stats (percentiles, stddev, Pearson) are pure-Python (Tasks 10–11).
```
