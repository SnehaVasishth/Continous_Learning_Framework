import { useEffect, useMemo, useState } from "react";

import { api, OpsLogFilters, OpsLogRow } from "../../api";
import { Button, Chip, PageHeader, Surface } from "../../components/ui";
import { hitlUrl, inboxUrl, traceUrl } from "../../lib/traceUrl";

const CATEGORY_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "SALES_PO", label: "SALES_PO" },
  { value: "ISC_WO_RTK", label: "ISC_WO_RTK" },
  { value: "KSO", label: "KSO" },
  { value: "OTHERS", label: "OTHERS" },
  { value: "AUTO_REPLY", label: "AUTO_REPLY" },
  { value: "UNDELIVERABLE", label: "UNDELIVERABLE" },
  { value: "COLLECTIONS", label: "COLLECTIONS" },
  { value: "PORTAL_ADMIN", label: "PORTAL_ADMIN" },
  { value: "BRAZIL_TAX", label: "BRAZIL_TAX" },
];

type RangeKey = "7d" | "30d" | "all";

const RANGES: { value: RangeKey; label: string; days: number | null }[] = [
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "all", label: "All time", days: null },
];

const TIER_TONE: Record<string, "success" | "info" | "warning" | "neutral"> = {
  L4_AUTO: "success",
  L3_ONE_CLICK: "info",
  L2_HITL: "warning",
};

const TIER_LABEL: Record<string, string> = {
  L4_AUTO: "Auto-closed",
  L3_ONE_CLICK: "One-click",
  L2_HITL: "Full review",
};

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  Success: "success",
  Pending: "warning",
  Fail: "danger",
};

const CATEGORY_TONE: Record<
  string,
  "info" | "violet" | "emphasis" | "neutral" | "warning" | "danger"
> = {
  SALES_PO: "emphasis",
  ISC_WO_RTK: "info",
  KSO: "violet",
  AUTO_REPLY: "neutral",
  COLLECTIONS: "warning",
  UNDELIVERABLE: "danger",
  OTHERS: "neutral",
  PORTAL_ADMIN: "neutral",
  BRAZIL_TAX: "neutral",
};

export function OpsLogsPage() {
  const [rows, setRows] = useState<OpsLogRow[] | null>(null);
  const [total, setTotal] = useState<number>(0);
  const [category, setCategory] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [range, setRange] = useState<RangeKey>("all");
  const [search, setSearch] = useState<string>("");
  const [debouncedSearch, setDebouncedSearch] = useState<string>("");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  const filters: OpsLogFilters = useMemo(() => {
    const f: OpsLogFilters = {};
    if (category) f.category = category;
    if (status) f.status = status;
    if (debouncedSearch) f.q = debouncedSearch;
    const r = RANGES.find((x) => x.value === range);
    if (r && r.days != null) {
      const since = new Date(Date.now() - r.days * 24 * 3600 * 1000);
      f.from = since.toISOString();
    }
    return f;
  }, [category, status, range, debouncedSearch]);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api
        .opsLog(filters)
        .then((res) => {
          if (cancelled) return;
          setRows(res.rows);
          setTotal(res.total);
          setGeneratedAt(res.generated_at);
        })
        .catch(() => undefined);
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [filters]);

  const downloadCsv = () => {
    const url = api.opsLogCsvUrl(filters);
    window.open(url, "_blank");
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Operations Log"
        subtitle="One row per processed email: categorized, timestamped, scored. Mirrors the column schema your front-office team uses today."
        badges={
          <Chip tone="info">
            <span className="tabular-nums">{total}</span> rows
          </Chip>
        }
        actions={
          <Button variant="primary" onClick={downloadCsv}>
            Export CSV
          </Button>
        }
      />

      <Surface className="p-3">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1 flex-wrap">
            {CATEGORY_FILTERS.map((c) => (
              <FilterPill
                key={c.value || "all"}
                active={category === c.value}
                onClick={() => setCategory(c.value)}
              >
                {c.label}
              </FilterPill>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search subject or sender…"
              className="h-8 px-3 rounded-md border border-zbrain-divider bg-white text-[13px] text-zbrain-ink placeholder-zbrain-muted/70 focus:outline-none focus:ring-1 focus:ring-zbrain min-w-[220px] dark:bg-zbrain-dark-elev1 dark:text-zbrain-dark-ink dark:border-zbrain-dark-divider"
            />
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="h-8 px-2 rounded-md border border-zbrain-divider bg-white text-[13px] text-zbrain-ink focus:outline-none focus:ring-1 focus:ring-zbrain dark:bg-zbrain-dark-elev1 dark:text-zbrain-dark-ink dark:border-zbrain-dark-divider"
            >
              <option value="">All status</option>
              <option value="Success">Success</option>
              <option value="Pending">Pending</option>
              <option value="Fail">Fail</option>
            </select>
            <div className="flex items-center gap-1">
              {RANGES.map((r) => (
                <FilterPill
                  key={r.value}
                  active={range === r.value}
                  onClick={() => setRange(r.value)}
                >
                  {r.label}
                </FilterPill>
              ))}
            </div>
          </div>
        </div>
      </Surface>

      <Surface className="overflow-hidden">
        {rows === null ? (
          <div className="p-10 text-center text-sm text-zbrain-muted">Loading ops log…</div>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center">
            <div className="text-sm font-medium text-zbrain-ink">No cases processed yet</div>
            <div className="text-xs text-zbrain-muted mt-1">
              Once emails come in, every processed message will land here.
            </div>
            <div className="mt-4">
              <Button
                variant="primary"
                onClick={() => window.open(inboxUrl(), "_blank", "noopener,noreferrer")}
              >
                Go to Inbox ↗
              </Button>
            </div>
          </div>
        ) : (
          <OpsTable rows={rows} />
        )}
      </Surface>

      <div className="flex items-center justify-between text-[11px] text-zbrain-muted px-1">
        <span>Refreshes every 5 s</span>
        {generatedAt && <span>Last sync · {fmtTimeOnly(generatedAt)}</span>}
      </div>
    </div>
  );
}

function FilterPill({
  active,
  onClick,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 h-7 rounded-full text-[12px] font-medium transition-colors ${
        active
          ? "bg-zbrain text-white shadow-sm"
          : "text-zbrain-ink hover:bg-zbrain-50 dark:text-zbrain-dark-ink dark:hover:bg-zbrain-dark-elev2"
      }`}
    >
      {children}
    </button>
  );
}

function OpsTable({ rows }: { rows: OpsLogRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-zbrain-muted text-left bg-zbrain-surface dark:bg-zbrain-dark-elev2/50">
            <Th className="pl-4">ID</Th>
            <Th>Inbox time</Th>
            <Th>Category</Th>
            <Th>Intent</Th>
            <Th className="min-w-[260px]">Subject</Th>
            <Th>Sender</Th>
            <Th>Tier</Th>
            <Th align="right">Conf.</Th>
            <Th>Status</Th>
            <Th align="right">Duration</Th>
            <Th className="pr-4" align="right">Actions</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const pipeId = r.currentId.replace(/^ZBR-0*/, "");
            return (
              <tr
                key={r.currentId}
                className="border-t border-zbrain-divider/40 hover:bg-zbrain-50/40 dark:hover:bg-zbrain-dark-elev2/40"
              >
                <td className="pl-4 py-2 font-mono text-[12px] text-zbrain-ink whitespace-nowrap">
                  {r.currentId}
                </td>
                <td className="py-2 pr-2 text-zbrain-muted whitespace-nowrap tabular-nums">
                  {fmtDateTime(r.inboxTime)}
                </td>
                <td className="py-2 pr-2 whitespace-nowrap">
                  <Chip tone={CATEGORY_TONE[r.category] || "neutral"}>
                    <span className="font-mono text-[11px]">{r.category}</span>
                  </Chip>
                </td>
                <td className="py-2 pr-2 text-zbrain-ink whitespace-nowrap">
                  <span className="font-mono text-[11.5px]">{r.intent || "-"}</span>
                </td>
                <td
                  className="py-2 pr-2 text-zbrain-ink truncate max-w-[360px]"
                  title={r.subject || ""}
                >
                  {r.subject || (
                    <span className="italic text-zbrain-muted/70">(no subject)</span>
                  )}
                </td>
                <td
                  className="py-2 pr-2 text-zbrain-muted truncate max-w-[200px]"
                  title={r.fromAddress || ""}
                >
                  {r.fromAddress || "-"}
                </td>
                <td className="py-2 pr-2 whitespace-nowrap">
                  {r.autonomyTier ? (
                    <Chip tone={TIER_TONE[r.autonomyTier] || "neutral"}>
                      {TIER_LABEL[r.autonomyTier] || r.autonomyTier}
                    </Chip>
                  ) : (
                    <span className="text-zbrain-muted/60">-</span>
                  )}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums text-zbrain-ink">
                  {fmtConfidence(r.confidence)}
                </td>
                <td className="py-2 pr-2 whitespace-nowrap">
                  {r.status ? (
                    <Chip tone={STATUS_TONE[r.status] || "neutral"}>{r.status}</Chip>
                  ) : (
                    <span className="text-zbrain-muted/60">-</span>
                  )}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums text-zbrain-muted">
                  {fmtDuration(r.duration_ms)}
                </td>
                <td className="pr-4 py-2 text-right whitespace-nowrap">
                  <a
                    href={traceUrl(pipeId)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[12px] text-zbrain hover:underline"
                  >
                    Trace →
                  </a>
                  {r.hitlStatus === "Awaiting CSR" && (
                    <a
                      href={hitlUrl(pipeId)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-2 text-[12px] text-amber-700 hover:underline"
                    >
                      HITL ↗
                    </a>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  className = "",
  align = "left",
}: {
  children: React.ReactNode;
  className?: string;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`py-2 pr-2 font-medium ${
        align === "right" ? "text-right" : "text-left"
      } ${className}`}
    >
      {children}
    </th>
  );
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const now = new Date();
  const sameYear = d.getFullYear() === now.getFullYear();
  const datePart = d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: sameYear ? undefined : "2-digit",
  });
  const timePart = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${datePart} ${timePart}`;
}

function fmtTimeOnly(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function fmtConfidence(c: number | null): string {
  if (c == null) return "-";
  return `${Math.round(c * 100)}%`;
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}
