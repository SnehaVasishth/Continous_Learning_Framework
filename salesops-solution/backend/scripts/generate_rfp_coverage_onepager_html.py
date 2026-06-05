"""Generate a print-ready single-page HTML version of the Keysight SalesOps
RFP coverage matrix.

The page is laid out at US Letter portrait and is designed to convert
cleanly to PDF via the browser's Print > Save as PDF or any HTML-to-PDF tool.
Palette matches the in-app value-capture calculator
(``app/routes/_benefit_calculator_value_html.py``).

Output: ``~/Downloads/Keysight_SalesOps_RFP_Coverage_OnePager.html``.
Run from the backend dir:

    .venv/bin/python scripts/generate_rfp_coverage_onepager_html.py
"""
from __future__ import annotations

from pathlib import Path
from html import escape


OUTPUT_PATH = Path.home() / "Downloads" / "Keysight_SalesOps_RFP_Coverage_OnePager.html"


# Stage strip — stage names and bullets sourced from the RFP End-to-End
# Process Flow diagram on the AI.SalesOps Details sheet.
STAGE_STRIP = [
    ("01", "Intake & Classification",
     "Receive inbound email + attachments, detect language, classify intent (6+ types), >=90% accuracy"),
    ("02", "Data Extraction & Enrichment",
     "OCR attached documents, LLM-extract fields, entity resolution, cross-system enrichment"),
    ("03", "Decision & Confidence Scoring",
     "Confidence per request, autonomy Levels 4 / 3 / 2, business rules, PO vs quote mismatch"),
    ("04", "Workflow Execution",
     "Orchestrate across CRM / ERP / service, manage holds, downstream processes, SLA escalation"),
    ("05", "Communication & Close-out",
     "Auto-generate reply, customer language, attach SOA, update status and close, full audit trail"),
    ("06", "Continuous Learning",
     "Capture CSR corrections, detect drift, recalibrate thresholds, infer rules, report trends"),
]


SECTIONS = [
    {
        "title": "Stage 1: Intake & Classification",
        "rows": [
            ("Receive inbound communication (email + attachments)",
             "Inbound mailbox polled via IMAP; attachments preserved on the Case.",
             "BUILT"),
            ("Detect language (multi-language support required)",
             "Three languages live: English, Spanish, Japanese.",
             "PARTIAL"),
            ("Classify customer intent (6+ intent types)",
             "14 intents live.",
             "BUILT"),
            ("Achieve >90% classification accuracy",
             "Per-email confidence shown on every Trace page.",
             "TO_BE_TESTED"),
            ("Read bodies, inline content, attachments (PDF, Excel, Word, images)",
             "PDF, Excel, Word, and image attachments all supported.",
             "BUILT"),
            ("Spam and phishing detection on inbound mail",
             "Dual-screen heuristic plus LLM check before any extraction cost is incurred.",
             "BUILT"),
            ("Pre-AI Outlook rules engine for mailbox-door routing",
             "Knowledge-Base Outlook rules deflect routine traffic (out-of-office, KSO redirect, Brazil tax, portal admin, collections) prior to classification.",
             "TO_BE_TESTED"),
            ("Mailbox-door triage and redirect (KSO, Brazil tax, collections, portal admin)",
             "Each redirected stream surfaces on the Dashboard mailbox-door tile with per-filter counts.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 2: Data Extraction & Enrichment",
        "rows": [
            ("OCR processing of attached documents (POs, scanned forms)",
             "Azure Document Intelligence.",
             "TO_BE_TESTED"),
            ("LLM-based extraction of structured fields from unstructured text",
             "Structured field extraction live per intent.",
             "TO_BE_TESTED"),
            ("Entity resolution (customer, order, product matching)",
             "Fuzzy match against the Salesforce Account, product, and order.",
             "BUILT"),
            ("Cross-system data enrichment (profile, history, catalog, entitlements)",
             "Four Salesforce queries fire on every email to enrich customer, order, and contact context.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 3: Decision & Confidence Scoring",
        "rows": [
            ("Confidence scoring per request",
             "Four signals scored independently; composite is the lowest signal. Logic to be enhanced with Keysight-specific signals before validation.",
             "TO_BE_TESTED"),
            ("Level 4 (&ge;95%): Fully autonomous, AI acts without approval",
             "PO intake and hold release flow end-to-end at Level 4 with no human touch.",
             "PARTIAL"),
            ("Level 3 (80 to 94%): One-click human approval",
             "HITL queue with acknowledgement checkboxes; CSR approves with one click.",
             "PARTIAL"),
            ("Level 2 (&lt;80%): Human decision and action required",
             "Full HITL review queue with draft, edit, and reject.",
             "PARTIAL"),
            ("Business rules validation (compliance, dollar thresholds, customer exclusions, export controls)",
             "Knowledge Base business-rules engine fires before any write.",
             "PARTIAL"),
            ("Mismatch detection (PO vs quote discrepancies)",
             "Reconcile checks for price, quantity, SKU, payment terms before Decide.",
             "PARTIAL"),
        ],
    },
    {
        "title": "Stage 4: Workflow Execution",
        "rows": [
            ("Orchestrate actions across CRM, ERP, and service platforms",
             "Cases, Orders, Order Lines, Chatter, and Contacts written to the Salesforce CCC; ERP via middleware is the next-phase add.",
             "PARTIAL"),
            ("Create / update orders, manage holds, process returns",
             "PO intake, Quote-to-Order conversion, hold release, and trade change order all running end-to-end.",
             "BUILT"),
            ("Trigger downstream processes (shipping, invoicing, SOA)",
             "SOA generated and filed; shipping and invoicing hooks ready.",
             "PARTIAL"),
            ("Manage regional workflow variations without code changes",
             "Knowledge Base namespaces editable in the UI cover routing, business rules, schemas, and prompts.",
             "PARTIAL"),
            ("SLA-driven task escalation",
             "Per-intent SLA target stamped at Decide; breach surfaces on the HITL queue and Trace page.",
             "PARTIAL"),
        ],
    },
    {
        "title": "Stage 5: Communication & Close-out",
        "rows": [
            ("Auto-generate customer-facing emails",
             "Every reply drafted by the LLM with a deterministic safety fallback per intent.",
             "BUILT"),
            ("Respond in customer's original language (translation)",
             "Live for English, Spanish, and Japanese. Translation glossary editable in the Knowledge Base.",
             "PARTIAL"),
            ("Attach relevant documents (order acknowledgements, SOAs)",
             "SOA generated, filed to SharePoint, deep-linked on the Salesforce Case. DocuNet integration needed for full document-store coverage.",
             "PARTIAL"),
            ("Update case / request status and close",
             "Stage 4 and HITL approval both close the Case with the right Stage and Status.",
             "BUILT"),
            ("Full audit trail from intake through resolution",
             "Every stage writes trace events; communication log and Case comment carry the Salesforce Case URL.",
             "TO_BE_TESTED"),
        ],
    },
    {
        "title": "Stage 6: Continuous Learning",
        "rows": [
            ("Capture CSR corrections to AI decisions",
             "Feedback (thumbs and edits) captured at every stage and surfaced on the Continuous Learning page.",
             "TO_BE_TESTED"),
            ("Detect classification drift over time",
             "Distribution shift detector plus classification-accuracy baseline; breach timeline on Application Governance.",
             "TO_BE_TESTED"),
            ("Recalibrate confidence thresholds",
             "Threshold-tuning suggestions surfaced on the Continuous Learning page; operator promotes them from the same screen.",
             "TO_BE_TESTED"),
            ("Infer new business rules from correction patterns",
             "Suggestion engine drafts new rules from edit patterns; operator promotes them in the Knowledge Base UI.",
             "TO_BE_TESTED"),
            ("Report on automation rates and accuracy trends",
             "Dashboard, Continuous Learning, and Application Governance views all live.",
             "BUILT"),
        ],
    },
    {
        "title": "Integration Requirements",
        "rows": [
            ("CRM Platform, bidirectional API (requests, customers, opportunities, quotes, orders)",
             "ZBrain sandbox environment: Cases, Accounts, Contacts, Orders, Order Lines, Chatter, and file attachments all live.",
             "BUILT"),
            ("ERP System, bidirectional API or middleware (orders, holds, schedules, shipping, invoicing)",
             "Stage 4 currently writes to Salesforce; the middleware bridge to ERP is committed for the next delivery phase.",
             "ROADMAP"),
            ("Email System, inbound listener and outbound send",
             "Inbound mailbox live via IMAP; outbound send pathway to be wired in the next delivery phase.",
             "PARTIAL"),
            ("Document Management API (store and retrieve PO documents, SOAs, attachments)",
             "SharePoint wired for search, upload, and deep-link; DocuNet integration is committed for the next delivery phase.",
             "PARTIAL"),
            ("AIOA order acceptance handoff (async validate, callback, resume)",
             "Stage 3 enqueues to AIOA; PASS resumes the pipeline; FAIL parks for HITL with a CSR clarification draft.",
             "PARTIAL"),
            ("Application Governance (policy engine, audit trail, kill-switch events)",
             "Separate Governance app live with policy enforcement, DID-based agent identity, and breach timeline.",
             "BUILT"),
        ],
    },
]


def _status_pill_html(status: str) -> str:
    cls = {
        "BUILT": "ok",
        "PARTIAL": "warn",
        "ROADMAP": "rose",
        "TO_BE_TESTED": "test",
    }.get(status, "ok")
    label = "TO BE TESTED" if status == "TO_BE_TESTED" else status
    return f'<span class="pill pill-{cls}">{label}</span>'


def _row_html(req_no: str, req: str, built: str, status: str) -> str:
    return (
        f"<tr>"
        f"<td class='reqno'>{escape(req_no)}</td>"
        f"<td class='req'>{req}</td>"
        f"<td class='built'>{escape(built)}</td>"
        f"<td class='status'>{_status_pill_html(status)}</td>"
        f"</tr>"
    )


def _section_html(section: dict, section_idx: int) -> str:
    # Number every row 1.1, 1.2, ... 2.1, 2.2, ... mirroring the RFP S.No
    # column. Integration Requirements becomes section 7.x.
    rows_html = "".join(
        _row_html(f"{section_idx}.{n}", req, built, status)
        for n, (req, built, status) in enumerate(section["rows"], start=1)
    )
    return (
        f"<tr class='section-band'><td colspan='4'>{escape(section['title'])}</td></tr>"
        f"{rows_html}"
    )


def _stage_strip_html() -> str:
    cells = []
    for n, label, outcome in STAGE_STRIP:
        cells.append(
            f"<div class='stage-cell'>"
            f"<div class='stage-n'>{escape(n)} &middot; {escape(label)}</div>"
            f"<div class='stage-outcome'>{escape(outcome)}</div>"
            f"</div>"
        )
    return "<div class='stage-strip'>" + "".join(cells) + "</div>"


def _compute_summary() -> tuple[int, int, int, int, int]:
    total = built = partial = roadmap = to_be_tested = 0
    for s in SECTIONS:
        for _r, _w, status in s["rows"]:
            total += 1
            if status == "BUILT":
                built += 1
            elif status == "PARTIAL":
                partial += 1
            elif status == "TO_BE_TESTED":
                to_be_tested += 1
            else:
                roadmap += 1
    return total, built, partial, roadmap, to_be_tested


def _stats_band_html() -> str:
    """Top stats band — coverage roll-up immediately under the cover."""
    total, built, partial, roadmap, to_be_tested = _compute_summary()
    # Coverage weights: Built and To be tested count as 1.0 (functionality
    # is in place; To be tested just needs Keysight-data validation), Partial
    # counts as 0.5 (in production with planned extensions still to land),
    # Roadmap counts as 0.
    weighted = built + to_be_tested + (0.5 * partial)
    coverage = round(100 * weighted / total) if total else 0
    items = [
        (str(total), "Total requirements", "muted"),
        (str(built), "Built", "ok"),
        (str(partial), "Partial", "warn"),
        (str(to_be_tested), "To be tested", "test"),
        (str(roadmap), "Roadmap", "rose"),
        (f"{coverage}%", "Overall coverage", "accent"),
    ]
    inner = "".join(
        f"<div class='stats-cell'><div class='stats-num stats-num-{tone}'>{escape(v)}</div>"
        f"<div class='stats-label'>{escape(l)}</div></div>"
        for v, l, tone in items
    )
    return f"<div class='stats-band'>{inner}</div>"


def _footer_html() -> str:
    total, built, partial, roadmap, _to_be_tested = _compute_summary()
    cov_built = round(100 * built / total) if total else 0
    cov_built_partial = round(100 * (built + partial) / total) if total else 0
    cells = [
        (str(total), "Total requirements"),
        (str(built), "Built"),
        (str(partial), "Partial"),
        (str(roadmap), "Roadmap"),
        (f"{cov_built}%", "Coverage (Built)"),
        (f"{cov_built_partial}%", "Coverage (Built + Partial)"),
    ]
    inner = "".join(
        f"<div class='footer-cell'><div class='footer-num'>{escape(v)}</div>"
        f"<div class='footer-label'>{escape(l)}</div></div>"
        for v, l in cells
    )
    return f"<div class='footer-band'>{inner}</div>"


HTML_TEMPLATE = """<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8' />
<title>Keysight SalesOps RFP coverage map</title>
<style>
  :root {{
    --ink: #131426;
    --muted: #6B7280;
    --rule: #E5E7EB;
    --surface: #F8FAFC;
    --accent: #1A55F9;
    --accent-soft: #EAF1FF;
    --accent-border: #C9D8FB;
    --ok: #1F8A4C;
    --ok-soft: #E1F4E8;
    --warn: #C77700;
    --warn-soft: #FEF3C7;
    --rose: #B91C1C;
    --rose-soft: #FEECEC;
    --cover-dark: #0E1230;
    --cover-eyebrow: #6E8AE8;
    --cover-text: #F5F7FB;
    --cover-muted: #C7CEE2;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #fff; color: var(--ink);
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
                -webkit-font-smoothing: antialiased; }}
  .page {{ width: 8.5in; margin: 0 auto; padding: 0.45in 0.45in 0.35in 0.45in; }}

  /* Cover header */
  .cover {{ background: linear-gradient(135deg, #0E1230 0%, #1E2A4D 100%);
            color: var(--cover-text); border-radius: 6px;
            padding: 22px 24px 20px 24px; position: relative;
            border-bottom: 4px solid var(--accent); }}
  .cover .eyebrow {{ color: var(--cover-eyebrow); font-size: 12px; font-weight: 700;
                     letter-spacing: 0.10em; text-transform: uppercase; }}
  .cover h1 {{ font-size: 22px; line-height: 1.25; margin: 6px 0 8px 0; font-weight: 700; }}
  .cover .sub {{ color: var(--cover-muted); font-size: 12.5px; line-height: 1.55; }}

  /* Stage strip */
  .stage-strip {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 0;
                  margin-top: 14px; background: var(--accent-soft);
                  border: 1px solid var(--accent-border); border-radius: 6px; }}
  .stage-cell {{ padding: 10px 12px; border-right: 1px solid var(--accent-border);
                 text-align: left; }}
  .stage-cell:last-child {{ border-right: none; }}
  .stage-n {{ font-size: 12.5px; font-weight: 700; color: var(--accent); line-height: 1.3; }}
  .stage-outcome {{ font-size: 10.5px; color: var(--muted); line-height: 1.45; margin-top: 4px; }}

  /* Matrix */
  table.matrix {{ width: 100%; border-collapse: collapse; margin-top: 14px; }}
  table.matrix thead th {{ background: var(--accent-soft); color: var(--ink);
                           font-size: 11.5px; font-weight: 700; text-align: left;
                           padding: 8px 10px; border-bottom: 1.5px solid var(--accent);
                           letter-spacing: 0.02em; }}
  table.matrix tbody tr {{ break-inside: avoid; page-break-inside: avoid; }}
  table.matrix tbody td {{ padding: 7px 10px; border-bottom: 1px solid var(--rule);
                           vertical-align: middle; font-size: 11px; line-height: 1.45; }}
  table.matrix tbody tr.section-band td {{ background: var(--accent-soft);
                                           color: var(--accent); font-weight: 700;
                                           font-size: 12px; text-transform: uppercase;
                                           padding: 9px 10px; border-bottom: 1.2px solid var(--accent-border);
                                           letter-spacing: 0.04em; }}
  td.reqno {{ width: 6%; color: var(--muted); font-family: 'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 10px; text-align: center; vertical-align: middle; }}
  td.req {{ width: 30%; color: var(--ink); }}
  td.built {{ width: 52%; color: var(--ink); }}
  td.status {{ width: 12%; text-align: center; }}

  /* Status pills */
  .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px;
           font-size: 9.5px; font-weight: 700; letter-spacing: 0.06em;
           text-transform: uppercase; border: 1px solid;
           white-space: nowrap; }}
  .pill-ok {{ color: var(--ok); background: var(--ok-soft); border-color: var(--ok); }}
  .pill-warn {{ color: var(--warn); background: var(--warn-soft); border-color: var(--warn); }}
  .pill-rose {{ color: var(--rose); background: var(--rose-soft); border-color: var(--rose); }}
  .pill-test {{ color: #4338CA; background: #EEF2FF; border-color: #4338CA; }}

  /* Legend */
  .legend {{ margin-top: 14px; color: var(--muted); font-size: 11px; line-height: 1.55; }}
  .legend b {{ color: var(--ink); }}
  .legend .lg-built {{ color: var(--ok); font-weight: 700; }}
  .legend .lg-partial {{ color: var(--warn); font-weight: 700; }}
  .legend .lg-test {{ color: #4338CA; font-weight: 700; }}
  .legend .lg-roadmap {{ color: var(--rose); font-weight: 700; }}

  /* Top stats band */
  .stats-band {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 0;
                 margin-top: 14px; background: var(--surface);
                 border: 1px solid var(--rule); border-radius: 6px; }}
  .stats-cell {{ padding: 12px 8px; text-align: center;
                 border-right: 1px solid var(--rule); }}
  .stats-cell:last-child {{ border-right: none; }}
  .stats-num {{ font-size: 22px; font-weight: 700; line-height: 1.15; }}
  .stats-num-ok {{ color: var(--ok); }}
  .stats-num-warn {{ color: var(--warn); }}
  .stats-num-rose {{ color: var(--rose); }}
  .stats-num-test {{ color: #4338CA; }}
  .stats-num-accent {{ color: var(--accent); }}
  .stats-num-muted {{ color: var(--ink); }}
  .stats-label {{ font-size: 9.5px; color: var(--muted);
                  text-transform: uppercase; letter-spacing: 0.10em; margin-top: 4px; }}

  /* Footer band */
  .footer-band {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 0;
                  background: var(--cover-dark); color: var(--cover-text);
                  border-radius: 6px; margin-top: 14px; }}
  .footer-cell {{ padding: 14px 8px; text-align: center; }}
  .footer-num {{ font-size: 22px; font-weight: 700; color: #fff; line-height: 1.15; }}
  .footer-label {{ font-size: 9.5px; color: var(--cover-muted);
                   text-transform: uppercase; letter-spacing: 0.10em; margin-top: 4px; }}

  @page {{ size: Letter portrait; margin: 0.4in; }}
  @media print {{
    html, body {{ background: #fff; }}
    .page {{ padding: 0; }}
    table.matrix thead {{ display: table-header-group; }}
    table.matrix tbody tr.section-band {{ break-after: avoid; page-break-after: avoid; }}
  }}
</style>
</head>
<body>
<div class='page'>
  <div class='cover'>
    <div class='eyebrow'>KEYSIGHT SALESOPS &middot; RFP COVERAGE MATRIX</div>
    <h1>Your RFP Vision version 1 is ready to be deployed</h1>
  </div>

  {stats_band}

  {stage_strip}

  <table class='matrix'>
    <thead>
      <tr>
        <th style='text-align:center;'>S.No</th>
        <th>RFP Requirement</th>
        <th>What we built</th>
        <th style='text-align:center;'>Status</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>

  <div class='legend'>
    <b>Legend</b>
    &nbsp; <span class='lg-built'>BUILT</span> capability delivered; tuning required for Keysight deployment
    &nbsp; <span class='lg-partial'>PARTIAL</span> in production with planned extensions
    &nbsp; <span class='lg-test'>TO BE TESTED</span> functionality in place; validation pending against Keysight data
    &nbsp; <span class='lg-roadmap'>ROADMAP</span> committed for the next delivery phase
  </div>
</div>
</body>
</html>
"""


def main() -> None:
    body_rows = "".join(_section_html(s, idx) for idx, s in enumerate(SECTIONS, start=1))
    stage_strip = _stage_strip_html()
    stats_band = _stats_band_html()
    footer = _footer_html()  # retained but not rendered in the body anymore
    html = HTML_TEMPLATE.format(
        stats_band=stats_band,
        stage_strip=stage_strip,
        body_rows=body_rows,
        footer=footer,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
