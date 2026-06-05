import { useEffect, useState } from "react";

/**
 * Appearance settings for the project's branding surfaces.
 *
 * Drives the logo, brand name, solution suffix, primary colour, and font on
 * both the SalesOps front-end and the Orchestrator back-end. Persists in
 * `localStorage` until the backend settings store is wired; mutations
 * notify every subscribed component via a custom DOM event so the header
 * updates instantly when someone saves a change on the Appearance page.
 */

export type Appearance = {
  logoUrl: string;
  brandName: string;
  solutionLabel: string;
  primaryHex: string;
  fontFamily: string;
};

const STORE_KEY = "zbrain-orchestrator:appearance";
const EVT = "zbrain-orchestrator:appearance:changed";

export const DEFAULTS: Appearance = {
  // Stored as path under the orchestrator's BASE_URL; resolved at render time
  // so both dev (/keysight-salesops-governance/keysight-logo.png) and prod
  // serve the same asset without re-hardcoding the base.
  logoUrl: "keysight-logo.png",
  brandName: "Keysight",
  solutionLabel: "SalesOps",
  primaryHex: "#1A55F9",
  fontFamily: "Inter, system-ui, -apple-system, Segoe UI, sans-serif",
};

export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULTS, ...parsed };
  } catch {
    return DEFAULTS;
  }
}

export function saveAppearance(next: Partial<Appearance>): Appearance {
  const cur = loadAppearance();
  const merged: Appearance = { ...cur, ...next };
  try { localStorage.setItem(STORE_KEY, JSON.stringify(merged)); } catch { /* noop */ }
  // Fan out to every listening component in the same tab.
  try { window.dispatchEvent(new CustomEvent(EVT, { detail: merged })); } catch { /* noop */ }
  return merged;
}

export function resetAppearance(): Appearance {
  try { localStorage.removeItem(STORE_KEY); } catch { /* noop */ }
  try { window.dispatchEvent(new CustomEvent(EVT, { detail: DEFAULTS })); } catch { /* noop */ }
  return DEFAULTS;
}

export function useAppearance(): Appearance {
  const [state, setState] = useState<Appearance>(() => loadAppearance());
  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<Appearance>).detail;
      if (detail) setState(detail);
      else setState(loadAppearance());
    };
    // Cross-tab updates land via the storage event too.
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORE_KEY) setState(loadAppearance());
    };
    window.addEventListener(EVT, onChange as EventListener);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(EVT, onChange as EventListener);
      window.removeEventListener("storage", onStorage);
    };
  }, []);
  return state;
}

export function resolveLogo(path: string): string {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith("/")) return path;
  // Treat as relative to the Vite base path so dev + prod stay consistent.
  const base = (import.meta as any).env?.BASE_URL || "/";
  return `${base}${path}`;
}
