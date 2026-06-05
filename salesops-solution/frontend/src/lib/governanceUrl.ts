/**
 * governanceUrl: cross-app helper that builds a URL to the ZBrain Orchestrator
 * (governance) app. The SalesOps SPA and the Governance SPA are deployed under
 * sibling base paths on the same origin; React Router only honours the
 * SalesOps basename, so a bare `/learning` from SalesOps would dead-end inside
 * the SalesOps router. Every cross-app link must route through this helper so
 * the destination resolves at the live Governance app.
 *
 * Base URL precedence:
 *   1. VITE_GOVERNANCE_BASE_URL env var (set per environment).
 *   2. Inferred from the current origin by anchoring to the Governance base
 *      path (`/keysight-salesops-governance/`). This works for the production
 *      deployment at app.solution.zbrain.ai and any equivalently provisioned
 *      environment where the two apps live under the same origin.
 *   3. `http://localhost:5174/keysight-salesops-governance` as the local-dev
 *      default.
 *
 * The returned URL always points at `/{base}/{path}` with the leading slash
 * normalised away. Intended for use with `<a href={...}>` (cross-app links
 * cannot use react-router-dom <Link>).
 */

const GOVERNANCE_BASE_PATH = "/keysight-salesops-governance";
// In local development the Governance app runs on port 5175 (Vite). The
// SalesOps app runs on port 5173. The previous default pointed at 5174 which
// is not the live Governance port and caused cross-app links to 404 until
// VITE_GOVERNANCE_BASE_URL was set manually.
const LOCAL_DEFAULT = "http://localhost:5175/keysight-salesops-governance";

function stripTrailingSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

function inferFromOrigin(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const origin = window.location.origin;
    // Local dev: SalesOps is served from Vite on :5173 while Governance is
    // served from Vite on :5175. The two apps live on different ports, so we
    // cannot reuse the SalesOps origin; we must rewrite the host port before
    // appending the Governance base path.
    if (origin.includes("localhost:5173") || origin.includes("127.0.0.1:5173")) {
      return "http://localhost:5175/keysight-salesops-governance";
    }
    return `${origin}${GOVERNANCE_BASE_PATH}`;
  } catch {
    return null;
  }
}

export function governanceBase(): string {
  const explicit = (import.meta as any).env?.VITE_GOVERNANCE_BASE_URL as string | undefined;
  if (explicit) return stripTrailingSlash(explicit);
  const inferred = inferFromOrigin();
  if (inferred) return stripTrailingSlash(inferred);
  return LOCAL_DEFAULT;
}

/**
 * Build a fully-qualified Governance URL for an internal Governance route.
 * The input path may include a leading slash; it is normalised.
 *
 * Examples:
 *   governanceUrl("integrations")              -> "/keysight-salesops-governance/integrations"
 *   governanceUrl("/integrations")             -> "/keysight-salesops-governance/integrations"
 *   governanceUrl("learning?tab=baselines")    -> "/keysight-salesops-governance/learning?tab=baselines"
 */
export function governanceUrl(path: string): string {
  const trimmed = path.replace(/^\/+/, "");
  return `${governanceBase()}/${trimmed}`;
}

/**
 * Convenience for the most common Governance link target: the Continuous
 * Learning page, optionally filtered to a baseline or tab.
 */
export function learningUrl(opts?: { tab?: string; baselineId?: number | string; rcaId?: number | string }): string {
  const params = new URLSearchParams();
  if (opts?.tab) params.set("tab", opts.tab);
  if (opts?.baselineId != null) params.set("baseline_id", String(opts.baselineId));
  if (opts?.rcaId != null) params.set("rca", String(opts.rcaId));
  const qs = params.toString();
  return governanceUrl(qs ? `learning?${qs}` : "learning");
}

/**
 * Convenience for the Integrations page in Governance.
 */
export function integrationsUrl(): string {
  return governanceUrl("integrations");
}
