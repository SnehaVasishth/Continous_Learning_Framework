// Per-stage detail page. Mirrors the Console-HTML stage-detail layout but
// renders entirely off /api/analytics/stage/:key. Sub-process rollups are
// driven by the backend taxonomy; this page contains no per-sub-process
// hard-coding.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type StageDetail, type StageMeta } from "../api";
import { decodeFingerprint } from "../components/Chips";
import { learningUrl } from "../lib/governanceUrl";

export function StageDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const stageKey = params.stageKey || "intake";
  const [stages, setStages] = useState<StageMeta[]>([]);
  const [data, setData] = useState<StageDetail | null>(null);
  const [windowDays, setWindowDays] = useState(30);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.analytics.stages().then(setStages).catch(() => setStages([]));
  }, []);

  useEffect(() => {
    setData(null);
    setErr(null);
    api.analytics
      .stageDetail(stageKey, windowDays)
      .then(setData)
      .catch((ex) => setErr(String(ex)));
  }, [stageKey, windowDays]);

  const autoPct = useMemo(() => {
    if (!data) return 0;
    const total = data.totals.auto + data.totals.hitl + data.totals.fail;
    return total > 0 ? (data.totals.auto / total) * 100 : 0;
  }, [data]);

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">
            Per-stage detail
          </div>
          <h1 className="text-[22px] font-semibold tracking-tight text-zbrain-ink mt-1">
            {data ? data.stage_label : "Loading…"}
          </h1>
          {data && (
            <p className="text-sm text-zbrain-muted mt-1 max-w-3xl">{data.tagline}</p>
          )}
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
        </div>
      </header>

      {/* Stage tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {stages.map((s) => (
          <button
            key={s.stage_key}
            onClick={() => navigate(`/analytics/stage/${s.stage_key}`)}
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
              s.stage_key === stageKey
                ? "bg-zbrain text-white border-zbrain shadow-sm"
                : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface"
            }`}
          >
            Stage {s.id} · {s.label}
          </button>
        ))}
      </div>

      {err && (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {err}
        </div>
      )}

      {!data && !err && (
        <div className="card p-10 text-center text-sm text-zbrain-muted">Loading per-stage rollup…</div>
      )}

      {data && (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiTile label="Cases in stage" value={data.totals.pipelines.toLocaleString()} sub="distinct pipelines (window)" />
            <KpiTile label="Automated" value={`${autoPct.toFixed(1)}%`} sub={`${data.totals.auto} L4 auto`} tone="ok" />
            <KpiTile
              label="Eventual HITL"
              value={data.totals.hitl.toLocaleString()}
              sub="L3 one-click + L2 review"
              tone="warn"
              tooltip="Share of pipelines that touched this stage AND ultimately required a human at any later stage. This is a cumulative-tier view, not a per-gate count."
            />
            <KpiTile label="Avg latency" value={fmtMs(data.totals.avg_latency_ms)} sub={`p95 ${fmtMs(data.totals.p95_latency_ms)}`} />
          </div>

          {/* Sub-process grid */}
          <Section title="Sub-processes" subtitle="One row per sub-process. Auto / HITL / Fail split is the parent-pipeline tier for cases that touched this sub-process.">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {data.subprocesses.map((sp) => (
                <SubprocessCard key={sp.key} sp={sp} />
              ))}
            </div>
          </Section>

          {/* Opportunities */}
          {data.opportunities.length > 0 && (
            <Section
              title="Open and active opportunities"
              subtitle="Tuning actions surfaced by the continuous-learning loop. Open the Continuous Learning page to accept, defer, or promote to A/B."
            >
              <div className="space-y-2">
                {data.opportunities.slice(0, 6).map((o) => (
                  <a
                    key={o.id}
                    href={learningUrl({ tab: "tuning" })}
                    className="block card p-3 hover:shadow-md transition-shadow"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">{o.segment}</span>
                      <StatusPill status={o.status} />
                      <span className="pill bg-slate-100 text-slate-700 text-[10px]">Score {o.score.toFixed(1)}</span>
                      <span className="pill bg-slate-100 text-slate-700 text-[10px]">{o.effort} effort</span>
                      <span className="pill bg-slate-100 text-slate-700 text-[10px]">{o.risk} risk</span>
                    </div>
                    <div className="mt-1 text-sm text-zbrain-ink leading-snug">{decodeFingerprint(o.fingerprint)}</div>
                    <div className="text-[10px] text-zbrain-muted font-mono mt-0.5" title="Internal fingerprint used for deduplication">({o.fingerprint})</div>
                    <div className="mt-0.5 text-xs text-zbrain-muted">{o.proposed_remedy}</div>
                  </a>
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  );
}

function fmtMs(ms: number): string {
  if (!ms) return "-";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} m ${Math.round((ms % 60000) / 1000)} s`;
}

function KpiTile({
  label,
  value,
  sub,
  tone = "neutral",
  tooltip,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn" | "neutral";
  tooltip?: string;
}) {
  const accent = tone === "ok" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : "text-zbrain-ink";
  return (
    <div className="card px-5 py-4" title={tooltip}>
      <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold flex items-center gap-1">
        <span>{label}</span>
        {tooltip && (
          <span
            className="w-3 h-3 rounded-full border border-zbrain-muted/60 text-zbrain-muted flex items-center justify-center text-[8px] font-bold leading-none cursor-help"
            aria-label={`About ${label}`}
          >
            i
          </span>
        )}
      </div>
      <div className={`mt-2 text-2xl font-semibold tabular-nums ${accent}`}>{value}</div>
      {sub && <div className="text-xs text-zbrain-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold text-zbrain-ink">{title}</h2>
        {subtitle && <p className="text-xs text-zbrain-muted mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function SubprocessCard({ sp }: { sp: import("../api").SubprocessRollup }) {
  return (
    <div className="card px-4 py-3 space-y-2">
      <div>
        <div className="text-sm font-semibold text-zbrain-ink leading-tight">{sp.label}</div>
        <div className="text-xs text-zbrain-muted mt-1 leading-relaxed">{sp.description}</div>
      </div>
      <div className="flex items-baseline justify-between">
        <div>
          <span className="text-2xl font-semibold tabular-nums text-zbrain-ink">{sp.volume.toLocaleString()}</span>
          <span className="text-xs text-zbrain-muted ml-1">cases</span>
        </div>
        <div className="text-[11px] text-zbrain-muted tabular-nums">{fmtMs(sp.avg_latency_ms)} avg</div>
      </div>
      {/* Stacked auto/HITL/fail bar */}
      <div className="h-2 bg-zbrain-surface rounded overflow-hidden flex">
        <div className="h-full bg-emerald-500" style={{ width: `${sp.auto_pct}%` }} title={`Auto ${sp.auto_pct}%`} />
        <div className="h-full bg-amber-500" style={{ width: `${sp.hitl_pct}%` }} title={`Sub-process HITL ${sp.hitl_pct}%: share of pipelines that fired a HITL gate at this sub-process node.`} />
        <div className="h-full bg-rose-500" style={{ width: `${sp.fail_pct}%` }} title={`Fail ${sp.fail_pct}%`} />
      </div>
      <div className="flex items-center justify-between text-[11px] text-zbrain-muted">
        <span><span className="inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1 align-middle" /><span className="tabular-nums text-emerald-700 font-medium">{sp.auto_pct.toFixed(1)}%</span> auto</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-amber-500 mr-1 align-middle" /><span className="tabular-nums text-amber-700 font-medium">{sp.hitl_pct.toFixed(1)}%</span> HITL</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-rose-500 mr-1 align-middle" /><span className="tabular-nums text-rose-700 font-medium">{sp.fail_pct.toFixed(1)}%</span> fail</span>
      </div>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted/70 pt-1 border-t border-zbrain-divider/60">
        source: {sp.source === "trace_events" ? "live trace events" : sp.source.replaceAll("_", " ")}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "promoted"
      ? "bg-emerald-100 text-emerald-700 border border-emerald-200"
      : status === "in_ab"
      ? "bg-zbrain-50 text-zbrain border border-zbrain/20"
      : status === "accepted"
      ? "bg-sky-50 text-sky-700 border border-sky-200"
      : status === "deferred"
      ? "bg-amber-50 text-amber-700 border border-amber-200"
      : status === "rejected" || status === "retired"
      ? "bg-zinc-100 text-zinc-600"
      : "bg-slate-100 text-slate-700";
  return <span className={`pill text-[10px] uppercase tracking-wide ${tone}`}>{status.replaceAll("_", " ")}</span>;
}
