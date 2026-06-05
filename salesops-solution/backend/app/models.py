from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from .db import Base


def now():
    return datetime.now(timezone.utc)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)
    name = Column(String)
    legal_entity = Column(String, nullable=True)
    region = Column(String)
    language = Column(String)
    email = Column(String)
    vertical = Column(String, nullable=True)
    compliance = Column(JSON, default=list)
    industry = Column(String, nullable=True)
    naics = Column(String, nullable=True)
    annual_revenue_usd = Column(Float, nullable=True)
    employees = Column(Integer, nullable=True)
    account_manager = Column(String, nullable=True)
    sales_engineer = Column(String, nullable=True)
    customer_since = Column(DateTime, nullable=True)
    status = Column(String, default="active")
    sla_tier = Column(String, nullable=True)
    duns = Column(String, nullable=True)
    tax_id = Column(String, nullable=True)
    payment_terms = Column(String, default="Net 30")
    credit_limit = Column(Float, default=0.0)
    default_currency = Column(String, default="USD")
    default_incoterms = Column(String, default="FOB Origin")
    addresses = Column(JSON, default=list)


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    name = Column(String)
    title = Column(String, nullable=True)
    role = Column(String)
    email = Column(String)
    phone = Column(String, nullable=True)
    language = Column(String, default="en")
    is_primary = Column(Boolean, default=False)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    sku = Column(String, unique=True, index=True)
    description = Column(String)
    list_price = Column(Float)
    family = Column(String, nullable=True)
    category = Column(String, nullable=True)
    mpn = Column(String, nullable=True)
    lifecycle_status = Column(String, default="active")
    lifecycle_eol_date = Column(DateTime, nullable=True)
    successor_sku = Column(String, nullable=True)
    lead_time_weeks = Column(Integer, default=8)
    calibration_interval_months = Column(Integer, nullable=True)
    country_of_origin = Column(String, default="US")
    eccn = Column(String, default="EAR99")
    hs_code = Column(String, nullable=True)
    warranty_months = Column(Integer, default=12)
    moq = Column(Integer, default=1)
    hazmat = Column(Boolean, default=False)
    weight_kg = Column(Float, nullable=True)


class Quote(Base):
    __tablename__ = "quotes"
    id = Column(Integer, primary_key=True)
    quote_number = Column(String, unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    quote_date = Column(DateTime, default=now)
    valid_until = Column(DateTime)
    revision = Column(Integer, default=1)
    currency = Column(String, default="USD")
    subtotal = Column(Float, default=0.0)
    discount_pct = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    freight = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    total = Column(Float)
    status = Column(String, default="open")
    sales_rep = Column(String, nullable=True)
    engineer = Column(String, nullable=True)
    opportunity_id = Column(String, nullable=True)
    pricing_terms = Column(String, default="standard")
    line_items = Column(JSON)
    customer = relationship("Customer")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_number = Column(String, unique=True, index=True)
    quote_id = Column(Integer, ForeignKey("quotes.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    customer_po = Column(String, nullable=True)
    order_date = Column(DateTime, default=now)
    status = Column(String, default="open")
    hold_reason = Column(String, nullable=True)
    requested_ship_date = Column(DateTime, nullable=True)
    promised_ship_date = Column(DateTime, nullable=True)
    currency = Column(String, default="USD")
    payment_terms = Column(String, default="Net 30")
    ship_via = Column(String, default="FedEx Priority")
    tracking_number = Column(String, nullable=True)
    sales_rep = Column(String, nullable=True)
    csr_owner = Column(String, nullable=True)
    subtotal = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    freight = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    total = Column(Float)
    bill_to_address = Column(JSON, nullable=True)
    ship_to_address = Column(JSON, nullable=True)
    incoterms = Column(String, nullable=True)
    hold_history = Column(JSON, default=list)
    line_items = Column(JSON)
    created_at = Column(DateTime, default=now)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id = Column(Integer, primary_key=True)
    wo_number = Column(String, unique=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    asset_serial = Column(String)
    asset_sku = Column(String, nullable=True)
    type = Column(String)
    description = Column(Text, nullable=True)
    status = Column(String, default="open")
    region = Column(String)
    assigned_team = Column(String, nullable=True)
    technician = Column(String, nullable=True)
    service_contract_id = Column(String, nullable=True)
    scheduled_date = Column(DateTime, nullable=True)
    sla_target_date = Column(DateTime, nullable=True)
    completed_date = Column(DateTime, nullable=True)
    standards_referenced = Column(JSON, default=list)
    labor_hours = Column(Float, default=0.0)
    parts_used = Column(JSON, default=list)
    signoff_status = Column(String, default="pending")
    cert_number = Column(String, nullable=True)
    root_cause = Column(Text, nullable=True)
    cost_usd = Column(Float, default=0.0)
    pdf_filename = Column(String, nullable=True)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    sku = Column(String, index=True)
    description = Column(String, nullable=True)
    serial = Column(String, unique=True, index=True)
    install_date = Column(DateTime, nullable=True)
    location = Column(String, nullable=True)
    last_cal_date = Column(DateTime, nullable=True)
    calibration_due_date = Column(DateTime, nullable=True)
    cal_interval_months = Column(Integer, nullable=True)
    status = Column(String, default="in_service")
    warranty_expires = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)


class ServiceContract(Base):
    __tablename__ = "service_contracts"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    contract_number = Column(String, unique=True, index=True)
    type = Column(String)
    starts_on = Column(DateTime, nullable=True)
    expires_on = Column(DateTime, nullable=True)
    sla_response_hours = Column(Integer, default=24)
    sla_resolution_hours = Column(Integer, default=72)
    included_assets = Column(JSON, default=list)
    annual_value_usd = Column(Float, default=0.0)
    status = Column(String, default="active")
    notes = Column(Text, nullable=True)


class CalibrationCert(Base):
    __tablename__ = "calibration_certs"
    id = Column(Integer, primary_key=True)
    cert_number = Column(String, unique=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    issued_date = Column(DateTime, nullable=True)
    expires_date = Column(DateTime, nullable=True)
    traceability = Column(String)
    lab_id = Column(String, nullable=True)
    technician = Column(String, nullable=True)
    out_of_tolerance = Column(Boolean, default=False)
    as_found_summary = Column(Text, nullable=True)
    as_left_summary = Column(Text, nullable=True)
    pdf_filename = Column(String, nullable=True)


class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), index=True)
    carrier = Column(String)
    tracking_number = Column(String, index=True)
    ship_date = Column(DateTime, nullable=True)
    eta_date = Column(DateTime, nullable=True)
    delivered_date = Column(DateTime, nullable=True)
    status = Column(String, default="prepared")
    weight_lbs = Column(Float, nullable=True)
    incoterms = Column(String, nullable=True)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    invoice_number = Column(String, unique=True, index=True)
    invoice_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    currency = Column(String, default="USD")
    amount = Column(Float, default=0.0)
    paid_amount = Column(Float, default=0.0)
    status = Column(String, default="issued")
    pdf_filename = Column(String, nullable=True)


class SalesforceConnection(Base):
    __tablename__ = "salesforce_connections"
    id = Column(Integer, primary_key=True)
    label = Column(String, default="Production org")
    instance_url = Column(String)
    username = Column(String)
    password_enc = Column(Text)
    security_token_enc = Column(Text, nullable=True)
    consumer_key_enc = Column(Text)
    consumer_secret_enc = Column(Text)
    domain = Column(String, default="login")
    api_version = Column(String, default="60.0")
    is_active = Column(Boolean, default=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    org_id = Column(String, nullable=True)
    org_name = Column(String, nullable=True)
    org_edition = Column(String, nullable=True)
    user_display_name = Column(String, nullable=True)
    daily_api_remaining = Column(Integer, nullable=True)
    daily_api_max = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=now)


class SharePointConnection(Base):
    __tablename__ = "sharepoint_connections"
    id = Column(Integer, primary_key=True)
    label = Column(String, default="Production site")
    tenant_id = Column(String)
    client_id = Column(String)
    client_secret_enc = Column(Text)
    site_id = Column(String)
    drive_id = Column(String, nullable=True)
    folder_path = Column(String, default="/")
    is_active = Column(Boolean, default=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    site_display_name = Column(String, nullable=True)
    site_web_url = Column(String, nullable=True)
    drive_name = Column(String, nullable=True)
    item_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=now)


class ServiceNowConnection(Base):
    __tablename__ = "servicenow_connections"
    id = Column(Integer, primary_key=True)
    label = Column(String, default="Production instance")
    instance_url = Column(String)
    username = Column(String)
    password_enc = Column(Text)
    case_table = Column(String, default="incident")
    is_active = Column(Boolean, default=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    instance_version = Column(String, nullable=True)
    incident_count = Column(Integer, nullable=True)
    csm_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class Notification(Base):
    """Enterprise-style notification record. Any subsystem can publish a
    notification (connection monitor, HITL queue, AIOA fallout, pipeline
    error, drift detector, continuous-learning suggestions, anything).
    The UI consumes a single feed and never sees which producer made the row.

    `kind` is a stable key the publisher uses to de-duplicate / auto-resolve
    (e.g., "salesforce_disconnected" — the same kind is reused across polls
    so we only ever have one open row for that condition, and resolving it
    happens by updating the same row to `resolved_at`).

    `category` is a UI grouping label (Connection / Queue / Workflow / Drift /
    System) shown as a small chip.

    `read_at` is set when the operator opens the dropdown that contains the
    row. `dismissed_at` is set when they explicitly close it. `resolved_at`
    is set by the publisher when the underlying condition healed.
    """

    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    kind = Column(String, index=True)
    category = Column(String, index=True)   # connection | queue | workflow | drift | system
    severity = Column(String, index=True)   # critical | warning | info
    title = Column(String)
    body = Column(Text, nullable=True)
    action_url = Column(String, nullable=True)
    action_label = Column(String, nullable=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now, index=True)
    updated_at = Column(DateTime, default=now, onupdate=now)
    read_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)


class IntegrationPlaceholder(Base):
    """Lightweight registry for upcoming / middleware-only integrations that
    don't have a dedicated connection table yet (Jitterbit, DocuNet, etc.).
    Lets Settings → Integrations show a real Enable/Disable trigger and store
    the operator-supplied config so the live integration can be wired in
    once Keysight provisions the middleware bridge."""
    __tablename__ = "integration_placeholders"
    id = Column(Integer, primary_key=True)
    provider = Column(String, unique=True, index=True)  # "jitterbit", "docunet"
    label = Column(String)
    enabled = Column(Boolean, default=False)
    config = Column(JSON, default=dict)
    last_enabled_at = Column(DateTime, nullable=True)
    last_disabled_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    id = Column(Integer, primary_key=True)
    provider = Column(String, default="imap")
    email_address = Column(String, unique=True, index=True)
    label = Column(String, nullable=True)
    imap_host = Column(String)
    imap_port = Column(Integer, default=993)
    use_ssl = Column(Boolean, default=True)
    username = Column(String)
    password_enc = Column(Text)
    folder = Column(String, default="INBOX")
    sync_interval_sec = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_uid_seen = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    messages_imported = Column(Integer, default=0)
    category_folder_map = Column(JSON, default=dict)
    # === v1.1 TASK-6 START === region for region-aware intent filtering
    region = Column(String, default="GLOBAL")  # AMS | EMEA | APAC | JP | GLOBAL
    # === v1.1 TASK-6 END ===
    created_at = Column(DateTime, default=now)


class KnowledgeRule(Base):
    """User-editable rule store powering the Knowledge Base page.
    Agents (intake / extract / decide / reconcile) read these at request time
    so business users can refine intent definitions and extraction schemas
    without code changes."""

    __tablename__ = "knowledge_rules"
    id = Column(Integer, primary_key=True)
    namespace = Column(String, index=True)
    key = Column(String, index=True)
    label = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    body = Column(JSON, default=dict)
    default_body = Column(JSON, default=dict)
    version = Column(Integer, default=1)
    updated_at = Column(DateTime, default=now, onupdate=now)
    updated_by = Column(String, default="system")


class CommunicationLog(Base):
    __tablename__ = "communication_logs"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    occurred_at = Column(DateTime, default=now, index=True)
    direction = Column(String, default="outbound")
    channel = Column(String, default="email")
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    language = Column(String, nullable=True)
    intent = Column(String, nullable=True)
    autonomy_tier = Column(String, nullable=True)
    sent_by = Column(String, nullable=True)
    csr_action = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    attachments = Column(JSON, default=list)
    delivery_status = Column(String, nullable=True, index=True)
    delivery_error = Column(Text, nullable=True)
    provider_message_id = Column(String, nullable=True)
    sent_via_account_id = Column(Integer, ForeignKey("email_accounts.id"), nullable=True)


class Email(Base):
    __tablename__ = "emails"
    id = Column(Integer, primary_key=True)
    received_at = Column(DateTime, default=now, index=True)
    from_address = Column(String)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    subject = Column(String)
    body = Column(Text)
    language_hint = Column(String, nullable=True)
    attachments = Column(JSON, default=list)
    status = Column(String, default="new", index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("email_accounts.id"), nullable=True, index=True)
    message_id = Column(String, nullable=True, index=True)
    in_reply_to = Column(String, nullable=True)
    email_references = Column(Text, nullable=True)


class Pipeline(Base):
    __tablename__ = "pipelines"
    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey("emails.id"))
    ccc_request_id = Column(Integer, ForeignKey("ccc_requests.id"), nullable=True)
    salesforce_case_id = Column(String, nullable=True, index=True)
    started_at = Column(DateTime, default=now)
    finished_at = Column(DateTime, nullable=True)
    intent = Column(String, nullable=True)
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    autonomy_tier = Column(String, nullable=True)
    customer_match = Column(JSON, default=dict)
    extracted = Column(JSON, default=dict)
    reconcile = Column(JSON, default=dict)
    decision = Column(JSON, default=dict)
    execution = Column(JSON, default=dict)
    reply = Column(JSON, default=dict)
    suggested_fix = Column(JSON, default=dict)
    status = Column(String, default="running", index=True)
    error = Column(Text, nullable=True)
    # === v1.1 TASK-4 START === existing-CCC status branch
    existing_case_id = Column(String, nullable=True, index=True)
    existing_case_status = Column(String, nullable=True)
    ccc_action = Column(String, nullable=True)  # new | update | clone_change_order
    duplicate_detected = Column(Boolean, default=False)
    # === v1.1 TASK-4 END ===
    # === v1.1 TASK-5 START === distributor + magic-SKU routing
    routing_target = Column(String, nullable=True, index=True)
    routing_basis = Column(String, nullable=True)  # rule key that fired
    # === v1.1 TASK-5 END ===
    # === v1.1 TASK-9 START === shadow classifier (third LLM pass)
    shadow_classification = Column(JSON, default=dict)
    # === v1.1 TASK-9 END ===


class CCCRequest(Base):
    """Customer Contact Center request — the RFP's central tracking entity that
    each inbound email gets converted into. Mirrors STATUS + STAGE lifecycle
    states from the RFP flow diagrams (New / Assigned / In Progress / Closed
    × Automation in Progress / Review Required / Automation Complete)."""

    __tablename__ = "ccc_requests"
    id = Column(Integer, primary_key=True)
    request_number = Column(String, unique=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    category = Column(String, nullable=True)
    request_type = Column(String, nullable=True)
    sub_type = Column(String, nullable=True)
    track = Column(String, nullable=True)
    status = Column(String, default="new", index=True)
    stage = Column(String, default="automation_in_progress", index=True)
    owner = Column(String, nullable=True)
    fallout_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
    closed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)


class TraceEvent(Base):
    __tablename__ = "trace_events"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), index=True)
    ts = Column(DateTime, default=now)
    stage = Column(String, index=True)
    kind = Column(String)
    message = Column(Text)
    data = Column(JSON, default=dict)
    duration_ms = Column(Integer, nullable=True)


class HitlTask(Base):
    __tablename__ = "hitl_tasks"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), index=True)
    created_at = Column(DateTime, default=now)
    resolved_at = Column(DateTime, nullable=True)
    reason = Column(String)
    payload = Column(JSON)
    status = Column(String, default="pending", index=True)
    resolution = Column(JSON, default=dict)
    # Assignment (individual CSR claim on top of the queue-level owner
    # already stamped on the Case by Decide).
    assignee_user_id = Column(String, nullable=True, index=True)
    assignee_name = Column(String, nullable=True)
    assignee_queue = Column(String, nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    assigned_by = Column(String, nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"))
    created_at = Column(DateTime, default=now)
    stage = Column(String)
    kind = Column(String)
    note = Column(Text)
    data = Column(JSON, default=dict)
    # Best-effort anchor to a Baseline Quality Target. Feedback signals do not
    # always map cleanly to a single baseline (a CSR edit on the intake stage
    # could speak to intent_classification_accuracy OR a per-language detector
    # baseline). The write path attempts a derivation; the read path falls
    # back to a segment-heuristic join when this column is null.
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True, index=True)


class PipelineExecution(Base):
    """Thread-level idempotency log for Stage 4 side-effects.

    Keyed on (thread_root_message_id, action, args_hash). Before any Stage 4
    side-effect call, the orchestrator looks up this table; on hit it returns
    the previously-recorded result (skipping the duplicate write); on miss it
    executes, then records the (key, result) pair so a re-run on a later email
    in the same thread is a no-op."""

    __tablename__ = "pipeline_executions"
    id = Column(Integer, primary_key=True)
    thread_root_message_id = Column(String, index=True)
    action = Column(String, index=True)
    args_hash = Column(String, index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=True)
    result = Column(JSON, default=dict)
    succeeded = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now, index=True)


# === v1.1 TASK-7 START === Test-corpus regression suite (labelled emails + run results)
class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    subject = Column(String)
    from_address = Column(String)
    body = Column(Text)
    attachments = Column(JSON, default=list)
    expected_intent = Column(String, index=True)
    expected_action = Column(String, nullable=True)
    expected_routing = Column(String, nullable=True)
    expected_keywords = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)


class TestRun(Base):
    __tablename__ = "test_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=now)
    finished_at = Column(DateTime, nullable=True)
    label = Column(String)
    case_count = Column(Integer, default=0)
    initial_pass = Column(Integer, default=0)
    initial_fail = Column(Integer, default=0)
    post_fix_pass = Column(Integer, default=0)
    still_failed = Column(Integer, default=0)
    pipeline_version_hash = Column(String, nullable=True)


class TestRunResult(Base):
    __tablename__ = "test_run_results"
    id = Column(Integer, primary_key=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), index=True)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"), index=True)
    actual_intent = Column(String, nullable=True)
    actual_keywords = Column(JSON, default=list)
    actual_reason = Column(Text, nullable=True)
    pass_initial = Column(Boolean, default=False)
    pass_post_fix = Column(Boolean, nullable=True)
    pipeline_id = Column(Integer, nullable=True)
    diff = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)
# === v1.1 TASK-7 END ===


# === v1.1 DOC-FEEDBACK START === Reviewer feedback / chat on the RFP-response docs viewer
class DocFeedback(Base):
    __tablename__ = "doc_feedback"
    id = Column(Integer, primary_key=True)
    doc_slug = Column(String, index=True, nullable=False)   # 'executive-summary' / 'scope' / 'all'
    section_anchor = Column(String, nullable=True)          # free text, e.g. '§5.1 Classification'
    comment_text = Column(Text, nullable=False)
    author = Column(String, nullable=True, default="reviewer")
    status = Column(String, default="open")                 # 'open' / 'addressed' / 'closed'
    created_at = Column(DateTime, default=now, index=True)
    updated_at = Column(DateTime, default=now)
# === v1.1 DOC-FEEDBACK END ===


# === Continuous learning ledger ===
class DriftAlert(Base):
    """A drift event raised against a rolling-baseline window. Persisted so that
    operators can acknowledge / resolve and so the timeline survives restarts.
    Drift is computed periodically from confidence, HITL rate, per-language
    accuracy, and per-intent SLA adherence. This table is the audit trail."""

    __tablename__ = "drift_alerts"
    id = Column(Integer, primary_key=True)
    detected_at = Column(DateTime, default=now, index=True)
    updated_at = Column(DateTime, default=now)
    fingerprint = Column(String, nullable=True, index=True)  # idempotency key per (detector, segment)
    segment = Column(String, nullable=False)             # 'intent:quote_to_order' / 'language:ja' / 'mailbox:emea-sales'
    metric = Column(String, nullable=False)              # 'confidence' / 'hitl_rate' / 'extraction_accuracy' / 'sla'
    baseline = Column(Float, nullable=True)
    current = Column(Float, nullable=True)
    delta = Column(Float, nullable=True)                 # absolute delta (current - baseline)
    delta_pct = Column(Float, nullable=True)
    severity = Column(String, default="info", index=True)   # 'info' / 'medium' / 'high'
    circuit_breaker_fired = Column(Boolean, default=False)
    status = Column(String, default="open", index=True)  # 'open' / 'in_review' / 'resolved'
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    detail = Column(JSON, default=dict)                  # detector-specific context (sample size, z-score, etc.)
    # Anchor to the Baseline Quality Target this alert originated from. Stamped
    # by the detector when the alert is created; backfilled for legacy rows
    # by matching (metric, segment). Powers the Baselines drill-through.
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True, index=True)
    # Per-segment breakdown the detector captured at the moment the rollup
    # crossed the baseline target. Ordered worst-first, capped at the top 5
    # rows so the operator sees which segments drove the breach without
    # opening the per-segment timeline. Shape mirrors
    # `baselines.segments_observed`.
    top_contributors = Column(JSON, nullable=True)


class ABShadowResult(Base):
    """One row per shadow execution of a candidate prompt against a real
    completed pipeline. Powers the "real A/B" story: the candidate ran
    side-by-side with production, here is the agreement rate over the last
    N cases. Never acted on — the production output is what reached the
    customer.

    Records per-case agreement (did the candidate produce the same key
    field as production?), the candidate's value, the production value, and
    whatever divergence detail the runner captured. Realised-lift reads
    agreement rate over a window from here, not just from CSR thumbs.
    """

    __tablename__ = "ab_shadow_results"
    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("ab_experiments.id"), index=True, nullable=False)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), index=True, nullable=True)
    created_at = Column(DateTime, default=now, index=True)
    stage = Column(String, nullable=False)             # 'intake' | 'decide' | 'communicate'
    field = Column(String, nullable=True)              # 'intent' | 'tier' | etc.
    agreement = Column(Boolean, default=False, index=True)
    production_value = Column(Text, nullable=True)
    candidate_value = Column(Text, nullable=True)
    divergence_note = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    method = Column(String, nullable=True)             # 'openai_replay' | 'llm_replay' | etc.


class Baseline(Base):
    """Admin-editable quality baseline that the drift detector evaluates each
    pipeline against. Replaces the hardcoded thresholds the detector used to
    carry (extraction_completeness >= 0.90, p95 latency <= 30s, etc.) with
    rows an admin can change without a deploy.

    Each row is a (metric, segment, direction, target_value, drift_pct) tuple
    plus a severity that decides what happens when a violation lands:
      - severity="warn" emits a DriftAlert with severity="warn"
      - severity="block_promotion" emits one with severity="high" and the
        promotion gate refuses to auto-promote affected candidates until the
        baseline is back in range.

    `direction="min"` means observed must stay >= target_value (e.g. accuracy).
    `direction="max"` means observed must stay <= target_value (e.g. latency).
    `drift_pct` is the tolerance band — fire only when observed crosses the
    target by more than this relative percentage.

    `last_observed` / `last_observed_at` are updated by the detector on every
    pass so the UI can render a live heatmap without a separate read query.
    """

    __tablename__ = "baselines"
    id = Column(Integer, primary_key=True)
    metric = Column(String, nullable=False, index=True)
    segment = Column(String, nullable=False, default="global", index=True)
    direction = Column(String, nullable=False, default="min")  # 'min' | 'max'
    target_value = Column(Float, nullable=False)
    drift_pct = Column(Float, nullable=False, default=5.0)     # tolerance band (%)
    severity = Column(String, nullable=False, default="warn")  # 'warn' | 'block_promotion'
    enabled = Column(Boolean, default=True, index=True)
    owner = Column(String, default="role:cl_admin")
    rationale = Column(Text, nullable=True)
    source = Column(String, default="manual")  # 'rfp' | 'slo' | 'customer_sla' | 'empirical_p50' | 'manual'
    unit = Column(String, nullable=True)       # 'ratio' | 'ms' | 'hours' | 'count' | 'pct'
    label = Column(String, nullable=True)      # short display label, optional override
    last_observed = Column(Float, nullable=True)
    last_observed_at = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)  # 'healthy' | 'drifting' | 'breached'
    # Concept-baseline rollup: the per-segment observations the detector
    # collapses into `last_observed`. Shape is a list of
    # {segment, observed, weight, sample_size, status}. The detector orders
    # this worst-first when materialising `top_contributors` on a drift alert.
    segments_observed = Column(JSON, nullable=True)
    # Rollup strategy the detector applies across the per-segment observations:
    #   weighted_avg : sum(observed * weight) / sum(weight). Default for
    #                  accuracy and completeness metrics where each segment
    #                  contributes proportionally to its sample size.
    #   max          : worst observation wins. Default for latency-like
    #                  metrics where the slowest stage sets the user-visible
    #                  experience.
    #   min          : least observation wins. Reserved for the unusual case
    #                  where a lower observation is worse and the floor
    #                  needs to be exposed.
    rollup_strategy = Column(String, default="weighted_avg")
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
    updated_by = Column(String, default="system")


class LearningOpportunity(Base):
    """A candidate improvement surfaced by the weekly batch. The tuning queue
    in the Continuous Learning page is the operator view onto this table."""

    __tablename__ = "learning_opportunities"
    id = Column(Integer, primary_key=True)
    detected_at = Column(DateTime, default=now, index=True)
    segment = Column(String, nullable=False)              # 'pt-BR PO emails from 4 distributors'
    fingerprint = Column(Text, nullable=False)            # one-line signal description
    proposed_remedy = Column(Text, nullable=False)        # one-line remedy text
    expected_lift = Column(String, nullable=True)         # e.g. '+140 emails/wk to correct queue'
    effort = Column(String, default="Med")                # 'Low' / 'Med' / 'High'
    risk = Column(String, default="Low")                  # 'Low' / 'Med' / 'High'
    score = Column(Float, default=0.0)                    # ranked by lift-over-effort
    status = Column(String, default="open", index=True)   # 'open' / 'accepted' / 'deferred' / 'rejected' / 'in_ab' / 'promoted' / 'retired'
    source = Column(String, default="csr_correction_cluster")  # 'csr_correction_cluster' / 'drift_signal' / 'manual'
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    linked_drift_alert_id = Column(Integer, ForeignKey("drift_alerts.id"), nullable=True)
    # Forward-link to the immutable RCA snapshot that this opportunity is
    # the proposed remedy for. Populated when the opportunity is generated
    # in response to a drift / regression signal.
    linked_rca_ticket_id = Column(Integer, nullable=True, index=True)
    sample_pipeline_ids = Column(JSON, default=list)      # supporting case references
    # Anchor to the Baseline Quality Target the originating signal mapped to.
    # Copied from the linked DriftAlert at write time; backfilled by (metric,
    # segment) match for legacy rows.
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True, index=True)


class ABExperiment(Base):
    """A shadow / candidate change under A/B evaluation alongside production.
    The candidate is observed only — never acted on — until a rule owner
    promotes it through the Governance and Analytics screen."""

    __tablename__ = "ab_experiments"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=now, index=True)
    candidate = Column(String, nullable=False)            # human label for the change being tested
    segment = Column(String, nullable=False)              # scope of the experiment
    horizon_kind = Column(String, default="time_window")  # 'time_window' / 'sample_size'
    horizon_value = Column(String, nullable=False)        # '10 days' / '5000 emails'
    sample_collected = Column(Integer, default=0)
    sample_target = Column(Integer, default=0)
    accuracy_delta_pct = Column(Float, nullable=True)
    accuracy_delta_ci = Column(String, nullable=True)     # '+6.4% (95% CI)'
    regression_status = Column(String, default="none")    # 'none' / 'watch' / 'fail'
    promote_status = Column(String, default="shadow", index=True)  # 'shadow' / 'ready' / 'promoted' / 'retired'
    promoted_by = Column(String, nullable=True)
    promoted_at = Column(DateTime, nullable=True)
    promote_note = Column(Text, nullable=True)
    linked_opportunity_id = Column(Integer, ForeignKey("learning_opportunities.id"), nullable=True)
    kb_namespace = Column(String, nullable=True)          # KB namespace the candidate edits (e.g. 'intent')
    kb_key = Column(String, nullable=True)                # KB key (e.g. 'po_intake')
    control_prompt = Column(Text, nullable=True)          # snapshot of the live prompt when the experiment was created
    candidate_prompt = Column(Text, nullable=True)        # proposed replacement prompt the operator is testing
    backtest_results = Column(JSON, nullable=True)        # {'sample_size': N, 'matches': M, 'baseline_correct': X, 'candidate_correct': Y, 'delta_pct': D, 'mismatches': [...]}
    backtest_ran_at = Column(DateTime, nullable=True)
    # Type of change the experiment represents. Not every change is a prompt
    # body. Surface this so the UI can render the right diff (text, value,
    # list, routing table).
    change_type = Column(String, default="prompt", index=True)  # 'prompt' | 'threshold' | 'pattern_list' | 'routing_rule' | 'validation_rule' | 'other'
    # Snapshot of the KB rule body taken at promotion. Used for one-click
    # rollback within the configured rollback window.
    previous_body_snapshot = Column(JSON, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by = Column(String, nullable=True)
    rolled_back_note = Column(Text, nullable=True)
    # Per-pipeline sample the backtest scored. Each entry:
    # {pipeline_id, control_decision, candidate_decision, agreed, intent, subject}
    # Powers the "Affected pipelines" section so operators can see exactly
    # which cases the candidate would handle differently from production.
    backtest_sample = Column(JSON, default=list)
    # === Realised-lift watcher ===
    # Production-side reconciliation of a promoted change. A background job
    # recomputes accuracy on real traffic after the promotion has been live
    # long enough to gather a usable sample, and writes the realised delta
    # here. If |realised - expected| breaches the configured tolerance, the
    # watcher auto-rolls-back and stamps `auto_rolled_back = True`.
    realised_lift_pct = Column(Float, nullable=True)
    realised_lift_ci = Column(String, nullable=True)         # '+5.8% (95% CI, n=120)'
    realised_lift_at = Column(DateTime, nullable=True)
    realised_sample_size = Column(Integer, nullable=True)
    auto_rolled_back = Column(Boolean, default=False)
    realised_note = Column(Text, nullable=True)
    # Anchor to the Baseline Quality Target this experiment is tuning against.
    # Copied from the linked LearningOpportunity at write time so the entire
    # signal → remedy → experiment chain points back at one baseline.
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True, index=True)


class KbRuleVersion(Base):
    """Append-only history of every KB rule body change. Each promote /
    rollback writes a new row capturing the body BEFORE the change so the
    rule's evolution is fully replayable. Powers the rule-history view and
    the rollback-to-any-point feature.

    Distinct from the rule itself (`knowledge_rules`), which only carries the
    current body and a single version counter. This table is the audit trail.
    """

    __tablename__ = "kb_rule_versions"
    id = Column(Integer, primary_key=True)
    namespace = Column(String, nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    body = Column(JSON, default=dict)
    changed_at = Column(DateTime, default=now, index=True)
    changed_by_id = Column(String, nullable=True)
    changed_by_name = Column(String, nullable=True)
    change_kind = Column(String, default="promote")  # 'promote' | 'rollback' | 'manual' | 'seed'
    experiment_id = Column(Integer, ForeignKey("ab_experiments.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)


class PromotionDecision(Base):
    """Audit row for every consequential Continuous-Learning action on an
    experiment: promote, force_promote, rollback, retire. Each row records
    who acted, when, against which gate evaluation, and the outcome. The
    Promoted experiment card surfaces the latest decision so an operator can
    see why a candidate went live (or was blocked) without digging into logs.

    Decisions are append-only; superseding actions write a new row rather than
    editing an existing one. The combination of (experiment_id, decided_at)
    is the canonical audit ordering.
    """

    __tablename__ = "promotion_decisions"
    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("ab_experiments.id"), index=True)
    decided_at = Column(DateTime, default=now, index=True)
    decided_by_id = Column(String, nullable=True, index=True)         # Salesforce User Id
    decided_by_name = Column(String, nullable=True)                   # Display name at time of action
    decided_by_role = Column(String, nullable=True)                   # 'zbrain_admin' | 'functional_reviewer' | 'viewer' resolved from SF Permission Sets at decision time
    decided_by_role_source = Column(String, nullable=True)            # 'sf_permission_set' | 'fallback_allowlist' | 'sf_offline' | etc.
    action = Column(String, nullable=False, index=True)               # 'promote' | 'force_promote' | 'rollback' | 'retire'
    gate_enabled = Column(Boolean, default=False)                     # was the gate green at decision time
    gate_reasons = Column(JSON, default=list)                         # [{condition, met, observed, threshold, label}, ...]
    sample_size = Column(Integer, nullable=True)
    delta_pct = Column(Float, nullable=True)
    force_reason = Column(Text, nullable=True)
    outcome = Column(String, nullable=False)                          # 'applied' | 'blocked' | 'errored'
    outcome_detail = Column(Text, nullable=True)
    # Tamper-evident hash chain: every PromotionDecision row hashes its own
    # canonical payload together with the previous row's `entry_hash`. A
    # verifier walks the chain and detects any retroactive edit or row
    # deletion. Populated by `services.audit_chain.append_decision()`.
    prev_hash = Column(String, nullable=True)
    entry_hash = Column(String, nullable=True, index=True)


class RCATicket(Base):
    """Immutable Root-Cause Analysis bundle.

    Created the moment a drift / regression signal is raised. Snapshots the
    LIVE context at the time of the alert — prompt body, model id, tool
    calls observed in the affected pipelines, policy verdicts that fired,
    audit-chain head — so the engineer who picks the ticket up later
    receives the exact state the system was in when the signal occurred,
    not whatever it looks like now after subsequent changes.

    The deck's "Isolate" step ("Alert bundled with prompt + tool calls +
    model version + policy verdict + audit-chain hash into one RCA ticket")
    is enforced by this entity. Every Continuous Learning opportunity that
    proposes a remedy points back at exactly one RCA ticket; every
    promotion ultimately traces signal → RCA → opportunity → experiment →
    KbRuleVersion → realised lift.
    """

    __tablename__ = "rca_tickets"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=now, index=True)

    # Originating signal (one of these is populated).
    source_kind = Column(String, nullable=False, index=True)  # 'drift_alert' | 'manual' | 'pipeline_error'
    source_id = Column(Integer, nullable=True, index=True)

    # What broke and where.
    segment = Column(String, nullable=False)
    metric = Column(String, nullable=True)
    severity = Column(String, default="info", index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)

    # Immutable snapshot of the live state at alert time.
    sample_pipeline_ids = Column(JSON, default=list)
    prompt_snapshot = Column(JSON, default=dict)          # {agent: 'extract', system: '...', user_template: '...', version: 7}
    tool_calls_snapshot = Column(JSON, default=list)      # [{tool, params, returned, status, pipeline_id}]
    model_versions = Column(JSON, default=dict)           # {extract: 'gpt-5.2', communicate: 'gpt-5.2'}
    policy_verdicts = Column(JSON, default=list)          # [{rule_key, scope, action, fired_count}]
    audit_chain_head = Column(String, nullable=True)
    solution_version = Column(String, nullable=True, index=True)

    # Workflow state.
    status = Column(String, default="open", index=True)   # 'open' | 'diagnosing' | 'remediating' | 'closed'
    owner_id = Column(String, nullable=True)
    owner_name = Column(String, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(String, nullable=True)
    resolution_note = Column(Text, nullable=True)

    # Forward links (opportunity that proposes the remedy, experiment that
    # validates it). Populated as the ticket progresses through the loop.
    linked_opportunity_id = Column(Integer, ForeignKey("learning_opportunities.id"), nullable=True, index=True)
    linked_experiment_id = Column(Integer, ForeignKey("ab_experiments.id"), nullable=True, index=True)
    # Anchor to the Baseline Quality Target the originating signal mapped to.
    # Copied from the source DriftAlert when the ticket is bundled.
    baseline_id = Column(Integer, ForeignKey("baselines.id"), nullable=True, index=True)
# === Continuous learning ledger end ===


class CostEvent(Base):
    """One row per metered external call (LLM, OCR, paid API).

    Real cost telemetry — written at the moment the call returns, by the
    `record_cost` helper in app.analytics.cost. The Cost dashboard reads
    aggregations over this table and refuses to render if coverage is < 100%.
    """

    __tablename__ = "cost_events"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=True, index=True)
    stage = Column(String, index=True, nullable=False)
    tool = Column(String, nullable=False)          # tool name from the orchestrator (e.g. "classify_intent")
    component = Column(String, nullable=False)     # "llm_input" / "llm_output" / "ocr" / "embedding" / "translate"
    model = Column(String, nullable=True)          # "claude-sonnet-4-6", "azure-doc-intelligence", "deepl-translator", etc.
    units = Column(Integer, default=0)             # tokens, pages, characters
    unit_kind = Column(String, nullable=False)     # "tokens" / "pages" / "chars"
    cost_usd = Column(Float, default=0.0)
    ts = Column(DateTime, default=now, index=True)


class LLMProviderConfig(Base):
    """Operator-managed API credentials for the LLM provider in use.

    Today only OpenAI is supported via this surface; the row is unique on
    `provider` so we can extend to Anthropic / others later. The API key is
    Fernet-encrypted at rest using the same helper as Salesforce / SharePoint.
    Resolution order at runtime: this row first, env var second.
    """

    __tablename__ = "llm_provider_configs"
    id = Column(Integer, primary_key=True)
    provider = Column(String, unique=True, index=True)  # 'openai'
    api_key_enc = Column(Text, nullable=True)
    model = Column(String, nullable=True)                # 'gpt-5.2' etc.
    is_active = Column(Boolean, default=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class AIOAProvider(Base):
    """Configurable external AI Order Acceptance provider.

    The operator configures the outbound webhook URL the workflow POSTs to,
    the auth scheme, and the timeout window. We also auto-generate the
    inbound callback URL + shared secret the provider must include when
    posting results back. One row per provider; a single provider is the
    norm but the table supports staging/swap.
    """

    __tablename__ = "aioa_providers"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    outbound_url = Column(String, nullable=False)
    outbound_auth_scheme = Column(String, default="bearer")  # 'bearer' | 'api_key' | 'none'
    outbound_auth_value = Column(Text, nullable=True)        # token / api key value
    inbound_secret = Column(String, nullable=False)          # auto-generated, callback verifies
    timeout_seconds = Column(Integer, default=1800)          # 30 minutes default
    retry_max = Column(Integer, default=3)
    retry_backoff_seconds = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    last_send_at = Column(DateTime, nullable=True)
    last_callback_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)


class AIOARequest(Base):
    """One row per AIOA validation request. The pipeline parks in
    `awaiting_aioa` status with a row here; the background sender posts to
    the provider; the callback endpoint updates the row with the response;
    the resumer then unpauses the pipeline and triggers the post-AIOA
    action inside the same service.

    Status lifecycle:
      pending_send -> sent -> response_received -> processed
    sidetracks: timed_out, error
    """

    __tablename__ = "aioa_requests"
    id = Column(Integer, primary_key=True)
    correlation_id = Column(String, unique=True, index=True, nullable=False)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), index=True, nullable=False)
    provider_id = Column(Integer, ForeignKey("aioa_providers.id"), nullable=True)
    status = Column(String, default="pending_send", index=True)
    created_at = Column(DateTime, default=now, index=True)
    sent_at = Column(DateTime, nullable=True)
    response_received_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    request_payload = Column(JSON, default=dict)
    response_payload = Column(JSON, default=dict)
    decision = Column(String, nullable=True)             # 'PASS' | 'FAIL' | None
    fallout_reasons = Column(JSON, default=list)
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    csr_draft = Column(JSON, default=dict)               # populated when decision='FAIL'
