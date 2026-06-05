import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, CaseRow, Pipeline, ThreadResponse, TraceEvent } from "../api";
import { ConfidenceBar, IntentPill, StatusPill, TierPill } from "../components/Pills";
import { attachmentUrl, PreviewItem, PreviewModal } from "../components/PreviewModal";
import { StageFeedback } from "../components/StageFeedback";

type StageKey = "intake" | "extract" | "decide" | "execute" | "communicate";
type SubStepStatus = "done" | "running" | "skipped" | "error" | "pending";

// === v1.1 TRACE-TERMINAL === skipped state added so terminal-intent flows show clearly
type StageStatus = { status: "pending" | "running" | "done" | "error" | "skipped" | "deferred"; ms?: number };

type SubStep = {
  num: string;
  name: string;
  status: SubStepStatus;
  result?: string;
  ms?: number | null;
  toolEvent?: TraceEvent | null;
  inputPreview?: string;
  processing?: string;
  provider?: string;
  rulesEvaluated?: any[];
  rawData?: any;
  kbNamespaces?: string[];
  kbRulesUsed?: string[];
  promptSystem?: string;
  promptUser?: string;
  rawResponse?: string;
  outputFields?: { label: string; value: any; mono?: boolean; long?: boolean; link?: string }[];
  outputPreview?: string;
  attachmentsBreakdown?: {
    filename: string;
    provider?: string;
    char_count?: number;
    text_preview?: string;
    page_count?: number;
    max_pages_requested?: number;
    notes?: string[];
  }[];
};

// === v1.1 TRACE-TERMINAL === pre_intake events surface under Intake & Classification (Stage 1)
// The `ccc` stage events (Salesforce Case lifecycle) belong under Stage 3 —
// that's where the lookup-or-create resolution runs once intake + extract
// have produced the real Case fields.
// Canonical stage names — match analytics.subprocess_taxonomy.STAGE_META.
// Keep this in sync with Dashboard STAGE_DEFS, Analytics STAGE_LABELS,
// Learning STAGE_LABELS, and each per-agent stage_label.
const STAGES: { key: StageKey; label: string; num: number; traceStages: string[] }[] = [
  { key: "intake", label: "Intake & Classification", num: 1, traceStages: ["intake", "pre_intake"] },
  { key: "extract", label: "Extraction & Enrichment", num: 2, traceStages: ["extract", "enrichment"] },
  { key: "decide", label: "Decision & Confidence Scoring", num: 3, traceStages: ["decide", "reconcile", "ccc"] },
  { key: "execute", label: "Workflow Execution", num: 4, traceStages: ["execute"] },
  { key: "communicate", label: "Communication & Close-out", num: 5, traceStages: ["communicate"] },
];

const LANG_NAMES: Record<string, string> = {
  en: "English",
  es: "Spanish",
  ja: "Japanese",
  fr: "French",
  de: "German",
  zh: "Chinese",
  ko: "Korean",
  pt: "Portuguese",
};

const INTENT_LABELS: Record<string, string> = {
  po_intake: "PO intake",
  quote_to_order: "Quote → Order conversion",
  hold_release: "Hold release",
  delivery_change: "Delivery rescheduling",
  service_order: "Service order",
  wo_status_inquiry: "Work-order status inquiry",
  general_inquiry: "General inquiry",
  spam: "Spam / Phishing",
};

const ACTION_LABELS: Record<string, string> = {
  create_order_acknowledgment: "Acknowledge purchase order",
  convert_quote_to_order: "Convert quote to order",
  release_hold: "Release order from hold",
  reschedule_order: "Reschedule shipment",
  create_work_order: "Create work order",
  report_wo_status: "Report work-order status",
  draft_reply: "Draft customer reply",
  discard: "Discard (spam)",
  route_to_csr: "Route to CSR",
};

// === Salesforce / SharePoint deep-link helpers ===========================
// Cache the active org's instance URL once per page load so each clickable
// link can be built without round-tripping the backend for every record.
let _sfInstanceCache: string | null | undefined = undefined;
async function getSalesforceInstanceUrl(): Promise<string | null> {
  if (_sfInstanceCache !== undefined) return _sfInstanceCache;
  try {
    const status = await api.integrations.salesforce.status();
    _sfInstanceCache = status.instance_url || null;
  } catch {
    _sfInstanceCache = null;
  }
  return _sfInstanceCache;
}

function buildSalesforceUrl(instanceUrl: string | null | undefined, recordId: string | null | undefined): string | null {
  if (!instanceUrl || !recordId) return null;
  const base = instanceUrl.replace(/\/$/, "");
  return `${base}/lightning/r/${recordId}/view`;
}

function SalesforceLink({ caseId, label = "Open in Salesforce" }: { caseId: string | null | undefined; label?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancel = false;
    if (!caseId) {
      setUrl(null);
      return;
    }
    getSalesforceInstanceUrl().then((inst) => {
      if (cancel) return;
      setUrl(buildSalesforceUrl(inst, caseId));
    });
    return () => { cancel = true; };
  }, [caseId]);
  if (!caseId) return null;
  if (!url) return <span className="text-[11px] text-emerald-700/70">(linking…)</span>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="ml-1 inline-flex items-center gap-1 rounded border border-emerald-300 bg-white/70 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-800 hover:bg-emerald-100"
    >
      {label} ↗
    </a>
  );
}

function ExternalLinkBadge({ href, label }: { href: string | null | undefined; label: string }) {
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[10.5px] font-semibold text-slate-700 hover:bg-slate-50"
    >
      {label} ↗
    </a>
  );
}

const VERTICAL_LABELS: Record<string, string> = {
  aerospace_defense: "Aerospace & Defense",
  semiconductor: "Semiconductor",
  wireless_5g6g: "Wireless / 5G·6G",
  automotive: "Automotive",
  research: "Research",
  industrial: "Industrial",
  test_systems_integrator: "T&M Systems Integrator",
};

export function TracePage() {
  const params = useParams();
  const pipelineId = params.pipelineId ? Number(params.pipelineId) : null;
  const [searchParams] = useSearchParams();
  const stageFromUrl = searchParams.get("stage");
  const initialStage: StageKey = (stageFromUrl === "extract" || stageFromUrl === "decide" || stageFromUrl === "execute" || stageFromUrl === "communicate")
    ? stageFromUrl
    : "intake";
  const [pipe, setPipe] = useState<Pipeline | null>(null);
  const [live, setLive] = useState<TraceEvent[]>([]);
  const [preview, setPreview] = useState<PreviewItem | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [selectedStage, setSelectedStage] = useState<StageKey>(initialStage);
  const [userPickedStage, setUserPickedStage] = useState<boolean>(!!stageFromUrl);

  useEffect(() => {
    if (pipelineId == null) return;
    let cancel = false;
    let intervalId: number | null = null;
    const fetchOnce = async () => {
      try {
        const p = await api.getPipeline(pipelineId);
        if (cancel) return;
        setPipe(p);
        // Stop polling once the pipeline reaches a terminal state — events
        // don't change after completion, so refetching the full events array
        // every 1.5s just wastes bandwidth and load.
        const terminal = ["completed", "discarded", "awaiting_hitl", "failed", "error"];
        if (p.status && terminal.includes(p.status) && intervalId != null) {
          clearInterval(intervalId);
          intervalId = null;
        }
      } catch {
        // Network/transient — keep the interval alive, next tick may succeed.
      }
    };
    fetchOnce();
    intervalId = setInterval(fetchOnce, 1500) as unknown as number;
    return () => {
      cancel = true;
      if (intervalId != null) clearInterval(intervalId);
    };
  }, [pipelineId]);

  useEffect(() => {
    if (pipelineId == null) return;
    const url = `/api/trace/stream?pipeline_id=${pipelineId}`;
    const src = new EventSource(url);
    const onEvent = (e: MessageEvent) => {
      try {
        const ev = JSON.parse(e.data);
        if (!ev.id) return;
        setLive((cur) => (cur.find((x) => x.id === ev.id) ? cur : [...cur, ev]));
      } catch {}
    };
    src.addEventListener("trace", onEvent as any);
    return () => {
      src.removeEventListener("trace", onEvent as any);
      src.close();
    };
  }, [pipelineId]);

  const events = useMemo(() => {
    const merged = [...(pipe?.events || [])];
    for (const e of live) {
      if (!merged.find((m) => m.id === e.id)) merged.push(e);
    }
    return merged.sort((a, b) => a.id - b.id);
  }, [pipe, live]);

  const stageState: Record<string, StageStatus> = {};
  for (const s of STAGES) stageState[s.key] = { status: "pending" };
  for (const ev of events) {
    const stageKey = STAGES.find((s) => s.traceStages.includes(ev.stage))?.key;
    if (!stageKey) continue;
    if (ev.kind === "stage_start" && stageState[stageKey].status === "pending") {
      stageState[stageKey].status = "running";
    }
    if (ev.kind === "stage_end") {
      if (stageState[stageKey].status !== "error") {
        stageState[stageKey].status = "done";
      }
      if (ev.duration_ms) {
        stageState[stageKey].ms = (stageState[stageKey].ms || 0) + ev.duration_ms;
      }
    }
    if (ev.kind === "stage_error") {
      stageState[stageKey].status = "error";
      if (ev.duration_ms) stageState[stageKey].ms = ev.duration_ms;
    }
    if (ev.kind === "stage_deferred") {
      // Pipeline parked upstream (Execute → HITL). Stage 5 doesn't run
      // until the operator resolves; show as deferred, not pending.
      stageState[stageKey].status = "deferred";
    }
  }

  // === v1.1 TRACE-TERMINAL START === Terminal-intent short-circuit handling.
  // When the pre-AI Outlook rules match (KSO / Undeliverable / Brazil Tax / Portal Admin / Collections / Auto-Reply),
  // Stage 1 (Intake) is effectively complete via deterministic rule, and Stages 2-5 are intentionally skipped.
  // Detect that here so the UI does not show downstream stages as 'pending' when they are not running.
  const preIntakeMatched = events.some((ev) => ev.stage === "pre_intake" && ev.kind === "rule_matched");
  const shortCircuited = events.some((ev) => ev.stage === "intake" && ev.kind === "short_circuit");
  if (preIntakeMatched && stageState["intake"].status === "pending") {
    stageState["intake"].status = "done";
  }
  if (shortCircuited || preIntakeMatched) {
    for (const k of ["extract", "decide", "execute", "communicate"] as const) {
      if (stageState[k].status === "pending") {
        stageState[k].status = "skipped";
      }
    }
  }
  const redirectEvent = events.find((ev) => ev.stage === "pre_intake" && ev.kind === "redirect");
  const ruleMatchEvent = events.find((ev) => ev.stage === "pre_intake" && ev.kind === "rule_matched");
  // === v1.1 TRACE-TERMINAL END ===

  if (!pipelineId) {
    return <ActivityList />;
  }

  const onRetry = async () => {
    if (!pipelineId) return;
    if (!confirm("Re-process this request from scratch? All recorded activity events will be cleared.")) return;
    await api.retryPipeline(pipelineId);
    setLive([]);
    setPipe(null);
  };

  const onSuggestFix = async () => {
    if (!pipelineId || suggesting) return;
    setSuggesting(true);
    try {
      await api.suggestFix(pipelineId);
    } finally {
      setSuggesting(false);
    }
  };

  // Map the pipeline-level status to the stage where the pipeline is parked.
  // Awaiting_aioa parks AFTER decide completes its substeps (3.5 AIOA handoff
  // queued the external validator). Awaiting_hitl / awaiting_one_click park
  // mid-execute (the workflow action was staged but not committed). Errors
  // are pinned to the stage that emitted the error.
  const parkedStage: StageKey | null = (() => {
    const status = pipe?.status;
    if (status === "awaiting_aioa") return "decide";
    if (status === "awaiting_hitl" || status === "awaiting_one_click") return "execute";
    if (status === "error") {
      const errStage = STAGES.find((s) => stageState[s.key]?.status === "error");
      return errStage?.key || null;
    }
    return null;
  })();

  if (!userPickedStage) {
    const running = STAGES.find((s) => stageState[s.key]?.status === "running");
    if (running && selectedStage !== running.key) {
      setSelectedStage(running.key);
    } else if (parkedStage && selectedStage !== parkedStage) {
      // For a parked pipeline, auto-jump to the parked stage so the CSR
      // lands on the right tab without scrolling.
      setSelectedStage(parkedStage);
    }
  }

  // First paint: until the first fetch resolves, render a lightweight skeleton
  // so the page is never empty. Avoids the perception of a slow load when the
  // pipeline detail endpoint returns a large events array.
  if (!pipe) {
    return (
      <div className="space-y-4">
        <div className="card p-5 animate-pulse">
          <div className="flex items-start justify-between">
            <div className="space-y-2 flex-1">
              <div className="h-3 w-32 bg-zbrain-divider/60 rounded" />
              <div className="h-5 w-56 bg-zbrain-divider/80 rounded" />
              <div className="h-3 w-44 bg-zbrain-divider/40 rounded" />
            </div>
            <div className="space-y-2 text-right">
              <div className="h-5 w-24 bg-zbrain-divider/60 rounded ml-auto" />
              <div className="h-3 w-32 bg-zbrain-divider/40 rounded ml-auto" />
            </div>
          </div>
        </div>
        <div className="card p-4 animate-pulse">
          <div className="h-3 w-40 bg-zbrain-divider/60 rounded mb-3" />
          <div className="h-3 w-full bg-zbrain-divider/40 rounded mb-1.5" />
          <div className="h-3 w-5/6 bg-zbrain-divider/40 rounded mb-1.5" />
          <div className="h-3 w-2/3 bg-zbrain-divider/40 rounded" />
        </div>
        <div className="grid grid-cols-5 gap-3 animate-pulse">
          {STAGES.map((s) => (
            <div key={s.key} className="card p-3 space-y-2">
              <div className="h-3 w-20 bg-zbrain-divider/60 rounded" />
              <div className="h-4 w-full bg-zbrain-divider/50 rounded" />
              <div className="h-3 w-24 bg-zbrain-divider/30 rounded" />
            </div>
          ))}
        </div>
        <div className="text-center text-xs text-zbrain-muted">Loading activity #{pipelineId}…</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ActivityHeader pipe={pipe} pipelineId={pipelineId} onRetry={onRetry} />
      <CloseOutSummaryCard pipe={pipe} events={events} />
      <NextStepBanner pipe={pipe} pipelineId={pipelineId} events={events} />
      {/* === v1.1 TRACE-TERMINAL START === Redirect banner shown when a pre-AI rule short-circuits */}
      {ruleMatchEvent && (
        <RedirectBanner
          ruleMatch={ruleMatchEvent}
          redirect={redirectEvent}
          intent={pipe.intent}
        />
      )}
      {/* === v1.1 TRACE-TERMINAL END === */}
      <InboundEmailCard pipe={pipe} setPreview={setPreview} />
      <ThreadContextPanel pipelineId={pipelineId} />

      <StageNavStrip
        stages={STAGES}
        stageState={stageState}
        selected={selectedStage}
        parked={parkedStage}
        onSelect={(k) => {
          setSelectedStage(k);
          setUserPickedStage(true);
        }}
      />

      {selectedStage === "intake" && (
        <IntakeStageCard pipe={pipe} state={stageState["intake"]} events={events} />
      )}
      {selectedStage === "extract" && (
        <ExtractStageCard pipe={pipe} state={stageState["extract"]} events={events} />
      )}
      {selectedStage === "decide" && (
        <DecideStageCard
          pipe={pipe}
          state={stageState["decide"]}
          events={events}
          suggesting={suggesting}
          onSuggest={onSuggestFix}
        />
      )}
      {selectedStage === "execute" && (
        <ExecuteStageCard pipe={pipe} state={stageState["execute"]} events={events} />
      )}
      {selectedStage === "communicate" && (
        <CommunicateStageCard
          pipe={pipe}
          state={stageState["communicate"]}
          events={events}
          setPreview={setPreview}
        />
      )}

      {/* Pipeline verification panel hidden per operator request; the agent
          activity log + per-stage details below cover the same evidence.
          Restore by uncommenting the line below when the verification UI is
          ready to surface again. */}
      {false && <VerificationPanel events={events} />}

      <button
        onClick={() => setShowLog((v) => !v)}
        className="w-full card px-4 py-2.5 text-sm text-zbrain hover:bg-zbrain-50/50 text-left flex items-center justify-between"
      >
        <span>{showLog ? "▾" : "▸"} Agent activity log ({events.length} events)</span>
        <span className="text-xs text-zbrain-muted">raw events from each stage</span>
      </button>
      {showLog && <ActivityLog events={events} />}

      <PreviewModal item={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

function ActivityHeader({
  pipe,
  pipelineId,
  onRetry,
}: {
  pipe: Pipeline | null;
  pipelineId: number;
  onRetry: () => void;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="text-xs uppercase tracking-wider text-zbrain-muted">Customer request</div>
          <h1 className="text-lg font-semibold mt-0.5">
            Activity <span className="text-zbrain-muted font-normal">#{pipelineId}</span>
          </h1>
          {pipe?.ccc_request?.request_number && pipe?.salesforce_case_id && (
            <div className="mt-2 inline-flex flex-wrap items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
              <span className="text-[11px] uppercase tracking-wider font-semibold text-emerald-800">Salesforce Case</span>
              <span className="text-[12.5px] font-semibold text-emerald-900 tabular-nums">
                {pipe.ccc_request.request_number}
              </span>
              {pipe.ccc_request.case_number && (
                <span className="text-[11px] text-emerald-700">Case#&nbsp;{pipe.ccc_request.case_number}</span>
              )}
              {pipe.ccc_request.track && <span className="text-[11px] text-emerald-700">· {pipe.ccc_request.track} track</span>}
              <span className="text-[11px] text-emerald-700">· resolved at Stage 3.0 · live from Salesforce</span>
              {(pipe as any)?.soa_sharepoint?.web_url ? null : null}
              <SalesforceLink caseId={pipe.salesforce_case_id} />
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-2">
            <StatusPill status={pipe?.status || "running"} />
            {pipe?.intent && <IntentPill intent={pipe.intent} />}
            {pipe?.autonomy_tier && <TierPill tier={pipe.autonomy_tier} />}
          </div>
          {pipe?.confidence != null && (
            <div className="w-44">
              <ConfidenceBar value={pipe.confidence} />
            </div>
          )}
          {pipe?.status === "error" && (
            <button onClick={onRetry} className="btn-secondary text-xs">
              ↻ Retry from start
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// NextStepBanner — a plain-English "where is this case now and what's next"
// strip rendered directly under the activity header.
//
// The detailed substep events on each stage card tell the engineering story.
// The functional CSR needs a single line: "This is parked at AIOA waiting
// for the external validator. The validator timed out at 19:06 UTC. You
// can re-issue the call from the AIOA queue."
//
// One component, one switch on pipe.status. Pulls live aioa_requests state
// when the pipeline is awaiting_aioa so the banner shows the REAL backend
// state (queued / sent / response_received / timed_out / processed), not
// just the cached pipeline-level field which can lag.
// ─────────────────────────────────────────────────────────────────────────
type AIOARequestRow = {
  id: number;
  correlation_id: string;
  pipeline_id: number;
  provider_name: string | null;
  status: string;
  decision: "PASS" | "FAIL" | null;
  retry_count: number;
  created_at: string | null;
  sent_at: string | null;
  response_received_at: string | null;
  processed_at: string | null;
  last_error: string | null;
};

function CloseOutSummaryCard({ pipe, events }: { pipe: Pipeline; events: TraceEvent[] }) {
  // Surface a "Case closed" summary card at the top of the Trace page when
  // the pipeline finished as a duplicate handoff (Stage 4 short-circuit) or
  // any other completed terminal status. The card carries the LLM-generated
  // closeout_summary so the operator sees what happened in plain language
  // without having to read the whole trace.
  const execution = (pipe.execution || {}) as any;
  const resultStatus = execution.status || "";
  const isDuplicateHandoff = resultStatus === "duplicate_handed_off";
  const summary: string | null = execution.closeout_summary || null;
  if (!isDuplicateHandoff || pipe.status !== "completed") return null;

  const existingCaseNumber = execution.existing_case_number || null;
  const existingCaseId = execution.existing_case_id || pipe.salesforce_case_id || null;
  const caseUrl = execution.salesforce_case_url || null;
  const action = execution.action || "attach_to_existing_case";
  const llmConfidence = execution.llm_confidence;

  return (
    <div className="card border-emerald-200 bg-emerald-50/50 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-emerald-700 text-lg font-semibold">Case closed</span>
            <span className="pill bg-emerald-100 text-emerald-800 border border-emerald-200 text-[11px] font-mono">
              status={resultStatus} · action={action}
            </span>
            {typeof llmConfidence === "number" && (
              <span className="pill bg-white text-emerald-700 border border-emerald-200 text-[11px]">
                LLM match {(llmConfidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          {summary && (
            <p className="mt-2.5 text-sm text-zbrain-ink leading-relaxed">{summary}</p>
          )}
          {existingCaseNumber && (
            <div className="mt-3 text-xs text-zbrain-muted flex items-center gap-2 flex-wrap">
              <span>Attached to Case</span>
              {caseUrl ? (
                <a
                  href={caseUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="pill bg-white text-emerald-700 border border-emerald-300 hover:bg-emerald-100 font-mono"
                >
                  {existingCaseNumber}
                </a>
              ) : (
                <span className="pill bg-white text-emerald-700 border border-emerald-300 font-mono">
                  {existingCaseNumber}
                </span>
              )}
              {existingCaseId && (
                <span className="text-[10px] text-zbrain-muted/70 font-mono">{existingCaseId}</span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NextStepBanner({
  pipe,
  pipelineId,
  events,
}: {
  pipe: Pipeline;
  pipelineId: number;
  events: TraceEvent[];
}) {
  const [aioa, setAioa] = useState<AIOARequestRow | null>(null);

  // Live AIOA state lookup — only fires when the pipeline is parked at AIOA.
  useEffect(() => {
    if (pipe?.status !== "awaiting_aioa") {
      setAioa(null);
      return;
    }
    let cancel = false;
    const load = () => {
      fetch(`/api/aioa/requests?pipeline_id=${pipelineId}&limit=1`)
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          if (cancel) return;
          const row = (j?.items || [])[0] || null;
          setAioa(row);
        })
        .catch(() => undefined);
    };
    load();
    const id = setInterval(load, 8000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [pipe?.status, pipelineId]);

  const status = pipe?.status || "running";

  // Helpers to mine the trace for relevant signal events.
  const aioaQueuedEv = events.find(
    (e) => e.stage === "decide" && e.kind === "substep_done" && (e.data as any)?.substep === "3.0.c",
  );
  const slaEv = events.find(
    (e) => e.stage === "decide" && e.kind === "substep_done" && (e.data as any)?.substep === "3.0e",
  );
  const slaDeadlineRaw =
    (slaEv?.data as any)?.deadline || (slaEv?.data as any)?.close_by || (slaEv?.data as any)?.target;
  const slaDeadline = slaDeadlineRaw ? new Date(slaDeadlineRaw) : null;
  const correlation = aioa?.correlation_id || (aioaQueuedEv?.data as any)?.correlation_id || null;
  const provider = aioa?.provider_name || (aioaQueuedEv?.data as any)?.provider || "AIOA";

  // Build per-state copy.
  let tone: "amber" | "rose" | "emerald" | "sky" | "slate" = "slate";
  let title = "";
  let body: React.ReactNode = null;
  let metaRows: { label: string; value: React.ReactNode }[] = [];
  let cta: { href: string; label: string } | null = null;

  if (status === "completed") {
    tone = "emerald";
    title = "Closed · pipeline completed";
    body = (
      <>
        Every stage finished successfully. Audit chain hash for this case is sealed and the Salesforce
        Case is marked closed. Nothing more is required from the CSR.
      </>
    );
  } else if (status === "discarded") {
    tone = "slate";
    title = "Discarded at intake";
    body = <>The spam/phishing screen rejected this email before it reached the LLM. No agent action was attempted.</>;
  } else if (status === "error") {
    tone = "rose";
    title = "Errored · CSR action required";
    body = <>The pipeline halted with an unrecoverable error. Open the Errors view for the root cause and the retry option.</>;
    cta = { href: "/errors", label: "Open Errors view →" };
  } else if (status === "running") {
    tone = "sky";
    title = "In flight";
    body = <>The pipeline is actively running. Stages will populate below as each one completes.</>;
  } else if (status === "awaiting_one_click") {
    tone = "sky";
    title = "Awaiting one-click approval";
    body = (
      <>
        Decide chose <strong>L3 one-click</strong>. The proposed action is staged but will not execute until a
        CSR reviews and clicks Approve in the HITL queue.
      </>
    );
    cta = { href: `/hitl?pipeline=${pipelineId}`, label: "Open HITL queue →" };
  } else if (status === "awaiting_hitl") {
    tone = "amber";
    title = "Parked for HITL review";
    body = (
      <>
        Decide tiered this case <strong>L2 (full review)</strong>. A CSR needs to review the extracted data
        and proposed action before anything is written back to the systems of record.
      </>
    );
    cta = { href: `/hitl?pipeline=${pipelineId}`, label: "Open HITL queue →" };
  } else if (status === "awaiting_aioa") {
    // Branch on the LIVE AIOA state.
    const aioaState = aioa?.status || "queued";
    if (aioaState === "timed_out") {
      tone = "rose";
      title = "AIOA timed out · CSR clarification needed";
      body = (
        <>
          The external Order Acceptance validator did not respond within the configured window. The pipeline
          is parked. The timeout sweep will roll this to HITL for a CSR to issue a clarification reply, or
          you can re-issue the call from the AIOA queue.
        </>
      );
    } else if (aioaState === "response_received" || aioaState === "processed") {
      tone = "sky";
      title = "AIOA responded · post-AIOA action in flight";
      body = (
        <>
          The validator returned a {aioa?.decision || "decision"}. The post-AIOA action will run shortly and
          the pipeline will resume.
        </>
      );
    } else {
      tone = "amber";
      title = "Parked: waiting for AIOA validation";
      body = (
        <>
          Decide routed this case to the external Order Acceptance validator. Execute and Communicate will
          start automatically when the callback returns <strong>PASS</strong>; a <strong>FAIL</strong> or a
          timeout sends the case to HITL with a CSR clarification draft attached.
        </>
      );
    }
    metaRows = [
      { label: "Validator", value: <span className="font-mono">{provider}</span> },
      correlation
        ? { label: "Correlation", value: <span className="font-mono">{correlation}</span> }
        : null,
      aioa?.sent_at
        ? { label: "Sent at", value: <span>{new Date(aioa.sent_at).toLocaleString()}</span> }
        : aioa?.created_at
        ? { label: "Queued at", value: <span>{new Date(aioa.created_at).toLocaleString()}</span> }
        : null,
      slaDeadline
        ? { label: "SLA", value: <span>{slaDeadline.toLocaleString()}</span> }
        : null,
      aioa?.retry_count
        ? { label: "Retries", value: <span className="tabular-nums">{aioa.retry_count}</span> }
        : null,
    ].filter(Boolean) as any;
    cta = { href: `/aioa?pipeline_id=${pipelineId}`, label: "Open AIOA queue →" };
  } else {
    tone = "slate";
    title = `Status: ${status}`;
    body = <>Live status; refer to the stage cards below.</>;
  }

  const toneStyles: Record<string, string> = {
    amber: "border-amber-200 bg-amber-50/70",
    rose: "border-rose-200 bg-rose-50/70",
    emerald: "border-emerald-200 bg-emerald-50/70",
    sky: "border-sky-200 bg-sky-50/70",
    slate: "border-zbrain-divider bg-zbrain-surface/60",
  };
  const dotStyles: Record<string, string> = {
    amber: "bg-amber-500",
    rose: "bg-rose-500",
    emerald: "bg-emerald-500",
    sky: "bg-sky-500",
    slate: "bg-slate-400",
  };
  const titleStyles: Record<string, string> = {
    amber: "text-amber-900",
    rose: "text-rose-900",
    emerald: "text-emerald-900",
    sky: "text-sky-900",
    slate: "text-zbrain-ink",
  };

  return (
    <div className={`card p-4 border-l-4 ${toneStyles[tone]}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-1 inline-flex h-2 w-2 rounded-full ${dotStyles[tone]} ${status.startsWith("awaiting") || status === "running" ? "animate-pulse" : ""}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-3 flex-wrap">
            <h2 className={`text-[13.5px] font-semibold ${titleStyles[tone]}`}>{title}</h2>
            {cta && (
              <Link
                to={cta.href}
                className="text-[11.5px] font-semibold text-zbrain hover:underline whitespace-nowrap"
              >
                {cta.label}
              </Link>
            )}
          </div>
          <p className="text-[12.5px] text-zbrain-ink/85 mt-1 leading-snug max-w-3xl">{body}</p>
          {metaRows.length > 0 && (
            <div className="mt-2.5 grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1.5">
              {metaRows.map((r, i) => (
                <div key={i} className="text-[11px]">
                  <div className="text-zbrain-muted uppercase tracking-wider text-[10px] font-semibold">{r.label}</div>
                  <div className="text-zbrain-ink mt-0.5">{r.value}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// === v1.1 TRACE-TERMINAL START === Redirect banner for terminal-intent pipelines.
// Shown when a pre-AI Outlook rule matched and short-circuited the pipeline.
// Makes it visually obvious that the mail trail ends here, with the rule and the destination.
function RedirectBanner({
  ruleMatch,
  redirect,
  intent,
}: {
  ruleMatch: TraceEvent;
  redirect: TraceEvent | undefined;
  intent: string | null | undefined;
}) {
  const ruleLabel = (ruleMatch.data as any)?.rule_label || (ruleMatch.data as any)?.rule_key || ruleMatch.message;
  const matchedIntent = (ruleMatch.data as any)?.intent || intent;
  const explicitRedirect = (ruleMatch.data as any)?.redirect_to as string | null | undefined;
  const redirectTarget =
    explicitRedirect ||
    ((redirect?.message || "").match(/forward to ([\w.@+-]+)/i)?.[1] ?? null);
  const severity = (ruleMatch.data as any)?.severity as string | undefined;
  const intentChip =
    matchedIntent ? (
      <span className="pill bg-violet-100 text-violet-800 uppercase tracking-wide text-[10px] font-semibold">
        {matchedIntent}
      </span>
    ) : null;
  return (
    <div className="card overflow-hidden border-violet-300/70 bg-violet-50/40">
      <div className="px-5 py-4 flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-violet-900">
            <span className="text-base">↪</span>
            <span className="text-sm font-semibold">Redirect &middot; mail trail ends here</span>
            {intentChip}
            {severity === "hard_block" && (
              <span className="pill bg-rose-100 text-rose-800 text-[10px] font-semibold uppercase">hard block</span>
            )}
          </div>
          <div className="text-sm text-zbrain-ink/85 mt-1.5">
            <span className="text-zbrain-muted">Knowledge-base rule:</span>{" "}
            <span className="font-medium">{ruleLabel}</span>
          </div>
          {redirectTarget && (
            <div className="text-sm text-zbrain-ink/85 mt-1">
              <span className="text-zbrain-muted">Would forward to:</span>{" "}
              <code className="font-mono text-[13px] bg-white border border-violet-200/60 rounded px-1.5 py-0.5">
                {redirectTarget}
              </code>
            </div>
          )}
          <div className="text-xs text-zbrain-muted mt-2 italic">
            Stages 2 to 5 are intentionally skipped for redirect classes (the pipeline does not extract,
            decide, execute, or reply on these). The redirect is logged for audit; no email is sent (demo lock).
          </div>
        </div>
      </div>
    </div>
  );
}
// === v1.1 TRACE-TERMINAL END ===

function InboundEmailCard({
  pipe,
  setPreview,
}: {
  pipe: Pipeline | null;
  setPreview: (p: PreviewItem | null) => void;
}) {
  // === v1.1 TRACE-EMAIL-BIGGER === only treat as 'long' beyond a higher threshold so most
  // operational emails (KSO, Brazil Tax, Undeliverable, status enquiries, short replies)
  // render in full without a collapse control.
  const [expanded, setExpanded] = useState(false);
  if (!pipe) return null;
  const body = pipe.email_body || "";
  const isLong = body.length > 1600 || body.split("\n").length > 24;
  const received = pipe.email_received_at ? new Date(pipe.email_received_at) : null;

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-zbrain-divider bg-zbrain-surface flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs uppercase tracking-wider text-zbrain-muted shrink-0">Inbound email</span>
        </div>
        {pipe.email_id != null && (
          <Link className="text-xs text-zbrain hover:underline shrink-0" to="/inbox">
            Open in inbox ↗
          </Link>
        )}
      </div>
      <div className="px-5 py-4">
        <div className="text-base font-semibold text-zbrain-ink">
          {pipe.email_subject || "(no subject)"}
        </div>
        <div className="text-xs text-zbrain-muted mt-1 flex items-center gap-3 flex-wrap">
          {pipe.email_from && (
            <span>
              From <span className="text-zbrain-ink font-medium">{pipe.email_from}</span>
            </span>
          )}
          {received && <span>· Received {received.toLocaleString()}</span>}
        </div>
        {body && (
          <>
            <div
              className={`mt-3 text-[14px] leading-[1.55] whitespace-pre-wrap text-zbrain-ink/90 bg-white border border-zbrain-divider rounded-lg p-4 font-[ui-sans-serif,system-ui] ${
                expanded || !isLong ? "" : "max-h-96 overflow-hidden relative"
              }`}
            >
              {body}
              {!expanded && isLong && (
                <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-white to-transparent" />
              )}
            </div>
            {isLong && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="text-xs text-zbrain hover:underline mt-2"
              >
                {expanded ? "Collapse" : "Show full message"}
              </button>
            )}
          </>
        )}
        {(pipe.email_attachments || []).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {(pipe.email_attachments || []).map((n) => {
              const name = typeof n === "string" ? n : (n as any).name || "attachment";
              return (
                <button
                  key={name}
                  onClick={() => setPreview({ name, url: attachmentUrl(n as any) })}
                  className="pill bg-slate-100 text-slate-700 hover:bg-zbrain-50 hover:text-zbrain"
                >
                  {name}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusGlyph({ s }: { s: SubStepStatus }) {
  if (s === "done") return <span className="text-emerald-600 font-semibold w-4 text-center inline-block">✓</span>;
  if (s === "error") return <span className="text-rose-600 font-semibold w-4 text-center inline-block">✗</span>;
  if (s === "skipped")
    return <span className="text-slate-400 font-semibold w-4 text-center inline-block">⊘</span>;
  if (s === "running")
    return <span className="text-blue-600 font-semibold w-4 text-center inline-block animate-pulse">…</span>;
  return <span className="text-slate-300 font-semibold w-4 text-center inline-block">○</span>;
}

function StageStatusPill({ status, ms }: { status: StageStatus["status"]; ms?: number }) {
  // === v1.1 TRACE-TERMINAL === added 'skipped' styling
  const cls =
    status === "done"
      ? "bg-emerald-100 text-emerald-800"
      : status === "running"
      ? "bg-blue-100 text-blue-800"
      : status === "error"
      ? "bg-rose-100 text-rose-800"
      : status === "skipped"
      ? "bg-slate-100 text-slate-500 italic"
      : status === "deferred"
      ? "bg-amber-100 text-amber-800 italic"
      : "bg-slate-100 text-slate-600";
  return (
    <span className="flex items-center gap-2">
      <span className={`pill ${cls}`}>{status}</span>
      {ms != null && <span className="text-xs text-zbrain-muted tabular-nums">{formatMs(ms)}</span>}
    </span>
  );
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 1000)} s`;
}

/** Wrapper card laying out a stage with its sub-step list, result line, and collapsible details. */
function StageCardShell({
  num,
  title,
  state,
  subSteps,
  resultLine,
  rightAction,
  toolbeltEvents,
  toolbeltStageKeys,
  notes,
  rawData,
  pipelineId,
  feedbackKey,
  feedbackSnapshot,
  extraSections,
}: {
  num: number;
  title: string;
  state?: StageStatus;
  subSteps: SubStep[];
  resultLine: string | null;
  rightAction?: React.ReactNode;
  toolbeltEvents: TraceEvent[];
  toolbeltStageKeys: string[];
  notes: string[];
  rawData: any;
  pipelineId?: number;
  feedbackKey?: string;
  feedbackSnapshot?: any;
  extraSections?: React.ReactNode;
}) {
  const status = state?.status || "pending";
  const borderTone =
    status === "done"
      ? "border-l-emerald-400"
      : status === "error"
      ? "border-l-rose-400"
      : status === "running"
      ? "border-l-sky-400"
      : status === "deferred"
      ? "border-l-amber-400"
      : "border-l-slate-200";

  const showFeedback =
    pipelineId != null && feedbackKey && (status === "done" || status === "error");

  return (
    <div className={`card overflow-hidden border-l-4 ${borderTone}`}>
      <div className="px-4 py-3 border-b border-zbrain-divider bg-zbrain-surface flex items-center gap-3">
        <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-mono">Stage {num}</div>
        <div className="text-sm font-semibold flex-1">{title}</div>
        {rightAction}
        <StageStatusPill status={status} ms={state?.ms} />
      </div>
      <div className="p-4 space-y-3">
        <SubStepDetailList steps={subSteps} />
        <div className="border-t border-zbrain-divider pt-3 text-xs">
          <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mr-2">
            Result
          </span>
          <span className="font-mono text-zbrain-ink">{resultLine || "-"}</span>
        </div>
        {extraSections}
        <CollapsibleSection
          label={`Agent toolbelt (${toolbeltEvents.filter((e) => e.kind === "tool_start").length} tool calls)`}
        >
          <ToolBeltSection events={toolbeltEvents} stageKeys={toolbeltStageKeys} />
        </CollapsibleSection>
        {notes.length > 0 && (
          <CollapsibleSection label={`Normalizer / guardrail notes (${notes.length})`}>
            <div className="flex flex-wrap gap-1.5 px-1">
              {notes.map((n, i) => (
                <span
                  key={i}
                  className="pill bg-amber-50 text-amber-800 border border-amber-200 text-[10px]"
                >
                  {n}
                </span>
              ))}
            </div>
          </CollapsibleSection>
        )}
        {rawData && Object.keys(rawData).length > 0 && (
          <CollapsibleSection label="Debug details (support team)">
            <pre className="text-[11px] bg-slate-50 border border-zbrain-divider rounded p-3 max-h-80 overflow-auto whitespace-pre-wrap mx-1">
              {JSON.stringify(rawData, null, 2)}
            </pre>
          </CollapsibleSection>
        )}
        {showFeedback && (
          <StageFeedback
            pipelineId={pipelineId!}
            stage={feedbackKey!}
            snapshot={feedbackSnapshot ?? rawData}
          />
        )}
      </div>
    </div>
  );
}

function CollapsibleSection({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="btn-secondary text-xs w-full flex items-center justify-between"
      >
        <span>{label}</span>
        <span className="text-zbrain-muted">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** Stage nav strip — 6 clickable cards at the top of the activity page.
 *
 * The selected card gets a primary ring. The parked card (where the pipeline
 * is currently held — awaiting AIOA / HITL / one-click / errored) gets an
 * amber outline + a pulsing "PARKED HERE" badge so a CSR scanning the page
 * sees at-a-glance where things stopped. The parked card is also the
 * default selection on first load via the auto-select logic upstream. */
function StageNavStrip({
  stages,
  stageState,
  selected,
  parked,
  onSelect,
}: {
  stages: { key: StageKey; label: string; num: number }[];
  stageState: Record<string, StageStatus>;
  selected: StageKey;
  parked: StageKey | null;
  onSelect: (k: StageKey) => void;
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
      {stages.map((s) => {
        const st = stageState[s.key]?.status || "pending";
        const ms = stageState[s.key]?.ms;
        const isSelected = selected === s.key;
        const isParked = parked === s.key;
        const baseTone =
          st === "done" ? "border-emerald-300 bg-emerald-50/50"
          : st === "error" ? "border-rose-300 bg-rose-50/50"
          : st === "running" ? "border-sky-300 bg-sky-50/50"
          : "border-zbrain-divider bg-white";
        // Parked overrides the base tone with an amber halo so the eye lands here first.
        const tone = isParked
          ? "border-amber-400 bg-amber-50/80 shadow-[0_0_0_3px_rgba(245,158,11,0.18)]"
          : baseTone;
        const ring = isSelected ? "ring-2 ring-zbrain ring-offset-1" : "";
        return (
          <button
            key={s.key}
            onClick={() => onSelect(s.key)}
            className={`relative text-left rounded-md border p-3 transition-all hover:border-zbrain ${tone} ${ring}`}
          >
            {isParked && (
              <span
                className="absolute -top-2 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-500 text-white text-[9px] font-bold uppercase tracking-wider shadow-sm"
                title="The pipeline is currently held here. The Next-step banner above tells you what it's waiting for."
              >
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-white animate-pulse" />
                Parked here
              </span>
            )}
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-mono">
                Stage {s.num}
              </span>
              <StageStatusPill status={st} ms={ms} />
            </div>
            <div
              className="text-sm font-semibold mt-1 text-zbrain-ink leading-tight break-words"
              title={s.label}
              style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as any, overflow: "hidden", minHeight: "2.5em" }}
            >
              {s.label}
            </div>
            <div className="text-[11px] mt-1">
              {isParked ? (
                <span className="text-amber-800 font-semibold">held: see banner above</span>
              ) : st === "done" ? (
                <span className="text-zbrain-muted">click to inspect</span>
              ) : st === "running" ? (
                <span className="text-sky-700">running…</span>
              ) : st === "error" ? (
                <span className="text-rose-700">click to debug</span>
              ) : (
                <span className="text-zbrain-muted">pending</span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}


/** Drill-down sub-step list — each row expandable showing input / processing / output / prompts / KB / raw. */
function SubStepDetailList({ steps }: { steps: SubStep[] }) {
  return (
    <div className="space-y-2">
      {steps.map((s) => (
        <SubStepDetailCard key={s.num} step={s} />
      ))}
    </div>
  );
}

function SubStepDetailCard({ step }: { step: SubStep }) {
  const [open, setOpen] = useState(false);
  const tone =
    step.status === "done" ? "border-emerald-200"
    : step.status === "error" ? "border-rose-200"
    : step.status === "running" ? "border-sky-200"
    : step.status === "skipped" ? "border-slate-200 bg-slate-50/40"
    : "border-zbrain-divider";
  const hasDetails =
    !!step.inputPreview ||
    !!step.processing ||
    !!step.promptSystem ||
    !!step.rawResponse ||
    (step.rulesEvaluated && step.rulesEvaluated.length > 0) ||
    (step.kbRulesUsed && step.kbRulesUsed.length > 0) ||
    (step.outputFields && step.outputFields.length > 0) ||
    (step.attachmentsBreakdown && step.attachmentsBreakdown.length > 0) ||
    !!step.rawData;

  return (
    <div className={`border rounded-md overflow-hidden ${tone}`}>
      <button
        onClick={() => hasDetails && setOpen((v) => !v)}
        className={`w-full flex items-start gap-3 px-3 py-2 text-left ${hasDetails ? "cursor-pointer hover:bg-zbrain-50/40" : "cursor-default"}`}
      >
        <span className="mt-px"><StatusGlyph s={step.status} /></span>
        <span className="font-mono text-[11px] text-zbrain-muted tabular-nums w-8 shrink-0 mt-px">
          {step.num}
        </span>
        <div className="flex-1 min-w-0">
          <div className="font-mono text-[12px] text-zbrain-ink truncate" title={step.name}>
            {step.name}
          </div>
          {step.result && (
            <div className="text-xs text-zbrain-ink/80 mt-0.5 truncate" title={step.result}>
              {step.result}
            </div>
          )}
        </div>
        <span className="text-[11px] text-zbrain-muted tabular-nums whitespace-nowrap shrink-0 mt-px">
          {step.ms != null ? formatMs(step.ms) : ""}
        </span>
        {hasDetails && (
          <span className="text-zbrain-muted text-xs mt-px shrink-0">{open ? "▾" : "▸"}</span>
        )}
      </button>
      {open && hasDetails && <SubStepDetail step={step} />}
    </div>
  );
}

function SubStepDetail({ step }: { step: SubStep }) {
  const hasOutput =
    (step.outputFields && step.outputFields.length > 0) ||
    !!step.outputPreview ||
    (step.rulesEvaluated && step.rulesEvaluated.length > 0);
  const hasActivities =
    !!step.promptSystem ||
    !!step.promptUser ||
    !!step.rawResponse ||
    (step.kbRulesUsed && step.kbRulesUsed.length > 0) ||
    !!step.rawData;

  return (
    <div className="border-t border-zbrain-divider px-3 py-3 space-y-4 bg-slate-50/30">
      <SectionLabel>Input</SectionLabel>
      <div className="space-y-2">
        {step.processing && (
          <div className="text-xs text-zbrain-ink/90 flex flex-wrap gap-x-4 gap-y-1">
            <span><span className="text-zbrain-muted">Method:</span> <span className="font-mono">{step.processing}</span></span>
            {step.provider && (
              <span><span className="text-zbrain-muted">Provider:</span> <span className="font-mono">{step.provider}</span></span>
            )}
          </div>
        )}
        {step.inputPreview ? (
          <pre className="text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 text-zbrain-ink/90 max-h-40 overflow-auto">
            {step.inputPreview}
          </pre>
        ) : (
          <div className="text-xs text-zbrain-muted italic">no input preview captured</div>
        )}
      </div>

      <SectionLabel>Output</SectionLabel>
      {hasOutput ? (
        <div className="space-y-2">
          {step.outputFields && step.outputFields.length > 0 && (
            <div className="bg-white border border-zbrain-divider rounded p-3 text-xs space-y-1.5">
              {step.outputFields.map((f, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="text-zbrain-muted shrink-0 w-32">{f.label}</span>
                  <span
                    className={`flex-1 ${f.mono ? "font-mono" : ""} ${f.long ? "whitespace-pre-wrap" : ""} text-zbrain-ink`}
                  >
                    {f.value === null || f.value === undefined || f.value === ""
                      ? <span className="text-zbrain-muted italic">-</span>
                      : f.link
                      ? <a href={f.link} target="_blank" rel="noreferrer" className="text-zbrain hover:underline break-all">{String(f.value)}</a>
                      : typeof f.value === "boolean"
                      ? (f.value ? "true" : "false")
                      : Array.isArray(f.value)
                      ? f.value.join(", ")
                      : String(f.value)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {step.outputPreview && (
            <pre className="text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 text-zbrain-ink/90 max-h-40 overflow-auto">
              {step.outputPreview}
            </pre>
          )}
          {step.rulesEvaluated && step.rulesEvaluated.length > 0 && (
            <RulesEvaluatedTable rules={step.rulesEvaluated} />
          )}
          {step.attachmentsBreakdown && step.attachmentsBreakdown.length > 0 && (
            <AttachmentsBreakdown items={step.attachmentsBreakdown} />
          )}
        </div>
      ) : (
        <div className="text-xs text-zbrain-muted italic">no output recorded</div>
      )}

      {hasActivities && (
        <>
          <SectionLabel>Activities (behind the scenes)</SectionLabel>
          <div className="space-y-1.5">
            {step.kbRulesUsed && step.kbRulesUsed.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zbrain hover:underline">
                  KB consulted: {(step.kbNamespaces || []).join(", ") || "(no namespace)"} · {step.kbRulesUsed.length} rule{step.kbRulesUsed.length === 1 ? "" : "s"}
                </summary>
                <div className="mt-1 flex flex-wrap gap-1 px-1">
                  {step.kbRulesUsed.map((k) => (
                    <span key={k} className="pill bg-sky-50 text-sky-700 border border-sky-200 font-mono text-[10px]">
                      {k}
                    </span>
                  ))}
                </div>
              </details>
            )}
            {step.promptSystem && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zbrain hover:underline">
                  View LLM system prompt ({step.promptSystem.length} chars)
                </summary>
                <pre className="mt-1 text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 max-h-64 overflow-auto">
                  {step.promptSystem}
                </pre>
              </details>
            )}
            {step.promptUser && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zbrain hover:underline">
                  View LLM user prompt ({step.promptUser.length} chars)
                </summary>
                <pre className="mt-1 text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 max-h-64 overflow-auto">
                  {step.promptUser}
                </pre>
              </details>
            )}
            {step.rawResponse && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zbrain hover:underline">
                  View LLM raw response ({step.rawResponse.length} chars)
                </summary>
                <pre className="mt-1 text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 max-h-64 overflow-auto">
                  {step.rawResponse}
                </pre>
              </details>
            )}
            {step.rawData && (
              <details className="text-xs">
                <summary className="cursor-pointer text-zbrain hover:underline">
                  View raw JSON for this sub-step
                </summary>
                <pre className="mt-1 text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 max-h-64 overflow-auto">
                  {JSON.stringify(step.rawData, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function RulesEvaluatedTable({ rules }: { rules: any[] }) {
  const matched = rules.filter((r) => r.matched);
  return (
    <div className="bg-white border border-zbrain-divider rounded p-2">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1.5">
        Rules evaluated ({rules.length}) · {matched.length} matched
      </div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-zbrain-muted text-left border-b border-zbrain-divider/60">
            <th className="font-medium pr-2 py-1">ID / category</th>
            <th className="font-medium pr-2 py-1">Description</th>
            <th className="font-medium pr-2 py-1">Pattern / kind</th>
            <th className="font-medium pr-2 py-1">Severity</th>
            <th className="font-medium pr-2 py-1">Matched</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r: any, i: number) => {
            const id = r.id || r.rule || r.label || "-";
            const desc = r.description || "";
            const pattern = r.regex || r.pattern || r.kind || r.scope || "";
            const sev = r.severity || r.tier || "";
            const cat = r.category || r.language || "";
            return (
              <tr
                key={i}
                className={`border-t border-zbrain-divider/40 ${r.matched ? "bg-amber-50/40" : ""}`}
              >
                <td className="pr-2 py-1 align-top">
                  <span className="font-mono text-[10px] text-zbrain-ink">{id}</span>
                  {cat && (
                    <div className="text-[9px] text-zbrain-muted font-mono mt-0.5">{cat}</div>
                  )}
                </td>
                <td className="pr-2 py-1 text-zbrain-ink/80 align-top">{desc}</td>
                <td
                  className="pr-2 py-1 font-mono text-zbrain-muted align-top truncate max-w-[200px]"
                  title={pattern}
                >
                  {String(pattern).slice(0, 60)}
                  {String(pattern).length > 60 ? "…" : ""}
                </td>
                <td className="pr-2 py-1 align-top text-[10px] text-zbrain-muted">{sev}</td>
                <td className="pr-2 py-1 align-top">
                  {r.matched ? (
                    <span className="pill bg-amber-50 text-amber-700 border border-amber-200 text-[10px]">
                      match{typeof r.count === "number" ? ` ×${r.count}` : ""}
                    </span>
                  ) : (
                    <span className="pill bg-slate-50 text-slate-500 border border-slate-200 text-[10px]">
                      no
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AttachmentsBreakdown({
  items,
}: {
  items: NonNullable<SubStep["attachmentsBreakdown"]>;
}) {
  return (
    <div className="bg-white border border-zbrain-divider rounded p-2 space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">
        Per-attachment extraction · {items.length} file{items.length === 1 ? "" : "s"}
      </div>
      {items.map((it, i) => (
        <details key={i} className="border border-zbrain-divider/60 rounded">
          <summary className="cursor-pointer px-2 py-1.5 flex items-center gap-3 text-[11px] hover:bg-slate-50">
            <span className="font-mono text-zbrain-ink truncate">{it.filename || `(file ${i + 1})`}</span>
            <span className="text-zbrain-muted text-[10px]">
              {(it.char_count ?? 0).toLocaleString()} chars
            </span>
            {it.max_pages_requested && (
              <span className="pill bg-slate-50 text-slate-600 border border-slate-200 text-[9px]">
                {it.max_pages_requested}-page cap
              </span>
            )}
            <span className="ml-auto text-zbrain-muted font-mono text-[10px]">
              {(it.provider || "").slice(0, 40)}
            </span>
          </summary>
          <div className="px-2 py-2 border-t border-zbrain-divider/60 space-y-1.5 bg-slate-50/40">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px]">
              <span><span className="text-zbrain-muted">Provider:</span> <span className="font-mono">{it.provider || "-"}</span></span>
              <span><span className="text-zbrain-muted">Char count:</span> {(it.char_count ?? 0).toLocaleString()}</span>
              {it.page_count != null && (
                <span><span className="text-zbrain-muted">Pages:</span> {it.page_count}</span>
              )}
              {it.max_pages_requested != null && (
                <span><span className="text-zbrain-muted">Max pages requested:</span> {it.max_pages_requested}</span>
              )}
            </div>
            {it.text_preview ? (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">
                  Extracted text
                </div>
                <pre className="text-[11px] whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 max-h-56 overflow-auto">
                  {it.text_preview}
                </pre>
              </div>
            ) : (
              <div className="text-[11px] text-zbrain-muted italic">no text extracted</div>
            )}
            {it.notes && it.notes.length > 0 && (
              <div className="text-[10px] text-amber-700">
                {it.notes.map((n, j) => (
                  <div key={j}>· {n}</div>
                ))}
              </div>
            )}
          </div>
        </details>
      ))}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold border-b border-zbrain-divider/70 pb-1">
      {children}
    </div>
  );
}

function DetailBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">{label}</div>
      {children}
    </div>
  );
}


/** Vertical list of named sub-steps as the primary visual content of a stage card. */
function SubStepList({ steps }: { steps: SubStep[] }) {
  return (
    <div className="border border-zbrain-divider rounded-md overflow-hidden">
      {steps.map((s, i) => (
        <div
          key={s.num}
          className={`flex items-start gap-3 px-3 py-2 ${
            i > 0 ? "border-t border-zbrain-divider" : ""
          } ${s.status === "skipped" ? "bg-slate-50/50" : ""}`}
        >
          <StatusGlyph s={s.status} />
          <span className="font-mono text-[11px] text-zbrain-muted tabular-nums w-8 shrink-0 mt-px">
            {s.num}
          </span>
          <span className="font-mono text-[12px] text-zbrain-ink shrink-0 mt-px w-56 truncate" title={s.name}>
            {s.name}
          </span>
          <span className="text-xs text-zbrain-ink/80 flex-1 truncate" title={s.result || ""}>
            {s.result ? <>: {s.result}</> : ""}
          </span>
          <span className="text-[11px] text-zbrain-muted tabular-nums whitespace-nowrap shrink-0 mt-px">
            {s.ms != null ? formatMs(s.ms) : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

type ToolEvent = {
  name: string;
  stage: string;
  ok: boolean;
  duration_ms: number | null;
  data: any;
  error: any;
  notes: string[];
  kb_namespaces: string[];
  inputsSummary: any;
  startedAt: string | null;
  endedAt: string | null;
  pending: boolean;
};

function useStageToolEvents(events: TraceEvent[], stageKeys: string[]): ToolEvent[] {
  return useMemo(() => {
    const stageEvents = events.filter(
      (e) => stageKeys.includes(e.stage) && (e.kind === "tool_start" || e.kind === "tool_end")
    );
    const order: { tool: string; stage: string }[] = [];
    const starts: Record<string, TraceEvent> = {};
    const ends: Record<string, TraceEvent> = {};
    for (const ev of stageEvents) {
      const tool = ev.data?.tool;
      if (!tool) continue;
      const key = `${ev.stage}::${tool}`;
      if (ev.kind === "tool_start") {
        if (!(key in starts)) order.push({ tool, stage: ev.stage });
        starts[key] = ev;
      } else if (ev.kind === "tool_end") {
        ends[key] = ev;
      }
    }
    return order.map(({ tool, stage }) => {
      const key = `${stage}::${tool}`;
      const s = starts[key];
      const e = ends[key];
      const endData = e?.data || {};
      const startData = s?.data || {};
      const notesRaw = endData.notes;
      const notes: string[] = Array.isArray(notesRaw)
        ? notesRaw.map((n: any) => String(n))
        : notesRaw
        ? [String(notesRaw)]
        : [];
      const kbRaw = startData.kb_namespaces;
      const kb_namespaces: string[] = Array.isArray(kbRaw) ? kbRaw.map((n: any) => String(n)) : [];
      return {
        name: tool,
        stage,
        ok: e ? endData.ok !== false : true,
        duration_ms:
          typeof endData.duration_ms === "number"
            ? endData.duration_ms
            : e?.duration_ms ?? null,
        data: endData.data,
        error: endData.error,
        notes,
        kb_namespaces,
        inputsSummary: startData.inputs_summary,
        startedAt: s?.ts ?? null,
        endedAt: e?.ts ?? null,
        pending: !e,
      };
    });
  }, [events, stageKeys]);
}

function ToolBeltSection({ events, stageKeys }: { events: TraceEvent[]; stageKeys: string[] }) {
  const tools = useStageToolEvents(events, stageKeys);
  if (tools.length === 0) {
    return <div className="text-xs text-zbrain-muted italic px-1">No agent tool calls recorded.</div>;
  }
  return (
    <div className="border border-sky-200 rounded-lg overflow-hidden bg-white mx-1">
      <div className="px-3 py-2 bg-sky-50/60 border-b border-sky-200 flex items-center gap-2">
        <div className="text-[10px] uppercase tracking-wider text-sky-700 font-semibold">
          Agent toolbelt
        </div>
        <div className="text-[10px] text-sky-700/70">
          {tools.length} tool{tools.length === 1 ? "" : "s"} invoked
        </div>
      </div>
      <div className="divide-y divide-zbrain-divider">
        {tools.map((t, i) => (
          <ToolBeltRow key={`${t.stage}-${t.name}-${i}`} tool={t} />
        ))}
      </div>
      <ExecutionPath tools={tools} />
    </div>
  );
}

function ToolBeltRow({ tool }: { tool: ToolEvent }) {
  const [open, setOpen] = useState(false);
  const hasData = tool.data != null && (typeof tool.data !== "object" || Object.keys(tool.data).length > 0);
  const hasError = tool.error != null;
  const expandable = hasData || hasError;
  const statusIcon = tool.pending ? (
    <span className="text-[11px] text-blue-600 tabular-nums w-4 text-center">…</span>
  ) : tool.ok ? (
    <span className="text-emerald-600 font-semibold w-4 text-center">{"✓"}</span>
  ) : (
    <span className="text-rose-600 font-semibold w-4 text-center">{"✗"}</span>
  );

  return (
    <div>
      <button
        onClick={() => expandable && setOpen((v) => !v)}
        disabled={!expandable}
        className={`w-full px-3 py-2 flex items-center gap-2.5 text-xs ${
          expandable ? "hover:bg-zbrain-50/40 cursor-pointer" : "cursor-default"
        }`}
      >
        {statusIcon}
        <span className="font-mono text-sky-800 text-[12px]">{tool.name}</span>
        {tool.kb_namespaces.length > 0 && (
          <span className="flex items-center gap-1">
            {tool.kb_namespaces.map((ns) => (
              <span
                key={ns}
                className="pill bg-slate-100 text-slate-700 text-[10px]"
                title="Knowledge base namespace consulted"
              >
                kb:{ns}
              </span>
            ))}
          </span>
        )}
        {tool.notes.length > 0 && (
          <span className="flex items-center gap-1">
            {tool.notes.map((n, i) => (
              <span
                key={i}
                className="pill bg-amber-50 text-amber-800 border border-amber-200 text-[10px]"
                title="Guardrail / coercion note"
              >
                {n}
              </span>
            ))}
          </span>
        )}
        <span className="flex-1" />
        <span className="text-[10px] text-zbrain-muted tabular-nums whitespace-nowrap min-w-[3rem] text-right">
          {tool.duration_ms != null ? `${tool.duration_ms} ms` : tool.pending ? "running…" : "-"}
        </span>
        {expandable && (
          <span className="text-zbrain-muted text-[10px] w-3 text-center">{open ? "▾" : "▸"}</span>
        )}
      </button>
      {open && expandable && (
        <div className="px-3 py-2.5 bg-slate-50 border-t border-zbrain-divider">
          {hasError && (
            <div className="mb-2">
              <div className="text-[10px] uppercase tracking-wider text-rose-700 font-semibold mb-0.5">
                Error
              </div>
              <pre className="text-[11px] whitespace-pre-wrap font-mono bg-rose-50 border border-rose-200 rounded p-2 max-h-40 overflow-auto text-rose-900">
                {typeof tool.error === "string" ? tool.error : JSON.stringify(tool.error, null, 2)}
              </pre>
            </div>
          )}
          {hasData && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-0.5">
                Output payload
              </div>
              <pre className="text-[11px] leading-relaxed font-mono whitespace-pre-wrap bg-white border border-zbrain-divider rounded p-2 max-h-60 overflow-auto">
                {JSON.stringify(tool.data, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ExecutionPath({ tools }: { tools: ToolEvent[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="px-3 py-2 bg-zbrain-surface border-t border-zbrain-divider flex items-center gap-1.5 flex-wrap">
      <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mr-1">
        Stage execution path
      </span>
      {tools.map((t, i) => (
        <span key={`${t.name}-${i}`} className="flex items-center gap-1.5">
          <span className="font-mono text-[11px] text-sky-800">{t.name}</span>
          {i < tools.length - 1 && <span className="text-zbrain-muted text-[11px]">{"→"}</span>}
        </span>
      ))}
    </div>
  );
}

function findToolEnd(events: TraceEvent[], stage: string, toolName: string): TraceEvent | null {
  return (
    events.find(
      (e) => e.stage === stage && e.kind === "tool_end" && e.data?.tool === toolName
    ) || null
  );
}

function findAnyToolEnd(
  events: TraceEvent[],
  stages: string[],
  toolName: string
): TraceEvent | null {
  return (
    events.find(
      (e) => stages.includes(e.stage) && e.kind === "tool_end" && e.data?.tool === toolName
    ) || null
  );
}

function findToolEnds(
  events: TraceEvent[],
  stages: string[],
  toolNames: string[]
): TraceEvent[] {
  return events.filter(
    (e) =>
      stages.includes(e.stage) &&
      e.kind === "tool_end" &&
      toolNames.includes(e.data?.tool || "")
  );
}

function collectStageNotes(events: TraceEvent[], stageKeys: string[]): string[] {
  const notes: string[] = [];
  for (const ev of events) {
    if (!stageKeys.includes(ev.stage)) continue;
    if (ev.kind === "tool_end" && Array.isArray(ev.data?.notes)) {
      for (const n of ev.data.notes) notes.push(String(n));
    }
    if (ev.kind === "stage_end" && Array.isArray(ev.data?.guardrails)) {
      for (const g of ev.data.guardrails) notes.push(String(g));
    }
  }
  return notes;
}

function IntakeStageCard({
  pipe,
  state,
  events,
}: {
  pipe: Pipeline | null;
  state?: StageStatus;
  events: TraceEvent[];
}) {
  const intakeData = events.find((e) => e.stage === "intake" && e.kind === "result")?.data || {};
  const lang = intakeData.language || pipe?.language;
  const langConf = intakeData.language_confidence;
  const translatedBody = intakeData.translated_body;
  const intent = intakeData.intent || pipe?.intent;
  const intentConf = intakeData.intent_confidence;
  const spam = intakeData.spam;
  const spamSignals = intakeData.spam_signals;
  const attachmentsCount = (pipe?.email_attachments || []).length;

  const hasIntake = state?.status === "done" || state?.status === "running" || state?.status === "error";

  const detectLang = findToolEnd(events, "intake", "detect_language");
  const translate = findToolEnd(events, "intake", "translate_to_english");
  const classify = findToolEnd(events, "intake", "classify_intent");
  const heuristicSpam = findToolEnd(events, "intake", "detect_spam");
  const llmSpam = findToolEnd(events, "intake", "llm_spam_check");
  const lightExtractEvents = findToolEnds(events, ["intake"], ["azure_doc_intelligence", "vision_ocr", "read_attachment"]);

  // === v1.1 TRACE-TERMINAL START === Pre-AI Outlook rule check (deterministic KB) sub-step.
  const ruleMatchedEv = events.find((e) => e.stage === "pre_intake" && e.kind === "rule_matched");
  const redirectEv = events.find((e) => e.stage === "pre_intake" && e.kind === "redirect");
  const shortCircuitEv = events.find((e) => e.stage === "intake" && e.kind === "short_circuit");
  const preIntakeStarted = events.some((e) => e.stage === "pre_intake" && e.kind === "stage_start");
  const ruleEnded = events.some((e) => e.stage === "pre_intake" && e.kind === "stage_end");
  const isTerminal = !!ruleMatchedEv;
  const preAiStatus: SubStepStatus = isTerminal
    ? "done"
    : ruleEnded
    ? "skipped"
    : preIntakeStarted
    ? "running"
    : "pending";
  // === v1.1 TRACE-TERMINAL END ===

  // === v1.1 TRACE-TERMINAL === when a pre-AI rule short-circuits, the LLM sub-steps below do not run.
  const langStatus: SubStepStatus = !hasIntake
    ? "pending"
    : isTerminal
    ? "skipped"
    : detectLang
    ? detectLang.data?.ok === false
      ? "error"
      : "done"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const translateStatus: SubStepStatus = !hasIntake
    ? "pending"
    : isTerminal
    ? "skipped"
    : !lang || lang === "en"
    ? "skipped"
    : translatedBody
    ? "done"
    : translate
    ? translate.data?.ok === false
      ? "error"
      : "done"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const intentStatus: SubStepStatus = !hasIntake
    ? "pending"
    : isTerminal
    ? "done"
    : classify
    ? classify.data?.ok === false
      ? "error"
      : "done"
    : intent
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const heuristicSpamStatus: SubStepStatus = !hasIntake
    ? "pending"
    : isTerminal
    ? "skipped"
    : heuristicSpam
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const lightExtractStatus: SubStepStatus = !hasIntake
    ? "pending"
    : isTerminal
    ? "skipped"
    : attachmentsCount === 0
    ? "skipped"
    : lightExtractEvents.length > 0
    ? "done"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const llmSpamStatus: SubStepStatus = !hasIntake
    ? "pending"
    : isTerminal
    ? "skipped"
    : llmSpam
    ? llmSpam.data?.ok === false
      ? "error"
      : "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  // The Salesforce Case is NOT created here anymore — Stage 3 owns the
  // lookup-or-create resolution once intake + extract have populated the
  // fields. See the "3.0 CCC Request resolution" substep on the Decide card.

  const subSteps: SubStep[] = [
    {
      num: "1.1",
      name: "Receive inbound communication",
      status: hasIntake ? "done" : "pending",
      result: pipe
        ? `email body${attachmentsCount > 0 ? ` + ${attachmentsCount} attachment${attachmentsCount === 1 ? "" : "s"}` : ""}`
        : undefined,
      processing: "Passthrough. IMAP-poller ingestion, no transformation at this step (input == output)",
      provider: "Internal IMAP poller",
      inputPreview: pipe
        ? `From: ${pipe.email_from || "-"}\nSubject: ${pipe.email_subject || "-"}\nReceived at: ${pipe.email_received_at || "-"}\nLanguage hint: ${pipe.email_language_hint || "-"}\nAttachments: ${attachmentsCount}${
            Array.isArray(pipe.email_attachments) && pipe.email_attachments.length > 0
              ? "\n  " + pipe.email_attachments.join("\n  ")
              : ""
          }\n\n${pipe.email_body || ""}`
        : undefined,
      outputFields: pipe
        ? [
            { label: "From", value: pipe.email_from, mono: true },
            { label: "Subject", value: pipe.email_subject },
            { label: "Received at", value: pipe.email_received_at, mono: true },
            { label: "IMAP language hint", value: pipe.email_language_hint || "-", mono: true },
            {
              label: "Attachments",
              value:
                Array.isArray(pipe.email_attachments) && pipe.email_attachments.length > 0
                  ? `${attachmentsCount} file${attachmentsCount === 1 ? "" : "s"}: ${pipe.email_attachments.join(", ")}`
                  : "(none)",
              mono: true,
            },
            {
              label: "Body (full, verbatim)",
              value: pipe.email_body || "(empty)",
              long: true,
            },
          ]
        : undefined,
      rawData: pipe
        ? {
            from: pipe.email_from,
            subject: pipe.email_subject,
            received_at: pipe.email_received_at,
            language_hint: pipe.email_language_hint,
            body: pipe.email_body,
            attachments: pipe.email_attachments,
          }
        : undefined,
    },
    // === v1.1 TRACE-TERMINAL START === Pre-AI Outlook KB check inserted as the FIRST gate
    {
      num: "1.2",
      name: "Pre-AI Outlook rule check (Knowledge Base)",
      status: preAiStatus,
      result: isTerminal
        ? `MATCH → ${(ruleMatchedEv?.data as any)?.intent || "redirect"} (deterministic, no LLM call)`
        : preAiStatus === "skipped"
        ? "no rule match. Fall through to LLM classifier"
        : preAiStatus === "running"
        ? "evaluating KB rules…"
        : undefined,
      ms: (ruleMatchedEv?.duration_ms ?? null) as number | null,
      processing:
        "Walks the Outlook-rules knowledge base in priority order. First match wins. Deterministic, runs before any LLM call. If matched, the pipeline short-circuits and stages 2-5 are skipped.",
      provider: "Internal rule engine (knowledge base)",
      inputPreview: pipe
        ? `From: ${pipe.email_from || "-"}\nSubject: ${pipe.email_subject || "-"}\n\n${pipe.email_body || ""}`
        : undefined,
      outputFields: ruleMatchedEv
        ? [
            { label: "Matched rule", value: (ruleMatchedEv.data as any)?.rule_label || (ruleMatchedEv.data as any)?.rule_key, mono: true },
            { label: "Predicate", value: (ruleMatchedEv.data as any)?.predicate_kind || "-", mono: true },
            { label: "Matched value", value: JSON.stringify((ruleMatchedEv.data as any)?.matched_value || "-"), mono: true },
            { label: "Resulting intent", value: (ruleMatchedEv.data as any)?.intent || "-", mono: true },
            { label: "Redirect to", value: (ruleMatchedEv.data as any)?.redirect_to || "(none: discard)", mono: true },
            { label: "Severity", value: (ruleMatchedEv.data as any)?.severity || "soft", mono: true },
          ]
        : preAiStatus === "skipped"
        ? [{ label: "Outcome", value: "No KB rule matched. The LLM classifier runs in the steps below." }]
        : undefined,
      rawData: ruleMatchedEv?.data,
    },
    // === v1.1 TRACE-TERMINAL END ===
    {
      num: "1.3",
      name: "Heuristic spam pre-screen",
      status: heuristicSpamStatus,
      result: heuristicSpam
        ? heuristicSpam.data?.data?.is_spam
          ? `flagged · ${(heuristicSpam.data.data.reasons || []).length} signal${
              (heuristicSpam.data.data.reasons || []).length === 1 ? "" : "s"
            }`
          : "clean"
        : undefined,
      ms: heuristicSpam?.duration_ms ?? null,
      inputPreview: heuristicSpam?.data?.data?.input_preview,
      processing: heuristicSpam?.data?.data?.processing_method,
      provider: heuristicSpam?.data?.data?.provider,
      rulesEvaluated: heuristicSpam?.data?.data?.rules_evaluated,
      outputFields: heuristicSpam
        ? [
            { label: "Verdict", value: heuristicSpam.data?.data?.is_spam ? "SPAM" : "clean", mono: true },
            { label: "Score", value: heuristicSpam.data?.data?.score },
            {
              label: "Rules matched",
              value:
                Array.isArray(heuristicSpam.data?.data?.rules_matched) &&
                heuristicSpam.data.data.rules_matched.length > 0
                  ? heuristicSpam.data.data.rules_matched.map((r: any) => r.rule).join(", ")
                  : "(none)",
              mono: true,
            },
          ]
        : undefined,
      rawData: heuristicSpam?.data?.data,
    },
    {
      num: "1.4",
      name: "Light attachment extraction",
      status: lightExtractStatus,
      result:
        attachmentsCount === 0
          ? "no attachments"
          : lightExtractEvents.length > 0
          ? `${lightExtractEvents.length} attachment${lightExtractEvents.length === 1 ? "" : "s"} · 3-page cap`
          : undefined,
      ms: lightExtractEvents.reduce((s, e) => s + (e.duration_ms || 0), 0) || null,
      processing: "Stage 1 light OCR (3-page cap per attachment)",
      provider: lightExtractEvents[0]?.data?.data?.provider || "AWS Lambda (Azure Document Intelligence)",
      inputPreview: pipe?.email_attachments && pipe.email_attachments.length > 0
        ? `Attachments queued for extraction (${pipe.email_attachments.length}):\n  ` +
          pipe.email_attachments.join("\n  ")
        : undefined,
      outputFields: lightExtractEvents.length > 0
        ? [
            { label: "Attachments processed", value: `${lightExtractEvents.length} of ${attachmentsCount}` },
            {
              label: "Total chars extracted",
              value:
                lightExtractEvents
                  .reduce((s, e) => s + (e.data?.data?.char_count || 0), 0)
                  .toLocaleString() + " chars",
            },
            {
              label: "Total time",
              value: `${lightExtractEvents.reduce((s, e) => s + (e.duration_ms || 0), 0)}ms`,
              mono: true,
            },
            {
              label: "Page cap",
              value: "3 pages per attachment (Stage 1 light extract)",
            },
            {
              label: "Files",
              value: lightExtractEvents.map((e) => e.data?.data?.filename).filter(Boolean).join(", "),
              mono: true,
            },
          ]
        : attachmentsCount === 0
        ? [{ label: "Reason", value: "skipped: no attachments on the email" }]
        : undefined,
      attachmentsBreakdown:
        lightExtractEvents.length > 0
          ? lightExtractEvents.map((e) => ({
              filename: e.data?.data?.filename || "(unnamed)",
              provider: e.data?.data?.provider,
              char_count: e.data?.data?.char_count,
              max_pages_requested: e.data?.data?.max_pages_requested,
              text_preview: (e.data?.data?.text || "").slice(0, 2000),
              notes: Array.isArray(e.data?.notes) ? e.data.notes : undefined,
            }))
          : undefined,
      rawData:
        lightExtractEvents.length > 0
          ? lightExtractEvents.map((e) => ({
              filename: e.data?.data?.filename,
              provider: e.data?.data?.provider,
              char_count: e.data?.data?.char_count,
              max_pages_requested: e.data?.data?.max_pages_requested,
              text_preview: (e.data?.data?.text || "").slice(0, 500),
              notes: e.data?.notes,
            }))
          : undefined,
    },
    {
      num: "1.5",
      name: "Detect language",
      status: langStatus,
      result:
        lang
          ? `${lang}${langConf != null ? ` (${Math.round(langConf * 100)}%)` : ""}${detectLang?.data?.data?.agreement === false ? " · disagreement" : ""}`
          : undefined,
      ms: detectLang?.duration_ms ?? null,
      inputPreview: detectLang?.data?.data?.input_preview,
      processing: detectLang?.data?.data?.processing_method,
      provider: detectLang?.data?.data?.provider,
      rulesEvaluated: detectLang?.data?.data?.rules_evaluated,
      outputFields: detectLang
        ? (() => {
            const d = detectLang.data?.data || {};
            const breakdown: any[] = Array.isArray(d.language_confidence_breakdown) ? d.language_confidence_breakdown : [];
            const baseConf: number = typeof d.language_confidence_base === "number" ? d.language_confidence_base : 0.40;

            const fmtDelta = (v: number) => (v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2));
            const longestLabel = breakdown.reduce(
              (n: number, e: any) => Math.max(n, (e.label || e.rule_key || "").length),
              0,
            );
            const padTo = Math.max(longestLabel, 28);
            const breakdownLines: string[] = [];
            breakdownLines.push(`Base (uninformed prior)                           ${baseConf.toFixed(2)}`);
            for (const e of breakdown) {
              const label = (e.label || e.rule_key || "").padEnd(padTo);
              const tick = e.matched ? "✓" : "·";
              const delta = fmtDelta(Number(e.delta || 0));
              breakdownLines.push(`  ${tick} ${label}  ${delta}`);
              if (e.matched && e.evidence) {
                const ev = String(e.evidence).replace(/\s+/g, " ").slice(0, 140);
                breakdownLines.push(`        evidence: ${ev}${e.evidence.length > 140 ? "…" : ""}`);
              }
            }
            const matchedSum = breakdown.reduce(
              (s: number, e: any) => s + (e.matched ? Number(e.delta || 0) : 0),
              0,
            );
            const computed = baseConf + matchedSum;
            const clamped = Math.max(0, Math.min(1, computed));
            if (breakdown.length > 0) {
              breakdownLines.push("─".repeat(padTo + 22));
              breakdownLines.push(`Sum of matched deltas                                ${fmtDelta(matchedSum)}`);
              breakdownLines.push(`Total (clamped to [0, 1])                             ${clamped.toFixed(2)}  →  ${Math.round(clamped * 100)}%`);
            }

            const out: { label: string; value: any; mono?: boolean; long?: boolean }[] = [
              { label: "Final language", value: d.language || lang, mono: true },
              {
                label: "Final confidence",
                value: d.confidence != null ? `${Math.round(d.confidence * 100)}%` : null,
              },
              { label: "Heuristic says", value: d.heuristic_language, mono: true },
              {
                label: "LLM says",
                value: d.llm_language
                  ? `${d.llm_language}${d.llm_confidence != null ? ` (${Math.round(d.llm_confidence * 100)}%)` : ""}`
                  : "(LLM not available)",
                mono: true,
              },
              {
                label: "Agreement",
                value:
                  d.agreement === true
                    ? "✓ heuristic and LLM agree"
                    : d.agreement === false
                    ? "⚠ disagreement: deferred to LLM"
                    : "-",
              },
              { label: "LLM reasoning", value: d.llm_reasoning, long: true },
            ];
            if (breakdown.length > 0) {
              out.push({
                label: "Confidence breakdown (KB rubric)",
                value: breakdownLines.join("\n"),
                mono: true,
                long: true,
              });
            }
            return out;
          })()
        : undefined,
      kbNamespaces: detectLang?.data?.data?.kb_namespaces_consulted || [],
      kbRulesUsed: [],
      promptSystem: detectLang?.data?.data?.prompt_system,
      promptUser: detectLang?.data?.data?.prompt_user,
      rawResponse: detectLang?.data?.data?.provider_response_raw,
      rawData: detectLang?.data?.data,
    },
    {
      num: "1.6",
      name: "Translate to English",
      status: translateStatus,
      result:
        translateStatus === "skipped" && lang === "en"
          ? "skipped (already en)"
          : translatedBody
          ? `translated · ${String(translatedBody).length} chars`
          : translateStatus === "skipped"
          ? "skipped"
          : undefined,
      ms: translate?.duration_ms ?? null,
      inputPreview: (() => {
        const sources = (intakeData.per_source_translations as any[]) || [];
        const body = sources.find((s) => s?.source === "email_body");
        return body?.input_text || translate?.data?.data?.input_text_full || translate?.data?.data?.input_preview;
      })(),
      processing: translate?.data?.data?.processing_method,
      provider: translate?.data?.data?.provider_label || translate?.data?.data?.provider,
      outputFields: (() => {
        if (translateStatus === "skipped") {
          return [{ label: "Reason", value: lang === "en" ? "skipped (email already in English)" : "skipped" }];
        }
        const sources = (intakeData.per_source_translations as any[]) || [];
        const body = sources.find((s) => s?.source === "email_body");
        const fullBody =
          body?.translated_text ||
          translate?.data?.data?.translated_text_full ||
          translate?.data?.data?.translated_text ||
          translate?.data?.data?.output_preview;
        const out: { label: string; value: any; mono?: boolean; long?: boolean }[] = [
          { label: "Source language", value: body?.source_language || translate?.data?.data?.source_language, mono: true },
          { label: "Body translated chars", value: body?.output_chars ?? translate?.data?.data?.output_chars },
          { label: "Attachments translated", value: sources.filter((s: any) => s?.source === "attachment").length },
          { label: "Translated email (full)", value: fullBody, long: true },
        ];
        return out;
      })(),
      attachmentsBreakdown: (() => {
        const sources = (intakeData.per_source_translations as any[]) || [];
        const atts = sources.filter((s: any) => s?.source === "attachment");
        if (atts.length === 0) return undefined;
        return atts.map((s: any) => ({
          filename: s.filename || s.label || "(attachment)",
          provider: s.provider,
          char_count: s.output_chars,
          text_preview: s.translated_text,
        }));
      })(),
      kbNamespaces: translate?.data?.data?.kb_namespaces_consulted || [],
      kbRulesUsed: translate?.data?.data?.kb_rules_used || [],
      promptSystem: translate?.data?.data?.prompt_system,
      promptUser: translate?.data?.data?.prompt_user,
      rawResponse: translate?.data?.data?.provider_response_raw,
      rawData: translate?.data?.data,
    },
    {
      num: "1.8",
      name: "Classify intent",
      status: intentStatus,
      result:
        intent
          ? `${INTENT_LABELS[intent] || intent}${
              intentConf != null ? ` (${Math.round(intentConf * 100)}%)` : ""
            }`
          : undefined,
      ms: classify?.duration_ms ?? null,
      inputPreview: classify?.data?.data?.input_preview,
      processing: classify?.data?.data?.processing_method,
      provider: classify?.data?.data?.provider,
      outputFields: classify
        ? (() => {
            const d = classify.data?.data || {};
            const breakdown: any[] = Array.isArray(d.intent_confidence_breakdown) ? d.intent_confidence_breakdown : [];
            const baseConf: number | undefined = typeof d.intent_confidence_base === "number" ? d.intent_confidence_base : 0.5;
            const finalConf: number | undefined = typeof d.intent_confidence === "number" ? d.intent_confidence : undefined;

            // Build a markdown-ish multi-line "math" string the SubStepDetailCard
            // renders with `long: true` (preserves whitespace). Mirrors the look
            // of Stage 3.2's confidence formula breakdown.
            const fmtDelta = (v: number) => (v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2));
            const longestLabel = breakdown.reduce(
              (n: number, e: any) => Math.max(n, (e.label || e.rule_key || "").length),
              0,
            );
            const padTo = Math.max(longestLabel, 28);
            const breakdownLines: string[] = [];
            breakdownLines.push(`Base (uninformed prior)                           ${(baseConf ?? 0).toFixed(2)}`);
            for (const e of breakdown) {
              const label = (e.label || e.rule_key || "").padEnd(padTo);
              const tick = e.matched ? "✓" : "·";
              const delta = fmtDelta(Number(e.delta || 0));
              breakdownLines.push(`  ${tick} ${label}  ${delta}`);
              if (e.matched && e.evidence) {
                const ev = String(e.evidence).replace(/\s+/g, " ").slice(0, 140);
                breakdownLines.push(`        evidence: ${ev}${e.evidence.length > 140 ? "…" : ""}`);
              }
            }
            const matchedSum = breakdown.reduce(
              (s: number, e: any) => s + (e.matched ? Number(e.delta || 0) : 0),
              0,
            );
            breakdownLines.push("─".repeat(padTo + 22));
            breakdownLines.push(
              `Sum of matched deltas                                ${fmtDelta(matchedSum)}`,
            );
            const computed = (baseConf ?? 0) + matchedSum;
            const clamped = Math.max(0, Math.min(1, computed));
            breakdownLines.push(
              `Total (clamped to [0, 1])                             ${clamped.toFixed(2)}  →  ${Math.round(clamped * 100)}%`,
            );

            const out: { label: string; value: any; mono?: boolean; long?: boolean }[] = [
              { label: "Intent", value: d.intent, mono: true },
              {
                label: "Confidence",
                value:
                  finalConf != null
                    ? `${Math.round(finalConf * 100)}% (${finalConf.toFixed(3)})`
                    : null,
              },
              { label: "Track hint", value: d.track_hint, mono: true },
              { label: "Reasoning", value: d.intent_reasoning, long: true },
              { label: "Summary", value: d.summary, long: true },
              {
                label: "Secondary intents",
                value:
                  Array.isArray(d.secondary_intents) && d.secondary_intents.length > 0
                    ? d.secondary_intents.map((s: any) => (typeof s === "string" ? s : s.intent)).join(", ")
                    : "(none)",
                mono: true,
              },
            ];
            if (breakdown.length > 0) {
              out.push({
                label: "Confidence breakdown (KB rubric)",
                value: breakdownLines.join("\n"),
                mono: true,
                long: true,
              });
            }
            out.push({
              label: "Normalizer corrections",
              value:
                Array.isArray(d.normalizer_corrections_applied) && d.normalizer_corrections_applied.length > 0
                  ? d.normalizer_corrections_applied.length + " applied"
                  : "(none)",
            });
            return out;
          })()
        : undefined,
      kbNamespaces: classify?.data?.data?.kb_namespaces_consulted || [],
      kbRulesUsed: classify?.data?.data?.kb_rules_used || [],
      promptSystem: classify?.data?.data?.prompt_system,
      promptUser: classify?.data?.data?.prompt_user,
      rawResponse: classify?.data?.data?.provider_response_raw,
      rawData: classify?.data?.data,
    },
  ];

  // Splice 1.6 (LLM spam) between 1.5 Translate and 1.7 Classify
  const subStep_1_6: SubStep = {
    num: "1.7",
    name: "LLM spam check",
    status: llmSpamStatus,
    result: llmSpam
      ? llmSpam.data?.data?.is_spam
        ? `SPAM · ${llmSpam.data?.data?.category || "phishing"} (${Math.round((llmSpam.data?.data?.confidence || 0) * 100)}%)`
        : `clean (${Math.round((llmSpam.data?.data?.confidence || 0) * 100)}% confident)`
      : undefined,
    ms: llmSpam?.duration_ms ?? null,
    inputPreview: llmSpam?.data?.data?.input_preview,
    processing: llmSpam?.data?.data?.processing_method,
    provider: llmSpam?.data?.data?.provider,
    outputFields: llmSpam
      ? [
          { label: "Verdict", value: llmSpam.data?.data?.is_spam ? "SPAM" : "clean", mono: true },
          { label: "Category", value: llmSpam.data?.data?.category, mono: true },
          {
            label: "Confidence",
            value: llmSpam.data?.data?.confidence != null
              ? `${Math.round(llmSpam.data.data.confidence * 100)}%`
              : null,
          },
          { label: "LLM reasoning", value: llmSpam.data?.data?.reasoning, long: true },
          {
            label: "Heuristic agreement",
            value: spamSignals
              ? `heuristic=${spamSignals.heuristic ? "SPAM" : "clean"} · LLM=${spamSignals.llm ? "SPAM" : "clean"}${
                  spamSignals.heuristic === spamSignals.llm ? " · ✓ agree" : " · ⚠ disagree"
                }`
              : "-",
          },
        ]
      : undefined,
    kbNamespaces: llmSpam?.data?.data?.kb_namespaces_consulted || [],
    promptSystem: llmSpam?.data?.data?.prompt_system,
    promptUser: llmSpam?.data?.data?.prompt_user,
    rawResponse: llmSpam?.data?.data?.provider_response_raw,
    rawData: llmSpam?.data?.data,
  };
  // splice it in just before the 1.7 Classify intent entry (last in the array)
  subSteps.splice(subSteps.length - 1, 0, subStep_1_6);
  // The variables below are referenced by the layout (kept to avoid eslint unused complaints).
  void spam;

  const resultLine = intent
    ? `intent=${intent} · confidence=${intentConf != null ? intentConf.toFixed(2) : "-"} · language=${lang || "-"}${
        spam ? " · spam" : ""
      }`
    : null;

  const stageEvents = events.filter((e) => e.stage === "intake");
  const notes = collectStageNotes(events, ["intake"]);

  return (
    <StageCardShell
      num={1}
      title="Intake & Classification"
      state={state}
      subSteps={subSteps}
      resultLine={resultLine}
      toolbeltEvents={stageEvents}
      toolbeltStageKeys={["intake"]}
      notes={notes}
      rawData={intakeData}
      pipelineId={pipe?.id}
      feedbackKey="intake"
      feedbackSnapshot={intakeData}
    />
  );
}

function ExtractStageCard({
  pipe,
  state,
  events,
}: {
  pipe: Pipeline | null;
  state?: StageStatus;
  events: TraceEvent[];
}) {
  const ex = pipe?.extracted || {};
  const cm = pipe?.customer_match;
  const sf = cm?.salesforce;

  const hasExtract = state?.status === "done" || state?.status === "running" || state?.status === "error";

  const ocrTools = findToolEnds(
    events,
    ["extract"],
    ["azure_doc_intelligence", "vision_ocr", "read_attachment"]
  );
  const llmExtract =
    findToolEnd(events, "extract", "schema_extract") ||
    findToolEnd(events, "extract", "llm_extract");
  const entityResolve = findToolEnd(events, "extract", "entity_resolve_customer");
  const sfQueries = findToolEnds(events, ["extract", "enrichment"], ["salesforce_soql"]);
  const sfFiles = findToolEnd(events, "extract", "salesforce_fetch_files");
  const sfAccountFetched = events.find(
    (e) =>
      (e.stage === "extract" || e.stage === "enrichment") &&
      e.kind === "salesforce_account_fetched"
  );
  const sfNoMatch = events.find(
    (e) =>
      (e.stage === "extract" || e.stage === "enrichment") &&
      e.kind === "salesforce_no_match"
  );
  const stageBlocked = events.find(
    (e) => e.stage === "extract" && e.kind === "stage_blocked"
  );
  const substepDone = (n: string) =>
    events.find(
      (e) => e.stage === "extract" && e.kind === "substep_done" && e.data?.substep === n
    );

  const ocrStatus: SubStepStatus = !hasExtract
    ? "pending"
    : (pipe?.email_attachments || []).length === 0
    ? "skipped"
    : ocrTools.length > 0
    ? "done"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const llmStatus: SubStepStatus = !hasExtract
    ? "pending"
    : llmExtract
    ? llmExtract.data?.ok === false
      ? "error"
      : "done"
    : Object.keys(ex).length > 0
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const entityStatus: SubStepStatus = !hasExtract
    ? "pending"
    : entityResolve
    ? "done"
    : cm?.customer_id
    ? "done"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const sfStatus: SubStepStatus = !hasExtract
    ? "pending"
    : sfAccountFetched || sfQueries.length > 0
    ? "done"
    : sfNoMatch
    ? "skipped"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const ocrToolBreakdown =
    ocrTools.length > 0
      ? Array.from(new Set(ocrTools.map((e) => e.data?.tool))).join(" + ")
      : "";

  const lineItemsCount = Array.isArray(ex.line_items) ? ex.line_items.length : 0;
  const llmFieldCount = Object.keys(ex || {}).filter((k) => !k.startsWith("_")).length;

  const totalOcrChars = ocrTools.reduce(
    (s, e) => s + (e.data?.data?.char_count || 0),
    0,
  );
  const ocrAttBreakdown = ocrTools.map((e) => ({
    filename: e.data?.data?.filename || "(unnamed)",
    provider: e.data?.data?.provider,
    char_count: e.data?.data?.char_count,
    max_pages_requested: e.data?.data?.max_pages_requested,
    text_preview: (e.data?.data?.text || "").slice(0, 4000),
    notes: Array.isArray(e.data?.notes) ? e.data.notes : undefined,
  }));

  const llmExtractData = llmExtract?.data?.data || {};
  const kbSchemaFields = (llmExtractData.kb_schema_fields as any[]) || [];
  const extractedFields = (llmExtractData.extracted_fields as Record<string, any>) || {};
  const validationNotes = (llmExtractData.validation_notes as string[]) || [];
  const extractedFieldsRows = Object.entries(extractedFields).map(([k, v]) => ({
    label: k,
    value:
      typeof v === "object"
        ? Array.isArray(v)
          ? `[${v.length} item${v.length === 1 ? "" : "s"}]`
          : JSON.stringify(v).slice(0, 200)
        : String(v ?? "-"),
    mono: true as const,
    long: typeof v === "string" && v.length > 80,
  }));
  if (Array.isArray(extractedFields.line_items)) {
    extractedFieldsRows.push({
      label: "line_items (full)",
      value: extractedFields.line_items
        .map((li: any, i: number) =>
          `  ${i + 1}. ${li.sku || "-"} · ${(li.description || "").slice(0, 60)} · qty=${li.qty} · @${li.unit_price}`,
        )
        .join("\n"),
      mono: true,
      long: true,
    });
  }

  const entityData = entityResolve?.data?.data || {};
  const attemptedLookups = (entityData.attempted_lookups as any[]) || [];
  const attemptedRows = attemptedLookups.map((a, i) => ({
    label: `attempt ${i + 1}`,
    value: `${a.method || "?"} = ${a.value || "?"} → ${a.matched ? "✓ matched" : "✗ no match"}`,
    mono: true as const,
  }));

  const sfAcc = sfAccountFetched?.data || {};
  const sfQueriesPretty = sfQueries.map((e) => ({
    label: (e.data?.data?.label || e.data?.data?.input?.label || "") as string,
    soql: (e.data?.data?.soql || e.data?.data?.input?.soql || "(soql not captured)") as string,
    count: (e.data?.data?.totalSize as number) ?? (e.data?.data?.records?.length as number) ?? 0,
    duration_ms: e.duration_ms,
    records: (e.data?.data?.records as any[]) || [],
  }));

  const subSteps: SubStep[] = [
    {
      num: "2.1",
      name: "Document extraction (full OCR via Azure Doc Intelligence)",
      status: ocrStatus,
      result:
        (pipe?.email_attachments || []).length === 0
          ? "no attachments"
          : ocrTools.length > 0
          ? `${ocrTools.length} attachment${ocrTools.length === 1 ? "" : "s"} · ${ocrToolBreakdown}`
          : undefined,
      ms: ocrTools.reduce((s, e) => s + (e.duration_ms || 0), 0) || null,
      processing: "Full OCR (no page cap) per attachment. Azure Doc Intelligence via Lambda for PDFs/images, openpyxl for XLSX, python-docx for DOCX",
      provider: ocrTools[0]?.data?.data?.provider || "Azure Document Intelligence",
      inputPreview:
        (pipe?.email_attachments || []).length > 0
          ? `Attachments queued (${pipe?.email_attachments?.length}):\n  ${pipe?.email_attachments?.join("\n  ")}`
          : undefined,
      outputFields:
        ocrTools.length > 0
          ? [
              { label: "Attachments processed", value: `${ocrTools.length} of ${(pipe?.email_attachments || []).length}` },
              { label: "Total chars extracted", value: totalOcrChars.toLocaleString() + " chars" },
              { label: "Total time", value: `${ocrTools.reduce((s, e) => s + (e.duration_ms || 0), 0)}ms`, mono: true },
              { label: "Files", value: ocrTools.map((e) => e.data?.data?.filename).filter(Boolean).join(", "), mono: true },
            ]
          : (pipe?.email_attachments || []).length === 0
          ? [{ label: "Reason", value: "no attachments on this email" }]
          : undefined,
      attachmentsBreakdown: ocrAttBreakdown.length > 0 ? ocrAttBreakdown : undefined,
      rawData: ocrTools.length > 0 ? ocrTools.map((e) => e.data?.data) : undefined,
    },
    {
      num: "2.2",
      name: "Schema-driven extraction (intent-specific KB schema)",
      status: llmStatus,
      result:
        llmStatus === "done"
          ? `${llmFieldCount} field${llmFieldCount === 1 ? "" : "s"}${
              lineItemsCount > 0 ? ` · ${lineItemsCount} line items` : ""
            }`
          : undefined,
      ms: llmExtract?.duration_ms ?? null,
      processing:
        llmExtractData.processing_method ||
        "OpenAI gpt-5.2 with response_format=json_object, schema from KB extract_schema rule",
      provider: llmExtractData.provider,
      inputPreview: llmExtractData.input_preview,
      outputFields:
        llmStatus === "done"
          ? [
              { label: "KB schema rule used", value: llmExtractData.kb_schema_key_used || "-", mono: true },
              { label: "Intent driving schema", value: llmExtractData.kb_schema_intent || pipe?.intent || "-", mono: true },
              {
                label: "Required fields populated",
                value:
                  llmExtractData.kb_schema_required_populated != null && llmExtractData.kb_schema_required_count != null
                    ? `${llmExtractData.kb_schema_required_populated} / ${llmExtractData.kb_schema_required_count}`
                    : "-",
              },
              { label: "Total fields extracted", value: llmFieldCount },
              ...extractedFieldsRows,
            ]
          : undefined,
      kbNamespaces: ["extract_schema"],
      kbRulesUsed: kbSchemaFields.map((f: any) => `${f.name}${f.required ? "*" : ""}`),
      promptSystem: llmExtractData.prompt_system,
      promptUser: llmExtractData.prompt_user,
      rawResponse: llmExtractData.provider_response_raw,
      rawData: { ...extractedFields, _validation_notes: validationNotes, _kb_schema_fields: kbSchemaFields },
    },
    {
      num: "2.3",
      name: "Customer identification",
      status: entityStatus,
      result:
        cm?.customer_name
          ? `${cm.customer_name}${cm.score != null ? ` (${Math.round(cm.score * 100)}%)` : ""}`
          : entityStatus === "skipped" || stageBlocked
          ? "no Salesforce match. Routed to HITL"
          : undefined,
      ms: entityResolve?.duration_ms ?? null,
      processing:
        "Salesforce Account lookup: Customer_Code__c → Contact.Email → Account.Name (fuzzy).",
      provider: "Salesforce REST",
      inputPreview:
        entityData.extracted_customer_code_seen || entityData.extracted_buyer_email_seen || entityData.extracted_customer_name_seen
          ? [
              `Extracted customer_code: ${entityData.extracted_customer_code_seen || "-"}`,
              `Extracted buyer email: ${entityData.extracted_buyer_email_seen || "-"}`,
              `Extracted customer name: ${entityData.extracted_customer_name_seen || "-"}`,
              `Email sender: ${entityData.sender_email_seen || "-"}`,
            ].join("\n")
          : undefined,
      outputFields: [
        { label: "Match outcome", value: cm?.customer_name || "no match", mono: true },
        { label: "Lookup basis", value: cm?.basis || "-", mono: true },
        { label: "Score", value: cm?.score != null ? `${Math.round((cm.score || 0) * 100)}%` : "-" },
        ...(sfAcc.salesforce_account_id ? [{ label: "Salesforce Account ID", value: sfAcc.salesforce_account_id, mono: true as const }] : []),
        ...(sfAcc.name ? [{ label: "Account name", value: sfAcc.name }] : []),
        ...(sfAcc.region ? [{ label: "Region", value: sfAcc.region }] : []),
        ...(sfAcc.sla_tier ? [{ label: "SLA tier", value: sfAcc.sla_tier }] : []),
        ...(sfAcc.compliance_flags ? [{ label: "Compliance flags", value: sfAcc.compliance_flags }] : []),
        ...attemptedRows,
        ...(stageBlocked ? [{ label: "Stage blocked", value: stageBlocked.data?.reason || "yes", mono: true as const }] : []),
      ],
      rawData: {
        customer_match: cm,
        salesforce_account_event: sfAcc,
      },
    },
    {
      num: "2.4",
      name: "Customer enrichment (intent-aware Salesforce queries)",
      status: sfStatus,
      result:
        sf?.account?.Name
          ? `${sf.account.Name} · ${sfQueries.length || 1} SOQL`
          : sfStatus === "skipped"
          ? "skipped: no Salesforce account matched"
          : undefined,
      ms: sfAccountFetched?.duration_ms ?? sfQueries.reduce((s, q) => s + (q.duration_ms || 0), 0) ?? null,
      processing: `Intent-aware enrichment for intent='${pipe?.intent || "?"}': different SOQL templates per intent (orders+opps+contacts for trade; work-orders+contacts for SOM; etc).`,
      provider: "Salesforce REST",
      inputPreview:
        sf?.account?.Id
          ? `Querying for AccountId=${sf.account.Id}`
          : sfStatus === "skipped"
          ? "no AccountId; enrichment skipped"
          : undefined,
      outputFields:
        sfQueriesPretty.length > 0
          ? sfQueriesPretty.map((q, i) => ({
              label: `Query ${i + 1}`,
              value: `${q.count} row${q.count === 1 ? "" : "s"} · ${q.duration_ms}ms\n${q.soql}`,
              mono: true as const,
              long: true,
            }))
          : sfStatus === "skipped"
          ? [{ label: "Reason", value: "no Salesforce match in 2.3; enrichment skipped" }]
          : undefined,
      rawData: {
        salesforce: sf,
        queries: sfQueriesPretty,
        files: sfFiles?.data?.data,
      },
    },
    (() => {
      const recon = pipe?.reconcile || {};
      const checks: any[] = Array.isArray(recon.checks_evaluated) ? recon.checks_evaluated : [];
      const issues: any[] = Array.isArray(recon.issues) ? recon.issues : [];
      const checkedFlag = recon.checked === true;
      const reconcileSubstepEvents = events.filter(
        (e) => (e.data || {}).substep === "2.5" || (e.message || "").startsWith("2.5 ")
      );
      const reconStatus: SubStepStatus =
        reconcileSubstepEvents.find((e) => e.kind === "substep_done")
          ? "done"
          : reconcileSubstepEvents.find((e) => e.kind === "substep_start")
          ? "running"
          : checkedFlag
          ? "done"
          : recon.checked === false
          ? "skipped"
          : "pending";

      const fired = checks.filter((c) => c.fired);
      const passed = checks.filter((c) => !c.fired && c.matched !== undefined);
      const totalCount = checks.length;

      const groupedBySeverity = {
        hard: fired.filter((c) => c.severity === "hard"),
        soft: fired.filter((c) => c.severity === "soft"),
        warn: fired.filter((c) => c.severity === "warn"),
      };

      const checkLines: string[] = [];
      const labelPad = checks.reduce((n, c) => Math.max(n, (c.id || "").length), 0) || 32;
      for (const c of checks) {
        const flag = c.fired ? "✗" : "✓";
        const sev = (c.severity || "warn").padEnd(4);
        const id = (c.id || "?").padEnd(Math.max(labelPad, 32));
        const scope = (c.scope || "").padEnd(10);
        const msg = c.message ? `: ${(c.message || "").slice(0, 80)}` : "";
        checkLines.push(`  ${flag} [${sev}] [${scope}] ${id}${msg}`);
      }

      return {
        num: "2.5",
        name: "Cross-system validation (KB-driven reconcile checks)",
        status: reconStatus,
        result:
          reconStatus === "done"
            ? `${fired.length} of ${totalCount} check${totalCount === 1 ? "" : "s"} fired${
                groupedBySeverity.hard.length
                  ? ` · ${groupedBySeverity.hard.length} hard`
                  : ""
              }${
                groupedBySeverity.soft.length
                  ? ` · ${groupedBySeverity.soft.length} soft`
                  : ""
              }`
            : reconStatus === "skipped"
            ? "skipped: no PO/Q2O intent or no quote matched"
            : undefined,
        processing:
          "Walks the KB `reconcile_checks` namespace. Each check is a predicate evaluated against (PO line / matched quote line / account billing / recent SF orders). Severity (hard/soft/warn) feeds into Stage 3.1 floor caps.",
        provider: "ZBrain reconcile · KB-driven",
        kbNamespaces: ["reconcile_checks"],
        inputPreview: recon.matched_quote
          ? `matched quote: ${(recon.matched_quote as any).quote_number || (recon.matched_quote as any).Name || "-"} · ${(recon.matched_quote as any).total != null ? "$" + ((recon.matched_quote as any).total as number).toLocaleString() : "no total"}`
          : checkedFlag
          ? "no matching quote; line-item checks skipped, address/duplicate checks ran"
          : undefined,
        outputFields:
          reconStatus === "done"
            ? [
                { label: "Total checks", value: totalCount, mono: true as const },
                { label: "Fired", value: `${fired.length} (${groupedBySeverity.hard.length} hard · ${groupedBySeverity.soft.length} soft · ${groupedBySeverity.warn.length} warn)`, mono: true as const },
                { label: "Passed", value: passed.length, mono: true as const },
                { label: "Issues handed to Stage 3", value: issues.length, mono: true as const },
                ...(checkLines.length > 0
                  ? [{
                      label: "Per-check breakdown",
                      value: checkLines.join("\n"),
                      mono: true as const,
                      long: true as const,
                    }]
                  : []),
                ...(issues.length > 0
                  ? [{
                      label: "Issues for Stage 3 confidence caps",
                      value: issues
                        .map((i: any, idx: number) => `${idx + 1}. ${i.kind}${i.sku ? " · sku=" + i.sku : ""}${i.po_qty != null ? " · po_qty=" + i.po_qty : ""}${i.quoted_qty != null ? " · quoted_qty=" + i.quoted_qty : ""}`)
                        .join("\n"),
                      mono: true as const,
                      long: true as const,
                    }]
                  : []),
              ]
            : undefined,
        rawData: { reconcile: recon },
      };
    })(),
  ];

  const resultLine =
    Object.keys(ex).length > 0
      ? `${ex.po_number ? `PO=${ex.po_number} · ` : ""}${
          lineItemsCount > 0 ? `${lineItemsCount} line items · ` : ""
        }customer=${cm?.customer_name || "-"}`
      : null;

  const stageEvents = events.filter((e) => e.stage === "extract" || e.stage === "enrichment");
  const notes = collectStageNotes(events, ["extract", "enrichment"]);

  return (
    <StageCardShell
      num={2}
      title="Extraction & Enrichment"
      state={state}
      subSteps={subSteps}
      resultLine={resultLine}
      toolbeltEvents={stageEvents}
      toolbeltStageKeys={["extract", "enrichment"]}
      notes={notes}
      rawData={ex}
      pipelineId={pipe?.id}
      feedbackKey="extract"
      feedbackSnapshot={ex}
      extraSections={
        <>
          {cm?.customer_id && <CustomerMatchInline cm={cm} />}
          {sf?.account && <SalesforceSnapshotInline sf={sf} />}
          {sfQueriesPretty.length > 0 && (
            <EnrichmentQueriesPanel queries={sfQueriesPretty} />
          )}
        </>
      }
    />
  );
}

/** Renders each intent-aware SOQL query result as a labeled, collapsible table.
 * Surfaces `Document_Url__c` / `Cal_Cert_Url__c` columns as click-through SharePoint links
 * so a CSR can audit the enrichment without leaving the trace. */
function EnrichmentQueriesPanel({
  queries,
}: {
  queries: Array<{
    label: string;
    soql: string;
    count: number;
    duration_ms: number | null;
    records: any[];
  }>;
}) {
  return (
    <div className="border border-zbrain-divider rounded-md overflow-hidden bg-white">
      <div className="px-3 py-2 border-b border-zbrain-divider bg-slate-50/60 flex items-center gap-2">
        <div className="w-6 h-6 rounded bg-sky-100 text-sky-700 flex items-center justify-center font-semibold text-xs">
          E
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-sky-700">
            Intent-aware enrichment
          </div>
          <div className="text-xs font-semibold text-zbrain-ink truncate">
            {queries.length} SOQL block{queries.length === 1 ? "" : "s"} · joined records visible below
          </div>
        </div>
      </div>
      <div className="divide-y divide-zbrain-divider">
        {queries.map((q, i) => (
          <EnrichmentQueryBlock key={`${q.label}-${i}`} q={q} />
        ))}
      </div>
    </div>
  );
}

function EnrichmentQueryBlock({
  q,
}: {
  q: {
    label: string;
    soql: string;
    count: number;
    duration_ms: number | null;
    records: any[];
  };
}) {
  const [open, setOpen] = useState(q.count > 0 && q.count <= 5);
  const labelPretty = (q.label || "query").replace(/_/g, " ");
  const cols = inferEnrichmentColumns(q.label, q.records);
  const docCol = cols.find((c) => c.isUrl) || null;

  return (
    <div className="bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 flex items-center gap-2 hover:bg-slate-50 transition"
      >
        <span className={`text-zbrain-muted text-xs ${open ? "rotate-90" : ""} transition`}>▶</span>
        <span className="text-xs font-semibold text-zbrain-ink capitalize">{labelPretty}</span>
        <span className="pill bg-slate-100 text-slate-700 text-[10px]">
          {q.count} row{q.count === 1 ? "" : "s"}
        </span>
        {docCol && q.records.some((r) => r[docCol.key]) && (
          <span className="pill bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px]">
            SharePoint links
          </span>
        )}
        {q.duration_ms != null && (
          <span className="ml-auto text-[10px] text-zbrain-muted font-mono">
            {q.duration_ms}ms
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1">
          {q.count === 0 ? (
            <div className="text-[11px] text-zbrain-muted italic py-1">no records</div>
          ) : (
            <div className="overflow-x-auto border border-zbrain-divider rounded">
              <table className="w-full text-[11px]">
                <thead className="bg-slate-50 text-zbrain-muted uppercase text-[10px] tracking-wider">
                  <tr>
                    {cols.map((c) => (
                      <th key={c.key} className="text-left px-2 py-1 font-medium whitespace-nowrap">
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.records.slice(0, 25).map((r, idx) => (
                    <tr key={idx} className="border-t border-zbrain-divider">
                      {cols.map((c) => (
                        <td key={c.key} className="px-2 py-1 align-top whitespace-nowrap">
                          {renderEnrichmentCell(r, c)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-2 text-[10px] font-mono text-zbrain-muted truncate" title={q.soql}>
            {q.soql}
          </div>
        </div>
      )}
    </div>
  );
}

type EnrichmentCol = { key: string; label: string; path?: string[]; isUrl?: boolean };

const ENRICHMENT_COLUMN_PRESETS: Record<string, EnrichmentCol[]> = {
  recent_orders: [
    { key: "OrderNumber", label: "Order #" },
    { key: "Status", label: "Status" },
    { key: "EffectiveDate", label: "Effective" },
    { key: "TotalAmount", label: "Total" },
    { key: "PoNumber", label: "PO #" },
  ],
  orders_on_hold: [
    { key: "OrderNumber", label: "Order #" },
    { key: "Status", label: "Status" },
    { key: "EffectiveDate", label: "Effective" },
    { key: "TotalAmount", label: "Total" },
    { key: "PoNumber", label: "PO #" },
  ],
  recent_opportunities: [
    { key: "Name", label: "Name" },
    { key: "StageName", label: "Stage" },
    { key: "Amount", label: "Amount" },
    { key: "CloseDate", label: "Close" },
  ],
  contacts: [
    { key: "Name", label: "Name" },
    { key: "Title", label: "Title" },
    { key: "Email", label: "Email" },
    { key: "Phone", label: "Phone" },
  ],
  recent_cases: [
    { key: "CaseNumber", label: "Case #" },
    { key: "Subject", label: "Subject" },
    { key: "Status", label: "Status" },
    { key: "Priority", label: "Priority" },
    { key: "CreatedDate", label: "Created" },
  ],
  recent_quotes: [
    { key: "Name", label: "Quote" },
    { key: "Status", label: "Status" },
    { key: "ExpirationDate", label: "Expires" },
    { key: "GrandTotal", label: "Total" },
    { key: "Sales_Rep__c", label: "Rep" },
    { key: "Document_Url__c", label: "PDF", isUrl: true },
  ],
  quote_line_items: [
    { key: "Quote.Name", label: "Quote", path: ["Quote", "Name"] },
    { key: "Product2.ProductCode", label: "SKU", path: ["Product2", "ProductCode"] },
    { key: "Quantity", label: "Qty" },
    { key: "UnitPrice", label: "Unit $" },
    { key: "TotalPrice", label: "Total" },
  ],
  installed_base: [
    { key: "Name", label: "Asset" },
    { key: "SerialNumber", label: "Serial" },
    { key: "Status", label: "Status" },
    { key: "Last_Cal_Date__c", label: "Last cal" },
    { key: "Calibration_Due_Date__c", label: "Cal due" },
    { key: "Cal_Cert_Url__c", label: "Cert PDF", isUrl: true },
    { key: "Document_Url__c", label: "Doc", isUrl: true },
  ],
  recent_work_orders: [
    { key: "WorkOrderNumber", label: "WO #" },
    { key: "Subject", label: "Subject" },
    { key: "Status", label: "Status" },
    { key: "StartDate", label: "Start" },
    { key: "Asset_Serial__c", label: "Asset" },
    { key: "Technician__c", label: "Tech" },
    { key: "Document_Url__c", label: "WO PDF", isUrl: true },
  ],
  active_service_contracts: [
    { key: "Name", label: "Contract" },
    { key: "Status", label: "Status" },
    { key: "StartDate", label: "Starts" },
    { key: "EndDate", label: "Expires" },
    { key: "Coverage_Type__c", label: "Coverage" },
    { key: "Annual_Value_USD__c", label: "Annual $" },
    { key: "Document_Url__c", label: "PDF", isUrl: true },
  ],
};

function inferEnrichmentColumns(label: string, records: any[]): EnrichmentCol[] {
  const preset = ENRICHMENT_COLUMN_PRESETS[label];
  if (preset) return preset;
  // Generic fallback: pick top 6 keys by frequency, mark *_Url__c as links.
  const counts = new Map<string, number>();
  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    for (const k of Object.keys(r)) counts.set(k, (counts.get(k) || 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  return sorted.map(([k]) => ({
    key: k,
    label: k.replace(/__c$/, "").replace(/_/g, " "),
    isUrl: /url__c$/i.test(k),
  }));
}

function renderEnrichmentCell(row: any, c: EnrichmentCol) {
  let v: any = row;
  if (c.path) {
    for (const p of c.path) {
      if (v == null) break;
      v = v[p];
    }
  } else {
    v = row?.[c.key];
  }
  if (v == null || v === "") return <span className="text-zbrain-muted">-</span>;
  if (c.isUrl && typeof v === "string") {
    const isPlaceholder = v.includes("sharepoint.placeholder");
    return (
      <a
        href={isPlaceholder ? undefined : v}
        target="_blank"
        rel="noreferrer"
        className={`inline-flex items-center gap-1 ${
          isPlaceholder
            ? "text-zbrain-muted line-through cursor-not-allowed"
            : "text-zbrain hover:underline"
        }`}
        title={isPlaceholder ? "Awaiting SharePoint upload (Phase 3)" : v}
        onClick={(e) => {
          if (isPlaceholder) e.preventDefault();
        }}
      >
        {isPlaceholder ? "pending upload" : "open ↗"}
      </a>
    );
  }
  if (typeof v === "number") return <span className="tabular-nums">{v.toLocaleString()}</span>;
  if (typeof v === "string" && v.length > 60) {
    return (
      <span className="block truncate max-w-[28ch]" title={v}>
        {v}
      </span>
    );
  }
  return String(v);
}

/** Inline customer-match summary embedded into the Extract stage card's enrichment row. */
function CustomerMatchInline({ cm }: { cm: NonNullable<Pipeline["customer_match"]> }) {
  if (!cm.customer_id) return null;
  const score = Math.round((cm.score || 0) * 100);
  return (
    <div className="border border-zbrain-divider rounded-md p-3 bg-white">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted mb-1">
        Customer match (CRM lookup)
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="text-sm font-semibold truncate">{cm.customer_name}</div>
          <div className="text-xs font-mono text-zbrain-muted">{cm.customer_code}</div>
        </div>
        <div className="text-xs text-zbrain-muted">
          {cm.region} · {VERTICAL_LABELS[cm.vertical || ""] || cm.vertical || "-"}
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">Score</div>
            <div className="text-base font-semibold tabular-nums">{score}%</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Inline Salesforce snapshot panel preserved from the previous design, embedded under sub-step 2.4. */
function SalesforceSnapshotInline({
  sf,
}: {
  sf: NonNullable<NonNullable<Pipeline["customer_match"]>["salesforce"]>;
}) {
  if (!sf.account) return null;
  const acc = sf.account;
  const compliance = (acc.Compliance_Flags__c || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const queriedAt = sf.queried_at ? new Date(sf.queried_at) : null;
  const ageSec = queriedAt ? Math.max(0, Math.round((Date.now() - queriedAt.getTime()) / 1000)) : null;
  const ageLabel =
    ageSec == null
      ? ""
      : ageSec < 60
      ? `${ageSec}s ago`
      : ageSec < 3600
      ? `${Math.round(ageSec / 60)}m ago`
      : queriedAt!.toLocaleTimeString();

  return (
    <div className="border border-sky-200 rounded-md overflow-hidden bg-white">
      <div className="px-3 py-2 border-b border-sky-200 bg-sky-50/60 flex items-center gap-2">
        <div className="w-6 h-6 rounded bg-sky-100 text-sky-700 flex items-center justify-center font-semibold text-xs">
          S
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-sky-700">Live · Salesforce</div>
          <div className="text-xs font-semibold text-zbrain-ink truncate">
            Cross-system enrichment from system of record
          </div>
        </div>
        <div className="text-[10px] text-sky-700 shrink-0">
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Fetched {ageLabel}
          </span>
        </div>
      </div>
      <div className="px-3 py-2 text-[11px] text-zbrain-muted border-b border-sky-200/50 bg-white/60 font-mono truncate">
        SOQL · WHERE {sf.matched_via}
      </div>
      <div className="p-3 grid grid-cols-12 gap-3">
        <div className="col-span-5">
          <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">SF Account</div>
          <div className="text-sm font-semibold mt-0.5">{acc.Name}</div>
          <div className="text-[11px] font-mono text-zbrain-muted mt-0.5">{acc.Id}</div>
          {compliance.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {compliance.map((tag) => (
                <span
                  key={tag}
                  className="pill bg-amber-50 text-amber-800 border border-amber-200 text-[10px]"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="col-span-4 grid grid-cols-2 gap-2 content-start">
          <SfField label="Region" value={acc.Region__c} />
          <SfField label="Vertical" value={(acc.Vertical__c || "").replace(/_/g, " ")} />
          <SfField
            label="SLA tier"
            value={acc.SLA_Tier__c}
            highlight={acc.SLA_Tier__c === "Platinum" || acc.SLA_Tier__c === "Gold"}
          />
          <SfField label="Payment terms" value={acc.Payment_Terms__c} />
        </div>
        <div className="col-span-3 grid grid-cols-1 gap-2 content-start">
          <SfField
            label="Credit limit"
            value={
              typeof acc.Credit_Limit__c === "number"
                ? `$${acc.Credit_Limit__c.toLocaleString()}`
                : null
            }
          />
          <SfField
            label="Live counts"
            value={`${sf.history?.contacts ?? 0} contacts · ${sf.history?.orders ?? 0} orders`}
          />
        </div>
      </div>
    </div>
  );
}

function SfField({ label, value, highlight }: { label: string; value: any; highlight?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">{label}</div>
      <div
        className={`text-xs font-medium tabular-nums truncate ${
          highlight ? "text-amber-700" : value ? "text-zbrain-ink" : "text-zbrain-muted"
        }`}
        title={value || ""}
      >
        {value || "-"}
      </div>
    </div>
  );
}

function DecideStageCard({
  pipe,
  state,
  events,
  suggesting,
  onSuggest,
}: {
  pipe: Pipeline | null;
  state?: StageStatus;
  events: TraceEvent[];
  suggesting: boolean;
  onSuggest: () => void;
}) {
  const recon = pipe?.reconcile || {};
  const decision = pipe?.decision || {};
  const signals = decision.signals || {};
  const tier = decision.autonomy_tier || pipe?.autonomy_tier;
  const conf = decision.confidence ?? pipe?.confidence;
  const fix = pipe?.suggested_fix;

  const hasDecide = state?.status === "done" || state?.status === "running" || state?.status === "error";
  const reconResult = events.find((e) => e.stage === "reconcile" && e.kind === "result");
  const businessRulesEval = findToolEnd(events, "decide", "business_rules_eval");

  const issuesCount = Array.isArray(recon.issues) ? recon.issues.length : 0;

  const reconStatus: SubStepStatus = !hasDecide
    ? "pending"
    : recon.checked === false
    ? "skipped"
    : reconResult
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const confidenceStatus: SubStepStatus = !hasDecide
    ? "pending"
    : Object.keys(signals).length > 0 || conf != null
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const rulesStatus: SubStepStatus = !hasDecide
    ? "pending"
    : businessRulesEval
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const tierStatus: SubStepStatus = !hasDecide
    ? "pending"
    : tier
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const firedRules = businessRulesEval?.data?.data?.fired || decision.fired_rules || [];
  const firedCount = Array.isArray(firedRules) ? firedRules.length : 0;

  const reconIssues = (recon.issues as any[]) || [];
  const guardrailsApplied = (decision.guardrails_applied as any[]) || [];

  // 3.0 CCC Request resolution — multi-signal lookup-or-create
  const cccCollectEv = events.find(
    (e) => e.stage === "decide" && e.kind === "substep_done" && e.data?.substep === "3.0.a",
  );
  const cccCreatedEv = events.find((e) => e.stage === "ccc" && e.kind === "created");
  const cccResolutionEv = events.find(
    (e) => e.stage === "decide" && e.kind === "substep_done" &&
      (e.data?.substep === "3.0" || e.data?.substep === "3.0.c"),
  );
  const cccCandidates: any[] = (cccCollectEv?.data as any)?.candidates || [];
  const cccCandidateCount = (cccCollectEv?.data as any)?.candidate_count ?? cccCandidates.length;
  const cccDecision = (cccResolutionEv?.data as any)?.ccc_action || ((cccResolutionEv?.data as any)?.adopted_case_id ? "update" : ((cccResolutionEv?.data as any)?.created_case_id ? "new" : null));
  const cccCaseUrl = ((cccCreatedEv?.data as any)?.links || {}).salesforce_case_url || ((cccResolutionEv?.data as any)?.links || {}).salesforce_case_url;
  const cccCaseNumber = (cccCreatedEv?.data as any)?.case_number || (cccResolutionEv?.data as any)?.case_number || pipe?.ccc_request?.case_number;
  const cccRequestNumber = (cccCreatedEv?.data as any)?.request_number || (cccResolutionEv?.data as any)?.request_number || pipe?.ccc_request?.request_number;
  const cccStatus: SubStepStatus = !hasDecide
    ? "pending"
    : cccResolutionEv
    ? "done"
    : state?.status === "running" || cccCollectEv
    ? "running"
    : "pending";

  const subSteps: SubStep[] = [
    {
      num: "3.0",
      name: "CCC Request resolution (check Salesforce + create if new)",
      status: cccStatus,
      result: cccResolutionEv
        ? (cccDecision === "new" || cccDecision === "new_after_cancelled"
            ? `created new Case ${cccCaseNumber || "-"} (${cccRequestNumber || "-"})`
            : cccDecision === "update"
            ? `adopted existing Case ${cccCaseNumber || "-"} → ccc_action=update`
            : cccDecision === "clone_change_order"
            ? `cloned Case ${cccCaseNumber || "-"} → ccc_action=clone_change_order`
            : `resolved (${cccCandidateCount} candidate(s))`)
        : cccCollectEv
        ? `${cccCandidateCount} candidate(s) collected; selecting…`
        : undefined,
      ms: cccCollectEv?.duration_ms ?? cccResolutionEv?.duration_ms ?? null,
      processing:
        "Multi-signal SOQL sweep against Salesforce Cases: PO_Number__c / WO_Number__c / Quote_Number__c / customer's open recent cases / email-thread parent. Each candidate is scored (PO +0.35, WO +0.30, Quote +0.25, open-recent +0.20, closed −0.30, account mismatch −0.40, thread parent +0.50). ≥0.70 adopt, 0.40–0.69 ambiguous (feasibility capped at 0.65), <0.40 create new.",
      provider: "Salesforce REST API (sf.query)",
      outputFields: cccResolutionEv
        ? [
            { label: "Decision", value: cccDecision || "new", mono: true },
            { label: "Case#", value: cccCaseNumber || "-", mono: true },
            { label: "Request #", value: cccRequestNumber || "-", mono: true },
            {
              label: "Candidates evaluated",
              value: cccCandidateCount > 0
                ? `${cccCandidateCount} candidate(s); top score ${cccCandidates[0]?.score ?? "-"}`
                : "0; no PO# / WO# / Quote# / open recent matches → creating new",
              mono: true,
            },
            ...(cccCandidates.length > 0
              ? [{
                  label: "Top candidates",
                  value: cccCandidates.slice(0, 5).map((c: any) =>
                    `${c.case_number || c.case_id} (status=${c.status || "?"} · score=${c.score} · signals=${(c.match_signals || []).join(",")})`
                  ).join("\n"),
                  mono: true, long: true,
                }]
              : []),
            { label: "Salesforce link", value: cccCaseUrl || "(linking…)", mono: true, link: cccCaseUrl || undefined },
          ]
        : undefined,
      rawData: cccResolutionEv?.data || cccCollectEv?.data,
    },
    {
      num: "3.1",
      name: "Reconcile vs quote",
      status: reconStatus,
      result:
        recon.checked === false
          ? "skipped: not a PO/Q2O intent"
          : recon.matched_quote
          ? `${recon.matched_quote.quote_number} · ${issuesCount} issue${issuesCount === 1 ? "" : "s"}`
          : reconStatus === "done"
          ? "no matching quote"
          : undefined,
      ms: reconResult?.duration_ms ?? null,
      processing: "Cross-reference extracted PO line items vs the matched Quote in CRM; emit price/qty/sku mismatches",
      provider: "ZBrain reconcile",
      inputPreview: pipe?.intent
        ? `intent='${pipe.intent}' · extracted PO=${pipe.extracted?.po_number || "-"} · quote_ref=${pipe.extracted?.quote_number || "-"}`
        : undefined,
      outputFields: [
        { label: "Checked?", value: recon.checked === false ? "skipped (intent isn't trade)" : "yes" },
        { label: "Matched quote", value: recon.matched_quote?.quote_number || "(none)", mono: true },
        { label: "Quote total (CRM)", value: recon.matched_quote?.total != null ? `$${(recon.matched_quote.total as number).toLocaleString()}` : "-" },
        { label: "Notes", value: recon.notes || "-" },
        { label: "Issues count", value: reconIssues.length },
        ...(reconIssues.length > 0
          ? [{ label: "Issues (full)", value: reconIssues.map((i: any, idx: number) => `${idx + 1}. ${JSON.stringify(i)}`).join("\n"), mono: true as const, long: true }]
          : []),
      ],
      rawData: recon,
    },
    {
      num: "3.2",
      name: "Confidence formula (KB-driven rubric)",
      status: confidenceStatus,
      result:
        confidenceStatus === "done"
          ? `${(conf ?? 0).toFixed(3)} → ${tier || "-"}`
          : undefined,
      processing: "Stage 3.1 walks the decision_confidence_rubric KB namespace: weighted_signals contribute weight × signal, then floor_caps step the running sum down per predicate. Operators tune weights and caps in /kb without code changes.",
      provider: "Stage3DecideAgent · KB-driven",
      kbNamespaces: ["decision_confidence_rubric"],
      inputPreview: Object.keys(signals).length
        ? `intent_confidence=${signals.intent_confidence}\nextraction_completeness=${signals.extraction_completeness}\ncustomer_match=${signals.customer_match}\nblocking_mismatches=${(signals.blocking_mismatches || []).length}\nsoft_mismatches=${(signals.soft_mismatches || []).length}`
        : undefined,
      outputFields:
        confidenceStatus === "done"
          ? (() => {
              const breakdown: any[] = Array.isArray((decision as any)?.confidence_breakdown)
                ? (decision as any).confidence_breakdown
                : [];
              const fmtDelta = (v: number) => (v >= 0 ? `+${v.toFixed(3)}` : v.toFixed(3));
              const longestLabel = breakdown.reduce(
                (n: number, e: any) => Math.max(n, (e.rule_key || "").length),
                0,
              );
              const padTo = Math.max(longestLabel, 32);
              const lines: string[] = [];
              for (const e of breakdown) {
                const label = (e.rule_key || "").padEnd(padTo);
                const tick = e.matched ? "✓" : "·";
                const kindBadge =
                  e.kind === "weighted_signal" ? "[signal]" :
                  e.kind === "floor_cap" ? "[cap]   " :
                  e.kind === "base" ? "[base]  " :
                  e.kind === "clamp" ? "[clamp] " :
                  "[other] ";
                if (e.kind === "weighted_signal") {
                  const w = (e.weight ?? 0).toFixed(2);
                  const sv = (e.signal_value ?? 0).toFixed(3);
                  lines.push(`  ${tick} ${kindBadge} ${label}  ${fmtDelta(Number(e.contribution ?? 0))}   = ${w} × ${sv}`);
                } else if (e.kind === "floor_cap" && e.matched) {
                  lines.push(`  ${tick} ${kindBadge} ${label}  ${fmtDelta(Number(e.contribution ?? 0))}   cap=${(e.cap ?? 1).toFixed(2)}  ← FIRED`);
                  if (e.evidence) {
                    lines.push(`              ${String(e.evidence).slice(0, 110)}`);
                  }
                } else if (e.kind === "floor_cap") {
                  lines.push(`  ${tick} ${kindBadge} ${label}                                   skipped`);
                } else if (e.kind === "base") {
                  lines.push(`  ${tick} ${kindBadge} ${label}  ${(e.running ?? 0).toFixed(3)}  (starting value)`);
                } else if (e.kind === "clamp") {
                  lines.push(`  ${tick} ${kindBadge} ${label}  running = ${(e.running ?? 0).toFixed(3)}`);
                }
              }
              lines.push("─".repeat(padTo + 28));
              lines.push(`Final confidence (after clamp + caps)        ${(conf ?? 0).toFixed(3)} → ${tier || "-"}`);

              return [
                { label: "Final confidence", value: `${Math.round((conf ?? 0) * 100)}% (${(conf ?? 0).toFixed(3)})`, mono: true as const },
                { label: "Autonomy tier", value: tier || "-", mono: true as const },
                { label: "Track-hint match", value: signals.track_hint_match ? "✓ yes" : "✗ no" },
                ...(breakdown.length > 0
                  ? [{
                      label: "Confidence breakdown (KB rubric)",
                      value: lines.join("\n"),
                      mono: true as const,
                      long: true as const,
                    }]
                  : []),
              ];
            })()
          : undefined,
      rawData: { signals, confidence_breakdown: (decision as any)?.confidence_breakdown },
    },
    {
      num: "3.3",
      name: "Business rules (KB-driven guardrails)",
      status: rulesStatus,
      result:
        rulesStatus === "done"
          ? `${firedCount} rule${firedCount === 1 ? "" : "s"} fired${
              guardrailsApplied.length
                ? ` · ${guardrailsApplied.length} guardrail${guardrailsApplied.length === 1 ? "" : "s"}`
                : ""
            }`
          : undefined,
      ms: businessRulesEval?.duration_ms ?? null,
      processing: "Predicate-driven evaluation of each KB business_rules entry against the AgentContext (intent, total, compliance flags, region, etc.)",
      provider: "BusinessRulesEvalTool",
      kbNamespaces: ["business_rules"],
      kbRulesUsed: businessRulesEval?.data?.data?.rules_evaluated?.map((r: any) => r.key) || [],
      outputFields: [
        { label: "Rules evaluated", value: businessRulesEval?.data?.data?.rules_evaluated?.length ?? 0 },
        { label: "Rules fired", value: firedCount },
        ...(Array.isArray(firedRules) && firedRules.length > 0
          ? firedRules.map((r: any, i: number) => ({
              label: `fired #${i + 1}`,
              value: typeof r === "string" ? r : `${r.key || r.name || "?"} · ${r.severity || "warn"} · ${r.message || ""}`,
              mono: true as const,
              long: true as const,
            }))
          : []),
        ...(guardrailsApplied.length > 0
          ? [{ label: "Guardrails applied (effects)", value: JSON.stringify(guardrailsApplied, null, 2), mono: true as const, long: true as const }]
          : []),
      ],
      rawData: businessRulesEval?.data?.data,
    },
    {
      num: "3.3",
      name: "Final tier decision",
      status: tierStatus,
      result:
        tier
          ? `${tier}${decision.action ? ` → ${ACTION_LABELS[decision.action] || decision.action}` : ""}`
          : undefined,
      processing: "Tier picked from final confidence: ≥0.95 → L4_AUTO, 0.80-0.94 → L3_ONE_CLICK, <0.80 → L2_HITL (and rules can cap)",
      inputPreview: `confidence=${(conf ?? 0).toFixed(3)} · rules_capped=${guardrailsApplied.length > 0 ? "yes" : "no"}`,
      outputFields: [
        { label: "Autonomy tier", value: tier || "-", mono: true },
        { label: "Action", value: decision.action ? `${ACTION_LABELS[decision.action] || decision.action} (${decision.action})` : "-" },
        { label: "Flow", value: decision.flow || "-", mono: true },
        { label: "Track hint", value: decision.track_hint || "-", mono: true },
        { label: "Misroute?", value: decision.misroute ? `yes: ${decision.misroute_reason || "?"}` : "no" },
        { label: "Reasoning", value: decision.reasoning_summary || "-", long: true },
      ],
      rawData: decision,
    },
    {
      num: "3.4",
      name: "Assign CCC Request owner",
      status: tierStatus,
      result: (() => {
        const o: any = (decision as any)?.owner || {};
        return o.owner_label ? `${o.owner_label}${o.owner_queue ? ` (${o.owner_queue})` : ""}` : undefined;
      })(),
      processing: "Pick CCC Request owner from (track + tier + fallout + AIOA outcome). The owner_mapping KB namespace supplies the human label and the Salesforce Queue Id. The orchestrator writes that Queue Id to Case.OwnerId so the case lands in the right queue in your SF org.",
      outputFields: (() => {
        const o: any = (decision as any)?.owner || {};
        const trk = (decision as any)?.track;
        const tracksTouched: string[] = (decision as any)?.tracks_touched || [];
        return [
          { label: "Primary track", value: trk || "-", mono: true as const },
          ...(tracksTouched.length > 0 ? [{ label: "Tracks touched", value: tracksTouched.join(" → "), mono: true as const }] : []),
          { label: "Owner label", value: o.owner_label || "-" },
          { label: "Owner queue", value: o.owner_queue || "-", mono: true as const },
          { label: "AI handled?", value: o.ai_handled ? "yes (no human queue)" : "no" },
          ...(o.salesforce_owner_id
            ? [{ label: "Salesforce queue", value: `${o.salesforce_queue_label || ""} (${o.salesforce_owner_id})`.trim(), mono: true as const }]
            : [{ label: "Salesforce queue", value: o.ai_handled ? "n/a (OwnerId stays on integration user)" : "not provisioned (Settings → Integrations → Provision)" }]),
          { label: "Reason", value: o.reason || "-", long: true as const },
        ];
      })(),
      rawData: (decision as any)?.owner,
    },
  ];

  // 3.5 · AIOA handoff — surface when Decide routed the case to the external
  // Order Acceptance validator. Substep_done event 3.0.c emits the
  // correlation_id; substep 3.0e emits the SLA deadline.
  const aioaQueuedEv = events.find(
    (e) => e.stage === "decide" && e.kind === "substep_done" && (e.data as any)?.substep === "3.0.c",
  );
  const aioaSlaEv = events.find(
    (e) => e.stage === "decide" && e.kind === "substep_done" && (e.data as any)?.substep === "3.0e",
  );
  if (aioaQueuedEv || pipe?.status === "awaiting_aioa") {
    const correlation = (aioaQueuedEv?.data as any)?.correlation_id;
    const provider = (aioaQueuedEv?.data as any)?.provider || "AIOA";
    const slaDeadline =
      (aioaSlaEv?.data as any)?.deadline ||
      (aioaSlaEv?.data as any)?.close_by ||
      (aioaSlaEv?.data as any)?.target;
    const liveStatus = pipe?.status === "awaiting_aioa" ? "queued · awaiting callback" : "completed";
    subSteps.push({
      num: "3.5",
      name: "AIOA handoff (external Order Acceptance validator)",
      status: pipe?.status === "awaiting_aioa" ? "running" : aioaQueuedEv ? "done" : "pending",
      result: pipe?.status === "awaiting_aioa"
        ? `parked · ${liveStatus}`
        : aioaQueuedEv
        ? `queued · correlation_id=${correlation || "-"}`
        : undefined,
      processing:
        "Builds the AIOA request payload from the extracted PO + customer + reconcile result, signs it, and POSTs to the configured Order Acceptance provider. The pipeline pauses here until the validator's callback returns PASS or FAIL (or the timeout window elapses). On PASS, Execute picks up and completes the workflow; on FAIL or timeout, the case rolls to HITL with a CSR clarification draft.",
      provider: String(provider),
      outputFields: [
        { label: "Provider", value: String(provider), mono: true as const },
        { label: "Correlation", value: correlation || "-", mono: true as const },
        { label: "Pipeline state", value: liveStatus, mono: true as const },
        ...(slaDeadline
          ? [{ label: "Callback SLA", value: new Date(slaDeadline).toLocaleString(), mono: true as const }]
          : []),
        {
          label: "Next step",
          value:
            pipe?.status === "awaiting_aioa"
              ? "Open the AIOA queue at /aioa to track the live status (queued → sent → response_received). Re-issue or escalate from there if needed."
              : "Validator responded; Execute resumed.",
          long: true as const,
        },
      ],
      rawData: aioaQueuedEv?.data,
    });
  }

  const resultLine = tier
    ? `tier=${tier} · confidence=${(conf ?? 0).toFixed(3)} · action=${decision.action || "-"}${
        issuesCount > 0 ? ` · ${issuesCount} mismatch${issuesCount === 1 ? "" : "es"}` : ""
      }${pipe?.status === "awaiting_aioa" ? " · parked at AIOA" : ""}`
    : pipe?.status === "awaiting_aioa"
    ? "parked at AIOA · awaiting external validator callback"
    : null;

  const stageEvents = events.filter((e) => e.stage === "decide" || e.stage === "reconcile");
  const notes = collectStageNotes(events, ["decide", "reconcile"]);

  const showSuggest = issuesCount > 0;
  const rightAction = showSuggest ? (
    <button
      onClick={onSuggest}
      disabled={suggesting || fix?.status === "drafting"}
      className="btn-primary text-xs py-1"
    >
      {suggesting || fix?.status === "drafting"
        ? "Drafting…"
        : fix?.status === "ready"
        ? "✎ Re-draft fix"
        : "✎ Suggest fix"}
    </button>
  ) : undefined;

  const rawData = { decision, reconcile: recon };

  return (
    <>
      <StageCardShell
        num={3}
        title="Decision & Confidence Scoring"
        state={state}
        subSteps={subSteps}
        resultLine={resultLine}
        rightAction={rightAction}
        toolbeltEvents={stageEvents}
        toolbeltStageKeys={["decide", "reconcile"]}
        notes={notes}
        rawData={rawData}
        pipelineId={pipe?.id}
        feedbackKey="decide"
        feedbackSnapshot={decision}
      />
      {fix?.status && fix.status !== "drafting" && <SuggestedFixCard fix={fix} />}
    </>
  );
}

function ExecuteStageCard({
  pipe,
  state,
  events,
}: {
  pipe: Pipeline | null;
  state?: StageStatus;
  events: TraceEvent[];
}) {
  const ex = pipe?.execution || {};
  const decision = pipe?.decision || {};
  const cm = pipe?.customer_match;

  const hasExecute = state?.status === "done" || state?.status === "running" || state?.status === "error";

  const sfCreateOrder = findToolEnd(events, "execute", "salesforce_create_order");
  const idempotentSkip = ex.idempotent_skip;
  const action = ex.action || decision.action;

  const guardrailStatus: SubStepStatus = !hasExecute
    ? "pending"
    : action === "discard"
    ? "skipped"
    : cm?.salesforce?.account?.Id || cm?.customer_id
    ? "done"
    : ex.reason?.includes("no Salesforce account")
    ? "error"
    : "done";

  const idempotencyStatus: SubStepStatus = !hasExecute
    ? "pending"
    : action === "discard"
    ? "skipped"
    : idempotentSkip
    ? "done"
    : ex.status
    ? "done"
    : state?.status === "running"
    ? "running"
    : "pending";

  const sfWriteStatus: SubStepStatus = !hasExecute
    ? "pending"
    : action === "discard"
    ? "skipped"
    : idempotentSkip
    ? "skipped"
    : sfCreateOrder
    ? sfCreateOrder.data?.ok === false
      ? "error"
      : "done"
    : ex.status === "applied"
    ? "done"
    : ex.status === "awaiting_one_click" || ex.status === "awaiting_hitl"
    ? "skipped"
    : state?.status === "running"
    ? "running"
    : "pending";

  const sfData = sfCreateOrder?.data?.data;
  const orderId = sfData?.order_id || sfData?.id;
  const orderStatus = sfData?.status;

  const sfApplied = (ex.applied || {}) as any;
  const sfBlock = sfApplied.salesforce || ex.draft || {};
  const lineItemsCreated = sfBlock.line_items_created;
  const sfOrderNumber = sfBlock.salesforce_order_number;

  const subSteps: SubStep[] = [
    {
      num: "4.1",
      name: "Customer-match guardrail",
      status: guardrailStatus,
      result:
        action === "discard"
          ? "skipped (discard)"
          : guardrailStatus === "error"
          ? "no SF account match"
          : cm?.customer_name
          ? `pass · ${cm.customer_name}`
          : "pass",
      processing: "Pre-execution gate. Refuses to write to Salesforce/ERP if Stage 2.3 did not resolve the customer to a real SF Account.",
      inputPreview: cm?.customer_name
        ? `Customer match: ${cm.customer_name} (${cm.customer_code || "-"}) · score=${cm.score} · basis=${cm.basis}`
        : "no customer match",
      outputFields: [
        { label: "Salesforce Account ID", value: (cm as any)?.salesforce_account_id || cm?.salesforce?.account?.Id || "-", mono: true },
        { label: "Match score", value: cm?.score != null ? `${Math.round((cm.score || 0) * 100)}%` : "-" },
        { label: "Match basis", value: cm?.basis || "-", mono: true },
        { label: "Source", value: (cm as any)?.source || "-", mono: true },
        { label: "Verdict", value: guardrailStatus === "error" ? "✗ blocked: no SF account" : "✓ pass" },
      ],
      rawData: cm,
    },
    {
      num: "4.2",
      name: "Duplicate-order check (existing Salesforce Order for this PO?)",
      status: idempotencyStatus,
      result:
        idempotentSkip
          ? `existing order found · skipped write`
          : idempotencyStatus === "done"
          ? "no duplicate"
          : undefined,
      processing: "Look up existing Salesforce Orders by PO number to avoid duplicate writes when the same email is reprocessed.",
      inputPreview: pipe?.extracted?.po_number ? `PO ref: ${pipe.extracted.po_number}` : undefined,
      outputFields: [
        { label: "PO checked", value: pipe?.extracted?.po_number || "-", mono: true },
        { label: "Existing order found?", value: idempotentSkip ? `yes: ${idempotentSkip.OrderNumber || idempotentSkip.Id || "match"}` : "no" },
        ...(idempotentSkip
          ? [
              { label: "Existing OrderNumber", value: idempotentSkip.OrderNumber || "-", mono: true as const },
              { label: "Existing Order Id", value: idempotentSkip.Id || "-", mono: true as const },
            ]
          : []),
      ],
      rawData: idempotentSkip || { skipped: false },
    },
    {
      num: "4.3",
      name: "Salesforce Order write",
      status: sfWriteStatus,
      result:
        idempotentSkip
          ? "skipped (idempotent)"
          : orderId
          ? `Order ${orderId}${orderStatus ? ` · ${orderStatus}` : ""}`
          : ex.status === "awaiting_one_click"
          ? "draft created · awaiting one-click"
          : ex.status === "awaiting_hitl"
          ? "skipped · awaiting HITL"
          : ex.status === "applied"
          ? "applied"
          : ex.status === "discarded"
          ? "skipped (discarded)"
          : undefined,
      ms: sfCreateOrder?.duration_ms ?? null,
      processing: "Create or activate a Salesforce Order with line items via REST. L4 → activate; L3 → draft (one-click activates); L2 → no write.",
      provider: "Salesforce REST",
      inputPreview: sfBlock?.payload
        ? JSON.stringify(sfBlock.payload, null, 2).slice(0, 600)
        : pipe?.extracted?.po_number
        ? `PO=${pipe.extracted.po_number} · ${(pipe.extracted.line_items || []).length} line items`
        : undefined,
      outputFields: [
        { label: "Action", value: action ? (ACTION_LABELS[action] || action) : "-", mono: true },
        { label: "Execution status", value: ex.status || "-", mono: true },
        ...(orderId ? [{ label: "Salesforce Order ID", value: orderId, mono: true as const }] : []),
        ...(sfOrderNumber ? [{ label: "OrderNumber", value: sfOrderNumber, mono: true as const }] : []),
        ...(orderStatus ? [{ label: "Order status", value: orderStatus }] : []),
        ...(lineItemsCreated != null ? [{ label: "Line items created", value: lineItemsCreated }] : []),
        ...(ex.status === "awaiting_hitl" ? [{ label: "HITL reason", value: ex.reason || "(low confidence: full review)" }] : []),
        ...(ex.status === "awaiting_one_click" ? [{ label: "Awaiting", value: "single-click activate" }] : []),
      ],
      rawResponse: sfCreateOrder?.data?.data ? JSON.stringify(sfCreateOrder.data.data, null, 2) : undefined,
      rawData: ex,
    },
  ];

  // Append any substep_done events emitted by the per-intent Stage 4 dispatch
  // (4.0 AIOA validation, 4.0a Existing-CCC handoff, 4.4 Attach evidence,
  // 4.5/4.6/4.7 CCC lifecycle, plus all the wo_*/service_*/trade_*/ssd_*
  // intent-specific substeps). Anything we don't already have hardcoded above
  // gets rendered from its trace event so the UI stays in sync with whatever
  // the backend dispatch emits.
  const _hardcoded = new Set(["4.1", "4.2", "4.3"]);
  const _seen = new Set<string>();
  const _dynamic: SubStep[] = [];
  for (const ev of events) {
    if (ev.stage !== "execute" || ev.kind !== "substep_done") continue;
    const num = (ev.data as any)?.substep;
    if (!num || _hardcoded.has(num) || _seen.has(num)) continue;
    _seen.add(num);
    const data = (ev.data as any) || {};
    const linksObj = data.links || {};
    const linkFields: { label: string; value: string; link?: string; mono?: boolean }[] = [];
    for (const [k, v] of Object.entries(linksObj)) {
      if (typeof v === "string" && v) {
        linkFields.push({ label: k.replace(/_/g, " "), value: v, link: v, mono: true });
      }
    }
    _dynamic.push({
      num,
      name: data.label || (ev.message || "").replace(/^\d+(\.\d+\w?)?\s*/, "").slice(0, 80) || `Substep ${num}`,
      status: "done",
      result: (ev.message || "").length > 140 ? (ev.message || "").slice(0, 140) + "…" : ev.message || undefined,
      ms: ev.duration_ms ?? null,
      outputFields: linkFields.length > 0 ? linkFields : undefined,
      rawData: data,
    });
  }
  // Stable ordering: 4.0 < 4.0a < 4.0b < 4.1 < 4.1a < ... < 4.7.
  const _all = [...subSteps, ..._dynamic].sort((a, b) => {
    const re = /^(\d+)\.(\d+)([a-z]?)/;
    const [, am, an, ax] = a.num.match(re) || ["", "0", "0", ""];
    const [, bm, bn, bx] = b.num.match(re) || ["", "0", "0", ""];
    if (am !== bm) return Number(am) - Number(bm);
    if (an !== bn) return Number(an) - Number(bn);
    return (ax || "").localeCompare(bx || "");
  });
  subSteps.length = 0;
  subSteps.push(..._all);

  const resultLine = ex.status
    ? `status=${ex.status} · action=${ACTION_LABELS[action] || action || "-"}${
        orderId ? ` · order=${orderId}` : ""
      }`
    : pipe?.status === "awaiting_aioa"
    ? "blocked · will run when AIOA returns PASS"
    : pipe?.status === "awaiting_hitl"
    ? "blocked · will run when HITL approves"
    : pipe?.status === "awaiting_one_click"
    ? "blocked · will run when CSR clicks Approve in the HITL one-click queue"
    : null;

  const stageEvents = events.filter((e) => e.stage === "execute");
  const notes = collectStageNotes(events, ["execute"]);

  return (
    <StageCardShell
      num={4}
      title="Workflow Execution"
      state={state}
      subSteps={subSteps}
      resultLine={resultLine}
      toolbeltEvents={stageEvents}
      toolbeltStageKeys={["execute"]}
      notes={notes}
      rawData={ex}
      pipelineId={pipe?.id}
      feedbackKey="execute"
      feedbackSnapshot={ex}
    />
  );
}

function CommunicateStageCard({
  pipe,
  state,
  events,
  setPreview,
}: {
  pipe: Pipeline | null;
  state?: StageStatus;
  events: TraceEvent[];
  setPreview: (p: PreviewItem | null) => void;
}) {
  const reply = pipe?.reply || {};
  const lang = reply.language;
  const detectedLang = pipe?.language;
  const soaUrl = pipe?.soa_url;
  const attachments: string[] = Array.isArray(reply.attachments) ? reply.attachments : [];

  const hasCommunicate = state?.status === "done" || state?.status === "running" || state?.status === "error";

  const translateTool = findToolEnd(events, "communicate", "translate_to_customer_language");
  const commLog = events.find((e) => e.stage === "communicate" && e.kind === "comm_log");

  const draftStatus: SubStepStatus = !hasCommunicate
    ? "pending"
    : reply.body
    ? "done"
    : reply.sent === false
    ? "skipped"
    : state?.status === "running"
    ? "running"
    : "pending";

  const translateStatus: SubStepStatus = !hasCommunicate
    ? "pending"
    : !detectedLang || detectedLang === "en"
    ? "skipped"
    : translateTool
    ? "done"
    : reply.body && lang === detectedLang
    ? "done"
    : state?.status === "running"
    ? "running"
    : "skipped";

  const attachStatus: SubStepStatus = !hasCommunicate
    ? "pending"
    : attachments.length > 0 || soaUrl
    ? "done"
    : "skipped";

  // Treat demo-lock as "done" (the comm log is the audit record; the lock is
  // intentional infrastructure config, not a failure). Only true skips render
  // as skipped now.
  const commLogStatus: SubStepStatus = !hasCommunicate
    ? "pending"
    : commLog
    ? "done"
    : pipe?.autonomy_tier === "L4_AUTO" && pipe?.status === "completed"
    ? "done"
    : reply.delivery_status === "blocked_by_demo_lock" || reply.delivery_status === "blocked_by_kill_switch"
    ? "done"
    : "skipped";

  const replyEnglish = reply.body_english || reply.body;
  const replyCustomerLang = reply.body_customer_language || reply.body;
  const subSteps: SubStep[] = [
    {
      num: "5.1",
      name: "Draft customer reply (LLM, English)",
      status: draftStatus,
      result:
        reply.body
          ? `${reply.subject ? `"${String(reply.subject).slice(0, 40)}${String(reply.subject).length > 40 ? "…" : ""}"` : "(no subject)"} · ${String(reply.body).length} chars`
          : reply.sent === false
          ? `no reply (${reply.reason || "-"})`
          : undefined,
      processing: "LLM drafts a polished English reply using the extracted PO/order summary, customer's quote ref, ship date, payment terms.",
      provider: "OpenAI gpt-5.2",
      inputPreview: pipe?.intent
        ? `intent='${pipe.intent}' · customer=${pipe?.customer_match?.customer_name || "-"}`
        : undefined,
      outputFields: [
        { label: "Subject", value: reply.subject || "-", mono: true },
        { label: "Body length", value: replyEnglish ? `${String(replyEnglish).length} chars` : "-" },
        { label: "Body (English, full)", value: replyEnglish || "(no body)", long: true },
      ],
      rawData: reply,
    },
    {
      num: "5.2",
      name: "Translate to customer language",
      status: translateStatus,
      result:
        translateStatus === "skipped" && (!detectedLang || detectedLang === "en")
          ? "skipped (en)"
          : lang
          ? `→ ${LANG_NAMES[lang] || lang}`
          : undefined,
      ms: translateTool?.duration_ms ?? null,
      processing: "If the customer's detected language ≠ en, translate the polished English reply using the same OpenAI strict-JSON path Stage 1.5 uses.",
      provider: "OpenAI gpt-5.2",
      inputPreview: detectedLang && detectedLang !== "en"
        ? `Source: en → Target: ${LANG_NAMES[detectedLang] || detectedLang}`
        : "skipped: customer language is en",
      outputFields:
        translateStatus === "skipped"
          ? [{ label: "Reason", value: detectedLang === "en" ? "customer is English-speaking; no translation needed" : "translate skipped" }]
          : [
              { label: "Source language", value: "en" },
              { label: "Target language", value: lang || detectedLang || "-" },
              { label: "Translated body (full)", value: replyCustomerLang || "-", long: true },
            ],
      promptSystem: translateTool?.data?.data?.prompt_system,
      promptUser: translateTool?.data?.data?.prompt_user,
      rawResponse: translateTool?.data?.data?.provider_response_raw,
    },
    {
      num: "5.3",
      name: "Attach SOA / file in SharePoint",
      status: attachStatus,
      result:
        attachments.length > 0
          ? attachments.slice(0, 2).join(", ") + (attachments.length > 2 ? ` +${attachments.length - 2}` : "")
          : soaUrl
          ? (pipe?.soa_sharepoint?.name || soaUrl.split("/").pop() || "SOA.pdf")
          : "none",
      processing: "Generate the SOA PDF, upload it to SharePoint (SalesOps/SOA folder), and stage the SharePoint link as the canonical attachment on the case. DocuNet handoff is appended only when that placeholder integration is enabled in Settings.",
      outputFields: [
        { label: "Attachments count", value: attachments.length || (soaUrl ? 1 : 0) },
        { label: "Files", value: (attachments.length > 0 ? attachments : soaUrl ? [pipe?.soa_sharepoint?.name || soaUrl.split("/").pop() || "SOA.pdf"] : ["(none)"]).join(", "), mono: true },
        ...(pipe?.soa_sharepoint?.web_url
          ? [
              { label: "Filed in SharePoint", value: pipe.soa_sharepoint.folder || "SalesOps/SOA", mono: true as const },
              { label: "SharePoint link", value: pipe.soa_sharepoint.web_url, mono: true as const, link: pipe.soa_sharepoint.web_url },
            ]
          : soaUrl
          ? [{ label: "Local SOA URL (SharePoint not connected)", value: soaUrl, mono: true as const, link: soaUrl }]
          : []),
      ],
      rawData: { attachments, soa_url: soaUrl, soa_sharepoint: pipe?.soa_sharepoint, soa_path: reply.soa_path, soa_attachment: reply.soa_attachment },
    },
    {
      num: "5.4",
      name: "Communication log written",
      status: commLogStatus,
      result:
        commLog
          ? "L4 auto-write"
          : commLogStatus === "skipped"
          ? "deferred (HITL or non-L4)"
          : undefined,
      processing: "L4 auto: write a CommunicationLog row + send via SMTP. L3/L2: defer until HITL approval.",
      outputFields: [
        { label: "Tier", value: pipe?.autonomy_tier || "-", mono: true },
        { label: "CommLog created?", value: commLog ? "yes" : "no" },
        {
          label: "Sent?",
          value: reply.sent === true
            ? "yes"
            : reply.delivery_status === "blocked_by_demo_lock"
            ? "queued (demo mode: outbound transmission locked; the CommLog row is the audit trail)"
            : reply.delivery_status === "blocked_by_kill_switch"
            ? "queued (outbound kill switch is on)"
            : reply.sent === false
            ? `no (${reply.reason || "-"})`
            : "pending",
        },
      ],
      rawData: commLog?.data,
    },
  ];

  const resultLine = reply.body
    ? `language=${lang || "-"} · ${String(reply.body).length} chars${
        attachments.length > 0 ? ` · ${attachments.length} attachment${attachments.length === 1 ? "" : "s"}` : ""
      }`
    : reply.sent === false
    ? `no reply drafted (${reply.reason || "-"})`
    : pipe?.status === "awaiting_aioa"
    ? "blocked · will draft + send when AIOA returns PASS"
    : pipe?.status === "awaiting_hitl"
    ? "blocked · reply drafts when HITL approves"
    : pipe?.status === "awaiting_one_click"
    ? "blocked · reply sends on CSR one-click approve"
    : null;

  const rightAction = soaUrl ? (
    <button
      onClick={() => setPreview({ name: soaUrl.split("/").pop() || "SOA.pdf", url: soaUrl })}
      className="pill bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
    >
      SOA PDF
    </button>
  ) : undefined;

  const stageEvents = events.filter((e) => e.stage === "communicate");
  const notes = collectStageNotes(events, ["communicate"]);

  return (
    <StageCardShell
      num={5}
      title="Communication & Close-out"
      state={state}
      subSteps={subSteps}
      resultLine={resultLine}
      rightAction={rightAction}
      toolbeltEvents={stageEvents}
      toolbeltStageKeys={["communicate"]}
      notes={notes}
      rawData={reply}
      pipelineId={pipe?.id}
      feedbackKey="communicate"
      feedbackSnapshot={reply}
    />
  );
}

function SuggestedFixCard({ fix }: { fix: NonNullable<Pipeline["suggested_fix"]> }) {
  const [showRaw, setShowRaw] = useState(false);
  if (fix.status === "error") {
    return (
      <div className="card p-3 border-rose-200">
        <div className="text-xs text-rose-700">Suggested fix failed: {fix.error}</div>
      </div>
    );
  }
  return (
    <div className="card overflow-hidden ring-1 ring-zbrain/40">
      <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between bg-zbrain-50/40">
        <div className="text-sm font-semibold flex items-center gap-2">
          ✎ Suggested corrective email
          <span className="pill bg-zbrain-50 text-zbrain text-[10px]">
            {LANG_NAMES[(fix.language || "").toLowerCase()] || fix.language}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              const text = (fix.subject ? `Subject: ${fix.subject}\n\n` : "") + (fix.body || "");
              navigator.clipboard.writeText(text);
            }}
            className="btn-secondary text-xs"
          >
            Copy
          </button>
          <button onClick={() => setShowRaw((v) => !v)} className="text-xs text-zbrain hover:underline">
            {showRaw ? "polished" : "show raw"}
          </button>
        </div>
      </div>
      {showRaw ? (
        <pre className="text-[11px] bg-slate-50 p-3 max-h-72 overflow-auto whitespace-pre-wrap">
          {JSON.stringify(fix, null, 2)}
        </pre>
      ) : (
        <div className="p-4">
          {fix.subject && <div className="text-sm font-semibold mb-2">Subject: {fix.subject}</div>}
          <pre className="text-[12px] whitespace-pre-wrap bg-zbrain-surface border border-zbrain-divider rounded p-3 max-h-80 overflow-auto">
            {fix.body}
          </pre>
        </div>
      )}
    </div>
  );
}

function ActivityLog({ events }: { events: TraceEvent[] }) {
  // Surface common deep-link URL keys as actual clickable affordances above
  // the raw JSON. Operators kept asking "where is the Salesforce case?
  // where did the file go?" — the URLs were in the event data already, just
  // not rendered as links. This block makes them one-click.
  const extractLinks = (data: any): { label: string; href: string }[] => {
    if (!data || typeof data !== "object") return [];
    const out: { label: string; href: string }[] = [];
    const sfc = data.salesforce_case_url || data.sf_case_url;
    if (typeof sfc === "string" && sfc.startsWith("http")) out.push({ label: "Open Salesforce Case", href: sfc });
    const sp = data.sharepoint_url || data.sharepoint_web_url || (data.sharepoint || {}).web_url;
    if (typeof sp === "string" && sp.startsWith("http")) out.push({ label: "Open in SharePoint", href: sp });
    if (Array.isArray(data.uploaded)) {
      for (const u of data.uploaded) {
        if (u && typeof u.web_url === "string" && u.web_url.startsWith("http")) {
          out.push({ label: `SharePoint: ${u.name || "file"}`, href: u.web_url });
        }
      }
    }
    return out;
  };
  return (
    <div className="card overflow-hidden">
      <div className="divide-y divide-zbrain-divider max-h-[60vh] overflow-auto">
        {events.map((ev) => {
          const links = extractLinks(ev.data);
          return (
            <div key={ev.id} className="p-3 hover:bg-zbrain-50/40">
              <div className="flex items-center gap-2 text-xs">
                <span className="font-mono text-zbrain-muted">{new Date(ev.ts).toLocaleTimeString()}</span>
                <span className="pill bg-slate-100 text-slate-700">{ev.stage}</span>
                <span className="pill bg-zbrain-50 text-zbrain">{ev.kind}</span>
                {ev.duration_ms != null && <span className="text-zbrain-muted">{ev.duration_ms} ms</span>}
              </div>
              <div className="mt-1 text-sm">{ev.message}</div>
              {links.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {links.map((l, i) => (
                    <a
                      key={i}
                      href={l.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[11px] text-zbrain hover:underline pill bg-zbrain-50 border border-zbrain-200"
                    >
                      {l.label} ↗
                    </a>
                  ))}
                </div>
              )}
              {ev.data && Object.keys(ev.data).length > 0 && (
                <pre className="mt-1.5 text-[11px] bg-slate-50 border border-zbrain-divider rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap">
                  {JSON.stringify(ev.data, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Renders the email thread chain for the current pipeline.
 *
 * Hidden when there's only 1 message on the thread (no thread to show).
 * The root message (primary intent source) is highlighted; subsequent replies
 * show as a vertical timeline. Cross-pipeline executions on the same thread
 * are surfaced at the bottom — that's the idempotency log, useful for "this
 * action was already taken by an earlier pipeline on this thread."
 */
function ThreadContextPanel({ pipelineId }: { pipelineId: number }) {
  const [thread, setThread] = useState<ThreadResponse | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    let cancel = false;
    api
      .getThread(pipelineId)
      .then((t) => {
        if (!cancel) setThread(t);
      })
      .catch(() => {
        if (!cancel) setThread(null);
      });
    return () => {
      cancel = true;
    };
  }, [pipelineId]);

  if (!thread || thread.message_count <= 1) return null;

  const toggle = (id: number) => {
    setExpandedIds((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider bg-sky-50/40 flex items-center gap-3">
        <div className="w-7 h-7 rounded bg-sky-100 text-sky-700 flex items-center justify-center font-semibold text-xs">
          T
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-sky-700">
            Email thread context
          </div>
          <div className="text-sm font-semibold text-zbrain-ink">
            {thread.message_count} message{thread.message_count === 1 ? "" : "s"} on this conversation
            {thread.thread_normalized_subject && (
              <span className="text-zbrain-muted font-normal">
                {" · "}
                {thread.thread_normalized_subject.slice(0, 60)}
              </span>
            )}
          </div>
        </div>
        <div className="text-[10px] text-zbrain-muted text-right">
          Root drives intent · replies add context
        </div>
      </div>

      <div className="px-4 py-3 space-y-2">
        {thread.messages.map((m, i) => {
          const isExpanded = expandedIds.has(m.id);
          const isRoot = m.is_root;
          const ts = m.received_at ? new Date(m.received_at) : null;
          return (
            <div
              key={m.id}
              className={`relative pl-6 ${i < thread.messages.length - 1 ? "pb-2" : ""}`}
            >
              {/* timeline line + dot */}
              <span
                className={`absolute left-[7px] top-1 w-2 h-2 rounded-full ${
                  isRoot ? "bg-sky-600" : "bg-zbrain-divider"
                }`}
              />
              {i < thread.messages.length - 1 && (
                <span className="absolute left-[10px] top-3 bottom-0 w-px bg-zbrain-divider" />
              )}

              <div
                className={`border rounded-md ${
                  isRoot
                    ? "border-sky-300 bg-sky-50/30"
                    : "border-zbrain-divider bg-white"
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggle(m.id)}
                  className="w-full px-3 py-2 flex items-start gap-2 hover:bg-slate-50/40 transition text-left"
                >
                  <span className="text-zbrain-muted text-xs font-mono mt-0.5 shrink-0">
                    {String(m.position).padStart(2, "0")}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      {isRoot && (
                        <span className="pill bg-sky-100 text-sky-800 border border-sky-300 text-[10px]">
                          ROOT · primary intent source
                        </span>
                      )}
                      <span className="text-xs font-semibold text-zbrain-ink truncate">
                        {m.from_address || "(unknown sender)"}
                      </span>
                      {m.attachments && m.attachments.length > 0 && (
                        <span className="pill bg-amber-50 text-amber-800 border border-amber-200 text-[10px]">
                          {m.attachments.length} attachment{m.attachments.length === 1 ? "" : "s"}
                        </span>
                      )}
                      {m.language_hint && m.language_hint !== "en" && (
                        <span className="pill bg-violet-50 text-violet-800 border border-violet-200 text-[10px] uppercase">
                          {m.language_hint}
                        </span>
                      )}
                      {m.pipeline_id && m.pipeline_id !== pipelineId && (
                        <Link
                          to={`/trace/${m.pipeline_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="pill bg-slate-50 text-zbrain-muted border border-zbrain-divider text-[10px] hover:bg-slate-100"
                          title={`This message was processed in pipeline ${m.pipeline_id}`}
                        >
                          pipeline #{m.pipeline_id}
                        </Link>
                      )}
                    </div>
                    <div className="text-xs text-zbrain-muted truncate mt-0.5">
                      {ts && (
                        <span className="tabular-nums">
                          {ts.toLocaleString(undefined, {
                            year: "numeric",
                            month: "short",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      )}
                      {m.subject && <span> · {m.subject}</span>}
                    </div>
                    {!isExpanded && (
                      <div className="text-xs text-zbrain-ink mt-1.5 line-clamp-2 whitespace-pre-wrap">
                        {m.body_preview}
                      </div>
                    )}
                  </div>
                  <span className={`text-zbrain-muted text-xs mt-1 transition ${isExpanded ? "rotate-90" : ""}`}>
                    ▶
                  </span>
                </button>
                {isExpanded && (
                  <div className="px-3 pb-3 border-t border-zbrain-divider">
                    <pre className="text-[11px] whitespace-pre-wrap font-sans text-zbrain-ink mt-2">
                      {m.body_preview}
                      {m.body_chars > m.body_preview.length && (
                        <span className="text-zbrain-muted italic">
                          {"\n\n... "}({m.body_chars - m.body_preview.length} more chars){"\n"}
                        </span>
                      )}
                    </pre>
                    {m.attachments && m.attachments.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {m.attachments.map((a, idx) => (
                          <span
                            key={idx}
                            className="pill bg-slate-50 text-zbrain-muted border border-zbrain-divider text-[10px]"
                          >
                            📎 {a.name || "(unnamed)"}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {thread.executions.length > 0 && (
        <div className="border-t border-zbrain-divider bg-slate-50/30 px-4 py-2">
          <div className="text-[10px] uppercase tracking-wider text-zbrain-muted mb-1">
            Cross-pipeline execution log (idempotency)
          </div>
          <div className="space-y-0.5">
            {thread.executions.map((e) => (
              <div
                key={e.id}
                className="text-[11px] flex items-center gap-2 font-mono text-zbrain-muted"
              >
                <span className={e.succeeded ? "text-emerald-700" : "text-rose-600"}>
                  {e.succeeded ? "✓" : "✗"}
                </span>
                <span className="text-zbrain-ink">{e.action}</span>
                <span className="text-zbrain-muted font-mono text-[10px]" title={`Idempotency key: ${e.args_hash}`}>id {e.args_hash.slice(0, 6)}</span>
                {e.pipeline_id && (
                  <Link
                    to={`/trace/${e.pipeline_id}`}
                    className={
                      e.pipeline_id === pipelineId
                        ? "text-zbrain-muted"
                        : "text-zbrain hover:underline"
                    }
                  >
                    pipeline #{e.pipeline_id}
                    {e.pipeline_id === pipelineId && " (this)"}
                  </Link>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// === Activity list (no pipeline selected) ===
// When a user navigates to /trace without a specific case ID, show a list of
// recent cases so they can drill into stage-level work for any one of them.
// Optional ?stage=<key> query param scopes the list to cases that touched
// that processing stage; the selected stage is forwarded to the case detail
// page so the drill-down opens directly at the relevant tab.

const STAGE_META: Record<string, { name: string; tagline: string }> = {
  intake: {
    name: "Intake & Classification",
    tagline: "Cases that have completed the intake stage.",
  },
  extract: {
    name: "Extraction & Enrichment",
    tagline: "Cases that have completed the extraction stage.",
  },
  decide: {
    name: "Decision & Confidence Scoring",
    tagline: "Cases that have been scored against the four-gate confidence model.",
  },
  execute: {
    name: "Workflow Execution",
    tagline: "Cases that triggered system-of-record writes or were routed to a CSR.",
    },
  communicate: {
    name: "Communication & Close-out",
    tagline: "Cases that reached the customer-reply step.",
  },
  learning: {
    name: "Continuous Learning",
    tagline: "Cases where CSR feedback or corrections were captured.",
  },
};

// Canonical intent labels shown in the Activities intent filter. Kept aligned
// with src/pages/Dashboard.tsx INTENT_LABEL so the same intent reads the same
// human-readable name across the app.
const ACTIVITY_INTENT_LABEL: Record<string, string> = {
  po_intake: "PO intake",
  quote_to_order: "Quote to Order",
  trade_change_order: "Trade change order",
  ssd_change_request: "SSD change request",
  hold_release: "Hold release",
  delivery_change: "Delivery change",
  service_order: "Service order",
  wo_update_request: "WO update",
  wo_status_inquiry: "WO status inquiry",
  service_contract_request: "Service contract",
  general_inquiry: "General inquiry",
  out_of_scope: "Out of scope",
  spam: "Spam",
  kso: "KSO restricted",
  collections: "Collections",
  portal_admin: "Portal admin",
  brazil_tax: "Brazil tax",
  undeliverable: "Undeliverable",
};

function activityIntentLabel(intent: string | null | undefined): string {
  if (!intent) return "Unclassified";
  return ACTIVITY_INTENT_LABEL[intent] || intent;
}

function ActivityList() {
  const [rows, setRows] = useState<CaseRow[] | null>(null);
  const [filter, setFilter] = useState<"all" | "running" | "completed" | "hitl">("all");
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const stageKey = searchParams.get("stage") || "";
  const intentKey = searchParams.get("intent") || "";
  const stageMeta = STAGE_META[stageKey] || null;

  useEffect(() => {
    let cancel = false;
    const refresh = async () => {
      try {
        const cases = await api.analytics.cases(stageKey || undefined);
        if (!cancel) setRows(cases);
      } catch {
        if (!cancel) setRows([]);
      }
    };
    refresh();
    const id = setInterval(refresh, 10000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [stageKey]);

  const cases = rows || [];

  // Intent filter applies first, then status/HITL filter on top. Counts
  // displayed on each status chip reflect the intent-scoped subset so a CSR
  // toggling an intent sees the matching status volumes immediately.
  const intentScoped = useMemo(() => {
    if (!intentKey) return cases;
    return cases.filter((c) => (c.intent || "") === intentKey);
  }, [cases, intentKey]);

  const filtered = useMemo(() => {
    const src = intentScoped;
    if (filter === "all") return src;
    if (filter === "running") return src.filter((c) => c.status === "running");
    if (filter === "completed") return src.filter((c) => c.status === "completed");
    if (filter === "hitl") return src.filter((c) => c.autonomy_tier === "L2_HITL" || c.status === "awaiting_hitl");
    return src;
  }, [intentScoped, filter]);

  const counts = useMemo(() => {
    return {
      all: intentScoped.length,
      running: intentScoped.filter((c) => c.status === "running").length,
      completed: intentScoped.filter((c) => c.status === "completed").length,
      hitl: intentScoped.filter((c) => c.autonomy_tier === "L2_HITL" || c.status === "awaiting_hitl").length,
    };
  }, [intentScoped]);

  // Build the intent dropdown options from the loaded case set so the
  // operator only sees intents present in the current stage scope. Counts
  // are per-intent on the full (non-intent-filtered) case list.
  const intentOptions = useMemo(() => {
    const tally = new Map<string, number>();
    for (const c of cases) {
      const k = c.intent || "";
      tally.set(k, (tally.get(k) || 0) + 1);
    }
    return Array.from(tally.entries())
      .map(([key, n]) => ({ key, label: activityIntentLabel(key), count: n }))
      .sort((a, b) => b.count - a.count);
  }, [cases]);

  const clearStage = () => {
    searchParams.delete("stage");
    setSearchParams(searchParams, { replace: true });
  };

  const openCase = (pipelineId: number) => {
    const detailPath = stageKey
      ? `/trace/${pipelineId}?stage=${stageKey}`
      : `/trace/${pipelineId}`;
    navigate(detailPath);
  };

  const setStage = (k: string) => {
    if (k) searchParams.set("stage", k);
    else searchParams.delete("stage");
    setSearchParams(searchParams, { replace: true });
  };

  const setIntent = (k: string) => {
    if (k) searchParams.set("intent", k);
    else searchParams.delete("intent");
    setSearchParams(searchParams, { replace: true });
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-[22px] font-semibold tracking-tight text-zbrain-ink dark:text-zbrain-dark-ink">
          Activities
        </h1>
        <p className="text-sm text-zbrain-muted dark:text-zbrain-dark-muted mt-1">
          Every case the solution has processed. Filter by stage or status below; click a row to open the stage-level activity.
        </p>
      </header>

      {/* Stage filter — usable directly from this page, no Dashboard round-trip required */}
      <div className="card p-3 flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold mr-1">Stage:</span>
        <FilterChip active={!stageKey} onClick={() => setStage("")} label="All stages" />
        {Object.entries(STAGE_META).map(([k, m]) => (
          <FilterChip key={k} active={stageKey === k} onClick={() => setStage(k)} label={m.name} />
        ))}
      </div>

      {/* Intent filter: matches the intent vocabulary the Dashboard Case-mix
          tile uses, so an operator can drill from a Dashboard intent slice
          straight into the cases that contributed to it. */}
      <div className="card p-3 flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold mr-1">Intent:</span>
        <FilterChip
          active={!intentKey}
          onClick={() => setIntent("")}
          label={`All intents (${cases.length})`}
        />
        {intentOptions.map((opt) => (
          <FilterChip
            key={opt.key || "_unclassified"}
            active={intentKey === opt.key}
            onClick={() => setIntent(opt.key)}
            label={`${opt.label} (${opt.count})`}
          />
        ))}
      </div>

      {stageMeta && (
        <div className="rounded-lg border border-zbrain-primary/30 bg-zbrain-primary/5 px-4 py-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-primary font-semibold">Stage focus</div>
            <div className="text-sm font-semibold text-zbrain-ink mt-0.5">{stageMeta.name}</div>
            <div className="text-xs text-zbrain-muted mt-0.5">{stageMeta.tagline}</div>
          </div>
          <button
            onClick={clearStage}
            className="text-xs font-medium text-zbrain-primary hover:underline shrink-0"
          >
            Clear stage filter
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 text-sm flex-wrap">
        <span className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold mr-1">Status:</span>
        <FilterChip active={filter === "all"} onClick={() => setFilter("all")} label={`All (${counts.all})`} />
        <FilterChip active={filter === "running"} onClick={() => setFilter("running")} label={`Running (${counts.running})`} />
        <FilterChip active={filter === "completed"} onClick={() => setFilter("completed")} label={`Completed (${counts.completed})`} />
        <FilterChip active={filter === "hitl"} onClick={() => setFilter("hitl")} label={`HITL (${counts.hitl})`} />
      </div>

      {rows === null ? (
        <div className="card p-10 text-center text-sm text-zbrain-muted">Loading cases…</div>
      ) : filtered.length === 0 ? (
        <div className="card p-12 text-center">
          <div className="text-sm font-medium text-zbrain-ink">No cases match this filter</div>
          <div className="text-xs text-zbrain-muted mt-1">
            {stageMeta ? "No cases have reached this stage yet." : "Cases appear here once inbound email has been processed."}
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-zbrain-surface text-[11px] uppercase tracking-wider text-zbrain-muted">
              <tr className="border-b border-zbrain-divider">
                <th className="text-left px-4 py-2.5 font-semibold">Case</th>
                <th className="text-left px-3 py-2.5 font-semibold">Intent</th>
                <th className="text-left px-3 py-2.5 font-semibold">Customer</th>
                <th className="text-left px-3 py-2.5 font-semibold">Language</th>
                <th className="text-left px-3 py-2.5 font-semibold">Tier</th>
                <th className="text-left px-3 py-2.5 font-semibold">Confidence</th>
                <th className="text-left px-3 py-2.5 font-semibold">Status</th>
                <th className="text-left px-3 py-2.5 font-semibold">Received</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zbrain-divider/70">
              {filtered.map((c) => (
                <tr
                  key={c.pipeline_id}
                  className="hover:bg-zbrain-surface cursor-pointer"
                  onClick={() => openCase(c.pipeline_id)}
                >
                  <td className="px-4 py-2.5">
                    <div className="text-zbrain-ink font-medium truncate max-w-[280px]">{c.subject || "(no subject)"}</div>
                    <div className="text-[11px] text-zbrain-muted font-mono">#{c.pipeline_id} · {c.from}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <IntentPill intent={c.intent} />
                  </td>
                  <td className="px-3 py-2.5 text-zbrain-ink">{c.customer_name || "-"}</td>
                  <td className="px-3 py-2.5 text-zbrain-muted uppercase text-[11px] font-mono">{c.language || c.language_hint || "-"}</td>
                  <td className="px-3 py-2.5"><TierPill tier={c.autonomy_tier} /></td>
                  <td className="px-3 py-2.5 w-32"><ConfidenceBar value={c.confidence} /></td>
                  <td className="px-3 py-2.5"><StatusPill status={c.status || "running"} /></td>
                  <td className="px-3 py-2.5 text-[11px] text-zbrain-muted whitespace-nowrap">
                    {c.received_at ? new Date(c.received_at).toLocaleString() : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FilterChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-full text-[12px] font-medium border transition-colors ${
        active
          ? "bg-zbrain text-white border-zbrain shadow-sm"
          : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface"
      }`}
    >
      {label}
    </button>
  );
}

// =========================================================================
// Verification panel — declarative invariants evaluated at each stage
// boundary. Rows are derived from the `verification.checked` trace events
// the backend emits via `agents/pipeline_verifier.py`. Each event carries a
// `results` array with one entry per rule that ran at that hook.
// =========================================================================
function VerificationPanel({ events }: { events: TraceEvent[] }) {
  const verifyEvents = events.filter((e) => e.stage === "verification" && e.kind === "checked");
  const llmAudit = events.find((e) => e.stage === "verification" && e.kind === "llm_audit");
  const halted = events.find((e) => e.stage === "verification" && e.kind === "halted");

  if (verifyEvents.length === 0 && !llmAudit && !halted) return null;

  // Flatten results across all hooks, but keep the latest verdict per rule.
  // (Same rule may evaluate at stage_end:decide AND at final — we surface the
  // most recent verdict.)
  const latestByRule: Record<string, any> = {};
  const ruleHookHistory: Record<string, string[]> = {};
  let totalEvaluations = 0;
  for (const ev of verifyEvents) {
    const data = (ev.data as any) || {};
    const results: any[] = data.results || [];
    const hook = data.hook || "?";
    for (const r of results) {
      if (!r?.rule_key) continue;
      totalEvaluations += 1;
      latestByRule[r.rule_key] = r;
      ruleHookHistory[r.rule_key] = [...(ruleHookHistory[r.rule_key] || []), hook];
    }
  }
  const rules = Object.values(latestByRule) as any[];
  const blockers = rules.filter((r) => r.verdict === "fail" && r.severity === "block" && r.mode === "active");
  const warnings = rules.filter((r) => r.verdict === "fail" && r.severity === "warn" && r.mode === "active");
  const audits = rules.filter((r) => r.verdict === "fail" && (r.severity === "audit" || r.mode === "shadow"));
  const passes = rules.filter((r) => r.verdict === "pass");
  const errors = rules.filter((r) => r.verdict === "error");

  // Group rules so the most actionable verdicts surface first. Blockers are
  // the only thing an admin must read. Warnings + audits are interesting but
  // not stopping the case. Passes are reassurance. Skipped (n/a) rules clutter
  // the panel — collapse them by default.
  const blockerRules = rules.filter((r) => r.verdict === "fail" && r.severity === "block" && r.mode === "active");
  const warnRules = rules.filter((r) => r.verdict === "fail" && r.severity === "warn" && r.mode === "active");
  const auditRules = rules.filter((r) => r.verdict === "fail" && (r.severity === "audit" || r.mode === "shadow"));
  const errorRules = rules.filter((r) => r.verdict === "error");
  const passRules = rules.filter((r) => r.verdict === "pass");
  const skippedRules = rules.filter((r) => r.verdict === "n/a" || r.verdict === "skipped");

  return (
    <section className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-zbrain-divider flex items-center justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zbrain-ink">Pipeline verification</h2>
          <p className="text-[11.5px] text-zbrain-muted mt-0.5">
            Declarative invariants the orchestrator evaluates at every stage boundary and at close.
            Each rule is an <em>applies-when</em> predicate + an <em>invariant</em> predicate + a severity + a
            corrective action. Failing block-severity rules halt or downgrade the case automatically; failing
            warn/audit rules record evidence without changing the outcome.{" "}
            <Link
              to="/kb?ns=pipeline_verification_rules"
              className="text-zbrain hover:underline whitespace-nowrap"
            >
              Edit rules in Knowledge Base →
            </Link>
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {blockers.length > 0 && <span className="pill bg-rose-100 text-rose-700">{blockers.length} block</span>}
          {warnings.length > 0 && <span className="pill bg-amber-100 text-amber-800">{warnings.length} warn</span>}
          {audits.length > 0 && <span className="pill bg-slate-100 text-slate-700">{audits.length} audit</span>}
          {errors.length > 0 && <span className="pill bg-rose-50 text-rose-700">{errors.length} error</span>}
          <span className="pill bg-emerald-100 text-emerald-700">{passes.length} pass</span>
        </div>
      </header>
      {halted && (
        <div className="px-5 py-2 bg-rose-50 border-b border-rose-200 text-[12.5px] text-rose-800">
          <strong>Halted by verifier:</strong> {halted.message}
        </div>
      )}
      <VerificationGroup title="Blocking failures" tone="rose"   rows={blockerRules} hookHistory={ruleHookHistory} defaultOpen />
      <VerificationGroup title="Warnings"          tone="amber"  rows={warnRules}    hookHistory={ruleHookHistory} defaultOpen />
      <VerificationGroup title="Audit / shadow failures" tone="slate" rows={auditRules}   hookHistory={ruleHookHistory} defaultOpen={false} />
      <VerificationGroup title="Evaluator errors" tone="rose"   rows={errorRules}   hookHistory={ruleHookHistory} defaultOpen />
      <VerificationGroup title="Passed"            tone="emerald" rows={passRules}    hookHistory={ruleHookHistory} defaultOpen={false} />
      <VerificationGroup title="Not applicable"    tone="slate"  rows={skippedRules} hookHistory={ruleHookHistory} defaultOpen={false} />
      {llmAudit && (
        <div className="px-5 py-3 border-t border-zbrain-divider bg-zbrain-surface/40">
          <div className="text-[10px] uppercase tracking-[0.14em] font-semibold text-zbrain-muted">LLM second-opinion</div>
          <div className="text-[12.5px] text-zbrain-ink mt-0.5">{llmAudit.message}</div>
        </div>
      )}
      <div className="px-5 py-2 border-t border-zbrain-divider bg-zbrain-surface/30 text-[10.5px] text-zbrain-muted flex items-center justify-between">
        <span>{rules.length} rule{rules.length === 1 ? "" : "s"} evaluated · {totalEvaluations} total checks across {verifyEvents.length} stage boundary(ies)</span>
        <Link to="/kb?ns=pipeline_verification_rules" className="text-zbrain hover:underline">Edit rules →</Link>
      </div>
    </section>
  );
}

// One collapsible group of verification rows. Blockers + warnings + errors
// open by default; passes + n/a stay collapsed (an admin can expand if they
// want reassurance). Each row shows the rule label, plain-English
// description, the applies-when / invariant predicates (for failed rows),
// and the corrective action the verifier would take. The rule_key pill is
// a deep-link to the KB row so an admin lands directly on the editable rule.
function VerificationGroup({
  title,
  tone,
  rows,
  hookHistory,
  defaultOpen,
}: {
  title: string;
  tone: "rose" | "amber" | "emerald" | "slate";
  rows: any[];
  hookHistory: Record<string, string[]>;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState<boolean>(defaultOpen);
  if (!rows.length) return null;
  const toneCls =
    tone === "rose" ? "bg-rose-50 text-rose-800 border-rose-200"
    : tone === "amber" ? "bg-amber-50 text-amber-900 border-amber-200"
    : tone === "emerald" ? "bg-emerald-50 text-emerald-800 border-emerald-200"
    : "bg-slate-50 text-slate-700 border-slate-200";
  const dotCls =
    tone === "rose" ? "bg-rose-500"
    : tone === "amber" ? "bg-amber-500"
    : tone === "emerald" ? "bg-emerald-500"
    : "bg-slate-400";
  return (
    <div className="border-t border-zbrain-divider">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`w-full px-5 py-2 flex items-center justify-between text-left border-l-4 ${toneCls} hover:brightness-[0.98]`}
      >
        <span className="flex items-center gap-2 text-[12.5px] font-semibold">
          <span className={`inline-block w-2 h-2 rounded-full ${dotCls}`} />
          {title}
          <span className="text-[11px] font-normal opacity-80">({rows.length})</span>
        </span>
        <span className="text-[11px] opacity-70">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <ul className="divide-y divide-zbrain-divider">
          {rows.map((r: any) => (
            <VerificationRow key={r.rule_key} r={r} hookHistory={hookHistory} />
          ))}
        </ul>
      )}
    </div>
  );
}

function VerificationRow({ r, hookHistory }: { r: any; hookHistory: Record<string, string[]> }) {
  const isFail = r.verdict === "fail" || r.verdict === "error";
  const isBlock = r.verdict === "fail" && r.severity === "block" && r.mode === "active";
  const isWarn = r.verdict === "fail" && r.severity === "warn" && r.mode === "active";
  const correctiveCopy = (action: string) => {
    switch (action) {
      case "halt": return "halt the pipeline and mark the case errored";
      case "force_no_reply": return "suppress the customer reply (auto-send disabled, CSR draft preserved)";
      case "force_tier_L2": return "downgrade the case to L2 full human review";
      case "flag_for_review": return "flag the case for review without changing state";
      case "none": return "record evidence only; no automatic correction";
      default: return action;
    }
  };
  return (
    <li className="px-5 py-3 flex items-start gap-3">
      <span
        className={[
          "inline-block w-2 h-2 rounded-full mt-1.5 shrink-0",
          r.verdict === "pass"
            ? "bg-emerald-500"
            : isBlock
              ? "bg-rose-500"
              : isWarn
                ? "bg-amber-500"
                : r.verdict === "error"
                  ? "bg-rose-400"
                  : "bg-slate-400",
        ].join(" ")}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[12.5px] font-semibold text-zbrain-ink">{r.label}</span>
          <Link
            to={`/kb?ns=pipeline_verification_rules&key=${encodeURIComponent(r.rule_key)}`}
            className="pill text-[10px] bg-slate-100 text-slate-600 font-mono hover:bg-zbrain hover:text-white transition-colors"
            title="Open this rule in the Knowledge Base"
          >
            {r.rule_key} ↗
          </Link>
          <span className={`pill text-[10px] ${
            r.severity === "block" ? "bg-rose-50 text-rose-700"
            : r.severity === "warn" ? "bg-amber-50 text-amber-800"
            : "bg-slate-100 text-slate-600"
          }`}>{r.severity}</span>
          {r.mode === "shadow" && (
            <span className="pill text-[10px] bg-indigo-50 text-indigo-700" title="Shadow rules evaluate but never change pipeline state. Used to back-test new invariants before promoting them to active mode.">shadow</span>
          )}
          <span className={`pill text-[10px] ${
            r.verdict === "pass" ? "bg-emerald-50 text-emerald-700"
            : r.verdict === "fail" ? "bg-rose-50 text-rose-700"
            : r.verdict === "error" ? "bg-rose-50 text-rose-700"
            : "bg-slate-100 text-slate-600"
          }`}>
            {r.verdict}
          </span>
        </div>
        {r.description && (
          <div className="text-[11.5px] text-zbrain-ink/80 mt-1 leading-relaxed">{r.description}</div>
        )}
        {isFail && (
          <div className="text-[11px] text-zbrain-muted mt-1 leading-relaxed">
            <span className="font-semibold text-zbrain-ink">If this fails the verifier will</span>{" "}
            {correctiveCopy(r.corrective_action)}.
          </div>
        )}
        {isFail && (r.applies_when || r.invariant) && (
          <details className="mt-1.5">
            <summary className="text-[10.5px] text-zbrain-muted cursor-pointer hover:text-zbrain-ink">
              Show predicates
            </summary>
            <div className="mt-1 space-y-1">
              {r.applies_when && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">Applies when</div>
                  <code className="block text-[11px] font-mono text-zbrain-ink/90 bg-slate-50 border border-slate-200 rounded px-2 py-1 overflow-x-auto">{r.applies_when}</code>
                </div>
              )}
              {r.invariant && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">Must hold (invariant)</div>
                  <code className="block text-[11px] font-mono text-zbrain-ink/90 bg-slate-50 border border-slate-200 rounded px-2 py-1 overflow-x-auto">{r.invariant}</code>
                </div>
              )}
            </div>
          </details>
        )}
        {r.error && (
          <div className="text-[11px] text-rose-700 font-mono mt-1">{r.error}</div>
        )}
        {(hookHistory[r.rule_key] || []).length > 0 && (
          <div className="text-[10.5px] text-zbrain-muted mt-1">
            evaluated at: {(hookHistory[r.rule_key] || []).join(" · ")}
          </div>
        )}
      </div>
    </li>
  );
}
