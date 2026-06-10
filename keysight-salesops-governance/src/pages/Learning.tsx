import type { ReactElement } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, type ABExperiment, type DriftAlert, type LearningOpportunity, type BaselineAnchor, type SegmentObservation } from "../api";
import {
  signalGraphApi,
  type SgRecommendation,
  type SgGate,
  type SgSuggestedRange,
} from "../api";
import { SignalGraphViewer } from "../components/SignalGraphViewer";
import { Button, Chip, Section, Surface } from "../components/ui";
import { useOperator } from "../lib/operator";
import { kbUrl as kbUrlFor, traceUrl } from "../lib/traceUrl";
import { InfoTip } from "../components/InfoTip";
import { BaselineChip } from "../components/BaselineChip";
import { BaselineFilter, invalidateBaselineCache, useBaselineLookup } from "../components/BaselineFilter";
import {
  BaselineDrillthrough,
  type DrillthroughJumpTab,
} from "../components/BaselineDrillthrough";
import { FeedbackLogPanel } from "./FeedbackLog";
import { STAGE_DISPLAY } from "../lib/stageNames";

type Dashboard = {
  window_days: number;
  generated_at: string;
  feedback_summary: {
    total: number;
    thumbs_up: number;
    thumbs_down: number;
    edits: number;
    ratio_positive: number;
    per_stage: Record<string, { thumbs_up: number; thumbs_down: number; edit: number; other: number }>;
  };
  drift_signals: {
    intent: string;
    kind: string;
    recent_median: number;
    baseline_median: number;
    delta: number;
    recent_n: number;
    baseline_n: number;
    severity: "high" | "medium";
  }[];
  intent_misclassifications: {
    pipeline_id: number;
    from_intent: string;
    to_intent: string;
    note: string;
    ts: string | null;
  }[];
  tuning_suggestions: {
    kind: string;
    namespace: string;
    rule_key: string;
    title: string;
    rationale: string;
    support: number;
  }[];
  throughput_24h: {
    pipelines: number;
    by_tier: Record<string, number>;
    by_status: Record<string, number>;
  };
};

// Canonical stage names sourced from src/lib/stageNames.ts so this page,
// FeedbackLog, Models, and any future surface render identical text. Keep
// new stage keys in the shared map, never inline here.
const STAGE_LABELS = STAGE_DISPLAY;

type SubTab = "dashboard" | "discover" | "baselines" | "feedback" | "drift" | "tuning" | "experiments" | "promote";

const SUB_TABS: { key: SubTab; label: string; funnelHint?: string }[] = [
  { key: "dashboard",   label: "Overview" },
  { key: "discover",    label: "Discover · quality gates" },
  { key: "baselines",   label: "Baselines · quality targets",   funnelHint: "00" },
  { key: "feedback",    label: "Capture · feedback log",        funnelHint: "01" },
  { key: "drift",       label: "Detect · drift & RCA bundles",  funnelHint: "02" },
  { key: "tuning",      label: "Propose · tuning queue",        funnelHint: "03" },
  { key: "experiments", label: "Validate · A/B experiments",    funnelHint: "04" },
  { key: "promote",     label: "Promote · live changes",        funnelHint: "05" },
];

function isSubTab(v: string | null): v is SubTab {
  return !!v && SUB_TABS.some((t) => t.key === v);
}

type Funnel = {
  generated_at: string;
  capture: { trace_events_7d: number; feedback_7d: number };
  detect: { drift_alerts_open: number; drift_alerts_total_30d: number; rca_tickets_open: number };
  propose: { opportunities_open: number; opportunities_accepted: number };
  validate: { shadow: number; ready: number; in_ab: number };
  promote: { promoted_30d: number; auto_rolled_back_30d: number; rolled_back_30d: number };
};

export function LearningPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab: SubTab = isSubTab(tabParam) ? tabParam : "dashboard";

  const [data, setData] = useState<Dashboard | null>(null);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [windowDays, setWindowDays] = useState(30);
  const [toast, setToast] = useState<string | null>(null);
  // Drill-through panel state. Opened from any tab; closed by Esc, click on
  // the backdrop, the × button, or by jumping to a tab via the section link.
  const [drillId, setDrillId] = useState<number | null>(null);
  // Per-tab baseline filters. Owning these here lets a "View more in tab" jump
  // from the drill-through panel preset the right filter before switching tab.
  const [driftFilter, setDriftFilter] = useState<number | null>(null);
  const [tuneFilter, setTuneFilter] = useState<number | null>(null);
  const [expFilter, setExpFilter] = useState<number | null>(null);
  const [promoteFilter, setPromoteFilter] = useState<number | null>(null);

  const reload = () => {
    setError(null);
    fetch(`/api/learning/dashboard?window_days=${windowDays}`)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e)));
    // Funnel powers the Overview KPIs (drift alerts, tuning suggestions). The
    // dashboard endpoint computes its own ad-hoc drift snapshot and never
    // populates `drift_signals` or `tuning_suggestions`, so reading those
    // arrays surfaces zero. The funnel endpoint exposes the canonical counts.
    fetch(`/api/learning/funnel`)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(setFunnel)
      .catch(() => undefined);
  };

  useEffect(() => {
    reload();
  }, [windowDays]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const switchTab = (next: SubTab) => {
    const p = new URLSearchParams(params);
    if (next === "dashboard") p.delete("tab");
    else p.set("tab", next);
    setParams(p, { replace: false });
  };

  const openDrill = (id: number) => setDrillId(id);
  const closeDrill = () => setDrillId(null);

  // Bridge from the drill-through panel: close the panel, pre-apply the
  // baseline filter on the destination tab, then switch the active tab.
  const jumpFromDrill = (jump: DrillthroughJumpTab, baselineId: number) => {
    if (jump === "drift") setDriftFilter(baselineId);
    if (jump === "tuning") setTuneFilter(baselineId);
    if (jump === "experiments") setExpFilter(baselineId);
    if (jump === "promote") setPromoteFilter(baselineId);
    setDrillId(null);
    if (jump === "feedback") switchTab("feedback");
    else if (jump === "drift") switchTab("drift");
    else if (jump === "tuning") switchTab("tuning");
    else if (jump === "experiments") switchTab("experiments");
    else if (jump === "promote") switchTab("promote");
  };

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <h1 className="display-md">Continuous Learning</h1>
        <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-3xl leading-relaxed">
          Track the AI's accuracy, surface classification drift before it impacts customers,
          and apply tuning suggestions with one click. Aggregates every CSR signal (thumbs,
          edits, and HITL outcomes) into a single quality workspace.
        </p>

        <div className="mt-4 flex items-center gap-1.5 flex-wrap">
          {SUB_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => switchTab(t.key)}
              className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                tab === t.key
                  ? "bg-zbrain text-white border-zbrain"
                  : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-50"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <HubFunnel onJump={switchTab} />

      {tab === "dashboard" && (
        <DashboardTab
          data={data}
          funnel={funnel}
          error={error}
          windowDays={windowDays}
          setWindowDays={setWindowDays}
          reload={reload}
          onOpenDrill={openDrill}
        />
      )}
      {tab === "discover" && <DiscoverTab />}
      {tab === "feedback" && <FeedbackLogPanel onOpenDrill={openDrill} />}
      {tab === "drift" && (
        <DriftTab
          data={data}
          error={error}
          windowDays={windowDays}
          reload={reload}
          baselineFilter={driftFilter}
          setBaselineFilter={setDriftFilter}
          onOpenDrill={openDrill}
        />
      )}
      {tab === "tuning" && (
        <TuningTab
          data={data}
          error={error}
          reload={reload}
          baselineFilter={tuneFilter}
          setBaselineFilter={setTuneFilter}
          onOpenDrill={openDrill}
          onApply={(s) => {
            // Suggestions come from clustered CSR corrections. The remedy is
            // a Knowledge Base edit, so the right "apply" is to open the
            // editor with the target rule pre-selected. The KB lives in the
            // SalesOps app; open it in a new tab via the cross-app helper so
            // the operator can keep this tuning queue in view while reviewing
            // the diff. Saving auto-creates an A/B experiment via the KB
            // save endpoint (kb_namespace + kb_key already pinned).
            const url = kbUrlFor(s.namespace, s.rule_key, { from: "tuning" });
            window.open(url, "_blank", "noopener,noreferrer");
          }}
        />
      )}
      {tab === "experiments" && (
        <ExperimentsTab
          baselineFilter={expFilter}
          setBaselineFilter={setExpFilter}
          onOpenDrill={openDrill}
        />
      )}
      {tab === "promote" && (
        <PromoteTab
          baselineFilter={promoteFilter}
          setBaselineFilter={setPromoteFilter}
          onOpenDrill={openDrill}
        />
      )}
      {tab === "baselines" && <BaselinesTab onToast={showToast} onOpenDrill={openDrill} />}

      <BaselineDrillthrough
        baselineId={drillId}
        onClose={closeDrill}
        onJumpToTab={jumpFromDrill}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50">
          <div className="bg-zbrain-ink text-white text-sm px-4 py-2.5 rounded-md shadow-lg">
            {toast}
          </div>
        </div>
      )}
    </div>
  );
}

function DashboardTab({
  data,
  funnel,
  error,
  windowDays,
  setWindowDays,
  reload,
  onOpenDrill,
}: {
  data: Dashboard | null;
  funnel: Funnel | null;
  error: string | null;
  windowDays: number;
  setWindowDays: (n: number) => void;
  reload: () => void;
  onOpenDrill: (id: number) => void;
}) {
  const positivePct = data ? Math.round(data.feedback_summary.ratio_positive * 100) : 0;
  // The dashboard endpoint's `drift_signals` and `tuning_suggestions` arrays
  // are derived from a separate ad-hoc snapshot and remain empty in normal
  // operation. The /funnel endpoint exposes the canonical counters that the
  // Detect and Propose cells render against; we read from there.
  const driftAlertsOpen = funnel?.detect.drift_alerts_open ?? 0;
  const rcaTicketsOpen = funnel?.detect.rca_tickets_open ?? 0;
  const tuningOpportunitiesOpen = funnel?.propose.opportunities_open ?? 0;
  const tuningOpportunitiesAccepted = funnel?.propose.opportunities_accepted ?? 0;

  const stageRows = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.feedback_summary.per_stage).sort((a, b) =>
      (b[1].thumbs_up + b[1].thumbs_down + b[1].edit) - (a[1].thumbs_up + a[1].thumbs_down + a[1].edit),
    );
  }, [data]);

  return (
    <div className="space-y-4">
      <ContinuousLearningLoop />

      <div className="card p-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
            Overview
            <InfoTip text="Feedback volume, positive ratio, drift-signal count, queue depth, and throughput over the active window." />
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-zbrain-muted">Window</label>
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className="text-xs border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
          <button onClick={reload} className="btn-secondary text-xs">
            ↻ Refresh
          </button>
        </div>
      </div>

      {error && <div className="card p-4 text-rose-700 text-sm">Failed to load: {error}</div>}
      {!data && !error && <div className="card p-6 text-sm text-zbrain-muted">Loading…</div>}

      {data && (
        <>
          <div className="grid grid-cols-12 gap-4">
            <Kpi
              label="Feedback events"
              value={data.feedback_summary.total.toLocaleString()}
              sub={`👍 ${data.feedback_summary.thumbs_up} · 👎 ${data.feedback_summary.thumbs_down} · ✎ ${data.feedback_summary.edits}`}
            />
            <Kpi
              label="Positive ratio"
              value={`${positivePct}%`}
              sub={`of ${data.feedback_summary.thumbs_up + data.feedback_summary.thumbs_down} thumb votes`}
              tone={positivePct >= 80 ? "good" : positivePct >= 60 ? "neutral" : "bad"}
            />
            <Kpi
              label="Drift signals"
              value={String(driftAlertsOpen)}
              sub={
                rcaTicketsOpen > 0
                  ? `${rcaTicketsOpen} RCA ticket${rcaTicketsOpen === 1 ? "" : "s"} open`
                  : "no RCA tickets open"
              }
              tone={driftAlertsOpen === 0 ? "good" : "bad"}
            />
            <Kpi
              label="Tuning suggestions"
              value={String(tuningOpportunitiesOpen)}
              sub={
                tuningOpportunitiesAccepted > 0
                  ? `${tuningOpportunitiesAccepted} accepted`
                  : "ready to apply"
              }
              tone={tuningOpportunitiesOpen > 0 ? "neutral" : "good"}
            />
          </div>

          <HealthByBaseline onOpenDrill={onOpenDrill} />

          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-zbrain-divider">
              <h2 className="text-sm font-semibold">CSR feedback by stage</h2>
              <p className="text-xs text-zbrain-muted mt-0.5">
                Where are CSRs spending review effort? Stages with many edits or thumbs-down are the ones needing
                prompt or KB tuning.
              </p>
            </div>
            <div>
              <table className="w-full text-sm">
                <thead className="bg-zbrain-surface text-[10px] uppercase tracking-wider text-zbrain-muted">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">Stage</th>
                    <th className="text-right px-3 py-2 font-medium">👍</th>
                    <th className="text-right px-3 py-2 font-medium">👎</th>
                    <th className="text-right px-3 py-2 font-medium">✎ Edits</th>
                    <th className="text-right px-3 py-2 font-medium">Total</th>
                    <th className="text-right px-4 py-2 font-medium">Positivity</th>
                  </tr>
                </thead>
                <tbody>
                  {stageRows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-sm text-zbrain-muted">
                        No CSR feedback recorded in this window. Open any case activity and use the 👍/👎 buttons in each stage to seed this view.
                      </td>
                    </tr>
                  )}
                  {stageRows.map(([stage, counts]) => {
                    const total = counts.thumbs_up + counts.thumbs_down + counts.edit;
                    const pos = counts.thumbs_up + counts.thumbs_down > 0
                      ? Math.round((counts.thumbs_up / (counts.thumbs_up + counts.thumbs_down)) * 100)
                      : null;
                    return (
                      <tr key={stage} className="border-t border-zbrain-divider/60">
                        <td className="px-4 py-2.5">
                          <div className="font-medium text-zbrain-ink">{STAGE_LABELS[stage] || stage}</div>
                          <div className="text-[11px] font-mono text-zbrain-muted">{stage}</div>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-emerald-700">{counts.thumbs_up}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-rose-700">{counts.thumbs_down}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-amber-700">{counts.edit}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{total}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">
                          {pos != null ? (
                            <span className={pos >= 80 ? "text-emerald-700" : pos >= 60 ? "text-zbrain-ink" : "text-rose-700"}>{pos}%</span>
                          ) : (
                            <span className="text-zbrain-muted">n/a</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">Last 24h throughput</h2>
                <p className="text-xs text-zbrain-muted mt-0.5">
                  How many emails were processed in the last day, by tier and final status.
                </p>
              </div>
              <div className="text-right">
                <div className="text-2xl font-semibold tabular-nums">{data.throughput_24h.pipelines}</div>
                <div className="text-[11px] text-zbrain-muted">cases · 24h</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 p-4">
              <Distribution title="By tier" counts={data.throughput_24h.by_tier} />
              <Distribution title="By status" counts={data.throughput_24h.by_status} />
            </div>
          </div>

          <div className="text-[11px] text-zbrain-muted text-right">
            Generated at {new Date(data.generated_at).toLocaleString()} · window {data.window_days} days
          </div>
        </>
      )}
    </div>
  );
}

function DriftTab({
  error,
  reload,
  baselineFilter,
  setBaselineFilter,
  onOpenDrill,
}: {
  data: Dashboard | null;
  error: string | null;
  windowDays: number;
  reload: () => void;
  baselineFilter: number | null;
  setBaselineFilter: (id: number | null) => void;
  onOpenDrill: (id: number) => void;
}) {
  const [showUnlinked, setShowUnlinked] = useState(false);
  const [unanchoredCount, setUnanchoredCount] = useState<number>(0);
  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
            Drift signals
            <InfoTip text="Live metric divergence against the enabled baselines. Circuit breaker fires on SLO-floor breaches; owners acknowledge and resolve from this view." />
          </h2>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <BaselineFilter value={baselineFilter} onChange={setBaselineFilter} />
          <label
            className={`inline-flex items-center gap-1.5 text-[11px] cursor-pointer select-none ${unanchoredCount === 0 ? "text-zbrain-muted/60" : "text-zbrain-muted"}`}
            title={unanchoredCount === 0
              ? "Every drift alert is baseline-anchored. Nothing to surface; toggle has no visible effect right now."
              : "Alerts without a baseline anchor are hidden by default. Toggle on to audit backfill gaps."}
          >
            <input
              type="checkbox"
              checked={showUnlinked}
              onChange={(e) => setShowUnlinked(e.target.checked)}
              className="accent-zbrain"
              disabled={unanchoredCount === 0}
            />
            Show alerts without a baseline anchor
            <span className={`ml-1 tabular-nums ${unanchoredCount === 0 ? "text-emerald-700" : "text-rose-700"}`}>
              ({unanchoredCount})
            </span>
          </label>
          <button onClick={reload} className="btn-secondary text-xs whitespace-nowrap">
            ↻ Refresh
          </button>
        </div>
      </div>

      <DriftAlertLedger
        baselineFilter={baselineFilter}
        showUnlinked={showUnlinked}
        onOpenDrill={onOpenDrill}
        onUnanchoredCountChange={setUnanchoredCount}
      />

      {error && <div className="card p-4 text-rose-700 text-sm">Failed to load: {error}</div>}
    </div>
  );
}

function TuningTab({
  data,
  error,
  reload,
  onApply,
  baselineFilter,
  setBaselineFilter,
  onOpenDrill,
}: {
  data: Dashboard | null;
  error: string | null;
  reload: () => void;
  onApply: (s: Dashboard["tuning_suggestions"][number]) => void;
  baselineFilter: number | null;
  setBaselineFilter: (id: number | null) => void;
  onOpenDrill: (id: number) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
            Tuning queue
            <InfoTip text="Ranked candidate changes from CSR corrections and drift. Accept routes to A/B shadow, defer parks, reject closes with reasoning." />
          </h2>
        </div>
        <div className="flex items-center gap-3">
          <BaselineFilter value={baselineFilter} onChange={setBaselineFilter} />
          <button onClick={reload} className="btn-secondary text-xs whitespace-nowrap">
            ↻ Refresh
          </button>
        </div>
      </div>

      <OpportunityBoard baselineFilter={baselineFilter} onOpenDrill={onOpenDrill} />

      {error && <div className="card p-4 text-rose-700 text-sm">Failed to load: {error}</div>}

      {data && data.tuning_suggestions.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-zbrain-divider">
            <h3 className="text-sm font-semibold inline-flex items-center gap-1.5">
              KB tuning suggestions
              <InfoTip text="Auto-derived from clustered CSR intent corrections. Surfaced once the same from-to pair repeats at least twice. Apply routes to the KB editor with the rule pre-selected." />
            </h3>
          </div>
          <div className="divide-y divide-zbrain-divider/60">
            {data.tuning_suggestions
              .filter((s) => baselineFilter == null || (s as any).baseline_id === baselineFilter)
              .map((s, i) => (
              <div key={i} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1.5">
                      <BaselineChip
                        baselineId={(s as any).baseline_id ?? null}
                        baselineLabel={(s as any).baseline_label ?? null}
                        onClick={onOpenDrill}
                        size="md"
                      />
                      <span className="pill bg-zbrain-50 text-zbrain text-[10.5px] border border-zbrain/20 font-semibold">
                        Support {s.support}
                      </span>
                      <span className="pill bg-slate-100 text-slate-700 text-[10px]">{s.kind}</span>
                    </div>
                    <div className="text-[14px] font-semibold text-zbrain-ink leading-snug inline-flex items-center gap-1.5">
                      {s.title}
                      {s.rationale && <InfoTip text={s.rationale} />}
                    </div>
                    <div className="text-[10.5px] text-zbrain-muted font-mono mt-1">
                      {s.namespace} · {s.rule_key}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <button
                      onClick={() => onApply(s)}
                      className="text-xs px-3 py-1.5 rounded-md bg-zbrain text-white border border-zbrain hover:bg-zbrain/90 whitespace-nowrap"
                    >
                      Apply suggestion
                    </button>
                    <a
                      href={kbUrlFor(s.namespace, s.rule_key)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-zbrain hover:underline whitespace-nowrap"
                    >
                      Open in KB ↗
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ExperimentsTab({
  baselineFilter,
  setBaselineFilter,
  onOpenDrill,
}: {
  baselineFilter: number | null;
  setBaselineFilter: (id: number | null) => void;
  onOpenDrill: (id: number) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
          Shadow A/B
          <InfoTip text="Candidates run alongside production with no customer impact. Promotion is gated by pre-set success criteria and carries a one-click rollback." />
        </h2>
        <BaselineFilter value={baselineFilter} onChange={setBaselineFilter} />
      </div>

      <ABExperimentsLive baselineFilter={baselineFilter} onOpenDrill={onOpenDrill} />
    </div>
  );
}


// =========================================================================
// Baselines tab — admin-editable quality targets the drift detector evaluates
// against. Each row is (metric, segment, direction, target, drift_pct,
// severity). Sourced from /api/learning/baselines; the live observed value
// + status are written back on every detector pass so this is a real-time
// heatmap, not a stale snapshot.
// =========================================================================
type Baseline = {
  id: number;
  metric: string;
  segment: string;
  direction: "min" | "max";
  target_value: number;
  drift_pct: number;
  severity: "warn" | "block_promotion";
  enabled: boolean;
  owner: string;
  rationale: string | null;
  source: string;
  unit: string | null;
  label: string | null;
  last_observed: number | null;
  last_observed_at: string | null;
  last_status: "healthy" | "drifting" | "breached" | "unknown";
  updated_at: string | null;
  updated_by: string | null;
  // Consolidated rollup metadata. The Baselines tab renders the
  // segments_observed breakdown when the operator expands a row.
  rollup_strategy?: "weighted_avg" | "max" | "min";
  segments_observed?: SegmentObservation[];
};

type BaselineSummary = {
  total: number;
  enabled: number;
  healthy: number;
  drifting: number;
  breached: number;
  unknown: number;
  block_promotion_breached: number;
};

type BaselineMetricsCatalog = {
  metrics: { key: string; label: string; unit: string; default_direction: "min" | "max" }[];
  segments: { key: string; label: string }[];
  directions: { key: "min" | "max"; label: string }[];
  severities: { key: "warn" | "block_promotion"; label: string }[];
  sources: string[];
};

function BaselinesTab({
  onToast,
  onOpenDrill,
}: {
  onToast: (msg: string) => void;
  onOpenDrill: (id: number) => void;
}) {
  const [rows, setRows] = useState<Baseline[]>([]);
  const [summary, setSummary] = useState<BaselineSummary | null>(null);
  const [catalog, setCatalog] = useState<BaselineMetricsCatalog | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Baseline | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    // Bust the BaselineFilter cache so any open dropdowns reflect adds /
    // deletes / status flips that just happened on this tab.
    invalidateBaselineCache();
    fetch("/api/learning/baselines")
      .then((r) => r.json())
      .then((d) => {
        setRows(d.items || []);
        setSummary(d.summary || null);
      })
      .catch((e) => setError(String(e)));
  };

  useEffect(() => {
    load();
    fetch("/api/learning/baselines/metrics")
      .then((r) => r.json())
      .then(setCatalog)
      .catch(() => {});
  }, []);

  const refreshObservations = async () => {
    setRefreshing(true);
    try {
      const r = await fetch("/api/learning/baselines/evaluate", { method: "POST" });
      const d = await r.json();
      onToast(`Observed all baselines. ${d.fired || 0} alert${d.fired === 1 ? "" : "s"} fired.`);
      load();
    } catch (e) {
      onToast(`Refresh failed: ${e}`);
    } finally {
      setRefreshing(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this baseline? The drift detector will stop evaluating it immediately.")) return;
    await fetch(`/api/learning/baselines/${id}`, { method: "DELETE" });
    onToast("Baseline deleted.");
    load();
  };

  const grouped = useMemo(() => {
    // Group by status so breached rows surface at the top — that's the only
    // thing an admin needs to react to. Healthy / drifting follow; unknown
    // (no data yet) goes last.
    const order: Baseline["last_status"][] = ["breached", "drifting", "healthy", "unknown"];
    const out: Record<string, Baseline[]> = {};
    for (const s of order) out[s] = rows.filter((r) => r.last_status === s);
    return out;
  }, [rows]);

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
              Quality targets
              <InfoTip text="Admin-set targets for live pipeline metrics. The drift detector evaluates every enabled target each pass; a breach can block auto-promotion of any candidate change." />
            </h2>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={refreshObservations}
              disabled={refreshing}
              className="text-xs px-3 py-1.5 rounded-md border border-zbrain-divider bg-white hover:bg-zbrain-50 disabled:opacity-50"
            >
              {refreshing ? "Observing…" : "Refresh observations"}
            </button>
            <button
              onClick={() => setAdding(true)}
              className="text-xs px-3 py-1.5 rounded-md border border-zbrain bg-zbrain text-white hover:opacity-90"
            >
              + Add baseline
            </button>
          </div>
        </div>

        {summary && (
          <div className="grid grid-cols-12 gap-3 mt-4">
            <Kpi
              label="Total baselines"
              value={String(summary.total)}
              sub={`${summary.enabled} enabled`}
            />
            <Kpi
              label="Healthy"
              value={String(summary.healthy)}
              sub={`of ${summary.total - summary.unknown} observed`}
              tone={summary.healthy === summary.total - summary.unknown ? "good" : undefined}
            />
            <Kpi
              label="Drifting"
              value={String(summary.drifting)}
              sub="inside tolerance band"
              tone={summary.drifting > 0 ? "neutral" : undefined}
            />
            <Kpi
              label="Breached"
              value={String(summary.breached)}
              sub={
                summary.block_promotion_breached > 0
                  ? `${summary.block_promotion_breached} blocking promotions`
                  : "no promotion blocks"
              }
              tone={summary.breached > 0 ? "bad" : "good"}
            />
          </div>
        )}

        {summary?.block_promotion_breached ? (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-800">
            <strong>{summary.block_promotion_breached}</strong> hard baseline
            {summary.block_promotion_breached === 1 ? " is" : "s are"} currently breached.
            Auto-promotion of any A/B candidate is paused until the underlying issue is resolved or the
            baseline severity is lowered to <code className="font-mono">warn</code>.
          </div>
        ) : null}

        {error && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-800">
            {error}
          </div>
        )}
      </div>

      {(["breached", "drifting", "healthy", "unknown"] as const).map((status) => {
        const list = grouped[status] || [];
        if (!list.length) return null;
        return (
          <BaselineGroup
            key={status}
            status={status}
            rows={list}
            onEdit={setEditing}
            onDelete={remove}
            onOpenDrill={onOpenDrill}
          />
        );
      })}

      {(editing || adding) && catalog && (
        <BaselineEditor
          row={editing}
          catalog={catalog}
          onClose={() => {
            setEditing(null);
            setAdding(false);
          }}
          onSaved={() => {
            setEditing(null);
            setAdding(false);
            onToast(editing ? "Baseline updated." : "Baseline created.");
            load();
          }}
        />
      )}
    </div>
  );
}

function BaselineGroup({
  status,
  rows,
  onEdit,
  onDelete,
  onOpenDrill,
}: {
  status: Baseline["last_status"];
  rows: Baseline[];
  onEdit: (r: Baseline) => void;
  onDelete: (id: number) => void;
  onOpenDrill: (id: number) => void;
}) {
  const title =
    status === "breached" ? "Breached"
    : status === "drifting" ? "Drifting (inside tolerance, watching)"
    : status === "healthy" ? "Healthy"
    : "No data yet";
  const tone =
    status === "breached" ? "bg-rose-50 border-rose-200 text-rose-800"
    : status === "drifting" ? "bg-amber-50 border-amber-200 text-amber-900"
    : status === "healthy" ? "bg-emerald-50 border-emerald-200 text-emerald-800"
    : "bg-slate-50 border-slate-200 text-slate-700";
  // Within each status band, sort block_promotion rows above warn rows so the
  // strict baselines surface first. Preserve the incoming order within each
  // severity bucket by using a stable sort key.
  const severityRank = (s: Baseline["severity"]): number =>
    s === "block_promotion" ? 0 : 1;
  const sorted = [...rows]
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const sr = severityRank(a.r.severity) - severityRank(b.r.severity);
      if (sr !== 0) return sr;
      const la = (a.r.label || a.r.metric).toLowerCase();
      const lb = (b.r.label || b.r.metric).toLowerCase();
      if (la !== lb) return la < lb ? -1 : 1;
      return a.i - b.i;
    })
    .map((x) => x.r);
  return (
    <div className="card overflow-hidden">
      <div className={`px-4 py-2 text-[12px] font-semibold border-b ${tone}`}>
        {title} <span className="text-[11px] font-normal opacity-80">({rows.length})</span>
      </div>
      <div className="divide-y divide-zbrain-divider">
        {sorted.map((b) => (
          <BaselineRow
            key={b.id}
            b={b}
            onEdit={() => onEdit(b)}
            onDelete={() => onDelete(b.id)}
            onOpenDrill={() => onOpenDrill(b.id)}
          />
        ))}
      </div>
    </div>
  );
}

function BaselineRow({
  b,
  onEdit,
  onDelete,
  onOpenDrill,
}: {
  b: Baseline;
  onEdit: () => void;
  onDelete: () => void;
  onOpenDrill: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const unit = b.unit || "";
  const formatVal = (v: number | null): string => {
    if (v == null) return "n/a";
    if (unit === "ms") return `${Math.round(v).toLocaleString()} ms`;
    if (unit === "hours") return `${v.toFixed(1)} h`;
    if (unit === "ratio" || unit === "pct") return `${(v * 100).toFixed(1)}%`;
    return String(v);
  };
  const dirText = b.direction === "min" ? "≥" : "≤";
  const hasSegments = Array.isArray(b.segments_observed) && b.segments_observed.length > 0;
  // Heatmap bar — relative position of observed to target. For 'min' it's
  // observed / target; for 'max' it's target / observed. Clamp 0..1.5.
  const ratio = (() => {
    if (b.last_observed == null || !b.target_value) return null;
    if (b.direction === "min") return b.last_observed / b.target_value;
    return b.target_value / b.last_observed;
  })();
  const barPct = ratio == null ? 0 : Math.min(150, Math.max(0, ratio * 100));
  const barColor =
    b.last_status === "breached" ? "bg-rose-500"
    : b.last_status === "drifting" ? "bg-amber-500"
    : b.last_status === "healthy" ? "bg-emerald-500"
    : "bg-slate-300";
  const observedTone =
    b.last_status === "breached" ? "text-rose-700"
    : b.last_status === "drifting" ? "text-amber-700"
    : b.last_status === "healthy" ? "text-emerald-700"
    : "text-slate-500";
  const statusTone =
    b.last_status === "breached" ? "bg-rose-50 text-rose-700 border border-rose-200"
    : b.last_status === "drifting" ? "bg-amber-50 text-amber-800 border border-amber-200"
    : b.last_status === "healthy" ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
    : "bg-slate-100 text-slate-600 border border-slate-200";
  const rowAccent =
    b.severity === "block_promotion"
      ? "border-l-2 border-l-rose-400"
      : "border-l-2 border-l-transparent";
  return (
    <div className={`px-5 py-3 ${rowAccent}`}>
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={onOpenDrill}
              className="text-[13px] font-semibold text-zbrain-ink inline-flex items-center gap-1.5 hover:text-zbrain hover:underline decoration-zbrain/40 underline-offset-2"
              title="Open timeline drill-through"
            >
              {b.label || b.metric}
              {b.rationale && <InfoTip text={b.rationale} />}
            </button>
            {b.severity !== "block_promotion" && (
              <span className="pill text-[10px] uppercase tracking-wider font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                warn
              </span>
            )}
            {!b.enabled && (
              <span className="pill text-[10px] bg-slate-200 text-slate-600">disabled</span>
            )}
          </div>
          <div className="mt-2 grid grid-cols-[repeat(3,minmax(0,1fr))_auto] gap-4 items-end max-w-2xl">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-medium">Target</div>
              <div className="text-[19px] leading-tight font-semibold text-zbrain-ink tabular-nums">
                {dirText} {formatVal(b.target_value)}
              </div>
            </div>
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-medium">Tolerance</div>
              <div className="text-[19px] leading-tight font-semibold text-zbrain-ink tabular-nums">
                &plusmn;{b.drift_pct}%
              </div>
            </div>
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-medium">Observed</div>
              <div className={`text-[19px] leading-tight font-semibold tabular-nums ${observedTone}`}>
                {formatVal(b.last_observed)}
              </div>
              {b.last_observed_at && (
                <div className="text-[10px] text-zbrain-muted mt-0.5">
                  {new Date(b.last_observed_at).toLocaleString()}
                </div>
              )}
            </div>
            <span className={`pill text-[10px] uppercase tracking-wider font-semibold self-center ${statusTone}`}>
              {b.last_status}
            </span>
          </div>
          {ratio != null && (
            <div className="mt-3 h-1.5 bg-slate-100 rounded-full overflow-hidden max-w-2xl relative">
              <div
                className={`h-full ${barColor} transition-all`}
                style={{ width: `${Math.min(100, barPct)}%` }}
              />
              {/* tick at 100%, the target */}
              <div className="absolute top-0 bottom-0 w-px bg-zbrain-ink/40" style={{ left: "100%" }} />
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onOpenDrill}
            className="text-[11px] px-2 py-1 rounded border border-zbrain/30 bg-zbrain-50 hover:bg-zbrain-100 text-zbrain"
            title="Open the full timeline drill-through for this baseline"
          >
            View timeline
          </button>
          <button
            onClick={onEdit}
            className="text-[11px] px-2 py-1 rounded border border-zbrain-divider bg-white hover:bg-zbrain-50"
          >
            Edit
          </button>
          <button
            onClick={onDelete}
            className="text-[11px] px-2 py-1 rounded border border-rose-200 bg-white hover:bg-rose-50 text-rose-700"
          >
            Delete
          </button>
          <button
            onClick={() => setExpanded((v) => !v)}
            disabled={!hasSegments}
            aria-expanded={expanded}
            className="text-[11px] px-1.5 py-1 rounded border border-zbrain-divider bg-white hover:bg-zbrain-50 disabled:opacity-40 disabled:cursor-not-allowed text-zbrain-muted hover:text-zbrain-ink"
            title={hasSegments ? "Expand per-segment breakdown" : "No per-segment breakdown available"}
          >
            <span className="inline-block w-3 text-center">{expanded ? "▾" : "▸"}</span>
          </button>
        </div>
      </div>
      {expanded && hasSegments && (
        <BaselineSegmentsBreakdown
          baseline={b}
          formatVal={formatVal}
          dirText={dirText}
        />
      )}
    </div>
  );
}

function BaselineSegmentsBreakdown({
  baseline,
  formatVal,
  dirText,
}: {
  baseline: Baseline;
  formatVal: (v: number | null) => string;
  dirText: string;
}) {
  const segs = baseline.segments_observed || [];
  // Worst-first: for min-direction baselines the worst observed is the lowest
  // value; for max-direction baselines the worst is the highest. Nulls
  // ("pending") sink to the bottom so observed rows surface first.
  const sorted = [...segs].sort((a, b) => {
    if (a.observed == null && b.observed == null) return 0;
    if (a.observed == null) return 1;
    if (b.observed == null) return -1;
    return baseline.direction === "min" ? a.observed - b.observed : b.observed - a.observed;
  });
  const rollupLabel =
    baseline.rollup_strategy === "weighted_avg"
      ? "weighted_avg"
      : baseline.rollup_strategy === "max"
        ? "max"
        : baseline.rollup_strategy === "min"
          ? "min"
          : "rollup";
  const statusDot = (s: SegmentObservation["status"]): string =>
    s === "breached"
      ? "bg-rose-500"
      : s === "drifting"
        ? "bg-amber-500"
        : s === "healthy"
          ? "bg-emerald-500"
          : "bg-slate-300";
  return (
    <div className="mt-3 ml-1 rounded-md border border-zbrain-divider/70 bg-zbrain-surface/40 overflow-hidden">
      <div className="px-3 py-1.5 text-[11px] text-zbrain-muted border-b border-zbrain-divider/60">
        Rolled-up via <span className="font-mono">{rollupLabel}</span>:{" "}
        <span className="font-semibold tabular-nums text-zbrain-ink">{formatVal(baseline.last_observed)}</span>{" "}
        (target {dirText} <span className="tabular-nums">{formatVal(baseline.target_value)}</span>)
      </div>
      <table className="w-full text-[11.5px]">
        <thead className="bg-white/60">
          <tr className="text-left text-zbrain-muted">
            <th className="px-3 py-1.5 font-medium">Segment</th>
            <th className="px-3 py-1.5 font-medium text-right">Observed</th>
            <th className="px-3 py-1.5 font-medium text-right">Weight</th>
            <th className="px-3 py-1.5 font-medium text-right">Sample size</th>
            <th className="px-3 py-1.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zbrain-divider/40">
          {sorted.map((s) => (
            <tr key={s.segment} className="hover:bg-white/60">
              <td className="px-3 py-1.5 font-mono text-[11px] text-zbrain-ink truncate max-w-[18rem]">
                {s.segment}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {s.observed == null ? (
                  <span className="text-zbrain-muted italic">pending</span>
                ) : (
                  formatVal(s.observed)
                )}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-zbrain-muted">
                {s.weight.toFixed(2)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-zbrain-muted">
                {s.sample_size.toLocaleString()}
              </td>
              <td className="px-3 py-1.5">
                <span className="inline-flex items-center gap-1.5">
                  <span className={`inline-block w-2 h-2 rounded-full ${statusDot(s.status)}`} />
                  <span className="text-[11px] capitalize text-zbrain-ink">{s.status}</span>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BaselineEditor({
  row,
  catalog,
  onClose,
  onSaved,
}: {
  row: Baseline | null;
  catalog: BaselineMetricsCatalog;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = !row;
  const [draft, setDraft] = useState<Partial<Baseline>>(
    row ? { ...row } : {
      metric: catalog.metrics[0]?.key || "",
      segment: "global",
      direction: catalog.metrics[0]?.default_direction || "min",
      target_value: 0.9,
      drift_pct: 5,
      severity: "warn",
      enabled: true,
      owner: "role:cl_admin",
      source: "manual",
      unit: catalog.metrics[0]?.unit || "ratio",
      label: "",
      rationale: "",
    },
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backtest, setBacktest] = useState<{ observed: number | null; status: string; would_fire_alert: boolean } | null>(null);
  const [backtesting, setBacktesting] = useState(false);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (isNew) {
        const r = await fetch("/api/learning/baselines", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        if (!r.ok) throw new Error((await r.json()).detail || String(r.status));
      } else {
        const r = await fetch(`/api/learning/baselines/${row!.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_value: draft.target_value,
            drift_pct: draft.drift_pct,
            severity: draft.severity,
            enabled: draft.enabled,
            direction: draft.direction,
            rationale: draft.rationale,
            label: draft.label,
            source: draft.source,
            unit: draft.unit,
          }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || String(r.status));
      }
      onSaved();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  const runBacktest = async () => {
    if (isNew || !row) return;
    setBacktesting(true);
    setError(null);
    try {
      // Save first so the backtest reads the in-flight values, not the
      // previously-saved ones. The endpoint reads the live row.
      const r = await fetch(`/api/learning/baselines/${row.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_value: draft.target_value,
          drift_pct: draft.drift_pct,
          direction: draft.direction,
        }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || String(r.status));
      const r2 = await fetch(`/api/learning/baselines/${row.id}/backtest`, { method: "POST" });
      const d = await r2.json();
      setBacktest({
        observed: d.observed,
        status: d.status,
        would_fire_alert: d.would_fire_alert,
      });
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBacktesting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-6">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-3 border-b border-zbrain-divider flex items-center justify-between">
          <h3 className="text-sm font-semibold">{isNew ? "Add baseline" : "Edit baseline"}</h3>
          <button onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink" aria-label="Close">✕</button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Metric</label>
              <select
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5 disabled:bg-slate-50 disabled:text-slate-500"
                value={draft.metric || ""}
                disabled={!isNew}
                onChange={(e) => {
                  const m = catalog.metrics.find((x) => x.key === e.target.value);
                  setDraft({ ...draft, metric: e.target.value, unit: m?.unit, direction: m?.default_direction });
                }}
              >
                {catalog.metrics.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
              {!isNew && <div className="text-[10px] text-zbrain-muted mt-0.5">metric is immutable; delete and recreate to change</div>}
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Segment</label>
              <select
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5 disabled:bg-slate-50 disabled:text-slate-500"
                value={draft.segment || "global"}
                disabled={!isNew}
                onChange={(e) => setDraft({ ...draft, segment: e.target.value })}
              >
                {catalog.segments.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Direction</label>
              <select
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5"
                value={draft.direction || "min"}
                onChange={(e) => setDraft({ ...draft, direction: e.target.value as "min" | "max" })}
              >
                {catalog.directions.map((d) => (
                  <option key={d.key} value={d.key}>{d.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Severity</label>
              <select
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5"
                value={draft.severity || "warn"}
                onChange={(e) => setDraft({ ...draft, severity: e.target.value as "warn" | "block_promotion" })}
              >
                {catalog.severities.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Target value</label>
              <input
                type="number"
                step="any"
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5 font-mono"
                value={draft.target_value ?? 0}
                onChange={(e) => setDraft({ ...draft, target_value: Number(e.target.value) })}
              />
              {draft.unit === "ratio" && (
                <div className="text-[10px] text-zbrain-muted mt-0.5">use the decimal form (0.90 = 90%)</div>
              )}
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Drift tolerance (%)</label>
              <input
                type="number"
                step="0.1"
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5 font-mono"
                value={draft.drift_pct ?? 5}
                onChange={(e) => setDraft({ ...draft, drift_pct: Number(e.target.value) })}
              />
              <div className="text-[10px] text-zbrain-muted mt-0.5">how far observed can stray before an alert fires</div>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Source</label>
              <select
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5"
                value={draft.source || "manual"}
                onChange={(e) => setDraft({ ...draft, source: e.target.value })}
              >
                {catalog.sources.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Display label</label>
              <input
                type="text"
                className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5"
                value={draft.label || ""}
                onChange={(e) => setDraft({ ...draft, label: e.target.value })}
                placeholder="optional; defaults to the metric name"
              />
            </div>
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wider text-zbrain-muted">Rationale</label>
            <textarea
              className="mt-1 w-full text-sm rounded border border-zbrain-divider px-2 py-1.5 leading-relaxed"
              rows={3}
              value={draft.rationale || ""}
              onChange={(e) => setDraft({ ...draft, rationale: e.target.value })}
              placeholder="Why this target? One sentence on the business or compliance driver behind the threshold."
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="bl-enabled"
              type="checkbox"
              checked={!!draft.enabled}
              onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
            />
            <label htmlFor="bl-enabled" className="text-[12px] text-zbrain-ink">
              Enabled (detector evaluates this baseline on every pass)
            </label>
          </div>
          {!isNew && (
            <div className="mt-3 border-t border-zbrain-divider pt-3">
              <div className="flex items-center justify-between">
                <div className="text-[12px] font-semibold text-zbrain-ink">Backtest against live data</div>
                <button
                  onClick={runBacktest}
                  disabled={backtesting}
                  className="text-[11px] px-2 py-1 rounded border border-zbrain-divider bg-white hover:bg-zbrain-50 disabled:opacity-50"
                >
                  {backtesting ? "Running…" : "Run backtest"}
                </button>
              </div>
              {backtest && (
                <div className="mt-2 text-[12px] rounded border border-zbrain-divider bg-slate-50 px-3 py-2">
                  Observed value:{" "}
                  <span className="font-mono">{backtest.observed == null ? "no data" : String(backtest.observed)}</span>
                  {" · status: "}
                  <span className={`font-semibold ${
                    backtest.status === "breached" ? "text-rose-700"
                    : backtest.status === "drifting" ? "text-amber-700"
                    : backtest.status === "healthy" ? "text-emerald-700"
                    : "text-slate-600"
                  }`}>{backtest.status}</span>
                  {backtest.would_fire_alert && (
                    <span className="ml-2 text-rose-700">would fire an alert with current settings</span>
                  )}
                </div>
              )}
              <div className="text-[10.5px] text-zbrain-muted mt-1">
                Backtest saves your draft first so the evaluator reads your in-flight changes. Close without
                saving to revert (the draft replaces target / drift / direction).
              </div>
            </div>
          )}
          {error && (
            <div className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-800">
              {error}
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-zbrain-divider flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="text-xs px-3 py-1.5 rounded-md border border-zbrain-divider bg-white hover:bg-zbrain-50"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="text-xs px-3 py-1.5 rounded-md border border-zbrain bg-zbrain text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : isNew ? "Create" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad" | "neutral";
}) {
  const valueCls =
    tone === "good"
      ? "text-emerald-700"
      : tone === "bad"
      ? "text-rose-700"
      : tone === "neutral"
      ? "text-amber-700"
      : "text-zbrain-ink";
  return (
    <div className="col-span-3 card p-4">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">{label}</div>
      <div className={`text-2xl font-semibold mt-1 tabular-nums ${valueCls}`}>{value}</div>
      {sub && <div className="text-[11px] text-zbrain-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function Distribution({ title, counts }: { title: string; counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((s, n) => s + n, 0);
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-medium mb-2">{title}</div>
      {rows.length === 0 && <div className="text-xs text-zbrain-muted">no data</div>}
      <div className="space-y-1.5">
        {rows.map(([k, v]) => {
          const pct = total > 0 ? (v / total) * 100 : 0;
          return (
            <div key={k}>
              <div className="flex items-center justify-between text-xs mb-0.5">
                <span className="font-mono text-zbrain-ink">{k}</span>
                <span className="tabular-nums text-zbrain-muted">
                  {v} · {Math.round(pct)}%
                </span>
              </div>
              <div className="h-1.5 bg-zbrain-divider/40 rounded-full overflow-hidden">
                <div className="h-full bg-zbrain rounded-full" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// === Drift alerts ledger ====================================================

// Plain-language dictionary for every metric the Monitor service emits.
// Each entry tells a functional user what the number is, where the baseline
// comes from, and what "higher is bad" or "lower is bad" means for the metric.
const METRIC_GLOSSARY: Record<string, {
  label: string;
  unit: "rate" | "pct" | "ms" | "score" | "raw";
  worse: "higher" | "lower";
  one_liner: string;
  baseline_source: string;
}> = {
  csr_edit_rate_24h: {
    label: "CSR edit rate",
    unit: "rate",
    worse: "higher",
    one_liner: "Share of cases the system handled where a CSR corrected the output (intent, extracted field, or final reply).",
    baseline_source: "Rolling 30-day average across the same segment.",
  },
  hitl_fire_rate_24h: {
    label: "HITL fire rate",
    unit: "rate",
    worse: "higher",
    one_liner: "Share of cases at this stage that paused for human review instead of flowing through automatically.",
    baseline_source: "Rolling 30-day average for the same stage.",
  },
  extract_field_correction_rate: {
    label: "Field-correction rate",
    unit: "rate",
    worse: "higher",
    one_liner: "Share of pipelines where a CSR had to correct the value extracted for a specific field (PO number, ship-to, quote number, etc.).",
    baseline_source: "Fixed floor of 5%. Above 10% is flagged for review, above 20% is an SLO breach.",
  },
  p95_latency_ms: {
    label: "P95 stage latency",
    unit: "ms",
    worse: "higher",
    one_liner: "The slowest 5% of recent stage runs. If this rises, the long-tail user experience is degrading even if the average looks fine.",
    baseline_source: "Rolling 30-day P95 for the same stage.",
  },
  aioa_pass_rate_24h: {
    label: "AIOA pass rate",
    unit: "rate",
    worse: "lower",
    one_liner: "Share of orders the AI Order Acceptance service auto-accepted (vs. fell out for human review).",
    baseline_source: "Rolling 30-day AIOA pass rate.",
  },
  psi_intent: {
    label: "Intent distribution shift (PSI)",
    unit: "score",
    worse: "higher",
    one_liner: "How much the mix of incoming intents in the last 24h differs from the 30-day baseline. PSI < 0.1 is normal, 0.1-0.2 is noteworthy, > 0.2 means the mix has materially shifted.",
    baseline_source: "Distribution computed from the prior 30 days excluding the last 24h.",
  },
  integration_write_failure_rate: {
    label: "Integration write failure rate",
    unit: "rate",
    worse: "higher",
    one_liner: "Share of pipelines that errored writing to an external system (Salesforce, SharePoint, ServiceNow) in the last 24h.",
    baseline_source: "Rolling 30-day failure rate for the same integration.",
  },
  // Legacy metric names from the original seed alerts kept here so cards
  // still render meaningfully for historical data.
  classification_accuracy: {
    label: "Classification accuracy",
    unit: "pct",
    worse: "lower",
    one_liner: "Share of cases the classifier got right (no CSR correction needed) in the recent window.",
    baseline_source: "Rolling 30-day accuracy across the same segment.",
  },
  extraction_completeness: {
    label: "Extraction completeness",
    unit: "pct",
    worse: "lower",
    one_liner: "Share of required extraction fields the system filled in correctly (no enrichment needed). Below the floor means cases are arriving with missing data the AI cannot resolve.",
    baseline_source: "Rolling 30-day completeness across the same segment.",
  },
  hitl_rate: {
    label: "HITL rate",
    unit: "rate",
    worse: "higher",
    one_liner: "Share of cases routed to human review in the recent window.",
    baseline_source: "Rolling 30-day HITL share for the same intent.",
  },
  aioa_fail_rate: {
    label: "AIOA fail rate",
    unit: "rate",
    worse: "higher",
    one_liner: "Share of orders the AI Order Acceptance service kicked out for review.",
    baseline_source: "Rolling 30-day AIOA fail rate.",
  },
  sla_adherence_p95_ms: {
    label: "SLA adherence P95",
    unit: "ms",
    worse: "higher",
    one_liner: "End-to-end pipeline P95 latency for this region. SLA target depends on the region.",
    baseline_source: "Rolling 30-day P95 latency for the same region.",
  },
  post_promotion_regression_pp: {
    label: "Post-promotion regression",
    unit: "pct",
    worse: "higher",
    one_liner: "Gap between what the candidate's backtest predicted and what the live data is showing after promotion. A growing gap means the promoted change is not performing as expected.",
    baseline_source: "The candidate's back-test prediction recorded at promotion time.",
  },
};

function fmtMetricValue(v: number | null | undefined, unit: string): string {
  if (v == null) return "n/a";
  if (unit === "rate")  return `${(v * 100).toFixed(1)}%`;
  if (unit === "pct")   return `${(v * 100).toFixed(1)}%`;
  if (unit === "ms")    return v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`;
  if (unit === "score") return v.toFixed(3);
  return String(v);
}

function severityCopy(sev: string, breaker: boolean): {
  chip: string;
  pillCls: string;
  description: string;
} {
  if (breaker) {
    return {
      chip: "Circuit breaker",
      pillCls: "bg-rose-50 text-rose-800 border-rose-200",
      description: "Auto-routing is suspended for the affected segment. New cases drop to L2 review until this clears.",
    };
  }
  if (sev === "high" || sev === "slo_breach") {
    return {
      chip: "SLO breach",
      pillCls: "bg-rose-50 text-rose-800 border-rose-200",
      description: "The metric has crossed the hard SLO floor. A rule owner should investigate within the on-call window.",
    };
  }
  if (sev === "medium" || sev === "warn") {
    return {
      chip: "Warning",
      pillCls: "bg-amber-50 text-amber-800 border-amber-200",
      description: "The metric is meaningfully off baseline. No customer impact yet, but worth a look in the next planning cycle.",
    };
  }
  return {
    chip: "Info",
    pillCls: "bg-slate-50 text-slate-700 border-slate-200",
    description: "Informational. The metric drifted but stayed within tolerance.",
  };
}

function describeSegment(segment: string): string {
  // Plain-English explanation of what cases fall into this segment.
  if (!segment) return "All cases.";
  const [kind, ...rest] = segment.split(":");
  const value = rest.join(":");
  if (kind === "intent") {
    if (value.includes("region:")) {
      const [intent, regionPart] = value.split(" region:");
      return `Pipelines classified as ${intent} from the ${regionPart.toUpperCase()} region.`;
    }
    return `Pipelines classified as ${value}.`;
  }
  if (kind === "region")        return `Pipelines from customers in the ${value.toUpperCase()} region.`;
  if (kind === "language")      return `Pipelines whose customer-language was detected as ${value.toUpperCase()}.`;
  if (kind === "stage")         return `The ${value} pipeline stage across all cases.`;
  if (kind === "extract_field") return `Extraction of the ${value} field across all intents.`;
  if (kind === "integration")   return `Writes to the ${value} integration across all cases.`;
  if (kind === "experiment")    return `Cases generated after experiment ${value} was promoted.`;
  if (kind === "aioa")          return "Orders routed through the AI Order Acceptance service.";
  if (kind === "intent_mix")    return "The overall mix of incoming intents.";
  return segment;
}

function DriftAlertCard({ r, onOpenDrill }: { r: DriftAlert; onOpenDrill?: (id: number) => void }) {
  const [showRaw, setShowRaw] = useState(false);
  const gloss = METRIC_GLOSSARY[r.metric] || {
    label: r.metric.replace(/_/g, " "),
    unit: "raw" as const,
    worse: "higher" as const,
    one_liner: `Metric \`${r.metric}\` (no glossary entry yet; please open a ticket to document this metric).`,
    baseline_source: "Unknown. See raw detail.",
  };
  const sev = severityCopy(r.severity, r.circuit_breaker_fired);
  const headline = (() => {
    const segDesc = describeSegment(r.segment);
    const baseStr = fmtMetricValue(r.baseline, gloss.unit);
    const curStr = fmtMetricValue(r.current, gloss.unit);
    const direction = gloss.worse === "higher" ? "rose to" : "dropped to";
    return `${gloss.label} for ${segDesc.replace(/\.$/, "")} ${direction} ${curStr} from a ${baseStr} baseline.`;
  })();

  const detail = (r.detail || {}) as Record<string, unknown>;
  const detailEntries = Object.entries(detail).filter(([k]) => k !== "_" && k !== "");

  // Share of cases: detector publishes either a percentage or a sample count
  // pair on the detail blob. Surface as a single value so the row stays scannable.
  const shareOfCases = (() => {
    const pct = (detail.share_pct ?? detail.share_of_cases_pct) as number | undefined;
    if (typeof pct === "number") return `${pct.toFixed(1)}% of cases`;
    const num = detail.affected_cases as number | undefined;
    const den = detail.total_cases as number | undefined;
    if (typeof num === "number" && typeof den === "number" && den > 0) {
      return `${num.toLocaleString()} of ${den.toLocaleString()} cases`;
    }
    return null;
  })();

  return (
    <div className="border border-zbrain-divider rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <BaselineChip
          baselineId={r.baseline_id ?? null}
          baselineLabel={r.baseline_label ?? null}
          onClick={onOpenDrill}
          size="md"
        />
        <span className={`pill border ${sev.pillCls} text-[10px] uppercase tracking-[0.1em] font-semibold`}>{sev.chip}</span>
        <span className="pill bg-slate-100 text-slate-700 text-[10px]">{gloss.label}</span>
        <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-mono">{r.segment}</span>
        <span className="ml-auto text-[11px] text-zbrain-muted whitespace-nowrap">
          Detected {r.detected_at ? new Date(r.detected_at).toLocaleString() : "n/a"}
        </span>
      </div>

      <div className="text-[14px] font-semibold text-zbrain-ink leading-snug inline-flex items-center gap-1.5">
        {headline}
        <InfoTip text={`${gloss.one_liner}\n\nBaseline source: ${gloss.baseline_source}\n\nSeverity rule: ${sev.description}`} />
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px]">
        <span>
          <span className="text-zbrain-muted">Baseline:</span>{" "}
          <span className="font-semibold tabular-nums">{fmtMetricValue(r.baseline, gloss.unit)}</span>
        </span>
        <span>
          <span className="text-zbrain-muted">Observed:</span>{" "}
          <span className="font-semibold tabular-nums">{fmtMetricValue(r.current, gloss.unit)}</span>
        </span>
        {r.delta_pct != null && (
          <span
            className={`tabular-nums font-semibold ${(gloss.worse === "higher" ? (r.delta_pct >= 0 ? "text-rose-700" : "text-emerald-700") : (r.delta_pct <= 0 ? "text-rose-700" : "text-emerald-700"))}`}
          >
            {r.delta_pct > 0 ? "+" : ""}{r.delta_pct.toFixed(1)}%
          </span>
        )}
        {shareOfCases && (
          <span>
            <span className="text-zbrain-muted">Share:</span>{" "}
            <span className="font-semibold tabular-nums">{shareOfCases}</span>
          </span>
        )}
      </div>

      {Array.isArray(r.top_contributors) && r.top_contributors.length > 0 && (
        <DriftTopContributorChip
          contributors={r.top_contributors}
          unit={gloss.unit}
        />
      )}

      {r.circuit_breaker_fired && (
        <div className="mt-2.5 px-3 py-2 rounded-md border border-rose-200 bg-rose-50 text-xs text-rose-900 inline-flex items-center gap-1.5">
          <span className="font-semibold">Circuit breaker is armed.</span>
          <InfoTip
            text={`New cases in this segment (${describeSegment(r.segment).toLowerCase()}) cannot auto-close at L4 right now. They drop to L2 human review until a rule owner resolves this alert or the metric recovers.`}
          />
        </div>
      )}

      {detailEntries.length > 0 && (
        <details className="mt-2.5">
          <summary className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold cursor-pointer hover:text-zbrain-ink select-none">
            How the detector got these numbers
          </summary>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-0.5 mt-1.5 text-[12px] leading-snug pl-3 border-l-2 border-zbrain-divider/70">
            {detailEntries.map(([k, v]) => (
              <div key={k}>
                <span className="text-zbrain-muted">{k.replace(/_/g, " ")}:</span>{" "}
                <span className="text-zbrain-ink tabular-nums">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="mt-3 flex items-center gap-2 text-[11px]">
        <span className={statusPill(r.status)}>Status: {({open:"Open", in_review:"In review", resolved:"Resolved"} as Record<string,string>)[r.status] || r.status.replace(/_/g, " ")}</span>
        {r.resolved_by && (
          <span className="text-zbrain-muted">Resolved by {r.resolved_by}</span>
        )}
        {r.note && !r.resolved_by && (
          <span className="text-zbrain-muted truncate">Note: {r.note}</span>
        )}
        <button
          onClick={() => setShowRaw((v) => !v)}
          className="ml-auto px-2.5 py-1 text-[11px] font-medium rounded-md text-zbrain-muted hover:text-zbrain-ink hover:bg-zinc-50"
          title="Show the raw alert record"
        >
          {showRaw ? "Hide raw" : "Show raw"}
        </button>
      </div>

      {showRaw && (
        <pre className="mt-2 text-[11px] leading-snug bg-zinc-50 border border-zbrain-divider rounded-md p-3 overflow-x-auto whitespace-pre">
          {JSON.stringify(r, null, 2)}
        </pre>
      )}
    </div>
  );
}

// Compact top-contributor chip rendered on each drift alert card. The worst
// segment surfaces inline; the InfoTip exposes the full top-5 list so the
// operator can scan without leaving the card.
function DriftTopContributorChip({
  contributors,
  unit,
}: {
  contributors: SegmentObservation[];
  unit: string;
}) {
  const head = contributors[0];
  if (!head) return null;
  const headValue = head.observed == null ? "pending" : fmtMetricValue(head.observed, unit);
  const rest = contributors.slice(0, 5);
  const tipLines = rest
    .map((c) => {
      const v = c.observed == null ? "pending" : fmtMetricValue(c.observed, unit);
      return `${c.segment} at ${v} (${c.status}, n=${c.sample_size.toLocaleString()})`;
    })
    .join("\n");
  return (
    <div className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-50/70 px-2 py-1 text-[11px] text-rose-900">
      <span className="text-rose-700 font-semibold uppercase tracking-wider text-[9.5px]">
        Top contributor
      </span>
      <span className="font-mono text-[11px]">{head.segment}</span>
      <span className="text-zbrain-muted">at</span>
      <span className="font-semibold tabular-nums">{headValue}</span>
      {rest.length > 1 && <InfoTip text={tipLines} />}
    </div>
  );
}

function DriftAlertLedger({
  baselineFilter,
  showUnlinked,
  onOpenDrill,
  onUnanchoredCountChange,
}: {
  baselineFilter: number | null;
  showUnlinked: boolean;
  onOpenDrill: (id: number) => void;
  onUnanchoredCountChange?: (n: number) => void;
}) {
  const [rows, setRows] = useState<DriftAlert[] | null>(null);
  const reload = async () => {
    try {
      const r = await api.learningDriftAlerts(baselineFilter ?? undefined);
      setRows(r);
      if (onUnanchoredCountChange) {
        const unanchored = (r || []).filter((row: DriftAlert) => row.baseline_id == null).length;
        onUnanchoredCountChange(unanchored);
      }
    } catch {
      setRows([]);
      if (onUnanchoredCountChange) onUnanchoredCountChange(0);
    }
  };
  useEffect(() => {
    reload();
    const id = setInterval(reload, 15000);
    return () => clearInterval(id);
  }, [baselineFilter]);

  // Unanchored alerts (baseline_id is null) are hidden by default: the
  // workspace is baseline-driven, so an alert without an anchor is treated
  // as a backfill gap rather than an actionable signal. The toggle in the
  // tab header lets an operator audit those rows on demand.
  const visibleRows = useMemo(() => {
    const all = rows || [];
    if (showUnlinked) return all;
    return all.filter((r) => r.baseline_id != null);
  }, [rows, showUnlinked]);

  const hiddenUnlinkedCount = useMemo(() => {
    if (showUnlinked) return 0;
    return (rows || []).filter((r) => r.baseline_id == null).length;
  }, [rows, showUnlinked]);

  // Group rows: open + circuit-breaker armed first, then open warnings, then resolved history.
  const partitioned = useMemo(() => {
    const open = visibleRows.filter((r) => r.status !== "resolved");
    const resolved = visibleRows.filter((r) => r.status === "resolved");
    open.sort((a, b) => {
      const sevOrder = (s: DriftAlert) =>
        (s.circuit_breaker_fired ? 0 : 1) +
        ((s.severity === "high" || s.severity === "slo_breach") ? 0 : 2) +
        ((s.severity === "medium" || s.severity === "warn") ? 0 : 4);
      return sevOrder(a) - sevOrder(b);
    });
    return { open, resolved };
  }, [visibleRows]);

  const armed = visibleRows.filter((r) => r.circuit_breaker_fired && r.status !== "resolved").length;
  const breached = visibleRows.filter((r) => (r.severity === "slo_breach" || r.severity === "high") && r.status !== "resolved").length;
  const warned = visibleRows.filter((r) => (r.severity === "warn" || r.severity === "medium") && r.status !== "resolved").length;
  const resolved = visibleRows.filter((r) => r.status === "resolved").length;

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
              Drift &amp; alerts
              <InfoTip text="Each card explains one metric: what it measures, where the baseline comes from, what changed, and which cases the circuit breaker is suppressing if armed. Cards are sorted by severity, breaker-armed first." />
            </h2>
          </div>
          {visibleRows.length > 0 && (
            <div className="flex items-center gap-2 text-[11px]">
              <span className="pill bg-rose-50 text-rose-700 border border-rose-200">Circuit breaker {armed}</span>
              <span className="pill bg-rose-50 text-rose-700 border border-rose-200">SLO breach {breached}</span>
              <span className="pill bg-amber-50 text-amber-700 border border-amber-200">Warning {warned}</span>
              <span className="pill bg-emerald-50 text-emerald-700 border border-emerald-200">Resolved {resolved}</span>
            </div>
          )}
        </div>
        {hiddenUnlinkedCount > 0 && (
          <div className="mt-2 text-[11px] text-zbrain-muted">
            {hiddenUnlinkedCount} alert{hiddenUnlinkedCount === 1 ? "" : "s"} hidden because no baseline anchor is recorded. Toggle the filter above to review.
          </div>
        )}
      </div>
      {rows === null ? (
        <div className="px-4 py-6 text-sm text-zbrain-muted text-center">Loading alerts…</div>
      ) : visibleRows.length === 0 ? (
        <div className="px-4 py-8 text-sm text-zbrain-muted text-center">
          No drift alerts anchored to baselines. All monitored metrics are within tolerance.
        </div>
      ) : (
        <div className="p-4 space-y-3">
          {partitioned.open.map((r) => <DriftAlertCard key={r.id} r={r} onOpenDrill={onOpenDrill} />)}
          {partitioned.resolved.length > 0 && (
            <details className="pt-2">
              <summary className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold cursor-pointer hover:text-zbrain-ink select-none">
                Resolved history ({partitioned.resolved.length})
              </summary>
              <div className="space-y-3 mt-2">
                {partitioned.resolved.map((r) => <DriftAlertCard key={r.id} r={r} onOpenDrill={onOpenDrill} />)}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

// === Opportunity board ======================================================

function OpportunityBoard({
  baselineFilter,
  onOpenDrill,
}: {
  baselineFilter: number | null;
  onOpenDrill: (id: number) => void;
}) {
  const [rows, setRows] = useState<LearningOpportunity[] | null>(null);
  const reload = async () => {
    try {
      const r = await api.learningOpportunities(baselineFilter ?? undefined);
      setRows(r);
    } catch {
      setRows([]);
    }
  };
  useEffect(() => {
    reload();
    const id = setInterval(reload, 15000);
    return () => clearInterval(id);
  }, [baselineFilter]);

  const decide = async (id: number, status: "accepted" | "deferred" | "rejected") => {
    try {
      const res = await api.decideOpportunity(id, {
        status,
        decided_by: "rule-owner",
        decision_note: `${status} from Continuous Learning queue`,
      });
      await reload();
      if (status === "accepted" && res?.ab_experiment_id) {
        // Hand the operator off to the A/B tab so they can back-test and promote.
        const url = new URL(window.location.href);
        url.searchParams.set("tab", "experiments");
        url.searchParams.set("highlight", String(res.ab_experiment_id));
        window.history.replaceState({}, "", url.toString());
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    } catch (e: any) {
      alert(`Decision failed: ${e?.message || e}`);
    }
  };

  if (rows === null) return <div className="card p-6 text-sm text-zbrain-muted">Loading opportunities…</div>;

  // Partition open candidates by anchor presence. The main list shows only
  // baseline-anchored rows so the queue mirrors the baseline-driven framework.
  // Unanchored rows are still visible but parked in a collapsible section at
  // the bottom so an operator can see them as a backfill audit surface.
  const openAll = rows.filter((r) => r.status === "open");
  const open = openAll.filter((r) => r.baseline_id != null);
  const openUnanchored = openAll.filter((r) => r.baseline_id == null);
  const decided = rows.filter((r) => r.status !== "open");

  return (
    <div className="space-y-4">
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
              Opportunity board
              <InfoTip text="Open opportunities ranked by lift over effort. Risk acts as the brake. Each row anchors to the baseline it would move." />
            </h2>
          </div>
          <div className="text-[11px] text-zbrain-muted">
            {open.length} anchored · {openUnanchored.length} unanchored · {decided.length} decided
          </div>
        </div>
        <div className="divide-y divide-zbrain-divider/60">
          {open.length === 0 && (
            <div className="px-4 py-8 text-sm text-zbrain-muted text-center">
              No open opportunities anchored to a baseline. The weekly batch has either decided or promoted everything in the queue.
            </div>
          )}
          {open.map((o) => (
            <OpportunityCard key={o.id} opp={o} onDecide={decide} onOpenDrill={onOpenDrill} />
          ))}
        </div>
      </div>

      {openUnanchored.length > 0 && (
        <div className="card overflow-hidden">
          <details>
            <summary className="px-4 py-3 cursor-pointer hover:bg-zbrain-50/40 select-none border-b border-zbrain-divider flex items-center justify-between">
              <div className="inline-flex items-center gap-1.5">
                <span className="text-sm font-semibold text-zbrain-ink">
                  Unanchored candidates ({openUnanchored.length})
                </span>
                <InfoTip text="Candidates without a recorded baseline anchor. Backend backfill is still in progress; review and decide as normal, anchors will populate on the next generator pass." />
              </div>
              <span className="text-[11px] text-zbrain-muted">backfill gap</span>
            </summary>
            <div className="divide-y divide-zbrain-divider/60">
              {openUnanchored.map((o) => (
                <OpportunityCard key={o.id} opp={o} onDecide={decide} onOpenDrill={onOpenDrill} />
              ))}
            </div>
          </details>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-zbrain-divider">
          <h2 className="text-sm font-semibold">Decided opportunities</h2>
          <p className="text-xs text-zbrain-muted mt-0.5">History of accepted, promoted, deferred, and rejected decisions.</p>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-zbrain-surface text-[11px] uppercase tracking-wider text-zbrain-muted">
            <tr className="border-b border-zbrain-divider">
              <th className="text-left px-4 py-2.5 font-semibold">Segment</th>
              <th className="text-left px-3 py-2.5 font-semibold">Status</th>
              <th className="text-left px-3 py-2.5 font-semibold">Decided by</th>
              <th className="text-left px-3 py-2.5 font-semibold">Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zbrain-divider/70">
            {decided.map((o) => (
              <tr key={o.id} className="align-top">
                <td className="px-4 py-2.5 text-zbrain-ink text-xs">{o.segment}</td>
                <td className="px-3 py-2.5"><span className={opportunityStatusPill(o.status)}>{o.status.replaceAll("_", " ")}</span></td>
                <td className="px-3 py-2.5 text-zbrain-muted text-xs">{o.decided_by || "n/a"}</td>
                <td className="px-3 py-2.5 text-zbrain-muted text-xs">{o.decision_note || "n/a"}</td>
              </tr>
            ))}
            {decided.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-sm text-zbrain-muted">No decisions yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type OppSummary = {
  changeType: string;
  changeTypeLabel: string;
  title: string;
  detail: string;
  badges: { label: string; value: string; tone?: "auto" | "click" | "review" | "neutral" }[];
  rationale: string | null;
  raw: unknown;
  evidence: OppEvidence | null;
};

// Grounding evidence carried alongside the proposal so a functional admin
// can see WHY we know the proposed change would help. Populated by:
//   - the seed stories (for demo opportunities)
//   - each generator (for live opportunities)
// Lives inside the proposed_remedy JSON under an `evidence` key.
type OppEvidence = {
  headline?: string;
  counterfactual?: {
    window_days: number;
    total_in_window: number;
    would_change: number;
    metric_label?: string;
    savings_label?: string;
  };
  sample_cases?: {
    pipeline_id: number;
    subject?: string;
    intent?: string;
    current_outcome?: string;
    proposed_outcome?: string;
    csr_action?: string;
  }[];
  observed_pattern?: string;
};

function parseRemedy(s: string | null | undefined): any | null {
  if (!s) return null;
  const trimmed = s.trim();
  if (!trimmed || (trimmed[0] !== "{" && trimmed[0] !== "[")) return null;
  try { return JSON.parse(trimmed); } catch { return null; }
}

function summarizeOpportunity(o: LearningOpportunity): OppSummary {
  const raw = parseRemedy(o.proposed_remedy);
  const changeType = raw?.change_type || "prompt";
  const proposed = raw?.proposed || {};
  const scope = raw?.scope || {};
  const segment = o.segment || "";
  // Strip "intent:" prefix for nicer display.
  const intentName = segment.startsWith("intent:") ? segment.slice("intent:".length) : null;

  let title = "";
  let detail = "";
  const badges: OppSummary["badges"] = [];

  switch (changeType) {
    case "threshold": {
      const current = raw?.current?.l4_floor;
      const next = raw?.proposed?.l4_floor;
      title = `Raise the L4 auto-close floor for ${intentName || "this intent"} from ${current ?? "?"} to ${next ?? "?"}`;
      detail = `Cases at confidence between ${current ?? "?"} and ${next ?? "?"} would move to L3 one-click review, reducing edits among auto-closed cases.`;
      if (current != null) badges.push({ label: "Current floor", value: String(current), tone: "neutral" });
      if (next != null) badges.push({ label: "Proposed floor", value: String(next), tone: "review" });
      break;
    }
    case "pattern_list": {
      const additions: string[] = Array.isArray(raw?.proposed_add) ? raw.proposed_add : [];
      title = `Add ${additions.length} keyword${additions.length === 1 ? "" : "s"} to the ${intentName || scope?.key || "intent"} rule`;
      detail = additions.length > 0
        ? `New phrases: ${additions.slice(0, 3).map((a) => `“${a}”`).join(", ")}${additions.length > 3 ? `, +${additions.length - 3} more` : ""}.`
        : "Tighten the deterministic rule with CSR-observed phrasings.";
      additions.slice(0, 3).forEach((a) => badges.push({ label: "Add phrase", value: a, tone: "auto" }));
      break;
    }
    case "routing_rule": {
      const current = raw?.current || {};
      const next = raw?.proposed || {};
      title = `Route ${current.intent || intentName || "this intent"} from ${current.queue || "?"} to ${next.queue || "?"}`;
      detail = `CSRs have been reassigning these cases manually. Updating the routing rule sends them directly to ${next.queue || "the right queue"}.`;
      badges.push({ label: "Currently routes to", value: String(current.queue || "?"), tone: "neutral" });
      badges.push({ label: "Should route to", value: String(next.queue || "?"), tone: "auto" });
      break;
    }
    case "validation_rule": {
      const action = String(proposed.action || "");
      const fires_on = String(proposed.fires_on || "");
      if (action.startsWith("request_enrichment:")) {
        const field = action.split(":", 2)[1] || "field";
        title = `Require ${field} before auto-write for ${intentName || scope?.key || "this intent"}`;
        detail = `When ${intentName || "this intent"} arrives with ${field} missing, pause for CSR enrichment instead of attempting the downstream write.`;
        badges.push({ label: "Trigger", value: `${field} missing`, tone: "review" });
        badges.push({ label: "Action", value: `Request CSR to add ${field}`, tone: "auto" });
      } else if (action === "require_review_against_historical_band") {
        const band: number[] = Array.isArray(proposed.two_sigma_band) ? proposed.two_sigma_band : [];
        const median = proposed.historical_median;
        title = `Flag outliers in ${(scope.key || "").split("_").slice(1, 2).join("_") || "value"} for ${intentName || "this intent"}`;
        detail = `Cases whose value falls outside the 2σ band${band.length === 2 ? ` [${band[0]} – ${band[1]}]` : ""} (median ${median ?? "?"}) need human review before action.`;
        if (median != null) badges.push({ label: "Historical median", value: String(median), tone: "neutral" });
        if (band.length === 2) badges.push({ label: "Auto-action band", value: `${band[0]} – ${band[1]}`, tone: "auto" });
      } else {
        title = "Add a new pre-flight verifier rule";
        detail = fires_on ? `Trigger: ${fires_on}.` : "Custom validation rule.";
      }
      break;
    }
    case "prompt":
    default: {
      title = intentName
        ? `Add CSR-corrected examples to the ${intentName} classifier`
        : "Tune the classifier with new examples";
      detail = "CSR-edited intents from recent feedback would be added to the classifier's positive-example list.";
      break;
    }
  }

  const changeTypeLabel = ({
    threshold: "Threshold tuning",
    pattern_list: "Pattern list addition",
    routing_rule: "Routing rule update",
    validation_rule: "Validation rule",
    prompt: "Classifier prompt",
  } as Record<string, string>)[changeType] || changeType;

  const evidence = (raw && typeof raw === "object" && raw.evidence) ? raw.evidence as OppEvidence : null;
  return {
    changeType,
    changeTypeLabel,
    title: evidence?.headline || title,
    detail,
    badges,
    rationale: raw?.rationale || (raw ? null : o.proposed_remedy || null),
    raw: raw || o.proposed_remedy || null,
    evidence,
  };
}

function changeTypePill(ct: string): string {
  const tone =
    ct === "threshold" ? "bg-amber-50 text-amber-800 border-amber-200" :
    ct === "pattern_list" ? "bg-sky-50 text-sky-800 border-sky-200" :
    ct === "routing_rule" ? "bg-violet-50 text-violet-800 border-violet-200" :
    ct === "validation_rule" ? "bg-emerald-50 text-emerald-800 border-emerald-200" :
    "bg-zinc-50 text-zinc-700 border-zinc-200";
  return `pill border ${tone} text-[10px] uppercase tracking-[0.1em] font-semibold`;
}

function badgeTone(tone?: "auto" | "click" | "review" | "neutral"): string {
  switch (tone) {
    case "auto":   return "bg-emerald-50 text-emerald-800 border-emerald-200";
    case "click":  return "bg-sky-50 text-sky-800 border-sky-200";
    case "review": return "bg-amber-50 text-amber-800 border-amber-200";
    default:       return "bg-zinc-50 text-zinc-700 border-zinc-200";
  }
}

function OpportunityCard({
  opp,
  onDecide,
  onOpenDrill,
}: {
  opp: LearningOpportunity;
  onDecide: (id: number, status: "accepted" | "deferred" | "rejected") => void | Promise<void>;
  onOpenDrill?: (id: number) => void;
}) {
  const s = summarizeOpportunity(opp);
  const [showRaw, setShowRaw] = useState(false);
  return (
    <div className="p-4">
      {/* Top row: baseline chip (prominent, leftmost) · score · kind */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <BaselineChip
          baselineId={opp.baseline_id ?? null}
          baselineLabel={opp.baseline_label ?? null}
          onClick={onOpenDrill}
          size="md"
        />
        <span className="pill bg-zbrain-50 text-zbrain text-[10.5px] border border-zbrain/20 font-semibold">
          Score {opp.score.toFixed(1)}
        </span>
        <span className={changeTypePill(s.changeType)}>{s.changeTypeLabel}</span>
        <span className="ml-auto text-[10px] uppercase tracking-wider text-zbrain-muted font-mono">{opp.segment}</span>
      </div>

      {/* Second row: 1-line proposed change */}
      <div className="text-[14px] font-semibold text-zbrain-ink leading-snug inline-flex items-center gap-1.5">
        {s.title}
        {(s.detail || s.rationale) && (
          <InfoTip
            text={[
              s.detail,
              s.rationale ? `Why this surfaced: ${s.rationale}` : null,
            ].filter(Boolean).join("\n\n")}
          />
        )}
      </div>

      {/* Third row: tiny meta (effort, risk, sample, source, expected lift) */}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zbrain-muted">
        <span className={effortRiskPill(opp.effort, "effort")}>Effort: {opp.effort}</span>
        <span className={effortRiskPill(opp.risk, "risk")}>Risk: {opp.risk}</span>
        <span>
          <span className="uppercase tracking-wider text-[10px] font-semibold">Sample</span>{" "}
          <span className="tabular-nums">{opp.sample_pipeline_ids?.length ?? 0}</span>
        </span>
        <span>
          <span className="uppercase tracking-wider text-[10px] font-semibold">Source</span>{" "}
          {(opp.source || "n/a").replaceAll("_", " ")}
        </span>
        {opp.expected_lift && (
          <span>
            <span className="uppercase tracking-wider text-[10px] font-semibold">Lift</span>{" "}
            {opp.expected_lift}
          </span>
        )}
      </div>

      {s.badges.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {s.badges.map((b, i) => (
            <span key={i} className={`pill border ${badgeTone(b.tone)} text-[11px]`}>
              <span className="font-medium">{b.label}:</span> <span className="ml-1 tabular-nums">{b.value}</span>
            </span>
          ))}
        </div>
      )}

      {s.evidence && <EvidencePanel evidence={s.evidence} />}

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <button
          onClick={() => onDecide(opp.id, "accepted")}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-zbrain text-white hover:opacity-90"
        >
          Accept & promote to A/B
        </button>
        <button
          onClick={() => onDecide(opp.id, "deferred")}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-white text-zbrain-ink border border-zbrain-divider hover:bg-zinc-50"
        >
          Defer
        </button>
        <button
          onClick={() => onDecide(opp.id, "rejected")}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-white text-zbrain-muted border border-zbrain-divider hover:bg-zinc-50"
        >
          Reject
        </button>
        <button
          onClick={() => setShowRaw((v) => !v)}
          className="ml-auto px-2.5 py-1 text-[11px] font-medium rounded-md text-zbrain-muted hover:text-zbrain-ink hover:bg-zinc-50"
          title="Show the raw JSON the generator emitted"
        >
          {showRaw ? "Hide raw" : "Show raw"}
        </button>
      </div>

      {showRaw && (
        <pre className="mt-2 text-[11px] leading-snug bg-zinc-50 border border-zbrain-divider rounded-md p-3 overflow-x-auto whitespace-pre">
          {typeof s.raw === "string" ? s.raw : JSON.stringify(s.raw, null, 2)}
        </pre>
      )}
    </div>
  );
}

// === Evidence panel ─────────────────────────────────────────────────────────
// Grounding shown under each proposal so a functional admin reads "if applied
// to the last 30 days, this would have changed N decisions out of M" plus a
// short table of concrete sample cases (subject + current outcome + proposed
// outcome + CSR action). Replaces the all-technical card body with something
// a non-engineer can act on.
function EvidencePanel({ evidence }: { evidence: OppEvidence }) {
  const cf = evidence.counterfactual;
  const cases = evidence.sample_cases || [];
  if (!cf && cases.length === 0 && !evidence.observed_pattern) return null;
  return (
    <div className="mt-3 rounded-md border border-zbrain-divider bg-zbrain-surface/40 overflow-hidden">
      <div className="px-3 py-2 border-b border-zbrain-divider flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-bold">
          Grounding · sample cases &amp; counterfactual
        </span>
        <span className="text-[10px] text-zbrain-muted italic">From production traffic the proposal is based on.</span>
      </div>
      <div className="px-3 py-3 space-y-3">
        {evidence.observed_pattern && (
          <div className="text-[12.5px] text-zbrain-ink leading-snug">
            <span className="text-zbrain-muted">What we observed:</span> {evidence.observed_pattern}
          </div>
        )}
        {cf && (
          <div className="grid grid-cols-3 gap-2">
            <CfTile
              label="Window"
              value={`${cf.window_days}d`}
              sub={`${cf.total_in_window.toLocaleString()} cases in scope`}
            />
            <CfTile
              label="Would change"
              value={`${cf.would_change.toLocaleString()}`}
              sub={`of ${cf.total_in_window.toLocaleString()} (${cf.total_in_window > 0 ? Math.round((cf.would_change / cf.total_in_window) * 100) : 0}%)`}
              accent
            />
            <CfTile
              label="Expected effect"
              value={cf.metric_label || "n/a"}
              sub={cf.savings_label || ""}
            />
          </div>
        )}
        {cases.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-left text-zbrain-muted uppercase tracking-wider text-[10px]">
                  <th className="py-1 pr-3 font-semibold">Pipeline</th>
                  <th className="py-1 pr-3 font-semibold">Subject</th>
                  <th className="py-1 pr-3 font-semibold">Today</th>
                  <th className="py-1 pr-3 font-semibold">After change</th>
                  <th className="py-1 font-semibold">CSR signal</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zbrain-divider/60">
                {cases.slice(0, 6).map((c) => (
                  <tr key={c.pipeline_id} className="align-top">
                    <td className="py-1.5 pr-3 font-mono tabular-nums text-zbrain-ink">#{c.pipeline_id}</td>
                    <td className="py-1.5 pr-3 text-zbrain-ink/85 max-w-[280px] truncate" title={c.subject || ""}>
                      {c.subject || "n/a"}
                    </td>
                    <td className="py-1.5 pr-3 text-rose-700">{c.current_outcome || "n/a"}</td>
                    <td className="py-1.5 pr-3 text-emerald-700">{c.proposed_outcome || "n/a"}</td>
                    <td className="py-1.5 text-zbrain-muted italic">{c.csr_action || "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function CfTile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-md border px-2.5 py-2 ${accent ? "border-zbrain bg-zbrain-50" : "border-zbrain-divider bg-white"}`}>
      <div className={`text-[9.5px] uppercase tracking-wider font-bold ${accent ? "text-zbrain" : "text-zbrain-muted"}`}>{label}</div>
      <div className={`text-[15px] font-bold tabular-nums leading-tight mt-0.5 ${accent ? "text-zbrain" : "text-zbrain-ink"}`}>{value}</div>
      {sub && <div className="text-[10px] mt-0.5 text-zbrain-muted leading-snug">{sub}</div>}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Deploy-target panel: spells out exactly where in the platform a
// promoted change lands. Calls /api/kb/rules/{namespace}/{key} to confirm
// the row exists and shows its version, label, and a "Verify in KB" link.
// ────────────────────────────────────────────────────────────────────────
function DeployTargetPanel({ namespace, keyName, changeType }: { namespace: string; keyName: string; changeType?: string | null }) {
  type Rule = { id: number; namespace: string; key: string; label?: string; version: number; updated_at?: string; updated_by?: string };
  const [rule, setRule] = useState<Rule | null | "missing">(null);
  useEffect(() => {
    let cancel = false;
    fetch(`/api/kb/${encodeURIComponent(namespace)}/${encodeURIComponent(keyName)}`)
      .then((r) => r.ok ? r.json() : null)
      .then((j) => { if (!cancel) setRule(j || "missing"); })
      .catch(() => { if (!cancel) setRule("missing"); });
    return () => { cancel = true; };
  }, [namespace, keyName]);

  // Knowledge Base lives in the SalesOps app; build a cross-app URL that
  // honours the deployed SalesOps base path so the link survives the
  // governance/SalesOps split.
  const kbUrl = kbUrlFor(namespace, keyName);
  const exists = rule && rule !== "missing";

  // Human-readable pickup story per change type.
  const pickup = (() => {
    if (changeType === "prompt" || changeType === "prompt_refinement")
      return "The agent loads this prompt body at every pipeline run. A promotion is effective on the next run, no deploy required.";
    if (changeType === "threshold")
      return "The Decision agent reads these floor values on every pipeline. Promoting writes the new floor and bumps the rule version.";
    if (changeType === "pattern_list" || changeType === "routing_rule")
      return "The Intake / Routing layer reads this rule on every email. Promoting takes effect on the next email arrival.";
    if (changeType === "validation_rule")
      return "The pipeline verifier reads these invariants on every case. Promoting takes effect on the next case that runs through.";
    return "Active on the next pipeline run.";
  })();

  return (
    <div className="mt-4 rounded-md border border-zbrain-divider bg-white overflow-hidden">
      <div className="px-3 py-2 border-b border-zbrain-divider flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-bold">
          Deploy target
        </span>
        <span className="text-[10px] text-zbrain-muted">
          Where this change writes in the platform
        </span>
      </div>
      <div className="px-3 py-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider font-bold text-zbrain-muted">KB rule</span>
          <span className="text-[12px] font-mono font-semibold text-zbrain-ink bg-zbrain-50 px-1.5 py-0.5 rounded">{namespace}/{keyName}</span>
          {rule === null && <span className="text-[10.5px] text-zbrain-muted">checking…</span>}
          {rule === "missing" && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200">
              ⚠ NOT FOUND
            </span>
          )}
          {exists && (
            <>
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                LIVE · v{(rule as Rule).version}
              </span>
              {(rule as Rule).label && (
                <span className="text-[11px] text-zbrain-ink/85">{(rule as Rule).label}</span>
              )}
            </>
          )}
          <a href={kbUrl} target="_blank" rel="noopener noreferrer" className="ml-auto text-[11px] font-semibold text-zbrain hover:underline">Verify in KB ↗</a>
        </div>
        <div className="text-[11.5px] text-zbrain-muted leading-snug">
          <span className="text-zbrain-ink font-semibold">How the agent picks it up:</span> {pickup}
        </div>
        {rule === "missing" && (
          <div className="text-[11.5px] text-rose-800 bg-rose-50 border border-rose-200 rounded px-2.5 py-1.5 leading-snug">
            This experiment's KB target does not exist yet. Promoting it would fail. Create the row in KB first, then re-promote.
          </div>
        )}
      </div>
    </div>
  );
}

// === Live A/B experiments ===================================================

function ABExperimentsLive({
  baselineFilter,
  onOpenDrill,
}: {
  baselineFilter: number | null;
  onOpenDrill: (id: number) => void;
}) {
  const [rows, setRows] = useState<ABExperiment[] | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [showAll, setShowAll] = useState<boolean>(false);
  // Tracks which highlight ids we have already auto-expanded so the 15-second
  // refetch does not reopen a row the operator has explicitly collapsed.
  const autoExpandedRef = useRef<Set<number>>(new Set());
  const { current: operator } = useOperator();
  const [params] = useSearchParams();
  // Resolves baseline.target_value + direction + unit for the Target /
  // Observed / Delta mini-stats rendered inside each FragmentABRow.
  const lookupBaseline = useBaselineLookup();
  const highlightId = (() => {
    const raw = params.get("highlight");
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : null;
  })();

  const reload = async () => {
    try {
      const r = await api.learningAbExperiments(baselineFilter ?? undefined);
      setRows(r);
    } catch {
      setRows([]);
    }
  };
  useEffect(() => {
    reload();
    const id = setInterval(reload, 15000);
    return () => clearInterval(id);
  }, [baselineFilter]);

  // When the Tuning tab hands an operator over with ?highlight=<id>, auto
  // expand that experiment row and scroll it into view so the next action
  // (backtest, then promote) is one click away. Also force-expand the full
  // list so a highlighted row past the default visible window is rendered.
  // Important: only auto-expand once per highlight id. Without the ref guard,
  // the 15-second `reload()` interval replaces `rows` and re-fires this
  // effect, reopening any row the operator has explicitly collapsed.
  useEffect(() => {
    if (!highlightId || !rows) return;
    if (autoExpandedRef.current.has(highlightId)) return;
    if (!rows.some((r) => r.id === highlightId)) return;
    autoExpandedRef.current.add(highlightId);
    setShowAll(true);
    setExpandedId(highlightId);
    const el = document.getElementById(`ab-exp-${highlightId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightId, rows]);

  const runBacktest = async (id: number) => {
    setBusy(id);
    try {
      await api.backtestAbExperiment(id);
      await reload();
      setExpandedId(id);
    } catch (e: any) {
      alert(`Back-test failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  const promote = async (id: number, promote_status: "promoted" | "retired", forceReason?: string) => {
    if (!operator) {
      alert("Pick a current operator in the header before taking this action.");
      return;
    }
    if (!operator.is_rule_owner) {
      alert(`${operator.name} is not on the Continuous Learning rule-owner allow-list. Switch to a rule owner (Andrew Chen, Priya Sharma, or David Park) in the header picker to ${promote_status === "promoted" ? "promote" : "retire"} this experiment.`);
      return;
    }
    const note = forceReason
      ? `force: ${forceReason}`
      : promote_status === "promoted"
      ? "Promoted to production. KB rule rolled forward, previous version snapshotted for rollback."
      : "Retired from shadow";
    if (promote_status === "promoted" && !forceReason && !confirm("Promote this candidate to production? The live KB rule will be overwritten and the next pipeline run uses the new version. A snapshot of the prior version is retained for a 7-day rollback window.")) {
      return;
    }
    setBusy(id);
    try {
      await api.decideAbExperiment(id, {
        promote_status,
        promoted_by: operator.name,
        promoted_by_id: operator.id,
        promote_note: note,
      });
      await reload();
    } catch (e: any) {
      alert(`${promote_status} failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  const rollback = async (id: number) => {
    if (!operator) {
      alert("Pick a current operator in the header before rolling back.");
      return;
    }
    if (!operator.is_rule_owner) {
      alert(`${operator.name} is not on the rule-owner allow-list. Switch to a rule owner in the header picker to roll back.`);
      return;
    }
    const note = prompt("Optional note describing why you are rolling back:");
    if (note === null) return; // operator cancelled the prompt
    setBusy(id);
    try {
      await api.rollbackAbExperiment(id, {
        rolled_back_by: operator.name,
        rolled_back_by_id: operator.id,
        note: note || undefined,
      });
      await reload();
    } catch (e: any) {
      alert(`Rollback failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  const [editingExp, setEditingExp] = useState<ABExperiment | null>(null);
  const editCandidate = (exp: ABExperiment) => setEditingExp(exp);
  const saveCandidate = async (id: number, candidateJson: string) => {
    setBusy(id);
    try {
      await api.editAbCandidate(id, {
        candidate_prompt: candidateJson,
        edited_by: operator?.name || "rule-owner",
      });
      await reload();
      setEditingExp(null);
    } catch (e: any) {
      alert(`Edit failed: ${e?.message || e}`);
    } finally {
      setBusy(null);
    }
  };

  const forcePromote = async (id: number) => {
    const reason = prompt("Force-promote bypasses the gate. Enter a reasoning sentence (will be saved to the audit trail).");
    if (!reason) return;
    await promote(id, "promoted", reason);
  };

  if (rows === null) return <div className="card p-6 text-sm text-zbrain-muted">Loading experiments…</div>;

  // Order rows so the highest-signal candidates surface first: active shadow
  // and ready candidates ahead of promoted, with retired at the back. Inside
  // each group, larger sample sizes come first so partial collection is
  // visible before fully-collected ones get auto-promoted.
  const stateRank = (r: ABExperiment): number => {
    if (r.promote_status === "ready") return 0;
    if (r.promote_status === "shadow") return 1;
    if (r.promote_status === "promoted") return 2;
    return 3;
  };
  const sortedRows = [...rows].sort((a, b) => stateRank(a) - stateRank(b));
  const DEFAULT_VISIBLE = 5;
  const visibleRows = showAll ? sortedRows : sortedRows.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = sortedRows.length - visibleRows.length;

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
            Active and recent experiments
            <InfoTip text="Shadow comparisons against production. Promotion is single-click for an authorised rule owner. Every promotion is reversible inside the rollback window." />
          </h2>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="pill bg-amber-50 text-amber-700 border border-amber-200">
            Shadow {rows.filter((r) => r.promote_status === "shadow").length}
          </span>
          <span className="pill bg-zbrain-50 text-zbrain border border-zbrain/20">
            Ready {rows.filter((r) => r.promote_status === "ready").length}
          </span>
          <span className="pill bg-emerald-50 text-emerald-700 border border-emerald-200">
            Promoted {rows.filter((r) => r.promote_status === "promoted").length}
          </span>
          <span className="pill bg-zinc-100 text-zinc-600">
            Retired {rows.filter((r) => r.promote_status === "retired").length}
          </span>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-6 text-sm text-zbrain-muted text-center">No experiments yet.</div>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead className="bg-zbrain-surface text-[11px] uppercase tracking-wider text-zbrain-muted">
              <tr className="border-b border-zbrain-divider">
                <th className="text-left px-4 py-2.5 font-semibold">Baseline &amp; candidate</th>
                <th className="text-left px-3 py-2.5 font-semibold">Sample</th>
                <th className="text-left px-3 py-2.5 font-semibold">Target · Observed · Δ</th>
                <th className="text-left px-3 py-2.5 font-semibold">Regression</th>
                <th className="text-left px-3 py-2.5 font-semibold">Status</th>
                <th className="text-right px-3 py-2.5 font-semibold">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zbrain-divider/70">
              {visibleRows.map((x) => (
                <FragmentABRow
                  key={x.id}
                  row={x}
                  baseline={lookupBaseline(x.baseline_id)}
                  highlighted={x.id === highlightId}
                  expanded={expandedId === x.id}
                  busy={busy === x.id}
                  onToggle={() => setExpandedId(expandedId === x.id ? null : x.id)}
                  onBacktest={() => runBacktest(x.id)}
                  onPromote={() => promote(x.id, "promoted")}
                  onForcePromote={() => forcePromote(x.id)}
                  onRetire={() => promote(x.id, "retired")}
                  onRollback={() => rollback(x.id)}
                  onEdit={() => editCandidate(x)}
                  onOpenDrill={onOpenDrill}
                />
              ))}
            </tbody>
          </table>
          {sortedRows.length > DEFAULT_VISIBLE && (
            <div className="px-4 py-2.5 border-t border-zbrain-divider bg-zbrain-surface/40 text-center">
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="text-[12px] font-semibold text-zbrain hover:underline"
              >
                {showAll
                  ? `Collapse to top ${DEFAULT_VISIBLE}`
                  : `Show all (${sortedRows.length})${hiddenCount > 0 ? ` · ${hiddenCount} hidden` : ""}`}
              </button>
            </div>
          )}
        </>
      )}
      {editingExp && (
        <EditCandidateModal
          exp={editingExp}
          onCancel={() => setEditingExp(null)}
          onSave={saveCandidate}
        />
      )}
    </div>
  );
}

function EditCandidateModal({
  exp, onCancel, onSave,
}: {
  exp: ABExperiment;
  onCancel: () => void;
  onSave: (id: number, candidateJson: string) => void | Promise<void>;
}) {
  const ct = (exp.change_type || "prompt").toLowerCase();
  const parsed = (() => {
    try { return JSON.parse(exp.candidate_prompt || "{}"); }
    catch { return {}; }
  })();
  const [body, setBody] = useState<any>(parsed);
  const [showRaw, setShowRaw] = useState(false);
  const [rawText, setRawText] = useState(JSON.stringify(parsed, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);

  const updateBody = (next: any) => {
    setBody(next);
    setRawText(JSON.stringify(next, null, 2));
  };
  const onRawChange = (s: string) => {
    setRawText(s);
    try {
      setBody(JSON.parse(s));
      setParseError(null);
    } catch (e: any) {
      setParseError(`Invalid JSON: ${e.message}`);
    }
  };
  const submit = () => onSave(exp.id, JSON.stringify(body, null, 2));

  const helpByType: Record<string, string> = {
    prompt: "Edits the classifier KB rule body. Saving resets the experiment to Proposed and clears the prior back-test result.",
    threshold: "Edits the proposed confidence floor. Saving resets the experiment to Proposed.",
    pattern_list: "Edits the proposed keyword additions. Saving resets the experiment to Proposed.",
    routing_rule: "Edits the proposed routing entry. Saving resets the experiment to Proposed.",
    validation_rule: "Edits the proposed pre-flight verifier rule. Saving resets the experiment to Proposed.",
  };

  return (
    <div className="fixed inset-0 z-40 bg-black/40 flex items-center justify-center p-6" onClick={onCancel}>
      <div
        className="bg-white rounded-lg shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-zbrain-divider flex items-start justify-between">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Edit candidate</div>
            <div className="text-base font-semibold text-zbrain-ink mt-0.5">{exp.candidate || "Experiment"}</div>
            <div className="text-[11px] text-zbrain-muted mt-0.5">Type: {ct} · {exp.kb_namespace}/{exp.kb_key}</div>
          </div>
          <button onClick={onCancel} className="text-zbrain-muted hover:text-zbrain-ink text-xl leading-none">×</button>
        </div>
        <div className="px-5 py-3 text-[12px] text-zbrain-ink/80 border-b border-zbrain-divider bg-emerald-50/40">
          {helpByType[ct] || "Edits the candidate body."}
        </div>
        <div className="p-5 overflow-y-auto flex-1 space-y-4">
          {!showRaw && ct === "threshold" && (
            <FormFieldL label="Proposed L4 confidence floor (0.00–1.00)">
              <input
                type="number" min={0} max={1} step={0.01}
                value={Number.isFinite(Number(body.l4_floor)) ? Number(body.l4_floor) : 0.95}
                onChange={(e) => updateBody({ ...body, l4_floor: Number(e.target.value) })}
                className="w-32 text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
              />
              <div className="text-[11px] text-zbrain-muted mt-1">Raising this routes more cases to L3 review. Lowering it lets more cases auto-close at L4.</div>
            </FormFieldL>
          )}

          {!showRaw && ct === "pattern_list" && (
            <FormFieldL label="Keywords this rule recognises (Enter to add a phrase)">
              <ChipList
                value={Array.isArray(body.keywords) ? body.keywords : []}
                onChange={(v) => updateBody({ ...body, keywords: v })}
              />
            </FormFieldL>
          )}

          {!showRaw && ct === "routing_rule" && (
            <>
              <FormFieldL label="Routes (per-intent assignment)">
                <RoutesEditor
                  value={Array.isArray(body.routes) ? body.routes : []}
                  onChange={(v) => updateBody({ ...body, routes: v })}
                />
              </FormFieldL>
            </>
          )}

          {!showRaw && ct === "validation_rule" && (
            <>
              <FormFieldL label="Rule ID">
                <input
                  type="text"
                  value={String(body.rule_id || "")}
                  onChange={(e) => updateBody({ ...body, rule_id: e.target.value })}
                  className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
                  placeholder="e.g. require_po_number_for_service_order"
                />
              </FormFieldL>
              <FormFieldL label="Trigger (when this is true, the rule fires)">
                <textarea
                  rows={2}
                  value={String(body.fires_on || "")}
                  onChange={(e) => updateBody({ ...body, fires_on: e.target.value })}
                  spellCheck={false}
                  className="w-full font-mono text-[12px] border border-zbrain-divider rounded-md px-2 py-1.5"
                  placeholder="intent='service_order' AND extracted.po_number is missing or empty"
                />
              </FormFieldL>
              <FormFieldL label="Action when the rule fires">
                <select
                  value={String(body.action || "")}
                  onChange={(e) => updateBody({ ...body, action: e.target.value })}
                  className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
                >
                  <option value="">(pick an action)</option>
                  <option value="request_enrichment:po_number">Request CSR to add po_number</option>
                  <option value="request_enrichment:ship_to">Request CSR to add ship_to</option>
                  <option value="request_enrichment:quote_number">Request CSR to add quote_number</option>
                  <option value="request_enrichment:customer_id">Request CSR to add customer_id</option>
                  <option value="require_review_against_historical_band">Require review against historical band</option>
                  <option value="route_to_track:service_contract">Route to Service Contract track</option>
                  <option value="halt_pipeline_and_route_to_hitl">Halt and route to HITL (fallback)</option>
                </select>
              </FormFieldL>
              <FormFieldL label="Severity">
                <select
                  value={String(body.severity || "block_until_enriched")}
                  onChange={(e) => updateBody({ ...body, severity: e.target.value })}
                  className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
                >
                  <option value="block_until_enriched">Block until enriched (pause for CSR)</option>
                  <option value="review_recommended">Review recommended (do not block)</option>
                  <option value="block">Block (no auto-action)</option>
                </select>
              </FormFieldL>
            </>
          )}

          {!showRaw && ct === "prompt" && (
            <>
              <FormFieldL label="Positive examples (phrases that mean this intent applies)">
                <ChipList
                  value={Array.isArray(body.examples_positive) ? body.examples_positive : []}
                  onChange={(v) => updateBody({ ...body, examples_positive: v })}
                />
              </FormFieldL>
              <FormFieldL label="Negative examples (phrases that look related but should NOT be this intent)">
                <ChipList
                  value={Array.isArray(body.examples_negative) ? body.examples_negative : []}
                  onChange={(v) => updateBody({ ...body, examples_negative: v })}
                />
              </FormFieldL>
              <FormFieldL label="Keywords (deterministic-rule terms that route to this intent)">
                <ChipList
                  value={Array.isArray(body.keywords) ? body.keywords : []}
                  onChange={(v) => updateBody({ ...body, keywords: v })}
                />
              </FormFieldL>
            </>
          )}

          <label className="flex items-center gap-2 text-[11px] text-zbrain-muted cursor-pointer pt-2 border-t border-zbrain-divider/60">
            <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
            Show raw JSON (developer view)
          </label>
          {showRaw && (
            <textarea
              value={rawText}
              onChange={(e) => onRawChange(e.target.value)}
              spellCheck={false}
              className="w-full text-[11px] font-mono p-3 min-h-[240px] border border-zbrain-divider rounded-md focus:border-zbrain focus:outline-none"
            />
          )}
          {parseError && showRaw && (
            <div className="text-[11px] text-rose-600">{parseError}</div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-zbrain-divider flex items-center gap-2 justify-end bg-zbrain-surface">
          <button onClick={onCancel} className="px-3 py-1.5 text-xs rounded-md border border-zbrain-divider bg-white">Cancel</button>
          <button
            onClick={submit}
            disabled={!!parseError}
            className="px-4 py-1.5 text-xs font-medium rounded-md bg-zbrain text-white hover:opacity-90 disabled:opacity-50"
          >Save candidate</button>
        </div>
      </div>
    </div>
  );
}

function ExperimentDiff({ exp }: { exp: ABExperiment }) {
  const [showRaw, setShowRaw] = useState(false);
  const ct = (exp.change_type || "prompt").toLowerCase();
  const parse = (s: string | null | undefined) => {
    if (!s) return null;
    try { return JSON.parse(s); } catch { return null; }
  };
  const ctrl = parse(exp.control_prompt);
  const cand = parse(exp.candidate_prompt);
  const hasAny = ctrl || cand;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] uppercase tracking-wide font-semibold text-zbrain-muted">
          Current rule vs. proposed change
        </div>
        <label className="flex items-center gap-1.5 text-[11px] text-zbrain-muted cursor-pointer">
          <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
          Show raw JSON
        </label>
      </div>

      {!showRaw && hasAny && ct === "threshold" && (
        <DiffRowPair
          label="L4 confidence floor"
          before={ctrl?.l4_floor != null ? Number(ctrl.l4_floor).toFixed(2) : "(unknown)"}
          after={cand?.l4_floor != null ? Number(cand.l4_floor).toFixed(2) : "(unset)"}
          note="Cases at this confidence or above auto-close at L4. Below it, they route to L3 review."
        />
      )}

      {!showRaw && hasAny && ct === "pattern_list" && (
        <PatternListDiff before={ctrl?.keywords || []} after={cand?.keywords || []} />
      )}

      {!showRaw && hasAny && ct === "routing_rule" && (
        <RoutingDiff before={ctrl?.routes || []} after={cand?.routes || []} />
      )}

      {!showRaw && hasAny && ct === "validation_rule" && (
        <ValidationRuleDiff before={ctrl} after={cand} />
      )}

      {!showRaw && hasAny && ct === "prompt" && (
        <PromptDiff before={ctrl} after={cand} />
      )}

      {(showRaw || !hasAny) && (
        <div className="grid md:grid-cols-2 gap-4 text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-wide font-semibold text-zbrain-muted mb-1">Current rule (live in production)</div>
            <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded bg-white border border-zbrain-divider p-3 text-[11px] leading-snug">
              {exp.control_prompt || "(not captured)"}
            </pre>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide font-semibold text-zbrain-muted mb-1">Proposed change</div>
            <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded bg-white border border-zbrain/30 p-3 text-[11px] leading-snug">
              {exp.candidate_prompt || "(not yet drafted; click Edit candidate to write one)"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function DiffRowPair({ label, before, after, note }: { label: string; before: string; after: string; note?: string }) {
  const changed = before !== after;
  return (
    <div className="rounded-md border border-zbrain-divider p-3">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-2">{label}</div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] text-zbrain-muted mb-0.5">Now</div>
          <div className="text-lg font-semibold text-zbrain-ink tabular-nums">{before}</div>
        </div>
        <div>
          <div className="text-[10px] text-zbrain-muted mb-0.5">Proposed</div>
          <div className={`text-lg font-semibold tabular-nums ${changed ? "text-emerald-700" : "text-zbrain-ink"}`}>
            {after} {changed && <span className="text-[11px] font-normal">({before} → {after})</span>}
          </div>
        </div>
      </div>
      {note && <div className="text-[11px] text-zbrain-muted mt-2">{note}</div>}
    </div>
  );
}

function PatternListDiff({ before, after }: { before: string[]; after: string[] }) {
  const beforeSet = new Set(before.map((s) => s.toLowerCase()));
  const afterSet = new Set(after.map((s) => s.toLowerCase()));
  const added = after.filter((s) => !beforeSet.has(s.toLowerCase()));
  const removed = before.filter((s) => !afterSet.has(s.toLowerCase()));
  const kept = before.filter((s) => afterSet.has(s.toLowerCase()));
  return (
    <div className="rounded-md border border-zbrain-divider p-3">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-2">Keyword list changes</div>
      <div className="space-y-2 text-xs">
        {added.length > 0 && (
          <div>
            <div className="text-[10px] text-emerald-700 font-semibold mb-1">Added ({added.length})</div>
            <div className="flex flex-wrap gap-1.5">
              {added.map((p, i) => <span key={i} className="pill bg-emerald-50 text-emerald-800 border border-emerald-200 text-[11px]">+ {p}</span>)}
            </div>
          </div>
        )}
        {removed.length > 0 && (
          <div>
            <div className="text-[10px] text-rose-700 font-semibold mb-1">Removed ({removed.length})</div>
            <div className="flex flex-wrap gap-1.5">
              {removed.map((p, i) => <span key={i} className="pill bg-rose-50 text-rose-800 border border-rose-200 text-[11px] line-through">{p}</span>)}
            </div>
          </div>
        )}
        {kept.length > 0 && (
          <details>
            <summary className="text-[10px] text-zbrain-muted font-semibold cursor-pointer hover:text-zbrain-ink">Unchanged ({kept.length})</summary>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {kept.map((p, i) => <span key={i} className="pill bg-zinc-50 text-zinc-700 border border-zinc-200 text-[11px]">{p}</span>)}
            </div>
          </details>
        )}
        {added.length === 0 && removed.length === 0 && (
          <div className="text-[11px] text-zbrain-muted italic">No changes to the keyword list.</div>
        )}
      </div>
    </div>
  );
}

function RoutingDiff({ before, after }: { before: any[]; after: any[] }) {
  const keyOf = (r: any) => `${r?.intent || ""}|${r?.queue || ""}`;
  const beforeMap = new Map(before.map((r) => [r?.intent, r]));
  const afterMap  = new Map(after.map((r) => [r?.intent, r]));
  const allIntents = Array.from(new Set([...beforeMap.keys(), ...afterMap.keys()]));
  return (
    <div className="rounded-md border border-zbrain-divider p-3">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-2">Routing changes</div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-zbrain-muted">
            <th className="text-left py-1">Intent</th>
            <th className="text-left py-1">Now routes to</th>
            <th className="text-left py-1">Proposed</th>
          </tr>
        </thead>
        <tbody>
          {allIntents.map((i) => {
            const b = beforeMap.get(i)?.queue || "(no rule)";
            const a = afterMap.get(i)?.queue || "(no rule)";
            const changed = keyOf({ intent: i, queue: b }) !== keyOf({ intent: i, queue: a });
            return (
              <tr key={i || "x"} className={`border-t border-zbrain-divider/60 ${changed ? "bg-emerald-50/40" : ""}`}>
                <td className="py-1.5 font-medium">{i}</td>
                <td className="py-1.5 text-zbrain-muted">{b}</td>
                <td className={`py-1.5 ${changed ? "text-emerald-700 font-medium" : ""}`}>{a}</td>
              </tr>
            );
          })}
          {allIntents.length === 0 && (
            <tr><td colSpan={3} className="py-2 text-[11px] text-zbrain-muted italic">No routes defined.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ValidationRuleDiff({ before, after }: { before: any | null; after: any | null }) {
  const Row = ({ label, b, a }: { label: string; b: any; a: any }) => {
    const changed = JSON.stringify(b) !== JSON.stringify(a);
    return (
      <div className="grid grid-cols-3 gap-3 py-1.5 text-xs border-t border-zbrain-divider/60">
        <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold pt-1">{label}</div>
        <div className="text-zbrain-muted">{b == null ? <span className="italic">(unset)</span> : String(b)}</div>
        <div className={changed ? "text-emerald-700 font-medium" : ""}>{a == null ? <span className="italic">(unset)</span> : String(a)}</div>
      </div>
    );
  };
  return (
    <div className="rounded-md border border-zbrain-divider p-3">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">Validation rule changes</div>
      <div className="grid grid-cols-3 gap-3 pt-1.5 text-[10px] uppercase tracking-wider text-zbrain-muted">
        <div></div>
        <div>Now</div>
        <div>Proposed</div>
      </div>
      <Row label="Rule ID" b={before?.rule_id} a={after?.rule_id} />
      <Row label="Trigger" b={before?.fires_on} a={after?.fires_on} />
      <Row label="Action"  b={before?.action}   a={after?.action} />
      <Row label="Severity" b={before?.severity} a={after?.severity} />
    </div>
  );
}

function PromptDiff({ before, after }: { before: any | null; after: any | null }) {
  const listDiff = (b: string[], a: string[]) => {
    const bs = new Set(b.map((s) => s.toLowerCase()));
    const as_ = new Set(a.map((s) => s.toLowerCase()));
    return {
      added: a.filter((s) => !bs.has(s.toLowerCase())),
      removed: b.filter((s) => !as_.has(s.toLowerCase())),
    };
  };
  const ep = listDiff(before?.examples_positive || [], after?.examples_positive || []);
  const en = listDiff(before?.examples_negative || [], after?.examples_negative || []);
  const kw = listDiff(before?.keywords || [], after?.keywords || []);
  const Sec = ({ title, d }: { title: string; d: { added: string[]; removed: string[] } }) => (
    (d.added.length > 0 || d.removed.length > 0) ? (
      <div className="mb-2">
        <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">{title}</div>
        <div className="flex flex-wrap gap-1.5">
          {d.added.map((p, i) => <span key={`a${i}`} className="pill bg-emerald-50 text-emerald-800 border border-emerald-200 text-[11px]">+ {p}</span>)}
          {d.removed.map((p, i) => <span key={`r${i}`} className="pill bg-rose-50 text-rose-800 border border-rose-200 text-[11px] line-through">{p}</span>)}
        </div>
      </div>
    ) : null
  );
  return (
    <div className="rounded-md border border-zbrain-divider p-3">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-2">Classifier prompt changes</div>
      <Sec title="Positive examples" d={ep} />
      <Sec title="Negative examples" d={en} />
      <Sec title="Keywords" d={kw} />
      {ep.added.length === 0 && ep.removed.length === 0 && en.added.length === 0 && en.removed.length === 0 && kw.added.length === 0 && kw.removed.length === 0 && (
        <div className="text-[11px] text-zbrain-muted italic">No changes to examples or keywords. The change may be in the description or other fields; toggle Show raw JSON to inspect.</div>
      )}
    </div>
  );
}

function FormFieldL({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">{label}</div>
      {children}
    </label>
  );
}

function ChipList({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState("");
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {value.length === 0 && <span className="text-[11px] text-zbrain-muted italic">(empty)</span>}
        {value.map((v, i) => (
          <span key={i} className="pill bg-zbrain-50 text-zbrain-ink text-[11px] inline-flex items-center gap-1">
            {v}
            <button onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-zbrain-muted hover:text-rose-700">×</button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && text.trim()) {
              e.preventDefault();
              onChange([...value, text.trim()]);
              setText("");
            }
          }}
          placeholder="Type a phrase and press Enter"
          className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 flex-1"
        />
        <button
          type="button"
          onClick={() => {
            if (text.trim()) { onChange([...value, text.trim()]); setText(""); }
          }}
          className="text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50"
        >Add</button>
      </div>
    </div>
  );
}

function RoutesEditor({ value, onChange }: { value: any[]; onChange: (v: any[]) => void }) {
  const addRow = () => onChange([...value, { intent: "", queue: "" }]);
  return (
    <div>
      <div className="space-y-1.5">
        {value.length === 0 && <div className="text-[11px] text-zbrain-muted italic">No routes defined yet.</div>}
        {value.map((r, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              value={r.intent || ""}
              onChange={(e) => onChange(value.map((x, j) => j === i ? { ...x, intent: e.target.value } : x))}
              placeholder="intent (e.g. trade_change_order)"
              className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 flex-1"
            />
            <span className="text-zbrain-muted text-xs">→</span>
            <input
              value={r.queue || ""}
              onChange={(e) => onChange(value.map((x, j) => j === i ? { ...x, queue: e.target.value } : x))}
              placeholder="queue (e.g. SOM CSR)"
              className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 flex-1"
            />
            <button onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-[11px] text-zbrain-muted hover:text-rose-700">Remove</button>
          </div>
        ))}
      </div>
      <button type="button" onClick={addRow} className="mt-2 text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50">Add route</button>
    </div>
  );
}

const STATE_STEPS = ["Proposed", "Backtested", "Ready", "Promoted"];

function StateProgression({ state }: { state: string }) {
  const stateIdx = state === "Retired" ? -1 : Math.max(0, STATE_STEPS.indexOf(state));
  return (
    <div className="flex items-center gap-1">
      {STATE_STEPS.map((s, i) => {
        const isActive = i === stateIdx;
        const isPast = i < stateIdx;
        const isRetired = state === "Retired";
        const cls = isRetired
          ? "bg-zinc-100 text-zinc-500 border-zinc-200"
          : isActive
          ? "bg-zbrain text-white border-zbrain"
          : isPast
          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : "bg-white text-zbrain-muted border-zbrain-divider";
        return (
          <span key={s} className={`pill text-[10px] border ${cls}`}>
            {i + 1}. {s}
          </span>
        );
      })}
      {state === "Retired" && (
        <span className="pill text-[10px] bg-rose-50 text-rose-700 border border-rose-200">Retired</span>
      )}
    </div>
  );
}

function ChangeTypeLabel(t: string | undefined): string {
  switch (t) {
    case "prompt": return "Prompt update";
    case "threshold": return "Threshold change";
    case "pattern_list": return "Pattern list edit";
    case "routing_rule": return "Routing rule change";
    case "validation_rule": return "Validation rule change";
    case "other": return "Other change";
    default: return "Prompt update";
  }
}

function FragmentABRow({
  row: x,
  baseline,
  expanded,
  highlighted,
  busy,
  onToggle,
  onBacktest,
  onPromote,
  onForcePromote,
  onRetire,
  onRollback,
  onEdit,
  onOpenDrill,
}: {
  row: ABExperiment;
  baseline: BaselineAnchor | null;
  expanded: boolean;
  highlighted?: boolean;
  busy: boolean;
  onToggle: () => void;
  onBacktest: () => void;
  onPromote: () => void;
  onForcePromote: () => void;
  onRetire: () => void;
  onRollback: () => void;
  onEdit: () => void;
  onOpenDrill?: (id: number) => void;
}) {
  const kbTarget = x.kb_namespace && x.kb_key ? `${x.kb_namespace}/${x.kb_key}` : null;
  const bt = (x.backtest_results as any) || null;
  const state = x.state || (x.promote_status === "shadow" ? (x.backtest_ran_at ? "Backtested" : "Proposed") : x.promote_status === "ready" ? "Ready" : x.promote_status === "promoted" ? "Promoted" : "Retired");
  const gate = x.promote_gate || { enabled: false };
  const rollbackInfo = x.rollback || { available: false };
  const sample = Array.isArray(x.backtest_sample) ? x.backtest_sample : [];
  const agreedCount = sample.filter((r) => r.agreed).length;
  const disagreedCount = sample.length - agreedCount;

  // Target / Observed / Delta numbers for the mini-stats column.
  //
  //   Target   = baseline.target_value (the operator-set quality floor or
  //              ceiling for this Baseline Quality Target).
  //   Observed = candidate accuracy computed from the backtest sample
  //              (count(candidate_correct) / sample_size). When no sample
  //              has been collected yet, we mark the row "pending".
  //   Delta    = observed minus target, expressed in percentage points.
  //              The arrow direction is baseline-direction-aware: a "min"
  //              baseline wants observed >= target (up arrow = good when
  //              delta >= 0); a "max" baseline wants observed <= target
  //              (up arrow = good when delta <= 0).
  const targetValue =
    baseline && typeof (baseline as any).target_value === "number"
      ? ((baseline as any).target_value as number)
      : null;
  const direction =
    baseline && ((baseline as any).direction === "min" || (baseline as any).direction === "max")
      ? ((baseline as any).direction as "min" | "max")
      : null;
  const baselineUnit =
    baseline && typeof (baseline as any).unit === "string"
      ? ((baseline as any).unit as string)
      : null;
  const observedRatio =
    sample.length > 0
      ? sample.filter((r) => r.candidate_correct).length / sample.length
      : null;
  const deltaPp =
    observedRatio != null && targetValue != null
      ? (observedRatio - targetValue) * 100
      : x.accuracy_delta_pct;
  const directionalGood =
    deltaPp == null
      ? null
      : direction === "max"
        ? deltaPp <= 0
        : deltaPp >= 0;
  const deltaArrow =
    deltaPp == null
      ? "·"
      : Math.abs(deltaPp) < 0.05
        ? "→"
        : directionalGood
          ? "↑"
          : "↓";
  const deltaTone =
    deltaPp == null
      ? "text-zbrain-muted"
      : directionalGood
        ? "text-emerald-700"
        : "text-rose-700";
  const fmtMetricValue = (n: number | null): string => {
    if (n == null) return "pending";
    if (baselineUnit === "ratio" || (Math.abs(n) <= 1 && Math.abs(n) > 0)) {
      return `${(n * 100).toFixed(1)}%`;
    }
    if (baselineUnit === "ms" || baselineUnit === "seconds") {
      return `${n.toFixed(0)}${baselineUnit === "ms" ? "ms" : "s"}`;
    }
    if (Math.abs(n) >= 100) return n.toFixed(1);
    if (Math.abs(n) >= 1) return n.toFixed(2);
    return n.toFixed(3);
  };
  const targetCell = targetValue != null ? fmtMetricValue(targetValue) : "no target";
  const observedCell =
    observedRatio != null ? fmtMetricValue(observedRatio) : "pending";
  const deltaCell =
    deltaPp != null ? `${deltaPp >= 0 ? "+" : ""}${deltaPp.toFixed(1)}pp` : "pending";

  return (
    <>
      <tr
        id={`ab-exp-${x.id}`}
        className={
          "align-top hover:bg-zbrain-surface/40 cursor-pointer " +
          (highlighted ? "bg-zbrain-50/70 ring-2 ring-zbrain/40" : "")
        }
        onClick={onToggle}
      >
        <td className="px-4 py-2.5 text-zbrain-ink text-sm">
          <div className="flex items-start gap-2">
            <span className="text-zbrain-muted text-[10px] w-3 mt-1">{expanded ? "▾" : "▸"}</span>
            <div className="min-w-0 flex-1">
              {/* BaselineChip is the leftmost, primary anchor */}
              <div onClick={(e) => e.stopPropagation()}>
                <BaselineChip
                  baselineId={x.baseline_id ?? null}
                  baselineLabel={x.baseline_label ?? null}
                  onClick={onOpenDrill}
                  size="md"
                />
              </div>
              <div className="font-medium mt-1">{x.candidate}</div>
              <div className="text-[10px] text-zbrain-muted mt-0.5 font-mono">
                {x.segment}
                {kbTarget && <> · KB {kbTarget}</>}
                {x.horizon_value && <> · {x.horizon_value}</>}
              </div>
            </div>
          </div>
        </td>
        <td className="px-3 py-2.5 text-zbrain-muted text-xs tabular-nums">
          <div className="font-semibold text-zbrain-ink">{x.sample_collected} / {x.sample_target}</div>
          <div className="text-[10px] mt-0.5">
            {x.sample_target > 0
              ? `${Math.min(100, Math.round((x.sample_collected / x.sample_target) * 100))}% collected`
              : "no target"}
          </div>
        </td>
        <td className="px-3 py-2.5 text-xs">
          <div className="space-y-0.5 tabular-nums">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[9.5px] uppercase tracking-wider text-zbrain-muted font-semibold w-[58px] shrink-0">
                Target
              </span>
              <span className="text-zbrain-ink font-semibold text-[11.5px]">
                {targetValue != null && direction
                  ? `${direction === "max" ? "≤" : "≥"} ${targetCell}`
                  : targetCell}
              </span>
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-[9.5px] uppercase tracking-wider text-zbrain-muted font-semibold w-[58px] shrink-0">
                Observed
              </span>
              <span
                className={`font-semibold text-[11.5px] ${
                  observedRatio == null ? "text-zbrain-muted italic" : "text-zbrain-ink"
                }`}
              >
                {observedCell}
              </span>
            </div>
            <div className={`flex items-baseline gap-1.5 ${deltaTone}`}>
              <span className="text-[9.5px] uppercase tracking-wider opacity-80 font-semibold w-[58px] shrink-0">
                {"Δ"}
              </span>
              <span
                className="font-semibold text-[11.5px] inline-flex items-center gap-1"
                title="Observed minus target in percentage points. Arrow is direction-aware: it points up when the candidate is moving the metric toward the target, down when moving away."
              >
                <span aria-hidden>{deltaArrow}</span>
                <span>{deltaCell}</span>
              </span>
            </div>
          </div>
          <div className="text-[10px] text-zbrain-muted mt-1">gate +2.0pp</div>
        </td>
        <td className="px-3 py-2.5">
          <span className={regressionPill(x.regression_status)}>
            {x.regression_status === "none" ? "None" : x.regression_status === "watch" ? "Watch" : "Fail"}
          </span>
        </td>
        <td className="px-3 py-2.5">
          <span className={promoteStatusPill(x.promote_status)}>{x.promote_status}</span>
          {x.promoted_by && (
            <div className="text-[10px] text-zbrain-muted mt-0.5">by {x.promoted_by}</div>
          )}
        </td>
        <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
          <div className="flex flex-col gap-1.5 items-end">
            {state !== "Promoted" && state !== "Retired" && (
              <button
                onClick={onBacktest}
                disabled={busy || !x.candidate_prompt}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-zbrain text-white hover:opacity-90 disabled:opacity-40 whitespace-nowrap"
                title={x.candidate_prompt
                  ? "Replay this candidate against historical pipelines using the live classifier with the candidate KB body injected."
                  : "Disabled: this experiment has no candidate body yet. Edit candidate first."}
              >
                {busy ? "Running…" : x.backtest_ran_at ? "Re-run backtest" : "Run backtest"}
              </button>
            )}
            {state !== "Promoted" && state !== "Retired" && (
              <button
                onClick={onPromote}
                disabled={busy || !gate.enabled}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 text-white hover:opacity-90 disabled:opacity-40 whitespace-nowrap"
                title={gate.enabled
                  ? "Apply candidate to production KB rule."
                  : "Disabled. " + (Array.isArray((gate as any).reasons)
                      ? (gate as any).reasons
                          .filter((c: any) => !c.met)
                          .map((c: any) => `${c.label} (observed: ${c.observed ?? "n/a"} / required: ${c.threshold})`)
                          .join(" · ")
                      : `gate not satisfied: ${gate.reason || "unknown"}`)}
              >
                Promote
              </button>
            )}
            {state !== "Promoted" && state !== "Retired" && !gate.enabled && x.backtest_ran_at && (
              <button
                onClick={onForcePromote}
                disabled={busy}
                className="px-2 py-1 text-[10px] font-medium rounded-md bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 whitespace-nowrap"
                title="Override the promote gate with an explicit reason."
              >
                Force-promote…
              </button>
            )}
            {state === "Promoted" && rollbackInfo.available && (
              <button
                onClick={onRollback}
                disabled={busy}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-rose-50 text-rose-800 border border-rose-200 hover:bg-rose-100 whitespace-nowrap"
                title={`Restore the prior KB version. ${rollbackInfo.days_remaining ?? 0} day(s) left in rollback window.`}
              >
                Rollback
              </button>
            )}
            {state !== "Promoted" && state !== "Retired" && (
              <button
                onClick={onEdit}
                disabled={busy}
                className="px-2 py-1 text-[10px] font-medium rounded-md bg-white text-zbrain-muted border border-zbrain-divider hover:bg-zinc-50 whitespace-nowrap"
                title="Revise the candidate. Saving resets state to Proposed."
              >
                Edit candidate
              </button>
            )}
            {state !== "Promoted" && state !== "Retired" && (
              <button
                onClick={onRetire}
                disabled={busy}
                className="px-2 py-1 text-[10px] font-medium rounded-md bg-white text-zbrain-muted border border-zbrain-divider hover:bg-zinc-50 whitespace-nowrap"
              >
                Retire
              </button>
            )}
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-zbrain-surface/30">
          <td colSpan={6} className="px-4 py-4">
            {/* State progression strip */}
            <div className="mb-4 flex items-center justify-between gap-3 flex-wrap">
              <StateProgression state={state} />
              <div className="text-[11px] text-zbrain-muted">
                Change type: <strong className="text-zbrain-ink">{ChangeTypeLabel(x.change_type)}</strong>
              </div>
            </div>

            {/* Gate / Rollback callouts */}
            {state !== "Promoted" && state !== "Retired" && !gate.enabled && (
              <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
                <strong>Promotion locked.</strong>{" "}
                {gate.reason === "no_backtest_run" && "Run a backtest first."}
                {gate.reason === "sample_too_small" && `Backtest sample is ${gate.n}; need at least ${gate.min}.`}
                {gate.reason === "delta_below_gate" && `Candidate delta is ${gate.delta_pct != null ? (gate.delta_pct > 0 ? "+" : "") + gate.delta_pct + "pp" : "n/a"}, gate requires +${gate.min_pct}pp.`}
                {" "}Use <em>Force-promote</em> with a written reason to override.
              </div>
            )}
            {state === "Promoted" && rollbackInfo.available && (
              <div className="mb-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-900">
                <strong>Live in production.</strong> Promoted by <strong>{x.promoted_by}</strong>{x.promoted_at ? ` on ${new Date(x.promoted_at).toLocaleString()}` : ""}. Previous version retained for rollback for {rollbackInfo.days_remaining ?? 0} more day(s).
              </div>
            )}
            {state === "Retired" && (
              <div className="mb-3 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-[12px] text-zinc-700">
                <strong>Retired.</strong>{x.rolled_back_at && <> Rolled back on {new Date(x.rolled_back_at).toLocaleString()} by {x.rolled_back_by || "unknown"}.</>}
                {x.rolled_back_note && <div className="mt-1 text-[11px] italic">"{x.rolled_back_note}"</div>}
              </div>
            )}

            <ExperimentDiff exp={x} />


            {bt ? (
              <div className="mt-4">
                <div className="text-[10px] uppercase tracking-wide font-semibold text-zbrain-muted mb-1">Backtest result</div>
                <div className="rounded bg-white border border-zbrain-divider p-3">
                  <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                    <div>Sample <strong>{bt.sample_size}</strong></div>
                    <div>Current rule <strong>{bt.baseline_accuracy_pct}%</strong> ({bt.baseline_correct}/{bt.sample_size})</div>
                    <div>Proposed <strong>{bt.candidate_accuracy_pct}%</strong> ({bt.candidate_correct}/{bt.sample_size})</div>
                    <div>Delta <strong className={(bt.delta_pct ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700"}>{bt.delta_pct > 0 ? "+" : ""}{bt.delta_pct}pp</strong></div>
                    {x.backtest_ran_at && (
                      <div className="text-zbrain-muted">Run at {new Date(x.backtest_ran_at).toLocaleString()}</div>
                    )}
                  </div>
                </div>
              </div>
            ) : state === "Proposed" ? (
              <div className="mt-4 text-xs text-zbrain-muted italic">
                No backtest yet. Click <strong>Run backtest</strong> to score this candidate against the historical pipelines from the source opportunity.
              </div>
            ) : null}

            {/* Affected pipelines: the per-row sample the backtest scored */}
            {sample.length > 0 && (
              <div className="mt-4">
                <div className="text-[10px] uppercase tracking-wide font-semibold text-zbrain-muted mb-1.5 flex items-center justify-between">
                  <span>Affected pipelines ({sample.length})</span>
                  <span className="text-zbrain-muted/80 font-normal">
                    {agreedCount} agreed · <span className="text-amber-700">{disagreedCount} would change</span>
                  </span>
                </div>
                <div className="rounded bg-white border border-zbrain-divider max-h-[280px] overflow-auto">
                  <table className="w-full text-[11px]">
                    <thead className="text-zbrain-muted bg-zbrain-surface/60 sticky top-0">
                      <tr>
                        <th className="text-left py-1.5 px-2 font-medium">Pipeline</th>
                        <th className="text-left py-1.5 px-2 font-medium">Subject</th>
                        <th className="text-left py-1.5 px-2 font-medium">Customer</th>
                        <th className="text-left py-1.5 px-2 font-medium">Current verdict</th>
                        <th className="text-left py-1.5 px-2 font-medium">Proposed verdict</th>
                        <th className="text-center py-1.5 px-2 font-medium">Outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sample.slice(0, 100).map((r) => (
                        <tr key={r.pipeline_id} className={`border-t border-zbrain-divider/60 ${r.agreed ? "" : "bg-amber-50/30"}`}>
                          <td className="py-1.5 px-2"><a className="text-zbrain hover:underline" href={traceUrl(r.pipeline_id)} target="_blank" rel="noopener noreferrer">#{r.pipeline_id}</a></td>
                          <td className="py-1.5 px-2 max-w-[280px] truncate" title={r.subject || ""}>{r.subject || "n/a"}</td>
                          <td className="py-1.5 px-2">{r.customer_name || "n/a"}</td>
                          <td className="py-1.5 px-2"><span className={r.baseline_correct ? "text-emerald-700" : "text-rose-700"}>{r.baseline_correct ? "Correct" : "Wrong"}</span> · {r.baseline_intent || "n/a"}</td>
                          <td className="py-1.5 px-2"><span className={r.candidate_correct ? "text-emerald-700" : "text-rose-700"}>{r.candidate_correct ? "Correct" : "Wrong"}</span></td>
                          <td className="py-1.5 px-2 text-center">{r.agreed ? <span className="text-zbrain-muted">=</span> : <span className="text-amber-700 font-medium">would change</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {sample.length > 100 && (
                  <div className="text-[10.5px] text-zbrain-muted mt-1">Showing first 100 of {sample.length}.</div>
                )}
              </div>
            )}

            {/* Deploy target — the KB row this promotion writes to. Surfaces
                "where does this change actually go in the system" with a
                live link to verify the row exists. */}
            {kbTarget && <DeployTargetPanel namespace={x.kb_namespace!} keyName={x.kb_key!} changeType={x.change_type} />}

            {/* Post-promotion details */}
            {state === "Promoted" && (
              <div className="mt-4 rounded border border-emerald-200 bg-emerald-50/50 p-3 text-[12px]">
                <div className="text-[10px] uppercase tracking-wide font-semibold text-emerald-800 mb-1">Production status</div>
                <div className="grid md:grid-cols-3 gap-3">
                  <div><span className="text-emerald-700/70">Promoted at:</span> <strong>{x.promoted_at ? new Date(x.promoted_at).toLocaleString() : "n/a"}</strong></div>
                  <div><span className="text-emerald-700/70">By:</span> <strong>{x.promoted_by || "n/a"}</strong></div>
                  <div><span className="text-emerald-700/70">KB target:</span> <strong>{kbTarget || "n/a"}</strong></div>
                </div>
                {x.promote_note && <div className="mt-2 text-[11px] italic text-emerald-900">"{x.promote_note}"</div>}
                {x.previous_body_snapshot && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[11px] text-emerald-800 hover:underline">View pre-promotion snapshot (used for rollback)</summary>
                    <pre className="mt-2 max-h-[200px] overflow-auto whitespace-pre-wrap rounded bg-white border border-emerald-200 p-2 text-[11px] leading-snug">
                      {typeof x.previous_body_snapshot === "string" ? x.previous_body_snapshot : JSON.stringify(x.previous_body_snapshot, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// === Pill helpers ===========================================================

function fmtMetric(v: number | null): string {
  if (v == null) return "n/a";
  if (Math.abs(v) <= 1) return v.toFixed(2);
  return v.toFixed(1);
}

function severityPill(s: string): string {
  const base = "pill text-[10px] uppercase tracking-wide";
  if (s === "slo_breach") return `${base} bg-rose-100 text-rose-800 border border-rose-200`;
  if (s === "warn") return `${base} bg-amber-100 text-amber-800 border border-amber-200`;
  return `${base} bg-slate-100 text-slate-700`;
}

function statusPill(s: string): string {
  const base = "pill text-[10px] uppercase tracking-wide";
  if (s === "resolved") return `${base} bg-emerald-50 text-emerald-700 border border-emerald-200`;
  if (s === "in_review") return `${base} bg-amber-50 text-amber-700 border border-amber-200`;
  return `${base} bg-rose-50 text-rose-700 border border-rose-200`;
}

function opportunityStatusPill(s: string): string {
  const base = "pill text-[10px] uppercase tracking-wide";
  if (s === "promoted") return `${base} bg-emerald-100 text-emerald-700 border border-emerald-200`;
  if (s === "in_ab") return `${base} bg-zbrain-50 text-zbrain border border-zbrain/20`;
  if (s === "accepted") return `${base} bg-sky-50 text-sky-700 border border-sky-200`;
  if (s === "deferred") return `${base} bg-amber-50 text-amber-700 border border-amber-200`;
  if (s === "rejected" || s === "retired") return `${base} bg-zinc-100 text-zinc-600`;
  return `${base} bg-slate-100 text-slate-700`;
}

function effortRiskPill(level: string, _kind: "effort" | "risk"): string {
  const base = "pill text-[10px] uppercase tracking-wide";
  if (level === "Low") return `${base} bg-emerald-50 text-emerald-700 border border-emerald-200`;
  if (level === "Med") return `${base} bg-amber-50 text-amber-700 border border-amber-200`;
  return `${base} bg-rose-50 text-rose-700 border border-rose-200`;
}

function regressionPill(s: string): string {
  const base = "pill text-[10px] uppercase tracking-wide";
  if (s === "fail") return `${base} bg-rose-100 text-rose-800 border border-rose-200`;
  if (s === "watch") return `${base} bg-amber-50 text-amber-700 border border-amber-200`;
  return `${base} bg-emerald-50 text-emerald-700 border border-emerald-200`;
}

function promoteStatusPill(s: string): string {
  const base = "pill text-[10px] uppercase tracking-wide";
  if (s === "promoted") return `${base} bg-emerald-100 text-emerald-700 border border-emerald-200`;
  if (s === "ready") return `${base} bg-zbrain-50 text-zbrain border border-zbrain/20`;
  if (s === "shadow") return `${base} bg-amber-50 text-amber-700 border border-amber-200`;
  return `${base} bg-zinc-100 text-zinc-600`;
}

// === Continuous Learning Loop visual =========================================
// Mirrors the wheel diagram from the RFP deck: Observe -> Identify -> Promote ->
// Improve, with Drift & Anomaly Detection as the always-on watch in the centre.
// Each loop card shows a real live count and clicks through to the tab where
// that loop runs.
function ContinuousLearningLoop() {
  const [counts, setCounts] = useState<{
    feedback: number;
    drift: number;
    opportunitiesOpen: number;
    abActive: number;
    abPromoted: number;
  }>({ feedback: 0, drift: 0, opportunitiesOpen: 0, abActive: 0, abPromoted: 0 });
  const navigate = useNavigate();

  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const [fb, drift, opps, abs] = await Promise.all([
          api.feedback().catch(() => []),
          api.learningDriftAlerts().catch(() => []),
          api.learningOpportunities().catch(() => []),
          api.learningAbExperiments().catch(() => []),
        ]);
        if (cancel) return;
        setCounts({
          feedback: fb.length,
          drift: drift.filter((d: any) => d.status !== "resolved").length,
          opportunitiesOpen: opps.filter((o: any) => o.status === "open").length,
          abActive: abs.filter((x: any) => x.promote_status === "shadow" || x.promote_status === "ready").length,
          abPromoted: abs.filter((x: any) => x.promote_status === "promoted").length,
        });
      } catch {
        /* leave previous values */
      }
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);

  const go = (tab: string) => navigate(`/learning?tab=${tab}`);

  const cell = (
    letter: string,
    name: string,
    subtitle: string,
    body: string,
    metric: { label: string; value: string | number; tone?: "ok" | "warn" | "neutral" },
    onClick: () => void,
    accent: string,
  ) => (
    <button
      onClick={onClick}
      className="text-left bg-white rounded-xl border border-zbrain-divider hover:border-zbrain hover:shadow-md transition p-4 w-full h-full"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-bold text-white" style={{ background: accent }}>
            {letter}
          </span>
          <div>
            <div className="text-[10px] uppercase tracking-[0.14em] font-semibold text-zbrain-muted">{subtitle}</div>
            <div className="text-sm font-semibold text-zbrain-ink leading-tight">{name}</div>
          </div>
        </div>
      </div>
      <p className="mt-2 text-xs text-zbrain-muted leading-snug">{body}</p>
      <div className="mt-3 flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted">{metric.label}</span>
        <span
          className={`text-2xl font-semibold tabular-nums ${
            metric.tone === "ok" ? "text-emerald-700" : metric.tone === "warn" ? "text-amber-700" : "text-zbrain-ink"
          }`}
        >
          {metric.value}
        </span>
      </div>
    </button>
  );

  return (
    <section className="card p-5 bg-gradient-to-br from-white to-zbrain-surface">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-emerald-700 font-semibold">
            Five learning loops · live since first mailbox cutover
          </div>
          <h2 className="text-base font-semibold text-zbrain-ink mt-1">Continuous Learning Loop</h2>
          <p className="text-xs text-zbrain-muted mt-1 max-w-3xl">
            Each loop converts a CSR action or a Monitor signal into an auditable improvement on a cycle measured in days, with one-click rollback on every promoted change.
          </p>
        </div>
      </div>

      <div className="relative">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_60px_1fr] gap-y-3 gap-x-2 items-stretch">
          {/* Row 1: A → B */}
          {cell(
            "A",
            "Signal capture",
            "Observe",
            "Every CSR action and drift event lands in the Learning Store.",
            { label: "Signals captured", value: counts.feedback, tone: counts.feedback > 0 ? "ok" : "neutral" },
            () => go("feedback"),
            "#1A55F9",
          )}
          <FlowArrow direction="right" label="Cluster" color="#1A55F9" />
          {cell(
            "B",
            "Opportunity identification",
            "Identify",
            "Clustered into ranked candidates with lift, effort, and risk.",
            { label: "Open opportunities", value: counts.opportunitiesOpen, tone: counts.opportunitiesOpen > 0 ? "warn" : "neutral" },
            () => go("tuning"),
            "#7A3CC1",
          )}

          {/* Row 2: vertical arrow ↓ on right column (B → C) and ↑ on left (D → A) */}
          <FlowArrow direction="up" label="Re-seed" color="#0F8FA9" />
          <div className="hidden md:block" />
          <FlowArrow direction="down" label="Promote to A/B" color="#7A3CC1" />

          {/* Row 3: D ← C */}
          {cell(
            "D",
            "Operator-tunable knowledge bases",
            "Improve",
            "Routine rule, glossary, and routing changes happen in the UI, not in code.",
            { label: "Promoted changes", value: counts.abPromoted, tone: counts.abPromoted > 0 ? "ok" : "neutral" },
            () => go("tuning"),
            "#0F8FA9",
          )}
          <FlowArrow direction="left" label="Promoted" color="#C97A0B" />
          {cell(
            "C",
            "A/B promotion",
            "Promote",
            "Shadow comparison against production until pre-defined success criteria gate promotion.",
            { label: "Active experiments", value: counts.abActive, tone: counts.abActive > 0 ? "warn" : "neutral" },
            () => go("experiments"),
            "#C97A0B",
          )}
        </div>

        {/* Loop E — always-on watch, spans the whole flow */}
        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 flex items-center gap-3">
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-full text-[12px] font-bold text-white shrink-0" style={{ background: "#10B981" }}>
            E
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.14em] font-semibold text-emerald-700">Always-on watch · spans A → B → C → D</div>
            <div className="text-sm font-semibold text-zbrain-ink leading-tight">Drift & anomaly detection</div>
            <p className="mt-1 text-xs text-zbrain-muted leading-snug">
              Rolling baselines surface accuracy and confidence anomalies. Crossing the SLO floor pauses auto-action for the affected segment.
            </p>
          </div>
          <button
            onClick={() => go("drift")}
            className="text-xs font-medium text-emerald-700 hover:underline whitespace-nowrap"
          >
            {counts.drift} active alerts →
          </button>
        </div>
      </div>
    </section>
  );
}

function FlowArrow({
  direction,
  label,
  color = "#94A3B8",
}: {
  direction: "up" | "down" | "left" | "right";
  label?: string;
  color?: string;
}) {
  // SVG flow arrow with a visible shaft + arrowhead. Renders inline at the
  // size of its grid cell so adjacent boxes look connected, not just adorned
  // with a tiny floating glyph.
  const horizontal = direction === "left" || direction === "right";
  const w = horizontal ? 60 : 24;
  const h = horizontal ? 24 : 60;
  const stroke = color;
  let line: ReactElement;
  let head: ReactElement;
  if (direction === "right") {
    line = <line x1="2" y1="12" x2="52" y2="12" stroke={stroke} strokeWidth="2" strokeLinecap="round" />;
    head = <polyline points="46,5 56,12 46,19" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />;
  } else if (direction === "left") {
    line = <line x1="8" y1="12" x2="58" y2="12" stroke={stroke} strokeWidth="2" strokeLinecap="round" />;
    head = <polyline points="14,5 4,12 14,19" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />;
  } else if (direction === "down") {
    line = <line x1="12" y1="2" x2="12" y2="52" stroke={stroke} strokeWidth="2" strokeLinecap="round" />;
    head = <polyline points="5,46 12,56 19,46" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />;
  } else {
    line = <line x1="12" y1="8" x2="12" y2="58" stroke={stroke} strokeWidth="2" strokeLinecap="round" />;
    head = <polyline points="5,14 12,4 19,14" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />;
  }
  return (
    <div
      className={`flex ${horizontal ? "flex-col" : "flex-row"} items-center justify-center gap-1 select-none`}
      aria-hidden
    >
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="flex-shrink-0">
        {line}
        {head}
      </svg>
      {label && (
        <span
          className="text-[10px] font-medium uppercase tracking-wide whitespace-nowrap"
          style={{ color }}
        >
          {label}
        </span>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Continuous Learning Hub — five-cell mini-funnel mirroring the framework
// deck (Capture → Detect → Propose → Validate → Promote). Each cell links
// into the corresponding sub-tab on this page; the numbers come straight
// from /api/learning/funnel and /api/learning/sla.
// ────────────────────────────────────────────────────────────────────────

type FunnelData = {
  generated_at: string;
  capture: { trace_events_7d: number; feedback_7d: number };
  detect: { drift_alerts_open: number; drift_alerts_total_30d: number; rca_tickets_open: number };
  propose: { opportunities_open: number; opportunities_accepted: number };
  validate: { shadow: number; ready: number; in_ab: number };
  promote: { promoted_30d: number; auto_rolled_back_30d: number; rolled_back_30d: number };
};

type SlaData = {
  target_p90_hours: number;
  p50_hours: number | null;
  p90_hours: number | null;
  met: boolean;
  samples: number;
};

function HubFunnel({ onJump }: { onJump: (tab: SubTab) => void }) {
  const [f, setF] = useState<FunnelData | null>(null);
  const [sla, setSla] = useState<SlaData | null>(null);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const [fr, sr] = await Promise.all([
          fetch("/api/learning/funnel").then((r) => r.json()),
          fetch("/api/learning/sla").then((r) => r.json()),
        ]);
        if (!cancel) { setF(fr); setSla(sr); }
      } catch { /* ignore */ }
    }
    load();
    const id = setInterval(load, 20000);
    return () => { cancel = true; clearInterval(id); };
  }, []);

  const stages: {
    key: string;
    num: string;
    title: string;
    blurb: string;
    primary: string;
    secondary?: string;
    color: string;
    bg: string;
    onClick?: () => void;
  }[] = [
    {
      key: "capture",
      num: "01",
      title: "Capture",
      blurb: "Telemetry from every decision boundary",
      primary: f ? `${f.capture.trace_events_7d.toLocaleString()} signals · 7d` : "n/a",
      secondary: f ? `${f.capture.feedback_7d} CSR feedback rows` : undefined,
      color: "#1A55F9",
      bg: "rgba(26, 85, 249, 0.06)",
      onClick: () => onJump("feedback"),
    },
    {
      key: "detect",
      num: "02",
      title: "Detect",
      blurb: "Drift alerts + RCA bundles",
      primary: f ? `${f.detect.drift_alerts_open} open drift alerts` : "n/a",
      secondary: f ? `${f.detect.rca_tickets_open} RCA tickets open` : undefined,
      color: "#C97A0B",
      bg: "rgba(201, 122, 11, 0.06)",
      onClick: () => onJump("drift"),
    },
    {
      key: "propose",
      num: "03",
      title: "Propose",
      blurb: "Typed remediation candidates",
      primary: f ? `${f.propose.opportunities_open} in queue` : "n/a",
      secondary: f ? `${f.propose.opportunities_accepted} accepted` : undefined,
      color: "#7A3CC1",
      bg: "rgba(122, 60, 193, 0.06)",
      onClick: () => onJump("tuning"),
    },
    {
      key: "validate",
      num: "04",
      title: "Validate",
      blurb: "Shadow / A/B / canary, gated",
      primary: f ? `${f.validate.shadow + f.validate.ready} live experiments` : "n/a",
      secondary: f ? `${f.validate.in_ab} opportunities in test` : undefined,
      color: "#0F8FA9",
      bg: "rgba(15, 143, 169, 0.06)",
      onClick: () => onJump("experiments"),
    },
    {
      key: "promote",
      num: "05",
      title: "Promote",
      blurb: "Signed, versioned, reconciled",
      primary: f ? `${f.promote.promoted_30d} promoted · 30d` : "n/a",
      secondary: f ? `${f.promote.rolled_back_30d} rollbacks (${f.promote.auto_rolled_back_30d} auto)` : undefined,
      color: "#1F8A4C",
      bg: "rgba(31, 138, 76, 0.06)",
      onClick: () => onJump("experiments"),
    },
  ];

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">
            Closed-loop discipline
          </div>
          <h2 className="text-sm font-semibold text-zbrain-ink mt-0.5">
            Capture → Detect → Propose → Validate → Promote
          </h2>
        </div>
        <SlaPill sla={sla} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
        {stages.map((s, i) => (
          <button
            key={s.key}
            type="button"
            onClick={s.onClick}
            className="text-left rounded-lg border border-zbrain-divider hover:border-zbrain hover:shadow-sm transition-all p-3 bg-white"
            style={{ borderTop: `3px solid ${s.color}` }}
            title={`Jump to ${s.title} surface`}
          >
            <div className="flex items-baseline justify-between gap-2 mb-1">
              <span className="text-[10px] uppercase tracking-[0.14em] font-bold" style={{ color: s.color }}>
                {s.num}
              </span>
              <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-semibold" style={{ background: s.bg, color: s.color }}>
                {i + 1}
              </span>
            </div>
            <div className="text-[13px] font-semibold text-zbrain-ink">{s.title}</div>
            <div className="text-[11px] text-zbrain-muted mb-2 leading-snug">{s.blurb}</div>
            <div className="text-[12.5px] font-semibold text-zbrain-ink tabular-nums">{s.primary}</div>
            {s.secondary && <div className="text-[10.5px] text-zbrain-muted mt-0.5 tabular-nums">{s.secondary}</div>}
          </button>
        ))}
      </div>
    </div>
  );
}

function SlaPill({ sla }: { sla: SlaData | null }) {
  if (!sla) {
    return <span className="text-[11px] text-zbrain-muted">SLO loading…</span>;
  }
  const tone = sla.met
    ? "bg-emerald-50 border-emerald-200 text-emerald-700"
    : "bg-rose-50 border-rose-200 text-rose-700";
  const target = sla.target_p90_hours;
  const p90 = sla.p90_hours;
  const days = (h: number | null) => h == null ? "n/a" : (h < 36 ? `${Math.round(h)}h` : `${(h / 24).toFixed(1)}d`);
  return (
    <span className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-md border text-[11px] font-semibold ${tone}`}>
      <span className="uppercase tracking-wider text-[9.5px]">Signal → remedy</span>
      <span className="tabular-nums">p90 {days(p90)}</span>
      <span className="opacity-70 tabular-nums">/ target {days(target)}</span>
      <span className="tabular-nums opacity-70">· n={sla.samples}</span>
    </span>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Promote tab — promoted experiments with realised lift, rollback status,
// and the explicit KB-change summary the deck promises.
// ────────────────────────────────────────────────────────────────────────

type PromotedExperiment = {
  id: number;
  candidate: string;
  segment: string;
  change_type: string;
  promote_status: string;
  promoted_by: string | null;
  promoted_at: string | null;
  promote_note: string | null;
  kb_namespace: string | null;
  kb_key: string | null;
  control_prompt: string | null;
  candidate_prompt: string | null;
  previous_body_snapshot: any;
  backtest_results: any;
  accuracy_delta_pct: number | null;
  accuracy_delta_ci: string | null;
  realised_lift_pct: number | null;
  realised_lift_ci: string | null;
  realised_lift_at: string | null;
  realised_sample_size: number | null;
  realised_note: string | null;
  auto_rolled_back: boolean | null;
  rolled_back_at: string | null;
  rolled_back_by: string | null;
  rolled_back_note: string | null;
  linked_opportunity_id: number | null;
  baseline_id?: number | null;
  baseline_label?: string | null;
};

function PromoteTab({
  baselineFilter,
  setBaselineFilter,
  onOpenDrill,
}: {
  baselineFilter: number | null;
  setBaselineFilter: (id: number | null) => void;
  onOpenDrill: (id: number) => void;
}) {
  const [rows, setRows] = useState<PromotedExperiment[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { current: operator } = useOperator();

  const load = async () => {
    try {
      const qs = baselineFilter != null ? `?baseline_id=${baselineFilter}` : "";
      const r = await fetch(`/api/learning/ab_experiments${qs}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const all = await r.json();
      const promoted = (Array.isArray(all) ? all : []).filter((x: any) =>
        x.promote_status === "promoted" || x.promote_status === "retired" || x.auto_rolled_back
      );
      setRows(promoted);
      setErr(null);
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  };

  useEffect(() => {
    let cancel = false;
    const safeLoad = () => { if (!cancel) load(); };
    safeLoad();
    const id = setInterval(safeLoad, 20000);
    return () => { cancel = true; clearInterval(id); };
  }, [baselineFilter]);

  const rollback = async (id: number) => {
    if (!operator) {
      alert("Pick a current operator in the header before rolling back.");
      return;
    }
    if (!operator.is_rule_owner) {
      alert(`${operator.name} is not on the rule-owner allow-list. Switch to a rule owner in the header picker to roll back.`);
      return;
    }
    const note = prompt("Optional note describing why you are rolling back:");
    if (note === null) return;
    try {
      await api.rollbackAbExperiment(id, {
        rolled_back_by: operator.name,
        rolled_back_by_id: operator.id,
        note: note || undefined,
      });
      await load();
    } catch (e: any) {
      alert(`Rollback failed: ${e?.message || e}`);
    }
  };

  return (
    <div className="space-y-3">
      <div className="card p-4 flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-sm font-semibold text-zbrain-ink inline-flex items-center gap-1.5">
          Live changes
          <InfoTip text="Each promotion records the operator, the KB entry moved, before vs after, backtest vs realised delta, and any rollback. Use rollback to restore the prior KB version inside the retention window." />
        </h2>
        <BaselineFilter value={baselineFilter} onChange={setBaselineFilter} />
      </div>

      {err && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{err}</div>}
      {rows === null && <div className="card p-6 text-sm text-zbrain-muted">Loading promotions…</div>}
      {rows && rows.length === 0 && (
        <div className="card p-6 text-sm text-zbrain-muted">No promotions yet. Once a Validate-stage experiment passes its gate it shows up here.</div>
      )}
      {rows && rows.map((e) => (
        <PromoteCard key={e.id} exp={e} onOpenDrill={onOpenDrill} onRollback={() => rollback(e.id)} />
      ))}
    </div>
  );
}

function PromoteCard({
  exp,
  onOpenDrill,
  onRollback,
}: {
  exp: PromotedExperiment;
  onOpenDrill?: (id: number) => void;
  onRollback?: () => void;
}) {
  const isPrompt = exp.change_type === "prompt" || exp.change_type === "prompt_refinement";
  const isThreshold = exp.change_type === "threshold";
  const isPattern = exp.change_type === "pattern_list";
  const promoted_at = exp.promoted_at ? new Date(exp.promoted_at) : null;

  // Look up baseline target_value + direction so the BEFORE / AFTER row
  // can compare the observed realised value against the operator-set target
  // for this baseline. Falls back to a neutral display if the cache is
  // still warming or the baseline is unanchored.
  const lookupBaseline = useBaselineLookup();
  const baseline = lookupBaseline(exp.baseline_id);
  const targetValue =
    baseline && typeof (baseline as any).target_value === "number"
      ? ((baseline as any).target_value as number)
      : null;
  const direction =
    baseline && ((baseline as any).direction === "min" || (baseline as any).direction === "max")
      ? ((baseline as any).direction as "min" | "max")
      : null;

  // Realised value approximation: when the baseline carries a target, we
  // surface "target_value × (1 + realised_lift_pct/100)" as the observed
  // metric value in baseline-native units. realised_lift_pct is computed
  // by the watcher as (candidate_accuracy − control_accuracy) × 100, where
  // accuracy is the share of CSR feedback marked positive after promotion.
  // Higher is always better in the lift convention, so we apply the lift
  // as a multiplicative scale and let the direction-aware comparison
  // against target decide pass/fail downstream.
  const realisedKnown = exp.realised_lift_pct != null;
  const observedValue = (() => {
    if (targetValue == null || exp.realised_lift_pct == null) return null;
    const factor = 1 + exp.realised_lift_pct / 100;
    return targetValue * factor;
  })();

  // Direction-aware target check. Compares observed against target in
  // baseline-native units: a "min" baseline wants observed >= target, a
  // "max" baseline wants observed <= target. When observed cannot be
  // computed (no realised signal or no target), defer to lift sign only.
  // An auto-rolled-back experiment is always classified as below target.
  const targetMet = (() => {
    if (exp.auto_rolled_back) return false;
    if (!realisedKnown) return null;
    if (observedValue != null && targetValue != null) {
      if (direction === "max") return observedValue <= targetValue;
      return observedValue >= targetValue;
    }
    // Fallback when target is missing: positive lift always counts as a
    // hit because the lift convention is "higher accuracy is better".
    return (exp.realised_lift_pct as number) >= 0;
  })();

  const fmtNum = (n: number | null) => {
    if (n == null) return "n/a";
    if (Math.abs(n) >= 100) return n.toFixed(1);
    if (Math.abs(n) >= 1) return n.toFixed(2);
    return n.toFixed(3);
  };

  return (
    <div className="card overflow-hidden">
      {/* Header: BaselineChip prominent + KB entry identity */}
      <div className="px-5 py-4 border-b border-zbrain-divider flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <BaselineChip
              baselineId={exp.baseline_id ?? null}
              baselineLabel={exp.baseline_label ?? null}
              onClick={onOpenDrill}
              size="md"
            />
            <span className={`text-[10px] uppercase tracking-[0.12em] px-2 py-0.5 rounded-full font-bold ${
              exp.auto_rolled_back
                ? "bg-rose-100 text-rose-700 border border-rose-200"
                : exp.promote_status === "promoted"
                ? "bg-emerald-100 text-emerald-700 border border-emerald-200"
                : "bg-slate-100 text-slate-700 border border-slate-200"
            }`}>
              {exp.auto_rolled_back ? "Auto-rolled-back" : exp.promote_status === "promoted" ? "Live" : exp.promote_status}
            </span>
            <span className="text-[10.5px] uppercase tracking-wider text-zbrain-muted font-semibold">{exp.change_type}</span>
          </div>
          <div className="mt-1.5 text-[13px] text-zbrain-ink">
            <span className="font-mono font-semibold">{exp.kb_namespace || "n/a"}</span>
            {exp.kb_key && (
              <>
                <span className="text-zbrain-muted mx-1">:</span>
                <span className="font-mono font-semibold">{exp.kb_key}</span>
              </>
            )}
          </div>
          <h3 className="text-[13px] text-zbrain-ink/85 mt-1 leading-snug inline-flex items-center gap-1.5">
            {exp.candidate}
            <InfoTip
              text={[
                `Segment: ${exp.segment}`,
                exp.promote_note ? `Operator note: ${exp.promote_note}` : null,
                exp.realised_note ? `Realised: ${exp.realised_note}` : null,
                exp.rolled_back_note ? `Rollback note: ${exp.rolled_back_note}` : null,
              ].filter(Boolean).join("\n\n")}
            />
          </h3>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10.5px] uppercase tracking-wider text-zbrain-muted font-semibold">Promoted</div>
          <div className="text-[12.5px] font-semibold text-zbrain-ink">{promoted_at ? promoted_at.toLocaleString() : "n/a"}</div>
          <div className="text-[11px] text-zbrain-muted mt-0.5">
            by <span className="font-semibold text-zbrain-ink">{exp.promoted_by || "n/a"}</span>
          </div>
        </div>
      </div>

      {/* Body: BEFORE → AFTER with baseline target vs observed */}
      <div className="px-5 py-4 bg-zbrain-surface/30 border-b border-zbrain-divider">
        <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold mb-2">
          Verification
        </div>
        {exp.baseline_id == null && (
          <div className="mb-2 rounded-md border border-zbrain-divider bg-white px-3 py-1.5 text-[11px] text-zbrain-muted italic">
            Target unavailable: experiment is not anchored to a baseline.
          </div>
        )}
        {exp.baseline_id != null && targetValue == null && (
          <div className="mb-2 rounded-md border border-zbrain-divider bg-white px-3 py-1.5 text-[11px] text-zbrain-muted italic">
            Target unavailable: anchored baseline has no recorded target_value.
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="rounded-md border border-zbrain-divider bg-white px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Before promotion</div>
            <div className="mt-1 flex items-baseline gap-2">
              <div className="text-[10.5px] text-zbrain-muted w-24 shrink-0">Target (goal):</div>
              <div className="text-[13px] font-semibold tabular-nums">
                {targetValue != null
                  ? `${direction === "max" ? "≤" : "≥"} ${fmtNum(targetValue)}`
                  : "n/a"}
              </div>
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <div className="text-[10.5px] text-zbrain-muted w-24 shrink-0">Backtest delta:</div>
              <div className="text-[13px] font-semibold tabular-nums">
                {exp.accuracy_delta_pct != null
                  ? `${exp.accuracy_delta_pct >= 0 ? "+" : ""}${exp.accuracy_delta_pct.toFixed(1)}pp`
                  : "n/a"}
              </div>
            </div>
          </div>
          <div className="rounded-md border border-zbrain-divider bg-white px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">After promotion</div>
            <div className="mt-1 flex items-baseline gap-2">
              <div className="text-[10.5px] text-zbrain-muted w-24 shrink-0">Target (bar):</div>
              <div className="text-[13px] font-semibold tabular-nums">
                {targetValue != null
                  ? `${direction === "max" ? "≤" : "≥"} ${fmtNum(targetValue)}`
                  : "n/a"}
              </div>
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <div className="text-[10.5px] text-zbrain-muted w-24 shrink-0">Observed:</div>
              <div className="text-[13px] font-semibold tabular-nums">
                {observedValue != null
                  ? fmtNum(observedValue)
                  : realisedKnown
                    ? `${(exp.realised_lift_pct as number) >= 0 ? "+" : ""}${(exp.realised_lift_pct as number).toFixed(1)}% lift`
                    : "Watching…"}
              </div>
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <div className="text-[10.5px] text-zbrain-muted w-24 shrink-0">Realised lift:</div>
              <div className="text-[13px] font-semibold tabular-nums">
                {realisedKnown
                  ? `${(exp.realised_lift_pct as number) >= 0 ? "+" : ""}${(exp.realised_lift_pct as number).toFixed(1)}%`
                  : exp.realised_lift_at
                    ? `measured ${new Date(exp.realised_lift_at).toLocaleString()}`
                    : "Reconciles 1h after promotion"}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
          {/* Badge precedence: auto-rolled-back > realised-signal trinary.
              When the watchdog has already rolled the change back, the rose
              "below target" badge must show regardless of whether a fresh
              realised-lift sample has landed. */}
          {exp.auto_rolled_back && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11px] font-semibold bg-rose-50 text-rose-800 border border-rose-200">
              Below target: auto-rolled-back
            </span>
          )}
          {!exp.auto_rolled_back && !realisedKnown && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-50 text-slate-700 border border-slate-200">
              Watching for realised signal
            </span>
          )}
          {!exp.auto_rolled_back && realisedKnown && targetMet === true && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
              Target met
            </span>
          )}
          {!exp.auto_rolled_back && realisedKnown && targetMet === false && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11px] font-semibold bg-rose-50 text-rose-800 border border-rose-200">
              Below target: rollback recommended
            </span>
          )}

          {/* Rollback control: wired to /learning/ab_experiments/{id}/rollback
              via api.rollbackAbExperiment. Visible whenever the experiment
              is currently live (promoted, not yet rolled back). */}
          {!exp.auto_rolled_back && !exp.rolled_back_at && exp.promote_status === "promoted" && onRollback && (
            <button
              type="button"
              onClick={onRollback}
              className="px-3 py-1.5 text-[11px] font-semibold rounded-md bg-rose-50 text-rose-800 border border-rose-200 hover:bg-rose-100 whitespace-nowrap"
              title="Restore the prior KB version inside the rollback window."
            >
              Roll back
            </button>
          )}
        </div>
      </div>

      {/* Diff bodies for prompt / threshold change types, gated by InfoTip
          so the verification panel stays the primary surface. */}
      {(isPrompt && (exp.control_prompt || exp.candidate_prompt)) || (isThreshold && exp.previous_body_snapshot) || isPattern ? (
        <details className="border-b border-zbrain-divider">
          <summary className="px-5 py-2.5 text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold cursor-pointer hover:text-zbrain-ink select-none">
            Knowledge-base diff
          </summary>
          <div className="px-5 pb-4">
            {isPrompt && (exp.control_prompt || exp.candidate_prompt) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <DiffBox label="Before (live prompt)" body={exp.control_prompt || ""} tone="muted" />
                <DiffBox label="After (promoted prompt)" body={exp.candidate_prompt || ""} tone="active" />
              </div>
            )}

            {isThreshold && exp.previous_body_snapshot && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <DiffBox
                  label="Before"
                  body={renderObjectShort(exp.previous_body_snapshot)}
                  tone="muted"
                  mono
                />
                <DiffBox
                  label="After"
                  body={renderObjectShort(extractProposedFromCandidate(exp))}
                  tone="active"
                  mono
                />
              </div>
            )}

            {isPattern && (
              <div className="text-[12px] text-zbrain-muted">
                Pattern-list change. See linked RCA bundle for the full diff.
              </div>
            )}
          </div>
        </details>
      ) : null}

      {/* Footer: RCA bundle link + jump to experiment record */}
      <div className="px-5 py-3 bg-white flex items-center justify-between gap-3">
        <div className="text-[11px] text-zbrain-muted">
          {exp.linked_opportunity_id != null
            ? <>Linked opportunity #{exp.linked_opportunity_id}{" "}·{" "}<RcaLinkFromOpportunity oppId={exp.linked_opportunity_id} /></>
            : "No linked opportunity"}
        </div>
        <Link
          to={`/learning?tab=experiments&highlight=${exp.id}`}
          className="text-[11px] font-semibold text-zbrain hover:underline"
        >
          Open in A/B experiments →
        </Link>
      </div>
    </div>
  );
}

function DiffBox({ label, body, tone, mono }: { label: string; body: string; tone: "muted" | "active"; mono?: boolean }) {
  return (
    <div className="rounded-md border border-zbrain-divider bg-white overflow-hidden">
      <div className={`px-3 py-1.5 text-[10px] uppercase tracking-wider font-bold ${tone === "active" ? "bg-emerald-50 text-emerald-800 border-b border-emerald-200" : "bg-zbrain-surface text-zbrain-muted border-b border-zbrain-divider"}`}>
        {label}
      </div>
      <pre className={`text-[11.5px] text-zbrain-ink whitespace-pre-wrap px-3 py-2 max-h-40 overflow-auto ${mono ? "font-mono" : ""}`}>{body || "n/a"}</pre>
    </div>
  );
}

function StatTile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone: "emerald" | "amber" | "rose" | "zbrain" | "slate" }) {
  const styles: Record<string, string> = {
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-800",
    amber:   "bg-amber-50 border-amber-200 text-amber-900",
    rose:    "bg-rose-50 border-rose-200 text-rose-800",
    zbrain:  "bg-zbrain-50 border-zbrain text-zbrain",
    slate:   "bg-slate-50 border-slate-200 text-slate-700",
  };
  return (
    <div className={`rounded-md border px-3 py-2.5 ${styles[tone]}`}>
      <div className="text-[10px] uppercase tracking-[0.12em] font-bold opacity-80">{label}</div>
      <div className="text-[18px] font-bold tabular-nums leading-tight mt-1">{value}</div>
      {sub && <div className="text-[10.5px] mt-1 leading-snug opacity-80">{sub}</div>}
    </div>
  );
}

function renderObjectShort(obj: any): string {
  if (!obj || typeof obj !== "object") return String(obj ?? "n/a");
  return Object.entries(obj).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n");
}

function extractProposedFromCandidate(exp: PromotedExperiment): any {
  // The promoted "after" for a threshold change can be derived from the linked
  // opportunity's proposed_remedy. For demo cards we just label it succinctly.
  if (exp.change_type === "threshold") return { l4_floor: "see linked opportunity" };
  return {};
}

function RcaLinkFromOpportunity({ oppId }: { oppId: number }) {
  const [rcaId, setRcaId] = useState<number | null>(null);
  useEffect(() => {
    let cancel = false;
    fetch(`/api/learning/opportunities/${oppId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((o) => { if (!cancel && o?.linked_rca_ticket_id) setRcaId(o.linked_rca_ticket_id); })
      .catch(() => undefined);
    return () => { cancel = true; };
  }, [oppId]);
  if (!rcaId) return <span className="text-zbrain-muted">no RCA link</span>;
  return (
    <Link to={`/learning?tab=drift&rca=${rcaId}`} className="text-zbrain font-semibold hover:underline">
      View signal bundle (RCA #{rcaId}) →
    </Link>
  );
}

// ────────────────────────────────────────────────────────────────────────
// Health by baseline. Compact roster on the Overview tab. One row per
// baseline with status pill and (lazily) the signal counts pulled from
// the timeline endpoint when the row enters the viewport. Clicking a row
// opens the drill-through panel.
// ────────────────────────────────────────────────────────────────────────
function HealthByBaseline({ onOpenDrill }: { onOpenDrill: (id: number) => void }) {
  const [items, setItems] = useState<BaselineAnchor[] | null>(null);
  useEffect(() => {
    let cancel = false;
    api
      .learningBaselines()
      .then((d) => {
        if (!cancel) setItems(Array.isArray(d?.items) ? d.items : []);
      })
      .catch(() => {
        if (!cancel) setItems([]);
      });
    return () => {
      cancel = true;
    };
  }, []);

  if (items === null) {
    return (
      <div className="card p-4 text-sm text-zbrain-muted">Loading baseline roster…</div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="card p-4 text-sm text-zbrain-muted">
        No baselines configured yet. Add one from the Baselines tab to start scoring health here.
      </div>
    );
  }

  // Sort: breached → drifting → unknown → healthy. Status determines what
  // an operator actually needs to look at first.
  const order: BaselineAnchor["last_status"][] = ["breached", "drifting", "unknown", "healthy"];
  const sorted = [...items].sort(
    (a, b) => order.indexOf(a.last_status) - order.indexOf(b.last_status),
  );

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
            Health by baseline
            <InfoTip text="Per-baseline status and signal volume. Click any row for the full timeline of drift alerts, candidates, experiments, and feedback anchored to that baseline." />
          </h2>
          <p className="text-xs text-zbrain-muted mt-0.5">
            Sorted by severity. Counts populate on demand from the timeline endpoint.
          </p>
        </div>
        <span className="text-[11px] text-zbrain-muted">{items.length} total</span>
      </div>
      <div className="divide-y divide-zbrain-divider/60">
        {sorted.map((b) => (
          <HealthByBaselineRow key={b.id} b={b} onOpenDrill={onOpenDrill} />
        ))}
      </div>
    </div>
  );
}

function HealthByBaselineRow({
  b,
  onOpenDrill,
}: {
  b: BaselineAnchor;
  onOpenDrill: (id: number) => void;
}) {
  const [counts, setCounts] = useState<{
    drift: number;
    opp: number;
    exp: number;
    fb: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchCounts = () => {
    if (counts || loading) return;
    setLoading(true);
    api
      .learningBaselineTimeline(b.id)
      .then((t) => {
        setCounts({
          drift: t.counts.drift_alerts,
          opp: t.counts.opportunities,
          exp: t.counts.experiments,
          fb: t.counts.feedback,
        });
      })
      .catch(() => setCounts({ drift: 0, opp: 0, exp: 0, fb: 0 }))
      .finally(() => setLoading(false));
  };

  const statusTone =
    b.last_status === "breached"
      ? "bg-rose-50 text-rose-800 border-rose-200"
      : b.last_status === "drifting"
        ? "bg-amber-50 text-amber-800 border-amber-200"
        : b.last_status === "healthy"
          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : "bg-slate-50 text-slate-600 border-slate-200";

  return (
    <button
      type="button"
      onClick={() => onOpenDrill(b.id)}
      onMouseEnter={fetchCounts}
      onFocus={fetchCounts}
      className="w-full text-left px-4 py-2.5 hover:bg-zbrain-50/40 transition-colors flex items-center gap-3"
    >
      <span
        className={`pill text-[10px] border ${statusTone} uppercase tracking-wider font-semibold shrink-0`}
      >
        {b.last_status}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-zbrain-ink truncate">
          {b.label || `Baseline #${b.id}`}
        </div>
      </div>
      <div className="flex items-center gap-1.5 text-[10.5px] text-zbrain-muted shrink-0">
        {counts ? (
          <>
            <span className="pill bg-white border border-zbrain-divider px-1.5 py-0.5 tabular-nums">
              drift {counts.drift}
            </span>
            <span className="pill bg-white border border-zbrain-divider px-1.5 py-0.5 tabular-nums">
              tune {counts.opp}
            </span>
            <span className="pill bg-white border border-zbrain-divider px-1.5 py-0.5 tabular-nums">
              A/B {counts.exp}
            </span>
            <span className="pill bg-white border border-zbrain-divider px-1.5 py-0.5 tabular-nums">
              fb {counts.fb}
            </span>
          </>
        ) : (
          <span className="italic">{loading ? "loading…" : "hover for counts"}</span>
        )}
      </div>
    </button>
  );
}

// ─── Discover · quality gates (signal-graph discovery) ───────────────────
// Drives the shared /api/signal-graph backend: fetch a client solution, let
// the LLM extract signals + propose candidate gates, set a user target to
// accept, then Analyze to compute edge weights + drift (data-conditional).

const SG_DEFAULT_TENANT = "676e7711192abc0024679612";
const SG_DEFAULT_SESSION = "f8651fcd-6c46-4ed2-83ec-665f31027267";

function sgRangeHint(r: SgSuggestedRange): string {
  if (r.status === "ok") {
    return `observed ${r.p10.toFixed(3)}–${r.p90.toFixed(3)} (median ${r.median.toFixed(3)}, ${r.n} windows)`;
  }
  return "not enough data yet";
}

function DiscoverTab() {
  const [tenantId, setTenantId] = useState(SG_DEFAULT_TENANT);
  const [sessionId, setSessionId] = useState(SG_DEFAULT_SESSION);
  const [recs, setRecs] = useState<SgRecommendation[]>([]);
  const [targets, setTargets] = useState<Record<number, string>>({});
  const [openGraphs, setOpenGraphs] = useState<Record<number, boolean>>({});
  const [gates, setGates] = useState<SgGate[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const loadRecs = async (sid: string) => {
    try {
      setRecs(await signalGraphApi.recommendations(sid));
    } catch (e) {
      setErrMsg(String(e));
    }
  };
  const loadGates = async (sid: string) => {
    try {
      setGates(await signalGraphApi.baselines(sid));
    } catch (e) {
      setErrMsg(String(e));
    }
  };

  useEffect(() => {
    loadRecs(sessionId);
    loadGates(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onDiscover = async () => {
    setDiscovering(true);
    setErrMsg(null);
    setStatusMsg(null);
    try {
      const res = await signalGraphApi.discover(tenantId, sessionId);
      setStatusMsg(`Discovered ${res.signals} signals and ${res.gates} candidate gates.`);
      await loadRecs(sessionId);
    } catch (e) {
      setErrMsg(String(e));
    } finally {
      setDiscovering(false);
    }
  };

  const onAccept = async (rec: SgRecommendation) => {
    const raw = targets[rec.id];
    const num = Number(raw);
    if (raw === undefined || raw.trim() === "" || Number.isNaN(num)) {
      setErrMsg(`Enter a numeric target for "${rec.metric}" before accepting.`);
      return;
    }
    setErrMsg(null);
    try {
      await signalGraphApi.accept(rec.id, num);
      setStatusMsg(`Accepted "${rec.metric}" with target ${num}.`);
      await loadRecs(sessionId);
      await loadGates(sessionId);
    } catch (e) {
      setErrMsg(String(e));
    }
  };

  const onDismiss = async (rec: SgRecommendation) => {
    setErrMsg(null);
    try {
      await signalGraphApi.dismiss(rec.id);
      await loadRecs(sessionId);
    } catch (e) {
      setErrMsg(String(e));
    }
  };

  const onAnalyze = async () => {
    setAnalyzing(true);
    setErrMsg(null);
    try {
      const res = await signalGraphApi.analyze(sessionId);
      setStatusMsg(`Analyzed: ${res.edges_updated} edge weights updated, ${res.gates_analyzed} gates checked.`);
      await loadGates(sessionId);
    } catch (e) {
      setErrMsg(String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const inp =
    "w-full px-3 py-2 rounded-md border border-zbrain-divider bg-white text-sm";

  return (
    <div className="space-y-4">
      {errMsg && (
        <Surface>
          <div className="p-4 text-sm text-rose-700">{errMsg}</div>
        </Surface>
      )}
      {statusMsg && (
        <Surface>
          <div className="p-4 text-sm text-emerald-700">{statusMsg}</div>
        </Surface>
      )}

      <Surface>
        <Section title="Discover" subtitle="Identify the client solution to analyze.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="eyebrow">Tenant ID</div>
              <input className={inp} value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
            </div>
            <div>
              <div className="eyebrow">Session ID</div>
              <input className={inp} value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3">
            <Button onClick={onDiscover} variant="primary" disabled={discovering}>
              {discovering ? "Discovering…" : "Discover"}
            </Button>
            <Button onClick={() => loadRecs(sessionId)} variant="ghost">Refresh</Button>
          </div>
        </Section>
      </Surface>

      <Surface>
        <Section
          title={`Candidate gates (${recs.length})`}
          subtitle="Set a target value to accept a gate, or dismiss it."
        >
          {recs.length === 0 && (
            <div className="py-6 text-center text-zbrain-muted">No open candidates. Click "Discover" above.</div>
          )}
          <div className="space-y-3">
            {recs.map((rec) => (
              <div key={rec.id} className="rounded-lg border border-zbrain-divider/60 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-mono text-sm font-medium text-zbrain-ink">{rec.metric}</div>
                    <div className="text-[13px] text-zbrain-muted mt-1">{rec.rationale}</div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Chip tone="info">{rec.direction === "min" ? "higher is better" : "lower is better"}</Chip>
                    {rec.compute && <Chip tone="neutral">{rec.compute}</Chip>}
                  </div>
                </div>

                {rec.inputs.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 mt-3">
                    <span className="text-[12px] text-zbrain-muted">signals:</span>
                    {rec.inputs.map((sig) => (
                      <Chip key={sig} tone="violet">{sig}</Chip>
                    ))}
                  </div>
                )}

                <div className="text-[12px] text-zbrain-muted mt-3">
                  suggested range: {sgRangeHint(rec.suggested_range)}
                </div>

                <div className="flex items-center gap-2 mt-2">
                  <input
                    className={inp + " max-w-[180px]"}
                    type="number"
                    placeholder="target value"
                    value={targets[rec.id] ?? ""}
                    onChange={(e) => setTargets((t) => ({ ...t, [rec.id]: e.target.value }))}
                  />
                  <Button onClick={() => onAccept(rec)} variant="primary">Accept</Button>
                  <Button onClick={() => onDismiss(rec)} variant="ghost">Dismiss</Button>
                  <Button
                    onClick={() => setOpenGraphs((g) => ({ ...g, [rec.id]: !g[rec.id] }))}
                    variant="ghost"
                  >
                    {openGraphs[rec.id] ? "Hide graph" : "Graph"}
                  </Button>
                </div>

                {openGraphs[rec.id] && (
                  <div className="mt-3">
                    <SignalGraphViewer recId={rec.id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      </Surface>

      <Surface>
        <Section
          title={`Baseline targets (${gates.length})`}
          subtitle="Gates you accepted, with live drift vs the target you set."
          action={
            <Button onClick={onAnalyze} variant="primary" disabled={analyzing}>
              {analyzing ? "Analyzing…" : "Analyze (weights & drift)"}
            </Button>
          }
        >
          {gates.length === 0 && (
            <div className="py-6 text-center text-zbrain-muted">
              No accepted gates yet. Set a target on a candidate above.
            </div>
          )}
          <div className="space-y-2">
            {gates.map((g) => (
              <div
                key={`${g.metric}:${g.segment}`}
                className="rounded-lg border border-zbrain-divider/60 p-3 flex items-center justify-between gap-4"
              >
                <div className="min-w-0">
                  <div className="font-mono text-sm font-medium text-zbrain-ink">{g.metric}</div>
                  <div className="text-[12px] text-zbrain-muted mt-0.5">
                    target {g.target_value ?? "—"}
                    {g.status === "ok" && (
                      <>
                        {" · "}current {g.current?.toFixed(3)}
                        {g.delta_pct != null && <> ({(g.delta_pct * 100).toFixed(1)}%)</>}
                        {g.psi != null && <> · PSI {g.psi.toFixed(2)}</>}
                      </>
                    )}
                  </div>
                </div>
                <div className="shrink-0">
                  {g.status !== "ok" ? (
                    <Chip tone="neutral">not enough data</Chip>
                  ) : g.severity === "high" ? (
                    <Chip tone="danger">breached</Chip>
                  ) : g.severity === "medium" ? (
                    <Chip tone="warning">drifting</Chip>
                  ) : (
                    <Chip tone="success">healthy</Chip>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      </Surface>
    </div>
  );
}
