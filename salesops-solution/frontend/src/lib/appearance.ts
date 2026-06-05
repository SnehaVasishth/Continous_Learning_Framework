import { useEffect, useState } from "react";

/**
 * Read-side mirror of the Orchestrator's appearance store.
 *
 * The SalesOps front-end consumes the same `localStorage` key the
 * Orchestrator writes (and the storage event fires across tabs on the same
 * origin, since both apps live under the same host). Defaults match the
 * Keysight SalesOps demo brand so a fresh install renders correctly even
 * before the operator opens Appearance settings for the first time.
 */

export type Appearance = {
  logoUrl: string;
  brandName: string;
  solutionLabel: string;
  primaryHex: string;
  fontFamily: string;
};

const STORE_KEY = "zbrain-orchestrator:appearance";

export const DEFAULTS: Appearance = {
  // SalesOps serves the logo from its own /public; resolveLogo() falls back
  // to that local copy when the stored path is a bare filename.
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

export function useAppearance(): Appearance {
  const [state, setState] = useState<Appearance>(() => loadAppearance());
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORE_KEY) setState(loadAppearance());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  return state;
}

export function resolveLogo(path: string): string {
  if (!path) return "";
  if (path.startsWith("data:")) return path;
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith("/")) return path;
  const base = (import.meta as any).env?.BASE_URL || "/";
  return `${base}${path}`;
}
