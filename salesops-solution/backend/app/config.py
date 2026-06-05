import os
from pathlib import Path

# Load backend/.env if present (OPENAI_API_KEY, LAMBDA_DOCEXTRACT_URL, …) before
# any module reads os.environ. dotenv won't overwrite values already set in the
# real environment, so production deployments via docker -e or CI secrets win.
try:
    from dotenv import load_dotenv as _load_dotenv
    _BACKEND_ROOT = Path(__file__).resolve().parents[1]
    _load_dotenv(_BACKEND_ROOT / ".env")
except Exception:
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str]) -> list[str]:
    v = os.environ.get(name)
    if not v:
        return default
    return [item.strip() for item in v.split(",") if item.strip()]


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "db" / "app.db"
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"

for p in (DB_PATH.parent, UPLOADS, OUTPUTS):
    p.mkdir(parents=True, exist_ok=True)

# DATABASE_URL takes precedence; otherwise local SQLite file.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_URL = DATABASE_URL or f"sqlite:///{DB_PATH.as_posix()}"

APP_PORT = int(os.environ.get("APP_PORT", "8000"))
APP_LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "info").lower()
APP_LOG_FORMAT = os.environ.get("APP_LOG_FORMAT", "text").lower()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")

# Solution-version stamped onto signal rows (trace_events, cost_events) and
# RCA tickets so cross-deploy comparisons are trivial. Bump the suffix on
# every release that changes agent behaviour, prompts, or workflow.
SOLUTION_VERSION = os.environ.get("SOLUTION_VERSION", "keysight-salesops@1.0.0")
APP_CORS_ORIGINS = _env_list(
    "APP_CORS_ORIGINS",
    [
        # SalesOps frontend (default Vite port)
        "http://localhost:5173", "http://127.0.0.1:5173",
        # Governance dashboard (separate Vite project on a different port).
        # 5174 is already used by another local Vite project on this machine,
        # so the governance dashboard binds to 5175 by default.
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:5175", "http://127.0.0.1:5175",
        # Production domain — both apps live under the same host but
        # listing it here lets the dashboard call the API directly when
        # served by a different reverse-proxy path during dev.
        "https://app.solution.zbrain.ai",
    ],
)

APP_AUTH_ENABLED = _env_bool("APP_AUTH_ENABLED", False)
APP_AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", "").strip()

# ─────────────────────────────────────────────────────────────────────────────
# DEMO HARD RULE — zero outbound transmission.
#
# Nothing in this demo is allowed to transmit to a customer-facing channel.
# The pipeline still RECORDS what it would have done (CommunicationLog,
# trace events, IMAP "would-move" markers) so the UI can show the action,
# but the actual SMTP send and IMAP folder mutation are blocked at the
# service layer regardless of any env var.
#
# This is a CODE-LEVEL INVARIANT. To send real mail or mutate a real mailbox,
# you must edit this constant — env vars alone won't override it.
# ─────────────────────────────────────────────────────────────────────────────
DEMO_TRANSMIT_LOCKED = True

# When True, the PII redactor (services/pii_redactor.py) is a no-op for
# LLM prompts. The demo data is fully synthetic (no real customer SSNs,
# cards, or phone numbers), and the redactor's broad regexes were
# false-flagging PO numbers and order references as PHONE matches,
# leaving "<REDACTED_PHONE_n>" tokens in customer-facing replies. In a
# production tenant this flag stays False and the redactor runs.
DEMO_DISABLE_PII_REDACTION = True

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "llm").lower()
LLM_TRACE = _env_bool("LLM_TRACE", False)

LANGUAGES = ["en", "es", "ja"]

INTENTS = [
    "po_intake",
    "quote_to_order",
    "trade_change_order",
    "ssd_change_request",
    "hold_release",
    "delivery_change",
    "service_order",
    "wo_update_request",
    "wo_status_inquiry",
    "service_contract_request",
    "general_inquiry",
    "out_of_scope",
    "spam",
    # === v1.1 TASK-1 START === 5 first-class intents from prior POC's 9-class taxonomy
    "kso",
    "collections",
    "portal_admin",
    "brazil_tax",
    "undeliverable",
    # === v1.1 TASK-1 END ===
]

# Intents that short-circuit the pipeline — Stages 2-6 are SKIPPED, the email
# is logged and discarded, no customer-facing reply is drafted.
TERMINAL_INTENTS = {
    "spam", "out_of_scope",
    # === v1.1 TASK-1 START === redirect/discard intents short-circuit the pipeline
    "kso", "collections", "portal_admin", "brazil_tax", "undeliverable",
    # === v1.1 TASK-1 END ===
}

INTENT_TO_FLOW = {
    "po_intake": "trade_order_entry",
    "quote_to_order": "trade_order_entry",
    "trade_change_order": "trade_change_order",
    "ssd_change_request": "ssd_change",
    "hold_release": "trade_order_entry",
    "delivery_change": "ssd_change",
    "service_order": "som_create",
    "wo_update_request": "som_update",
    "wo_status_inquiry": "som_inquiry",
    "service_contract_request": "service_contract",
    "general_inquiry": "general",
    "out_of_scope": "discarded",
    "spam": "discarded",
    # === v1.1 TASK-1 START ===
    "kso": "redirected",
    "collections": "redirected",
    "portal_admin": "redirected",
    "brazil_tax": "redirected",
    "undeliverable": "discarded",
    # === v1.1 TASK-1 END ===
}

INTENT_DESCRIPTIONS = {
    "po_intake": "new purchase order received from a customer (no prior quote referenced)",
    "quote_to_order": "customer asking to convert an existing quote into a sales order",
    "trade_change_order": "customer requesting line-level changes to an EXISTING booked sales order: quantity bump or cut, unit-price revision, line add or remove, SKU swap, billing-address change. NOT for ship-date moves (ssd_change_request), NOT for ship-to or carrier changes (delivery_change), NOT for hold releases (hold_release)",
    "ssd_change_request": "customer asking to move the SHIP DATE on an existing order — push out, pull in, or split partial. Date-only, not address or carrier",
    "hold_release": "customer or internal note saying an existing order can come off a hold: credit hold, export-compliance hold, tax hold, quality hold, or customer-requested hold. Usually references the resolving artefact (paid invoice, BIS approval, tax exemption certificate)",
    "delivery_change": "customer changing HOW or WHERE an existing order ships, NOT WHEN. Ship-to address change, carrier swap (FedEx to DHL, etc.), Incoterm change (EXW to DAP, etc.), delivery-instruction updates (gate codes, dock hours, hazmat), or partial-split to multiple addresses",
    "service_order": "new request to create a work order — calibration, repair, installation, on-site service, possibly multi-asset",
    "wo_update_request": "customer asking to update or modify an EXISTING work order (add notes, add tasks, update assets)",
    "wo_status_inquiry": "customer asking about the status of an existing work order or open WOs",
    "service_contract_request": "customer asking for a service contract / support agreement quote or order (cal plan, onsite plan, PM plan)",
    "general_inquiry": "other legitimate business question (EOL roadmap, product info, lead-time questions, etc.)",
    "out_of_scope": "legitimate but non-customer-business — automated notifications (Google/Microsoft security, AWS, GitHub), social-network alerts (LinkedIn), newsletter subscriptions, internal admin (HR, IT, payroll), out-of-office auto-replies, calendar invites, vendor receipts. Not spam, but not actionable in the SalesOps queue — discard / archive without reply",
    "spam": "unsolicited / phishing / off-topic / promotional from unknown senders",
    # === v1.1 TASK-1 START ===
    "kso": "Government / defense / federal-prime customer — redirect to keysightorders@",
    "collections": "Payment / remittance / banking notification — redirect to collections.pdl-americas@",
    "portal_admin": "Portal / SSO / verification-code system message — redirect to portal-admin.pdl",
    "brazil_tax": "Brazilian tax document (NF-e / Nota Fiscal) — redirect to lar_orders@",
    "undeliverable": "Bounce / DSN / mail-delivery-failure — discard",
    # === v1.1 TASK-1 END ===
}

# === v1.1 TASK-1 START === Per-intent redirect destination for terminal-intent
# short-circuit. The orchestrator records this as `would_route_to` in the
# CommunicationLog (DEMO_TRANSMIT_LOCKED — no real SMTP send).
INTENT_REDIRECT_TARGETS = {
    "kso": "keysightorders@keysight.com",
    "collections": "collections.pdl-americas@keysight.com,usar_keysight@keysight.com",
    "portal_admin": "portal-admin.pdl-ccc-americas@keysight.com",
    "brazil_tax": "lar_orders@keysight.com",
    "undeliverable": None,
}
# === v1.1 TASK-1 END ===

CONFIDENCE_TIERS = {
    "L4_AUTO": 0.95,
    "L3_ONE_CLICK": 0.80,
    "L2_HITL": 0.0,
}


# Continuous Learning — rule-owner allow-list. Promotion, force-promote,
# rollback, and retire actions must be performed by a Salesforce user whose
# username matches one of these. Identity is read from the live Salesforce
# org so the allow-list survives a Salesforce user-record rename; matching is
# by username local-part (case-insensitive) rather than by ephemeral SF Id.
LEARNING_RULE_OWNERS = {
    "andrew.chen": "Andrew Chen (Trade CSR lead)",
    "priya.sharma": "Priya Sharma (SOM CSR lead)",
    "david.park": "David Park (Service Contract owner)",
}


# Continuous Learning — promotion freeze windows. Each entry is
# (start_iso, end_iso, reason). While `datetime.utcnow()` falls inside any
# window, promote / force-promote / rollback / retire calls return
# 423 LOCKED with the configured reason. Rule owners can still accept
# opportunities and run backtests during a freeze; the gate only blocks the
# actual write to production.
LEARNING_PROMOTION_FREEZE_WINDOWS: list[dict] = [
    # Example: freeze the quarter-end accounting close week.
    # {"start": "2026-06-25T00:00:00Z", "end": "2026-07-02T00:00:00Z",
    #  "reason": "Q2 close — no production KB changes until July 2"},
]


# Continuous Learning — approver count per change_type. Defaults to 1
# (single rule-owner approval). Higher-risk change types can require multiple
# rule owners to co-sign the promotion. Enforced server-side via the
# PromotionDecision audit table: a promote with `approver_count > 1` and
# fewer recorded approvals returns 412 with a clear message.
LEARNING_APPROVER_COUNT_BY_TYPE: dict[str, int] = {
    "prompt": 1,
    "pattern_list": 1,
    "threshold": 2,
    "routing_rule": 2,
    "validation_rule": 1,
    "other": 1,
}


# Continuous Learning — auto-rollback regression watchdog. After a promotion,
# the watchdog checks the relevant metric at 24h, 72h, and 168h. If the
# metric regresses past these thresholds (relative to the candidate's
# back-test prediction), the watchdog auto-rolls-back the change and pages
# the rule owner.
LEARNING_AUTOROLLBACK_THRESHOLDS = {
    "edit_rate_regression_pp": 2.0,
    "hitl_rate_regression_pp": 5.0,
    "latency_p95_regression_pct": 50.0,
}


# Continuous Learning — pre-A/B shadow window. New experiments are not
# eligible for back-test until they have observed at least this many hours
# of live shadow data. Set to 0 to allow immediate back-test (the demo
# default — long-running customer demos shorten this so we can iterate).
LEARNING_SHADOW_HOURS = 0
