"""Tiny additive migrations.

create_all() makes new tables but won't add columns to existing ones. For the
demo we keep things lean: any new column goes in this list, runs on startup,
no-ops if already applied. SQLite-friendly (one ADD COLUMN per ALTER).

If we ever need real data migrations or downgrades, swap this for Alembic.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("db_migrate")

ADDS: list[tuple[str, str, str]] = [
    ("emails", "account_id", "INTEGER"),
    ("emails", "message_id", "VARCHAR"),
    ("emails", "in_reply_to", "VARCHAR"),
    ("emails", "email_references", "TEXT"),
    ("communication_logs", "delivery_status", "VARCHAR"),
    ("communication_logs", "delivery_error", "TEXT"),
    ("communication_logs", "provider_message_id", "VARCHAR"),
    ("communication_logs", "sent_via_account_id", "INTEGER"),
    ("pipelines", "salesforce_case_id", "VARCHAR"),
    ("email_accounts", "category_folder_map", "TEXT"),
    # === v1.1 TASK-4 ===
    ("pipelines", "existing_case_id", "VARCHAR"),
    ("pipelines", "existing_case_status", "VARCHAR"),
    ("pipelines", "ccc_action", "VARCHAR"),
    ("pipelines", "duplicate_detected", "BOOLEAN"),
    # === v1.1 TASK-5 ===
    ("pipelines", "routing_target", "VARCHAR"),
    ("pipelines", "routing_basis", "VARCHAR"),
    # === v1.1 TASK-6 ===
    ("email_accounts", "region", "VARCHAR"),
    # === v1.1 TASK-9 ===
    ("pipelines", "shadow_classification", "TEXT"),
    # === Tuning → A/B → Promote-to-prod ===
    ("ab_experiments", "kb_namespace", "VARCHAR"),
    ("ab_experiments", "kb_key", "VARCHAR"),
    ("ab_experiments", "control_prompt", "TEXT"),
    ("ab_experiments", "candidate_prompt", "TEXT"),
    ("ab_experiments", "backtest_results", "TEXT"),
    ("ab_experiments", "backtest_ran_at", "DATETIME"),
    # === HITL assignment ===
    ("hitl_tasks", "assignee_user_id", "VARCHAR"),
    ("hitl_tasks", "assignee_name", "VARCHAR"),
    ("hitl_tasks", "assignee_queue", "VARCHAR"),
    ("hitl_tasks", "assigned_at", "DATETIME"),
    ("hitl_tasks", "assigned_by", "VARCHAR"),
    # === A/B experiment redesign ===
    ("ab_experiments", "change_type", "VARCHAR"),
    ("ab_experiments", "previous_body_snapshot", "TEXT"),
    ("ab_experiments", "rolled_back_at", "DATETIME"),
    ("ab_experiments", "rolled_back_by", "VARCHAR"),
    ("ab_experiments", "rolled_back_note", "TEXT"),
    ("ab_experiments", "backtest_sample", "TEXT"),
    # === Monitor service ===
    ("drift_alerts", "fingerprint", "VARCHAR"),
    ("drift_alerts", "delta", "FLOAT"),
    ("drift_alerts", "updated_at", "DATETIME"),
    ("drift_alerts", "detail", "TEXT"),
    # === Continuous Learning v2: RCA + realised lift + solution version ===
    ("learning_opportunities", "linked_rca_ticket_id", "INTEGER"),
    # Realised-lift watcher: production-side reconciliation after promotion.
    ("ab_experiments", "realised_lift_pct", "FLOAT"),
    ("ab_experiments", "realised_lift_ci", "VARCHAR"),
    ("ab_experiments", "realised_lift_at", "DATETIME"),
    ("ab_experiments", "realised_sample_size", "INTEGER"),
    ("ab_experiments", "auto_rolled_back", "BOOLEAN"),
    ("ab_experiments", "realised_note", "TEXT"),
    # Solution-version tagging so cross-deploy comparisons are trivial.
    ("trace_events", "solution_version", "VARCHAR"),
    ("cost_events", "solution_version", "VARCHAR"),
    # Tamper-evident audit chain on promotion decisions.
    ("promotion_decisions", "prev_hash", "VARCHAR"),
    ("promotion_decisions", "entry_hash", "VARCHAR"),
    # Resolved RBAC role + its source at decision time. Lets the audit log
    # answer "what authority did this person have when they clicked?" even
    # if their Salesforce permission set changes later.
    ("promotion_decisions", "decided_by_role", "VARCHAR"),
    ("promotion_decisions", "decided_by_role_source", "VARCHAR"),
    # === Baseline anchor: every Continuous-Learning signal carries the
    # baselines.id it originated from so the UI can offer a drill-through
    # "show every signal anchored to this baseline" view. Populated by the
    # detector at write time; backfilled at startup for legacy rows. ===
    ("drift_alerts", "baseline_id", "INTEGER"),
    ("learning_opportunities", "baseline_id", "INTEGER"),
    ("ab_experiments", "baseline_id", "INTEGER"),
    ("rca_tickets", "baseline_id", "INTEGER"),
    ("feedback", "baseline_id", "INTEGER"),
    # === Concept-baseline consolidation: per-segment evidence is rolled up
    # into one concept-level baseline. The baseline row carries the rollup
    # strategy and the per-segment observations that fed the rolled-up
    # last_observed. Drift alerts carry a top_contributors list ordered
    # worst-first so the operator sees which segment drove the breach. ===
    ("baselines", "segments_observed", "TEXT"),
    ("baselines", "rollup_strategy", "VARCHAR"),
    ("drift_alerts", "top_contributors", "TEXT"),
    # === Signal-graph: per-client scoping so any discovered client is isolated
    # under Continuous Learning. DEFAULT 'keysight' backfills the existing rows. ===
    ("baselines", "domain", "VARCHAR DEFAULT 'keysight'"),
    ("drift_alerts", "domain", "VARCHAR DEFAULT 'keysight'"),
]


# Single-column secondary indexes to add after the columns exist. The
# tuples are (index_name, table, column). CREATE INDEX IF NOT EXISTS is
# safe to re-run and idempotent on SQLite.
INDEXES: list[tuple[str, str, str]] = [
    ("ix_drift_alerts_baseline_id", "drift_alerts", "baseline_id"),
    ("ix_learning_opportunities_baseline_id", "learning_opportunities", "baseline_id"),
    ("ix_ab_experiments_baseline_id", "ab_experiments", "baseline_id"),
    ("ix_rca_tickets_baseline_id", "rca_tickets", "baseline_id"),
    ("ix_feedback_baseline_id", "feedback", "baseline_id"),
]


def _existing_columns(engine: Engine, table: str) -> set[str]:
    insp = inspect(engine)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def apply_lightweight_migrations(engine: Engine, adds: Iterable[tuple[str, str, str]] = ADDS) -> None:
    by_table: dict[str, set[str]] = {}
    with engine.begin() as conn:
        for table, col, sql_type in adds:
            cols = by_table.get(table)
            if cols is None:
                cols = _existing_columns(engine, table)
                by_table[table] = cols
            if col in cols:
                continue
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {sql_type}'))
            cols.add(col)
            log.info("migrated: %s.%s added", table, col)
        for index_name, table, col in INDEXES:
            try:
                conn.execute(text(
                    f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ("{col}")'
                ))
            except Exception as e:
                log.warning("migrated: could not create %s on %s.%s: %s", index_name, table, col, e)
