import { governanceApi as api } from "../api";
import { usePolling } from "../lib/usePolling";
import { SloTab } from "./_governance_source";
import { PageHeader } from "../components/PageHeader";

export function SloPage() {
  const { data, loading, error, lastFetchedAt } = usePolling(() => api.slo());
  return (
    <div className="space-y-4">
      <PageHeader title="SLO Monitor" subtitle="Service-level objectives, latency budgets, and cost guardrails." lastFetchedAt={lastFetchedAt} error={error} />
      {loading && <div className="card p-6 text-sm text-zbrain-muted">Loading SLO posture…</div>}
      {data && <SloTab sloData={data} />}
    </div>
  );
}
