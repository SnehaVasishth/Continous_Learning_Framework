import { useEffect, useState } from "react";

import {
  AIOAProvider,
  AIOAProviderInput,
  EmailAccount,
  IntegrationPlaceholder,
  OpenAIConnectBody,
  OpenAIStatus,
  SalesforceConnectBody,
  SalesforceStatus,
  ServiceNowConnectBody,
  ServiceNowStatus,
  SharePointConnectBody,
  SharePointStatus,
  aioaApi,
  api,
} from "../api";
import {
  AIOALogo,
  AzureLogo,
  ContractsLogo,
  EmailLogo,
  OpenAILogo,
  OracleLogo,
  SalesforceLogo,
  ServiceNowLogo,
  SharePointLogo,
} from "../components/IntegrationLogos";
import { ConnectionsSection } from "./settings/Connections";
import { InfoTip } from "../components/InfoTip";

type StaticCard = {
  key: string;
  name: string;
  category: "Translation" | "Document" | "LLM";
  description: string;
  detail: string;
  iconBg: string;
  iconLetter: string;
  status: "available" | "planned" | "connected";
  envSourced?: { envVar: string; masked: string };
};

const STATIC_CARDS: StaticCard[] = [
  {
    key: "azure_doc_intelligence",
    name: "Azure Document Intelligence",
    category: "Document",
    description: "OCR and structured extraction on PO PDFs, scanned invoices, and signed quotes. Uses the Layout model for tables and key-value pairs; falls back to the local pypdf extractor when the service is unreachable.",
    detail: "Per-page cost is metered on every call and surfaces in Analytics → AI infrastructure cost. Rate book: Layout $10 / 1k pages, Read $1.50 / 1k pages.",
    status: "connected",
    iconBg: "bg-indigo-100 text-indigo-700",
    iconLetter: "DI",
  },
  {
    key: "azure_translator",
    name: "Azure Translator",
    category: "Translation",
    description: "Inbound translation for non-English mail and bilingual outbound replies. Today the workflow routes translation through the configured LLM provider; the Azure Translator slot is provisioned for the production cutover.",
    detail: "No additional configuration needed for the demo.",
    status: "available",
    iconBg: "bg-amber-100 text-amber-700",
    iconLetter: "Tr",
  },
];

const CATEGORY_PILL: Record<string, { cls: string }> = {
  Email: { cls: "bg-rose-50 text-rose-700" },
  CRM: { cls: "bg-sky-50 text-sky-700" },
  ITSM: { cls: "bg-emerald-50 text-emerald-700" },
  Documents: { cls: "bg-indigo-50 text-indigo-700" },
  Middleware: { cls: "bg-violet-50 text-violet-700" },
  Document: { cls: "bg-indigo-50 text-indigo-700" },
  Translation: { cls: "bg-amber-50 text-amber-700" },
  LLM: { cls: "bg-slate-100 text-slate-700" },
};

export function IntegrationsPage() {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [sfStatus, setSfStatus] = useState<SalesforceStatus | null>(null);
  const [snStatus, setSnStatus] = useState<ServiceNowStatus | null>(null);
  const [spStatus, setSpStatus] = useState<SharePointStatus | null>(null);
  const [placeholders, setPlaceholders] = useState<IntegrationPlaceholder[]>([]);
  const [aioaProvider, setAioaProvider] = useState<AIOAProvider | null>(null);
  const [openaiStatus, setOpenaiStatus] = useState<OpenAIStatus | null>(null);
  const [showEmailDetail, setShowEmailDetail] = useState(false);
  const [showSalesforceModal, setShowSalesforceModal] = useState(false);
  const [showSalesforceDetails, setShowSalesforceDetails] = useState(false);
  const [showServiceNowModal, setShowServiceNowModal] = useState(false);
  const [showSharePointModal, setShowSharePointModal] = useState(false);
  const [showAIOAModal, setShowAIOAModal] = useState(false);
  const [showOpenAIModal, setShowOpenAIModal] = useState(false);

  const loadAll = async () => {
    const [emails, sf, sn, sp, ph, aioa, oai] = await Promise.all([
      api.emailAccounts.list().catch(() => [] as EmailAccount[]),
      api.integrations.salesforce.status().catch(() => ({ connected: false } as SalesforceStatus)),
      api.integrations.servicenow.status().catch(() => ({ connected: false } as ServiceNowStatus)),
      api.integrations.sharepoint.status().catch(() => ({ connected: false } as SharePointStatus)),
      api.integrations.placeholders.list().catch(() => ({ items: [] as IntegrationPlaceholder[] })),
      aioaApi.listProviders().catch(() => [] as AIOAProvider[]),
      api.integrations.openai.status().catch(() => null as OpenAIStatus | null),
    ]);
    setAccounts(emails);
    setSfStatus(sf);
    setSnStatus(sn);
    setSpStatus(sp);
    setPlaceholders(ph.items || []);
    setAioaProvider((aioa && aioa[0]) || null);
    setOpenaiStatus(oai);
  };

  useEffect(() => {
    loadAll();
  }, []);

  if (showEmailDetail) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setShowEmailDetail(false)}
          className="text-xs text-zbrain hover:underline inline-flex items-center gap-1"
        >
          ← Back to integrations
        </button>
        <ConnectionsSection />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="display-md inline-flex items-center gap-2">
          Integrations
          <InfoTip text="Systems ZBrain reads from and writes to. CRM resolves customer, product, and order data live; the document store sources files; case status syncs to the ITSM of record." />
        </h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <EmailTile accounts={accounts} onConfigure={() => setShowEmailDetail(true)} />
        <SalesforceTile
          status={sfStatus}
          onConnect={() => setShowSalesforceModal(true)}
          onViewDetails={() => setShowSalesforceDetails(true)}
          onChange={loadAll}
        />
        <ServiceNowTile status={snStatus} onConnect={() => setShowServiceNowModal(true)} onChange={loadAll} />
        <SharePointTile status={spStatus} onConnect={() => setShowSharePointModal(true)} onChange={loadAll} />
        <AIOATile provider={aioaProvider} onConnect={() => setShowAIOAModal(true)} onChange={loadAll} />
        <OpenAITile status={openaiStatus} onConnect={() => setShowOpenAIModal(true)} onChange={loadAll} />
        {placeholders.map((p) => (
          <PlaceholderTile key={p.provider} row={p} onChange={loadAll} />
        ))}
        {STATIC_CARDS.map((c) => (
          <StaticTile key={c.key} card={c} />
        ))}
      </div>

      {showSalesforceModal && (
        <SalesforceConnectModal
          existing={sfStatus}
          onClose={() => setShowSalesforceModal(false)}
          onSaved={() => {
            setShowSalesforceModal(false);
            loadAll();
          }}
        />
      )}
      {showServiceNowModal && (
        <ServiceNowConnectModal
          existing={snStatus}
          onClose={() => setShowServiceNowModal(false)}
          onSaved={() => {
            setShowServiceNowModal(false);
            loadAll();
          }}
        />
      )}
      {showSharePointModal && (
        <SharePointConnectModal
          existing={spStatus}
          onClose={() => setShowSharePointModal(false)}
          onSaved={() => {
            setShowSharePointModal(false);
            loadAll();
          }}
        />
      )}
      {showSalesforceDetails && (
        <SalesforceDetailsModal onClose={() => setShowSalesforceDetails(false)} />
      )}
      {showAIOAModal && aioaProvider && (
        <AIOAConnectModal
          existing={aioaProvider}
          onClose={() => setShowAIOAModal(false)}
          onSaved={() => {
            setShowAIOAModal(false);
            loadAll();
          }}
        />
      )}
      {showOpenAIModal && (
        <OpenAIConnectModal
          existing={openaiStatus}
          onClose={() => setShowOpenAIModal(false)}
          onSaved={() => {
            setShowOpenAIModal(false);
            loadAll();
          }}
        />
      )}
    </div>
  );
}

function TileShell({
  iconBg,
  iconLetter,
  iconNode,
  name,
  category,
  description,
  detail,
  statusPill,
  actions,
}: {
  iconBg: string;
  iconLetter: string;
  iconNode?: React.ReactNode;
  name: string;
  category: string;
  description: string;
  detail?: React.ReactNode;
  statusPill: React.ReactNode;
  actions: React.ReactNode;
}) {
  return (
    <div className="card p-4 flex gap-4 hover:border-zbrain/30 transition-colors">
      {iconNode ? (
        <div className="shrink-0 w-11 h-11 rounded-md bg-white border border-zbrain-divider flex items-center justify-center p-1.5">
          <div className="w-full h-full flex items-center justify-center [&>svg]:w-full [&>svg]:h-full">
            {iconNode}
          </div>
        </div>
      ) : (
        <div
          className={`shrink-0 w-11 h-11 rounded-md flex items-center justify-center text-sm font-semibold ${iconBg}`}
        >
          {iconLetter}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-zbrain-ink">{name}</span>
          <span className={`pill ${(CATEGORY_PILL[category] || CATEGORY_PILL.Email).cls}`}>{category}</span>
          <span className="ml-auto shrink-0">{statusPill}</span>
        </div>
        <div className="text-xs text-zbrain-muted mt-1">{description}</div>
        {detail && <div className="text-xs text-zbrain-ink/80 mt-2">{detail}</div>}
        <div className="mt-3 flex gap-2 flex-wrap">{actions}</div>
      </div>
    </div>
  );
}

function EmailTile({ accounts, onConfigure }: { accounts: EmailAccount[]; onConfigure: () => void }) {
  const connected = accounts.length > 0;
  const totalImported = accounts.reduce((a, x) => a + (x.messages_imported || 0), 0);
  return (
    <TileShell
      iconBg="bg-rose-100 text-rose-700"
      iconLetter="@"
      iconNode={<EmailLogo />}
      name="Email: Gmail / Outlook / IMAP"
      category="Email"
      description="Mailboxes monitored for inbound customer requests. App-password authenticated."
      detail={
        connected
          ? `${accounts.length} mailbox${accounts.length === 1 ? "" : "es"} connected · ${totalImported} messages imported`
          : "Connect a Gmail or Outlook mailbox to start ingesting real customer email."
      }
      statusPill={
        connected ? (
          <span className="pill bg-emerald-100 text-emerald-700">Connected</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Available</span>
        )
      }
      actions={
        <button onClick={onConfigure} className="btn-secondary text-xs">
          {connected ? "Manage mailboxes" : "Connect mailbox"}
        </button>
      }
    />
  );
}

function SalesforceTile({
  status,
  onConnect,
  onViewDetails,
  onChange,
}: {
  status: SalesforceStatus | null;
  onConnect: () => void;
  onViewDetails: () => void;
  onChange: () => void;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [ownersMsg, setOwnersMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const connected = !!status?.connected;

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await api.integrations.salesforce.refresh();
      onChange();
    } finally {
      setRefreshing(false);
    }
  };

  const onProvisionOwners = async () => {
    setProvisioning(true);
    setOwnersMsg(null);
    try {
      const r = await api.integrations.salesforce.provisionOwners();
      const created = r.created.length;
      const skipped = r.skipped.length;
      const errored = r.errored.length;
      setOwnersMsg({
        tone: errored > 0 ? "err" : "ok",
        text: `${created} provisioned · ${skipped} skipped (already exists) · ${errored} errored`,
      });
    } catch (e: any) {
      setOwnersMsg({ tone: "err", text: e?.message || "Provision failed" });
    } finally {
      setProvisioning(false);
    }
  };

  const onSyncOwners = async () => {
    setSyncing(true);
    setOwnersMsg(null);
    try {
      const r = await api.integrations.salesforce.syncOwners();
      setOwnersMsg({
        tone: "ok",
        text: `${r.synced.length} synced from ${r.case_queues_in_sf} Case-eligible queues · ${r.not_in_sf.length} not in SF (run Provision)`,
      });
    } catch (e: any) {
      setOwnersMsg({ tone: "err", text: e?.message || "Sync failed" });
    } finally {
      setSyncing(false);
    }
  };

  const onDisconnect = async () => {
    if (!confirm("Disconnect Salesforce? Already-imported data stays. You can reconnect later.")) return;
    await api.integrations.salesforce.disconnect();
    onChange();
  };

  let detail: React.ReactNode = "Customer 360, quotes, orders, products, and assets, live from Salesforce.";
  if (connected) {
    const apiQuota =
      status?.daily_api_remaining != null && status?.daily_api_max
        ? `${status.daily_api_remaining.toLocaleString()} / ${status.daily_api_max.toLocaleString()} API calls remaining`
        : null;
    detail = (
      <span>
        Org <span className="font-medium text-zbrain-ink">{status?.org_name}</span> ({status?.org_edition}) · running as{" "}
        <span className="font-medium text-zbrain-ink">{status?.user_display_name}</span>
        {apiQuota && (
          <>
            <br />
            {apiQuota}
          </>
        )}
        {status?.last_tested_at && (
          <>
            <br />
            <span className="text-zbrain-muted">
              Last verified {new Date(status.last_tested_at).toLocaleString()}
            </span>
          </>
        )}
      </span>
    );
  }

  return (
    <TileShell
      iconBg="bg-sky-100 text-sky-700"
      iconLetter="S"
      iconNode={<SalesforceLogo />}
      name="Salesforce"
      category="CRM"
      description="System of record for accounts, contacts, products, quotes, orders, and assets."
      detail={detail}
      statusPill={
        connected ? (
          <span className="pill bg-emerald-100 text-emerald-700">Connected</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Available</span>
        )
      }
      actions={
        connected ? (
          <>
            <button onClick={onViewDetails} className="btn-primary text-xs">
              View details
            </button>
            <button onClick={onRefresh} disabled={refreshing} className="btn-secondary text-xs">
              {refreshing ? "Verifying…" : "Verify connection"}
            </button>
            <button onClick={onProvisionOwners} disabled={provisioning} className="btn-secondary text-xs" title="Provision the 6 CSR queues (FCNV, SOM, Trade, CTA, AI OA, POB) in this Salesforce org. Idempotent: adopts existing queues by DeveloperName.">
              {provisioning ? "Provisioning…" : "Provision case-owner queues"}
            </button>
            <button onClick={onSyncOwners} disabled={syncing} className="btn-secondary text-xs" title="Sync KB owner_mapping rows from live SF queues (refreshes queue_id and label).">
              {syncing ? "Syncing…" : "Sync from Salesforce"}
            </button>
            <button onClick={onConnect} className="btn-secondary text-xs">
              Reconfigure
            </button>
            <button
              onClick={onDisconnect}
              className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
            >
              Disconnect
            </button>
            {ownersMsg && (
              <span className={`text-[11px] ml-2 ${ownersMsg.tone === "err" ? "text-rose-700" : "text-emerald-700"}`}>
                {ownersMsg.text}
              </span>
            )}
          </>
        ) : (
          <button onClick={onConnect} className="btn-primary text-xs">
            Connect Salesforce
          </button>
        )
      }
    />
  );
}

function ServiceNowTile({
  status,
  onConnect,
  onChange,
}: {
  status: ServiceNowStatus | null;
  onConnect: () => void;
  onChange: () => void;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const connected = !!status?.connected;

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await api.integrations.servicenow.refresh();
      onChange();
    } finally {
      setRefreshing(false);
    }
  };

  const onDisconnect = async () => {
    if (!confirm("Disconnect ServiceNow? Existing cases stay in the instance. You can reconnect later.")) return;
    await api.integrations.servicenow.disconnect();
    onChange();
  };

  let detail: React.ReactNode = "Customer service cases. Owns the CCC Request lifecycle (status / stage transitions).";
  if (connected) {
    detail = (
      <span>
        Instance <span className="font-medium text-zbrain-ink">{status?.instance_url?.replace("https://", "")}</span> ·
        case table <span className="font-medium text-zbrain-ink">{status?.case_table}</span>
        {status?.csm_active === false && status?.case_table === "incident" && (
          <span className="text-zbrain-muted"> (CSM not active, using incident)</span>
        )}
        {status?.incident_count != null && (
          <>
            <br />
            {status.incident_count.toLocaleString()} cases in instance
          </>
        )}
        {status?.last_tested_at && (
          <>
            <br />
            <span className="text-zbrain-muted">
              Last verified {new Date(status.last_tested_at).toLocaleString()}
            </span>
          </>
        )}
      </span>
    );
  }

  return (
    <TileShell
      iconBg="bg-emerald-100 text-emerald-700"
      iconLetter="N"
      iconNode={<ServiceNowLogo />}
      name="ServiceNow"
      category="ITSM"
      description="Authoritative ITSM for the CCC Request: case create, state transitions, closure."
      detail={detail}
      statusPill={
        connected ? (
          <span className="pill bg-emerald-100 text-emerald-700">Connected</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Available</span>
        )
      }
      actions={
        connected ? (
          <>
            <button onClick={onRefresh} disabled={refreshing} className="btn-secondary text-xs">
              {refreshing ? "Verifying…" : "Verify connection"}
            </button>
            <button onClick={onConnect} className="btn-secondary text-xs">
              Reconfigure
            </button>
            <button
              onClick={onDisconnect}
              className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
            >
              Disconnect
            </button>
          </>
        ) : (
          <button onClick={onConnect} className="btn-primary text-xs">
            Connect ServiceNow
          </button>
        )
      }
    />
  );
}

function ServiceNowConnectModal({
  existing,
  onClose,
  onSaved,
}: {
  existing: ServiceNowStatus | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [instanceUrl, setInstanceUrl] = useState(existing?.instance_url || "");
  const [username, setUsername] = useState(existing?.username || "admin");
  const [password, setPassword] = useState("");
  const [caseTable, setCaseTable] = useState(existing?.case_table || "incident");
  const [label, setLabel] = useState(existing?.label || "Production instance");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string; whoami?: any } | null>(null);

  const buildBody = (): ServiceNowConnectBody => ({
    instance_url: instanceUrl.trim().replace(/\/$/, ""),
    username: username.trim(),
    password,
    case_table: caseTable,
    label: label.trim() || "Production instance",
  });

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.integrations.servicenow.test(buildBody());
      setTestResult({ ok: res.ok, msg: res.message, whoami: res.whoami });
    } catch (e: any) {
      setTestResult({ ok: false, msg: e?.message || "test failed" });
    } finally {
      setTesting(false);
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await api.integrations.servicenow.connect(buildBody());
      onSaved();
    } catch (e: any) {
      setTestResult({
        ok: false,
        msg: e?.message?.includes("400") ? "Connection rejected. Check credentials." : e?.message,
      });
    } finally {
      setSaving(false);
    }
  };

  const canSubmit = !!instanceUrl && !!username && !!password;

  return (
    <div className="fixed inset-0 bg-zbrain-ink/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl max-h-[90vh] overflow-auto">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-center justify-between">
          <h2 className="text-base font-semibold">Connect ServiceNow</h2>
          <button onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink text-lg leading-none">
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div className="text-xs text-zbrain-muted bg-zbrain-surface border border-zbrain-divider rounded-md p-3">
            <strong className="text-zbrain-ink">REST + Basic Auth.</strong> For production we recommend OAuth 2.0 with a
            dedicated integration user. PDIs and demo instances run fine on Basic Auth.
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Instance URL</label>
            <input
              value={instanceUrl}
              onChange={(e) => setInstanceUrl(e.target.value)}
              placeholder="https://devXXXXXX.service-now.com"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Username</label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••••••"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Case table</label>
              <select
                value={caseTable}
                onChange={(e) => setCaseTable(e.target.value)}
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
              >
                <option value="incident">incident (default)</option>
                <option value="sn_customerservice_case">sn_customerservice_case (CSM plugin)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Label</label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Production instance"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
              />
            </div>
          </div>

          {testResult && (
            <div
              className={`text-sm rounded-md p-3 ${
                testResult.ok
                  ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  : "bg-rose-50 text-rose-800 border border-rose-200"
              }`}
            >
              {testResult.ok ? (
                <>
                  <div className="font-medium">✓ Connected</div>
                  {testResult.whoami && (
                    <div className="text-xs mt-1">
                      Instance <strong>{testResult.whoami.instance_url?.replace("https://", "")}</strong> ·{" "}
                      <strong>{testResult.whoami.incident_count?.toLocaleString() || 0}</strong> existing cases
                      {testResult.whoami.csm_active === false && testResult.whoami.case_table === "incident" && (
                        <> · CSM plugin not active (using incident table, fine for demo)</>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="font-medium">✗ Connection failed</div>
                  <div className="text-xs mt-1 font-mono">{testResult.msg}</div>
                </>
              )}
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
              {saving ? "Saving…" : "Save & connect"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PlaceholderTile({ row, onChange }: { row: IntegrationPlaceholder; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const isJitterbit = row.provider === "jitterbit";
  const category = row.kind || (isJitterbit ? "Middleware" : "Documents");
  const iconLetter = isJitterbit ? "J" : "D";
  const iconBg = isJitterbit ? "bg-violet-100 text-violet-700" : "bg-indigo-100 text-indigo-700";
  const iconNode = isJitterbit ? <OracleLogo /> : <ContractsLogo />;
  const onToggle = async () => {
    setBusy(true);
    try {
      await api.integrations.placeholders.update(row.provider, { enabled: !row.enabled });
      onChange();
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <TileShell
        iconBg={iconBg}
        iconLetter={iconLetter}
        iconNode={iconNode}
        name={row.label}
        category={category}
        description={row.description || ""}
        detail={
          row.enabled ? (
            <span>
              <span className="text-emerald-700 font-medium">Enabled</span>
              {row.last_enabled_at && ` · since ${new Date(row.last_enabled_at).toLocaleString()}`}
              {row.config && Object.keys(row.config).length > 0 && (
                <> · {Object.keys(row.config).length} config field{Object.keys(row.config).length === 1 ? "" : "s"} set</>
              )}
            </span>
          ) : (
            <span className="text-zbrain-muted">Disabled. Actions stay in the local mock until enabled.</span>
          )
        }
        statusPill={
          row.enabled ? (
            <span className="pill bg-emerald-100 text-emerald-700">Enabled</span>
          ) : (
            <span className="pill bg-indigo-50 text-indigo-700">Upcoming</span>
          )
        }
        actions={
          <>
            <button onClick={onToggle} disabled={busy} className={row.enabled ? "btn-secondary text-xs" : "btn-primary text-xs"}>
              {busy ? "Saving…" : row.enabled ? "Disable" : "Enable"}
            </button>
            <button onClick={() => setShowConfig(true)} className="btn-secondary text-xs">
              Configure endpoint
            </button>
          </>
        }
      />
      {showConfig && (
        <PlaceholderConfigModal
          row={row}
          onClose={() => setShowConfig(false)}
          onSaved={() => {
            setShowConfig(false);
            onChange();
          }}
        />
      )}
    </>
  );
}

function PlaceholderConfigModal({
  row,
  onClose,
  onSaved,
}: {
  row: IntegrationPlaceholder;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isJitterbit = row.provider === "jitterbit";
  const initialConfig = (row.config || {}) as Record<string, string>;
  const [endpointUrl, setEndpointUrl] = useState<string>(String(initialConfig.endpoint_url || ""));
  const [authHeader, setAuthHeader] = useState<string>(String(initialConfig.auth_header_name || (isJitterbit ? "X-API-Key" : "X-DocuNet-Token")));
  const [authSecret, setAuthSecret] = useState<string>(String(initialConfig.auth_secret || ""));
  const [docType, setDocType] = useState<string>(String(initialConfig.doc_type || (isJitterbit ? "" : "FCNV")));
  const [note, setNote] = useState<string>(row.note || "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onSave = async () => {
    setSaving(true);
    setErr(null);
    try {
      const cfg: Record<string, unknown> = {
        endpoint_url: endpointUrl.trim(),
        auth_header_name: authHeader.trim(),
        auth_secret: authSecret.trim(),
      };
      if (!isJitterbit) cfg.doc_type = docType.trim();
      await api.integrations.placeholders.update(row.provider, { config: cfg, note: note.trim() || undefined });
      onSaved();
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-6">
      <div className="card w-full max-w-lg p-6 space-y-4">
        <div>
          <h3 className="text-lg font-semibold text-zbrain-ink inline-flex items-center gap-1.5">
            Configure {row.label}
            <InfoTip
              text={
                isJitterbit
                  ? "Operator-supplied endpoint for the Jitterbit bridge to Oracle EBS and DocuNet. ZBrain POSTs executed actions here once enabled; until then writes stay in the local mock."
                  : "DocuNet handoff configuration. Files route via Jitterbit; this card stores the doc-type tag and POST authentication. Enable to dual-write SOAs and attachments alongside SharePoint."
              }
            />
          </h3>
        </div>
        <label className="block text-sm">
          <span className="text-zbrain-ink font-medium">Endpoint URL</span>
          <input
            value={endpointUrl}
            onChange={(e) => setEndpointUrl(e.target.value)}
            placeholder={isJitterbit ? "https://jitterbit.keysight.local/api/v1/orders" : "https://docunet.keysight.local/api/v1/files"}
            className="mt-1 w-full border border-zbrain-divider rounded px-3 py-1.5 text-sm"
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-sm">
            <span className="text-zbrain-ink font-medium">Auth header name</span>
            <input
              value={authHeader}
              onChange={(e) => setAuthHeader(e.target.value)}
              className="mt-1 w-full border border-zbrain-divider rounded px-3 py-1.5 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="text-zbrain-ink font-medium">Auth secret</span>
            <input
              type="password"
              value={authSecret}
              onChange={(e) => setAuthSecret(e.target.value)}
              placeholder="••••••••"
              className="mt-1 w-full border border-zbrain-divider rounded px-3 py-1.5 text-sm"
            />
          </label>
        </div>
        {!isJitterbit && (
          <label className="block text-sm">
            <span className="text-zbrain-ink font-medium">Doc type tag</span>
            <input
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              placeholder="FCNV"
              className="mt-1 w-full border border-zbrain-divider rounded px-3 py-1.5 text-sm"
            />
            <span className="text-[11px] text-zbrain-muted">Applied to every file filed via DocuNet (Keysight default: FCNV).</span>
          </label>
        )}
        <label className="block text-sm">
          <span className="text-zbrain-ink font-medium">Operator note</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            className="mt-1 w-full border border-zbrain-divider rounded px-3 py-1.5 text-sm"
            placeholder="Anything the next operator should know about this connection."
          />
        </label>
        {err && <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2">{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-secondary text-xs">Cancel</button>
          <button onClick={onSave} disabled={saving} className="btn-primary text-xs">{saving ? "Saving…" : "Save configuration"}</button>
        </div>
      </div>
    </div>
  );
}

function StaticTile({ card }: { card: StaticCard }) {
  const isConnected = card.status === "connected";
  const isPlanned = card.status === "planned";
  const logoNode =
    card.key === "azure_doc_intelligence" || card.key === "azure_translator"
      ? <AzureLogo />
      : undefined;
  return (
    <TileShell
      iconBg={card.iconBg}
      iconLetter={card.iconLetter}
      iconNode={logoNode}
      name={card.name}
      category={card.category}
      description={card.description}
      detail={
        <div className="space-y-1">
          <div>{card.detail}</div>
          {card.envSourced && (
            <div className="text-[11px] text-zbrain-muted">
              <span className="font-mono">{card.envSourced.envVar}</span>{" "}
              <span className="font-mono">{card.envSourced.masked}</span>
            </div>
          )}
        </div>
      }
      statusPill={
        isConnected ? (
          <span className="pill bg-emerald-50 text-emerald-700">Connected · env-sourced</span>
        ) : isPlanned ? (
          <span className="pill bg-slate-100 text-slate-600">Roadmap</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Available</span>
        )
      }
      actions={
        isConnected ? (
          <span className="text-xs text-zbrain-muted">
            Edit <code className="font-mono">{card.envSourced?.envVar}</code> in <code className="font-mono">backend/.env</code> and restart to rotate the credential.
          </span>
        ) : isPlanned ? (
          <span className="text-xs text-zbrain-muted">Roadmap: Q3 2026</span>
        ) : (
          <button
            disabled
            className="btn-secondary text-xs opacity-60 cursor-not-allowed"
            title="Provide credentials to enable this integration"
          >
            Connect (provide credentials)
          </button>
        )
      }
    />
  );
}

function SalesforceConnectModal({
  existing,
  onClose,
  onSaved,
}: {
  existing: SalesforceStatus | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [instanceUrl, setInstanceUrl] = useState(existing?.instance_url || "");
  const [consumerKey, setConsumerKey] = useState("");
  const [consumerSecret, setConsumerSecret] = useState("");
  const [label, setLabel] = useState(existing?.label || "Production org");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string; whoami?: any } | null>(null);

  const buildBody = (): SalesforceConnectBody => ({
    instance_url: instanceUrl.trim().replace(/\/$/, ""),
    consumer_key: consumerKey.trim(),
    consumer_secret: consumerSecret.trim(),
    flow: "client_credentials",
    label: label.trim() || "Production org",
  });

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.integrations.salesforce.test(buildBody());
      setTestResult({ ok: res.ok, msg: res.message, whoami: res.whoami });
    } catch (e: any) {
      setTestResult({ ok: false, msg: e?.message || "test failed" });
    } finally {
      setTesting(false);
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await api.integrations.salesforce.connect(buildBody());
      onSaved();
    } catch (e: any) {
      setTestResult({ ok: false, msg: e?.message?.includes("400") ? "Connection rejected. Check credentials." : e?.message });
    } finally {
      setSaving(false);
    }
  };

  const canSubmit = !!instanceUrl && !!consumerKey && !!consumerSecret;

  return (
    <div className="fixed inset-0 bg-zbrain-ink/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl max-h-[90vh] overflow-auto">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-center justify-between">
          <h2 className="text-base font-semibold">Connect Salesforce</h2>
          <button onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink text-lg leading-none">
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div className="text-xs text-zbrain-muted bg-zbrain-surface border border-zbrain-divider rounded-md p-3">
            <strong className="text-zbrain-ink">OAuth 2.0 Client Credentials Flow.</strong> No usernames or passwords stored;
            server-to-server authentication via your External Client App's consumer key + secret.
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Instance URL</label>
            <input
              value={instanceUrl}
              onChange={(e) => setInstanceUrl(e.target.value)}
              placeholder="https://yourorg.my.salesforce.com"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Consumer Key</label>
            <input
              value={consumerKey}
              onChange={(e) => setConsumerKey(e.target.value)}
              placeholder="3MVG9..."
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Consumer Secret</label>
            <input
              type="password"
              value={consumerSecret}
              onChange={(e) => setConsumerSecret(e.target.value)}
              placeholder="••••••••••••••••"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Label</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Production org"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
            />
          </div>

          {testResult && (
            <div
              className={`text-sm rounded-md p-3 ${
                testResult.ok
                  ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  : "bg-rose-50 text-rose-800 border border-rose-200"
              }`}
            >
              {testResult.ok ? (
                <>
                  <div className="font-medium">✓ Connected</div>
                  {testResult.whoami && (
                    <div className="text-xs mt-1">
                      Org <strong>{testResult.whoami.org_name}</strong> ({testResult.whoami.org_edition}) · running as{" "}
                      <strong>{testResult.whoami.user_display_name}</strong>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="font-medium">✗ Connection failed</div>
                  <div className="text-xs mt-1 font-mono">{testResult.msg}</div>
                </>
              )}
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
              {saving ? "Saving…" : "Save & connect"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SharePointTile({
  status,
  onConnect,
  onChange,
}: {
  status: SharePointStatus | null;
  onConnect: () => void;
  onChange: () => void;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const connected = !!status?.connected;

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await api.integrations.sharepoint.refresh();
      onChange();
    } finally {
      setRefreshing(false);
    }
  };

  const onDisconnect = async () => {
    if (!confirm("Disconnect SharePoint? Files in the library are not deleted. You can reconnect later.")) return;
    await api.integrations.sharepoint.disconnect();
    onChange();
  };

  let detail: React.ReactNode =
    "Document library for inbound customer files and outbound generated artifacts (SOAs, invoices, cal certs).";
  if (connected) {
    detail = (
      <span>
        Site <span className="font-medium text-zbrain-ink">{status?.site_display_name || status?.site_id}</span>
        {status?.drive_name && (
          <>
            {" "}· library <span className="font-medium text-zbrain-ink">{status.drive_name}</span>
          </>
        )}
        {" "}· folder <span className="font-mono text-zbrain-ink">{status?.folder_path || "/"}</span>
        {status?.item_count != null && (
          <>
            <br />
            {status.item_count.toLocaleString()} items in folder
          </>
        )}
        {status?.last_tested_at && (
          <>
            <br />
            <span className="text-zbrain-muted">
              Last verified {new Date(status.last_tested_at).toLocaleString()}
            </span>
          </>
        )}
        {status?.last_error && (
          <>
            <br />
            <span className="text-rose-700 text-xs font-mono">{status.last_error}</span>
          </>
        )}
      </span>
    );
  }

  return (
    <TileShell
      iconBg="bg-indigo-100 text-indigo-700"
      iconLetter="SP"
      iconNode={<SharePointLogo />}
      name="SharePoint"
      category="Documents"
      description="Read PDFs from a managed library and write generated SOAs / invoices / cal certs back to it."
      detail={detail}
      statusPill={
        connected ? (
          <span className="pill bg-emerald-100 text-emerald-700">Connected</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Available</span>
        )
      }
      actions={
        connected ? (
          <>
            <button onClick={onRefresh} disabled={refreshing} className="btn-secondary text-xs">
              {refreshing ? "Verifying…" : "Verify connection"}
            </button>
            {status?.site_web_url && (
              <a
                href={status.site_web_url}
                target="_blank"
                rel="noreferrer"
                className="btn-secondary text-xs"
                title="Open the SharePoint site in a new tab"
              >
                Open in SharePoint ↗
              </a>
            )}
            <button onClick={onConnect} className="btn-secondary text-xs">
              Reconfigure
            </button>
            <button
              onClick={onDisconnect}
              className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
            >
              Disconnect
            </button>
          </>
        ) : (
          <button onClick={onConnect} className="btn-primary text-xs">
            Connect SharePoint
          </button>
        )
      }
    />
  );
}

function SharePointConnectModal({
  existing,
  onClose,
  onSaved,
}: {
  existing: SharePointStatus | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [tenantId, setTenantId] = useState(existing?.tenant_id || "");
  const [clientId, setClientId] = useState(existing?.client_id || "");
  const [clientSecret, setClientSecret] = useState("");
  const [siteId, setSiteId] = useState(existing?.site_id || "");
  const [driveId, setDriveId] = useState(existing?.drive_id || "");
  const [folderPath, setFolderPath] = useState(existing?.folder_path || "/");
  const [label, setLabel] = useState(existing?.label || "Production site");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string; whoami?: any } | null>(null);

  const buildBody = (): SharePointConnectBody => ({
    tenant_id: tenantId.trim(),
    client_id: clientId.trim(),
    client_secret: clientSecret.trim(),
    site_id: siteId.trim(),
    drive_id: driveId.trim() || null,
    folder_path: folderPath.trim() || "/",
    label: label.trim() || "Production site",
  });

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.integrations.sharepoint.test(buildBody());
      setTestResult({ ok: res.ok, msg: res.message, whoami: res.whoami });
    } catch (e: any) {
      setTestResult({ ok: false, msg: e?.message || "test failed" });
    } finally {
      setTesting(false);
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await api.integrations.sharepoint.connect(buildBody());
      onSaved();
    } catch (e: any) {
      setTestResult({
        ok: false,
        msg: e?.message?.includes("400") ? "Connection rejected. Check credentials and admin consent." : e?.message,
      });
    } finally {
      setSaving(false);
    }
  };

  const canSubmit = !!tenantId && !!clientId && !!clientSecret && !!siteId;

  return (
    <div className="fixed inset-0 bg-zbrain-ink/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl max-h-[90vh] overflow-auto">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-center justify-between">
          <h2 className="text-base font-semibold">Connect SharePoint</h2>
          <button onClick={onClose} className="text-zbrain-muted hover:text-zbrain-ink text-lg leading-none">
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div className="text-xs text-zbrain-muted bg-zbrain-surface border border-zbrain-divider rounded-md p-3">
            <strong className="text-zbrain-ink">Microsoft Graph + OAuth client_credentials.</strong> Register an app in
            Entra ID, grant <span className="font-mono">Sites.ReadWrite.All</span> +{" "}
            <span className="font-mono">Files.ReadWrite.All</span> application permissions, and have a Global Admin click{" "}
            <em>Grant admin consent</em>.
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Directory (tenant) ID</label>
            <input
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Application (client) ID</label>
            <input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Client secret</label>
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder={existing?.connected ? "(paste again to update)" : "secret value"}
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Site ID</label>
            <input
              value={siteId}
              onChange={(e) => setSiteId(e.target.value)}
              placeholder="contoso.sharepoint.com,abc123-...,def456-..."
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Drive ID (optional)</label>
              <input
                value={driveId}
                onChange={(e) => setDriveId(e.target.value)}
                placeholder="default Documents library"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Folder path</label>
              <input
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
                placeholder="/Salesops"
                className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none font-mono"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wider text-zbrain-muted mb-1">Label</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Production site"
              className="w-full border border-zbrain-divider rounded-md text-sm px-3 py-2 focus:border-zbrain focus:outline-none"
            />
          </div>

          {testResult && (
            <div
              className={`text-sm rounded-md p-3 ${
                testResult.ok
                  ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  : "bg-rose-50 text-rose-800 border border-rose-200"
              }`}
            >
              {testResult.ok ? (
                <>
                  <div className="font-medium">✓ Connected</div>
                  {testResult.whoami && (
                    <div className="text-xs mt-1">
                      Site <strong>{testResult.whoami.site_display_name || testResult.whoami.site_id}</strong>
                      {testResult.whoami.drive_name && <> · library <strong>{testResult.whoami.drive_name}</strong></>}
                      {" "}· <strong>{testResult.whoami.item_count ?? 0}</strong> items in folder{" "}
                      <span className="font-mono">{testResult.whoami.folder_path}</span>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="font-medium">✗ Connection failed</div>
                  <div className="text-xs mt-1 font-mono">{testResult.msg}</div>
                </>
              )}
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
              {saving ? "Saving…" : "Save & connect"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// AIOA (Order Acceptance) provider tile + connect modal
// ============================================================================

function AIOATile({
  provider,
  onConnect,
  onChange,
}: {
  provider: AIOAProvider | null;
  onConnect: () => void;
  onChange: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const configured = !!provider && !!(provider.outbound_url || "").trim() && !!provider.is_active;

  const onTest = async () => {
    if (!provider) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await aioaApi.testProvider(provider.id);
      setTestResult(r.ok ? `Probe OK · HTTP ${r.http_status}` : `Probe failed · ${r.error || `HTTP ${r.http_status}`}`);
    } catch (e: any) {
      setTestResult(`Probe error: ${e?.message || e}`);
    } finally {
      setTesting(false);
    }
  };

  const callbackReady = !!provider?.callback_url_configured;
  let detail: React.ReactNode =
    "Send order-acceptance validation requests to the external AIOA tool via webhook. The pipeline parks until AIOA responds or the timeout window elapses.";
  if (provider) {
    detail = (
      <span>
        {configured ? (
          <>
            Outbound <span className="font-mono text-zbrain-ink">{provider.outbound_url}</span>
            <br />
            Timeout <span className="font-medium text-zbrain-ink">{Math.round(provider.timeout_seconds / 60)} min</span>
            {" · auth "}<span className="font-medium text-zbrain-ink">{provider.outbound_auth_scheme}</span>
            {!callbackReady && (
              <>
                <br />
                <span className="text-amber-700">
                  Callback URL not yet derivable from a public host. AIOA cannot reach this app until APP_BASE_URL is set or a public tunnel is running.
                </span>
              </>
            )}
          </>
        ) : (
          <span className="text-zbrain-muted">No outbound URL set yet. Click Configure to point ZBrain at your AIOA endpoint.</span>
        )}
        {provider.last_send_at && (
          <>
            <br />
            <span className="text-zbrain-muted">
              Last outbound send {new Date(provider.last_send_at).toLocaleString()}
            </span>
          </>
        )}
        {provider.last_callback_at ? (
          <>
            <br />
            <span className="text-zbrain-muted">
              Last callback received {new Date(provider.last_callback_at).toLocaleString()}
            </span>
          </>
        ) : null}
        {testResult && (
          <>
            <br />
            <span className="text-xs font-mono text-zbrain-ink">{testResult}</span>
          </>
        )}
      </span>
    );
  }

  return (
    <TileShell
      iconBg="bg-amber-100 text-amber-800"
      iconLetter="AO"
      iconNode={<AIOALogo />}
      name="AIOA"
      category="Order Acceptance"
      description="Order Acceptance webhook used during Stage 3 of the pipeline. Pipeline parks in awaiting state until AIOA returns PASS or FAIL."
      detail={detail}
      statusPill={
        configured ? (
          <span className="pill bg-emerald-100 text-emerald-700">Connected</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Not configured</span>
        )
      }
      actions={
        configured ? (
          <>
            <button onClick={onTest} disabled={testing} className="btn-secondary text-xs">
              {testing ? "Probing…" : "Test probe"}
            </button>
            <button onClick={onConnect} className="btn-secondary text-xs">
              Reconfigure
            </button>
          </>
        ) : (
          <button onClick={onConnect} className="btn-primary text-xs">
            Configure AIOA
          </button>
        )
      }
    />
  );
}

function AIOAConnectModal({
  existing,
  onClose,
  onSaved,
}: {
  existing: AIOAProvider;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(existing.name || "AIOA");
  const [outboundUrl, setOutboundUrl] = useState(existing.outbound_url || "");
  const [authScheme, setAuthScheme] = useState<AIOAProvider["outbound_auth_scheme"]>(existing.outbound_auth_scheme || "none");
  const [authValue, setAuthValue] = useState("");
  const [timeoutMinutes, setTimeoutMinutes] = useState(Math.round((existing.timeout_seconds || 1800) / 60));
  const [isActive, setIsActive] = useState(existing.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canSubmit = !!outboundUrl.trim() && !saving;

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const body: AIOAProviderInput = {
        name: name.trim() || "AIOA",
        outbound_url: outboundUrl.trim(),
        outbound_auth_scheme: authScheme,
        outbound_auth_value: authValue ? authValue : null,
        timeout_seconds: Math.max(60, Math.round(timeoutMinutes * 60)),
        retry_max: existing.retry_max,
        retry_backoff_seconds: existing.retry_backoff_seconds,
        is_active: isActive,
      };
      await aioaApi.updateProvider(existing.id, body);
      onSaved();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[90vh] flex flex-col">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-zbrain-ink inline-flex items-center gap-1.5">
              Configure AIOA
              <InfoTip text="ZBrain POSTs validation requests to the outbound URL. The inbound callback URL and shared secret below are what AIOA POSTs results back to." />
            </h2>
          </div>
        </div>

        <div className="px-6 py-5 space-y-5 overflow-y-auto">
          <div className="rounded-md border border-zbrain-divider bg-white p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-zbrain-ink">ZBrain → AIOA (outbound)</h3>
              <p className="text-xs text-zbrain-muted mt-0.5">
                Where ZBrain sends each validation request and how it authenticates.
              </p>
            </div>

            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">Display name</label>
              <input
                className="form-input w-full mt-1"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="AIOA"
              />
            </div>

            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">Outbound webhook URL</label>
              <input
                className="form-input w-full mt-1 font-mono text-sm"
                value={outboundUrl}
                onChange={(e) => setOutboundUrl(e.target.value)}
                placeholder="https://aioa.example.com/api/v1/order-acceptance/inbound"
              />
              <p className="text-xs text-zbrain-muted mt-1">
                Leave blank to keep the AIOA flow paused on every request until configured.
              </p>
            </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">Auth scheme</label>
              <select
                className="form-input w-full mt-1"
                value={authScheme}
                onChange={(e) => setAuthScheme(e.target.value as AIOAProvider["outbound_auth_scheme"])}
              >
                <option value="none">None</option>
                <option value="bearer">Bearer token</option>
                <option value="api_key">API key (X-API-Key header)</option>
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">
                Auth value {existing.has_outbound_auth_value && <span className="text-zbrain-muted normal-case tracking-normal">(existing kept if blank)</span>}
              </label>
              <input
                className="form-input w-full mt-1 font-mono text-sm"
                type="password"
                value={authValue}
                onChange={(e) => setAuthValue(e.target.value)}
                placeholder={existing.has_outbound_auth_value ? "•••••• (existing)" : ""}
                disabled={authScheme === "none"}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">Timeout (minutes)</label>
              <input
                className="form-input w-full mt-1"
                type="number"
                min={1}
                max={1440}
                value={timeoutMinutes}
                onChange={(e) => setTimeoutMinutes(Number(e.target.value) || 30)}
              />
              <p className="text-xs text-zbrain-muted mt-1">
                If AIOA doesn't respond within this window, the pipeline rolls to CSR fallout automatically.
              </p>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">Status</label>
              <select
                className="form-input w-full mt-1"
                value={isActive ? "y" : "n"}
                onChange={(e) => setIsActive(e.target.value === "y")}
              >
                <option value="y">Active</option>
                <option value="n">Paused</option>
              </select>
              <p className="text-xs text-zbrain-muted mt-1">
                When paused, queued requests sit until the timeout window elapses.
              </p>
            </div>
          </div>
          </div>

          <div className="rounded-md border border-zbrain-divider bg-zbrain-surface p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-zbrain-ink">AIOA → ZBrain (inbound)</h3>
              <p className="text-xs text-zbrain-muted mt-0.5">
                Hand these two values to whoever runs the AIOA service. They will POST validation
                results to the callback URL using the secret in the <code>X-AIOA-Signature</code> header.
              </p>
            </div>
            <CalloutReadOnlyField
              label="Inbound callback URL"
              value={existing.callback_url}
              emptyHint="Public URL not available yet. Set APP_BASE_URL or expose the app via cloudflared, then reopen this dialog."
            />
            <CalloutReadOnlyField
              label="Inbound shared secret"
              value={existing.inbound_secret}
              secret
              emptyHint="Secret will be generated when the provider is first saved."
            />
          </div>

          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-zbrain-divider flex items-center justify-end gap-2 bg-zbrain-surface">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button onClick={onSave} disabled={!canSubmit} className="btn-primary">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldReadOnly({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">{label}</div>
      <div className="flex items-center gap-2 mt-0.5">
        <code className="text-xs bg-white border border-zbrain-divider rounded px-2 py-1 flex-1 break-all">{value}</code>
        <button
          type="button"
          onClick={() => navigator.clipboard.writeText(value)}
          className="text-xs text-zbrain hover:underline"
        >
          copy
        </button>
      </div>
    </div>
  );
}

/**
 * Read-only field for the AIOA Settings modal.
 *
 * Handles three states:
 *  - value missing: render an amber empty-state hint, no copy button.
 *  - value present + secret: render masked, with show/hide and copy.
 *  - value present: render plain, with copy + copied-toast feedback.
 */
function CalloutReadOnlyField({
  label,
  value,
  secret = false,
  emptyHint,
}: {
  label: string;
  value: string;
  secret?: boolean;
  emptyHint?: string;
}) {
  const [shown, setShown] = useState(!secret);
  const [copied, setCopied] = useState(false);
  const hasValue = !!(value || "").trim();

  const display = hasValue ? (shown ? value : value.replace(/./g, "•")) : "";

  const onCopy = async () => {
    if (!hasValue) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {}
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="text-[11px] uppercase tracking-wider text-zbrain-muted font-medium">{label}</div>
        <div className="flex items-center gap-3 text-[11px]">
          {hasValue && secret && (
            <button
              type="button"
              onClick={() => setShown((s) => !s)}
              className="text-zbrain hover:underline"
            >
              {shown ? "Hide" : "Show"}
            </button>
          )}
          {hasValue && (
            <button
              type="button"
              onClick={onCopy}
              className="text-zbrain hover:underline"
              title="Copy to clipboard"
            >
              {copied ? "Copied ✓" : "Copy"}
            </button>
          )}
        </div>
      </div>
      {hasValue ? (
        <code className="block text-xs bg-white border border-zbrain-divider rounded px-3 py-2 break-all font-mono leading-relaxed">
          {display}
        </code>
      ) : (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {emptyHint || "Not configured."}
        </div>
      )}
    </div>
  );
}


// ============================================================================
// OpenAI provider tile + connect modal
// ============================================================================

function OpenAITile({
  status,
  onConnect,
  onChange,
}: {
  status: OpenAIStatus | null;
  onConnect: () => void;
  onChange: () => void;
}) {
  const connected = !!status?.connected;
  const source = status?.source || "none";

  const onDisconnect = async () => {
    if (!confirm("Disconnect OpenAI? The pipeline will fall back to the OPENAI_API_KEY env var, or LLM calls will skip if no env key is set.")) return;
    await api.integrations.openai.disconnect();
    onChange();
  };

  let detail: React.ReactNode =
    "LLM provider used by Intake (classification, language detection, spam screen) and the draft generator. The key is encrypted at rest.";
  if (status) {
    detail = (
      <span>
        Model <span className="font-mono text-zbrain-ink">{status.model}</span>
        <br />
        Source <span className="font-medium text-zbrain-ink">{source === "db" ? "configured here" : source === "env" ? "OPENAI_API_KEY env var" : "not set"}</span>
        {status.api_key_masked && (
          <>
            {" · key "}<span className="font-mono text-zbrain-ink">{status.api_key_masked}</span>
          </>
        )}
        {status.last_tested_at && (
          <>
            <br />
            <span className="text-zbrain-muted">
              Last verified {new Date(status.last_tested_at).toLocaleString()}
            </span>
          </>
        )}
        {status.last_error && (
          <>
            <br />
            <span className="text-rose-700 text-xs font-mono">{status.last_error}</span>
          </>
        )}
      </span>
    );
  }

  return (
    <TileShell
      iconBg="bg-slate-900 text-white"
      iconLetter="AI"
      iconNode={<OpenAILogo />}
      name="OpenAI"
      category="LLM"
      description="The language model that classifies inbound mail, extracts business data, drafts customer replies, and runs verifier checks."
      detail={detail}
      statusPill={
        connected ? (
          <span className="pill bg-emerald-100 text-emerald-700">Connected</span>
        ) : (
          <span className="pill bg-zbrain-50 text-zbrain">Available</span>
        )
      }
      actions={
        connected ? (
          <>
            <button onClick={onConnect} className="btn-secondary text-xs">
              Reconfigure
            </button>
            {source === "db" && (
              <button
                onClick={onDisconnect}
                className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
              >
                Disconnect
              </button>
            )}
          </>
        ) : (
          <button onClick={onConnect} className="btn-primary text-xs">
            Connect OpenAI
          </button>
        )
      }
    />
  );
}

function OpenAIConnectModal({
  existing,
  onClose,
  onSaved,
}: {
  existing: OpenAIStatus | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(existing?.model || "gpt-5.2");
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canSubmit = !!apiKey.trim() && !busy;

  const body: OpenAIConnectBody = { api_key: apiKey.trim(), model: model.trim() || null };

  const onTest = async () => {
    setBusy(true);
    setError(null);
    setTestResult(null);
    try {
      const r = await api.integrations.openai.test(body);
      setTestResult({ ok: r.ok, message: r.message || (r.ok ? "Authenticated." : "Failed.") });
    } catch (e: any) {
      setTestResult({ ok: false, message: e?.message || String(e) });
    } finally {
      setBusy(false);
    }
  };

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.integrations.openai.connect(body);
      onSaved();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg max-w-2xl w-full max-h-[90vh] flex flex-col">
        <div className="px-6 py-4 border-b border-zbrain-divider">
          <h2 className="text-lg font-semibold text-zbrain-ink inline-flex items-center gap-1.5">
            Configure OpenAI
            <InfoTip text="ZBrain calls OpenAI for intent classification, document extraction, and reply drafting. Paste a key to override OPENAI_API_KEY; the value is encrypted at rest." />
          </h2>
        </div>

        <div className="px-6 py-5 space-y-5 overflow-y-auto">
          <div className="rounded-md border border-zbrain-divider bg-white p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-zbrain-ink">Credentials</h3>
              <p className="text-xs text-zbrain-muted mt-0.5">
                Get a key from <span className="font-mono">platform.openai.com → API keys</span>. Project-scoped keys
                (sk-proj-…) and standard keys are both supported.
              </p>
            </div>

            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">API key</label>
              <input
                className="form-input w-full mt-1 font-mono text-sm"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={existing?.api_key_masked ? `Existing: ${existing.api_key_masked}` : "sk-proj-..."}
                type="password"
                autoComplete="new-password"
              />
              <p className="text-[11.5px] text-zbrain-muted mt-1">
                Leave blank to keep the existing key. Saving a new value replaces the current credentials.
              </p>
            </div>

            <div>
              <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">Model</label>
              <select
                className="form-input w-full mt-1"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                <option value="gpt-5.2">gpt-5.2 (recommended)</option>
                <option value="gpt-5">gpt-5</option>
                <option value="gpt-4.1">gpt-4.1</option>
                <option value="gpt-4o">gpt-4o</option>
              </select>
              <p className="text-[11.5px] text-zbrain-muted mt-1">
                Used by every pipeline stage that talks to the LLM. Cost is metered per call and rolls up
                under Analytics → AI infrastructure cost.
              </p>
            </div>
          </div>

          {testResult && (
            <div
              className={
                "rounded-md border px-3 py-2 text-xs " +
                (testResult.ok
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : "border-rose-200 bg-rose-50 text-rose-900")
              }
            >
              <strong>{testResult.ok ? "Test passed." : "Test failed."}</strong> {testResult.message}
            </div>
          )}

          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-zbrain-divider flex items-center justify-between gap-2 bg-zbrain-surface">
          <button onClick={onTest} disabled={!canSubmit} className="btn-secondary">
            {busy ? "Testing..." : "Test connection"}
          </button>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary">Cancel</button>
            <button onClick={onSave} disabled={!canSubmit} className="btn-primary">
              {busy ? "Saving..." : "Save and connect"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


// ============================================================================
// Salesforce details modal
// ============================================================================

function SalesforceDetailsModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.integrations.salesforceDetails>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    api.integrations
      .salesforceDetails()
      .then((d) => {
        if (cancel) return;
        setData(d);
        setLoading(false);
      })
      .catch((e: any) => {
        if (cancel) return;
        setErr(e?.message || String(e));
        setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, []);

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg max-w-5xl w-full max-h-[92vh] flex flex-col">
        <div className="px-6 py-4 border-b border-zbrain-divider flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-zbrain-ink">Salesforce details</h2>
            <p className="text-xs text-zbrain-muted mt-0.5">
              Live read from the connected org. Queues, queue members, and headline counts.
              Click any record to open it directly in Salesforce.
            </p>
          </div>
          <button onClick={onClose} className="btn-secondary text-xs">Close</button>
        </div>

        <div className="px-6 py-5 overflow-y-auto space-y-5">
          {loading && <div className="text-sm text-zbrain-muted">Loading from Salesforce…</div>}
          {err && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              Failed to load: {err}
            </div>
          )}

          {data && (
            <>
              <div className="rounded-md border border-zbrain-divider bg-zbrain-surface px-4 py-3 flex items-center justify-between flex-wrap gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-zbrain-muted font-medium">Connected org</div>
                  <div className="text-sm font-semibold mt-0.5">{data.org_name}</div>
                  <a
                    className="text-[11px] font-mono text-zbrain hover:underline"
                    href={data.instance_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {data.instance_url}
                  </a>
                </div>
                <div className="grid grid-cols-3 gap-x-6 gap-y-2 text-xs">
                  <Counter label="Accounts" value={data.counts.accounts} />
                  <Counter label="Cases (open)" value={data.counts.cases_open} highlight />
                  <Counter label="Cases (total)" value={data.counts.cases_total} />
                  <Counter label="Orders" value={data.counts.orders} />
                  <Counter label="Work orders" value={data.counts.work_orders} />
                  <Counter label="Service contracts" value={data.counts.service_contracts} />
                </div>
              </div>

              <section>
                <h3 className="text-sm font-semibold mb-2">Queues and members</h3>
                <p className="text-[11.5px] text-zbrain-muted mb-2">
                  The ZBrain CSR queues provisioned in this org. Each queue is a routing destination
                  the Decision Agent can stamp as the preliminary owner. CSRs are queue members.
                </p>
                <div className="space-y-3">
                  {data.queues.map((q) => (
                    <div key={q.id} className="rounded-md border border-zbrain-divider bg-white">
                      <div className="px-4 py-3 flex items-center justify-between border-b border-zbrain-divider/70">
                        <div>
                          <div className="text-sm font-semibold text-zbrain-ink">{q.name}</div>
                          <div className="text-[11px] text-zbrain-muted font-mono mt-0.5">{q.developer_name}</div>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="pill bg-zbrain-50 text-zbrain text-[11px]">
                            {q.member_count} {q.member_count === 1 ? "member" : "members"}
                          </span>
                          {q.queue_url && (
                            <a
                              href={q.queue_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[11px] text-zbrain hover:underline whitespace-nowrap"
                            >
                              Open in Salesforce ↗
                            </a>
                          )}
                        </div>
                      </div>
                      {q.members.length === 0 ? (
                        <div className="px-4 py-3 text-[12px] text-zbrain-muted italic">
                          No members assigned to this queue. Cases routed here will sit until someone claims them.
                        </div>
                      ) : (
                        <table className="w-full text-[12px]">
                          <thead className="text-zbrain-muted bg-zbrain-surface/40">
                            <tr>
                              <th className="text-left px-4 py-1.5 font-medium">Name</th>
                              <th className="text-left px-4 py-1.5 font-medium">Email</th>
                              <th className="text-left px-4 py-1.5 font-medium">Status</th>
                              <th className="text-right px-4 py-1.5 font-medium">Profile</th>
                            </tr>
                          </thead>
                          <tbody>
                            {q.members.map((m) => (
                              <tr key={m.id} className="border-t border-zbrain-divider/60">
                                <td className="px-4 py-2 font-medium text-zbrain-ink">{m.name}</td>
                                <td className="px-4 py-2 font-mono text-[11.5px] text-zbrain-muted">{m.email || m.username}</td>
                                <td className="px-4 py-2">
                                  {m.is_active ? (
                                    <span className="pill bg-emerald-50 text-emerald-700 text-[10px]">Active</span>
                                  ) : (
                                    <span className="pill bg-zinc-100 text-zinc-600 text-[10px]">Inactive</span>
                                  )}
                                </td>
                                <td className="px-4 py-2 text-right">
                                  {m.profile_url && (
                                    <a
                                      href={m.profile_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-[11px] text-zbrain hover:underline whitespace-nowrap"
                                    >
                                      Open in Salesforce ↗
                                    </a>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <h3 className="text-sm font-semibold mb-2">Recent Cases</h3>
                <div className="rounded-md border border-zbrain-divider overflow-hidden">
                  <table className="w-full text-[12px]">
                    <thead className="text-zbrain-muted bg-zbrain-surface">
                      <tr>
                        <th className="text-left px-4 py-2 font-medium">Case #</th>
                        <th className="text-left px-4 py-2 font-medium">Subject</th>
                        <th className="text-left px-4 py-2 font-medium">Account</th>
                        <th className="text-left px-4 py-2 font-medium">Status</th>
                        <th className="text-left px-4 py-2 font-medium">Created</th>
                        <th className="text-right px-4 py-2 font-medium">Open</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_cases.map((c) => (
                        <tr key={c.id} className="border-t border-zbrain-divider/60">
                          <td className="px-4 py-2 font-mono">{c.case_number}</td>
                          <td className="px-4 py-2 max-w-[300px] truncate" title={c.subject || ""}>
                            {c.subject || "n/a"}
                          </td>
                          <td className="px-4 py-2">{c.account_name || "n/a"}</td>
                          <td className="px-4 py-2">{c.status || "n/a"}</td>
                          <td className="px-4 py-2 text-[11px] text-zbrain-muted">
                            {c.created_at ? new Date(c.created_at).toLocaleString() : "n/a"}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {c.url && (
                              <a
                                href={c.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-[11px] text-zbrain hover:underline whitespace-nowrap"
                              >
                                Open ↗
                              </a>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section>
                <h3 className="text-sm font-semibold mb-2">Recent Accounts</h3>
                <div className="rounded-md border border-zbrain-divider overflow-hidden">
                  <table className="w-full text-[12px]">
                    <thead className="text-zbrain-muted bg-zbrain-surface">
                      <tr>
                        <th className="text-left px-4 py-2 font-medium">Name</th>
                        <th className="text-left px-4 py-2 font-medium">Industry</th>
                        <th className="text-left px-4 py-2 font-medium">Created</th>
                        <th className="text-right px-4 py-2 font-medium">Open</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_accounts.map((a) => (
                        <tr key={a.id} className="border-t border-zbrain-divider/60">
                          <td className="px-4 py-2 font-medium text-zbrain-ink">{a.name || "n/a"}</td>
                          <td className="px-4 py-2">{a.industry || "n/a"}</td>
                          <td className="px-4 py-2 text-[11px] text-zbrain-muted">
                            {a.created_at ? new Date(a.created_at).toLocaleString() : "n/a"}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {a.url && (
                              <a
                                href={a.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-[11px] text-zbrain hover:underline whitespace-nowrap"
                              >
                                Open ↗
                              </a>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Counter({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-zbrain-muted">{label}</span>
      <span className={"font-semibold tabular-nums " + (highlight ? "text-emerald-700" : "text-zbrain-ink")}>
        {value.toLocaleString()}
      </span>
    </div>
  );
}
