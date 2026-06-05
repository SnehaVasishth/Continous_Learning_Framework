export type Theme = "light";

const STORAGE_KEY = "zbrain.theme";

function forceLight() {
  if (typeof window === "undefined") return;
  const root = document.documentElement;
  root.classList.remove("dark");
  // Clear any prior dark / system preference left in localStorage so a
  // returning user does not get the old theme flashed back in.
  try {
    window.localStorage.setItem(STORAGE_KEY, "light");
  } catch {
    /* ignore storage failures */
  }
}

/** Hook stub kept for callers; product is locked to light mode. */
export function useTheme() {
  return {
    theme: "light" as const,
    setTheme: (_t: Theme) => forceLight(),
    toggle: () => forceLight(),
    cycle: () => forceLight(),
  };
}

/** Synchronous bootstrap called once at app start (in main.tsx) before
 *  first render. Hard-forces the light theme. */
export function bootstrapTheme() {
  forceLight();
}
