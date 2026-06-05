export function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    new: "bg-slate-100 text-slate-700",
    processing: "bg-blue-100 text-blue-700",
    awaiting_hitl: "bg-amber-100 text-amber-800",
    processed: "bg-emerald-100 text-emerald-700",
    discarded: "bg-rose-100 text-rose-700",
    rejected: "bg-rose-100 text-rose-700",
    // Sweeper bucket: aged-out, never-triaged mail. Slate-toned so it reads
    // as inert rather than alarming (rose) or in-progress (amber/blue).
    expired_unworkable: "bg-slate-200 text-slate-600",
    redirected: "bg-violet-100 text-violet-700",
    completed: "bg-emerald-100 text-emerald-700",
    pending: "bg-amber-100 text-amber-800",
    resolved: "bg-emerald-100 text-emerald-700",
    error: "bg-rose-100 text-rose-700",
    running: "bg-blue-100 text-blue-700",
  };
  return <span className={`pill ${map[status] || "bg-slate-100 text-slate-700"}`}>{status.replaceAll("_", " ")}</span>;
}

export function TierPill({ tier }: { tier: string | null | undefined }) {
  if (!tier) return null;
  // Plain-English labels with the raw tier code in the tooltip.
  const map: Record<string, string> = {
    L4_AUTO: "bg-emerald-100 text-emerald-700",
    L3_ONE_CLICK: "bg-blue-100 text-blue-700",
    L2_HITL: "bg-amber-100 text-amber-800",
  };
  const label: Record<string, string> = {
    L4_AUTO: "Auto-closed",
    L3_ONE_CLICK: "One-click",
    L2_HITL: "Full review",
  };
  return (
    <span className={`pill ${map[tier] || "bg-slate-100 text-slate-700"}`} title={`Tier code: ${tier}`}>
      {label[tier] || tier}
    </span>
  );
}

export function LangPill({ lang }: { lang: string | null | undefined }) {
  if (!lang) return null;
  return <span className="pill bg-zbrain-50 text-zbrain">{lang.toUpperCase()}</span>;
}

export function IntentPill({ intent }: { intent: string | null | undefined }) {
  if (!intent) return null;
  const label = intent.replaceAll("_", " ");
  return <span className="pill bg-slate-100 text-slate-700">{label}</span>;
}

export function ConfidenceBar({ value }: { value: number | null | undefined }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const pct = Math.round(v * 100);
  const color = v >= 0.95 ? "bg-emerald-500" : v >= 0.8 ? "bg-zbrain" : "bg-amber-500";
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-1.5 bg-slate-200 rounded">
        <div className={`h-1.5 ${color} rounded`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-zbrain-muted w-9 text-right">{pct}%</span>
    </div>
  );
}
