import { useEffect, useMemo, useState } from "react";

import { api, FeedbackEntry } from "../api";
import { InfoTip } from "../components/InfoTip";
import { BaselineChip } from "../components/BaselineChip";
import { BaselineFilter } from "../components/BaselineFilter";
import { traceUrl } from "../lib/traceUrl";
import { STAGE_DISPLAY } from "../lib/stageNames";

// Canonical stage display names sourced from src/lib/stageNames.ts so the
// FeedbackLog uses the same labels as the SalesOps Dashboard, Continuous
// Learning Overview, and Models inventory.
const STAGE_LABEL: Record<string, string> = STAGE_DISPLAY;

const STAGE_TONE: Record<string, string> = {
  intake: "bg-blue-50 text-blue-700 border-blue-200",
  extract: "bg-emerald-50 text-emerald-700 border-emerald-200",
  reconcile: "bg-amber-50 text-amber-800 border-amber-200",
  decide: "bg-violet-50 text-violet-700 border-violet-200",
  execute: "bg-zbrain-50 text-zbrain border-zbrain-200",
  communicate: "bg-rose-50 text-rose-700 border-rose-200",
  learning: "bg-cyan-50 text-cyan-700 border-cyan-200",
  hitl: "bg-slate-100 text-slate-700 border-zbrain-divider",
  suggest_fix: "bg-amber-50 text-amber-800 border-amber-200",
};

function classifyKind(kind: string): { tone: string; label: string; icon: string } {
  if (kind.endsWith("_up") || kind === "approve") {
    return { tone: "bg-emerald-100 text-emerald-700", label: kind, icon: "👍" };
  }
  if (kind.endsWith("_down") || kind === "reject") {
    return { tone: "bg-rose-100 text-rose-700", label: kind, icon: "👎" };
  }
  if (kind.endsWith("_note")) {
    return { tone: "bg-zbrain-50 text-zbrain", label: kind, icon: "💬" };
  }
  if (kind === "edit_and_approve") {
    return { tone: "bg-amber-100 text-amber-800", label: kind, icon: "✎" };
  }
  return { tone: "bg-slate-100 text-slate-700", label: kind, icon: "•" };
}

export function FeedbackLogPanel({
  onOpenDrill,
}: {
  onOpenDrill?: (id: number) => void;
} = {}) {
  const [rows, setRows] = useState<FeedbackEntry[]>([]);
  const [stage, setStage] = useState<string>("all");
  const [kind, setKind] = useState<string>("all");
  const [groupByPipeline, setGroupByPipeline] = useState<boolean>(true);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [baselineFilter, setBaselineFilter] = useState<number | null>(null);

  const reload = () => api.feedback(baselineFilter ?? undefined).then(setRows);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 4000);
    return () => clearInterval(id);
  }, [baselineFilter]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (stage !== "all" && r.stage !== stage) return false;
      if (kind === "positive" && !(r.kind.endsWith("_up") || r.kind === "approve")) return false;
      if (kind === "negative" && !(r.kind.endsWith("_down") || r.kind === "reject")) return false;
      if (kind === "note" && !r.kind.endsWith("_note")) return false;
      if (kind === "edit" && r.kind !== "edit_and_approve") return false;
      return true;
    });
  }, [rows, stage, kind]);

  const grouped = useMemo(() => {
    const m = new Map<number, FeedbackEntry[]>();
    for (const r of filtered) {
      const arr = m.get(r.pipeline_id) || [];
      arr.push(r);
      m.set(r.pipeline_id, arr);
    }
    return Array.from(m.entries()).sort((a, b) => b[0] - a[0]);
  }, [filtered]);

  const stageCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) c[r.stage] = (c[r.stage] || 0) + 1;
    return c;
  }, [rows]);

  const totals = {
    all: rows.length,
    positive: rows.filter((r) => r.kind.endsWith("_up") || r.kind === "approve").length,
    negative: rows.filter((r) => r.kind.endsWith("_down") || r.kind === "reject").length,
    note: rows.filter((r) => r.kind.endsWith("_note")).length,
    edit: rows.filter((r) => r.kind === "edit_and_approve").length,
  };

  const togglePipeline = (id: number) => {
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold inline-flex items-center gap-1.5">
              Feedback log
              <InfoTip text="Per-stage CSR signals from Trace and HITL outcomes. Feeds tuning and drift detection." />
            </h2>
          </div>
          <div className="flex items-start gap-3 flex-wrap">
            <div className="grid grid-cols-5 gap-2 text-center">
              <KPIPill label="Total" n={totals.all} tone="text-zbrain-ink" />
              <KPIPill label="👍" n={totals.positive} tone="text-emerald-700" />
              <KPIPill label="👎" n={totals.negative} tone="text-rose-700" />
              <KPIPill label="✎" n={totals.edit} tone="text-amber-700" />
              <KPIPill label="💬" n={totals.note} tone="text-zbrain" />
            </div>
            <BaselineFilter value={baselineFilter} onChange={setBaselineFilter} />
            <button onClick={reload} className="btn-secondary text-xs whitespace-nowrap">
              ↻ Refresh
            </button>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2 flex-wrap">
          <span className="text-xs uppercase tracking-wider text-zbrain-muted">Stage:</span>
          <FilterPill active={stage === "all"} onClick={() => setStage("all")} label="All" count={rows.length} />
          {Object.keys(STAGE_LABEL).map((k) => (
            <FilterPill
              key={k}
              active={stage === k}
              onClick={() => setStage(k)}
              label={STAGE_LABEL[k]}
              count={stageCounts[k] || 0}
            />
          ))}
          <span className="ml-3 text-xs uppercase tracking-wider text-zbrain-muted">Kind:</span>
          <FilterPill active={kind === "all"} onClick={() => setKind("all")} label="All" />
          <FilterPill active={kind === "positive"} onClick={() => setKind("positive")} label="👍" />
          <FilterPill active={kind === "negative"} onClick={() => setKind("negative")} label="👎" />
          <FilterPill active={kind === "edit"} onClick={() => setKind("edit")} label="✎ edits" />
          <FilterPill active={kind === "note"} onClick={() => setKind("note")} label="💬 notes" />
          <button
            onClick={() => setGroupByPipeline((v) => !v)}
            className="ml-auto text-xs text-zbrain hover:underline"
          >
            {groupByPipeline ? "show flat list" : "group by activity"}
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="card p-12 text-center text-zbrain-muted text-sm">
          No feedback yet. Open a request in Activity and use the per-stage feedback controls, or resolve a HITL task.
        </div>
      ) : groupByPipeline ? (
        <div className="space-y-3">
          {grouped.map(([pid, items]) => (
            <PipelineGroup
              key={pid}
              pipelineId={pid}
              items={items}
              expanded={open.has(pid) || grouped.length <= 3}
              onToggle={() => togglePipeline(pid)}
              onOpenDrill={onOpenDrill}
            />
          ))}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="divide-y divide-zbrain-divider">
            {filtered.map((f) => (
              <FeedbackRow key={f.id} f={f} showPipeline onOpenDrill={onOpenDrill} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PipelineGroup({
  pipelineId,
  items,
  expanded,
  onToggle,
  onOpenDrill,
}: {
  pipelineId: number;
  items: FeedbackEntry[];
  expanded: boolean;
  onToggle: () => void;
  onOpenDrill?: (id: number) => void;
}) {
  const stageBreakdown: Record<string, number> = {};
  let pos = 0,
    neg = 0,
    note = 0,
    edit = 0;
  for (const f of items) {
    stageBreakdown[f.stage] = (stageBreakdown[f.stage] || 0) + 1;
    if (f.kind.endsWith("_up") || f.kind === "approve") pos += 1;
    else if (f.kind.endsWith("_down") || f.kind === "reject") neg += 1;
    else if (f.kind === "edit_and_approve") edit += 1;
    else if (f.kind.endsWith("_note")) note += 1;
  }
  return (
    <div className="card overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 bg-zbrain-surface hover:bg-zbrain-50/40 flex items-center gap-3 border-b border-zbrain-divider"
      >
        <span className="text-xs text-zbrain-muted">{expanded ? "▾" : "▸"}</span>
        <span className="text-sm font-semibold">Activity #{pipelineId}</span>
        <span className="text-xs text-zbrain-muted">·</span>
        <span className="text-xs text-zbrain-muted">{items.length} signal{items.length === 1 ? "" : "s"}</span>
        <div className="flex items-center gap-1.5 ml-2">
          {pos > 0 && <span className="pill bg-emerald-100 text-emerald-700 text-[10px]">👍 {pos}</span>}
          {neg > 0 && <span className="pill bg-rose-100 text-rose-700 text-[10px]">👎 {neg}</span>}
          {edit > 0 && <span className="pill bg-amber-100 text-amber-800 text-[10px]">✎ {edit}</span>}
          {note > 0 && <span className="pill bg-zbrain-50 text-zbrain text-[10px]">💬 {note}</span>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {Object.entries(stageBreakdown).map(([k, v]) => (
            <span key={k} className={`pill border text-[10px] ${STAGE_TONE[k] || "bg-slate-100 text-slate-700 border-zbrain-divider"}`}>
              {STAGE_LABEL[k] || k} · {v}
            </span>
          ))}
          <a
            href={traceUrl(pipelineId)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-zbrain hover:underline whitespace-nowrap"
          >
            Open Trace ↗
          </a>
        </div>
      </button>
      {expanded && (
        <div className="divide-y divide-zbrain-divider">
          {items.map((f) => (
            <FeedbackRow key={f.id} f={f} onOpenDrill={onOpenDrill} />
          ))}
        </div>
      )}
    </div>
  );
}

function FeedbackRow({
  f,
  showPipeline,
  onOpenDrill,
}: {
  f: FeedbackEntry;
  showPipeline?: boolean;
  onOpenDrill?: (id: number) => void;
}) {
  const k = classifyKind(f.kind);
  // Anchor priority: persisted baseline_id wins. Fall back to derived; if
  // only the derived id is present, the chip marks itself as inferred.
  const persistedId = f.baseline_id ?? null;
  const derivedId = f.derived_baseline_id ?? null;
  const anchorId = persistedId ?? derivedId;
  const isDerivedOnly = persistedId == null && derivedId != null;
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2 text-xs flex-wrap">
        <span className="font-mono text-zbrain-muted whitespace-nowrap">
          {f.created_at ? new Date(f.created_at).toLocaleString() : "-"}
        </span>
        <span
          className={`pill border text-[10px] ${STAGE_TONE[f.stage] || "bg-slate-100 text-slate-700 border-zbrain-divider"}`}
        >
          {STAGE_LABEL[f.stage] || f.stage}
        </span>
        <span className={`pill ${k.tone} text-[10px]`}>
          {k.icon} {k.label}
        </span>
        <BaselineChip
          baselineId={anchorId}
          baselineLabel={f.baseline_label ?? null}
          derivedOnly={isDerivedOnly}
          onClick={onOpenDrill}
        />
        {showPipeline && (
          <a
            href={traceUrl(f.pipeline_id)}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto text-zbrain hover:underline"
          >
            Activity #{f.pipeline_id} ↗
          </a>
        )}
      </div>
      {f.note && <div className="mt-1.5 text-sm text-zbrain-ink">{f.note}</div>}
      {f.data && Object.keys(f.data).length > 0 && (
        <details className="mt-2">
          <summary className="text-[11px] text-zbrain-muted cursor-pointer hover:text-zbrain-ink">
            stage snapshot ({Object.keys(f.data).length} key{Object.keys(f.data).length === 1 ? "" : "s"})
          </summary>
          <pre className="mt-1.5 text-[10px] bg-slate-50 border border-zbrain-divider rounded p-2 max-h-48 overflow-auto whitespace-pre-wrap">
            {JSON.stringify(f.data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function KPIPill({ label, n, tone }: { label: string; n: number; tone: string }) {
  return (
    <div className="bg-zbrain-surface border border-zbrain-divider rounded-md px-2 py-1.5 min-w-[60px]">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">{label}</div>
      <div className={`text-base font-semibold tabular-nums ${tone}`}>{n}</div>
    </div>
  );
}

export function FeedbackPage() {
  return <FeedbackLogPanel />;
}

function FilterPill({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
        active
          ? "bg-zbrain text-white border-zbrain"
          : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-50"
      }`}
    >
      {label}
      {count != null && (
        <span className={`ml-1 text-[10px] ${active ? "text-white/80" : "text-zbrain-muted"}`}>
          {count}
        </span>
      )}
    </button>
  );
}
