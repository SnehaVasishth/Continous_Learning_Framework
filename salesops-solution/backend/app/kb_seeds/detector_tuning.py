"""Detector tuning knobs surfaced as admin-editable KB rows.

Each drift detector previously carried hardcoded sensitivity constants — z
score thresholds, relative regression cutoffs, distribution shift floors,
minimum sample sizes. That made tuning a code change. These rows replace
the constants: a Continuous-Learning admin lowers / raises a threshold,
the next detector tick reads the new value, no deploy needed.

Body shape per row:
  high_threshold:  numeric  — promote to severity="high" above this
  warn_threshold:  numeric  — fire at severity="medium" above this
  min_sample:      int      — minimum recent rows before evaluating
  min_baseline:    int      — minimum baseline rows before evaluating
  notes:           text     — admin-facing rationale for the chosen values

Detectors call `detector_tuning.get(db, key)` and treat missing rows as
"use the historical default". Default values mirror what was hardcoded in
monitor.py before this refactor so behavior is preserved.
"""
from __future__ import annotations

from typing import Any


def all_rules() -> list[dict[str, Any]]:
    return [
        {
            "key": "segment_edit_rate",
            "label": "Detector · per-segment CSR edit rate",
            "description": (
                "Fires when the 24-hour CSR-edit rate per (intent × region) "
                "exceeds the 30-day baseline by more than the z-threshold. "
                "Raise the threshold to reduce noise; lower it to catch "
                "drift earlier."
            ),
            "warn_threshold": 2.0,
            "high_threshold": 3.0,
            "min_sample": 5,
            "min_baseline": 20,
            "notes": "Sigma-based; warn at 2.0 sigma, escalate to high at 3.0 sigma.",
        },
        {
            "key": "stage_hitl_rate",
            "label": "Detector · per-stage HITL fire rate",
            "description": (
                "Fires when 24-hour HITL fire rate per stage climbs more "
                "than the relative threshold above its 30-day baseline."
            ),
            "warn_threshold": 0.5,
            "high_threshold": 1.0,
            "min_sample": 5,
            "min_baseline": 20,
            "notes": "Relative regression; +50% climb fires warn, +100% fires high.",
        },
        {
            "key": "extraction_field_error_rate",
            "label": "Detector · extraction field error rate",
            "description": (
                "Fires when the CSR-correction rate on critical extracted "
                "fields exceeds the absolute threshold."
            ),
            "warn_threshold": 0.10,
            "high_threshold": 0.20,
            "min_sample": 1,
            "min_baseline": 1,
            "notes": "Absolute rate; warn at 10%, high at 20%.",
        },
        {
            "key": "latency_tails",
            "label": "Detector · p95 stage latency regression",
            "description": (
                "Fires when 24-hour p95 latency per stage climbs more than "
                "the relative threshold above the 30-day baseline."
            ),
            "warn_threshold": 0.5,
            "high_threshold": 1.0,
            "min_sample": 5,
            "min_baseline": 5,
            "notes": "Relative regression on p95; +50% slowdown fires warn.",
        },
        {
            "key": "aioa_pass_rate",
            "label": "Detector · AIOA pass-rate drop",
            "description": (
                "Fires when the 24-hour AIOA pass rate drops more than the "
                "absolute percentage-point threshold below the baseline."
            ),
            "warn_threshold": 0.10,
            "high_threshold": 0.20,
            "min_sample": 5,
            "min_baseline": 20,
            "notes": "Drop in pp; warn at 10pp, high at 20pp.",
        },
        {
            "key": "distribution_shift",
            "label": "Detector · intent distribution PSI",
            "description": (
                "Fires when the Population Stability Index between the 24h "
                "intent distribution and the 30-day baseline exceeds the "
                "threshold."
            ),
            "warn_threshold": 0.2,
            "high_threshold": 0.5,
            "min_sample": 1,
            "min_baseline": 1,
            "notes": "PSI; 0.2 is moderate shift, 0.5 is severe.",
        },
        {
            "key": "integration_write_failures",
            "label": "Detector · integration write failure rate",
            "description": (
                "Fires when failure rate for an integration (Salesforce / "
                "SharePoint / ServiceNow) exceeds baseline by the threshold."
            ),
            "warn_threshold": 0.05,
            "high_threshold": 0.10,
            "min_sample": 5,
            "min_baseline": 20,
            "notes": "Absolute delta in pp; warn at +5pp, high at +10pp.",
        },
        {
            "key": "rolling_window_days",
            "label": "Detector · rolling baseline window (days)",
            "description": (
                "Number of days of historical pipelines that constitute the "
                "rolling baseline for every detector. Increase for a more "
                "stable signal, decrease for a faster reaction."
            ),
            "warn_threshold": 30,
            "high_threshold": 30,
            "min_sample": 0,
            "min_baseline": 0,
            "notes": "Single value lookup; `warn_threshold` is read as the window size.",
        },
    ]
