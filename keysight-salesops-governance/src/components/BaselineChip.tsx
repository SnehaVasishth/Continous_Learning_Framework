/**
 * BaselineChip: compact pill that anchors a Continuous Learning signal row to
 * its source baseline. Renders as a button when an id is present (clicking
 * opens the drill-through panel) and as a faint "unlinked" span otherwise.
 *
 * Visual:
 *   [⌖ Intent Confidence (intent:invoice_inquiry)]
 *   [⌖ Reconcile p95 latency · inferred]   (derivedOnly={true})
 *   <span>unlinked</span>                  (baselineId == null)
 *
 * Sizing:
 *   sm (default): 10.5px text, 12px icon. Matches the pill density used by
 *                 existing chips in DriftAlertCard and OpportunityCard.
 *   md         : 11.5px text, 13px icon. For row headers in the drill-through
 *                 panel where the chip is the primary anchor.
 */
import type { MouseEvent } from "react";

type BaselineChipProps = {
  baselineId: number | null | undefined;
  baselineLabel: string | null | undefined;
  derivedOnly?: boolean;
  onClick?: (baselineId: number) => void;
  size?: "sm" | "md";
  className?: string;
};

const MAX_LABEL_CHARS = 24;

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}

export function BaselineChip({
  baselineId,
  baselineLabel,
  derivedOnly = false,
  onClick,
  size = "sm",
  className = "",
}: BaselineChipProps) {
  if (baselineId == null) {
    return (
      <span
        className={`inline-flex items-center gap-1 text-[10.5px] text-zbrain-muted/70 italic ${className}`}
        title="No baseline anchor recorded for this signal."
      >
        unlinked
      </span>
    );
  }

  const fullLabel = baselineLabel || `Baseline #${baselineId}`;
  const shown = truncate(fullLabel, MAX_LABEL_CHARS);
  const textCls = size === "md" ? "text-[11.5px]" : "text-[10.5px]";
  const iconSize = size === "md" ? 13 : 12;
  const pad = size === "md" ? "px-2 py-0.5" : "px-1.5 py-0.5";

  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (onClick) onClick(baselineId);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      title={derivedOnly ? `${fullLabel} (inferred at read time)` : fullLabel}
      className={
        "inline-flex items-center gap-1 rounded-full border border-zbrain/30 bg-zbrain-50 " +
        "text-zbrain font-medium hover:bg-zbrain-100 hover:border-zbrain " +
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-zbrain/40 " +
        "transition-colors max-w-[200px] " +
        textCls +
        " " +
        pad +
        " " +
        className
      }
    >
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 12 12"
        aria-hidden
        className="shrink-0"
      >
        <circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <circle cx="6" cy="6" r="2" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <circle cx="6" cy="6" r="0.6" fill="currentColor" />
      </svg>
      <span className="truncate">{shown}</span>
      {derivedOnly && (
        <span
          className="ml-0.5 px-1 py-px rounded-sm bg-white/70 text-zbrain-muted text-[9px] uppercase tracking-wider font-semibold border border-zbrain/15"
          title="Anchor inferred from row context at read time, not persisted on the row."
        >
          inferred
        </span>
      )}
    </button>
  );
}

export default BaselineChip;
