"""Concept-level quality baselines the drift detector evaluates against.

Each row is a single concept baseline at `segment="global"` that the
detector resolves into per-segment observations at evaluation time and
rolls up into a single `last_observed` according to the row's
`rollup_strategy`. The per-segment evidence is persisted on the baseline
row in `segments_observed` and surfaced as `top_contributors` on the
DriftAlert emitted when the rollup crosses the target.

Why concept-level: the prior seed shape carried ~30 per-segment rows
(`extraction_completeness @ intent:po_intake`, `extraction_completeness @
intent:service_order`, etc.). Operators saw a long flat list with no
clear "what is the main signal" anchor. The consolidated set has one row
per metric concept and exposes the segment evidence as a secondary,
expandable view on the same row.

Promotion-gate semantics are preserved at the concept level. A baseline
with `severity="block_promotion"` blocks auto-promote when the rolled-up
observation crosses the target. Sub-segment thresholds (for example, PO
intake held to a stricter 0.95 floor inside extraction completeness) are
captured in the rationale and emitted as top contributors when they
breach. The promotion gate fires off the rolled-up value, not off the
individual contributor.

Sources:
  - rfp           : taken verbatim from an explicit RFP success criterion
  - slo           : taken from the published service-level objective
  - customer_sla  : enforced by customer contracts
  - empirical_p50 : 30-day rolling median observed on the live system
"""
from __future__ import annotations

from typing import Any

# Concept-level vocabulary. Each row carries an explicit `rollup_strategy`
# the detector reads when computing `last_observed` from the underlying
# per-segment observations. Add a baseline here AND the matching
# `_observe_metric` rollup branch in monitor.py for the detector to
# evaluate it.
_BASELINE_ROWS: list[dict[str, Any]] = [
    {
        "metric": "extraction_completeness",
        "segment": "global",
        "direction": "min",
        "target_value": 0.90,
        "drift_pct": 5.0,
        "severity": "block_promotion",
        "source": "rfp",
        "unit": "ratio",
        "label": "Extraction completeness",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Extraction completeness gates a case from Extract to Decide. The orchestrator "
            "requires at least 90% of an intent's required fields to be populated before "
            "downstream stages execute. This baseline is the promotion gate; auto-promotion "
            "is suspended while the rolled-up value sits below 0.90. The rollup aggregates "
            "per-intent observations as a sample-weighted average. PO intake carries the "
            "highest volume on this path and is held to a stricter internal floor; when PO "
            "intake regresses it surfaces as a top contributor in the drift alert."
        ),
    },
    {
        "metric": "intent_classification_accuracy",
        "segment": "global",
        "direction": "min",
        "target_value": 0.92,
        "drift_pct": 4.0,
        "severity": "warn",
        "source": "empirical_p50",
        "unit": "ratio",
        "label": "Intent classification accuracy",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Classifier accuracy measured against CSR corrections recorded in the Feedback "
            "ledger across a 30-day rolling window. The rollup is a sample-weighted average "
            "over per-intent and per-region observations so a regression isolated to one "
            "intent or one region (for example, WO update requests or APAC traffic) shows "
            "up as a top contributor instead of being averaged away by the global mix. A "
            "drop below 0.92 indicates the intent knowledge base needs additional positive "
            "examples or refined disambiguation rules."
        ),
    },
    {
        "metric": "customer_match_rate",
        "segment": "global",
        "direction": "min",
        "target_value": 0.85,
        "drift_pct": 5.0,
        "severity": "warn",
        "source": "empirical_p50",
        "unit": "ratio",
        "label": "Customer match rate",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Pipelines that fail to match an inbound message to a known customer record "
            "bypass entitlement, credit, and region-aware routing and divert to the "
            "unknown_customer queue for manual triage. The rollup is a sample-weighted "
            "average across active customer segments. Median match rate over the trailing "
            "30 days holds at 0.93; the 0.85 floor fires only on a meaningful regression."
        ),
    },
    {
        "metric": "language_detection_accuracy",
        "segment": "global",
        "direction": "min",
        "target_value": 0.90,
        "drift_pct": 5.0,
        "severity": "warn",
        "source": "customer_sla",
        "unit": "ratio",
        "label": "Language detection accuracy",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Inbound language detection drives translation glossary selection and reply "
            "tone register. The rollup is a sample-weighted average over per-language "
            "observations. Japanese traffic is the most sensitive contributor; sustained "
            "Japanese detection accuracy below 0.90 degrades reply quality visibly for "
            "Japanese-market customers and increases CSR rewrites at the Communicate stage. "
            "Per-language regressions surface as top contributors on the drift alert."
        ),
    },
    {
        "metric": "p95_stage_latency_ms",
        "segment": "global",
        "direction": "max",
        "target_value": 30000,
        "drift_pct": 20.0,
        "severity": "warn",
        "source": "slo",
        "unit": "ms",
        "label": "Stage p95 latency",
        "rollup_strategy": "max",
        "rationale": (
            "Per-stage p95 latency rolled up by taking the worst-stage observation. Extract "
            "is the longest stage by design at 30s; Intake holds a 5s ceiling; Decide is "
            "expected at 8s. The rollup uses max because user-visible latency is dictated "
            "by the slowest stage, not by an average across stages. The stage that breached "
            "shows up as the top contributor; sustained breaches drive CSR queue depth "
            "growth within the same operating hour."
        ),
    },
    {
        "metric": "autonomy_l4_rate",
        "segment": "global",
        "direction": "min",
        "target_value": 0.55,
        "drift_pct": 10.0,
        "severity": "warn",
        "source": "rfp",
        "unit": "ratio",
        "label": "L4 autonomy rate",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Share of qualifying cases that complete with no human touch. The 55% floor is "
            "the operating target the business case assumes for autonomous throughput. "
            "Sustained drift below this level indicates the confidence scoring is too "
            "conservative or business rules are capping autonomy more aggressively than "
            "policy intends. Per-intent rates roll up as a sample-weighted average."
        ),
    },
    {
        "metric": "hitl_resolution_p95_hours",
        "segment": "global",
        "direction": "max",
        "target_value": 24,
        "drift_pct": 25.0,
        "severity": "block_promotion",
        "source": "customer_sla",
        "unit": "hours",
        "label": "HITL p95 resolution",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Contracted SLA: a case escalated to Human-in-the-Loop review must clear within "
            "24 hours at p95. This baseline is a promotion gate because resolution-time "
            "regressions are the most common post-promotion symptom of an over-aggressive "
            "rule change; auto-promotion is suspended while the rolled-up p95 exceeds the "
            "contracted ceiling. The HITL queue depth ceiling is sized against the "
            "contracted reviewer headcount at p95 inbound volume; deep queues surface as a "
            "contributing signal on the drift alert."
        ),
    },
    {
        "metric": "reply_send_success_rate",
        "segment": "global",
        "direction": "min",
        "target_value": 0.995,
        "drift_pct": 0.5,
        "severity": "block_promotion",
        "source": "slo",
        "unit": "ratio",
        "label": "Reply send success",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Customer-facing reply delivery is a non-negotiable downstream guarantee. Every "
            "drafted reply must leave the configured mailbox; sustained success rates below "
            "99.5% indicate an outbound mail integration failure that puts customer trust "
            "at material risk. Promotion is blocked while this baseline is breached so no "
            "rule change lands on top of a delivery outage. The rollup is a sample-weighted "
            "average across active mailboxes."
        ),
    },
    {
        "metric": "spam_false_positive_rate",
        "segment": "global",
        "direction": "max",
        "target_value": 0.02,
        "drift_pct": 50.0,
        "severity": "warn",
        "source": "empirical_p50",
        "unit": "ratio",
        "label": "Spam false positive rate",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Pre-screen false-positive rate computed from CSR un-discard actions. Sustained "
            "values above 2% indicate genuine customer correspondence is being routed to "
            "the discarded bin and recovered manually. The 50% tolerance band reflects the "
            "small absolute counts in this measurement and reduces noise in the alerting "
            "feed."
        ),
    },
    {
        "metric": "cost_per_pipeline_usd",
        "segment": "global",
        "direction": "max",
        "target_value": 0.45,
        "drift_pct": 30.0,
        "severity": "warn",
        "source": "slo",
        "unit": "usd",
        "label": "Cost per pipeline (USD)",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Aggregate per-pipeline spend across LLM inference, OCR, and translation. The "
            "0.45 USD ceiling reflects the planned model mix in steady-state operation. A "
            "30% drift above this ceiling indicates either model selection has regressed "
            "onto a heavier variant or token consumption per pipeline has inflated through "
            "a prompt or retrieval change."
        ),
    },
    {
        "metric": "aioa_handoff_success_rate",
        "segment": "global",
        "direction": "min",
        "target_value": 0.97,
        "drift_pct": 2.0,
        "severity": "warn",
        "source": "slo",
        "unit": "ratio",
        "label": "AIOA handoff success",
        "rollup_strategy": "weighted_avg",
        "rationale": (
            "Share of autonomous pipelines whose final handoff to the downstream system "
            "completes without rejection or retry. The 97% floor is the operating target; "
            "sustained drift below this band is the leading indicator that approved cases "
            "are failing at the ERP boundary. PO intake carries the highest autonomous "
            "volume and surfaces as a top contributor when its handoff rate regresses. The "
            "rollup is a sample-weighted average across intents."
        ),
    },
    {
        "metric": "psi_intent",
        "segment": "global",
        "direction": "max",
        "target_value": 0.15,
        "drift_pct": 33.0,
        "severity": "warn",
        "source": "empirical_p50",
        # PSI is a dimensionless statistic, not a 0-1 ratio. Rendering it as
        # a percentage (10.9 → "1092.7%") was misleading operators into
        # thinking an extreme breach had occurred when in reality the small
        # window produced an unstable estimate. "score" renders as a plain
        # 3-decimal number (0.150) which matches PSI literature.
        "unit": "score",
        "label": "Intent-mix stability (PSI)",
        "rollup_strategy": "max",
        "rationale": (
            "Population Stability Index for the intent mix observed by the intake "
            "classifier, computed against the 30-day reference window. The rollup uses max "
            "because the worst-shifting intent slice is the signal of interest; averaging "
            "would mask a single intent surging or collapsing. Values above 0.15 indicate "
            "a meaningful shift that may require retraining, glossary updates, or a new "
            "intent definition. Sustained breaches typically precede classifier accuracy "
            "regressions by several days."
        ),
    },
]


def all_baselines() -> list[dict[str, Any]]:
    """Return the concept-level seed rows. Pure data; no DB session required."""
    return list(_BASELINE_ROWS)
