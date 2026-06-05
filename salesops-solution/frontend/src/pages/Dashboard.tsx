// === v1.1 DASHBOARD START === Operations Dashboard re-skinned from the Console HTML reference design.
// Real data only: backend /api/analytics/summary + /api/analytics/agent_fabric. No invented numbers,
// no compare-to-prior-period deltas, no cost dashboard, no fake recommendations.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
} from "chart.js";
import { Doughnut } from "react-chartjs-2";

import { aioaApi, api, type AgentFabricStats, type AnalyticsSummary, type EmailSummary } from "../api";
import { useReadiness } from "../hooks/useReadiness";

ChartJS.register(ArcElement, Tooltip, Legend, CategoryScale, LinearScale, BarElement, Title);

// Canonical stage names — must match analytics.subprocess_taxonomy.STAGE_META
// and each agent class's stage_label so the funnel, the trace UI, the
// governance dashboard, and the analytics tabs all show the same agent name.
const STAGE_DEFS: { id: number; key: string; name: string; tagline: string }[] = [
  { id: 1, key: "intake",      name: "Intake & Classification",        tagline: "Read inbound mail, detect language, classify intent." },
  { id: 2, key: "extract",     name: "Extraction & Enrichment",        tagline: "OCR, schema-driven extraction, entity resolution in Salesforce." },
  { id: 3, key: "decide",      name: "Decision & Confidence Scoring",  tagline: "Four-gate confidence model, tiered autonomy, routing." },
  { id: 4, key: "execute",     name: "Workflow Execution",             tagline: "Salesforce CCC / Case writes today. Oracle EBS via Jitterbit is upcoming once the middleware is enabled." },
  { id: 5, key: "communicate", name: "Communication & Close-out",      tagline: "Reply drafted in customer's language, SOA filed in SharePoint." },
  { id: 6, key: "learning",    name: "Continuous Learning",            tagline: "CSR corrections, drift detection, KB updates." },
];

const INTENT_LABEL: Record<string, string> = {
  po_intake: "PO intake",
  quote_to_order: "Quote-to-Order",
  trade_change_order: "Trade Change Order",
  ssd_change_request: "SSD Change",
  hold_release: "Hold release",
  delivery_change: "Delivery change",
  service_order: "Service Order (WO)",
  wo_update_request: "WO update",
  wo_status_inquiry: "WO status / inquiry",
  service_contract_request: "Service Contract",
  general_inquiry: "Others (general)",
  out_of_scope: "Out of scope",
  spam: "Spam",
  kso: "KSO (restricted)",
  collections: "Collections",
  portal_admin: "Portal admin",
  brazil_tax: "Brazil tax",
  undeliverable: "Undeliverable",
};

// Design palette aligned to the Console HTML reference.
const PAL = {
  bluePrimary: "#1F4ED8",
  blueAccent: "#2050E0",
  blueBright: "#3070F0",
  blueSoft: "#8090F0",
  blueCard: "#E0E8F0",
  blueTint: "#F2F5FB",
  auto: "#1F8A4C",
  autoSoft: "#E1F4E8",
  hitl: "#C97A0B",
  hitlSoft: "#FBEFD8",
  risk: "#C53030",
  text: "#2A2A2A",
  textMute: "#777777",
  line: "#D8DCE2",
};

const INTENT_COLORS = [
  PAL.bluePrimary, "#1F8A4C", "#3070F0", "#C97A0B", "#7B8AA8",
  "#9CB28C", "#5C8AF7", "#C53030", "#8FA2C9", "#1F4ED8",
  "#2DAA61", "#3F84F2", "#A85B0A", "#6E81A8", "#88AA88",
  "#B0BEDB",
];

function relTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

function num(n: number | null | undefined): string {
  if (n == null) return "-";
  return n.toLocaleString("en-US");
}

export function DashboardPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [fabric, setFabric] = useState<AgentFabricStats | null>(null);
  const [recent, setRecent] = useState<EmailSummary[]>([]);
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [sfStatus, setSfStatus] = useState<{ connected?: boolean; org_name?: string } | null>(null);
  const [spStatus, setSpStatus] = useState<{ connected?: boolean; site_display_name?: string } | null>(null);
  const [mailboxes, setMailboxes] = useState<{ total: number; active: number; providers: string[]; lastSyncedAt: string | null; anyError: boolean } | null>(null);
  const [queue, setQueue] = useState<import("../api").QueueStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    const refresh = async () => {
      // Per-call resilience: a transient blip on one endpoint (typical when
      // the backend is briefly busy committing a fresh pipeline) must not
      // blank the entire dashboard. Use Promise.allSettled and only error
      // when EVERY core call fails for several ticks. This kills the
      // "shows error on first tick, works after refresh" race.
      const results = await Promise.allSettled([
        api.analytics(),
        api.analytics.agentFabric(),
        api.listEmails({}),
        api.emailCounts(),
        api.queueStatus(),
      ]);
      if (cancel) return;
      const [sR, fR, eR, cR, qR] = results;
      if (sR.status === "fulfilled") setSummary(sR.value);
      if (fR.status === "fulfilled") setFabric(fR.value);
      if (eR.status === "fulfilled") setRecent(eR.value.slice(0, 10));
      if (cR.status === "fulfilled") setCounts(cR.value);
      if (qR.status === "fulfilled") setQueue(qR.value);
      const fatals = [sR, fR, eR, cR].filter((r) => r.status === "rejected");
      if (fatals.length === 4) {
        // Only surface an error when EVERY core endpoint is down. A single
        // 5xx during the pipeline-commit window will not flash a red banner.
        const first = fatals[0];
        const msg = first.status === "rejected" ? String(first.reason?.message || first.reason || "Failed to load dashboard") : "Failed to load dashboard";
        setErr(msg);
      } else {
        setErr(null);
      }
      try {
        const r = await fetch("/api/integrations/salesforce/status", {
          credentials: "include",
        });
        if (r.ok) {
          const j = await r.json();
          if (!cancel) setSfStatus(j);
        }
      } catch {}
      try {
        const r = await fetch("/api/integrations/sharepoint/status", {
          credentials: "include",
        });
        if (r.ok) {
          const j = await r.json();
          if (!cancel) setSpStatus(j);
        }
      } catch {}
      try {
        const accounts = await api.emailAccounts.list();
        if (cancel) return;
        const active = accounts.filter((a) => a.is_active);
        const providers = Array.from(new Set(accounts.map((a) => a.provider))).sort();
        const lastSync = accounts
          .map((a) => a.last_synced_at)
          .filter((v): v is string => !!v)
          .sort()
          .reverse()[0] || null;
        const anyError = accounts.some((a) => !!a.last_error);
        setMailboxes({ total: accounts.length, active: active.length, providers, lastSyncedAt: lastSync, anyError });
      } catch {}
    };
    refresh();
    const id = setInterval(refresh, 10000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);

  // Funnel data: real per-stage tier split from the backend. Each stage
  // shows how the pipelines that actually touched THAT stage broke down
  // into auto (L4 + L3) vs HITL (L2). Different stages have different
  // mixes; the dashboard reflects that honestly.
  const funnel = useMemo(() => {
    if (!fabric || !summary) return [];
    return STAGE_DEFS.map((s) => {
      const st = fabric.stage_timing[s.key];
      const vol = st?.pipeline_count ?? st?.count ?? 0;
      const p95 = st?.p95_ms ?? 0;
      const autoPct = st?.auto_pct ?? 0;
      const hitlPct = st?.hitl_pct ?? 0;
      return {
        ...s,
        volume: vol,
        autoPct,
        hitlPct,
        autoCount: st?.auto_count ?? 0,
        hitlCount: st?.hitl_count ?? 0,
        p95,
      };
    });
  }, [fabric, summary]);

  const topIntents = useMemo(() => {
    if (!summary?.by_intent) return [];
    return Object.entries(summary.by_intent)
      .filter(([, n]) => (n as number) > 0)
      .sort((a, b) => (b[1] as number) - (a[1] as number));
  }, [summary]);

  const automationPct = summary ? Math.round((summary.autonomy.automation_rate || 0) * 100) : 0;
  const avgMs = summary?.quality.avg_processing_ms || 0;

  // ===== Derived signals for the new layout =====
  const erroredCount = summary?.totals.errored ?? 0;
  const runningCount = summary?.totals.running ?? 0;
  const completedCount = summary?.totals.completed ?? 0;
  const totalCases = summary?.totals.pipelines ?? 0;
  const inboxNew = counts?.new ?? summary?.totals.inbox_unprocessed ?? 0;
  // Total ingested excludes stale (expired_unworkable) mail. Those rows
  // still exist in the DB for audit but are not surfaced on operator-facing
  // tiles. Counting them here would inflate the number divorced from the
  // actionable queue.
  const inboxTotal = summary?.totals.inbox_total ?? 0;

  return (
    <div className="space-y-4">
      {/* ===== Header — title + system pulse ===== */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-zbrain-ink dark:text-zbrain-dark-ink">
            Case Operations
          </h1>
          <StatusPulse />
        </div>
      </header>

      {err && (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {err}
        </div>
      )}

      {/* Remove the old big readiness + verification tiles; SystemHealthStrip + StatusPulse cover both now. */}

      {/* ===== Slim errors banner — only when there's something to retry ===== */}
      {erroredCount > 0 && (
        <button
          onClick={() => navigate("/errors")}
          className="w-full rounded-md border border-rose-200 bg-rose-50 px-4 py-2.5 flex items-center justify-between hover:bg-rose-100/60 transition-colors"
        >
          <div className="flex items-center gap-3">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-rose-100">
              <IconAlert className="h-4 w-4 text-rose-700" />
            </span>
            <div className="text-left">
              <div className="text-sm font-semibold text-rose-900">
                {erroredCount.toLocaleString()} case{erroredCount === 1 ? "" : "s"} halted on retryable system errors
              </div>
              <div className="text-xs text-rose-700/80">
                Most were stranded by prior restarts. Open the case queue to bulk-retry.
              </div>
            </div>
          </div>
          <span className="text-sm font-semibold text-rose-700">Open queue →</span>
        </button>
      )}

      {/* ===== Hero metrics — what a CSR/admin reads first ===== */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <HeroMetric
          icon={<IconCases />}
          accent="#1F4ED8"
          label="Cases handled"
          value={num(completedCount)}
          unit="closed end-to-end"
          sub={`${num(totalCases)} cases processed across all stages`}
          onClick={() => navigate("/trace")}
        />
        <HeroMetric
          icon={<IconAutomation />}
          accent="#1F8A4C"
          label="Automation rate"
          value={`${automationPct}%`}
          unit="closed without a human"
          sub={`L4 auto ${num(summary?.autonomy.L4_AUTO)} · L3 one-click ${num(summary?.autonomy.L3_ONE_CLICK)} · L2 review ${num(summary?.autonomy.L2_HITL)} (of ${num(summary?.autonomy.tiered_total)} tiered)`}
          tooltip={
            summary
              ? `Denominator is pipelines that reached Decide and were assigned an autonomy tier (${num(summary.autonomy.tiered_total)} of ${num(totalCases)}). The remaining ${num(Math.max(0, totalCases - (summary.autonomy.tiered_total ?? 0)))} either short-circuited before intake (spam, KSO routing, Brazil tax, collections, undeliverable, portal admin) or errored before Decide, and were never eligible for L4 automation.`
              : "Denominator is pipelines that reached Decide and were assigned an autonomy tier. Pre-intake-terminated and pre-Decide errored cases are excluded because they were never eligible for L4 automation."
          }
          onClick={() => navigate("/analytics")}
        />
        <HeroMetric
          icon={<IconTime />}
          accent="#C97A0B"
          label="Avg time to close"
          value={avgMs ? fmtMs(avgMs) : "-"}
          unit="per case"
          sub={
            summary?.throughput
              ? `P50 ${fmtMs(summary.throughput.p50_ms || 0)} · P95 ${fmtMs(summary.throughput.p95_ms || 0)}`
              : "median + tail latency"
          }
          onClick={() => navigate("/analytics")}
        />
      </div>

      {/* ===== Inbox + Order Acceptance + Throughput strip ===== */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <Card title="Inbox" linkLabel="Open inbox →" linkTo="/inbox">
          <div className="px-5 py-4 grid grid-cols-3 gap-3">
            <Stat label="New" value={num(inboxNew)} />
            {/* "Running" tracks pipelines whose status is literally `running`. The
                broader cohort awaiting human or external action (awaiting_hitl,
                awaiting_aioa) is exposed on the HITL and Order Acceptance cards
                respectively; conflating them here masked where work was actually
                stuck. */}
            <Stat label="Running" value={num(runningCount)} />
            <Stat label="Total ingested" value={num(inboxTotal)} />
          </div>
        </Card>
        <OrderAcceptanceCard summary={summary} onOpen={() => navigate("/aioa")} />
        <div className="lg:col-span-2">
          <ThroughputCard summary={summary} queue={queue} onAnalytics={() => navigate("/analytics")} />
        </div>
      </div>

      {/* ===== Case funnel — six stages with per-stage automation ===== */}
      <Card
        title="Case funnel"
        meta="Six stages each case flows through. Bars show how much of the volume cleared each stage with no human."
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 px-4 pb-4">
          {funnel.length === 0
            ? STAGE_DEFS.map((s) => <FunnelSkeleton key={s.id} />)
            : funnel.map((s, i) => (
                <FunnelStage
                  key={s.id}
                  stage={s}
                  isLast={i === funnel.length - 1}
                  onClick={() => navigate(`/trace?stage=${s.key}`)}
                />
              ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* ===== Intent doughnut ===== */}
        <div className="lg:col-span-1">
          <Card title="Intent mix" meta={`${num(summary?.totals.pipelines)} cases classified`}>
            {topIntents.length === 0 ? (
              <Empty text="No cases yet." />
            ) : (
              <div className="px-4 pb-4">
                <div className="relative" style={{ height: 240 }}>
                  <Doughnut
                    data={{
                      labels: topIntents.map(([k]) => INTENT_LABEL[k] || k),
                      datasets: [
                        {
                          data: topIntents.map(([, v]) => v as number),
                          backgroundColor: topIntents.map((_, i) => INTENT_COLORS[i % INTENT_COLORS.length]),
                          borderWidth: 0,
                        },
                      ],
                    }}
                    options={{
                      responsive: true,
                      maintainAspectRatio: false,
                      cutout: "60%",
                      onClick: (_, elements) => {
                        if (elements.length > 0) {
                          const idx = elements[0].index;
                          const intentKey = topIntents[idx]?.[0];
                          if (intentKey) navigate(`/inbox?intent=${encodeURIComponent(intentKey)}`);
                        }
                      },
                      plugins: {
                        legend: {
                          position: "bottom",
                          labels: {
                            boxWidth: 10,
                            font: { size: 11, family: "Inter, system-ui, sans-serif" },
                            color: PAL.textMute,
                            padding: 8,
                          },
                        },
                        tooltip: { enabled: true },
                      },
                    }}
                  />
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                  {topIntents.slice(0, 8).map(([k, v]) => (
                    <button
                      key={k}
                      onClick={() => navigate(`/inbox?intent=${encodeURIComponent(k)}`)}
                      className="flex items-center justify-between text-left hover:bg-zbrain-50 rounded px-1.5 py-0.5"
                      title={`Open inbox filtered to ${INTENT_LABEL[k] || k}`}
                    >
                      <span className="text-zbrain-ink truncate">{INTENT_LABEL[k] || k}</span>
                      <span className="text-zbrain-muted tabular-nums shrink-0 ml-2">{num(v as number)}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>

        {/* ===== Recent activities ===== */}
        <div className="lg:col-span-2">
          <Card title="Recent activities" meta="Most recent 10 emails" linkLabel="Open Inbox →" linkTo="/inbox">
            {recent.length === 0 ? (
              <Empty text="No emails yet." />
            ) : (
              <ul className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
                {recent.map((e) => (
                  <li
                    key={e.id}
                    className="px-4 py-2.5 hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2 transition-colors cursor-pointer"
                    onClick={() => {
                      // Awaiting-HITL rows go straight to the HITL queue
                      // filtered to that pipeline; everything else opens the
                      // trace (if present) or the email in the inbox.
                      if (e.status === "awaiting_hitl" && e.pipeline?.id) {
                        navigate(`/hitl?pipeline=${e.pipeline.id}`);
                        return;
                      }
                      navigate(e.pipeline?.id ? `/trace/${e.pipeline.id}` : `/inbox?id=${e.id}`);
                    }}
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[13.5px] font-medium truncate text-zbrain-ink">
                            {e.subject || "(no subject)"}
                          </span>
                          <ActivityStatusPill status={e.status} />
                          {e.pipeline?.intent && (
                            <span
                              className={`pill text-[10px] uppercase tracking-wide ${pillTone(e.pipeline.intent)}`}
                            >
                              {INTENT_LABEL[e.pipeline.intent] || e.pipeline.intent}
                            </span>
                          )}
                          {e.pipeline?.autonomy_tier && (
                            <span className="pill text-[10px] bg-slate-100 text-slate-600">
                              {e.pipeline.autonomy_tier}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-zbrain-muted mt-0.5 truncate">
                          {e.from} · {e.customer_name || "-"}
                        </div>
                      </div>
                      <div className="text-xs text-zbrain-muted shrink-0 tabular-nums">
                        {relTime(e.received_at)}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {/* System health and admin shortcuts moved to the Orchestrator (admin
          back-end). The functional Dashboard now sticks to case work only. */}

      <PipelineDetailPanel summary={summary} navigate={navigate} />

      <RecentAutonomousReplies />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <QuickLink
          to="/kb"
          icon={<IconKB />}
          title="Knowledge Base"
          desc="Outlook rules, intent definitions, routing, operational rules."
        />
        <QuickLink
          to="/analytics"
          icon={<IconAnalytics />}
          title="Analytics"
          desc="Funnel, throughput, intent mix, autonomy distribution."
        />
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// System readiness tile — surfaces blockers loudly on the dashboard.
// ────────────────────────────────────────────────────────────────
function ReadinessTile() {
  const { report } = useReadiness();
  if (!report) return null;
  const ok = report.ok;
  const blockers = report.blockers;
  const warnings = report.warnings;
  return (
    <Card title="System readiness" meta={ok ? "ready" : `${blockers.length} blocker${blockers.length === 1 ? "" : "s"}`}>
      <div className="px-4 py-3">
        {report.demo_mode && (
          <div className="mb-3 px-3 py-2 rounded-md bg-rose-50 border border-rose-200 text-[12px] text-rose-800">
            <strong>Demo mode:</strong> local fallbacks enabled. Do not run in production.
          </div>
        )}
        {ok && blockers.length === 0 && warnings.length === 0 && (
          <div className="text-sm text-emerald-700 font-medium">
            All required services connected. Pipeline can process inbound mail.
          </div>
        )}
        {blockers.length > 0 && (
          <ul className="space-y-2">
            {blockers.map((b) => (
              <li key={b.provider} className="flex items-start gap-3 text-sm">
                <span className="inline-block w-2 h-2 rounded-full bg-rose-500 mt-1.5 shrink-0" />
                <div className="flex-1">
                  <div className="font-semibold text-zbrain-ink">{b.title}</div>
                  <div className="text-xs text-zbrain-muted mt-0.5">{b.detail}</div>
                </div>
                <Link to={b.fix_url} className="text-xs font-medium text-zbrain hover:underline whitespace-nowrap mt-1">
                  Connect →
                </Link>
              </li>
            ))}
          </ul>
        )}
        {blockers.length === 0 && warnings.length > 0 && (
          <ul className="space-y-2">
            {warnings.map((w) => (
              <li key={w.provider + w.title} className="flex items-start gap-3 text-sm">
                <span className="inline-block w-2 h-2 rounded-full bg-amber-500 mt-1.5 shrink-0" />
                <div className="flex-1">
                  <div className="font-semibold text-zbrain-ink">{w.title}</div>
                  <div className="text-xs text-zbrain-muted mt-0.5">{w.detail}</div>
                </div>
                <Link to={w.fix_url} className="text-xs font-medium text-zbrain hover:underline whitespace-nowrap mt-1">
                  Configure →
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

// ────────────────────────────────────────────────────────────────
// Pipeline verification tile — surfaces the verifier's rollup across the
// last 7 days. Shows pass/fail counts, top firing rules, and a link to
// the Knowledge Base where operators can edit / promote rules.
// ────────────────────────────────────────────────────────────────
function VerificationTile() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.system.verificationRollup>> | null>(null);
  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const r = await api.system.verificationRollup(7);
        if (!cancel) setData(r);
      } catch {
        if (!cancel) setData(null);
      }
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => { cancel = true; clearInterval(id); };
  }, []);
  if (!data) return null;
  const fail = data.fail_count;
  const pass = data.pass_count;
  const total = pass + fail;
  return (
    <Card title="Pipeline verification" meta={`${total} checks · ${fail} violated · last ${data.window_days}d`}>
      <div className="px-4 py-3 space-y-3">
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div className="rounded-md border border-zbrain-divider px-3 py-2.5 bg-zbrain-surface/30">
            <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">Pipelines halted</div>
            <div className="text-lg font-semibold tabular-nums mt-1 text-rose-700">{data.halted_pipelines.length}</div>
          </div>
          <div className="rounded-md border border-zbrain-divider px-3 py-2.5 bg-zbrain-surface/30">
            <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">With blockers</div>
            <div className="text-lg font-semibold tabular-nums mt-1 text-rose-700">{data.pipelines_with_block}</div>
          </div>
          <div className="rounded-md border border-zbrain-divider px-3 py-2.5 bg-zbrain-surface/30">
            <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">With warnings</div>
            <div className="text-lg font-semibold tabular-nums mt-1 text-amber-700">{data.pipelines_with_warn}</div>
          </div>
        </div>
        {data.top_failing_rules.length > 0 ? (
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold mb-1.5">Top firing rules</div>
            <ul className="space-y-1">
              {data.top_failing_rules.map((r) => (
                <li key={r.rule_key} className="flex items-center justify-between text-[12.5px]">
                  <span className="font-mono text-zbrain-ink truncate">{r.rule_key}</span>
                  <span className="text-zbrain-muted tabular-nums shrink-0 ml-2">
                    <span className="text-rose-700 font-medium">{r.fail_count}</span> fail / <span className="text-emerald-700 font-medium">{r.pass_count}</span> pass
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="text-sm text-emerald-700 font-medium">
            All verification rules are passing.
          </div>
        )}
        <div className="pt-1 border-t border-zbrain-divider mt-1 text-[11px] text-zbrain-muted flex items-center justify-between">
          <span>{pass + fail} total invariant evaluations</span>
          <Link to="/kb" className="text-zbrain hover:underline font-medium">Edit verification rules →</Link>
        </div>
      </div>
    </Card>
  );
}

// ────────────────────────────────────────────────────────────────
// KPI tile — sharper visual per the Console design.
// ────────────────────────────────────────────────────────────────
function KpiTile({
  label,
  value,
  unit,
  sub,
  tone = "neutral",
  onClick,
}: {
  label: string;
  value: number | string;
  unit?: string;
  sub?: string;
  tone?: "neutral" | "amber" | "rose";
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "text-left card px-4 py-3.5 transition-all w-full",
        "hover:shadow-md hover:-translate-y-[1px]",
        tone === "amber" ? "ring-1 ring-amber-300/70 bg-amber-50/40" : "",
        tone === "rose" ? "ring-1 ring-rose-300/70 bg-rose-50/40" : "",
      ].join(" ")}
    >
      <div className="text-[11px] uppercase tracking-wider font-semibold text-zbrain-muted">
        {label}
      </div>
      <div className="flex items-baseline gap-1.5 mt-1.5">
        <div className="text-[26px] font-semibold tabular-nums text-zbrain-ink leading-none tracking-tight">
          {value}
        </div>
        {unit && <span className="text-[12px] text-zbrain-muted font-medium">{unit}</span>}
      </div>
      {sub && (
        <div className="text-[11.5px] text-zbrain-muted mt-1.5 truncate">{sub}</div>
      )}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────
// Inline SVG icons — flat, single-color, sized to the parent class. Kept
// inline to avoid pulling another icon library; matches the lucide-style
// hairline weight used elsewhere.
// ────────────────────────────────────────────────────────────────
function SvgBase({ className = "h-5 w-5", children }: { className?: string; children: React.ReactNode }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}
function IconCases({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </SvgBase>
  );
}
function IconAutomation({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
      <circle cx="12" cy="12" r="3" />
    </SvgBase>
  );
}
function IconTime({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </SvgBase>
  );
}
function IconAlert({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12" y2="17" />
    </SvgBase>
  );
}
function IconRunBatch({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <polygon points="6 4 20 12 6 20 6 4" />
    </SvgBase>
  );
}
function IconLearning({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <path d="M22 10 12 4 2 10l10 6 10-6Z" />
      <path d="M6 12v5c0 1 4 3 6 3s6-2 6-3v-5" />
    </SvgBase>
  );
}
function IconKB({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5v14Z" />
      <path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5H6.5A2.5 2.5 0 0 0 4 19.5Z" />
    </SvgBase>
  );
}
function IconIntegrations({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <rect x="9" y="2" width="6" height="6" rx="1" />
      <rect x="2" y="14" width="6" height="6" rx="1" />
      <rect x="16" y="14" width="6" height="6" rx="1" />
      <path d="M12 8v3M5 14v-3h14v3" />
    </SvgBase>
  );
}
function IconAnalytics({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <path d="M4 19h16" />
      <rect x="6" y="11" width="3" height="6" rx="0.5" />
      <rect x="11" y="7" width="3" height="10" rx="0.5" />
      <rect x="16" y="13" width="3" height="4" rx="0.5" />
    </SvgBase>
  );
}
function IconCheck({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <polyline points="20 6 9 17 4 12" />
    </SvgBase>
  );
}
function IconX({ className }: { className?: string } = {}) {
  return (
    <SvgBase className={className}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </SvgBase>
  );
}

// ────────────────────────────────────────────────────────────────
// Hero metric — large, icon-led tile used for the 3 numbers a CSR/admin
// reads on the first screen.
// ────────────────────────────────────────────────────────────────
function HeroMetric({
  icon,
  accent,
  label,
  value,
  unit,
  sub,
  tooltip,
  onClick,
}: {
  icon: React.ReactNode;
  accent: string;
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  tooltip?: string;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="text-left card px-5 py-4 transition-all w-full hover:shadow-md hover:-translate-y-[1px]"
    >
      <div className="flex items-center gap-3">
        <span
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg shrink-0"
          style={{ background: `${accent}1A`, color: accent }}
        >
          {icon}
        </span>
        <div className="flex items-center gap-1.5">
          <div className="text-[11px] uppercase tracking-wider font-semibold text-zbrain-muted">
            {label}
          </div>
          {tooltip && (
            <span
              className="relative inline-flex group"
              onClick={(e) => e.stopPropagation()}
            >
              <span
                className="w-3.5 h-3.5 rounded-full border border-zbrain-muted/60 text-zbrain-muted flex items-center justify-center text-[9px] font-bold leading-none cursor-help hover:border-zbrain hover:text-zbrain transition-colors"
                aria-label={`About ${label}`}
              >
                i
              </span>
              <span className="pointer-events-none absolute left-0 top-5 z-30 hidden group-hover:block w-72 rounded-lg bg-zbrain-ink text-white text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line normal-case font-normal tracking-normal">
                {tooltip}
              </span>
            </span>
          )}
        </div>
      </div>
      <div className="flex items-baseline gap-1.5 mt-3">
        <div className="text-[30px] font-semibold tabular-nums text-zbrain-ink leading-none tracking-tight">
          {value}
        </div>
        {unit && <span className="text-[12px] text-zbrain-muted font-medium">{unit}</span>}
      </div>
      {sub && (
        <div className="text-[11.5px] text-zbrain-muted mt-2 truncate">{sub}</div>
      )}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────
// System health strip — compact icon row of every system the pipeline
// depends on, with a state pill per service. Replaces the two big
// ReadinessTile + VerificationTile blocks.
// ────────────────────────────────────────────────────────────────
// SystemHealthStrip removed — system health is an admin concern and now
// lives in the ZBrain Orchestrator (Application Governance → Overview).
// Functional users still see degraded state via the readiness banner.

// ────────────────────────────────────────────────────────────────
// Status pulse — one-line "is the system healthy?" indicator under the title.
// Replaces the bottom-of-page readiness card as a glanceable header signal.
// ────────────────────────────────────────────────────────────────
function StatusPulse() {
  const { report } = useReadiness();
  if (!report) {
    return (
      <p className="text-sm text-zbrain-muted mt-1">System status loading…</p>
    );
  }
  const ok = report.ok;
  const blockerCount = report.blockers.length;
  const warningCount = report.warnings.length;
  const dotClass = !ok
    ? "bg-rose-500"
    : warningCount > 0
    ? "bg-amber-500"
    : "bg-emerald-500";
  const label = !ok
    ? `System halted · ${blockerCount} blocker${blockerCount === 1 ? "" : "s"}`
    : warningCount > 0
    ? `Healthy · ${warningCount} warning${warningCount === 1 ? "" : "s"}`
    : "Healthy · all required services connected";
  return (
    <div className="mt-1.5 flex items-center gap-2 text-sm text-zbrain-muted">
      <span className={`inline-block h-2 w-2 rounded-full ${dotClass}`} aria-hidden />
      <span>{label}</span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Attention tile — large, colored, action-oriented. Shown only when count > 0.
// ────────────────────────────────────────────────────────────────
function AttentionTile({
  label,
  value,
  hint,
  cta,
  tone,
  onClick,
}: {
  label: string;
  value: number;
  hint: string;
  cta: string;
  tone: "rose" | "amber";
  onClick: () => void;
}) {
  const palette =
    tone === "rose"
      ? {
          bg: "bg-rose-50",
          ring: "ring-rose-200",
          accent: "text-rose-700",
          dot: "bg-rose-500",
        }
      : {
          bg: "bg-amber-50",
          ring: "ring-amber-200",
          accent: "text-amber-700",
          dot: "bg-amber-500",
        };
  return (
    <button
      onClick={onClick}
      className={`text-left rounded-xl ring-1 ${palette.ring} ${palette.bg} px-5 py-4 transition-all hover:-translate-y-[1px] hover:shadow-md w-full`}
    >
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2 w-2 rounded-full ${palette.dot}`} aria-hidden />
        <div className="text-[11px] uppercase tracking-wider font-semibold text-zbrain-muted">
          {label}
        </div>
      </div>
      <div className="flex items-baseline gap-2 mt-2">
        <div className={`text-[36px] font-semibold tabular-nums leading-none tracking-tight ${palette.accent}`}>
          {value.toLocaleString()}
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[12px] text-zbrain-muted">{hint}</span>
        <span className={`text-[12px] font-semibold ${palette.accent}`}>{cta} →</span>
      </div>
    </button>
  );
}

// ────────────────────────────────────────────────────────────────
// Throughput card — unifies emails/min, worker pool utilisation, queue depth,
// and percentiles into a single panel instead of three KpiTile fragments.
// ────────────────────────────────────────────────────────────────
function ThroughputCard({
  summary,
  queue,
  onAnalytics,
}: {
  summary: AnalyticsSummary | null;
  queue: import("../api").QueueStatus | null;
  onAnalytics: () => void;
}) {
  const epm = summary?.throughput?.emails_per_minute ?? 0;
  const p50 = summary?.throughput?.p50_ms ?? 0;
  const p95 = summary?.throughput?.p95_ms ?? 0;
  const queueDepth = summary?.throughput?.queue_depth ?? 0;
  const max = queue?.max_workers ?? 0;
  const inFlight = queue?.in_flight ?? 0;
  const util = queue?.utilisation_pct ?? 0;
  return (
    <Card title="Throughput · live pool status" linkLabel="Detailed analytics →" linkTo="/analytics">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 px-5 py-4">
        <Stat label="Rate" value={`${epm}`} unit="emails/min" />
        <Stat label="Pool" value={`${inFlight} / ${max || "-"}`} unit={`workers · ${util}% util`} />
        <Stat label="P50 latency" value={fmtMs(p50)} unit="median" />
        <Stat label="P95 latency" value={fmtMs(p95)} unit="tail" />
      </div>
      <div className="border-t border-zbrain-divider px-5 py-3 flex items-center justify-between text-[11.5px] text-zbrain-muted">
        <span>Backlog (new + in flight): <strong className="text-zbrain-ink tabular-nums">{num(queueDepth)}</strong> emails</span>
        <button onClick={onAnalytics} className="text-zbrain hover:underline">Open process flow →</button>
      </div>
    </Card>
  );
}

function Stat({ label, value, unit, hint }: { label: string; value: string; unit?: string; hint?: string }) {
  return (
    <div title={hint || undefined} className={hint ? "cursor-help" : undefined}>
      <div className="text-[10.5px] uppercase tracking-wider font-semibold text-zbrain-muted">{label}</div>
      <div className="flex items-baseline gap-1.5 mt-1.5">
        <div className="text-[22px] font-semibold tabular-nums text-zbrain-ink leading-none tracking-tight">
          {value}
        </div>
        {unit && <span className="text-[11px] text-zbrain-muted">{unit}</span>}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Pipeline detail panel — collapsible (default closed) home for the secondary
// metrics that used to occupy their own KpiTile row: mailbox triage, AIOA,
// CMD activation. Surfaced behind a click so the headline dashboard stays
// focused on the four numbers operators actually act on.
// ────────────────────────────────────────────────────────────────
function PipelineDetailPanel({
  summary,
  navigate,
}: {
  summary: AnalyticsSummary | null;
  navigate: (to: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!summary) return null;
  const triage = summary.mailbox_door_triage || { matched_by_rule: 0, by_filter: {} as Record<string, number> };
  const aioa = summary.aioa || { pass: 0, fail: 0, skipped_not_applicable: 0, timed_out: 0 };
  const cmd = summary.cmd_activation || { requested: 0 };
  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 border-b border-zbrain-divider flex items-center justify-between hover:bg-zbrain-50"
      >
        <div className="text-left">
          <div className="text-[13.5px] font-semibold text-zbrain-ink tracking-tight">
            Process detail
          </div>
          <div className="text-[11.5px] text-zbrain-muted mt-0.5">
            Mailbox triage, AIOA validation, CMD activation: secondary signals.
          </div>
        </div>
        <span className="text-zbrain-muted text-xs">{open ? "▾ Hide" : "▸ Show"}</span>
      </button>
      {open && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 px-4 py-4">
          <KpiTile
            label="Mailbox-door triage"
            value={num(triage.matched_by_rule)}
            unit="filtered"
            sub={(() => {
              // Per-intent breakdown reconciled against the total per-intent
              // case count: if the deterministic mailbox rule caught 23 of 32
              // KSO cases, the remaining 9 were caught downstream by the LLM
              // intent classifier at Intake. Surface "X of Y" so the operator
              // can reconcile this tile against the Intent-mix tile without
              // wondering why the numbers differ.
              const f = triage.by_filter || {};
              const totals = summary.by_intent || ({} as Record<string, number>);
              const keys = ["spam", "kso", "brazil_tax", "collections", "portal_admin", "undeliverable"];
              const parts: string[] = [];
              for (const k of keys) {
                const at_door = f[k] || 0;
                const total = totals[k] || 0;
                if (!at_door && !total) continue;
                const label =
                  k === "spam" ? "spam" :
                  k === "kso" ? "KSO" :
                  k === "brazil_tax" ? "Brazil tax" :
                  k === "collections" ? "collections" :
                  k === "portal_admin" ? "portal admin" :
                  "bounces";
                const downstream = Math.max(0, total - at_door);
                parts.push(
                  downstream > 0
                    ? `${label} ${at_door}/${total} (+${downstream} downstream)`
                    : `${label} ${at_door}`,
                );
              }
              return parts.length ? parts.slice(0, 3).join(" · ") : "Stage 0 pre-AI rules";
            })()}
            onClick={() => navigate("/inbox?status=redirected&intent=kso")}
          />
          <KpiTile
            label="AIOA validation"
            value={`${aioa.pass}/${aioa.pass + aioa.fail}`}
            unit="pass"
            sub={`${num(aioa.fail)} fallout · ${num(aioa.timed_out || 0)} timed out · ${num(aioa.skipped_not_applicable)} not applicable`}
            onClick={() => navigate("/aioa")}
          />
          <KpiTile
            label="CMD activation"
            value={num(cmd.requested)}
            unit="triggered"
            sub="Customer not in Salesforce; CMD pattern fired"
            onClick={() => navigate("/hitl?reason=unknown_customer_in_salesforce")}
          />
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Pipeline funnel stage card.
// ────────────────────────────────────────────────────────────────
function FunnelStage({
  stage,
  isLast,
  onClick,
}: {
  stage: { id: number; key: string; name: string; tagline: string; volume: number; autoPct: number; hitlPct: number; p95: number };
  isLast: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="relative text-left transition-all hover:-translate-y-[1px] hover:shadow-md group"
      style={{
        background: PAL.blueTint,
        border: `1px solid ${PAL.line}`,
        borderRadius: 10,
        padding: "14px 12px",
        minHeight: 184,
      }}
    >
      <div
        className="text-[10.5px] font-bold uppercase tracking-wider"
        style={{ color: PAL.bluePrimary }}
      >
        Stage {stage.id}
      </div>
      <div
        className="text-[12.5px] font-semibold leading-tight mt-1 mb-2.5"
        style={{ color: PAL.text }}
      >
        {stage.name}
      </div>
      <div className="flex items-baseline gap-1">
        <div className="text-[22px] font-semibold tabular-nums leading-none tracking-tight" style={{ color: PAL.text }}>
          {num(stage.volume)}
        </div>
        <span className="text-[10.5px] font-medium" style={{ color: PAL.textMute }}>
          {stage.volume === 1 ? "case" : "cases"}
        </span>
      </div>
      <div className="mt-2">
        <div
          className="flex overflow-hidden"
          style={{ height: 8, borderRadius: 4, background: "#E5E7EB" }}
        >
          <div style={{ background: PAL.auto, width: `${stage.autoPct}%`, height: "100%" }} />
          <div style={{ background: PAL.hitl, width: `${stage.hitlPct}%`, height: "100%" }} />
        </div>
        <div className="flex justify-between text-[10.5px] mt-1.5" style={{ color: PAL.textMute }}>
          <span>
            <span style={{ color: PAL.auto, fontWeight: 600 }}>{stage.autoPct.toFixed(0)}%</span> auto
          </span>
          <span
            title="Share of pipelines that paused for a human gate AT this stage. Upstream of Execute, no human gate fires, so intake reads as 0%."
            className="cursor-help"
          >
            <span style={{ color: PAL.hitl, fontWeight: 600 }}>{stage.hitlPct.toFixed(0)}%</span> HITL
          </span>
        </div>
      </div>
      {stage.p95 > 0 && (
        <div className="text-[10.5px] mt-2 tabular-nums" style={{ color: PAL.textMute }}>
          p95 {fmtMs(stage.p95)}
        </div>
      )}
      {!isLast && (
        <span
          aria-hidden
          className="hidden lg:block absolute z-10"
          style={{
            right: -6,
            top: "50%",
            transform: "translateY(-50%) rotate(45deg)",
            width: 12,
            height: 12,
            background: PAL.blueTint,
            borderTop: `1px solid ${PAL.line}`,
            borderRight: `1px solid ${PAL.line}`,
          }}
        />
      )}
    </button>
  );
}

function FunnelSkeleton() {
  return (
    <div
      style={{
        background: PAL.blueTint,
        border: `1px solid ${PAL.line}`,
        borderRadius: 10,
        padding: "14px 12px",
        minHeight: 184,
      }}
      className="animate-pulse"
    >
      <div className="h-3 w-16 bg-slate-200 rounded mb-2" />
      <div className="h-4 w-28 bg-slate-200/80 rounded mb-3" />
      <div className="h-6 w-20 bg-slate-200/60 rounded" />
      <div className="h-2 w-full bg-slate-200/40 rounded mt-3" />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Card primitive matching Console HTML's .card and .card-head.
// ────────────────────────────────────────────────────────────────
function Card({
  title,
  meta,
  linkLabel,
  linkTo,
  children,
}: {
  title: string;
  meta?: string;
  linkLabel?: string;
  linkTo?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between">
        <div>
          <div className="text-[13.5px] font-semibold text-zbrain-ink tracking-tight">{title}</div>
          {meta && <div className="text-[11.5px] text-zbrain-muted mt-0.5">{meta}</div>}
        </div>
        {linkLabel && linkTo && (
          <Link to={linkTo} className="text-xs text-zbrain hover:underline shrink-0">
            {linkLabel}
          </Link>
        )}
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="px-4 py-8 text-sm text-zbrain-muted text-center">{text}</div>;
}

function QuickLink({
  to,
  title,
  desc,
  icon,
}: {
  to: string;
  title: string;
  desc: string;
  icon?: React.ReactNode;
}) {
  // Paths that point outside the SalesOps SPA (the Orchestrator app or an
  // env-overridden absolute URL) need a hard navigation, not a SPA Link.
  const isExternal =
    /^https?:\/\//i.test(to) || to.startsWith("/keysight-salesops-governance/");
  const Tag = isExternal ? "a" : Link;
  const linkProps = isExternal ? { href: to } : { to };
  return (
    // @ts-expect-error union props
    <Tag {...linkProps} className="card px-4 py-3.5 hover:shadow-md transition-all block">
      <div className="flex items-center gap-2">
        {icon && (
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-zbrain-50 text-zbrain-primary">
            {icon}
          </span>
        )}
        <div className="text-[13.5px] font-semibold text-zbrain-ink">{title}</div>
      </div>
      <div className="text-[11.5px] text-zbrain-muted mt-1.5">{desc}</div>
    </Tag>
  );
}

function SysRow({
  name,
  status,
  detail,
}: {
  name: string;
  status: "ok" | "external" | "down" | "unknown" | "not-configured" | "mock" | "upcoming";
  detail?: string;
}) {
  const tone =
    status === "ok"
      ? { dot: PAL.auto, label: "live", tag: "bg-emerald-100 text-emerald-700" }
      : status === "down"
      ? { dot: PAL.risk, label: "down", tag: "bg-rose-100 text-rose-700" }
      : status === "external"
      ? { dot: "#6B7280", label: "Keysight-side", tag: "bg-slate-100 text-slate-600" }
      : status === "mock"
      ? { dot: PAL.bluePrimary, label: "demo mock", tag: "bg-blue-50 text-blue-700" }
      : status === "upcoming"
      ? { dot: PAL.blueSoft, label: "upcoming", tag: "bg-indigo-50 text-indigo-700" }
      : status === "not-configured"
      ? { dot: "#9CA3AF", label: "not configured", tag: "bg-slate-100 text-slate-600" }
      : { dot: "#9CA3AF", label: "unknown", tag: "bg-slate-100 text-slate-500" };
  return (
    <li className="flex items-center justify-between">
      <div className="flex items-center gap-2 min-w-0">
        <span className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: tone.dot }} />
        <span className="text-zbrain-ink truncate">{name}</span>
      </div>
      <span className="flex items-center gap-2 shrink-0">
        {detail && <span className="text-[11.5px] text-zbrain-muted truncate">{detail}</span>}
        <span className={`pill text-[10px] uppercase tracking-wide ${tone.tag}`}>{tone.label}</span>
      </span>
    </li>
  );
}

// Recent autonomous replies — shows the latest L4 customer replies that
// went out (or would have gone out under the demo lock) so the operator can
// audit the front-side outbound without going into the HITL queue.
function RecentAutonomousReplies() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<import("../api").CommLogEntry[] | null>(null);
  useEffect(() => {
    let cancel = false;
    const refresh = async () => {
      try {
        const r = await api.communicationLogs();
        if (!cancel) setRows(r);
      } catch {
        if (!cancel) setRows([]);
      }
    };
    refresh();
    const id = setInterval(refresh, 15000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);

  const l4 = (rows || []).filter((r) => r.direction === "outbound" && (r.autonomy_tier || "").toUpperCase() === "L4_AUTO").slice(0, 6);

  return (
    <div>
      <Card
        title="Autonomous replies (L4)"
        meta={rows == null ? "-" : `${l4.length} most recent · ${(rows || []).filter((r) => (r.autonomy_tier || "").toUpperCase() === "L4_AUTO").length} total`}
        linkLabel="See all →"
        linkTo="/inbox?autonomy_tier=L4_AUTO"
      >
        {rows == null ? (
          <Empty text="Loading…" />
        ) : l4.length === 0 ? (
          <Empty text="No L4 autonomous replies yet. They appear here as soon as a case clears the 0.95 confidence threshold and the reply is sent." />
        ) : (
          // Compact 2-column tile grid. Each tile is self-contained and
          // narrow so the card stops eating full-page width; intent pill +
          // subject + sender stack vertically with the timestamp right-aligned.
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 p-3">
            {l4.map((r) => (
              <button
                type="button"
                key={r.id}
                onClick={() => r.pipeline_id && navigate(`/trace/${r.pipeline_id}`)}
                className="text-left rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 px-3 py-2 hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2 transition-colors"
              >
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="pill text-[9.5px] bg-emerald-100 text-emerald-700">L4</span>
                  {r.intent && (
                    <span className={`pill text-[9.5px] ${pillTone(r.intent)}`}>{INTENT_LABEL[r.intent] || r.intent}</span>
                  )}
                  <span className="ml-auto text-[10px] text-zbrain-muted tabular-nums shrink-0">
                    {relTime(r.occurred_at)}
                  </span>
                </div>
                <div className="text-[12.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink mt-1 truncate">
                  {r.subject || "(no subject)"}
                </div>
                <div className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 truncate">
                  {(r.customer_code || r.customer_name || "-")}
                  {r.body_preview && (
                    <>
                      <span className="opacity-60"> · </span>
                      {(r.body_preview || "").slice(0, 80)}
                    </>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function ActivityStatusPill({ status }: { status?: string | null }) {
  if (!status) return null;
  const s = String(status).toLowerCase();
  const map: Record<string, { label: string; cls: string }> = {
    new: { label: "New", cls: "bg-slate-100 text-slate-700" },
    processing: { label: "Processing", cls: "bg-blue-100 text-blue-700" },
    awaiting_hitl: { label: "Awaiting HITL", cls: "bg-amber-100 text-amber-800" },
    processed: { label: "Processed", cls: "bg-emerald-100 text-emerald-700" },
    redirected: { label: "Redirected", cls: "bg-violet-100 text-violet-700" },
    discarded: { label: "Discarded", cls: "bg-rose-100 text-rose-700" },
    rejected: { label: "Rejected", cls: "bg-rose-100 text-rose-700" },
  };
  const m = map[s] || { label: s, cls: "bg-slate-100 text-slate-600" };
  return <span className={`pill text-[10px] uppercase tracking-wide ${m.cls}`}>{m.label}</span>;
}

function pillTone(intent: string): string {
  if (["kso", "undeliverable", "brazil_tax", "portal_admin", "collections"].includes(intent))
    return "bg-rose-100 text-rose-700";
  if (intent === "spam" || intent === "out_of_scope") return "bg-slate-100 text-slate-600";
  if (["wo_status_inquiry", "general_inquiry"].includes(intent)) return "bg-amber-100 text-amber-800";
  if (["po_intake", "quote_to_order"].includes(intent)) return "bg-emerald-100 text-emerald-700";
  return "bg-sky-100 text-sky-700";
}
// === v1.1 DASHBOARD END ===


// ────────────────────────────────────────────────────────────────
// Order Acceptance dashboard card — surfaces the AIOA queue at a
// glance so a CSR can jump straight to /aioa without going through
// the main nav (which doesn't expose this queue by design).
// ────────────────────────────────────────────────────────────────
function OrderAcceptanceCard({
  summary,
  onOpen,
}: {
  summary: AnalyticsSummary | null;
  onOpen: () => void;
}) {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [providerOffline, setProviderOffline] = useState<boolean>(false);
  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const r = await aioaApi.listRequests({ limit: 1 });
        if (!cancel) setCounts(r.counts_by_status || {});
      } catch {}
      // Provider readiness: the queue can hold stranded `timed_out` requests
      // even when no provider is active. Surface the offline state alongside
      // the queue stats so the CSR sees the cause, not just the symptom.
      try {
        const providers = await aioaApi.listProviders();
        if (cancel) return;
        const anyActive = providers.some((p) => p.is_active);
        setProviderOffline(!anyActive);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 6000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);
  const waitingNow = summary?.totals.awaiting_aioa ?? 0;
  const pending = counts.pending_send || 0;
  const sent = counts.sent || 0;
  const processed = counts.processed || 0;
  const timed = counts.timed_out || 0;
  // Decide which stat to render in the "in progress" slot. When the queue
  // is entirely composed of timed-out requests, showing `Waiting: 37` is
  // misleading because nothing is actually progressing. Render `Timed out`
  // instead so the operator knows the cases are stranded, not in-flight.
  const inProgress = pending + sent;
  const showTimedAsPrimary = inProgress === 0 && timed > 0;
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between">
        <div>
          <div className="text-[13.5px] font-semibold text-zbrain-ink tracking-tight">Order Acceptance</div>
          <div className="text-[11.5px] text-zbrain-muted mt-0.5">AIOA validation queue</div>
        </div>
        <button onClick={onOpen} className="text-xs text-zbrain hover:underline shrink-0">
          Open queue →
        </button>
      </div>
      {/* Provider-offline banner removed. Pipeline-stopping config errors
          surface in the case trace at the parking stage, not as a side-card
          banner on the Dashboard. */}
      <div className="px-5 py-4 grid grid-cols-3 gap-3">
        {showTimedAsPrimary ? (
          <Stat label="Timed out" value={String(timed)} />
        ) : (
          <Stat label="Waiting" value={String(waitingNow || inProgress)} />
        )}
        <Stat label="Processed" value={String(processed)} />
        {showTimedAsPrimary ? (
          <Stat label="Waiting" value={String(waitingNow || inProgress)} />
        ) : (
          <Stat label={timed > 0 ? "Timed out" : "Timeout"} value={String(timed)} />
        )}
      </div>
    </div>
  );
}
