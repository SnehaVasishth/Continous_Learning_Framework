import { Link } from "react-router-dom";

import type { ReadinessBlocker } from "../api";
import { useReadiness } from "../hooks/useReadiness";

const PROVIDER_LABEL: Record<string, string> = {
  salesforce: "Salesforce",
  sharepoint: "SharePoint",
  mailbox: "Mailbox",
  llm: "LLM",
};

export function ReadinessBanner() {
  const { report } = useReadiness();
  if (!report) return null;
  // Demo mode shows a red sandbox badge regardless of blockers, so the
  // operator always knows local fallbacks are in play.
  if (report.demo_mode) {
    return (
      <div className="bg-rose-700 text-white text-[12.5px] font-medium px-5 py-2 flex items-center gap-3">
        <span className="pill bg-white/15 text-white border border-white/30 uppercase tracking-wide text-[10px]">
          Demo mode
        </span>
        <span>
          Local fallbacks enabled (ENABLE_DEMO_FALLBACKS=1). The pipeline writes to local DB / outputs/ when external services are missing. Never enable this in production.
        </span>
        <Link to="/settings/integrations" className="ml-auto underline whitespace-nowrap">
          Open Integrations →
        </Link>
      </div>
    );
  }
  if (report.ok && report.warnings.length === 0) return null;
  // Red blockers take priority. Amber warnings only show when there are no blockers.
  if (report.blockers.length > 0) {
    return (
      <div className="bg-rose-600 text-white px-5 py-2.5 text-[12.5px] flex items-start gap-3 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-white font-semibold tracking-wide uppercase text-[10px]">System blocked</span>
          <span className="pill bg-white/15 text-white border border-white/30 uppercase tracking-wide text-[10px]">
            {report.blockers.length} issue{report.blockers.length === 1 ? "" : "s"}
          </span>
        </div>
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 flex-1">
          {report.blockers.map((b: ReadinessBlocker) => (
            <li key={b.provider} className="inline-flex items-center gap-1.5">
              <span className="font-semibold">{PROVIDER_LABEL[b.provider] || b.provider}:</span>
              <span className="text-white/90">{b.title}</span>
              <Link to={b.fix_url} className="underline whitespace-nowrap">
                Connect now →
              </Link>
            </li>
          ))}
        </ul>
        <span className="text-white/75 italic shrink-0">
          New email processing is paused until the system is reconnected.
        </span>
      </div>
    );
  }
  // Amber warnings (placeholders enabled but missing config, etc.)
  return (
    <div className="bg-amber-100 text-amber-900 border-b border-amber-200 px-5 py-2 text-[12.5px] flex items-start gap-3 flex-wrap">
      <span className="pill bg-amber-200/80 text-amber-900 uppercase tracking-wide text-[10px] shrink-0">Warnings</span>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 flex-1">
        {report.warnings.map((w: ReadinessBlocker) => (
          <li key={w.provider + w.title} className="inline-flex items-center gap-1.5">
            <span className="font-semibold">{w.title}:</span>
            <span>{w.detail}</span>
            <Link to={w.fix_url} className="underline whitespace-nowrap">
              Configure →
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
