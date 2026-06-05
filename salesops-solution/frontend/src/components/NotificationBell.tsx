import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { NotificationFeed, NotificationItem, api } from "../api";

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

const POLL_MS = 8000;

/**
 * Notifications center — generic operator-facing feed.
 *
 * Surfaces any alert published into `/api/notifications`: connection issues,
 * new HITL tasks, AIOA fallout, pipeline errors, KB drift, anything. The UI
 * is intentionally agnostic about which subsystem produced each row — every
 * notification carries the same shape (severity, category chip, title, body,
 * action link). When the underlying condition heals the publisher resolves
 * the row and it falls off the feed automatically.
 */
export function NotificationBell() {
  const [feed, setFeed] = useState<NotificationFeed | null>(null);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  const refresh = async () => {
    try {
      const f = await api.notifications.list({ limit: 30 });
      setFeed(f);
    } catch {
      // best-effort polling — keep the previous snapshot on transient errors
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
  const criticalCount = feed?.summary.by_severity.critical ?? 0;
  const hasCritical = criticalCount > 0;
  const badgeCount = unread > 0 ? unread : items.length;
  const showBadge = badgeCount > 0;

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

  const title = !feed
    ? "Notifications loading…"
    : items.length === 0
      ? "No notifications"
      : `${items.length} notification${items.length === 1 ? "" : "s"}${unread ? ` · ${unread} unread` : ""}`;

  return (
    <div ref={wrapperRef} className="relative">
      <button
        onClick={onOpen}
        title={title}
        aria-label={title}
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
        <div className="absolute right-0 mt-2 w-[400px] max-w-[calc(100vw-2rem)] z-50">
          <div className="card overflow-hidden border border-zbrain-divider shadow-xl">
            <div className="px-4 py-3 border-b border-zbrain-divider flex items-center justify-between bg-zbrain-surface/60">
              <div className="text-sm font-semibold text-zbrain-ink">Notifications</div>
              <div className="flex items-center gap-3 text-[11px]">
                {unread > 0 && (
                  <button onClick={onMarkAllRead} className="text-zbrain hover:underline">
                    Mark all read
                  </button>
                )}
                <span className="text-zbrain-muted">{items.length} active</span>
              </div>
            </div>

            <div className="max-h-[60vh] overflow-auto">
              {!feed && (
                <div className="px-4 py-6 text-center text-sm text-zbrain-muted">Loading…</div>
              )}
              {feed && items.length === 0 && (
                <div className="px-4 py-10 text-center">
                  <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-emerald-50 text-emerald-700 mb-2 text-lg">
                    ✓
                  </div>
                  <div className="text-sm font-medium text-zbrain-ink">You're all caught up</div>
                  <div className="text-xs text-zbrain-muted mt-1">
                    No active notifications. New alerts will appear here automatically.
                  </div>
                </div>
              )}
              {items.length > 0 && (
                <ul className="divide-y divide-zbrain-divider">
                  {items.map((n) => (
                    <li
                      key={n.id}
                      onClick={() => onRowClick(n)}
                      className={[
                        "px-4 py-3 flex items-start gap-3 cursor-pointer transition-colors",
                        n.read_at == null
                          ? "bg-zbrain-50/40 hover:bg-zbrain-50"
                          : "hover:bg-zbrain-50/60",
                      ].join(" ")}
                    >
                      <span
                        className={`inline-block w-2 h-2 rounded-full mt-1.5 shrink-0 ${SEVERITY_DOT[n.severity] || "bg-slate-400"}`}
                        title={n.severity}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`pill text-[10px] uppercase tracking-wide ${CATEGORY_TONE[n.category] || "bg-slate-100 text-slate-600"}`}>
                            {CATEGORY_LABEL[n.category] || n.category}
                          </span>
                          <span className="text-[12.5px] font-semibold text-zbrain-ink leading-tight">
                            {n.title}
                          </span>
                        </div>
                        {n.body && (
                          <div className="text-[11.5px] text-zbrain-muted mt-1 leading-snug line-clamp-3">
                            {n.body}
                          </div>
                        )}
                        <div className="text-[10px] text-zbrain-muted/80 mt-1.5 flex items-center gap-2">
                          <span>{timeAgo(n.created_at)}</span>
                          {n.action_url && n.action_label && (
                            <>
                              <span>·</span>
                              <span className="text-zbrain font-medium">{n.action_label} →</span>
                            </>
                          )}
                        </div>
                      </div>
                      {!(n.category === "connection" && n.severity === "critical") && (
                        <button
                          onClick={(e) => onDismiss(e, n)}
                          className="text-zbrain-muted/60 hover:text-zbrain-ink text-sm leading-none shrink-0 mt-0.5"
                          title="Dismiss"
                        >
                          ×
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="px-4 py-2 border-t border-zbrain-divider bg-zbrain-surface/60 flex items-center justify-end">
              <span className="text-[10px] text-zbrain-muted">Auto-refresh · {POLL_MS / 1000}s</span>
            </div>
          </div>
        </div>
      )}
    </div>
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
