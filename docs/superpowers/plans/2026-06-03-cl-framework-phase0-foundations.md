# Continuous-Learning Framework — Phase 0 (Foundations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the dependency-light `cl_core` package — the typed contracts, the 9 ports, the Domain Profile, the Adaptive Parameter Engine, and a fully-tested pure-Python statistics module — without touching or changing any existing behaviour.

**Architecture:** A new self-contained package at `salesops-solution/backend/app/cl_core/`. It depends on nothing in the existing app (no models, no DB, no agents). The statistics module turns every adaptive formula from the design docs into a small, individually-tested function with known numeric inputs/outputs. The types and ports define the contracts later phases will implement. This phase is purely additive: nothing imports `cl_core` yet, so it cannot change production behaviour.

**Tech Stack:** Python 3.10+, pydantic 2.9.2 (already installed), pytest (added in Task 1), pure-Python `math`/`statistics` (no numpy/scipy).

**Source design docs:**
- `docs/superpowers/specs/2026-06-03-continuous-learning-framework-design.md` (architecture, 9 ports, Adaptive Parameter Engine, phased migration)
- `docs/superpowers/specs/2026-06-03-continuous-learning-adaptive-mechanisms.md` (the 9 algorithms with worked numbers — the test cases below come directly from its worked examples)

**Scope note:** This is the first of nine plans (Phase 0 of the 8-phase migration). It produces working, tested software on its own (a statistics library + contracts) and is safe to merge with zero behavioural impact. Phases 1–8 each get their own plan after this one is complete.

**Conventions for the executor:**
- TDD throughout: write the failing test, see it fail, implement, see it pass, commit.
- All commands run from `salesops-solution/backend/` unless stated otherwise.
- All commits end with the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Run tests with the project venv: `salesops-solution/backend/.venv/Scripts/python -m pytest` on Windows.

---

## File Structure

**Created in this phase:**
- `app/cl_core/__init__.py` — package marker, exports.
- `app/cl_core/stats.py` — pure-Python statistical foundation (the heart of the adaptive math).
- `app/cl_core/segment.py` — the structured `Segment` value type.
- `app/cl_core/types.py` — the typed contracts (Signal, MetricValue, BaselineSpec, DriftVerdict, ArtifactRef, Candidate, EvalResult, PromotionRecord, TrustVerdict, and supporting types).
- `app/cl_core/ports.py` — the 9 `Protocol` interfaces.
- `app/cl_core/parameters.py` — the Adaptive Parameter Engine (resolution + provenance).
- `app/cl_core/domain_profile.py` — the DomainProfile wiring object.
- `tests/cl_core/__init__.py`, `tests/cl_core/test_stats.py`, `test_segment.py`, `test_types.py`, `test_ports.py`, `test_parameters.py`, `test_domain_profile.py`
- `pytest.ini` — test discovery config.
- `requirements-dev.txt` — pytest dependency.

**Modified in this phase:** none of the existing application files. (Only new files + dev tooling.)

---

## Task 1: Version control + test tooling + package skeleton

**Files:**
- Create: `salesops-solution/backend/requirements-dev.txt`
- Create: `salesops-solution/backend/pytest.ini`
- Create: `salesops-solution/backend/app/cl_core/__init__.py`
- Create: `salesops-solution/backend/tests/cl_core/__init__.py`
- Create: `salesops-solution/backend/tests/cl_core/test_smoke.py`

- [ ] **Step 1: Initialise git if the repo is not under version control**

Run from `D:\ZBrain_Project\keysight-salesops-bundle`:
```bash
git rev-parse --is-inside-work-tree 2>NUL || git init
```
If `git init` runs, also create a `.gitignore` at the repo root containing at least:
```
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.sqlite
*.db
```
(If a `.gitignore` already exists, append any missing lines rather than overwriting.)

- [ ] **Step 2: Add the dev dependency file**

Create `salesops-solution/backend/requirements-dev.txt`:
```
pytest==8.3.3
```

- [ ] **Step 3: Install pytest into the project venv**

Run from `salesops-solution/backend`:
```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
```
Expected: pytest installs successfully.

- [ ] **Step 4: Add pytest config**

Create `salesops-solution/backend/pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -q
```

- [ ] **Step 5: Create the package and test package markers**

Create `salesops-solution/backend/app/cl_core/__init__.py`:
```python
"""cl_core — the domain-agnostic continuous-learning framework.

This package contains no Keysight/salesops knowledge. It defines the typed
contracts, the ports (interfaces) that domain adapters implement, the
Adaptive Parameter Engine, and a pure-Python statistics module. Nothing in
the existing application imports this package during Phase 0; it is purely
additive.
"""
```

Create `salesops-solution/backend/tests/cl_core/__init__.py`:
```python
```
(empty file)

- [ ] **Step 6: Write a smoke test that proves the package imports**

Create `salesops-solution/backend/tests/cl_core/test_smoke.py`:
```python
def test_cl_core_imports():
    import app.cl_core  # noqa: F401
```

- [ ] **Step 7: Run the smoke test**

Run from `salesops-solution/backend`:
```bash
.venv/Scripts/python -m pytest tests/cl_core/test_smoke.py -v
```
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add salesops-solution/backend/requirements-dev.txt salesops-solution/backend/pytest.ini salesops-solution/backend/app/cl_core/__init__.py salesops-solution/backend/tests/cl_core/
git commit -m "chore(cl_core): add pytest tooling and package skeleton

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: stats — robust centre and spread (median, MAD, robust sigma)

These replace mean/stdev so outliers don't distort baselines (design mechanism 2.3).

**Files:**
- Create: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Write the failing tests**

Create `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
import math
import pytest
from app.cl_core import stats


def test_median_odd():
    assert stats.median([3, 1, 2]) == 2.0


def test_median_even():
    assert stats.median([1, 2, 3, 4]) == 2.5


def test_median_empty_raises():
    with pytest.raises(ValueError):
        stats.median([])


def test_mad_basic():
    # values 1,2,3,4,5 -> median 3 -> abs devs 2,1,0,1,2 -> median 1
    assert stats.mad([1, 2, 3, 4, 5]) == 1.0


def test_robust_sigma_matches_design_example():
    # design 2.3: median 0.93, MAD 0.008 -> sigma ~= 0.01186
    vals = [0.93, 0.938, 0.922, 0.93, 0.946, 0.914]  # median 0.93, mad 0.008
    assert stats.median(vals) == pytest.approx(0.93, abs=1e-9)
    assert stats.mad(vals) == pytest.approx(0.008, abs=1e-9)
    assert stats.robust_sigma(vals) == pytest.approx(0.0118608, abs=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError` (stats has no `median`).

- [ ] **Step 3: Implement median/MAD/robust_sigma**

Create `salesops-solution/backend/app/cl_core/stats.py`:
```python
"""Pure-Python statistical foundation for the continuous-learning framework.

Every function here is a building block for the adaptive mechanisms described
in docs/superpowers/specs/2026-06-03-continuous-learning-adaptive-mechanisms.md.
No numpy/scipy: keep cl_core dependency-light and portable.
"""
from __future__ import annotations

import math

# 1.4826 scales MAD to approximate the standard deviation for normal data.
_MAD_TO_SIGMA = 1.4826


def median(values: list[float]) -> float:
    """Middle value (average of the two middle values for even counts)."""
    s = sorted(float(v) for v in values)
    n = len(s)
    if n == 0:
        raise ValueError("median() requires at least one value")
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def mad(values: list[float]) -> float:
    """Median absolute deviation: median(|v - median(v)|). Robust to outliers."""
    m = median(values)
    return median([abs(float(v) - m) for v in values])


def robust_sigma(values: list[float]) -> float:
    """Outlier-resistant standard-deviation estimate (1.4826 * MAD)."""
    return _MAD_TO_SIGMA * mad(values)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add robust centre/spread stats (median, MAD, robust sigma)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: stats — normal distribution helpers (CDF, two-sided p-value, inverse CDF)

Needed by the z-score, FDR, and power calculations. Pure-Python, using `math.erf` and Acklam's inverse-normal approximation.

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_normal_cdf_zero_is_half():
    assert stats.normal_cdf(0.0) == pytest.approx(0.5, abs=1e-9)


def test_normal_cdf_196():
    assert stats.normal_cdf(1.96) == pytest.approx(0.9750021, abs=1e-6)


def test_two_sided_p_value_196():
    # |z| = 1.96 -> p ~= 0.05
    assert stats.two_sided_p_value(1.96) == pytest.approx(0.05, abs=1e-3)


def test_normal_ppf_is_inverse_of_cdf():
    assert stats.normal_ppf(0.975) == pytest.approx(1.95996, abs=1e-3)
    assert stats.normal_ppf(0.8) == pytest.approx(0.84162, abs=1e-3)


def test_normal_ppf_domain_guard():
    with pytest.raises(ValueError):
        stats.normal_ppf(0.0)
    with pytest.raises(ValueError):
        stats.normal_ppf(1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `normal_cdf`).

- [ ] **Step 3: Implement the normal helpers**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def normal_cdf(x: float) -> float:
    """Standard-normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_sided_p_value(z: float) -> float:
    """Two-sided p-value for a z statistic."""
    return 2.0 * (1.0 - normal_cdf(abs(z)))


# Coefficients for Acklam's inverse-normal approximation.
_A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
_B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00]
_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def normal_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile function) via Acklam's method.

    Good to ~1e-9 across the central region; ample for sample-size and
    threshold math. Raises for p outside (0, 1).
    """
    if not (0.0 < p < 1.0):
        raise ValueError("normal_ppf() requires 0 < p < 1")
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    if p <= _P_HIGH:
        q = p - 0.5
        r = q * q
        return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
               (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
           ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 11).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add normal CDF, two-sided p-value, inverse-normal (ppf)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: stats — two-proportion SE, z, and delta confidence interval

This is the fix for the wrong-variance drift z-score (failure 1.8 #1) and the wrong realised-lift CI (1.8 #2). Worked numbers come straight from design mechanisms 2.1 and 2.7.

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_two_proportion_se_pooled():
    # design 2.1: p_b=0.02 n_b=1000, p_r=0.022 n_r=500 -> SE ~= 0.007914
    se = stats.two_proportion_se(0.02, 1000, 0.022, 500)
    assert se == pytest.approx(0.007914, abs=1e-5)


def test_two_proportion_z_not_significant():
    # same example -> z ~= 0.253 (old buggy code reported ~3.1)
    z = stats.two_proportion_z(0.02, 1000, 0.022, 500)
    assert z == pytest.approx(0.2527, abs=1e-3)


def test_two_proportion_z_zero_se_returns_zero():
    assert stats.two_proportion_z(0.0, 100, 0.0, 100) == 0.0


def test_proportion_delta_ci_includes_control_variance():
    # design 2.7: realised 0.80 n=100, control 0.75 n=100
    # SE = sqrt(0.80*0.20/100 + 0.75*0.25/100) = 0.058949; half = 1.96*SE = 0.11554
    lo, hi = stats.proportion_delta_ci(0.80, 100, 0.75, 100)
    assert (hi - lo) / 2 == pytest.approx(0.11554, abs=1e-4)
    assert lo == pytest.approx(0.05 - 0.11554, abs=1e-4)
    assert hi == pytest.approx(0.05 + 0.11554, abs=1e-4)


def test_proportion_delta_ci_large_n_lower_bound_positive():
    # design 2.7: at n=1000/1000 the lower bound clears zero -> promotable
    lo, hi = stats.proportion_delta_ci(0.80, 1000, 0.75, 1000)
    assert lo > 0.0


def test_two_proportion_se_bad_n_raises():
    with pytest.raises(ValueError):
        stats.two_proportion_se(0.1, 0, 0.1, 10)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `two_proportion_se`).

- [ ] **Step 3: Implement the two-proportion functions**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def two_proportion_se(p_b: float, n_b: int, p_r: float, n_r: int) -> float:
    """Standard error of the DIFFERENCE between two proportions (pooled form).

    This is the statistically-correct SE for comparing a recent rate to a
    baseline rate. The old code used only the baseline term, underestimating
    the SE and inflating z-scores (failure 1.8 #1).
    """
    if n_b <= 0 or n_r <= 0:
        raise ValueError("two_proportion_se() requires positive sample sizes")
    return math.sqrt(p_b * (1.0 - p_b) / n_b + p_r * (1.0 - p_r) / n_r)


def two_proportion_z(p_b: float, n_b: int, p_r: float, n_r: int) -> float:
    """z statistic for (recent - baseline) using the pooled difference SE."""
    se = two_proportion_se(p_b, n_b, p_r, n_r)
    if se == 0.0:
        return 0.0
    return (p_r - p_b) / se


def proportion_delta_ci(
    p_a: float, n_a: int, p_b: float, n_b: int, z: float = 1.96
) -> tuple[float, float]:
    """Confidence interval for the difference (p_a - p_b).

    Includes BOTH groups' variance (fixes failure 1.8 #2, where the control
    variance was dropped). Returns (lower, upper) on the delta scale.
    """
    se = two_proportion_se(p_b, n_b, p_a, n_a)
    delta = p_a - p_b
    half = z * se
    return (delta - half, delta + half)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 17).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add pooled two-proportion SE, z, and delta CI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: stats — Wilson interval for a single proportion

A correct single-proportion interval (used where we summarise one rate, not a delta).

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_wilson_interval_brackets_point():
    lo, hi = stats.wilson_interval(0.8, 100)
    assert lo < 0.8 < hi
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_interval_known_value():
    # p=0.5, n=100, z=1.96 -> approx (0.4038, 0.5962)
    lo, hi = stats.wilson_interval(0.5, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3)
    assert hi == pytest.approx(0.5962, abs=1e-3)


def test_wilson_interval_bad_n_raises():
    with pytest.raises(ValueError):
        stats.wilson_interval(0.5, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `wilson_interval`).

- [ ] **Step 3: Implement Wilson interval**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def wilson_interval(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a single proportion. Valid at small n and
    near 0/1, unlike the normal approximation."""
    if n <= 0:
        raise ValueError("wilson_interval() requires positive n")
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    margin = (z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))) / denom
    return (centre - margin, centre + margin)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 20).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add Wilson score interval for single proportion

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: stats — Benjamini-Hochberg FDR control

Fixes the multiple-comparisons false-alarm flood (failure 1.3; design mechanism 2.2).

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_bh_fdr_basic():
    # design 2.2 style: only the two smallest p-values clear BH at q=0.1
    flags = stats.benjamini_hochberg([0.001, 0.04, 0.5, 0.2], q=0.1)
    assert flags == [True, True, False, False]


def test_bh_fdr_preserves_input_order():
    flags = stats.benjamini_hochberg([0.5, 0.001, 0.2, 0.04], q=0.1)
    assert flags == [False, True, False, True]


def test_bh_fdr_none_significant():
    flags = stats.benjamini_hochberg([0.4, 0.6, 0.8], q=0.05)
    assert flags == [False, False, False]


def test_bh_fdr_empty():
    assert stats.benjamini_hochberg([], q=0.1) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `benjamini_hochberg`).

- [ ] **Step 3: Implement BH-FDR**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def benjamini_hochberg(pvalues: list[float], q: float = 0.1) -> list[bool]:
    """Benjamini-Hochberg false-discovery-rate control.

    Given p-values from many simultaneous tests, return a boolean list (aligned
    to the input order) marking which tests are significant while bounding the
    expected fraction of false discoveries to q. This is what makes running
    hundreds of detector/segment tests per tick safe.
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    max_rank = 0
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= (rank / m) * q:
            max_rank = rank
    significant_idx = set(order[:max_rank])
    return [i in significant_idx for i in range(m)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 24).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add Benjamini-Hochberg FDR control

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: stats — required sample size from statistical power

Replaces the arbitrary min-sample gates (5/20/30/100) with a power-based number (design mechanism 2.4).

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_required_sample_size_design_example():
    # design 2.4: detect 5pp at p=0.10, alpha=0.05, power=0.8 -> ~565 per group
    n = stats.required_sample_size(p=0.10, mde=0.05, alpha=0.05, power=0.8)
    assert 555 <= n <= 575


def test_required_sample_size_smaller_effect_needs_more():
    n_big = stats.required_sample_size(p=0.10, mde=0.05)
    n_small = stats.required_sample_size(p=0.10, mde=0.025)
    assert n_small > n_big


def test_required_sample_size_bad_mde_raises():
    with pytest.raises(ValueError):
        stats.required_sample_size(p=0.10, mde=0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `required_sample_size`).

- [ ] **Step 3: Implement required_sample_size**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def required_sample_size(
    p: float, mde: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    """Per-group sample size needed to detect a minimum effect `mde` (in
    proportion points) around base rate `p`, at significance `alpha` and the
    given statistical `power`. Two-sided two-proportion approximation.
    """
    if mde <= 0.0:
        raise ValueError("required_sample_size() requires mde > 0")
    z_alpha = normal_ppf(1.0 - alpha / 2.0)
    z_beta = normal_ppf(power)
    n = ((z_alpha + z_beta) ** 2 * 2.0 * p * (1.0 - p)) / (mde * mde)
    return math.ceil(n)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 27).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add power-based required sample size

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: stats — quantile, percentile, and Tukey fences

Provides a correct quantile and the distribution-free outlier fences that replace the 2-sigma rule (failure 1.8 #6; design mechanism 2.6).

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_quantile_linear_interpolation():
    # type-7 quantile on 1..5: q=0.25 -> 2.0, q=0.5 -> 3.0, q=0.75 -> 4.0
    vals = [1, 2, 3, 4, 5]
    assert stats.quantile(vals, 0.25) == pytest.approx(2.0)
    assert stats.quantile(vals, 0.5) == pytest.approx(3.0)
    assert stats.quantile(vals, 0.75) == pytest.approx(4.0)


def test_percentile_p95_small_sample_is_max():
    assert stats.percentile([10, 20, 30], 95) == 30.0


def test_tukey_fences_flag_high_outlier():
    vals = [10, 11, 12, 12, 13, 14, 15, 40, 42, 300]
    lo, hi = stats.tukey_fences(vals)
    assert 300 > hi          # 300 is flagged as a high outlier
    assert 42 <= hi          # 42 is within the fence (not an outlier)


def test_quantile_empty_raises():
    with pytest.raises(ValueError):
        stats.quantile([], 0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `quantile`).

- [ ] **Step 3: Implement quantile, percentile, Tukey fences**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def quantile(values: list[float], q: float) -> float:
    """Type-7 (linear interpolation) quantile, matching NumPy's default."""
    s = sorted(float(v) for v in values)
    n = len(s)
    if n == 0:
        raise ValueError("quantile() requires at least one value")
    if n == 1:
        return float(s[0])
    pos = (n - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(s[int(lo)])
    frac = pos - lo
    return float(s[int(lo)] * (1.0 - frac) + s[int(hi)] * frac)


def percentile(values: list[float], pct: float) -> float:
    """Percentile (pct in 0..100)."""
    return quantile(values, pct / 100.0)


def tukey_fences(values: list[float], k: float = 1.5) -> tuple[float, float]:
    """Distribution-free outlier fences: (Q1 - k*IQR, Q3 + k*IQR).

    Unlike mean +/- 2*sigma, this does not assume a bell curve, so it behaves
    correctly on skewed business data (prices, quantities).
    """
    q1 = quantile(values, 0.25)
    q3 = quantile(values, 0.75)
    iqr = q3 - q1
    return (q1 - k * iqr, q3 + k * iqr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 31).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add quantile, percentile, and Tukey outlier fences

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: stats — smoothed PSI and safe relative delta

Fixes the PSI epsilon-floor distortion (1.8 #5) and the `1e-9` garbage relative delta (1.8 #4).

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_psi_zero_for_identical_distributions():
    counts = {"a": 50, "b": 50}
    assert stats.psi(counts, counts) == pytest.approx(0.0, abs=1e-9)


def test_psi_positive_for_shift():
    expected = {"a": 95, "b": 5}
    actual = {"a": 50, "b": 50}
    assert stats.psi(expected, actual) > 0.2


def test_psi_handles_new_category_without_error():
    # 'c' missing from expected -> Laplace smoothing, no ln(0)/div-by-zero
    expected = {"a": 50, "b": 50}
    actual = {"a": 40, "b": 40, "c": 20}
    val = stats.psi(expected, actual)
    assert val > 0.0 and math.isfinite(val)


def test_safe_relative_delta_normal():
    assert stats.safe_relative_delta(0.84, 0.93) == pytest.approx(0.09 / 0.93, abs=1e-9)


def test_safe_relative_delta_near_zero_uses_absolute():
    # baseline ~ 0: a 0 -> 0.5 jump must NOT explode; returns absolute change
    assert stats.safe_relative_delta(0.5, 0.0) == pytest.approx(0.5, abs=1e-9)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `psi`).

- [ ] **Step 3: Implement smoothed PSI and safe relative delta**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def psi(expected_counts: dict[str, float], actual_counts: dict[str, float]) -> float:
    """Population Stability Index with Laplace (add-one) smoothing.

    Smoothing on raw counts avoids ln(0)/divide-by-zero and the arbitrary
    1e-6 floor in the old code; no artificial cap is applied so genuine large
    shifts are not hidden.
    """
    keys = set(expected_counts) | set(actual_counts)
    k = len(keys)
    if k == 0:
        return 0.0
    e_total = sum(expected_counts.values()) + k
    a_total = sum(actual_counts.values()) + k
    total = 0.0
    for key in keys:
        e = (expected_counts.get(key, 0.0) + 1.0) / e_total
        a = (actual_counts.get(key, 0.0) + 1.0) / a_total
        total += (a - e) * math.log(a / e)
    return total


def safe_relative_delta(current: float, baseline: float, eps: float = 1e-6) -> float:
    """Relative change |current-baseline|/|baseline|, but when baseline is
    ~0 fall back to the ABSOLUTE change instead of dividing by a tiny epsilon
    (which produced astronomically large, then capped, garbage values)."""
    if abs(baseline) < eps:
        return abs(current - baseline)
    return abs(current - baseline) / abs(baseline)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 36).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add smoothed PSI and safe relative delta

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: stats — EWMA online update

The online-update primitive for parameters that adapt continuously (design "shared foundation").

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/stats.py`
- Test: `salesops-solution/backend/tests/cl_core/test_stats.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_stats.py`:
```python
def test_ewma_first_observation_is_seed():
    assert stats.ewma(None, 0.7, alpha=0.3) == 0.7


def test_ewma_blends():
    # 0.3*1.0 + 0.7*0.0 = 0.3
    assert stats.ewma(0.0, 1.0, alpha=0.3) == pytest.approx(0.3, abs=1e-9)


def test_ewma_bad_alpha_raises():
    with pytest.raises(ValueError):
        stats.ewma(0.0, 1.0, alpha=0.0)
    with pytest.raises(ValueError):
        stats.ewma(0.0, 1.0, alpha=1.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: FAIL (no `ewma`).

- [ ] **Step 3: Implement ewma**

Append to `salesops-solution/backend/app/cl_core/stats.py`:
```python
def ewma(prev: float | None, obs: float, alpha: float) -> float:
    """Exponentially-weighted moving average. `alpha` in (0, 1]; higher = more
    weight on the latest observation. A None `prev` seeds with `obs`."""
    if not (0.0 < alpha <= 1.0):
        raise ValueError("ewma() requires 0 < alpha <= 1")
    if prev is None:
        return float(obs)
    return alpha * float(obs) + (1.0 - alpha) * float(prev)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_stats.py -v`
Expected: all passed (now 39).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/stats.py salesops-solution/backend/tests/cl_core/test_stats.py
git commit -m "feat(cl_core): add EWMA online update

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: The Segment value type

Replaces brittle colon-delimited segment strings (failure: unescaped `split(":")` across the code).

**Files:**
- Create: `salesops-solution/backend/app/cl_core/segment.py`
- Test: `salesops-solution/backend/tests/cl_core/test_segment.py`

- [ ] **Step 1: Write the failing tests**

Create `salesops-solution/backend/tests/cl_core/test_segment.py`:
```python
import pytest
from app.cl_core.segment import Segment


def test_key_is_sorted_and_canonical():
    s = Segment(dims={"region": "US", "intent": "po_intake"})
    assert s.key() == "intent=po_intake;region=US"


def test_key_round_trips_through_parse():
    s = Segment(dims={"intent": "po_intake", "region": "US"})
    assert Segment.parse(s.key()).dims == s.dims


def test_key_escapes_separators():
    s = Segment(dims={"note": "a;b=c"})
    parsed = Segment.parse(s.key())
    assert parsed.dims == {"note": "a;b=c"}


def test_parse_legacy_space_colon_form():
    # tolerant of the old "intent:po_intake region:US" strings
    s = Segment.parse("intent:po_intake region:US")
    assert s.dims == {"intent": "po_intake", "region": "US"}


def test_empty_segment_key_is_empty_string():
    assert Segment(dims={}).key() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_segment.py -v`
Expected: FAIL (no module `app.cl_core.segment`).

- [ ] **Step 3: Implement Segment**

Create `salesops-solution/backend/app/cl_core/segment.py`:
```python
"""Structured segment identity.

A Segment is a set of named dimensions (e.g. intent=po_intake, region=US).
`key()` produces a canonical, escaped, collision-free string for use as a
dictionary key or DB column. `parse()` reverses it and is also tolerant of the
legacy "k:v k:v" space-delimited strings used by the old code.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

_ESC = {"\\": "\\\\", "=": "\\=", ";": "\\;"}
_UNESC = {"\\\\": "\\", "\\=": "=", "\\;": ";"}


def _escape(text: str) -> str:
    out = []
    for ch in text:
        out.append(_ESC.get(ch, ch))
    return "".join(out)


def _unescape(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in _UNESC:
            out.append(_UNESC[pair])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _split_unescaped(text: str, sep: str) -> list[str]:
    parts = []
    buf = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            buf.append(text[i:i + 2])
            i += 2
            continue
        if text[i] == sep:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(text[i])
        i += 1
    parts.append("".join(buf))
    return parts


class Segment(BaseModel):
    """A set of named dimensions identifying a slice of traffic."""

    dims: dict[str, str] = Field(default_factory=dict)

    def key(self) -> str:
        """Canonical, escaped, order-independent string key."""
        items = sorted(self.dims.items(), key=lambda kv: kv[0])
        return ";".join(f"{_escape(k)}={_escape(v)}" for k, v in items)

    @classmethod
    def parse(cls, s: str) -> "Segment":
        """Parse a canonical key, or a legacy 'k:v k:v' string."""
        s = (s or "").strip()
        if not s:
            return cls(dims={})
        if "=" in s and ":" not in s.split("=", 1)[0]:
            dims: dict[str, str] = {}
            for token in _split_unescaped(s, ";"):
                if not token:
                    continue
                k, _, v = token.partition("=")
                dims[_unescape(k)] = _unescape(v)
            return cls(dims=dims)
        # Legacy fallback: "intent:po_intake region:US"
        dims = {}
        for token in s.split():
            if ":" in token:
                k, _, v = token.partition(":")
                dims[k] = v
        return cls(dims=dims)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_segment.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/segment.py salesops-solution/backend/tests/cl_core/test_segment.py
git commit -m "feat(cl_core): add structured Segment value type

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Typed contracts — part 1 (Window, Contributor, Signal, MetricValue)

**Files:**
- Create: `salesops-solution/backend/app/cl_core/types.py`
- Test: `salesops-solution/backend/tests/cl_core/test_types.py`

- [ ] **Step 1: Write the failing tests**

Create `salesops-solution/backend/tests/cl_core/test_types.py`:
```python
from datetime import datetime, timedelta
import pytest
from app.cl_core.segment import Segment
from app.cl_core import types as T


def test_signal_defaults_and_required_fields():
    sig = T.Signal(
        id="s1",
        kind="correction",
        subject_ref="pipeline:42",
        segment=Segment(dims={"intent": "po_intake"}),
        polarity=-1.0,
        payload={"from": "quote_to_order", "to": "po_intake"},
        provenance="csr:alice",
        fingerprint="corr:42:intent",
        observed_at=datetime(2026, 6, 3, 12, 0, 0),
    )
    assert sig.weight == 1.0           # default
    assert sig.schema_version == 1     # default
    assert sig.kind == "correction"


def test_signal_rejects_unknown_kind():
    with pytest.raises(Exception):
        T.Signal(
            id="s1", kind="banana", subject_ref="x",
            segment=Segment(dims={}), polarity=0.0, payload={},
            provenance="x", fingerprint="x", observed_at=datetime.utcnow(),
        )


def test_metric_value_carries_sample_size_and_window():
    now = datetime(2026, 6, 3, 12, 0, 0)
    mv = T.MetricValue(
        metric="intent_classification_accuracy",
        segment=Segment(dims={"intent": "po_intake"}),
        value=0.84,
        sample_size=140,
        window=T.Window(start=now - timedelta(days=30), end=now),
    )
    assert mv.sample_size == 140
    assert mv.window.end == now
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_types.py -v`
Expected: FAIL (no module `app.cl_core.types`).

- [ ] **Step 3: Implement part-1 types**

Create `salesops-solution/backend/app/cl_core/types.py`:
```python
"""Typed contracts spoken by every port. No domain concepts live here.

Every persisted/serialised shape carries `schema_version` so JSON blobs can
evolve safely (addresses the unversioned-blob shortcoming).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .segment import Segment

SignalKind = Literal["correction", "outcome", "implicit", "approval"]
TrustStatus = Literal["trusted", "review", "quarantined"]
Severity = Literal["info", "warn", "critical"]
Direction = Literal["min", "max"]
Effort = Literal["Low", "Med", "High"]
Risk = Literal["Low", "Med", "High"]
BaselineProvenance = Literal["pinned_slo", "empirical", "outcome_adjusted", "warming_up"]


class Window(BaseModel):
    """A half-open time window [start, end)."""
    start: datetime
    end: datetime


class Contributor(BaseModel):
    """One sub-segment's contribution to a drift verdict, worst-first."""
    segment: Segment
    value: float
    sample_size: int


class Signal(BaseModel):
    """One piece of evidence the system learns from.

    Generalises the old Feedback row: supports corrections, outcomes, implicit
    signals, and approvals; carries a weight (set by the trust scorer), a
    provenance string, and an idempotency fingerprint.
    """
    schema_version: int = 1
    id: str
    kind: SignalKind
    subject_ref: str
    segment: Segment
    polarity: float
    weight: float = 1.0
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: str
    fingerprint: str
    observed_at: datetime


class MetricValue(BaseModel):
    """A metric observed over one segment and time window. `sample_size` is
    always carried so confidence intervals and power can be computed."""
    schema_version: int = 1
    metric: str
    segment: Segment
    value: float
    sample_size: int
    window: Window
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_types.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/types.py salesops-solution/backend/tests/cl_core/test_types.py
git commit -m "feat(cl_core): add Signal/MetricValue/Window/Contributor contracts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Typed contracts — part 2 (the remaining models)

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/types.py`
- Test: `salesops-solution/backend/tests/cl_core/test_types.py`

- [ ] **Step 1: Append the failing tests**

Append to `salesops-solution/backend/tests/cl_core/test_types.py`:
```python
def test_trust_verdict():
    tv = T.TrustVerdict(signal_id="s1", trust=0.2, status="quarantined",
                        reasons=["oscillation"], corroboration={"shadow_agree": False})
    assert tv.status == "quarantined"


def test_baseline_spec_band_and_provenance():
    bs = T.BaselineSpec(
        metric="intent_classification_accuracy",
        segment=Segment(dims={"intent": "po_intake"}),
        target=0.894, tolerance=(0.036, 0.036), direction="min",
        confidence=0.9, provenance="empirical", sample_size=1200, floor=None,
    )
    assert bs.direction == "min"
    assert bs.tolerance == (0.036, 0.036)


def test_artifact_ref_and_candidate_score_bounds():
    ref = T.ArtifactRef(store="kb", namespace="intent", key="po_intake")
    cand = T.Candidate(
        change_type="prompt", segment=Segment(dims={"intent": "po_intake"}),
        fingerprint="prompt:po_intake", target=ref, current_body={"x": 1},
        proposed_body={"x": 2}, rationale="add examples", score=0.147,
        effort="Low", risk="Low", evidence_refs=["pipeline:1"],
    )
    assert 0.0 <= cand.score <= 1.0
    assert cand.advisory is False


def test_candidate_rejects_out_of_range_score():
    ref = T.ArtifactRef(store="kb", namespace="intent", key="po_intake")
    with pytest.raises(Exception):
        T.Candidate(
            change_type="prompt", segment=Segment(dims={}), fingerprint="x",
            target=ref, current_body=None, proposed_body={}, rationale="x",
            score=1.5, effort="Low", risk="Low",
        )


def test_eval_result_and_promotion_record():
    er = T.EvalResult(
        delta=0.08, delta_ci=(0.028, 0.132), significant=True, power=0.9,
        sample_size=300, baseline_score=0.84, candidate_score=0.92,
        method="data_replay", per_item=[], reproducible=True,
    )
    assert er.significant
    ref = T.ArtifactRef(store="kb", namespace="intent", key="po_intake")
    pr = T.PromotionRecord(
        candidate_fingerprint="prompt:po_intake", artifact=ref,
        from_version=4, to_version=5,
        rollout=T.RolloutPlan(mode="canary", fraction=0.1),
        actor="alice", promoted_at=T.Window(start=T._epoch(), end=T._epoch()).end,
    )
    assert pr.to_version == 5
    assert pr.rollout.mode == "canary"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_types.py -v`
Expected: FAIL (no `TrustVerdict`).

- [ ] **Step 3: Append the remaining types**

Append to `salesops-solution/backend/app/cl_core/types.py`:
```python
from datetime import datetime as _dt


def _epoch() -> _dt:
    """Fixed timestamp helper for tests/builders that must avoid wall-clock."""
    return _dt(1970, 1, 1)


class TrustVerdict(BaseModel):
    """How much a signal can be trusted, and why."""
    schema_version: int = 1
    signal_id: str
    trust: float = Field(ge=0.0, le=1.0)
    status: TrustStatus
    reasons: list[str] = Field(default_factory=list)
    corroboration: dict[str, Any] = Field(default_factory=dict)


class BaselineSpec(BaseModel):
    """A living quality gate. `tolerance` is an asymmetric (down, up) band;
    `floor` (when set) is a contractual value auto-tuning never crosses."""
    schema_version: int = 1
    metric: str
    segment: Segment
    target: float
    tolerance: tuple[float, float]
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: BaselineProvenance
    sample_size: int
    floor: float | None = None


class DriftVerdict(BaseModel):
    """An informative drift finding: how big, how certain, where, why, and
    which fix types to try."""
    schema_version: int = 1
    metric: str
    segment: Segment
    severity: Severity
    observed: float
    baseline: BaselineSpec
    delta: float
    delta_ci: tuple[float, float]
    significant: bool
    statistic: dict[str, Any] = Field(default_factory=dict)
    top_contributors: list[Contributor] = Field(default_factory=list)
    likely_causes: list[str] = Field(default_factory=list)
    recommended_change_types: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ArtifactRef(BaseModel):
    """Points at the tunable thing a change targets (a KB rule today; a model
    config or flag tomorrow). Decouples 'the artifact' from 'a KB row'."""
    store: str
    namespace: str
    key: str
    field: str | None = None


class Candidate(BaseModel):
    """A proposed change, scored on one normalized 0..1 scale for all
    generators."""
    schema_version: int = 1
    change_type: str
    segment: Segment
    fingerprint: str
    target: ArtifactRef
    current_body: dict[str, Any] | None = None
    proposed_body: dict[str, Any]
    rationale: str
    score: float = Field(ge=0.0, le=1.0)
    effort: Effort = "Med"
    risk: Risk = "Low"
    evidence_refs: list[str] = Field(default_factory=list)
    advisory: bool = False


class EvalResult(BaseModel):
    """The result of validating a candidate: delta with a confidence interval,
    significance, power, and a reproducibility flag."""
    schema_version: int = 1
    delta: float
    delta_ci: tuple[float, float]
    significant: bool
    power: float | None = None
    sample_size: int
    baseline_score: float
    candidate_score: float
    method: str
    per_item: list[dict[str, Any]] = Field(default_factory=list)
    reproducible: bool = False


class RolloutPlan(BaseModel):
    """How a promotion is applied: full, canary (a fraction), or per-segment."""
    mode: Literal["full", "canary", "per_segment"] = "full"
    fraction: float | None = None
    segments: list[Segment] = Field(default_factory=list)


class PromotionRecord(BaseModel):
    """Audit record of one promotion, enough to roll back to a prior version."""
    schema_version: int = 1
    candidate_fingerprint: str
    artifact: ArtifactRef
    from_version: int
    to_version: int
    rollout: RolloutPlan
    actor: str
    promoted_at: datetime
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_types.py -v`
Expected: all passed (8 in this file).

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/types.py salesops-solution/backend/tests/cl_core/test_types.py
git commit -m "feat(cl_core): add trust/baseline/drift/candidate/eval/promotion contracts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: The 9 port interfaces

**Files:**
- Create: `salesops-solution/backend/app/cl_core/ports.py`
- Test: `salesops-solution/backend/tests/cl_core/test_ports.py`

- [ ] **Step 1: Write the failing tests**

Create `salesops-solution/backend/tests/cl_core/test_ports.py`:
```python
from app.cl_core import ports


def test_all_nine_ports_exist():
    expected = [
        "SignalSource", "SignalTrustScorer", "Metric", "MetricRegistry",
        "BaselineSynthesizer", "DriftDetector", "CandidateGenerator",
        "KnowledgeStore", "Evaluator", "Promoter",
    ]
    for name in expected:
        assert hasattr(ports, name), f"missing port: {name}"


def test_ports_are_protocols_with_methods():
    # A trivial duck-typed class satisfying SignalSource should be accepted by
    # a structural check (Protocols are runtime_checkable).
    class FakeSource:
        def fetch(self, since, segment=None):
            return []

        def dedup_key(self, raw):
            return "k"

    assert isinstance(FakeSource(), ports.SignalSource)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_ports.py -v`
Expected: FAIL (no module `app.cl_core.ports`).

- [ ] **Step 3: Implement the ports**

Create `salesops-solution/backend/app/cl_core/ports.py`:
```python
"""The 9 ports (interfaces) the framework depends on. Domain adapters
implement these; the core never imports a concrete adapter.

All are runtime_checkable Protocols so adapters need only match the shape
(duck typing), not inherit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Protocol, runtime_checkable

from .segment import Segment
from .types import (
    BaselineSpec,
    Candidate,
    DriftVerdict,
    EvalResult,
    MetricValue,
    PromotionRecord,
    RolloutPlan,
    Signal,
    TrustVerdict,
    Window,
)


@runtime_checkable
class SignalSource(Protocol):
    def fetch(self, since: datetime, segment: Segment | None = None) -> Iterable[Signal]: ...
    def dedup_key(self, raw: Any) -> str: ...


@runtime_checkable
class SignalTrustScorer(Protocol):
    def score(self, signal: Signal, ctx: Any) -> TrustVerdict: ...


@runtime_checkable
class Metric(Protocol):
    name: str
    direction: str
    def observe(self, repo: Any, segment: Segment, window: Window) -> MetricValue | None: ...
    def segments(self, repo: Any, window: Window) -> list[Segment]: ...


@runtime_checkable
class MetricRegistry(Protocol):
    def register(self, metric: Metric) -> None: ...
    def all(self) -> list[Metric]: ...
    def get(self, name: str) -> Metric: ...


@runtime_checkable
class BaselineSynthesizer(Protocol):
    def synthesize(self, metric: Metric, segment: Segment,
                   history: list[MetricValue]) -> BaselineSpec: ...
    def recalibrate(self, current: BaselineSpec, history: list[MetricValue],
                    outcomes: list[PromotionRecord]) -> BaselineSpec: ...


@runtime_checkable
class DriftDetector(Protocol):
    name: str
    def evaluate(self, observed: MetricValue, baseline: BaselineSpec,
                 history: list[MetricValue]) -> DriftVerdict | None: ...


@runtime_checkable
class CandidateGenerator(Protocol):
    change_type: str
    consumes: list[str]
    affects: list[str]
    def generate(self, ctx: Any) -> list[Candidate]: ...


@runtime_checkable
class KnowledgeStore(Protocol):
    def read(self, ref: Any) -> dict | None: ...
    def write(self, ref: Any, body: dict, *, expected_version: int, actor: str) -> int: ...
    def snapshot(self, ref: Any) -> Any: ...
    def history(self, ref: Any) -> list[Any]: ...
    def restore(self, ref: Any, version: int, actor: str) -> None: ...


@runtime_checkable
class Evaluator(Protocol):
    supports: list[str]
    def evaluate(self, candidate: Candidate, dataset: Any) -> EvalResult: ...


@runtime_checkable
class Promoter(Protocol):
    def promote(self, candidate: Candidate, *, rollout: RolloutPlan, actor: str) -> PromotionRecord: ...
    def rollback(self, record: PromotionRecord, *, to_version: int | None) -> None: ...
    def supports_shadow(self, change_type: str) -> bool: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_ports.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/ports.py salesops-solution/backend/tests/cl_core/test_ports.py
git commit -m "feat(cl_core): add the 9 port protocols

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: The Adaptive Parameter Engine

The single source for every tunable number, with the four-source priority (Learned → Derived → Configured → Fallback) and provenance (design Part 2 intro).

**Files:**
- Create: `salesops-solution/backend/app/cl_core/parameters.py`
- Test: `salesops-solution/backend/tests/cl_core/test_parameters.py`

- [ ] **Step 1: Write the failing tests**

Create `salesops-solution/backend/tests/cl_core/test_parameters.py`:
```python
import pytest
from app.cl_core.parameters import AdaptiveParameterEngine


def test_fallback_used_when_nothing_else():
    eng = AdaptiveParameterEngine(fallbacks={"z_cutoff": 2.0})
    res = eng.resolve("z_cutoff")
    assert res.value == 2.0
    assert res.source == "fallback"


def test_configured_beats_fallback():
    eng = AdaptiveParameterEngine(configured={"z_cutoff": 2.5}, fallbacks={"z_cutoff": 2.0})
    res = eng.resolve("z_cutoff")
    assert res.value == 2.5
    assert res.source == "configured"


def test_derived_beats_configured():
    eng = AdaptiveParameterEngine(configured={"k": 3.0}, fallbacks={"k": 3.0})
    eng.register_derived("k", lambda ctx: 2.5)
    res = eng.resolve("k")
    assert res.value == 2.5
    assert res.source == "derived"


def test_learned_beats_derived():
    eng = AdaptiveParameterEngine()
    eng.register_derived("k", lambda ctx: 2.5)
    eng.register_learned("k", lambda ctx: 2.0)
    res = eng.resolve("k")
    assert res.value == 2.0
    assert res.source == "learned"


def test_derived_returning_none_falls_through():
    eng = AdaptiveParameterEngine(configured={"k": 3.0})
    eng.register_derived("k", lambda ctx: None)  # not enough data
    res = eng.resolve("k")
    assert res.value == 3.0
    assert res.source == "configured"


def test_unknown_parameter_raises():
    eng = AdaptiveParameterEngine()
    with pytest.raises(KeyError):
        eng.resolve("nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_parameters.py -v`
Expected: FAIL (no module `app.cl_core.parameters`).

- [ ] **Step 3: Implement the engine**

Create `salesops-solution/backend/app/cl_core/parameters.py`:
```python
"""Adaptive Parameter Engine.

One place that supplies every tunable number, choosing the first available of:
  1. Learned   — from outcome history (callable returns a value or None)
  2. Derived   — computed from current data (callable returns a value or None)
  3. Configured — operator-provided default
  4. Fallback  — documented safe default (the old hardcoded constant)

Every result records which source produced it, so decisions are auditable.
In Phase 0 the Learned/Derived hooks are empty; later phases register them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

ParameterSource = Literal["learned", "derived", "configured", "fallback"]


@dataclass(frozen=True)
class ParameterResult:
    value: Any
    source: ParameterSource


class AdaptiveParameterEngine:
    def __init__(
        self,
        configured: dict[str, Any] | None = None,
        fallbacks: dict[str, Any] | None = None,
    ) -> None:
        self._configured: dict[str, Any] = dict(configured or {})
        self._fallbacks: dict[str, Any] = dict(fallbacks or {})
        self._learned: dict[str, Callable[[Any], Any]] = {}
        self._derived: dict[str, Callable[[Any], Any]] = {}

    def register_learned(self, name: str, fn: Callable[[Any], Any]) -> None:
        self._learned[name] = fn

    def register_derived(self, name: str, fn: Callable[[Any], Any]) -> None:
        self._derived[name] = fn

    def resolve(self, name: str, ctx: Any = None) -> ParameterResult:
        fn = self._learned.get(name)
        if fn is not None:
            v = fn(ctx)
            if v is not None:
                return ParameterResult(v, "learned")
        fn = self._derived.get(name)
        if fn is not None:
            v = fn(ctx)
            if v is not None:
                return ParameterResult(v, "derived")
        if name in self._configured:
            return ParameterResult(self._configured[name], "configured")
        if name in self._fallbacks:
            return ParameterResult(self._fallbacks[name], "fallback")
        raise KeyError(f"no value for parameter {name!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_parameters.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/parameters.py salesops-solution/backend/tests/cl_core/test_parameters.py
git commit -m "feat(cl_core): add Adaptive Parameter Engine with provenance

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: The DomainProfile wiring object

The single object a domain provides: its port implementations, declared vocabularies, and a parameter engine. The core reads only this.

**Files:**
- Create: `salesops-solution/backend/app/cl_core/domain_profile.py`
- Test: `salesops-solution/backend/tests/cl_core/test_domain_profile.py`

- [ ] **Step 1: Write the failing tests**

Create `salesops-solution/backend/tests/cl_core/test_domain_profile.py`:
```python
from app.cl_core.domain_profile import DomainProfile
from app.cl_core.parameters import AdaptiveParameterEngine


def test_domain_profile_construction_and_vocab():
    profile = DomainProfile(
        name="salesops",
        segment_dimensions=["intent", "region", "language"],
        change_types=["prompt", "threshold", "pattern_list", "routing_rule", "validation_rule"],
        metric_names=["intent_classification_accuracy", "extraction_completeness"],
        parameters=AdaptiveParameterEngine(fallbacks={"fdr_q": 0.1}),
    )
    assert profile.name == "salesops"
    assert "intent" in profile.segment_dimensions
    assert profile.parameters.resolve("fdr_q").value == 0.1


def test_domain_profile_ports_optional_in_phase0():
    # Ports default to None so the structure is usable before adapters exist.
    profile = DomainProfile(
        name="toy",
        segment_dimensions=["kind"],
        change_types=["prompt"],
        metric_names=["accuracy"],
        parameters=AdaptiveParameterEngine(),
    )
    assert profile.signal_source is None
    assert profile.promoter is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_domain_profile.py -v`
Expected: FAIL (no module `app.cl_core.domain_profile`).

- [ ] **Step 3: Implement DomainProfile**

Create `salesops-solution/backend/app/cl_core/domain_profile.py`:
```python
"""The DomainProfile: the one object a domain supplies to use the framework.

It declares the domain's vocabularies (segment dimensions, change types,
metric names) and holds the port implementations plus the parameter engine.
Ports are Optional so the structure is usable in Phase 0 before any adapter
exists; later phases populate them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .parameters import AdaptiveParameterEngine
from .ports import (
    BaselineSynthesizer,
    CandidateGenerator,
    DriftDetector,
    Evaluator,
    KnowledgeStore,
    MetricRegistry,
    Promoter,
    SignalSource,
    SignalTrustScorer,
)


@dataclass
class DomainProfile:
    name: str
    segment_dimensions: list[str]
    change_types: list[str]
    metric_names: list[str]
    parameters: AdaptiveParameterEngine

    # Ports — populated by adapters in later phases.
    signal_source: SignalSource | None = None
    trust_scorer: SignalTrustScorer | None = None
    metrics: MetricRegistry | None = None
    baseline_synth: BaselineSynthesizer | None = None
    detectors: list[DriftDetector] = field(default_factory=list)
    generators: list[CandidateGenerator] = field(default_factory=list)
    knowledge_store: KnowledgeStore | None = None
    evaluators: list[Evaluator] = field(default_factory=list)
    promoter: Promoter | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_domain_profile.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add salesops-solution/backend/app/cl_core/domain_profile.py salesops-solution/backend/tests/cl_core/test_domain_profile.py
git commit -m "feat(cl_core): add DomainProfile wiring object

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Package exports + full-suite verification

**Files:**
- Modify: `salesops-solution/backend/app/cl_core/__init__.py`
- Test: `salesops-solution/backend/tests/cl_core/test_smoke.py`

- [ ] **Step 1: Append an exports test**

Append to `salesops-solution/backend/tests/cl_core/test_smoke.py`:
```python
def test_public_exports_present():
    import app.cl_core as cl
    for name in ["stats", "Segment", "DomainProfile", "AdaptiveParameterEngine"]:
        assert hasattr(cl, name), f"cl_core should export {name}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/cl_core/test_smoke.py::test_public_exports_present -v`
Expected: FAIL (exports not defined).

- [ ] **Step 3: Add the exports**

Replace the contents of `salesops-solution/backend/app/cl_core/__init__.py` with:
```python
"""cl_core — the domain-agnostic continuous-learning framework.

This package contains no Keysight/salesops knowledge. It defines the typed
contracts, the ports (interfaces) that domain adapters implement, the
Adaptive Parameter Engine, and a pure-Python statistics module. Nothing in
the existing application imports this package during Phase 0; it is purely
additive.
"""
from . import stats
from .segment import Segment
from .parameters import AdaptiveParameterEngine, ParameterResult
from .domain_profile import DomainProfile

__all__ = [
    "stats",
    "Segment",
    "AdaptiveParameterEngine",
    "ParameterResult",
    "DomainProfile",
]
```

- [ ] **Step 4: Run the entire cl_core suite**

Run from `salesops-solution/backend`:
```bash
.venv/Scripts/python -m pytest tests/cl_core -v
```
Expected: all tests pass (≈ 60 across the files). No warnings about missing imports.

- [ ] **Step 5: Confirm no existing behaviour changed**

Run a quick check that the app still imports (cl_core is additive and unreferenced):
```bash
.venv/Scripts/python -c "import app.main"
```
Expected: no error (or the same behaviour as before this phase — cl_core is not imported by the app).

- [ ] **Step 6: Commit**

```bash
git add salesops-solution/backend/app/cl_core/__init__.py salesops-solution/backend/tests/cl_core/test_smoke.py
git commit -m "feat(cl_core): export public surface and verify full Phase 0 suite

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 0 Definition of Done

- [ ] `app/cl_core/` exists with `stats.py`, `segment.py`, `types.py`, `ports.py`, `parameters.py`, `domain_profile.py`.
- [ ] All `tests/cl_core/` tests pass.
- [ ] The statistics module implements every adaptive primitive the design relies on, each verified against the worked numbers in the design doc.
- [ ] Nothing in the existing application imports `cl_core`; production behaviour is unchanged.
- [ ] All work committed.

**Next plan:** Phase 1 — the data-access (repository) layer, so the engine can read/write through interfaces instead of touching SQLAlchemy models directly. (Separate plan, authored after Phase 0 is complete.)

---

## Self-Review (completed by author)

**Spec coverage:** Phase 0 of the migration plan in the design doc calls for "the typed data shapes, the port definitions, the Domain Profile, and a shared statistics helper (confidence intervals, robust spread)." All four are covered: types (Tasks 12–13), ports (Task 14), DomainProfile (Task 16), stats (Tasks 2–10). The Adaptive Parameter Engine (design Part 2 intro) is added in Task 15. The statistics tasks cover every primitive the 9 mechanisms need: robust centre/spread (2.3), pooled SE + z (2.1), delta CI + Wilson (2.7), BH-FDR (2.2), power-based n (2.4), Tukey fences (2.6), smoothed PSI + safe relative delta (1.8 #4/#5), EWMA (shared foundation).

**Placeholder scan:** No TBD/TODO; every code step contains complete, runnable code and exact commands.

**Type consistency:** `Segment` is used consistently across types/ports/tests. `MetricValue`, `BaselineSpec`, `Candidate`, `EvalResult`, `PromotionRecord`, `RolloutPlan`, `TrustVerdict`, `Window`, `Contributor`, `ArtifactRef` are defined in Task 12–13 and referenced with matching names/fields in ports (Task 14) and tests. `AdaptiveParameterEngine.resolve` returns `ParameterResult(value, source)` — used consistently in Task 15 tests and Task 16. Port method names (`fetch`/`dedup_key`, `observe`/`segments`, `synthesize`/`recalibrate`, `evaluate`, `read`/`write`/`snapshot`/`history`/`restore`, `promote`/`rollback`/`supports_shadow`) match their design-doc signatures.
