import { useEffect, useState, useCallback } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "zbrain.theme";

function applyTheme(t: Theme) {
  // Light is the canonical product theme. "system" resolves to whatever the
  // OS picks; user can still cycle to dark explicitly if they want it.
  const resolved = t === "system" ? "light" : t;
  const root = document.documentElement;
  if (resolved === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
}

/** SSR-safe initial pick — resolves at hook call time. Defaults to light. */
function readStored(): Theme {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem(STORAGE_KEY) as Theme | null;
  if (saved === "light" || saved === "dark" || saved === "system") return saved;
  return "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStored);

  // Apply on mount + when theme changes
  useEffect(() => {
    applyTheme(theme);
    if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  // React to OS-level changes when in "system" mode
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((cur) => {
      const resolved = cur === "system"
        ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
        : cur;
      return resolved === "dark" ? "light" : "dark";
    });
  }, []);

  const cycle = useCallback(() => {
    setTheme((cur) => (cur === "light" ? "dark" : cur === "dark" ? "system" : "light"));
  }, []);

  // Pre-init the dark class as early as possible (useful when hook runs late)
  useEffect(() => {
    applyTheme(readStored());
  }, []);

  return { theme, setTheme, toggle, cycle };
}

/** Synchronous bootstrap — call once at app start (in main.tsx) BEFORE first render
 * to avoid a light → dark flash for users who prefer dark. */
export function bootstrapTheme() {
  if (typeof window === "undefined") return;
  applyTheme(readStored());
}
