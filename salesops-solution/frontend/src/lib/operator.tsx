/**
 * Current-operator context.
 *
 * The Continuous Learning page (and any future audit-bearing surface) needs a
 * stable, real identity for the person performing actions. We use the live
 * Salesforce user directory (GET /api/sf-users) as the identity source so
 * the audit trail records a real Salesforce User Id and Name, not a
 * free-text "by qa" string.
 *
 * The user selects a current operator once via the header picker; the
 * selection persists in localStorage. Promote / rollback / retire endpoints
 * require the selected operator to be on the rule-owner allow-list (server
 * side), so the picker also surfaces the badge.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";

export type SfUser = {
  id: string;
  name: string;
  username: string | null;
  email: string | null;
  is_rule_owner: boolean;
  rule_owner_label: string | null;
};

const STORAGE_KEY = "currentOperatorId";

type OperatorState = {
  users: SfUser[];
  loaded: boolean;
  error: string | null;
  current: SfUser | null;
  setCurrentId: (id: string | null) => void;
  refresh: () => Promise<void>;
};

const OperatorContext = createContext<OperatorState | null>(null);

export function OperatorProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<SfUser[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentId, setCurrentIdState] = useState<string | null>(() => {
    try { return localStorage.getItem(STORAGE_KEY) || null; } catch { return null; }
  });

  const fetchUsers = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch("/api/sf-users");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const list: SfUser[] = await res.json();
      setUsers(list);
      // If no operator chosen yet, default to the first rule owner so the
      // demo doesn't open with a 403 on every learning action.
      if (!currentId && list.length > 0) {
        const firstOwner = list.find((u) => u.is_rule_owner) || list[0];
        if (firstOwner) {
          setCurrentIdState(firstOwner.id);
          try { localStorage.setItem(STORAGE_KEY, firstOwner.id); } catch {}
        }
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoaded(true);
    }
  }, [currentId]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const setCurrentId = useCallback((id: string | null) => {
    setCurrentIdState(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {}
  }, []);

  const current = useMemo(() => users.find((u) => u.id === currentId) || null, [users, currentId]);

  const value: OperatorState = { users, loaded, error, current, setCurrentId, refresh: fetchUsers };
  return <OperatorContext.Provider value={value}>{children}</OperatorContext.Provider>;
}

export function useOperator(): OperatorState {
  const ctx = useContext(OperatorContext);
  if (!ctx) throw new Error("useOperator must be used inside <OperatorProvider>");
  return ctx;
}
