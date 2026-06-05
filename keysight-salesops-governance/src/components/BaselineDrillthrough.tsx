/**
 * BaselineDrillthrough: right-side panel that opens when an operator clicks a
 * BaselineChip anywhere on the Continuous Learning page. Fetches the timeline
 * for the selected baseline and renders six collapsible sections that mirror
 * the funnel: Drift alerts → Tuning candidates → Shadow A/B → RCA tickets →
 * Promotions → Feedback.
 *
 * Each section caps preview rows at 8. The "View more in this tab" link
 * closes the panel, switches to the source tab, and pre-applies the baseline
 * filter so the operator lands on the full list scoped to this baseline.
 *
 * Mirrors the PreviewModal sizing/animation conventions used elsewhere in the
 * app: fixed-position right rail, click-outside-to-close, Esc key handler.
 */
import { useEffect, useState } from "react";

import {
  api,
  type BaselineTimeline,
  type DriftAlert,
  type LearningOpportunity,
  type ABExperiment,
  type RCATicket,
  type FeedbackEntry,
  type SegmentObservation,
} from "../api";
import { InfoTip } from "./InfoTip";

export type DrillthroughJumpTab =
  | "drift"
  | "tuning"
  | "experiments"
  | "promote"
  | "feedback";

type BaselineDrillthroughProps = {
  baselineId: number | null;
  onClose: () => void;
  /** Called when the user clicks "View more in this tab" on a section.
   *  The host (Learning page) is responsible for closing the panel,
   *  switching the active tab, and pre-applying the baseline filter. */
  onJumpToTab?: (tab: DrillthroughJumpTab, baselineId: number) => void;
};

function statusPillCls(status: string): string {
  switch (status) {
    case "breached":
      return "bg-rose-50 text-rose-800 border-rose-200";
    case "drifting":
      return "bg-amber-50 text-amber-800 border-amber-200";
    case "healthy":
      return "bg-emerald-50 text-emerald-800 border-emerald-200";
    default:
      return "bg-slate-50 text-slate-700 border-slate-200";
  }
}

export function BaselineDrillthrough({
  baselineId,
  onClose,
  onJumpToTab,
}: BaselineDrillthroughProps) {
  const [data, setData] = useState<BaselineTimeline | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (baselineId == null) return;
    setData(null);
    setErr(null);
    setLoading(true);
    let cancel = false;
    api
      .learningBaselineTimeline(baselineId)
      .then((d) => {
        if (!cancel) setData(d);
      })
      .catch((e: any) => {
        if (!cancel) setErr(String(e?.message || e));
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [baselineId]);

  useEffect(() => {
    if (baselineId == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [baselineId, onClose]);

  if (baselineId == null) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-zbrain-ink/40 backdrop-blur-sm flex items-stretch justify-end"
      onClick={onClose}
    >
      <div
        className="bg-white shadow-2xl w-full max-w-2xl h-full flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Baseline drill-through"
      >
        <DrillthroughHeader data={data} loading={loading} err={err} onClose={onClose} />

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 bg-zbrain-surface/30">
          {loading && !data && (
            <div className="text-sm text-zbrain-muted px-2 py-6 text-center">
              Loading timeline…
            </div>
          )}
          {err && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              Could not load timeline: {err}
            </div>
          )}
          {data && (
            <>
              <Section
                title="Drift alerts"
                count={data.counts.drift_alerts}
                onJump={() => onJumpToTab?.("drift", baselineId)}
              >
                {data.drift_alerts.length === 0 ? (
                  <EmptyRow text="No drift alerts attributed to this baseline." />
                ) : (
                  data.drift_alerts.slice(0, 8).map((r) => (
                    <DriftRow key={r.id} r={r} />
                  ))
                )}
              </Section>

              <Section
                title="Tuning candidates"
                count={data.counts.opportunities}
                onJump={() => onJumpToTab?.("tuning", baselineId)}
              >
                {data.opportunities.length === 0 ? (
                  <EmptyRow text="No tuning candidates linked to this baseline." />
                ) : (
                  data.opportunities.slice(0, 8).map((o) => (
                    <OppRow key={o.id} o={o} />
                  ))
                )}
              </Section>

              <Section
                title="Shadow A/B experiments"
                count={data.counts.experiments}
                onJump={() => onJumpToTab?.("experiments", baselineId)}
              >
                {data.experiments.length === 0 ? (
                  <EmptyRow text="No experiments running against this baseline." />
                ) : (
                  data.experiments.slice(0, 8).map((x) => (
                    <ExpRow key={x.id} x={x} />
                  ))
                )}
              </Section>

              <Section
                title="RCA tickets"
                count={data.counts.rca_tickets}
                onJump={() => onJumpToTab?.("drift", baselineId)}
              >
                {data.rca_tickets.length === 0 ? (
                  <EmptyRow text="No RCA tickets linked to this baseline." />
                ) : (
                  data.rca_tickets.slice(0, 8).map((t) => (
                    <RcaRow key={t.id} t={t} />
                  ))
                )}
              </Section>

              <Section
                title="Promotions"
                count={data.counts.promotions}
                onJump={() => onJumpToTab?.("promote", baselineId)}
              >
                {data.promotions.length === 0 ? (
                  <EmptyRow text="No promotions recorded against this baseline." />
                ) : (
                  data.promotions.slice(0, 8).map((p) => (
                    <PromoRow key={p.id} p={p} />
                  ))
                )}
              </Section>

              <Section
                title="Feedback"
                count={data.counts.feedback}
                onJump={() => onJumpToTab?.("feedback", baselineId)}
              >
                {data.feedback.length === 0 ? (
                  <EmptyRow text="No CSR feedback attributed to this baseline." />
                ) : (
                  data.feedback.slice(0, 8).map((f) => (
                    <FbRow key={f.id} f={f} />
                  ))
                )}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DrillthroughHeader({
  data,
  loading,
  err,
  onClose,
}: {
  data: BaselineTimeline | null;
  loading: boolean;
  err: string | null;
  onClose: () => void;
}) {
  const b = data?.baseline;
  const c = data?.counts;
  return (
    <div className="px-5 py-4 border-b border-zbrain-divider bg-white">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">
            Baseline timeline
          </div>
          <div className="mt-0.5 flex items-center gap-2 flex-wrap">
            <h2 className="text-base font-semibold text-zbrain-ink truncate inline-flex items-center gap-1.5">
              {b?.label || (loading ? "Loading…" : err ? "Error" : `Baseline #${b?.id ?? ""}`)}
              {b?.rationale && <InfoTip text={b.rationale} />}
            </h2>
            {b && (
              <span
                className={`pill text-[10px] border ${statusPillCls(b.last_status)} uppercase tracking-wider font-semibold`}
              >
                {b.last_status}
              </span>
            )}
            {b && (
              <span
                className={`pill text-[10px] border ${
                  b.severity === "block_promotion"
                    ? "bg-rose-50 text-rose-700 border-rose-200"
                    : "bg-amber-50 text-amber-800 border-amber-200"
                }`}
              >
                {b.severity === "block_promotion" ? "blocks promotion" : "warn"}
              </span>
            )}
          </div>
          {b && (
            <div className="mt-1 text-[11px] text-zbrain-muted font-mono">
              {b.metric} · {b.segment}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-zbrain-muted hover:text-zbrain-ink text-xl leading-none shrink-0"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {c && (
        <div className="mt-3 grid grid-cols-6 gap-1.5">
          <CountTile label="Drift" value={c.drift_alerts} />
          <CountTile label="Tuning" value={c.opportunities} />
          <CountTile label="A/B" value={c.experiments} />
          <CountTile label="RCA" value={c.rca_tickets} />
          <CountTile label="Promoted" value={c.promotions} />
          <CountTile label="Feedback" value={c.feedback} />
        </div>
      )}

      {b && Array.isArray(b.segments_observed) && b.segments_observed.length > 0 && (
        <SegmentsStrip
          segments={b.segments_observed}
          direction={b.direction || "min"}
          unit={b.unit || ""}
          target={typeof b.target_value === "number" ? b.target_value : null}
        />
      )}
    </div>
  );
}

function fmtSegValue(v: number | null, unit: string): string {
  if (v == null) return "pending";
  if (unit === "ms") return `${Math.round(v).toLocaleString()}ms`;
  if (unit === "hours") return `${v.toFixed(1)}h`;
  if (unit === "ratio" || unit === "pct") return `${(v * 100).toFixed(1)}%`;
  if (Math.abs(v) >= 100) return v.toFixed(0);
  return v.toFixed(2);
}

function SegmentsStrip({
  segments,
  direction,
  unit,
  target,
}: {
  segments: SegmentObservation[];
  direction: "min" | "max";
  unit: string;
  target: number | null;
}) {
  // Worst-first ordering matches the per-row breakdown on the Baselines tab.
  // Pending (null observed) rows sink to the bottom.
  const sorted = [...segments].sort((a, b) => {
    if (a.observed == null && b.observed == null) return 0;
    if (a.observed == null) return 1;
    if (b.observed == null) return -1;
    return direction === "min" ? a.observed - b.observed : b.observed - a.observed;
  });
  const head = sorted.slice(0, 6);
  const tone = (s: SegmentObservation["status"]): string => {
    switch (s) {
      case "breached":
        return "border-rose-200 bg-rose-50 text-rose-800";
      case "drifting":
        return "border-amber-200 bg-amber-50 text-amber-900";
      case "healthy":
        return "border-emerald-200 bg-emerald-50 text-emerald-800";
      default:
        return "border-slate-200 bg-slate-50 text-slate-600";
    }
  };
  const glyph = (s: SegmentObservation): string => {
    if (s.observed == null || target == null) return "→";
    const meetsTarget = direction === "min" ? s.observed >= target : s.observed <= target;
    if (meetsTarget) return "↑";
    return "↓";
  };
  return (
    <div className="mt-3">
      <div className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold mb-1.5">
        Segments breakdown
      </div>
      <div className="flex flex-wrap gap-1.5">
        {head.map((s) => (
          <button
            key={s.segment}
            type="button"
            className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10.5px] font-mono cursor-default ${tone(s.status)}`}
            title={`${s.segment}: weight ${s.weight.toFixed(2)}, n=${s.sample_size.toLocaleString()}, ${s.status}`}
          >
            <span className="truncate max-w-[10rem]">{s.segment}</span>
            <span className="tabular-nums font-semibold">{fmtSegValue(s.observed, unit)}</span>
            <span aria-hidden="true">{glyph(s)}</span>
          </button>
        ))}
        {sorted.length > head.length && (
          <span className="inline-flex items-center text-[10.5px] text-zbrain-muted px-1">
            +{sorted.length - head.length} more
          </span>
        )}
      </div>
    </div>
  );
}

function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-zbrain-divider bg-white px-2 py-1.5 text-center">
      <div className="text-[9px] uppercase tracking-wider text-zbrain-muted font-semibold">
        {label}
      </div>
      <div className="text-sm font-semibold tabular-nums text-zbrain-ink">{value}</div>
    </div>
  );
}

function Section({
  title,
  count,
  onJump,
  children,
}: {
  title: string;
  count: number;
  onJump?: () => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="rounded-md border border-zbrain-divider bg-white overflow-hidden"
    >
      <summary className="px-3 py-2 cursor-pointer hover:bg-zbrain-50/40 list-none flex items-center gap-2 select-none">
        <span className="text-zbrain-muted text-[10px]">{open ? "▾" : "▸"}</span>
        <span className="text-[12px] font-semibold text-zbrain-ink">{title}</span>
        <span className="pill bg-zbrain-50 text-zbrain text-[10px] border border-zbrain/20">
          {count}
        </span>
        {onJump && count > 0 && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onJump();
            }}
            className="ml-auto text-[11px] text-zbrain hover:underline whitespace-nowrap"
          >
            View more in this tab →
          </button>
        )}
      </summary>
      <div className="divide-y divide-zbrain-divider/60">{children}</div>
    </details>
  );
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-3 py-3 text-[12px] text-zbrain-muted italic">{text}</div>;
}

function DriftRow({ r }: { r: DriftAlert }) {
  const sev =
    r.severity === "high" || r.severity === "slo_breach"
      ? "bg-rose-50 text-rose-800 border-rose-200"
      : r.severity === "warn" || r.severity === "medium"
        ? "bg-amber-50 text-amber-800 border-amber-200"
        : "bg-slate-50 text-slate-700 border-slate-200";
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`pill text-[9.5px] border ${sev} uppercase tracking-wider font-semibold`}>
          {r.severity}
        </span>
        <span className="font-mono text-[10.5px] text-zbrain-muted truncate">
          {r.metric} · {r.segment}
        </span>
        <span className="ml-auto text-[10.5px] text-zbrain-muted">
          {r.detected_at ? new Date(r.detected_at).toLocaleString() : "n/a"}
        </span>
      </div>
      {r.delta_pct != null && (
        <div className="text-[11px] text-zbrain-muted tabular-nums mt-0.5">
          Δ {r.delta_pct > 0 ? "+" : ""}
          {r.delta_pct.toFixed(1)}%
          {r.note && <span className="ml-2 italic">{r.note}</span>}
        </div>
      )}
    </div>
  );
}

function OppRow({ o }: { o: LearningOpportunity }) {
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="pill bg-slate-100 text-slate-700 text-[9.5px] uppercase tracking-wider">
          {o.status.replaceAll("_", " ")}
        </span>
        <span className="font-mono text-[10.5px] text-zbrain-muted truncate">{o.segment}</span>
        <span className="pill bg-zbrain-50 text-zbrain text-[9.5px] border border-zbrain/20 ml-auto">
          score {o.score.toFixed(1)}
        </span>
      </div>
      <div className="text-zbrain-ink leading-snug mt-0.5 truncate" title={o.proposed_remedy}>
        {o.expected_lift || o.proposed_remedy.slice(0, 120)}
      </div>
    </div>
  );
}

function ExpRow({ x }: { x: ABExperiment }) {
  const tone =
    x.promote_status === "promoted"
      ? "bg-emerald-50 text-emerald-800 border-emerald-200"
      : x.promote_status === "ready"
        ? "bg-zbrain-50 text-zbrain border-zbrain/20"
        : x.promote_status === "shadow"
          ? "bg-amber-50 text-amber-800 border-amber-200"
          : "bg-slate-100 text-slate-700 border-zbrain-divider";
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`pill text-[9.5px] border ${tone} uppercase tracking-wider font-semibold`}>
          {x.promote_status}
        </span>
        <span className="font-medium text-zbrain-ink truncate flex-1" title={x.candidate}>
          {x.candidate}
        </span>
        {x.accuracy_delta_pct != null && (
          <span
            className={`text-[11px] tabular-nums font-semibold ${
              x.accuracy_delta_pct >= 0 ? "text-emerald-700" : "text-rose-700"
            }`}
          >
            {x.accuracy_delta_pct > 0 ? "+" : ""}
            {x.accuracy_delta_pct.toFixed(1)}pp
          </span>
        )}
      </div>
      <div className="text-[10.5px] text-zbrain-muted mt-0.5 font-mono truncate">{x.segment}</div>
    </div>
  );
}

function RcaRow({ t }: { t: RCATicket }) {
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="pill bg-slate-100 text-slate-700 text-[9.5px] uppercase tracking-wider">
          {t.status}
        </span>
        {t.severity && (
          <span className="pill bg-amber-50 text-amber-800 border border-amber-200 text-[9.5px] uppercase tracking-wider">
            {t.severity}
          </span>
        )}
        <span className="font-medium text-zbrain-ink truncate flex-1" title={t.title || ""}>
          {t.title || `RCA #${t.id}`}
        </span>
        <span className="text-[10.5px] text-zbrain-muted">
          {t.created_at ? new Date(t.created_at).toLocaleDateString() : ""}
        </span>
      </div>
    </div>
  );
}

function PromoRow({ p }: { p: ABExperiment }) {
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="pill bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9.5px] uppercase tracking-wider font-semibold">
          live
        </span>
        <span className="font-medium text-zbrain-ink truncate flex-1" title={p.candidate}>
          {p.candidate}
        </span>
        <span className="text-[10.5px] text-zbrain-muted">
          {p.promoted_at ? new Date(p.promoted_at).toLocaleDateString() : ""}
        </span>
      </div>
      <div className="text-[10.5px] text-zbrain-muted mt-0.5 font-mono truncate">
        {p.kb_namespace}/{p.kb_key}
      </div>
    </div>
  );
}

function FbRow({ f }: { f: FeedbackEntry }) {
  const inferred = f.anchor_kind === "derived";
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="pill bg-slate-100 text-slate-700 text-[9.5px] uppercase tracking-wider font-mono">
          {f.stage}
        </span>
        <span className="pill bg-slate-50 text-slate-700 text-[9.5px]">{f.kind}</span>
        {inferred && (
          <span
            className="pill text-[9px] bg-white text-zbrain-muted border border-zbrain/15 uppercase tracking-wider"
            title="Anchor inferred from row context at read time."
          >
            inferred
          </span>
        )}
        <span className="ml-auto text-[10.5px] text-zbrain-muted">
          {f.created_at ? new Date(f.created_at).toLocaleString() : ""}
        </span>
      </div>
      {f.note && (
        <div className="text-zbrain-ink leading-snug mt-0.5 truncate" title={f.note}>
          {f.note}
        </div>
      )}
    </div>
  );
}

export default BaselineDrillthrough;
