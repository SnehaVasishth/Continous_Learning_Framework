import { useEffect, useRef, useState } from "react";

/**
 * Lightweight 15-second polling hook. Every governance page uses this so the
 * dashboard reflects the live state of the SalesOps backend without manual
 * refresh.
 *
 * - Calls `loader()` on mount and every `intervalMs` thereafter.
 * - Cancels in-flight requests on unmount.
 * - Surfaces { data, loading (first fetch only), error, lastFetchedAt, refresh }.
 * - `refresh()` triggers an immediate fetch without waiting for the timer.
 */
export function usePolling<T>(
  loader: () => Promise<T>,
  intervalMs: number = 15_000,
): {
  data: T | null;
  loading: boolean;
  error: string | null;
  lastFetchedAt: Date | null;
  refresh: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const aliveRef = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const fetchOnce = async () => {
    try {
      const next = await loaderRef.current();
      if (!aliveRef.current) return;
      setData(next);
      setError(null);
      setLastFetchedAt(new Date());
    } catch (e: any) {
      if (!aliveRef.current) return;
      setError(String(e?.message || e));
    } finally {
      if (aliveRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    aliveRef.current = true;
    fetchOnce();
    const id = setInterval(fetchOnce, intervalMs);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { data, loading, error, lastFetchedAt, refresh: fetchOnce };
}
