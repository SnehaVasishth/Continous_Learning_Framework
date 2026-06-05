import { createContext, useContext, useEffect, useState } from "react";

import { api, ReadinessReport } from "../api";

type ReadinessState = {
  report: ReadinessReport | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

export const ReadinessContext = createContext<ReadinessState>({
  report: null,
  loading: true,
  error: null,
  refresh: async () => {},
});

export function useReadinessProvider(pollMs = 10000): ReadinessState {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const r = await api.system.readiness();
      setReport(r);
      setError(null);
    } catch (e: any) {
      setError(e?.message || "readiness fetch failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      if (cancel) return;
      await refresh();
    };
    tick();
    const id = setInterval(tick, pollMs);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [pollMs]);

  return { report, loading, error, refresh };
}

export function useReadiness(): ReadinessState {
  return useContext(ReadinessContext);
}

export function isReadyToRun(report: ReadinessReport | null): boolean {
  if (!report) return false;
  return report.ok === true;
}
