/**
 * BaselineFilter: small select that scopes a Continuous Learning surface to a
 * single baseline. Renders as a compact pill button that opens a searchable
 * dropdown. "All baselines" is always the first option. Once a baseline is
 * selected, the active label is rendered inline with an "×" affordance to
 * clear back to "All".
 *
 * Reads from /api/learning/baselines on first mount and caches the result in
 * a module-level cache so multiple tabs on the same page do not re-fetch.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type BaselineAnchor } from "../api";

let _cache: BaselineAnchor[] | null = null;
let _inflight: Promise<BaselineAnchor[]> | null = null;

async function loadBaselines(): Promise<BaselineAnchor[]> {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  _inflight = api
    .learningBaselines()
    .then((d) => {
      _cache = Array.isArray(d?.items) ? d.items : [];
      return _cache;
    })
    .catch(() => {
      _cache = [];
      return _cache;
    })
    .finally(() => {
      _inflight = null;
    });
  return _inflight;
}

/** Invalidate the cache. Call when a baseline is created or deleted. */
export function invalidateBaselineCache(): void {
  _cache = null;
}

/**
 * useBaselineLookup: return a synchronous lookup function that resolves a
 * baseline anchor by id. Backed by the same module-level cache the picker
 * uses, so the first call mounts a single fetch and subsequent rows share
 * the result. Returns null while the cache is warming.
 */
export function useBaselineLookup(): (id: number | null | undefined) => BaselineAnchor | null {
  const [items, setItems] = useState<BaselineAnchor[]>(_cache || []);
  useEffect(() => {
    let cancel = false;
    loadBaselines().then((d) => {
      if (!cancel) setItems(d);
    });
    return () => {
      cancel = true;
    };
  }, []);
  return (id) => {
    if (id == null) return null;
    return items.find((b) => b.id === id) || null;
  };
}

type BaselineFilterProps = {
  value: number | null;
  onChange: (id: number | null) => void;
  className?: string;
};

function statusDot(status: BaselineAnchor["last_status"]): string {
  switch (status) {
    case "breached":
      return "bg-rose-500";
    case "drifting":
      return "bg-amber-500";
    case "healthy":
      return "bg-emerald-500";
    default:
      return "bg-slate-300";
  }
}

export function BaselineFilter({ value, onChange, className = "" }: BaselineFilterProps) {
  const [items, setItems] = useState<BaselineAnchor[]>(_cache || []);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancel = false;
    loadBaselines().then((d) => {
      if (!cancel) setItems(d);
    });
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const selected = useMemo(
    () => (value == null ? null : items.find((b) => b.id === value) || null),
    [value, items],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((b) => {
      const lbl = (b.label || "").toLowerCase();
      const seg = (b.segment || "").toLowerCase();
      const met = (b.metric || "").toLowerCase();
      return lbl.includes(q) || seg.includes(q) || met.includes(q);
    });
  }, [items, query]);

  return (
    <div ref={wrapRef} className={`relative inline-flex items-center gap-1.5 ${className}`}>
      <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">
        Baseline
      </span>
      {selected ? (
        <span className="inline-flex items-center gap-1 rounded-md border border-zbrain/30 bg-zbrain-50 text-zbrain text-[11px] font-medium px-2 py-1 max-w-[260px]">
          <span className={`w-1.5 h-1.5 rounded-full ${statusDot(selected.last_status)}`} aria-hidden />
          <span className="truncate" title={selected.label || `Baseline #${selected.id}`}>
            {selected.label || `Baseline #${selected.id}`}
          </span>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="ml-0.5 text-zbrain-muted hover:text-zbrain-ink text-xs leading-none"
            aria-label="Clear baseline filter"
            title="Clear filter"
          >
            ×
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md border border-zbrain-divider bg-white text-zbrain-ink hover:bg-zbrain-50 text-[11px] font-medium px-2 py-1"
        >
          All baselines
          <span className="text-zbrain-muted text-[10px]">▾</span>
        </button>
      )}

      {!selected && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="sr-only"
          aria-label="Open baseline picker"
        >
          open
        </button>
      )}

      {selected && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-[10.5px] text-zbrain hover:underline"
        >
          change
        </button>
      )}

      {open && (
        <div className="absolute top-full right-0 mt-1 z-30 w-80 rounded-md border border-zbrain-divider bg-white shadow-xl overflow-hidden">
          <div className="px-2.5 py-2 border-b border-zbrain-divider">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search baselines"
              className="w-full text-xs border border-zbrain-divider rounded px-2 py-1 focus:outline-none focus:border-zbrain"
            />
          </div>
          <div className="max-h-64 overflow-auto">
            <button
              type="button"
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-zbrain-50 ${
                value == null ? "bg-zbrain-50 font-semibold" : ""
              }`}
            >
              All baselines{" "}
              <span className="text-zbrain-muted font-normal">({items.length})</span>
            </button>
            {filtered.length === 0 && (
              <div className="px-3 py-3 text-xs text-zbrain-muted text-center">
                No baselines match.
              </div>
            )}
            {filtered.map((b) => (
              <button
                key={b.id}
                type="button"
                onClick={() => {
                  onChange(b.id);
                  setOpen(false);
                }}
                className={`w-full text-left px-3 py-1.5 text-xs hover:bg-zbrain-50 flex items-center gap-2 ${
                  value === b.id ? "bg-zbrain-50 font-semibold" : ""
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(b.last_status)}`}
                  aria-hidden
                />
                <span className="truncate flex-1">{b.label || `Baseline #${b.id}`}</span>
                <span className="text-[10px] text-zbrain-muted font-mono shrink-0">
                  {b.metric}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default BaselineFilter;
