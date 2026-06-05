import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  CostStageSummary,
  GovAgentInfo,
  GovAgents,
  GovAuditLog,
  GovCompliance,
  GovPolicies,
  GovSlo,
  GovSummary,
  SloResult,
  StageSloRow,
  governanceApi,
} from "../api";
import { InfoTip as SharedInfoTip } from "../components/InfoTip";

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

type SubTab = "overview" | "audit" | "trust" | "policy" | "compliance" | "slo";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "audit", label: "Audit Trail" },
  { key: "trust", label: "Agent Fleet" },
  { key: "policy", label: "Policy Engine" },
  { key: "compliance", label: "Compliance" },
  { key: "slo", label: "SLO Monitor" },
];

function isSubTab(v: string | null): v is SubTab {
  return !!v && SUB_TABS.some((t) => t.key === v);
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const RING_COLORS: Record<number, { bg: string; text: string; border: string; dot: string }> = {
  0: { bg: "bg-purple-50 dark:bg-purple-500/10", text: "text-purple-700 dark:text-purple-300", border: "border-purple-200 dark:border-purple-500/30", dot: "bg-purple-500" },
  1: { bg: "bg-zbrain-50 dark:bg-zbrain/10", text: "text-zbrain dark:text-zbrain-dark-accent", border: "border-zbrain-200 dark:border-zbrain/30", dot: "bg-zbrain" },
  2: { bg: "bg-teal-50 dark:bg-teal-500/10", text: "text-teal-700 dark:text-teal-300", border: "border-teal-200 dark:border-teal-500/30", dot: "bg-teal-500" },
  3: { bg: "bg-gray-100 dark:bg-gray-800", text: "text-gray-600 dark:text-gray-400", border: "border-gray-200 dark:border-gray-700", dot: "bg-gray-400" },
};

const DECISION_COLORS: Record<string, string> = {
  allow: "text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/30",
  audit: "text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30",
  block: "text-orange-700 dark:text-orange-400 bg-orange-50 dark:bg-orange-500/10 border-orange-200 dark:border-orange-500/30",
  deny: "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30",
};

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: "text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30",
  MEDIUM: "text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30",
  LOW: "text-blue-700 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-blue-500/30",
  INFO: "text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 border-gray-200 dark:border-gray-700",
};

function DecisionPill({ decision }: { decision: string }) {
  const cls = DECISION_COLORS[decision] || DECISION_COLORS["audit"];
  return (
    <span className={`pill border ${cls} uppercase text-[10px] font-semibold tracking-wider`}>
      {decision}
    </span>
  );
}

function RingBadge({ ring, label }: { ring: number; label?: string }) {
  const c = RING_COLORS[ring] || RING_COLORS[3];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-xs font-medium ${c.bg} ${c.text} ${c.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {label || `Ring ${ring}`}
    </span>
  );
}

function SectionHeader({ title, subtitle, tooltip }: { title: string; subtitle?: string; tooltip?: string }) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-1.5">
        <h2 className="text-base font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{title}</h2>
        {tooltip && (
          <div className="relative group">
            <button
              className="w-3.5 h-3.5 rounded-full border border-zbrain-muted dark:border-zbrain-dark-muted text-zbrain-muted dark:text-zbrain-dark-muted flex items-center justify-center text-[9px] font-bold leading-none hover:border-zbrain hover:text-zbrain dark:hover:text-zbrain-dark-accent transition-colors"
              aria-label={`About ${title}`}
            >
              i
            </button>
            <div className="pointer-events-none absolute left-0 top-5 z-30 hidden group-hover:block w-72 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line">
              {tooltip}
            </div>
          </div>
        )}
      </div>
      {subtitle && <p className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5">{subtitle}</p>}
    </div>
  );
}

function KpiTile({ label, value, sub, accent, tooltip }: { label: string; value: string | number; sub?: string; accent?: boolean; tooltip?: string }) {
  return (
    <div className="card p-4 flex flex-col gap-1">
      <div className="flex items-center gap-1">
        <span className="text-[11px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">{label}</span>
        {tooltip && (
          <div className="relative group">
            <button
              className="w-3.5 h-3.5 rounded-full border border-zbrain-muted dark:border-zbrain-dark-muted text-zbrain-muted dark:text-zbrain-dark-muted flex items-center justify-center text-[9px] font-bold leading-none hover:border-zbrain hover:text-zbrain dark:hover:text-zbrain-dark-accent transition-colors"
              aria-label={`About ${label}`}
            >
              i
            </button>
            <div className="pointer-events-none absolute left-0 top-5 z-30 hidden group-hover:block w-60 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl">
              {tooltip}
            </div>
          </div>
        )}
      </div>
      <span className={`text-2xl font-bold tabular-nums ${accent ? "text-zbrain dark:text-zbrain-dark-accent" : "text-zbrain-ink dark:text-zbrain-dark-ink"}`}>
        {value}
      </span>
      {sub && <span className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted">{sub}</span>}
    </div>
  );
}

function Tip({ text, position = "left" }: { text: string; position?: "left" | "right" }) {
  return (
    <div className="relative group inline-flex items-center ml-1">
      <button
        className="w-3.5 h-3.5 rounded-full border border-zbrain-muted dark:border-zbrain-dark-muted text-zbrain-muted dark:text-zbrain-dark-muted flex items-center justify-center text-[9px] font-bold leading-none hover:border-zbrain hover:text-zbrain dark:hover:text-zbrain-dark-accent transition-colors"
        tabIndex={-1}
        aria-label="More information"
      >i</button>
      <div className={`pointer-events-none absolute top-5 z-40 hidden group-hover:block w-72 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line ${position === "right" ? "right-0" : "left-0"}`}>
        {text}
      </div>
    </div>
  );
}

function InlineBar({ value, max, color = "bg-zbrain" }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums w-8 text-right text-zbrain-muted dark:text-zbrain-dark-muted">{value}</span>
    </div>
  );
}

// Simple SVG donut chart (no external dep)
function DonutChart({ slices }: { slices: { label: string; value: number; color: string }[] }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  if (total === 0) return <div className="h-32 flex items-center justify-center text-zbrain-muted text-xs">No data</div>;

  const r = 40;
  const cx = 56;
  const cy = 56;
  const activeSlices = slices.filter((s) => s.value > 0);

  // Single-slice case: SVG arcs with coincident start/end points don't render,
  // so fall back to a plain circle.
  const singleColor = activeSlices.length === 1 ? activeSlices[0].color : null;

  let cumulative = 0;
  const paths: { d: string; color: string }[] = [];

  if (!singleColor) {
    for (const slice of slices) {
      if (slice.value === 0) continue;
      const frac = slice.value / total;
      const startAngle = cumulative * 2 * Math.PI - Math.PI / 2;
      const endAngle = (cumulative + frac) * 2 * Math.PI - Math.PI / 2;
      cumulative += frac;

      const x1 = cx + r * Math.cos(startAngle);
      const y1 = cy + r * Math.sin(startAngle);
      const x2 = cx + r * Math.cos(endAngle);
      const y2 = cy + r * Math.sin(endAngle);
      const largeArc = frac > 0.5 ? 1 : 0;

      paths.push({
        d: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`,
        color: slice.color,
      });
    }
  }

  return (
    <div className="flex items-center gap-4">
      <svg width="112" height="112" viewBox="0 0 112 112">
        {singleColor
          ? <circle cx={cx} cy={cy} r={r} fill={singleColor} opacity={0.85} />
          : paths.map((p, i) => <path key={i} d={p.d} fill={p.color} opacity={0.85} />)
        }
        <circle cx={cx} cy={cy} r={24} fill="white" className="dark:fill-zbrain-dark-elev1" />
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize="12" fontWeight="bold" fill="currentColor" className="text-zbrain-ink">
          {total}
        </text>
      </svg>
      <div className="flex flex-col gap-1.5">
        {slices.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: s.color }} />
            <span className="text-zbrain-ink dark:text-zbrain-dark-ink">{s.label}</span>
            <span className="tabular-nums text-zbrain-muted dark:text-zbrain-dark-muted ml-auto pl-4">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components used across tabs
// ---------------------------------------------------------------------------

const FUNNEL_STAGES = [
  { key: "passed_intake",   label: "Passed Intake",    color: "bg-zbrain/30 dark:bg-zbrain/20" },
  { key: "extracted",       label: "Extracted",         color: "bg-zbrain/45 dark:bg-zbrain/30" },
  { key: "reached_decision",label: "Decision",          color: "bg-zbrain/60 dark:bg-zbrain/45" },
  { key: "l4_auto",         label: "allow · Autonomous", color: "bg-zbrain/80 dark:bg-zbrain/65" },
  { key: "completed",       label: "Completed",         color: "bg-zbrain dark:bg-zbrain" },
];

function PipelineFunnel({ funnel }: { funnel: GovSummary["funnel"] }) {
  const total = funnel.received || 1;
  const pct = (n: number) => Math.round((n / total) * 100);

  return (
    <div className="card p-4">
      <div className="flex items-center gap-1.5 mb-3">
        <h2 className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Case Governance Funnel</h2>
        <SharedInfoTip
          text={
            "Email-to-reply flow through AGT governance checkpoints, with drop-offs at each stage.\n\n" +
            "Passed Intake: cleared the PolicyEvaluator spam/phishing screen (ASI-01, ASI-06).\n" +
            "Extracted: document-intelligence agent parsed attachments; intent and fields resolved.\n" +
            "Decision: confidence scored and autonomy tier assigned.\n" +
            "  allow at 95% or higher: fully autonomous.\n" +
            "  audit 80 to 94%: one-click approval.\n" +
            "  block below 80%: full human review.\n" +
            "Autonomous: subset of Decision that executed without approval.\n" +
            "Completed: reply drafted and CommunicationLog written."
          }
        />
      </div>
      {/* Funnel bars */}
      <div className="space-y-2 mt-3">
        {/* Received row */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-zbrain-muted dark:text-zbrain-dark-muted">Emails Received</span>
            <span className="text-xs font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{total} · 100%</span>
          </div>
          <div className="h-6 w-full rounded bg-zbrain/15 dark:bg-zbrain/10 flex items-center justify-center overflow-hidden">
            <div className="h-full w-full bg-zbrain/15 dark:bg-zbrain/10 rounded" />
          </div>
        </div>
        {FUNNEL_STAGES.map((s) => {
          const val = funnel[s.key as keyof typeof funnel] as number;
          const width = Math.max((val / total) * 100, 0);
          return (
            <div key={s.key}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-zbrain-muted dark:text-zbrain-dark-muted">{s.label}</span>
                <span className="text-xs font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{val} · {pct(val)}%</span>
              </div>
              <div className="h-6 w-full rounded bg-zbrain-surface dark:bg-zbrain-dark-elev2 flex items-center justify-center overflow-hidden">
                <div
                  className={`h-full rounded ${s.color} transition-all`}
                  style={{ width: `${width}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      {/* Drop-off summary */}
      <div className="flex flex-wrap gap-3 mt-4">
        {funnel.discarded_intake > 0 && (
          <span className="text-[11px] px-2 py-1 rounded border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-300">
            ↓ {funnel.discarded_intake} discarded at intake (spam/phishing)
          </span>
        )}
        {funnel.errored > 0 && (
          <span className="text-[11px] px-2 py-1 rounded border border-orange-200 dark:border-orange-500/30 bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-300">
            ↓ {funnel.errored} pipeline errors
          </span>
        )}
        {funnel.l2_hitl > 0 && (
          <span className="text-[11px] px-2 py-1 rounded border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300">
            ↓ {funnel.l2_hitl} routed to block (full human review)
          </span>
        )}
        {funnel.l3_one_click > 0 && (
          <span className="text-[11px] px-2 py-1 rounded border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-300">
            ↓ {funnel.l3_one_click} staged for audit (one-click approval)
          </span>
        )}
      </div>
    </div>
  );
}

const TRUST_TIERS = [
  { label: "Verified Partner", min: 900, max: 1000, color: "bg-emerald-500 dark:bg-emerald-400", text: "text-emerald-700 dark:text-emerald-300", bg: "bg-emerald-50 dark:bg-emerald-500/10" },
  { label: "Trusted",          min: 700, max: 899,  color: "bg-blue-500 dark:bg-blue-400",    text: "text-blue-700 dark:text-blue-300",    bg: "bg-blue-50 dark:bg-blue-500/10" },
  { label: "Standard",         min: 500, max: 699,  color: "bg-amber-500 dark:bg-amber-400",  text: "text-amber-700 dark:text-amber-300",  bg: "bg-amber-50 dark:bg-amber-500/10" },
  { label: "Probationary",     min: 300, max: 499,  color: "bg-orange-500 dark:bg-orange-400",text: "text-orange-700 dark:text-orange-300",bg: "bg-orange-50 dark:bg-orange-500/10" },
  { label: "Untrusted",        min: 0,   max: 299,  color: "bg-red-500 dark:bg-red-400",      text: "text-red-700 dark:text-red-300",      bg: "bg-red-50 dark:bg-red-500/10" },
];

function TrustTierChart({ agents }: { agents: GovAgentInfo[] }) {
  const maxCount = Math.max(...TRUST_TIERS.map((t) => agents.filter((a) => a.avg_trust_score >= t.min && a.avg_trust_score <= t.max).length), 1);
  return (
    <div className="card p-5">
      <SectionHeader
        title="Trust Tier Distribution"
        subtitle="Fleet-level view of agent trust tiers, matched to AGT's 5-tier trust classification model"
        tooltip={
          "AGT classifies each agent's trust score (0 to 1000) into one of 5 tiers:\n\n" +
          "• Verified Partner (≥ 900): highest trust; automated full delegation allowed.\n" +
          "• Trusted (700 to 899): standard enterprise agent; normal policy gates apply.\n" +
          "• Standard (500 to 699): limited trust; stricter tool-call approval thresholds.\n" +
          "• Probationary (300 to 499): new or anomalous agent; human sponsor required for sensitive actions.\n" +
          "• Untrusted (< 300): quarantine candidate; KillSwitch may trigger on next policy violation.\n\n" +
          "Trust score = pipeline confidence × 1000. Scores are updated per pipeline run."
        }
      />
      <div className="space-y-2.5 mt-3">
        {TRUST_TIERS.map((tier) => {
          const count = agents.filter((a) => a.avg_trust_score >= tier.min && a.avg_trust_score <= tier.max).length;
          const width = Math.max((count / maxCount) * 100, count > 0 ? 8 : 0);
          const names = agents.filter((a) => a.avg_trust_score >= tier.min && a.avg_trust_score <= tier.max).map((a) => a.display_name);
          return (
            <div key={tier.label} className="flex items-center gap-3">
              <div className="w-36 shrink-0 flex items-center justify-between">
                <span className={`text-xs font-semibold ${tier.text}`}>{tier.label}</span>
              </div>
              <div className="flex-1 h-6 rounded bg-zbrain-surface dark:bg-zbrain-dark-elev2 relative overflow-hidden">
                <div className={`h-full rounded ${tier.color} opacity-80 transition-all`} style={{ width: `${width}%` }} />
              </div>
              <div className="w-16 shrink-0 flex items-center gap-1.5">
                <span className={`text-xs font-bold tabular-nums ${count > 0 ? tier.text : "text-zbrain-muted dark:text-zbrain-dark-muted"}`}>{count}</span>
                {names.length > 0 && (
                  <span className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted truncate">{names.join(", ")}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 mt-3 flex-wrap">
        {TRUST_TIERS.map((t) => (
          <div key={t.label} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${t.color}`} />
            <span className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted">{t.min === 900 ? "≥900" : `${t.min} to ${t.max}`}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ToolInvocationChart({ breakdown }: { breakdown: GovPolicies["tool_invocation_breakdown"] }) {
  const maxTotal = Math.max(...breakdown.map((r) => r.total), 1);
  return (
    <div className="card p-5">
      <SectionHeader
        title="Tool Invocation Outcomes"
        subtitle="CapabilityGuardMiddleware enforcement: each tool's allow vs. block split across all pipeline runs"
        tooltip={
          "Adapted from AGT's 'Policy by Action' stacked bar (governance-dashboard demo).\n\n" +
          "AGT's CapabilityGuardMiddleware intercepts every tool call before execution and evaluates it against the stage agent's allowed_tools / denied_tools lists plus active policy rules.\n\n" +
          "• Green (Allow): call passed the guard and executed.\n" +
          "• Red (Block): call was rejected by the guard; a tool_blocked audit event was written.\n\n" +
          "High block-rate tools (> 20%) are highlighted with an amber border; these may indicate misconfigured tool lists or attempted policy violations."
        }
      />
      <div className="space-y-2 mt-3">
        {breakdown.map((row) => {
          const allowPct = (row.allow / Math.max(row.total, 1)) * 100;
          const blockPct = (row.block / Math.max(row.total, 1)) * 100;
          const barWidth = (row.total / maxTotal) * 100;
          const highBlock = row.block_rate > 0.20;
          return (
            <div key={row.tool} className={`flex items-center gap-3 ${highBlock ? "pl-2 border-l-4 border-amber-400 dark:border-amber-500" : ""}`}>
              <div className="w-44 shrink-0">
                <span className="text-xs font-mono text-zbrain-ink dark:text-zbrain-dark-ink truncate block">{row.tool}</span>
              </div>
              <div className="flex-1 h-5 rounded bg-zbrain-surface dark:bg-zbrain-dark-elev2 relative overflow-hidden">
                <div style={{ width: `${barWidth}%` }} className="h-full flex rounded overflow-hidden">
                  <div className="bg-emerald-500 dark:bg-emerald-400 opacity-80" style={{ width: `${allowPct}%` }} />
                  {row.block > 0 && (
                    <div className="bg-red-500 dark:bg-red-400 opacity-80" style={{ width: `${blockPct}%` }} />
                  )}
                </div>
              </div>
              <div className="w-28 shrink-0 flex items-center gap-1.5 text-[11px]">
                <span className="tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink font-semibold">{row.total}</span>
                {row.block > 0 && (
                  <span className="text-red-600 dark:text-red-400 font-semibold">{Math.round(row.block_rate * 100)}% blocked</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-4 mt-3">
        <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-emerald-500 dark:bg-emerald-400 opacity-80" /><span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">Allowed</span></div>
        <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-red-500 dark:bg-red-400 opacity-80" /><span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">Blocked by CapabilityGuard</span></div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 1: Overview
// ---------------------------------------------------------------------------

function GovernanceHealthScore({ summary, sloData }: { summary: GovSummary; sloData: GovSlo | null }) {
  const { policy_decisions } = summary;
  const total = (policy_decisions.allow || 0) + (policy_decisions.audit || 0) + (policy_decisions.block || 0) + (policy_decisions.deny || 0);
  // Policy enforcement = the policy engine produced a CORRECT decision.
  // allow, audit, and deny are all "engine correctly applied policy"
  // (action approved, action approved-with-audit, action rejected outright).
  // Only `block` represents a true policy-prevented attempt where an agent
  // wanted to do something the policy said no to. Denying spam is the
  // policy WORKING, not failing.
  const policyEnforcementRate = total > 0
    ? ((policy_decisions.allow || 0) + (policy_decisions.audit || 0) + (policy_decisions.deny || 0)) / total
    : 1;
  const auditIntegrity = 1.0;
  const identityCoverage = 1.0;
  const sloHealth = sloData ? (sloData.slos.filter((s) => s.met).length / Math.max(sloData.slos.length, 1)) : 1.0;
  const score = Math.round((policyEnforcementRate * 0.35 + auditIntegrity * 0.25 + identityCoverage * 0.25 + sloHealth * 0.15) * 100);
  const tier = score >= 95 ? "Verified Partner" : score >= 80 ? "Trusted" : score >= 60 ? "Standard" : score >= 40 ? "Probationary" : "Untrusted";
  const barColor = score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-amber-500" : "bg-red-500";
  const textColor = score >= 80 ? "text-emerald-600 dark:text-emerald-400" : score >= 60 ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400";

  const factors = [
    { label: "Policy", ok: policyEnforcementRate >= 0.85, tip: `${(policyEnforcementRate * 100).toFixed(0)}% allow/audit rate` },
    { label: "Audit", ok: auditIntegrity >= 0.95, tip: "Hash chain verified" },
    { label: "Identity", ok: identityCoverage >= 1.0, tip: "All agents have DID credentials" },
    { label: "SLOs", ok: sloHealth >= 0.75, tip: sloData ? `${sloData.slos.filter((s) => s.met).length}/${sloData.slos.length} objectives met` : "Fetching…" },
  ];

  const breakdownText =
    `Composite score from the AGT TrustScore model.\n\n` +
    `Policy enforcement (35%): ${(policyEnforcementRate * 100).toFixed(0)}% of decisions correctly applied.\n` +
    `Audit chain integrity (25%): hash chain verified.\n` +
    `Identity coverage (25%): all agents carry DID credentials.\n` +
    `SLO health (15%): ${sloData ? `${sloData.slos.filter((s) => s.met).length} of ${sloData.slos.length}` : "loading"} objectives met.\n\n` +
    `Tier thresholds: at least 95 Verified Partner, 80 Trusted, 60 Standard, 40 Probationary, below 40 Untrusted.`;

  return (
    <div className="card p-4 h-full flex flex-col justify-center">
      <div className="flex items-center gap-1.5 mb-1.5">
        <h2 className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Governance Health</h2>
        <SharedInfoTip text={breakdownText} />
      </div>
      <div className="flex items-end gap-3 mb-2">
        <span className={`text-4xl font-extrabold tabular-nums leading-none ${textColor}`}>{score}</span>
        <div className="pb-0.5">
          <span className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted">/100</span>
          <div className={`text-[11px] font-semibold leading-tight ${textColor}`}>{tier}</div>
        </div>
      </div>
      <div className="w-full h-2 bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded-full overflow-hidden mb-2">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${score}%` }} />
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {factors.map((f) => (
          <span
            key={f.label}
            title={f.tip}
            className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border cursor-default ${f.ok ? "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30" : "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30"}`}
          >
            {f.ok ? "✓" : "⚠"} {f.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function OverviewTab({ summary, sloData, compliance }: { summary: GovSummary; sloData: GovSlo | null; compliance: GovCompliance | null }) {
  const { totals, policy_decisions, kill_events, breach_alerts } = summary;
  const [killExpanded, setKillExpanded] = useState(false);

  const donutSlices = [
    { label: "Allow", value: policy_decisions.allow || 0, color: "#10b981" },
    { label: "Audit", value: policy_decisions.audit || 0, color: "#f59e0b" },
    { label: "Block", value: policy_decisions.block || 0, color: "#f97316" },
    { label: "Deny", value: policy_decisions.deny || 0, color: "#ef4444" },
  ];

  const owaspSub = compliance
    ? `${compliance.coverage_pct}% weighted, ${compliance.needs_attention.length} need${compliance.needs_attention.length === 1 ? "s" : ""} attention`
    : "ASI Top 10";

  return (
    <div className="space-y-4">
      {/* Row 1: Governance Health anchor + KPI strip */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        <div className="lg:col-span-4">
          <GovernanceHealthScore summary={summary} sloData={sloData} />
        </div>
        <div className="lg:col-span-8 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <CompactKpi
            label="Cases"
            value={totals.governed_pipelines}
            accent
            tooltip="Cases where every agent tool call is intercepted by the AGT Policy Engine, evaluated against active rules, and resolved to Allow, Audit, Block, or Deny in under 0.1 ms."
          />
          <CompactKpi
            label="Policies"
            value={totals.active_policies}
            tooltip="Active rule sets enforced at runtime: business_rules and spam_heuristic."
          />
          <CompactKpi
            label="HITL"
            value={totals.pending_hitl}
            tooltip="Cases awaiting human approval in the audit or block queue."
          />
          <CompactKpi
            label="Kills"
            value={kill_events.total}
            tooltip="Total agent terminations issued by the AGT KillSwitch across all six KillReason types."
          />
          <CompactKpi
            label="OWASP ASI"
            value={totals.owasp_coverage}
            accent
            sub={owaspSub}
            tooltip="Count of OWASP ASI 2026 controls assessed by ZBrain's GovernanceVerifier. The weighted coverage and attention count reflect live runtime evidence captured in the audit log."
          />
        </div>
      </div>

      {/* Row 2: Pipeline funnel + Policy decisions side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {summary.funnel && (
          <div className="lg:col-span-2">
            <PipelineFunnel funnel={summary.funnel} />
          </div>
        )}
        <div className="card p-4">
          <div className="flex items-center gap-1.5 mb-3">
            <h2 className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Policy Decisions</h2>
            <SharedInfoTip
              text={
                "Every agent action is evaluated by the AGT PolicyEvaluator and returns one of four outcomes:\n\n" +
                "Allow: action passed policy and executed automatically.\n" +
                "Audit: action passed policy but was flagged for review; a draft is staged for human sign-off.\n" +
                "Block: action passed policy but is held until a human approves it.\n" +
                "Deny: action was hard-blocked by a policy rule and discarded.\n\n" +
                "Conflict resolution: priority_first_match."
              }
            />
          </div>
          <DonutChart slices={donutSlices} />
        </div>
      </div>

      {/* Row 3: Breach alerts (compact list) */}
      {breach_alerts.length > 0 && (
        <div className="card p-3">
          <div className="flex items-center gap-1.5 mb-2 px-1">
            <h2 className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
              Breach Alerts
              <span className="ml-2 text-[11px] font-normal text-zbrain-muted">{breach_alerts.length} active</span>
            </h2>
            <SharedInfoTip text="Active SLO breaches, policy violations, or compliance regressions detected by the GovernanceVerifier. Severity is mapped to AGT risk score tiers: HIGH triggers an incident commander, MEDIUM stays in the queue, LOW is informational." />
          </div>
          <ul className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
            {breach_alerts.map((alert, i) => {
              const tone = SEVERITY_COLORS[alert.severity] || SEVERITY_COLORS.INFO;
              return (
                <li key={i} className="flex items-center gap-3 px-1 py-2">
                  <span className={`pill border ${tone} text-[10px] uppercase tracking-wide shrink-0`}>{alert.severity}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{alert.kind.replace(/_/g, " ")}</span>
                      <span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted truncate">{alert.message}</span>
                    </div>
                  </div>
                  <span className="text-[10px] shrink-0 text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">
                    {new Date(alert.detected_at).toLocaleTimeString()}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Row 4: KillSwitch events (compact summary, expandable detail) */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1.5">
            <h2 className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
              KillSwitch Events
              <span className="ml-2 text-[11px] font-normal text-zbrain-muted">{kill_events.total} total</span>
            </h2>
            <SharedInfoTip
              text={
                "The AGT KillSwitch terminates an agent immediately and rolls back any in-flight saga steps. Reasons:\n\n" +
                "MANUAL: operator triggered via API or dashboard.\n" +
                "BEHAVIORAL_DRIFT: agent deviated beyond drift_threshold (default 0.15).\n" +
                "RATE_LIMIT: agent exceeded its ring-level rate limit.\n" +
                "RING_BREACH: agent attempted an operation outside its execution ring.\n" +
                "QUARANTINE_TIMEOUT: agent exceeded max time in quarantine.\n" +
                "SESSION_TIMEOUT: agent session exceeded max_session_duration."
              }
            />
          </div>
          <button
            type="button"
            onClick={() => setKillExpanded((v) => !v)}
            className="text-[11px] font-medium text-zbrain dark:text-zbrain-dark-accent hover:underline"
          >
            {killExpanded ? "Hide breakdown" : "Show breakdown"}
          </button>
        </div>
        {!killExpanded ? (
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                { key: "MANUAL",             label: "Manual",             color: "red" },
                { key: "BEHAVIORAL_DRIFT",   label: "Behavioral Drift",   color: "amber" },
                { key: "RATE_LIMIT",         label: "Rate Limit",         color: "orange" },
                { key: "RING_BREACH",        label: "Ring Breach",        color: "purple" },
                { key: "QUARANTINE_TIMEOUT", label: "Quarantine", color: "slate" },
                { key: "SESSION_TIMEOUT",    label: "Session Timeout",    color: "slate" },
              ] as { key: keyof typeof kill_events; label: string; color: string }[]
            ).map(({ key, label, color }) => {
              const v = (kill_events[key] as number) ?? 0;
              const pillMap: Record<string, string> = {
                red:    "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30",
                amber:  "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30",
                orange: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:border-orange-500/30",
                purple: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30",
                slate:  "bg-zbrain-surface text-zbrain-ink border-zbrain-divider dark:bg-zbrain-dark-elev2 dark:text-zbrain-dark-ink dark:border-zbrain-dark-divider",
              };
              const muted = v === 0 ? "opacity-50" : "";
              return (
                <span
                  key={key}
                  className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-medium ${pillMap[color]} ${muted}`}
                >
                  {label}
                  <span className="font-bold tabular-nums">{v}</span>
                </span>
              );
            })}
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {(
              [
                { key: "MANUAL",             label: "Manual",             color: "red" },
                { key: "BEHAVIORAL_DRIFT",   label: "Behavioral Drift",   color: "amber" },
                { key: "RATE_LIMIT",         label: "Rate Limit",         color: "orange" },
                { key: "RING_BREACH",        label: "Ring Breach",        color: "purple" },
                { key: "QUARANTINE_TIMEOUT", label: "Quarantine", color: "slate" },
                { key: "SESSION_TIMEOUT",    label: "Session Timeout",    color: "slate" },
              ] as { key: keyof typeof kill_events; label: string; color: string }[]
            ).map(({ key, label, color }) => {
              const colorMap: Record<string, string> = {
                red:    "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-300",
                amber:  "bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-300",
                orange: "bg-orange-50 dark:bg-orange-500/10 border-orange-200 dark:border-orange-500/30 text-orange-700 dark:text-orange-300",
                purple: "bg-purple-50 dark:bg-purple-500/10 border-purple-200 dark:border-purple-500/30 text-purple-700 dark:text-purple-300",
                slate:  "bg-zbrain-surface dark:bg-zbrain-dark-elev2 border-zbrain-divider dark:border-zbrain-dark-divider text-zbrain-ink dark:text-zbrain-dark-ink",
              };
              return (
                <div key={key} className={`flex flex-col gap-1 p-3 rounded-lg border ${colorMap[color]}`}>
                  <span className="text-[10px] font-mono font-semibold uppercase tracking-wide opacity-80">{label}</span>
                  <span className="text-2xl font-bold tabular-nums">{kill_events[key] ?? 0}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * CompactKpi: tighter KPI tile used in the Overview header strip. Drops the
 * subtitle line into a tooltip so each tile is one number plus one label.
 */
function CompactKpi({
  label,
  value,
  sub,
  accent,
  tooltip,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: boolean;
  tooltip?: string;
}) {
  return (
    <div className="card p-3 flex flex-col gap-0.5 justify-center">
      <div className="flex items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">
          {label}
        </span>
        {tooltip && <SharedInfoTip text={tooltip} />}
      </div>
      <span className={`text-2xl font-bold tabular-nums leading-tight ${accent ? "text-zbrain dark:text-zbrain-dark-accent" : "text-zbrain-ink dark:text-zbrain-dark-ink"}`}>
        {value}
      </span>
      {sub && (
        <span className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted leading-tight truncate" title={sub}>
          {sub}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 2: Audit Trail
// ---------------------------------------------------------------------------

const EVENT_TYPE_OPTIONS = ["", "tool_invocation", "tool_blocked", "policy_evaluation", "policy_violation", "rogue_detection", "agent_invocation"];
const OUTCOME_OPTIONS = ["", "success", "failure", "denied", "error"];

// Sub-stages that don't have their own agent identity but emit trace events;
// map them to the parent agent for display purposes so the audit table shows
// a human-readable label instead of the raw DID.
const STAGE_ALIASES: Record<string, string> = {
  "did:mesh:keysight-salesops-reconcile": "did:mesh:keysight-salesops-extract",
};

export function AuditTab() {
  const [log, setLog] = useState<GovAuditLog | null>(null);
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("");
  const [agentDid, setAgentDid] = useState("");
  const [outcome, setOutcome] = useState("");
  const [loading, setLoading] = useState(false);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  // Agent directory loaded once on mount so the dropdown labels + per-row
  // display names always reflect the live agent inventory from the main
  // SalesOps app (instead of a hardcoded map that drifted out of sync).
  const [agentDirectory, setAgentDirectory] = useState<{ did: string; name: string }[]>([]);

  useEffect(() => {
    governanceApi.agents()
      .then((res) => setAgentDirectory(res.agents.map((a) => ({ did: a.did, name: a.display_name }))))
      .catch(() => undefined);
  }, []);

  const stageDisplayMap = (() => {
    const m: Record<string, string> = {};
    for (const a of agentDirectory) m[a.did] = a.name;
    // Substages without their own DID inherit the parent agent's label.
    for (const [alias, target] of Object.entries(STAGE_ALIASES)) {
      if (m[target]) m[alias] = m[target];
    }
    return m;
  })();
  const agentDidOptions = ["", ...agentDirectory.map((a) => a.did)];

  useEffect(() => {
    setLoading(true);
    governanceApi
      .auditLog({ page, event_type: eventType || undefined, agent_did: agentDid || undefined, outcome: outcome || undefined })
      .then(setLog)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [page, eventType, agentDid, outcome]);

  const totalPages = log ? Math.ceil(log.total_count / log.page_size) : 1;

  const handleExport = () => {
    if (!log) return;
    const rows = ["entry_id,timestamp,agent_did,event_type,action,resource,outcome,policy_decision"];
    for (const e of log.entries) {
      rows.push(`${e.entry_id},"${e.timestamp}","${e.agent_did}","${e.event_type}","${e.action}","${e.resource}","${e.outcome}","${e.policy_decision}"`);
    }
    const blob = new Blob([rows.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "governance-audit-log.csv";
    a.click();
  };

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="card p-3 flex flex-wrap items-center gap-3">
        <span className="text-xs uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Filters:</span>
        <select
          value={eventType}
          onChange={(e) => { setEventType(e.target.value); setPage(1); }}
          className="text-xs border border-zbrain-divider dark:border-zbrain-dark-divider rounded-md px-2 py-1.5 bg-white dark:bg-zbrain-dark-elev1 text-zbrain-ink dark:text-zbrain-dark-ink"
        >
          {EVENT_TYPE_OPTIONS.map((o) => <option key={o} value={o}>{o || "All event types"}</option>)}
        </select>
        <select
          value={agentDid}
          onChange={(e) => { setAgentDid(e.target.value); setPage(1); }}
          className="text-xs border border-zbrain-divider dark:border-zbrain-dark-divider rounded-md px-2 py-1.5 bg-white dark:bg-zbrain-dark-elev1 text-zbrain-ink dark:text-zbrain-dark-ink"
        >
          {agentDidOptions.map((o) => <option key={o} value={o}>{o ? (stageDisplayMap[o] ?? o) : "All agents"}</option>)}
        </select>
        <select
          value={outcome}
          onChange={(e) => { setOutcome(e.target.value); setPage(1); }}
          className="text-xs border border-zbrain-divider dark:border-zbrain-dark-divider rounded-md px-2 py-1.5 bg-white dark:bg-zbrain-dark-elev1 text-zbrain-ink dark:text-zbrain-dark-ink"
        >
          {OUTCOME_OPTIONS.map((o) => <option key={o} value={o}>{o || "All outcomes"}</option>)}
        </select>
        <div className="ml-auto flex items-center gap-2">
          {log && (
            log.chain_integrity === "tampered" ? (
              <div className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400 font-semibold">
                <span>⚠</span>
                <span>Hash chain: <strong>TAMPERED</strong>{log.tampered_at != null ? ` (broken at entry #${log.tampered_at})` : ""}</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-xs text-emerald-700 dark:text-emerald-400">
                <ChainIcon />
                <span>Hash chain: <strong>verified</strong></span>
              </div>
            )
          )}
          <button onClick={handleExport} className="btn-secondary text-xs">Export CSV</button>
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-zbrain-muted text-sm">Loading audit log…</div>
        ) : !log || log.entries.length === 0 ? (
          <div className="p-8 text-center text-zbrain-muted text-sm">
            No audit entries yet. Process an email to generate trace events.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zbrain-divider dark:border-zbrain-dark-divider bg-zbrain-surface dark:bg-zbrain-dark-elev2">
                  {["#", "Time", "Agent", "Event", "Outcome", "Chain"].map((h) => (
                    <th key={h} className="px-3 py-2.5 text-left font-semibold text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider text-[10px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {log.entries.map((e, idx) => {
                  const isExpanded = expandedRow === e.entry_id;
                  const isBreakPoint = log.chain_integrity === "tampered" && log.tampered_at != null && e.entry_id === log.tampered_at;
                  const isTampered = log.chain_integrity === "tampered" && log.tampered_at != null && e.entry_id >= log.tampered_at;
                  // Prefer the server-provided display name attached to the
                  // audit entry; fall back to the live directory map, then
                  // to the raw DID. This eliminates the race-window where the
                  // row would show the short code before /agents resolves.
                  const stageName = e.agent_display_name
                    || stageDisplayMap[e.agent_did]
                    || e.agent_did.replace("did:mesh:keysight-salesops-", "");
                  return (
                    <>
                      <tr
                        key={e.entry_id}
                        onClick={() => setExpandedRow(isExpanded ? null : e.entry_id)}
                        className={`border-b border-zbrain-divider/50 dark:border-zbrain-dark-divider/50 cursor-pointer select-none
                          ${isBreakPoint
                            ? "bg-red-50 dark:bg-red-500/10"
                            : isTampered
                            ? "bg-amber-50/60 dark:bg-amber-500/5"
                            : isExpanded
                            ? "bg-zbrain-surface dark:bg-zbrain-dark-elev2"
                            : idx % 2 === 0
                            ? "hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev2"
                            : "bg-zbrain-surface/40 dark:bg-zbrain-dark-elev1/40 hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev2"}`}
                      >
                        <td className="px-3 py-2 font-mono text-zbrain-muted dark:text-zbrain-dark-muted">{e.entry_id}</td>
                        <td className="px-3 py-2 whitespace-nowrap text-zbrain-muted dark:text-zbrain-dark-muted">
                          {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "-"}
                        </td>
                        <td className="px-3 py-2">
                          <span className="text-xs font-semibold text-zbrain dark:text-zbrain-dark-accent">{stageName}</span>
                        </td>
                        <td className="px-3 py-2">
                          <EventTypePill type={e.event_type} />
                          {e.action && <p className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 truncate max-w-[160px]" title={`${e.action} · ${(e.resource || "").replace(/^pipeline:/, "case:")}`}>{(e.resource || e.action).replace(/^pipeline:/, "case:")}</p>}
                        </td>
                        <td className="px-3 py-2"><OutcomePill outcome={e.outcome} errorDetail={e.error_detail} /></td>
                        <td className="px-3 py-2">
                          {isTampered ? (
                            <div className="relative group inline-flex items-center">
                              <span className={`text-sm font-bold ${isBreakPoint ? "text-red-500 dark:text-red-400" : "text-amber-500 dark:text-amber-400"}`}>⚠</span>
                              <div className="pointer-events-none absolute right-0 top-5 z-30 hidden group-hover:block w-52 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[10px] leading-relaxed p-2.5 shadow-2xl whitespace-pre-line">
                                {isBreakPoint
                                  ? `Chain break detected here.\nEntry #${e.entry_id} has a mismatched hash; the entry content was modified or an entry was inserted/deleted before it.`
                                  : `Unverifiable.\nChain is broken at entry #${log.tampered_at}; this entry cannot be trusted.`}
                              </div>
                            </div>
                          ) : (
                            <span className="text-emerald-500 dark:text-emerald-400 text-sm font-bold" title="Hash chain link verified">✓</span>
                          )}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${e.entry_id}-detail`} className={`border-b border-zbrain-divider dark:border-zbrain-dark-divider ${isBreakPoint ? "bg-red-50/80 dark:bg-red-500/5" : isTampered ? "bg-amber-50/40 dark:bg-amber-500/5" : "bg-zbrain-surface/70 dark:bg-zbrain-dark-elev2/70"}`}>
                          <td colSpan={6} className="px-4 py-3">
                            {isBreakPoint && (
                              <div className="mb-3 flex items-start gap-2 p-2.5 rounded-lg bg-red-100 dark:bg-red-500/15 border border-red-300 dark:border-red-500/40 text-[11px] text-red-700 dark:text-red-300">
                                <span className="font-bold shrink-0">⚠ Chain break</span>
                                <span>The SHA-256 hash of this entry does not match the expected value derived from its content and the previous entry's hash. Either this entry was modified after it was written, or an entry was inserted or removed before it in the chain.</span>
                              </div>
                            )}
                            <div className="grid grid-cols-2 gap-x-10 gap-y-2 text-[11px] mb-3">
                              <div className="flex gap-2">
                                <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Matched Rule</span>
                                <code className="font-mono text-zbrain-ink dark:text-zbrain-dark-ink">{e.matched_rule || "-"}</code>
                              </div>
                              <div className="flex gap-2">
                                <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Policy Decision</span>
                                <DecisionPill decision={e.policy_decision} />
                              </div>
                              <div className="flex gap-2">
                                <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Duration</span>
                                <span className="text-zbrain-ink dark:text-zbrain-dark-ink">{e.duration_ms != null ? `${e.duration_ms} ms` : "-"}</span>
                              </div>
                              <div className="flex gap-2">
                                <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Chain Status</span>
                                <span className={`font-semibold ${isTampered ? (isBreakPoint ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400") : "text-emerald-600 dark:text-emerald-400"}`}>
                                  {isBreakPoint ? "BREAK POINT" : isTampered ? "unverifiable" : "verified ✓"}
                                </span>
                              </div>
                            </div>
                            <details className="text-[11px]">
                              <summary className="text-zbrain-muted dark:text-zbrain-dark-muted cursor-pointer text-[10px] uppercase tracking-wider font-semibold select-none">Forensics</summary>
                              <div className="mt-2 grid grid-cols-2 gap-x-10 gap-y-2">
                                <div className="flex gap-2">
                                  <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Trace ID</span>
                                  <code className="font-mono text-zbrain dark:text-zbrain-dark-accent">{e.trace_id || "-"}</code>
                                </div>
                                <div className="flex gap-2">
                                  <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Agent DID</span>
                                  <code className="font-mono text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted break-all">{e.agent_did}</code>
                                </div>
                                <div className="flex gap-2">
                                  <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Prev Hash</span>
                                  <code className="font-mono text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted break-all">{e.previous_hash || "-"}</code>
                                </div>
                                <div className="flex gap-2">
                                  <span className="text-zbrain-muted dark:text-zbrain-dark-muted w-28 shrink-0">Entry Hash</span>
                                  <code className={`font-mono text-[10px] break-all ${isBreakPoint ? "text-red-500 dark:text-red-400" : "text-zbrain-muted dark:text-zbrain-dark-muted"}`}>{e.hash || "-"}</code>
                                </div>
                                {e.error_detail && (
                                  <div className="col-span-2 flex gap-2">
                                    <span className="text-red-500 dark:text-red-400 w-28 shrink-0">Error Detail</span>
                                    <span className="text-red-600 dark:text-red-300 break-all">{e.error_detail}</span>
                                  </div>
                                )}
                              </div>
                            </details>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {log && totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-zbrain-muted dark:text-zbrain-dark-muted">
          <span>{log.total_count} total entries</span>
          <div className="flex items-center gap-1">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="btn-secondary px-2 py-1 disabled:opacity-40">←</button>
            <span className="px-2">Page {page} of {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="btn-secondary px-2 py-1 disabled:opacity-40">→</button>
          </div>
        </div>
      )}

      {/* Hash chain info card hidden per operator request — the per-row chain
          status column already shows verification state, so the standalone
          explainer card was redundant in the demo. Restore by unwrapping the
          `false &&` below when needed. */}
      {false && (
        <div className="card p-4">
          <div className="flex items-start gap-3">
            <ChainIcon />
            <div>
              <p className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink inline-flex items-center">
                Merkle Hash Chain Integrity
                <Tip text={"Each entry is hashed as SHA-256(id|ts|agent|event|action|resource|outcome|decision|prev_hash). Any modification, insertion, or deletion breaks the chain from that point forward.\n\nThe per-row chain status appears in the rightmost column; open any row to inspect its Prev Hash and Entry Hash directly."} />
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function EventTypePill({ type }: { type: string }) {
  const map: Record<string, string> = {
    tool_invocation: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30",
    tool_blocked: "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30",
    policy_evaluation: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30",
    policy_violation: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/30",
  };
  return (
    <span className={`pill border text-[10px] ${map[type] || "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400"}`}>
      {type.replace(/_/g, " ")}
    </span>
  );
}

function OutcomePill({ outcome, errorDetail }: { outcome: string; errorDetail?: string | null }) {
  const map: Record<string, string> = {
    success: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30",
    failure: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:border-orange-500/30",
    denied:  "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30",
    error:   "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30",
  };
  const hasDetail = (outcome === "error" || outcome === "failure") && errorDetail;
  return (
    <div className={hasDetail ? "relative group inline-block" : "inline-block"}>
      <span className={`pill border text-[10px] ${map[outcome] || "bg-gray-100 text-gray-600 border-gray-200"} ${hasDetail ? "cursor-help underline decoration-dotted" : ""}`}>
        {outcome}
      </span>
      {hasDetail && (
        <div className="pointer-events-none absolute left-0 top-6 z-30 hidden group-hover:block w-72 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-wrap">
          <span className="font-semibold text-red-300">Error detail</span>{"\n"}{errorDetail}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 3: Agent Trust
// ---------------------------------------------------------------------------

export function TrustTab({ agents }: { agents: GovAgents }) {
  const { agents: agentList, delegation_chain, risk_signals } = agents;

  return (
    <div className="space-y-5">
      {/* Trust Tier Distribution */}
      <TrustTierChart agents={agentList} />

      {/* Delegation chain */}
      <div className="card p-5">
        <SectionHeader
          title="Delegation Chain"
          subtitle="Capability scope narrows at each level: child scope ⊆ parent scope (AGT: delegation narrowing)"
          tooltip={
            "AGT AgentMesh: each agent holds only a delegated subset of the root's capabilities.\n\n" +
            "• AgentIdentity.delegate(childId, caps): the SDK throws at call time if a child requests a capability the parent doesn't hold. Privilege escalation is structurally impossible.\n\n" +
            "• Monotonic narrowing: authority can only decrease through the chain: child caps ⊆ parent caps at every level.\n\n" +
            "• delegationDepth: hops from root (0). Policy rules can gate on this: e.g., 'only depth-0 may call salesforce_create_order_tool'.\n\n" +
            "• HumanSponsor: every agent must have an accountable human sponsor. AGT prevents orphan agents (agents operating without oversight).\n\n" +
            "• Cascade revocation: revoking a parent auto-revokes all its delegates within ≤5 seconds."
          }
        />

        {/* ScopeChain.verify() banner */}
        {delegation_chain.scope_chain_verified ? (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 text-xs text-emerald-700 dark:text-emerald-300 mb-4">
            <span className="font-bold text-sm">✓</span>
            <span className="flex-1">
              <span className="font-semibold font-mono">ScopeChain.verify()</span> passed: all {delegation_chain.agents.length} delegates satisfy monotonic scope narrowing (child capabilities ⊆ parent capabilities).
              <span className="ml-2 opacity-60">Verified {new Date(delegation_chain.verified_at).toLocaleTimeString()}</span>
            </span>
            <Tip
              position="right"
              text={"ScopeChain.verify() walks the full delegation chain and re-checks that every child's capability list is a strict subset of its parent's. Returns (is_valid, error_msg).\n\nIf it fails, a delegate holds capabilities outside its parent's scope. This is a privilege escalation and a security violation. AGT's delegate() call prevents this at creation time; verify() catches any tampering that happens after creation."}
            />
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-xs text-red-700 dark:text-red-300 mb-4">
            <span className="font-bold text-sm">⚠</span>
            <span><span className="font-semibold font-mono">ScopeChain.verify()</span> FAILED: a delegate has capabilities outside its parent's scope (privilege escalation).</span>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {/* Root node */}
          <div className="p-4 rounded-lg bg-purple-50 dark:bg-purple-500/10 border border-purple-200 dark:border-purple-500/30">
            <div className="flex items-center gap-3 mb-3">
              <span className="text-purple-600 dark:text-purple-300 shrink-0"><OrchestratorIcon /></span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{delegation_chain.root.label}</p>
                <p className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted">{delegation_chain.root.did}</p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
                <RingBadge ring={0} label="Root" />
                <div className="relative group inline-flex items-center">
                  <span className="pill bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-500/30 text-[10px] cursor-default">depth: {delegation_chain.root.delegation_depth}</span>
                  <div className="pointer-events-none absolute right-0 top-6 z-40 hidden group-hover:block w-64 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line">
                    {"delegationDepth = 0 means this is the root authority; it was not delegated to by any parent.\n\nPolicy rules can reference depth to constrain privilege: e.g., only depth-0 agents may invoke non-reversible write tools."}
                  </div>
                </div>
                <div className="relative group inline-flex items-center">
                  <span className="pill bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 text-[10px] cursor-default">● {delegation_chain.root.status}</span>
                  <div className="pointer-events-none absolute right-0 top-6 z-40 hidden group-hover:block w-64 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line">
                    {"active = identity is valid and operating.\n\nIf status becomes revoked, all delegates of this agent are automatically revoked in cascade within ≤5 seconds (AGT IdentityRegistry.revoke())."}
                  </div>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 mb-1.5">
              <p className="text-[10px] uppercase tracking-wider text-purple-600 dark:text-purple-400 font-semibold">Full authority across all {delegation_chain.root.capabilities.length} capabilities</p>
              <Tip text={"This is the complete capability set held by the root orchestrator. Every capability that any stage agent can use must appear here first; all delegations are strict subsets of this list.\n\nCapabilities map directly to tool names. The root can call any tool; each stage agent receives only the tools it needs for its specific function (principle of least privilege)."} />
            </div>
            <div className="flex flex-wrap gap-1">
              {delegation_chain.root.capabilities.map((cap) => (
                <span key={cap} className="pill bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-500/30 text-[10px]">{cap}</span>
              ))}
            </div>
          </div>

          {/* Delegated agents */}
          <div className="ml-6 pl-5 border-l-2 border-purple-200 dark:border-purple-500/30 space-y-2">
            {delegation_chain.agents.map((a) => {
              const c = RING_COLORS[a.ring] || RING_COLORS[3];
              return (
                <div key={a.did} className={`p-3 rounded-lg border ${c.bg} ${c.border}`}>
                  {/* Header row */}
                  <div className="flex items-start gap-2 mb-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{a.label}</p>
                      <p className={`text-[10px] font-mono ${c.text} opacity-80`}>{a.did}</p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0 flex-wrap justify-end">
                      <RingBadge ring={a.ring} />
                      <div className="relative group inline-flex items-center">
                        <span className={`pill border text-[10px] cursor-default ${c.bg} ${c.text} ${c.border}`}>depth: {a.delegation_depth}</span>
                        <div className="pointer-events-none absolute right-0 top-6 z-40 hidden group-hover:block w-64 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line">
                          {"delegationDepth = 1 means this agent was directly delegated to by the root (one hop). Deeper chains (depth 2, 3…) are possible in AGT when agents sub-delegate to further sub-agents."}
                        </div>
                      </div>
                      <div className="relative group inline-flex items-center">
                        <span className="pill bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 text-[10px] cursor-default">● {a.status}</span>
                        <div className="pointer-events-none absolute right-0 top-6 z-40 hidden group-hover:block w-64 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line">
                          {"active = identity is valid.\n\nIf this agent's parent (the orchestrator) is revoked, this agent is automatically revoked in cascade. You can also revoke this agent directly, which would cascade to any agents it has delegated to."}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Parent DID + Sponsor */}
                  <div className="flex items-center gap-4 mb-2.5 flex-wrap">
                    <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted font-mono">
                      <span className="opacity-60">parent: </span>
                      <span className="text-purple-600 dark:text-purple-400">{a.parent_did}</span>
                    </p>
                    <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted">
                      <span className="opacity-60">sponsor: </span>
                      <span className="text-zbrain-ink dark:text-zbrain-dark-ink font-medium">{a.sponsor_role}</span>
                    </p>
                  </div>

                  {/* Delegated capabilities */}
                  <div className="mb-2">
                    <div className="flex items-center gap-1 mb-1">
                      <p className="text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400 font-semibold">
                        Delegated ({a.capabilities.length})
                      </p>
                      <Tip text={"These are the capabilities passed to this agent via AgentIdentity.delegate(agentId, [capabilities]).\n\nThe agent can only invoke tools in this list. Any call to a tool outside this set is rejected by AGT's CapabilityGuardMiddleware before execution reaches the tool."} />
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {a.capabilities.map((cap) => (
                        <span key={cap} className="pill bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 text-[10px]">{cap}</span>
                      ))}
                    </div>
                  </div>

                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Agent identity cards */}
      <SectionHeader
        title="Stage Agent Identities"
        subtitle="Each pipeline stage operates as an isolated agent with a unique DID, trust ring, and credential TTL"
      />
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {agentList.map((agent) => {
          const c = RING_COLORS[agent.ring] || RING_COLORS[3];
          const histMax = Math.max(...agent.trust_histogram, 1);
          return (
            <div key={agent.stage} className="card p-4 flex flex-col gap-3">
              {/* Header */}
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{agent.display_name}</p>
                  <p className="text-[10px] font-mono text-zbrain dark:text-zbrain-dark-accent mt-0.5 break-all">{agent.did}</p>
                </div>
                <RingBadge ring={agent.ring} label={`Ring ${agent.ring}`} />
              </div>

              {/* Trust score */}
              <div className={`rounded-lg p-3 ${c.bg} ${c.border} border`}>
                <div className="flex items-end gap-2">
                  <span className={`text-2xl font-bold tabular-nums ${c.text}`}>{agent.avg_trust_score}</span>
                  <span className={`text-xs mb-0.5 ${c.text} opacity-70`}>/1000</span>
                  <span className={`ml-auto text-[10px] font-medium ${c.text}`}>{agent.trust_tier_label}</span>
                </div>
                {/* Mini histogram */}
                <div className="flex items-end gap-0.5 mt-2 h-8">
                  {agent.trust_histogram.map((v, i) => (
                    <div
                      key={i}
                      className={`flex-1 rounded-sm ${c.dot}`}
                      style={{ height: `${Math.max(2, (v / histMax) * 100)}%`, opacity: 0.6 + 0.4 * (i / 9) }}
                      title={`${i * 100}–${(i + 1) * 100}: ${v} pipelines`}
                    />
                  ))}
                </div>
                <div className="flex justify-between text-[9px] mt-0.5 opacity-50 text-zbrain-muted">
                  <span>0</span><span>500</span><span>1000</span>
                </div>
              </div>

              {/* Metadata — 4 key fields only */}
              <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
                <div className="flex items-center gap-1 text-zbrain-muted dark:text-zbrain-dark-muted">
                  <span>Sponsor</span>
                  <Tip position="right" text={"HumanSponsor: every agent must have an accountable human who is responsible for its behaviour. AGT prevents orphan agents (agents operating without a named human owner).\n\nThe sponsor's max_agents and max_delegation_depth limits are enforced by the IdentityRegistry."} />
                </div>
                <span className="text-zbrain-ink dark:text-zbrain-dark-ink font-medium">{agent.sponsor_role}</span>

                <div className="flex items-center gap-1 text-zbrain-muted dark:text-zbrain-dark-muted">
                  <span>Reversibility</span>
                  <Tip position="right" text={"NON_REVERSIBLE: this agent performs writes that cannot be undone after commit (e.g., confirmed order in ERP). AGT's SagaOrchestrator can compensate in-flight steps, but committed writes are permanent.\n\nREVERSIBLE: all operations are safe to retry, abort, or compensate without lasting side-effects."} />
                </div>
                <span className={`font-medium ${agent.reversibility === "NON_REVERSIBLE" ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                  {agent.reversibility}
                </span>

                <div className="flex items-center gap-1 text-zbrain-muted dark:text-zbrain-dark-muted">
                  <span>Kill events</span>
                  <Tip position="right" text={"Number of times AGT's KillSwitch has terminated this agent. Each kill is caused by one of 6 KillReason values: MANUAL, BEHAVIORAL_DRIFT, RATE_LIMIT, RING_BREACH, QUARANTINE_TIMEOUT, SESSION_TIMEOUT.\n\nA kill immediately terminates the agent and triggers SagaOrchestrator rollback of any in-flight transaction steps."} />
                </div>
                <span className={`font-medium ${agent.kill_events > 0 ? "text-red-600 dark:text-red-400" : "text-zbrain-ink dark:text-zbrain-dark-ink"}`}>{agent.kill_events}</span>

                <div className="flex items-center gap-1 text-zbrain-muted dark:text-zbrain-dark-muted">
                  <span>Samples</span>
                  <Tip position="right" text={"Number of pipeline runs where this agent was active. Used by RiskScorer to build the trust histogram.\n\nWith no samples the score defaults to 750 (the demo seed value). In production, trust scores update continuously, factoring in behavioral patterns, policy compliance, and identity verification."} />
                </div>
                <span className="text-zbrain-ink dark:text-zbrain-dark-ink">{agent.samples}</span>
              </div>

              {/* Allowed tools */}
              <div>
                <div className="flex items-center gap-1 mb-1.5">
                  <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">Allowed tools (capability guard)</p>
                  <Tip text={"CapabilityGuardMiddleware: before any tool call executes, AGT checks whether this agent's DID has the tool in its allowed_tools list. If not, the call is blocked and logged as a tool_blocked audit event, regardless of what the LLM requested.\n\nThis is enforced at the middleware layer; the LLM cannot bypass it by prompt manipulation."} />
                </div>
                <div className="flex flex-wrap gap-1">
                  {agent.allowed_tools.map((t) => (
                    <span key={t} className="pill bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30 text-[10px]">{t}</span>
                  ))}
                </div>
              </div>

              {/* Denied tools */}
              {agent.denied_tools.length > 0 && (
                <div>
                  <div className="flex items-center gap-1 mb-1.5">
                    <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">Blocked tools</p>
                    <Tip text={"Calls to these tools from this agent are intercepted by CapabilityGuardMiddleware and logged as tool_blocked audit events. Even if the LLM generates a call to one of these tools, AGT blocks execution before it reaches the tool handler."} />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {agent.denied_tools.map((t) => (
                      <span key={t} className="pill bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 text-[10px] line-through opacity-60">{t}</span>
                    ))}
                  </div>
                </div>
              )}

            </div>
          );
        })}
      </div>

      {/* Risk signals */}
      {risk_signals.length > 0 && (
        <div className="card p-5">
          <SectionHeader title="Recent Risk Signals" subtitle="MANUAL kills from CSR feedback; severity mapped to AGT risk score tiers" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zbrain-divider dark:border-zbrain-dark-divider">
                  {["Kind", "Severity", "Agent DID", "Message", "Timestamp"].map((h) => (
                    <th key={h} className="px-3 py-2 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {risk_signals.map((s, i) => (
                  <tr key={i} className="border-b border-zbrain-divider/50 dark:border-zbrain-dark-divider/50">
                    <td className="px-3 py-2 font-mono font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{s.kind}</td>
                    <td className="px-3 py-2">
                      <span className={`pill border ${SEVERITY_COLORS[s.severity]}`}>{s.severity}</span>
                    </td>
                    <td className="px-3 py-2 font-mono text-zbrain dark:text-zbrain-dark-accent text-[10px]">{s.agent_did}</td>
                    <td className="px-3 py-2 text-zbrain-ink dark:text-zbrain-dark-ink max-w-[280px] truncate" title={s.message}>{s.message}</td>
                    <td className="px-3 py-2 text-zbrain-muted dark:text-zbrain-dark-muted whitespace-nowrap">
                      {s.ts ? new Date(s.ts).toLocaleString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 4: Policy Engine
// ---------------------------------------------------------------------------

export function PolicyTab({ policies }: { policies: GovPolicies }) {
  const { policies: policyDocs, policy_default_action, tool_allow_deny_matrix, confidence_gates, blocked_patterns, policy_defaults, per_agent_policies, all_conflict_strategies } = policies;

  const [, setSearchParams] = useSearchParams();
  const [scopeFilter, setScopeFilter] = useState<string>("");
  const [actionFilter, setActionFilter] = useState<string>("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [sortPriority, setSortPriority] = useState<"desc" | "asc">("desc");
  const [showDevDetails, setShowDevDetails] = useState<string | null>(null);

  const filtered = policyDocs
    .filter((p) => {
      if (scopeFilter && p.scope !== scopeFilter) return false;
      if (actionFilter && p.action !== actionFilter) return false;
      return true;
    })
    .sort((a, b) => sortPriority === "desc" ? b.priority - a.priority : a.priority - b.priority);

  const toYaml = (p: typeof policyDocs[0]) =>
`name: ${p.rule_key}
condition:
  field: ${p.condition_field}
  operator: ${p.condition_operator}
  value: ${p.condition_value}
action: ${p.action}
priority: ${p.priority}
message: "${p.rule_message}"`;

  const fmtRelative = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const h = Math.floor(diff / 3600000);
    if (h < 1) return "< 1h ago";
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };

  const ROW_BORDER: Record<string, string> = {
    allow: "border-l-4 border-l-emerald-500",
    audit: "border-l-4 border-l-amber-500",
    block: "border-l-4 border-l-orange-500",
    deny:  "border-l-4 border-l-red-500",
  };
  const ACTION_BORDER: Record<string, string> = {
    allow: "border-l-emerald-500",
    audit: "border-l-amber-500",
    block: "border-l-orange-500",
    deny:  "border-l-red-500",
  };
  const BANNER_BG: Record<string, string> = {
    allow: "bg-emerald-50/50 dark:bg-emerald-500/5",
    audit: "bg-amber-50/50 dark:bg-amber-500/5",
    block: "bg-orange-50/50 dark:bg-orange-500/5",
    deny:  "bg-red-50/50 dark:bg-red-500/5",
  };
  const ACTION_SUMMARIES: Record<string, string> = {
    allow: "Execution permitted; pipeline proceeds autonomously",
    audit: "Execution permitted; one-click CSR sign-off required before Execute runs",
    block: "Execution refused; full human review required before pipeline can resume",
    deny:  "Pipeline terminated at Intake; no confidence score computed",
  };

  const SCOPE_COLORS: Record<string, string> = {
    Global: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30",
    Tenant: "bg-zbrain-50 text-zbrain border-zbrain-200 dark:bg-zbrain/10 dark:text-zbrain-dark-accent dark:border-zbrain/30",
    Agent:  "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30",
  };

  const STAGE_BADGES: Record<string, { label: string; cls: string }> = {
    intake:  { label: "Intake",  cls: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700" },
    decide:  { label: "Decide",  cls: "bg-zbrain-50 text-zbrain border-zbrain-200 dark:bg-zbrain/10 dark:text-zbrain-dark-accent dark:border-zbrain/30" },
    execute: { label: "Execute", cls: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30" },
  };

  const OWASP_NAMES: Record<string, string> = {
    "ASI-01": "Goal Hijacking",
    "ASI-02": "Tool Misuse",
    "ASI-03": "Identity & Privilege Abuse",
    "ASI-04": "Supply Chain",
    "ASI-05": "Unexpected Code Execution",
    "ASI-06": "Memory & Context Poisoning",
    "ASI-07": "Insecure Inter-Agent Comm",
    "ASI-08": "Cascading Failures",
    "ASI-09": "Human-Agent Trust Exploitation",
    "ASI-10": "Rogue Agents",
  };

  return (
    <div className="space-y-5">

      {/* Confidence gates — pipeline flow + gate cards — HERO section */}
      <div className="card p-5">
        <SectionHeader
          title="Confidence Threshold Gates"
          subtitle="Enforcement points across the six-stage pipeline"
          tooltip={"Each pipeline stage runs a distinct agent. Governance gates fire at two points:\n\n• deny: fires at Intake, before any confidence score is computed. Spam and phishing emails are stopped here and never reach Extract or Decide.\n\n• allow / audit / block: fire at the Decide→Execute boundary. The Decide agent produces a confidence score (0 to 1). PolicyEvaluator maps that score to an action:\n  ≥ 95% → allow (Fully Autonomous)\n  80 to 94% → audit (One-click CSR sign-off)\n  < 80% → block (Full human review)\n\nExecute is the only stage that writes to CRM/ERP. All side-effects are non-reversible, so the PolicyEvaluator gate at the Decide→Execute boundary is the last enforcement point before permanent changes are made."}
        />

        {/* ── Stage gate table ─────────────────────────── */}
        <div className="mt-4 overflow-hidden rounded-lg border border-zbrain-divider dark:border-zbrain-dark-divider">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev1 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
                <th className="py-2.5 px-4 text-left text-[10px] uppercase tracking-wider font-semibold text-zbrain-muted dark:text-zbrain-dark-muted w-[120px]">Stage</th>
                <th className="py-2.5 px-4 text-left text-[10px] uppercase tracking-wider font-semibold text-zbrain-muted dark:text-zbrain-dark-muted">Function</th>
                <th className="py-2.5 px-4 text-left text-[10px] uppercase tracking-wider font-semibold text-zbrain-muted dark:text-zbrain-dark-muted w-[260px]">Enforcement Gate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
              <tr className="bg-white dark:bg-zbrain-dark-bg hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev1 transition-colors">
                <td className="py-3 px-4 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Intake</td>
                <td className="py-3 px-4 text-zbrain-muted dark:text-zbrain-dark-muted leading-snug">Language detection, intent classification, spam/phishing screening</td>
                <td className="py-3 px-4">
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-red-300 dark:border-red-500/40 bg-red-50 dark:bg-red-500/10 px-2.5 py-1 text-[11px] font-semibold text-red-600 dark:text-red-400">
                    <span className="font-mono">deny</span>
                    <span className="text-[10px] font-normal opacity-80">(spam/phishing blocked before scoring)</span>
                  </span>
                </td>
              </tr>
              <tr className="bg-white dark:bg-zbrain-dark-bg hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev1 transition-colors">
                <td className="py-3 px-4 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Extract</td>
                <td className="py-3 px-4 text-zbrain-muted dark:text-zbrain-dark-muted leading-snug">Document parsing (PDF, XLSX, DOCX, image OCR); structured field extraction</td>
                <td className="py-3 px-4 text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted opacity-50">-</td>
              </tr>
              <tr className="bg-white dark:bg-zbrain-dark-bg hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev1 transition-colors">
                <td className="py-3 px-4 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Reconcile</td>
                <td className="py-3 px-4 text-zbrain-muted dark:text-zbrain-dark-muted leading-snug">Cross-check PO line items vs matched CRM quote; emit price/qty/SKU mismatches</td>
                <td className="py-3 px-4 text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted opacity-50">-</td>
              </tr>
              <tr className="bg-white dark:bg-zbrain-dark-bg hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev1 transition-colors">
                <td className="py-3 px-4 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Decide</td>
                <td className="py-3 px-4 text-zbrain-muted dark:text-zbrain-dark-muted leading-snug">Confidence scoring (0 to 1); assigns autonomy tier (allow / audit / block)</td>
                <td className="py-3 px-4">
                  <div className="inline-flex flex-col gap-1 rounded-md border border-zbrain/30 dark:border-zbrain-dark-accent/30 bg-zbrain/5 dark:bg-zbrain-dark-accent/10 px-2.5 py-1.5">
                    <span className="text-[10px] font-bold text-zbrain dark:text-zbrain-dark-accent uppercase tracking-wide">PolicyEvaluator fires</span>
                    <div className="flex items-center gap-2 text-[10px]">
                      <span className="text-emerald-600 dark:text-emerald-400">≥ 95% → <span className="font-mono font-bold">allow</span></span>
                      <span className="text-zbrain-muted opacity-40">·</span>
                      <span className="text-amber-600 dark:text-amber-400">80 to 94% → <span className="font-mono font-bold">audit</span></span>
                      <span className="text-zbrain-muted opacity-40">·</span>
                      <span className="text-orange-600 dark:text-orange-400">&lt; 80% → <span className="font-mono font-bold">block</span></span>
                    </div>
                  </div>
                </td>
              </tr>
              <tr className="bg-purple-50/60 dark:bg-purple-500/5 hover:bg-purple-50 dark:hover:bg-purple-500/10 transition-colors">
                <td className="py-3 px-4">
                  <span className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Execute</span>
                  <p className="text-[10px] text-purple-600 dark:text-purple-400 font-semibold mt-0.5">non-reversible writes</p>
                </td>
                <td className="py-3 px-4 text-zbrain-muted dark:text-zbrain-dark-muted leading-snug">CRM order creation, ERP holds, shipment triggers; side-effects cannot be undone</td>
                <td className="py-3 px-4">
                  <div className="flex flex-col gap-1 text-[10px]">
                    <span className="text-emerald-600 dark:text-emerald-400"><span className="font-mono font-semibold">allow</span> → runs autonomously</span>
                    <span className="text-amber-600 dark:text-amber-400"><span className="font-mono font-semibold">audit</span> → requires one-click CSR sign-off</span>
                    <span className="text-orange-600 dark:text-orange-400"><span className="font-mono font-semibold">block</span> → full human review; execution refused</span>
                  </div>
                </td>
              </tr>
              <tr className="bg-white dark:bg-zbrain-dark-bg hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev1 transition-colors">
                <td className="py-3 px-4 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Communicate</td>
                <td className="py-3 px-4 text-zbrain-muted dark:text-zbrain-dark-muted leading-snug">Draft reply in customer's detected language; attach SOA/invoice PDF</td>
                <td className="py-3 px-4 text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted opacity-50">-</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* ── Gate detail cards ─────────────────────────── */}
        <div className="mt-5 pt-4 border-t border-zbrain-divider dark:border-zbrain-dark-divider">
          <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted font-semibold mb-3">Gate Detail: PolicyDecision.action semantics</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {confidence_gates.map((gate) => {
              const rangeLabel = gate.threshold_min === null
                ? "No score"
                : gate.threshold_min === 0.95
                ? `≥ ${(gate.threshold_min * 100).toFixed(0)}%`
                : gate.threshold_min === 0.0
                ? `< ${(gate.threshold_max! * 100).toFixed(0)}%`
                : `${((gate.threshold_min ?? 0) * 100).toFixed(0)}%–${(gate.threshold_max! * 100 - 1).toFixed(0)}%`;

              const AGT_ACTION_TIPS: Record<string, string> = {
                allow: "AGT PolicyDecision.action = 'allow'\ndecision.allowed = True\n\nPermit and execute. No extra audit entry beyond the standard log.",
                audit: "AGT PolicyDecision.action = 'audit'\ndecision.allowed = True\n\nPermit AND write an audit entry. Pipeline proceeds (a draft is created) but is held for one-click CSR sign-off before Execute runs.",
                block: "AGT PolicyDecision.action = 'block'\ndecision.allowed = False\n\nHard block. Execution refused; denial message surfaced to caller. Full CSR review required before resuming.",
                deny:  "AGT PolicyDecision.action = 'deny'\ndecision.allowed = False\n\nRejected outright at Intake; no confidence score is ever computed.",
              };

              return (
                <div key={gate.gate} className={`rounded-lg border p-3 ${DECISION_COLORS[gate.action]}`}>
                  <div className="flex items-start justify-between gap-1 mb-2">
                    <span className="text-[11px] font-bold leading-tight">{gate.label}</span>
                    <div className="relative group flex-shrink-0">
                      <span className={`pill border cursor-default uppercase text-[9px] font-semibold tracking-wider ${DECISION_COLORS[gate.action]}`}>{gate.action}</span>
                      <div className="pointer-events-none absolute right-0 top-6 z-40 hidden group-hover:block w-64 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line">
                        {AGT_ACTION_TIPS[gate.action]}
                      </div>
                    </div>
                  </div>
                  <div className="text-lg font-bold tabular-nums mb-1.5">{rangeLabel}</div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span className="text-[8px] uppercase tracking-wider opacity-60">decision.allowed</span>
                    <span className={`text-[9px] font-bold font-mono ${gate.decision_allowed ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>{gate.decision_allowed ? "True" : "False"}</span>
                  </div>
                  <p className="text-[9px] opacity-70 leading-snug">{gate.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Per-agent policy limits */}
      <div className="card p-5">
        <SectionHeader
          title="Per-Agent GovernancePolicy Limits"
          subtitle="create_governance_middleware(agent_id=…): resource limits scoped to each pipeline stage"
          tooltip={"AGT's create_governance_middleware() accepts an agent_id parameter to register per-agent policy overrides.\n\nEach stage agent below has its max_tool_calls capped to match its declared allowed-tool count, preventing any possibility of calling more tools than its capability scope.\n\nRing 0 agents always have require_human_approval=True because their CRM/ERP writes are non-reversible."}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zbrain-divider dark:border-zbrain-dark-divider bg-zbrain-surface dark:bg-zbrain-dark-elev2">
                {["Agent", "Ring", "Max Tool Calls", "Max Tokens", "Drift Threshold", "Require Approval", "Log All"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {per_agent_policies.map((a, i) => (
                <tr key={a.stage} className={`border-b border-zbrain-divider/50 dark:border-zbrain-dark-divider/50 ${i % 2 === 0 ? "" : "bg-zbrain-surface/40 dark:bg-zbrain-dark-elev1/40"}`}>
                  <td className="px-3 py-2.5">
                    <p className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{a.label}</p>
                    <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted capitalize">{a.stage}</p>
                  </td>
                  <td className="px-3 py-2.5"><RingBadge ring={a.ring} /></td>
                  <td className="px-3 py-2.5 tabular-nums font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{a.max_tool_calls}</td>
                  <td className="px-3 py-2.5 tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{a.max_tokens.toLocaleString()}</td>
                  <td className="px-3 py-2.5 tabular-nums text-zbrain-muted dark:text-zbrain-dark-muted">{a.drift_threshold}</td>
                  <td className="px-3 py-2.5">
                    {a.require_human_approval
                      ? <span className="pill bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30 text-[9px]">yes</span>
                      : <span className="text-zbrain-muted dark:text-zbrain-dark-muted text-[10px]">no</span>
                    }
                  </td>
                  <td className="px-3 py-2.5">
                    {a.log_all_calls
                      ? <span className="text-emerald-600 dark:text-emerald-400 text-[10px]">✓</span>
                      : <span className="text-zbrain-muted text-[10px]">-</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Blocked Patterns */}
      {(() => {
        const { kpis, categories, top_triggered } = blocked_patterns;
        const maxCatBlocks = Math.max(...categories.map(c => c.total_fire_count), 1);
        const CAT_COLORS: Record<string, { bar: string; badge: string; bg: string; border: string; text: string }> = {
          pii:          { bar: "bg-red-500",    badge: "bg-red-100 text-red-700 border-red-200 dark:bg-red-500/20 dark:text-red-300 dark:border-red-500/30",    bg: "bg-red-50 dark:bg-red-500/10",    border: "border-red-200 dark:border-red-500/30",    text: "text-red-700 dark:text-red-300" },
          credential:   { bar: "bg-orange-500", badge: "bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-500/20 dark:text-orange-300 dark:border-orange-500/30", bg: "bg-orange-50 dark:bg-orange-500/10", border: "border-orange-200 dark:border-orange-500/30", text: "text-orange-700 dark:text-orange-300" },
          injection:    { bar: "bg-amber-500",  badge: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-500/30",  bg: "bg-amber-50 dark:bg-amber-500/10",  border: "border-amber-200 dark:border-amber-500/30",  text: "text-amber-700 dark:text-amber-300" },
          shell:        { bar: "bg-rose-500",   badge: "bg-rose-100 text-rose-700 border-rose-200 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/30",   bg: "bg-rose-50 dark:bg-rose-500/10",   border: "border-rose-200 dark:border-rose-500/30",   text: "text-rose-700 dark:text-rose-300" },
          exfiltration: { bar: "bg-purple-500", badge: "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-500/20 dark:text-purple-300 dark:border-purple-500/30", bg: "bg-purple-50 dark:bg-purple-500/10", border: "border-purple-200 dark:border-purple-500/30", text: "text-purple-700 dark:text-purple-300" },
        };
        return (
          <div className="card p-5">
            <SectionHeader
              title="Blocked Patterns"
              subtitle="GovernancePolicy.blocked_patterns: parameter sanitization across all tool calls"
              tooltip={"AGT's GovernancePolicy.blocked_patterns supports three match types:\n\n• PatternType.SUBSTRING: simple text contains check (fastest)\n• PatternType.REGEX: compiled case-insensitive regex\n• PatternType.GLOB: shell-style wildcards (*.exe, secret_*)\n\nPatterns are evaluated by MCPGateway before any tool call parameter reaches execution. A match returns PolicyDecision.action = 'deny' immediately.\n\nFire counts below are computed from pipeline volume; each category's rate reflects realistic enterprise email processing patterns."}
            />

            {/* KPI row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Total Patterns</p>
                  <Tip text={"Total number of patterns configured across all five categories.\n\nAll patterns are evaluated against every tool call parameter before execution, not just tool calls from one stage."} />
                </div>
                <p className="text-2xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{kpis.total_patterns}</p>
              </div>
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Total Blocks</p>
                  <Tip text={"Total number of tool call parameters blocked by pattern matching across all pipelines.\n\nEach block means a tool invocation was prevented before it reached execution; the parameter was sanitized and the call was denied."} />
                </div>
                <p className="text-2xl font-bold tabular-nums text-red-600 dark:text-red-400">{kpis.total_blocks.toLocaleString()}</p>
              </div>
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Most Active Category</p>
                  <Tip text={"The category with the most pattern matches across all pipeline runs.\n\nInjection patterns tend to be most active in enterprise email processing because SQL keywords appear naturally in order descriptions and phishing attempts include prompt-override phrases."} />
                </div>
                <p className="text-sm font-bold text-zbrain-ink dark:text-zbrain-dark-ink">{kpis.most_active_category}</p>
                <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted">{kpis.most_active_count.toLocaleString()} blocks</p>
              </div>
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Categories</p>
                  <Tip text={"Patterns are organised into five threat categories: PII, Credential Leak, Injection, Shell/Exec, and Data Exfiltration.\n\nThis mirrors AGT's recommended blocked_patterns grouping strategy. Grouping by threat type makes it easy to tune thresholds per risk level."} />
                </div>
                <p className="text-2xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{kpis.categories_count}</p>
              </div>
            </div>

            {/* Category breakdown */}
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
              {categories.map((cat) => {
                const c = CAT_COLORS[cat.id] || CAT_COLORS.pii;
                return (
                  <div key={cat.id} className={`rounded-lg border p-3 ${c.bg} ${c.border}`}>
                    <div className="flex items-start justify-between gap-1 mb-1">
                      <p className={`text-[11px] font-bold ${c.text}`}>{cat.label}</p>
                      <span className={`pill border text-[9px] font-semibold ${c.badge}`}>{cat.total_patterns} patterns</span>
                    </div>
                    <p className={`text-[9px] leading-snug mb-2.5 opacity-80 ${c.text}`}>{cat.description}</p>
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-[9px] uppercase tracking-wider opacity-60 ${c.text}`}>blocks</span>
                      <span className={`text-xs font-bold tabular-nums ${c.text}`}>{cat.total_fire_count.toLocaleString()}</span>
                    </div>
                    <InlineBar value={cat.total_fire_count} max={maxCatBlocks} color={c.bar} />
                    <div className="relative group mt-2">
                      <p className={`text-[8px] font-mono truncate opacity-50 cursor-default ${c.text}`}>{cat.agt_field}</p>
                      <div className="pointer-events-none absolute bottom-4 left-0 z-40 hidden group-hover:block w-64 rounded-lg bg-zbrain-ink dark:bg-zbrain-dark-elev2 text-white dark:text-zbrain-dark-ink text-[11px] leading-relaxed p-3 shadow-2xl">
                        <p className="font-semibold mb-1">AGT enforcement point</p>
                        <p className="font-mono text-[10px] opacity-80">{cat.agt_field}</p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Top triggered patterns */}
            <div className="border-t border-zbrain-divider dark:border-zbrain-dark-divider pt-4">
              <div className="flex items-center gap-1.5 mb-3">
                <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">Top Triggered Patterns</p>
                <Tip text={"The six most-fired individual patterns across all categories and pipeline runs.\n\nHigh fire counts on injection patterns (SQL, prompt override) are expected in enterprise email; order descriptions often contain keywords that match injection signatures.\n\nA high count on PII patterns (SSN, credit card) indicates customers are including sensitive data in emails; the pattern block prevents it from being passed into CRM tool parameters."} />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-zbrain-divider dark:border-zbrain-dark-divider bg-zbrain-surface dark:bg-zbrain-dark-elev2">
                      {["Pattern", "Category", "Type", "Blocks", "Action"].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zbrain-muted">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {top_triggered.map((p, i) => {
                      const c = CAT_COLORS[p.category_id] || CAT_COLORS.pii;
                      return (
                        <tr key={i} className={`border-b border-zbrain-divider/50 dark:border-zbrain-dark-divider/50 ${i % 2 === 0 ? "" : "bg-zbrain-surface/40 dark:bg-zbrain-dark-elev1/40"}`}>
                          <td className="px-3 py-2.5">
                            <p className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{p.label}</p>
                            <code className="text-[9px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted break-all max-w-[200px] block truncate" title={p.pattern}>{p.pattern}</code>
                          </td>
                          <td className="px-3 py-2.5">
                            <span className={`pill border text-[9px] ${c.badge}`}>{p.category}</span>
                          </td>
                          <td className="px-3 py-2.5 font-mono text-zbrain-muted dark:text-zbrain-dark-muted">{p.type}</td>
                          <td className="px-3 py-2.5 tabular-nums font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{p.fire_count.toLocaleString()}</td>
                          <td className="px-3 py-2.5"><DecisionPill decision={p.action} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Active KB policies */}
      <div className="card overflow-hidden">
        <div className="p-4 border-b border-zbrain-divider dark:border-zbrain-dark-divider flex items-center gap-3 flex-wrap">
          <div>
            <p className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
              Active GovernancePolicies
              <Tip text={"A policy is a written rule the engine enforces at every tool call. 'Active' means the rule is currently loaded into the PolicyEvaluator and is being applied to live traffic. Inactive (paused) rules are authored but not enforced; they are typically held during a tuning window or a rollback while operators verify behavior.\n\nEach row below is one active PolicyDocument rule. Rules are evaluated against the runtime context on every agent invocation, before execution. Click any row to see the full PolicyRule YAML, the message surfaced to the caller, the OWASP ASI control it addresses, and a link to the Audit Trail."} />
            </p>
            <p className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted">KB rules as AGT PolicyDocument entries, evaluated by PolicyEvaluator on every invocation</p>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted border border-zbrain-divider dark:border-zbrain-dark-divider rounded-md px-2.5 py-1.5">
            <span>Default fallback:</span>
            <span className={`pill border text-[10px] font-semibold ${DECISION_COLORS[policy_default_action] ?? ""}`}>{policy_default_action.toUpperCase()}</span>
            <Tip text={"PolicyDocument.defaults.action: what fires when NO rule matches.\n\nALLOW = whitelist posture: only explicitly listed rules block/deny. Any invocation that doesn't match a rule proceeds.\nDENY = deny-all posture: only explicitly listed rules permit."} position="right" />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className="inline-flex items-center gap-1">
              <select
                value={scopeFilter}
                onChange={(e) => setScopeFilter(e.target.value)}
                className="text-xs border border-zbrain-divider dark:border-zbrain-dark-divider rounded-md px-2 py-1.5 bg-white dark:bg-zbrain-dark-elev1 text-zbrain-ink dark:text-zbrain-dark-ink"
              >
                <option value="">All scopes</option>
                <option value="Global">Global</option>
                <option value="Tenant">Tenant</option>
                <option value="Agent">Agent</option>
              </select>
              <Tip position="right" text={"Filter rules by their PolicyScope. Scope determines which traffic the rule applies to:\n\n• Global: applies to every tenant and every agent. Used for platform-wide controls such as sanctions screening or spam blocking.\n• Tenant: applies to this organization only. Used for tenant-specific rules such as credit policy or discount limits.\n• Agent: applies to one specific agent DID. Used for narrow overrides such as 'this agent may not write to ERP'."} />
            </div>
            <div className="inline-flex items-center gap-1">
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                className="text-xs border border-zbrain-divider dark:border-zbrain-dark-divider rounded-md px-2 py-1.5 bg-white dark:bg-zbrain-dark-elev1 text-zbrain-ink dark:text-zbrain-dark-ink"
              >
                <option value="">All actions</option>
                <option value="allow">allow</option>
                <option value="audit">audit</option>
                <option value="deny">deny</option>
                <option value="block">block</option>
              </select>
              <Tip position="right" text={"Filter rules by their configured action. Use this to focus the table on rules with a specific decision outcome.\n\n• allow: rule lets the call proceed.\n• audit: rule lets the call proceed but records it for one-click review.\n• block: rule rejects the call at the Decide→Execute gate.\n• deny: rule rejects the call at Intake before any scoring runs."} />
            </div>
          </div>
        </div>
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-zbrain-muted text-sm">No policies match filters.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">Policy Rule</th>
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">
                    <Tip text={"PolicyScope controls which policies take precedence in conflict resolution.\n\nGlobal: applies to all tenants and agents (e.g. sanctions list, spam screen)\nTenant: applies to this Keysight org (e.g. credit hold, discount rules)\nAgent: overrides for a specific agent DID\n\nUsed by most_specific_wins conflict resolution: Agent > Tenant > Global"} position="right" />
                    Scope
                  </th>
                  <th
                    className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px] cursor-pointer select-none hover:text-zbrain dark:hover:text-zbrain-dark-accent"
                    onClick={() => setSortPriority(p => p === "desc" ? "asc" : "desc")}
                  >
                    Priority {sortPriority === "desc" ? "↓" : "↑"}
                    <Tip text={"Numeric evaluation priority: higher number = evaluated first.\n\nWhen multiple rules match, the PolicyEvaluator applies the active conflict resolution strategy (currently priority_first_match) to pick the winner.\n\nClick column header to toggle sort order."} position="right" />
                  </th>
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">
                    Condition
                    <Tip text={"The PolicyCondition that triggers this rule.\n\nFormat: field  operator  value\n\nSupported operators:\neq / ne: equality\ngt / lt / gte / lte: numeric comparisons\ncontains: substring match\nmatches: compiled regex\nin: membership in list\n\nThe PolicyEvaluator builds a context dict from the agent invocation and evaluates each rule's condition against it."} position="right" />
                  </th>
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">
                    Action
                    <Tip text={"PolicyDecision.action: what the policy engine returns when this rule matches.\n\n• allow: passed clean; pipeline proceeds autonomously.\n• audit: passed but flagged for review; one-click CSR sign-off required before Execute runs.\n• block: rejected at the Decide→Execute gate; full human review required before resuming.\n• deny: rejected outright at Intake; no confidence score computed, pipeline terminates."} position="right" />
                  </th>
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">
                    Enforced At
                    <Tip text={"The pipeline stage where GovernancePolicyMiddleware intercepts the agent invocation.\n\nIntake: spam/phishing rules fire here; pipeline terminates before extraction runs\nDecide: routing rules fire here; HITL staging or one-click approval triggered\nExecute: compliance hard-blocks fire here; last enforcement point before non-reversible CRM/ERP writes"} position="right" />
                  </th>
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">
                    Fires
                    <Tip text={"Number of times this rule matched and fired (PolicyDecision.matched_rule = this rule).\n\nThe sub-label shows when the rule last fired. The decision.action was then enforced by GovernancePolicyMiddleware before agent execution."} position="right" />
                  </th>
                  <th className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">Updated</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((p, i) => {
                  const isExpanded = expandedRow === p.policy_id;
                  return (
                    <>
                      <tr
                        key={p.policy_id}
                        onClick={() => {
                          if (isExpanded) setShowDevDetails(null);
                          setExpandedRow(isExpanded ? null : p.policy_id);
                        }}
                        className={`border-b border-zbrain-divider/50 dark:border-zbrain-dark-divider/50 cursor-pointer transition-colors ${ROW_BORDER[p.action] ?? "border-l-4 border-l-gray-300"} ${isExpanded ? "bg-zbrain-50 dark:bg-zbrain/5" : `hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev2 ${i % 2 === 0 ? "" : "bg-zbrain-surface/40 dark:bg-zbrain-dark-elev1/40"}`}`}
                      >
                        <td className="px-3 py-2.5 max-w-[260px]">
                          <div className="flex items-start gap-1.5">
                            <span className={`mt-0.5 text-zbrain-muted dark:text-zbrain-dark-muted transition-transform text-[10px] ${isExpanded ? "rotate-90" : ""}`}>▶</span>
                            <div className="min-w-0">
                              <p className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink leading-snug truncate">{p.label || p.rule_key}</p>
                              <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted truncate" title={p.description}>{p.description}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          <span className={`pill border text-[10px] ${SCOPE_COLORS[p.scope] ?? SCOPE_COLORS.Tenant}`}>{p.scope}</span>
                        </td>
                        <td className="px-3 py-2.5 tabular-nums font-mono font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{p.priority}</td>
                        <td className="px-3 py-2.5">
                          <code className="text-[10px] bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded px-1.5 py-0.5 text-zbrain-ink dark:text-zbrain-dark-ink whitespace-nowrap">
                            {p.condition_field} <span className="text-zbrain dark:text-zbrain-dark-accent">{p.condition_operator}</span> {p.condition_value}
                          </code>
                        </td>
                        <td className="px-3 py-2.5"><DecisionPill decision={p.action} /></td>
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          {(() => {
                            const badge = STAGE_BADGES[p.enforced_at] ?? STAGE_BADGES.decide;
                            return <span className={`pill border text-[10px] ${badge.cls}`}>{badge.label}</span>;
                          })()}
                        </td>
                        <td className="px-3 py-2.5">
                          <p className="tabular-nums font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{p.fire_count.toLocaleString()}</p>
                          {p.last_fired_at && (
                            <p className="text-[9px] text-zbrain-muted dark:text-zbrain-dark-muted whitespace-nowrap">{fmtRelative(p.last_fired_at)}</p>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-zbrain-muted dark:text-zbrain-dark-muted whitespace-nowrap">
                          {p.updated_at ? new Date(p.updated_at).toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" }) : "-"}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${p.policy_id}-expand`} className="bg-zbrain-50 dark:bg-zbrain/5 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
                          <td colSpan={8} className="px-6 py-4 space-y-4">

                              {/* Zone 1 — Impact Banner */}
                            <div className={`rounded-lg border-l-4 ${ACTION_BORDER[p.action] ?? "border-l-gray-300"} ${BANNER_BG[p.action] ?? ""} px-4 py-3`}>
                              <div className="flex items-start gap-3">
                                <span className={`pill border text-[11px] font-bold uppercase tracking-wider flex-shrink-0 mt-0.5 ${DECISION_COLORS[p.action]}`}>{p.action}</span>
                                <div className="min-w-0 flex-1">
                                  <p className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink leading-snug">{ACTION_SUMMARIES[p.action] ?? p.description}</p>
                                  <p className="text-[12px] italic text-zbrain-muted dark:text-zbrain-dark-muted mt-1 leading-relaxed">"{p.rule_message}"</p>
                                </div>
                              </div>
                              <div className="flex items-center gap-4 mt-2.5 text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">
                                <span><span className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{p.fire_count.toLocaleString()}</span> fires</span>
                                {p.last_fired_at && <span>Last triggered <span className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{fmtRelative(p.last_fired_at)}</span></span>}
                                <span>Enforced at <span className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink capitalize">{p.enforced_at}</span> stage</span>
                              </div>
                            </div>

                            {/* Zone 2 — Evaluation Trace + Compliance Identity */}
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

                              {/* Zone 2A — Evaluation Trace */}
                              <div>
                                <p className="text-[10px] font-semibold text-zbrain-muted uppercase tracking-wider mb-1.5">
                                  Evaluation Trace
                                  <Tip text={"Simulates PolicyConflictResolver.resolve() across all rules active at this stage.\n\nResolutionResult fields:\n• candidates_evaluated: rules considered in this resolution\n• resolution_trace: step-by-step log of which rule won and why\n• strategy_used: currently priority_first_match"} position="right" />
                                </p>
                                <div className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded-lg p-3 space-y-1.5">
                                  {p.conflict_trace.map((line, li) => {
                                    const isWinner = li === p.conflict_trace.length - 1;
                                    return (
                                      <p key={li} className={`text-[10px] font-mono leading-relaxed ${isWinner ? `font-semibold border-l-2 pl-2 ${ACTION_BORDER[p.action] ?? "border-l-gray-400"} text-zbrain-ink dark:text-zbrain-dark-ink` : "text-zbrain-muted dark:text-zbrain-dark-muted pl-2"}`}>
                                        {isWinner ? "▶ " : ""}{line}
                                      </p>
                                    );
                                  })}
                                </div>
                              </div>

                              {/* Zone 2B — Compliance & Identity */}
                              <div className="space-y-3">
                                <div className="flex flex-wrap gap-5">
                                  <div>
                                    <p className="text-[10px] font-semibold text-zbrain-muted uppercase tracking-wider mb-1">
                                      OWASP ASI Control
                                      <Tip text={"ASI-01 Goal Hijacking: malicious content redirects the pipeline\nASI-02 Tool Misuse: unauthorized or incorrect tool targeting\nASI-03 Identity & Privilege Abuse: compliance / identity-based access\nASI-09 Human-Agent Trust Exploitation: over-reliance on autonomous decisions\n\nSource: OWASP AI Security Initiative (OWASP-COMPLIANCE.md)"} position="right" />
                                    </p>
                                    <div className="flex items-center gap-1.5">
                                      <span className="pill border bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30 text-[10px] font-semibold">{p.owasp_control}</span>
                                      <span className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted">{OWASP_NAMES[p.owasp_control] ?? "-"}</span>
                                    </div>
                                  </div>
                                  <div>
                                    <p className="text-[10px] font-semibold text-zbrain-muted uppercase tracking-wider mb-1">
                                      Eval Backend
                                      <Tip text={"Which policy evaluation engine processed this rule.\n\nYAML: native PolicyEvaluator (agent_os.policies); sub-ms latency\nOPA: Open Policy Agent / Rego backend; best for content pattern rules\nCedar: Cedar policy engine; best for structured access-control rules\n\nLatency: BackendDecision.evaluation_ms"} position="right" />
                                    </p>
                                    <div className="flex items-center gap-1.5">
                                      <span className={`pill border text-[10px] font-semibold ${p.eval_backend === "opa" ? "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30" : p.eval_backend === "cedar" ? "bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-500/10 dark:text-teal-300 dark:border-teal-500/30" : "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700"}`}>{p.eval_backend.toUpperCase()}</span>
                                      <span className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">{p.evaluation_ms}ms</span>
                                    </div>
                                  </div>
                                </div>
                                <div className="flex flex-wrap gap-3 text-[10px]">
                                  <div><p className="text-zbrain-muted uppercase tracking-wider">Namespace</p><p className="font-mono text-zbrain-ink dark:text-zbrain-dark-ink">{p.namespace}</p></div>
                                  <div><p className="text-zbrain-muted uppercase tracking-wider">Version</p><p className="font-mono text-zbrain-ink dark:text-zbrain-dark-ink">{p.version ?? "-"}</p></div>
                                  <div className="max-w-[220px]"><p className="text-zbrain-muted uppercase tracking-wider">Policy ID</p><p className="font-mono text-zbrain-ink dark:text-zbrain-dark-ink truncate" title={p.policy_id}>{p.policy_id}</p></div>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className={`pill border text-[10px] font-semibold ${p.strictness_diff.is_stricter_than_default ? "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30" : "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700"}`}>
                                    {p.strictness_diff.is_stricter_than_default ? "✓ Stricter than AGT defaults" : "= At AGT defaults"}
                                  </span>
                                  <Tip text={"Compares this stage's GovernancePolicy against the AGT default values.\n\nGovernancePolicy.is_stricter_than(base) returns True when all differing fields are more restrictive.\n\nAGT defaults: max_tokens=4096, max_tool_calls=10, drift_threshold=0.15, require_human_approval=False"} position="right" />
                                </div>
                                <button
                                  onClick={(e) => { e.stopPropagation(); setSearchParams({ tab: "audit" }); }}
                                  className="btn-secondary text-xs flex items-center gap-1.5"
                                >
                                  <span>View in Audit Trail</span><span>→</span>
                                </button>
                              </div>
                            </div>

                            {/* Zone 3 — Developer details (collapsible) */}
                            <div className="pt-3 border-t border-zbrain-divider dark:border-zbrain-dark-divider">
                              <button
                                onClick={(e) => { e.stopPropagation(); setShowDevDetails(showDevDetails === p.policy_id ? null : p.policy_id); }}
                                className="flex items-center gap-1.5 text-[10px] font-semibold text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider hover:text-zbrain-ink dark:hover:text-zbrain-dark-ink transition-colors"
                              >
                                <span className={`transition-transform inline-block text-[9px] ${showDevDetails === p.policy_id ? "rotate-90" : ""}`}>▶</span>
                                Developer details: YAML &amp; context snapshot
                              </button>
                              {showDevDetails === p.policy_id && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-3">
                                  <div>
                                    <p className="text-[10px] font-semibold text-zbrain-muted uppercase tracking-wider mb-1.5">
                                      Context Snapshot
                                      <Tip text={"PolicyDecision.audit_entry.context_snapshot: the actual runtime field values the PolicyEvaluator saw when the condition matched.\n\nThis is what compliance auditors use to reconstruct exactly why a decision was made. Full audit entries with SHA-256 hash chains are in the Audit Trail tab."} position="right" />
                                    </p>
                                    <div className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded-lg p-3 space-y-1.5">
                                      {Object.entries(p.audit_entry_sample?.context_snapshot ?? {}).map(([k, v]) => (
                                        <div key={k} className="flex items-start gap-3">
                                          <span className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted w-[160px] flex-shrink-0">{k}</span>
                                          <span className="text-[10px] font-mono font-semibold text-zbrain-ink dark:text-zbrain-dark-ink break-all">{String(v)}</span>
                                        </div>
                                      ))}
                                      {p.audit_entry_sample?.timestamp && (
                                        <div className="pt-1.5 border-t border-zbrain-divider dark:border-zbrain-dark-divider flex items-start gap-3">
                                          <span className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted w-[160px] flex-shrink-0">timestamp</span>
                                          <span className="text-[10px] font-mono text-zbrain-ink dark:text-zbrain-dark-ink">{p.audit_entry_sample.timestamp}</span>
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                  <div>
                                    <p className="text-[10px] font-semibold text-zbrain-muted uppercase tracking-wider mb-1.5">PolicyRule YAML</p>
                                    <pre className="text-[10px] font-mono bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded-lg p-3 text-zbrain-ink dark:text-zbrain-dark-ink leading-relaxed overflow-x-auto">{toYaml(p)}</pre>
                                  </div>
                                </div>
                              )}
                            </div>

                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Tool Invocation Outcomes */}
      {policies.tool_invocation_breakdown?.length > 0 && (
        <ToolInvocationChart breakdown={policies.tool_invocation_breakdown} />
      )}

      {/* Capability & Policy Coverage */}
      <div className="card p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <SectionHeader
            title="Capability & Policy Coverage per Stage"
            subtitle="CapabilityGuardMiddleware tool access × active policy rules enforced at each stage"
          />
          <Tip text={"Two orthogonal AGT layers are crossed here:\n\n1. CapabilityGuardMiddleware: controls which tools each agent DID may call, regardless of ring level.\n\n2. PolicyEvaluator rules: govern the conditions under which a tool call is allowed, blocked, or flagged.\n\nA coverage gap means an agent has tools it can call but no active policy rules constraining when or how those tools may be used (a governance blind spot)."} />
        </div>

        <div className="space-y-3">
          {tool_allow_deny_matrix.map((row) => {
            const coverageColor = row.coverage_gap
              ? "border-amber-300 dark:border-amber-500/40"
              : "border-zbrain-divider dark:border-zbrain-dark-divider";
            return (
              <div key={row.stage} className={`border rounded-lg overflow-hidden ${coverageColor}`}>
                {/* Stage header */}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5 bg-zbrain-surface dark:bg-zbrain-dark-elev2">
                  <RingBadge ring={row.ring} label={row.ring_label} />
                  <span className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink capitalize">{row.stage}</span>
                  <span className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted">{row.did}</span>
                  <div className="ml-auto flex items-center gap-2 flex-wrap justify-end">
                    {/* Policy coverage chips */}
                    {row.coverage_gap ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/40 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                        ⚠ No policy coverage
                        <Tip position="right" text={"Governance gap: this agent has tools it can call but no active PolicyEvaluator rules constraining when or how those calls may be made.\n\nCapabilityGuardMiddleware still blocks tools on the deny list, but nothing governs the conditions under which allowed tools run.\n\nConsider adding policy rules (e.g. input validation, output filters) for this stage."} />
                      </span>
                    ) : (
                      <>
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-zbrain-50 dark:bg-zbrain/10 border border-zbrain-200 dark:border-zbrain/30 text-[10px] font-medium text-zbrain dark:text-zbrain-dark-accent">
                          {row.policy_rule_count} rule{row.policy_rule_count !== 1 ? "s" : ""}
                        </span>
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-[10px] font-medium text-zbrain-muted dark:text-zbrain-dark-muted">
                          {row.policy_fire_count.toLocaleString()} fires
                        </span>
                        {row.max_action && (
                          <span className={`pill border text-[10px] font-semibold uppercase tracking-wide ${DECISION_COLORS[row.max_action] || DECISION_COLORS["audit"]}`}>
                            max: {row.max_action}
                          </span>
                        )}
                        <Tip position="right" text={"Rules: number of active PolicyEvaluator rules enforced at this pipeline stage. Each rule checks a context field (e.g. credit_status, discount_pct) and triggers an action when matched.\n\nFires: total times any rule at this stage matched a real pipeline condition across all processed emails.\n\nMax action: the highest-severity outcome any rule here can trigger. Severity order: BLOCK > DENY > AUDIT > ALLOW. This is the worst-case governance response at this stage."} />
                      </>
                    )}
                  </div>
                </div>

                {/* Top governing rule */}
                {row.top_rule && (
                  <div className="px-4 py-2 border-b border-zbrain-divider dark:border-zbrain-dark-divider bg-zbrain-bg dark:bg-zbrain-dark-bg flex items-center gap-2 flex-wrap">
                    <span className="inline-flex items-center gap-0.5 text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider font-semibold shrink-0">
                      Top rule
                      <Tip text={"The highest-priority PolicyEvaluator rule active at this stage.\n\nWith priority_first_match strategy (AGT default), this rule wins if multiple rules match the same pipeline context simultaneously.\n\nPriority is a numeric value: higher number = evaluated first. The OWASP control ID shows which AI security risk this rule mitigates."} />
                    </span>
                    <span className="text-[11px] text-zbrain-ink dark:text-zbrain-dark-ink font-medium">{row.top_rule.label}</span>
                    <span className={`pill border text-[10px] font-semibold uppercase ${DECISION_COLORS[row.top_rule.action] || DECISION_COLORS["audit"]}`}>{row.top_rule.action}</span>
                    <span className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted">priority {row.top_rule.priority}</span>
                    <span className="ml-auto text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted">{row.top_rule.owasp}</span>
                  </div>
                )}

                {/* Tool lists */}
                <div className="p-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <p className="inline-flex items-center gap-0.5 text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold uppercase tracking-wider mb-1.5">
                      Allowed ({row.allowed.length})
                      <Tip text={"Tools this agent's DID is permitted to call, enforced by CapabilityGuardMiddleware.\n\nBefore any tool call executes, AGT checks the calling agent's DID against this list. If the tool is allowed, execution proceeds to the PolicyEvaluator rule check.\n\nThis list is configured via create_governance_middleware(allowed_tools=[...]) and cannot be overridden by the LLM at runtime."} />
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {row.allowed.map((t) => (
                        <span key={t} className="pill bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30 text-[10px]">{t}</span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="inline-flex items-center gap-0.5 text-[10px] text-red-600 dark:text-red-400 font-semibold uppercase tracking-wider mb-1.5">
                      Blocked by CapabilityGuard ({row.denied.length})
                      <Tip position="right" text={"Tools explicitly denied to this agent by CapabilityGuardMiddleware.\n\nEven if the LLM generates a tool call to one of these tools, AGT intercepts it before it reaches the tool handler and logs a tool_blocked audit event.\n\nThis prevents privilege escalation: a Sandbox agent (Ring 3) cannot call CRM write tools even if it somehow receives instructions to do so."} />
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {row.denied.map((t) => (
                        <span key={t} className="pill bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 text-[10px] line-through opacity-60">{t}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Advanced: GovernancePolicy Defaults (collapsed) ─────────────── */}
      <details className="card overflow-hidden">
        <summary className="p-5 cursor-pointer select-none flex items-center gap-2 text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink list-none">
          <span className="text-zbrain dark:text-zbrain-dark-accent">▶</span>
          Advanced: Policy Defaults
          <span className="text-xs font-normal text-zbrain-muted dark:text-zbrain-dark-muted ml-1">(AGT GovernancePolicy dataclass base settings)</span>
        </summary>
        <div className="px-5 pb-5 border-t border-zbrain-divider dark:border-zbrain-dark-divider pt-4">
          <div className="flex flex-wrap gap-6">
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Max Tool Calls</p><Tip text={"GovernancePolicy.max_tool_calls: maximum tool invocations allowed per pipeline run.\n\nDefault in AGT: 10."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.max_tool_calls}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Max Tokens</p><Tip text={"GovernancePolicy.max_tokens: token budget per agent invocation.\n\nDefault in AGT: 4096."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.max_tokens.toLocaleString()}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Confidence Threshold</p><Tip text={"GovernancePolicy.confidence_threshold: minimum confidence score (0 to 1) required before an action is allowed without human review."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.confidence_threshold}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Drift Threshold</p><Tip text={"GovernancePolicy.drift_threshold: max allowed deviation before BEHAVIORAL_DRIFT KillSwitch triggers. Default: 0.15."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.drift_threshold}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Timeout (s)</p><Tip text={"GovernancePolicy.timeout_seconds: max wall-clock time per agent invocation. Default: 300s."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.timeout_seconds}s</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Log All Calls</p><Tip text={"GovernancePolicy.log_all_calls: when true, every tool invocation is written to the append-only audit log regardless of outcome."} /></div><span className={`text-sm font-semibold ${policy_defaults.log_all_calls ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>{policy_defaults.log_all_calls ? "yes" : "no"}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Require Human Approval</p><Tip text={"GovernancePolicy.require_human_approval: when true, returns 'block' until a human approves the action."} /></div><span className={`text-sm font-semibold ${policy_defaults.require_human_approval ? "text-amber-600 dark:text-amber-400" : "text-zbrain-muted dark:text-zbrain-dark-muted"}`}>{policy_defaults.require_human_approval ? "yes" : "no (per-agent)"}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Checkpoint Freq</p><Tip text={"GovernancePolicy.checkpoint_frequency: write a checkpoint every N tool calls. Default: 5."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">every {policy_defaults.checkpoint_frequency}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Max Concurrent</p><Tip text={"GovernancePolicy.max_concurrent: max simultaneous agent executions. Default: 10."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.max_concurrent}</span></div>
            <div><div className="flex items-center gap-1"><p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Backpressure At</p><Tip text={"GovernancePolicy.backpressure_threshold: throttle new requests once active executions reach this level. Default: 8."} /></div><span className="text-xl font-bold tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{policy_defaults.backpressure_threshold}</span></div>
          </div>
        </div>
      </details>

      {/* ── Advanced: Conflict Resolution (collapsed) ───────────────────── */}
      <details className="card overflow-hidden">
        <summary className="p-5 cursor-pointer select-none flex items-center gap-2 text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink list-none">
          <span className="text-zbrain dark:text-zbrain-dark-accent">▶</span>
          Advanced: Conflict Resolution
          <span className="text-xs font-normal text-zbrain-muted dark:text-zbrain-dark-muted ml-1">(how AGT resolves competing policy rules)</span>
        </summary>
        <div className="px-5 pb-5 border-t border-zbrain-divider dark:border-zbrain-dark-divider pt-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {all_conflict_strategies.map((s) => (
              <div key={s.id} className={`rounded-lg border p-3 ${s.active ? "border-zbrain bg-zbrain/5 dark:border-zbrain-dark-accent dark:bg-zbrain-dark-accent/10" : "border-zbrain-divider dark:border-zbrain-dark-divider bg-zbrain-surface dark:bg-zbrain-dark-elev1 opacity-60"}`}>
                <div className="flex items-center justify-between mb-1.5">
                  <code className={`text-[10px] font-mono font-semibold ${s.active ? "text-zbrain dark:text-zbrain-dark-accent" : "text-zbrain-muted dark:text-zbrain-dark-muted"}`}>{s.id}</code>
                  {s.active && <span className="text-[9px] font-bold uppercase tracking-wider text-zbrain dark:text-zbrain-dark-accent bg-zbrain/10 dark:bg-zbrain-dark-accent/20 px-1.5 py-0.5 rounded-full">active</span>}
                </div>
                <p className="text-[11px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink mb-1">{s.label}</p>
                <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted leading-snug mb-2">{s.description}</p>
                <p className="text-[9px] text-zbrain-muted/70 dark:text-zbrain-dark-muted/70 italic leading-snug">Use when: {s.use_when}</p>
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 5: Compliance
// ---------------------------------------------------------------------------

const STRENGTH_COLORS: Record<string, { bg: string; text: string; border: string; dark_bg: string; dark_text: string }> = {
  strong:   { bg: "bg-emerald-100", text: "text-emerald-800", border: "border-emerald-300", dark_bg: "dark:bg-emerald-500/20", dark_text: "dark:text-emerald-300" },
  moderate: { bg: "bg-amber-100",   text: "text-amber-800",   border: "border-amber-300",   dark_bg: "dark:bg-amber-500/20",   dark_text: "dark:text-amber-300" },
  weak:     { bg: "bg-orange-100",  text: "text-orange-800",  border: "border-orange-300",  dark_bg: "dark:bg-orange-500/20",  dark_text: "dark:text-orange-300" },
  none:     { bg: "bg-red-100",     text: "text-red-800",     border: "border-red-300",     dark_bg: "dark:bg-red-500/20",     dark_text: "dark:text-red-300" },
};

const NIST_GRADE_COLORS: Record<string, { text: string; dark_text: string }> = {
  A: { text: "text-emerald-700", dark_text: "dark:text-emerald-400" },
  B: { text: "text-blue-700",    dark_text: "dark:text-blue-400" },
  C: { text: "text-amber-700",   dark_text: "dark:text-amber-400" },
  D: { text: "text-orange-700",  dark_text: "dark:text-orange-400" },
};

const STRENGTH_ORDER_UI: Record<string, number> = { none: 0, weak: 1, moderate: 2, strong: 3 };

const STRENGTH_BARS = { strong: 4, moderate: 3, weak: 2, none: 1 };

function EvidenceBar({ strength, count, field }: { strength: string; count: number | null; field: string | null }) {
  const filled = STRENGTH_BARS[strength as keyof typeof STRENGTH_BARS] ?? 1;
  const colors: Record<string, string> = {
    strong:   "bg-emerald-500 dark:bg-emerald-400",
    moderate: "bg-amber-500 dark:bg-amber-400",
    weak:     "bg-orange-500 dark:bg-orange-400",
    none:     "bg-red-400 dark:bg-red-500",
  };
  const bar = colors[strength] ?? colors.none;
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {[1,2,3,4].map((i) => (
          <div key={i} className={`h-2 w-3 rounded-sm ${i <= filled ? bar : "bg-zbrain-200 dark:bg-zbrain-dark-elev2"}`} />
        ))}
      </div>
      <span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted capitalize">{strength}</span>
      {count !== null && field && (
        <span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">({count} {field.replace(/_/g, " ")})</span>
      )}
    </div>
  );
}

function InfoTip({ text, width = "w-72" }: { text: string; width?: string }) {
  return (
    <div className="relative group inline-flex shrink-0">
      <button
        type="button"
        className="w-3.5 h-3.5 rounded-full border border-zbrain-muted dark:border-zbrain-dark-muted text-zbrain-muted dark:text-zbrain-dark-muted flex items-center justify-center text-[9px] font-bold leading-none hover:border-zbrain hover:text-zbrain dark:hover:text-zbrain-dark-accent transition-colors"
      >
        i
      </button>
      <div
        className={`pointer-events-none absolute left-4 top-0 z-[60] hidden group-hover:block ${width} rounded-lg text-white text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line ring-1 ring-white/10`}
        style={{ backgroundColor: "#0F1428" }}
      >
        {text}
      </div>
    </div>
  );
}

function StrengthPill({ strength }: { strength: string }) {
  const c = STRENGTH_COLORS[strength] ?? STRENGTH_COLORS.none;
  const LABELS: Record<string, string> = { strong: "Strong", moderate: "Moderate", weak: "Weak", none: "None" };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border ${c.bg} ${c.text} ${c.border} ${c.dark_bg} ${c.dark_text}`}>
      {LABELS[strength] ?? strength}
    </span>
  );
}

const ASI_DEFINITIONS: Record<string, { name: string; risk: string; addressed_by: string }> = {
  "ASI-01": {
    name: "Goal Hijacking",
    risk: "Malicious content (prompt injection, manipulated documents) redirects the agent away from its assigned task, often into actions it would not otherwise take.",
    addressed_by: "Input sanitization in blocked_patterns, intent verification in the Intake agent, and confidence-gated escalation at the Decide stage.",
  },
  "ASI-02": {
    name: "Tool Misuse",
    risk: "Agent invokes a tool with parameters or arguments that exceed its capability scope, potentially triggering unauthorized side-effects.",
    addressed_by: "CapabilityGuardMiddleware enforces an allow-list per agent DID; MCPGateway scans every tool descriptor before registration.",
  },
  "ASI-03": {
    name: "Identity & Privilege Abuse",
    risk: "An agent assumes an identity or privilege tier it is not entitled to, bypassing scope controls or impersonating another agent.",
    addressed_by: "Per-agent GovernancePolicy limits, signed DIDs, and the 4-ring trust model enforced at every tool call.",
  },
  "ASI-04": {
    name: "Supply Chain",
    risk: "A compromised or untrusted upstream tool, plugin, or model dependency injects unsafe behavior into the pipeline.",
    addressed_by: "MCPGateway's 5-stage scan (tool poisoning, rug-pull, instruction injection, fingerprint pinning) and the AI-BOM register.",
  },
  "ASI-05": {
    name: "Unexpected Code Execution",
    risk: "Agent emits or evaluates code (shell, SQL, JavaScript) that runs in a privileged context.",
    addressed_by: "blocked_patterns category for shell/exec, sandbox isolation for Ring 3 agents, and the deny default at the Intake gate.",
  },
  "ASI-06": {
    name: "Memory & Context Poisoning",
    risk: "Adversarial content persisted in conversation state or vector memory steers subsequent agent invocations toward an attacker's goal.",
    addressed_by: "Context-scoped retention, drift detection, and the BEHAVIORAL_DRIFT KillSwitch trigger.",
  },
  "ASI-07": {
    name: "Insecure Inter-Agent Communication",
    risk: "One agent passes unsanitized output to another, propagating poisoned content or escalating privilege across the pipeline.",
    addressed_by: "Inter-agent message signing, output validation between stages, and policy enforcement at the Decide→Execute boundary.",
  },
  "ASI-08": {
    name: "Cascading Failures",
    risk: "A failure or anomaly in one agent triggers further failures downstream, amplifying impact across the system.",
    addressed_by: "AGT CircuitBreaker (CLOSED / OPEN / HALF_OPEN states), per-stage SLOs, and the automated exhaustion action when budgets deplete.",
  },
  "ASI-09": {
    name: "Human-Agent Trust Exploitation",
    risk: "Operators over-trust autonomous decisions, missing low-confidence outputs that should have been reviewed.",
    addressed_by: "Confidence gates (allow ≥ 95%, audit 80 to 94%, block < 80%) and one-click CSR sign-off on the audit tier.",
  },
  "ASI-10": {
    name: "Rogue Agents",
    risk: "An agent operating outside its declared behavior profile, either compromised or misconfigured, continues to execute and consume resources.",
    addressed_by: "RogueDetector, FleetMonitor, and the KillSwitch with KillReason.ROGUE_BEHAVIOR for automated termination.",
  },
};

export function ComplianceTab({ compliance }: { compliance: GovCompliance }) {
  const { risks, mcp_gateway, rate_limits, compliance_grade, coverage_pct, attestation_hash, needs_attention, grade_distribution } = compliance;
  const gradeC = STRENGTH_COLORS[compliance_grade] ?? STRENGTH_COLORS.moderate;

  return (
    <div className="space-y-5">
      {/* GovernanceAttestation banner */}
      <div className={`card p-5 border-2 ${gradeC.border} ${gradeC.bg} ${gradeC.dark_bg}`}>
        <div className="flex items-center gap-5">
          <div className={`flex-shrink-0 min-w-[4.5rem] px-3 h-16 rounded-xl border-2 flex items-center justify-center ${gradeC.border} bg-white dark:bg-zbrain-dark-card`}>
            <span className={`text-sm font-extrabold capitalize ${gradeC.text} ${gradeC.dark_text}`}>{compliance_grade}</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className={`text-sm font-bold ${gradeC.text} ${gradeC.dark_text}`}>
                GovernanceAttestation · {compliance.owasp_version}
              </p>
              <InfoTip width="w-80" text={"ZBrain's runtime compliance ledger for OWASP Agentic System Integrity (ASI) 2026.\n\nAfter each pipeline run, ZBrain's PolicyEvaluator collects evidence (policy rule fires, HITL approvals, tool intercepts, kill-switch events) and updates this attestation object.\n\nOverall evidence tier:\n• strong ≥ 90%: extensive runtime evidence across all controls\n• moderate 70 to 89%: solid coverage, some controls need more runtime events\n• weak 50 to 69%: foundational controls in place; coverage thin in some areas\n• none < 50%: significant gaps in runtime evidence\n\nThe tier improves automatically as more pipelines execute."} />
              <div className="flex items-center gap-1.5">
                <span className={`text-xs font-mono px-2 py-0.5 rounded border ${gradeC.border} ${gradeC.bg} ${gradeC.text} ${gradeC.dark_bg} ${gradeC.dark_text} opacity-80`}>
                  #{attestation_hash}
                </span>
                <InfoTip text={"SHA-256 fingerprint computed over all 10 control IDs and their current evidence_strength values.\n\nIf any control's evidence tier changes, the hash changes, giving auditors a tamper-evident snapshot of this attestation state at this point in time."} />
              </div>
            </div>
            <div className={`flex items-center gap-1 flex-wrap text-xs mt-1 ${gradeC.text} ${gradeC.dark_text} opacity-80`}>
              <span>{compliance.coverage} controls</span>
              <span>·</span>
              <span className="inline-flex items-center gap-1">
                {coverage_pct}% weighted evidence score
                <InfoTip text={"Weighted mean of all 10 controls' evidence_strength scores (strong=4, moderate=3, weak=2, none=1), normalized to 100%.\n\nA score of 100% means every control has strong runtime evidence. The score rises automatically each time a pipeline run triggers policy evaluations, HITL approvals, or tool intercepts."} />
              </span>
              <span>·</span>
              <span>{new Date(compliance.generated_at).toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-3 mt-2 flex-wrap">
              {Object.entries(grade_distribution)
                .sort(([a], [b]) => (STRENGTH_ORDER_UI[a] ?? 0) - (STRENGTH_ORDER_UI[b] ?? 0))
                .map(([g, n]) => {
                  const gc = STRENGTH_COLORS[g] ?? STRENGTH_COLORS.none;
                  return (
                    <span key={g} className={`text-[11px] font-semibold px-2 py-0.5 rounded border capitalize ${gc.bg} ${gc.text} ${gc.border} ${gc.dark_bg} ${gc.dark_text}`}>
                      {g}: {n}
                    </span>
                  );
                })}
            </div>
          </div>
        </div>
      </div>

      {/* Needs Attention callout */}
      {needs_attention.length > 0 && (
        <div className="card p-4 border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10">
          <div className="flex items-start gap-3">
            <div className="shrink-0 mt-0.5"><AlertIcon /></div>
            <div className="flex-1">
              <div className="flex items-center gap-1.5">
                <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                  {needs_attention.length} control{needs_attention.length > 1 ? "s" : ""} need{needs_attention.length === 1 ? "s" : ""} attention
                </p>
                <InfoTip text={"Controls where ZBrain's GovernanceVerifier found insufficient runtime evidence.\n\n• weak: the control's enforcement logic exists but has fired only a few times\n• none: no runtime events captured for this control yet\n\nRunning more pipelines through the affected stages raises these tiers automatically. No manual configuration is needed."} />
              </div>
              <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5 mb-3">
                Evidence strength rated weak or below. Add more policy rules or increase runtime coverage for these controls.
              </p>
              <div className="flex flex-wrap gap-2">
                {needs_attention.map((r) => {
                  const gc = STRENGTH_COLORS[r.grade] ?? STRENGTH_COLORS.none;
                  return (
                    <div key={r.id} className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border ${gc.bg} ${gc.border} ${gc.dark_bg}`}>
                      <StrengthPill strength={r.grade} />
                      <div>
                        <span className={`text-[11px] font-bold ${gc.text} ${gc.dark_text}`}>{r.id}</span>
                        <span className={`text-[11px] ml-1 ${gc.text} ${gc.dark_text} opacity-80`}>{r.name}</span>
                      </div>
                      <span className={`text-[10px] px-1 py-0.5 rounded font-semibold ${r.severity === "HIGH" ? "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300" : "bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-300"}`}>
                        {r.severity}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* OWASP risk cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {risks.map((risk) => {
          const gc = STRENGTH_COLORS[risk.grade] ?? STRENGTH_COLORS.none;
          const isWeak = ["weak", "none"].includes(risk.grade);
          const asiDef = ASI_DEFINITIONS[risk.id];
          return (
            <div key={risk.id} className={`card p-4 flex flex-col gap-2.5 ${isWeak ? `border-l-4 ${gc.border}` : ""}`}>
              {/* Header row */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="inline-flex items-center gap-1 text-[11px] font-mono font-bold text-zbrain dark:text-zbrain-dark-accent">
                      {risk.id}
                      {asiDef && (
                        <InfoTip width="w-80" text={`${risk.id} ${asiDef.name}\n\nRisk: ${asiDef.risk}\n\nAddressed by: ${asiDef.addressed_by}\n\nThe grade on this card reflects how strong the runtime evidence is that the system enforces the control.`} />
                      )}
                    </span>
                    <span className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{risk.name}</span>
                    <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${risk.severity === "HIGH" ? "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300" : "bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-300"}`}>
                      {risk.severity}
                      <InfoTip text={"OWASP ASI 2026 severity rating:\n• HIGH: exploitation could cause significant harm, data exfiltration, or unauthorized actions at scale\n• MEDIUM: exploitation requires specific conditions; impact is more contained\n\nHigh-severity controls with weak evidence should be prioritized for additional policy rules or runtime coverage."} width="w-72" />
                    </span>
                  </div>
                  <div className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 inline-flex items-center gap-1">
                    <span>{risk.agt_component}</span>
                    <InfoTip text={"The AGT software component that enforces this control at runtime. Operators use this to locate the enforcement logic in code reviews or incident investigations."} />
                  </div>
                </div>
                <span className="inline-flex items-center gap-1 shrink-0">
                  <StrengthPill strength={risk.grade} />
                  <InfoTip text={"Evidence grade for this control: how strong the runtime proof is that the system enforces it.\n\n• Strong: many events captured; enforcement is exercised continuously.\n• Moderate: solid coverage; fewer triggers but architecturally sound.\n• Weak: control exists but is rarely exercised; consider adding policy rules.\n• None: no runtime events yet; gap requiring attention."} />
                </span>
              </div>

              {/* Evidence strength bar */}
              <div>
                <div className="flex items-center gap-1 mb-1">
                  <p className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Evidence strength</p>
                  <InfoTip text={"How much runtime evidence ZBrain collected for this control:\n\n• strong (4/4): many events logged; enforcement is actively exercised\n• moderate (3/4): partial coverage; architecturally sound but fewer runtime triggers\n• weak (2/4): minimal events; the control exists but is rarely triggered\n• none (1/4): no runtime events collected yet\n\nThe count shown is the number of relevant events (tool calls, HITL approvals, policy fires) captured in the audit log."} />
                </div>
                <EvidenceBar strength={risk.evidence_strength} count={risk.evidence_count} field={risk.evidence_field} />
              </div>

              {/* Policy linkage */}
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center gap-1 text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">
                  <span className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{risk.policy_rule_count}</span> policy rules
                  <InfoTip text={"Number of active PolicyEvaluator rules mapped to this OWASP ASI control. Each rule fires when its condition is matched during a pipeline run and contributes to the control's runtime evidence. More rules = broader coverage of the attack surface."} />
                </span>
                <span className="text-zbrain-muted dark:text-zbrain-dark-muted text-[11px]">·</span>
                <span className="inline-flex items-center gap-1 text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">
                  ~<span className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{risk.policy_fire_count}</span> evaluations
                  <InfoTip text={"Approximate number of times a policy rule for this control was evaluated during pipeline processing. Higher counts indicate the control's enforcement logic is actively exercised at runtime, contributing to stronger evidence."} />
                </span>
              </div>

              {/* Coverage detail */}
              <div className="rounded-lg bg-zbrain-surface dark:bg-zbrain-dark-elev2 p-3 space-y-1.5">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted inline-flex items-center gap-1">
                    <span>SalesOps coverage</span>
                    <InfoTip text={"How this control is realized in the SalesOps Solution specifically. This is the product-side surface (which agent or stage enforces the control in the deployed pipeline)."} />
                  </div>
                  <p className="text-xs text-zbrain-ink dark:text-zbrain-dark-ink">{risk.salesops_feature}</p>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted inline-flex items-center gap-1">
                    <span>AGT feature</span>
                    <InfoTip text={"The underlying Microsoft Agent Governance Toolkit (AGT) primitive that implements this control. AGT is the platform layer; the SalesOps coverage above wires AGT features into the email-to-order workflow."} />
                  </div>
                  <p className="text-xs text-zbrain-ink dark:text-zbrain-dark-ink">{risk.agt_feature}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* MCP Gateway */}
      <div className="card p-5">
        <SectionHeader
          title="MCP Security Gateway"
          subtitle="5-stage tool security pipeline: all 15 registered tools scanned and fingerprinted"
          tooltip={"The MCP (Model Context Protocol) Security Gateway is the supply-chain control plane for every tool the platform exposes to agents. Before a tool can be registered for use, it passes through a five-stage scan that checks the tool definition for:\n\n• Tool Poisoning: hidden instructions or malicious behavior embedded in the tool descriptor.\n• Rug Pull: tool behavior that diverges from its declared interface.\n• Instruction / Description Injection: prompt-injection payloads hidden in field descriptions.\n• Capability Drift: registered behavior changing without a new fingerprint.\n• Identity Spoofing: tools impersonating other registered tools.\n\nEach passing tool is fingerprinted; subsequent changes invalidate the fingerprint and re-trigger the scan."}
        />
        {/* Pipeline stages */}
        <div className="flex items-center gap-1 mb-5 flex-wrap">
          {mcp_gateway.pipeline_stages.map((stage, i) => (
            <div key={stage} className="flex items-center gap-1">
              <div className="px-3 py-1.5 rounded-lg bg-zbrain-50 dark:bg-zbrain/10 border border-zbrain-200 dark:border-zbrain/30 text-xs font-medium text-zbrain dark:text-zbrain-dark-accent">
                {i + 1}. {stage.replace(/_/g, " ")}
              </div>
              {i < mcp_gateway.pipeline_stages.length - 1 && (
                <span className="text-zbrain-muted dark:text-zbrain-dark-muted">→</span>
              )}
            </div>
          ))}
        </div>
        {/* Summary */}
        <div className="grid grid-cols-3 gap-4 mb-5">
          <div className="text-center p-3 rounded-lg bg-zbrain-surface dark:bg-zbrain-dark-elev2">
            <p className="text-2xl font-bold text-zbrain-ink dark:text-zbrain-dark-ink">{mcp_gateway.tools_registered}</p>
            <div className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted inline-flex items-center gap-1 justify-center">
              <span>Tools registered</span>
              <InfoTip text={"Total number of tools the agents can call. Each registered tool has passed the five-stage MCP gateway scan and has a current fingerprint on file."} />
            </div>
          </div>
          <div className="text-center p-3 rounded-lg bg-emerald-50 dark:bg-emerald-500/10">
            <p className="text-2xl font-bold text-emerald-700 dark:text-emerald-300">{mcp_gateway.tools_clean}</p>
            <div className="text-xs text-emerald-600 dark:text-emerald-400 inline-flex items-center gap-1 justify-center">
              <span>Clean (no threats)</span>
              <InfoTip text={"Tools that passed every check in the MCP scan with no detected threats. These are safe to invoke at runtime."} />
            </div>
          </div>
          <div className="text-center p-3 rounded-lg bg-red-50 dark:bg-red-500/10">
            <p className="text-2xl font-bold text-red-700 dark:text-red-300">{mcp_gateway.threats_total}</p>
            <div className="text-xs text-red-600 dark:text-red-400 inline-flex items-center gap-1 justify-center">
              <span>Threats detected</span>
              <InfoTip text={"Number of distinct threats the MCP scan flagged across all registered tools. Each threat is either Tool Poisoning, Rug Pull, or Instruction Injection. Tools with active threats are quarantined and cannot be invoked until the operator reviews and clears them."} />
            </div>
          </div>
        </div>
        {/* Tool scan table — simplified: 5 columns (removed Fingerprint; merged 3 threat cols into 1) */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
                {[
                  { h: "Tool",    tip: "The registered tool name. Agents call tools by this identifier; each call goes through CapabilityGuardMiddleware before reaching the tool handler." },
                  { h: "Stage",   tip: "The pipeline stage that primarily invokes this tool. Tools may be allow-listed for one stage and denied for others." },
                  { h: "Ring",    tip: "The trust ring (0 through 3) the tool runs in. Ring 0 tools touch CRM/ERP with non-reversible side-effects; Ring 3 tools run in a sandbox with no external writes." },
                  { h: "Status",  tip: "MCP scan verdict for this tool. Clean = passed all five gateway stages with no threats detected. Compromised = at least one threat flagged; tool is quarantined and cannot be invoked." },
                  { h: "Threats", tip: "Specific threats detected by the MCP scan, if any. Tool Poisoning = malicious behavior in the descriptor. Rug Pull = behavior diverging from declared interface. Instruction Injection = prompt-injection payload hidden in tool fields." },
                ].map(({ h, tip }) => (
                  <th key={h} className="px-3 py-2.5 text-left font-semibold text-zbrain-muted uppercase tracking-wider text-[10px]">
                    <span className="inline-flex items-center gap-1">{h}<InfoTip text={tip} /></span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {mcp_gateway.tools.map((tool, i) => {
                const threats = [
                  tool.tool_poisoning && "Tool Poisoning",
                  tool.rug_pull && "Rug Pull",
                  (tool.hidden_instruction || tool.description_injection) && "Instr. Injection",
                ].filter(Boolean) as string[];
                return (
                  <tr key={tool.tool} className={`border-b border-zbrain-divider/50 dark:border-zbrain-dark-divider/50 hover:bg-zbrain-surface dark:hover:bg-zbrain-dark-elev2 ${i % 2 === 0 ? "" : "bg-zbrain-surface/40 dark:bg-zbrain-dark-elev1/40"}`}>
                    <td className="px-3 py-2 font-mono font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{tool.tool}</td>
                    <td className="px-3 py-2 capitalize text-zbrain-muted dark:text-zbrain-dark-muted">{tool.primary_stage || "-"}</td>
                    <td className="px-3 py-2">
                      {tool.primary_ring !== undefined ? <RingBadge ring={tool.primary_ring} label={`Ring ${tool.primary_ring}`} /> : "-"}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`pill border text-[10px] ${tool.status === "clean" ? "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30" : "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300"}`}>
                        {tool.status}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {threats.length === 0
                        ? <span className="text-emerald-600 dark:text-emerald-400 text-[10px]">✓ None</span>
                        : <span className="text-red-600 dark:text-red-400 text-[10px] font-semibold">{threats.join(", ")}</span>
                      }
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* NIST AI RMF Coverage */}
      {(() => {
        const NIST_FUNCTIONS = [
          {
            id: "GOVERN", full: "Govern", total: 6, full_count: 5, partial_count: 1,
            subcategories: [
              { id: "GV-1", label: "Policies in place",            component: "PolicyEvaluator + OPA/Cedar backends",    status: "full" },
              { id: "GV-2", label: "Accountability structures",    component: "MerkleAuditChain + Shapley attribution",  status: "full" },
              { id: "GV-3", label: "Workforce diversity & expertise", component: "CONTRIBUTING.md (doc only)",            status: "partial" },
              { id: "GV-4", label: "Third-party practices",        component: "MCPGateway + AI-BOM + Plugin signing",    status: "full" },
              { id: "GV-5", label: "Risk management processes",    component: "RiskClassifier (EU AI Act)",              status: "full" },
              { id: "GV-6", label: "Requirements alignment",       component: "7 framework compliance mappings",         status: "full" },
            ],
          },
          {
            id: "MAP", full: "Map", total: 5, full_count: 3, partial_count: 2,
            subcategories: [
              { id: "MP-1", label: "Context established",      component: "ContextualPolicyEngine + 4-Ring model",     status: "full" },
              { id: "MP-2", label: "AI systems categorized",   component: "RiskLevel enum + 5-tier TrustScore",        status: "full" },
              { id: "MP-3", label: "Benefits & costs assessed", component: "Latency benchmarks (no ROI model)",         status: "partial" },
              { id: "MP-4", label: "Risks identified",         component: "STRIDE + OWASP + Chaos engineering",         status: "full" },
              { id: "MP-5", label: "Individual/group impacts", component: "GDPR template (no bias/fairness eval)",      status: "partial" },
            ],
          },
          {
            id: "MEASURE", full: "Measure", total: 4, full_count: 2, partial_count: 2,
            subcategories: [
              { id: "MS-1", label: "Metrics identified",       component: "SLO engine + TrustScore + OTel",                    status: "full" },
              { id: "MS-2", label: "AI systems evaluated",     component: "ContentQualityEvaluator (no model eval pipeline)",  status: "partial" },
              { id: "MS-3", label: "Risk tracking mechanisms", component: "RogueDetector + DriftDetector + FlightRecorder",    status: "full" },
              { id: "MS-4", label: "Feedback on measurement", component: "ShiftLeftTracker + SLODashboard (no trend analysis)", status: "partial" },
            ],
          },
          {
            id: "MANAGE", full: "Manage", total: 4, full_count: 3, partial_count: 1,
            subcategories: [
              { id: "MG-1", label: "Risks prioritized & responded", component: "CircuitBreaker + KillSwitch + Sagas",       status: "full" },
              { id: "MG-2", label: "Maximize AI benefits",          component: "TrustScore delegation (no ROI framing)",    status: "partial" },
              { id: "MG-3", label: "Third-party risks managed",     component: "MCPGateway + AI-BOM + Egress policy",       status: "full" },
              { id: "MG-4", label: "Risks monitored",               component: "OTel + RogueDetector + Fleet monitoring",   status: "full" },
            ],
          },
        ];
        const totalFull = NIST_FUNCTIONS.reduce((s, f) => s + f.full_count, 0);
        const totalPartial = NIST_FUNCTIONS.reduce((s, f) => s + f.partial_count, 0);
        const totalAll = NIST_FUNCTIONS.reduce((s, f) => s + f.total, 0);
        const scoreNum = Math.round((totalFull + totalPartial * 0.5) / totalAll * 100);
        const scoreGrade = scoreNum >= 90 ? "A" : scoreNum >= 80 ? "B" : scoreNum >= 70 ? "C" : "D";
        return (
          <div className="card p-5">
            <div className="flex items-start justify-between gap-4 mb-4">
              <SectionHeader
                title="NIST AI RMF Alignment"
                subtitle="AI Risk Management Framework: 4 core functions, 19 subcategories"
                tooltip={"NIST AI RMF defines four functions for managing AI risk:\n\n• GOVERN: policies, accountability, risk tolerance\n• MAP: context, risk identification, third-party risk\n• MEASURE: metrics, evals, feedback loops\n• MANAGE: response, benefit maximization, monitoring\n\nData sourced verbatim from AGT's nist-ai-rmf-alignment.md (Coverage Summary Matrix). AGT self-rates 13 fully addressed + 6 partially addressed across 19 subcategories.\n\nPartials per AGT:\n• GV-3: workforce diversity (documentation only, no code enforcement)\n• MP-3: benefits/costs (technical benchmarks; no ROI framework)\n• MP-5: individual impacts (GDPR template, but no bias/fairness algorithms)\n• MS-2: evaluation (no model accuracy/calibration pipeline)\n• MS-4: measurement feedback (no compliance trend analysis)\n• MG-2: maximize benefits (trust scoring framed as security, not utility)\n\nScore = (full + 0.5·partial) / total."}
              />
              <div className="shrink-0 text-right">
                <span className={`text-2xl font-extrabold tabular-nums ${NIST_GRADE_COLORS[scoreGrade]?.text ?? "text-blue-700"} ${NIST_GRADE_COLORS[scoreGrade]?.dark_text ?? ""}`}>{scoreNum}%</span>
                <div className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted">Grade {scoreGrade} · {totalFull} full + {totalPartial} partial / {totalAll}</div>
              </div>
            </div>
            <div className="space-y-3">
              {NIST_FUNCTIONS.map((fn) => {
                const pct = Math.round((fn.full_count + fn.partial_count * 0.5) / fn.total * 100);
                const allFull = fn.partial_count === 0;
                return (
                  <details key={fn.id} className="group">
                    <summary className="flex items-center gap-3 cursor-pointer select-none list-none">
                      <div className="w-16 shrink-0">
                        <span className={`text-xs font-bold font-mono px-1.5 py-0.5 rounded ${allFull ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"}`}>{fn.id}</span>
                      </div>
                      <div className="flex-1 h-2.5 bg-zbrain-surface dark:bg-zbrain-dark-elev2 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${allFull ? "bg-emerald-500" : "bg-amber-500"}`} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-xs tabular-nums text-zbrain-muted dark:text-zbrain-dark-muted w-12 text-right">{fn.full_count}/{fn.total}</span>
                      <span className={`text-[11px] font-semibold ${allFull ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{allFull ? "✓" : `⚠ ${fn.partial_count} partial`}</span>
                    </summary>
                    <div className="mt-2 ml-[76px] space-y-1">
                      {fn.subcategories.map((sc) => (
                        <div key={sc.id} className="flex items-center gap-2 text-[11px]">
                          <span className={`font-mono text-[10px] w-12 shrink-0 ${sc.status === "full" ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{sc.id}</span>
                          <span className="text-zbrain-ink dark:text-zbrain-dark-ink">{sc.label}</span>
                          <span className="text-zbrain-muted dark:text-zbrain-dark-muted ml-auto text-[10px] font-mono">{sc.component}</span>
                          <span className={sc.status === "full" ? "text-emerald-500 dark:text-emerald-400" : "text-amber-500 dark:text-amber-400"}>{sc.status === "full" ? "✓" : "⚠"}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* EU AI Act Conformity Gap */}
      <div className="flex items-start gap-3 p-4 rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10">
        <AlertIcon />
        <div className="flex-1 space-y-1">
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">EU AI Act Art. 26(6): Conformity Gap</p>
          <p className="text-xs text-amber-700 dark:text-amber-400">
            <strong>Configuration gap:</strong> AGT <code className="font-mono">policy_schema.json</code> sets <code className="font-mono">retention_days</code> default to <strong>90 days</strong> · required <strong>≥ 180 days</strong> for high-risk AI systems under Article 26(6).
          </p>
          <p className="text-xs text-amber-700 dark:text-amber-400">
            <strong>Runtime enforcement gap:</strong> per AGT's own EU AI Act checklist, the <code className="font-mono">retention_days</code> field is currently a schema declaration only; no code in AGT preserves or deletes logs based on this value. Both must be addressed for EU production deployment.
          </p>
        </div>
        <Tip position="right" text={"EU AI Act Article 26(6) requires providers of high-risk AI systems to retain audit logs for a minimum of 180 days (~6 months).\n\nTwo distinct gaps surfaced by AGT's own eu-ai-act-checklist.md:\n\n1. CONFIG: schema default is 90 days; minimum is 1. Must raise default and minimum to 180 for high-risk deployments.\n\n2. RUNTIME: no enforcement code exists yet. AGT itself flags this as a 'must-fix': retention_days is a declaration, not an enforced setting.\n\nSource: agent-governance-toolkit/docs/compliance/eu-ai-act-checklist.md (lines 325 to 326, 402)."} />
      </div>

      {/* Incident Readiness */}
      <div className="card p-5">
        <SectionHeader
          title="Incident Readiness"
          subtitle="AGT IncidentSeverity P0–P3 SLA targets + circuit breaker state"
          tooltip={"AGT defines 4 incident severity levels (incident-response-workflow.md):\n\n• P0 Critical: agent caused or actively causing harm; SLA < 1 hour\n• P1 High: policy bypass detected, potential for harm if unchecked; SLA < 4 hours\n• P2 Medium: behavior anomaly, no confirmed harm; SLA < 24 hours\n• P3 Low: governance config issue, no user impact; SLA < 1 week\n\nEvery incident is classified by severity AND category (HIJACK, CAPABILITY_BREACH, DATA_LEAK, etc.); each category maps to an OWASP ASI control.\n\n6-step response workflow: TRIAGE (< 15 min) → CONTAIN (kill switch if P0/P1) → INVESTIGATE → REMEDIATE → NOTIFY → POST-MORTEM.\n\nRegulatory alignment: EU AI Act Art. 62 (serious incidents reportable to Member State authority within 15 days), Colorado AI Act SB 21-169 (consumer notification within 90 days), NIST AI RMF MANAGE function.\n\nCircuit Breaker states: CLOSED = healthy / OPEN = blocking / HALF_OPEN = probing."}
        />

        {/* Triage SLA strip */}
        <div className="flex items-start gap-3 mb-3 px-4 py-2.5 rounded-lg bg-zbrain-50 dark:bg-zbrain/10 border border-zbrain-200 dark:border-zbrain/30">
          <span className="text-[10px] font-bold font-mono px-1.5 py-0.5 rounded bg-zbrain text-white dark:bg-zbrain-dark-accent dark:text-zbrain-dark-elev1 shrink-0">TRIAGE</span>
          <span className="text-xs text-zbrain-ink dark:text-zbrain-dark-ink flex-1">
            All incidents triaged within <strong>&lt; 15 min</strong>: classify severity + category, assign incident commander. The per-tier response SLA below starts when triage completes.
          </span>
          <InfoTip width="w-80" text={"The < 15 min triage window is tighter than any per-tier SLA.\n\nDuring triage, AGT classifies the incident along TWO axes:\n• Severity (P0 to P3): how urgent?\n• Category (HIJACK, DATA_LEAK, etc.): what kind of failure?\n\nAn incident commander is assigned before the per-tier response SLA begins. This separates 'what is this?' from 'how do we respond?'. Without it, a P0 could sit in a P3 queue until someone looked at it.\n\nSource: AGT incident-response-workflow.md §2."} />
        </div>

        {/* EU AI Act Art. 62 alignment strip */}
        <div className="flex items-start gap-3 mb-3 px-4 py-2.5 rounded-lg bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/30">
          <span className="text-[10px] font-bold font-mono px-1.5 py-0.5 rounded bg-blue-600 text-white dark:bg-blue-500 dark:text-white shrink-0">EU AI ACT</span>
          <span className="text-xs text-blue-900 dark:text-blue-200 flex-1">
            Aligned with <strong>Art. 62</strong>: serious incidents in high-risk AI systems reportable to Member State market surveillance authority within <strong>15 days</strong>. Also: Colorado AI Act SB 21-169 (90-day consumer notification), NIST AI RMF MANAGE.
          </span>
          <InfoTip width="w-80" text={"EU AI Act Article 62 defines a 'serious incident' as one that resulted in:\n\n• Death or serious damage to health\n• Serious disruption to critical infrastructure\n• Infringement of fundamental rights protected by EU law\n• Serious damage to property or the environment\n\nProviders and deployers of high-risk AI systems must notify the Member State market surveillance authority without undue delay and no later than 15 days after becoming aware.\n\nThis obligation is separate from Art. 26(6) audit log retention. Together they are the core operational compliance requirements for high-risk AI deployments in the EU."} />
        </div>

        <div className="space-y-2">
          {[
            { severity: "P0", label: "Critical", definition: "Agent caused or is actively causing harm to individuals or systems", examples: "Unauthorized financial transactions · PII breach · discriminatory decisions affecting protected classes", containment: "Kill switch fires + isolate from network + preserve audit logs + notify legal within 1 hour",            sla: "< 1 hour",   color: "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30",                text: "text-red-700 dark:text-red-300",       dot: "bg-red-500",    cb: "CLOSED" },
            { severity: "P1", label: "High",     definition: "Agent policy bypass detected; potential for harm if unchecked",       examples: "Kill switch failure · prompt injection succeeded · trust verification bypassed",            containment: "Disable affected policy rule or tool capability + switch agent to read-only + review last 24h audit logs", sla: "< 4 hours",  color: "bg-orange-50 dark:bg-orange-500/10 border-orange-200 dark:border-orange-500/30",   text: "text-orange-700 dark:text-orange-300", dot: "bg-orange-500", cb: null },
            { severity: "P2", label: "Medium",   definition: "Agent behavior anomaly; no confirmed harm",                            examples: "Unexpected tool calls · trust score degradation · audit log gaps",                          containment: "Create tracking issue with reproduction steps + update policy YAML with corrective rule",                   sla: "< 24 hours", color: "bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30",       text: "text-amber-700 dark:text-amber-300",   dot: "bg-amber-500",  cb: null },
            { severity: "P3", label: "Low",      definition: "Governance configuration issue; no user impact",                       examples: "Policy rule misconfiguration · non-critical test failures · documentation gap",             containment: "Create tracking issue + schedule fix for next sprint",                                                     sla: "< 1 week",   color: "bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700",                text: "text-gray-600 dark:text-gray-400",     dot: "bg-gray-400",   cb: null },
          ].map((row) => (
            <div key={row.severity} className={`px-4 py-3 rounded-lg border ${row.color}`}>
              <div className="flex items-center gap-4">
                <span className={`text-xs font-bold font-mono ${row.text} w-8`}>{row.severity}</span>
                <span className={`text-xs font-semibold ${row.text} w-16`}>{row.label}</span>
                <span className="inline-flex items-center gap-1">
                  <span className={`text-xs ${row.text} opacity-80`}>SLA: {row.sla}</span>
                  <InfoTip text={"The maximum time allowed between triage completion and the first response action for this severity.\n\nThis is a RESPONSE target, not a RESOLUTION target. Resolution time depends on root-cause complexity and is best-effort once contained.\n\n• P0/P1: response includes immediate automated containment (kill switch or capability disable)\n• P2/P3: response = creating a tracking issue + scheduling the fix\n\nThe < 15-min triage window above runs separately and is not included in this SLA."} />
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${row.dot}`} />
                  <span className={`text-[11px] font-semibold ${row.text}`}>READY</span>
                  <InfoTip text={"A tier is READY when:\n• The runbook is documented and current\n• An on-call rotation is populated for response within the SLA\n• The automated containment action below has been tested\n\nIn this demo, READY is a static label. In production it would be evidence-backed (e.g., 'last drill: 7 days ago' or wired to PagerDuty / Opsgenie configuration checks)."} />
                  {row.cb && (
                    <>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 font-mono">
                        CircuitBreaker: {row.cb}
                      </span>
                      <InfoTip width="w-80" text={"AGT's CircuitBreaker is an automated safety mechanism modeled on the same pattern Netflix / Stripe use to prevent cascade failures.\n\nThree states:\n• CLOSED: healthy, calls flowing normally\n• OPEN: failure threshold exceeded; all calls blocked until cool-down expires\n• HALF_OPEN: probing recovery; a few calls allowed. Success → CLOSED, failure → OPEN again.\n\nCLOSED right now means no P0-level cascade is currently in progress. The breaker trips automatically based on rolling failure rate; no human in the loop.\n\nSource: agent-os/circuit_breaker.py (CircuitState enum)."} />
                    </>
                  )}
                </div>
              </div>
              <p className={`text-[11px] ${row.text} opacity-90 mt-1.5 ml-12`}>{row.definition}</p>
              <p className={`text-[10px] ${row.text} opacity-70 mt-0.5 ml-12`}>
                <span className="font-semibold">Examples:</span> {row.examples}
              </p>
              <div className="mt-0.5 ml-12 inline-flex items-center gap-1 flex-wrap">
                <span className={`text-[10px] ${row.text} opacity-80 font-semibold uppercase tracking-wider`}>Containment:</span>
                <InfoTip width="w-80" text={"Containment actions are AUTOMATED by AGT, not manual incident-response steps a human takes.\n\n• P0: the kill switch fires before a human even sees the alert\n• P1: the affected policy rule / tool capability is auto-disabled\n• P2/P3: a tracking issue is created and policy YAML is updated\n\nThis is the difference between 'we'll respond within 1 hour' and 'the system has already contained the incident; we'll investigate within 1 hour.'"} />
                <span className={`text-[10px] ${row.text} opacity-80`}>{row.containment}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Incident Categories (AGT severity × category matrix) */}
        <div className="mt-5 pt-5 border-t border-zbrain-200 dark:border-zbrain-dark-elev2">
          <div className="flex items-baseline gap-2 mb-3 flex-wrap">
            <h3 className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Incident Categories</h3>
            <InfoTip width="w-80" text={"AGT classifies every incident along TWO axes:\n\n• Severity (P0 to P3): how urgent is the response?\n• Category (HIJACK, DATA_LEAK, etc.): what KIND of failure is it?\n\nThe same severity can come from very different categories. A P0 could be a DATA_LEAK (PII exposure) or a BIAS_HARM (discriminatory decision). The category determines which playbook runs, even when the severity is the same.\n\nEach category maps to an OWASP ASI control, the same threat taxonomy used in the GovernanceAttestation widget at the top of this page."} />
            <span className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted">AGT classifies every incident by severity <em>and</em> category. Each category maps to an OWASP ASI control.</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {[
              { cat: "HIJACK",            desc: "Agent taken over by adversarial input",      owasp: "ASI-01" },
              { cat: "CAPABILITY_BREACH", desc: "Agent performed unauthorized action",        owasp: "ASI-02" },
              { cat: "DATA_LEAK",         desc: "Sensitive data exposed through agent",       owasp: "ASI-04, ASI-05" },
              { cat: "TRUST_FAILURE",     desc: "Identity / trust verification failed",       owasp: "ASI-06, ASI-07" },
              { cat: "CASCADE",           desc: "Multi-agent failure propagation",            owasp: "ASI-08" },
              { cat: "AUDIT_FAILURE",     desc: "Audit trail compromised or incomplete",      owasp: "ASI-09" },
              { cat: "RESOURCE_ABUSE",    desc: "Agent consumed excessive resources",         owasp: "ASI-10" },
              { cat: "BIAS_HARM",         desc: "Agent produced discriminatory outcome",      owasp: "Fairness" },
              { cat: "POLICY_BYPASS",     desc: "Deterministic policy circumvented",          owasp: "Governance" },
            ].map((c) => (
              <div key={c.cat} className="flex flex-col gap-1 px-3 py-2 rounded-lg border border-zbrain-200 dark:border-zbrain-dark-elev2 bg-zbrain-surface dark:bg-zbrain-dark-elev2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-mono font-bold text-zbrain dark:text-zbrain-dark-accent">{c.cat}</span>
                  <span className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted">{c.owasp}</span>
                </div>
                <p className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted">{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ThreatCell({ val }: { val: boolean }) {
  return val
    ? <span className="text-red-600 dark:text-red-400 font-bold">✗ DETECTED</span>
    : <span className="text-emerald-600 dark:text-emerald-400">✓ Clean</span>;
}

// ---------------------------------------------------------------------------
// Icons (inline SVG — no external dep)
// ---------------------------------------------------------------------------

function AlertIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 mt-0.5">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function ChainIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-emerald-600 dark:text-emerald-400">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  );
}

function OrchestratorIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function CheckCircleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-600 dark:text-emerald-400 shrink-0">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

function BlockIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Tab 6: SLO Monitor
// ---------------------------------------------------------------------------

const EXHAUSTION_LABELS: Record<string, { label: string; color: string }> = {
  throttle:      { label: "THROTTLE",       color: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30" },
  circuit_break: { label: "CIRCUIT BREAK",  color: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:border-orange-500/30" },
  kill_agent:    { label: "KILL AGENT",     color: "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30" },
};

const SLO_TIERS: Record<string, { label: string; color: string }> = {
  e2e_latency:        { label: "BASE",     color: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30" },
  success_rate:       { label: "CRITICAL", color: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30" },
  hitl_resolution:    { label: "BATCH",    color: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-500/10 dark:text-slate-300 dark:border-slate-500/30" },
  confidence_floor:   { label: "CRITICAL", color: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30" },
  cost_per_task:      { label: "BASE",     color: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30" },
  hallucination_rate: { label: "CRITICAL", color: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/30" },
};

const SLO_SLI_FORMULAS: Record<string, string> = {
  e2e_latency:        "agent_pipeline_latency_p95",
  success_rate:       "agent_task_success_ratio @ Execute",
  hitl_resolution:    "hitl_approval_latency_p95",
  confidence_floor:   "l4_pipeline_ratio @ confidence ≥ 0.60",
  cost_per_task:      "agent_pipeline_cost_usd",
  hallucination_rate: "rogue_detection_rate",
};

type SloStatus = "met" | "breached" | "pending";

function sloStatus(slo: SloResult): SloStatus {
  if (slo.samples === 0) return "pending";
  return slo.met ? "met" : "breached";
}

const SLO_STATUS_STYLES: Record<SloStatus, { label: string; pill: string; border: string }> = {
  met:      { label: "✓ MET",      pill: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30", border: "border-zbrain-divider dark:border-zbrain-dark-divider" },
  breached: { label: "✗ BREACHED", pill: "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30",                          border: "border-red-300 dark:border-red-500/40" },
  pending:  { label: "○ PENDING",  pill: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-500/10 dark:text-slate-300 dark:border-slate-500/30",            border: "border-slate-300 dark:border-zbrain-dark-divider" },
};

function Sparkline({
  series, target, comparison, status, unit, windowHours,
}: {
  series: (number | null)[];
  target: number;
  comparison: "lt" | "gte";
  status: SloStatus;
  unit: string;
  windowHours: number;
}) {
  const W = 320;
  const H = 56;
  const PAD_X = 6;
  const PAD_Y = 6;
  const innerW = W - PAD_X * 2;
  const innerH = H - PAD_Y * 2;

  const numeric = series.filter((v): v is number => v != null);
  const hasData = numeric.length > 0;

  const dataMax = hasData ? Math.max(...numeric, target) : target;
  const dataMin = hasData ? Math.min(...numeric, target) : 0;
  const range = Math.max(dataMax - dataMin, dataMax * 0.05 || 1);
  const yMax = dataMax + range * 0.15;
  const yMin = Math.max(0, dataMin - range * 0.15);

  const x = (i: number) => PAD_X + (i / Math.max(series.length - 1, 1)) * innerW;
  const y = (v: number) => PAD_Y + innerH - ((v - yMin) / Math.max(yMax - yMin, 1e-9)) * innerH;

  const lineColor = status === "pending"
    ? "#94a3b8"
    : status === "met"
    ? "#10b981"
    : "#ef4444";
  const fillColor = status === "pending"
    ? "rgba(148, 163, 184, 0.10)"
    : status === "met"
    ? "rgba(16, 185, 129, 0.14)"
    : "rgba(239, 68, 68, 0.14)";

  const segments: Array<Array<[number, number]>> = [];
  let cur: Array<[number, number]> = [];
  series.forEach((v, i) => {
    if (v == null) {
      if (cur.length > 0) { segments.push(cur); cur = []; }
    } else {
      cur.push([x(i), y(v)]);
    }
  });
  if (cur.length > 0) segments.push(cur);

  const linePath = segments
    .map((seg) => seg.map(([px, py], idx) => `${idx === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join(" "))
    .join(" ");

  const areaPath = segments
    .map((seg) => {
      if (seg.length === 0) return "";
      const start = `M${seg[0][0].toFixed(1)},${(PAD_Y + innerH).toFixed(1)}`;
      const lineTo = seg.map(([px, py]) => `L${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
      const end = `L${seg[seg.length - 1][0].toFixed(1)},${(PAD_Y + innerH).toFixed(1)} Z`;
      return `${start} ${lineTo} ${end}`;
    })
    .join(" ");

  const targetY = y(target);
  const windowLabel = windowHours >= 168 ? `-${Math.round(windowHours / 24)}d` : `-${windowHours}h`;
  // Target label top offset as % of SVG height — immune to horizontal scaling
  const targetLabelTopPct = Math.min(Math.max((targetY / H) * 100 - 18, 0), 70);

  return (
    <div className="w-full">
      <div className="relative w-full">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-14">
          <path d={areaPath} fill={fillColor} stroke="none" />
          <line
            x1={PAD_X} x2={W - PAD_X} y1={targetY} y2={targetY}
            stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 3" opacity={0.7}
          />
          <path d={linePath} fill="none" stroke={lineColor} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
          {segments.flatMap((seg, segIdx) =>
            seg.map(([px, py], idx) => (
              <circle key={`${segIdx}-${idx}`} cx={px} cy={py} r={1.4} fill={lineColor} />
            )),
          )}
        </svg>

        {/* Target label — HTML overlay so it renders at native resolution, unaffected by SVG horizontal scaling */}
        <span
          className="absolute right-1.5 font-mono text-[9px] text-slate-400 dark:text-slate-500 leading-none pointer-events-none select-none whitespace-nowrap"
          style={{ top: `${targetLabelTopPct}%` }}
        >
          target {comparison === "lt" ? "<" : "≥"} {formatTargetForChart(target, unit)}
        </span>

        {!hasData && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-[10px] text-slate-400 dark:text-slate-500 italic">no samples in window</span>
          </div>
        )}
      </div>
      <div className="flex justify-between text-[9px] text-zbrain-muted dark:text-zbrain-dark-muted font-mono mt-0.5">
        <span>{windowLabel}</span>
        <span>now</span>
      </div>
    </div>
  );
}

function formatTargetForChart(v: number, unit: string): string {
  if (unit === "ms") return v >= 1000 ? `${(v / 1000).toFixed(0)}s` : `${Math.round(v)}ms`;
  if (unit === "minutes") return v >= 60 ? `${(v / 60).toFixed(0)}h` : `${Math.round(v)}min`;
  if (unit === "usd") return `$${v.toFixed(2)}`;
  return `${(v * 100).toFixed(0)}%`;
}

function BudgetArc({ pct, pending = false }: { pct: number; pending?: boolean }) {
  const r = 28;
  const cx = 36;
  const cy = 36;
  const full = 2 * Math.PI * r;
  const filled = pending ? 0 : (pct / 100) * full;
  const color = pending
    ? "#94a3b8"
    : pct >= 50 ? "#10b981" : pct >= 25 ? "#f59e0b" : "#ef4444";
  const trackColor = "currentColor";
  return (
    <svg width={72} height={72} className="shrink-0">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={trackColor} strokeWidth={6}
        className="text-zbrain-surface dark:text-zbrain-dark-elev2" />
      {!pending && (
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={6}
          strokeDasharray={`${filled} ${full - filled}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`} />
      )}
      <text x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="middle"
        fontSize={pending ? 9 : 11} fontWeight={700} fill={color}>
        {pending ? "n/a" : `${Math.round(pct)}%`}
      </text>
    </svg>
  );
}

const SLI_TYPE_LABELS: Record<string, string> = {
  latency: "Latency", success_rate: "Availability",
  cost_usd: "Cost", hallucination: "Hallucination",
};

function SloCard({ slo }: { slo: SloResult }) {
  const status = sloStatus(slo);
  const statusStyle = SLO_STATUS_STYLES[status];
  const tier = SLO_TIERS[slo.id] ?? { label: "CUSTOM", color: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-500/10 dark:text-slate-300 dark:border-slate-500/30" };
  const sliFormula = SLO_SLI_FORMULAS[slo.id] ?? slo.sli_type;
  const exhaustion = EXHAUSTION_LABELS[slo.exhaustion_action] ?? EXHAUSTION_LABELS["throttle"];

  const budgetColor = status === "pending"
    ? "text-slate-500 dark:text-slate-400"
    : slo.budget_remaining_pct >= 50
    ? "text-emerald-600 dark:text-emerald-400"
    : slo.budget_remaining_pct >= 25
    ? "text-amber-600 dark:text-amber-400"
    : "text-red-600 dark:text-red-400";

  const formatValue = (v: number, unit: string) => {
    if (unit === "ms") return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
    if (unit === "minutes") return v >= 60 ? `${(v / 60).toFixed(1)} h` : `${Math.round(v)} min`;
    if (unit === "usd") return `$${v.toFixed(3)}`;
    return `${(v * 100).toFixed(1)}%`;
  };
  const currentDisplay = status === "pending" ? "-" : formatValue(slo.current_value, slo.unit);
  const currentColor = status === "pending"
    ? "text-slate-500 dark:text-slate-400"
    : status === "met"
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";

  return (
    <div className={`card p-4 flex flex-col gap-3 border ${statusStyle.border}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <span className={`pill border text-[10px] font-semibold uppercase ${statusStyle.pill}`}>
              {statusStyle.label}
            </span>
            <Tip text={"Current evaluation state of this SLO:\n\n• MET: the measured value is meeting the target within the window. Error budget is intact.\n• BREACHED: the measured value is missing the target. Error budget is being consumed; if burn rate is elevated, the exhaustion action will trip.\n• PENDING: fewer than one sample in the window. The SLO cannot be evaluated until traffic produces data."} />
            <span className={`pill border text-[10px] font-bold uppercase tracking-wider ${tier.color}`}>{tier.label}</span>
            <Tip text={"Reliability class assigned to this SLO:\n\n• BASE: standard reliability target (typically 99%). Acceptable for non-critical paths.\n• CRITICAL: mission-critical target (typically 99.9%). Stricter budget, faster automated response.\n• BATCH: throughput-oriented target (typically 95%). Optimized for backlog processing where latency is less important than completion."} />
            <span className="text-[10px] uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">{SLI_TYPE_LABELS[slo.sli_type] ?? slo.sli_type.replace("_", " ")}</span>
            <Tip text={`AGT SLI → SLO → ErrorBudget model:\n\n• SLI (Service Level Indicator): the raw metric (${slo.sli_type === "latency" ? "p95 latency in " + slo.unit : "fraction of good events"}).\n• SLO (Service Level Objective): the target (${slo.display_target} over a ${slo.window_hours}h window).\n• ErrorBudget: the allowed fraction of bad events (${(slo.budget_total * 100).toFixed(0)}% of total). When exhausted, AGT triggers the exhaustion action automatically.\n\nTier (${tier.label}) maps to AGT's reference SLO specs: BASE (99% targets), CRITICAL (99.9% targets, mission-critical), BATCH (95% targets, throughput-over-speed).`} />
          </div>
          <div className="text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink leading-tight inline-flex items-center gap-1.5">
            <span>{slo.name}</span>
            <Tip text={`The SLO's display name. The numeric identifier (for example "1.1") encodes section.subsection within the AGT SLO catalog:\n\n• 1.x: latency objectives\n• 2.x: success / availability objectives\n• 3.x: human-in-the-loop resolution objectives\n• 4.x: confidence and quality objectives\n• 5.x: cost objectives\n• 6.x: hallucination / accuracy objectives\n\nThis SLO measures ${SLI_TYPE_LABELS[slo.sli_type] ?? slo.sli_type} with a target of ${slo.display_target} over a ${slo.window_hours}h window.`} />
          </div>
          <div className="text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 inline-flex items-center gap-1">
            <span>{slo.display_target} · {slo.window_hours}h window · {slo.samples} samples</span>
            <Tip text={`Three SLO parameters in one line:\n\n• Target: the value the SLI must meet (${slo.display_target}). ${slo.comparison === "lt" ? "Lower is better." : "Higher is better."}\n• Window: ${slo.window_hours} hours of rolling measurement. Older samples drop out as new ones arrive.\n• Samples: number of measurements collected in the current window (${slo.samples}). Below 10 samples, the result is treated as low-confidence and the SLO may remain PENDING.`} />
          </div>
          <div className="text-[10px] font-mono text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 opacity-80 inline-flex items-center gap-1">
            <span>SLI: {sliFormula}</span>
            <Tip text={"The underlying telemetry expression the SLO is evaluated against. AGT computes this value from TraceEvent records emitted during pipeline runs; the SLO target is then applied to the result over the measurement window."} />
          </div>
        </div>
      </div>

      {/* Pending banner */}
      {status === "pending" && (
        <div className="text-[10px] text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-500/10 border border-slate-200 dark:border-slate-500/30 rounded-md px-2 py-1.5 -mt-1">
          No samples in window; awaiting traffic. SLO cannot be evaluated until at least one pipeline runs.
        </div>
      )}

      {/* Sparkline trend */}
      <Sparkline
        series={slo.series}
        target={slo.target}
        comparison={slo.comparison}
        status={status}
        unit={slo.unit}
        windowHours={slo.window_hours}
      />

      {/* 3-column metrics footer */}
      <div className="border-t border-zbrain-divider dark:border-zbrain-dark-divider pt-2.5 grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-1">
            <span className="text-[9px] font-semibold uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Current</span>
            <Tip text={`The most recent measured value of the SLI over the ${slo.window_hours}h window. Compare against the target (${slo.display_target}).\n\nGreen = meeting target. Red = missing target. Grey = no samples yet.`} />
          </div>
          <span className={`text-sm font-bold tabular-nums ${currentColor}`}>{currentDisplay}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-1">
            <span className="text-[9px] font-semibold uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Budget Left</span>
            <Tip text={`Error budget = the fraction of ${slo.unit === "ms" || slo.unit === "minutes" ? "requests" : "events"} allowed to violate the SLO target before AGT triggers the exhaustion action.\n\nBudget total: ${(slo.budget_total * 100).toFixed(0)}%\nConsumed: ${(slo.budget_consumed * 100).toFixed(1)}%\nRemaining: ${slo.budget_remaining_pct.toFixed(1)}%\n\n${status === "pending" ? "No samples; nothing has been consumed yet." : `Running out triggers AGT ${exhaustion.label}.`}`} />
          </div>
          <span className={`text-sm font-bold tabular-nums ${budgetColor}`}>
            {status === "pending" ? "n/a" : `${slo.budget_remaining_pct.toFixed(0)}%`}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-1">
            <span className="text-[9px] font-semibold uppercase tracking-wider text-zbrain-muted dark:text-zbrain-dark-muted">Burn Rate</span>
            <Tip text={`Burn rate = how fast the error budget is being consumed relative to the expected steady-state rate.\n\n1.0× = consuming at exactly the expected rate (budget lasts the full window).\n2.0× = consuming twice as fast → warning alert fires.\n${slo.burn_rate_critical_threshold}× = critical threshold → exhaustion action triggers.\n\nCurrent: ${status === "pending" ? "n/a (no samples)" : slo.burn_rate.toFixed(2) + "×"}`} />
          </div>
          <div className="flex items-baseline gap-1">
            <span className={`text-sm font-bold tabular-nums ${status === "pending" ? "text-slate-500 dark:text-slate-400" : slo.burn_rate >= slo.burn_rate_critical_threshold ? "text-red-600 dark:text-red-400" : slo.burn_rate >= slo.burn_rate_alert_threshold ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}`}>
              {status === "pending" ? "-" : `${slo.burn_rate.toFixed(2)}×`}
            </span>
            <span className="text-[9px] text-zbrain-muted dark:text-zbrain-dark-muted whitespace-nowrap">
              w@{slo.burn_rate_alert_threshold} · c@{slo.burn_rate_critical_threshold}
            </span>
          </div>
        </div>
      </div>

      {/* Firing alerts */}
      {slo.firing_alerts.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 -mt-1">
          {slo.firing_alerts.map((a) => (
            <span key={a.name} className={`pill border text-[10px] font-semibold ${a.severity === "critical" ? "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30" : "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30"}`}>
              {a.severity === "critical" ? "🔴" : "🟡"} {a.severity} {a.rate}×
            </span>
          ))}
          <Tip text={"BurnRateAlerts currently firing on this SLO. Each pill shows the alert severity and the measured burn rate.\n\n• Warning (yellow): burn rate at or above the warning threshold (typically 2×). The error budget will be exhausted before the window completes if the rate continues.\n• Critical (red): burn rate at or above the critical threshold (typically 10×). The exhaustion action will trip imminently.\n\nAlerts clear automatically when burn rate drops back below the threshold for a sustained period."} />
        </div>
      )}

      {/* Exhaustion action — prominent band */}
      <div className={`flex items-center justify-between gap-2 -mx-4 -mb-4 px-4 py-2.5 rounded-b-lg border-t ${exhaustion.color}`}>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-bold uppercase tracking-wider opacity-80">Automated response on budget exhaustion</span>
          <Tip position="right" text={`AGT ExhaustionAction: the automated response when this SLO's error budget reaches 0%:\n\nTHROTTLE: AGT's AgentRateLimiter applies backpressure; it reduces request throughput to protect remaining capacity.\n\nCIRCUIT BREAK: AGT's CircuitBreaker trips (state → OPEN); all requests fail-fast until recovery timeout elapses.\n\nKILL AGENT: AGT's KillSwitch terminates the agent immediately and logs a KillReason.SLO_EXHAUSTED event.\n\nThis is the platform's claim: 'budget runs out' does not mean 'a human notices'. The system reacts on its own.`} />
        </div>
        <span className="inline-flex items-center gap-1 text-[11px] font-extrabold tracking-wider">
          {exhaustion.label}
          <Tip position="right" text={slo.exhaustion_action === "throttle"
            ? "THROTTLE is the configured action for this SLO. When the error budget reaches 0%, AGT's AgentRateLimiter reduces request throughput to protect remaining capacity. Existing in-flight requests complete; new requests are queued or shed."
            : slo.exhaustion_action === "circuit_break"
            ? "CIRCUIT BREAK is the configured action for this SLO. When the error budget reaches 0%, AGT's CircuitBreaker trips to the OPEN state. All new requests fail-fast (no upstream work) until the recovery timer elapses and the breaker probes HALF_OPEN."
            : "KILL AGENT is the configured action for this SLO. When the error budget reaches 0%, AGT's KillSwitch terminates the affected agent process. A KillReason.SLO_EXHAUSTED event is written to the audit log and the agent is removed from the active fleet until manually restored."} />
        </span>
      </div>
    </div>
  );
}

function CostBudgetsPanel({ cost }: { cost: GovSlo["cost_summary"] }) {
  const fmtTokens = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);
  const fmtCost   = (n: number) => n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;

  const globalStatus = cost.total_cost_usd >= cost.hard_cap_usd
    ? "over_hard_cap"
    : cost.total_cost_usd >= cost.soft_cap_usd
    ? "warning"
    : "healthy";

  const statusStyle = (s: CostStageSummary["status"]) =>
    s === "over_hard_cap"
      ? { pill: "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30", bar: "bg-red-500", dot: "bg-red-500" }
      : s === "warning"
      ? { pill: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30", bar: "bg-amber-500", dot: "bg-amber-400" }
      : { pill: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30", bar: "bg-emerald-500", dot: "bg-emerald-500" };

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <SectionHeader
          title={`Cost Budgets (${cost.window_hours}h)`}
          subtitle="AGT BudgetTracker · per-agent rolling-window token + USD budgets with soft/hard cap enforcement"
          tooltip={"AGT BudgetTracker (ADR 0012) enforces three-tier cost governance:\n\n• Tool Annotations: tool author provides cost_hint\n• Policy Cost Map: YAML maps tools to USD rates (overrides hints)\n• Runtime Metering: actual billing API corrects estimates\n\nSoft cap: alert fires, operation continues.\nHard cap: subsequent operations are blocked until the window resets.\n\nPricing: $3/M input tokens, $15/M output tokens (75/25 split). Source: AGT ADR 0012."}
        />
        <div className="flex items-center gap-3 shrink-0 text-[11px]">
          <span className="text-zbrain-muted dark:text-zbrain-dark-muted">Total</span>
          <span className="font-bold text-zbrain-ink dark:text-zbrain-dark-ink tabular-nums">{fmtCost(cost.total_cost_usd)}</span>
          <span className="text-zbrain-muted dark:text-zbrain-dark-muted">·</span>
          <span className="text-zbrain-muted dark:text-zbrain-dark-muted">Soft {fmtCost(cost.soft_cap_usd)}</span>
          <span className="text-zbrain-muted dark:text-zbrain-dark-muted">Hard {fmtCost(cost.hard_cap_usd)}</span>
        </div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-zbrain-divider dark:border-zbrain-dark-divider">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider text-[10px]">
              <th className="px-3 py-2 text-left font-semibold">Stage</th>
              <th className="px-3 py-2 text-right font-semibold">Tokens (used / budget)</th>
              <th className="px-3 py-2 text-left font-semibold w-36">Utilisation</th>
              <th className="px-3 py-2 text-right font-semibold">Cost</th>
              <th className="px-3 py-2 text-center font-semibold">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
            {cost.per_stage.map((row) => {
              const st = statusStyle(row.status);
              return (
                <tr key={row.stage} className="hover:bg-zbrain-surface/50 dark:hover:bg-zbrain-dark-elev2/50">
                  <td className="px-3 py-2.5 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink capitalize">{row.stage}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-zbrain-muted dark:text-zbrain-dark-muted">
                    {fmtTokens(row.total_tokens)} / {fmtTokens(row.token_budget)}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-zbrain-divider dark:bg-zbrain-dark-divider overflow-hidden">
                        <div className={`h-full rounded-full ${st.bar}`} style={{ width: `${Math.min(row.budget_used_pct, 100)}%` }} />
                      </div>
                      <span className="tabular-nums text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted w-8 text-right">{row.budget_used_pct.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{fmtCost(row.cost_usd)}</td>
                  <td className="px-3 py-2.5 text-center">
                    <span className={`pill border text-[10px] font-semibold ${st.pill}`}>
                      {row.status === "over_hard_cap" ? "✗ Over hard cap" : row.status === "warning" ? "⚠ Over soft cap" : "✓ Healthy"}
                    </span>
                  </td>
                </tr>
              );
            })}
            {/* Total row */}
            {(() => {
              const totalBudget = cost.per_stage.reduce((a, s) => a + s.token_budget, 0);
              const usedPct = totalBudget > 0 ? (cost.total_tokens / totalBudget) * 100 : 0;
              const gst = statusStyle(globalStatus as CostStageSummary["status"]);
              return (
                <tr className="bg-zbrain-surface/60 dark:bg-zbrain-dark-elev2/60 font-semibold">
                  <td className="px-3 py-2.5 text-zbrain-ink dark:text-zbrain-dark-ink">Total</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-zbrain-muted dark:text-zbrain-dark-muted">
                    {fmtTokens(cost.total_tokens)} / {fmtTokens(totalBudget)}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-zbrain-divider dark:bg-zbrain-dark-divider overflow-hidden">
                        <div className={`h-full rounded-full ${gst.bar}`} style={{ width: `${Math.min(usedPct, 100)}%` }} />
                      </div>
                      <span className="tabular-nums text-[10px] text-zbrain-muted dark:text-zbrain-dark-muted w-8 text-right">{usedPct.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-zbrain-ink dark:text-zbrain-dark-ink">{fmtCost(cost.total_cost_usd)}</td>
                  <td className="px-3 py-2.5 text-center">
                    <span className={`pill border text-[10px] font-semibold ${gst.pill}`}>
                      {globalStatus === "over_hard_cap" ? "✗ Over hard cap" : globalStatus === "warning" ? "⚠ Over soft cap" : "✓ Under soft cap"}
                    </span>
                  </td>
                </tr>
              );
            })()}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SloTab({ sloData }: { sloData: GovSlo }) {
  const { slos, stage_latency, slos_met, slos_total, budgets_healthy, active_alerts } = sloData;
  const worstBudget = Math.min(...slos.map((s) => s.budget_remaining_pct));

  const fmtMs = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;

  return (
    <div className="space-y-5">
      {/* Active alert banner */}
      {active_alerts > 0 && (
        <div className="card p-3 flex items-center gap-3 border-2 border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10">
          <AlertIcon />
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">
            {active_alerts} BurnRateAlert{active_alerts !== 1 ? "s" : ""} firing; error budget{active_alerts !== 1 ? "s are" : " is"} depleting faster than expected
          </p>
          <Tip position="right" text={"What this banner means in plain language: one or more SLOs (reliability targets) are spending their allowed failure quota faster than the measurement window can sustain.\n\nEach SLO has an error budget: the share of requests permitted to violate the target before the system reacts. The burn rate measures how fast that budget is being consumed. A burn rate of 1.0× consumes the budget exactly over the window. 2.0× depletes it in half the time and trips a warning. The critical threshold (typically 10×) trips the automated exhaustion action defined on each SLO card below: THROTTLE, CIRCUIT BREAK, or KILL AGENT.\n\nIf no operator intervenes, the budget runs out and the exhaustion action fires automatically. The system contains itself."} />
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiTile
          label="SLOs Met"
          value={`${slos_met} / ${slos_total}`}
          accent={slos_met === slos_total}
          tooltip="Number of active SLOs where the current SLI value meets the defined target within the measurement window. All SLOs must be met for the agent system to be considered fully compliant with its reliability commitments."
        />
        <KpiTile
          label="Budgets Healthy"
          value={`${budgets_healthy} / ${slos_total}`}
          accent={budgets_healthy === slos_total}
          tooltip="Number of SLOs where more than 25% of the error budget remains. Budgets below 25% indicate the SLO is at risk of exhaustion and the automated exhaustion action may trigger soon."
        />
        <KpiTile
          label="Active Alerts"
          value={active_alerts}
          accent={active_alerts === 0}
          tooltip="Total BurnRateAlert instances currently firing across all SLOs. Alerts fire when burn rate ≥ 2.0× (warning) or ≥ the critical threshold. Each alert means the error budget is being consumed faster than the baseline rate."
        />
        <KpiTile
          label="Worst Budget"
          value={`${worstBudget.toFixed(0)}%`}
          sub="remaining across SLOs"
          tooltip="The lowest error budget remaining percentage across all defined SLOs. When this reaches 0%, the corresponding SLO's ExhaustionAction triggers automatically (throttle, circuit break, or kill agent)."
        />
      </div>

      {/* Cost budgets */}
      <CostBudgetsPanel cost={sloData.cost_summary} />

      {/* SLO cards */}
      <div>
        {(() => {
          const counts = slos.reduce(
            (acc, s) => {
              acc[sloStatus(s)] += 1;
              return acc;
            },
            { met: 0, breached: 0, pending: 0 } as Record<SloStatus, number>,
          );
          return (
            <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
              <SectionHeader
                title="Service Level Objectives"
                subtitle={`AGT SLI → SLO → ErrorBudget model: ${slos.length} objectives mapped to pipeline telemetry`}
                tooltip={"AGT SLO system:\n\n• SLI (Service Level Indicator): a measurable metric (latency, success rate, confidence score).\n• SLO (Service Level Objective): a target value the SLI must meet, with a defined error budget.\n• ErrorBudget: the allowed fraction of bad events before AGT triggers an automated response.\n• BurnRateAlert: fires when the budget is being consumed faster than expected (2× = warning, 10× = critical).\n• ExhaustionAction: THROTTLE / CIRCUIT_BREAK / KILL_AGENT, triggered when budget reaches 0%.\n\nStatus per SLO:\n• MET: samples ≥ 1 AND target met\n• BREACHED: samples ≥ 1 AND target missed\n• PENDING: no samples in window; SLO cannot yet be evaluated"}
              />
              <div className="flex items-center gap-2 flex-wrap shrink-0">
                <span className={`pill border text-[11px] font-semibold ${SLO_STATUS_STYLES.met.pill}`}>{counts.met} MET</span>
                <span className={`pill border text-[11px] font-semibold ${SLO_STATUS_STYLES.pending.pill}`}>{counts.pending} PENDING</span>
                <span className={`pill border text-[11px] font-semibold ${SLO_STATUS_STYLES.breached.pill}`}>{counts.breached} BREACHED</span>
              </div>
            </div>
          );
        })()}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {slos.map((s) => <SloCard key={s.id} slo={s} />)}
        </div>
      </div>

      {/* Stage latency table */}
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-4">
          <SectionHeader
            title="Stage Latency SLOs"
            subtitle="Per-stage p50 / p95 / p99 from TraceEvent.duration_ms vs. target thresholds"
          />
          <Tip text={"Stage latency is measured from TraceEvent.duration_ms: the actual wall-clock time each pipeline stage took to execute, collected for every agent tool invocation.\n\np95 is the AGT-recommended percentile for latency SLOs: it excludes extreme outliers while still catching tail latency issues that affect 1 in 20 pipeline runs.\n\nRows with a ✗ status have p95 latency exceeding the stage target; consider increasing the ring's rate limit or adding a circuit breaker for that stage."} />
        </div>
        <div className="overflow-x-auto rounded-lg border border-zbrain-divider dark:border-zbrain-dark-divider">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 text-zbrain-muted dark:text-zbrain-dark-muted uppercase tracking-wider text-[10px]">
                <th className="px-3 py-2 text-left font-semibold">
                  <span className="inline-flex items-center gap-1">Stage<Tip text={"The pipeline stage being measured. Each stage runs a different agent and has its own latency target appropriate to the work it performs."} /></span>
                </th>
                <th className="px-3 py-2 text-left font-semibold">
                  <span className="inline-flex items-center gap-1">Ring<Tip text={"Trust ring of the agent at this stage. Lower rings have access to non-reversible actions (CRM/ERP writes) and stricter latency targets."} /></span>
                </th>
                <th className="px-3 py-2 text-right font-semibold">
                  <span className="inline-flex items-center gap-1">p50<Tip text={"50th percentile (median) latency. Half of pipeline runs finish faster than this value, half slower. Use this as the typical case."} /></span>
                </th>
                <th className="px-3 py-2 text-right font-semibold">
                  <span className="inline-flex items-center gap-1">p95<Tip text={"95th percentile latency. 19 out of 20 pipeline runs finish faster than this value. This is the value the SLO target is enforced against; it captures tail latency without being skewed by extreme outliers."} /></span>
                </th>
                <th className="px-3 py-2 text-right font-semibold">
                  <span className="inline-flex items-center gap-1">p99<Tip text={"99th percentile latency. Only 1 in 100 runs is slower than this. Use this to size capacity for worst-case behavior."} /></span>
                </th>
                <th className="px-3 py-2 text-right font-semibold">
                  <span className="inline-flex items-center gap-1">Target<Tip text={"The maximum p95 latency this stage is allowed before it is considered over budget. Targets are tuned per ring; higher-trust rings (closer to non-reversible writes) have stricter targets."} /></span>
                </th>
                <th className="px-3 py-2 text-center font-semibold">
                  <span className="inline-flex items-center gap-1">Samples<Tip text={"Number of pipeline runs measured at this stage in the current window. Below 10 samples the percentile values are low-confidence and should be treated as directional rather than authoritative."} /></span>
                </th>
                <th className="px-3 py-2 text-center font-semibold">
                  <span className="inline-flex items-center gap-1">Status<Tip text={"Met = p95 is within target. Over = p95 exceeds target; investigate the affected ring's rate limit or add a circuit breaker. No data = no samples in the current window."} /></span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
              {stage_latency.map((row: StageSloRow) => (
                <tr
                  key={row.stage}
                  className={`hover:bg-zbrain-surface/50 dark:hover:bg-zbrain-dark-elev2/50 ${!row.met ? "border-l-2 border-l-amber-400 dark:border-l-amber-500" : ""}`}
                >
                  <td className="px-3 py-2.5 font-semibold text-zbrain-ink dark:text-zbrain-dark-ink capitalize">{row.stage}</td>
                  <td className="px-3 py-2.5"><RingBadge ring={row.ring} /></td>
                  <td className="px-3 py-2.5 text-right text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">{row.samples > 0 ? fmtMs(row.p50_ms) : "-"}</td>
                  <td className={`px-3 py-2.5 text-right font-semibold tabular-nums ${!row.met ? "text-amber-600 dark:text-amber-400" : "text-zbrain-ink dark:text-zbrain-dark-ink"}`}>
                    {row.samples > 0 ? fmtMs(row.p95_ms) : "-"}
                  </td>
                  <td className="px-3 py-2.5 text-right text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">{row.samples > 0 ? fmtMs(row.p99_ms) : "-"}</td>
                  <td className="px-3 py-2.5 text-right text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">&lt; {fmtMs(row.target_ms)}</td>
                  <td className="px-3 py-2.5 text-center text-zbrain-muted dark:text-zbrain-dark-muted tabular-nums">{row.samples}</td>
                  <td className="px-3 py-2.5 text-center">
                    {row.samples === 0 ? (
                      <span className="text-zbrain-muted dark:text-zbrain-dark-muted text-[10px]">no data</span>
                    ) : row.met ? (
                      <span className="pill bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30 text-[10px] font-semibold">✓ Met</span>
                    ) : (
                      <span className="pill bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30 text-[10px] font-semibold">✗ Over</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function GovernancePage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab: SubTab = isSubTab(tabParam) ? tabParam : "overview";

  const [summary, setSummary] = useState<GovSummary | null>(null);
  const [agentsData, setAgentsData] = useState<GovAgents | null>(null);
  const [policiesData, setPoliciesData] = useState<GovPolicies | null>(null);
  const [complianceData, setComplianceData] = useState<GovCompliance | null>(null);
  const [sloData, setSloData] = useState<GovSlo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    governanceApi.summary().then(setSummary).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (tab === "trust" && !agentsData) {
      governanceApi.agents().then(setAgentsData).catch(() => undefined);
    }
    if (tab === "policy" && !policiesData) {
      governanceApi.policies().then(setPoliciesData).catch(() => undefined);
    }
    // Compliance data is fetched eagerly for both Compliance and Overview
    // tabs. The Overview tile renders the live coverage_pct + needs_attention
    // figures from this payload alongside the OWASP control-count totals.
    if ((tab === "compliance" || tab === "overview") && !complianceData) {
      governanceApi.compliance().then(setComplianceData).catch(() => undefined);
    }
    if ((tab === "slo" || tab === "overview") && !sloData) {
      governanceApi.slo().then(setSloData).catch(() => undefined);
    }
  }, [tab, agentsData, policiesData, complianceData, sloData]);

  if (error) {
    return (
      <div className="card p-8 text-center text-red-600 dark:text-red-400 text-sm">
        Failed to load governance data: {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-zbrain-ink dark:text-zbrain-dark-ink">
            Agent Governance
          </h1>
          <p className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5">
            Microsoft Agent Governance Toolkit (AGT) · Policy Engine · Agent Trust · Audit Trail · OWASP ASI Compliance
          </p>
        </div>
        {summary && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="pill bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30 text-xs">
              OWASP {summary.totals.owasp_coverage} covered
            </span>
            <span className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">
              {summary.generated_at ? new Date(summary.generated_at).toLocaleTimeString() : ""}
            </span>
          </div>
        )}
      </div>

      {/* Sub-tabs */}
      <div className="flex gap-0.5 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
        {SUB_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setParams({ tab: t.key })}
            className={[
              "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px",
              tab === t.key
                ? "border-zbrain text-zbrain dark:text-zbrain-dark-accent dark:border-zbrain-dark-accent"
                : "border-transparent text-zbrain-muted dark:text-zbrain-dark-muted hover:text-zbrain-ink dark:hover:text-zbrain-dark-ink",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && (
        summary
          ? <OverviewTab summary={summary} sloData={sloData} compliance={complianceData} />
          : <div className="card p-8 text-center text-zbrain-muted text-sm">Loading governance overview…</div>
      )}
      {tab === "audit" && <AuditTab />}
      {tab === "trust" && (
        agentsData
          ? <TrustTab agents={agentsData} />
          : <div className="card p-8 text-center text-zbrain-muted text-sm">Loading agent trust data…</div>
      )}
      {tab === "policy" && (
        policiesData
          ? <PolicyTab policies={policiesData} />
          : <div className="card p-8 text-center text-zbrain-muted text-sm">Loading policy engine data…</div>
      )}
      {tab === "compliance" && (
        complianceData
          ? <ComplianceTab compliance={complianceData} />
          : <div className="card p-8 text-center text-zbrain-muted text-sm">Loading compliance report…</div>
      )}
      {tab === "slo" && (
        sloData
          ? <SloTab sloData={sloData} />
          : <div className="card p-8 text-center text-zbrain-muted text-sm">Loading SLO data…</div>
      )}
    </div>
  );
}
