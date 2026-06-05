# Signal Graph — Baseline Recommender + Dual-Input Drift — Design

> **Status:** Design / spec for review.
> **Scope:** Two connected backend subsystems requested by the senior developer, built on one shared artifact (a Signal Dependency Graph). Frontend is **out of scope** for this plan — we deliver the backend plus clean API contracts; the Continuous-Learning UI lives in the separate **ZBrain Orchestrator** app and is built by that team.
> **Audience:** Backend engineers (Python / FastAPI / SQLAlchemy) working in `salesops-solution/backend`.

---

## 1. The two tasks (in the senior developer's words, restated)

### Task 1 — Baseline recommender + signal backtracking
1. A system/agent that **inspects the solution** (here: Keysight) and **recommends baseline quality gates** to the user.
2. The user can **also add their own** gates beyond what the system recommends.
3. For **both** kinds of gate (recommended and user-added), a system that **walks backward** from the gate to **derive which input signals and data affect it**.
4. **The expected/target number is always set by the human (admin/CSR), never by an algorithm.** The system may *show* a historical distribution as context, but it never sets the number.

### Task 2 — Dual-input drift over all autonomy tiers
1. Treat the two input sources as first-class: **feedback** (CSR corrections) and **agent traceback activity** (the agent's own per-case log).
2. **Analyze all cases — L2, L3, and L4** — not just human-reviewed ones, so fully-automated cases stop being invisible.
3. **Consolidate** both streams, **map the consolidated signals to the baseline targets** (using Task 1's signal map), and **compute drift** from the combined picture.

### How they connect
They are one system sharing one backbone — the **Signal Dependency Graph**. Task 1 builds and recommends it; Task 2 fills it with consolidated observations and computes drift over it.

---

## 2. What exists today (grounded findings)

**Baselines (Task 1 area):**
- `Baseline` model (`app/models.py:704–761`): `metric, segment, direction, target_value, drift_pct, severity, rollup_strategy, source, rationale`, plus observed-value bookkeeping. **No field records which signals affect a baseline.**
- Admin creates a baseline via `POST /baselines` (`app/routes/learning.py:1496`) and **supplies `target_value` directly** (`BaselineIn.target_value: float`). **No code auto-computes a target** — so "human sets the number" already matches reality.
- The relationship "metric → which signals feed it" is **implicit**, hardcoded inside `_observe_metric_impl()` (`app/services/monitor.py:632–996`). There is **no lineage / backtrack / provenance** concept anywhere.

**Inputs and drift (Task 2 area):**
- **Feedback** (`app/models.py:540–554`): `kind` (edit/approve/reject/restore), `stage`, `pipeline_id`, before/after in `data`. Exists only when a human touched a case.
- **Agent traceback**: `TraceEvent` (`app/models.py:509–518`): per-case, per-stage `stage/kind/duration_ms/data` (stage_start/end/error, hitl_created, integration failures). Plus the `Pipeline` row's per-stage output JSON (`extracted, decision, confidence, customer_match, autonomy_tier, shadow_classification, status`). **Exists for every case — L2/L3/L4.**
- The 8 detectors and the metric observers each use **one stream or the other, never consolidated** (`app/services/monitor.py:1475–1484` lists the detectors). Critically, the accuracy metrics (`intent_classification_accuracy`, `language_detection_accuracy`) are **feedback-only**, so a fully-automated L4 case contributes zero edits and makes accuracy look **perfect exactly where no human checked** (self-blinding).

---

## 3. Guiding decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Source of truth for recommending gates + backtracking signals | **Hybrid: structure first (deterministic, complete), data second (rank + confirm)** |
| Depth of backtracking | **Layered dependency graph**: `baseline_target ← metric ← stage_outcome ← raw_signal` |
| Build approach | **Approach A** — declarative Signal Registry + deterministic scanner/backtracker; LLM only to bootstrap and always human-verified |
| Who sets the target number | **The human.** System shows a context hint, never the number itself |
| Frontend | **Out of scope** — backend + API contracts only; Orchestrator team builds screens |

---

## 4. Architecture

One shared, stored, queryable artifact — the **Signal Dependency Graph** — with six components around it.

```
                         ┌─────────────────────────────────────┐
                         │      SIGNAL DEPENDENCY GRAPH          │
                         │  baseline_target ← metric ←           │
                         │     stage_outcome ← raw_signal        │
                         └─────────────────────────────────────┘
                            ▲          ▲                ▲
            builds/ranks    │          │ resolves       │ fills with
                            │          │ subgraph        │ observations
        ┌───────────────────┘   ┌──────┘          ┌──────┘
┌───────────────┐   ┌────────────────────┐  ┌──────────────────────┐
│ RECOMMENDER   │   │   BACKTRACKER      │  │  SIGNAL EXTRACTOR     │
│ (Task 1)      │   │   (Task 1)         │  │  / CONSOLIDATOR       │
│ scanner +     │   │ derive signals for │  │  (Task 2)             │
│ confirmer     │   │ ANY gate, keep     │  │ feedback + traceback  │
│ → ranked recs │   │ current            │  │ for ALL tiers         │
└───────────────┘   └────────────────────┘  └──────────────────────┘
        │                       │                 │
        ▼                       ▼                 ▼
  admin reviews,          GET /baselines/    DRIFT-OVER-GRAPH:
  SETS THE NUMBER,        {id}/signals       compute target from
  accepts gate            (the lineage)      consolidated signals,
                                             attribute breach to
                                             top upstream causes + tier
```

### Components and where they live
A new package `app/services/signal_graph/`, small additions to `app/models.py`, `app/services/baselines.py`, `app/services/monitor.py`, and `app/routes/learning.py`.

| Component | File | Responsibility | Depends on |
|---|---|---|---|
| Graph + observation models | `app/models.py` (+ `SignalNode`, `SignalEdge`, `SignalObservation`, `BaselineRecommendation`) | Persist nodes, "affects" edges, consolidated observations, and recommendation state | DB |
| MetricSpec registry | `signal_graph/metric_specs.py` | Declare each metric's stage / segment dimension / inputs / compute — the structural source of truth | — |
| Solution scanner | `signal_graph/scanner.py` | Structure pass: enumerate candidate gates + structural subgraphs | MetricSpec registry, intent/stage/integration config |
| Data confirmer | `signal_graph/confirm.py` | Data pass: rank candidates, score edge weights from history | history (Pipelines/Traces/Feedback) |
| Recommender | `signal_graph/recommender.py` | Combine scanner + confirmer → ranked recommendations | scanner, confirmer |
| Backtracker | `signal_graph/backtrack.py` | Resolve + persist + keep-current the subgraph for any gate | graph model, confirmer |
| Signal extractor / consolidator | `signal_graph/extract.py` | Per case, all tiers → normalized `SignalObservation` from both streams | TraceEvent, Pipeline, Feedback |
| Drift-over-graph | extends `monitor.detect_baseline_violations` | Compute target from consolidated signals; attribute breach to causes + tier | graph + observations |
| API | `routes/learning.py` | Recommendation, signals, drill-down endpoints | recommender, backtracker |

### End-to-end data flow
1. **Recommend** — scanner enumerates candidate gates → confirmer ranks + weights → admin sees a ranked list with each gate's signal subgraph and a *context number*.
2. **Set the number** — admin accepts a gate (or adds their own) and types `target_value`; a `Baseline` row is created.
3. **Backtrack** — for that gate (recommended or hand-added) the Backtracker resolves and persists the upstream subgraph with data-confirmed weights.
4. **Consolidate** — the extractor turns every case's feedback + traceback into normalized observations, including L4 cases with no human feedback.
5. **Detect drift** — each gate's target is computed from those consolidated signals (population-wide), compared to the human-set number, and any breach is explained by walking the graph to the upstream signals that moved most, broken down by tier.

### Two keystone choices
- **MetricSpec registry is the keystone.** Instead of re-parsing `_observe_metric_impl` at runtime, each metric's inputs are *declared once*. This makes the graph buildable, testable, and general, and it doubles as the metric registry the broader framework needs later.
- **"Context numbers, not target numbers."** The data pass computes a metric's historical distribution (median, p10–p90) and *shows* it next to the input box; the human still types the target. The machine never sets it.

---

## 5. Data model

### Table 1 — `SignalNode` (the things in the graph)
| Field | Meaning |
|---|---|
| `id` | PK |
| `node_type` | `baseline_target` \| `metric` \| `stage_outcome` \| `raw_signal` |
| `key` | canonical id, e.g. `target:extraction_completeness@intent:po_intake`, `metric:extraction_completeness`, `stage:extract`, `raw:trace:extract:stage_error`, `raw:pipeline:extracted.ship_to` |
| `label`, `description` | human-readable |
| `source_stream` | raw signals only: `feedback` \| `traceback` |
| `baseline_id` | FK → `Baseline`, set only for `baseline_target` nodes |
| `spec_ref` | metric nodes: which MetricSpec defines it |
| `domain` | solution/tenant id (e.g. `keysight`) — enables generality |
| `meta` (JSON), `created_at`, `updated_at` | — |

### Table 2 — `SignalEdge` (the "affects" arrows)
Backtracking = follow incoming edges of a target upstream.
| Field | Meaning |
|---|---|
| `id`, `domain` | — |
| `from_node_id` | upstream cause/signal |
| `to_node_id` | downstream affected metric/target |
| `relation` | `affects` |
| `origin` | `structural` \| `statistical` \| `llm` \| `manual` |
| `weight` | 0–1 strength from the data pass; `null` until enough history |
| `evidence` (JSON) | `{correlation, sample_size, window, last_computed_at}` |
| `status` | `active` \| `suggested` (needs human confirm) \| `rejected` |
| `created_at`, `updated_at` | — |

### Table 3 — `SignalObservation` (the consolidated evidence — heart of Task 2)
One row = one signal's value, in one segment, one window — split by stream and tier.
| Field | Meaning |
|---|---|
| `id`, `domain` | — |
| `signal_key` | which node this measures (indexed) |
| `segment` | e.g. `intent:po_intake`, `global` |
| `window_start`, `window_end` | the time bucket |
| `value`, `sample_size` | measured number, count of cases |
| `source_stream` | `feedback` \| `traceback` \| `consolidated` (store each stream **and** the merged value) |
| `autonomy_tier` | `L4_AUTO` \| `L3` \| `L2` \| `null` (all) — enables "mostly L4-auto" attribution |
| `meta` (JSON), `created_at` | — |

Indexes: `(signal_key, segment, window_start)`, `(domain)`.

### Table 4 — `BaselineRecommendation` (recommendation state)
| Field | Meaning |
|---|---|
| `id`, `domain` | — |
| `metric`, `segment`, `direction` | the proposed gate |
| `score` | ranking score |
| `rationale` | plain-English why |
| `context_stats` (JSON) | `{median, p10, p90}` — shown as a hint, never the target |
| `subgraph_snapshot` (JSON) | the structural dependency preview |
| `status` | `open` \| `accepted` \| `dismissed` |
| `created_at`, `updated_at` | — |

### In-code registry — `MetricSpec` (structural source of truth)
A declared list the scanner reads. Example:
```python
MetricSpec(
  key="extraction_completeness",
  stage="extract",
  segment_dimension="intent",     # → one gate per intent
  direction="min",
  inputs=[
    Input("raw:pipeline:extracted.{required_field}", stream="traceback", role="field_present"),
    Input("raw:trace:extract:stage_error",           stream="traceback", role="stage_health"),
    Input("raw:feedback:edit:extract",               stream="feedback",  role="human_correction"),
  ],
  compute=extraction_completeness_fn,   # how to combine consolidated inputs
)
```
One declaration tells the scanner *what gate to recommend, which raw signals feed it, and how to compute its value from consolidated observations.* Swap the MetricSpecs → the engine works for any domain.

---

## 6. The Recommender (Task 1)

**Pass 1 — Solution scanner (structure).** Reads the MetricSpec registry, intent definitions (required fields per intent), pipeline stages, integrations, and autonomy tiers. For each MetricSpec it expands by `segment_dimension` to enumerate candidate gates, and builds each one's structural subgraph from the spec's inputs. Deterministic, complete, no number.

**Pass 2 — Data confirmer (evidence).** Over recent history (e.g. 90 days), per candidate: volume, variability (robust spread), breach-proneness, signal coverage, and a **context distribution** (median, p10–p90). For each structural edge, correlation between upstream signal and target → fills `weight`. Surprising correlations not predicted by structure are added as `suggested` edges.

**Pass 3 — Ranking.** Transparent score: rank ↑ when volume is high, the metric moves, it has breached before, and it has at least one strong upstream signal (so future drift is explainable); rank ↓ for tiny volume / near-constant / no signal coverage.

**Pass 4 — Output.** Each recommendation: `{metric, segment, direction, rationale, context_stats, subgraph_preview, status}`. On **Accept**, the admin types `target_value` → creates the `Baseline`, persists the subgraph as `active`, triggers the Backtracker. Re-runs on a schedule; `BaselineRecommendation.status` keeps dismissed/accepted ones from re-nagging.

Purely additive: never creates a gate by itself, never sets a number.

---

## 7. The Backtracker (Task 1)

Owns the signal map for **every existing gate** — recommended or hand-added. Four responsibilities:

1. **Resolve** the upstream subgraph from three declared sources: MetricSpec inputs (direct raw signals), **pipeline stage order** (cross-stage upstream links, e.g. extract is fed by intake), and declared metric-to-metric dependencies. Same structural expansion the scanner uses.
2. **Confirm** each edge's weight + evidence from history.
3. **Handle two cases:**
   - **Case A — known metric (the normal path).** Every baseline today references a declared metric, so the map is derived automatically from the spec + stage order — including for **user-added** gates. This satisfies "user-added gates must also be backtracked."
   - **Case B — metric with no spec (future/new domains).** Fall back to statistical discovery (correlate candidate signals against the target's history) and optional LLM bootstrap; everything produced is `suggested` until a human confirms. Rarely hit today; exists for generality.
4. **Keep current.** Re-runs on a schedule: recompute weights, promote human-confirmed `suggested` edges, demote edges that lost correlation.

Exposes the resolved subgraph via `GET /baselines/{id}/signals`.

---

## 8. The Signal Extractor / Consolidator (Task 2)

**Two extractors:**
- **Traceback extractor — every case (L2/L3/L4):** reads `TraceEvent` + `Pipeline` JSON → `raw:pipeline:extracted.{field}` (present?), `raw:trace:{stage}:stage_error`, `raw:trace:{stage}:duration_ms`, `raw:pipeline:confidence`, `raw:pipeline:shadow_classification`, integration `send_error`, etc.
- **Feedback extractor — reviewed cases only:** reads `Feedback` → `raw:feedback:edit:{stage}` / `:{field}`, approve/reject/restore.

**Normalization:** every observation tagged `(signal_key, segment, window, source_stream, autonomy_tier, value, sample_size)`; aggregated per group **and** rolled up into a `consolidated` / `tier = all` row.

**Consolidation rule (the core idea):**
- **Traceback = coverage** — exists for all cases, the base population measurement.
- **Feedback = ground truth** — higher quality, biased to the reviewed slice.
- **Directly-observable metrics** (completeness, latency, error rate): traceback measures them across all cases with no human; feedback corroborates → L4 visible.
- **Accuracy-type metrics** (historically human-labeled): stop assuming "no feedback = correct." Extend coverage to L4 via **traceback proxies** (shadow disagreement, downstream rework, confidence, later corrections), **calibrated** against feedback where it exists.

**Disagreement is a signal.** When feedback contradicts the traceback proxy, the human wins for that case and the disagreement is recorded — a calibration signal and the natural hook for a future **trust-weighting** layer (down-weighting unreliable feedback). The trust subsystem itself is out of scope here; the seam is left in place.

**Runtime:** `extractor.consolidate_window(db, domain, window)` on each monitoring tick, bucketed into the same windows the drift detector uses; idempotent per `(signal, segment, window, stream, tier)`; reuses existing segment resolution.

---

## 9. Drift-over-Graph (Task 2)

For each enabled gate, per tick:
1. **Read** subgraph + consolidated observations for recent vs baseline window.
2. **Compute** the target's observed value via `MetricSpec.compute` across all tiers.
3. **Compare** to the **human-set** `target_value ± drift band` → `healthy/drifting/breached` (proper two-window comparison).
4. **Attribute:** walk upstream; rank signals by *(movement) × (edge weight)* → top contributors, likely cause, tier breakdown.
5. **Emit** an enriched `DriftAlert` — reusing the existing `top_contributors` and `baseline_id` fields on the model (no new alert table), now filled with graph-derived content.

---

## 10. API contracts (for the Orchestrator team)

**Task 1**
- `GET /baselines/recommendations` → `[{id, metric, segment, direction, score, rationale, context_stats:{median,p10,p90}, subgraph_preview, status}]`
- `POST /baselines/recommendations/{id}/accept` → body `{target_value, drift_pct?, severity?}` (**target_value required**) → creates `Baseline`, persists subgraph, returns baseline
- `POST /baselines/recommendations/{id}/dismiss`
- `GET /baselines/{id}/signals` → `{nodes:[…], edges:[{from,to,weight,origin,status,evidence}]}`
- `POST /baselines/{id}/signals/edges/{edge_id}/confirm | /reject`

**Task 2**
- `GET /learning/drift_alerts` *(enriched)* → each alert carries `top_contributors`, `tier_breakdown`, `likely_cause`, `recommended_fix_area`
- `GET /baselines/{id}/observations?window=…` → consolidated signals split by stream & tier

**Unchanged:** `POST/PATCH/DELETE /baselines` keep working (admin still sets `target_value` directly); create now triggers the Backtracker.

---

## 11. Error handling

- **Isolation, not silence:** a failure on one signal/metric/case logs and skips — it never kills the batch (mirrors today's per-detector `try/except`) — but **no silent `return 0`**; errors are recorded to a health surface so a broken extractor is visible.
- **Sample-size gate:** the Confirmer assigns an edge weight only with enough history; below that the edge stays `structural` with `weight=null` (not a false "weak").
- **Backtracker always returns something** (Case B → `suggested`).
- **Idempotency:** observations and recommendations are keyed so re-runs don't duplicate.
- **Statistics guards:** handle empty windows and division-by-zero explicitly.

---

## 12. Testing (TDD, synthetic data + worked numbers)

- **Scanner:** fixture solution → asserts exact candidate gates + structural subgraph.
- **Confirmer:** constructed history → asserts edge weights + ranking order.
- **Backtracker:** Case A (known metric → correct map), Case B (unknown → `suggested` edges), keep-current (weights update).
- **Extractor (key regression):** an L4 case with no feedback still produces traceback observations — proves self-blinding is fixed.
- **Consolidation:** the pay-stub/ship_to scenario — completeness drops only because traceback sees it; a feedback-only computation would miss it.
- **Drift-over-Graph:** seeded drift → asserts breach + correct top-contributor attribution + tier breakdown.
- **API contract tests** for every endpoint.

---

## 13. Suggested build order (detailed in the implementation plan)

1. **Foundation** — data model (4 tables + `MetricSpec` registry) + **Extractor** (Task 2 base).
2. **Structure** — `MetricSpec`s for the 12 existing metrics + **Scanner**.
3. **Recommend** — **Confirmer** + **Recommender** + recommendation API.
4. **Backtrack** — **Backtracker** + signals API.
5. **Drift** — **Drift-over-Graph** + enriched alerts + drill-down API.

Tasks 1 and 2 share the graph and specs; the foundation (step 1) and structure (step 2) unblock both. Detailed step-by-step tasks are produced in the writing-plans phase.

---

## 14. Out of scope (deliberately)

- **Frontend / Orchestrator screens** — we deliver API contracts only.
- **The full trust-scoring subsystem** — only the seam (disagreement recording) is left in place.
- **Auto-setting target numbers** — explicitly excluded; the human always sets the number.
- **The broader `cl_core` framework migration** — this design is compatible with it (the MetricSpec registry and ports-style separation align), but that migration is a separate effort.

---

## Appendix A — Worked example (LendFast, a non-Keysight domain)

A loan processor with fields `annual_income, credit_score, employment_status, loan_amount, applicant_name`; stages `intake → extract → verify → decide → notify`; most applications auto-decided, borderline ones reviewed.

1. **Recommend:** scanner sees "Loan Application requires 5 fields" + a completeness metric + high volume → recommends a gate on *Extraction Completeness for Loan Applications*, context ~0.90. Admin types **0.92**.
2. **Backtrack:** derives `target ← extraction_completeness ← extract stage ← {annual_income, credit_score…} + extract stage_error + OCR confidence + intake intent (weak)`; data confirms OCR confidence is the strong driver.
3. **Consolidate:** a new pay-stub format breaks OCR; `annual_income` goes missing on many **auto-decided** applications (no human feedback). Traceback still records the misses across all cases → completeness drops to **0.85**.
4. **Drift:** 0.85 < 0.92 → breach, attributed to *OCR confidence ↓, missing field annual_income, mostly L4-auto*. The old feedback-only system would have shown "fine."

The steps are identical to the Keysight PO-email case — proving the engine is domain-agnostic.
