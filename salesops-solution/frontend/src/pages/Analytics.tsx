import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Doughnut } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";

import { SeverityChip } from "../components/Chips";

import {
  AgentFabricStats,
  AnalyticsSummary,
  KbRuleFire,
  StageMeta,
  ToolInvocationStat,
  api,
} from "../api";

ChartJS.register(ArcElement, Tooltip, Legend);

const RANGES: { label: string; hours: number }[] = [
  { label: "All time", hours: 0 },
  { label: "Last 24h", hours: 24 },
  { label: "Last 7d", hours: 24 * 7 },
  { label: "Last 30d", hours: 24 * 30 },
  { label: "Last hour", hours: 1 },
];

const INTENT_LABELS: Record<string, string> = {
  po_intake: "PO intake",
  quote_to_order: "Quote → Order",
  hold_release: "Hold release",
  delivery_change: "Delivery change",
  service_order: "Service order",
  wo_status_inquiry: "WO status",
  wo_update_request: "WO update",
  general_inquiry: "Inquiry",
  trade_change_order: "Trade change",
  ssd_change_request: "SSD change",
  service_contract_request: "Service contract",
  spam: "Spam",
  unknown: "Unknown",
};

// Canonical stage names: matches analytics.subprocess_taxonomy.STAGE_META
// and frontend/Dashboard STAGE_DEFS. Keep these in sync.
const STAGE_LABELS: Record<string, string> = {
  intake: "Intake & Classification",
  extract: "Extraction & Enrichment",
  decide: "Decision & Confidence Scoring",
  execute: "Workflow Execution",
  communicate: "Communication & Close-out",
  learning: "Continuous Learning",
};

const STAGE_ORDER = ["intake", "extract", "decide", "execute", "communicate", "learning"];

const PROVIDER_LABELS: Record<string, string> = {
  llm: "ZBrain LLM",
  azure: "Azure Translator",
  deepl: "DeepL",
  google: "Google Translate",
};

type ToolSortKey = "count" | "ok_rate" | "p50_ms" | "p95_ms" | "tool";

export function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [fabric, setFabric] = useState<AgentFabricStats | null>(null);
  const [hours, setHours] = useState<number>(0);
  const [toolSort, setToolSort] = useState<ToolSortKey>("count");
  const [toolDesc, setToolDesc] = useState<boolean>(true);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api.analytics(hours).then((d) => !cancelled && setSummary(d)).catch(() => undefined);
      api.analytics.agentFabric().then((d) => !cancelled && setFabric(d)).catch(() => undefined);
    };
    tick();
    const id = setInterval(tick, 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [hours]);

  const drillTo = (params: Record<string, string>) => {
    const usp = new URLSearchParams(params);
    navigate(`/inbox?${usp.toString()}`);
  };

  const sortedTools = useMemo(() => {
    if (!fabric) return [];
    const rows = [...fabric.tool_invocations];
    rows.sort((a, b) => compareTools(a, b, toolSort, toolDesc));
    return rows;
  }, [fabric, toolSort, toolDesc]);

  if (!summary || !fabric)
    return <div className="card p-8 text-center text-zbrain-muted text-sm">Loading analytics…</div>;

  const { totals, autonomy, feedback } = summary;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-[22px] font-semibold tracking-tight text-zbrain-ink">Analytics</h1>
        <p className="text-sm text-zbrain-muted mt-1">
          Operational health of the SalesOps solution. Process flow, cost telemetry, per-stage rollup, and diagnostics.
        </p>
      </header>

      <AnalyticsHeroPanels />

      <PerStageEntry />

      <div className="card p-3 flex items-center gap-2 flex-wrap">
        <span className="text-xs uppercase tracking-wider text-zbrain-muted px-1">Diagnostics time range:</span>
        {RANGES.map((r) => (
          <button
            key={r.hours}
            onClick={() => setHours(r.hours)}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              hours === r.hours
                ? "bg-zbrain text-white"
                : "border border-zbrain-divider text-zbrain-ink hover:bg-zbrain-50"
            }`}
          >
            {r.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-zbrain-muted">
          Refreshes every 10 s · agent-fabric metrics are all-time
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPI label="Cases processed" value={totals.pipelines} sub={`${totals.completed} completed`} />
        <KPI
          label="Pending HITL"
          value={totals.pending_hitl}
          sub={`${feedback.total} resolutions`}
          highlight={totals.pending_hitl > 0}
          onClick={() => navigate(`/hitl`)}
        />
        <KPI
          label="Automation rate"
          value={`${Math.round(autonomy.automation_rate * 100)}%`}
          sub="L4 fully autonomous"
          onClick={() => drillTo({ autonomy_tier: "L4_AUTO" })}
        />
        <KPI label="Inbox" value={totals.inbox_total} sub={`${totals.inbox_unprocessed} new`} />
      </div>

      <DiagnosticsSummary
        fabric={fabric}
        sortedTools={sortedTools}
        toolSort={toolSort}
        toolDesc={toolDesc}
        onToolSort={(k) => {
          if (k === toolSort) setToolDesc((d) => !d);
          else {
            setToolSort(k);
            setToolDesc(k !== "tool");
          }
        }}
      />

      <section className="card p-5">
        <SectionHeader
          title="Spam detection: LLM vs heuristic"
          hint="Two independent screens; redundancy catches both LLM blind spots and regex blind spots"
        />
        <SpamSignalsBlock data={fabric.spam_signals} />
      </section>

      <section className="card p-5">
        <SectionHeader
          title="Autonomy funnel by intent"
          hint="How cases for each intent split across L4 / L3 / L2 tiers"
        />
        <AutonomyFunnel data={fabric.autonomy_funnel_by_intent} />
      </section>

      <section className="card p-5">
        <SectionHeader
          title="Case ownership distribution"
          hint="How CCC Requests land across the named queues, resolved at Stage 3.4 from the owner_mapping KB namespace"
        />
        <ByOwnerDoughnut data={summary.by_owner || {}} />
      </section>

      <section className="card p-5">
        <SectionHeader
          title="Translation provider mix"
          hint="Adapters wired into the TranslateTool. Additional providers ship empty until configured"
        />
        <TranslationMix data={fabric.translation_provider_mix} />
      </section>
    </div>
  );
}

function ByOwnerDoughnut({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (total === 0) return <div className="text-sm text-zbrain-muted">No case-ownership data yet.</div>;
  const OWNER_COLORS = ["#1A55F9", "#1F8A4C", "#7A3CC1", "#C97A0B", "#0F8FA9", "#C53030", "#6B7280"];
  return (
    <div className="grid grid-cols-12 gap-4 items-start">
      <div className="col-span-12 md:col-span-5 max-w-[280px]">
        <Doughnut
          data={{
            labels: entries.map(([k]) => k),
            datasets: [
              {
                data: entries.map(([, v]) => v),
                backgroundColor: entries.map((_, i) => OWNER_COLORS[i % OWNER_COLORS.length]),
                borderWidth: 0,
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: true,
            cutout: "60%",
            plugins: {
              legend: { display: false },
              tooltip: { enabled: true },
            },
          }}
        />
      </div>
      <div className="col-span-12 md:col-span-7">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zbrain-muted text-left border-b border-zbrain-divider">
              <th className="py-1.5 pr-2 font-medium">Owner</th>
              <th className="py-1.5 pr-2 font-medium tabular-nums text-right">Cases</th>
              <th className="py-1.5 pr-2 font-medium tabular-nums text-right">Share</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([k, v], i) => (
              <tr key={k} className="border-b border-zbrain-divider/60 last:border-0">
                <td className="py-1.5 pr-2 flex items-center gap-2 text-zbrain-ink">
                  <span className="inline-block w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: OWNER_COLORS[i % OWNER_COLORS.length] }} />
                  {k}
                </td>
                <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink text-right">{v}</td>
                <td className="py-1.5 pr-2 tabular-nums text-zbrain-muted text-right">{((v / total) * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SectionHeader({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="text-xs text-zbrain-muted mt-0.5">{hint}</p>
    </div>
  );
}

function StageTimingChart({ stages }: { stages: AgentFabricStats["stage_timing"] }) {
  const present = STAGE_ORDER.filter((s) => stages[s]);
  const max = Math.max(1, ...present.map((s) => stages[s]?.p95_ms || 0));
  if (present.length === 0)
    return <div className="text-sm text-zbrain-muted">No stage timing yet.</div>;
  return (
    <>
      <div className="space-y-3">
        {present.map((s) => {
          const t = stages[s];
          if (!t) return null;
          return (
            <div key={s}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-zbrain-ink font-medium">{STAGE_LABELS[s] || s}</span>
                <span className="tabular-nums text-zbrain-muted">
                  P50 {t.p50_ms} ms · P95 {t.p95_ms} ms · n={t.count}
                </span>
              </div>
              <div className="relative h-3 bg-slate-100 rounded">
                <div
                  className="absolute left-0 top-0 h-3 bg-zbrain-200 rounded"
                  style={{ width: `${(t.p95_ms / max) * 100}%` }}
                  title={`P95 ${t.p95_ms} ms`}
                />
                <div
                  className="absolute left-0 top-0 h-3 bg-zbrain rounded"
                  style={{ width: `${(t.p50_ms / max) * 100}%` }}
                  title={`P50 ${t.p50_ms} ms`}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-5 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zbrain-muted text-left border-b border-zbrain-divider">
              <th className="py-1.5 pr-2 font-medium">Stage</th>
              <th className="py-1.5 pr-2 font-medium tabular-nums">Count</th>
              <th className="py-1.5 pr-2 font-medium tabular-nums">P50 ms</th>
              <th className="py-1.5 pr-2 font-medium tabular-nums">P95 ms</th>
            </tr>
          </thead>
          <tbody>
            {present.map((s) => {
              const t = stages[s];
              if (!t) return null;
              return (
                <tr key={s} className="border-b border-zbrain-divider/60 last:border-0">
                  <td className="py-1.5 pr-2 text-zbrain-ink">{STAGE_LABELS[s] || s}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink">{t.count}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink">{t.p50_ms}</td>
                  <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink">{t.p95_ms}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function compareTools(
  a: ToolInvocationStat,
  b: ToolInvocationStat,
  key: ToolSortKey,
  desc: boolean
): number {
  let av: number | string;
  let bv: number | string;
  if (key === "tool") {
    av = a.tool;
    bv = b.tool;
  } else if (key === "ok_rate") {
    av = a.count ? a.ok_count / a.count : 0;
    bv = b.count ? b.ok_count / b.count : 0;
  } else {
    av = a[key];
    bv = b[key];
  }
  if (av === bv) return 0;
  const cmp = av > bv ? 1 : -1;
  return desc ? -cmp : cmp;
}

// Plain-English dictionary for the most-fired tool names. Keys are the
// tool identifiers the orchestrator emits; values are the human label and a
// one-sentence description shown under the row. Unknown tools fall back to
// the snake-cased identifier.
const TOOL_DICT: Record<string, { label: string; hint: string }> = {
  detect_spam:              { label: "Spam detector (heuristic)",  hint: "Sub-step 1.2: matches the inbound email against the regex / keyword rules in spam_heuristic." },
  detect_language:          { label: "Language detector",          hint: "Sub-step 1.4: picks the customer language from script, diacritics, and keyword density." },
  llm_spam_check:           { label: "LLM spam classifier",        hint: "Sub-step 1.3: second-pass spam check using the LLM when the heuristic is inconclusive." },
  classify_intent:          { label: "Intent classifier",          hint: "Sub-step 1.7: picks the primary intent (PO intake, quote-to-order, etc.) from the email body and attachments." },
  override_pass:            { label: "CSR-override detector",      hint: "Catches CSR-typed force-HITL / do-not-auto / route-to-team instructions inside the email body." },
  detect_csr_override:      { label: "CSR-override pre-check",     hint: "Fast deterministic scan for CSR override phrases before the LLM runs." },
  shadow_classifier:        { label: "Shadow classifier",          hint: "Third-pass classifier whose outputs are observed but never acted on. Powers continuous-learning baselines." },
  schema_extract:           { label: "Document schema extractor",  hint: "Sub-step 2.2: pulls structured fields out of the PO / quote / WO attachments." },
  entity_resolve_customer:  { label: "Customer resolver",          hint: "Sub-step 2.3: matches the email sender + attachments to a Salesforce Account / Contact." },
  salesforce_soql:          { label: "Salesforce query",           hint: "SOQL query against the connected Salesforce org to fetch a record." },
  salesforce_fetch_files:   { label: "Salesforce attachment fetch", hint: "Pulls files (Cal Cert, contract PDFs) from the matched Salesforce record." },
  sharepoint_fetch_doc:     { label: "SharePoint document fetch",  hint: "Pulls files from the configured SharePoint site for the matched case." },
  business_rules_eval:      { label: "Business-rule sandbox",      hint: "Sub-step 3.2: evaluates each business_rules predicate against the case." },
  translate:                { label: "Translator",                 hint: "Sub-step 1.5 / 5.2: translates the customer email to English (inbound) or English reply to customer language (outbound)." },
  translate_to_english:     { label: "Translate to English",       hint: "Inbound translator (sub-step 1.5)." },
  translate_to_customer:    { label: "Translate to customer lang", hint: "Outbound translator (sub-step 5.2)." },
};

function ToolTable({
  rows,
  sortKey,
  desc,
  onSort,
}: {
  rows: ToolInvocationStat[];
  sortKey: ToolSortKey;
  desc: boolean;
  onSort: (k: ToolSortKey) => void;
}) {
  if (rows.length === 0)
    return <div className="text-sm text-zbrain-muted">No tool invocations recorded yet.</div>;
  const arrow = (k: ToolSortKey) => (sortKey === k ? (desc ? " ↓" : " ↑") : "");
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-zbrain-muted text-left border-b border-zbrain-divider">
            <ThSort active={sortKey === "tool"} onClick={() => onSort("tool")}>
              Tool{arrow("tool")}
            </ThSort>
            <ThSort active={sortKey === "count"} onClick={() => onSort("count")} numeric>
              Count{arrow("count")}
            </ThSort>
            <ThSort active={sortKey === "ok_rate"} onClick={() => onSort("ok_rate")} numeric>
              Success{arrow("ok_rate")}
            </ThSort>
            <ThSort active={sortKey === "p50_ms"} onClick={() => onSort("p50_ms")} numeric>
              P50 ms{arrow("p50_ms")}
            </ThSort>
            <ThSort active={sortKey === "p95_ms"} onClick={() => onSort("p95_ms")} numeric>
              P95 ms{arrow("p95_ms")}
            </ThSort>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const rate = r.count ? r.ok_count / r.count : 0;
            const meta = TOOL_DICT[r.tool];
            return (
              <tr key={r.tool} className="border-b border-zbrain-divider/60 last:border-0">
                <td className="py-1.5 pr-2 text-[12px] text-zbrain-ink">
                  <div className="font-medium" title={r.tool}>{meta?.label || r.tool.replace(/_/g, " ")}</div>
                  {meta?.hint && (
                    <div className="text-[10px] text-zbrain-muted leading-snug">{meta.hint}</div>
                  )}
                </td>
                <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink text-right">{r.count}</td>
                <td className="py-1.5 pr-2 text-right">
                  <SuccessPill rate={rate} okCount={r.ok_count} total={r.count} />
                </td>
                <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink text-right">{r.p50_ms}<span className="text-[10px] text-zbrain-muted ml-0.5">ms</span></td>
                <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink text-right">{r.p95_ms}<span className="text-[10px] text-zbrain-muted ml-0.5">ms</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ThSort({
  children,
  onClick,
  active,
  numeric,
}: {
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  numeric?: boolean;
}) {
  return (
    <th
      onClick={onClick}
      className={`py-1.5 pr-2 font-medium cursor-pointer select-none ${
        numeric ? "text-right" : ""
      } ${active ? "text-zbrain" : ""} hover:text-zbrain`}
    >
      {children}
    </th>
  );
}

function SuccessPill({ rate, okCount, total }: { rate: number; okCount: number; total: number }) {
  const tone =
    rate >= 0.99
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : rate >= 0.9
        ? "bg-amber-50 text-amber-700 border-amber-200"
        : "bg-rose-50 text-rose-700 border-rose-200";
  return (
    <span className={`pill border ${tone}`} title={`${okCount}/${total} ok`}>
      {Math.round(rate * 100)}%
    </span>
  );
}

function KbRuleTable({ rows }: { rows: KbRuleFire[] }) {
  if (rows.length === 0)
    return <div className="text-sm text-zbrain-muted">No KB rule fires yet.</div>;
  const max = Math.max(1, ...rows.map((r) => r.fires));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-zbrain-muted text-left border-b border-zbrain-divider">
            <th className="py-1.5 pr-2 font-medium">Rule key</th>
            <th className="py-1.5 pr-2 font-medium">Severity</th>
            <th className="py-1.5 pr-2 font-medium tabular-nums">Fires</th>
            <th className="py-1.5 pr-2 font-medium">Last fired</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.rule_key} className="border-b border-zbrain-divider/60 last:border-0">
              <td className="py-1.5 pr-2 font-mono text-[12px] text-zbrain-ink">{r.rule_key}</td>
              <td className="py-1.5 pr-2">
                <SeverityPill severity={r.severity} />
              </td>
              <td className="py-1.5 pr-2 tabular-nums text-zbrain-ink">
                <div className="flex items-center gap-2">
                  <span className="w-6 text-right">{r.fires}</span>
                  <div className="h-1.5 bg-slate-100 rounded flex-1 min-w-[60px]">
                    <div
                      className="h-1.5 bg-zbrain rounded"
                      style={{ width: `${(r.fires / max) * 100}%` }}
                    />
                  </div>
                </div>
              </td>
              <td className="py-1.5 pr-2 text-zbrain-muted">{relativeTime(r.last_fired_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeverityPill({ severity }: { severity: string }) {
  return <SeverityChip severity={severity} />;
}

function NormalizerSection({ data }: { data: AgentFabricStats["normalizer_corrections"] }) {
  const pct = Math.round((data.correction_rate || 0) * 100);
  return (
    <div>
      <div className="flex items-baseline gap-3">
        <div className="text-3xl font-semibold text-zbrain-ink tabular-nums">{pct}%</div>
        <div className="text-xs text-zbrain-muted">
          {data.corrected} of {data.total_classifications} classifications normalized
        </div>
      </div>
      <div className="mt-4">
        <div className="text-[11px] uppercase tracking-wider text-zbrain-muted mb-2">
          Top LLM drifts caught
        </div>
        {data.top_corrections.length === 0 ? (
          <div className="text-xs text-zbrain-muted">No corrections yet.</div>
        ) : (
          <ul className="space-y-1.5">
            {data.top_corrections.map((c, i) => (
              <li key={i} className="flex items-center justify-between text-xs">
                <span className="font-mono text-zbrain-ink">
                  {c.from} <span className="text-zbrain-muted">→</span> {c.to}
                </span>
                <span className="tabular-nums text-zbrain-muted">×{c.count}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function SpamSignalsBlock({ data }: { data: AgentFabricStats["spam_signals"] }) {
  const total = data.llm_only + data.heuristic_only + data.both + data.neither;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MiniKPI
          label="Agreement rate"
          value={`${Math.round(data.agreement_rate * 100)}%`}
          sub={`${total} cases screened`}
          tone="emerald"
        />
        <MiniKPI label="LLM only" value={data.llm_only} sub="caught by LLM, missed by regex" tone="amber" />
        <MiniKPI
          label="Heuristic only"
          value={data.heuristic_only}
          sub="caught by regex, missed by LLM"
          tone="amber"
        />
        <MiniKPI label="Both fired" value={data.both} sub="confirmed spam" tone="rose" />
      </div>
      <p className="mt-3 text-[11px] text-zbrain-muted">
        Two independent screens run in parallel. Disagreement (LLM-only or heuristic-only) is the early-warning signal.
        A regex catch the LLM missed flags a prompt-tuning gap; an LLM catch the regex missed flags new spam patterns to
        codify.
      </p>
    </>
  );
}

function MiniKPI({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number | string;
  sub?: string;
  tone: "emerald" | "amber" | "rose";
}) {
  const accent =
    tone === "emerald"
      ? "text-emerald-700"
      : tone === "amber"
        ? "text-amber-700"
        : "text-rose-700";
  return (
    <div className="border border-zbrain-divider rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wider text-zbrain-muted">{label}</div>
      <div className={`text-xl font-semibold mt-0.5 ${accent} tabular-nums`}>{value}</div>
      {sub && <div className="text-[11px] text-zbrain-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function AutonomyFunnel({ data }: { data: AgentFabricStats["autonomy_funnel_by_intent"] }) {
  // Compact intent-tile grid. Each tile surfaces the autonomy rate as a KPI
  // and a short stacked-bar; ranked by autonomy rate so the best-performing
  // intents float to the top and outliers are obvious at a glance. Replaces
  // the long-yellow-bar-per-intent layout that wasted horizontal space and
  // overemphasised HITL volume.
  const entries = Object.entries(data)
    .filter(([, b]) => b.total > 0)
    .map(([intent, b]) => {
      const total = Math.max(1, b.total);
      const autonomyPct = ((b.L4_AUTO + b.L3_ONE_CLICK) / total) * 100;
      return { intent, b, total, autonomyPct };
    })
    .sort((a, z) => z.autonomyPct - a.autonomyPct || z.b.total - a.b.total);

  if (entries.length === 0)
    return <div className="text-sm text-zbrain-muted">No cases yet.</div>;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-[11px] text-zbrain-muted">
        <LegendDot color="bg-emerald-500" label="L4 Auto-closed" />
        <LegendDot color="bg-zbrain" label="L3 One-click" />
        <LegendDot color="bg-amber-500" label="L2 Full review" />
        <span className="ml-auto text-[10px] tracking-wide uppercase text-zbrain-muted">
          Sorted by autonomy rate
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2.5">
        {entries.map(({ intent, b, total, autonomyPct }) => {
          const l4 = (b.L4_AUTO / total) * 100;
          const l3 = (b.L3_ONE_CLICK / total) * 100;
          const l2 = (b.L2_HITL / total) * 100;
          const tone =
            autonomyPct >= 75 ? "text-emerald-700 dark:text-emerald-300"
            : autonomyPct >= 50 ? "text-zbrain dark:text-zbrain-dark-accent"
            : "text-amber-700 dark:text-amber-300";
          return (
            <div
              key={intent}
              className="rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 px-3 py-2.5"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink leading-tight truncate">
                  {INTENT_LABELS[intent] || intent}
                </span>
                <span className={`text-[15px] font-bold tabular-nums ${tone}`}>
                  {autonomyPct.toFixed(0)}%
                </span>
              </div>
              <div className="mt-1.5 h-1.5 bg-slate-100 dark:bg-zbrain-dark-elev2 rounded overflow-hidden flex">
                <div className="bg-emerald-500" style={{ width: `${l4}%` }} title={`L4 ${b.L4_AUTO}`} />
                <div className="bg-zbrain" style={{ width: `${l3}%` }} title={`L3 ${b.L3_ONE_CLICK}`} />
                <div className="bg-amber-500" style={{ width: `${l2}%` }} title={`L2 ${b.L2_HITL}`} />
              </div>
              <div className="mt-1.5 flex items-center justify-between text-[10.5px] text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">
                <span>
                  <span className="text-emerald-700 dark:text-emerald-300 font-semibold">{b.L4_AUTO}</span>
                  <span className="opacity-60"> · </span>
                  <span className="text-zbrain dark:text-zbrain-dark-accent font-semibold">{b.L3_ONE_CLICK}</span>
                  <span className="opacity-60"> · </span>
                  <span className="text-amber-700 dark:text-amber-300 font-semibold">{b.L2_HITL}</span>
                </span>
                <span>n={b.total}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function TranslationMix({ data }: { data: Record<string, number> }) {
  const ordered = ["llm", "azure", "deepl", "google"];
  const total = ordered.reduce((acc, k) => acc + (data[k] || 0), 0);
  return (
    <div className="space-y-3">
      {ordered.map((p) => {
        const v = data[p] || 0;
        const pct = total ? (v / total) * 100 : 0;
        return (
          <div key={p}>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-zbrain-ink font-medium">{PROVIDER_LABELS[p] || p}</span>
              <span className="tabular-nums text-zbrain-muted">
                {v} · {total ? `${Math.round(pct)}%` : "0%"}
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded">
              <div className="h-2 bg-zbrain rounded" style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
      {total === 0 && (
        <p className="text-[11px] text-zbrain-muted">
          No translations recorded yet. Sample data is largely English.
        </p>
      )}
    </div>
  );
}

function KPI({
  label,
  value,
  sub,
  highlight,
  onClick,
}: {
  label: string;
  value: number | string;
  sub?: string;
  highlight?: boolean;
  onClick?: () => void;
}) {
  const cls = `card p-4 ${highlight ? "ring-1 ring-amber-300" : ""} ${
    onClick ? "cursor-pointer hover:bg-zbrain-50/40 transition-colors" : ""
  }`;
  const Wrap: any = onClick ? "button" : "div";
  return (
    <Wrap className={`text-left ${cls}`} onClick={onClick}>
      <div className="text-xs uppercase tracking-wider text-zbrain-muted">{label}</div>
      <div className="text-2xl font-semibold text-zbrain-ink mt-1">{value}</div>
      {sub && <div className="text-xs text-zbrain-muted mt-0.5">{sub}</div>}
    </Wrap>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "-";
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  return `${d}d ago`;
}

// === Per-stage entry =========================================================
// Surfaces the new per-stage detail capability at the top of the Analytics page.
// Each card links to /analytics/stage/<key>.
function PerStageEntry() {
  const [stages, setStages] = useState<StageMeta[]>([]);
  useEffect(() => {
    api.analytics.stages().then(setStages).catch(() => setStages([]));
  }, []);

  if (stages.length === 0) return null;

  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-zbrain-ink">Per-stage detail</h2>
          <p className="text-xs text-zbrain-muted mt-0.5">
            Sub-process rollup for any of the six processing stages. Auto / HITL / fail split and latency, computed live from trace events.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
        {stages.map((s) => (
          <Link
            key={s.stage_key}
            to={`/analytics/stage/${s.stage_key}`}
            className="block rounded-lg border border-zbrain-divider bg-white hover:border-zbrain hover:shadow-sm transition px-3 py-2.5"
          >
            <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">Stage {s.id}</div>
            <div className="text-sm font-semibold text-zbrain-ink mt-0.5 leading-tight">{s.label}</div>
            <div className="text-[11px] text-zbrain-muted mt-1 line-clamp-2 leading-snug">{s.tagline}</div>
            <div className="text-[11px] text-zbrain mt-2 font-medium">Open detail →</div>
          </Link>
        ))}
      </div>
    </section>
  );
}

// === Hero panel (Process Flow) ==============================================
// AI infrastructure cost moved out of Analytics into the Orchestrator's
// Models page where it sits alongside the registered models. The functional
// Analytics page now focuses on flow, throughput, and autonomy metrics that
// the SalesOps operator actually consumes.
function AnalyticsHeroPanels() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <ProcessFlowCard />
    </div>
  );
}

function ProcessFlowCard() {
  const [flow, setFlow] = useState<import("../api").ProcessFlowData | null>(null);
  useEffect(() => {
    api.analytics.processFlow({ window_days: 30 }).then(setFlow).catch(() => setFlow(null));
  }, []);
  return (
    <Link to="/analytics/process-flow" className="block card p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">Process map</div>
          <h2 className="text-sm font-semibold text-zbrain-ink mt-0.5">How cases flowed through processing (last 30 days)</h2>
          <p className="text-xs text-zbrain-muted mt-1 max-w-md">
            Sub-process nodes and weighted transitions, computed live from trace events. Click to open the full map.
          </p>
        </div>
        <span className="text-xs font-medium text-zbrain whitespace-nowrap">Open map →</span>
      </div>
      {flow ? (
        <div className="grid grid-cols-3 gap-3 text-sm">
          <HeroStat label="Cases (30d)" value={flow.total_cases.toLocaleString()} />
          <HeroStat label="Sub-processes" value={String(flow.nodes.filter((n) => !n.virtual).length)} />
          <HeroStat label="Transitions" value={String(flow.edges.length)} />
        </div>
      ) : (
        <div className="text-xs text-zbrain-muted">Loading…</div>
      )}
    </Link>
  );
}

// CostPanelCard moved to the Orchestrator (Models page).

function HeroStat({ label, value, accent }: { label: string; value: string; accent?: "ok" }) {
  return (
    <div className="rounded-lg bg-zbrain-surface border border-zbrain-divider px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">{label}</div>
      <div className={`text-lg font-semibold tabular-nums mt-1 ${accent === "ok" ? "text-emerald-700" : "text-zbrain-ink"}`}>{value}</div>
    </div>
  );
}

// Compressed diagnostic block: replaces three full-page sections with one
// card containing summary tiles + collapsible "Show details" panels. The
// previous layout exploded the page; this keeps the same information one
// click away without burying it.
function DiagnosticsSummary({
  fabric,
  sortedTools,
  toolSort,
  toolDesc,
  onToolSort,
}: {
  fabric: AgentFabricStats;
  sortedTools: ToolInvocationStat[];
  toolSort: ToolSortKey;
  toolDesc: boolean;
  onToolSort: (k: ToolSortKey) => void;
}) {
  const [open, setOpen] = useState<null | "stages" | "tools" | "kb" | "norm">(null);
  const stagesPresent = STAGE_ORDER.filter((s) => fabric.stage_timing[s]);
  const toolsCount = fabric.tool_invocations.length;
  const okRate =
    toolsCount > 0
      ? fabric.tool_invocations.reduce((s, r) => s + (r.count ? r.ok_count / r.count : 0), 0) / toolsCount
      : 0;
  const totalKb = fabric.kb_rule_fires.length;
  const firedKb = fabric.kb_rule_fires.filter((r) => (r.fires ?? 0) > 0).length;
  const slowest = stagesPresent
    .slice()
    .sort((a, b) => (fabric.stage_timing[b]?.p95_ms || 0) - (fabric.stage_timing[a]?.p95_ms || 0))[0];
  const slowestMs = slowest ? fabric.stage_timing[slowest]?.p95_ms || 0 : 0;

  return (
    <section className="card p-5">
      <SectionHeader
        title="Pipeline diagnostics"
        hint="Per-stage timing, tool invocations, KB rule fires, and normalizer corrections. Click any tile to expand."
      />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DiagTile
          label="Stages tracked"
          value={stagesPresent.length}
          sub={slowest ? `${STAGE_LABELS[slowest] || slowest} slowest @ ${slowestMs} ms p95` : "no timings yet"}
          active={open === "stages"}
          onClick={() => setOpen(open === "stages" ? null : "stages")}
        />
        <DiagTile
          label="Tool invocations"
          value={toolsCount}
          sub={toolsCount ? `${(okRate * 100).toFixed(1)}% avg success` : "no calls yet"}
          active={open === "tools"}
          onClick={() => setOpen(open === "tools" ? null : "tools")}
        />
        <DiagTile
          label="KB rules"
          value={`${firedKb} / ${totalKb}`}
          sub={totalKb ? "fired / evaluated" : "no rules evaluated"}
          active={open === "kb"}
          onClick={() => setOpen(open === "kb" ? null : "kb")}
        />
        <DiagTile
          label="Normalizer hits"
          value={fabric.normalizer_corrections?.corrected || 0}
          sub={fabric.normalizer_corrections ? `${(fabric.normalizer_corrections.correction_rate * 100).toFixed(1)}% correction rate` : "LLM-output drift caught"}
          active={open === "norm"}
          onClick={() => setOpen(open === "norm" ? null : "norm")}
        />
      </div>
      {open === "stages" && (
        <div className="mt-4">
          <StageTimingChart stages={fabric.stage_timing} />
        </div>
      )}
      {open === "tools" && (
        <div className="mt-4">
          <ToolTable rows={sortedTools} sortKey={toolSort} desc={toolDesc} onSort={onToolSort} />
        </div>
      )}
      {open === "kb" && (
        <div className="mt-4">
          <KbRuleTable rows={fabric.kb_rule_fires} />
        </div>
      )}
      {open === "norm" && (
        <div className="mt-4">
          <NormalizerSection data={fabric.normalizer_corrections} />
        </div>
      )}
    </section>
  );
}

function DiagTile({
  label,
  value,
  sub,
  active,
  onClick,
}: {
  label: string;
  value: number | string;
  sub?: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left rounded-lg border px-3 py-2.5 transition-all hover:shadow-sm ${
        active ? "border-zbrain bg-zbrain-50" : "border-zbrain-divider bg-white"
      }`}
    >
      <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">{label}</div>
      <div className="text-lg font-semibold tabular-nums mt-1 text-zbrain-ink">{value}</div>
      {sub && <div className="text-[11px] text-zbrain-muted mt-1 truncate">{sub}</div>}
      <div className="text-[10px] text-zbrain mt-1.5 font-medium">{active ? "Hide details ↑" : "Show details ↓"}</div>
    </button>
  );
}
