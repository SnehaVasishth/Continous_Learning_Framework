# Turning the Continuous Learning Module into a General-Purpose, Self-Adapting Framework

**Date:** 2026-06-03
**Status:** Design blueprint (planning only — no code is changed yet)
**Goal in one line:** Take today's Keysight-specific "continuous learning" code and turn it into a framework that **adapts its behaviour to whatever input it receives**, instead of relying on fixed numbers and Keysight-specific rules that are written directly into the code.

---

## 1. How to read this document

This document is written so that anyone — not only the engineers who wrote the code — can understand it. It is organised like this:

1. **A plain-English explanation** of what "continuous learning" means and how the current system works (Sections 2–3).
2. **The single core problem** and the guiding principle that fixes it (Section 4).
3. **The detailed list of shortcomings**, grouped by theme, each explained simply with concrete examples from the real code (Sections 5–10). This is the heart of the document.
4. **The target design** — how we restructure the system so it adapts to its input (Sections 11–13).
5. **A step-by-step migration plan, risks, and a reference appendix** with the exact formulas and hardcoded values found in the code (Sections 14–16).

### Glossary (read this first)

- **Pipeline:** one run of the system on one input. Today an input is an email; in a general framework it could be a claim, a support ticket, a transaction, etc.
- **Signal:** a piece of evidence the system learns from. Two kinds: **feedback** (a human corrected or approved something) and **activity/outcome** (something happened — the task succeeded, failed, was slow, etc.).
- **Metric:** a number that measures quality, e.g. "how often the system classified the email correctly."
- **Baseline / quality gate:** the target a metric is compared against, e.g. "classification accuracy should stay above 92%." If the metric falls below the gate, that is "drift."
- **Drift:** a meaningful drop (or change) in a metric — a sign that quality is slipping.
- **Opportunity / candidate:** a proposed change to fix the drift, e.g. "add these example phrases to the classifier."
- **Backtest / evaluation:** replaying past data to check whether a proposed change would actually have helped, before applying it for real.
- **Promotion:** applying a proposed change to the live system.
- **KB (Knowledge Base):** the editable settings the system reads at runtime — the prompts, thresholds, example lists, and rules. Changing the system's behaviour means editing the KB.
- **Hardcoded:** a value or rule written directly into the program text, so changing it requires a developer to edit and redeploy the code.

---

## 2. What "continuous learning" is, in plain terms

Imagine a new employee who processes incoming emails. At first they make mistakes. A supervisor (CSR — Customer Service Representative) corrects them. A good employee notices the pattern in those corrections, updates their own notes, and gradually makes fewer mistakes — without anyone rewriting their job description.

That is what this module tries to do automatically:

1. **Capture** the corrections and outcomes (the signals).
2. **Observe** how well the system is doing (the metrics).
3. **Detect** when quality slips (drift against a baseline).
4. **Generate** a proposed fix (a candidate change to the KB).
5. **Validate** the fix by replaying history (backtest).
6. **Promote** the fix if it helps, **watch** the result, and **roll back** if it hurts.

The loop is sound. The problem is *how* each step is currently implemented.

---

## 3. How the current system is built (and why that limits it)

The six steps map to real files:

| Step | What it does | Where it lives |
|------|--------------|----------------|
| 1. Capture | stores corrections/approvals | `Feedback` table; `stage6_learning_agent.py` (currently just counts rows) |
| 2. Observe | computes 12 quality metrics | `monitor.py` → `_observe_metric_impl` |
| 3. Detect | 8 drift detectors + baseline checks | `monitor.py` |
| 4. Generate | 6 "candidate generators" | `learning_generators/` |
| 5. Validate | 3 validity checks + 5 backtests | `learning_validity.py`, `learning_promotion.py` |
| 6. Promote/Watch | apply, roll back, measure | `learning_promotion.py`, `realised_lift_watcher.py`, `cl_scheduler.py` |

Every one of these steps was written *for Keysight's email operation specifically*. The email types, the team queues, the quality targets, the statistical thresholds, the time windows, and the scoring formulas are all written into the code as fixed values. The system cannot be pointed at a different problem (insurance claims, loan processing, support triage) without a developer rewriting large parts of it.

---

## 4. The core problem, and the principle that fixes it

> **The core problem:** The system's intelligence is *frozen into constants*. Hundreds of numbers and rules — what counts as an email type, what a "good" accuracy is, how sensitive a drift alarm should be, how to score a proposed fix — are hardcoded and tuned for Keysight. None of them adapt to the data actually flowing through the system.

There are really **three distinct things** hardcoded into the code today, and they need three different treatments:

1. **Identity values** — *what the domain is made of* (email types, team queues, field names, integrations). These describe the business, not the algorithm.
2. **Frozen mathematics** — *fixed formulas and magic numbers* (a "2-sigma" rule, a "score = count ÷ 5" formula, a "0.92 target," a "30-day window"). These were hand-picked for Keysight and never change.
3. **Operational policy** — *who may approve a change, when changes are frozen, how many sign-offs are needed.* These belong to whoever runs the system.

### The guiding principle: **Configure, Derive, or Learn — never hardcode**

For every hardcoded value, we apply the first of these that fits:

- **Configure** — if the value describes the domain or a policy choice, move it out of the code into a configuration the operator supplies. *Example:* the list of email types should come from a domain config file, not be written into the program.
- **Derive** — if the value should reflect the data, compute it from the incoming signals. *Example:* the "normal" error rate for a field should be measured from that field's own recent history, not fixed at 0.05.
- **Learn** — if the value should reflect what actually works, learn it from outcomes over time. *Example:* how strongly to weight a "warning" vs a "critical" alert should be learned from whether warnings actually led to valuable fixes — not set to 0.65 by hand.

This single principle is the spine of the whole redesign. The rest of the document applies it, step by step, to the real shortcomings found in the code.

---

## 5. Shortcoming Group A — The system's identity is hardcoded to Keysight

These are values that describe *Keysight's specific business* but are baked into the program. A different domain cannot use the system until each of these becomes configuration.

**A1. Email types ("intents") are written into the code.** There are 18 fixed types — `po_intake`, `quote_to_order`, `wo_status_inquiry`, `brazil_tax`, and so on — defined in `kb_seeds/intent_definitions_v2.py:43-64` and `config.py:99-175`. They are grouped into Keysight categories (`SALES_PO`, `ISC_WO_RTK`, …) and mapped to Keysight mailbox addresses (`config.py:180-186`). A loan-processing system has none of these.
- **Fix (Configure):** the domain supplies its own list of input types in a config file. The framework treats "type" as an opaque label.

**A2. Each type is tied to a required field, hardcoded.** `monitor.py:686-698` says "a `po_intake` is only workable if `po_number` is filled, a `service_order` needs `work_order_number`," etc. These field names are Keysight's data model.
- **Fix (Configure):** the domain config declares which field(s) make each input type "complete."

**A3. The processing stages are fixed.** The six stages `intake, extract, reconcile, decide, execute, communicate` are hardcoded (`monitor.py:1019`), and each stage is wired to a specific metric (`baselines.py:294-302`). Another domain may have three stages or ten.
- **Fix (Configure):** the pipeline stages and what each stage is measured on come from config.

**A4. The editable-settings categories ("KB namespaces") are hardcoded.** Generators write to fixed namespaces like `intent`, `threshold`, `track_classifier`, `verification_rule`, `agent_prompts` (scattered across `learning_generators/*`). These are Keysight's knowledge structure.
- **Fix (Configure):** namespaces and their schemas are declared per domain.

**A5. The integrations are hardcoded to Salesforce / SharePoint / ServiceNow.** Failure detection watches for the literal events `sf_error`, `sp_error`, `sn_error`, `salesforce_write_failed` (`monitor.py:529`; `learning_validity.py:35-40`). Customer matching assumes a Salesforce account id and a 0.7 match score (`monitor.py:810-820`).
- **Fix (Configure):** integrations and their error vocabularies are plug-ins; the core knows only "an external write succeeded or failed."

**A6. The autonomy tiers are Keysight policy.** Three tiers — `L4_AUTO ≥ 0.95`, `L3_ONE_CLICK ≥ 0.80`, `L2_HITL` — are hardcoded (`config.py:189-193`). Another domain might have two tiers, or five, or different cutoffs.
- **Fix (Configure):** tier count and cutoffs come from config.

**A7. Geography and language lists are fixed.** Regions are hardcoded to `AMS, EMEA, APAC, JP` (`monitor.py:1093`) and languages to a fixed eight `en, ja, de, zh, fr, es, pt, ko` (`monitor.py:1021`). A new customer region or language simply won't be seen.
- **Fix (Derive):** these "segments" should be **discovered from the data** as new values appear, not pre-listed.

**Why this matters:** as long as the system's vocabulary is written in code, "general purpose" is impossible. Every one of these must become either configuration (the domain declares it) or discovery (the framework learns it from the data).

---

## 6. Shortcoming Group B — The mathematics is frozen (this is the big one)

This is the deepest problem and the one most overlooked. **Almost every calculation in the system uses fixed numbers that were hand-picked for Keysight.** They do not adapt to the data. Below, each important formula is explained in plain English, why it is too rigid, and how to make it adapt to the input. (The exact equations and line numbers are in Appendix 16.)

### B1. Drift alarms use fixed sensitivity thresholds

- **What it does now:** To decide if an error rate "spiked," the code computes a *z-score* — a measure of how many standard deviations the recent value is from the historical average — and raises an alarm if it crosses **2.0** (warn) or **3.0** (critical). These cutoffs are fixed for every segment (`monitor.py:178-220`). The same approach uses fixed "50% increase" / "100% increase" cutoffs for other detectors, and the textbook **0.2 / 0.5** cutoffs for distribution shift (PSI), with an arbitrary cap of **5.0**.
- **Plain-English problem:** A "2-standard-deviation" jump means very different things for a quiet email type with 5 examples a week versus a busy one with 5,000. A fixed cutoff causes **false alarms on small/quiet segments and missed problems on volatile ones**. The numbers were chosen once and never revisited.
- **Fix (Derive + Learn):** the alarm threshold for each metric and segment should be **derived from that segment's own historical variability** (how much it naturally bounces around), and the final sensitivity should be **learned from outcomes** — did alarms at this level actually catch real problems, or were they noise?

### B2. The "normal" error rate is hardcoded, not measured

- **What it does now:** The extraction-error detector compares the live error rate against a **hardcoded baseline of 0.05** (5%) (`monitor.py:349`), the same for every field.
- **Plain-English problem:** Some fields are naturally harder to read than others. Treating a 5% error rate as "normal" for all of them is wrong — it over-alarms on easy fields and under-alarms on hard ones.
- **Fix (Derive):** each field's "normal" rate should be **its own recent median**, measured from the data.

### B3. "Good enough" quality is decided by hardcoded buckets

- **What it does now:** Extraction completeness is scored with fixed buckets: if at least **66%** of fields are filled the score is forced to **1.0**; at **40%** it becomes **0.97**; below that it is the raw ratio (`monitor.py:733-738`). These cliffs (0.40, 0.66, 0.97) are unexplained.
- **Plain-English problem:** Why is 66%-filled treated as perfect? These numbers encode a Keysight judgement about "workable enough," not a measured relationship to whether the case actually succeeded downstream.
- **Fix (Learn):** the mapping from "how complete" to "how good" should be **learned from real outcomes** — i.e. how completeness actually relates to downstream success.

### B4. Every quality target ("baseline") is a hand-set constant

- **What it does now:** All 12 quality targets are typed into the code: accuracy target **0.92**, completeness **0.90**, latency **30,000 ms**, and so on, each with a fixed tolerance band (`drift_pct`) like **4%** or **20%** (`kb_seeds/baselines.py:40-286`). Three of them are even labelled `source = "empirical_p50"` ("the median we observed") — but the value is still a hand-typed literal, **never actually computed from data**. Nothing ever recalibrates these targets.
- **Plain-English problem:** The targets are guesses frozen in time. After the system improves, the target stays at the old number, so it either nags forever or stops being meaningful. The fixed tolerance band (e.g. "5% wiggle room") is applied identically to a near-perfect 99.5% metric and a noisy 55% metric, which makes no statistical sense.
- **Fix (Derive + Learn):** see Section 9 — baselines should be **synthesised from the metric's own history** (a robust centre, with a tolerance band sized to the metric's natural variability), kept fresh automatically, and **ratcheted up when a proven improvement lands**. Contractual targets (a real 24-hour SLA) stay pinned as a floor.

### B5. The "how important is this fix" scores use inconsistent, arbitrary formulas

- **What it does now:** Each generator scores its proposed fix with a different made-up formula:
  - threshold generator: `score = edit_rate × 10` (`threshold_generator.py:127`)
  - pattern-list generator: `score = count ÷ 5` (`pattern_list_generator.py:139`)
  - routing & validation generators: `score = count ÷ 3` (`routing_rule_generator.py:115`, `validation_rule_generator.py:141`)
  - drift generator: `score = severity_weight × (0.6 + 0.4 × …)` capped at 1.0 (`drift_alert_generator.py:339`)
  - prompt-refinement generator: `score = edits ÷ 20`
- **Plain-English problem:** Two problems. First, **the scales don't match** — some produce 0–10, others 0–1 — so when the dashboard ranks fixes by score, the ranking is meaningless. Second, **the divisors (3, 5, 10, 20) are arbitrary** — there is no reason a routing fix is "worth" `count ÷ 3` and a pattern fix `count ÷ 5`.
- **Fix (Learn):** all generators should produce a **single 0–1 score on the same scale**, and that score should reflect **expected value learned from history** — how much did fixes of this type, at this size, actually improve the metric? — rather than a hand-picked divisor.

### B6. The "severity weights" are guesses

- **What it does now:** A "critical" alert is weighted **1.0**, a "warning" **0.65**, "info" **0.4** (`drift_alert_generator.py:51-57`).
- **Plain-English problem:** These weights claim that an info-level drift is worth exactly 40% of a critical one. That precise ratio is a guess.
- **Fix (Learn):** weight each severity by **how often alerts at that level actually led to a valuable, promoted fix.**

### B7. The outlier rule assumes a bell curve

- **What it does now:** To flag a numeric value as an outlier, the validation generator uses **mean ± 2×standard deviation** (`validation_rule_generator.py:190`).
- **Plain-English problem:** This "2-sigma" rule assumes the numbers follow a symmetric bell curve. Prices, quantities, and amounts are usually skewed (a few very large values), so this rule mis-flags them.
- **Fix (Derive):** use a method that doesn't assume a bell curve — e.g. **IQR / Tukey fences** (based on percentiles) or a multiplier learned from how often flagged outliers were truly problems.

### B8. The promotion gate uses a fixed "+2%" rule with no notion of certainty

- **What it does now:** A proposed change is marked "ready" if the backtest shows at least a **+2 percentage-point** improvement, with a minimum sample of **10** (`learning.py:217-218`; `learning_promotion.py:595-601`).
- **Plain-English problem:** "+2% on 10 examples" is almost certainly luck; "+2% on 10,000 examples" is rock-solid — but the code treats them the same. There is **no measure of statistical confidence.**
- **Fix (Derive):** promote based on **confidence, not a point number** — e.g. only when the *lower bound* of the improvement's confidence interval is above zero, with enough samples to have real statistical power. The "+2%" minimum, if kept, should be per-metric, not global.

### B9. Feedback is scored with a guessed 0.5

- **What it does now:** When measuring real-world lift, an "approve" counts as 1.0 correct, a "reject" as 0, and an "edit" as **0.5** — and any unknown feedback type also defaults to **0.5** (`realised_lift_watcher.py:118-126`).
- **Plain-English problem:** "An edit is half-correct" is a guess, and defaulting unknown signals to 0.5 silently invents data.
- **Fix (Learn):** derive the weight of an "edit" from **how much rework it actually represents** (e.g. time spent, size of change), and never silently default unknown types.

### B10. The confidence score itself is a fixed additive formula

- **What it does now:** The classifier's confidence starts at a fixed base of **0.50** and adds/subtracts fixed deltas from a rubric, clamped to 0–1 (`classify_intent_tool.py:514`). A separate check warns only if the model's own number disagrees by more than **0.05**.
- **Plain-English problem:** The 0.50 starting point is arbitrary, and adding rubric points assumes the clues are independent (they usually aren't — an explicit subject line and an action verb tend to appear together, so they're double-counted). The 0.05 disagreement threshold is also arbitrary.
- **Fix (Learn/Derive):** the base and the rubric weights should be **fitted to the domain's own historical data** rather than hand-set, and the disagreement threshold should be **derived from how much the two numbers normally differ.**

**The common thread of Group B:** every formula assumes (a) all segments behave the same, (b) distributions never change, (c) relationships are simple/linear, and (d) the hand-picked numbers are correct forever. A general framework must replace each fixed number with one that is **derived from the data** or **learned from outcomes.**

---

## 7. Shortcoming Group C — Signals and metrics are a fixed menu, not an open system

- **What it does now:** The 12 metrics are a hardcoded `if/elif` chain inside one function (`monitor.py:632`). Adding a metric means editing and redeploying the code. The kinds of signal are similarly fixed: only human corrections of a known shape are really used; positive outcomes and implicit signals (e.g. "the customer never replied, so we got it right") are not captured. The Stage-6 learning agent that is *supposed* to process signals just counts rows and does nothing else (`stage6_learning_agent.py:22-24`).
- **Plain-English problem:** A general framework cannot know in advance which metrics a new domain cares about, or which signals it can collect. A fixed menu defeats the purpose.
- **Fix (Configure + Derive):**
  - **Metrics become plug-ins.** A metric is a small, self-contained unit (it knows how to compute itself over a time window and a segment). The framework keeps a *registry* of metrics; a domain registers the ones it needs. No code change to the core.
  - **Signals become a general, typed concept** with four kinds — correction, outcome, implicit, approval — each carrying a weight and a source. The system can then learn from successes, not only from corrections.

---

## 8. Shortcoming Group D — Feedback is trusted blindly (one of your two points)

- **What it does now:** A single human correction is taken as absolute truth. One "edit" instantly lowers the measured accuracy (`monitor.py:766-771`), and a CSR's corrected label becomes the "right answer" that a proposed change is graded against (`learning_promotion.py:519`). There is **no check that the correction was itself correct.**
- **Plain-English problem:** People make mistakes, rush, or disagree. One careless correction can ripple all the way through: it triggers a false drift alarm → spawns a fix → the fix is graded against the wrong "truth" → a bad change gets promoted. The whole loop can be **poisoned by low-quality feedback.**
- **The good news:** the system *already records* everything needed to judge feedback quality — it just never connects it. Available today: a second AI opinion (`shadow_classification`), an order-validation verdict (`AIOARequest.decision`), the original confidence score (`Pipeline.confidence`), the reviewer's identity and role (via `HitlTask` and `sf_identity`), and the history of multiple edits on the same item.
- **Fix (a new "trust" step — Derive + Learn):** before any signal is allowed to influence metrics, baselines, fixes, or grading, score how trustworthy it is, using five general checks:
  1. **Corroboration** — does an independent opinion (second AI, validation verdict) agree?
  2. **Confidence-consistency** — a human overturning a *very confident* automated decision is both more suspicious and more valuable, so flag it for a closer look.
  3. **Reviewer reliability** — track, per reviewer, how often their corrections later survive vs. get reversed.
  4. **Contradiction/oscillation** — if the same item is corrected back and forth, quarantine it.
  5. **Consensus (optional)** — for high-stakes segments, require a second reviewer to agree.
  - Signals that fail are **quarantined** (ignored) or **down-weighted**; trustworthy ones get full weight. This closes the poisoning path for every later step at once.

---

## 9. Shortcoming Group E — Quality gates (baselines) are static (your other point)

- **What it does now:** Quality targets are hand-typed and **never change** (Section B4). The detector only *reads* them; nothing recalibrates them. There is no warm-up period for new segments, no per-segment targets, no confidence band, and no feedback loop from real outcomes back into the target. After a change proves it improves accuracy by 3 points, the target stays at the old number forever.
- **Plain-English problem:** A static target drifts out of touch with reality. New segments with little data trigger false alarms on day one; proven improvements are never "locked in" as the new normal.
- **Fix (a "baseline synthesiser" — Derive + Learn):** baselines become **living quality gates** computed from the data, using one policy with three cases:
  1. **Contractual targets** (a real 24-hour SLA, a 99.5% delivery floor) stay **pinned** — the system never lowers them.
  2. **Earned targets** (accuracy, match rate) are **derived from the metric's own recent history**: the target is a robust centre of past performance, and the tolerance band is sized to how much the metric naturally varies (wide band for noisy metrics, tight band for stable ones). This automatically replaces the hand-tuned "drift %."
  3. **New segments** start in a **warm-up** state: until enough data accumulates, the band is wide and the alarm can only "warn," never block — so day-one noise doesn't cause false emergencies.
  - Plus two feedback loops the system lacks today: when a promoted change proves a *statistically real* improvement, **ratchet the target upward** so the gain becomes the new floor; and when the input mix shifts noticeably, **re-synthesise** the target instead of judging against a stale one.

---

## 10. Shortcoming Group F — Reliability, safety, and packaging (briefly)

These don't change the math but must be fixed for a "high-standard" framework. Each is explained in one line:

- **Concurrency:** two changes promoted at the same time can silently overwrite each other (no locking on KB writes); two scheduler runs can create duplicate alarms (`monitor.py:120-161`). *Fix: locking + database uniqueness so duplicates are impossible.*
- **All-or-nothing changes:** a change goes live to 100% of traffic instantly, and rollback only remembers **one** previous version. *Fix: gradual ("canary") rollout and a full version history.*
- **Silent failures:** if a detector or generator crashes, the code records "0" — indistinguishable from "nothing found" (`learning_generators/__init__.py:98-108`). *Fix: explicit error reporting and a health view.*
- **No self-monitoring:** nobody is told if a detector has been broken for a week or a background thread has died. *Fix: a health endpoint reporting each component's last run and error count.*
- **Welded to the app:** the learning code reads Keysight database tables directly everywhere, with no separation layer, no data retention limits, no privacy redaction in the learning path, and no multi-customer isolation. *Fix: a thin data-access layer so the core depends on interfaces, not Keysight tables.*
- **No tests:** there is no automated test suite for the learning loop, and demo/seed data can contaminate real metrics. *Fix: a test suite and a separate, clearly-marked space for demo data.*

---

## 11. The target design, in plain English

### The big idea: separate the "engine" from the "domain"

Think of a power tool with interchangeable heads. The **motor** (the engine) is always the same; you snap on a different **head** (drill, sander, saw) for each job. We want the continuous-learning **loop** to be the motor — built once, never changed — and each domain (Keysight email, insurance claims, …) to be a **head** that snaps on.

The connection points between the motor and the heads are called **ports**. A port is just a clearly-defined socket: "give me signals," "compute this metric," "apply this change." The Keysight-specific code becomes one set of heads (an **adapter**) that plugs into those sockets. To support a new domain, you write a new adapter — you never touch the engine.

### The 9 ports (sockets)

| # | Port (socket) | What plugs into it | Replaces today's |
|---|---------------|--------------------|------------------|
| 1 | **Signal source** | where corrections/outcomes come from | `Feedback` reads |
| 2 | **Signal trust** *(new)* | judges if a signal is reliable | *nothing today* |
| 3 | **Metric registry** | the set of quality metrics | the fixed 12-metric `if/elif` |
| 4 | **Baseline synthesiser** *(new behaviour)* | computes living quality gates | the static `Baseline` table |
| 5 | **Drift detector** | decides "did quality change?" with confidence | the 8 fixed detectors |
| 6 | **Candidate generator** | proposes fixes | the 6 generators (already pluggable) |
| 7 | **Knowledge store** | reads/writes/versions the editable settings | direct KB overwrites |
| 8 | **Evaluator** | backtests a proposed fix | the 5 fixed backtests |
| 9 | **Promoter** | applies / stages / rolls back a fix | the KB-overwrite + single snapshot |

### The Domain Profile: where all the configuration lives

Everything from **Group A** (the domain's identity) and the operator's **policy** lives in one place a domain provides, called the **Domain Profile**: the list of input types, the stages, the metrics to use, the segment dimensions, the approval rules, etc. The engine reads only the Domain Profile and the ports — it contains **zero** Keysight knowledge.

---

## 12. The Adaptive Parameter Engine: the cure for the frozen math

This is the component that directly answers your concern about hardcoded math. Instead of constants scattered through the code, there is **one place** that supplies every tunable number, and it supplies them in priority order:

1. **Learned value** — if we have enough outcome history, use the value learned from what actually worked (e.g. the real value of a "warning" alert, the score for a fix of a given type).
2. **Derived value** — otherwise, compute the value from the data (e.g. an alarm threshold sized to a segment's own variability; a "normal" error rate from a field's own median; an outlier fence from percentiles).
3. **Configured value** — otherwise, use the operator's configured default.
4. **Safe fallback** — only if none of the above is available, use a documented built-in default (today's hardcoded number becomes the *last* resort, not the only option).

Concretely, the magic numbers from Section 6 are replaced like this:

| Today's frozen number | Becomes |
|-----------------------|---------|
| z-score cutoff 2.0 / 3.0 (B1) | a threshold **derived** from each segment's own variability, **learned** from whether alarms were useful |
| "normal" error rate 0.05 (B2) | the field's **own recent median** |
| completeness buckets 0.40/0.66/0.97 (B3) | a curve **learned** from completeness → real success |
| quality targets 0.92, 0.90, … (B4) | **synthesised** from history; contractual ones pinned |
| score divisors 3 / 5 / 10 / 20 (B5) | one **0–1 scale**, value **learned** from realised lift |
| severity weights 1.0/0.65/0.4 (B6) | weights **learned** from how often each severity led to a real fix |
| 2-sigma outlier rule (B7) | percentile-based fences (no bell-curve assumption) |
| "+2% on 10" gate (B8) | **confidence-interval** gate with real statistical power |
| "edit = 0.5" (B9) | weight **derived** from actual rework; no silent defaults |
| confidence base 0.50 + fixed deltas (B10) | base and weights **fitted** to the domain's data |

The engine also records *why* each number was chosen (learned / derived / configured / fallback) so operators can see and audit it.

---

## 13. How the loop runs, end to end (plain)

1. **Collect** new signals from the signal-source port.
2. **Trust-check** each signal; quarantine or down-weight the unreliable ones.
3. **Measure** each metric over each segment (segments discovered from data).
4. **Synthesise** the living quality gate (baseline) for each metric/segment.
5. **Detect** drift with a confidence-aware, adaptive threshold; produce an *informative* alert (how big, how certain, worst sub-segment, likely cause, which fix types to try).
6. **Generate** candidate fixes, each scored on one 0–1 scale.
7. **Validate** each fix by backtesting on held-out history (quarantined signals excluded from grading).
8. **Gate** on statistical confidence, not a raw number.
9. **Promote** the fix gradually (canary), watch the real result, and **feed the proven gain back** into the baseline. Roll back automatically if it regresses.

Every number used in steps 2–9 comes from the Adaptive Parameter Engine, not from a constant in the code.

---

## 14. Migration plan (safe, step-by-step)

Each phase is independently useful, keeps the system working, and can be reversed.

- **Phase 0 — Foundations.** Create the engine package with the typed data shapes, the port definitions, the Domain Profile, and a shared statistics helper (confidence intervals, robust spread). No behaviour change.
- **Phase 1 — Data-access layer.** Route all reads/writes through a thin interface so the engine no longer touches Keysight tables directly. Enables testing. No behaviour change.
- **Phase 2 — Wrap today's code as adapters.** Put the existing 12 metrics, 8 detectors, 6 generators, backtests, KB writes behind the ports. Normalise all fix-scores to one 0–1 scale. Behaviour stays the same.
- **Phase 3 — Adaptive Parameter Engine.** Introduce the central source for tunable numbers. Start by having it return today's constants (the "fallback" path), then switch them on to "derive" one by one, comparing against the old values. This is where the frozen math (Group B) is unfrozen, safely and measurably.
- **Phase 4 — Signal trust.** Add the trust step (Group D) using data that already exists; prove on seeded bad feedback that the poisoning path is closed.
- **Phase 5 — Dynamic baselines.** Add the baseline synthesiser (Group E); run it in shadow next to the static targets, compare alarm quality, then switch over.
- **Phase 6 — Informative drift + confidence gates.** Enrich alerts and switch the promotion gate to confidence-based (Group B8).
- **Phase 7 — Reliability & rollout.** Locking, atomic promotion, gradual rollout, full version history, self-monitoring (Group F).
- **Phase 8 — Packaging & isolation.** Per-customer isolation, configurable policy, privacy redaction; package the engine as a reusable library with the Keysight adapter as the reference example, and prove generality with one small second adapter.

**Order rationale:** we make the structure safe first (Phases 0–2), then unfreeze the math with measurement (Phase 3), then add the two new intelligence subsystems (Phases 4–5), then polish (6–8). The math is unfrozen *before* the new subsystems because the trust scorer and baseline synthesiser both rely on the adaptive-parameter machinery.

---

## 15. Risks and open questions

- **Database limits:** today's storage limits true concurrency and locking; reliable multi-instance operation may need a stronger database. *Confirm target deployment.*
- **Cold start:** "learned" values need history. Until it accumulates, the engine falls back to "derived," then "configured," then safe defaults — so the system is never worse than today, but the smartest behaviour arrives over time.
- **Backtest determinism:** grading that calls an AI model must be run in a repeatable mode (fixed settings / cached answers) so results are reproducible.
- **Baseline cutover:** dynamic baselines must run in shadow long enough to prove they don't *miss* real problems before they replace the static targets.
- **Scope discipline (don't over-build):** make the *engine and ports* general now, but build only the Keysight adapter. Do not build adapters for domains that don't exist yet — only the interfaces need to be general.

---

## 16. Appendix — exact reference (formulas and hardcoded values)

### 16A. Frozen formulas and their magic constants

| Formula & location | What it computes | Magic constants | Make it adaptive by |
|--------------------|------------------|-----------------|---------------------|
| z-score, `monitor.py:220` | edit-rate spike vs history | warn 2.0, high 3.0, min 5/20, σ-floor 1e-4 | per-segment variability + learned sensitivity |
| relative rate, `monitor.py:282` | HITL-rate increase | 0.5 / 1.0 | per-stage tolerance from history (k·MAD) |
| field error rate, `monitor.py:341-349` | extraction error spike | warn 0.10, high 0.20, **baseline 0.05** | per-field median baseline |
| latency relative, `monitor.py:393` | P95 latency regression | 0.5 / 1.0 | per-stage learned tolerance |
| AIOA drop, `monitor.py:438` | pass-rate drop | 0.10 / 0.20 | threshold scaled to baseline rate |
| PSI, `monitor.py:458-477` | intent-mix shift | warn 0.2, high 0.5, cap 5.0, min 30/100 | learned per-domain PSI threshold |
| integration failures, `monitor.py:571` | write-failure delta | 0.05 / 0.10 | per-integration learned baseline |
| completeness buckets, `monitor.py:733-738` | completeness → score | 0.40 / 0.66 / 0.97 | learned completeness→success curve |
| rollup weighting, `monitor.py:1137-1174` | combine segments | weight floor 1.0 | Bayesian shrinkage to global mean |
| baseline status, `baselines.py:92-104` | healthy/drifting/breached | drift_pct (5.0 default) | band = k·robust-spread of history |
| severity weights, `drift_alert_generator.py:51-57` | severity → multiplier | 1.0 / 0.65 / 0.4 | learned from realised value per severity |
| drift score, `drift_alert_generator.py:339` | opportunity score | 0.6, 0.4, 1.5, cap 1.0 | learned (severity, magnitude)→lift curve |
| missing-field score, `validation_rule_generator.py:141` | opportunity score | ÷3, cap 10 | learned cost-per-incident |
| invariant score, `validation_rule_generator.py:242` | opportunity score | ÷3, cap 10 | learned cost-per-incident |
| 2-sigma outlier, `validation_rule_generator.py:190` | outlier fence | ×2 | IQR/Tukey fences |
| pattern score, `pattern_list_generator.py:139` | opportunity score | ÷5, cap 10 | one 0–1 scale, learned |
| routing score, `routing_rule_generator.py:115` | opportunity score | ÷3, cap 10 | one 0–1 scale, learned |
| threshold score, `threshold_generator.py:127` | opportunity score | ×10, floor 0.05 | logistic curve learned from raises |
| L4 floor pick, `threshold_generator.py:93-97` | new confidence floor | quartile ÷4, cap 0.995 | cost-minimising cutoff from data |
| corpus gate, `learning_promotion.py:50` | block if tests weak | 0.80, 7 days | calibrate to live defect correlation |
| backtest delta, `learning_promotion.py:676` | candidate − baseline acc | none | weight by intent volume/impact |
| promote gate, `learning_promotion.py:595-601` & `learning.py:217-218` | ready/fail/watch | ±2.0, min 10 | confidence-interval + power |
| feedback weights, `learning_promotion.py:118-126` | thumbs → correctness | 1.0/0.0/0.5/0.5 | learned from rework |
| Wilson CI, `realised_lift_watcher.py:156` | confidence interval | z 1.96 | configurable; exact CI for small n |
| control window, `realised_lift_watcher.py:133` | pre-promotion baseline | 14 days | match backtest window width |
| auto-rollback, `realised_lift_watcher.py:196` | revert if gap too big | 5.0 pp | per-change-type + CI-aware |
| confidence rubric, `classify_intent_tool.py:514` | classifier confidence | base 0.50, clamp 0–1 | fit base & weights to domain data |
| confidence disagreement, `classify_intent_tool.py:381` | sanity check | 0.05 | derive from normal disagreement spread |

### 16B. Hardcoded Keysight/operational values (move to config or discovery)

1. **Intents (18):** `intent_definitions_v2.py:43-64`; categories, flows, redirect mailboxes in `config.py:99-186`. → domain config.
2. **Intent→required-field map:** `monitor.py:686-698`. → domain config.
3. **Stages (6) & stage→metric map:** `monitor.py:1019`, `baselines.py:294-302`. → domain config.
4. **KB namespaces:** `intent, threshold, track_classifier, verification_rule, agent_prompts, training_data, sla, language_heuristic_rules, detector_tuning, drift` (across generators). → domain config.
5. **Integrations:** `sf_error/sp_error/sn_error/salesforce_write_failed` (`monitor.py:529`), infra signatures (`learning_validity.py:35-40`), customer-match schema & 0.7 score (`monitor.py:810-820`). → integration plug-ins.
6. **Autonomy tiers:** `L4 0.95 / L3 0.80 / L2` (`config.py:189-193`). → domain config.
7. **Critical fields:** `po_number, ship_to, quote_number, work_order_number` (`monitor.py:303`). → domain config.
8. **Regions** `AMS/EMEA/APAC/JP` (`monitor.py:1093`), **languages** `en/ja/de/zh/fr/es/pt/ko` (`monitor.py:1021`). → discover from data.
9. **12 metrics, targets, drift%, severity, units, rollup:** `kb_seeds/baselines.py:40-286`. → metric plug-ins + synthesised targets.
10. **Time windows:** baseline 30d, recent 24h, short 1h, generator lookback 30d, corpus 7d, control 14d (`monitor.py:59-61,597`; generators; `realised_lift_watcher.py`). → scale to segment traffic / config.
11. **Sample minimums:** 5 / 20 / 30 / 100; generator minimums 3 / 20 (across detectors & generators). → statistical-power based.
12. **Schedules:** detector 1800s, generator 3600s, watcher 120s, watch-delay 1h, rollback window 7d (`cl_scheduler.py:39-40`; `realised_lift_watcher.py:41-47`). → config.
13. **Policy:** rule owners, approver counts per change type, freeze windows, shadow hours, auto-rollback thresholds (`config.py:201-252`). → operator config + generic RBAC.
