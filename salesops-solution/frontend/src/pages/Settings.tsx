import { Outlet } from "react-router-dom";

/**
 * SalesOps Settings is now a thin pass-through. The only first-class
 * surface here is the per-operator User Profile. Admin-scope surfaces
 * (Integrations, Notifications, Ops Logs, Models, Continuous Learning,
 * Application Governance, Appearance) live in the ZBrain Orchestrator at
 * /keysight-salesops-governance/.
 *
 * The previous sidebar (workspace configuration + admin links) is gone:
 * with just one section there is nothing to navigate, and admin links
 * belong in the Orchestrator, not in the functional front-end.
 */
export function SettingsLayout() {
  return (
    <div className="max-w-3xl mx-auto">
      <Outlet />
    </div>
  );
}
