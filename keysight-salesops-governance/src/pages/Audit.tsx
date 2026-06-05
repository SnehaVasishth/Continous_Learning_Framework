import { AuditTab } from "./_governance_source";
import { PageHeader } from "../components/PageHeader";

export function AuditPage() {
  return (
    <div className="space-y-4">
      <PageHeader title="Audit Trail" subtitle="Tamper-evident log of every tool invocation in the pipeline." lastFetchedAt={null} error={null} />
      <AuditTab />
    </div>
  );
}
