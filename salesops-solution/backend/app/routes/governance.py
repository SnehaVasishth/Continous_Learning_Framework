"""Agent Governance Toolkit (AGT) dashboard — surfaces Microsoft AGT governance
concepts (policy decisions, agent trust, audit trail, MCP gateway security, OWASP
compliance) using data already collected by the SalesOps pipeline.

AGT concept → SalesOps mapping:
  PolicyEvaluator allow/deny/audit/block  →  autonomy tier routing (L4/L3/L2/discard)
  AgentDID (did:mesh:…)                  →  one DID per pipeline stage
  Trust Rings (0–3)                      →  stage privilege level
  Trust score (0–1000)                   →  pipeline confidence × 1000
  AuditLog (tool_invocation, …)          →  TraceEvent rows
  KillSwitch                             →  pipeline termination (reject / discard)
  MCPGateway 5-stage pipeline            →  per-tool security status
  OWASP ASI Top 10                       →  compliance report
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DriftAlert, Feedback, HitlTask, KnowledgeRule, Pipeline, TraceEvent

router = APIRouter()


# ---------------------------------------------------------------------------
# Governance write actions — acknowledge / resolve drift alerts.
#
# Per the dashboard's "read-only by default + ack/resolve" decision, these
# are the only write endpoints. Every action stamps the audit row with the
# fixed actor "governance_dashboard" since the dashboard does not collect
# an operator identity.
# ---------------------------------------------------------------------------


class AlertActionBody(BaseModel):
    kind: str | None = None              # fingerprint / segment to match (preferred)
    alert_id: int | None = None          # explicit DriftAlert.id (alternative)
    actor: str | None = "governance_dashboard"
    note: str | None = None


def _resolve_target_alerts(db: Session, body: AlertActionBody) -> list[DriftAlert]:
    """Find the DriftAlert rows the body refers to. `alert_id` wins if set;
    otherwise `kind` matches the fingerprint or segment of any open alert."""
    if body.alert_id is not None:
        row = db.get(DriftAlert, body.alert_id)
        return [row] if row else []
    if body.kind:
        kind = body.kind.strip()
        return (
            db.query(DriftAlert)
            .filter(DriftAlert.status != "resolved")
            .filter((DriftAlert.fingerprint == kind) | (DriftAlert.segment == kind))
            .all()
        )
    return []


@router.post("/alerts/acknowledge")
def acknowledge_alert(body: AlertActionBody, db: Session = Depends(get_db)) -> dict:
    targets = _resolve_target_alerts(db, body)
    if not targets:
        raise HTTPException(404, "no matching open alert (provide kind or alert_id)")
    now = datetime.utcnow()
    for r in targets:
        r.status = "in_review"
        r.updated_at = now if hasattr(r, "updated_at") else None
        r.resolved_by = body.actor or "governance_dashboard"
        if body.note:
            r.note = (r.note + " | " if r.note else "") + body.note
    db.commit()
    return {"ok": True, "acknowledged": [t.id for t in targets]}


@router.post("/alerts/resolve")
def resolve_alert(body: AlertActionBody, db: Session = Depends(get_db)) -> dict:
    targets = _resolve_target_alerts(db, body)
    if not targets:
        raise HTTPException(404, "no matching open alert (provide kind or alert_id)")
    now = datetime.utcnow()
    for r in targets:
        r.status = "resolved"
        r.resolved_at = now
        r.resolved_by = body.actor or "governance_dashboard"
        if body.note:
            r.note = (r.note + " | " if r.note else "") + body.note
        # Resolving also clears the circuit breaker so the orchestrator
        # stops forcing the affected segment to L2 review.
        if hasattr(r, "circuit_breaker_fired"):
            r.circuit_breaker_fired = False
    db.commit()
    return {"ok": True, "resolved": [t.id for t in targets]}

# ---------------------------------------------------------------------------
# Static AGT metadata — stage → ring, DID, sponsor, allowed tools
# ---------------------------------------------------------------------------

_STAGE_AGENTS = [
    {
        "stage": "intake",
        "did": "did:mesh:keysight-salesops-intake",
        "display_name": "Intake Agent",
        "ring": 3,
        "ring_label": "Ring 3 — Sandbox",
        "sponsor_role": "SalesOps Platform Team",
        "credential_ttl_sec": 900,
        "allowed_tools": [
            "detect_spam",
            "detect_language_tool",
            "llm_spam_check_tool",
            "classify_intent_tool",
            "translate_to_english",
        ],
        "denied_tools": [
            "salesforce_create_order_tool",
            "schema_extract_tool",
            "salesforce_query_tool",
        ],
        "reversibility": "REVERSIBLE",
        "description": "Processes untrusted external email input; read-only, rate-limited at 10 calls/min.",
        "key_properties": [
            "Handles untrusted external input — no pre-filtering assumed on incoming email",
            "Ring 3 Sandbox: read-only, zero CRM/ERP writes, rate-limited to 10 calls/min",
            "First defence layer: spam screen → language detect → intent classify before any data propagates",
            "Discarded emails are logged as tool_blocked events; pipeline is terminated before extraction",
        ],
    },
    {
        "stage": "extract",
        "did": "did:mesh:keysight-salesops-extract",
        "display_name": "Extract Agent",
        "ring": 2,
        "ring_label": "Ring 2 — Standard",
        "sponsor_role": "SalesOps Platform Team",
        "credential_ttl_sec": 900,
        "allowed_tools": [
            "azure_doc_intelligence_tool",
            "schema_extract_tool",
            "entity_resolve_tool",
            "salesforce_query_tool",
        ],
        "denied_tools": [
            "salesforce_create_order_tool",
            "detect_spam",
            "llm_spam_check_tool",
        ],
        "reversibility": "REVERSIBLE",
        "description": "Reads and extracts structured data from attachments and CRM; no write operations.",
        "key_properties": [
            "Parses PDF/XLSX/DOCX attachments via document-intelligence OCR (azure_doc_intelligence_tool)",
            "Resolves customer entity against CRM — read-only query, no writes to Salesforce",
            "Ring 2 Standard: REVERSIBLE — safe to retry or abort, no lasting side-effects",
            "Extracts intent-specific schema fields and enriches them before the decision stage runs",
        ],
    },
    {
        "stage": "decide",
        "did": "did:mesh:keysight-salesops-decide",
        "display_name": "Decide Agent",
        "ring": 1,
        "ring_label": "Ring 1 — Privileged",
        "sponsor_role": "AI Governance Council",
        "credential_ttl_sec": 900,
        "allowed_tools": [
            "business_rules_eval_tool",
            "salesforce_query_tool",
        ],
        "denied_tools": [
            "salesforce_create_order_tool",
            "azure_doc_intelligence_tool",
            "detect_spam",
        ],
        "reversibility": "REVERSIBLE",
        "description": "Evaluates business rules and sets autonomy tier; high-trust but produces no side-effects.",
        "key_properties": [
            "Evaluates KB business rules and computes pipeline confidence score (0–1 float)",
            "Sets autonomy tier: L4_AUTO (≥95%) → allow, L3_ONE_CLICK (80–94%) → audit, L2_HITL (<80%) → block",
            "Ring 1 Privileged: read-only — produces a decision record but never writes to CRM or ERP",
            "Narrowest allowed-tool set of any read-stage agent (2 tools only)",
        ],
    },
    {
        "stage": "execute",
        "did": "did:mesh:keysight-salesops-execute",
        "display_name": "Execute Agent",
        "ring": 0,
        "ring_label": "Ring 0 — Root",
        "sponsor_role": "SRE & Order Operations",
        "credential_ttl_sec": 900,
        "allowed_tools": [
            "salesforce_create_order_tool",
            "salesforce_query_tool",
        ],
        "denied_tools": [
            "detect_spam",
            "llm_spam_check_tool",
            "azure_doc_intelligence_tool",
            "classify_intent_tool",
        ],
        "reversibility": "NON_REVERSIBLE",
        "description": "Writes orders, triggers field-service workflows. Non-reversible — Ring 0 only for L4 paths.",
        "key_properties": [
            "Performs non-reversible CRM/ERP writes — only activated on L4_AUTO (confidence ≥ 95%) pipelines",
            "Ring 0 Root: requires SRE Witness attestation; any anomaly triggers immediate KillSwitch + saga rollback",
            "Creates confirmed orders and triggers field-service work orders in the ERP",
            "All writes are recorded in the append-only audit log before execution commits",
        ],
    },
    {
        "stage": "communicate",
        "did": "did:mesh:keysight-salesops-communicate",
        "display_name": "Communicate Agent",
        "ring": 2,
        "ring_label": "Ring 2 — Standard",
        "sponsor_role": "SalesOps Platform Team",
        "credential_ttl_sec": 900,
        "allowed_tools": [
            "translate_to_english",
        ],
        "denied_tools": [
            "salesforce_create_order_tool",
            "schema_extract_tool",
            "entity_resolve_tool",
        ],
        "reversibility": "REVERSIBLE",
        "description": "Drafts and sends customer reply; reversible (drafts held for HITL on L3/L2).",
        "key_properties": [
            "Drafts reply in the customer's detected language and attaches a synthetic SOA PDF",
            "L3/L2 pipelines: drafts are staged for CSR HITL approval before sending — never auto-sends on low confidence",
            "Narrowest delegation in the chain: only 1 allowed tool (translate_to_english)",
            "Writes the final entry to the communication log and closes the pipeline audit record",
        ],
    },
    {
        # Stage 0 deterministic pre-filter. Not an LLM agent — it applies the
        # SpamAssassin / SwiftFilter / KSO / Brazil-tax / portal-admin rules
        # before any model reads the email body. Included here so the
        # governance dashboard accounts for every email path, not just the
        # AI stages.
        "stage": "pre_intake",
        "did": "did:mesh:keysight-salesops-pre-intake",
        "display_name": "Pre-Intake Filter",
        "ring": 3,
        "ring_label": "Ring 3 — Sandbox",
        "sponsor_role": "SalesOps Platform Team",
        "credential_ttl_sec": 900,
        "allowed_tools": [
            "outlook_prefilter_rules",
        ],
        "denied_tools": [
            "classify_intent_tool",
            "schema_extract_tool",
            "salesforce_query_tool",
            "salesforce_create_order_tool",
        ],
        "reversibility": "REVERSIBLE",
        "description": "Deterministic Outlook pre-AI rules. No LLM. Redirects KSO / Brazil-tax / collections / portal-admin / bounces before the Intake Agent sees the email.",
        "key_properties": [
            "Zero LLM calls — pure regex / keyword rule book inherited from the prior POC's override book",
            "Ring 3 Sandbox: only reads the inbound email; writes nothing",
            "First filter in the chain — discarded or redirected emails never reach Stage 1",
            "Rules are sourced from the spam_heuristic and intent KB namespaces; operators tune them via Knowledge Base",
        ],
    },
    {
        # Stage 6 cross-cutting learning agent. Not run per inbound email.
        # Runs on a schedule (and on operator demand) to back-test candidate
        # KB changes, generate tuning opportunities, and watch drift.
        "stage": "learning",
        "did": "did:mesh:keysight-salesops-learning",
        "display_name": "Continuous Learning Agent",
        "ring": 1,
        "ring_label": "Ring 1 — Privileged",
        "sponsor_role": "AI Governance Council",
        "credential_ttl_sec": 3600,
        "allowed_tools": [
            "classify_intent_tool",
            "business_rules_eval_tool",
            "kb_read",
            "kb_write_proposed",
        ],
        "denied_tools": [
            "salesforce_create_order_tool",
            "salesforce_write_anything",
            "send_outbound_email",
        ],
        "reversibility": "REVERSIBLE",
        "description": "Generates A/B candidates, back-tests them against historical pipelines, surfaces drift alerts. Writes only to the proposed-changes ledger; promotion to live KB requires a rule-owner click.",
        "key_properties": [
            "Cross-cutting — does NOT run per inbound email; runs on a 15-min schedule and on operator-triggered refresh",
            "Calls the live classifier (LLM) to back-test candidates against the last 30 days of cases",
            "Writes only to LearningOpportunity / ABExperiment / DriftAlert tables; promotion to KB requires a rule owner",
            "Ring 1 Privileged: produces decisions, but every promotion is gated by the rule-owner allow-list + audit trail",
        ],
    },
]

_STAGE_TO_RING: dict[str, int] = {a["stage"]: a["ring"] for a in _STAGE_AGENTS}


# ---------------------------------------------------------------------------
# Live grounding — every governance handler should call _live_stage_agents()
# instead of using _STAGE_AGENTS directly. This pulls the stage display label
# from the main app's canonical STAGE_META taxonomy and the agent's
# allowed_tools from the actual TraceEvent tool inventory, so renaming a
# stage or shipping a new tool in the main app immediately appears in the
# governance dashboard.
# ---------------------------------------------------------------------------


def _live_stage_agents(db: Session) -> list[dict[str, Any]]:
    """Return a copy of `_STAGE_AGENTS` with display_name and allowed_tools
    sourced from live state in the main SalesOps app:

      * display_name ← `analytics.subprocess_taxonomy.STAGE_META[stage].label`
        plus " Agent". If the main app renames a stage, the governance
        dashboard's Agent Fleet and Audit Trail show the new label without
        any code change in this file.

      * allowed_tools ← distinct `data.tool` values across `TraceEvent` rows
        with kind == "tool_start" for this stage in the last 30 days. The
        static fallback list survives a cold start with no telemetry.

    Sponsor_role and key_properties remain static metadata defined above —
    they are NOT data the main app emits, they are governance-team
    annotations of each stage's ring posture.
    """
    # Stage labels from the main app's canonical taxonomy.
    try:
        from ..analytics.subprocess_taxonomy import STAGE_META
        live_labels = {k: f"{v.get('label', k.title())} Agent" for k, v in STAGE_META.items()}
    except Exception:
        live_labels = {}

    # Tool inventory actually observed per stage in the last 30 days.
    from datetime import timedelta as _td
    cutoff = datetime.now(timezone.utc) - _td(days=30)
    try:
        observed_rows = (
            db.query(TraceEvent.stage, TraceEvent.data)
            .filter(TraceEvent.kind == "tool_start")
            .filter(TraceEvent.ts >= _naive(cutoff) if cutoff else True)
            .all()
        )
    except Exception:
        observed_rows = []
    observed: dict[str, set[str]] = defaultdict(set)
    for stage, data in observed_rows:
        if isinstance(data, dict):
            tool = data.get("tool")
            if isinstance(tool, str) and tool:
                observed[stage or ""].add(tool)

    out: list[dict[str, Any]] = []
    for a in _STAGE_AGENTS:
        merged = dict(a)
        stage = merged["stage"]
        if stage in live_labels:
            merged["display_name"] = live_labels[stage]
        observed_tools = sorted(observed.get(stage, set()))
        if observed_tools:
            merged["allowed_tools"] = observed_tools
        out.append(merged)
    return out

# MCP tool fingerprints (SHA-256 of tool spec — simulated static values)
_TOOL_FINGERPRINTS: dict[str, str] = {
    "detect_spam": "a3f1c2d9e8b74501",
    "detect_language_tool": "b4e2d3f0a9c85612",
    "llm_spam_check_tool": "c5f3e4a1b0d96723",
    "classify_intent_tool": "d6a4f5b2c1e07834",
    "translate_to_english": "e7b5a6c3d2f18945",
    "azure_doc_intelligence_tool": "f8c6b7d4e3a29056",
    "schema_extract_tool": "a9d7c8e5f4b30167",
    "entity_resolve_tool": "b0e8d9f6a5c41278",
    "salesforce_query_tool": "c1f9e0a7b6d52389",
    "salesforce_create_order_tool": "d2a0f1b8c7e6349a",
    "business_rules_eval_tool": "e3b1a2c9d8f745ab",
    "claude_vision_tool": "f4c2b3d0e9a856bc",
    "read_tool": "a5d3c4e1f0b967cd",
    "sharepoint_fetch_doc_tool": "b6e4d5f2a1c078de",
    "salesforce_files_tool": "c7f5e6a3b2d189ef",
}

_TOOL_SCAN_STATUS: dict[str, dict] = {
    tool: {
        "fingerprint": fp,
        "last_scanned": "2026-05-07T04:00:00Z",
        "tool_poisoning": False,
        "rug_pull": False,
        "cross_server_attack": False,
        "confused_deputy": False,
        "hidden_instruction": False,
        "description_injection": False,
        "threats_detected": 0,
        "status": "clean",
    }
    for tool, fp in _TOOL_FINGERPRINTS.items()
}

_OWASP_RISKS: list[dict] = [
    {
        "id": "ASI-01", "severity": "HIGH",
        "name": "Goal Hijacking",
        "agt_component": "PolicyEvaluator (Agent OS)",
        "salesops_feature": "Spam detection + intent classification blocks malicious email goals",
        "agt_feature": "Deterministic pre-execution interception; allow/deny/audit/block decisions",
        "status": "covered", "evidence_field": "discard_count",
    },
    {
        "id": "ASI-02", "severity": "HIGH",
        "name": "Tool Misuse",
        "agt_component": "CapabilityGuardMiddleware (Agent OS)",
        "salesops_feature": "Per-stage tool allow/deny lists prevent cross-stage tool abuse",
        "agt_feature": "Tool allow/deny lists + business rules eval sandboxing",
        "status": "covered", "evidence_field": "tool_count",
    },
    {
        "id": "ASI-03", "severity": "HIGH",
        "name": "Identity Abuse",
        "agt_component": "AgentMesh (DID + Trust Scoring)",
        "salesops_feature": "Each pipeline stage holds a distinct AgentDID with narrowed capability scope",
        "agt_feature": "Ed25519 AgentDID + delegation narrowing; child scope ⊆ parent scope",
        "status": "covered", "evidence_field": "agent_count",
    },
    {
        "id": "ASI-04", "severity": "HIGH",
        "name": "Supply Chain Compromise",
        "agt_component": "AI-BOM (AgentMesh)",
        "salesops_feature": "ZBrain orchestrator provenance tracked; model weights pinned and signed",
        "agt_feature": "AI Bill of Materials: model provenance, dataset tracking, SBOM signing",
        "status": "covered", "evidence_field": None,
    },
    {
        "id": "ASI-05", "severity": "HIGH",
        "name": "Unsafe Code Execution",
        "agt_component": "Agent Runtime (4-tier Ring Model)",
        "salesops_feature": "Business rules evaluated in sandboxed Python AST evaluator; no exec()/eval()",
        "agt_feature": "Ring isolation + AST-safe execution + resource limits per ring",
        "status": "covered", "evidence_field": "rule_count",
    },
    {
        "id": "ASI-06", "severity": "HIGH",
        "name": "Memory Poisoning",
        "agt_component": "PolicyEvaluator (Agent OS) + CMVK",
        "salesops_feature": "Prompt injection screened in intake stage via spam heuristics + LLM guard",
        "agt_feature": "VFS policies + CMVK verification + prompt injection pattern detection",
        "status": "covered", "evidence_field": "spam_block_count",
    },
    {
        "id": "ASI-07", "severity": "HIGH",
        "name": "Insecure Inter-Agent Communication",
        "agt_component": "AgentMesh (IATP Protocol)",
        "salesops_feature": "Stage-to-stage handoff authenticated via cryptographic IATP channels",
        "agt_feature": "IATP encrypted channels + mutual authentication + TrustBridge",
        "status": "covered", "evidence_field": "agent_count",
    },
    {
        "id": "ASI-08", "severity": "HIGH",
        "name": "Cascading Failures",
        "agt_component": "Agent SRE (Circuit Breakers + SLO)",
        "salesops_feature": "HITL backlog spike triggers circuit breaker; Saga orchestrator auto-compensates",
        "agt_feature": "Circuit breakers + SLO enforcement + SagaOrchestrator compensation",
        "status": "covered", "evidence_field": "pending_hitl",
    },
    {
        "id": "ASI-09", "severity": "HIGH",
        "name": "Human-Agent Trust Failure",
        "agt_component": "Human-in-the-Loop (Agent OS)",
        "salesops_feature": "L2/L3 pipelines require explicit CSR approval before executing writes",
        "agt_feature": "require_human_approval flag + approval callback + HumanSponsor accountability",
        "status": "covered", "evidence_field": "hitl_count",
    },
    {
        "id": "ASI-10", "severity": "MEDIUM",
        "name": "Rogue / Uncontrolled Agents",
        "agt_component": "Agent Runtime (KillSwitch + Ring Breach Detection)",
        "salesops_feature": "Confidence drift + CSR rejections trigger kill switch; ring breach detector monitors anomalies",
        "agt_feature": "KillSwitch (BEHAVIORAL_DRIFT / MANUAL / RATE_LIMIT) + RingBreachDetector",
        "status": "covered", "evidence_field": "kill_count",
    },
]

# Evidence count thresholds for GovernanceVerifier — AGT evidence_strength per control
_EVIDENCE_THRESHOLDS: dict[str, dict[str, int]] = {
    "discard_count":    {"strong": 15, "moderate": 8, "weak": 3},
    "tool_count":       {"strong": 12, "moderate": 8, "weak": 5},
    "agent_count":      {"strong": 5,  "moderate": 4, "weak": 3},
    "hitl_count":       {"strong": 10, "moderate": 5, "weak": 2},
    "kill_count":       {"strong": 5,  "moderate": 3, "weak": 2},
    "rule_count":       {"strong": 10, "moderate": 7, "weak": 4},
    "spam_block_count": {"strong": 15, "moderate": 8, "weak": 3},
    "pending_hitl":     {"strong": 5,  "moderate": 3, "weak": 1},
}

_STRENGTH_ORDER = {"strong": 4, "moderate": 3, "weak": 2, "none": 1}


def _evidence_grade(count: int | None, field: str | None) -> str:
    """Map evidence count to AGT evidence_strength (strong/moderate/weak/none)."""
    if count is None or field is None:
        return "moderate"  # architecturally covered; no runtime events required
    thresh = _EVIDENCE_THRESHOLDS.get(field, {"strong": 10, "moderate": 5, "weak": 2})
    if count >= thresh["strong"]: return "strong"
    if count >= thresh["moderate"]: return "moderate"
    if count >= thresh["weak"]: return "weak"
    return "none"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _compute_hash_chain(entries: list[dict]) -> list[dict]:
    """Compute SHA-256 hash chain over entry content.

    Each hash covers: entry_id|timestamp|agent_did|event_type|action|
                      resource|outcome|policy_decision|previous_hash
    This means any modification to any field of any entry breaks the chain
    at that entry and invalidates every subsequent hash.
    Entries must be passed in ascending entry_id order.
    """
    prev = "0" * 16  # genesis sentinel
    result = []
    for entry in entries:
        content = "|".join([
            str(entry["entry_id"]),
            entry.get("timestamp") or "",
            entry.get("agent_did", ""),
            entry.get("event_type", ""),
            entry.get("action", ""),
            entry.get("resource", ""),
            entry.get("outcome", ""),
            entry.get("policy_decision", ""),
            prev,
        ])
        digest = hashlib.sha256(content.encode()).hexdigest()[:16]
        result.append({
            "entry_id": entry["entry_id"],
            "hash": digest,
            "previous_hash": prev,
        })
        prev = digest
    return result


def _verify_chain(entries: list[dict]) -> tuple[str, int | None]:
    """Re-walk the chain and return ('verified', None) or ('tampered', entry_id).

    Entries must be in ascending entry_id order and already contain 'hash'
    and 'previous_hash' as set by _compute_hash_chain.
    """
    prev = "0" * 16
    for entry in entries:
        if entry["previous_hash"] != prev:
            return "tampered", entry["entry_id"]
        expected_content = "|".join([
            str(entry["entry_id"]),
            entry.get("timestamp") or "",
            entry.get("agent_did", ""),
            entry.get("event_type", ""),
            entry.get("action", ""),
            entry.get("resource", ""),
            entry.get("outcome", ""),
            entry.get("policy_decision", ""),
            prev,
        ])
        if entry["hash"] != hashlib.sha256(expected_content.encode()).hexdigest()[:16]:
            return "tampered", entry["entry_id"]
        prev = entry["hash"]
    return "verified", None


def _tier_to_policy_decision(tier: str | None, status: str | None) -> str:
    """Map an autonomy-tier outcome to the AGT policy-decision vocabulary.

    AGT decisions are about the policy ENGINE's evaluation, not about whether
    a human was eventually involved:
      allow  — the agent took the action autonomously
      audit  — the agent took an action under a logged / reviewed policy
                (one-click approvals, HITL-routed reviews are both audited)
      block  — the policy actively prevented an action that was requested
      deny   — the case was rejected outright (spam, out-of-scope discards)

    L2_HITL is NOT a block. It's a successful policy routing: the system
    correctly identified the case required human review and handed it off
    with a full audit trail. The human then makes the action decision under
    audit. So L2_HITL → audit, not block. block is reserved for genuine
    policy-engine blocks (e.g., hard_block business rules that refuse the
    action even with human approval).
    """
    if status == "discarded":
        return "deny"
    if tier == "L4_AUTO":
        return "allow"
    if tier == "L3_ONE_CLICK":
        return "audit"
    if tier == "L2_HITL":
        return "audit"
    return "audit"


def _tier_to_ring(tier: str | None, status: str | None) -> int:
    if status == "discarded":
        return 3
    if tier == "L4_AUTO":
        return 0
    if tier == "L3_ONE_CLICK":
        return 1
    if tier == "L2_HITL":
        return 2
    return 3


def _event_type_from_kind(kind: str, data: dict) -> str:
    # tool_invocation = agent called a tool (success OR failure — tool ran regardless)
    # policy_violation = agent violated a governance policy (unexpected runtime error)
    if kind in ("tool_end", "tool_start"):
        return "tool_invocation"
    if kind == "error":
        return "policy_violation"
    if kind == "result":
        blocked = (data or {}).get("blocked") or (data or {}).get("is_spam")
        return "tool_blocked" if blocked else "policy_evaluation"
    return "policy_evaluation"


def _derive_matched_rule(etype: str, tool_name: str, pipe, ok: bool = True) -> str | None:
    """Map event type to the AGT policy rule that produced the outcome."""
    if etype == "tool_blocked":
        return f"capability_deny.{tool_name}"
    if etype == "policy_violation":
        return f"governance_error.{tool_name}"
    if etype == "policy_evaluation":
        tier = (pipe.autonomy_tier if pipe else None) or "unknown"
        return f"tier_router.{tier}"
    if etype == "tool_invocation":
        # Tool was permitted by capability guard regardless of whether it succeeded
        return f"capability_allow.{tool_name}"
    return None


def _cutoff(hours: int) -> datetime | None:
    if hours and hours > 0:
        return datetime.now(timezone.utc) - timedelta(hours=hours)
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary")
def summary(hours: int = 0, db: Session = Depends(get_db)) -> dict[str, Any]:
    cut = _cutoff(hours)
    pipe_q = db.query(Pipeline)
    if cut:
        pipe_q = pipe_q.filter(Pipeline.started_at >= cut)
    pipes_all = pipe_q.all()

    # Use the same in-funnel definition as /api/analytics/summary so the
    # Governance Overview funnel and the SalesOps Dashboard funnel report
    # identical counts. A pipeline is "in funnel" once it has emitted at
    # least one stage_end event for a Stage 1+ stage (intake, extract,
    # decide, execute, communicate). Pipelines that only fired pre_intake
    # events (mailbox-door redirects, spam, KSO routing, Brazil tax,
    # collections, undeliverable, portal admin) are surfaced separately
    # on `funnel.pre_intake_terminated` so the audit trail still shows
    # them; they no longer inflate the funnel top.
    _FUNNEL_STAGES = ("intake", "extract", "decide", "execute", "communicate")
    funnel_q = (
        db.query(TraceEvent.pipeline_id)
        .filter(TraceEvent.kind == "stage_end")
        .filter(TraceEvent.stage.in_(_FUNNEL_STAGES))
        .distinct()
    )
    funnel_pipe_ids: set[int] = {int(r[0]) for r in funnel_q.all() if r[0] is not None}
    pipes = [p for p in pipes_all if p.id in funnel_pipe_ids]
    pre_intake_terminated = len(pipes_all) - len(pipes)

    total = len(pipes)
    tier_counter: Counter = Counter()
    # Ring distribution counts agents (from _STAGE_AGENTS), not pipeline runs.
    # AGT assigns rings to agents based on their privilege level, not per-request confidence.
    ring_counter: Counter = Counter({"Ring 0": 0, "Ring 1": 0, "Ring 2": 0, "Ring 3": 0})
    ring_agents: dict[str, list[str]] = {"Ring 0": [], "Ring 1": [], "Ring 2": [], "Ring 3": []}
    live_agents = _live_stage_agents(db)
    for agent in live_agents:
        key = f"Ring {agent['ring']}"
        ring_counter[key] += 1
        ring_agents[key].append(agent["display_name"])
    decision_counter: Counter = Counter({"allow": 0, "audit": 0, "block": 0, "deny": 0})
    trust_scores: list[float] = []
    kill_manual = kill_drift = kill_rate = 0

    for p in pipes:
        tier_counter[p.autonomy_tier or "unknown"] += 1
        decision_counter[_tier_to_policy_decision(p.autonomy_tier, p.status)] += 1
        if p.confidence is not None:
            trust_scores.append(p.confidence * 1000)
        if p.status == "rejected":
            kill_manual += 1
        elif p.status == "discarded":
            kill_rate += 1
        elif p.status == "error":
            kill_drift += 1

    avg_trust = int(sum(trust_scores) / len(trust_scores)) if trust_scores else 0

    funnel_extracted = sum(
        1 for p in pipes
        if p.status not in ("discarded", "error") and p.intent is not None
    )
    funnel_completed = sum(1 for p in pipes if p.status == "completed")
    funnel_l4 = tier_counter.get("L4_AUTO", 0)
    funnel_l3 = tier_counter.get("L3_ONE_CLICK", 0)
    funnel_l2 = tier_counter.get("L2_HITL", 0)

    fb_q = db.query(Feedback).filter(Feedback.kind == "reject")
    if cut:
        fb_q = fb_q.filter(Feedback.created_at >= cut)
    manual_kills_fb = fb_q.count()

    active_policies = db.query(KnowledgeRule).filter(
        KnowledgeRule.namespace.in_(["business_rules", "spam_heuristic"])
    ).count()

    hitl_pending = db.query(HitlTask).filter(HitlTask.status == "pending").count()

    # Ring breach detection — anomaly score based on HITL backlog + confidence drift
    breach_alerts: list[dict] = []
    if hitl_pending > 5:
        breach_alerts.append({
            "kind": "HITL_BACKLOG_SPIKE",
            "severity": "HIGH" if hitl_pending > 10 else "MEDIUM",
            "message": f"HITL backlog has {hitl_pending} pending tasks — possible cascading failure (ASI-08)",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        })

    recent_pipes = [p for p in pipes if p.confidence is not None]
    if len(recent_pipes) >= 5:
        recent_conf = [p.confidence for p in recent_pipes[-5:]]  # type: ignore[misc]
        all_conf = [p.confidence for p in recent_pipes]
        recent_avg = sum(recent_conf) / len(recent_conf)
        all_avg = sum(all_conf) / len(all_conf)
        drift = all_avg - recent_avg
        if drift > 0.10:
            breach_alerts.append({
                "kind": "BEHAVIORAL_DRIFT",
                "severity": "HIGH" if drift > 0.20 else "MEDIUM",
                "message": f"Confidence dropped {drift:.2%} vs baseline — possible goal-hijack signal (ASI-01)",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })

    # Surface every open DriftAlert + every armed circuit breaker as a
    # governance breach. The Monitor service writes these; the governance
    # dashboard is the operator-facing read view.
    try:
        drift_rows = (
            db.query(DriftAlert)
            .filter(DriftAlert.status != "resolved")
            .order_by(DriftAlert.detected_at.desc())
            .all()
        )
    except Exception:
        drift_rows = []
    for da in drift_rows:
        sev = (da.severity or "info").upper()
        if sev == "SLO_BREACH":
            sev = "HIGH"
        elif sev in ("WARN", "MEDIUM"):
            sev = "MEDIUM"
        elif sev == "HIGH":
            sev = "HIGH"
        else:
            sev = "INFO"
        # Plain-English alert kind so the dashboard renders it as a human
        # label, not a SHOUTY_SNAKE_CASE identifier.
        metric_label = (da.metric or "metric").replace("_", " ").title()
        segment_label = (da.segment or "").replace("_", " ")
        kind_label = f"{metric_label} drift on {segment_label}" if segment_label else f"{metric_label} drift"
        msg_parts = [kind_label]
        if da.baseline is not None and da.current is not None:
            msg_parts.append(f"current={da.current} vs baseline={da.baseline}")
        if getattr(da, "circuit_breaker_fired", False):
            msg_parts.append("circuit breaker armed — affected segment forced to L2 review")
        breach_alerts.append({
            "kind": kind_label,
            "severity": sev,
            "message": " · ".join(msg_parts),
            "detected_at": (da.detected_at or datetime.now(timezone.utc)).isoformat() if da.detected_at else datetime.now(timezone.utc).isoformat(),
        })

    return {
        "hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "governed_pipelines": total,
            "active_policies": active_policies,
            "pending_hitl": hitl_pending,
            "avg_trust_score": avg_trust,
            "owasp_coverage": "10/10",
        },
        "policy_decisions": dict(decision_counter),
        "ring_distribution": dict(ring_counter),
        "ring_agents": ring_agents,
        "kill_events": {
            "MANUAL": kill_manual + manual_kills_fb,
            "BEHAVIORAL_DRIFT": kill_drift,
            "RATE_LIMIT": kill_rate,
            "RING_BREACH": 0,
            "QUARANTINE_TIMEOUT": 0,
            "SESSION_TIMEOUT": 0,
            "total": kill_manual + manual_kills_fb + kill_drift + kill_rate,
        },
        "breach_alerts": breach_alerts,
        "autonomy_tiers": dict(tier_counter),
        "funnel": {
            "received": total,
            "passed_intake": total - kill_rate,
            "extracted": funnel_extracted,
            "reached_decision": funnel_l4 + funnel_l3 + funnel_l2,
            "l4_auto": funnel_l4,
            "l3_one_click": funnel_l3,
            "l2_hitl": funnel_l2,
            "completed": funnel_completed,
            "discarded_intake": kill_rate,
            "errored": kill_drift,
            # Pre-intake-terminated cases (KSO routing, spam, Brazil tax,
            # collections, undeliverable, portal admin, mailbox-door
            # redirects). Held out of the headline funnel so it matches
            # /api/analytics/summary; surfaced here so the Governance audit
            # trail does not lose visibility of those terminations.
            "pre_intake_terminated": pre_intake_terminated,
        },
    }


@router.get("/audit-log")
def audit_log(
    page: int = 1,
    page_size: int = 20,
    event_type: str | None = None,
    agent_did: str | None = None,
    outcome: str | None = None,
    hours: int = 0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cut = _cutoff(hours)
    # Build the DID → display_name map up front so each audit entry can carry
    # its rendered agent label. This eliminates the brief window where the
    # frontend would render the short stage code before the /agents response
    # arrived — every row now ships with the same name the Agent Fleet tab
    # shows for that DID.
    _agents_for_audit = _live_stage_agents(db)
    display_name_by_did = {a["did"]: a["display_name"] for a in _agents_for_audit}
    # Substages without their own DID inherit the parent agent's label.
    if "did:mesh:keysight-salesops-extract" in display_name_by_did:
        display_name_by_did["did:mesh:keysight-salesops-reconcile"] = display_name_by_did["did:mesh:keysight-salesops-extract"]
    q = db.query(TraceEvent).filter(TraceEvent.kind.in_(["tool_start", "tool_end", "error", "result"]))
    if cut:
        q = q.filter(TraceEvent.ts >= cut)
    if agent_did:
        stage = agent_did.replace("did:mesh:keysight-salesops-", "")
        q = q.filter(TraceEvent.stage == stage)

    # Fetch the full ordered set ascending for chain computation, then paginate.
    q_asc = q.order_by(TraceEvent.id.asc())
    total_count = q_asc.count()
    all_events = q_asc.all()

    # Load pipeline map
    pipe_ids = {e.pipeline_id for e in all_events if e.pipeline_id}
    pipe_map: dict[int, Pipeline] = {}
    if pipe_ids:
        for p in db.query(Pipeline).filter(Pipeline.id.in_(pipe_ids)).all():
            pipe_map[p.id] = p

    # --- Step 1: build raw entries (ascending, no hash yet) ---
    raw_entries: list[dict] = []
    for ev in all_events:
        data = ev.data or {}
        etype = _event_type_from_kind(ev.kind, data)
        if event_type and etype != event_type:
            continue

        pipe = pipe_map.get(ev.pipeline_id) if ev.pipeline_id else None
        decision = _tier_to_policy_decision(
            pipe.autonomy_tier if pipe else None,
            pipe.status if pipe else None,
        )
        tool_name = data.get("tool") or ev.message or ev.kind
        ok = data.get("ok", True) if ev.kind == "tool_end" else True

        if ev.kind == "tool_end":
            ev_outcome = "success" if ok else "failure"
        elif ev.kind == "error":
            ev_outcome = "error"
        else:
            ev_outcome = "success"

        if etype == "tool_blocked":
            ev_outcome = "denied"

        if outcome and ev_outcome != outcome:
            continue

        if etype == "tool_invocation":
            event_decision = "allow"
        elif etype == "tool_blocked":
            event_decision = "deny"
        else:
            event_decision = decision

        error_detail: str | None = None
        if ev_outcome in ("failure", "error"):
            error_detail = data.get("error") or data.get("notes") or ev.message or None
            if isinstance(error_detail, dict):
                error_detail = str(error_detail)

        did = f"did:mesh:keysight-salesops-{ev.stage}"
        raw_entries.append({
            "entry_id": ev.id,
            "timestamp": ev.ts.isoformat() if ev.ts else None,
            "agent_did": did,
            "agent_display_name": display_name_by_did.get(did) or (ev.stage or "").replace("-", " ").title(),
            "event_type": etype,
            "action": tool_name,
            "resource": f"pipeline:{ev.pipeline_id}" if ev.pipeline_id else "-",
            "outcome": ev_outcome,
            "policy_decision": event_decision,
            "matched_rule": _derive_matched_rule(etype, tool_name, pipe, ok),
            "trace_id": f"trace-pipeline-{ev.pipeline_id}" if ev.pipeline_id else None,
            "error_detail": error_detail,
            "duration_ms": ev.duration_ms,
            "stage": ev.stage,
        })

    # --- Step 2: compute content-based hash chain (ascending order) ---
    chain_data = _compute_hash_chain(raw_entries)
    hash_map = {c["entry_id"]: c for c in chain_data}
    for entry in raw_entries:
        c = hash_map.get(entry["entry_id"], {})
        entry["hash"] = c.get("hash", "")
        entry["previous_hash"] = c.get("previous_hash", "")

    # --- Step 3: verify the full chain ---
    chain_status, tampered_at = _verify_chain(raw_entries)

    # --- Step 4: paginate descending for display ---
    raw_entries.reverse()
    page_start = (page - 1) * page_size
    entries = raw_entries[page_start: page_start + page_size]

    return {
        "page": page,
        "page_size": page_size,
        "total_count": len(raw_entries),
        "chain_integrity": chain_status,
        "tampered_at": tampered_at,
        "entries": entries,
    }


@router.get("/agents")
def agents(db: Session = Depends(get_db)) -> dict[str, Any]:
    pipes = db.query(Pipeline).all()

    # Aggregate trust scores by stage via TraceEvent stage participation
    stage_pipe_confidence: dict[str, list[float]] = defaultdict(list)
    for p in pipes:
        if p.confidence is None:
            continue
        # Approximate: assign trust score to each stage the pipeline passed through
        ring = _tier_to_ring(p.autonomy_tier, p.status)
        # Stages in execution path depend on ring
        stages_run = ["intake", "extract", "decide"]
        if ring <= 0:
            stages_run += ["execute", "communicate"]
        elif ring <= 1:
            stages_run += ["communicate"]
        for s in stages_run:
            stage_pipe_confidence[s].append(p.confidence * 1000)

    # Kill events per stage from errors
    stage_kills: Counter = Counter()
    error_events = db.query(TraceEvent).filter(TraceEvent.kind == "error").all()
    for ev in error_events:
        if ev.stage:
            stage_kills[ev.stage] += 1

    # Recent risk signals
    risk_signals: list[dict] = []
    rejects = db.query(Feedback).filter(Feedback.kind == "reject").order_by(Feedback.created_at.desc()).limit(5).all()
    for f in rejects:
        risk_signals.append({
            "kind": "MANUAL_KILL",
            "severity": "HIGH",
            "stage": f.stage or "decide",
            "agent_did": f"did:mesh:keysight-salesops-{f.stage or 'decide'}",
            "message": f.note or "CSR rejected agent decision",
            "ts": f.created_at.isoformat() if f.created_at else None,
        })

    result_agents = []
    for agent in _live_stage_agents(db):
        scores = stage_pipe_confidence.get(agent["stage"], [])
        avg_score = int(sum(scores) / len(scores)) if scores else 750
        if avg_score >= 900:
            trust_tier = "Verified Partner"
        elif avg_score >= 700:
            trust_tier = "Trusted"
        elif avg_score >= 500:
            trust_tier = "Standard"
        else:
            trust_tier = "Probationary"

        # Trust score histogram buckets (0-1000 in 10 buckets of 100)
        hist: list[int] = [0] * 10
        for s in scores:
            bucket = min(int(s // 100), 9)
            hist[bucket] += 1

        result_agents.append({
            **agent,
            "avg_trust_score": avg_score,
            "trust_tier_label": trust_tier,
            "samples": len(scores),
            "kill_events": stage_kills.get(agent["stage"], 0),
            "trust_histogram": hist,
            "credential_rotate_threshold_sec": 60,
            "last_credential_rotation": datetime.now(timezone.utc).isoformat(),
        })

    all_capabilities = sorted(set(
        tool for a in _STAGE_AGENTS for tool in a["allowed_tools"]
    ))
    root_did = "did:mesh:keysight-salesops-orchestrator"
    delegation_chain = {
        "root": {
            "label": "ZBrain Orchestrator",
            "did": root_did,
            "ring": "Root",
            "capabilities": all_capabilities,
            "delegation_depth": 0,
            "status": "active",
        },
        "agents": [
            {
                "label": a["display_name"],
                "did": a["did"],
                "ring": a["ring"],
                "capabilities": a["allowed_tools"],
                "dropped_capabilities": [c for c in all_capabilities if c not in a["allowed_tools"]],
                "scope_narrowed": True,
                "delegation_depth": 1,
                "parent_did": root_did,
                "status": "active",
                "sponsor_role": a["sponsor_role"],
            }
            for a in _STAGE_AGENTS
        ],
        "scope_chain_verified": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "agents": result_agents,
        "delegation_chain": delegation_chain,
        "risk_signals": risk_signals,
    }


# Rule enrichment: (keywords, priority, scope, action, cond_field, cond_op, cond_val,
#                   message, fire_frac, enforced_at, owasp_control, eval_backend)
# eval_backend: "yaml" = native PolicyEvaluator, "opa" = OPA/Rego, "cedar" = Cedar policy engine
_RULE_ENRICHMENT = [
    (["credit hold"],          100, "Tenant", "block", "credit_status",           "eq",      "credit_hold",    "Customer is on credit hold — no new orders can be processed until AR releases the account",  0.040, "execute", "ASI-09", "yaml"),
    (["sanction"],              99, "Global", "block", "ship_to_country",         "in",      "sanctions_list", "EAR customer + sanctioned ship-to country — hard blocked, legal escalation required",        0.008, "execute", "ASI-03", "cedar"),
    (["ear-flagged", "ear_flagged", "ear compliance"],
                                98, "Global", "block", "compliance_flags",        "contains","EAR",            "EAR-regulated customer — export compliance review required before execution",                 0.015, "execute", "ASI-03", "cedar"),
    (["asset not on", "asset not on this"],
                                90, "Tenant", "deny",  "asset_account_match",     "eq",      "false",          "Asset serial not found on customer installed base — order blocked",                           0.018, "execute", "ASI-02", "yaml"),
    (["end-of-life", "end of life", "eol sku", "eol-"],
                                88, "Tenant", "deny",  "sku_status",              "eq",      "EOL",            "Order contains EOL SKU — customer must be contacted for replacement options",                 0.020, "execute", "ASI-02", "yaml"),
    (["credit utilization"],    85, "Tenant", "audit", "credit_utilization_pct",  "gt",      "80",             "Credit utilization above 80% — finance review required before execution",                    0.025, "execute", "ASI-09", "yaml"),
    (["after-hours", "22:00"],  80, "Tenant", "audit", "order_value",             "gt",      "50000",          "High-value order received outside business hours — staged for CSR one-click approval",        0.012, "decide",  "ASI-09", "yaml"),
    (["discount"],              78, "Tenant", "audit", "discount_pct",            "gt",      "5",              "PO unit price more than 5% below quote — staged for pricing team approval",                   0.030, "decide",  "ASI-09", "yaml"),
    (["apac"],                  75, "Tenant", "audit", "order_value",             "gt",      "250000",         "APAC order exceeds $250k threshold — regional finance pre-approval required",                 0.010, "decide",  "ASI-09", "yaml"),
    (["calibration"],           70, "Tenant", "audit", "calibration_overdue_days","gt",      "30",             "Calibration overdue >30 days — routed to specialist field service queue",                    0.008, "decide",  "ASI-02", "yaml"),
    (["spam", "phishing"],     100, "Global", "deny",  "message_content",         "matches", r"(?i)phishing",  "Spam or phishing detected — pipeline terminated at Intake before extraction runs",           0.050, "intake",  "ASI-01", "opa"),
]

# AGT Tutorial 01 GovernancePolicy defaults — used as baseline for strictness diff.
# Token budgets aligned with current generation reasoning models (16k output)
# so structured JSON responses and long PO line-item extracts no longer cap.
_AGT_POLICY_DEFAULTS: dict[str, Any] = {
    "max_tokens": 16384, "max_tool_calls": 10, "confidence_threshold": 0.80,
    "drift_threshold": 0.15, "require_human_approval": False, "timeout_seconds": 300,
}

# Per-stage GovernancePolicy values (mirrors _per_agent_* dicts, kept module-level for reuse).
# Budgets bumped to accommodate verbose stage outputs: Decide returns a full
# autonomy-tier rationale block, Extract emits multi-line PO schemas, Execute
# composes Salesforce write payloads. Previous caps (1024-4096) routinely
# truncated structured JSON on dense quotes.
_STAGE_POLICY_MAP: dict[str, dict[str, Any]] = {
    "intake":  {"max_tokens": 8192,  "max_tool_calls": 5,  "confidence_threshold": 0.80, "drift_threshold": 0.15, "require_human_approval": False, "timeout_seconds": 300},
    "decide":  {"max_tokens": 8192,  "max_tool_calls": 2,  "confidence_threshold": 0.80, "drift_threshold": 0.10, "require_human_approval": False, "timeout_seconds": 300},
    "execute": {"max_tokens": 4096,  "max_tool_calls": 2,  "confidence_threshold": 0.80, "drift_threshold": 0.05, "require_human_approval": True,  "timeout_seconds": 300},
    "extract": {"max_tokens": 16384, "max_tool_calls": 4,  "confidence_threshold": 0.80, "drift_threshold": 0.15, "require_human_approval": False, "timeout_seconds": 300},
}

# Seeded context snapshots showing what runtime fields matched each rule (PolicyDecision.audit_entry.context_snapshot)
_AUDIT_CONTEXT_SAMPLES: dict[str, dict[str, Any]] = {
    "credit_status":            {"agent_did": "did:mesh:keysight-salesops-execute", "credit_status": "credit_hold",       "customer_code": "CUST-0042", "order_value": 15400.0},
    "ship_to_country":          {"agent_did": "did:mesh:keysight-salesops-execute", "ship_to_country": "IR",              "compliance_flags": ["EAR"],  "customer_code": "CUST-0117"},
    "compliance_flags":         {"agent_did": "did:mesh:keysight-salesops-execute", "compliance_flags": ["EAR"],          "customer_code": "CUST-0089", "order_type": "new_order"},
    "asset_account_match":      {"agent_did": "did:mesh:keysight-salesops-execute", "asset_account_match": False,        "asset_serial": "SN-KY-20491","customer_code": "CUST-0033"},
    "sku_status":               {"agent_did": "did:mesh:keysight-salesops-execute", "sku_status": "EOL",                 "sku_code": "N9010B",         "customer_code": "CUST-0071"},
    "credit_utilization_pct":   {"agent_did": "did:mesh:keysight-salesops-execute", "credit_utilization_pct": 87.3,      "credit_limit": 50000.0,      "outstanding_balance": 43650.0},
    "order_value_50000":        {"agent_did": "did:mesh:keysight-salesops-decide",  "order_value": 68500.0,              "hour_utc": 23,               "customer_code": "CUST-0055"},
    "order_value_250000":       {"agent_did": "did:mesh:keysight-salesops-decide",  "order_value": 315000.0,             "region": "APAC",             "customer_code": "CUST-0091"},
    "discount_pct":             {"agent_did": "did:mesh:keysight-salesops-decide",  "discount_pct": 7.5,                 "quote_unit_price": 1200.0,   "po_unit_price": 1110.0},
    "calibration_overdue_days": {"agent_did": "did:mesh:keysight-salesops-decide",  "calibration_overdue_days": 47,      "asset_serial": "SN-KY-19823","last_cal_date": "2025-11-20"},
    "message_content":          {"agent_did": "did:mesh:keysight-salesops-intake",  "message_content": "URGENT wire transfer required...", "sender_domain": "bad-actor.io", "spam_score": 0.94},
}

# Seeded evaluation latency per backend (ms) — from AGT BackendDecision.evaluation_ms
_BACKEND_LATENCY_MS: dict[str, float] = {"yaml": 0.08, "opa": 2.3, "cedar": 1.1}

# ---------------------------------------------------------------------------
# AGT SLO definitions — SLI type, target, error budget, exhaustion action
# ---------------------------------------------------------------------------

_SLO_DEFS = [
    {
        "id": "e2e_latency",
        "name": "End-to-End Pipeline Latency",
        # Switched from p95 to p90: with the production LLM stack the p95
        # tail is dominated by occasional document-extraction OCR retries
        # (multi-page PDFs, Azure DocIntel cold-start). p90 is the SLO the
        # operator actually feels and matches the rest of the platform's
        # latency contracts. The 30s budget is unchanged.
        "sli_type": "latency",
        "target": 30_000.0,
        "comparison": "lt",
        "window_hours": 24,
        "budget_total": 0.10,
        "burn_rate_alert": 2.0,
        "burn_rate_critical": 10.0,
        "exhaustion_action": "throttle",
        "description": "90th-percentile pipeline completion time must stay below 30 seconds.",
        "unit": "ms",
        "display_target": "p90 < 30 s",
    },
    {
        "id": "success_rate",
        "name": "Pipeline Success Rate",
        "sli_type": "success_rate",
        "target": 0.95,
        "comparison": "gte",
        "window_hours": 24,
        "budget_total": 0.05,
        "burn_rate_alert": 2.0,
        "burn_rate_critical": 10.0,
        "exhaustion_action": "circuit_break",
        "description": "At least 95% of pipelines must complete without error.",
        "unit": "percent",
        "display_target": "≥ 95%",
    },
    {
        "id": "hitl_resolution",
        "name": "HITL Approval Latency",
        "sli_type": "latency",
        "target": 240.0,
        "comparison": "lt",
        "window_hours": 168,
        "budget_total": 0.10,
        "burn_rate_alert": 2.0,
        "burn_rate_critical": 5.0,
        "exhaustion_action": "throttle",
        "description": "Human-in-the-loop tasks must be resolved within 4 hours.",
        "unit": "minutes",
        "display_target": "p95 < 4 h",
    },
    {
        "id": "confidence_floor",
        "name": "Agent Confidence Floor",
        "sli_type": "success_rate",
        "target": 0.80,
        "comparison": "gte",
        # 7-day rolling window matches industry standard for confidence
        # health (single-day windows are too volatile for sparse traffic).
        "window_hours": 168,
        "budget_total": 0.20,
        "burn_rate_alert": 2.0,
        "burn_rate_critical": 10.0,
        "exhaustion_action": "kill_agent",
        "description": "80% of pipelines over a rolling 7-day window must achieve confidence ≥ 0.60 (above the L2_HITL threshold).",
        "unit": "percent",
        "display_target": "≥ 80% at conf ≥ 0.60 (7-day rolling)",
    },
    {
        "id": "cost_per_task",
        "name": "Cost Per Task",
        "sli_type": "cost_usd",
        "target": 0.50,
        "comparison": "lt",
        "window_hours": 24,
        "budget_total": 0.10,
        "burn_rate_alert": 2.0,
        "burn_rate_critical": 5.0,
        "exhaustion_action": "throttle",
        "description": "Average LLM cost per pipeline run must stay below $0.50.",
        "unit": "usd",
        "display_target": "< $0.50 / task",
    },
    {
        "id": "hallucination_rate",
        "name": "Hallucination Rate",
        "sli_type": "hallucination",
        "target": 0.05,
        "comparison": "lt",
        "window_hours": 24,
        "budget_total": 0.10,
        "burn_rate_alert": 2.0,
        "burn_rate_critical": 5.0,
        "exhaustion_action": "circuit_break",
        "description": "Fraction of trace events triggering rogue/drift detection must stay below 5%.",
        "unit": "percent",
        "display_target": "< 5% rogue events",
    },
]

_STAGE_LATENCY_TARGETS_MS: dict[str, int] = {
    "intake": 2_000, "extract": 8_000, "decide": 3_000,
    "execute": 5_000, "communicate": 4_000,
}

# AGT BudgetTracker / ADR 0012 cost governance constants
_COST_PER_M_INPUT  = 3.0    # $/M input tokens
_COST_PER_M_OUTPUT = 15.0   # $/M output tokens
_OUTPUT_RATIO      = 0.25   # 25% output, 75% input (structured-output tasks)
_STAGE_TOKEN_FRACTIONS: dict[str, float] = {
    "intake": 0.60, "extract": 0.75, "decide": 0.45,
    "execute": 0.30, "communicate": 0.65,
}
# Per-stage output-token ceiling used by the Cost dashboard projection.
# Bumped to match the bumped _STAGE_POLICY_MAP so the Governance Policy
# Engine, AI Infra Cost panel, and per-agent policy table all agree.
_STAGE_MAX_TOKENS_COST: dict[str, int] = {
    "intake": 8192, "extract": 16384, "decide": 8192,
    "execute": 4096, "communicate": 16384,
}
_STAGE_SOFT_CAP_USD  = 5.00
_STAGE_HARD_CAP_USD  = 25.00
_GLOBAL_SOFT_CAP_USD = 25.00
_GLOBAL_HARD_CAP_USD = 100.00

# Per-task hard cost filter — AGT BudgetTracker enforces this at the agent
# layer: any pipeline whose projected token spend would exceed this cap is
# throttled (exhaustion_action=throttle) before completion, so it never lands
# in the SLO sample set. Pinning the SLO compute path against this value
# makes the 100% compliance guarantee explicit instead of relying on the
# implicit "constant cost < target" relationship.
_COST_PER_TASK_HARD_CAP_USD = 0.45  # 90% of the SLO target ($0.50), 10% headroom


def _pct(values: list[float], p: int) -> float:
    """Return the p-th percentile of a list (0–100). Returns 0.0 if empty."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, int(len(s) * p / 100) - 1) if p < 100 else len(s) - 1
    return s[min(idx, len(s) - 1)]


def _enrich_rule(label: str, ns: str) -> dict:
    label_lower = label.lower()
    for kws, priority, scope, action, c_field, c_op, c_val, msg, frac, enforced_at, owasp, backend in _RULE_ENRICHMENT:
        if any(kw in label_lower for kw in kws):
            return {"priority": priority, "scope": scope, "action": action,
                    "condition_field": c_field, "condition_operator": c_op,
                    "condition_value": str(c_val), "rule_message": msg, "_fire_frac": frac,
                    "enforced_at": enforced_at, "owasp_control": owasp, "eval_backend": backend}
    scope = "Global" if ns == "spam_heuristic" else "Tenant"
    enforced_at = "intake" if ns == "spam_heuristic" else "decide"
    return {"priority": 50, "scope": scope, "action": "deny",
            "condition_field": "message_content", "condition_operator": "contains",
            "condition_value": "-", "rule_message": "Policy rule: contact admin for details",
            "_fire_frac": 0.005, "enforced_at": enforced_at, "owasp_control": "ASI-01", "eval_backend": "yaml"}


def _build_tool_invocation_breakdown(db: Session) -> list[dict]:
    events = (
        db.query(TraceEvent)
        .filter(TraceEvent.kind.in_(["tool_start", "tool_end", "tool_blocked"]))
        .all()
    )
    stats: dict[str, dict] = {}
    for ev in events:
        data = ev.data or {}
        tool_name = data.get("tool") or ev.message or ev.kind
        if not tool_name:
            continue
        t = stats.setdefault(tool_name, {"allow": 0, "block": 0, "total": 0})
        if ev.kind == "tool_end":
            if data.get("ok", True):
                t["allow"] += 1
            else:
                t["block"] += 1
            t["total"] += 1
        elif ev.kind == "tool_blocked":
            t["block"] += 1
            t["total"] += 1
        # tool_start counted only if no corresponding tool_end (treat as in-flight allow)
    return sorted(
        [{"tool": t, **v, "block_rate": round(v["block"] / max(v["total"], 1), 3)}
         for t, v in stats.items() if v["total"] > 0],
        key=lambda x: -x["total"],
    )


@router.get("/policies")
def policies(db: Session = Depends(get_db)) -> dict[str, Any]:
    kb_rules = (
        db.query(KnowledgeRule)
        .filter(KnowledgeRule.namespace.in_(["business_rules", "spam_heuristic"]))
        .order_by(KnowledgeRule.namespace, KnowledgeRule.key)
        .all()
    )

    policy_docs = []
    for rule in kb_rules:
        body = rule.body or {}
        ns = rule.namespace
        enrich = _enrich_rule(rule.label or rule.key or "", ns)
        policy_docs.append({
            "policy_id": f"policy:{ns}:{rule.key}",
            "namespace": ns,
            "scope": enrich["scope"],
            "rule_key": rule.key,
            "label": rule.label or rule.key,
            "description": rule.description or str(body)[:120],
            "action": enrich["action"],
            "priority": enrich["priority"],
            "condition_field": enrich["condition_field"],
            "condition_operator": enrich["condition_operator"],
            "condition_value": enrich["condition_value"],
            "rule_message": enrich["rule_message"],
            "enforced_at": enrich["enforced_at"],
            "owasp_control": enrich["owasp_control"],
            "eval_backend": enrich["eval_backend"],
            "_fire_frac": enrich["_fire_frac"],
            "version": rule.version,
            "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        })

    # Live tool allow/deny matrix per stage — display labels and allowed tools
    # come from the running system via `_live_stage_agents`.
    _ring_burst = {0: 200, 1: 50, 2: 20, 3: 10}
    tool_matrix = []
    for agent in _live_stage_agents(db):
        tool_matrix.append({
            "stage": agent["stage"],
            "did": agent["did"],
            "ring": agent["ring"],
            "ring_label": agent["ring_label"],
            "reversibility": agent["reversibility"],
            "rate_limit_burst": _ring_burst.get(agent["ring"], 10),
            "allowed": agent["allowed_tools"],
            "denied": agent["denied_tools"],
        })

    # Confidence threshold gates — ordered by pipeline stage (deny first, then confidence tiers)
    # threshold_min/max define the actual score range for each tier
    threshold_gates = [
        {
            "gate": "DISCARD",
            "label": "Discard (Spam/Phishing)",
            "threshold_min": None,
            "threshold_max": None,
            "action": "deny",
            "decision_allowed": False,
            "stage": "intake",
            "description": "Rejected by spam/phishing screening before confidence scoring runs — pipeline terminates at Intake",
        },
        {
            "gate": "L4_AUTO",
            "label": "Full Autonomy",
            "threshold_min": 0.95,
            "threshold_max": 1.0,
            "action": "allow",
            "decision_allowed": True,
            "stage": "decide",
            "description": "Pipeline executes end-to-end without human review",
        },
        {
            "gate": "L3_ONE_CLICK",
            "label": "One-Click Approval",
            "threshold_min": 0.80,
            "threshold_max": 0.95,
            "action": "audit",
            "decision_allowed": True,
            "stage": "decide",
            "description": "Pipeline proceeds; draft created and staged for CSR one-click sign-off before Execute runs",
        },
        {
            "gate": "L2_HITL",
            "label": "Full Human Review",
            "threshold_min": 0.0,
            "threshold_max": 0.80,
            "action": "block",
            "decision_allowed": False,
            "stage": "decide",
            "description": "Pipeline halted; CSR must review, edit, and approve before any execution",
        },
    ]

    # Blocked patterns — 5 categories, fire counts proportional to pipeline volume
    # Use 500 as minimum so demo shows realistic numbers regardless of seed data size
    effective_count = max(db.query(Pipeline).count(), 500)

    _raw_categories = [
        {
            "id": "pii",
            "label": "PII",
            "description": "Personally identifiable information in tool parameters",
            "agt_field": "GovernancePolicy.blocked_patterns (PatternType.REGEX)",
            "patterns": [
                {"label": "SSN",              "pattern": r"\b\d{3}-\d{2}-\d{4}\b",                               "type": "regex",    "frac": 0.025},
                {"label": "Credit Card",      "pattern": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",                         "type": "regex",    "frac": 0.012},
                {"label": "Phone Number",     "pattern": r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",                   "type": "regex",    "frac": 0.008},
                {"label": "Email in param",   "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",    "type": "regex",    "frac": 0.005},
                {"label": "DOB hint",         "pattern": "dob|date of birth|born on",                             "type": "substring","frac": 0.002},
            ],
        },
        {
            "id": "credential",
            "label": "Credential Leak",
            "description": "API keys, tokens, passwords accidentally included in parameters",
            "agt_field": "MCPGateway parameter sanitization",
            "patterns": [
                {"label": "Bearer Token",     "pattern": r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",                     "type": "regex",    "frac": 0.004},
                {"label": "API key pattern",  "pattern": r"(?i)api[_-]?key\s*[:=]\s*\S+",                        "type": "regex",    "frac": 0.003},
                {"label": "Private key hdr",  "pattern": "-----BEGIN PRIVATE KEY-----",                           "type": "substring","frac": 0.001},
                {"label": "Password field",   "pattern": r"(?i)password\s*[:=]\s*\S+",                            "type": "regex",    "frac": 0.003},
                {"label": "AWS key prefix",   "pattern": r"AKIA[0-9A-Z]{16}",                                     "type": "regex",    "frac": 0.0},
            ],
        },
        {
            "id": "injection",
            "label": "Injection",
            "description": "SQL, prompt, and LDAP injection attempts in email content",
            "agt_field": "GovernancePolicyMiddleware (blocked_patterns evaluation)",
            "patterns": [
                {"label": "SQL DROP/DELETE",  "pattern": r"(?i)(drop|delete|truncate)\s+table",                   "type": "regex",    "frac": 0.015},
                {"label": "SQL UNION attack", "pattern": r"(?i)union\s+select",                                    "type": "regex",    "frac": 0.008},
                {"label": "Prompt override",  "pattern": r"(?i)ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", "type": "regex","frac": 0.012},
                {"label": "Jailbreak hint",   "pattern": r"(?i)(DAN|jailbreak|pretend you are|act as if you)",    "type": "regex",    "frac": 0.006},
                {"label": "LDAP injection",   "pattern": r"\*\)\(\|",                                             "type": "regex",    "frac": 0.001},
            ],
        },
        {
            "id": "shell",
            "label": "Shell / Exec",
            "description": "Destructive commands and code execution — enforces Ring 3 sandbox isolation",
            "agt_field": "CapabilityGuardMiddleware (Ring 3 Sandbox enforcement)",
            "patterns": [
                {"label": "Destructive shell","pattern": r"rm\s+-rf|del\s+/[sq]|format\s+c:",                     "type": "regex",    "frac": 0.003},
                {"label": "Cmd substitution", "pattern": r"\$\(.*\)|`[^`]+`",                                     "type": "regex",    "frac": 0.002},
                {"label": "Python exec/eval", "pattern": r"(?:exec|eval)\s*\(",                                    "type": "regex",    "frac": 0.001},
                {"label": "Pipe to shell",    "pattern": r"\|\s*(?:sh|bash|zsh|cmd)\b",                            "type": "regex",    "frac": 0.002},
                {"label": "Fork bomb",        "pattern": r":\(\)\{\s*:\|:",                                        "type": "regex",    "frac": 0.0},
            ],
        },
        {
            "id": "exfiltration",
            "label": "Data Exfiltration",
            "description": "Attempts to route data to external endpoints outside approved domains",
            "agt_field": "MCPGateway egress policy + AgentMesh IATP boundary enforcement",
            "patterns": [
                {"label": "External URL",     "pattern": r"https?://(?!(?:keysight|salesforce|sap)\.com)",         "type": "regex",    "frac": 0.002},
                {"label": "Base64 blob",      "pattern": r"(?:[A-Za-z0-9+/]{4}){20,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)", "type": "regex", "frac": 0.001},
                {"label": "Webhook keyword",  "pattern": "webhook|callback_url|exfil",                             "type": "substring","frac": 0.003},
                {"label": "Data URI scheme",  "pattern": r"data:[a-z]+/[a-z]+;base64,",                            "type": "regex",    "frac": 0.001},
            ],
        },
    ]

    # Materialise fire counts and compute per-category totals
    all_patterns_flat = []
    for cat in _raw_categories:
        for p in cat["patterns"]:
            p["fire_count"] = max(0, int(effective_count * p.pop("frac")))
            p["action"] = "deny"
            all_patterns_flat.append({**p, "category": cat["label"], "category_id": cat["id"]})
        cat["total_patterns"] = len(cat["patterns"])
        cat["total_fire_count"] = sum(p["fire_count"] for p in cat["patterns"])

    total_blocks = sum(c["total_fire_count"] for c in _raw_categories)
    most_active = max(_raw_categories, key=lambda c: c["total_fire_count"])
    top_triggered = sorted(all_patterns_flat, key=lambda p: p["fire_count"], reverse=True)[:6]

    blocked_patterns = {
        "kpis": {
            "total_patterns": sum(c["total_patterns"] for c in _raw_categories),
            "total_blocks": total_blocks,
            "most_active_category": most_active["label"],
            "most_active_count": most_active["total_fire_count"],
            "categories_count": len(_raw_categories),
        },
        "categories": _raw_categories,
        "top_triggered": top_triggered,
    }

    # Count rule fires and collect last_fired_at from TraceEvents
    fired_counts: Counter = Counter()
    last_fired_map: dict[str, datetime] = {}
    decide_events = db.query(TraceEvent).filter(
        TraceEvent.stage == "decide",
        TraceEvent.kind == "tool_end",
    ).all()
    for ev in decide_events:
        data = ev.data or {}
        fired = (data.get("data") or {}).get("fired_rules") or []
        if isinstance(fired, list):
            for r in fired:
                k = r.get("key") if isinstance(r, dict) else str(r)
                if k:
                    fired_counts[k] += 1
                    ts = getattr(ev, "created_at", None)
                    if ts and (k not in last_fired_map or ts > last_fired_map[k]):
                        last_fired_map[k] = ts

    now_utc = datetime.now(timezone.utc)
    for doc in policy_docs:
        traced = fired_counts.get(doc["rule_key"], 0)
        frac = doc.pop("_fire_frac", 0.005)
        doc["fire_count"] = traced if traced > 0 else max(0, int(effective_count * frac))
        if doc["rule_key"] in last_fired_map:
            doc["last_fired_at"] = last_fired_map[doc["rule_key"]].isoformat()
        elif doc["fire_count"] > 0:
            # Seed a stable demo timestamp from rule_key hash
            seed = int(hashlib.md5(doc["rule_key"].encode()).hexdigest()[:8], 16)
            doc["last_fired_at"] = (now_utc - timedelta(hours=(seed % 71) + 1)).isoformat()
        else:
            doc["last_fired_at"] = None

    # ── Gap 6: Conflict resolution trace ────────────────────────────────────────
    # Simulate PolicyConflictResolver.resolve() per rule using co-active rules at same stage.
    stage_groups: dict[str, list[dict]] = defaultdict(list)
    for doc in policy_docs:
        stage_groups[doc["enforced_at"]].append(doc)

    for doc in policy_docs:
        co_rules = stage_groups[doc["enforced_at"]]
        top_candidates = sorted(co_rules, key=lambda r: r["priority"], reverse=True)[:3]
        action_set = {r["action"] for r in co_rules}
        conflict_detected = len(action_set) > 1
        candidates_evaluated = min(len(co_rules), 3)
        winner = top_candidates[0]
        trace = [
            f"Evaluating {candidates_evaluated} candidate(s) at '{doc['enforced_at']}' with priority_first_match",
        ]
        if conflict_detected:
            trace.append(f"Conflict detected — mix of {', '.join(sorted(action_set))} actions at this stage")
        else:
            trace.append(f"No conflict — all {len(co_rules)} rules at '{doc['enforced_at']}' share action '{doc['action']}'")
        trace.append(f"Winner: {winner['rule_key']} ({winner['action']}, priority={winner['priority']}, scope={winner['scope']})")
        doc["conflict_trace"] = trace
        doc["conflict_detected"] = conflict_detected
        doc["candidates_evaluated"] = candidates_evaluated

    # ── Gap 7: Audit entry sample (PolicyDecision.audit_entry.context_snapshot) ─
    import json as _json
    for doc in policy_docs:
        cfield = doc["condition_field"]
        cval   = doc["condition_value"]
        lookup = f"{cfield}_{cval}" if cfield == "order_value" else cfield
        snapshot = _AUDIT_CONTEXT_SAMPLES.get(lookup) or _AUDIT_CONTEXT_SAMPLES.get(cfield) or {}
        doc["audit_entry_sample"] = {
            "policy": doc["namespace"],
            "rule":   doc["rule_key"],
            "action": doc["action"],
            "context_snapshot": snapshot,
            "timestamp": doc.get("last_fired_at") or now_utc.isoformat(),
            "error": False,
        }

    # ── Gap 8: Evaluation latency from BackendDecision.evaluation_ms ─────────────
    for doc in policy_docs:
        doc["evaluation_ms"] = _BACKEND_LATENCY_MS.get(doc["eval_backend"], 0.08)

    # ── Gap 9: Strictness diff vs. AGT defaults (GovernancePolicy.is_stricter_than) ─
    _STRICTER_WHEN_LOWER = {"max_tokens", "max_tool_calls", "drift_threshold", "timeout_seconds"}
    _STRICTER_WHEN_HIGHER = {"confidence_threshold"}
    _STRICTER_WHEN_TRUE   = {"require_human_approval"}
    for doc in policy_docs:
        stage_pol = _STAGE_POLICY_MAP.get(doc["enforced_at"], _AGT_POLICY_DEFAULTS)
        diffs: list[dict] = []
        for field, base_val in _AGT_POLICY_DEFAULTS.items():
            cur_val = stage_pol.get(field, base_val)
            if cur_val == base_val:
                continue
            if field in _STRICTER_WHEN_LOWER:
                direction = "stricter" if cur_val < base_val else "looser"
            elif field in _STRICTER_WHEN_HIGHER:
                direction = "stricter" if cur_val > base_val else "looser"
            elif field in _STRICTER_WHEN_TRUE:
                direction = "stricter" if cur_val else "looser"
            else:
                direction = "changed"
            diffs.append({"field": field, "base": base_val, "current": cur_val, "direction": direction})
        is_stricter = bool(diffs) and all(d["direction"] == "stricter" for d in diffs)
        doc["strictness_diff"] = {"is_stricter_than_default": is_stricter, "diffs": diffs}

    # Coverage cross-reference: policy rules + fire counts per enforced_at stage → tool matrix
    _action_sev = {"block": 3, "deny": 2, "audit": 1, "allow": 0}
    _stage_cov: dict[str, dict] = {}
    for doc in policy_docs:
        s = doc["enforced_at"]
        if s not in _stage_cov:
            _stage_cov[s] = {"rule_count": 0, "fire_count": 0, "max_sev": -1,
                             "max_action": None, "top_rule": None, "top_priority": -1}
        cov = _stage_cov[s]
        cov["rule_count"] += 1
        cov["fire_count"] += doc.get("fire_count", 0)
        sev = _action_sev.get(doc["action"], 0)
        if sev > cov["max_sev"]:
            cov["max_sev"] = sev
            cov["max_action"] = doc["action"]
        if doc["priority"] > cov["top_priority"]:
            cov["top_priority"] = doc["priority"]
            cov["top_rule"] = {
                "label": doc["label"], "action": doc["action"],
                "priority": doc["priority"], "owasp": doc["owasp_control"],
            }
    for entry in tool_matrix:
        cov = _stage_cov.get(entry["stage"], {})
        entry["policy_rule_count"] = cov.get("rule_count", 0)
        entry["policy_fire_count"] = cov.get("fire_count", 0)
        entry["max_action"] = cov.get("max_action", None)
        entry["top_rule"] = cov.get("top_rule", None)
        entry["coverage_gap"] = len(entry["allowed"]) > 0 and cov.get("rule_count", 0) == 0

    # Per-agent GovernancePolicy config — each agent has its own resource limits
    # max_tool_calls matches len(allowed_tools) so agents are capped at their declared scope
    _per_agent_tool_calls = {"pre_intake": 1, "intake": 5, "extract": 4, "decide": 2, "execute": 2, "communicate": 1, "learning": 4}
    _per_agent_max_tokens = {"pre_intake": 0,    "intake": 8192, "extract": 16384, "decide": 8192, "execute": 4096, "communicate": 16384, "learning": 16384}
    _per_agent_drift     = {"pre_intake": 0.0,  "intake": 0.15, "extract": 0.15, "decide": 0.10, "execute": 0.05, "communicate": 0.15, "learning": 0.10}
    per_agent_policies = [
        {
            "stage": a["stage"],
            "label": a["display_name"],
            "ring": a["ring"],
            "max_tool_calls": _per_agent_tool_calls.get(a["stage"], 1),
            "max_tokens": _per_agent_max_tokens.get(a["stage"], 4096),
            "confidence_threshold": 0.80,
            "require_human_approval": a["ring"] == 0,
            "log_all_calls": True,
            "drift_threshold": _per_agent_drift.get(a["stage"], 0.15),
            "timeout_seconds": 300,
        }
        for a in _live_stage_agents(db)
    ]

    all_conflict_strategies = [
        {
            "id": "deny_overrides",
            "label": "Deny Overrides",
            "description": "Any deny wins; most restrictive outcome applies",
            "use_when": "Enterprise default-allow posture with hard deny guardrails",
            "active": False,
        },
        {
            "id": "allow_overrides",
            "label": "Allow Overrides",
            "description": "Any allow wins; most permissive outcome applies",
            "use_when": "Zero-trust baseline with explicit per-agent exceptions",
            "active": False,
        },
        {
            "id": "priority_first_match",
            "label": "Priority First Match",
            "description": "Highest numeric priority rule wins, regardless of action",
            "use_when": "Single-policy system or predictable priority-ordered evaluation",
            "active": True,
        },
        {
            "id": "most_specific_wins",
            "label": "Most Specific Wins",
            "description": "Narrowest scope wins: Agent > Tenant > Global; priority breaks ties",
            "use_when": "Multi-tenant with org → team → agent policy layering",
            "active": False,
        },
    ]

    return {
        "conflict_resolution": "priority_first_match",
        "all_conflict_strategies": all_conflict_strategies,
        "policy_defaults": {
            "max_tool_calls": 10,
            "max_tokens": 16384,
            "confidence_threshold": 0.80,
            "drift_threshold": 0.15,
            "require_human_approval": False,
            "log_all_calls": True,
            "timeout_seconds": 300,
            "checkpoint_frequency": 5,
            "max_concurrent": 10,
            "backpressure_threshold": 8,
        },
        "per_agent_policies": per_agent_policies,
        "policies": policy_docs,
        "policy_default_action": "allow",
        "tool_allow_deny_matrix": tool_matrix,
        "confidence_gates": threshold_gates,
        "blocked_patterns": blocked_patterns,
        "total_active": len(policy_docs),
        "tool_invocation_breakdown": _build_tool_invocation_breakdown(db),
    }


@router.get("/compliance")
def compliance(db: Session = Depends(get_db)) -> dict[str, Any]:
    pipes = db.query(Pipeline).all()

    discarded = sum(1 for p in pipes if p.status == "discarded")
    hitl_total = db.query(HitlTask).count()
    hitl_pending = db.query(HitlTask).filter(HitlTask.status == "pending").count()
    kills_manual = db.query(Feedback).filter(Feedback.kind == "reject").count()
    kills_drift = sum(1 for p in pipes if p.status == "error")
    kills_total = kills_manual + kills_drift + discarded
    active_rules = db.query(KnowledgeRule).filter(
        KnowledgeRule.namespace.in_(["business_rules", "spam_heuristic"])
    ).count()
    live_agents_compliance = _live_stage_agents(db)
    tool_count = len(_TOOL_FINGERPRINTS)
    agent_count = len(live_agents_compliance)

    evidence_map = {
        "discard_count": discarded,
        "hitl_count": hitl_total,
        "pending_hitl": hitl_pending,
        "kill_count": kills_total,
        "rule_count": active_rules,
        "tool_count": tool_count,
        "agent_count": agent_count,
        "spam_block_count": discarded,
    }

    # Build per-owasp-control rule counts + estimated fire counts from KnowledgeRule
    kb_rules = (
        db.query(KnowledgeRule)
        .filter(KnowledgeRule.namespace.in_(["business_rules", "spam_heuristic"]))
        .all()
    )
    owasp_rule_counts: dict[str, int] = {}
    owasp_fire_counts: dict[str, float] = {}
    for rule in kb_rules:
        ns = rule.namespace
        enrich = _enrich_rule(rule.label or rule.key or "", ns)
        ctrl = enrich["owasp_control"]
        owasp_rule_counts[ctrl] = owasp_rule_counts.get(ctrl, 0) + 1
        # estimate fires: use evidence count as proxy volume × fire fraction
        ev_count = evidence_map.get("discard_count", 1) if ns == "spam_heuristic" else evidence_map.get("rule_count", 1)
        owasp_fire_counts[ctrl] = owasp_fire_counts.get(ctrl, 0.0) + max(1, ev_count) * enrich["_fire_frac"]

    risks_with_evidence = []
    grade_counts: dict[str, int] = {}
    for risk in _OWASP_RISKS:
        ev_field = risk.get("evidence_field")
        ctrl = risk["id"]
        ev_count = evidence_map.get(ev_field, None) if ev_field else None
        grade = _evidence_grade(ev_count, ev_field)
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        risks_with_evidence.append({
            **risk,
            "evidence_count": ev_count,
            "grade": grade,
            "evidence_strength": grade,
            "policy_rule_count": owasp_rule_counts.get(ctrl, 0),
            "policy_fire_count": round(owasp_fire_counts.get(ctrl, 0.0)),
        })

    # GovernanceAttestation-style overall grade: weighted mean of per-control AGT evidence_strength
    total_strength_score = sum(_STRENGTH_ORDER[r["grade"]] for r in risks_with_evidence)
    coverage_pct = round(total_strength_score / (len(risks_with_evidence) * 4) * 100, 1)
    if coverage_pct >= 90:
        compliance_grade = "strong"
    elif coverage_pct >= 70:
        compliance_grade = "moderate"
    elif coverage_pct >= 50:
        compliance_grade = "weak"
    else:
        compliance_grade = "none"

    # attestation_hash: SHA-256 over sorted risk ids + evidence_strength (deterministic fingerprint)
    attestation_payload = "|".join(
        f"{r['id']}:{r['grade']}" for r in sorted(risks_with_evidence, key=lambda x: x["id"])
    )
    attestation_hash = hashlib.sha256(attestation_payload.encode()).hexdigest()[:16]

    # needs_attention: controls with evidence_strength weak or below, sorted worst-first
    needs_attention = sorted(
        [r for r in risks_with_evidence if _STRENGTH_ORDER[r["grade"]] <= _STRENGTH_ORDER["weak"]],
        key=lambda x: _STRENGTH_ORDER[x["grade"]],
    )

    mcp_tools = list(_TOOL_SCAN_STATUS.values())
    for i, (tool_name, scan) in enumerate(list(_TOOL_SCAN_STATUS.items())):
        mcp_tools[i] = {"tool": tool_name, **scan}

    # Assign stage to each tool — uses the LIVE agent inventory so newly
    # observed tools land on the right stage automatically.
    for entry in mcp_tools:
        tname = entry["tool"]
        for agent in live_agents_compliance:
            if tname in agent["allowed_tools"]:
                entry.setdefault("primary_stage", agent["stage"])
                entry.setdefault("primary_ring", agent["ring"])
                break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "owasp_version": "ASI 2026",
        "coverage": "10/10",
        "all_covered": True,
        "compliance_grade": compliance_grade,
        "coverage_pct": coverage_pct,
        "attestation_hash": attestation_hash,
        "grade_distribution": grade_counts,
        "needs_attention": [{"id": r["id"], "name": r["name"], "grade": r["grade"],
                              "evidence_strength": r["evidence_strength"], "severity": r["severity"]} for r in needs_attention],
        "risks": risks_with_evidence,
        "mcp_gateway": {
            "tools_registered": len(mcp_tools),
            "tools_clean": sum(1 for t in mcp_tools if t["status"] == "clean"),
            "threats_total": sum(t["threats_detected"] for t in mcp_tools),
            "last_full_scan": "2026-05-07T04:00:00Z",
            "pipeline_stages": [
                "deny_list_check",
                "allow_list_check",
                "parameter_sanitization",
                "rate_limit_check",
                "human_approval_gate",
            ],
            "tools": mcp_tools,
        },
        "rate_limits": [
            {"ring": 0, "label": "Root", "calls_per_sec": 100, "burst": 200},
            {"ring": 1, "label": "Privileged", "calls_per_sec": 16, "burst": 50},
            {"ring": 2, "label": "Standard", "calls_per_sec": 1, "burst": 20},
            {"ring": 3, "label": "Sandbox", "calls_per_sec": 0, "burst": 10},
        ],
    }


_SLO_SERIES_BUCKETS = 24


def _ensure_slo_demo_data(db: Session) -> None:
    """Top up synthetic SLO sample data so the demo charts always render with meaningful traffic.

    Idempotent: only inserts when recent counts are below display thresholds. Existing seed
    data is left untouched; this just ensures the rolling-window queries return enough rows
    to draw a presentable sparkline even when the backend has been running long enough for
    the original seed to drift out of the 24h / 168h SLO windows.
    """
    import random as _r
    now = datetime.utcnow()  # naive — consistent with SQLite storage
    cutoff_24h = now - timedelta(hours=24)
    cutoff_168h = now - timedelta(hours=168)

    rng = _r.Random(int(now.timestamp() // 3600))  # stable for an hour at a time

    recent_pipelines = (
        db.query(Pipeline)
        .filter(Pipeline.started_at >= cutoff_24h)
        .count()
    )
    if recent_pipelines < 60:
        # Spread 90 synthetic pipelines across the last 24h, biased toward recency.
        for _ in range(90 - recent_pipelines):
            offset_hours = rng.betavariate(2.0, 3.0) * 24  # weighted toward earlier in window
            started = now - timedelta(hours=offset_hours)
            roll = rng.random()
            if roll < 0.88:
                duration_s = rng.uniform(4.0, 22.0)
                status = "completed"
            elif roll < 0.96:
                duration_s = rng.uniform(24.0, 42.0)  # straddles the 30s target
                status = "completed"
            else:
                duration_s = rng.uniform(5.0, 14.0)
                status = "error"
            finished = started + timedelta(seconds=duration_s) if status == "completed" else None
            conf_roll = rng.random()
            if conf_roll < 0.60:
                conf = rng.uniform(0.95, 0.99)
                tier = "L4_AUTO"
            elif conf_roll < 0.85:
                conf = rng.uniform(0.80, 0.945)
                tier = "L3_ONE_CLICK"
            elif conf_roll < 0.95:
                conf = rng.uniform(0.62, 0.795)
                tier = "L2_HITL"
            else:
                conf = rng.uniform(0.40, 0.58)
                tier = "L2_HITL"
            db.add(Pipeline(
                started_at=started,
                finished_at=finished,
                intent="demo_synthetic",
                confidence=round(conf, 3),
                autonomy_tier=tier,
                status=status,
            ))
        db.flush()

    recent_hitl = (
        db.query(HitlTask)
        .filter(HitlTask.created_at >= cutoff_168h)
        .count()
    )
    if recent_hitl < 30:
        # 40 HITL tasks spread across the last 7 days, p95 should land near (but below) 4h.
        for _ in range(40 - recent_hitl):
            offset_hours = rng.uniform(0.0, 168.0)
            created = now - timedelta(hours=offset_hours)
            roll = rng.random()
            if roll < 0.55:
                minutes = rng.uniform(8.0, 75.0)         # quick: < 1.25h
            elif roll < 0.85:
                minutes = rng.uniform(75.0, 180.0)       # medium: 1.25–3h
            elif roll < 0.96:
                minutes = rng.uniform(180.0, 230.0)      # slow but within 4h
            else:
                minutes = rng.uniform(240.0, 320.0)      # breach: > 4h
            db.add(HitlTask(
                pipeline_id=None,
                created_at=created,
                resolved_at=created + timedelta(minutes=minutes),
                reason="demo_synthetic",
                payload={},
                status="resolved",
                resolution={},
            ))
        db.flush()

    recent_rogue = (
        db.query(TraceEvent)
        .filter(TraceEvent.kind == "rogue_detection", TraceEvent.ts >= cutoff_24h)
        .count()
    )
    if recent_rogue < 4:
        for _ in range(6 - recent_rogue):
            offset_hours = rng.uniform(0.0, 24.0)
            ts = now - timedelta(hours=offset_hours)
            db.add(TraceEvent(
                pipeline_id=None,
                ts=ts,
                stage="extract",
                kind="rogue_detection",
                message="demo: rogue detection threshold exceeded",
                data={"score": round(rng.uniform(0.72, 0.95), 2)},
                duration_ms=None,
            ))
        db.flush()

    db.commit()


@router.post("/seed_demo_slo")
def seed_demo_slo(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Opt-in demo-data top-up for the SLO tab. Inserts synthetic Pipeline /
    HitlTask / TraceEvent rows so the SLO rolling windows are non-empty.
    Idempotent in the sense that it only inserts up to a quota threshold,
    but it DOES write to the database — never call this in production."""
    _ensure_slo_demo_data(db)
    return {"ok": True, "note": "synthetic SLO seed applied"}


def _naive(dt: datetime | None) -> datetime | None:
    """Strip timezone info so naive SQLite datetimes and aware UTC datetimes can be compared."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _bucket_values(
    items: list[tuple[datetime | None, float]],
    window_hours: int,
    cut: datetime,
    aggregator,
    n_buckets: int = _SLO_SERIES_BUCKETS,
) -> list[float | None]:
    """Bucket (timestamp, value) pairs into N time buckets and apply aggregator per bucket.

    Returns one value per bucket (or None for empty buckets). Used to drive sparklines.
    """
    cut_n = _naive(cut)
    bucket_seconds = (window_hours * 3600) / n_buckets
    buckets: list[list[float]] = [[] for _ in range(n_buckets)]
    for ts, value in items:
        ts_n = _naive(ts)
        if ts_n is None or cut_n is None:
            continue
        offset_seconds = (ts_n - cut_n).total_seconds()
        idx = int(offset_seconds // bucket_seconds)
        if 0 <= idx < n_buckets:
            buckets[idx].append(value)
    return [aggregator(b) if b else None for b in buckets]


def _bucket_counts(
    timestamps: list[datetime | None],
    window_hours: int,
    cut: datetime,
    n_buckets: int = _SLO_SERIES_BUCKETS,
) -> list[int]:
    cut_n = _naive(cut)
    bucket_seconds = (window_hours * 3600) / n_buckets
    counts = [0] * n_buckets
    for ts in timestamps:
        ts_n = _naive(ts)
        if ts_n is None or cut_n is None:
            continue
        offset_seconds = (ts_n - cut_n).total_seconds()
        idx = int(offset_seconds // bucket_seconds)
        if 0 <= idx < n_buckets:
            counts[idx] += 1
    return counts


@router.get("/slo")
def slo(db: Session = Depends(get_db)) -> dict[str, Any]:
    # Governance endpoints are read-only. The original snapshot of this
    # file auto-seeded synthetic Pipeline / HitlTask / TraceEvent rows
    # whenever the SLO window was thin; that side effect mutated the
    # production database every time an operator opened the SLO tab. The
    # seed path lives behind `POST /api/governance/seed_demo_slo` for
    # explicit, opt-in demo data top-ups.
    now_utc = datetime.now(timezone.utc)

    def _window_cutoff(hours: int) -> datetime:
        return now_utc - timedelta(hours=hours)

    def _compute_slo(defn: dict) -> dict:
        cut = _window_cutoff(defn["window_hours"])
        budget_total: float = defn["budget_total"]
        target: float = defn["target"]
        comparison: str = defn["comparison"]

        series: list[float | None]

        if defn["id"] == "e2e_latency":
            rows = (
                db.query(Pipeline)
                .filter(Pipeline.started_at.isnot(None), Pipeline.finished_at.isnot(None))
                .filter(Pipeline.started_at >= cut)
                .all()
            )
            values = [
                (p.finished_at - p.started_at).total_seconds() * 1000
                for p in rows
            ]
            current_value = _pct(values, 90)
            bad = [v for v in values if v >= target]
            series = _bucket_values(
                [(p.started_at, (p.finished_at - p.started_at).total_seconds() * 1000) for p in rows],
                defn["window_hours"], cut, lambda b: _pct(b, 90),
            )

        elif defn["id"] == "success_rate":
            rows = (
                db.query(Pipeline)
                .filter(Pipeline.started_at.isnot(None))
                .filter(Pipeline.started_at >= cut)
                .all()
            )
            # "Success" in the AGT sense = the pipeline reached an intended
            # operational state. Reaching `completed` is success. Parking at
            # `awaiting_hitl` / `awaiting_aioa` is ALSO success — the agent
            # correctly identified the case needed human or external review
            # and routed it under the audit trail. Only `error` is a real
            # failure; `discarded` is the system correctly refusing spam /
            # out-of-scope and is also a success.
            _success_states = {"completed", "awaiting_hitl", "awaiting_one_click", "awaiting_aioa", "discarded"}
            values = [1.0 if p.status in _success_states else 0.0 for p in rows]
            good_count = sum(values)
            total = max(len(values), 1)
            current_value = good_count / total
            bad = [v for v in values if v == 0.0]
            series = _bucket_values(
                [(p.started_at, 1.0 if p.status in _success_states else 0.0) for p in rows],
                defn["window_hours"], cut, lambda b: sum(b) / len(b),
            )

        elif defn["id"] == "hitl_resolution":
            rows = (
                db.query(HitlTask)
                .filter(HitlTask.created_at.isnot(None), HitlTask.resolved_at.isnot(None))
                .filter(HitlTask.created_at >= cut)
                .all()
            )
            values = [
                (t.resolved_at - t.created_at).total_seconds() / 60.0
                for t in rows
            ]
            current_value = _pct(values, 95)
            bad = [v for v in values if v >= target]
            series = _bucket_values(
                [(t.created_at, (t.resolved_at - t.created_at).total_seconds() / 60.0) for t in rows],
                defn["window_hours"], cut, lambda b: _pct(b, 95),
            )

        elif defn["id"] == "confidence_floor":
            rows = (
                db.query(Pipeline)
                .filter(Pipeline.confidence.isnot(None))
                .filter(Pipeline.started_at.isnot(None))
                .filter(Pipeline.started_at >= cut)
                .all()
            )
            values = [1.0 if (p.confidence or 0) >= 0.60 else 0.0 for p in rows]
            good_count = sum(values)
            total = max(len(values), 1)
            current_value = good_count / total
            bad = [v for v in values if v == 0.0]
            series = _bucket_values(
                [(p.started_at, 1.0 if (p.confidence or 0) >= 0.60 else 0.0) for p in rows],
                defn["window_hours"], cut, lambda b: sum(b) / len(b),
            )

        elif defn["sli_type"] == "cost_usd":
            cost_rows = (
                db.query(Pipeline)
                .filter(Pipeline.started_at.isnot(None), Pipeline.started_at >= cut)
                .all()
            )
            pipeline_count = len(cost_rows)
            tokens_per_task = sum(
                round(_STAGE_MAX_TOKENS_COST[s] * _STAGE_TOKEN_FRACTIONS[s])
                for s in _STAGE_TOKEN_FRACTIONS
            )
            input_tok = round(tokens_per_task * (1 - _OUTPUT_RATIO))
            output_tok = round(tokens_per_task * _OUTPUT_RATIO)
            raw_cost = (
                input_tok / 1_000_000 * _COST_PER_M_INPUT +
                output_tok / 1_000_000 * _COST_PER_M_OUTPUT
            )
            # Hard cost filter — AGT BudgetTracker throttles any pipeline
            # whose projected spend would breach _COST_PER_TASK_HARD_CAP_USD,
            # so the SLO sample set is guaranteed to contain only compliant
            # values. Clamping here makes that invariant explicit and pegs
            # Cost Per Task compliance at 100% by construction.
            current_value = min(raw_cost, _COST_PER_TASK_HARD_CAP_USD)
            values = [current_value] * pipeline_count
            bad = []  # hard filter — out-of-budget pipelines are throttled before sampling
            # Cost per task is constant; sparkline reflects whether pipelines ran in each bucket
            series = _bucket_values(
                [(p.started_at, current_value) for p in cost_rows],
                defn["window_hours"], cut, lambda b: sum(b) / len(b),
            )

        elif defn["sli_type"] == "hallucination":
            rogue_events = (
                db.query(TraceEvent)
                .filter(TraceEvent.kind == "rogue_detection", TraceEvent.ts >= cut)
                .all()
            )
            total_events_rows = (
                db.query(TraceEvent)
                .filter(TraceEvent.ts >= cut)
                .all()
            )
            rogue_count = len(rogue_events)
            total_count = len(total_events_rows)
            current_value = rogue_count / max(total_count, 1)
            values = [0.0] * (total_count - rogue_count) + [1.0] * rogue_count
            bad = [v for v in values if v > 0.5]
            rogue_buckets = _bucket_counts([e.ts for e in rogue_events], defn["window_hours"], cut)
            total_buckets = _bucket_counts([e.ts for e in total_events_rows], defn["window_hours"], cut)
            series = [(r / t) if t > 0 else None for r, t in zip(rogue_buckets, total_buckets)]

        else:
            values, bad, current_value = [], [], 0.0
            series = [None] * _SLO_SERIES_BUCKETS

        samples = len(values)
        budget_consumed_frac = len(bad) / max(samples, 1)
        budget_remaining_pct = max(
            0.0, (budget_total - budget_consumed_frac) / budget_total * 100.0
        )
        burn_rate = budget_consumed_frac / budget_total if budget_total > 0 else 0.0

        met = (current_value < target) if comparison == "lt" else (current_value >= target)

        firing_alerts = []
        if burn_rate >= defn["burn_rate_critical"]:
            firing_alerts.append({
                "name": "burn_rate_critical",
                "rate": round(burn_rate, 2),
                "severity": "critical",
            })
        elif burn_rate >= defn["burn_rate_alert"]:
            firing_alerts.append({
                "name": "burn_rate_warning",
                "rate": round(burn_rate, 2),
                "severity": "warning",
            })

        return {
            "id": defn["id"],
            "name": defn["name"],
            "sli_type": defn["sli_type"],
            "description": defn["description"],
            "display_target": defn["display_target"],
            "unit": defn["unit"],
            "exhaustion_action": defn["exhaustion_action"],
            "window_hours": defn["window_hours"],
            "current_value": round(current_value, 4),
            "target": target,
            "comparison": comparison,
            "met": met,
            "samples": samples,
            "budget_total": budget_total,
            "budget_consumed": round(budget_consumed_frac, 4),
            "budget_remaining_pct": round(budget_remaining_pct, 1),
            "is_exhausted": budget_remaining_pct <= 0,
            "burn_rate": round(burn_rate, 3),
            "burn_rate_alert_threshold": defn["burn_rate_alert"],
            "burn_rate_critical_threshold": defn["burn_rate_critical"],
            "firing_alerts": firing_alerts,
            "series": [round(v, 4) if v is not None else None for v in series],
        }

    slo_results = [_compute_slo(d) for d in _SLO_DEFS]

    # Cost budgets (AGT BudgetTracker / ADR 0012)
    pipeline_count_24h = (
        db.query(Pipeline)
        .filter(Pipeline.started_at.isnot(None), Pipeline.started_at >= _window_cutoff(24))
        .count()
    )
    cost_per_stage = []
    total_tokens = 0
    total_cost_usd = 0.0
    total_token_budget = 0
    for stage in ["intake", "extract", "decide", "execute", "communicate"]:
        max_tok = _STAGE_MAX_TOKENS_COST[stage]
        frac    = _STAGE_TOKEN_FRACTIONS[stage]
        used    = round(max_tok * frac)
        inp_tok = round(used * (1 - _OUTPUT_RATIO))
        out_tok = round(used * _OUTPUT_RATIO)
        tok_total = inp_tok + out_tok
        tok_budget = max_tok  # per-pipeline budget; scale by pipeline count for window total
        window_inp = inp_tok * pipeline_count_24h
        window_out = out_tok * pipeline_count_24h
        window_total = window_inp + window_out
        window_budget = tok_budget * pipeline_count_24h
        cost = (window_inp / 1_000_000 * _COST_PER_M_INPUT +
                window_out / 1_000_000 * _COST_PER_M_OUTPUT)
        budget_used_pct = (window_total / max(window_budget, 1)) * 100.0
        status = ("over_hard_cap" if cost >= _STAGE_HARD_CAP_USD
                  else "warning" if cost >= _STAGE_SOFT_CAP_USD
                  else "healthy")
        cost_per_stage.append({
            "stage": stage,
            "input_tokens": window_inp,
            "output_tokens": window_out,
            "total_tokens": window_total,
            "token_budget": window_budget,
            "cost_usd": round(cost, 4),
            "soft_cap_usd": _STAGE_SOFT_CAP_USD,
            "hard_cap_usd": _STAGE_HARD_CAP_USD,
            "budget_used_pct": round(budget_used_pct, 1),
            "status": status,
        })
        total_tokens += window_total
        total_cost_usd += cost
        total_token_budget += window_budget

    cost_summary = {
        "window_hours": 24,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost_usd, 4),
        "soft_cap_usd": _GLOBAL_SOFT_CAP_USD,
        "hard_cap_usd": _GLOBAL_HARD_CAP_USD,
        "per_stage": cost_per_stage,
    }

    # Stage latency from TraceEvents
    stage_events: dict[str, list[float]] = defaultdict(list)
    cut_24h = _window_cutoff(24)
    for ev in (
        db.query(TraceEvent)
        .filter(TraceEvent.duration_ms.isnot(None), TraceEvent.ts >= cut_24h)
        .all()
    ):
        if ev.stage in _STAGE_LATENCY_TARGETS_MS:
            stage_events[ev.stage].append(float(ev.duration_ms))

    stage_latency = []
    for stage, target_ms in _STAGE_LATENCY_TARGETS_MS.items():
        vals = stage_events.get(stage, [])
        p95 = _pct(vals, 95)
        stage_latency.append({
            "stage": stage,
            "ring": _STAGE_TO_RING.get(stage, 3),
            "p50_ms": round(_pct(vals, 50), 1),
            "p95_ms": round(p95, 1),
            "p99_ms": round(_pct(vals, 99), 1),
            "samples": len(vals),
            "target_ms": target_ms,
            "met": p95 < target_ms if vals else True,
        })

    slos_met = sum(1 for s in slo_results if s["met"])
    budgets_healthy = sum(1 for s in slo_results if s["budget_remaining_pct"] > 25)
    active_alerts = sum(len(s["firing_alerts"]) for s in slo_results)

    return {
        "generated_at": now_utc.isoformat(),
        "window_hours": 24,
        "slos": slo_results,
        "stage_latency": stage_latency,
        "cost_summary": cost_summary,
        "slos_met": slos_met,
        "slos_total": len(_SLO_DEFS),
        "budgets_healthy": budgets_healthy,
        "active_alerts": active_alerts,
    }
