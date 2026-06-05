import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SolutionDocPage() {
  const [md, setMd] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/docs/solution")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.text();
      })
      .then(setMd)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="min-h-screen bg-slate-200 dark:bg-zbrain-dark print:bg-white py-10 print:py-0">
      <div className="mx-auto bg-white dark:bg-zbrain-dark-elev1 shadow-2xl print:shadow-none rounded-md print:rounded-none doc-page">
        <header className="px-12 pt-12 pb-6 border-b border-zbrain-divider dark:border-zbrain-dark-divider print:border-none">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-zbrain-muted dark:text-zbrain-dark-muted">
                Solution document · v1
              </div>
              <h1 className="mt-1 text-3xl font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
                Keysight SalesOps: AI Automation Demo
              </h1>
              <div className="mt-1 text-sm text-zbrain-muted dark:text-zbrain-dark-muted">
                LeewayHertz / ZBrain · Generated from <span className="font-mono text-xs">SOLUTION.md</span>
              </div>
            </div>
            <div className="flex flex-col items-end gap-2 print:hidden">
              <button
                onClick={() => window.print()}
                className="btn-primary text-xs"
                title="Use the browser print dialog to save as PDF"
              >
                ⎙ Print / Save as PDF
              </button>
              <a href="/api/docs/solution" target="_blank" rel="noreferrer" className="btn-secondary text-xs">
                ⤓ Download .md source
              </a>
            </div>
          </div>
        </header>
        <article className="doc-body px-12 py-10 print:py-6">
          {error && (
            <div className="text-sm text-rose-700">Failed to load: {error}</div>
          )}
          {!error && !md && <div className="text-sm text-zbrain-muted">Loading document…</div>}
          {md && (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
          )}
        </article>
        <footer className="px-12 pt-6 pb-12 text-xs text-zbrain-muted dark:text-zbrain-dark-muted border-t border-zbrain-divider dark:border-zbrain-dark-divider">
          End of document. Source kept at <span className="font-mono">SOLUTION.md</span> at the project root.
        </footer>
      </div>
    </div>
  );
}
