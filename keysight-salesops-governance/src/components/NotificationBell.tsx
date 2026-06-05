import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { NotificationFeed, NotificationItem, NotificationSeverity, api } from "../api";
import { InfoTip } from "./InfoTip";

const CATEGORY_LABEL: Record<string, string> = {
  connection: "Connection",
  queue: "Queue",
  workflow: "Workflow",
  drift: "Drift",
  system: "System",
  learning: "Learning",
};

const CATEGORY_TONE: Record<string, string> = {
  connection: "bg-rose-50 text-rose-700",
  queue: "bg-amber-50 text-amber-800",
  workflow: "bg-violet-50 text-violet-700",
  drift: "bg-sky-50 text-sky-700",
  system: "bg-slate-100 text-slate-700",
  learning: "bg-emerald-50 text-emerald-700",
};

const SEVERITY_DOT: Record<string, string> = {
  critical: "bg-rose-500",
  warning: "bg-amber-500",
  info: "bg-slate-400",
};

const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
};

const SEVERITY_HEADER_TONE: Record<string, string> = {
  critical: "text-rose-700 bg-rose-50/70 border-rose-200",
  warning: "text-amber-800 bg-amber-50/70 border-amber-200",
  info: "text-slate-700 bg-slate-50 border-slate-200",
};

const SEVERITY_ORDER: NotificationSeverity[] = ["critical", "warning", "info"];

const COLLAPSE_THRESHOLD = 5;
const POLL_MS = 8000;

/**
 * Notifications center: operator-facing feed grouped by severity.
 *
 * Surfaces any alert published into /api/notifications (connection issues,
 * HITL tasks, AIOA fallout, pipeline errors, KB drift). The dropdown groups
 * rows by severity (critical, warning, info) so a flood of items reads as a
 * compact, ranked summary rather than a wall of text. Each group collapses
 * past the threshold and exposes a one-line summary; the row body remains
 * accessible via the action link.
 */
export function NotificationBell() {
  const [feed, setFeed] = useState<NotificationFeed | null>(null);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    critical: true,
    warning: true,
    info: false,
  });
  const [showAll, setShowAll] = useState<Record<string, boolean>>({});
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  const refresh = async () => {
    try {
      const f = await api.notifications.list({ limit: 30 });
      setFeed(f);
    } catch {
      // best-effort polling: keep the previous snapshot on transient errors
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (ev: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(ev.target as Node)) setOpen(false);
    };
    const onEsc = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const items = feed?.items || [];
  const unread = feed?.summary.unread_total ?? 0;
  const bySeverity = feed?.summary.by_severity ?? { critical: 0, warning: 0, info: 0 };
  const criticalCount = bySeverity.critical ?? 0;
  const hasCritical = criticalCount > 0;
  const badgeCount = unread > 0 ? unread : items.length;
  const showBadge = badgeCount > 0;

  // Group items by severity, preserving incoming order within each group.
  const grouped = useMemo(() => {
    const buckets: Record<string, NotificationItem[]> = { critical: [], warning: [], info: [] };
    for (const n of items) {
      const key = SEVERITY_ORDER.includes(n.severity as NotificationSeverity) ? n.severity : "info";
      (buckets[key] = buckets[key] || []).push(n);
    }
    return buckets;
  }, [items]);

  const onOpen = async () => {
    setOpen((v) => !v);
  };

  const onRowClick = async (n: NotificationItem) => {
    if (n.read_at == null) {
      try {
        await api.notifications.markRead(n.id);
      } catch {}
    }
    if (n.action_url) {
      setOpen(false);
      navigate(n.action_url);
    } else {
      refresh();
    }
  };

  const onDismiss = async (e: React.MouseEvent, n: NotificationItem) => {
    e.stopPropagation();
    try {
      await api.notifications.dismiss(n.id);
    } catch {}
    refresh();
  };

  const onMarkAllRead = async () => {
    try {
      await api.notifications.markAllRead();
    } catch {}
    refresh();
  };

  const toggleGroup = (sev: string) =>
    setExpanded((s) => ({ ...s, [sev]: !s[sev] }));

  const toggleShowAll = (sev: string) =>
    setShowAll((s) => ({ ...s, [sev]: !s[sev] }));

  const titleSummary = SEVERITY_ORDER
    .filter((s) => (bySeverity[s] ?? 0) > 0)
    .map((s) => `${bySeverity[s]} ${SEVERITY_LABEL[s].toLowerCase()}`)
    .join(" · ");

  const buttonTitle = !feed
    ? "Notifications loading"
    : items.length === 0
      ? "No notifications"
      : `${items.length} active: ${titleSummary || "no breakdown"}`;

  return (
    <div ref={wrapperRef} className="relative">
      <button
        onClick={onOpen}
        title={buttonTitle}
        aria-label={buttonTitle}
        className={[
          "h-9 w-9 inline-flex items-center justify-center rounded-md transition-colors relative",
          hasCritical
            ? "text-rose-700 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-500/10"
            : showBadge
              ? "text-amber-700 hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-500/10"
              : "text-zbrain-muted hover:text-zbrain-ink hover:bg-zbrain-50 dark:text-zbrain-dark-muted dark:hover:text-zbrain-dark-ink dark:hover:bg-zbrain-dark-elev2",
        ].join(" ")}
      >
        <BellIcon ringing={hasCritical && open === false} />
        {showBadge && (
          <span
            className={[
              "absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] px-1 inline-flex items-center justify-center rounded-full text-[10px] font-semibold tabular-nums text-white",
              hasCritical ? "bg-rose-600" : "bg-amber-500",
              "ring-2 ring-white dark:ring-zbrain-dark-elev1",
              hasCritical ? "animate-pulse" : "",
            ].join(" ")}
          >
            {badgeCount > 99 ? "99+" : badgeCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[420px] max-w-[calc(100vw-2rem)] z-50">
          <div className="card overflow-hidden border border-zbrain-divider shadow-xl">
            {/* Header: total + severity breakdown + actions */}
            <div className="px-4 py-3 border-b border-zbrain-divider bg-zbrain-surface/60">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-1.5 min-w-0">
                  <div className="text-sm font-semibold text-zbrain-ink truncate">Notifications</div>
                  <InfoTip
                    position="right"
                    text={
                      "Active alerts emitted by AGT subsystems: connection probes, HITL queue, AIOA pipelines, KB drift detector, and policy violations.\n\n" +
                      "Rows resolve automatically when the underlying condition clears. Critical rows trigger an incident commander; warnings stay in queue."
                    }
                  />
                </div>
                <div className="flex items-center gap-3 text-[11px] shrink-0">
                  {unread > 0 && (
                    <button onClick={onMarkAllRead} className="text-zbrain hover:underline">
                      Mark all read
                    </button>
                  )}
                </div>
              </div>
              {/* Severity counts strip */}
              {items.length > 0 && (
                <div className="flex items-center gap-2 mt-2 text-[11px]">
                  {SEVERITY_ORDER.map((sev) => {
                    const n = bySeverity[sev] ?? 0;
                    const active = n > 0;
                    return (
                      <span
                        key={sev}
                        className={[
                          "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border tabular-nums",
                          active ? SEVERITY_HEADER_TONE[sev] : "text-zbrain-muted bg-transparent border-zbrain-divider opacity-60",
                        ].join(" ")}
                      >
                        <span className={`inline-block w-1.5 h-1.5 rounded-full ${SEVERITY_DOT[sev]}`} />
                        <span className="font-semibold">{n}</span>
                        <span>{SEVERITY_LABEL[sev].toLowerCase()}</span>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="max-h-[60vh] overflow-auto">
              {!feed && (
                <div className="px-4 py-6 text-center text-sm text-zbrain-muted">Loading</div>
              )}

              {feed && items.length === 0 && (
                <div className="px-4 py-10 text-center">
                  <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-emerald-50 text-emerald-700 mb-2 text-lg">
                    ✓
                  </div>
                  <div className="text-sm font-medium text-zbrain-ink inline-flex items-center gap-1.5 justify-center">
                    No active notifications
                    <InfoTip
                      position="right"
                      text="Notifications are emitted by connection probes, the HITL queue, AIOA pipelines, the KB drift detector, and the policy engine. New alerts arrive here automatically and clear themselves when the underlying condition resolves."
                    />
                  </div>
                  <div className="text-xs text-zbrain-muted mt-1">
                    The feed refreshes every {POLL_MS / 1000} seconds.
                  </div>
                </div>
              )}

              {items.length > 0 && (
                <div>
                  {SEVERITY_ORDER.map((sev) => {
                    const bucket = grouped[sev] || [];
                    if (bucket.length === 0) return null;
                    const isExpanded = expanded[sev] ?? sev !== "info";
                    const showingAll = showAll[sev] ?? false;
                    const visible = showingAll ? bucket : bucket.slice(0, COLLAPSE_THRESHOLD);
                    const hidden = bucket.length - visible.length;
                    return (
                      <div key={sev} className="border-b border-zbrain-divider last:border-b-0">
                        <button
                          type="button"
                          onClick={() => toggleGroup(sev)}
                          className="w-full px-4 py-2 flex items-center justify-between gap-2 hover:bg-zbrain-50/60 transition-colors"
                          aria-expanded={isExpanded}
                        >
                          <div className="flex items-center gap-2">
                            <span className={`inline-block w-2 h-2 rounded-full ${SEVERITY_DOT[sev]}`} />
                            <span className="text-[12px] font-semibold uppercase tracking-wide text-zbrain-ink">
                              {SEVERITY_LABEL[sev]}
                            </span>
                            <span className="text-[11px] text-zbrain-muted tabular-nums">{bucket.length}</span>
                          </div>
                          <Chevron open={isExpanded} />
                        </button>
                        {isExpanded && (
                          <ul className="divide-y divide-zbrain-divider/60">
                            {visible.map((n) => (
                              <li
                                key={n.id}
                                onClick={() => onRowClick(n)}
                                className={[
                                  "px-4 py-2 flex items-center gap-2.5 cursor-pointer transition-colors",
                                  n.read_at == null ? "bg-zbrain-50/40 hover:bg-zbrain-50" : "hover:bg-zbrain-50/60",
                                ].join(" ")}
                                title={n.body || n.title}
                              >
                                <span className={`pill text-[9px] uppercase tracking-wide shrink-0 ${CATEGORY_TONE[n.category] || "bg-slate-100 text-slate-600"}`}>
                                  {CATEGORY_LABEL[n.category] || n.category}
                                </span>
                                <span className="flex-1 min-w-0 text-[12px] font-medium text-zbrain-ink truncate">
                                  {n.title}
                                </span>
                                <span className="text-[10px] text-zbrain-muted tabular-nums shrink-0">
                                  {timeAgo(n.created_at)}
                                </span>
                                {n.action_url && (
                                  <span className="text-[11px] text-zbrain font-medium shrink-0">View</span>
                                )}
                                {!(n.category === "connection" && n.severity === "critical") && (
                                  <button
                                    onClick={(e) => onDismiss(e, n)}
                                    className="text-zbrain-muted/60 hover:text-zbrain-ink text-sm leading-none shrink-0 px-1"
                                    title="Dismiss"
                                    aria-label="Dismiss"
                                  >
                                    ×
                                  </button>
                                )}
                              </li>
                            ))}
                            {hidden > 0 && (
                              <li className="px-4 py-1.5 bg-zbrain-surface/40">
                                <button
                                  type="button"
                                  onClick={() => toggleShowAll(sev)}
                                  className="text-[11px] text-zbrain hover:underline font-medium"
                                >
                                  Show {hidden} more
                                </button>
                              </li>
                            )}
                            {showingAll && bucket.length > COLLAPSE_THRESHOLD && (
                              <li className="px-4 py-1.5 bg-zbrain-surface/40">
                                <button
                                  type="button"
                                  onClick={() => toggleShowAll(sev)}
                                  className="text-[11px] text-zbrain hover:underline font-medium"
                                >
                                  Show fewer
                                </button>
                              </li>
                            )}
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="px-4 py-2 border-t border-zbrain-divider bg-zbrain-surface/60 flex items-center justify-between">
              <span className="text-[10px] text-zbrain-muted">{items.length} active</span>
              <span className="text-[10px] text-zbrain-muted">Auto refresh, {POLL_MS / 1000}s</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`text-zbrain-muted transition-transform ${open ? "rotate-180" : ""}`}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

function BellIcon({ ringing }: { ringing?: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={ringing ? "animate-[wiggle_1s_ease-in-out_infinite]" : ""}
    >
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "-";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
