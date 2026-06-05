import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { aioaApi, AIOARequestDetail, AIOARequestRow } from "../api";
import { Button, Chip, Eyebrow, PageHeader, Section, Surface } from "../components/ui";
import { integrationsUrl } from "../lib/governanceUrl";

type ChipTone = "neutral" | "info" | "success" | "warning" | "danger" | "violet" | "emphasis";

const STATUS_LABEL: Record<string, string> = {
  pending_send: "Waiting",
  sent: "Awaiting AIOA response",
  response_received: "Response received",
  processed: "Processed",
  timed_out: "Timed out",
};

const STATUS_TONE: Record<string, ChipTone> = {
  pending_send: "info",
  sent: "info",
  response_received: "violet",
  processed: "success",
  timed_out: "warning",
};

const STATUS_BLURB: Record<string, string> = {
  pending_send: "Waiting on the configured AIOA endpoint to accept the request. The pipeline is parked until a response arrives or the timeout window elapses.",
  sent: "Sent to AIOA. The pipeline is parked and the service is waiting for AIOA's callback with the validation decision.",
  response_received: "AIOA's callback has arrived. The service is about to run the post-AIOA action (CSR draft on FAIL, resume on PASS).",
  processed: "Post-AIOA action complete. FAIL requests parked the pipeline on the HITL queue with a CSR draft; PASS requests handed control back to the pipeline.",
  timed_out: "AIOA did not respond within the configured timeout window. The service treated this as a fallout and queued a CSR clarification on the HITL queue.",
};

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function AIOAQueuePage() {
  const [items, setItems] = useState<AIOARequestRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AIOARequestDetail | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [providerOffline, setProviderOffline] = useState<boolean>(false);
  const [searchParams] = useSearchParams();
  const pipelineFilter = searchParams.get("pipeline_id") || "";
  const [autoSelectedFor, setAutoSelectedFor] = useState<string | null>(null);

  const load = useCallback(async () => {
    const status = statusFilter === "all" ? undefined : statusFilter;
    const r = await aioaApi.listRequests({ status, limit: 200 });
    setItems(r.items);
    setCounts(r.counts_by_status || {});
    setLoading(false);
    // Provider readiness is a separate concern from the queue listing; we
    // refresh it on the same cadence so the banner reflects the live state.
    try {
      const providers = await aioaApi.listProviders();
      const anyActive = providers.some((p) => p.is_active);
      setProviderOffline(!anyActive);
    } catch {
      // Silently ignore: a transient error should not flap the banner.
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  // Totals used by the offline banner: aggregate every status the queue
  // exposes so a stranded `timed_out` cohort still counts as "the queue is
  // non-empty and the provider is offline".
  const queueTotal = Object.values(counts).reduce((acc, n) => acc + (n || 0), 0);
  const strandedTotal = (counts.pending_send || 0) + (counts.sent || 0) + (counts.timed_out || 0);

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    aioaApi.getRequest(selectedId).then(setDetail).catch(() => setDetail(null));
  }, [selectedId]);

  // Deep-link from a Trace page banner: ?pipeline_id=N opens the most recent
  // AIOA request for that pipeline. We only auto-select once per query value
  // so the operator stays in control of the right-hand detail panel after the
  // initial focus.
  useEffect(() => {
    if (!pipelineFilter) return;
    if (autoSelectedFor === pipelineFilter) return;
    const match = items.find((r) => String(r.pipeline_id) === pipelineFilter);
    if (match) {
      setSelectedId(match.id);
      setAutoSelectedFor(pipelineFilter);
    }
  }, [items, pipelineFilter, autoSelectedFor]);

  const filtered = useMemo(() => {
    if (!pipelineFilter) return items;
    return items.filter((r) => String(r.pipeline_id) === pipelineFilter);
  }, [items, pipelineFilter]);

  const showToast = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 3500);
  };

  const replay = async (decision: "PASS" | "FAIL") => {
    if (!detail) return;
    setActionBusy(true);
    try {
      await aioaApi.replay(detail.id, {
        decision,
        fallout_reasons:
          decision === "FAIL"
            ? [
                { check: "operator_replay", detail: "Operator replayed this request as FAIL for testing" },
              ]
            : [],
      });
      showToast("ok", `Replayed as ${decision}`);
      const fresh = await aioaApi.getRequest(detail.id);
      setDetail(fresh);
      void load();
    } catch (e: any) {
      showToast("err", `Replay failed: ${e?.message || e}`);
    } finally {
      setActionBusy(false);
    }
  };

  const resend = async () => {
    if (!detail) return;
    setActionBusy(true);
    try {
      await aioaApi.resend(detail.id);
      showToast("ok", "Resent. Sender will retry on the next tick");
      const fresh = await aioaApi.getRequest(detail.id);
      setDetail(fresh);
      void load();
    } catch (e: any) {
      showToast("err", `Resend failed: ${e?.message || e}`);
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <div className="max-w-[1440px] mx-auto px-5 py-6">
      <PageHeader
        title="Order Acceptance · AIOA Queue"
        subtitle="Every request sent to the external AI Order Acceptance service, with full status, payload, and replay controls."
      />

      {/* AIOA provider-offline banner removed by design. Configuration errors
          that cause a pipeline to stop must surface AT THE STAGE in the case
          trace where the pipeline parked, not as a side-page banner. The
          aioa_timeout trace event now carries the provider readiness payload
          so the Trace page renders the error in context. */}

      {toast && (
        <div
          className={
            "fixed bottom-4 right-4 z-50 rounded-md px-4 py-2 text-sm shadow-md " +
            (toast.kind === "ok"
              ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
              : "bg-rose-100 text-rose-800 border border-rose-200")
          }
        >
          {toast.msg}
        </div>
      )}

      <Surface className="mb-5">
        <Section title="About this queue">
          <p className="text-sm text-zbrain-muted">
            Each row is a validation request the Order Acceptance service sent to AIOA on behalf of a paused pipeline.
            Configure the AIOA endpoint in Settings → Integrations before requests can leave the queue.
            Pipelines stay parked until AIOA responds or the configured timeout window elapses.
          </p>
        </Section>
      </Surface>

      {/* Status filters */}
      <Surface className="mb-5">
        <Section title="Filters">
          <div className="flex gap-2 flex-wrap">
            <FilterChip label={`All (${items.length})`} active={statusFilter === "all"} onClick={() => setStatusFilter("all")} />
            {Object.entries(STATUS_LABEL).map(([key, label]) => (
              <FilterChip
                key={key}
                label={`${label} (${counts[key] || 0})`}
                active={statusFilter === key}
                onClick={() => setStatusFilter(key)}
              />
            ))}
          </div>
        </Section>
      </Surface>

      {/* Queue list + detail panel */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-5">
        <Surface>
          <Section title={`Requests (${filtered.length})`}>
            {loading ? (
              <p className="text-sm text-zbrain-muted">Loading…</p>
            ) : filtered.length === 0 ? (
              <p className="text-sm text-zbrain-muted">No AIOA requests in this view.</p>
            ) : (
              <div className="overflow-x-auto -mx-2">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wider text-zbrain-muted border-b border-zbrain-divider">
                      <th className="px-2 py-2 text-left font-medium">Correlation</th>
                      <th className="px-2 py-2 text-left font-medium">Pipeline</th>
                      <th className="px-2 py-2 text-left font-medium">Status</th>
                      <th className="px-2 py-2 text-left font-medium">Decision</th>
                      <th className="px-2 py-2 text-left font-medium">Created</th>
                      <th className="px-2 py-2 text-left font-medium">Sent</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((r) => (
                      <tr
                        key={r.id}
                        onClick={() => setSelectedId(r.id)}
                        className={
                          "border-b border-zbrain-divider/60 cursor-pointer hover:bg-zbrain-50 " +
                          (selectedId === r.id ? "bg-zbrain-50" : "")
                        }
                      >
                        <td className="px-2 py-2 font-mono text-xs">{r.correlation_id}</td>
                        <td className="px-2 py-2">
                          <Link
                            to={`/trace/${r.pipeline_id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-zbrain hover:underline"
                          >
                            #{r.pipeline_id}
                          </Link>
                        </td>
                        <td className="px-2 py-2">
                          <Chip tone={STATUS_TONE[r.status] || "neutral"}>{STATUS_LABEL[r.status] || r.status}</Chip>
                        </td>
                        <td className="px-2 py-2">
                          {r.decision ? (
                            <Chip tone={r.decision === "PASS" ? "success" : "danger"}>{r.decision}</Chip>
                          ) : (
                            <span className="text-zbrain-muted">-</span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-xs text-zbrain-muted">{fmtTime(r.created_at)}</td>
                        <td className="px-2 py-2 text-xs text-zbrain-muted">{fmtTime(r.sent_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </Surface>

        <Surface>
          {!detail ? (
            <Section title="Request detail">
              <p className="text-sm text-zbrain-muted">Select a request on the left to see its payload, status, and actions.</p>
            </Section>
          ) : (
            <Section
              title={`Request #${detail.id}`}
              subtitle={`Correlation ${detail.correlation_id}`}
              action={
                <div className="flex gap-2 flex-wrap">
                  {(detail.status === "sent" || detail.status === "timed_out" || detail.status === "pending_send") && (
                    <>
                      <Button variant="ghost" onClick={() => replay("PASS")} disabled={actionBusy}>Replay as PASS</Button>
                      <Button variant="ghost" onClick={() => replay("FAIL")} disabled={actionBusy}>Replay as FAIL</Button>
                    </>
                  )}
                  {(detail.status === "error" || detail.status === "timed_out") && (
                    <Button variant="ghost" onClick={resend} disabled={actionBusy}>Resend</Button>
                  )}
                </div>
              }
            >
              <div className="space-y-3">
                <div className="flex gap-2 flex-wrap">
                  <Chip tone={STATUS_TONE[detail.status] || "neutral"}>{STATUS_LABEL[detail.status] || detail.status}</Chip>
                  {detail.decision && (
                    <Chip tone={detail.decision === "PASS" ? "success" : "danger"}>{detail.decision}</Chip>
                  )}
                </div>
                <p className="text-sm text-zbrain-muted">{STATUS_BLURB[detail.status]}</p>

                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <Eyebrow>Pipeline</Eyebrow>
                    <Link to={`/trace/${detail.pipeline_id}`} className="text-zbrain hover:underline">
                      #{detail.pipeline_id} (open trace)
                    </Link>
                  </div>
                  <div>
                    <Eyebrow>Provider</Eyebrow>
                    <div>{detail.provider_name || "-"}</div>
                  </div>
                  <div>
                    <Eyebrow>Created</Eyebrow>
                    <div className="text-xs">{fmtTime(detail.created_at)}</div>
                  </div>
                  <div>
                    <Eyebrow>Sent</Eyebrow>
                    <div className="text-xs">{fmtTime(detail.sent_at)}</div>
                  </div>
                  <div>
                    <Eyebrow>Response received</Eyebrow>
                    <div className="text-xs">{fmtTime(detail.response_received_at)}</div>
                  </div>
                  <div>
                    <Eyebrow>Processed</Eyebrow>
                    <div className="text-xs">{fmtTime(detail.processed_at)}</div>
                  </div>
                </div>

                {detail.last_error && (
                  <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                    <strong>Last error:</strong> {detail.last_error}
                  </div>
                )}

                {detail.fallout_reasons && detail.fallout_reasons.length > 0 && (
                  <div>
                    <Eyebrow>Fallout reasons</Eyebrow>
                    <ul className="list-disc pl-5 text-sm">
                      {detail.fallout_reasons.map((f: any, i: number) => (
                        <li key={i}>
                          {typeof f === "string"
                            ? f
                            : `${f.check || f.label || "review item"}: ${f.detail || ""}`}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {detail.csr_draft && detail.csr_draft.subject && (
                  <div className="rounded-md border border-zbrain-divider bg-zbrain-50 p-3">
                    <Eyebrow>CSR clarification draft</Eyebrow>
                    <div className="text-sm font-semibold">{detail.csr_draft.subject}</div>
                    <pre className="text-xs whitespace-pre-wrap mt-2 text-zbrain-ink">{detail.csr_draft.body}</pre>
                  </div>
                )}

                <details>
                  <summary className="cursor-pointer text-sm text-zbrain hover:underline">Request payload</summary>
                  <pre className="text-xs bg-zbrain-50 p-2 rounded overflow-x-auto mt-2">
                    {JSON.stringify(detail.request_payload, null, 2)}
                  </pre>
                </details>

                {detail.response_payload && Object.keys(detail.response_payload).length > 0 && (
                  <details>
                    <summary className="cursor-pointer text-sm text-zbrain hover:underline">Response payload</summary>
                    <pre className="text-xs bg-zbrain-50 p-2 rounded overflow-x-auto mt-2">
                      {JSON.stringify(detail.response_payload, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            </Section>
          )}
        </Surface>
      </div>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "px-3 py-1 rounded-full text-xs border transition-colors " +
        (active
          ? "bg-zbrain text-white border-zbrain"
          : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-50")
      }
    >
      {label}
    </button>
  );
}
