# General-Purpose Quality-Gate Discovery & Monitoring — Architecture Design

- **Date:** 2026-06-09
- **Status:** Design (v1, approved for implementation)
- **Scope of this doc:** the **Discovery layer** in implementation depth, plus the backend API and frontend integration needed to ship a v1. The recommendation engine already exists (and is generalized here); `extract.py` / `drift.py` (Task 2) are integrated at the boundary and get their own detail pass.

---

## 0. Goal & the one invariant

Build a system that, given **any** client's running software, can:
1. **discover** the quality signals the system emits and **propose** candidate baseline quality gates,
2. let the user **accept** a gate and **set its threshold**,
3. **backtrack** each gate to the signals that affect it, and
4. **monitor drift** of each gate over time and attribute it to a cause.

**The one fixed rule, everywhere:** the system proposes *which* gates and shows real context (typical ranges), but **the user sets every threshold** — never an algorithm, never the LLM. Enforced structurally: recommendations carry no `target_value`; a gate's number only exists once a user types it on accept.

## 1. The universal principle (why this generalizes)

A client can be anything — an agentic pipeline (keysight sales-ops), a content studio, or a plain CRUD todo app. We do **not** assume stages, agents, roles, or any fixed metric taxonomy. The only things that hold across all software:

- **Telemetry / traceback is always present** — running software emits observable signals (requests, status codes, errors, latency, logs, events, DB ops).
- **Human feedback is present only sometimes** — only when the system produces output a human judges or corrects (CSR edits, refine chat, profile edits). A pure CRUD app has none.
- **Everything else is discovered per client, never fixed** — what signals exist, what "quality" means, whether there are stages, what segments apply.

> Slogan: we fix the *grammar* (two evidence streams + the engine), and discover the *vocabulary* (signals, metrics, gates) per client.

## 2. High-level architecture (v1 flow — no approval gate)

```
 (tenant_id, session_id)
        │
        ▼
 SOLUTION-FETCH API → downloads the client's codebase zip → extract
        │
        ▼
┌─ DISCOVERY LAYER  (LLM, onboarding, two passes, automatic) ─┐
│   Pass 1: Signal Extraction  (facts, with file/line evidence)│
│   Pass 2: Gate Proposal      (judgments over the signals)    │
│   → Solution Model { signals[], candidate_gates[]+graph }    │
└───────────────┬──────────────────────────────────────────────┘
                ▼
        PERSIST directly  (SignalNode · SignalEdge · candidate gates)   ← no human review in v1
                ▼
        RECOMMENDATIONS  (scored once data exists; cold-start = LLM-proposed)
                ▼
        USER accepts + types threshold  → Baseline gate                 ← the invariant
                ▼
        DRIFT  (consolidate telemetry+feedback across all tiers,
                compare to baseline, walk edge weights → root-cause)
```

The user is still the **final human filter**: a weak LLM-proposed candidate simply sits as a dismissable recommendation; nothing becomes a live gate without a user accepting it and setting a number. That is why dropping the separate discovery-review gate is low-risk for v1.

## 3. Discovery layer (the new piece, in depth)

### Input acquisition — the Solution-Fetch API
The codebase is fetched (not uploaded) from ZBrain's solution-app API:
- `POST {SOLUTION_API_BASE}/solution-apps/download-app`  (staging base: `https://content.staging.zbrain.ai`, from env)
- Headers: `Authorization: Bearer <JWT>` (auth0 token, **from env/secrets — never hardcoded**; it expires, so a refresh/source strategy is a config concern), `Content-Type: application/json`, `Accept: application/json`
- Body: `{ "sessionId": "<uuid>", "tenantId": "<id>" }`
- Response: the client's solution as a downloadable app (zip), which we extract to a working dir.

`sessionId` identifies one solution/project (our continuous-learning scope); `tenantId` the owning org. (Confirmed: the example zips were produced by this exact call — e.g. `sessionId f8651fcd-…` = the tristone todo app.)

**v1 hardcode (local-fixture mode):** `fetch_solution(tenant_id, session_id)` keeps this signature but, behind an env flag `SOLUTION_FETCH_MODE` (default `local` for the demo), resolves `session_id` to a **local zip already in the repo** instead of calling the API — no bearer token, no network, no expiry. Swapping to the live API later is `SOLUTION_FETCH_MODE=live` with no downstream changes. The bearer JWT, when used, comes from env/secrets — never source.

Then an LLM/agent reads the **whole codebase** (docs *and* source) — the only approach that generalizes across arbitrary languages/frameworks. It runs in **two passes**, back-to-back and automatic.

### Pass 1 — Signal Extraction (facts)
Outputs verifiable facts about what the system observably emits:

```jsonc
Signal {
  key:         "post_title_400",                        // stable id
  description: "POST /api/todos returns 400 when title missing",
  stream:      "telemetry" | "feedback",                // the ONLY fixed categorization
  observable:  "status_code",                           // free-text hint, NOT a fixed enum
  evidence:    "backend/src/routes/todos.ts:42 | spec.md:177",
  segment_hint?: "endpoint:POST /todos"                 // optional
}
```

### Pass 2 — Gate Proposal (judgments)
Takes **only the Signal list** (not the codebase again) and proposes candidate gates:

```jsonc
CandidateGate {
  key:         "validation_error_rate",
  description: "rate of POST creates rejected for missing title",
  direction:   "min" | "max",
  compute:     "rate",                  // whitelist: rate|ratio|p95|psi|count|mean
  inputs:      ["post_title_400"],      // signal keys → THESE ARE THE GRAPH EDGES (gate ← signals)
  segment_dimension?: "endpoint",       // discovered; may be "global"
  rationale:   "validation failures indicate client/contract drift"
  // NO threshold — the user sets it on accept (invariant)
}
```

The `inputs` mapping **is the backtrack graph** — discovery produces the graph for free.

### Components (focused units)
| Unit | Responsibility | Depends on |
|---|---|---|
| `services/signal_graph/discovery/fetch_solution.py` | call the Solution-Fetch API with `(tenant_id, session_id)`, download + extract the codebase zip to a working dir | external API, config (base URL, bearer token) |
| `services/signal_graph/discovery/schema.py` | `Signal` + `CandidateGate` pydantic schemas (the contracts) | — |
| `services/signal_graph/discovery/extract_signals.py` | Pass 1: run the agent, return validated `Signal[]` | LLM client, schema |
| `services/signal_graph/discovery/propose_gates.py` | Pass 2: signals → validated `CandidateGate[]` | LLM client, schema |
| `services/signal_graph/discovery/run.py` | orchestrate Pass 1→2, persist the Solution Model | the two passes, persistence |

LLM output is **structured-output / schema-validated** with one repair attempt; a hard failure marks the run failed and persists nothing.

## 4. Persistence (reuse existing models)

- each `Signal` → `SignalNode` (leaf node, `source_stream`-tagged)
- each `CandidateGate` → a candidate row (reuse `BaselineRecommendation`, which already has **no `target_value`**) + a `baseline_target` `SignalNode`
- each `inputs` edge → `SignalEdge` (gate ← signal), `weight=None` until observations arrive
- evidence stored on nodes (in `meta`) for later inspection/debugging
- **identity / multi-tenancy:** every row is scoped by **`(tenant_id, session_id)`**. `session_id` is the per-solution continuous-learning key (it supersedes the old abstract `domain`); `tenant_id` is the owning org. Two solutions never mix, even within one tenant.

## 5. Engine — what is kept vs retired

| File | Fate | Why |
|---|---|---|
| `metric_specs.py`, `domain_config.py` | **retired** | the hardcoded keysight catalog is replaced by per-client discovery |
| `scanner.py` (enumerate + build subgraph) | **retired** | discovery produces candidates + graph |
| `recommender.py` (volume/variance scoring) | **kept** | scores discovered candidates once data exists |
| `confirm.py` (distribution, variance, edge weight = abs Pearson) | **kept** | the data-analysis core; math unchanged, domain-agnostic |
| `backtrack.py` | **kept, slimmed** | now *persists the discovered graph + fills edge weights from data*, instead of building structure from specs |

The statistical engine survives intact; only the hardcoded keysight content is replaced. Scoring stays the same blend (busyness `log10(volume+1)/3`, explainability bonus, wobble from variance) and runs once observations exist.

## 6. Backend API — `app/routes/signal_graph.py`

New `APIRouter`, registered in `main.py` following the existing pattern:
```python
app.include_router(signal_graph.router, prefix="/api/signal-graph", tags=["signal-graph"])
```
Uses `get_db` + `require_role` (same RBAC as `learning.py`). v1 endpoints (no approve/revise):

| Method / path | Purpose |
|---|---|
| `POST /api/signal-graph/discover` | body `{ tenant_id, session_id }`; fetches the codebase via the Solution-Fetch API, runs discovery; long-running → returns `{ run_id }` (background task) |
| `GET  /api/signal-graph/discovery/{run_id}` | poll status + summary (counts of signals/gates discovered) |
| `GET  /api/signal-graph/recommendations` | scored candidate gates (recommender output) |
| `POST /api/signal-graph/recommendations/{id}/accept` | body `{ target_value }` → creates a `Baseline` (**user threshold**) + triggers backtrack |
| `POST /api/signal-graph/recommendations/{id}/dismiss` | dismiss a candidate |
| `GET  /api/signal-graph/baselines/{id}/graph` | the backtrack graph: nodes + edges + weights |
| drift | **reuse** existing `GET /api/learning/drift_alerts` |

Discovery is long-running (LLM crawling a codebase), so `discover` returns a `run_id` the client polls — consistent with the project's plain-REST style (no SSE).

## 7. Frontend integration (what we reuse + what is new)

The frontend (`salesops-solution/frontend`, React 18 + Vite + TS, plain `fetch` client in `api.ts`) is already well prepared. We **reuse aggressively** and add a small, focused surface.

### Already there — reuse, don't rebuild
- **Typed API client** `api.ts` (`BASE="/api"`, `jsonRequest<T>` helper) and types `Baseline`, `BaselinesResponse` (`last_status: healthy|drifting|breached`), `DriftAlert`, `LearningOpportunity`, plus `learningBaselines/learningDriftAlerts/learningOpportunities` functions.
- **Graph rendering stack** — `pages/ProcessFlow.tsx` already uses **`@xyflow/react` + `dagre`** to lay out and render an interactive node/edge graph with stage bands, hover-highlight, and a KPI rail. The signal-graph viewer reuses this exact stack.
- **Drift surface** — `DriftAlert` types and the `/api/learning/drift_alerts` feed already exist; the drift view lights up by pointing at our gates.

### New frontend to build (kept minimal for v1)
1. **`api.ts` additions** — typed functions + types for the new `/api/signal-graph/*` endpoints:
   - types: `DiscoveredSignal`, `CandidateGate` (recommendation), `SignalGraph { nodes, edges }`.
   - functions: `sgDiscover()`, `sgDiscoveryStatus(runId)`, `sgRecommendations()`, `sgAcceptRecommendation(id, targetValue)`, `sgDismissRecommendation(id)`, `sgBaselineGraph(baselineId)`.
2. **`hooks/useSignalGraph.ts`** — fetch + poll discovery status, fetch recommendations/graph (matches the existing hook style).
3. **`pages/SignalGraph.tsx`** — one new page composed of three sections:
   - **Discover** — a button to trigger `POST /discover`, with a status/progress indicator polling `discovery/{run_id}`.
   - **Recommended gates** — a ranked list/cards of candidate gates (score, rationale, evidence). Each card has **Dismiss** and **Accept**; Accept opens a small inline **threshold input** (the user types the number) → `accept`. (New, simple component; models on existing list/card patterns and `ui.tsx` primitives.)
   - **Signal graph** — render the accepted gate's backtrack graph via the **reused `@xyflow/react` + dagre** setup: nodes = signals/stage(optional)/gate, edges labelled with weights; high-weight edges emphasized. (New node/edge mapping; reuses the rendering infra and layout helpers extracted from `ProcessFlow.tsx`.)
4. **Routing + nav** — add `<Route path="/signal-graph" element={<SignalGraphPage/>} />` in `App.tsx` and a nav entry in `components/Layout.tsx` (e.g. label "Quality Gates").
5. **Drift** — reuse the existing `DriftAlert` UI / `learningDriftAlerts()`; our accepted gates become the baselines it reports on.

### New-frontend summary
| Item | New or reuse |
|---|---|
| graph rendering (`@xyflow/react`+dagre) | **reuse** (from ProcessFlow) |
| `Baseline`/`DriftAlert`/`LearningOpportunity` types + drift feed | **reuse** |
| `api.ts` signal-graph functions + types | **new (small)** |
| `useSignalGraph` hook | **new (small)** |
| `SignalGraph.tsx` page: Discover + Recommended gates + Graph | **new** |
| route + nav entry | **new (tiny)** |

## 8. Observations & drift (Task 2 — integrated at the boundary)

- **`extract.py`** — ingest the client's real signal data → `SignalObservation` rows tagged with `source_stream` (telemetry/feedback) + tier (e.g. L4/L3/L2). Lights up **both** the recommender's scoring **and** drift.
- **`drift.py`** — for each gate: **consolidate both streams across all tiers** into a current value (this is the self-blinding fix — telemetry covers every case, feedback calibrates the reviewed subset), then compare to baseline:
  - **scalar metrics** → relative change vs. tolerance, respecting `direction`/`target`.
  - **distribution metrics** → **PSI** (`Σ (curr%−ref%)·ln(curr%/ref%)`), alert above threshold (~0.15).
  - **root-cause** → walk the gate's incoming edges; the high-`weight` signal that also moved is the probable cause.
- Wired as a periodic detector; alerts surface through the existing `/api/learning/drift_alerts` UI.
- **Graceful degradation:** a client with no feedback stream (todo app) runs telemetry-only drift; "one stream empty" is handled naturally.

## 9. Error handling & generality

- LLM output **schema-validated** (structured output) with one repair attempt; hard fail → run marked failed, **nothing persisted**.
- **Evidence required** on every signal/gate (file/line) so a human can verify — essential when clients are arbitrary.
- **Cold-start:** brand-new client, no data → LLM proposals stand alone; scoring + edge-weights stay deferred until observations arrive.
- **No-feedback clients:** telemetry-only; no self-blinding to fix.
- **Isolation:** all keyed by `domain`; one client never affects another.

## 10. Build order (v1, by deadline)

```
1. discovery/schema.py + extract_signals.py (Pass 1) + propose_gates.py (Pass 2) + run.py
2. persist Solution Model; slim backtrack.py to persist discovered graph
3. routes/signal_graph.py (+ register in main.py); reuse /api/learning/drift_alerts
4. frontend: api.ts additions + useSignalGraph + SignalGraph.tsx (Discover / Recommended gates / Graph) + route+nav
5. extract.py → SignalObservation (also lights up scoring)   [Task 2 pt 1]
6. drift.py → consolidate + compare + root-cause; reuse drift UI  [Task 2 pt 2]
```

## 11. Deferred to later passes (not "out of scope")

These get built; just not detailed here:
- the LLM prompts / codebase-crawl strategy (tuned against the three example zips during implementation),
- `extract.py` / `drift.py` internals (own detail pass),
- the human-approval/review gate (intentionally dropped for v1; revisit post-demo),
- tests (deferred — golden-tests-per-example-client + keysight parity remain the eventual check).
