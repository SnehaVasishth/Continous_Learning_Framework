import { useEffect, useState } from "react";

import { AccountFormBody, EmailAccount, api } from "../../api";

const PROVIDER_META: Record<string, { label: string; icon: string; appPasswordUrl?: string; help: string }> = {
  gmail: {
    label: "Gmail",
    icon: "G",
    appPasswordUrl: "https://myaccount.google.com/apppasswords",
    help: "Generate a 16-character app password (requires 2-Step Verification). Paste it below; your Google account password will not work.",
  },
  outlook: {
    label: "Outlook · Microsoft 365",
    icon: "O",
    appPasswordUrl: "https://account.live.com/proofs/AppPassword",
    help: "Personal accounts: generate an app password at the linked page. Microsoft 365 work accounts: your tenant admin must enable IMAP and app passwords first.",
  },
  imap: {
    label: "Generic IMAP",
    icon: "@",
    help: "Use any IMAP-over-TLS host. Provide host, port, and account credentials.",
  },
};

const PROVIDER_ICON_BG: Record<string, string> = {
  gmail: "bg-rose-100 text-rose-700",
  outlook: "bg-sky-100 text-sky-700",
  imap: "bg-slate-200 text-slate-700",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function ConnectionsSection() {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [smtpTestingId, setSmtpTestingId] = useState<number | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const load = async () => setAccounts(await api.emailAccounts.list());

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  const showToast = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 4000);
  };

  const onRefresh = async (id: number) => {
    setRefreshingId(id);
    try {
      const res = await api.emailAccounts.refresh(id);
      if (!res.ok) showToast("err", res.error || "refresh failed");
      else showToast("ok", `Fetched ${res.new_email_ids.length} new`);
      await load();
    } finally {
      setRefreshingId(null);
    }
  };

  const onRefreshAll = async () => {
    setRefreshingAll(true);
    try {
      const res = await api.emailAccounts.refreshAll();
      const total = res.results.reduce((a, r) => a + r.new, 0);
      const failed = res.results.filter((r) => r.error).length;
      showToast(
        failed > 0 ? "err" : "ok",
        `${total} new across ${res.results.length} mailbox${res.results.length === 1 ? "" : "es"}${
          failed > 0 ? ` · ${failed} failed` : ""
        }`
      );
      await load();
    } finally {
      setRefreshingAll(false);
    }
  };

  const onToggle = async (id: number) => {
    await api.emailAccounts.toggle(id);
    await load();
  };

  const onDelete = async (id: number, email: string) => {
    if (!confirm(`Disconnect ${email}? Already-imported emails stay in the inbox.`)) return;
    await api.emailAccounts.remove(id);
    await load();
  };

  const onTestSmtp = async (id: number) => {
    setSmtpTestingId(id);
    try {
      const res = await api.emailAccounts.testSmtp(id);
      showToast(res.ok ? "ok" : "err", res.ok ? `SMTP ready · ${res.message}` : `SMTP failed: ${res.message}`);
    } finally {
      setSmtpTestingId(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="display-md">Email connections</h1>
          <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">
            Connect mailboxes ZBrain should monitor. New mail is fetched automatically and lands in the Inbox queue
            for case processing. App passwords are encrypted at rest.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {accounts.length > 0 && (
            <button onClick={onRefreshAll} disabled={refreshingAll} className="btn-secondary">
              {refreshingAll ? "Fetching…" : "↻ Fetch all"}
            </button>
          )}
          <button onClick={() => setShowAdd(true)} className="btn-primary">+ Add connection</button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <EmptyState onAdd={() => setShowAdd(true)} />
      ) : (
        <div className="space-y-2">
          {accounts.map((a) => (
            <AccountRow
              key={a.id}
              account={a}
              refreshing={refreshingId === a.id}
              testingSmtp={smtpTestingId === a.id}
              onRefresh={() => onRefresh(a.id)}
              onToggle={() => onToggle(a.id)}
              onDelete={() => onDelete(a.id, a.email_address)}
              onTestSmtp={() => onTestSmtp(a.id)}
            />
          ))}
        </div>
      )}

      {showAdd && (
        <AddConnectionModal
          onClose={() => setShowAdd(false)}
          onSaved={() => {
            setShowAdd(false);
            load();
          }}
          onToast={showToast}
        />
      )}

      {toast && (
        <div
          className={`fixed bottom-6 right-6 px-4 py-2 rounded-md text-sm shadow-lg ${
            toast.kind === "ok" ? "bg-emerald-600 text-white" : "bg-rose-600 text-white"
          }`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="card p-10 text-center">
      <div className="inline-flex w-12 h-12 rounded-full bg-zbrain-50 text-zbrain items-center justify-center text-xl mb-3">
        ✉
      </div>
      <div className="text-base font-medium text-zbrain-ink">No mailboxes connected</div>
      <div className="text-sm text-zbrain-muted mt-1 max-w-md mx-auto">
        Connect Gmail, Outlook, or any IMAP mailbox to start ingesting customer email as cases.
      </div>
      <button onClick={onAdd} className="btn-primary mt-4">+ Add your first mailbox</button>
    </div>
  );
}

function AccountRow({
  account,
  refreshing,
  testingSmtp,
  onRefresh,
  onToggle,
  onDelete,
  onTestSmtp,
}: {
  account: EmailAccount;
  refreshing: boolean;
  testingSmtp: boolean;
  onRefresh: () => void;
  onToggle: () => void;
  onDelete: () => void;
  onTestSmtp: () => void;
}) {
  const meta = PROVIDER_META[account.provider] || PROVIDER_META.imap;
  const iconBg = PROVIDER_ICON_BG[account.provider] || PROVIDER_ICON_BG.imap;
  const dotColor = account.last_error
    ? "bg-rose-500"
    : account.is_active
    ? "bg-emerald-500"
    : "bg-slate-400";

  const [folderRoutingOpen, setFolderRoutingOpen] = useState(false);

  return (
    <div className="card p-4 hover:border-zbrain/30 transition-colors">
      <div className="flex items-center gap-4">
        <div className={`w-10 h-10 rounded-md flex items-center justify-center font-semibold ${iconBg}`}>
          {meta.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${dotColor}`} aria-hidden />
            <span className="font-medium truncate">{account.email_address}</span>
            <span className="text-xs text-zbrain-muted">· {meta.label}</span>
          </div>
          <div className="text-xs text-zbrain-muted mt-1 flex items-center gap-3 flex-wrap">
            <span>
              {account.imap_host}:{account.imap_port}
            </span>
            <span>·</span>
            <span>poll {account.sync_interval_sec}s</span>
            <span>·</span>
            <span>{account.messages_imported} imported</span>
            <span>·</span>
            <span>last sync {relativeTime(account.last_synced_at)}</span>
            {!account.is_active && <span className="pill bg-slate-200 text-slate-700">Paused</span>}
          </div>
          {account.last_error && (
            <div
              className="text-xs text-rose-700 mt-1 font-mono truncate max-w-xl"
              title={account.last_error}
            >
              {account.last_error}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button onClick={onRefresh} disabled={refreshing} className="btn-secondary" title="Fetch new mail now">
            {refreshing ? "…" : "↻"}
          </button>
          <button
            onClick={onTestSmtp}
            disabled={testingSmtp}
            className="btn-secondary"
            title="Verify outbound SMTP login (used when CSR sends a reply)"
          >
            {testingSmtp ? "…" : "✉ Test send"}
          </button>
          <button onClick={onToggle} className="btn-secondary" title={account.is_active ? "Pause polling" : "Resume polling"}>
            {account.is_active ? "Pause" : "Resume"}
          </button>
          <button
            onClick={onDelete}
            className="btn-secondary text-rose-700 border-rose-200 hover:bg-rose-50"
            title="Disconnect"
          >
            Remove
          </button>
        </div>
      </div>
      <div className="mt-3 border-t border-zbrain-divider pt-3">
        <button
          onClick={() => setFolderRoutingOpen((s) => !s)}
          className="text-xs text-zbrain hover:underline flex items-center gap-1"
        >
          <span>{folderRoutingOpen ? "▾" : "▸"}</span>
          <span>Folder routing: moves processed mail per category</span>
        </button>
        {folderRoutingOpen && (
          <FolderRoutingPanel accountId={account.id} provider={account.provider} />
        )}
      </div>
    </div>
  );
}

const FOLDER_CATEGORIES: { key: string; label: string }[] = [
  { key: "SALES_PO", label: "Sales POs" },
  { key: "ISC_WO_RTK", label: "Service / Work Orders" },
  { key: "KSO", label: "Government" },
  { key: "OTHERS", label: "Others" },
  { key: "AUTO_REPLY", label: "Auto-Replies" },
  { key: "UNDELIVERABLE", label: "Undeliverable" },
  { key: "COLLECTIONS", label: "Collections" },
  { key: "PORTAL_ADMIN", label: "Portal Admin" },
  { key: "BRAZIL_TAX", label: "Brazil Tax" },
];

function FolderRoutingPanel({ accountId, provider }: { accountId: number; provider: string }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [map, setMap] = useState<Record<string, string>>({});
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.emailAccounts
      .get(accountId)
      .then((acc) => {
        if (cancelled) return;
        const existing = acc.category_folder_map || {};
        const filled: Record<string, string> = {};
        for (const c of FOLDER_CATEGORIES) {
          filled[c.key] = existing[c.key] || "";
        }
        setMap(filled);
      })
      .catch((e) => {
        if (!cancelled) setErrMsg(e?.message || "load failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  const onSave = async () => {
    setSaving(true);
    setSavedMsg(null);
    setErrMsg(null);
    try {
      const cleaned: Record<string, string> = {};
      for (const [k, v] of Object.entries(map)) {
        if (v && v.trim()) cleaned[k] = v.trim();
      }
      await api.emailAccounts.updateFolderMap(accountId, cleaned);
      setSavedMsg("Folder map saved");
      setTimeout(() => setSavedMsg(null), 3000);
    } catch (e: any) {
      setErrMsg(e?.message || "save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="text-xs text-zbrain-muted mt-3">Loading folder map…</div>;
  }

  return (
    <div className="mt-3">
      {provider === "gmail" && (
        <div className="text-xs text-zbrain-muted bg-zbrain-surface border border-zbrain-divider rounded-md p-2 mb-3">
          Gmail uses labels; folders here become labels.
        </div>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wider text-zbrain-muted border-b border-zbrain-divider">
            <th className="py-2 pr-3 w-1/3">Category</th>
            <th className="py-2">Folder</th>
          </tr>
        </thead>
        <tbody>
          {FOLDER_CATEGORIES.map((c) => (
            <tr key={c.key} className="border-b border-zbrain-divider/60 last:border-b-0">
              <td className="py-1.5 pr-3 font-mono text-xs text-zbrain-ink">{c.label}</td>
              <td className="py-1.5">
                <input
                  value={map[c.key] || ""}
                  onChange={(e) => setMap((m) => ({ ...m, [c.key]: e.target.value }))}
                  placeholder="ZBrain/…"
                  className="w-full border border-zbrain-divider rounded-md text-sm px-2 py-1 focus:border-zbrain focus:outline-none"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between mt-3">
        <div className="text-xs">
          {savedMsg && <span className="text-emerald-700">{savedMsg}</span>}
          {errMsg && <span className="text-rose-700">{errMsg}</span>}
        </div>
        <button onClick={onSave} disabled={saving} className="btn-primary">
          {saving ? "Saving…" : "Save folder map"}
        </button>
      </div>
    </div>
  );
}

export function AddConnectionModal({
  onClose,
  onSaved,
  onToast,
}: {
  onClose: () => void;
  onSaved: () => void;
  onToast: (kind: "ok" | "err", msg: string) => void;
}) {
  const [provider, setProvider] = useState<"gmail" | "outlook" | "imap">("gmail");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState(993);
  const [folder, setFolder] = useState("INBOX");
  const [syncInterval, setSyncInterval] = useState(60);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const meta = PROVIDER_META[provider];

  const buildBody = (): AccountFormBody => ({
    provider,
    email_address: email.trim(),
    password,
    imap_host: provider === "imap" ? imapHost.trim() : undefined,
    imap_port: provider === "imap" ? imapPort : undefined,
    folder,
  });

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.emailAccounts.test(buildBody());
      setTestResult({ ok: res.ok, msg: res.message });
    } catch (e: any) {
      setTestResult({ ok: false, msg: e?.message || "test failed" });
    } finally {
      setTesting(false);
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await api.emailAccounts.create({ ...buildBody(), sync_interval_sec: syncInterval });
      onToast("ok", "Connected. First poll will run within 10 seconds.");
      onSaved();
    } catch (e: any) {
      onToast(
        "err",
        e?.message?.includes("400") ? "Connection test failed. Check credentials." : e?.message || "save failed"
      );
    } finally {
      setSaving(false);
    }
  };

  const canSubmit = !!email && !!password && (provider !== "imap" || !!imapHost);

  return (
    <div className="fixed inset-0 bg-zbrain-ink/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl max-h-[90vh] overflow-auto">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-center justify-between">
          <h2 className="text-base font-semibold">Connect a mailbox</h2>
          <button onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink text-lg leading-none">
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-2">Provider</label>
            <div className="grid grid-cols-3 gap-2">
              {(["gmail", "outlook", "imap"] as const).map((p) => {
                const m = PROVIDER_META[p];
                const ib = PROVIDER_ICON_BG[p];
                const active = provider === p;
                return (
                  <button
                    key={p}
                    onClick={() => setProvider(p)}
                    className={`p-3 rounded-md border text-left transition-colors ${
                      active
                        ? "border-zbrain bg-zbrain-50"
                        : "border-zbrain-divider hover:border-zbrain/40 hover:bg-zbrain-50/50"
                    }`}
                  >
                    <div className={`w-7 h-7 rounded-md flex items-center justify-center font-semibold mb-1.5 ${ib}`}>
                      {m.icon}
                    </div>
                    <div className={`text-sm font-medium ${active ? "text-zbrain" : "text-zbrain-ink"}`}>
                      {m.label}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="text-xs text-zbrain-muted bg-zbrain-surface border border-zbrain-divider rounded-md p-3">
            <strong className="text-zbrain-ink">{meta.help.split(".")[0]}.</strong>{" "}
            {meta.help.split(".").slice(1).join(".").trim()}
            {meta.appPasswordUrl && (
              <>
                {" "}
                <a
                  href={meta.appPasswordUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-zbrain hover:underline whitespace-nowrap"
                >
                  Open app-password page →
                </a>
              </>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Email address</label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="csr@yourcompany.com"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">App password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••••••"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
              />
            </div>
          </div>

          {provider === "imap" && (
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">IMAP host</label>
                <input
                  value={imapHost}
                  onChange={(e) => setImapHost(e.target.value)}
                  placeholder="imap.example.com"
                  className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Port</label>
                <input
                  type="number"
                  value={imapPort}
                  onChange={(e) => setImapPort(parseInt(e.target.value) || 993)}
                  className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
                />
              </div>
            </div>
          )}

          <button
            onClick={() => setShowAdvanced((s) => !s)}
            className="text-xs text-zbrain hover:underline"
          >
            {showAdvanced ? "Hide advanced options" : "Advanced options"}
          </button>

          {showAdvanced && (
            <div className="grid grid-cols-2 gap-3 pt-1">
              <div>
                <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Folder</label>
                <input
                  value={folder}
                  onChange={(e) => setFolder(e.target.value)}
                  className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">
                  Poll every (seconds)
                </label>
                <input
                  type="number"
                  min={15}
                  value={syncInterval}
                  onChange={(e) => setSyncInterval(Math.max(15, parseInt(e.target.value) || 60))}
                  className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
                />
              </div>
            </div>
          )}

          {testResult && (
            <div
              className={`text-sm rounded-md p-2 ${
                testResult.ok
                  ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  : "bg-rose-50 text-rose-800 border border-rose-200"
              }`}
            >
              {testResult.ok ? "✓ Connection OK" : `✗ ${testResult.msg}`}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-zbrain-divider flex items-center justify-between bg-zbrain-surface">
          <button onClick={onTest} disabled={testing || !canSubmit} className="btn-secondary">
            {testing ? "Testing…" : "Test connection"}
          </button>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button onClick={onSave} disabled={saving || !canSubmit} className="btn-primary">
              {saving ? "Connecting…" : "Connect & sync"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
