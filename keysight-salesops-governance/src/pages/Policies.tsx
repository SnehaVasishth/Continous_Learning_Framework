import { governanceApi as api } from "../api";
import { usePolling } from "../lib/usePolling";
import { PolicyTab } from "./_governance_source";
import { PageHeader } from "../components/PageHeader";

export function PoliciesPage() {
  const { data, loading, error, lastFetchedAt } = usePolling(() => api.policies());
  return (
    <div className="space-y-4">
      <PageHeader title="Policy Engine" subtitle="Active rules, conflict resolution, and tool allow-deny matrices." lastFetchedAt={lastFetchedAt} error={error} />
      {loading && <div className="card p-6 text-sm text-zbrain-muted">Loading policies…</div>}
      {data && <PolicyTab policies={data} />}
    </div>
  );
}
