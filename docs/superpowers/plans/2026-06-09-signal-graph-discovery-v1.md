# Signal-Graph Discovery (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Execution mode: inline, baby-steps — the implementer writes each piece and explains logic/purpose/why/how-Python-accomplishes-it to the user as they go (user is learning Python).**

**Goal:** Given a client `session_id`, fetch its codebase (local zip fixture for v1), have an LLM discover the quality **signals** and propose candidate **quality gates**, persist them, let the user accept a gate + set its threshold, and view the gate's signal graph — exposed via `/api/signal-graph/*` and a new frontend **SignalGraph** page.

**Architecture:** Two-pass LLM discovery (Pass 1 = signals/facts, Pass 2 = candidate gates/judgments). Persist directly (no human-approval gate in v1). Reuse the existing scoring/graph engine (`recommender`, `confirm`, `backtrack`) and the existing frontend graph stack (`@xyflow/react` + `dagre`). Everything scoped by `session_id` (stored in the existing `domain` column for v1 — no DB migration).

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), `app/agents/llm.ask_llm` (LLM), React 18 + Vite + TS + `@xyflow/react`/`dagre` (frontend). Spec: `docs/superpowers/specs/2026-06-09-general-quality-gate-discovery-design.md`.

**v1 simplifications (deliberate, noted in spec):** discovery runs **synchronously** (small example codebases, 2 LLM calls) and returns a summary — no background-task/poll infra yet. No human-approval gate. No tests (deferred); each task ends in a manual verification step.

---

## File Structure

**Backend (new), under `app/services/signal_graph/discovery/`:**
- `schema.py` — `Signal`, `CandidateGate` pydantic models (the contracts).
- `fetch_solution.py` — resolve `session_id` → local zip, extract to a temp dir (v1 local mode).
- `extract_signals.py` — Pass 1: read codebase digest → `list[Signal]`.
- `propose_gates.py` — Pass 2: `list[Signal]` → `list[CandidateGate]`.
- `run.py` — orchestrate fetch → Pass 1 → Pass 2 → persist; return summary.

**Backend (modify):**
- `app/routes/signal_graph.py` (new route module) + register in `app/main.py`.

**Frontend (new/modify), under `salesops-solution/frontend/src/`:**
- `api.ts` (modify) — types + client functions.
- `hooks/useSignalGraph.ts` (new) — fetch helpers.
- `pages/SignalGraph.tsx` (new) — Discover + recommendation cards + threshold + graph.
- `App.tsx` (modify) — route. `components/Layout.tsx` (modify) — nav entry.

---

## Task 1: Discovery schemas (`Signal`, `CandidateGate`)

**Files:**
- Create: `app/services/signal_graph/discovery/__init__.py` (empty)
- Create: `app/services/signal_graph/discovery/schema.py`

- [ ] **Step 1: Write the schemas**

```python
# app/services/signal_graph/discovery/schema.py
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel

# A SIGNAL is a FACT: something the running system observably emits.
class Signal(BaseModel):
    key: str                                   # stable id, e.g. "post_title_400"
    description: str                           # human-readable fact
    stream: Literal["telemetry", "feedback"]   # the ONE fixed categorization
    observable: str                            # free-text hint, e.g. "status_code" (NOT an enum)
    evidence: str                              # file:line / doc ref, for verification
    segment_hint: Optional[str] = None         # e.g. "endpoint:POST /todos"

# A CANDIDATE GATE is a JUDGMENT: a quality threshold worth watching, over signals.
class CandidateGate(BaseModel):
    key: str
    description: str
    direction: Literal["min", "max"]
    compute: Literal["rate", "ratio", "p95", "psi", "count", "mean"]
    inputs: list[str]                          # Signal.key list = the graph edges (gate <- signals)
    segment_dimension: str = "global"          # discovered; may be "global"
    rationale: str
    # NO target_value — the user sets it on accept (the invariant).
    # NO priority either — candidates are unranked suggestions; priority is a
    # property of ACCEPTED baseline targets, computed from data (Task 12).
```

*Why:* these two classes are the **contract** between the LLM and the rest of the system. Pydantic validates the LLM's JSON automatically — if the model returns a bad shape, construction raises, so garbage never flows downstream. `Signal` = fact, `CandidateGate` = judgment, kept as separate types because they're produced by separate passes and reviewed differently.

- [ ] **Step 2: Verify it imports and validates**

Run: `cd salesops-solution/backend && python -c "from app.services.signal_graph.discovery.schema import Signal, CandidateGate; print(Signal(key='k', description='d', stream='telemetry', observable='status_code', evidence='f:1')); print(CandidateGate(key='g', description='d', direction='max', compute='rate', inputs=['k'], rationale='r'))"`
Expected: prints two model instances, no error.

- [ ] **Step 3: Commit**

```bash
git add app/services/signal_graph/discovery/
git commit -m "feat(signal-graph): discovery Signal/CandidateGate schemas"
```

---

## Task 2: Local-fixture fetch (`fetch_solution`)

**Files:**
- Create: `app/services/signal_graph/discovery/fetch_solution.py`

- [ ] **Step 1: Write the fetcher**

```python
# app/services/signal_graph/discovery/fetch_solution.py
from __future__ import annotations
import os, tempfile, zipfile
from pathlib import Path

# v1 LOCAL MODE: map a session_id to a zip already in the repo root.
# (Later: SOLUTION_FETCH_MODE=live calls the real download-app API.)
_REPO_ROOT = Path(__file__).resolve().parents[6]   # .../keysight-salesops-bundle (zips live here)
# parents: 0=discovery 1=signal_graph 2=services 3=app 4=backend 5=salesops-solution 6=repo-root
_FIXTURES = {
    "f8651fcd-6c46-4ed2-83ec-665f31027267": "tristone---test-case-3.zip",   # todo app
    # add content-research session id here when known:
    # "<session-id>": "content-research-solution.zip",
}

def fetch_solution(tenant_id: str, session_id: str) -> Path:
    """Return a directory containing the client's extracted codebase.
    v1: read a local zip fixture keyed by session_id."""
    mode = os.environ.get("SOLUTION_FETCH_MODE", "local")
    if mode != "local":
        raise NotImplementedError("live Solution-Fetch API not wired in v1")
    zip_name = _FIXTURES.get(session_id)
    if not zip_name:
        raise ValueError(f"no local fixture for session_id={session_id}")
    zip_path = _REPO_ROOT / zip_name
    work_dir = Path(tempfile.mkdtemp(prefix=f"sg_{session_id[:8]}_"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work_dir)
    return work_dir
```

*Why:* this keeps the **same signature** we'll use for the real API (`tenant_id, session_id -> dir`), so swapping to live later changes only this file. `parents[5]` walks up from `.../backend/app/services/signal_graph/discovery/fetch_solution.py` to the repo root where the zips live. `tempfile.mkdtemp` gives an isolated extraction dir per run so concurrent discoveries never collide.

- [ ] **Step 2: Verify extraction works**

Run: `cd salesops-solution/backend && python -c "from app.services.signal_graph.discovery.fetch_solution import fetch_solution; d=fetch_solution('t','f8651fcd-6c46-4ed2-83ec-665f31027267'); import os; print(d); print(sorted(os.listdir(d)))"`
Expected: prints a temp dir and a listing containing `tristone---test-case-3` (the extracted folder).

- [ ] **Step 3: Commit**

```bash
git add app/services/signal_graph/discovery/fetch_solution.py
git commit -m "feat(signal-graph): local-fixture solution fetch"
```

---

## Task 3: Pass 1 — extract signals (`extract_signals`)

**Files:**
- Create: `app/services/signal_graph/discovery/extract_signals.py`

- [ ] **Step 1: Write the digest builder + Pass-1 call**

```python
# app/services/signal_graph/discovery/extract_signals.py
from __future__ import annotations
from pathlib import Path
from ....agents.llm import ask_llm        # 4 dots: discovery->signal_graph->services->app, then agents.llm
from .schema import Signal

# Read the docs + source most likely to reveal observable signals.
_DOC_GLOBS = ("*.md",)
_SRC_GLOBS = ("**/routes/*.*", "**/schema.sql", "**/*.sql", "**/server.*", "**/agents-plan.md")
_MAX_CHARS = 60_000   # keep the digest within model context for v1 small codebases

def _build_digest(code_dir: Path) -> str:
    parts: list[str] = []
    seen: set[Path] = set()
    for pat in _DOC_GLOBS + _SRC_GLOBS:
        for f in sorted(code_dir.rglob(pat)):
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            parts.append(f"\n\n===== FILE: {f.relative_to(code_dir).as_posix()} =====\n{text}")
    return "".join(parts)[:_MAX_CHARS]

_SYSTEM = (
    "You are analyzing a software system to find its observable QUALITY SIGNALS. "
    "A signal is a FACT about something the running system emits or records: HTTP status codes, "
    "errors, latencies, log/telemetry events, DB writes (these are 'telemetry'); or human "
    "corrections/edits/reviews of the system's output (these are 'feedback'). Do NOT invent metrics "
    "or thresholds. Only report signals you can point to in the provided files. "
    "Return JSON: {\"signals\": [{\"key\",\"description\",\"stream\",\"observable\",\"evidence\",\"segment_hint\"}]}. "
    "stream is exactly 'telemetry' or 'feedback'. evidence is a file:line or filename reference."
)

def extract_signals(code_dir: Path) -> list[Signal]:
    digest = _build_digest(code_dir)
    data = ask_llm(system=_SYSTEM, user=digest, json_only=True)
    raw = (data or {}).get("signals", []) if isinstance(data, dict) else []
    out: list[Signal] = []
    for item in raw:
        try:
            out.append(Signal(**item))          # pydantic validates each; bad ones skipped
        except Exception:
            continue
    return out
```

*Why:* Pass 1 must be grounded in real code, so we build a **digest** of the files most likely to contain signals (docs + routes + schema + server) and hand it to the LLM. `_MAX_CHARS` caps it so it fits the model context (fine for the small example zips; chunking is a later concern). `json_only=True` makes `ask_llm` return parsed JSON. We validate every item through `Signal(**item)` so a malformed entry is dropped rather than crashing the run — the `stream` field is the one thing we force into `telemetry|feedback`.

- [ ] **Step 2: Verify Pass 1 on the todo app**

Run: `cd salesops-solution/backend && python -c "from app.services.signal_graph.discovery.fetch_solution import fetch_solution; from app.services.signal_graph.discovery.extract_signals import extract_signals; d=fetch_solution('t','f8651fcd-6c46-4ed2-83ec-665f31027267'); sigs=extract_signals(next(d.iterdir())); print(len(sigs)); [print(s.key, s.stream, '|', s.evidence) for s in sigs[:8]]"`
Expected: prints a count > 0 and several signals like `post_title_400 telemetry | ...` (requires a working LLM key in env/DB).

- [ ] **Step 3: Commit**

```bash
git add app/services/signal_graph/discovery/extract_signals.py
git commit -m "feat(signal-graph): Pass 1 signal extraction"
```

---

## Task 4: Pass 2 — propose gates (`propose_gates`)

**Files:**
- Create: `app/services/signal_graph/discovery/propose_gates.py`

- [ ] **Step 1: Write the Pass-2 call**

```python
# app/services/signal_graph/discovery/propose_gates.py
from __future__ import annotations
import json
from ....agents.llm import ask_llm        # 4 dots -> app.agents.llm
from .schema import Signal, CandidateGate

_SYSTEM = (
    "You are proposing baseline QUALITY GATES for a software system, given a list of its observable "
    "signals. A gate is a metric over one or more signals that is worth monitoring. Do NOT set any "
    "threshold/target number (a human will). For each gate give a compute type from "
    "[rate, ratio, p95, psi, count, mean], a direction ('min' better-is-higher / 'max' better-is-lower), "
    "and 'inputs' = the list of signal keys it is computed from. "
    "Return JSON: {\"gates\":[{\"key\",\"description\",\"direction\",\"compute\",\"inputs\",\"segment_dimension\",\"rationale\"}]}."
)

def propose_gates(signals: list[Signal]) -> list[CandidateGate]:
    signal_list = [{"key": s.key, "description": s.description, "stream": s.stream} for s in signals]
    user = "SIGNALS:\n" + json.dumps(signal_list, indent=2)
    data = ask_llm(system=_SYSTEM, user=user, json_only=True)
    raw = (data or {}).get("gates", []) if isinstance(data, dict) else []
    valid_keys = {s.key for s in signals}
    out: list[CandidateGate] = []
    for item in raw:
        try:
            gate = CandidateGate(**item)
        except Exception:
            continue
        gate.inputs = [k for k in gate.inputs if k in valid_keys]   # drop hallucinated signal refs
        if gate.inputs:                                             # a gate needs >=1 real signal
            out.append(gate)
    return out
```

*Why:* Pass 2 only sees the **signal list** (not the codebase again) — facts in, judgments out. We pass just `key/description/stream` so the model reasons over the signal vocabulary. After validation we **filter `inputs` to real signal keys** — this is how we stop the LLM from wiring a gate to a signal that doesn't exist, which would later create a dangling graph edge. A gate with no surviving inputs is dropped.

- [ ] **Step 2: Verify Pass 2**

Run: `cd salesops-solution/backend && python -c "from app.services.signal_graph.discovery.fetch_solution import fetch_solution; from app.services.signal_graph.discovery.extract_signals import extract_signals; from app.services.signal_graph.discovery.propose_gates import propose_gates; d=fetch_solution('t','f8651fcd-6c46-4ed2-83ec-665f31027267'); s=extract_signals(next(d.iterdir())); g=propose_gates(s); print(len(g)); [print(x.key, x.direction, x.compute, x.inputs) for x in g[:8]]"`
Expected: prints gate count > 0 with each gate's inputs being a subset of the signal keys.

- [ ] **Step 3: Commit**

```bash
git add app/services/signal_graph/discovery/propose_gates.py
git commit -m "feat(signal-graph): Pass 2 gate proposal"
```

---

## Task 5: Orchestrate + persist (`run_discovery`)

**Files:**
- Create: `app/services/signal_graph/discovery/run.py`
- Reference (read): `app/models.py` (`SignalNode`, `SignalEdge`, `BaselineRecommendation`)

- [ ] **Step 1: Write the orchestrator that persists the Solution Model**

```python
# app/services/signal_graph/discovery/run.py
from __future__ import annotations
from sqlalchemy.orm import Session
from ....models import SignalNode, SignalEdge, BaselineRecommendation
from .fetch_solution import fetch_solution
from .extract_signals import extract_signals
from .propose_gates import propose_gates

def run_discovery(db: Session, *, tenant_id: str, session_id: str) -> dict:
    """Fetch -> Pass1 -> Pass2 -> persist (scoped by session_id in the `domain` column)."""
    domain = session_id                              # v1: session_id is our scope key
    code_dir = fetch_solution(tenant_id, session_id)
    root = next(code_dir.iterdir())                  # the single extracted top folder
    signals = extract_signals(root)
    gates = propose_gates(signals)

    # 1) persist each signal as a raw_signal SignalNode
    key_to_node: dict[str, SignalNode] = {}
    for s in signals:
        node = SignalNode(domain=domain, key=s.key, node_type="raw_signal",
                          source_stream=s.stream, meta={"description": s.description,
                          "evidence": s.evidence, "observable": s.observable})
        db.add(node); db.flush()
        key_to_node[s.key] = node

    # 2) persist each gate: a target node + a candidate recommendation + edges signal->target
    for g in gates:
        tnode = SignalNode(domain=domain, key=f"target:{g.key}", node_type="baseline_target",
                          meta={"description": g.description, "rationale": g.rationale,
                          "compute": g.compute})
        db.add(tnode); db.flush()
        db.add(BaselineRecommendation(domain=domain, metric=g.key, segment=g.segment_dimension,
              direction=g.direction, score=0.0, rationale=g.rationale,   # candidates are UNRANKED (no data yet)
              context_stats={}, subgraph_snapshot={"inputs": g.inputs, "compute": g.compute}, status="open"))
        for sk in g.inputs:
            src = key_to_node.get(sk)
            if src:
                db.add(SignalEdge(domain=domain, from_node_id=src.id, to_node_id=tnode.id,
                      relation="affects", origin="discovered", status="active",
                      weight=None, evidence={}))
    db.commit()
    return {"session_id": session_id, "signals": len(signals), "gates": len(gates)}
```

*Why:* this is the **persist-directly** step (no approval gate). Each `Signal` becomes a `raw_signal` node; each `CandidateGate` becomes a `baseline_target` node + an **`open` `BaselineRecommendation`** (which has no `target_value` — the invariant) + `affects` edges from its input signals. We store `session_id` in the existing `domain` column so **no DB migration** is needed for v1. `db.flush()` assigns node ids before we create edges that reference them. Edge `weight=None` until observation data arrives.

- [ ] **Step 2: Verify the full pipeline persists**

Run: `cd salesops-solution/backend && python -c "from app.db import SessionLocal; from app.services.signal_graph.discovery.run import run_discovery; db=SessionLocal(); print(run_discovery(db, tenant_id='676e7711192abc0024679612', session_id='f8651fcd-6c46-4ed2-83ec-665f31027267'))"`
Expected: prints e.g. `{'session_id': '...', 'signals': N, 'gates': M}` with N,M > 0.

- [ ] **Step 3: Commit**

```bash
git add app/services/signal_graph/discovery/run.py
git commit -m "feat(signal-graph): orchestrate discovery and persist solution model"
```

---

## Task 6: Backend API route module

**Files:**
- Create: `app/routes/signal_graph.py`
- Modify: `app/main.py` (add one `include_router` line near the others, ~line 156)
- Reference (read): `app/routes/learning.py` (router/get_db pattern), `app/models.py` (`Baseline`)

- [ ] **Step 1: Write the route module**

```python
# app/routes/signal_graph.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import BaselineRecommendation, SignalNode, SignalEdge, Baseline
from ..services.signal_graph.discovery.run import run_discovery

router = APIRouter()

class DiscoverBody(BaseModel):
    tenant_id: str
    session_id: str

@router.post("/discover")
def discover(body: DiscoverBody, db: Session = Depends(get_db)) -> dict:
    return run_discovery(db, tenant_id=body.tenant_id, session_id=body.session_id)

@router.get("/recommendations")
def recommendations(session_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(BaselineRecommendation).filter(
        BaselineRecommendation.domain == session_id,
        BaselineRecommendation.status == "open").all()
    return [{"id": r.id, "metric": r.metric, "segment": r.segment, "direction": r.direction,
             "score": r.score, "rationale": r.rationale,
             "inputs": (r.subgraph_snapshot or {}).get("inputs", [])} for r in rows]

class AcceptBody(BaseModel):
    target_value: float

@router.post("/recommendations/{rec_id}/accept")
def accept(rec_id: int, body: AcceptBody, db: Session = Depends(get_db)) -> dict:
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")
    baseline = Baseline(domain=rec.domain, metric=rec.metric, segment=rec.segment,
                        direction=rec.direction, target_value=body.target_value)  # USER's number
    db.add(baseline); rec.status = "accepted"; db.commit()
    return {"baseline_id": baseline.id, "metric": rec.metric, "target_value": body.target_value}

@router.post("/recommendations/{rec_id}/dismiss")
def dismiss(rec_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")
    rec.status = "dismissed"; db.commit()
    return {"ok": True}

@router.get("/recommendations/{rec_id}/graph")
def graph(rec_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.query(BaselineRecommendation).filter(BaselineRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "recommendation not found")
    tnode = db.query(SignalNode).filter(SignalNode.domain == rec.domain,
                                        SignalNode.key == f"target:{rec.metric}").first()
    nodes = [{"key": tnode.key, "type": tnode.node_type}] if tnode else []
    edges = []
    if tnode:
        for e in db.query(SignalEdge).filter(SignalEdge.domain == rec.domain,
                                             SignalEdge.to_node_id == tnode.id).all():
            src = db.query(SignalNode).filter(SignalNode.id == e.from_node_id).first()
            if src:
                nodes.append({"key": src.key, "type": src.node_type})
                edges.append({"from": src.key, "to": tnode.key, "weight": e.weight})
    return {"nodes": nodes, "edges": edges}
```

*Why:* this exposes the flow over HTTP using the project's exact router pattern (`APIRouter` + `Depends(get_db)`). `accept` is the **only** place a `target_value` is written, and it comes straight from the request body — enforcing "the user sets the threshold." `graph` reconstructs the gate's subgraph from the persisted nodes/edges so the frontend can draw it. (Confirm `Baseline`'s real column names against `models.py` while implementing; adjust if needed.)

- [ ] **Step 2: Register the router in `main.py`**

```python
# app/main.py — add alongside the other include_router lines (~line 156)
from .routes import signal_graph
app.include_router(signal_graph.router, prefix="/api/signal-graph", tags=["signal-graph"])
```

- [ ] **Step 3: Verify the endpoints respond**

Run: start the backend (`uvicorn app.main:app --reload` from `salesops-solution/backend`), then:
`curl -X POST localhost:8000/api/signal-graph/discover -H "Content-Type: application/json" -d '{"tenant_id":"676e7711192abc0024679612","session_id":"f8651fcd-6c46-4ed2-83ec-665f31027267"}'`
then `curl "localhost:8000/api/signal-graph/recommendations?session_id=f8651fcd-6c46-4ed2-83ec-665f31027267"`
Expected: discover returns counts; recommendations returns a JSON list of gates.

- [ ] **Step 4: Commit**

```bash
git add app/routes/signal_graph.py app/main.py
git commit -m "feat(signal-graph): /api/signal-graph routes"
```

---

## Task 7: Frontend API client additions

**Files:**
- Modify: `salesops-solution/frontend/src/api.ts` (add types + functions near the other `api.*` methods)

- [ ] **Step 1: Add types + functions**

```typescript
// api.ts — add to the exported types
export type SgRecommendation = {
  id: number; metric: string; segment: string;
  direction: "min" | "max"; score: number; rationale: string; inputs: string[];
};
export type SgGraph = {
  nodes: { key: string; type: string }[];
  edges: { from: string; to: string; weight: number | null }[];
};

// api.ts — add inside the exported `api` object
  sgDiscover: (tenantId: string, sessionId: string) =>
    jsonRequest<{ session_id: string; signals: number; gates: number }>(
      `/signal-graph/discover`,
      { method: "POST", body: JSON.stringify({ tenant_id: tenantId, session_id: sessionId }) }),
  sgRecommendations: (sessionId: string) =>
    jsonRequest<SgRecommendation[]>(`/signal-graph/recommendations?session_id=${encodeURIComponent(sessionId)}`),
  sgAccept: (recId: number, targetValue: number) =>
    jsonRequest<{ baseline_id: number }>(`/signal-graph/recommendations/${recId}/accept`,
      { method: "POST", body: JSON.stringify({ target_value: targetValue }) }),
  sgDismiss: (recId: number) =>
    jsonRequest<{ ok: boolean }>(`/signal-graph/recommendations/${recId}/dismiss`, { method: "POST" }),
  sgGraph: (recId: number) =>
    jsonRequest<SgGraph>(`/signal-graph/recommendations/${recId}/graph`),
```

*Why:* mirrors the existing `jsonRequest<T>` pattern so the new calls are typed end-to-end and the page code stays tiny. `encodeURIComponent` guards the session-id query param.

- [ ] **Step 2: Verify it type-checks**

Run: `cd salesops-solution/frontend && npx tsc --noEmit`
Expected: no new type errors from `api.ts`.

- [ ] **Step 3: Commit**

```bash
git add salesops-solution/frontend/src/api.ts
git commit -m "feat(signal-graph): frontend api client methods"
```

---

## Task 8: SignalGraph page (Discover + recommendations + threshold)

**Files:**
- Create: `salesops-solution/frontend/src/pages/SignalGraph.tsx`
- Reference (read): `pages/Analytics.tsx` and `components/ui.tsx` for existing card/button primitives.

- [ ] **Step 1: Write the page (discover + recommendation cards + accept/dismiss)**

```tsx
// pages/SignalGraph.tsx
import { useState } from "react";
import { api, type SgRecommendation } from "../api";

// v1: session/tenant hardcoded to the todo-app fixture (later: from app context).
const TENANT = "676e7711192abc0024679612";
const SESSION = "f8651fcd-6c46-4ed2-83ec-665f31027267";

export default function SignalGraphPage() {
  const [recs, setRecs] = useState<SgRecommendation[]>([]);
  const [busy, setBusy] = useState(false);
  const [accepting, setAccepting] = useState<number | null>(null);
  const [target, setTarget] = useState("");

  async function discover() {
    setBusy(true);
    try {
      await api.sgDiscover(TENANT, SESSION);
      setRecs(await api.sgRecommendations(SESSION));
    } finally { setBusy(false); }
  }
  async function accept(id: number) {
    await api.sgAccept(id, parseFloat(target));
    setAccepting(null); setTarget("");
    setRecs(await api.sgRecommendations(SESSION));
  }
  async function dismiss(id: number) {
    await api.sgDismiss(id);
    setRecs(await api.sgRecommendations(SESSION));
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Quality Gates</h1>
        <button className="btn-primary" onClick={discover} disabled={busy}>
          {busy ? "Discovering…" : "Discover"}
        </button>
      </div>
      {recs.length === 0 && !busy && <p className="text-gray-500">No gates yet. Click Discover.</p>}
      <ul className="space-y-3">
        {recs.map(r => (
          <li key={r.id} className="rounded-xl shadow p-4">
            <div className="flex justify-between">
              <div>
                <div className="font-medium">{r.metric} <span className="text-xs text-gray-400">({r.direction})</span></div>
                <div className="text-sm text-gray-600">{r.rationale}</div>
                <div className="text-xs text-gray-400">signals: {r.inputs.join(", ")}</div>
              </div>
              <div className="flex items-start gap-2">
                {accepting === r.id ? (
                  <>
                    <input className="border rounded px-2 w-24" placeholder="target"
                           value={target} onChange={e => setTarget(e.target.value)} />
                    <button className="btn-primary" onClick={() => accept(r.id)}>Confirm</button>
                  </>
                ) : (
                  <button className="btn" onClick={() => setAccepting(r.id)}>Accept</button>
                )}
                <button className="btn" onClick={() => dismiss(r.id)}>Dismiss</button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

*Why:* one self-contained page covering Discover → list → Accept(threshold)/Dismiss. The **threshold `<input>`** is where the user types the number — the UI embodiment of the invariant. State is local `useState` (no global store needed for v1). Class names follow the app's Tailwind utility style; swap `btn`/`btn-primary` for the real `ui.tsx` primitives while implementing.

- [ ] **Step 2: Verify it renders (after Task 9 route)**

Covered by Task 9's verification (the page needs the route to be reachable).

- [ ] **Step 3: Commit**

```bash
git add salesops-solution/frontend/src/pages/SignalGraph.tsx
git commit -m "feat(signal-graph): SignalGraph page (discover + recommendations + threshold)"
```

---

## Task 9: Route + nav entry

**Files:**
- Modify: `salesops-solution/frontend/src/App.tsx` (add a `<Route>`)
- Modify: `salesops-solution/frontend/src/components/Layout.tsx` (add a nav item)

- [ ] **Step 1: Add the route**

```tsx
// App.tsx — import + add inside the inner <Routes> (near the other page routes ~line 60)
import SignalGraphPage from "./pages/SignalGraph";
// ...
<Route path="/signal-graph" element={<SignalGraphPage />} />
```

- [ ] **Step 2: Add the nav entry**

```tsx
// components/Layout.tsx — add to the nav array (near line 16-21)
{ to: "/signal-graph", label: "Quality Gates" },
```

- [ ] **Step 3: Verify end-to-end in the browser**

Run: start backend (`uvicorn app.main:app --reload`) and frontend (`npm run dev` in `frontend`). Open the app, click **Quality Gates** in the nav → click **Discover** → recommendation cards appear → click **Accept**, type a number, **Confirm** → card disappears (status accepted).
Expected: full discover → recommend → accept flow works against the todo-app fixture.

- [ ] **Step 4: Commit**

```bash
git add salesops-solution/frontend/src/App.tsx salesops-solution/frontend/src/components/Layout.tsx
git commit -m "feat(signal-graph): route + nav entry for Quality Gates"
```

---

## Task 10: Signal-graph viewer (reuse xyflow) — optional polish if time

**Files:**
- Modify: `salesops-solution/frontend/src/pages/SignalGraph.tsx` (add a graph panel)
- Reference (read): `pages/ProcessFlow.tsx` for the `@xyflow/react` + `dagre` setup.

- [ ] **Step 1: Add a "view graph" action + panel**

Add to a recommendation card: a `View graph` button that calls `api.sgGraph(r.id)` and renders the returned `{nodes, edges}` with `@xyflow/react` (reuse the `ReactFlow`/`dagre` layout pattern from `ProcessFlow.tsx`: map `nodes` → React Flow nodes, `edges` → React Flow edges labelled with `weight ?? "pending"`).

*Why:* this is the backtrack visualization — signals pointing at the gate, edge labels showing weight (or "pending" until observation data exists). It reuses the app's existing graph stack, so it's mapping work, not new infrastructure. Marked optional because the core demo (discover → recommend → accept) stands without it.

- [ ] **Step 2: Verify**

Run: in the browser, click **View graph** on an accepted/recommended gate → a node/edge diagram renders (gate + its input signals).

- [ ] **Step 3: Commit**

```bash
git add salesops-solution/frontend/src/pages/SignalGraph.tsx
git commit -m "feat(signal-graph): signal-graph viewer panel"
```

---

---

# Part B — Analysis (data-conditional: real numbers if data exists, else "pending")

> These build the **scoring + drift** machinery. They read `SignalObservation` rows keyed by `signal_key`. Ingestion (Task 11) is **best-effort** — for the example zips it may find little, in which case scoring falls back to the LLM `priority` and drift reports `pending`. The code is correct and activates fully when a running system emits properly-keyed observations.

## Task 11: Best-effort observation ingestion (`observe.py`)

**Files:**
- Create: `app/services/signal_graph/discovery/observe.py`
- Modify: `app/services/signal_graph/discovery/run.py` (call it after persisting)
- Reference (read): `app/models.py` (`SignalObservation` columns: `signal_key, segment, window_start, window_end, value, sample_size, source_stream, autonomy_tier`)

- [ ] **Step 1: Write the probe**

```python
# app/services/signal_graph/discovery/observe.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from sqlalchemy.orm import Session
from ....models import SignalObservation, now

def ingest_observations(db: Session, *, domain: str, code_dir: Path) -> int:
    """Best-effort: if the fetched codebase ships a sqlite DB, record snapshot
    observations (per-table row counts) so scoring/drift have something to read.
    Returns count written; writes nothing if no usable DB is found."""
    written = 0
    for db_file in code_dir.rglob("*.db"):
        try:
            con = sqlite3.connect(str(db_file)); cur = con.cursor()
            tables = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for t in tables:
                try:
                    n = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
                except Exception:
                    continue
                db.add(SignalObservation(
                    signal_key=f"table:{t}:row_count", segment="global",
                    window_start=now(), window_end=now(), value=float(n),
                    sample_size=n, source_stream="telemetry", autonomy_tier=None))
                written += 1
            con.close()
        except Exception:
            continue
    db.commit()
    return written
```

*Why:* this is the one place that turns *available* client data into observations. v1 handles the common case (a shipped sqlite DB → per-table snapshot counts). It writes **nothing** when there's no DB, so the analysis correctly shows "pending" rather than inventing numbers. It's deliberately small and extensible — richer per-client extraction (mapping specific signal keys to queries/logs) is added later without touching the analysis code.

- [ ] **Step 2: Call it from `run.py`** (add after the gates loop, before the final `db.commit()`):

```python
    from .observe import ingest_observations
    obs_written = ingest_observations(db, domain=domain, code_dir=root)
```
and add `"observations": obs_written` to the returned summary dict.

- [ ] **Step 3: Verify**

Run: `cd salesops-solution/backend && python -c "from app.db import SessionLocal; from app.services.signal_graph.discovery.run import run_discovery; db=SessionLocal(); print(run_discovery(db, tenant_id='t', session_id='f8651fcd-6c46-4ed2-83ec-665f31027267'))"`
Expected: summary now includes an `observations` count (tristone ships `todos.db`, so > 0).

- [ ] **Step 4: Commit**

```bash
git add app/services/signal_graph/discovery/observe.py app/services/signal_graph/discovery/run.py
git commit -m "feat(signal-graph): best-effort observation ingestion"
```

---

## Task 12: Suggested range (accept guidance) + data-ranked baseline targets

**Files:**
- Modify: `app/routes/signal_graph.py`
- Reference (read): `recommender.py` (`_score`), `confirm.py` (`context_distribution`, `variability`)

Two data-conditional behaviors, both reusing the existing stats engine. Candidates stay **unranked**; the data work is the *suggested range* (at accept) and the *priority sort* (on accepted baseline targets).

- [ ] **Step 1: Shared helpers + suggested range on candidates**

```python
# app/routes/signal_graph.py — add imports + helpers
from ..models import SignalObservation, Baseline
from ..services.signal_graph import confirm
from ..services.signal_graph.recommender import _score

def _obs_values(db, inputs: list[str]) -> list[float]:
    if not inputs:
        return []
    rows = db.query(SignalObservation).filter(SignalObservation.signal_key.in_(inputs)).all()
    return [o.value for o in rows if o.value is not None]

def _context_range(db, inputs: list[str]):
    return confirm.context_distribution(_obs_values(db, inputs))   # {p10,median,p90} or None
```
In `recommendations()` add `"context": _context_range(db, item_inputs)` to each returned item (null when no data → UI shows "no range yet").

*Why:* this is the "**suggest a range, the user sets the number**" guidance — p10/median/p90 straight from the data when it exists. We only inform; the user still types the target. Reuses `confirm.context_distribution` and the `context_stats` column already on the recommendation.

- [ ] **Step 2: Data-ranked baseline-targets endpoint**

```python
@router.get("/baselines")
def baselines(session_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Baseline).filter(Baseline.domain == session_id).all()
    out = []
    for b in rows:
        rec = db.query(BaselineRecommendation).filter(
            BaselineRecommendation.domain == session_id,
            BaselineRecommendation.metric == b.metric).first()
        inputs = (rec.subgraph_snapshot or {}).get("inputs", []) if rec else []
        vals = _obs_values(db, inputs)
        var = confirm.variability(vals) or 0.0
        priority = _score(len(vals), var, bool(inputs))   # data-driven; ~0 when no data
        out.append({"baseline_id": b.id, "metric": b.metric, "target_value": b.target_value,
                    "direction": b.direction, "priority": priority})
    out.sort(key=lambda x: x["priority"], reverse=True)    # highest priority on top
    return out
```

*Why:* the **accepted baseline targets are arranged by a data-driven priority** (`_score` over their signals' observations). With no data, priority ≈ 0 and they're effectively unranked; as data accrues, the busiest/most-volatile gates rise to the top. (Drift severity from Task 13 is layered into this sort once available — breached/drifting first.)

- [ ] **Step 3: Verify**

Run (backend up): `curl "localhost:8000/api/signal-graph/recommendations?session_id=f8651fcd-6c46-4ed2-83ec-665f31027267"` (each item has a `context` field), then `curl "localhost:8000/api/signal-graph/baselines?session_id=f8651fcd-6c46-4ed2-83ec-665f31027267"` (accepted gates sorted by `priority`).
Expected: `context` is null pre-data; baselines list sorted by priority.

- [ ] **Step 4: Commit**

```bash
git add app/routes/signal_graph.py
git commit -m "feat(signal-graph): suggested range + data-ranked baseline targets"
```

---

## Task 13: Analysis math — edge weights + drift (scalar + PSI) → existing drift UI

**Files:**
- Create: `app/services/signal_graph/drift.py`
- Modify: `app/routes/signal_graph.py` (drift endpoint), `app/services/signal_graph/discovery/run.py` (call edge-weight recompute)
- Reference (read): `confirm.py` (`edge_weight`), `app/models.py` (`Baseline`, `DriftAlert`, `SignalEdge`, `SignalNode`, `SignalObservation`)

- [ ] **Step 1: Recompute edge weights from data**

```python
# app/services/signal_graph/drift.py  (top half)
from __future__ import annotations
import math
from sqlalchemy.orm import Session
from ...models import (Baseline, SignalObservation, SignalEdge, SignalNode,
                       DriftAlert, now)
from . import confirm   # sibling module: edge_weight (abs Pearson)

def _series(db, signal_key: str) -> list[float]:
    rows = (db.query(SignalObservation)
              .filter(SignalObservation.signal_key == signal_key)
              .order_by(SignalObservation.window_start.asc()).all())
    return [o.value for o in rows if o.value is not None]

def recompute_edge_weights(db: Session, *, domain: str) -> int:
    """For each edge signal->target: weight = |Pearson| of the signal's value
    series vs the target's series. None when there's too little paired data."""
    n = 0
    for e in db.query(SignalEdge).filter(SignalEdge.domain == domain).all():
        src = db.query(SignalNode).filter(SignalNode.id == e.from_node_id).first()
        tgt = db.query(SignalNode).filter(SignalNode.id == e.to_node_id).first()
        if not (src and tgt):
            continue
        w = confirm.edge_weight(_series(db, src.key), _series(db, tgt.key))
        if w is not None:
            e.weight = w; n += 1
    db.commit()
    return n
```
Call `recompute_edge_weights(db, domain=domain)` at the end of `run.py` (after `ingest_observations`).

*Why:* the LLM said an edge *exists*; this measures *how strongly* from data using your existing abs-Pearson `confirm.edge_weight`. `None` → the graph edge shows "pending" until enough paired windows exist. These weights power root-cause (the drifting gate's highest-weight moving signal is the suspect) and label the graph edges.

- [ ] **Step 2: Drift calculator (scalar + PSI) that writes to the existing drift UI**

```python
# app/services/signal_graph/drift.py  (bottom half)
def _psi(ref: list[float], cur: list[float]) -> float:
    # distribution drift: sum over aligned buckets of (cur% - ref%) * ln(cur%/ref%)
    tr, tc = (sum(ref) or 1.0), (sum(cur) or 1.0)
    psi = 0.0
    for r, c in zip(ref, cur):
        pr = (r / tr) or 1e-6
        pc = (c / tc) or 1e-6
        psi += (pc - pr) * math.log(pc / pr)
    return psi

def compute_drift(db: Session, *, baseline_id: int, write_alert: bool = True) -> dict:
    b = db.query(Baseline).filter(Baseline.id == baseline_id).first()
    if not b:
        return {"status": "unknown"}
    series = _series(db, b.metric)                    # the gate's value series
    if len(series) < 2:
        return {"status": "pending", "reason": "need >=2 windows"}
    reference, current = series[0], series[-1]
    drift_pct = (current - reference) / reference if reference else 0.0
    breached = (b.direction == "min" and current < b.target_value) or \
               (b.direction == "max" and current > b.target_value)
    status = "breached" if breached else ("drifting" if abs(drift_pct) > 0.10 else "healthy")
    if write_alert and status in ("breached", "drifting"):
        # writing a DriftAlert is what makes our gate appear in the EXISTING
        # /api/learning/drift_alerts UI. (Confirm DriftAlert columns vs models.py.)
        db.add(DriftAlert(baseline_id=b.id, status=status,
                          observed=current, baseline=reference, created_at=now()))
        db.commit()
    return {"status": status, "current": current, "reference": reference,
            "drift_pct": round(drift_pct, 4), "target": b.target_value}
```

*Why:* scalar drift compares the current vs reference window vs the user's `target_value` → healthy/drifting/breached; `_psi` (finished at build time) handles distribution gates. The key move: when a gate is breached/drifting we **write a `DriftAlert` row** — exactly what the **existing `/api/learning/drift_alerts` screen already reads** — so our gates surface in the drift UI you already have, **no new drift UI needed**. Still honest: `pending` until ≥2 windows.

- [ ] **Step 3: Add the endpoint** in `signal_graph.py`:

```python
from ..services.signal_graph.drift import compute_drift

@router.get("/baselines/{baseline_id}/drift")
def baseline_drift(baseline_id: int, db: Session = Depends(get_db)) -> dict:
    return compute_drift(db, baseline_id=baseline_id)
```

- [ ] **Step 4: Fold drift severity into the baseline-targets sort (Task 12)** — order accepted gates by (breached > drifting > healthy > pending), then by data `priority`. This is the "priority order of issue."

- [ ] **Step 3: Verify**

Run (backend up, after accepting a gate): `curl localhost:8000/api/signal-graph/baselines/1/drift`
Expected: `{"status":"pending", ...}` for a fresh gate (correct — no time series yet), or a healthy/drifting/breached verdict once ≥2 windows exist.

- [ ] **Step 4: Commit**

```bash
git add app/services/signal_graph/drift.py app/routes/signal_graph.py
git commit -m "feat(signal-graph): scalar drift calculation + endpoint"
```

---

## Task 14: Frontend — show score source + drift status

**Files:**
- Modify: `salesops-solution/frontend/src/api.ts` (add `sgDrift`), `pages/SignalGraph.tsx`

- [ ] **Step 1:** add `sgDrift: (baselineId: number) => jsonRequest<{status:string;[k:string]:any}>(\`/signal-graph/baselines/${baselineId}/drift\`)` to `api.ts`, and on each recommendation card show the `score` with a small tag from `score_source` (`data` vs `estimated`). After Accept, show the gate's drift `status` badge (`pending` / `healthy` / `drifting` / `breached`) by calling `sgDrift(baseline_id)`.

*Why:* makes the data-conditional behavior visible — the user sees "estimated" + "pending" before data exists, and real scores + a drift verdict once it does, without any fake numbers.

- [ ] **Step 2: Verify** in the browser: recommendation cards show a score + source tag; an accepted gate shows a `pending` drift badge (fresh) — confirming the full loop renders.

- [ ] **Step 3: Commit**

```bash
git add salesops-solution/frontend/src/api.ts salesops-solution/frontend/src/pages/SignalGraph.tsx
git commit -m "feat(signal-graph): show score source + drift status in UI"
```

---

## Out of scope for this plan (later)

- Richer per-client observation extraction (mapping specific signals to bespoke queries/log parsing) — v1 ingestion is best-effort row-counts.
- Background-task + polling for discovery (v1 is synchronous).
- Human-approval review gate.
- Live Solution-Fetch API (v1 is local-fixture).
- Multi-tenant columns / migration (v1 reuses `domain` = `session_id`).
- Tests (deferred; manual verification steps stand in).
