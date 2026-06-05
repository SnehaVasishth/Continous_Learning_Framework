import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, CostCoverage, CostRollup } from "../api";
import { PageHeader } from "../components/PageHeader";
import { STAGE_DISPLAY, PIPELINE_STAGE_KEYS } from "../lib/stageNames";

/**
 * Models catalogue.
 *
 * Lists every model registered against the platform: the live OpenAI
 * provider sourced from the backend `llm_provider_configs` table, plus any
 * custom models registered locally via the form below. Custom registrations
 * persist in `localStorage` so a CSR can prototype quickly without touching
 * the backend store; the "Promote to platform" action is the planned
 * migration step that writes them to the real config table.
 */

type ModelSource = "platform" | "custom";
type ModelRow = {
  id: string;
  provider: string;
  model: string;
  endpoint?: string;
  connected: boolean;
  source: ModelSource;
  backend_source?: "db" | "env" | "none";
  api_key_masked?: string | null;
  is_active?: boolean;
  last_tested_at?: string | null;
  last_error?: string | null;
  updated_at?: string | null;
  used_in_stages: string[];
  note?: string;
};

const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  azure_openai: "Azure OpenAI",
  bedrock: "AWS Bedrock",
  vertex: "Google Vertex AI",
  zbrain: "ZBrain Hosted",
  custom: "Custom",
};

const PLATFORM_STAGE_USAGE: Record<string, string[]> = {
  // Demo-time hint of where each provider is consumed. Backed by the
  // backend stage-to-provider mapping in production. Values are pipeline
  // stage keys; the UI resolves them to canonical display names via
  // STAGE_DISPLAY so labels stay aligned with the SalesOps Dashboard.
  openai: ["intake", "extract", "decide", "communicate"],
};

const CUSTOM_STORE_KEY = "zbrain-orchestrator:custom-models";

type CustomModel = {
  id: string;
  provider: string;
  model: string;
  endpoint: string;
  api_key_masked: string;
  used_in_stages: string[];
  created_at: string;
  note?: string;
};

function loadCustom(): CustomModel[] {
  try {
    const raw = localStorage.getItem(CUSTOM_STORE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveCustom(rows: CustomModel[]) {
  try { localStorage.setItem(CUSTOM_STORE_KEY, JSON.stringify(rows)); } catch { /* noop */ }
}

// Pipeline stage keys (lowercased) wired through STAGE_DISPLAY so the
// AddModel form chips render the same canonical names as the rest of the
// app (Intake & Classification, Extraction & Enrichment, etc.).
const STAGES_ALL: string[] = PIPELINE_STAGE_KEYS.filter((k) => k !== "learning");

export function ModelsPage() {
  const [platform, setPlatform] = useState<ModelRow[] | null>(null);
  const [custom, setCustom] = useState<CustomModel[]>(() => loadCustom());
  const [err, setErr] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const oai = await api.integrations.openai.status();
        const next: ModelRow[] = [
          {
            id: "platform:openai",
            provider: "openai",
            model: oai.model || "gpt-5.2",
            connected: !!oai.connected,
            source: "platform",
            backend_source: (oai.source as ModelRow["backend_source"]) || "none",
            api_key_masked: oai.api_key_masked,
            is_active: oai.is_active,
            last_tested_at: oai.last_tested_at,
            last_error: oai.last_error,
            updated_at: oai.updated_at,
            used_in_stages: PLATFORM_STAGE_USAGE.openai,
          },
        ];
        if (!cancel) {
          setPlatform(next);
          setLastFetched(new Date());
          setErr(null);
        }
      } catch (e: any) {
        if (!cancel) setErr(String(e?.message || e));
      }
    }
    load();
    const id = setInterval(load, 20000);
    return () => { cancel = true; clearInterval(id); };
  }, []);

  const rows: ModelRow[] = useMemo(() => {
    const customRows: ModelRow[] = custom.map((c) => ({
      id: c.id,
      provider: c.provider,
      model: c.model,
      endpoint: c.endpoint,
      connected: true,
      source: "custom",
      api_key_masked: c.api_key_masked,
      used_in_stages: c.used_in_stages,
      updated_at: c.created_at,
      note: c.note,
    }));
    return [...(platform || []), ...customRows];
  }, [platform, custom]);

  function addModel(input: Omit<CustomModel, "id" | "created_at" | "api_key_masked"> & { api_key: string }) {
    const masked = input.api_key
      ? `${input.api_key.slice(0, 4)}…${input.api_key.slice(-4)}`
      : "(none)";
    const row: CustomModel = {
      id: `custom:${Date.now()}`,
      provider: input.provider,
      model: input.model,
      endpoint: input.endpoint,
      api_key_masked: masked,
      used_in_stages: input.used_in_stages,
      created_at: new Date().toISOString(),
      note: input.note,
    };
    const next = [...custom, row];
    setCustom(next);
    saveCustom(next);
  }

  function removeModel(id: string) {
    const next = custom.filter((c) => c.id !== id);
    setCustom(next);
    saveCustom(next);
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Models"
        subtitle="Every model registered against the platform. Add a custom model below to make it selectable from any Solution."
        lastFetchedAt={lastFetched}
        error={err}
      />

      <AIInfrastructureCostCard />

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider flex items-center justify-between gap-4">
          <div>
            <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Registered models</div>
            <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
              Platform-managed rows reflect the live LLM Providers store. Custom rows live in this browser until promoted.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 px-3 h-8 rounded-md bg-zbrain text-white text-[12.5px] font-semibold hover:opacity-90"
          >
            <span aria-hidden>＋</span> Add model
          </button>
        </div>

        {rows.length === 0 ? (
          <div className="px-5 py-6 text-sm text-zbrain-muted">No models registered.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider text-[10.5px]">
                  <th className="px-4 py-2.5 text-left font-semibold">Provider</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Model</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Status</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Origin</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Used in stages</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Last updated</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
                {rows.map((r) => {
                  const tone = r.connected
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-rose-50 text-rose-700 border-rose-200";
                  const origin = r.source === "platform"
                    ? `Platform · ${r.backend_source || "store"}`
                    : "Custom (this browser)";
                  return (
                    <tr key={r.id} className="hover:bg-zbrain-surface/40 dark:hover:bg-zbrain-dark-elev2/50">
                      <td className="px-4 py-3 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
                        {PROVIDER_LABEL[r.provider] || r.provider}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        <div>{r.model}</div>
                        {r.endpoint && (
                          <div className="text-[10.5px] text-zbrain-muted font-mono mt-0.5 truncate max-w-[280px]">
                            {r.endpoint}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-semibold border ${tone}`}>
                          {r.connected ? "Connected" : "Not connected"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-zbrain-muted text-[11.5px]">{origin}</td>
                      <td className="px-4 py-3">
                        {r.used_in_stages.length === 0 ? (
                          <span className="text-zbrain-muted">-</span>
                        ) : (
                          r.used_in_stages.map((s) => (
                            <span key={s} className="inline-block mr-1 mb-1 px-2 py-0.5 rounded-full text-[10.5px] bg-zbrain-50 dark:bg-zbrain-dark-elev2 text-zbrain-ink dark:text-zbrain-dark-ink">
                              {STAGE_DISPLAY[s] || s}
                            </span>
                          ))
                        )}
                      </td>
                      <td className="px-4 py-3 text-zbrain-muted tabular-nums">
                        {r.updated_at ? new Date(r.updated_at).toLocaleString() : "-"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {r.source === "platform" ? (
                          <Link
                            to="/integrations"
                            className="text-zbrain text-[12px] font-medium hover:underline"
                          >
                            Manage →
                          </Link>
                        ) : (
                          <button
                            type="button"
                            onClick={() => removeModel(r.id)}
                            className="text-rose-700 text-[12px] font-medium hover:underline"
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card p-4 text-[12.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
        <div className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink mb-1">On the roadmap</div>
        <ul className="list-disc list-inside space-y-0.5">
          <li>Per-stage model assignment (Intake & Classification, Extraction & Enrichment, Decision & Confidence Scoring, Communication & Close-out)</li>
          <li>Fallback chain editor with deterministic failover order</li>
          <li>Side-by-side A/B with traffic split and statistical significance gate</li>
          <li>Per-model spend caps with automated throttle</li>
          <li>"Promote to platform" action that writes custom rows into the backend LLM Providers store</li>
        </ul>
      </div>

      {adding && (
        <AddModelModal
          onClose={() => setAdding(false)}
          onSave={(payload) => { addModel(payload); setAdding(false); }}
        />
      )}
    </div>
  );
}

function AddModelModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (payload: Omit<CustomModel, "id" | "created_at" | "api_key_masked"> & { api_key: string }) => void;
}) {
  const [provider, setProvider] = useState("custom");
  const [model, setModel] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [stages, setStages] = useState<string[]>([]);
  const [note, setNote] = useState("");

  function toggleStage(s: string) {
    setStages((cur) => cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]);
  }

  const valid = model.trim().length > 0 && endpoint.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="w-full max-w-[560px] bg-white dark:bg-zbrain-dark-elev1 rounded-lg shadow-xl border border-zbrain-divider dark:border-zbrain-dark-divider">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider flex items-center justify-between">
          <div>
            <div className="text-[14px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Register a model</div>
            <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5">
              Make a new LLM endpoint selectable across every Solution in this project.
            </div>
          </div>
          <button type="button" onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink" aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m6 6 12 12M6 18 18 6"/></svg>
          </button>
        </div>

        <div className="p-5 space-y-3.5">
          <Field label="Provider">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full h-9 px-3 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-[13px] text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30"
            >
              <option value="custom">Custom</option>
              <option value="openai">OpenAI</option>
              <option value="azure_openai">Azure OpenAI</option>
              <option value="bedrock">AWS Bedrock</option>
              <option value="vertex">Google Vertex AI</option>
              <option value="zbrain">ZBrain Hosted</option>
            </select>
          </Field>

          <Field label="Model name" hint="The id passed to the provider, e.g. gpt-4.1, claude-sonnet-4-6, mistral-large.">
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4.1"
              className="w-full h-9 px-3 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-[13px] text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30"
            />
          </Field>

          <Field label="Endpoint URL" hint="HTTPS endpoint. For OpenAI-compatible providers this is the /v1 base.">
            <input
              type="url"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="https://api.example.com/v1"
              className="w-full h-9 px-3 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-[13px] text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30"
            />
          </Field>

          <Field label="API key" hint="Stored masked. Only the last 4 characters are kept in the catalogue view.">
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-…"
              className="w-full h-9 px-3 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-[13px] text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30"
              autoComplete="off"
            />
          </Field>

          <Field label="Used in stages" hint="Optional. Tag where this model is intended to run.">
            <div className="flex flex-wrap gap-1.5">
              {STAGES_ALL.map((s) => {
                const on = stages.includes(s);
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => toggleStage(s)}
                    className={[
                      "px-2.5 py-1 rounded-full text-[11px] font-semibold border transition-colors",
                      on
                        ? "bg-zbrain-50 text-zbrain border-zbrain dark:bg-zbrain-dark-elev2 dark:text-zbrain-dark-accent dark:border-zbrain-dark-accent"
                        : "bg-white text-zbrain-muted border-zbrain-divider hover:bg-zbrain-50/60 dark:bg-zbrain-dark-elev1 dark:text-zbrain-dark-muted dark:border-zbrain-dark-divider",
                    ].join(" ")}
                  >
                    {STAGE_DISPLAY[s] || s}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label="Note" hint="Optional. Surfaced in the catalogue row.">
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Reserved for low-stakes prototypes"
              className="w-full h-9 px-3 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-[13px] text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30"
            />
          </Field>
        </div>

        <div className="px-5 py-3 border-t border-zbrain-divider dark:border-zbrain-dark-divider flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 h-8 rounded-md text-[12.5px] font-medium text-zbrain-muted hover:text-zbrain-ink hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!valid}
            onClick={() => onSave({
              provider,
              model: model.trim(),
              endpoint: endpoint.trim(),
              api_key: apiKey,
              used_in_stages: stages,
              note: note.trim() || undefined,
            })}
            className={[
              "px-3 h-8 rounded-md text-[12.5px] font-semibold",
              valid ? "bg-zbrain text-white hover:opacity-90" : "bg-zbrain-divider text-zbrain-muted cursor-not-allowed",
            ].join(" ")}
          >
            Save model
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{label}</div>
      {hint && <div className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 mb-1.5">{hint}</div>}
      {!hint && <div className="mb-1.5" />}
      {children}
    </label>
  );
}

/**
 * AI Infrastructure Cost card.
 *
 * Real cost telemetry for every paid call the platform has made in the last
 * 30 days: LLM tokens, OCR, translation, embedding. Lives on the Models
 * page because it's the cost of the registered models themselves, not a
 * functional analytics metric. Numbers come straight from
 * `/api/analytics/cost`, which is computed off the `cost_events` table.
 */
function AIInfrastructureCostCard() {
  const [data, setData] = useState<{ rollup: CostRollup; coverage: CostCoverage } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const d = await api.analytics.cost(30);
        if (!cancel) { setData(d); setErr(null); }
      } catch (e: any) {
        if (!cancel) setErr(String(e?.message || e));
      }
    }
    load();
    const id = setInterval(load, 30000);
    return () => { cancel = true; clearInterval(id); };
  }, []);

  const coveragePct = data?.coverage.coverage_pct ?? 0;
  const coverageTone = coveragePct >= 95
    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
    : "bg-amber-50 text-amber-800 border-amber-200";

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider flex items-center justify-between gap-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">AI infrastructure cost</div>
          <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink mt-0.5">Metered tokens, OCR, translation, embedding</div>
          <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5">
            Real spend on every paid call the registered models have made in the last 30 days.
          </div>
        </div>
        {data && (
          <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wide ${coverageTone}`}>
            Coverage {coveragePct.toFixed(0)}% ({data.coverage.metered_pipelines.toLocaleString()} of {data.coverage.completed_pipelines.toLocaleString()})
          </span>
        )}
      </div>

      <div className="px-5 py-4">
        {err ? (
          <div className="text-[12.5px] text-rose-700">Cost telemetry failed to load: {err}</div>
        ) : !data ? (
          <div className="text-[12.5px] text-zbrain-muted">Loading cost…</div>
        ) : coveragePct < 95 ? (
          <div className="text-[12.5px] text-amber-900 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
            Coverage is {coveragePct.toFixed(0)}%; {data.coverage.completed_pipelines - data.coverage.metered_pipelines} pipelines
            (deterministic short-circuits, spam discards, pre-paid-stage errors) have no paid call to meter.
            Run the cost backfill script to close historical gaps; new pipelines auto-record cost at every paid call.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <CostStat label="Total spend (30d)" value={`$${data.rollup.total_usd.toFixed(2)}`} accent="ok" />
            <CostStat label="Per case" value={`$${data.rollup.cost_per_case.toFixed(4)}`} />
            <CostStat label="Cases with cost" value={`${data.rollup.metered_pipelines.toLocaleString()} of ${data.coverage.completed_pipelines.toLocaleString()}`} />

            <div className="md:col-span-3 grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-zbrain-divider dark:border-zbrain-dark-divider">
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted dark:text-zbrain-dark-muted font-semibold mb-1">By component</div>
                <ul className="space-y-1">
                  {data.rollup.by_component.slice(0, 5).map((c) => (
                    <li key={c.component} className="flex items-center justify-between text-[12.5px]">
                      <span className="text-zbrain-ink dark:text-zbrain-dark-ink">{c.component}</span>
                      <span className="text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">${c.cost_usd.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted dark:text-zbrain-dark-muted font-semibold mb-1">By model</div>
                <ul className="space-y-1">
                  {data.rollup.by_model.slice(0, 5).map((m) => (
                    <li key={m.model} className="flex items-center justify-between text-[12.5px]">
                      <span className="text-zbrain-ink dark:text-zbrain-dark-ink font-mono">{m.model}</span>
                      <span className="text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">${m.cost_usd.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CostStat({ label, value, accent }: { label: string; value: string; accent?: "ok" }) {
  return (
    <div className="rounded-lg bg-zbrain-surface dark:bg-zbrain-dark-elev2 border border-zbrain-divider dark:border-zbrain-dark-divider px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">{label}</div>
      <div className={`text-lg font-semibold tabular-nums mt-1 ${accent === "ok" ? "text-emerald-700 dark:text-emerald-300" : "text-zbrain-ink dark:text-zbrain-dark-ink"}`}>{value}</div>
    </div>
  );
}
