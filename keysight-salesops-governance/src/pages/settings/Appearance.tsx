import { useEffect, useState } from "react";

import { PageHeader } from "../../components/PageHeader";
import {
  Appearance,
  DEFAULTS,
  loadAppearance,
  resetAppearance,
  resolveLogo,
  saveAppearance,
} from "../../lib/appearance";

const FONT_PRESETS: { id: string; label: string; stack: string }[] = [
  { id: "inter",   label: "Inter (default)",    stack: "Inter, system-ui, -apple-system, Segoe UI, sans-serif" },
  { id: "roboto",  label: "Roboto",             stack: "Roboto, Inter, system-ui, sans-serif" },
  { id: "system",  label: "System UI",          stack: "system-ui, -apple-system, Segoe UI, sans-serif" },
  { id: "ibm",     label: "IBM Plex Sans",      stack: "'IBM Plex Sans', Inter, system-ui, sans-serif" },
  { id: "sourcer", label: "Source Sans 3",      stack: "'Source Sans 3', Inter, system-ui, sans-serif" },
];

/**
 * Appearance settings — applies to the SalesOps front-end only.
 *
 * The Orchestrator is the ZBrain platform admin and is not re-brandable;
 * its own header stays on the ZBrain wordmark across every project. This
 * page lets the platform owner customise the functional front-end (logo,
 * brand name, solution label, primary colour, font) per project. Changes
 * apply instantly and persist in `localStorage` until the backend
 * appearance store is wired.
 */
export function AppearancePage() {
  const [form, setForm] = useState<Appearance>(() => loadAppearance());
  const [saved, setSaved] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Keep the form in sync with cross-tab updates.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === "zbrain-orchestrator:appearance") {
        setForm(loadAppearance());
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  function update<K extends keyof Appearance>(key: K, value: Appearance[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function apply() {
    saveAppearance(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2200);
  }

  function reset() {
    const def = resetAppearance();
    setForm(def);
    setSaved(true);
    setTimeout(() => setSaved(false), 2200);
  }

  function onFile(file: File) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setUploadError("Logo must be an image file (PNG, SVG, or JPG).");
      return;
    }
    if (file.size > 750 * 1024) {
      setUploadError("Logo too large (max 750 KB). Compress or upload an SVG.");
      return;
    }
    setUploadError(null);
    setUploading(true);
    const reader = new FileReader();
    reader.onload = () => {
      setUploading(false);
      update("logoUrl", String(reader.result || ""));
    };
    reader.onerror = () => {
      setUploading(false);
      setUploadError("Could not read the file.");
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Appearance"
        subtitle="Brand the SalesOps front-end for this project. The Orchestrator stays on the ZBrain wordmark across every project."
        lastFetchedAt={null}
        error={null}
      />

      <div className="card border-l-4 border-l-zbrain px-5 py-3 text-[12.5px] text-zbrain-ink dark:text-zbrain-dark-ink">
        These settings apply to <strong>SalesOps</strong> only. Reload an open
        SalesOps tab to pick up new branding. The Orchestrator header is
        platform-owned and does not change.
      </div>

      {/* Live preview */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider flex items-center justify-between">
          <div>
            <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">SalesOps preview</div>
            <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
              How the functional front-end's header will render after you apply.
            </div>
          </div>
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] uppercase tracking-[0.12em] font-semibold"
            style={{ backgroundColor: `${form.primaryHex}1A`, color: form.primaryHex }}
          >
            Live preview
          </span>
        </div>
        <div className="px-5 py-4 bg-white dark:bg-zbrain-dark-elev1" style={{ fontFamily: form.fontFamily }}>
          <div className="flex items-center gap-3">
            {form.logoUrl ? (
              <img src={resolveLogo(form.logoUrl)} alt={form.brandName} className="h-6 w-auto block" />
            ) : (
              <span className="text-zbrain-muted text-sm">No logo set</span>
            )}
            <span className="text-zbrain-muted/60 text-sm select-none">|</span>
            <span className="text-sm font-semibold tracking-tight whitespace-nowrap" style={{ color: form.primaryHex }}>
              {form.solutionLabel}
            </span>
          </div>
        </div>
      </div>

      {/* Editable fields */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
          <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Brand</div>
          <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
            The brand name is the customer; the solution label is the product running on top of it.
          </div>
        </div>
        <div className="px-5 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Brand name">
            <input
              type="text"
              value={form.brandName}
              onChange={(e) => update("brandName", e.target.value)}
              className={inputClass}
              placeholder="Keysight"
            />
          </Field>
          <Field label="Solution label">
            <input
              type="text"
              value={form.solutionLabel}
              onChange={(e) => update("solutionLabel", e.target.value)}
              className={inputClass}
              placeholder="SalesOps"
            />
          </Field>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
          <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Logo</div>
          <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
            Paste a hosted URL or upload a file (PNG, SVG, JPG · max 750 KB). Recommended height 24-32 px.
          </div>
        </div>
        <div className="px-5 py-4 space-y-3">
          <Field label="Logo URL or path">
            <input
              type="text"
              value={form.logoUrl}
              onChange={(e) => update("logoUrl", e.target.value)}
              className={inputClass + " font-mono text-[12.5px]"}
              placeholder="keysight-logo.png  or  https://…"
            />
          </Field>
          <div>
            <label className="inline-flex items-center gap-2 px-3 h-8 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider text-[12.5px] font-medium text-zbrain-ink dark:text-zbrain-dark-ink hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2 cursor-pointer">
              {uploading ? "Reading…" : "Upload file"}
              <input
                type="file"
                accept="image/png,image/svg+xml,image/jpeg"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onFile(f);
                }}
              />
            </label>
            {uploadError && <div className="mt-2 text-[11.5px] text-rose-700">{uploadError}</div>}
          </div>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-zbrain-divider dark:border-zbrain-dark-divider">
          <div className="text-[13.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">Type &amp; colour</div>
          <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
            Primary colour drives the accent across pills, links, and active nav. Font applies to every header.
          </div>
        </div>
        <div className="px-5 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Primary colour">
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={form.primaryHex}
                onChange={(e) => update("primaryHex", e.target.value)}
                className="h-9 w-12 rounded-md border border-zbrain-divider cursor-pointer"
              />
              <input
                type="text"
                value={form.primaryHex}
                onChange={(e) => update("primaryHex", e.target.value)}
                className={inputClass + " font-mono"}
                placeholder="#1A55F9"
              />
            </div>
          </Field>
          <Field label="Font family">
            <select
              value={form.fontFamily}
              onChange={(e) => update("fontFamily", e.target.value)}
              className={inputClass}
            >
              {FONT_PRESETS.map((f) => (
                <option key={f.id} value={f.stack}>{f.label}</option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={apply}
          className="px-3 h-9 rounded-md bg-zbrain text-white text-[12.5px] font-semibold hover:opacity-90"
        >
          Apply
        </button>
        <button
          type="button"
          onClick={reset}
          className="px-3 h-9 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider text-[12.5px] font-medium text-zbrain-ink dark:text-zbrain-dark-ink hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2"
        >
          Reset to defaults
        </button>
        {saved && (
          <span className="text-[12px] text-emerald-700 dark:text-emerald-300">
            Saved. Reload the SalesOps tab to pick up new branding there.
          </span>
        )}
      </div>

      <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted">
        Defaults: brand "{DEFAULTS.brandName}", solution "{DEFAULTS.solutionLabel}",
        primary {DEFAULTS.primaryHex}.
      </div>
    </div>
  );
}

const inputClass =
  "w-full h-9 px-3 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-[13px] text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11.5px] font-semibold text-zbrain-ink dark:text-zbrain-dark-ink mb-1.5">{label}</div>
      {children}
    </label>
  );
}
