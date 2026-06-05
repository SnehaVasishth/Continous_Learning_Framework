import { governanceApi as api } from "../api";
import { usePolling } from "../lib/usePolling";
import { TrustTab } from "./_governance_source";
import { PageHeader } from "../components/PageHeader";

export function AgentsPage() {
  const { data, loading, error, lastFetchedAt } = usePolling(() => api.agents());
  return (
    <div className="space-y-4">
      <PageHeader title="Agent Fleet" subtitle="Identities, capabilities, and trust posture of every pipeline stage." lastFetchedAt={lastFetchedAt} error={error} />
      {loading && <div className="card p-6 text-sm text-zbrain-muted">Loading agent fleet…</div>}
      {data && <TrustTab agents={data} />}
    </div>
  );
}
