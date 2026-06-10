import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../api";
import { useAppearance, resolveLogo } from "../lib/appearance";
import { NotificationBell } from "./NotificationBell";
import { OperatorPicker } from "./OperatorPicker";
import { ReadinessBanner } from "./ReadinessBanner";
import { ReadinessContext, useReadinessProvider } from "../hooks/useReadiness";

// SalesOps front-end nav: functional-only entries. Continuous Learning,
// Integrations, Notifications, Models, and Application Governance live in
// the ZBrain Orchestrator (admin back-end) and are reached via the
// "Orchestrator" launcher in the right-hand utility cluster below.
const NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/inbox", label: "Inbox" },
  { to: "/trace", label: "Activities" },
  { to: "/hitl", label: "HITL Queue" },
  { to: "/analytics", label: "Analytics" },
  { to: "/kb", label: "Knowledge Base" },
  { to: "/signal-graph", label: "Quality Gates" },
  // AIOA Queue and Errors are not surfaced in the top nav. Operators reach
  // AIOA via the Order Acceptance card on the Dashboard. Errors auto-retry
  // behind the scenes; the contextual banner on the Dashboard surfaces any
  // retryable cohort with a one-click "Open queue" affordance when there is
  // something to action.
];

export function Layout({ children }: { children: React.ReactNode }) {
  const [pendingHitl, setPendingHitl] = useState<number>(0);
  const readiness = useReadinessProvider();
  const appearance = useAppearance();

  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const a = await api.analytics();
        if (!cancel) setPendingHitl(a.totals.pending_hitl);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);

  return (
    <ReadinessContext.Provider value={readiness}>
      <div className="min-h-screen flex flex-col bg-zbrain-surface dark:bg-zbrain-dark">
      <ReadinessBanner />
      <header className="sticky top-0 z-30 bg-white/85 dark:bg-zbrain-dark-elev1/85 backdrop-blur-md border-b border-zbrain-divider dark:border-zbrain-dark-divider">
        <div className="max-w-[1440px] mx-auto px-5 h-14 flex items-center gap-5">
          {/* Far left: Keysight | SalesOps (driven by Appearance settings in the Orchestrator) */}
          <div className="flex items-center gap-3 shrink-0 mr-1">
            <img
              src={resolveLogo(appearance.logoUrl)}
              alt={appearance.brandName}
              className="h-6 w-auto block"
            />
            <span className="text-zbrain-muted/60 dark:text-zbrain-dark-muted/50 text-sm select-none">|</span>
            <span className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink tracking-tight whitespace-nowrap">{appearance.solutionLabel}</span>
          </div>
          {/* Center: primary nav — flex-1 so it gets the breathing room */}
          <nav className="flex-1 flex items-center gap-0.5 min-w-0 overflow-x-auto no-scrollbar">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/inbox" || n.to === "/dashboard"}
                className={({ isActive }) =>
                  ["nav-link whitespace-nowrap", isActive ? "nav-link-active" : ""].join(" ")
                }
              >
                <span className="inline-flex items-center gap-1.5">
                  {n.label}
                  {n.to === "/hitl" && pendingHitl > 0 && (
                    <span className="pill bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300 border border-amber-200/70 dark:border-amber-500/30 tabular-nums">
                      {pendingHitl}
                    </span>
                  )}
                </span>
              </NavLink>
            ))}
          </nav>
          {/* Far right: operator picker, notifications, Settings */}
          <div className="flex items-center gap-2 shrink-0">
            <OperatorPicker />
            <NotificationBell />
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                [
                  "h-9 w-9 inline-flex items-center justify-center rounded-md transition-colors",
                  isActive
                    ? "bg-zbrain-50 text-zbrain dark:bg-zbrain-dark-elev2 dark:text-zbrain-dark-accent"
                    : "text-zbrain-muted hover:text-zbrain-ink hover:bg-zbrain-50 dark:text-zbrain-dark-muted dark:hover:text-zbrain-dark-ink dark:hover:bg-zbrain-dark-elev2",
                ].join(" ")
              }
              title="User profile"
              aria-label="User profile"
            >
              <SettingsIcon />
            </NavLink>
          </div>
        </div>
      </header>
      <main className="flex-1 min-w-0">
        <div className="max-w-[1400px] mx-auto px-6 py-6 min-w-0 overflow-x-hidden">{children}</div>
      </main>
      </div>
    </ReadinessContext.Provider>
  );
}

function OrchestratorIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6l8-3z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
