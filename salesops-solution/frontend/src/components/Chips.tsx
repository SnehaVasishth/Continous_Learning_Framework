/**
 * Shared "code → plain English" chip components.
 *
 * The platform's internal codes (autonomy tiers, severity strings, change
 * types, rubric kinds) are terse identifiers that mean nothing to a
 * functional user. These chips render the human-readable label, keep the
 * raw code in the tooltip for engineers, and apply a consistent colour
 * tone for the same code across every page.
 *
 * Every page that surfaces one of these codes should import the matching
 * chip rather than rolling its own pill. That guarantees a CSR looking at
 * the Dashboard, the HITL queue, the Trace timeline, and Analytics sees
 * the same word for the same concept.
 */
import React from "react";

// ---- Autonomy tier -----------------------------------------------------------

export type AutonomyTier = "L4_AUTO" | "L3_ONE_CLICK" | "L2_HITL" | string | null | undefined;

export function TierChip({ tier, size = "sm" }: { tier: AutonomyTier; size?: "xs" | "sm" }) {
  const meta = tierMeta(tier);
  const sz = size === "xs" ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <span className={`pill border ${sz} ${meta.cls}`} title={`${meta.label} (${meta.code})`}>
      {meta.label}
    </span>
  );
}

function tierMeta(tier: AutonomyTier): { label: string; code: string; cls: string } {
  const code = String(tier || "").toUpperCase();
  if (code === "L4_AUTO")     return { label: "Auto-closed", code, cls: "bg-emerald-50 text-emerald-800 border-emerald-200" };
  if (code === "L3_ONE_CLICK") return { label: "One-click",   code, cls: "bg-sky-50 text-sky-800 border-sky-200" };
  if (code === "L2_HITL")     return { label: "Full review", code, cls: "bg-amber-50 text-amber-800 border-amber-200" };
  return { label: code || "-", code, cls: "bg-slate-50 text-slate-600 border-slate-200" };
}

export function tierLabel(tier: AutonomyTier): string {
  return tierMeta(tier).label;
}

// ---- Business-rule severity --------------------------------------------------

export type BusinessSeverity = "hard_block" | "cap_at_0.70" | "cap_at_0.88" | "warn" | string;

export function SeverityChip({ severity, size = "sm" }: { severity: BusinessSeverity; size?: "xs" | "sm" }) {
  const meta = severityMeta(severity);
  const sz = size === "xs" ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <span className={`pill border ${sz} ${meta.cls}`} title={meta.tooltip}>
      {meta.label}
    </span>
  );
}

function severityMeta(severity: string): { label: string; cls: string; tooltip: string } {
  switch (severity) {
    case "hard_block":  return { label: "Hard block",       cls: "bg-rose-50 text-rose-800 border-rose-200",     tooltip: "Refuse the action entirely. No auto-close, no one-click. Manual handling only. (raw: hard_block)" };
    case "cap_at_0.70": return { label: "Cap → L2 review",  cls: "bg-amber-50 text-amber-800 border-amber-200",  tooltip: "Force the case down to L2 full human review. (raw: cap_at_0.70)" };
    case "cap_at_0.88": return { label: "Cap → L3 one-click", cls: "bg-yellow-50 text-yellow-800 border-yellow-200", tooltip: "Force the case down to L3 one-click approval. (raw: cap_at_0.88)" };
    case "warn":        return { label: "Warn only",        cls: "bg-slate-50 text-slate-700 border-slate-200",  tooltip: "Trace event only; no tier change. (raw: warn)" };
    case "hard":        return { label: "Blocking",         cls: "bg-rose-50 text-rose-800 border-rose-200",     tooltip: "Blocking issue: caps confidence at 0.70 (L2 review). (raw: hard)" };
    case "soft":        return { label: "Soft cap",         cls: "bg-amber-50 text-amber-800 border-amber-200",  tooltip: "Soft cap: caps confidence at 0.88 (L3 one-click). (raw: soft)" };
    case "high":        return { label: "High",             cls: "bg-rose-50 text-rose-800 border-rose-200",     tooltip: "High severity. (raw: high)" };
    case "medium":      return { label: "Medium",           cls: "bg-amber-50 text-amber-800 border-amber-200",  tooltip: "Medium severity. (raw: medium)" };
    case "low":         return { label: "Low",              cls: "bg-slate-50 text-slate-700 border-slate-200",  tooltip: "Low severity. (raw: low)" };
    case "slo_breach":  return { label: "SLO breach",       cls: "bg-rose-50 text-rose-800 border-rose-200",     tooltip: "Crossed a hard SLO floor. (raw: slo_breach)" };
    case "info":        return { label: "Info",             cls: "bg-slate-50 text-slate-700 border-slate-200",  tooltip: "Informational. (raw: info)" };
    case "block":       return { label: "Block",            cls: "bg-rose-50 text-rose-800 border-rose-200",     tooltip: "Block the action. (raw: block)" };
    case "block_until_enriched": return { label: "Pause for CSR", cls: "bg-amber-50 text-amber-800 border-amber-200", tooltip: "Pause for CSR enrichment before any side effect. (raw: block_until_enriched)" };
    case "review_recommended": return { label: "Review recommended", cls: "bg-sky-50 text-sky-800 border-sky-200", tooltip: "Review recommended but not blocked. (raw: review_recommended)" };
    case "definitive":  return { label: "Definitive",       cls: "bg-emerald-50 text-emerald-800 border-emerald-200", tooltip: "Unambiguous match. (raw: definitive)" };
    default:            return { label: severity || "-",    cls: "bg-slate-50 text-slate-700 border-slate-200",  tooltip: severity };
  }
}

export function severityLabel(severity: string): string {
  return severityMeta(severity).label;
}

// ---- Rubric rule kind --------------------------------------------------------

export function KindChip({ kind, size = "sm" }: { kind: string; size?: "xs" | "sm" }) {
  const meta = kindMeta(kind);
  const sz = size === "xs" ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <span className={`pill border ${sz} ${meta.cls}`} title={`${meta.label} (raw: ${kind})`}>
      {meta.label}
    </span>
  );
}

function kindMeta(kind: string): { label: string; cls: string } {
  switch (kind) {
    case "base":            return { label: "Starting prior",     cls: "bg-zinc-50 text-zinc-700 border-zinc-200" };
    case "weighted_signal": return { label: "Signal weight",      cls: "bg-sky-50 text-sky-800 border-sky-200" };
    case "floor_cap":       return { label: "Floor cap",          cls: "bg-amber-50 text-amber-800 border-amber-200" };
    case "trigger":         return { label: "Boost trigger",      cls: "bg-emerald-50 text-emerald-800 border-emerald-200" };
    case "clearance":       return { label: "Clean-signal bonus", cls: "bg-teal-50 text-teal-800 border-teal-200" };
    case "penalty":         return { label: "Penalty",            cls: "bg-rose-50 text-rose-800 border-rose-200" };
    case "rule":            return { label: "Rule",               cls: "bg-zinc-50 text-zinc-700 border-zinc-200" };
    case "preserve_verbatim": return { label: "Preserve verbatim", cls: "bg-slate-50 text-slate-700 border-slate-200" };
    case "tone_guidance":   return { label: "Tone guidance",      cls: "bg-violet-50 text-violet-800 border-violet-200" };
    case "format_guidance": return { label: "Format guidance",    cls: "bg-violet-50 text-violet-800 border-violet-200" };
    case "unicode_block":   return { label: "Unicode block",      cls: "bg-zinc-50 text-zinc-700 border-zinc-200" };
    default:                return { label: kind || "(unknown)",  cls: "bg-slate-50 text-slate-700 border-slate-200" };
  }
}

// ---- Change type (Continuous Learning) --------------------------------------

export function ChangeTypeChip({ type, size = "sm" }: { type: string; size?: "xs" | "sm" }) {
  const meta = changeTypeMeta(type);
  const sz = size === "xs" ? "text-[10px] px-1.5 py-0.5" : "text-[11px] px-2 py-0.5";
  return (
    <span className={`pill border ${sz} ${meta.cls}`} title={`${meta.label} (raw: ${type})`}>
      {meta.label}
    </span>
  );
}

function changeTypeMeta(t: string): { label: string; cls: string } {
  switch (t) {
    case "threshold":       return { label: "Threshold tuning",      cls: "bg-amber-50 text-amber-800 border-amber-200" };
    case "pattern_list":    return { label: "Pattern list addition", cls: "bg-sky-50 text-sky-800 border-sky-200" };
    case "routing_rule":    return { label: "Routing rule update",   cls: "bg-violet-50 text-violet-800 border-violet-200" };
    case "validation_rule": return { label: "Validation rule",       cls: "bg-emerald-50 text-emerald-800 border-emerald-200" };
    case "prompt":          return { label: "Classifier prompt",     cls: "bg-zinc-50 text-zinc-700 border-zinc-200" };
    default:                return { label: t || "-",                cls: "bg-slate-50 text-slate-700 border-slate-200" };
  }
}

// ---- Fingerprint decoder -----------------------------------------------------

/**
 * Decode a generator fingerprint like
 *   "validation_rule:missing_field:service_order:po_number"
 * into a human-readable label.
 */
export function decodeFingerprint(fp: string | null | undefined): string {
  if (!fp) return "";
  const parts = fp.split(":");
  if (parts.length < 2) return fp;
  const [type, subtype, ...rest] = parts;
  if (type === "validation_rule" && subtype === "missing_field" && rest.length >= 2) {
    return `Validation rule: ${rest[0]} cases with missing ${rest[1]}`;
  }
  if (type === "validation_rule" && subtype === "invariant_outlier" && rest.length >= 2) {
    return `Validation rule: ${rest[0]} cases with ${rest[1]} value outside historical band`;
  }
  if (type === "pattern_list" && subtype === "rule" && rest.length >= 1) {
    return `Pattern list: extend the ${rest[0]} deterministic rule`;
  }
  if (type === "threshold" && subtype === "l4_floor" && rest.length >= 1) {
    return `Threshold: raise the L4 confidence floor for ${rest[0]}`;
  }
  if (type === "routing_rule" && rest.length >= 1) {
    return `Routing rule: ${parts.slice(1).join(" ")}`;
  }
  return fp.replace(/_/g, " ").replace(/:/g, " · ");
}
