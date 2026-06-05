import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api";
import { PageHeader } from "../../components/PageHeader";

/**
 * Users settings — Salesforce-backed operator directory with resolved
 * RBAC role per user.
 *
 * Source of truth: live Salesforce. The list comes from members of any
 * `ZBrain_*` queue. The RBAC role per user is derived from the user's
 * Salesforce Permission Set assignments (with the legacy `LEARNING_RULE_OWNERS`
 * Python allowlist as a fallback when the org has not provisioned the
 * permission set yet).
 *
 * Two roles, matching the operating model:
 *   - zbrain_admin → drives platform changes (promote, rollback, edit baselines, edit governance policies)
 *   - viewer       → read-only access; cannot mutate
 *
 * The Keysight functional team (CSRs, ops) work inside Salesforce, not in
 * this admin app, so they are not a separate role here.
 */

type RoleKey = "viewer" | "zbrain_admin";

type SfUserRow = {
  id: string;
  name: string;
  username: string | null;
  email: string | null;
  is_rule_owner: boolean;
  rule_owner_label: string | null;
  role: RoleKey;
  permission_sets: string[];
  role_source: {
    source: string;
    matched?: string | null;
    username?: string | null;
    permission_sets?: string[];
  };
};

type SfStatus = {
  connected: boolean;
  source?: string | null;
  instance_url?: string | null;
  org_label?: string | null;
  username?: string | null;
};

const ROLE_LABEL: Record<RoleKey, string> = {
  zbrain_admin: "ZBrain Admin",
  viewer: "Viewer",
};

const ROLE_TONE: Record<RoleKey, string> = {
  zbrain_admin: "bg-zbrain-50 text-zbrain border border-zbrain/30",
  viewer: "bg-slate-100 text-slate-700 border border-slate-200",
};

const ROLE_AUTHORITY: Record<RoleKey, string[]> = {
  zbrain_admin: [
    "Promote / rollback A/B experiments",
    "Edit baselines + detector tuning",
    "Edit governance policies",
    "Delete baselines",
  ],
  viewer: [
    "Read-only access to every dashboard",
    "Cannot promote, rollback, or edit",
  ],
};

function sourceCopy(src: string): { label: string; tone: string } {
  switch (src) {
    case "sf_permission_set":
      return { label: "Salesforce permission set", tone: "text-emerald-700" };
    case "sf_permission_set_no_assignment":
      return { label: "No ZBrain permission set assigned", tone: "text-slate-600" };
    case "fallback_allowlist":
      return { label: "Fallback allowlist (config.py)", tone: "text-amber-700" };
    case "fallback_allowlist_no_match":
      return { label: "Fallback allowlist (no match)", tone: "text-slate-600" };
    case "sf_offline":
      return { label: "Salesforce offline (defaulted)", tone: "text-rose-700" };
    case "sf_query_failed":
      return { label: "Salesforce query failed", tone: "text-rose-700" };
    default:
      return { label: src || "-", tone: "text-slate-600" };
  }
}

export function UsersPage() {
  const [rows, setRows] = useState<SfUserRow[] | null>(null);
  const [sf, setSf] = useState<SfStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const [users, status] = await Promise.all([
          api.listSfUsers(),
          api.integrations.salesforce.status().catch(() => null),
        ]);
        if (cancel) return;
        setRows(users);
        setSf(status);
        setLastFetched(new Date());
        setErr(null);
      } catch (e: any) {
        if (!cancel) setErr(String(e?.message || e));
      }
    }
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, []);

  const sfConnected = !!sf?.connected;
  const sfInstance = sf?.instance_url || "";
  const sfOrgLabel = sf?.org_label || sfInstance.replace(/^https?:\/\//, "").split(".")[0] || "Salesforce org";

  const counts = useMemo(() => {
    const c: Record<RoleKey, number> = { zbrain_admin: 0, viewer: 0 };
    if (rows) for (const r of rows) c[r.role] = (c[r.role] || 0) + 1;
    return c;
  }, [rows]);

  // Detect whether ANY user resolved via the production path (Salesforce
  // Permission Set) so we can show a banner if the org is still on the
  // fallback allowlist.
  const onProductionPath = useMemo(() => {
    if (!rows) return false;
    return rows.some((r) => r.role_source?.source === "sf_permission_set");
  }, [rows]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        subtitle="Salesforce-backed operator directory and the RBAC role each user holds."
        lastFetchedAt={lastFetched}
        error={err}
      />

      {/* Source-of-truth banner */}
      <div
        className={[
          "card px-5 py-3.5 flex items-start gap-3",
          sfConnected
            ? onProductionPath
              ? "border-l-4 border-l-emerald-500"
              : "border-l-4 border-l-amber-500"
            : "border-l-4 border-l-rose-500",
        ].join(" ")}
      >
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
            Identity + role source: Salesforce
          </div>
          <div className="text-[12px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 leading-relaxed">
            {!sfConnected ? (
              <>
                Salesforce is <strong>not connected</strong>. The roster falls back to local state and roles
                default to viewer. Reconnect Salesforce in Integrations to restore the live source.
              </>
            ) : onProductionPath ? (
              <>
                Roster live from <span className="font-mono text-zbrain-ink dark:text-zbrain-dark-ink">{sfOrgLabel}</span>.
                Admin authority resolves from the
                <span className="font-mono"> ZBrain_Platform_Admin</span> Salesforce Permission Set. Assign it to
                a user in Salesforce Setup and the change takes effect on the next 5-minute cache cycle. Everyone
                else is viewer.
              </>
            ) : (
              <>
                Roster live from <span className="font-mono text-zbrain-ink dark:text-zbrain-dark-ink">{sfOrgLabel}</span>,
                but no user holds the <span className="font-mono">ZBrain_Platform_Admin</span> permission set yet.
                Admin authority is falling back to the legacy allowlist in
                <span className="font-mono"> config.LEARNING_RULE_OWNERS</span>.
                Provision the <span className="font-mono">ZBrain_Platform_Admin</span> permission set in Salesforce
                Setup and assign it to admin users to move to the production path.
              </>
            )}
          </div>
        </div>
        <Link
          to="/integrations"
          className="text-[12px] font-semibold text-zbrain hover:underline whitespace-nowrap shrink-0"
        >
          Manage in Integrations →
        </Link>
      </div>

      {/* Role-count strip */}
      <div className="grid grid-cols-2 gap-3">
        {(["zbrain_admin", "viewer"] as RoleKey[]).map((r) => (
          <div key={r} className="card p-4">
            <div className="flex items-center gap-2">
              <span className={`pill text-[10.5px] font-semibold ${ROLE_TONE[r]}`}>{ROLE_LABEL[r]}</span>
              <span className="text-[10px] uppercase tracking-wider text-zbrain-muted">Active</span>
            </div>
            <div className="text-2xl font-semibold tabular-nums mt-1 text-zbrain-ink dark:text-zbrain-dark-ink">
              {counts[r]}
            </div>
            <ul className="mt-2 space-y-0.5">
              {ROLE_AUTHORITY[r].map((line, i) => (
                <li key={i} className="text-[11.5px] text-zbrain-muted leading-snug">· {line}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Roster table */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider flex items-center justify-between">
          <div>
            <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Operator roster</div>
            <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
              {rows ? `${rows.length} operator${rows.length === 1 ? "" : "s"}` : "Loading…"} · Add/remove via Salesforce queue
              membership · Role via Salesforce Permission Sets.
            </div>
          </div>
          <span className="text-[10.5px] uppercase tracking-[0.12em] text-zbrain-muted dark:text-zbrain-dark-muted">
            {sfConnected ? "Live · Salesforce" : "Disconnected"}
          </span>
        </div>

        {rows === null ? (
          <div className="px-5 py-6 text-sm text-zbrain-muted">Loading users…</div>
        ) : rows.length === 0 ? (
          <div className="px-5 py-6 text-sm text-zbrain-muted">No operators registered.</div>
        ) : (
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider text-[10.5px]">
                <th className="px-4 py-2.5 text-left font-semibold">Name</th>
                <th className="px-4 py-2.5 text-left font-semibold">Email</th>
                <th className="px-4 py-2.5 text-left font-semibold">SF username</th>
                <th className="px-4 py-2.5 text-left font-semibold">Role</th>
                <th className="px-4 py-2.5 text-left font-semibold">Permission sets</th>
                <th className="px-4 py-2.5 text-left font-semibold">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
              {rows.map((u) => {
                const role: RoleKey = (u.role || "viewer") as RoleKey;
                const src = sourceCopy(u.role_source?.source || "");
                const perms = u.permission_sets || [];
                return (
                  <tr key={u.id} className="hover:bg-zbrain-surface/40 dark:hover:bg-zbrain-dark-elev2/50 align-top">
                    <td className="px-4 py-3 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{u.name}</td>
                    <td className="px-4 py-3 text-zbrain-muted">{u.email || "-"}</td>
                    <td className="px-4 py-3 text-zbrain-muted font-mono text-[11.5px]">{u.username || "-"}</td>
                    <td className="px-4 py-3">
                      <span className={`pill text-[10.5px] font-semibold ${ROLE_TONE[role]}`}>{ROLE_LABEL[role]}</span>
                    </td>
                    <td className="px-4 py-3 text-zbrain-muted">
                      {perms.length === 0 ? (
                        <span className="text-zbrain-muted">-</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {perms.slice(0, 4).map((p) => (
                            <span key={p} className="pill text-[10px] bg-slate-100 text-slate-700 font-mono">{p}</span>
                          ))}
                          {perms.length > 4 && (
                            <span className="pill text-[10px] bg-slate-100 text-slate-500">+{perms.length - 4}</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className={`px-4 py-3 text-[11.5px] ${src.tone}`}>
                      {src.label}
                      {u.role_source?.matched && (
                        <div className="text-[10.5px] text-zbrain-muted mt-0.5">
                          matched: <span className="font-mono">{u.role_source.matched}</span>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
