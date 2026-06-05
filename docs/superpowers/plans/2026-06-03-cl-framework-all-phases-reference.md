# Continuous-Learning Framework — Complete Implementation Reference (All Phases)

> **Purpose:** A single, self-contained reference for engineers implementing the migration of the Keysight continuous-learning (CL) module into a general, self-adapting framework. It spans all nine phases (0–8). It is a **living document**: refine, re-sequence, and correct each phase as implementation reveals reality.
>
> **Audience:** Backend engineers (Python/FastAPI/SQLAlchemy) who may have little prior context on this codebase.
>
> **Status:** Reference / handoff. Phase 0 has a fully step-by-step companion plan (`2026-06-03-cl-framework-phase0-foundations.md`); later phases are at reference granularity and will get their own detailed plans when started.

---

## 0. How to use this document

- **Read Sections 1–4 first.** They explain the problem, the guiding principle, the target architecture, and the conventions every phase follows. Without them, the phases read like disconnected refactors.
- **Each phase (Section 6) is self-contained software.** It states its goal, what it depends on, the files/components it produces, representative tasks, which design mechanisms/fixes it lands, whether it changes behaviour, how to test it, its Definition of Done, and its risks.
- **The migration is additive-then-cutover, not rip-and-replace.** The new framework (`cl_core`) is built alongside the existing code. Existing behaviour is preserved until a phase explicitly runs the new path in shadow, compares it, and cuts over. Nothing user-facing breaks midway.
- **Trace coverage with the appendix.** Appendix A maps every frozen number → its adaptive mechanism → the phase that lands it. Appendix B maps every shortcoming → the phase that fixes it. Use these to verify nothing is dropped as phases get edited.

**Source design documents (read for the "why" and the math):**
- `docs/superpowers/specs/2026-06-03-continuous-learning-framework-design.md` — architecture: 9 ports, DomainProfile, Adaptive Parameter Engine, the 8-phase migration, plain-English shortcomings (Groups A–F).
- `docs/superpowers/specs/2026-06-03-continuous-learning-adaptive-mechanisms.md` — deep failure modes (systemic + statistical bugs), the 9 adaptive algorithms with worked numbers, an end-to-end worked example.

---

## 1. The problem in one paragraph

The CL loop (capture → observe → detect → generate → validate → promote → watch) is conceptually sound, but its intelligence is **frozen into constants and welded to Keysight**. Email types, team queues, field names, integrations, quality targets, statistical thresholds, time windows, and scoring formulas are all hardcoded. Several core calculations are not merely rigid but **statistically biased or wrong** (e.g. the drift z-score uses the wrong variance; accuracy is measured only on human-reviewed cases, so the system can blind itself). The goal is a framework whose behaviour **adapts to the input it receives**, is statistically correct, and is reliable enough to run in production.

## 2. The guiding principle: Configure, Derive, or Learn — never hardcode

For every tunable value, apply the first that fits:
1. **Configure** — domain/policy facts the operator declares (email types, stages, approval rules).
2. **Derive** — values that should reflect the data, computed from incoming signals (a segment's own variability, a field's own error rate).
3. **Learn** — values that should reflect what actually works, learned from outcomes (the real value of a "warning" alert, the success rate of a fix type).

A single component, the **Adaptive Parameter Engine**, serves every number in this priority order (Learned → Derived → Configured → Fallback) and records which source it used, so decisions are auditable. Today's hardcoded constant becomes the *last-resort fallback*, not the only option.

## 3. Target architecture (recap)

**Ports & Adapters ("hexagonal").** A domain-agnostic **CL Core** (the loop, the data model, the orchestration) depends only on **9 ports** (interfaces). All Keysight specifics live in **one adapter package** implementing those ports. A new domain = a new adapter set; the core never changes.

**The 9 ports:** `SignalSource`, `SignalTrustScorer` *(new)*, `Metric`/`MetricRegistry`, `BaselineSynthesizer` *(new behaviour)*, `DriftDetector`, `CandidateGenerator`, `KnowledgeStore`, `Evaluator`, `Promoter`. A thin **Repository** seam keeps the core off SQLAlchemy/the salesops schema.

**The DomainProfile** is the one object a domain supplies: its port implementations, its declared vocabularies (segment dimensions, change types, metric names), and its parameter engine. The core reads only the DomainProfile.

## 4. Conventions every phase follows

- **TDD:** write the failing test → see it fail → implement → see it pass → commit. Tests use the worked numbers from the design docs wherever possible.
- **Pure Python for math:** no numpy/scipy. `cl_core` stays dependency-light and portable. (pydantic 2.x is already a project dependency and is used for typed contracts.)
- **Frequent commits**, each ending with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Behaviour-preserving until cutover:** new code runs in shadow and is compared to the old path before replacing it. Each behaviour-changing switch sits behind a flag with an A/B comparison recorded.
- **Test command (Windows):** `salesops-solution/backend/.venv/Scripts/python -m pytest`.
- **Package root:** `salesops-solution/backend/app/`; the framework lives at `app/cl_core/`, adapters at `app/cl_core_adapters/salesops/` (created in Phase 2).

## 5. Sequencing and dependency graph

```
Phase 0  Foundations            (no deps)            ── contracts + stats, additive
Phase 1  Repository layer       (needs 0)            ── data access behind interfaces
Phase 2  Wrap existing as       (needs 0,1)          ── ports populated; outputs match old
         adapters
Phase 3  Adaptive Parameter     (needs 0,2)          ── unfreeze the math (shadow→switch)
         Engine integration
Phase 4  Signal trust           (needs 0,1,2,3)      ── new accuracy subsystem
Phase 5  Dynamic baselines +    (needs 0,1,2,3)      ── new accuracy subsystem (shadow→switch)
         measurement integrity
Phase 6  Informative drift +    (needs 3,5)          ── richer verdicts + causal gates
         confidence gates
Phase 7  Reliability & rollout  (needs 2,6)          ── locking, canary, versioning, health
Phase 8  Packaging & isolation  (needs all)          ── tenancy, RBAC, PII, library packaging
```

**Why this order:** make the structure safe first (0–2), then unfreeze the math *with measurement* (3), then add the two new intelligence subsystems that depend on the parameter machinery (4–5), then enrich and harden (6–7), then package (8). Phases 4 and 5 are independent of each other and may run in parallel by different engineers.

**Rough relative effort** (from the cross-cutting audit; total ≈ 4–6 months for 2–3 engineers): Phase 0 S, Phase 1 M, Phase 2 L, Phase 3 M, Phase 4 M, Phase 5 L, Phase 6 M, Phase 7 L, Phase 8 L.

---

## 6. Phase-by-phase reference

Each phase below uses the same template: **Goal · Depends on · Components/Files · Representative tasks · Mechanisms & fixes landed · Behaviour change · Testing · Definition of Done · Risks.**

### Phase 0 — Foundations

- **Goal:** Build the dependency-light `cl_core` package: typed contracts, the 9 ports, the Adaptive Parameter Engine, the DomainProfile, and a fully-tested pure-Python statistics module. Purely additive.
- **Depends on:** nothing.
- **Components/Files:** `app/cl_core/{__init__,stats,segment,types,ports,parameters,domain_profile}.py`; `tests/cl_core/*`; `pytest.ini`; `requirements-dev.txt`.
- **Representative tasks:** see the detailed companion plan `docs/superpowers/plans/2026-06-03-cl-framework-phase0-foundations.md` (17 TDD tasks). Highlights: `stats` implements median/MAD/robust-sigma, pooled two-proportion SE + z, delta CI, Wilson interval, Benjamini-Hochberg FDR, power-based sample size, Tukey fences, quantile/percentile, smoothed PSI, safe relative delta, EWMA — each pinned to a known number. `types` defines Signal/MetricValue/BaselineSpec/DriftVerdict/Candidate/EvalResult/PromotionRecord/TrustVerdict (+ Window/Contributor/ArtifactRef/RolloutPlan), all with `schema_version`. `ports` defines the 9 runtime-checkable Protocols. `parameters` implements the four-source resolution with provenance. `domain_profile` wires it together.
- **Mechanisms & fixes landed:** the statistical *primitives* for every mechanism (2.1–2.9) and the corrected math for bugs 1.8 #1/#2/#4/#5/#6 — as tested library functions (not yet wired into the live path).
- **Behaviour change:** none. Nothing imports `cl_core`.
- **Testing:** ~60 unit tests; every stats function asserted against worked numbers.
- **Definition of Done:** package exists; all `tests/cl_core` pass; `import app.main` unaffected; committed.
- **Risks:** inverse-normal (`normal_ppf`) precision — mitigated by asserting tolerant ranges for power-based sample size.

### Phase 1 — Repository (data-access) layer

- **Goal:** Introduce repository interfaces so the new framework reads/writes through abstractions, not raw SQLAlchemy on salesops tables. Enables unit testing with mock repos and a future datastore swap.
- **Depends on:** Phase 0.
- **Components/Files:** `app/cl_core/repository.py` (Protocols: `SignalRepo`, `PipelineRepo`, `MetricSourceRepo`, `DriftRepo`, `OpportunityRepo`, `ExperimentRepo`, `BaselineRepo`, `KnowledgeRepo`); `app/cl_core_adapters/salesops/repos.py` (SQLAlchemy implementations wrapping the existing queries from `monitor.py`, `baselines.py`, `learning_promotion.py`); `tests/cl_core/test_repository_contract.py` + in-memory fakes.
- **Representative tasks:** define each repo Protocol with the minimal query surface the CL code needs (e.g. `pipelines_since(window, segment)`, `feedback_since(window)`, `knowledge_read/write`); implement the salesops repos by lifting the current SQLAlchemy queries verbatim (no logic change); write a shared contract test suite that both the real and fake repos must pass.
- **Mechanisms & fixes landed:** addresses the "welded to the app / no abstraction layer" packaging blocker; sets up testability (fixes the "no tests" gap for downstream phases).
- **Behaviour change:** none. The existing services keep running on their own queries; the repos are new and used only by the new code path.
- **Testing:** contract tests run against both fake and real repos; verify the real repo returns the same rows the old inline queries did (spot-check against a seeded DB).
- **Definition of Done:** every query the new path needs is available behind a repo interface; fakes exist; contract tests pass; no existing file's behaviour changed.
- **Risks:** scope creep (don't abstract queries the framework won't use); N+1 patterns inherited from old queries — note them for Phase 7, don't fix yet.

### Phase 2 — Wrap the existing steps as adapters

- **Goal:** Populate the 9 ports with adapters that reproduce today's behaviour, and run a core loop through the ports whose outputs match the current system. This is the structural backbone; no intelligence changes yet.
- **Depends on:** Phases 0, 1.
- **Components/Files:** `app/cl_core_adapters/salesops/`:
  - `metrics.py` — each of the 12 metrics as a `Metric` object + a `MetricRegistry` (replaces the `if/elif` in `monitor._observe_metric_impl`).
  - `detectors.py` — the 8 detectors behind `DriftDetector`.
  - `generators.py` — the 6 generators returning typed `Candidate` via a shared generator SDK (dedup, baseline-anchor, phrase-extraction, scoring) — **scores normalized to one 0–1 scale** (fixes B5 scale mismatch).
  - `knowledge_store.py` — `KbKnowledgeStore` over `KnowledgeRule` (read/write/snapshot/history/restore).
  - `evaluators.py` — the 5 backtests behind `Evaluator` (LLM-replay is one evaluator; data-replay the others).
  - `signal_source.py` — `Feedback`/outcome reads behind `SignalSource`.
  - `app/cl_core/loop.py` — the domain-agnostic orchestrator calling ports.
  - DB: add a unique constraint/index on opportunity & drift-alert fingerprints (makes dedup races impossible — failure 1.3/concurrency).
- **Representative tasks:** port one metric end-to-end first (e.g. `intent_classification_accuracy`) and assert the adapter's output equals the legacy function's output on the same data; repeat for all 12; same for detectors and generators; build a `salesops_profile()` factory returning a wired `DomainProfile`; add a parity harness comparing legacy `run_all_detectors`/`run_all_generators` output to the new loop's output.
- **Mechanisms & fixes landed:** runtime-pluggable metrics/generators (Group C); normalized candidate score (B5); formal `Candidate` contract; fingerprint uniqueness at the DB.
- **Behaviour change:** none intended — adapters must match legacy outputs (parity harness enforces this). The normalized score is an internal change; ranking order should be preserved or improved (documented).
- **Testing:** parity tests (legacy vs adapter) per metric/detector/generator on seeded data; generator SDK unit tests; knowledge-store round-trip tests.
- **Definition of Done:** the new loop runs through all 9 ports and produces outputs matching the current system within documented tolerance; fingerprint uniqueness enforced; legacy code still in place (not yet removed).
- **Risks:** subtle output differences (rounding, ordering) — investigate each before accepting; large surface area — do it metric-by-metric, not big-bang.

### Phase 3 — Adaptive Parameter Engine integration (unfreeze the math)

- **Goal:** Route the live detection/scoring path's tunable numbers through the Adaptive Parameter Engine, then switch each from a hardcoded fallback to a *derived* value, measuring the difference before keeping it.
- **Depends on:** Phases 0, 2.
- **Components/Files:** `app/cl_core_adapters/salesops/parameters.py` (registers derived/learned providers backed by `cl_core.stats`); modifications to the Phase-2 detector/evaluator adapters to read parameters via the engine; a comparison log table/endpoint capturing "constant vs derived" alarm sets.
- **Representative tasks:** seed the engine so every number returns today's constant via the *fallback* path (zero behaviour change, full provenance); then, one parameter at a time, register a *derived* provider and run both in shadow:
  - drift threshold → pooled-SE z (mechanism 2.1) replacing the wrong-variance z (bug 1.8 #1);
  - multiple-comparison control → BH-FDR across all tests per tick (mechanism 2.2, fixes 1.3);
  - "normal" field error rate → the field's own median (B2);
  - outlier rule → Tukey fences (2.6, fixes 1.8 #6);
  - PSI → smoothed PSI; relative delta → safe relative delta (1.8 #4/#5);
  - min-sample gates → power-based `required_sample_size` (2.4).
  For each, record how alarm volume/precision changed vs the constant, then flip the default.
- **Mechanisms & fixes landed:** Group B (frozen math) in the live path; bugs 1.8 #1/#4/#5/#6; the false-alarm flood (1.3).
- **Behaviour change:** **yes, intentional and measured.** Each switch is gated, shadow-compared, and reversible. Expect a large drop in false alarms (1.3) and corrected (often fewer) z-score firings (1.8 #1).
- **Testing:** for each parameter, a test that the engine returns fallback when no provider is registered and derived when one is; shadow-comparison reports reviewed before flipping; regression tests that known-good and known-bad scenarios alarm correctly.
- **Definition of Done:** all Group-B numbers served by the engine; each derived switch has a recorded before/after comparison; provenance visible per decision.
- **Risks:** a derived value behaving worse than the constant on some segment — that's exactly why every switch is shadowed and reversible; don't flip without the comparison.

### Phase 4 — Signal Trust subsystem

- **Goal:** Implement `SignalTrustScorer` and insert a trust gate so untrustworthy feedback is quarantined or down-weighted before it can influence metrics, baselines, candidates, or backtest ground-truth.
- **Depends on:** Phases 0, 1, 2, 3.
- **Components/Files:** `app/cl_core_adapters/salesops/trust.py` (the scorer, using data that already exists: `shadow_classification`, `AIOARequest.decision`, `Pipeline.confidence`, reviewer id via `HitlTask`, role via `sf_identity`, multi-edit oscillation); `app/cl_core/reputation.py` (reviewer reliability store, EWMA of survival vs reversal); loop change to call the trust gate after capture; UI/endpoint surfacing trust scores and quarantine reasons.
- **Representative tasks:** implement the five trust checks (corroboration, confidence-consistency, reviewer reputation, contradiction/oscillation, optional consensus) each as a small scorer contributing to a `TrustVerdict`; wire quarantine/down-weight into metric and ground-truth computation; build a seeded "bad feedback" scenario and prove the poisoning path is closed (a deliberately wrong correction no longer moves the metric or becomes backtest truth).
- **Mechanisms & fixes landed:** Group D (feedback trusted blindly); contributes to closing the self-reinforcing trap (1.1) by refusing to let unverified L4 overrides drive learning.
- **Behaviour change:** yes — some signals now carry reduced or zero weight. Shadow first (compute trust but don't act), compare, then enforce.
- **Testing:** unit tests per trust check with synthetic signals; an integration test on seeded contradictory/low-trust feedback proving exclusion from metrics, baselines, candidate generation, and backtest labeling.
- **Definition of Done:** quarantined signals provably excluded everywhere downstream; trust scores and reasons visible; reviewer reputation accrues over time.
- **Risks:** cold start (reputation needs history) — fall back to corroboration + confidence-consistency until it accrues; over-quarantining — tune the gate conservatively and monitor the quarantine rate.

### Phase 5 — Dynamic baselines + measurement integrity

- **Goal:** Replace static quality targets with synthesised, self-recalibrating baselines, and fix the measurement that feeds them so the system measures the whole population honestly (not just the reviewed subset).
- **Depends on:** Phases 0, 1, 2, 3.
- **Components/Files:** `app/cl_core_adapters/salesops/baseline_synth.py` (the `BaselineSynthesizer`); `app/cl_core_adapters/salesops/audit_sampling.py` (stratified random audit of L4-auto cases + corroboration signals — mechanism 2.9); changes so metrics are computed on a representative sample; shadow tables storing synthesised baselines beside the static ones for comparison.
- **Representative tasks:** implement the three-case policy (pinned contractual floors; empirical `median ± k·robust_sigma` bands from clean, promotion-decontaminated history; warm-up for low-sample segments) using `cl_core.stats`; implement the outcome ratchet (raise target when a promotion's realised-lift CI lower bound > 0) and shift-coupling (re-synthesise when PSI fires); implement stratified audit sampling so L4-auto quality is observed (fixes selection bias 1.1 and Simpson's-paradox visibility 1.4 by reporting per-segment alongside rollup); run synthesised baselines in shadow, compare alarm quality to static ones, then cut over; bound segment cardinality (fix 1.7).
- **Mechanisms & fixes landed:** Group E (static baselines); mechanism 2.3, 2.4, 2.9; failures 1.1, 1.4 (visibility), 1.5 (contamination), 1.7 (cardinality bound).
- **Behaviour change:** yes — alarms now fire against living, per-segment gates. Shadow-then-cutover. Expect fewer cold-start false alarms and no post-promotion staleness.
- **Testing:** synthesiser unit tests against worked numbers (median 0.93/MAD 0.008 → floor 0.894); warm-up behaviour; ratchet behaviour; an audit-sampling test proving the L4-quality estimate is unbiased on a constructed population; shadow-comparison report.
- **Definition of Done:** baselines self-calibrate and ratchet; warm-up suppresses day-1 false alarms; L4 quality is measured on a representative sample; segment cardinality bounded; cutover after shadow comparison.
- **Risks:** dynamic baselines could *miss* real regressions if bands are too wide — run in shadow long enough to confirm they don't, and keep contractual floors pinned as a safety net.

### Phase 6 — Informative drift + confidence-based & causal gates

- **Goal:** Make drift verdicts actionable and make promotion decisions rest on statistical confidence and causal evidence, not point estimates.
- **Depends on:** Phases 3, 5.
- **Components/Files:** enriched `DriftDetector` adapter producing full `DriftVerdict` (delta CI, significance, ranked contributors, likely causes, recommended change types); `Evaluator`/gate changes for confidence-based promotion; `app/cl_core_adapters/salesops/causal_lift.py` (A/B holdout at serving time where possible, else difference-in-differences) replacing the confounded pre/post realised-lift.
- **Representative tasks:** populate `DriftVerdict.delta_ci/significant/top_contributors/likely_causes/recommended_change_types`; route recommended change types to the matching generators; change the promote gate to "lower bound of delta CI > 0 AND n ≥ required_sample_size" (mechanism 2.7, fixes bug 1.8 #2 and the "+2%/n≥10" gate B8); implement DiD/holdout realised-lift (mechanism 2.8, fixes confounding 1.2) with the correct two-proportion delta CI.
- **Mechanisms & fixes landed:** mechanisms 2.7, 2.8; B8; failures 1.2, 1.8 #2; informative drift (Group B5 verdict richness).
- **Behaviour change:** yes — the gate rejects underpowered "wins" the old rule would have promoted; lift numbers change (often smaller, honest).
- **Testing:** gate tests using the worked numbers (+5pp at n=100 → not promoted; at n=1000 → promoted); DiD test stripping a constructed seasonal tailwind; verdict-content tests.
- **Definition of Done:** verdicts carry CI/significance/causes/recommended fixes; promotion requires statistical confidence; realised lift is measured against a control.
- **Risks:** serving-time A/B holdout may be infeasible in some integrations — fall back to DiD and document the weaker causal guarantee.

### Phase 7 — Reliability & rollout hardening

- **Goal:** Make the loop safe under concurrency and production operations: atomic, locked, observable, gradually-rolled-out, and reversible to any prior version.
- **Depends on:** Phases 2, 6.
- **Components/Files:** optimistic locking in `KbKnowledgeStore.write` (version compare-and-set); atomic multi-artifact promotion (unit-of-work/saga) in `Promoter`; canary/per-segment rollout in `Promoter`; N-step version history & rollback via `KnowledgeStore.history/restore`; thread-safe scheduler singletons + graceful shutdown in `cl_scheduler`/`realised_lift_watcher`; leader election/DB advisory locks for multi-instance; `Result`/error types replacing `except: return 0`; a CL self-observability endpoint (per-detector/generator last-run, error count, watcher liveness, LLM-replay failure rate, baseline status-transition history).
- **Representative tasks:** add `version` CAS to KB writes and a concurrency test that two simultaneous promotions can't clobber each other; wrap snapshot+apply+status in one transaction; implement canary fraction routing at serving time; implement `history()`/`restore(version)`; add shutdown events; replace broad excepts with explicit error reporting surfaced in the health endpoint.
- **Mechanisms & fixes landed:** Group F (reliability); concurrency races; all-or-nothing rollout; single-snapshot rollback; silent failures; no self-monitoring.
- **Behaviour change:** operationally yes (canary, locking), but candidate *outcomes* unchanged; safer.
- **Testing:** concurrency tests (simulated simultaneous writes/promotions); rollback-to-arbitrary-version test; shutdown test; health-endpoint contract test; fault-injection (a detector raises → health shows it, loop continues).
- **Definition of Done:** concurrent promotions safe; canary demonstrated; rollback to any prior version works; health endpoint live; no silent-zero ambiguity.
- **Risks:** SQLite limits true locking/concurrency — confirm production datastore (Postgres) for multi-instance; saga complexity — keep multi-artifact promotions rare and well-tested.

### Phase 8 — Packaging, isolation, and generality proof

- **Goal:** Make the framework genuinely reusable: per-tenant isolation, pluggable identity, privacy, data lifecycle, operability, and a packaged library with a second adapter proving domain-independence.
- **Depends on:** all prior phases.
- **Components/Files:** `tenant_id` on CL tables + tenant-scoped repos; a generic RBAC/identity provider interface (SF identity becomes one adapter); PII redaction in the learning path (reuse `pii_redactor` before replay/phrase-extraction/persistence); data retention/TTL/archival jobs + windowed/paginated queries (fixes unbounded growth); dry-run/preview and audit drill-through endpoints; runtime-tunable config (gate delta, intervals, approver counts) instead of redeploy; `schema_version` migration shims for existing JSON blobs; a separate, clearly-marked demo/seed namespace; packaging `cl_core` (+ `cl_core_adapters`) as an installable library; a small second toy adapter (e.g. a generic text-classification domain) wired to the same core.
- **Representative tasks:** add tenant scoping and prove cross-tenant isolation with a test; extract the RBAC provider interface and re-implement SF auth behind it; insert redaction; add retention jobs and pagination; build the preview/drill-through endpoints; write the second adapter and run the full loop on it.
- **Mechanisms & fixes landed:** the packaging blockers (coupling, tenancy, PII, retention, versioning, operability) from the cross-cutting audit.
- **Behaviour change:** additive/operational; the second adapter proves the core needs no Keysight knowledge.
- **Testing:** tenant-isolation tests; redaction tests on PII-bearing signals; retention job tests; the second-adapter end-to-end test (the real generality proof).
- **Definition of Done:** a second adapter compiles and runs against the unchanged core; the framework is packaged; per-tenant, privacy, retention, and operability requirements met.
- **Risks:** retroactively adding `tenant_id` to populated tables needs a careful migration; over-generalising the second adapter — keep it minimal, its only job is to prove the seams.

---

## 7. Cross-cutting deliverables (tracked across phases, not owned by one)

- **Test suite:** grows every phase; target meaningful coverage of the loop by Phase 6.
- **Provenance & auditability:** every adaptive number records its source (Phase 3 onward); every promotion/rollback records actor, gate state, and outcome (Phase 6–7).
- **Documentation:** keep the two design docs and this reference in sync as phases are edited; each phase that changes a contract updates `cl_core/types.py` docstrings.
- **Feature flags:** every behaviour-changing switch (Phases 3–6) is flag-gated and reversible.

## 8. Definition of Done for the whole programme

1. The CL loop runs entirely through the 9 ports; the core contains no Keysight knowledge.
2. Every Group-B frozen number is served by the Adaptive Parameter Engine (learned/derived where possible, configured/fallback otherwise), with visible provenance.
3. Feedback is trust-scored; quarantined signals never influence learning.
4. Baselines are synthesised, per-segment, warm-up-aware, and ratcheted from outcomes; contractual floors are pinned.
5. Drift verdicts are informative; promotion requires statistical confidence; lift is measured causally.
6. The loop is concurrency-safe, observable, gradually rolled out, and reversible to any prior version.
7. A second domain adapter runs on the unchanged core (generality proven); the framework is packaged with per-tenant isolation, PII handling, and retention.

---

## Appendix A — Frozen number → adaptive mechanism → phase

| Frozen today | Mechanism | Lands in |
|--------------|-----------|----------|
| drift z = 2.0/3.0 (wrong variance) | pooled-SE z + learned/derived cutoff | Phase 3 |
| (no multiple-comparison control) | Benjamini-Hochberg FDR | Phase 3 |
| "normal" field error rate 0.05 | field's own median (derived) | Phase 3 |
| 2-sigma outlier rule | Tukey IQR fences | Phase 3 |
| PSI 1e-6 floor / 5.0 cap | smoothed PSI | Phase 3 |
| 1e-9 relative-delta guard / 1.5 cap | safe relative delta | Phase 3 |
| min_sample 5/20/30/100 | power-based required_sample_size | Phase 3 (+ gate Phase 6) |
| score divisors ÷3/÷5/×10/÷20 | one 0–1 expected-value score | Phase 2 (scale) + Phase 3/6 (learned value) |
| severity weights 1.0/0.65/0.4 | learned from realised value | Phase 3/6 |
| targets 0.92/0.90/… + flat drift_pct | synthesised median ± k·MAD; pinned floors; ratchet | Phase 5 |
| "+2% & n≥10" promote gate | CI-lower-bound > 0 + power | Phase 6 |
| pre/post lift (confounded) | A/B holdout or difference-in-differences | Phase 6 |
| accuracy on reviewed subset only | stratified audit sample + corroboration | Phase 5 |
| confidence base 0.50 + fixed deltas | fitted base/weights (domain) | Phase 3 (later refinement) |

## Appendix B — Shortcoming → phase that fixes it

| Shortcoming | Group/ID | Phase |
|-------------|----------|-------|
| Hardcoded intents/stages/namespaces/integrations/tiers/regions/languages | A1–A7 | Phase 2 (config-driven adapters) + Phase 8 (tenancy) |
| Frozen mathematics / magic numbers | B1–B10 | Phase 3 (+ 5/6 for baselines/gates) |
| Metrics/signals are a fixed menu | C | Phase 2 (registry) + Phase 4 (signal kinds) |
| Feedback trusted blindly | D / 1.1 | Phase 4 |
| Static baselines | E / 1.5 | Phase 5 |
| Self-reinforcing accuracy trap (selection bias) | 1.1 | Phase 5 (audit sampling) + Phase 4 (trust) |
| No control group (confounded lift) | 1.2 | Phase 6 |
| Multiple-comparison false-alarm flood | 1.3 | Phase 3 |
| Simpson's paradox in rollup | 1.4 | Phase 5 (per-segment visibility) |
| Baseline reference contamination | 1.5 | Phase 5 |
| Gameable metric (Goodhart) | 1.6 | Phase 5 (anti-gaming guards) |
| Unbounded segment growth | 1.7 | Phase 5 (cardinality bound) |
| Statistical bugs (z, Wilson, rollup, delta, PSI, 2σ) | 1.8 | Phase 0 (functions) → Phase 3 (wired) |
| Reliability/concurrency/rollout/observability | F | Phase 7 |
| Packaging/coupling/tenancy/PII/retention/versioning/tests | — | Phase 8 (+ Phase 1 repos, ongoing tests) |
