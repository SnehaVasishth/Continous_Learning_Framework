// Process map. Renders nodes (sub-processes from the taxonomy) and edges
// (transitions A -> B with case_count + avg_duration_ms) computed live from
// trace_events by /api/analytics/process_flow.
//
// Design target: a Celonis / Signavio class process explorer.
//   - Stage column bands behind the graph for instant orientation
//   - Edge frequency slider strips low-volume noise
//   - "Main path" toggle dims everything outside the dominant flow
//   - Hover an edge / node to highlight only the touched sub-flow
//   - Right rail: KPIs, top variants, bottleneck list
//   - Precise zoom presets (Fit / 50% / 100% / 200%)
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, type Baseline, type ProcessFlowData, type ProcessFlowEdge, type ProcessFlowNode, type StageMeta } from "../api";
import { learningUrl } from "../lib/governanceUrl";

type FlowNode = ProcessFlowNode;
type FlowEdge = ProcessFlowEdge;
type FlowData = ProcessFlowData;

const STAGE_COLOR: Record<string, string> = {
  intake: "#1A55F9",
  extract: "#1F8A4C",
  decide: "#7A3CC1",
  execute: "#C97A0B",
  communicate: "#0F8FA9",
  learning: "#6B7280",
};

const STAGE_BG: Record<string, string> = {
  intake: "rgba(26, 85, 249, 0.05)",
  extract: "rgba(31, 138, 76, 0.05)",
  decide: "rgba(122, 60, 193, 0.05)",
  execute: "rgba(201, 122, 11, 0.05)",
  communicate: "rgba(15, 143, 169, 0.05)",
  learning: "rgba(107, 114, 128, 0.05)",
};

const STAGE_ORDER = ["intake", "extract", "decide", "execute", "communicate", "learning"];

const NODE_W = 232;
const NODE_H = 128;
const VNODE_W = 138;
const VNODE_H = 60;

type Highlight = {
  // ids of nodes/edges that should be highlighted (others dimmed). null = no
  // highlight active.
  nodes: Set<string>;
  edges: Set<string>;
} | null;

// Highlight is delivered to node renderers via context so the rfNodes array
// keeps a stable identity across hovers. This prevents React Flow from
// treating every pointer movement as a "node changed" event, which was the
// root cause of the hover jitter / shake.
const HighlightCtx = createContext<Highlight>(null);

type LayoutResult = {
  rfNodes: Node[];
  rfEdges: Edge[];
  bounds: { xMin: number; xMax: number; yMin: number; yMax: number };
  stageColumns: { stage: string; xMin: number; xMax: number; label: string }[];
};

function computeMainPath(data: FlowData): { nodeIds: Set<string>; edgeIds: Set<string> } {
  // Greedy: from __START__, follow the highest-volume outgoing edge until __END__ or a cycle.
  const byPrefix: Record<string, FlowEdge[]> = {};
  data.edges.forEach((e) => {
    if (!byPrefix[e.source]) byPrefix[e.source] = [];
    byPrefix[e.source].push(e);
  });
  Object.values(byPrefix).forEach((es) => es.sort((a, b) => b.case_count - a.case_count));

  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  let cur: string | undefined = "__START__";
  for (let i = 0; cur && i < 24; i++) {
    nodeIds.add(cur);
    const next: FlowEdge | undefined = (byPrefix[cur] || []).find((e) => !nodeIds.has(e.target));
    if (!next) break;
    edgeIds.add(`${next.source}->${next.target}`);
    nodeIds.add(next.target);
    cur = next.target;
    if (cur === "__END__") break;
  }
  return { nodeIds, edgeIds };
}

function layout(nodes: FlowNode[], edges: FlowEdge[], stageLabels: Record<string, string>): LayoutResult {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 64, ranksep: 150, marginx: 56, marginy: 56, ranker: "tight-tree" });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, {
    width:  n.virtual ? VNODE_W : NODE_W,
    height: n.virtual ? VNODE_H : NODE_H,
  }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  // Collect bounds + per-stage horizontal column ranges so we can render
  // soft swim bands behind the graph.
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  const stageRange: Record<string, { xMin: number; xMax: number }> = {};
  const positioned: Node[] = nodes.map((n) => {
    const p = g.node(n.id);
    const x = p.x - p.width / 2;
    const y = p.y - p.height / 2;
    xMin = Math.min(xMin, x);
    yMin = Math.min(yMin, y);
    xMax = Math.max(xMax, x + p.width);
    yMax = Math.max(yMax, y + p.height);
    if (!n.virtual && n.stage) {
      const sr = stageRange[n.stage] || { xMin: Infinity, xMax: -Infinity };
      sr.xMin = Math.min(sr.xMin, x);
      sr.xMax = Math.max(sr.xMax, x + p.width);
      stageRange[n.stage] = sr;
    }
    return {
      id: n.id,
      type: n.virtual ? "virtual" : "subprocess",
      position: { x, y },
      data: n,
    } as Node;
  });

  const maxCases = Math.max(1, ...edges.map((e) => e.case_count));
  const rfEdges: Edge[] = edges.map((e) => {
    const intensity = e.case_count / maxCases;
    const stroke = intensity >= 0.6
      ? "#1A55F9"
      : intensity >= 0.3
      ? "#3B82F6"
      : intensity >= 0.1
      ? "#64748B"
      : "#9CA3AF";
    return {
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      type: "smoothstep",
      label: intensity >= 0.15 ? `${e.case_count}${e.avg_duration_ms > 0 ? ` · ${formatDuration(e.avg_duration_ms)}` : ""}` : "",
      data: { case_count: e.case_count, avg_duration_ms: e.avg_duration_ms, intensity },
      style: {
        strokeWidth: Math.max(1.2, intensity * 7),
        stroke,
        opacity: intensity < 0.05 ? 0.45 : 0.95,
      },
      labelStyle: { fontSize: 10.5, fontWeight: 600, fill: "#0F172A" },
      labelBgStyle: { fill: "#FFFFFF", fillOpacity: 0.95 },
      labelBgPadding: [4, 3],
      labelBgBorderRadius: 4,
      markerEnd: { type: "arrowclosed" as any, color: stroke, width: 14, height: 14 },
    } as Edge;
  });

  // Reorder stage columns by the canonical pipeline order so swim bands read
  // left-to-right correctly even if the dataset is sparse.
  const stageColumns = STAGE_ORDER
    .filter((s) => stageRange[s])
    .map((s) => ({
      stage: s,
      xMin: stageRange[s]!.xMin - 20,
      xMax: stageRange[s]!.xMax + 20,
      label: stageLabels[s] || s,
    }));

  return {
    rfNodes: positioned,
    rfEdges,
    bounds: {
      xMin: xMin - 80,
      xMax: xMax + 80,
      yMin: yMin - 60,
      yMax: yMax + 40,
    },
    stageColumns,
  };
}

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  return `${(m / 60).toFixed(1)}h`;
}

// ─── Node renderers ──────────────────────────────────────────────────────

function SubprocessNode({ id, data }: NodeProps) {
  const n = data as unknown as FlowNode;
  const stageBar = n.stage ? STAGE_COLOR[n.stage] : "#9CA3AF";
  const isBottleneck = n.hitl_pct >= 40 || n.fail_pct >= 5;
  const hl = useContext(HighlightCtx);
  const dim = hl && hl.nodes.size > 0 && !hl.nodes.has(id);
  return (
    <div
      style={{
        background: "white",
        borderRadius: 12,
        border: isBottleneck ? "1px solid #F59E0B" : "1px solid #E5E7EB",
        boxShadow: isBottleneck
          ? "0 1px 2px rgba(15,23,42,0.04), 0 8px 22px rgba(245, 158, 11, 0.18)"
          : "0 1px 2px rgba(15,23,42,0.04), 0 8px 22px rgba(15,23,42,0.06)",
        width: NODE_W,
        height: NODE_H,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        opacity: dim ? 0.18 : 1,
        transition: "opacity 140ms ease",
        willChange: "opacity",
      }}
      title={`${n.label}\n${n.volume.toLocaleString()} cases\nAuto ${n.auto_pct.toFixed(0)}% · Sub-process HITL ${n.hitl_pct.toFixed(0)}% · Fail ${n.fail_pct.toFixed(0)}%\n\nSub-process HITL = share of pipelines that fired a HITL gate at this specific sub-process node.${isBottleneck ? "\n\nBottleneck candidate (Sub-process HITL ≥ 40% or Fail ≥ 5%)" : ""}`}
    >
      <Handle type="target" position={Position.Left} style={{ background: stageBar, width: 9, height: 9, border: "2px solid white" }} />
      <div style={{ height: 4, background: stageBar }} />
      <div style={{ padding: "10px 12px", flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
          <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: stageBar, fontWeight: 700 }}>
            {n.stage || "-"}
          </span>
          {isBottleneck && (
            <span style={{ fontSize: 9, fontWeight: 700, color: "#92400E", background: "#FEF3C7", padding: "1px 6px", borderRadius: 999, letterSpacing: "0.04em" }}>
              ⚠ BOTTLENECK
            </span>
          )}
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "#0F172A", lineHeight: 1.25, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {n.label}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: "auto" }}>
          <span style={{ fontSize: 19, color: "#0F172A", fontWeight: 700, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
            {n.volume.toLocaleString()}
          </span>
          <span style={{ fontSize: 10, color: "#64748B", fontWeight: 500 }}>cases</span>
        </div>
        <div style={{ display: "flex", height: 5, background: "#F1F5F9", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ width: `${n.auto_pct}%`, background: "#10B981" }} />
          <div style={{ width: `${n.hitl_pct}%`, background: "#F59E0B" }} />
          <div style={{ width: `${n.fail_pct}%`, background: "#EF4444" }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
          <span style={{ color: "#10B981" }}>{n.auto_pct.toFixed(0)}%</span>
          <span style={{ color: "#F59E0B" }}>{n.hitl_pct.toFixed(0)}%</span>
          <span style={{ color: "#EF4444" }}>{n.fail_pct.toFixed(0)}%</span>
        </div>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: stageBar, width: 9, height: 9, border: "2px solid white" }} />
    </div>
  );
}

function VirtualNode({ id, data }: NodeProps) {
  const n = data as unknown as FlowNode;
  const isStart = n.id === "__START__";
  const hl = useContext(HighlightCtx);
  const dim = hl && hl.nodes.size > 0 && !hl.nodes.has(id);
  return (
    <div
      style={{
        background: isStart ? "#0F172A" : "#1F2937",
        color: "white",
        borderRadius: 999,
        padding: "9px 18px",
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        boxShadow: "0 4px 12px rgba(15,23,42,0.22)",
        whiteSpace: "nowrap",
        opacity: dim ? 0.18 : 1,
        transition: "opacity 140ms ease",
        willChange: "opacity",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "#0F172A", width: 9, height: 9, border: "2px solid white" }} />
      <span>{n.label}</span>
      {n.volume ? (
        <span style={{ fontWeight: 500, opacity: 0.78, textTransform: "none", letterSpacing: 0 }}>
          {n.volume.toLocaleString()} cases
        </span>
      ) : null}
      <Handle type="source" position={Position.Right} style={{ background: "#0F172A", width: 9, height: 9, border: "2px solid white" }} />
    </div>
  );
}

const NODE_TYPES = { subprocess: SubprocessNode, virtual: VirtualNode };

// ─── Page ────────────────────────────────────────────────────────────────

export function ProcessFlowPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const stageKey = searchParams.get("stage") || "";
  const [windowDays, setWindowDays] = useState<number>(30);
  const [stages, setStages] = useState<StageMeta[]>([]);
  const [data, setData] = useState<FlowData | null>(null);
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Explorer controls
  const [minPct, setMinPct] = useState<number>(0); // 0..100 of max edge volume
  const [mainPathOnly, setMainPathOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [highlight, setHighlight] = useState<Highlight>(null);

  useEffect(() => {
    api.analytics.stages().then(setStages).catch(() => setStages([]));
    // Pull the Continuous Learning baselines so every bottleneck signal on
    // this map can surface its anchoring Baseline Quality Target. The fetch
    // is best-effort: when the endpoint is unavailable the badge simply
    // does not render and the rest of the page is unaffected.
    api.learningBaselines()
      .then((r) => setBaselines(r.items || []))
      .catch(() => setBaselines([]));
  }, []);

  useEffect(() => {
    setData(null);
    setErr(null);
    api.analytics
      .processFlow({ window_days: windowDays, stage: stageKey || undefined })
      .then(setData)
      .catch((ex) => setErr(String(ex)));
  }, [stageKey, windowDays]);

  const stageLabels = useMemo(() => {
    const m: Record<string, string> = {};
    stages.forEach((s) => { m[s.stage_key] = s.label; });
    return m;
  }, [stages]);

  // Apply the frequency slider + main-path filter BEFORE laying out.
  const filtered = useMemo(() => {
    if (!data) return null;
    const maxC = Math.max(1, ...data.edges.map((e) => e.case_count));
    const cut = (minPct / 100) * maxC;
    let keepEdges = data.edges.filter((e) => e.case_count >= cut);

    let mainPath: { nodeIds: Set<string>; edgeIds: Set<string> } | null = null;
    if (mainPathOnly) {
      mainPath = computeMainPath(data);
      keepEdges = keepEdges.filter((e) => mainPath!.edgeIds.has(`${e.source}->${e.target}`));
    }

    const reachable = new Set<string>(["__START__", "__END__"]);
    keepEdges.forEach((e) => { reachable.add(e.source); reachable.add(e.target); });
    const keepNodes = data.nodes.filter((n) => reachable.has(n.id) || !n.virtual && !mainPathOnly);
    const finalNodes = mainPathOnly
      ? data.nodes.filter((n) => mainPath!.nodeIds.has(n.id))
      : keepNodes;

    return { nodes: finalNodes, edges: keepEdges, total_cases: data.total_cases, min_edge_cases: data.min_edge_cases };
  }, [data, minPct, mainPathOnly]);

  const layouted = useMemo(
    () => (filtered ? layout(filtered.nodes, filtered.edges, stageLabels) : null),
    [filtered, stageLabels],
  );

  // Highlight derivation from search
  useEffect(() => {
    if (!search.trim() || !filtered) { setHighlight(null); return; }
    const q = search.trim().toLowerCase();
    const matchNodeIds = new Set<string>();
    filtered.nodes.forEach((n) => {
      if (!n.virtual && n.label.toLowerCase().includes(q)) matchNodeIds.add(n.id);
    });
    if (matchNodeIds.size === 0) { setHighlight({ nodes: new Set(), edges: new Set() }); return; }
    const edgeIds = new Set<string>();
    filtered.edges.forEach((e) => {
      if (matchNodeIds.has(e.source) || matchNodeIds.has(e.target)) {
        edgeIds.add(`${e.source}->${e.target}`);
      }
    });
    // Include neighbours so the path context shows
    const expanded = new Set<string>(matchNodeIds);
    filtered.edges.forEach((e) => {
      if (matchNodeIds.has(e.source)) expanded.add(e.target);
      if (matchNodeIds.has(e.target)) expanded.add(e.source);
    });
    setHighlight({ nodes: expanded, edges: edgeIds });
  }, [search, filtered]);

  const setStage = (k: string) => {
    const p = new URLSearchParams(searchParams);
    if (k) p.set("stage", k);
    else p.delete("stage");
    setSearchParams(p, { replace: true });
  };

  // The rfNodes / rfEdges arrays returned by `layout()` are STABLE across
  // hovers. Dimming is applied by:
  //   - Node renderers reading HighlightCtx and setting their own opacity
  //   - Edges getting a CSS className (".rf-edge-dim") which is toggled by
  //     adding a class to the wrapping container, not by mutating each Edge
  //
  // Mutating per-render was the source of the hover jitter; this keeps React
  // Flow's diff happy and the layout stationary.

  // KPI summary for the right rail.
  const kpis = useMemo(() => {
    if (!filtered) return null;
    const real = filtered.nodes.filter((n) => !n.virtual);
    const totalEdgeWeight = filtered.edges.reduce((s, e) => s + e.case_count, 0);
    const avgDurationMs = filtered.edges.length
      ? filtered.edges.reduce((s, e) => s + (e.avg_duration_ms * e.case_count), 0) / Math.max(1, totalEdgeWeight)
      : 0;
    const bottlenecks = real.filter((n) => n.hitl_pct >= 40 || n.fail_pct >= 5);
    const heaviest = real.slice().sort((a, b) => b.volume - a.volume)[0];
    return {
      cases: filtered.total_cases,
      nodes: real.length,
      edges: filtered.edges.length,
      avgDurationMs,
      bottlenecks,
      heaviest,
    };
  }, [filtered]);

  return (
    <div className="space-y-3">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">
            Analytics · End-to-end case flow
          </div>
          <h1 className="text-[22px] font-semibold tracking-tight text-zbrain-ink mt-1">
            Process map
          </h1>
          <p className="text-sm text-zbrain-muted mt-1 max-w-3xl">
            Nodes are sub-processes; edges are real transitions weighted by case count. Use the slider to strip low-volume edges, toggle main-path to see only the dominant flow, or search to focus on a sub-process and its neighbours.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setStage("")}
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
              !stageKey ? "bg-zbrain text-white border-zbrain shadow-sm" : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface"
            }`}
          >
            Whole pipeline
          </button>
          {stages.map((s) => (
            <button
              key={s.stage_key}
              onClick={() => setStage(s.stage_key)}
              className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
                stageKey === s.stage_key ? "bg-zbrain text-white border-zbrain shadow-sm" : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface"
              }`}
            >
              {s.label}
            </button>
          ))}
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className="text-xs border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
          >
            <option value={7}>7d</option>
            <option value={14}>14d</option>
            <option value={30}>30d</option>
            <option value={90}>90d</option>
          </select>
        </div>
      </header>

      {err && (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{err}</div>
      )}

      {/* Explorer toolbar */}
      <div className="card p-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px]">
        <div className="flex items-center gap-2 min-w-[260px]">
          <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold whitespace-nowrap">Edge frequency</span>
          <input
            type="range"
            min={0}
            max={80}
            step={1}
            value={minPct}
            onChange={(e) => setMinPct(Number(e.target.value))}
            className="flex-1 accent-zbrain"
          />
          <span className="text-zbrain-ink tabular-nums w-9 text-right">{minPct}%</span>
        </div>

        <button
          onClick={() => setMainPathOnly((v) => !v)}
          className={`text-[12px] px-2.5 py-1 rounded-md border transition-colors ${
            mainPathOnly
              ? "bg-zbrain text-white border-zbrain"
              : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface"
          }`}
          title="Show only the highest-volume path from start to end"
        >
          {mainPathOnly ? "Showing main path" : "Show main path only"}
        </button>

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Search</span>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find a sub-process…"
            className="text-[12.5px] h-8 px-2.5 w-56 rounded-md border border-zbrain-divider bg-white focus:outline-none focus:ring-2 focus:ring-zbrain/30"
          />
          {search && (
            <button onClick={() => setSearch("")} className="text-[11px] text-zbrain-muted hover:text-zbrain-ink underline">
              clear
            </button>
          )}
        </div>

        <div className="ml-auto flex items-center gap-4 text-[11px]">
          <span className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Node tier</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-emerald-500 rounded" />Auto</span>
            <span
              className="flex items-center gap-1 cursor-help"
              title="Sub-process HITL: share of pipelines that fired a HITL gate at this specific sub-process node."
            ><span className="inline-block w-2 h-2 bg-amber-500 rounded" />Sub-process HITL</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 bg-rose-500 rounded" />Fail</span>
          </span>
          <span className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Edge flow</span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-[2px] w-4 bg-slate-400 rounded" />
              <span>low</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-[3px] w-5 bg-slate-500 rounded" />
              <span>mid</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-[4px] w-6 bg-zbrain rounded" />
              <span>high</span>
            </span>
          </span>
        </div>
      </div>

      {/* Canvas + side rail */}
      <div className="grid grid-cols-12 gap-3">
        <div
          className="col-span-12 lg:col-span-9 card p-0 overflow-hidden bg-gradient-to-b from-white to-slate-50/60"
          style={{ height: "clamp(680px, 80vh, 1000px)" }}
        >
          {!data && !err && (
            <div className="h-full flex items-center justify-center text-sm text-zbrain-muted">Loading process map…</div>
          )}
          {layouted && (
            <HighlightCtx.Provider value={highlight}>
              <ReactFlowProvider>
                <FlowCanvas
                  layout={layouted}
                  highlight={highlight}
                  onClearHighlight={() => { setSearch(""); setHighlight(null); }}
                  onEdgeHover={(id) => {
                    if (!id) { if (!search) setHighlight(null); return; }
                    const e = layouted.rfEdges.find((x) => x.id === id);
                    if (!e) return;
                    setHighlight({ nodes: new Set([e.source, e.target]), edges: new Set([id]) });
                  }}
                  onNodeHover={(id) => {
                    if (!id) { if (!search) setHighlight(null); return; }
                    const touching = layouted.rfEdges.filter((e) => e.source === id || e.target === id);
                    const nodes = new Set<string>([id]);
                    touching.forEach((e) => { nodes.add(e.source); nodes.add(e.target); });
                    setHighlight({ nodes, edges: new Set(touching.map((e) => e.id)) });
                  }}
                  onNodeClick={(node) => {
                    const nd = node.data as unknown as FlowNode;
                    if (nd.virtual) return;
                    navigate(`/trace?stage=${encodeURIComponent(nd.stage || "")}`);
                  }}
                  stageLabels={stageLabels}
                />
              </ReactFlowProvider>
            </HighlightCtx.Provider>
          )}
        </div>

        {/* Right rail */}
        <div className="col-span-12 lg:col-span-3 space-y-3">
          <KpiCard kpis={kpis} />
          {filtered && <VariantsCard data={filtered} stageLabels={stageLabels} onPick={(seq) => {
            setHighlight({
              nodes: new Set(seq),
              edges: new Set(
                seq.slice(0, -1).map((id, i) => `${id}->${seq[i + 1]}`)
              ),
            });
          }} />}
          {kpis?.bottlenecks && kpis.bottlenecks.length > 0 && (
            <BottlenecksCard
              bottlenecks={kpis.bottlenecks}
              baselines={baselines}
              onPick={(id) => {
                if (!layouted) return;
                const touching = layouted.rfEdges.filter((e) => e.source === id || e.target === id);
                const nodes = new Set<string>([id]);
                touching.forEach((e) => { nodes.add(e.source); nodes.add(e.target); });
                setHighlight({ nodes, edges: new Set(touching.map((e) => e.id)) });
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Canvas (uses ReactFlow hooks) ───────────────────────────────────────

function FlowCanvas({
  layout,
  highlight,
  onClearHighlight,
  onEdgeHover,
  onNodeHover,
  onNodeClick,
  stageLabels,
}: {
  layout: LayoutResult;
  highlight: Highlight;
  onClearHighlight: () => void;
  onEdgeHover: (id: string | null) => void;
  onNodeHover: (id: string | null) => void;
  onNodeClick: (node: Node) => void;
  stageLabels: Record<string, string>;
}) {
  const { zoomTo, fitView } = useReactFlow();
  const [zoom, setZoom] = useState<number>(1);

  const zoomPresetClass = (val: number) =>
    Math.abs(zoom - val) < 0.05
      ? "bg-zbrain text-white border-zbrain"
      : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface";

  // Edge dimming is applied with a CSS class on the wrapping div so the
  // edge objects themselves stay referentially stable. Pure CSS, zero
  // ReactFlow diff churn. We rebuild the edges array only when the active
  // set genuinely changes — not on every pointer event in between.
  const hlOn = !!highlight && highlight.nodes.size > 0;
  const hlEdgeIds = highlight?.edges;
  const hlSig = hlEdgeIds ? Array.from(hlEdgeIds).sort().join("|") : "";
  const taggedEdges = useMemo(
    () => layout.rfEdges.map((e) => ({
      ...e,
      className: hlEdgeIds && hlEdgeIds.has(e.id) ? "rf-edge-on" : undefined,
    })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layout.rfEdges, hlSig],
  );

  return (
    <div
      className={`relative w-full h-full rf-hl-${hlOn ? "on" : "off"}`}
      data-active-edges={hlEdgeIds ? Array.from(hlEdgeIds).join("|") : ""}
    >
      <style>{`
        .rf-hl-on .react-flow__edge { opacity: 0.12; transition: opacity 140ms ease; }
        .rf-hl-on .react-flow__edge.rf-edge-on { opacity: 1; }
        .rf-hl-off .react-flow__edge { opacity: 1; transition: opacity 140ms ease; }
      `}</style>
      {/* Stage band overlay — painted in the same coordinate space as the canvas
          via a fixed-position absolute container that we transform with the
          ReactFlow viewport. ReactFlow doesn't expose a clean background
          renderer for arbitrary HTML, so we layer this on top of <Background /> using a CSS hook. */}
      <ReactFlow
        nodes={layout.rfNodes}
        edges={taggedEdges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.18, includeHiddenNodes: false }}
        minZoom={0.2}
        maxZoom={2.5}
        defaultEdgeOptions={{ type: "smoothstep" }}
        proOptions={{ hideAttribution: true }}
        onMove={(_, viewport) => setZoom(viewport.zoom)}
        onEdgeMouseEnter={(_, edge) => onEdgeHover(edge.id)}
        onEdgeMouseLeave={() => onEdgeHover(null)}
        onNodeMouseEnter={(_, node) => onNodeHover(node.id)}
        onNodeMouseLeave={() => onNodeHover(null)}
        onPaneClick={() => onClearHighlight()}
        onNodeClick={(_, n) => onNodeClick(n)}
      >
        {/* Stage band markers — drawn as a SVG layer scaled in graph space.
            React Flow handles transform for us when we attach to its
            internal viewport via the absolute-positioned MiniMap layer. We
            instead emit a simple coloured strip header at the top of the
            canvas with stage labels, which sticks regardless of pan/zoom. */}
        <Background gap={32} size={1.1} color="#E2E8F0" />
        <StageBands stageColumns={layout.stageColumns} stageLabels={stageLabels} />
        <Controls position="bottom-right" showInteractive={false} />
        <MiniMap
          position="top-right"
          zoomable
          pannable
          nodeStrokeWidth={2}
          nodeColor={(node) => {
            const d = node.data as unknown as FlowNode;
            if (!d) return "#cbd5e1";
            if (d.virtual) return "#0F172A";
            return d.stage ? STAGE_COLOR[d.stage] ?? "#94a3b8" : "#94a3b8";
          }}
          maskColor="rgba(15,23,42,0.04)"
          style={{ background: "white", border: "1px solid #E5E7EB", borderRadius: 8, boxShadow: "0 4px 14px rgba(15,23,42,0.06)" }}
        />
      </ReactFlow>

      {/* Zoom presets toolbar (overlay) */}
      <div className="absolute top-3 left-3 flex items-center gap-1.5 z-10 bg-white/95 backdrop-blur px-1.5 py-1 rounded-lg border border-zbrain-divider shadow-sm">
        <button onClick={() => fitView({ padding: 0.18, duration: 220 })}
          className="text-[11px] px-2 h-7 rounded-md border bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-surface"
          title="Fit to view">Fit</button>
        <button onClick={() => zoomTo(0.5, { duration: 220 })}
          className={`text-[11px] px-2 h-7 rounded-md border ${zoomPresetClass(0.5)}`}
          title="Zoom to 50%">50%</button>
        <button onClick={() => zoomTo(1, { duration: 220 })}
          className={`text-[11px] px-2 h-7 rounded-md border ${zoomPresetClass(1)}`}
          title="Zoom to 100%">100%</button>
        <button onClick={() => zoomTo(2, { duration: 220 })}
          className={`text-[11px] px-2 h-7 rounded-md border ${zoomPresetClass(2)}`}
          title="Zoom to 200%">200%</button>
        <span className="text-[10.5px] text-zbrain-muted tabular-nums px-1 border-l border-zbrain-divider ml-0.5 pl-2">
          {Math.round(zoom * 100)}%
        </span>
      </div>
    </div>
  );
}

// Renders soft stage swim bands behind the graph. The columns sit in graph
// coordinates so they pan/zoom with the canvas. We piggy-back on React Flow's
// viewport via the <foreignObject> trick: render an absolutely-positioned
// SVG inside the canvas surface and let React Flow's transform handle pan/zoom.
function StageBands({ stageColumns, stageLabels }: { stageColumns: LayoutResult["stageColumns"]; stageLabels: Record<string, string> }) {
  return (
    <>
      {stageColumns.map((c) => (
        <div
          key={c.stage}
          style={{
            position: "absolute",
            left: c.xMin,
            top: 0,
            width: c.xMax - c.xMin,
            bottom: 0,
            background: STAGE_BG[c.stage] || "rgba(0,0,0,0.02)",
            borderLeft: `1px dashed ${STAGE_COLOR[c.stage] || "#cbd5e1"}33`,
            borderRight: `1px dashed ${STAGE_COLOR[c.stage] || "#cbd5e1"}33`,
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              position: "sticky",
              top: 8,
              display: "inline-block",
              marginLeft: 12,
              padding: "3px 10px",
              background: "white",
              border: `1px solid ${STAGE_COLOR[c.stage] || "#cbd5e1"}55`,
              borderLeft: `3px solid ${STAGE_COLOR[c.stage] || "#cbd5e1"}`,
              borderRadius: 6,
              fontSize: 10.5,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              color: STAGE_COLOR[c.stage] || "#0F172A",
              boxShadow: "0 1px 3px rgba(15,23,42,0.04)",
            }}
          >
            {stageLabels[c.stage] || c.stage}
          </div>
        </div>
      ))}
    </>
  );
}

// ─── Side rail cards ─────────────────────────────────────────────────────

function KpiCard({ kpis }: { kpis: { cases: number; nodes: number; edges: number; avgDurationMs: number; heaviest: FlowNode | undefined; bottlenecks: FlowNode[] } | null }) {
  return (
    <section className="card p-4">
      <h2 className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">KPIs</h2>
      <div className="grid grid-cols-2 gap-3 mt-2">
        <KpiCell label="Cases" value={kpis ? kpis.cases.toLocaleString() : "-"} />
        <KpiCell label="Sub-processes" value={kpis ? String(kpis.nodes) : "-"} />
        <KpiCell label="Transitions" value={kpis ? String(kpis.edges) : "-"} />
        <KpiCell label="Avg transit" value={kpis && kpis.avgDurationMs > 0 ? formatDuration(kpis.avgDurationMs) : "-"} />
      </div>
      {kpis?.heaviest && (
        <div className="mt-3 pt-3 border-t border-zbrain-divider">
          <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Highest volume node</div>
          <div className="mt-1 text-[12.5px] font-semibold text-zbrain-ink leading-tight">{kpis.heaviest.label}</div>
          <div className="text-[11px] text-zbrain-muted mt-0.5 tabular-nums">{kpis.heaviest.volume.toLocaleString()} cases · {kpis.heaviest.stage}</div>
        </div>
      )}
    </section>
  );
}

function KpiCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-zbrain-surface border border-zbrain-divider px-2.5 py-2">
      <div className="text-[9.5px] uppercase tracking-wider text-zbrain-muted font-semibold">{label}</div>
      <div className="text-[15px] font-semibold text-zbrain-ink tabular-nums mt-0.5">{value}</div>
    </div>
  );
}

function VariantsCard({
  data,
  stageLabels,
  onPick,
}: {
  data: { nodes: FlowNode[]; edges: FlowEdge[] };
  stageLabels: Record<string, string>;
  onPick: (sequenceIds: string[]) => void;
}) {
  const labels: Record<string, string> = {};
  const stages: Record<string, string | null> = {};
  data.nodes.forEach((n) => { labels[n.id] = n.label; stages[n.id] = n.stage || null; });

  const byPrefix: Record<string, FlowEdge[]> = {};
  data.edges.forEach((e) => {
    if (!byPrefix[e.source]) byPrefix[e.source] = [];
    byPrefix[e.source].push(e);
  });
  Object.values(byPrefix).forEach((es) => es.sort((a, b) => b.case_count - a.case_count));

  const paths: { ids: string[]; cases: number }[] = [];
  const starters = (byPrefix["__START__"] || []).slice(0, 5);
  for (const start of starters) {
    let cur: string | undefined = start.target;
    const seq: string[] = ["__START__", start.target];
    let cases = start.case_count;
    for (let i = 0; i < 7 && cur; i++) {
      const next: FlowEdge | undefined = (byPrefix[cur] || []).filter((e) => !seq.includes(e.target))[0];
      if (!next || next.target === "__END__") break;
      seq.push(next.target);
      cases = Math.min(cases, next.case_count);
      cur = next.target;
    }
    paths.push({ ids: seq, cases });
  }
  if (paths.length === 0) return null;

  return (
    <section className="card p-4">
      <h2 className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">Top variants</h2>
      <p className="text-[11px] text-zbrain-muted mt-0.5">Click a variant to highlight it on the map.</p>
      <ol className="mt-2 space-y-2">
        {paths.map((p, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => onPick(p.ids)}
              className="w-full text-left rounded-md border border-zbrain-divider hover:border-zbrain px-2.5 py-2 transition-colors bg-white"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold">Variant {i + 1}</span>
                <span className="text-[11.5px] font-semibold text-zbrain-ink tabular-nums">{p.cases.toLocaleString()} cases</span>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1 items-center">
                {p.ids.map((id, j) => (
                  <span key={id + j} className="inline-flex items-center gap-1">
                    <span
                      className="px-1.5 py-0.5 rounded text-[10.5px] font-medium"
                      style={{
                        background: stages[id] ? `${STAGE_COLOR[stages[id]!]}14` : "#F1F5F9",
                        color: stages[id] ? STAGE_COLOR[stages[id]!] : "#475569",
                      }}
                    >
                      {labels[id] || id}
                    </span>
                    {j < p.ids.length - 1 && <span className="text-[10px] text-zbrain-muted">→</span>}
                  </span>
                ))}
              </div>
            </button>
          </li>
        ))}
      </ol>
      {Object.keys(stageLabels).length === 0 && null /* keep stageLabels in scope for completeness */}
    </section>
  );
}

// Cross-app link to the Continuous Learning page in the Orchestrator,
// filtered to a specific Baseline Quality Target. Routes through the
// `learningUrl` helper so the destination honours the deployed Governance
// base path and any env-overridden host.
function governanceBaselineUrl(baselineId: number): string {
  return learningUrl({ tab: "baselines", baselineId });
}

// Static mapping from a Process Flow bottleneck signal to the (metric,
// segment) tuples that identify the existing Baseline Quality Target(s).
// The set of baselines is admin-controlled. Empty entries mean the
// bottleneck is observable on the map but no SLO baseline currently
// governs it; we render an explicit muted note so the gap is visible
// rather than implied. Adding a new baseline is an admin action in the
// seed file, not an automatic runtime behaviour.
type BaselineKey = { metric: string; segment: string };
type BottleneckSignal = "hitl" | "fail";

// After the baseline consolidation only 12 concept baselines exist, all
// anchored at segment="global". The previous mapping referenced per-stage
// and per-intent segment values (e.g. "stage:intake", "intent:po_intake")
// that no longer have rows, so every bottleneck rendered the "no baseline
// defined" affordance. The mapping below routes each (stage, signal) to the
// concept baseline(s) that actually govern the failure mode; entries left
// as `[]` are intentional gaps (no SLO baseline currently exists).
const BOTTLENECK_BASELINE_MAP: Record<string, Partial<Record<BottleneckSignal, BaselineKey[]>>> = {
  intake: {
    hitl: [
      { metric: "intent_classification_accuracy", segment: "global" },
      { metric: "spam_false_positive_rate", segment: "global" },
    ],
    fail: [
      { metric: "extraction_completeness", segment: "global" },
    ],
  },
  extract: {
    hitl: [
      // Extraction completeness governs both the HITL trigger (low score
      // routes to CSR review) and the fail mode in this stage, hence the
      // shared concept baseline here and on the fail path.
      { metric: "extraction_completeness", segment: "global" },
    ],
    fail: [
      { metric: "p95_stage_latency_ms", segment: "global" },
    ],
  },
  decide: {
    hitl: [
      { metric: "autonomy_l4_rate", segment: "global" },
      { metric: "hitl_resolution_p95_hours", segment: "global" },
    ],
    fail: [
      { metric: "p95_stage_latency_ms", segment: "global" },
    ],
  },
  execute: {
    hitl: [
      { metric: "customer_match_rate", segment: "global" },
    ],
    fail: [
      { metric: "aioa_handoff_success_rate", segment: "global" },
    ],
  },
  communicate: {
    // Communicate HITL does not have a concept baseline today. The send-success
    // baseline governs the fail mode only.
    hitl: [],
    fail: [
      { metric: "reply_send_success_rate", segment: "global" },
    ],
  },
  learning: {
    // Learning surfaces no per-stage SLO baseline today. Intentional gap.
    hitl: [],
    fail: [],
  },
};

// Resolve the (metric, segment) tuples for a bottleneck node into the
// concrete Baseline rows fetched from the API. Returns the resolved
// baselines plus the list of keys that had no match so the caller can show
// the "no baseline defined" affordance instead of silently hiding the gap.
type LinkedBaselineResult = {
  resolved: Baseline[];
  signals: BottleneckSignal[];
  hasGap: boolean;
};

function linkedBaselinesFor(node: FlowNode, baselines: Baseline[]): LinkedBaselineResult {
  const empty: LinkedBaselineResult = { resolved: [], signals: [], hasGap: false };
  if (!node.stage) return empty;
  const stageMap = BOTTLENECK_BASELINE_MAP[node.stage];
  if (!stageMap) return { ...empty, hasGap: true };

  const active: BottleneckSignal[] = [];
  if (node.hitl_pct >= 40) active.push("hitl");
  if (node.fail_pct >= 5) active.push("fail");
  if (active.length === 0) return empty;

  const wanted: BaselineKey[] = [];
  let gap = false;
  for (const sig of active) {
    const keys = stageMap[sig] || [];
    if (keys.length === 0) {
      gap = true;
      continue;
    }
    wanted.push(...keys);
  }

  const seen = new Set<number>();
  const resolved: Baseline[] = [];
  for (const key of wanted) {
    const match = baselines.find(
      (b) => b.metric === key.metric && b.segment === key.segment,
    );
    if (match && !seen.has(match.id)) {
      resolved.push(match);
      seen.add(match.id);
    } else if (!match) {
      gap = true;
    }
  }

  // Sort breached first, then drifting, then healthy, then unknown so the
  // most actionable signal renders at the top.
  const rank: Record<string, number> = {
    breached: 0,
    drifting: 1,
    healthy: 2,
    unknown: 3,
  };
  resolved.sort((a, b) => (rank[a.last_status] ?? 9) - (rank[b.last_status] ?? 9));
  return { resolved: resolved.slice(0, 3), signals: active, hasGap: gap };
}

function baselineStatusStyle(status: Baseline["last_status"]): { bg: string; fg: string; label: string } {
  switch (status) {
    case "breached":
      return { bg: "#FEE2E2", fg: "#991B1B", label: "Breached" };
    case "drifting":
      return { bg: "#FEF3C7", fg: "#92400E", label: "Drifting" };
    case "healthy":
      return { bg: "#DCFCE7", fg: "#166534", label: "Healthy" };
    default:
      return { bg: "#F1F5F9", fg: "#475569", label: "No data" };
  }
}

function BottlenecksCard({ bottlenecks, baselines, onPick }: { bottlenecks: FlowNode[]; baselines: Baseline[]; onPick: (id: string) => void }) {
  const sorted = bottlenecks.slice().sort((a, b) => (b.hitl_pct + b.fail_pct) - (a.hitl_pct + a.fail_pct)).slice(0, 6);
  return (
    <section className="card p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[10px] uppercase tracking-[0.12em] text-amber-700 font-semibold">Bottlenecks</h2>
        <span className="text-[10px] text-zbrain-muted">HITL ≥ 40% or Fail ≥ 5%</span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {sorted.map((n) => {
          const linked = linkedBaselinesFor(n, baselines);
          return (
            <li key={n.id}>
              <div className="rounded-md border border-amber-200 bg-amber-50/60 hover:bg-amber-50 transition-colors">
                <button
                  type="button"
                  onClick={() => onPick(n.id)}
                  className="w-full text-left px-2.5 pt-2 pb-1.5"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[12px] font-semibold text-zbrain-ink truncate">{n.label}</span>
                    <span className="text-[10.5px] text-zbrain-muted tabular-nums whitespace-nowrap">{n.volume.toLocaleString()}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[10.5px] tabular-nums">
                    <span className="text-emerald-700">{n.auto_pct.toFixed(0)}%</span>
                    <span
                      className="text-amber-700 font-semibold cursor-help"
                      title="Sub-process HITL: share of pipelines that fired a HITL gate at this specific sub-process node."
                    >{n.hitl_pct.toFixed(0)}% Sub-process HITL</span>
                    <span className="text-rose-700">{n.fail_pct.toFixed(0)}% fail</span>
                  </div>
                </button>
                {linked.resolved.length > 0 && (
                  <div className="mx-2.5 mt-0.5 pt-1.5 pb-2 border-t border-amber-200/70">
                    <div className="text-[9px] uppercase tracking-wider text-amber-700/80 font-semibold mb-1">
                      Linked baseline
                    </div>
                    <div className="flex flex-col gap-1">
                      {linked.resolved.map((b) => {
                        const s = baselineStatusStyle(b.last_status);
                        const labelText = b.label || `${b.metric} (${b.segment})`;
                        return (
                          <a
                            key={b.id}
                            href={governanceBaselineUrl(b.id)}
                            className="flex items-center justify-between gap-2 hover:underline"
                            title={b.rationale || labelText}
                          >
                            <span className="text-[10.5px] text-zbrain-ink truncate">
                              {labelText}
                            </span>
                            <span
                              className="text-[9.5px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap"
                              style={{ background: s.bg, color: s.fg }}
                            >
                              {s.label}
                            </span>
                          </a>
                        );
                      })}
                    </div>
                  </div>
                )}
                {linked.resolved.length === 0 && linked.signals.length > 0 && (
                  <div className="mx-2.5 mt-0.5 pt-1.5 pb-2 border-t border-amber-200/70">
                    <div className="text-[10px] text-zbrain-muted italic">
                      No SLO baseline defined for this stage.
                    </div>
                  </div>
                )}
                {linked.resolved.length > 0 && linked.hasGap && (
                  <div className="px-2.5 pb-2 -mt-0.5">
                    <div className="text-[10px] text-zbrain-muted italic">
                      One signal at this stage has no SLO baseline defined.
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
