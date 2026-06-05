"""Per-intent autonomy thresholds.

Continuous-Learning threshold experiments target rows in this namespace. A
promotion writes the new `l4_floor` / `l3_floor` values; the Decide agent
reads the active body from here at decide-time so the change is effective
on the next pipeline run, without a deploy.
"""
from __future__ import annotations

from typing import Any


_INTENTS = [
    "po_intake",
    "quote_to_order",
    "trade_change_order",
    "hold_release",
    "delivery_change",
    "ssd_change_request",
    "service_order",
    "wo_update_request",
    "wo_status_inquiry",
    "service_contract_request",
    "general_inquiry",
]


def all_rules() -> list[dict[str, Any]]:
    return [
        {
            "key": intent,
            "label": f"Autonomy thresholds · {intent.replace('_', ' ')}",
            "description": (
                f"Per-intent autonomy floors used by the Decision agent to choose "
                f"between L4 (auto), L3 (one-click), and L2 (HITL) for {intent}. "
                f"Tuned by Continuous-Learning threshold experiments."
            ),
            "l4_floor": 0.95,
            "l3_floor": 0.80,
            "intent": intent,
            "notes": "Lower means more automation. Raise when the L4 cohort shows a meaningful CSR-edit rate.",
        }
        for intent in _INTENTS
    ]
