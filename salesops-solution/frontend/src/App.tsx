import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { governanceUrl } from "./lib/governanceUrl";
import { AIOAQueuePage } from "./pages/AIOAQueue";
import { AnalyticsPage } from "./pages/Analytics";
import { DashboardPage } from "./pages/Dashboard";
import { ErrorsPage } from "./pages/Errors";
import { HitlPage } from "./pages/Hitl";
import { InboxPage } from "./pages/Inbox";
import { KnowledgeBasePage } from "./pages/KnowledgeBase";
import { TestCorpusPage } from "./pages/TestCorpus";
import { SettingsLayout } from "./pages/Settings";
import { UserProfileSection } from "./pages/settings/UserProfile";
import { SolutionDocPage } from "./pages/SolutionDoc";
import { SolutionOverviewPage } from "./pages/SolutionOverview";
import { ProcessFlowPage } from "./pages/ProcessFlow";
import { StageDetailPage } from "./pages/StageDetail";
import { TracePage } from "./pages/Trace";

// SalesOps is the functional front-end. Admin surfaces — Integrations,
// Notifications, Ops Logs, Users, Continuous Learning, Models, Application
// Governance — live in the ZBrain Orchestrator app at
// /keysight-salesops-governance/. The only Settings route kept here is the
// per-operator User Profile.

function OrchestratorRedirect({ path }: { path: string }) {
  if (typeof window !== "undefined") {
    window.location.replace(governanceUrl(path));
  }
  return (
    <div className="p-8 text-sm text-zbrain-muted">
      Redirecting to the ZBrain Orchestrator…
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/solution" element={<SolutionDocPage />} />
      <Route path="/solution-overview" element={<SolutionOverviewPage />} />
      <Route
        path="/*"
        element={
          <Layout>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/trace/:pipelineId" element={<TracePage />} />
              <Route path="/trace" element={<TracePage />} />
              <Route path="/hitl" element={<HitlPage />} />
              <Route path="/aioa" element={<AIOAQueuePage />} />
              <Route path="/errors" element={<ErrorsPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/analytics/stage/:stageKey" element={<StageDetailPage />} />
              <Route path="/analytics/stage" element={<Navigate to="/analytics/stage/intake" replace />} />
              <Route path="/analytics/process-flow" element={<ProcessFlowPage />} />
              <Route path="/kb" element={<KnowledgeBasePage />} />
              <Route path="/test-corpus" element={<TestCorpusPage />} />

              {/* User profile stays on the functional front-end. Every other
                  /settings/* path is now owned by the Orchestrator. */}
              <Route path="/settings" element={<SettingsLayout />}>
                <Route index element={<Navigate to="user-profile" replace />} />
                <Route path="user-profile" element={<UserProfileSection />} />
              </Route>

              {/* Hard redirects out to the Orchestrator for routes that
                  moved. Anyone with an old bookmark lands in the right
                  place instead of a 404. */}
              <Route path="/settings/integrations" element={<OrchestratorRedirect path="integrations" />} />
              <Route path="/settings/connections"  element={<OrchestratorRedirect path="integrations" />} />
              <Route path="/settings/notifications" element={<OrchestratorRedirect path="settings/notifications" />} />
              <Route path="/settings/ops-log"      element={<OrchestratorRedirect path="settings/ops-logs" />} />
              <Route path="/learning"              element={<OrchestratorRedirect path="learning" />} />
              <Route path="/feedback"              element={<OrchestratorRedirect path="learning?tab=feedback" />} />
              <Route path="/ops"                   element={<OrchestratorRedirect path="settings/ops-logs" />} />
              <Route path="/mailboxes"             element={<OrchestratorRedirect path="integrations" />} />

              <Route path="/data" element={<Navigate to="/inbox" replace />} />
              <Route path="/data/*" element={<Navigate to="/inbox" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </Layout>
        }
      />
    </Routes>
  );
}
