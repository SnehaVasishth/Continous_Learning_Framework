import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, EmailAccount, EmailDetail, EmailFilter, EmailSummary, EmailThread } from "../api";
import { useReadiness } from "../hooks/useReadiness";
import { ConfidenceBar, IntentPill, LangPill, StatusPill, TierPill } from "../components/Pills";
import { Chip, PageHeader } from "../components/ui";
import { attachmentUrl, PreviewItem, PreviewModal } from "../components/PreviewModal";
import { integrationsUrl } from "../lib/governanceUrl";
// Mailbox connections moved to the ZBrain Orchestrator (admin back-end).
// The Inbox now deep-links there instead of hosting the connect modal.

const INTENT_LABELS: Record<string, string> = {
  po_intake: "PO intake",
  quote_to_order: "Quote → Order",
  hold_release: "Hold release",
  delivery_change: "Delivery change",
  service_order: "Service order",
  wo_status_inquiry: "WO status",
  general_inquiry: "Inquiry",
  spam: "Spam",
};

const TIER_LABELS: Record<string, string> = {
  L4_AUTO: "L4 · Auto",
  L3_ONE_CLICK: "L3 · One-click",
  L2_HITL: "L2 · HITL",
};

const PROVIDER_CHIP: Record<string, { icon: string; bg: string; label: string }> = {
  gmail: { icon: "G", bg: "bg-rose-100 text-rose-700", label: "Gmail" },
  outlook: { icon: "O", bg: "bg-sky-100 text-sky-700", label: "Outlook" },
  imap: { icon: "@", bg: "bg-slate-200 text-slate-700", label: "IMAP" },
};

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const ts = new Date(iso).getTime();
  if (isNaN(ts)) return "-";
  const diff = Date.now() - ts;
  // Future timestamps (synthetic data or clock skew) — show the absolute
  // date+time so the row never lies with "just now".
  if (diff < 0) {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  }
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  if (diff < 7 * 86_400_000) return `${Math.round(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
}

function domainOf(addr: string): string {
  const m = (addr || "").match(/@([^>\s]+)/);
  return m ? m[1].toLowerCase() : "";
}

function providerForFrom(from: string, accounts: EmailAccount[]): "gmail" | "outlook" | "imap" {
  const dom = domainOf(from);
  if (!dom) return "imap";
  if (dom === "gmail.com" || dom === "googlemail.com") return "gmail";
  if (dom === "outlook.com" || dom === "hotmail.com" || dom === "live.com") return "outlook";
  for (const acc of accounts) {
    const accDom = domainOf(acc.email_address);
    if (accDom && accDom === dom) {
      const p = (acc.provider || "imap").toLowerCase();
      if (p === "gmail" || p === "outlook") return p;
      return "imap";
    }
  }
  return "imap";
}

export function InboxPage() {
  const [params, setParams] = useSearchParams();
  const intent = params.get("intent") || "";
  const language = params.get("language") || "";
  const tier = params.get("autonomy_tier") || "";
  const status = params.get("status") || "all";

  const { report: readinessReport } = useReadiness();
  const systemReady = !!readinessReport && readinessReport.ok === true;
  const readinessTooltip = readinessReport && !readinessReport.ok
    ? `System not ready: ${readinessReport.blockers.map((b) => b.title).join(" · ")}. Reconnect in Settings → Integrations.`
    : undefined;

  const [rows, setRows] = useState<EmailSummary[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [running, setRunning] = useState<Set<number>>(new Set());
  const [fetchingMail, setFetchingMail] = useState(false);
  const [search, setSearch] = useState<string>("");
  const [newMailFlash, setNewMailFlash] = useState(0);
  const [detailEmailId, setDetailEmailId] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewItem | null>(null);

  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [mailboxesExpanded, setMailboxesExpanded] = useState<boolean | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [fetchMenuOpen, setFetchMenuOpen] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const fetchMenuRef = useRef<HTMLDivElement | null>(null);

  const navigate = useNavigate();

  const filter = useMemo<EmailFilter>(
    () => ({
      intent: intent || undefined,
      language: language || undefined,
      autonomy_tier: tier || undefined,
      status: status !== "all" ? status : undefined,
    }),
    [intent, language, tier, status]
  );

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const [data, c] = await Promise.all([
        api.listEmails(filter),
        api.emailCounts().catch(() => ({} as Record<string, number>)),
      ]);
      if (!cancelled) {
        setRows(data);
        setCounts(c);
      }
    };
    load();
    const id = setInterval(load, 300000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [filter]);

  useEffect(() => {
    let cancelled = false;
    const loadAccounts = async () => {
      try {
        const data = await api.emailAccounts.list();
        if (!cancelled) {
          setAccounts(data);
          setAccountsLoaded(true);
        }
      } catch {
        if (!cancelled) setAccountsLoaded(true);
      }
    };
    loadAccounts();
    const id = setInterval(loadAccounts, 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (mailboxesExpanded !== null || !accountsLoaded) return;
    setMailboxesExpanded(accounts.length === 0);
  }, [accountsLoaded, accounts.length, mailboxesExpanded]);

  useEffect(() => {
    const es = new EventSource("/api/email-accounts/events");
    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "new_emails" && Array.isArray(msg.ids) && msg.ids.length > 0) {
          api.listEmails(filter).then(setRows);
          setNewMailFlash((n) => n + msg.ids.length);
          setTimeout(() => setNewMailFlash(0), 4000);
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => es.close();
  }, [filter]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!fetchMenuRef.current) return;
      if (!fetchMenuRef.current.contains(e.target as Node)) setFetchMenuOpen(false);
    };
    if (fetchMenuOpen) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [fetchMenuOpen]);

  const reloadAccounts = async () => {
    const data = await api.emailAccounts.list();
    setAccounts(data);
  };

  const onFetchAll = async () => {
    setFetchingMail(true);
    setFetchMenuOpen(false);
    try {
      const res = await api.emailAccounts.refreshAll();
      const total = res.results.reduce((a, r) => a + r.new, 0);
      if (total > 0) {
        setNewMailFlash(total);
        setTimeout(() => setNewMailFlash(0), 4000);
      }
      const data = await api.listEmails(filter);
      setRows(data);
      await reloadAccounts();
    } finally {
      setFetchingMail(false);
    }
  };

  const onFetchOne = async (id: number) => {
    setRefreshingId(id);
    setFetchMenuOpen(false);
    try {
      const res = await api.emailAccounts.refresh(id);
      if (res.ok && res.new_email_ids.length > 0) {
        setNewMailFlash(res.new_email_ids.length);
        setTimeout(() => setNewMailFlash(0), 4000);
      }
      const data = await api.listEmails(filter);
      setRows(data);
      await reloadAccounts();
    } finally {
      setRefreshingId(null);
    }
  };

  const onToggleAccount = async (id: number) => {
    await api.emailAccounts.toggle(id);
    await reloadAccounts();
  };

  const onRemoveAccount = async (id: number, email: string) => {
    if (!confirm(`Disconnect ${email}? Already-imported emails stay in the inbox.`)) return;
    await api.emailAccounts.remove(id);
    await reloadAccounts();
  };

  const onRun = async (e: EmailSummary) => {
    setRunning((s) => new Set(s).add(e.id));
    try {
      const { pipeline_id } = await api.runPipeline(e.id);
      navigate(`/trace/${pipeline_id}`);
    } catch (err: any) {
      // The backend refuses with HTTP 412 + structured readiness payload when
      // Salesforce / SharePoint / mailbox aren't connected. Surface that to
      // the operator instead of failing silently.
      const msg = (err && (err.message || String(err))) || "Pipeline run failed";
      if (typeof window !== "undefined") {
        alert(
          msg.includes("412") || msg.toLowerCase().includes("blocker")
            ? "System not ready: Salesforce, SharePoint, or the mailbox is disconnected. Open Settings → Integrations to reconnect."
            : msg
        );
      }
    } finally {
      setRunning((s) => {
        const n = new Set(s);
        n.delete(e.id);
        return n;
      });
    }
  };

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value && value !== "all") next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const clearAllFilters = () => setParams({}, { replace: true });

  const term = search.trim().toLowerCase();
  const filtered = rows.filter((r) => {
    if (!term) return true;
    return (
      r.subject.toLowerCase().includes(term) ||
      (r.from || "").toLowerCase().includes(term) ||
      (r.customer_name || "").toLowerCase().includes(term)
    );
  });

  const activeFilterChips: { label: string; key: string }[] = [];
  if (intent) activeFilterChips.push({ label: `Intent: ${INTENT_LABELS[intent] || intent}`, key: "intent" });
  if (language) activeFilterChips.push({ label: `Language: ${language.toUpperCase()}`, key: "language" });
  if (tier) activeFilterChips.push({ label: `Tier: ${TIER_LABELS[tier] || tier}`, key: "autonomy_tier" });

  const activeMailboxCount = accounts.filter((a) => a.is_active).length;
  const expanded = mailboxesExpanded ?? false;
  const hasMailboxes = accounts.length > 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Inbox"
        subtitle="Customer email arriving from connected mailboxes. Open any message as a case to run it through the six processing stages, or open the thread to see its full conversation context."
        badges={
          <Chip tone={rows.length > 0 ? "info" : "neutral"}>
            {rows.length} {rows.length === 1 ? "message" : "messages"}
          </Chip>
        }
      />

      <div className="grid grid-cols-12 gap-5">
      <div className="col-span-12 space-y-4">
        <div className="card overflow-hidden">
          <div className="flex items-center gap-3 px-4 py-3">
            <button
              onClick={() => setMailboxesExpanded((v) => !(v ?? false))}
              className="flex items-center gap-2 flex-1 min-w-0 text-left"
              aria-expanded={expanded}
            >
              <span className="text-zbrain-muted text-sm">{expanded ? "▾" : "▸"}</span>
              <span className="font-medium text-zbrain-ink">Connected mailboxes</span>
              <span className="pill bg-zbrain-50 text-zbrain">
                {activeMailboxCount} active{accounts.length !== activeMailboxCount ? ` · ${accounts.length} total` : ""}
              </span>
            </button>
            {/* === v1.1 Inbox === Add mailbox lives in Settings → Connections, not here. */}
          </div>

          {expanded && (
            <div className="border-t border-zbrain-divider divide-y divide-zbrain-divider">
              {accounts.length === 0 ? (
                <div className="p-5 text-center">
                  <div className="text-sm font-medium text-zbrain-ink">No mailboxes connected yet</div>
                  <div className="text-xs text-zbrain-muted mt-1">
                    Add a Gmail / Outlook / IMAP mailbox in the{" "}
                    <a
                      href={integrationsUrl()}
                      className="text-zbrain underline hover:text-zbrain-600"
                    >
                      ZBrain Orchestrator → Integrations
                    </a>
                    .
                  </div>
                </div>
              ) : (
                accounts.map((a) => {
                  const chip = PROVIDER_CHIP[a.provider] || PROVIDER_CHIP.imap;
                  const dotColor = a.last_error
                    ? "bg-rose-500"
                    : a.is_active
                    ? "bg-emerald-500"
                    : "bg-slate-400";
                  return (
                    <div key={a.id} className="px-4 py-3 flex items-center gap-3">
                      <div
                        className={`w-8 h-8 rounded-md flex items-center justify-center text-sm font-semibold ${chip.bg}`}
                        title={chip.label}
                      >
                        {chip.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${dotColor}`} aria-hidden />
                          <span className="text-sm font-medium truncate">{a.email_address}</span>
                          {!a.is_active && <span className="pill bg-slate-200 text-slate-700">Paused</span>}
                        </div>
                        <div className="text-xs text-zbrain-muted mt-0.5 flex items-center gap-2 flex-wrap">
                          <span>last sync {relativeTime(a.last_synced_at)}</span>
                          <span>·</span>
                          <span>imported {a.messages_imported}</span>
                          {a.last_error && (
                            <>
                              <span>·</span>
                              <span className="text-rose-700 truncate max-w-xs" title={a.last_error}>
                                {a.last_error}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          onClick={() => onFetchOne(a.id)}
                          disabled={refreshingId === a.id}
                          className="btn-secondary text-xs"
                          title="Fetch this mailbox now"
                        >
                          {refreshingId === a.id ? "…" : "↻"}
                        </button>
                        <button
                          onClick={() => onToggleAccount(a.id)}
                          className="btn-secondary text-xs"
                          title={a.is_active ? "Pause polling" : "Resume polling"}
                        >
                          {a.is_active ? "Pause" : "Resume"}
                        </button>
                        <button
                          onClick={() => onRemoveAccount(a.id, a.email_address)}
                          className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
                          title="Disconnect"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>

        <div className="card overflow-hidden">
          <div className="flex items-center justify-between p-4 border-b border-zbrain-divider">
            <div>
              <h1 className="text-lg font-semibold">Inbound Email Queue</h1>
              <p className="text-sm text-zbrain-muted">
                Synthetic customer requests across PO, Q2O, holds, deliveries, and service.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {newMailFlash > 0 && (
                <span className="pill bg-emerald-100 text-emerald-700 animate-pulse">+{newMailFlash} new</span>
              )}
              <div ref={fetchMenuRef} className="relative inline-flex">
                <button
                  onClick={onFetchAll}
                  disabled={fetchingMail || accounts.length === 0}
                  className="btn-primary rounded-r-none"
                  title={accounts.length === 0 ? "Connect a mailbox first" : "Fetch new mail from all mailboxes"}
                >
                  {fetchingMail ? "Fetching…" : "Fetch new mail"}
                </button>
                <button
                  onClick={() => setFetchMenuOpen((v) => !v)}
                  disabled={fetchingMail || accounts.length === 0}
                  className="btn-primary rounded-l-none border-l border-white/30 px-2"
                  aria-label="Fetch options"
                >
                  ▾
                </button>
                {fetchMenuOpen && (
                  <div className="absolute right-0 top-full mt-1 w-64 bg-white border border-zbrain-divider rounded-md shadow-lg z-20">
                    <div className="px-3 py-2 text-xs uppercase tracking-wider text-zbrain-muted border-b border-zbrain-divider">
                      Fetch a single mailbox
                    </div>
                    <div className="max-h-64 overflow-auto">
                      {accounts.map((a) => {
                        const chip = PROVIDER_CHIP[a.provider] || PROVIDER_CHIP.imap;
                        return (
                          <button
                            key={a.id}
                            onClick={() => onFetchOne(a.id)}
                            disabled={refreshingId === a.id}
                            className="w-full px-3 py-2 text-left text-sm hover:bg-zbrain-50 flex items-center gap-2"
                          >
                            <span
                              className={`w-5 h-5 rounded text-xs flex items-center justify-center font-semibold ${chip.bg}`}
                            >
                              {chip.icon}
                            </span>
                            <span className="flex-1 truncate">{a.email_address}</span>
                            <span className="text-xs text-zbrain-muted">
                              {refreshingId === a.id ? "…" : "Fetch"}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search subject, sender, customer…"
                className="border border-zbrain-divider rounded-md text-sm px-2 py-1.5 bg-white w-60"
              />
              <select
                value={status}
                onChange={(e) => updateParam("status", e.target.value)}
                className="border border-zbrain-divider rounded-md text-sm px-2 py-1.5 bg-white"
              >
                {(() => {
                  // Statuses surfaced in the dropdown. `ALWAYS_SHOW` entries
                  // render even when their count is zero so an operator can
                  // route to an empty queue intentionally. The remaining
                  // entries (`processing`, `rejected`) only render when the
                  // current corpus has at least one row in that state, to
                  // avoid baking dead options like "Rejected (0)" into the UI.
                  const ALWAYS_SHOW = new Set([
                    "all",
                    "new",
                    "awaiting_hitl",
                    "awaiting_aioa",
                    "processed",
                    "redirected",
                    "discarded",
                  ]);
                  const OPTIONS = [
                    { value: "all", label: "All status" },
                    { value: "new", label: "New" },
                    { value: "processing", label: "Processing" },
                    { value: "awaiting_hitl", label: "Awaiting HITL" },
                    { value: "awaiting_aioa", label: "Awaiting AIOA" },
                    { value: "processed", label: "Processed" },
                    { value: "rejected", label: "Rejected" },
                    { value: "discarded", label: "Discarded" },
                    { value: "redirected", label: "Redirected" },
                  ];
                  return OPTIONS.filter((opt) => {
                    if (ALWAYS_SHOW.has(opt.value)) return true;
                    return (counts[opt.value] ?? 0) > 0;
                  }).map((opt) => {
                    const n = counts[opt.value];
                    return (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                        {typeof n === "number" ? ` (${n})` : ""}
                      </option>
                    );
                  });
                })()}
              </select>
            </div>
          </div>

          {activeFilterChips.length > 0 && (
            <div className="px-4 py-2 bg-zbrain-50/40 border-b border-zbrain-divider flex items-center gap-2 flex-wrap">
              <span className="text-xs uppercase tracking-wider text-zbrain-muted">Filters:</span>
              {activeFilterChips.map((c) => (
                <button
                  key={c.key}
                  onClick={() => updateParam(c.key, "")}
                  className="pill bg-zbrain text-white hover:bg-zbrain-600"
                >
                  {c.label} ✕
                </button>
              ))}
              <button onClick={clearAllFilters} className="text-xs text-zbrain hover:underline">
                clear all
              </button>
            </div>
          )}

          <div className="divide-y divide-zbrain-divider max-h-[calc(100vh-320px)] overflow-auto">
            {accountsLoaded && !hasMailboxes && filtered.length === 0 ? (
              <div className="p-10 text-center">
                <div className="inline-flex w-12 h-12 rounded-full bg-zbrain-50 text-zbrain items-center justify-center text-xl mb-3">
                  ✉
                </div>
                <div className="text-base font-medium text-zbrain-ink">
                  Connect a mailbox to start ingesting customer email
                </div>
                <div className="text-sm text-zbrain-muted mt-1 max-w-md mx-auto">
                  Gmail, Outlook, or any IMAP mailbox. New mail is fetched automatically and queued for the agent
                  fabric to process.
                </div>
                <a
                  href={integrationsUrl()}
                  className="btn-primary mt-4"
                >
                  Open Orchestrator → Integrations
                </a>
              </div>
            ) : (
              <>
                {filtered.map((r) => {
                  const provKey = providerForFrom(r.from, accounts);
                  const chip = PROVIDER_CHIP[provKey];
                  const hasPipeline = !!r.pipeline?.id;
                  return (
                    <div
                      key={r.id}
                      onClick={() => setDetailEmailId(r.id)}
                      className="w-full text-left p-4 hover:bg-zbrain-50/60 transition-colors cursor-pointer"
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold shrink-0 ${chip.bg}`}
                          title={chip.label}
                        >
                          {chip.icon}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-medium truncate">{r.subject}</div>
                          <div className="text-xs text-zbrain-muted truncate mt-0.5">
                            {r.customer_name ? `${r.customer_name} · ` : ""}
                            {r.from}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {r.received_at && (
                            <span
                              className="text-[11px] text-zbrain-muted tabular-nums whitespace-nowrap"
                              title={new Date(r.received_at).toLocaleString()}
                            >
                              {relativeTime(r.received_at)}
                            </span>
                          )}
                          {r.attachments.length > 0 && (
                            <span className="pill bg-slate-100 text-slate-700">{r.attachments.length} attachment{r.attachments.length === 1 ? "" : "s"}</span>
                          )}
                          <StatusPill status={r.status} />
                          {hasPipeline ? (
                            <button
                              onClick={(ev) => {
                                ev.stopPropagation();
                                navigate(`/trace/${r.pipeline!.id}`);
                              }}
                              className="btn-secondary text-xs"
                              title="View activity for this email"
                            >
                              View activity
                            </button>
                          ) : (
                            <button
                              onClick={(ev) => {
                                ev.stopPropagation();
                                onRun(r);
                              }}
                              disabled={running.has(r.id) || r.status === "processing" || !systemReady}
                              className="btn-primary text-xs disabled:opacity-50 disabled:cursor-not-allowed"
                              title={readinessTooltip || "Process this customer request through the 6-stage automation"}
                            >
                              {running.has(r.id) ? "Running…" : !systemReady ? "Blocked" : "Process"}
                            </button>
                          )}
                        </div>
                      </div>
                      {r.pipeline && (
                        <div className="mt-2 ml-10 flex items-center gap-2">
                          <IntentPill intent={r.pipeline.intent} />
                          <LangPill lang={r.pipeline.language} />
                          <TierPill tier={r.pipeline.autonomy_tier} />
                          <ConfidenceBar value={r.pipeline.confidence} />
                        </div>
                      )}
                    </div>
                  );
                })}
                {filtered.length === 0 && hasMailboxes && (
                  <div className="p-8 text-center text-zbrain-muted text-sm">
                    No emails match the current filter.
                  </div>
                )}
              </>
            )}
          </div>

          <div className="px-4 py-2 border-t border-zbrain-divider text-xs text-zbrain-muted text-center">
            Auto-refreshes every 5 minutes. Use Fetch new mail for an immediate poll.
          </div>
        </div>
      </div>

      {detailEmailId != null && (
        <EmailDetailModal
          emailId={detailEmailId}
          summary={rows.find((x) => x.id === detailEmailId) || null}
          onClose={() => setDetailEmailId(null)}
          onRun={(e) => {
            setDetailEmailId(null);
            onRun(e);
          }}
          running={running.has(detailEmailId)}
          systemReady={systemReady}
          readinessTooltip={readinessTooltip}
          onPreview={setPreview}
        />
      )}

      <PreviewModal item={preview} onClose={() => setPreview(null)} />
      </div>
    </div>
  );
}

function EmailDetailModal({
  emailId,
  summary,
  onClose,
  onRun,
  running,
  systemReady,
  readinessTooltip,
  onPreview,
}: {
  emailId: number;
  summary: EmailSummary | null;
  onClose: () => void;
  onRun: (e: EmailSummary) => void;
  running: boolean;
  systemReady: boolean;
  readinessTooltip?: string;
  onPreview: (item: PreviewItem | null) => void;
}) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<EmailDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    api
      .getEmail(emailId)
      .then((d) => {
        if (!cancel) {
          setDetail(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [emailId]);

  const hasPipeline = !!detail?.pipeline_id;

  return (
    <div className="fixed inset-0 bg-zbrain-ink/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="text-xs uppercase tracking-wider text-zbrain-muted mb-1">Inbound email</div>
            <h2 className="text-base font-semibold truncate">{detail?.subject || summary?.subject || "(loading)"}</h2>
            {detail && (
              <div className="text-xs text-zbrain-muted mt-1 flex items-center gap-2 flex-wrap">
                <span>From <span className="text-zbrain-ink font-medium">{detail.from}</span></span>
                {detail.received_at && <span>· {new Date(detail.received_at).toLocaleString()}</span>}
                {detail.language_hint && (
                  <span className="pill bg-slate-100 text-slate-700">{detail.language_hint.toUpperCase()}</span>
                )}
                {detail.customer && (
                  <span>· {detail.customer.name} ({detail.customer.region})</span>
                )}
                <StatusPill status={detail.status} />
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink text-lg leading-none shrink-0">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-auto px-6 py-4 space-y-4">
          {loading && <div className="text-sm text-zbrain-muted">Loading…</div>}
          {detail && detail.thread && detail.thread.message_count > 1 && (
            <ThreadTrailView thread={detail.thread} selfId={detail.id} onPreview={onPreview} />
          )}
          {detail && (!detail.thread || detail.thread.message_count <= 1) && (
            <>
              <div className="text-sm whitespace-pre-wrap text-zbrain-ink/90 bg-zbrain-surface border border-zbrain-divider rounded-lg p-4 font-sans">
                {detail.body || "(empty body)"}
              </div>
              {detail.attachments && detail.attachments.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-wider text-zbrain-muted mb-1.5">
                    Attachments ({detail.attachments.length})
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {detail.attachments.map((a) => {
                      const name = a.name;
                      return (
                        <button
                          key={name}
                          onClick={() => onPreview({ name, url: attachmentUrl(a) })}
                          className="pill bg-slate-100 text-slate-700 hover:bg-zbrain-50 hover:text-zbrain"
                        >
                          {name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-zbrain-divider flex items-center justify-between bg-zbrain-surface">
          <div className="text-xs text-zbrain-muted">
            {hasPipeline
              ? "This customer request has already been processed."
              : "Process this customer request through the 6-stage automation."}
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary">
              Close
            </button>
            {hasPipeline ? (
              <button
                onClick={() => {
                  onClose();
                  navigate(`/trace/${detail!.pipeline_id}`);
                }}
                className="btn-primary"
              >
                View activity →
              </button>
            ) : (
              <button
                onClick={() => summary && onRun(summary)}
                disabled={running || !summary || !systemReady}
                title={readinessTooltip}
                className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {running ? "Running…" : !systemReady ? "System blocked" : "▶ Process customer request"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Renders a complete email trail: every message in chronological order with
 * its own attachment block. The current message (the one the user opened) is
 * outlined; the root is badged. Each message body is collapsed by default
 * (one-line preview) except the current message which expands automatically.
 */
function ThreadTrailView({
  thread,
  selfId,
  onPreview,
}: {
  thread: EmailThread;
  selfId: number;
  onPreview: (item: PreviewItem | null) => void;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set([selfId]));
  const totalAttachments = thread.messages.reduce(
    (sum, m) => sum + (m.attachments?.length || 0),
    0
  );
  const toggle = (id: number) =>
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 px-3 py-2 rounded-md bg-sky-50/40 border border-sky-200">
        <div className="w-7 h-7 rounded bg-sky-100 text-sky-700 flex items-center justify-center font-semibold text-xs">
          T
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-sky-700">
            Email thread
          </div>
          <div className="text-sm font-semibold text-zbrain-ink truncate">
            {thread.message_count} message{thread.message_count === 1 ? "" : "s"}
            {totalAttachments > 0 && ` · ${totalAttachments} attachment${totalAttachments === 1 ? "" : "s"} across the trail`}
          </div>
        </div>
        <button
          type="button"
          onClick={() =>
            setExpanded(
              expanded.size >= thread.message_count
                ? new Set([selfId])
                : new Set(thread.messages.map((m) => m.id))
            )
          }
          className="text-[11px] text-zbrain hover:underline"
        >
          {expanded.size >= thread.message_count ? "Collapse all" : "Expand all"}
        </button>
      </div>

      <div className="space-y-2">
        {thread.messages.map((m) => {
          const isOpen = expanded.has(m.id);
          const ts = m.received_at ? new Date(m.received_at) : null;
          const isSelf = m.id === selfId;
          return (
            <div
              key={m.id}
              className={`border rounded-md transition ${
                isSelf
                  ? "border-zbrain-300 ring-1 ring-zbrain-300/40 bg-white"
                  : m.is_root
                  ? "border-sky-200 bg-sky-50/20"
                  : "border-zbrain-divider bg-white"
              }`}
            >
              <button
                type="button"
                onClick={() => toggle(m.id)}
                className="w-full px-3 py-2 flex items-start gap-3 hover:bg-slate-50/50 transition text-left"
              >
                <span className="text-zbrain-muted text-xs font-mono mt-0.5 shrink-0">
                  {String(m.position).padStart(2, "0")}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    {m.is_root && (
                      <span className="pill bg-sky-100 text-sky-800 border border-sky-300 text-[10px]">
                        ROOT
                      </span>
                    )}
                    {isSelf && (
                      <span className="pill bg-zbrain-50 text-zbrain border border-zbrain-300 text-[10px]">
                        OPENED
                      </span>
                    )}
                    <span className="text-xs font-semibold text-zbrain-ink truncate">
                      {m.from || "(unknown)"}
                    </span>
                    {(m.attachments?.length || 0) > 0 && (
                      <span className="pill bg-amber-50 text-amber-800 border border-amber-200 text-[10px]">
                        📎 {m.attachments!.length}
                      </span>
                    )}
                    {m.language_hint && m.language_hint !== "en" && (
                      <span className="pill bg-violet-50 text-violet-800 border border-violet-200 text-[10px] uppercase">
                        {m.language_hint}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-zbrain-muted truncate mt-0.5">
                    {ts && (
                      <span className="tabular-nums">
                        {ts.toLocaleString(undefined, {
                          year: "numeric",
                          month: "short",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    )}
                    {m.subject && <span> · {m.subject}</span>}
                  </div>
                  {!isOpen && (
                    <div className="text-xs text-zbrain-ink/80 mt-1.5 line-clamp-2 whitespace-pre-wrap">
                      {(m.body || "").slice(0, 280)}
                    </div>
                  )}
                </div>
                <span
                  className={`text-zbrain-muted text-xs mt-1 shrink-0 transition ${
                    isOpen ? "rotate-90" : ""
                  }`}
                >
                  ▶
                </span>
              </button>

              {isOpen && (
                <div className="px-3 pb-3 border-t border-zbrain-divider/60 space-y-2">
                  <pre className="text-[12px] whitespace-pre-wrap font-sans text-zbrain-ink/90 mt-2 bg-zbrain-surface border border-zbrain-divider rounded p-3">
                    {m.body || "(empty body)"}
                  </pre>
                  {m.attachments && m.attachments.length > 0 && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted mb-1">
                        Attachments ({m.attachments.length})
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {m.attachments.map((a, i) => {
                          const name = a.name || `attachment ${i + 1}`;
                          const url = attachmentUrl(a);
                          return (
                            <button
                              key={name + i}
                              onClick={() => onPreview({ name, url })}
                              className="pill bg-slate-100 text-slate-700 hover:bg-zbrain-50 hover:text-zbrain"
                            >
                              📎 {name}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
