import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { Button, Chip, Eyebrow, PageHeader, Section, Surface } from "../components/ui";

type ErrorRow = {
  pipeline_id: number;
  email_id: number | null;
  email_subject: string | null;
  email_from: string | null;
  intent: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string;
  reason_class: "restart_killed" | "db_locked" | "txn_rolled_back" | "other";
};

const REASON_LABEL: Record<ErrorRow["reason_class"], string> = {
  restart_killed: "Backend restart",
  db_locked: "Database contention",
  txn_rolled_back: "Transaction aborted",
  other: "Other",
};

const REASON_BLURB: Record<ErrorRow["reason_class"], string> = {
  restart_killed: "Pipeline was in flight when the backend restarted. Safe to retry; the original email is still attached.",
  db_locked: "SQLite write contention during the original run. Retrying with the current worker-pool size usually clears it.",
  txn_rolled_back: "An earlier exception aborted the session. Retry will start a fresh transaction.",
  other: "Unrecognised failure. Open the trace to inspect, or retry to re-run from Stage 1.",
};

type ChipTone = "neutral" | "info" | "success" | "warning" | "danger" | "violet" | "emphasis";
const REASON_CHIP: Record<ErrorRow["reason_class"], ChipTone> = {
  restart_killed: "warning",
  db_locked: "warning",
  txn_rolled_back: "danger",
  other: "neutral",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

export function ErrorsPage() {
  const [items, setItems] = useState<ErrorRow[]>([]);
  const [byReason, setByReason] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [reasonFilter, setReasonFilter] = useState<ErrorRow["reason_class"] | "all">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listErroredPipelines(200);
      setItems(data.items);
      setByReason(data.by_reason);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(
    () => (reasonFilter === "all" ? items : items.filter((r) => r.reason_class === reasonFilter)),
    [items, reasonFilter],
  );

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleAllVisible = () => {
    if (filtered.every((r) => selected.has(r.pipeline_id))) {
      const next = new Set(selected);
      filtered.forEach((r) => next.delete(r.pipeline_id));
      setSelected(next);
    } else {
      const next = new Set(selected);
      filtered.forEach((r) => next.add(r.pipeline_id));
      setSelected(next);
    }
  };

  const retrySelected = async () => {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      const res = await api.retryPipelinesBatch({ pipeline_ids: Array.from(selected) });
      setToast(`Submitted ${res.submitted.length} retries. ${res.rejected.length ? `${res.rejected.length} rejected.` : ""}`);
      setSelected(new Set());
      await load();
    } catch (e: any) {
      setToast(`Retry failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const retryAll = async () => {
    if (!confirm(`Retry all ${items.length} errored pipelines?`)) return;
    setBusy(true);
    try {
      const res = await api.retryPipelinesBatch({ retry_all_errored: true });
      setToast(`Submitted ${res.submitted.length} retries. ${res.rejected.length ? `${res.rejected.length} rejected.` : ""}`);
      setSelected(new Set());
      await load();
    } catch (e: any) {
      setToast(`Retry failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Errored pipelines"
        subtitle="Pipelines that failed mid-run. Pick targets and retry; the original email and extracted state stay intact."
      />

      <Surface>
        <div className="flex flex-wrap items-center gap-3 px-5 py-4">
          <button onClick={() => setReasonFilter("all")} className="appearance-none border-0 bg-transparent p-0">
            <Chip tone={reasonFilter === "all" ? "info" : "neutral"}>All ({items.length})</Chip>
          </button>
          {(Object.keys(REASON_LABEL) as Array<ErrorRow["reason_class"]>).map((k) => {
            const n = byReason[k] || 0;
            if (n === 0) return null;
            return (
              <button key={k} onClick={() => setReasonFilter(k)} className="appearance-none border-0 bg-transparent p-0">
                <Chip tone={reasonFilter === k ? REASON_CHIP[k] : "neutral"}>
                  {REASON_LABEL[k]} ({n})
                </Chip>
              </button>
            );
          })}
          <div className="flex-1" />
          <Button
            variant="secondary"
            onClick={retrySelected}
            disabled={busy || selected.size === 0}
          >
            Retry selected ({selected.size})
          </Button>
          <Button variant="primary" onClick={retryAll} disabled={busy || items.length === 0}>
            Retry all
          </Button>
        </div>
      </Surface>

      {toast && (
        <Surface>
          <div className="px-5 py-3 text-sm text-zbrain-text">{toast}</div>
        </Surface>
      )}

      <Section title="Errored runs" subtitle={`${filtered.length} of ${items.length}`}>
        {loading ? (
          <div className="px-5 py-6 text-sm text-zbrain-muted">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="px-5 py-6 text-sm text-zbrain-muted">
            {items.length === 0 ? "No errored pipelines. Nice." : "No matches for this filter."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-zbrain-divider text-left text-xs uppercase tracking-wide text-zbrain-muted">
                  <th className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label="Select all visible"
                      checked={filtered.length > 0 && filtered.every((r) => selected.has(r.pipeline_id))}
                      onChange={toggleAllVisible}
                    />
                  </th>
                  <th className="px-3 py-2">Pipeline</th>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Intent</th>
                  <th className="px-3 py-2">Reason</th>
                  <th className="px-3 py-2">Failed at</th>
                  <th className="px-3 py-2">Detail</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.pipeline_id} className="border-b border-zbrain-divider/50 align-top hover:bg-zbrain-surface-soft">
                    <td className="px-3 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Select pipeline ${r.pipeline_id}`}
                        checked={selected.has(r.pipeline_id)}
                        onChange={() => toggle(r.pipeline_id)}
                      />
                    </td>
                    <td className="px-3 py-3 font-medium">
                      <Link className="text-zbrain-primary hover:underline" to={`/trace/${r.pipeline_id}`}>
                        #{r.pipeline_id}
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <div className="max-w-[320px] truncate text-zbrain-text" title={r.email_subject || ""}>
                        {r.email_subject || "(no subject)"}
                      </div>
                      <div className="text-xs text-zbrain-muted">{r.email_from || ""}</div>
                    </td>
                    <td className="px-3 py-3">{r.intent || <Eyebrow>-</Eyebrow>}</td>
                    <td className="px-3 py-3">
                      <Chip tone={REASON_CHIP[r.reason_class]}>{REASON_LABEL[r.reason_class]}</Chip>
                      <div className="mt-1 max-w-[260px] text-xs text-zbrain-muted">{REASON_BLURB[r.reason_class]}</div>
                    </td>
                    <td className="px-3 py-3 text-xs text-zbrain-muted">{fmtTime(r.finished_at)}</td>
                    <td className="px-3 py-3">
                      <details>
                        <summary className="cursor-pointer text-xs text-zbrain-muted hover:text-zbrain-text">View error</summary>
                        <pre className="mt-2 max-w-[420px] whitespace-pre-wrap break-words rounded bg-zbrain-surface-soft p-2 text-xs">
                          {r.error || "(no detail)"}
                        </pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

export default ErrorsPage;
