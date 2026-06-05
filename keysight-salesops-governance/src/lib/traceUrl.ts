/**
 * traceUrl: cross-app helper that builds an absolute URL to the SalesOps
 * Trace page for a given pipeline. The Governance app is a separate Vite
 * deployment; a relative `/trace/...` link incorrectly resolves inside the
 * Governance SPA. Every "open trace" callsite must route through this helper
 * so the destination is the live SalesOps Trace page.
 *
 * Base URL precedence:
 *   1. VITE_SALESOPS_BASE_URL env var (set per environment).
 *   2. Inferred from the current origin by swapping the Governance base path
 *      (`/keysight-salesops-governance/`) for the SalesOps base path
 *      (`/keysight-salesops/`). This works for the production deployment at
 *      app.solution.zbrain.ai and any equivalently provisioned environment.
 *   3. `http://localhost:5173/keysight-salesops` as the local-dev default.
 *
 * The returned URL always points at `/{base}/trace/{pipelineId}` and is
 * intended to be opened in a new tab with rel="noopener noreferrer".
 */

const GOVERNANCE_BASE = "/keysight-salesops-governance";
const SALESOPS_BASE_PATH = "/keysight-salesops";
// In local development the Governance app runs on port 5175 and the SalesOps
// app runs on port 5173. The previous default pointed at 5173 unconditionally,
// which 404'd because the inferFromOrigin fallback combined the Governance
// origin (`localhost:5175`) with the SalesOps base path. The explicit default
// captures the cross-port hop so local-dev cross-app links resolve.
const LOCAL_DEFAULT = "http://localhost:5173/keysight-salesops";

function stripTrailingSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

function inferFromOrigin(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const origin = window.location.origin;
    // Local dev: Governance app is served from Vite on :5175 while SalesOps
    // is served from Vite on :5173. The two apps live on different ports, so
    // we cannot reuse the Governance origin; we must rewrite the host port
    // before appending the SalesOps base path.
    if (origin.includes("localhost:5175") || origin.includes("127.0.0.1:5175")) {
      return "http://localhost:5173/keysight-salesops";
    }
    // Production / staging: same host, SalesOps lives at /keysight-salesops/.
    // Distinguish based on whether the current pathname includes the
    // Governance base. If yes, swap; otherwise return null so we fall through.
    const path = window.location.pathname || "";
    if (path.startsWith(GOVERNANCE_BASE)) {
      return `${origin}${SALESOPS_BASE_PATH}`;
    }
    return null;
  } catch {
    return null;
  }
}

export function salesOpsBase(): string {
  const explicit = (import.meta as any).env?.VITE_SALESOPS_BASE_URL as string | undefined;
  if (explicit) return stripTrailingSlash(explicit);
  const inferred = inferFromOrigin();
  if (inferred) return stripTrailingSlash(inferred);
  return LOCAL_DEFAULT;
}

/**
 * Build a fully-qualified SalesOps Trace URL for the given pipeline. Callers
 * should render this as <a href={traceUrl(id)} target="_blank" rel="noopener noreferrer" />.
 */
export function traceUrl(pipelineId: number | string): string {
  return `${salesOpsBase()}/trace/${pipelineId}`;
}

/**
 * Build a fully-qualified SalesOps Inbox URL. The Governance app does not
 * host an inbox; this helper points the operator at the SalesOps inbox where
 * inbound mail and per-message processing live.
 */
export function inboxUrl(query?: Record<string, string | number | undefined>): string {
  const base = `${salesOpsBase()}/inbox`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

/**
 * Build a fully-qualified SalesOps HITL queue URL, optionally scoped to a
 * pipeline. Used by Governance surfaces that surface "awaiting CSR" rows and
 * need to hand the operator off to the live HITL queue in SalesOps.
 */
export function hitlUrl(pipelineId?: number | string): string {
  const base = `${salesOpsBase()}/hitl`;
  return pipelineId != null ? `${base}?pipeline=${pipelineId}` : base;
}

/**
 * Build a fully-qualified SalesOps Knowledge Base URL, optionally scoped to a
 * specific namespace and rule key. Used by Continuous Learning suggestions
 * that need to deep-link into the editable rule in SalesOps.
 */
export function kbUrl(namespace?: string, ruleKey?: string, extra?: Record<string, string>): string {
  const base = `${salesOpsBase()}/kb`;
  if (!namespace && !ruleKey && !extra) return base;
  const params = new URLSearchParams();
  if (namespace) params.set("ns", namespace);
  if (ruleKey) params.set("key", ruleKey);
  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v != null && v !== "") params.set(k, v);
    }
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}
