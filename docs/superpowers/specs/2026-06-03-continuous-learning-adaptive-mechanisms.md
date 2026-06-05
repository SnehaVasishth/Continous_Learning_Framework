# Continuous Learning — Deep Failure Modes, Adaptive Mechanisms, and a Worked Example

**Date:** 2026-06-03
**Status:** Design deep-dive (planning only). Companion to `2026-06-03-continuous-learning-framework-design.md`.
**Why this document exists:** The companion blueprint says *what* to make adaptive. This document goes deeper: it (1) documents serious problems that are **not** just "hardcoded values" — biases and outright math bugs in how the system reasons; (2) **designs the actual adaptive algorithms** that replace the frozen formulas, with update rules and worked numbers; and (3) walks one scenario **end to end with real numbers**.

All findings below were confirmed against the real code with file:line references.

---

# Part 1 — Deep failure modes (newly found, beyond "hardcoded values")

These are the problems that make the current system not just inflexible but, in places, **statistically invalid**. They matter even for Keysight today — and they must be fixed for any general framework.

## 1.1 The system can blind itself (self-reinforcing accuracy trap) — **CONFIRMED**

**The chain of cause and effect:**
- Accuracy is computed as `1 − (human edits ÷ total cases)` (`monitor.py:766-771`).
- Human edits exist **only when a case was reviewed** — feedback is written only on HITL resolution (`hitl.py:285-292`).
- L4-auto cases run **without human review**, so they contribute **zero edits = counted as correct by default**.
- Therefore the metric measures quality on the *reviewed subset only*, and treats all auto-handled cases as perfect.

**Why this is dangerous:** if a tuning change raises the L4-auto rate, fewer cases go to humans, fewer corrections are captured, the edit-based metric sees fewer edits and **looks healthier — even if true quality dropped.** Higher autonomy → fewer observations → fewer detected errors → "looks great" → push autonomy higher. The loop optimizes itself into a blind spot.

**Plain analogy:** a teacher who only grades the homework of students who ask for help, then concludes the class is doing great because fewer students asked this week.

## 1.2 No control group → realised "lift" is confounded — **CONFIRMED**

`realised_lift_watcher.py:84-155` compares a *post-promotion* window to a *14-day pre-promotion* window. There is **no concurrent control** (no slice of traffic kept on the old rule). So **everything** that changed after promotion — season, volume, customer mix, *other* promotions — is credited to this one change. A promotion "measured" at +5% may have truly delivered +1%.

## 1.3 No multiple-comparison control → false-alarm flood — **CONFIRMED**

`run_all_detectors` runs 8 detectors across many segments every 30 minutes — roughly **70–150 independent statistical tests per tick** (`monitor.py:1487-1500`). There is no Bonferroni/FDR correction and no quiet-period. At a 5%-equivalent threshold that is an estimated **168–360 false alarms per day**. Operators learn to ignore alarms — which defeats the system.

## 1.4 Simpson's paradox in the rollup — **CONFIRMED**

The weighted-average rollup (`monitor.py:1164-1174`) can show "all healthy" globally while **every individual segment is degrading**, purely because the *mix* of traffic shifted toward easier segments — or raise a false breach from a mix change with no quality change at all.

## 1.5 Baseline reference is contaminated — **CONFIRMED**

The 30-day "normal" window the detector compares against (`monitor.py:59-61, 184-188`) **includes data produced after earlier promotions.** The reference is a moving, self-influenced goalpost, so regressions get harder to see after each change.

## 1.6 The metric is gameable (Goodhart) — **CONFIRMED**

Because edit-rate is the quality proxy, it can be improved *without improving quality*: route more cases to terminal intents (spam/kso) so they never reach the stages that accumulate edits, or shift routing so edits are recorded elsewhere. The metric then measures routing behaviour, not quality.

## 1.7 Unbounded segment growth — **CONFIRMED**

Segments are discovered live from data (`monitor.py:1024-1134`) with a hard cap of 20 only on customers — **no cap on intents or languages.** A new product line with 50 sub-types would spray the baseline table with noisy, tiny, cold-start segments that false-alarm as they cross thresholds.

## 1.8 Outright statistical bugs in the formulas — **CONFIRMED**

| Bug | Location | What's wrong | Concrete failure |
|-----|----------|--------------|------------------|
| **Drift z-score uses the wrong variance** | `monitor.py:220` | Uses only baseline variance `√(p(1−p)/n_b)` instead of the **pooled** variance of a *difference*. Underestimates the standard error ~40%. | Baseline 2.0% (n=1000) vs recent 2.2% (n=500): code computes z≈3.1 → **HIGH alarm**; correct z≈0.25 → no alarm. A pure false positive. |
| **Realised-lift CI ignores control variance** | `realised_lift_watcher.py:156-158` | Computes the CI of a *single* proportion, not of the *delta*; drops the control group's variance entirely. | +5% lift on n=100/100: code reports ±7.8pp; correct is ±12.9pp. The system claims certainty it doesn't have. |
| **Empty segment gets full vote** | `monitor.py:1168` | A segment with `n=0` is given weight `1.0` and injects a spurious value into the weighted average. | A real-but-empty segment drags the global number toward an invented value. |
| **`1e-9` guard creates garbage drift scores** | `drift_alert_generator.py:338-339` | When baseline≈0, `delta/1e-9` explodes to ~1e6, then is capped at 1.5 — so a *catastrophic* "0% → 50% failure" scores the **same** as a mild 1.5× change. | A brand-new 50% failure rate is scored as low urgency. |
| **PSI epsilon floor distorts proportions** | `monitor.py:458-465` | Missing buckets are floored to `1e-6` instead of using smoothing or omission, and a hard cap of 5.0 hides large genuine shifts. | Large intent-mix shifts are dampened. |
| **2-sigma outlier rule assumes a bell curve** | `validation_rule_generator.py:186-191` | Uses population stdev and `mean ± 2σ` with a one-sided floor at 0; invalid on skewed/bimodal data (prices, quantities). | Skewed price data mis-flags normal values and misses real ones. |

(Percentile/P95 at `monitor.py:164-169` and the confidence-rubric clamp at `classify_intent_tool.py:514` were checked and found **correct**, aside from a missing "value was clamped" note.)

**Takeaway for Part 1:** several core calculations are not merely rigid — they are **biased or wrong**. The adaptive redesign in Part 2 fixes the *flexibility* problem and the *correctness* problem at the same time.

---

# Part 2 — The adaptive mechanisms (the actual algorithms)

Every tunable number is served by one component, the **Adaptive Parameter Engine**, which returns a value using the first available of four sources, and records which one it used (so it is auditable):

1. **Learned** — from outcome history (what actually worked).
2. **Derived** — computed from the incoming data (its own variability/volume).
3. **Configured** — the operator's setting.
4. **Fallback** — a documented safe default (today's constant, now the *last* resort).

Below, each mechanism gives: **the problem**, **the algorithm**, **where the number comes from**, and a **worked example with numbers** (old vs new).

### Shared statistical foundation (used by several mechanisms)

- **Robust centre & spread:** instead of mean/stdev (which outliers distort), use the **median** and **MAD** (median absolute deviation). For roughly-normal data, `σ̂ ≈ 1.4826 × MAD`. This is the backbone of adaptive thresholds and bands.
- **Two-proportion difference:** to compare a recent rate to a baseline rate correctly, the standard error is
  `SE = √( p_b(1−p_b)/n_b + p_r(1−p_r)/n_r )` — the **pooled** form (fixes bug 1.8 #1 and #2).
- **Online updates:** parameters that should adapt continuously use an **EWMA** (exponentially-weighted moving average): `new = α·observation + (1−α)·old`, so recent data matters more without storing everything.

---

## 2.1 Adaptive drift threshold (replaces fixed z = 2.0 / 3.0)

**Problem:** a fixed cutoff over-alarms on quiet segments and misses problems on volatile ones, and the variance formula is wrong (bug 1.8 #1).

**Algorithm:**
1. Compute the difference correctly using the **pooled SE** above: `z = (recent − baseline) / SE`.
2. Choose the alarm cutoff `k` not as a constant but from a **target false-discovery rate across all of today's tests** (see 2.2) — and refine it with a **learned correction**: track, per metric, what fraction of past alarms turned into confirmed problems or successful fixes; nudge `k` up if too many alarms were noise (EWMA controller).

**Where the number comes from:** *Derived* (pooled SE from this segment's own counts) + *Learned* (the cutoff `k` from past alarm precision).

**Worked example:** baseline edit-rate `p_b=0.02` over `n_b=1000`; recent `p_r=0.022` over `n_r=500`.
- Old code: `SE = √(0.02·0.98/1000) = 0.0044`; `z = 0.002/0.0044 ≈ 0.45` *(and with the floor/variance quirks it can read ~3.1 — a false HIGH alarm).*
- New: `SE = √(0.02·0.98/1000 + 0.022·0.978/500) = √(0.0000196+0.0000430) = 0.0079`; `z = 0.002/0.0079 ≈ 0.25` → **not significant.** Correct call: no alarm.

---

## 2.2 Multiple-comparison control (new — fixes the false-alarm flood, 1.3)

**Problem:** hundreds of tests per day with no correction → hundreds of false alarms.

**Algorithm:** collect the p-value of **every** (detector × segment) test in a tick, then apply **Benjamini-Hochberg FDR** at a target `q` (e.g. 10%): sort p-values ascending; find the largest `i` with `p(i) ≤ (i/m)·q`; fire only those. This bounds the *expected fraction of false alarms* to `q` regardless of how many segments exist — which also makes unbounded segment discovery (1.7) safe.

**Where the number comes from:** *Configured* `q` (a policy: "I tolerate 10% false alarms"); everything else *derived*.

**Worked example:** 120 tests in a tick; with raw α=0.05 you'd expect ~6 false alarms every tick. BH at q=0.10 typically fires only the handful of tests whose p-values are genuinely small (e.g. 3), and mathematically guarantees that on average ≤10% of *fired* alarms are false. Daily false alarms drop from ~200 to a small, bounded number.

---

## 2.3 Dynamic baseline synthesis (replaces hand-set targets + flat drift_pct, 1.5 / B4)

**Problem:** targets are frozen guesses; the tolerance band is one-size-fits-all; the reference is contaminated.

**Algorithm (one policy, three cases):**
- **Contractual** (a real SLA like 24 h, 99.5% delivery): the target is **pinned** as a hard floor; never auto-lowered.
- **Earned** (accuracy, match rate, completeness): from the metric's **own trust-weighted history (excluding windows contaminated by recent promotions)**:
  `centre = median(history)`, `spread = 1.4826 × MAD(history)`, `target = centre − k·spread` (for "higher-is-better"), `band = k·spread`.
- **Warm-up:** if sample size `< n_required` (from 2.4), mark *warming-up*, widen the band, and cap severity at "warn."
- **Outcome ratchet:** when a promotion's realised-lift CI lower bound > 0 (a *real* gain), raise the target toward the new centre so the gain becomes the new floor.

**Where the number comes from:** *Derived* (centre/spread from history) + *Learned* (ratchet from outcomes) + *Configured* (`k`, contractual floors).

**Worked example:** observed accuracy history has `median = 0.93`, `MAD = 0.008` → `σ̂ = 0.0119`; with `k=3`, `band = 0.036`, `target floor = 0.894`.
- A *stable* metric (small MAD) gets a **tight** band → catches small real regressions.
- A *noisy* metric with `MAD = 0.04` → `band = 0.18` → a **wide** band → stops false alarms.
- Old code used a flat 0.92 ± 4% for both, which is too loose for the stable one and too tight for the noisy one.

---

## 2.4 Sample size from statistical power (replaces min_sample = 5 / 20 / 30 / 100)

**Problem:** the minimum-sample gates (5, 20, …) are arbitrary; "+2% on 10 cases" is treated as real.

**Algorithm:** given the smallest effect worth detecting `δ`, the significance `α`, and desired power `1−β` (e.g. 0.8), require
`n ≥ (z_α + z_β)² · 2·p(1−p) / δ²` per group. The detector/gate only fires when it has enough data to actually see an effect that size.

**Where the number comes from:** *Configured* (`δ`, power) + *Derived* (`p` from data).

**Worked example:** to detect `δ = 5pp` around `p ≈ 0.10` at α=0.05 (z≈1.96), power 0.8 (z≈0.84):
`n ≥ (1.96+0.84)² · 2·0.10·0.90 / 0.05² = 7.84 · 0.18 / 0.0025 ≈ 565` per group.
So "10 samples" was off by ~50×. The gate now *knows* it needs ~565 to trust a 5pp claim.

---

## 2.5 One normalized opportunity score (replaces ÷3, ÷5, ×10, ÷20 — B5)

**Problem:** every generator invents its own 0–10 or 0–1 formula, so ranking fixes is meaningless.

**Algorithm:** every candidate scores on **one 0–1 scale** as an **expected-value** estimate:
`score = P(fix helps) × normalized_impact`, where
- `P(fix helps)` is a **logistic model learned** from history: features of past candidates (change type, evidence strength, segment) → did the realised lift beat zero?
- `normalized_impact = reach × magnitude`, where `reach` = fraction of traffic in the affected segment and `magnitude` = the size of the drift it addresses, both scaled to 0–1.
- **Cold start:** before enough history exists, fall back to a *derived* proxy — `significance_strength × affected_volume_fraction` — still on 0–1.

**Where the number comes from:** *Learned* (the probability model) → *Derived* (the proxy) → *Fallback*.

**Worked example:** Candidate A: addresses a drift affecting 40% of traffic, historical success probability 0.7 → score `0.7 × (0.40 × 0.8) = 0.224`. Candidate B: 5% of traffic, success 0.9 → `0.9 × (0.05 × 0.9) = 0.041`. A ranks above B — consistently, on the same scale, for *all* generators. Today, A (a threshold generator, ×10) and B (a pattern generator, ÷5) would be on different scales and rank arbitrarily.

---

## 2.6 Distribution-free outlier fences (replaces 2-sigma — bug 1.8 #6)

**Problem:** `mean ± 2σ` assumes a bell curve; business numbers are skewed.

**Algorithm:** use **Tukey fences**: `lower = Q1 − 1.5·IQR`, `upper = Q3 + 1.5·IQR` (IQR = Q3 − Q1). Optionally learn the `1.5` multiplier from how often flagged values were truly problems.

**Worked example:** right-skewed prices `[10,11,12,12,13,14,15,40,42,300]`.
- 2σ rule: `mean≈46.9`, `σ≈86` → upper `≈219` → flags only 300, and its lower bound goes negative (floored to 0), so it never flags suspiciously *low* prices.
- Tukey: `Q1≈12, Q3≈40, IQR≈28` → upper `= 40 + 42 = 82` → flags **42? no (42<82), 300 yes**, and would flag an abnormally low value too. More faithful to "unusual for this data."

---

## 2.7 Confidence-based promotion gate (replaces "+2% and n≥10" — B8)

**Problem:** promotes on a point estimate with no certainty.

**Algorithm:** promote only when the **lower bound of the delta's confidence interval > 0** (using the correct pooled SE), **and** `n ≥ n_required` from 2.4. The "+2%" minimum, if kept at all, becomes a per-metric *configured* floor, not a global constant.

**Where the number comes from:** *Derived* (CI from data) + *Configured* (confidence level, per-metric floor).

**Worked example:** candidate shows +5pp.
- At `n=100/100`: correct CI ±12.9pp → lower bound `−7.9 < 0` → **do not promote** (old code promoted: +5 ≥ 2 and n ≥ 10).
- At `n=1000/1000`: `SE = √(0.80·0.20/1000 + 0.75·0.25/1000) ≈ 0.0207` → CI ±4.1pp → lower bound `+0.9 > 0` → **promote.**
The gate now demands *evidence*, not luck.

---

## 2.8 Causal realised-lift with a control (fixes confounding, 1.2)

**Problem:** all post-promotion change is credited to the promotion.

**Algorithm (best to good):**
1. **Best — concurrent A/B holdout:** keep a small % of traffic on the old rule; compare candidate vs control over the *same* period. Removes season/volume/mix confounds by construction.
2. **Good — difference-in-differences (DiD):** if a holdout isn't possible, subtract the change seen in a comparable *unaffected* segment over the same window from the change in the affected segment.
3. Always compute the delta with the **two-proportion CI** (including control variance).

**Worked example (DiD):** affected segment went 0.85 → 0.91 (+6pp), but a comparable unaffected segment went 0.85 → 0.88 (+3pp) over the same window (a seasonal tailwind). DiD lift = `+6 − 3 = +3pp`, not +6. The naive method would over-credit the promotion by 2×.

---

## 2.9 Representative measurement & the blind-spot fix (fixes 1.1 / 1.6)

**Problem:** quality is measured only on the self-selected reviewed subset; auto-handled cases are invisible.

**Algorithm:**
1. **Stratified audit sample:** randomly select a small, fixed fraction of L4-auto cases for human review, so accuracy is estimated on the *whole population*, not just cases that happened to be reviewed. Weight the estimate by stratum.
2. **Independent corroboration:** on auto cases, use the second-AI opinion (`shadow_classification`) and validation verdicts (`AIOARequest.decision`) as independent quality signals that don't depend on a human looking.
3. **Anti-gaming guard:** monitor per-stage edit rates and terminal-intent rates together, so "improvement" achieved by shoving cases into spam/kso (where edits aren't counted) is visible, not invisible.

**Where the number comes from:** *Configured* audit fraction + *Derived* corroboration rates.

**Worked example:** suppose true L4 accuracy is 0.80 but only the 10% of L4 cases that humans happened to review are counted, and those skew toward easy ones reading 0.95. The metric reports 0.95 — a 15-point illusion. A 2% random audit of *all* L4 cases estimates ~0.80 honestly, and the illusion disappears.

---

# Part 3 — One scenario, end to end, with numbers

**Setting:** a general deployment (not necessarily Keysight). One input type, call it `T`, in region `R`. We follow a real accuracy regression through the whole adaptive loop.

**Step 0 — Signals arrive.** Over the last day, region `R` produced 140 reviewed cases of type `T`, plus a 2% random audit of auto-handled cases (mechanism 2.9). Among the corrections, two are contradictory edits on the same case.

**Step 1 — Trust scoring (2.x / Group D).** The two contradictory edits oscillate, and one of them disagrees with both the second-AI opinion and the validation verdict → both are **quarantined**. A third edit overturns a 0.97-confidence decision → flagged for review but kept at reduced weight. Net: the metric is computed on trustworthy signals only.

**Step 2 — Observe the metric.** On the representative sample (reviewed + audited), accuracy for `(T, R)` = **0.84** at `n = 140`.

**Step 3 — Synthesize the baseline (2.3).** History for `(T, R)`: `median = 0.93`, `MAD = 0.008` → `σ̂ = 0.0119`. With `k = 3`: band `±0.036`, **target floor = 0.894**. Observed 0.84 is below the floor. (Contractual? No — this is an earned metric, so the floor is derived, not pinned.)

**Step 4 — Detect drift correctly (2.1) under FDR (2.2).** Pooled SE for the drop from 0.93 (baseline `n_b≈1200`) to 0.84 (`n_r=140`):
`SE = √(0.93·0.07/1200 + 0.84·0.16/140) = √(0.0000543 + 0.000960) = 0.0318`.
`z = (0.84 − 0.93)/0.0318 ≈ −2.83`, p ≈ 0.0023. Across the 118 other tests this tick, BH-FDR at q=0.10 **confirms** this one fires (its p-value is among the smallest). Power check (2.4): n=140 is enough to detect a 9pp drop. **Real, significant drift.**

**Step 5 — Informative verdict.** The alert reads: *"Accuracy for type T in region R fell to 0.84 (Δ −0.09; 95% CI [−0.15, −0.03]; significant after FDR). Worst sub-segment: R. Likely cause: input-mix shift in R (PSI on R's subject text = 0.34). Recommended fixes: add examples (prompt), keyword patterns."*

**Step 6 — Generate a candidate, scored on one scale (2.5).** A generator proposes adding region-R example phrases to the classifier. Reach = R is 35% of T's traffic; magnitude = the 0.09 drop (normalized ≈ 0.6); historical success probability for this fix type ≈ 0.7. **Score = 0.7 × (0.35 × 0.6) = 0.147**, directly comparable to every other candidate in the queue.

**Step 7 — Backtest on held-out data (Evaluator).** Replay on R cases *not* used to surface the drift, quarantined signals excluded as ground truth. Candidate accuracy 0.92 vs baseline 0.84 on `n = 300/300`.
`SE = √(0.92·0.08/300 + 0.84·0.16/300) = √(0.000245 + 0.000448) = 0.0263`; delta +8pp, **95% CI [+2.8, +13.2]**, lower bound > 0. Power (2.4) satisfied. 

**Step 8 — Confidence gate (2.7).** Lower CI bound +2.8 > 0 and n sufficient → **promote.** (The old "+2% & n≥10" rule would also have said yes here — but it would equally have said yes to a +5% fluke on 10 samples; the new gate would not.)

**Step 9 — Promote as canary + causal watch (2.8).** Roll out to 10% of R traffic, keeping 90% on the old rule as a concurrent control for 48 h. Observed: candidate slice 0.91, control slice 0.86 over the same window. **Difference-in-differences lift = +5pp**, two-proportion CI [+1.5, +8.5], lower bound > 0 → genuine. (A naive pre/post comparison would have read +7pp because R also had a mild seasonal tailwind; DiD strips that out.)

**Step 10 — Ratchet the baseline (2.3 outcome loop).** Because the gain is statistically real, raise `(T, R)`'s target floor from 0.894 toward the new centre (~0.91). The improvement is now the standard the system holds itself to — so silent backsliding to 0.86 would itself trigger drift next time.

**What every number traced back to:** the SEs and bands were **derived** from the data's own counts and variability; the FDR `q`, the power target, the canary %, and the audit fraction were **configured** policies; the fix-success probability and the ratchet were **learned** from outcomes. **Not one decision rested on a constant hand-tuned for one domain.** That is the difference between the system today and a framework that adapts to its input.

---

## Appendix — mapping: frozen number → adaptive mechanism

| Frozen today | Section | Becomes |
|--------------|---------|---------|
| z = 2.0 / 3.0, wrong variance | 2.1 | pooled-SE z, cutoff from FDR + learned precision |
| (no multiple-comparison control) | 2.2 | Benjamini-Hochberg FDR across all tests |
| targets 0.92/0.90/…, flat drift_pct | 2.3 | median ± k·MAD from clean history; pinned contractual floors; outcome ratchet |
| min_sample 5/20/30/100 | 2.4 | required-n from statistical power |
| score ÷3 / ÷5 / ×10 / ÷20 | 2.5 | one 0–1 expected-value score (learned P(helps) × impact) |
| 2-sigma outliers | 2.6 | Tukey IQR fences |
| "+2% & n≥10" gate | 2.7 | CI lower bound > 0 + power |
| pre/post lift (confounded) | 2.8 | A/B holdout or difference-in-differences, correct CI |
| accuracy on reviewed subset only | 2.9 | stratified audit sample + independent corroboration |
| 1e-9 guard / 1.5 cap garbage | 1.8 / 2.x | absolute-change fallback near zero; remove the cap |
