import { useState, useEffect, useRef } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { useAppearance, resolveLogo } from "../lib/appearance";
import { OperatorPicker } from "./OperatorPicker";

/**
 * ZBrain Orchestrator & Governance shell.
 *
 * Three-column composition: a collapsible left rail of top-level sections,
 * an optional sub-rail listing the active section's child pages, and the
 * main content area. The header carries the ZBrain wordmark and the project
 * picker. Visually paired with the SalesOps front-end so an operator
 * switching apps stays in the same visual system.
 */

type IconC = (p: { className?: string }) => React.ReactElement;

type NavChild = { to: string; label: string };
type NavSection = {
  key: string;
  label: string;
  icon: IconC;
  path: string;            // landing path when the rail icon is clicked
  matchPrefix: string;     // pathname prefix that marks this section active
  children?: NavChild[];
};

const NAV: NavSection[] = [
  {
    key: "governance",
    label: "Application Governance",
    icon: IconShield,
    path: "/governance/overview",
    matchPrefix: "/governance",
    children: [
      { to: "/governance/overview",   label: "Overview" },
      { to: "/governance/audit",      label: "Audit Trail" },
      { to: "/governance/agents",     label: "Agent Fleet" },
      { to: "/governance/policies",   label: "Policy Engine" },
      { to: "/governance/compliance", label: "Compliance" },
      { to: "/governance/slo",        label: "SLO Monitor" },
    ],
  },
  {
    key: "integrations",
    label: "Integrations",
    icon: IconPlug,
    path: "/integrations",
    matchPrefix: "/integrations",
  },
  {
    key: "learning",
    label: "Continuous Learning",
    icon: IconLearning,
    path: "/learning",
    matchPrefix: "/learning",
  },
  {
    key: "models",
    label: "Models",
    icon: IconChip,
    path: "/models",
    matchPrefix: "/models",
  },
  {
    key: "settings",
    label: "Settings",
    icon: IconGear,
    path: "/settings/notifications",
    matchPrefix: "/settings",
    children: [
      { to: "/settings/notifications", label: "Notifications" },
      { to: "/settings/ops-logs",      label: "Ops Logs" },
      { to: "/settings/users",         label: "Users" },
      { to: "/settings/appearance",    label: "Appearance" },
    ],
  },
];

const PROJECTS = [
  { id: "keysight-salesops", label: "Project Keysight · SalesOps" },
];

const RAIL_PREF_KEY = "zbrain-orchestrator:rail-expanded";

export function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  const active = NAV.find((s) => loc.pathname.startsWith(s.matchPrefix)) || NAV[0];

  const [railExpanded, setRailExpanded] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(RAIL_PREF_KEY);
      return v === null ? true : v === "1";
    } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem(RAIL_PREF_KEY, railExpanded ? "1" : "0"); } catch { /* noop */ }
  }, [railExpanded]);

  return (
    <div className="min-h-screen flex flex-col bg-zbrain-surface dark:bg-zbrain-dark">
      <Header />
      <div className="flex-1 flex">
        {/* Left rail */}
        <aside
          className={[
            "shrink-0 bg-white dark:bg-zbrain-dark-elev1 border-r border-zbrain-divider dark:border-zbrain-dark-divider flex flex-col py-3 transition-[width] duration-150 ease-out",
            railExpanded ? "w-[244px]" : "w-[64px]",
          ].join(" ")}
        >
          {/* Collapse / expand toggle. Icon-only by design; tooltip carries the label. */}
          <div className={[
            "flex mb-2",
            railExpanded ? "justify-end pr-2" : "justify-center",
          ].join(" ")}>
            <button
              type="button"
              onClick={() => setRailExpanded((v) => !v)}
              className="h-8 w-8 inline-flex items-center justify-center rounded-md text-zbrain-muted dark:text-zbrain-dark-muted hover:text-zbrain-ink dark:hover:text-zbrain-dark-ink hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2 transition-colors"
              title={railExpanded ? "Collapse navigation" : "Expand navigation"}
              aria-label={railExpanded ? "Collapse navigation" : "Expand navigation"}
            >
              <IconCollapse expanded={railExpanded} />
            </button>
          </div>

          <nav className="flex flex-col gap-1 px-2">
            {NAV.map((s) => {
              const Icon = s.icon;
              const isActive = loc.pathname.startsWith(s.matchPrefix);
              return (
                <NavLink
                  key={s.key}
                  to={s.path}
                  title={!railExpanded ? s.label : undefined}
                  className={[
                    "h-10 inline-flex items-center rounded-md transition-colors",
                    railExpanded ? "px-3 gap-3" : "justify-center",
                    isActive
                      ? "bg-zbrain text-white dark:bg-zbrain-dark-accent"
                      : "text-zbrain-muted hover:text-zbrain-ink hover:bg-zbrain-50 dark:text-zbrain-dark-muted dark:hover:text-zbrain-dark-ink dark:hover:bg-zbrain-dark-elev2",
                  ].join(" ")}
                  aria-label={s.label}
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  {railExpanded && <span className="text-[13px] font-medium truncate">{s.label}</span>}
                </NavLink>
              );
            })}
          </nav>
        </aside>

        {/* Sub-rail (children of current section) */}
        {active.children && active.children.length > 0 && (
          <aside className="w-[220px] shrink-0 bg-white dark:bg-zbrain-dark-elev1 border-r border-zbrain-divider dark:border-zbrain-dark-divider px-3 py-4">
            <div className="px-3 pb-2 mb-1 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
              <div className="text-[13px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
                {active.label}
              </div>
            </div>
            <nav className="flex flex-col gap-0.5 mt-2">
              {active.children.map((c) => (
                <NavLink
                  key={c.to}
                  to={c.to}
                  end
                  className={({ isActive }) =>
                    [
                      "px-3 py-1.5 rounded-md text-[13px] font-medium",
                      isActive
                        ? "bg-zbrain-50 text-zbrain dark:bg-zbrain-dark-elev2 dark:text-zbrain-dark-accent"
                        : "text-zbrain-ink/80 hover:text-zbrain-ink hover:bg-zbrain-50/60 dark:text-zbrain-dark-ink/80 dark:hover:bg-zbrain-dark-elev2/70",
                    ].join(" ")
                  }
                >
                  {c.label}
                </NavLink>
              ))}
            </nav>
          </aside>
        )}

        {/* Main */}
        <main className="flex-1 min-w-0">
          <div className="max-w-[1400px] mx-auto px-6 py-6 min-w-0 overflow-x-hidden">{children}</div>
        </main>
      </div>
    </div>
  );
}

function Header() {
  // The Orchestrator is the ZBrain platform admin. Its own header is fixed
  // to the ZBrain wordmark on every project; only the SalesOps front-end is
  // re-brandable via Settings → Appearance.
  return (
    <header className="sticky top-0 z-30 bg-white/85 dark:bg-zbrain-dark-elev1/85 backdrop-blur-md border-b border-zbrain-divider dark:border-zbrain-dark-divider">
      <div className="max-w-[1600px] mx-auto px-5 h-14 flex items-center gap-4">
        <div className="flex items-center gap-3 shrink-0">
          <img
            src={`${import.meta.env.BASE_URL}zbrain-logo.svg`}
            alt="ZBrain"
            className="h-5 w-auto block"
          />
          <span className="text-zbrain-muted/60 dark:text-zbrain-dark-muted/50 text-sm select-none">|</span>
          <span className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink tracking-tight whitespace-nowrap">
            Orchestrator &amp; Governance
          </span>
        </div>

        <ProjectPicker />

        <div className="ml-auto flex items-center gap-2 shrink-0">
          <OperatorPicker />
          <span
            className="hidden lg:inline-flex items-center px-2 py-0.5 rounded-full bg-zbrain-50 text-zbrain text-[10px] uppercase tracking-[0.12em] font-semibold dark:bg-zbrain-dark-elev2 dark:text-zbrain-dark-accent"
            title="Admin back-end for ZBrain Solutions. The SalesOps app is the functional front-end."
          >
            Admin · Backend
          </span>
        </div>
      </div>
    </header>
  );
}

function ProjectPicker() {
  const [open, setOpen] = useState(false);
  const [project, setProject] = useState(PROJECTS[0]);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 px-3 h-8 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2 text-[13px] font-medium text-zbrain-ink dark:text-zbrain-dark-ink"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
        <span className="truncate max-w-[260px]">{project.label}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="opacity-60">
          <path d="M3 4.5 6 7.5 9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 w-[300px] rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 shadow-lg z-40">
          <div className="px-3 py-2 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
            <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">
              Projects
            </div>
          </div>
          <ul className="py-1" role="listbox">
            {PROJECTS.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => { setProject(p); setOpen(false); }}
                  className={[
                    "w-full text-left px-3 py-2 text-[13px] hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2",
                    p.id === project.id ? "text-zbrain dark:text-zbrain-dark-accent font-semibold" : "text-zbrain-ink dark:text-zbrain-dark-ink",
                  ].join(" ")}
                  role="option"
                  aria-selected={p.id === project.id}
                >
                  <div className="flex items-center gap-2">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    <span>{p.label}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
          <div className="px-3 py-2 border-t border-zbrain-divider dark:border-zbrain-dark-divider">
            <span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">
              Multi-project scope is on the platform roadmap.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Icons ──────────────────────────────────────────────────────────────

function IconShield({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6l8-3z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}
function IconPlug({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 2v4M15 2v4" />
      <rect x="6" y="6" width="12" height="8" rx="2" />
      <path d="M12 14v4a3 3 0 0 0 3 3" />
    </svg>
  );
}
// Continuous Learning — a refresh loop with a small spark to suggest a
// feedback cycle that keeps improving. Replaces the old "brain" outline.
function IconLearning({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 12a8 8 0 0 1 14-5.3" />
      <path d="M20 12a8 8 0 0 1-14 5.3" />
      <path d="M18 3v4h-4" />
      <path d="M6 21v-4h4" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}
function IconChip({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 10h6v4H9z" />
      <path d="M9 2v3M12 2v3M15 2v3M9 19v3M12 19v3M15 19v3M2 9h3M2 12h3M2 15h3M19 9h3M19 12h3M19 15h3" />
    </svg>
  );
}
function IconGear({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M2 12h3M19 12h3M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12" />
    </svg>
  );
}
function IconCollapse({ expanded }: { expanded: boolean }) {
  // Double-chevron: points left when expanded (to collapse) and right when collapsed (to expand).
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {expanded ? (
        <>
          <path d="m15 6-6 6 6 6" />
          <path d="m9 6-6 6 6 6" opacity="0.55" />
        </>
      ) : (
        <>
          <path d="m9 6 6 6-6 6" />
          <path d="m15 6 6 6-6 6" opacity="0.55" />
        </>
      )}
    </svg>
  );
}
