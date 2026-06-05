import { useEffect, useState } from "react";

import { api, CustomerDetail } from "../api";
import { StatusPill } from "./Pills";

const COMPLIANCE_LEGEND: Record<string, string> = {
  ITAR: "Int'l Traffic in Arms Regulations: defense items, US-controlled",
  EAR: "Export Administration Regulations: dual-use items",
  EAR99: "EAR catch-all classification: generally exportable",
  AS9100: "Aerospace quality management standard",
  DFARS_252_204_7012: "DoD cybersecurity & cloud requirements",
  ISO_17025: "Calibration / testing lab competence",
  ISO_9001: "Quality management systems",
  ISO_14001: "Environmental management systems",
  IATF_16949: "Automotive quality management standard",
  ISO_26262: "Automotive functional safety",
  ETSI_EN_301: "European wireless conformance",
};

const SLA_COLOR: Record<string, string> = {
  Platinum: "bg-violet-100 text-violet-800",
  Gold: "bg-amber-100 text-amber-800",
  Silver: "bg-slate-200 text-slate-700",
  Standard: "bg-slate-100 text-slate-600",
};

const VERTICAL_LABELS: Record<string, string> = {
  aerospace_defense: "Aerospace & Defense",
  semiconductor: "Semiconductor",
  wireless_5g6g: "Wireless / 5G·6G",
  automotive: "Automotive",
  research: "Research",
  industrial: "Industrial",
  test_systems_integrator: "T&M Systems Integrator",
};

export function CustomerDetailModal({
  customerId,
  onClose,
}: {
  customerId: number | string | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<CustomerDetail | null>(null);
  const [tab, setTab] = useState<string>("overview");

  useEffect(() => {
    if (customerId == null) {
      setData(null);
      return;
    }
    setData(null);
    setTab("overview");
    api.customerDetail(customerId).then(setData);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [customerId, onClose]);

  if (customerId == null) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-zbrain-ink/40 backdrop-blur-sm flex items-stretch justify-end"
      onClick={onClose}
    >
      <div
        className="bg-white w-full max-w-5xl h-full flex flex-col overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {!data ? (
          <div className="flex-1 flex items-center justify-center text-zbrain-muted text-sm">Loading customer 360…</div>
        ) : (
          <>
            <Header data={data} onClose={onClose} />
            <Tabs tab={tab} onTab={setTab} data={data} />
            <div className="flex-1 overflow-auto bg-zbrain-surface">
              {tab === "overview" && <OverviewTab d={data} />}
              {tab === "contacts" && <ContactsList items={data.contacts} />}
              {tab === "quotes" && <QuotesList items={data.quotes} />}
              {tab === "orders" && <OrdersList items={data.orders} />}
              {tab === "work-orders" && <WorkOrdersList items={data.work_orders} />}
              {tab === "assets" && <AssetsList items={data.assets} />}
              {tab === "contracts" && <ContractsList items={data.contracts} />}
              {tab === "invoices" && <InvoicesList items={data.invoices} />}
              {tab === "cal-certs" && <CalCertsList items={data.cal_certs} />}
              {tab === "comm-log" && <CommLogList items={data.communication_log} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Header({ data, onClose }: { data: CustomerDetail; onClose: () => void }) {
  return (
    <div className="px-6 py-4 border-b border-zbrain-divider flex items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="text-xs uppercase tracking-wider text-zbrain-muted">{data.code}</div>
        <h2 className="text-xl font-semibold mt-0.5">{data.name}</h2>
        {data.legal_entity && data.legal_entity !== data.name && (
          <div className="text-xs text-zbrain-muted mt-0.5">{data.legal_entity}</div>
        )}
        <div className="mt-2 flex flex-wrap gap-1.5 items-center">
          {data.sla_tier && (
            <span className={`pill ${SLA_COLOR[data.sla_tier] || "bg-slate-100 text-slate-700"}`}>
              SLA · {data.sla_tier}
            </span>
          )}
          {data.vertical && (
            <span className="pill bg-zbrain-50 text-zbrain text-[10px]">
              {VERTICAL_LABELS[data.vertical] || data.vertical}
            </span>
          )}
          <span className="pill bg-slate-100 text-slate-700 text-[10px]">{data.region}</span>
          <span className="pill bg-slate-100 text-slate-700 text-[10px]">{data.language.toUpperCase()}</span>
          <StatusPill status={data.status} />
          {data.compliance.map((tag) => (
            <ComplianceBadge key={tag} tag={tag} />
          ))}
        </div>
      </div>
      <button onClick={onClose} className="btn-ghost text-base">
        ✕
      </button>
    </div>
  );
}

function ComplianceBadge({ tag }: { tag: string }) {
  const explain = COMPLIANCE_LEGEND[tag] || COMPLIANCE_LEGEND[tag.replace(/\./g, "_")] || "Compliance/standards tag";
  return (
    <span
      className="pill bg-rose-50 text-rose-700 text-[10px] cursor-help"
      title={explain}
    >
      {tag}
    </span>
  );
}

function Tabs({ tab, onTab, data }: { tab: string; onTab: (k: string) => void; data: CustomerDetail }) {
  const items = [
    { k: "overview", label: "Overview" },
    { k: "contacts", label: "Contacts", count: data.contacts.length },
    { k: "quotes", label: "Quotes", count: data.quotes.length },
    { k: "orders", label: "Orders", count: data.orders.length },
    { k: "work-orders", label: "Work Orders", count: data.work_orders.length },
    { k: "assets", label: "Installed Base", count: data.assets.length },
    { k: "contracts", label: "Service Contracts", count: data.contracts.length },
    { k: "invoices", label: "Invoices", count: data.invoices.length },
    { k: "cal-certs", label: "Cal Certs", count: data.cal_certs.length },
    { k: "comm-log", label: "Communication", count: data.communication_log.length },
  ];
  return (
    <div className="px-6 border-b border-zbrain-divider flex items-center gap-1 flex-wrap">
      {items.map((i) => (
        <button
          key={i.k}
          onClick={() => onTab(i.k)}
          className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === i.k ? "border-zbrain text-zbrain" : "border-transparent text-zbrain-muted hover:text-zbrain-ink"
          }`}
        >
          {i.label}
          {i.count != null && (
            <span className={`ml-1.5 text-[10px] tabular-nums ${tab === i.k ? "text-zbrain" : "text-zbrain-muted"}`}>
              {i.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

function OverviewTab({ d }: { d: CustomerDetail }) {
  return (
    <div className="p-6 grid grid-cols-12 gap-4">
      <Block title="Account" cols={6}>
        <KV k="Account Manager" v={d.account_manager} />
        <KV k="Sales Engineer" v={d.sales_engineer} />
        <KV k="Customer since" v={d.customer_since?.slice(0, 10) || "-"} />
        <KV k="Status" v={d.status} />
      </Block>
      <Block title="Finance" cols={6}>
        <KV k="Payment Terms" v={d.payment_terms} />
        <KV k="Credit Limit" v={`${d.default_currency} ${d.credit_limit.toLocaleString()}`} />
        <KV k="Default Currency" v={d.default_currency} />
        <KV k="Default Incoterms" v={d.default_incoterms} />
      </Block>
      <Block title="Industry" cols={6}>
        <KV k="Industry" v={d.industry} />
        <KV k="NAICS" v={d.naics} />
        <KV k="Annual Revenue" v={d.annual_revenue_usd ? `$${(d.annual_revenue_usd / 1e9).toFixed(2)}B` : null} />
        <KV k="Employees" v={d.employees ? d.employees.toLocaleString() : null} />
      </Block>
      <Block title="Identifiers" cols={6}>
        <KV k="Customer Code" v={<span className="font-mono">{d.code}</span>} />
        <KV k="DUNS" v={d.duns} />
        <KV k="Tax ID" v={d.tax_id} />
        <KV k="Primary Email" v={d.email} mono />
      </Block>
      <Block title="Addresses" cols={12}>
        <div className="grid grid-cols-3 gap-3">
          {d.addresses.map((a, i) => (
            <div key={i} className="bg-white border border-zbrain-divider rounded-md p-3">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">{a.type}</div>
              <div className="text-sm mt-1">{a.line1 || "-"}</div>
              {a.line2 && <div className="text-xs text-zbrain-muted">{a.line2}</div>}
              <div className="text-xs text-zbrain-muted mt-0.5">
                {a.city}{a.region ? `, ${a.region}` : ""} {a.postal || ""}
              </div>
              <div className="text-xs text-zbrain-muted mt-0.5">{a.country}</div>
            </div>
          ))}
        </div>
      </Block>
      <Block title="Compliance / Standards" cols={12}>
        {d.compliance.length === 0 ? (
          <div className="text-xs text-zbrain-muted">None tagged.</div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {d.compliance.map((tag) => (
              <div key={tag} className="bg-white border border-zbrain-divider rounded-md p-2 text-xs">
                <div className="font-mono font-semibold text-rose-700">{tag}</div>
                <div className="text-zbrain-muted mt-0.5">
                  {COMPLIANCE_LEGEND[tag] || COMPLIANCE_LEGEND[tag.replace(/\./g, "_")] || "-"}
                </div>
              </div>
            ))}
          </div>
        )}
      </Block>
    </div>
  );
}

function Block({ title, children, cols }: { title: string; children: React.ReactNode; cols: number }) {
  const COLS: Record<number, string> = { 4: "col-span-4", 6: "col-span-6", 8: "col-span-8", 12: "col-span-12" };
  return (
    <div className={`${COLS[cols] || "col-span-6"} bg-white border border-zbrain-divider rounded-lg p-4`}>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted mb-2 font-semibold">{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function KV({ k, v, mono }: { k: string; v: any; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between text-xs gap-3">
      <span className="text-zbrain-muted">{k}</span>
      <span className={`text-zbrain-ink font-medium text-right ${mono ? "font-mono" : ""}`}>
        {v == null || v === "" ? "-" : v}
      </span>
    </div>
  );
}

function ListWrap({ children, empty }: { children: React.ReactNode; empty: string }) {
  return (
    <div className="p-6">
      <div className="bg-white border border-zbrain-divider rounded-lg overflow-hidden">{children}</div>
      <div className="text-xs text-zbrain-muted mt-2">{empty}</div>
    </div>
  );
}

function ContactsList({ items }: { items: CustomerDetail["contacts"] }) {
  if (items.length === 0) return <Empty msg="No contacts on record." />;
  return (
    <div className="p-6 grid grid-cols-2 gap-3">
      {items.map((c) => (
        <div key={c.id} className="bg-white border border-zbrain-divider rounded-lg p-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{c.name}</span>
            {c.is_primary && <span className="pill bg-emerald-100 text-emerald-700 text-[10px]">primary</span>}
            <span className="pill bg-slate-100 text-slate-700 text-[10px] ml-auto">{c.role}</span>
          </div>
          <div className="text-xs text-zbrain-muted mt-1">{c.title || "-"}</div>
          <div className="text-xs font-mono mt-1">{c.email}</div>
          {c.phone && <div className="text-xs text-zbrain-muted">{c.phone}</div>}
        </div>
      ))}
    </div>
  );
}

function QuotesList({ items }: { items: CustomerDetail["quotes"] }) {
  if (items.length === 0) return <Empty msg="No quotes." />;
  return (
    <Table headers={["Quote #", "Sales Rep", "Opp ID", "Status", "Valid Until", "Total"]}>
      {items.map((q) => (
        <Row key={q.id}>
          <Cell mono>{q.quote_number}</Cell>
          <Cell>{q.sales_rep || "-"}</Cell>
          <Cell mono>{q.opportunity_id || "-"}</Cell>
          <Cell>
            <StatusPill status={q.status} />
          </Cell>
          <Cell>{q.valid_until?.slice(0, 10) || "-"}</Cell>
          <Cell right>${q.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}</Cell>
        </Row>
      ))}
    </Table>
  );
}

function OrdersList({ items }: { items: CustomerDetail["orders"] }) {
  if (items.length === 0) return <Empty msg="No orders." />;
  return (
    <Table headers={["Order #", "Status", "Hold", "Ship Date", "Tracking", "CSR", "Total"]}>
      {items.map((o) => (
        <Row key={o.id}>
          <Cell mono>{o.order_number}</Cell>
          <Cell>
            <StatusPill status={o.status} />
          </Cell>
          <Cell>
            {o.hold_reason ? (
              <span className="pill bg-amber-100 text-amber-800 text-[10px]">{o.hold_reason.replaceAll("_", " ")}</span>
            ) : (
              "-"
            )}
          </Cell>
          <Cell>{o.requested_ship_date?.slice(0, 10) || "-"}</Cell>
          <Cell mono>{o.tracking_number || "-"}</Cell>
          <Cell>{o.csr_owner || "-"}</Cell>
          <Cell right>${o.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}</Cell>
        </Row>
      ))}
    </Table>
  );
}

function WorkOrdersList({ items }: { items: CustomerDetail["work_orders"] }) {
  if (items.length === 0) return <Empty msg="No work orders." />;
  return (
    <Table headers={["WO #", "Type", "Status", "Asset S/N", "Scheduled", "Technician"]}>
      {items.map((w) => (
        <Row key={w.id}>
          <Cell mono>{w.wo_number}</Cell>
          <Cell>
            <span className="pill bg-slate-100 text-slate-700 text-[10px]">{w.type}</span>
          </Cell>
          <Cell>
            <StatusPill status={w.status} />
          </Cell>
          <Cell mono>{w.asset_serial}</Cell>
          <Cell>{w.scheduled_date?.slice(0, 10) || "-"}</Cell>
          <Cell>{w.technician || "-"}</Cell>
        </Row>
      ))}
    </Table>
  );
}

function AssetsList({ items }: { items: CustomerDetail["assets"] }) {
  if (items.length === 0) return <Empty msg="No assets in installed base." />;
  return (
    <Table headers={["Serial", "SKU", "Description", "Location", "Cal Due", "Status"]}>
      {items.map((a) => (
        <Row key={a.id}>
          <Cell mono>{a.serial}</Cell>
          <Cell mono>{a.sku}</Cell>
          <Cell>{a.description || "-"}</Cell>
          <Cell>{a.location || "-"}</Cell>
          <Cell>{a.calibration_due_date?.slice(0, 10) || "-"}</Cell>
          <Cell>
            <StatusPill status={a.status} />
          </Cell>
        </Row>
      ))}
    </Table>
  );
}

function ContractsList({ items }: { items: CustomerDetail["contracts"] }) {
  if (items.length === 0) return <Empty msg="No service contracts." />;
  return (
    <Table headers={["Contract #", "Type", "Starts", "Expires", "Annual Value", "Status"]}>
      {items.map((c) => (
        <Row key={c.id}>
          <Cell mono>{c.contract_number}</Cell>
          <Cell>{c.type}</Cell>
          <Cell>{c.starts_on?.slice(0, 10) || "-"}</Cell>
          <Cell>{c.expires_on?.slice(0, 10) || "-"}</Cell>
          <Cell right>${c.annual_value_usd.toLocaleString()}</Cell>
          <Cell>
            <StatusPill status={c.status} />
          </Cell>
        </Row>
      ))}
    </Table>
  );
}

function InvoicesList({ items }: { items: CustomerDetail["invoices"] }) {
  if (items.length === 0) return <Empty msg="No invoices." />;
  return (
    <Table headers={["Invoice #", "Issued", "Due", "Currency", "Amount", "Paid", "Status"]}>
      {items.map((i) => (
        <Row key={i.id}>
          <Cell mono>{i.invoice_number}</Cell>
          <Cell>{i.invoice_date?.slice(0, 10) || "-"}</Cell>
          <Cell>{i.due_date?.slice(0, 10) || "-"}</Cell>
          <Cell>{i.currency}</Cell>
          <Cell right>{i.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</Cell>
          <Cell right>{i.paid_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</Cell>
          <Cell>
            <StatusPill status={i.status} />
          </Cell>
        </Row>
      ))}
    </Table>
  );
}

function CalCertsList({ items }: { items: CustomerDetail["cal_certs"] }) {
  if (items.length === 0) return <Empty msg="No cal certs." />;
  return (
    <Table headers={["Cert #", "Issued", "Expires", "Traceability", "OOT"]}>
      {items.map((c) => (
        <Row key={c.id}>
          <Cell mono>{c.cert_number}</Cell>
          <Cell>{c.issued_date?.slice(0, 10) || "-"}</Cell>
          <Cell>{c.expires_date?.slice(0, 10) || "-"}</Cell>
          <Cell>
            <span className="pill bg-slate-100 text-slate-700 text-[10px]">{c.traceability}</span>
          </Cell>
          <Cell>
            {c.out_of_tolerance ? (
              <span className="pill bg-rose-100 text-rose-700 text-[10px]">OOT</span>
            ) : (
              <span className="text-emerald-700">in tolerance</span>
            )}
          </Cell>
        </Row>
      ))}
    </Table>
  );
}

function CommLogList({ items }: { items: CustomerDetail["communication_log"] }) {
  if (items.length === 0) {
    return <Empty msg="No communications yet. Process a customer request or approve a HITL task to create one." />;
  }
  return (
    <div className="p-6 space-y-2">
      {items.map((c) => (
        <div key={c.id} className="bg-white border border-zbrain-divider rounded-lg p-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="font-mono text-zbrain-muted">
              {c.occurred_at ? new Date(c.occurred_at).toLocaleString() : "-"}
            </span>
            <span className="pill bg-zbrain-50 text-zbrain text-[10px]">{c.direction}</span>
            <span className="pill bg-slate-100 text-slate-700 text-[10px]">{c.channel}</span>
            {c.intent && <span className="pill bg-slate-100 text-slate-700 text-[10px]">{c.intent}</span>}
            {c.autonomy_tier && (
              <span className="pill bg-slate-100 text-slate-700 text-[10px]">{c.autonomy_tier}</span>
            )}
            {c.language && (
              <span className="pill bg-zbrain-50 text-zbrain text-[10px] ml-auto">{c.language.toUpperCase()}</span>
            )}
          </div>
          <div className="text-sm font-medium mt-1.5">{c.subject || "(no subject)"}</div>
          <div className="text-xs text-zbrain-muted mt-0.5">By: {c.sent_by || "-"}</div>
          <div className="mt-1.5 text-xs text-zbrain-ink whitespace-pre-wrap line-clamp-4">{c.body_preview}</div>
          {(c.pipeline_id || c.order_id || c.work_order_id) && (
            <div className="mt-1.5 text-[11px] text-zbrain-muted flex gap-2">
              {c.pipeline_id && <span>Activity #{c.pipeline_id}</span>}
              {c.order_id && <span>Order #{c.order_id}</span>}
              {c.work_order_id && <span>WO #{c.work_order_id}</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <div className="p-6">
      <div className="bg-white border border-zbrain-divider rounded-lg overflow-hidden">
        <div className="grid bg-zbrain-surface text-[10px] uppercase tracking-wider text-zbrain-muted px-3 py-2 font-medium" style={{ gridTemplateColumns: `repeat(${headers.length}, minmax(0, 1fr))` }}>
          {headers.map((h, i) => (
            <div key={i} className={i === headers.length - 1 ? "text-right" : ""}>
              {h}
            </div>
          ))}
        </div>
        {children}
      </div>
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  const arr = Array.isArray(children) ? children : [children];
  return (
    <div
      className="grid border-t border-zbrain-divider px-3 py-2 text-xs items-center"
      style={{ gridTemplateColumns: `repeat(${arr.length}, minmax(0, 1fr))` }}
    >
      {children}
    </div>
  );
}

function Cell({ children, mono, right }: { children: React.ReactNode; mono?: boolean; right?: boolean }) {
  return (
    <div className={`${mono ? "font-mono" : ""} ${right ? "text-right tabular-nums" : ""}`}>{children}</div>
  );
}

function Empty({ msg }: { msg: string }) {
  return <div className="p-12 text-center text-sm text-zbrain-muted">{msg}</div>;
}
