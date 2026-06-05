import { governanceApi as api } from "../api";
import { usePolling } from "../lib/usePolling";
import { OverviewTab } from "./_governance_source";
import { PageHeader } from "../components/PageHeader";

export function OverviewPage() {
  const summary = usePolling(() => api.summary(0));
  const slo = usePolling(() => api.slo());
  // Compliance posture powers the OWASP tile (controls assessed + live
  // coverage_pct + needs_attention). Without it the tile falls back to
  // showing only the count, but we poll it here so the live posture matches
  // what the Compliance tab shows.
  const compliance = usePolling(() => api.compliance());
  const err = summary.error || slo.error;
  const ts = summary.lastFetchedAt;
  return (
    <div className="space-y-4">
      <PageHeader title="Overview" subtitle="Fleet posture at a glance." lastFetchedAt={ts} error={err} />
      {(summary.loading || slo.loading) && !summary.data && <div className="card p-6 text-sm text-zbrain-muted">Loading overview…</div>}
      {summary.data && <OverviewTab summary={summary.data} sloData={slo.data} compliance={compliance.data} />}
    </div>
  );
}
