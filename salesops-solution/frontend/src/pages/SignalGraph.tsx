import { useEffect, useState } from "react";

import {
  signalGraphApi,
  type SgRecommendation,
  type SgGate,
  type SgSuggestedRange,
} from "../api";
import { Button, Chip, PageHeader, Section, Surface } from "../components/ui";
import { SignalGraphViewer } from "../components/SignalGraphViewer";

// Render the data-conditional range hint as a short line of text.
function rangeHint(r: SgSuggestedRange | undefined): string {
  // Defensive: an older backend may not send suggested_range at all.
  if (r && r.status === "ok") {
    return `observed ${r.p10.toFixed(3)}–${r.p90.toFixed(3)} (median ${r.median.toFixed(3)}, ${r.n} windows)`;
  }
  return "not enough data yet";
}

// Demo fixture identifiers (the same pair the senior dev's download-app curl
// used). Prefilled so the v1 demo is one click; the user can overwrite them.
const DEFAULT_TENANT = "676e7711192abc0024679612";
const DEFAULT_SESSION = "f8651fcd-6c46-4ed2-83ec-665f31027267";

export function SignalGraphPage() {
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT);
  const [sessionId, setSessionId] = useState(DEFAULT_SESSION);
  const [recs, setRecs] = useState<SgRecommendation[]>([]);
  // Per-card target inputs, keyed by recommendation id. Kept as strings
  // because that is what an <input> always gives us; converted to a number
  // only at accept time.
  const [targets, setTargets] = useState<Record<number, string>>({});
  const [discovering, setDiscovering] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  // Which cards have their graph expanded, keyed by recommendation id.
  const [openGraphs, setOpenGraphs] = useState<Record<number, boolean>>({});
  // Accepted gates (baseline targets) with their drift.
  const [gates, setGates] = useState<SgGate[]>([]);
  const [analyzing, setAnalyzing] = useState(false);

  const loadRecs = async (sid: string) => {
    try {
      const rows = await signalGraphApi.recommendations(sid);
      setRecs(rows);
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

  // Load whatever candidates + accepted gates already exist on mount.
  useEffect(() => {
    loadRecs(sessionId);
    loadGates(sessionId);
  }, []);

  const onAnalyze = async () => {
    setAnalyzing(true);
    setErrMsg(null);
    try {
      const res = await signalGraphApi.analyze(sessionId);
      setStatusMsg(
        `Analyzed: ${res.edges_updated} edge weights updated, ${res.gates_analyzed} gates checked for drift.`,
      );
      await loadGates(sessionId);
    } catch (e) {
      setErrMsg(String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const onSeed = async () => {
    setErrMsg(null);
    try {
      const res = await signalGraphApi.seedDemo(sessionId);
      setStatusMsg(
        `Seeded ${res.observations_written} sample observations. Click Analyze to compute drift & weights.`,
      );
      await loadRecs(sessionId);
      await loadGates(sessionId);
    } catch (e) {
      setErrMsg(String(e));
    }
  };

  const onDiscover = async () => {
    setDiscovering(true);
    setErrMsg(null);
    setStatusMsg(null);
    try {
      const res = await signalGraphApi.discover(tenantId, sessionId);
      setStatusMsg(
        `Discovered ${res.signals} signals and ${res.gates} candidate gates.`,
      );
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
    // The user must set the number themselves; we never invent one.
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

  const inp =
    "w-full px-3 py-2 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-sm";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quality Gates: discover from a client codebase"
        subtitle="Fetch a client solution, let the LLM extract signals and propose candidate quality gates, then set a target on the ones you want to monitor."
      />

      {errMsg && (
        <Surface>
          <div className="p-4 text-sm text-rose-700 dark:text-rose-300">{errMsg}</div>
        </Surface>
      )}
      {statusMsg && (
        <Surface>
          <div className="p-4 text-sm text-emerald-700 dark:text-emerald-300">{statusMsg}</div>
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
            <Button onClick={() => loadRecs(sessionId)} variant="ghost">
              Refresh
            </Button>
            <Button onClick={onSeed} variant="ghost" title="Demo only: write synthetic observations so range/drift/weights can be shown">
              Seed sample data
            </Button>
          </div>
        </Section>
      </Surface>

      <Surface>
        <Section
          title={`Candidate gates (${recs.length})`}
          subtitle="Set a target value to accept a gate, or dismiss it."
        >
          {recs.length === 0 && (
            <div className="py-6 text-center text-zbrain-muted dark:text-zbrain-dark-muted">
              No open candidates. Click "Discover" above.
            </div>
          )}
          <div className="space-y-3">
            {recs.map((rec) => (
              <div
                key={rec.id}
                className="rounded-lg border border-zbrain-divider/60 dark:border-zbrain-dark-divider/60 p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-mono text-sm font-medium text-zbrain-ink dark:text-zbrain-dark-ink">
                      {rec.metric}
                    </div>
                    <div className="text-[13px] text-zbrain-muted dark:text-zbrain-dark-muted mt-1">
                      {rec.rationale}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Chip tone="info">
                      {rec.direction === "min" ? "higher is better" : "lower is better"}
                    </Chip>
                    {rec.compute && <Chip tone="neutral">{rec.compute}</Chip>}
                  </div>
                </div>

                {rec.inputs.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 mt-3">
                    <span className="text-[12px] text-zbrain-muted dark:text-zbrain-dark-muted">
                      signals:
                    </span>
                    {rec.inputs.map((sig) => (
                      <Chip key={sig} tone="violet">
                        {sig}
                      </Chip>
                    ))}
                  </div>
                )}

                <div className="text-[12px] text-zbrain-muted dark:text-zbrain-dark-muted mt-3">
                  suggested range: {rangeHint(rec.suggested_range)}
                </div>

                <div className="flex items-center gap-2 mt-2">
                  <input
                    className={inp + " max-w-[180px]"}
                    type="number"
                    placeholder="target value"
                    value={targets[rec.id] ?? ""}
                    onChange={(e) =>
                      setTargets((t) => ({ ...t, [rec.id]: e.target.value }))
                    }
                  />
                  <Button onClick={() => onAccept(rec)} variant="primary">
                    Accept
                  </Button>
                  <Button onClick={() => onDismiss(rec)} variant="ghost">
                    Dismiss
                  </Button>
                  <Button
                    onClick={() =>
                      setOpenGraphs((g) => ({ ...g, [rec.id]: !g[rec.id] }))
                    }
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
            <div className="py-6 text-center text-zbrain-muted dark:text-zbrain-dark-muted">
              No accepted gates yet. Set a target on a candidate above.
            </div>
          )}
          <div className="space-y-2">
            {gates.map((g) => (
              <div
                key={`${g.metric}:${g.segment}`}
                className="rounded-lg border border-zbrain-divider/60 dark:border-zbrain-dark-divider/60 p-3 flex items-center justify-between gap-4"
              >
                <div className="min-w-0">
                  <div className="font-mono text-sm font-medium text-zbrain-ink dark:text-zbrain-dark-ink">
                    {g.metric}
                  </div>
                  <div className="text-[12px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5">
                    target {g.target_value ?? "—"}
                    {g.status === "ok" && (
                      <>
                        {" · "}current {g.current?.toFixed(3)}
                        {g.delta_pct != null && (
                          <> ({(g.delta_pct * 100).toFixed(1)}%)</>
                        )}
                        {g.psi != null && <> · PSI {g.psi.toFixed(2)}</>}
                        {g.streams && <> · {g.streams}</>}
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
