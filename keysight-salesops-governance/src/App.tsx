import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/Overview";
import { AuditPage } from "./pages/Audit";
import { AgentsPage } from "./pages/Agents";
import { PoliciesPage } from "./pages/Policies";
import { CompliancePage } from "./pages/Compliance";
import { SloPage } from "./pages/Slo";
import { IntegrationsPage } from "./pages/Integrations";
import { LearningPage } from "./pages/Learning";
import { ModelsPage } from "./pages/Models";
import { NotificationsSettingsPage } from "./pages/settings/NotificationsSettings";
import { OpsLogsPage } from "./pages/settings/OpsLogs";
import { UsersPage } from "./pages/settings/Users";
import { AppearancePage } from "./pages/settings/Appearance";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/governance/overview" replace />} />

        {/* Application Governance — the six dashboards from v1, now nested */}
        <Route path="/governance" element={<Navigate to="/governance/overview" replace />} />
        <Route path="/governance/overview"   element={<OverviewPage />} />
        <Route path="/governance/audit"      element={<AuditPage />} />
        <Route path="/governance/agents"     element={<AgentsPage />} />
        <Route path="/governance/policies"   element={<PoliciesPage />} />
        <Route path="/governance/compliance" element={<CompliancePage />} />
        <Route path="/governance/slo"        element={<SloPage />} />

        {/* Top-level admin surfaces moved out of SalesOps */}
        <Route path="/integrations" element={<IntegrationsPage />} />
        <Route path="/learning"     element={<LearningPage />} />
        <Route path="/models"       element={<ModelsPage />} />

        {/* Settings cluster */}
        <Route path="/settings" element={<Navigate to="/settings/notifications" replace />} />
        <Route path="/settings/notifications" element={<NotificationsSettingsPage />} />
        <Route path="/settings/ops-logs"      element={<OpsLogsPage />} />
        <Route path="/settings/users"         element={<UsersPage />} />
        <Route path="/settings/appearance"    element={<AppearancePage />} />

        {/* Legacy v1 tab paths → redirect into the new /governance/* tree */}
        <Route path="/overview"   element={<Navigate to="/governance/overview" replace />} />
        <Route path="/audit"      element={<Navigate to="/governance/audit" replace />} />
        <Route path="/agents"     element={<Navigate to="/governance/agents" replace />} />
        <Route path="/policies"   element={<Navigate to="/governance/policies" replace />} />
        <Route path="/compliance" element={<Navigate to="/governance/compliance" replace />} />
        <Route path="/slo"        element={<Navigate to="/governance/slo" replace />} />

        <Route path="*" element={<Navigate to="/governance/overview" replace />} />
      </Routes>
    </Layout>
  );
}
