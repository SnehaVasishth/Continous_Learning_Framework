const BASE = "/api";

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export type EmailSummary = {
  id: number;
  received_at: string;
  from: string;
  subject: string;
  language_hint: string | null;
  attachments: string[];
  status: string;
  customer_name: string | null;
  pipeline: PipelineSummary | null;
};

export type PipelineSummary = {
  id: number;
  status: string;
  intent: string | null;
  language: string | null;
  confidence: number | null;
  autonomy_tier: string | null;
};

export type EmailThreadMsg = {
  id: number;
  is_root: boolean;
  is_self: boolean;
  position: number;
  from: string | null;
  subject: string | null;
  received_at: string | null;
  body: string;
  attachments: Array<{ name: string; type?: string; path?: string }>;
  language_hint: string | null;
  pipeline_id: number | null;
};

export type EmailThread = {
  thread_root_message_id: string | null;
  thread_normalized_subject: string;
  message_count: number;
  messages: EmailThreadMsg[];
};

export type EmailAttachmentRef = {
  name: string;
  path?: string;
  kind?: string;
  type?: string;
};

export type EmailDetail = Omit<EmailSummary, "attachments"> & {
  body: string;
  customer: { id: number; code: string; name: string; region: string; language: string } | null;
  pipeline_id: number | null;
  attachments: EmailAttachmentRef[];
  thread: EmailThread | null;
};

export type TraceEvent = {
  id: number;
  pipeline_id: number;
  ts: string;
  stage: string;
  kind: string;
  message: string;
  data: any;
  duration_ms: number | null;
};

export type ThreadMessage = {
  id: number;
  is_root: boolean;
  position: number;
  message_id: string | null;
  in_reply_to: string | null;
  from_address: string | null;
  subject: string | null;
  received_at: string | null;
  body_preview: string;
  body_chars: number;
  attachments: Array<{ name: string | null; type: string | null }>;
  language_hint: string | null;
  pipeline_id: number | null;
};

export type ThreadExecution = {
  id: number;
  action: string;
  args_hash: string;
  pipeline_id: number | null;
  email_id: number | null;
  succeeded: boolean;
  created_at: string | null;
  result: Record<string, any>;
};

export type ThreadResponse = {
  pipeline_id: number;
  thread_root_message_id: string | null;
  thread_root_pipeline_id: number | null;
  thread_normalized_subject: string;
  message_count: number;
  seed_email_id: number;
  messages: ThreadMessage[];
  executions: ThreadExecution[];
};

export type Pipeline = {
  id: number;
  email_id: number;
  email_subject?: string | null;
  email_from?: string | null;
  email_body?: string | null;
  email_language_hint?: string | null;
  email_received_at?: string | null;
  email_attachments?: string[];
  started_at: string | null;
  finished_at: string | null;
  status: string;
  intent: string | null;
  language: string | null;
  confidence: number | null;
  autonomy_tier: string | null;
  salesforce_case_id?: string | null;
  ccc_request?: {
    id: number;
    case_number?: string | null;
    request_number: string;
    category: string | null;
    request_type: string | null;
    sub_type?: string | null;
    track: string | null;
    status: string;
    stage: string;
    owner: string | null;
    fallout_reason: string | null;
    created_at: string | null;
    closed_at: string | null;
  } | null;
  customer_match?: {
    customer_id?: number | null;
    customer_code?: string | null;
    customer_name?: string | null;
    region?: string | null;
    vertical?: string | null;
    compliance?: string[];
    score?: number;
    basis?: string;
    history?: { quotes: number; orders: number; work_orders: number };
    salesforce?: {
      queried_at?: string;
      matched_via?: string;
      account?: {
        Id?: string;
        Name?: string;
        Customer_Code__c?: string | null;
        Region__c?: string | null;
        Vertical__c?: string | null;
        SLA_Tier__c?: string | null;
        Compliance_Flags__c?: string | null;
        Payment_Terms__c?: string | null;
        Credit_Limit__c?: number | null;
        Annual_Revenue_USD__c?: number | null;
        Default_Currency__c?: string | null;
        Industry?: string | null;
        BillingCity?: string | null;
        BillingCountryCode?: string | null;
      };
      history?: { contacts?: number; orders?: number; opportunities?: number };
    };
  };
  extracted: any;
  reconcile: any;
  decision: any;
  execution: any;
  reply: any;
  suggested_fix?: { status?: string; subject?: string; body?: string; language?: string; error?: string };
  soa_url?: string | null;
  soa_sharepoint?: {
    store?: string | null;
    name?: string | null;
    web_url?: string | null;
    folder?: string | null;
    size?: number | null;
  } | null;
  error: string | null;
  events: TraceEvent[];
};

export type HitlAssignee = {
  user_id: string;
  name: string;
  queue: string | null;
  assigned_at: string | null;
  assigned_by: string | null;
};

export type HitlOperator = {
  id: string;
  name: string;
  first_name?: string;
  last_name?: string;
  username?: string;
  email?: string;
};

export type HitlSummary = {
  id: number;
  display_id?: string;
  created_at: string;
  reason: string;
  status: string;
  owner_queue?: string | null;
  assignee?: HitlAssignee | null;
  pipeline: { id: number; intent: string; confidence: number; autonomy_tier: string; language?: string | null } | null;
  email: { id: number; subject: string; from: string; language_hint: string; body?: string; received_at?: string | null; attachments?: string[] } | null;
  payload?: any;
  resolution?: any;
  reply?: {
    subject?: string;
    body?: string;
    language?: string;
    sent?: boolean;
    sent_at?: string | null;
    delivery_status?: string | null;
    provider_message_id?: string | null;
    sent_via_account_id?: number | null;
    send_error?: string | null;
  };
  execution?: any;
  customer_match?: any;
  delivery?: {
    delivery_status?: string | null;
    provider_message_id?: string | null;
    sent_via_account_id?: number | null;
    error?: string | null;
    smtp_host?: string | null;
  };
  /** Active SF org base URL — used by the CSR playbook to build "Open in
   * Salesforce" / "Create Account" deep links. Null when SF isn't connected. */
  salesforce_instance_url?: string | null;
};

export type AnalyticsSummary = {
  totals: {
    pipelines: number;
    completed: number;
    rejected: number;
    running: number;
    errored?: number;
    awaiting_aioa?: number;
    pending_hitl: number;
    inbox_total: number;
    inbox_unprocessed: number;
  };
  autonomy: { L4_AUTO: number; L3_ONE_CLICK: number; L2_HITL: number; tiered_total?: number; automation_rate: number; one_click_rate?: number };
  feedback: { total: number; edits: number; rejects: number };
  quality: { accuracy_proxy: number; avg_processing_ms: number };
  by_intent: Record<string, number>;
  by_language: Record<string, number>;
  by_flow?: Record<string, number>;
  by_owner?: Record<string, number>;
  mismatch_kinds?: Record<string, number>;
  multi_intent_pipelines?: number;
  misroute_pipelines?: number;
  intent_taxonomy_size?: number;
  communications?: { total: number; auto_sent: number; csr_approved: number };
  throughput?: {
    emails_per_minute: number;
    queue_depth: number;
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
  };
  mailbox_door_triage?: {
    total_evaluated: number;
    matched_by_rule: number;
    fell_through_to_llm: number;
    by_filter: Record<string, number>;
  };
  aioa?: {
    pass: number;
    fail: number;
    skipped_not_applicable: number;
    timed_out?: number;
  };
  cmd_activation?: {
    requested: number;
  };
};

export type QueueStatus = {
  max_workers: number;
  in_flight: number;
  queue_capacity: number;
  utilisation_pct: number;
  total_submitted: number;
  completed: number;
  errored: number;
  latency_ms: {
    samples: number;
    p50: number;
    p95: number;
    p99: number;
  };
};

export type StageTiming = {
  p50_ms: number;
  p95_ms: number;
  count: number;
  pipeline_ids?: number[];
  pipeline_count?: number;
  // Per-stage tier split: how the pipelines that touched this stage actually
  // ended up. Not the global mix.
  tier_l4?: number;
  tier_l3?: number;
  tier_l2?: number;
  tier_unknown?: number;
  auto_count?: number;
  hitl_count?: number;
  auto_pct?: number;
  hitl_pct?: number;
};

export type DriftAlert = {
  id: number;
  detected_at: string | null;
  updated_at?: string | null;
  fingerprint?: string | null;
  segment: string;
  metric: string;
  baseline: number | null;
  current: number | null;
  delta?: number | null;
  delta_pct: number | null;
  severity: "info" | "warn" | "slo_breach" | "medium" | "high";
  circuit_breaker_fired: boolean;
  status: "open" | "in_review" | "resolved";
  resolved_at: string | null;
  resolved_by: string | null;
  note: string | null;
  detail?: Record<string, unknown> | null;
};

export type Baseline = {
  id: number;
  metric: string;
  segment: string;
  direction: "min" | "max";
  target_value: number;
  drift_pct: number;
  severity: "warn" | "block_promotion";
  enabled: boolean;
  owner: string | null;
  rationale: string | null;
  source: string | null;
  unit: string | null;
  label: string | null;
  last_observed: number | null;
  last_observed_at: string | null;
  last_status: "healthy" | "drifting" | "breached" | "unknown";
  created_at: string | null;
  updated_at: string | null;
  updated_by: string | null;
};

export type BaselinesResponse = {
  items: Baseline[];
  summary: {
    total: number;
    enabled: number;
    healthy: number;
    drifting: number;
    breached: number;
    unknown: number;
    block_promotion_breached: number;
  };
};

export type LearningOpportunity = {
  id: number;
  detected_at: string | null;
  segment: string;
  fingerprint: string;
  proposed_remedy: string;
  expected_lift: string | null;
  effort: "Low" | "Med" | "High";
  risk: "Low" | "Med" | "High";
  score: number;
  status: "open" | "accepted" | "deferred" | "rejected" | "in_ab" | "promoted" | "retired";
  source: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  linked_drift_alert_id: number | null;
  sample_pipeline_ids: number[];
};

export type ABExperimentState = "Proposed" | "Backtested" | "Ready" | "Promoted" | "Retired";

export type ABExperimentSampleRow = {
  pipeline_id: number;
  baseline_intent: string | null;
  target_intent: string | null;
  baseline_correct: boolean;
  candidate_correct: boolean;
  agreed: boolean;
  subject?: string | null;
  from_address?: string | null;
  customer_name?: string | null;
};

export type ABExperimentPromoteGate = {
  enabled: boolean;
  reason?: string;
  delta_pct?: number | null;
  min_pct?: number;
  n?: number;
  min?: number;
};

export type ABExperimentRollback = {
  available: boolean;
  reason?: string;
  days_remaining?: number;
  days_since_promotion?: number;
};

export type ABExperiment = {
  id: number;
  started_at: string | null;
  candidate: string;
  segment: string;
  horizon_kind: "time_window" | "sample_size";
  horizon_value: string;
  sample_collected: number;
  sample_target: number;
  accuracy_delta_pct: number | null;
  accuracy_delta_ci: string | null;
  regression_status: "none" | "watch" | "fail";
  promote_status: "shadow" | "ready" | "promoted" | "retired";
  state?: ABExperimentState;
  promoted_by: string | null;
  promoted_at: string | null;
  promote_note: string | null;
  linked_opportunity_id: number | null;
  kb_namespace: string | null;
  kb_key: string | null;
  control_prompt: string | null;
  candidate_prompt: string | null;
  backtest_results: any | null;
  backtest_ran_at: string | null;
  // Redesigned fields
  change_type?: "prompt" | "threshold" | "pattern_list" | "routing_rule" | "validation_rule" | "other" | string;
  backtest_sample?: ABExperimentSampleRow[];
  previous_body_snapshot?: any | null;
  rolled_back_at?: string | null;
  rolled_back_by?: string | null;
  rolled_back_note?: string | null;
  promote_gate?: ABExperimentPromoteGate;
  rollback?: ABExperimentRollback;
};

export type ABBacktestSummary = {
  sample_size: number;
  target_intent: string | null;
  baseline_correct: number;
  candidate_correct: number;
  baseline_accuracy_pct: number;
  candidate_accuracy_pct: number;
  delta_pct: number;
  mismatches: Array<{
    pipeline_id: number;
    baseline_intent: string | null;
    target_intent: string | null;
    baseline_correct: boolean;
    candidate_correct: boolean;
  }>;
  all_rows: any[];
};

export type StageMeta = {
  stage_key: string;
  id: number;
  label: string;
  tagline: string;
};

export type SubprocessRollup = {
  key: string;
  label: string;
  description: string;
  volume: number;
  auto: number;
  hitl: number;
  fail: number;
  auto_pct: number;
  hitl_pct: number;
  fail_pct: number;
  avg_latency_ms: number;
  source: string;
  ledger_rows?: number;
};

export type StageDetail = {
  stage_key: string;
  stage_id: number;
  stage_label: string;
  tagline: string;
  window_days: number;
  totals: {
    pipelines: number;
    auto: number;
    hitl: number;
    fail: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
  };
  subprocesses: SubprocessRollup[];
  opportunities: Array<{
    id: number;
    segment: string;
    fingerprint: string;
    proposed_remedy: string;
    expected_lift: string | null;
    effort: string;
    risk: string;
    score: number;
    status: string;
  }>;
};

export type CostRollup = {
  window_days: number;
  total_usd: number;
  cost_per_case: number;
  metered_pipelines: number;
  by_stage: Record<string, { total_usd: number; tokens_in: number; tokens_out: number; pages: number; chars: number }>;
  by_component: { component: string; cost_usd: number }[];
  by_model: { model: string; cost_usd: number }[];
};

export type CostCoverage = {
  window_days: number;
  completed_pipelines: number;
  metered_pipelines: number;
  coverage_pct: number;
  fully_covered: boolean;
  missing_pipeline_ids: number[];
};

export type ProcessFlowNode = {
  id: string;
  label: string;
  stage: string | null;
  volume: number;
  auto: number;
  hitl: number;
  fail: number;
  auto_pct: number;
  hitl_pct: number;
  fail_pct: number;
  virtual?: boolean;
};

export type ProcessFlowEdge = {
  source: string;
  target: string;
  case_count: number;
  avg_duration_ms: number;
};

export type ProcessFlowData = {
  window_days: number;
  stage: string | null;
  total_cases: number;
  nodes: ProcessFlowNode[];
  edges: ProcessFlowEdge[];
  min_edge_cases: number;
};

export type CaseRow = {
  pipeline_id: number;
  email_id: number;
  subject: string | null;
  from: string | null;
  received_at: string | null;
  language_hint: string | null;
  customer_name: string | null;
  status: string | null;
  intent: string | null;
  language: string | null;
  confidence: number | null;
  autonomy_tier: string | null;
  started_at: string | null;
};

export type ToolInvocationStat = {
  tool: string;
  count: number;
  ok_count: number;
  p50_ms: number;
  p95_ms: number;
};

export type KbRuleFire = {
  rule_key: string;
  fires: number;
  severity: string;
  last_fired_at: string | null;
};

export type NormalizerCorrections = {
  total_classifications: number;
  corrected: number;
  correction_rate: number;
  top_corrections: { from: string; to: string; count: number }[];
};

export type SpamSignals = {
  llm_only: number;
  heuristic_only: number;
  both: number;
  neither: number;
  agreement_rate: number;
};

export type AutonomyFunnelByIntent = Record<
  string,
  { L4_AUTO: number; L3_ONE_CLICK: number; L2_HITL: number; total: number }
>;

export type AgentFabricStats = {
  stage_timing: Record<string, StageTiming>;
  tool_invocations: ToolInvocationStat[];
  kb_rule_fires: KbRuleFire[];
  normalizer_corrections: NormalizerCorrections;
  spam_signals: SpamSignals;
  autonomy_funnel_by_intent: AutonomyFunnelByIntent;
  translation_provider_mix: Record<string, number>;
};

export type OpsLogRow = {
  currentId: string;
  inboxTime: string | null;
  agentTime: string | null;
  subject: string | null;
  fromAddress: string | null;
  category: string;
  intent: string | null;
  status: "Success" | "Pending" | "Fail" | "";
  startTime: string | null;
  endTime: string | null;
  duration_ms: number | null;
  senderEmail: string | null;
  keywords: string;
  reason: string;
  overrideCategory: string;
  overrideReason: string;
  autonomyTier: string | null;
  confidence: number | null;
  hitlStatus: string;
  mailbox: string;
};

export type OpsLogResponse = {
  rows: OpsLogRow[];
  total: number;
  generated_at: string;
};

export type OpsLogFilters = {
  category?: string;
  status?: string;
  q?: string;
  from?: string;
  to?: string;
  mailbox?: string;
};

export type FeedbackEntry = {
  id: number;
  pipeline_id: number;
  created_at: string;
  stage: string;
  kind: string;
  note: string | null;
  data: any;
};

export type EmailFilter = {
  status?: string;
  intent?: string;
  language?: string;
  autonomy_tier?: string;
};

function qs(params: Record<string, string | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) usp.set(k, v);
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export type CustomerRecord = {
  id: number | string;
  code: string;
  name: string;
  email: string | null;
  region: string;
  language: string;
  vertical: string | null;
  compliance: string[];
  history: { quotes: number; orders: number; work_orders: number; contacts?: number };
  _source?: "salesforce" | "sqlite";
  _sf_account_id?: string;
};

export type ProductRecord = {
  id: number;
  sku: string;
  mpn: string | null;
  description: string;
  list_price: number;
  family: string | null;
  category: string | null;
  lifecycle_status: string;
  lifecycle_eol_date: string | null;
  successor_sku: string | null;
  lead_time_weeks: number;
  calibration_interval_months: number | null;
  country_of_origin: string;
  eccn: string;
  hs_code: string | null;
  warranty_months: number;
  moq: number;
  hazmat: boolean;
  weight_kg: number | null;
};

export type QuoteRecord = {
  id: number;
  quote_number: string;
  customer_code: string | null;
  customer_name: string | null;
  valid_until: string | null;
  total: number;
  status: string;
  line_count: number;
  line_items: any[];
};

export type OrderRecord = {
  id: number;
  order_number: string;
  customer_code: string | null;
  customer_name: string | null;
  status: string;
  hold_reason: string | null;
  requested_ship_date: string | null;
  total: number;
  line_count: number;
  line_items: any[];
  created_at: string | null;
};

export type WorkOrderRecord = {
  id: number;
  wo_number: string;
  customer_code: string | null;
  customer_name: string | null;
  asset_serial: string;
  asset_sku: string | null;
  type: string;
  status: string;
  region: string;
  assigned_team: string | null;
  technician: string | null;
  service_contract_id: string | null;
  scheduled_date: string | null;
  sla_target_date: string | null;
  completed_date: string | null;
  standards_referenced: string[];
  labor_hours: number;
  signoff_status: string;
  cert_number: string | null;
  cost_usd: number;
  pdf_url?: string | null;
  pdf_filename?: string | null;
};

export type ContactRecord = {
  id: number;
  customer_code: string | null;
  customer_name: string | null;
  name: string;
  title: string | null;
  role: string;
  email: string;
  phone: string | null;
  language: string;
  is_primary: boolean;
};

export type AssetRecord = {
  id: number;
  serial: string;
  sku: string;
  description: string | null;
  customer_code: string | null;
  customer_name: string | null;
  install_date: string | null;
  location: string | null;
  last_cal_date: string | null;
  calibration_due_date: string | null;
  cal_interval_months: number | null;
  cal_status: "overdue" | "due_soon" | "current" | "n_a";
  status: string;
  warranty_expires: string | null;
};

export type ServiceContractRecord = {
  id: number;
  contract_number: string;
  customer_code: string | null;
  customer_name: string | null;
  type: string;
  starts_on: string | null;
  expires_on: string | null;
  days_until_expiry: number | null;
  sla_response_hours: number;
  sla_resolution_hours: number;
  included_assets: string[];
  annual_value_usd: number;
  status: string;
};

export type CalCertRecord = {
  id: number;
  cert_number: string;
  customer_code: string | null;
  customer_name: string | null;
  asset_serial: string | null;
  work_order_id: number | null;
  issued_date: string | null;
  expires_date: string | null;
  traceability: string;
  lab_id: string | null;
  technician: string | null;
  out_of_tolerance: boolean;
  as_found_summary: string | null;
  pdf_url?: string | null;
  pdf_filename?: string | null;
};

export type ShipmentRecord = {
  id: number;
  order_id: number;
  order_number: string | null;
  customer_name: string | null;
  carrier: string;
  tracking_number: string;
  ship_date: string | null;
  eta_date: string | null;
  delivered_date: string | null;
  status: string;
  weight_lbs: number | null;
  incoterms: string | null;
};

export type InvoiceRecord = {
  id: number;
  invoice_number: string;
  order_id: number;
  order_number: string | null;
  customer_code: string | null;
  customer_name: string | null;
  invoice_date: string | null;
  due_date: string | null;
  days_overdue: number | null;
  currency: string;
  amount: number;
  paid_amount: number;
  status: string;
  pdf_url?: string | null;
  pdf_filename?: string | null;
};

export type CustomerDetail = Omit<CustomerRecord, "id"> & {
  id: number | string;
  _sf_instance_url?: string;
  legal_entity: string | null;
  industry: string | null;
  naics: string | null;
  annual_revenue_usd: number | null;
  employees: number | null;
  account_manager: string | null;
  sales_engineer: string | null;
  customer_since: string | null;
  status: string;
  sla_tier: string | null;
  duns: string | null;
  tax_id: string | null;
  payment_terms: string;
  credit_limit: number;
  default_currency: string;
  default_incoterms: string;
  addresses: Array<{
    type: string;
    line1?: string;
    line2?: string;
    city?: string;
    region?: string;
    country?: string;
    postal?: string;
  }>;
  contacts: Array<{
    id: number;
    name: string;
    title: string | null;
    role: string;
    email: string;
    phone: string | null;
    language: string;
    is_primary: boolean;
  }>;
  quotes: Array<{
    id: number;
    quote_number: string;
    total: number;
    status: string;
    valid_until: string | null;
    sales_rep: string | null;
    opportunity_id: string | null;
  }>;
  orders: Array<{
    id: number;
    order_number: string;
    status: string;
    hold_reason: string | null;
    requested_ship_date: string | null;
    total: number;
    tracking_number: string | null;
    csr_owner: string | null;
  }>;
  work_orders: Array<{
    id: number;
    wo_number: string;
    type: string;
    status: string;
    asset_serial: string;
    scheduled_date: string | null;
    technician: string | null;
  }>;
  assets: Array<{
    id: number;
    serial: string;
    sku: string;
    description: string | null;
    location: string | null;
    calibration_due_date: string | null;
    status: string;
  }>;
  contracts: Array<{
    id: number;
    contract_number: string;
    type: string;
    starts_on: string | null;
    expires_on: string | null;
    annual_value_usd: number;
    status: string;
  }>;
  invoices: Array<{
    id: number;
    invoice_number: string;
    invoice_date: string | null;
    due_date: string | null;
    amount: number;
    paid_amount: number;
    status: string;
    currency: string;
  }>;
  cal_certs: Array<{
    id: number;
    cert_number: string;
    issued_date: string | null;
    expires_date: string | null;
    traceability: string;
    out_of_tolerance: boolean;
    asset_id: number | null;
  }>;
  communication_log: Array<{
    id: number;
    occurred_at: string | null;
    direction: string;
    channel: string;
    subject: string | null;
    language: string | null;
    intent: string | null;
    autonomy_tier: string | null;
    sent_by: string | null;
    csr_action: string | null;
    pipeline_id: number | null;
    order_id: number | null;
    work_order_id: number | null;
    body_preview: string;
  }>;
};

export type CommLogEntry = {
  id: number;
  customer_id: number | null;
  customer_code: string | null;
  customer_name: string | null;
  occurred_at: string | null;
  direction: string;
  channel: string;
  subject: string | null;
  body_preview: string;
  language: string | null;
  intent: string | null;
  autonomy_tier: string | null;
  sent_by: string | null;
  csr_action: string | null;
  pipeline_id: number | null;
  order_id: number | null;
  work_order_id: number | null;
  attachments: string[];
};

export const api = {
  listEmails: (filter: EmailFilter = {}) =>
    jsonRequest<EmailSummary[]>(`/emails${qs(filter as Record<string, string | undefined>)}`),
  emailCounts: () => jsonRequest<Record<string, number>>(`/emails/counts`),
  customers: () => jsonRequest<CustomerRecord[]>(`/data/customers`),
  customerDetail: (id: number | string) => jsonRequest<CustomerDetail>(`/data/customers/${id}`),
  communicationLogs: () => jsonRequest<CommLogEntry[]>(`/data/communication-logs`),
  products: () => jsonRequest<ProductRecord[]>(`/data/products`),
  quotes: () => jsonRequest<QuoteRecord[]>(`/data/quotes`),
  orders: () => jsonRequest<OrderRecord[]>(`/data/orders`),
  workOrders: () => jsonRequest<WorkOrderRecord[]>(`/data/work-orders`),
  contacts: () => jsonRequest<ContactRecord[]>(`/data/contacts`),
  assets: () => jsonRequest<AssetRecord[]>(`/data/assets`),
  serviceContracts: () => jsonRequest<ServiceContractRecord[]>(`/data/service-contracts`),
  calCerts: () => jsonRequest<CalCertRecord[]>(`/data/cal-certs`),
  shipments: () => jsonRequest<ShipmentRecord[]>(`/data/shipments`),
  invoices: () => jsonRequest<InvoiceRecord[]>(`/data/invoices`),
  getEmail: (id: number) => jsonRequest<EmailDetail>(`/emails/${id}`),
  runPipeline: (emailId: number) =>
    jsonRequest<{ pipeline_id: number }>(`/pipelines/run/${emailId}`, { method: "POST" }),
  queueStatus: () => jsonRequest<QueueStatus>(`/pipelines/queue-status`),
  retryPipeline: (id: number) =>
    jsonRequest<{ ok: boolean }>(`/pipelines/${id}/retry`, { method: "POST" }),
  listErroredPipelines: (limit = 100) =>
    jsonRequest<{
      items: Array<{
        pipeline_id: number;
        email_id: number | null;
        email_subject: string | null;
        email_from: string | null;
        intent: string | null;
        started_at: string | null;
        finished_at: string | null;
        error: string;
        reason_class: "restart_killed" | "db_locked" | "txn_rolled_back" | "other";
      }>;
      total: number;
      by_reason: Record<string, number>;
    }>(`/pipelines/errors?limit=${limit}`),
  retryPipelinesBatch: (body: { pipeline_ids?: number[]; retry_all_errored?: boolean }) =>
    jsonRequest<{
      submitted: number[];
      rejected: Array<{ pipeline_id: number; reason: string }>;
    }>(`/pipelines/retry-batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  suggestFix: (id: number) =>
    jsonRequest<{ ok: boolean }>(`/pipelines/${id}/suggest-fix`, { method: "POST" }),
  getPipeline: (id: number) => jsonRequest<Pipeline>(`/pipelines/${id}`),
  getThread: (pipelineId: number) =>
    jsonRequest<ThreadResponse>(`/threads/${pipelineId}`),
  listHitl: (params: { status?: string; q?: string; reason?: string; intent?: string; tier?: string; assignee_user_id?: string } | string = "pending") => {
    if (typeof params === "string") {
      return jsonRequest<HitlSummary[]>(`/hitl?status=${params}`);
    }
    const u = new URLSearchParams();
    if (params.status) u.set("status", params.status);
    if (params.q) u.set("q", params.q);
    if (params.reason) u.set("reason", params.reason);
    if (params.intent) u.set("intent", params.intent);
    if (params.tier) u.set("tier", params.tier);
    if (params.assignee_user_id) u.set("assignee_user_id", params.assignee_user_id);
    const qs = u.toString();
    return jsonRequest<HitlSummary[]>(`/hitl${qs ? `?${qs}` : ""}`);
  },
  getHitl: (id: number) => jsonRequest<HitlSummary>(`/hitl/${id}`),
  listHitlOperators: (queue?: string) =>
    jsonRequest<{ users: HitlOperator[]; queue: string | null; note?: string }>(
      `/hitl/operators${queue ? `?queue=${encodeURIComponent(queue)}` : ""}`,
    ),
  assignHitl: (id: number, body: { user_id?: string | null; user_name?: string | null; queue?: string | null; assigned_by?: string | null }) =>
    jsonRequest<HitlSummary>(`/hitl/${id}/assign`, { method: "POST", body: JSON.stringify(body) }),
  resolveHitl: (
    id: number,
    body: { action: string; note?: string; edits?: any; reply?: { subject?: string; body?: string } }
  ) =>
    jsonRequest<{
      ok: boolean;
      delivery?: {
        delivery_status?: string | null;
        provider_message_id?: string | null;
        sent_via_account_id?: number | null;
        error?: string | null;
        smtp_host?: string | null;
      };
      recipient?: string | null;
    }>(`/hitl/${id}/resolve`, { method: "POST", body: JSON.stringify(body) }),
  analytics: Object.assign(
    (sinceHours?: number) =>
      jsonRequest<AnalyticsSummary>(
        `/analytics/summary${sinceHours ? `?since_hours=${sinceHours}` : ""}`
      ),
    {
      agentFabric: () => jsonRequest<AgentFabricStats>(`/analytics/agent_fabric`),
      cases: (stage?: string) =>
        jsonRequest<CaseRow[]>(
          `/analytics/cases${stage ? `?stage=${encodeURIComponent(stage)}` : ""}`,
        ),
      stages: () => jsonRequest<StageMeta[]>(`/analytics/stages`),
      stageDetail: (key: string, windowDays = 30) =>
        jsonRequest<StageDetail>(`/analytics/stage/${encodeURIComponent(key)}?window_days=${windowDays}`),
      cost: (windowDays = 30) =>
        jsonRequest<{ rollup: CostRollup; coverage: CostCoverage }>(`/analytics/cost?window_days=${windowDays}`),
      processFlow: (params: { window_days?: number; stage?: string; min_edge_cases?: number } = {}) => {
        const q = new URLSearchParams();
        q.set("window_days", String(params.window_days ?? 30));
        if (params.stage) q.set("stage", params.stage);
        if (params.min_edge_cases != null) q.set("min_edge_cases", String(params.min_edge_cases));
        return jsonRequest<ProcessFlowData>(`/analytics/process_flow?${q.toString()}`);
      },
    }
  ),
  opsLog: (filters: OpsLogFilters = {}) =>
    jsonRequest<OpsLogResponse>(
      `/analytics/ops_log${qs(filters as Record<string, string | undefined>)}`
    ),
  opsLogCsvUrl: (filters: OpsLogFilters = {}) =>
    `${BASE}/analytics/ops_log.csv${qs(filters as Record<string, string | undefined>)}`,
  feedback: () => jsonRequest<FeedbackEntry[]>(`/feedback`),
  learningBaselines: () => jsonRequest<BaselinesResponse>(`/learning/baselines`),
  learningDriftAlerts: () => jsonRequest<DriftAlert[]>(`/learning/drift_alerts`),
  learningOpportunities: () => jsonRequest<LearningOpportunity[]>(`/learning/opportunities`),
  learningAbExperiments: () => jsonRequest<ABExperiment[]>(`/learning/ab_experiments`),
  learningAbExperiment: (id: number) =>
    jsonRequest<ABExperiment>(`/learning/ab_experiments/${id}`),
  backtestAbExperiment: (id: number) =>
    jsonRequest<{ ok: boolean; summary: ABBacktestSummary; experiment: ABExperiment }>(
      `/learning/ab_experiments/${id}/backtest`,
      { method: "POST" },
    ),
  rollbackAbExperiment: (id: number, body: { rolled_back_by?: string; rolled_back_by_id?: string; note?: string; force?: boolean }) =>
    jsonRequest<{ ok: boolean; experiment_id: number; rolled_back_at: string }>(
      `/learning/ab_experiments/${id}/rollback`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  editAbCandidate: (id: number, body: { candidate_prompt: string; edited_by?: string; note?: string }) =>
    jsonRequest<{ ok: boolean; experiment_id: number; promote_status: string; experiment: ABExperiment }>(
      `/learning/ab_experiments/${id}/candidate`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  decideOpportunity: (
    id: number,
    body: { status: string; decided_by?: string; decision_note?: string },
  ) =>
    jsonRequest<{ ok: boolean; id: number; status: string; ab_experiment_id?: number }>(
      `/learning/opportunities/${id}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  decideAbExperiment: (
    id: number,
    body: { promote_status: string; promoted_by?: string; promoted_by_id?: string; promote_note?: string },
  ) =>
    jsonRequest<{ ok: boolean; id: number; promote_status: string }>(
      `/learning/ab_experiments/${id}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  reset: () => jsonRequest(`/seed/reset`, { method: "POST" }),
  integrations: {
    salesforce: {
      status: () => jsonRequest<SalesforceStatus>(`/integrations/salesforce/status`),
      test: (body: SalesforceConnectBody) =>
        jsonRequest<{ ok: boolean; message: string; whoami: SalesforceWhoami | null }>(
          `/integrations/salesforce/test`,
          { method: "POST", body: JSON.stringify(body) }
        ),
      connect: (body: SalesforceConnectBody) =>
        jsonRequest<SalesforceStatus>(`/integrations/salesforce/connect`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      refresh: () =>
        jsonRequest<SalesforceStatus>(`/integrations/salesforce/refresh`, { method: "POST" }),
      disconnect: () =>
        jsonRequest<{ ok: boolean }>(`/integrations/salesforce/disconnect`, { method: "DELETE" }),
      provisionOwners: (only_keys?: string[]) =>
        jsonRequest<{
          checked: number;
          created: { key: string; queue_id: string; queue_label: string; developer_name: string; action: string }[];
          skipped: { key: string; reason: string; queue_id?: string }[];
          errored: { key: string; developer_name: string; error: string }[];
        }>(`/integrations/salesforce/owners/provision`, {
          method: "POST",
          body: JSON.stringify({ only_keys: only_keys || null }),
        }),
      syncOwners: () =>
        jsonRequest<{
          case_queues_in_sf: number;
          synced: { key: string; queue_id: string; queue_label: string; developer_name: string }[];
          not_in_sf: { key: string; developer_name: string }[];
        }>(`/integrations/salesforce/owners/sync`, { method: "POST" }),
    },
    servicenow: {
      status: () => jsonRequest<ServiceNowStatus>(`/integrations/servicenow/status`),
      test: (body: ServiceNowConnectBody) =>
        jsonRequest<{ ok: boolean; message: string; whoami: any }>(`/integrations/servicenow/test`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      connect: (body: ServiceNowConnectBody) =>
        jsonRequest<ServiceNowStatus>(`/integrations/servicenow/connect`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      refresh: () =>
        jsonRequest<ServiceNowStatus>(`/integrations/servicenow/refresh`, { method: "POST" }),
      disconnect: () =>
        jsonRequest<{ ok: boolean }>(`/integrations/servicenow/disconnect`, { method: "DELETE" }),
    },
    openai: {
      status: () => jsonRequest<OpenAIStatus>(`/integrations/openai/status`),
      test: (body: OpenAIConnectBody) =>
        jsonRequest<{ ok: boolean; message: string; model_preview?: string[] }>(
          `/integrations/openai/test`,
          { method: "POST", body: JSON.stringify(body) },
        ),
      connect: (body: OpenAIConnectBody) =>
        jsonRequest<OpenAIStatus>(`/integrations/openai/connect`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      disconnect: () =>
        jsonRequest<{ ok: boolean }>(`/integrations/openai/disconnect`, { method: "DELETE" }),
    },
    salesforceDetails: () =>
      jsonRequest<{
        instance_url: string;
        org_name: string;
        queues: Array<{
          id: string;
          name: string;
          developer_name: string;
          queue_url: string | null;
          member_count: number;
          members: Array<{
            id: string;
            name: string;
            first_name: string | null;
            last_name: string | null;
            username: string;
            email: string | null;
            is_active: boolean;
            profile_url: string | null;
          }>;
        }>;
        counts: {
          accounts: number;
          cases_open: number;
          cases_total: number;
          orders: number;
          work_orders: number;
          service_contracts: number;
        };
        recent_cases: Array<{
          id: string;
          case_number: string;
          subject: string | null;
          status: string | null;
          created_at: string | null;
          account_name: string | null;
          url: string | null;
        }>;
        recent_accounts: Array<{
          id: string;
          name: string | null;
          industry: string | null;
          created_at: string | null;
          url: string | null;
        }>;
      }>(`/integrations/salesforce/details`),
    sharepoint: {
      status: () => jsonRequest<SharePointStatus>(`/integrations/sharepoint/status`),
      test: (body: SharePointConnectBody) =>
        jsonRequest<{ ok: boolean; message: string; whoami: SharePointWhoami | null }>(
          `/integrations/sharepoint/test`,
          { method: "POST", body: JSON.stringify(body) }
        ),
      connect: (body: SharePointConnectBody) =>
        jsonRequest<SharePointStatus>(`/integrations/sharepoint/connect`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      refresh: () =>
        jsonRequest<SharePointStatus>(`/integrations/sharepoint/refresh`, { method: "POST" }),
      disconnect: () =>
        jsonRequest<{ ok: boolean }>(`/integrations/sharepoint/disconnect`, { method: "DELETE" }),
      updateSettings: (body: { folder_path?: string; drive_id?: string | null; label?: string }) =>
        jsonRequest<SharePointStatus>(`/integrations/sharepoint/settings`, {
          method: "PATCH",
          body: JSON.stringify(body),
        }),
      listFiles: (subfolder?: string) =>
        jsonRequest<{ folder: string; subfolder: string | null; items: SharePointItem[]; count: number }>(
          `/integrations/sharepoint/files${subfolder ? `?subfolder=${encodeURIComponent(subfolder)}` : ""}`
        ),
      uploadFile: async (file: File, subfolder?: string) => {
        const fd = new FormData();
        fd.append("file", file);
        const url = `/integrations/sharepoint/files/upload${subfolder ? `?subfolder=${encodeURIComponent(subfolder)}` : ""}`;
        const res = await fetch(`/api${url}`, { method: "POST", body: fd });
        if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text()}`);
        return res.json() as Promise<SharePointItem>;
      },
      downloadUrl: (itemId: string) => `/api/integrations/sharepoint/files/${encodeURIComponent(itemId)}/download`,
      deleteFile: (itemId: string) =>
        jsonRequest<{ ok: boolean }>(`/integrations/sharepoint/files/${encodeURIComponent(itemId)}`, {
          method: "DELETE",
        }),
    },
    placeholders: {
      list: () =>
        jsonRequest<{ items: IntegrationPlaceholder[] }>(`/integrations/placeholders`),
      get: (provider: string) =>
        jsonRequest<IntegrationPlaceholder>(`/integrations/placeholders/${encodeURIComponent(provider)}`),
      update: (provider: string, body: { enabled?: boolean; config?: Record<string, unknown>; note?: string }) =>
        jsonRequest<IntegrationPlaceholder>(`/integrations/placeholders/${encodeURIComponent(provider)}`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
    },
  },
  system: {
    readiness: () => jsonRequest<ReadinessReport>(`/system/readiness`),
    verificationRollup: (windowDays = 7) =>
      jsonRequest<{
        window_days: number;
        total_evaluations: number;
        pass_count: number;
        fail_count: number;
        pipelines_with_block: number;
        pipelines_with_warn: number;
        pipelines_with_audit_only: number;
        halted_pipelines: number[];
        top_failing_rules: { rule_key: string; fail_count: number; pass_count: number }[];
      }>(`/system/verification/rollup?window_days=${windowDays}`),
    simulateVerificationRule: (body: any, limit = 200) =>
      jsonRequest<{
        checked_pipelines: number;
        rule_applied_count: number;
        rule_passed_count: number;
        rule_failed_count: number;
        rule_error_count: number;
        match_rate_pct: number;
        fail_rate_pct: number;
        results: any[];
      }>(`/kb/pipeline_verification_rules/_simulate`, {
        method: "POST",
        body: JSON.stringify({ body, limit }),
      }),
  },
  notifications: {
    list: (opts: { include_resolved?: boolean; include_dismissed?: boolean; limit?: number } = {}) => {
      const qs: string[] = [];
      if (opts.include_resolved) qs.push("include_resolved=true");
      if (opts.include_dismissed) qs.push("include_dismissed=true");
      if (opts.limit) qs.push(`limit=${opts.limit}`);
      return jsonRequest<NotificationFeed>(`/notifications${qs.length ? "?" + qs.join("&") : ""}`);
    },
    markRead: (id: number) =>
      jsonRequest<NotificationItem>(`/notifications/${id}/read`, { method: "POST" }),
    dismiss: (id: number) =>
      jsonRequest<NotificationItem>(`/notifications/${id}/dismiss`, { method: "POST" }),
    markAllRead: () =>
      jsonRequest<{ marked_read: number }>(`/notifications/mark-all-read`, { method: "POST" }),
  },
  emailAccounts: {
    list: () => jsonRequest<EmailAccount[]>(`/email-accounts`),
    providers: () => jsonRequest<ProviderPreset[]>(`/email-accounts/providers`),
    test: (body: AccountFormBody) =>
      jsonRequest<{ ok: boolean; message: string; imap_host: string; imap_port: number; folder: string }>(
        `/email-accounts/test`,
        { method: "POST", body: JSON.stringify(body) }
      ),
    create: (body: AccountFormBody & { sync_interval_sec?: number; label?: string | null }) =>
      jsonRequest<EmailAccount>(`/email-accounts`, { method: "POST", body: JSON.stringify(body) }),
    remove: (id: number) => jsonRequest(`/email-accounts/${id}`, { method: "DELETE" }),
    toggle: (id: number) => jsonRequest<EmailAccount>(`/email-accounts/${id}/toggle`, { method: "POST" }),
    refresh: (id: number) =>
      jsonRequest<{ ok: boolean; new_email_ids: number[]; error: string | null; account: EmailAccount }>(
        `/email-accounts/${id}/refresh`,
        { method: "POST" }
      ),
    refreshAll: () =>
      jsonRequest<{ results: { account_id: number; email_address: string; new: number; error: string | null }[] }>(
        `/email-accounts/refresh-all`,
        { method: "POST" }
      ),
    testSmtp: (id: number) =>
      jsonRequest<{ ok: boolean; message: string }>(`/email-accounts/${id}/test-smtp`, { method: "POST" }),
    get: (id: number) => jsonRequest<EmailAccount>(`/email-accounts/${id}`),
    updateFolderMap: (id: number, category_folder_map: Record<string, string>) =>
      jsonRequest<EmailAccount>(`/email-accounts/${id}/folder-map`, {
        method: "PATCH",
        body: JSON.stringify({ category_folder_map }),
      }),
  },
};

export type SalesforceConnectBody = {
  instance_url: string;
  consumer_key: string;
  consumer_secret: string;
  flow?: "client_credentials" | "password";
  username?: string;
  password?: string;
  security_token?: string;
  domain?: string;
  api_version?: string;
  label?: string;
};

export type SalesforceWhoami = {
  org_id: string;
  org_name: string;
  org_edition: string;
  user_display_name: string;
  instance_url: string;
  daily_api_remaining: number | null;
  daily_api_max: number | null;
};

export type ServiceNowConnectBody = {
  instance_url: string;
  username: string;
  password: string;
  case_table?: string;
  label?: string;
};

export type ServiceNowStatus = {
  connected: boolean;
  id?: number;
  label?: string;
  instance_url?: string;
  username?: string;
  case_table?: string | null;
  instance_version?: string | null;
  incident_count?: number | null;
  csm_active?: boolean;
  last_tested_at?: string | null;
  last_error?: string | null;
};

export type SalesforceStatus = {
  connected: boolean;
  id?: number;
  label?: string;
  instance_url?: string;
  username?: string;
  org_id?: string | null;
  org_name?: string | null;
  org_edition?: string | null;
  user_display_name?: string | null;
  daily_api_remaining?: number | null;
  daily_api_max?: number | null;
  last_tested_at?: string | null;
  last_error?: string | null;
};

export type SharePointConnectBody = {
  tenant_id: string;
  client_id: string;
  client_secret: string;
  site_id: string;
  drive_id?: string | null;
  folder_path?: string;
  label?: string;
};

export type SharePointWhoami = {
  site_id: string;
  site_display_name: string | null;
  site_web_url: string | null;
  drive_id: string | null;
  drive_name: string | null;
  folder_path: string;
  item_count: number | null;
};

export type SharePointStatus = {
  connected: boolean;
  id?: number;
  label?: string;
  tenant_id?: string;
  client_id?: string;
  site_id?: string;
  drive_id?: string | null;
  folder_path?: string;
  site_display_name?: string | null;
  site_web_url?: string | null;
  drive_name?: string | null;
  item_count?: number | null;
  last_tested_at?: string | null;
  last_error?: string | null;
};

export type SharePointItem = {
  id: string;
  name: string;
  kind: "file" | "folder";
  size: number | null;
  web_url: string | null;
  last_modified: string | null;
  mime_type: string | null;
  download_url: string | null;
};

export type IntegrationPlaceholder = {
  provider: string;
  label: string;
  kind: string | null;
  description: string | null;
  enabled: boolean;
  config: Record<string, unknown>;
  last_enabled_at: string | null;
  last_disabled_at: string | null;
  note: string | null;
};

export type ReadinessBlocker = {
  provider: "salesforce" | "sharepoint" | "mailbox" | "llm" | string;
  severity: "blocker" | "warning";
  title: string;
  detail: string;
  fix_url: string;
  last_event_at: string | null;
  last_error: string | null;
};

export type ReadinessReport = {
  ok: boolean;
  demo_mode: boolean;
  checked_at: string;
  blockers: ReadinessBlocker[];
  warnings: ReadinessBlocker[];
  summary: {
    blocker_count: number;
    warning_count: number;
    missing_providers: string[];
  };
};

export type NotificationCategory = "connection" | "queue" | "workflow" | "drift" | "system" | "learning";
export type NotificationSeverity = "critical" | "warning" | "info";

export type NotificationItem = {
  id: number;
  kind: string;
  category: NotificationCategory | string;
  severity: NotificationSeverity | string;
  title: string;
  body: string | null;
  action_url: string | null;
  action_label: string | null;
  meta: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  read_at: string | null;
  dismissed_at: string | null;
  resolved_at: string | null;
};

export type NotificationFeed = {
  items: NotificationItem[];
  summary: {
    active_total: number;
    unread_total: number;
    by_severity: { critical: number; warning: number; info: number };
  };
};

export type EmailAccount = {
  id: number;
  provider: string;
  email_address: string;
  label: string | null;
  imap_host: string;
  imap_port: number;
  folder: string;
  sync_interval_sec: number;
  is_active: boolean;
  last_synced_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  messages_imported: number;
  category_folder_map?: Record<string, string>;
  created_at: string | null;
};

export type ProviderPreset = {
  key: string;
  imap_host: string;
  imap_port: number;
  folder: string;
};

export type AccountFormBody = {
  provider: string;
  email_address: string;
  password: string;
  imap_host?: string;
  imap_port?: number;
  folder?: string;
  username?: string;
};

// === v1.1 TASK-7 START === Test-corpus regression suite types + endpoints
export type TestCase = {
  id: number;
  name: string;
  subject: string;
  from_address: string;
  body: string;
  expected_intent: string;
  expected_action: string | null;
  expected_routing: string | null;
  expected_keywords: string[];
  notes: string | null;
  created_at: string | null;
};

export type TestRun = {
  id: number;
  label: string;
  started_at: string | null;
  finished_at: string | null;
  case_count: number;
  initial_pass: number;
  initial_fail: number;
  post_fix_pass: number;
  still_failed: number;
  pass_pct: number | null;
  post_fix_pct: number | null;
};

export type TestRunResult = {
  id: number;
  test_case_id: number;
  case_name: string | null;
  case_subject: string | null;
  expected_intent: string | null;
  actual_intent: string | null;
  pass_initial: boolean;
  pass_post_fix: boolean | null;
  pipeline_id: number | null;
  diff: Record<string, unknown>;
};

export const testCorpusApi = {
  listCases: () => jsonRequest<TestCase[]>(`/test-corpus/cases`),
  addCase: (c: Omit<TestCase, "id" | "created_at">) =>
    jsonRequest<TestCase>(`/test-corpus/cases`, { method: "POST", body: JSON.stringify(c) }),
  deleteCase: (id: number) =>
    jsonRequest<{ ok: boolean }>(`/test-corpus/cases/${id}`, { method: "DELETE" }),
  listRuns: () => jsonRequest<TestRun[]>(`/test-corpus/runs`),
  getRunResults: (id: number) =>
    jsonRequest<{ run: TestRun; results: TestRunResult[] }>(`/test-corpus/runs/${id}/results`),
  triggerRun: (label?: string, case_ids?: number[]) =>
    jsonRequest<TestRun>(`/test-corpus/run`, {
      method: "POST",
      body: JSON.stringify({ label, case_ids }),
    }),
};
// === v1.1 TASK-7 END ===


// === AIOA (Order Acceptance) ===
export type OpenAIStatus = {
  connected: boolean;
  source: "db" | "env" | "none";
  provider: string;
  model: string;
  api_key_masked: string;
  is_active?: boolean;
  last_tested_at?: string | null;
  last_error?: string | null;
  updated_at?: string | null;
};

export type OpenAIConnectBody = {
  api_key: string;
  model?: string | null;
  is_active?: boolean;
};

export type AIOAProvider = {
  id: number;
  slug: string;
  name: string;
  outbound_url: string;
  outbound_auth_scheme: "none" | "bearer" | "api_key";
  timeout_seconds: number;
  retry_max: number;
  retry_backoff_seconds: number;
  is_active: boolean;
  last_send_at: string | null;
  last_callback_at: string | null;
  callback_url: string;
  callback_url_configured?: boolean;
  has_outbound_auth_value: boolean;
  inbound_secret: string;
};

export type AIOAProviderInput = {
  name: string;
  outbound_url: string;
  outbound_auth_scheme: "none" | "bearer" | "api_key";
  outbound_auth_value?: string | null;
  timeout_seconds: number;
  retry_max: number;
  retry_backoff_seconds: number;
  is_active: boolean;
};

export type AIOARequestRow = {
  id: number;
  correlation_id: string;
  pipeline_id: number;
  provider_id: number | null;
  provider_name: string | null;
  status: string;
  decision: "PASS" | "FAIL" | null;
  fallout_reasons: any[];
  retry_count: number;
  last_error: string | null;
  created_at: string | null;
  sent_at: string | null;
  response_received_at: string | null;
  processed_at: string | null;
  csr_draft_subject?: string | null;
};

export type AIOARequestDetail = AIOARequestRow & {
  request_payload: Record<string, any>;
  response_payload: Record<string, any>;
  csr_draft: { subject?: string; body?: string; kind?: string; correlation_id?: string };
};

// === SIGNAL GRAPH (Quality-Gate Discovery) ===
// One candidate quality gate returned by GET /signal-graph/recommendations.
// Mirrors the dict the backend builds in routes/signal_graph.py.
export type SgRecommendation = {
  id: number;                 // recommendation row id (used to accept/dismiss/graph)
  metric: string;            // the gate's key, e.g. "availability.healthcheck_success_rate"
  segment: string;           // scope of the metric, "global" in v1
  direction: "min" | "max";  // "min" = higher-is-better, "max" = lower-is-better
  score: number;             // ranking score (0 until data exists)
  rationale: string;         // LLM's one-line reason this gate is worth watching
  inputs: string[];          // the signal keys this gate is computed from (graph edges)
  compute: string | null;    // how it's computed: rate | ratio | p95 | psi | count | mean
  suggested_range: SgSuggestedRange; // non-binding hint for the human's target
};

// Data-conditional hint: "ok" carries median/p10/p90 over n windows; otherwise
// the status explains why there's nothing to show (no telemetry yet).
export type SgSuggestedRange =
  | { status: "ok"; n: number; median: number; p10: number; p90: number }
  | { status: "no_data" | "insufficient_data" };

// The signal subgraph for one gate, returned by GET /recommendations/{id}/graph.
export type SgGraph = {
  nodes: { key: string; type: string }[];                       // signals + the target node
  edges: { from: string; to: string; weight: number | null }[]; // signal -> target links
};

// Small summary returned by POST /signal-graph/discover.
export type SgDiscoverResult = {
  session_id: string;
  signals: number;  // how many signals Pass 1 extracted
  gates: number;    // how many candidate gates Pass 2 proposed
};

// An accepted gate (a baseline target) with its data-conditional drift, from
// GET /signal-graph/baselines. "ok" carries live drift; otherwise the status
// explains why there's nothing computed yet.
export type SgGate = {
  metric: string;
  segment: string;
  direction: "min" | "max";
  target_value: number | null;
  status: "ok" | "insufficient_data" | "no_data" | "no_target";
  current?: number;
  delta?: number;
  delta_pct?: number | null;
  psi?: number | null;
  breached?: boolean;
  severity?: "high" | "medium" | "info";
};

// Summary from POST /signal-graph/analyze.
export type SgAnalyzeResult = {
  domain: string;
  edges_updated: number;
  gates_analyzed: number;
};

export const signalGraphApi = {
  discover: (tenant_id: string, session_id: string) =>
    jsonRequest<SgDiscoverResult>(`/signal-graph/discover`, {
      method: "POST",
      body: JSON.stringify({ tenant_id, session_id }),
    }),
  recommendations: (session_id: string) =>
    jsonRequest<SgRecommendation[]>(
      `/signal-graph/recommendations?session_id=${encodeURIComponent(session_id)}`,
    ),
  accept: (id: number, target_value: number) =>
    jsonRequest<{ id: number; metric: string; target_value: number; status: string }>(
      `/signal-graph/recommendations/${id}/accept`,
      { method: "POST", body: JSON.stringify({ target_value }) },
    ),
  dismiss: (id: number) =>
    jsonRequest<{ ok: boolean }>(`/signal-graph/recommendations/${id}/dismiss`, {
      method: "POST",
    }),
  graph: (id: number) =>
    jsonRequest<SgGraph>(`/signal-graph/recommendations/${id}/graph`),
  analyze: (session_id: string) =>
    jsonRequest<SgAnalyzeResult>(`/signal-graph/analyze`, {
      method: "POST",
      body: JSON.stringify({ tenant_id: "", session_id }),
    }),
  baselines: (session_id: string) =>
    jsonRequest<SgGate[]>(
      `/signal-graph/baselines?session_id=${encodeURIComponent(session_id)}`,
    ),
  seedDemo: (session_id: string, windows = 8) =>
    jsonRequest<{ domain: string; windows: number; observations_written: number; gates: number; signals_seeded: number }>(
      `/signal-graph/seed-demo`,
      { method: "POST", body: JSON.stringify({ session_id, windows }) },
    ),
};


export const aioaApi = {
  listProviders: () => jsonRequest<AIOAProvider[]>(`/aioa/providers`),
  getProvider: (id: number) => jsonRequest<AIOAProvider>(`/aioa/providers/${id}`),
  updateProvider: (id: number, body: AIOAProviderInput) =>
    jsonRequest<AIOAProvider>(`/aioa/providers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  testProvider: (id: number, outbound_url?: string) =>
    jsonRequest<{ ok: boolean; http_status: number; body_preview?: string; error?: string }>(
      `/aioa/providers/${id}/test`,
      { method: "POST", body: JSON.stringify({ outbound_url: outbound_url ?? null }) },
    ),
  listRequests: (params: { status?: string; pipeline_id?: number; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.pipeline_id != null) q.set("pipeline_id", String(params.pipeline_id));
    if (params.limit != null) q.set("limit", String(params.limit));
    const qs = q.toString();
    return jsonRequest<{ items: AIOARequestRow[]; counts_by_status: Record<string, number> }>(
      `/aioa/requests${qs ? `?${qs}` : ""}`,
    );
  },
  getRequest: (id: number) => jsonRequest<AIOARequestDetail>(`/aioa/requests/${id}`),
  replay: (id: number, body: { decision: "PASS" | "FAIL"; fallout_reasons?: any[]; evidence?: any }) =>
    jsonRequest<{ ok: boolean; correlation_id: string; status: string }>(
      `/aioa/requests/${id}/replay`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  resend: (id: number) =>
    jsonRequest<{ ok: boolean; correlation_id: string; status: string }>(
      `/aioa/requests/${id}/resend`,
      { method: "POST" },
    ),
};
