import { useEffect, useState } from "react";

export type PreviewItem = {
  name: string;
  url: string;
};

export type AttachmentLike =
  | string
  | { name?: string | null; path?: string | null };

/** Build the static URL for an email/pipeline attachment.
 * Prefers the `path` field (e.g. "use_case_seeds/UC1-A1_PO-UCA1-2026-1001.pdf")
 * so files materialised in sub-directories under `backend/data/uploads/` resolve
 * correctly. Falls back to bare `name` for legacy attachments. Strings are
 * treated as the legacy bare-name form.
 */
export function attachmentUrl(att: AttachmentLike): string {
  if (typeof att === "string") return `/files/uploads/${att}`;
  const rel = (att.path || att.name || "").replace(/^\/+/, "");
  return `/files/uploads/${rel}`;
}

export function attachmentName(att: AttachmentLike): string {
  if (typeof att === "string") return att;
  return att.name || att.path || "(unnamed)";
}

const isImage = (n: string) => /\.(png|jpe?g|gif|webp|bmp)$/i.test(n);
const isPdf = (n: string) => /\.pdf$/i.test(n);
const isXlsx = (n: string) => /\.(xlsx|xls)$/i.test(n);
const isCsv = (n: string) => /\.csv$/i.test(n);
const isDocx = (n: string) => /\.(docx|doc)$/i.test(n);

function parseCsv(text: string, maxRows = 30): string[][] {
  // Minimal CSV parser: handles quoted fields with embedded commas/quotes and
  // CRLF/LF line endings. Good enough for the preview's first ~30 rows.
  const rows: string[][] = [];
  let cur: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ",") {
        cur.push(field);
        field = "";
      } else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && text[i + 1] === "\n") i++;
        cur.push(field);
        rows.push(cur);
        cur = [];
        field = "";
        if (rows.length >= maxRows) return rows;
      } else {
        field += ch;
      }
    }
  }
  if (field.length > 0 || cur.length > 0) {
    cur.push(field);
    rows.push(cur);
  }
  return rows;
}

function CsvPreview({ url, name }: { url: string; name: string }) {
  const [rows, setRows] = useState<string[][] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.text();
      })
      .then((t) => {
        if (!cancelled) setRows(parseCsv(t, 30));
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zbrain-divider bg-white">
        <div className="text-xs text-zbrain-muted">
          {rows ? `Showing first ${rows.length} row${rows.length === 1 ? "" : "s"}` : err ? "Preview unavailable" : "Loading preview…"}
        </div>
        <a href={url} download className="btn-secondary text-xs">
          ⬇ Download CSV
        </a>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {err && (
          <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded p-3">
            Could not load {name}: {err}
          </div>
        )}
        {rows && rows.length > 0 && (
          <table className="text-xs border-collapse">
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className={ri === 0 ? "bg-slate-100 font-medium" : ri % 2 === 1 ? "bg-slate-50" : ""}>
                  {r.map((c, ci) => (
                    <td key={ci} className="border border-zbrain-divider px-2 py-1 whitespace-pre align-top">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {rows && rows.length === 0 && (
          <div className="text-sm text-zbrain-muted">File is empty.</div>
        )}
      </div>
    </div>
  );
}

export function PreviewModal({ item, onClose }: { item: PreviewItem | null; onClose: () => void }) {
  useEffect(() => {
    if (!item) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, onClose]);

  if (!item) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-zbrain-ink/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-5xl h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-zbrain-divider">
          <div className="min-w-0 flex items-center gap-2">
            <span className="text-base font-medium truncate">{item.name}</span>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={item.url}
              download
              className="btn-secondary text-xs"
              onClick={(e) => e.stopPropagation()}
            >
              ⬇ Download
            </a>
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="btn-secondary text-xs"
              onClick={(e) => e.stopPropagation()}
            >
              ↗ Open in new tab
            </a>
            <button onClick={onClose} className="btn-ghost text-base">
              ✕
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto bg-zbrain-surface">
          {isImage(item.name) && (
            <div className="h-full flex items-center justify-center p-4">
              <img src={item.url} alt={item.name} className="max-h-full max-w-full object-contain" />
            </div>
          )}
          {isPdf(item.name) && (
            <iframe src={item.url} title={item.name} className="w-full h-full" />
          )}
          {isCsv(item.name) && <CsvPreview url={item.url} name={item.name} />}
          {(isXlsx(item.name) || isDocx(item.name)) && (
            <div className="h-full flex flex-col items-center justify-center text-zbrain-muted text-sm gap-3 p-8">
              <div className="text-5xl">📄</div>
              <div className="font-medium text-zbrain-ink">{item.name}</div>
              <div className="max-w-md text-center">
                {isXlsx(item.name) ? "Excel workbook" : "Word document"}. Browsers cannot preview this format inline.
                Use Download or Open in new tab to view.
              </div>
              <a href={item.url} download className="btn-primary mt-2">
                ⬇ Download
              </a>
            </div>
          )}
          {!isImage(item.name) && !isPdf(item.name) && !isCsv(item.name) && !isXlsx(item.name) && !isDocx(item.name) && (
            <div className="h-full flex flex-col items-center justify-center text-zbrain-muted text-sm gap-3 p-8">
              <div className="text-5xl">📎</div>
              <div className="font-medium text-zbrain-ink">{item.name}</div>
              <a href={item.url} download className="btn-primary mt-2">
                ⬇ Download
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
