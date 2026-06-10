import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";

import { signalGraphApi, type SgGraph } from "../api";

// Box size used both for the dagre layout maths and the rendered node.
const NODE_W = 210;
const NODE_H = 48;

// Turn the backend's {nodes, edges} into React-Flow nodes/edges WITH positions
// computed by dagre (left-to-right: signals -> target).
function layoutGraph(g: SgGraph): { nodes: Node[]; edges: Edge[] } {
  const dg = new dagre.graphlib.Graph();
  dg.setGraph({ rankdir: "LR", nodesep: 22, ranksep: 130, marginx: 24, marginy: 24 });
  dg.setDefaultEdgeLabel(() => ({}));

  g.nodes.forEach((n) => dg.setNode(n.key, { width: NODE_W, height: NODE_H }));
  g.edges.forEach((e) => dg.setEdge(e.from, e.to));
  dagre.layout(dg);

  const nodes: Node[] = g.nodes.map((n) => {
    const p = dg.node(n.key);
    const isTarget = n.type === "baseline_target";
    return {
      id: n.key,
      position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 },
      data: { label: isTarget ? n.key.replace(/^target:/, "") : n.key },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        width: NODE_W,
        height: NODE_H,
        borderRadius: 10,
        border: isTarget ? "1.5px solid #7A3CC1" : "1px solid #CBD5E1",
        background: isTarget ? "#F5F0FC" : "#FFFFFF",
        color: "#0F172A",
        fontSize: 11,
        fontWeight: isTarget ? 700 : 500,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 10px",
        textAlign: "center",
        lineHeight: 1.2,
      },
    } as Node;
  });

  const edges: Edge[] = g.edges.map((e) => ({
    id: `${e.from}->${e.to}`,
    source: e.from,
    target: e.to,
    type: "smoothstep",
    label: e.weight == null ? "–" : e.weight.toFixed(2),
    labelStyle: { fontSize: 10, fill: "#475569" },
    labelBgStyle: { fill: "#FFFFFF", fillOpacity: 0.9 },
    style: { stroke: "#94A3B8", strokeWidth: 1.4 },
    markerEnd: { type: "arrowclosed" as any, color: "#94A3B8", width: 14, height: 14 },
  }));

  return { nodes, edges };
}

export function SignalGraphViewer({ recId }: { recId: number }) {
  const [graph, setGraph] = useState<SgGraph | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    signalGraphApi
      .graph(recId)
      .then((g) => {
        if (!cancel) setGraph(g);
      })
      .catch((e) => {
        if (!cancel) setErr(String(e));
      });
    return () => {
      cancel = true;
    };
  }, [recId]);

  const layouted = useMemo(() => (graph ? layoutGraph(graph) : null), [graph]);

  if (err) {
    return <div className="text-sm text-rose-700 p-3">{err}</div>;
  }
  if (!layouted) {
    return <div className="text-sm text-zbrain-muted p-3">Loading graph…</div>;
  }

  return (
    <div className="rounded-lg border border-zbrain-divider/60 bg-white" style={{ height: 280 }}>
      <ReactFlow
        nodes={layouted.nodes}
        edges={layouted.edges}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={28} size={1} color="#E2E8F0" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
