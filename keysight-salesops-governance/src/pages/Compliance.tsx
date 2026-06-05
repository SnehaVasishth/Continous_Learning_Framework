import { governanceApi as api } from "../api";
import { usePolling } from "../lib/usePolling";
import { ComplianceTab } from "./_governance_source";
import { PageHeader } from "../components/PageHeader";

export function CompliancePage() {
  const { data, loading, error, lastFetchedAt } = usePolling(() => api.compliance());
  return (
    <div className="space-y-4">
      <PageHeader title="Compliance" subtitle="OWASP ASI-10 control coverage, evidence grades, attestation hash." lastFetchedAt={lastFetchedAt} error={error} />
      {loading && <div className="card p-6 text-sm text-zbrain-muted">Loading compliance posture…</div>}
      {data && <ComplianceTab compliance={data} />}
    </div>
  );
}
