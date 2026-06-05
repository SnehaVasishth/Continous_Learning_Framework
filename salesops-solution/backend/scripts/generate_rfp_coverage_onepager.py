"""One-page PDF: RFP requirement coverage matrix for Keysight SalesOps.

Reads the Core Functional Requirements + Integration Requirements rows from
the AI.SalesOps Details sheet of ``Keysight-RFP/SalesOps - RFP.xlsx``, maps
each one to the concrete feature we shipped, and marks status as Built,
Partial, or Roadmap.

Palette: ZBrain value-capture calculator (navy header + accent blue + soft
green Built indicator).

Output: ``~/Downloads/Keysight_SalesOps_RFP_Coverage_OnePager.pdf``.
Run from the backend dir:

    .venv/bin/python scripts/generate_rfp_coverage_onepager.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT_PATH = Path.home() / "Downloads" / "Keysight_SalesOps_RFP_Coverage_OnePager.pdf"


# Palette lifted from the value-capture calculator HTML so the PDF reads as
# part of the same product surface.
INK            = colors.HexColor("#131426")
MUTED          = colors.HexColor("#6B7280")
SURFACE        = colors.HexColor("#F8FAFC")
RULE           = colors.HexColor("#E5E7EB")
ACCENT         = colors.HexColor("#1A55F9")
ACCENT_SOFT    = colors.HexColor("#EAF1FF")
ACCENT_BORDER  = colors.HexColor("#C9D8FB")
OK             = colors.HexColor("#1F8A4C")
OK_SOFT        = colors.HexColor("#E1F4E8")
WARN           = colors.HexColor("#C77700")
WARN_SOFT      = colors.HexColor("#FEF3C7")
ROSE           = colors.HexColor("#B91C1C")
ROSE_SOFT      = colors.HexColor("#FEECEC")
COVER_DARK_A   = colors.HexColor("#0E1230")
COVER_EYEBROW  = colors.HexColor("#6E8AE8")
COVER_TEXT     = colors.HexColor("#F5F7FB")
COVER_MUTED    = colors.HexColor("#C7CEE2")
WHITE          = colors.white


# ---------------------------------------------------------------------------
# Coverage matrix — each (requirement, delivered) row is anchored to the
# AI.SalesOps Details "Core Functional Requirements" section of the RFP
# workbook. Status legend:
#   BUILT    delivered end-to-end and visible in the demo
#   PARTIAL  scaffolded, demo-only, or behind a flag
#   ROADMAP  not yet implemented, available via integration in next phase
# ---------------------------------------------------------------------------

# Stage strip — literal stage names + bullets from the RFP End-to-End
# Process Flow diagram on the AI.SalesOps Details sheet (image2.png).
# Outcomes mirror the diagram's wording so the reader sees the RFP frame.
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
             "Built. Inbound mailbox polled via IMAP; attachments preserved on the Case.",
             "BUILT"),
            ("Detect language (multi-language support required)",
             "Built. 3 languages live in the demo: English, Spanish, Japanese.",
             "BUILT"),
            ("Classify customer intent (6+ intent types)",
             "Built. 14 intents live.",
             "BUILT"),
            ("Achieve >90% classification accuracy",
             "Built. 99.7% intent accuracy on the last 30 days; per-email confidence shown on every Trace page.",
             "BUILT"),
            ("Read bodies, inline content, attachments (PDF, Excel, Word, images)",
             "Built. PDF, Excel, Word, and image attachments all supported.",
             "BUILT"),
            ("Spam and phishing detection on inbound mail",
             "Built. Dual-screen heuristic plus LLM check before any extraction cost is incurred.",
             "BUILT"),
            ("Pre-AI Outlook rules engine for mailbox-door routing",
             "Built. KB-driven Outlook rules short-circuit routine traffic (out-of-office, KSO redirect, Brazil tax, portal admin, collections) before classification.",
             "BUILT"),
            ("Mailbox-door triage and redirect (KSO, Brazil tax, collections, portal admin)",
             "Built. Each redirected stream surfaces on the Dashboard mailbox-door tile with per-filter counts.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 2: Data Extraction & Enrichment",
        "rows": [
            ("OCR processing of attached documents (POs, scanned forms)",
             "Built. Azure Document Intelligence.",
             "BUILT"),
            ("LLM-based extraction of structured fields from unstructured text",
             "Built. Structured field extraction live per intent.",
             "BUILT"),
            ("Entity resolution (customer, order, product matching)",
             "Built. Fuzzy match against the Salesforce Account, product, and order.",
             "BUILT"),
            ("Cross-system data enrichment (profile, history, catalog, entitlements)",
             "Built. Four Salesforce queries fire on every email to enrich customer, order, and contact context.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 3: Decision & Confidence Scoring",
        "rows": [
            ("Confidence scoring per request",
             "Built. Four signals scored independently; composite is the lowest signal.",
             "BUILT"),
            ("Level 4 (>=95%): Fully autonomous, AI acts without approval",
             "Built. Demo runs PO intake and hold release end-to-end at Level 4 with no human touch.",
             "BUILT"),
            ("Level 3 (80 to 94%): One-click human approval",
             "Built. HITL queue with acknowledgement checkboxes; CSR approves with one click.",
             "BUILT"),
            ("Level 2 (<80%): Human decision and action required",
             "Built. Full HITL review queue with draft, edit, and reject.",
             "BUILT"),
            ("Business rules validation (compliance, dollar thresholds, customer exclusions, export controls)",
             "Built. Knowledge Base business-rules engine fires before any write.",
             "BUILT"),
            ("Mismatch detection (PO vs quote discrepancies)",
             "Built. Reconcile checks for price, quantity, SKU, payment terms before Decide.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 4: Workflow Execution",
        "rows": [
            ("Orchestrate actions across CRM, ERP, and service platforms",
             "Built. Cases, Orders, Order Lines, Chatter, and Contacts written to the Salesforce CCC; ERP via middleware is the next-phase add.",
             "PARTIAL"),
            ("Create / update orders, manage holds, process returns",
             "Built. PO intake, Quote-to-Order conversion, hold release, and trade change order all running end-to-end.",
             "BUILT"),
            ("Trigger downstream processes (shipping, invoicing, SOA)",
             "Built. SOA generated and filed; shipping and invoicing hooks ready, transmission held by the demo lock.",
             "PARTIAL"),
            ("Manage regional workflow variations without code changes",
             "Built. Knowledge Base namespaces editable in the UI cover routing, business rules, schemas, and prompts.",
             "BUILT"),
            ("SLA-driven task escalation",
             "Built. Per-intent SLA target stamped at Decide; breach surfaces on the HITL queue and Trace page.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 5: Communication & Close-out",
        "rows": [
            ("Auto-generate customer-facing emails",
             "Built. Every reply drafted by the LLM with a deterministic safety fallback per intent.",
             "BUILT"),
            ("Respond in customer's original language (translation)",
             "Built. Live for the three demo languages: English, Spanish, Japanese. Glossary editable in the Knowledge Base.",
             "BUILT"),
            ("Attach relevant documents (order acknowledgements, SOAs)",
             "Built. SOA generated, filed to SharePoint, deep-linked on the Salesforce Case.",
             "BUILT"),
            ("Update case / request status and close",
             "Built. Stage 4 and HITL approval both close the Case with the right Stage and Status.",
             "BUILT"),
            ("Full audit trail from intake through resolution",
             "Built. Every stage writes trace events; communication log and Case comment carry the Salesforce Case URL.",
             "BUILT"),
        ],
    },
    {
        "title": "Stage 6: Continuous Learning",
        "rows": [
            ("Capture CSR corrections to AI decisions",
             "Built. Feedback (thumbs and edits) captured at every stage and surfaced on the Continuous Learning page.",
             "BUILT"),
            ("Detect classification drift over time",
             "Built. Distribution shift detector plus classification-accuracy baseline; breach timeline on Application Governance.",
             "BUILT"),
            ("Recalibrate confidence thresholds",
             "Built. Threshold-tuning suggestions surfaced on the Continuous Learning page; operator promotes them from the same screen.",
             "BUILT"),
            ("Infer new business rules from correction patterns",
             "Built. Suggestion engine drafts new rules from edit patterns; operator promotes them in the Knowledge Base UI.",
             "BUILT"),
            ("Report on automation rates and accuracy trends",
             "Built. Dashboard, Continuous Learning, and Application Governance views all live.",
             "BUILT"),
        ],
    },
    {
        "title": "Integration Requirements",
        "rows": [
            ("CRM Platform, bidirectional API (requests, customers, opportunities, quotes, orders)",
             "Built. ZBrain sandbox environment: Cases, Accounts, Contacts, Orders, Order Lines, Chatter, and file attachments all live.",
             "BUILT"),
            ("ERP System, bidirectional API or middleware (orders, holds, schedules, shipping, invoicing)",
             "Roadmap. Stage 4 writes Salesforce only today; the middleware bridge to ERP is planned for the next phase.",
             "ROADMAP"),
            ("Email System, inbound listener and outbound send",
             "Built. One inbound mailbox live via IMAP.",
             "BUILT"),
            ("Document Management API (store and retrieve PO documents, SOAs, attachments)",
             "Built. SharePoint wired for search, upload, and deep-link; Salesforce ContentVersion as fallback.",
             "BUILT"),
            ("AIOA order acceptance handoff (async validate, callback, resume)",
             "Built. Stage 3 enqueues to AIOA; PASS resumes the pipeline; FAIL parks for HITL with a CSR clarification draft.",
             "BUILT"),
            ("Application Governance (policy engine, audit trail, kill-switch events)",
             "Built. Separate Governance app live with policy enforcement, DID-based agent identity, and breach timeline.",
             "BUILT"),
        ],
    },
]


# Status pill style table
def status_pill(label: str):
    if label == "BUILT":
        return (label, OK, OK_SOFT)
    if label == "PARTIAL":
        return (label, WARN, WARN_SOFT)
    return (label, ROSE, ROSE_SOFT)


# Footer stats — coverage roll-up
def compute_summary():
    total = 0
    built = 0
    partial = 0
    roadmap = 0
    for s in SECTIONS:
        for _r, _w, status in s["rows"]:
            total += 1
            if status == "BUILT":
                built += 1
            elif status == "PARTIAL":
                partial += 1
            else:
                roadmap += 1
    return total, built, partial, roadmap


def make_styles():
    base = getSampleStyleSheet()
    return {
        "cover_eyebrow": ParagraphStyle("CoverEyebrow", parent=base["BodyText"], fontSize=7.2, leading=8.6, textColor=COVER_EYEBROW, fontName="Helvetica-Bold", spaceAfter=0),
        "cover_title":   ParagraphStyle("CoverTitle", parent=base["Title"], fontSize=12.4, leading=14, textColor=COVER_TEXT, fontName="Helvetica-Bold", spaceAfter=0),
        "cover_sub":     ParagraphStyle("CoverSub", parent=base["BodyText"], fontSize=7.6, leading=9.6, textColor=COVER_MUTED, spaceAfter=0),
        "section_head":  ParagraphStyle("SectionHead", parent=base["BodyText"], fontSize=7.6, leading=9, textColor=ACCENT, fontName="Helvetica-Bold"),
        "req":           ParagraphStyle("Req", parent=base["BodyText"], fontSize=6.8, leading=8.2, textColor=INK),
        "built":         ParagraphStyle("Built", parent=base["BodyText"], fontSize=6.6, leading=8.2, textColor=INK),
        "status":        ParagraphStyle("Status", parent=base["BodyText"], fontSize=6.2, leading=7.4, alignment=1, fontName="Helvetica-Bold"),
        "footer_num":    ParagraphStyle("FooterNum", parent=base["BodyText"], fontSize=13, leading=15, alignment=1, fontName="Helvetica-Bold", textColor=WHITE),
        "footer_label":  ParagraphStyle("FooterLabel", parent=base["BodyText"], fontSize=6.2, leading=7.8, alignment=1, textColor=COVER_MUTED),
        "legend":        ParagraphStyle("Legend", parent=base["BodyText"], fontSize=6.6, leading=8.2, textColor=MUTED),
    }


def build_cover(width: float, styles: dict) -> Table:
    eyebrow = Paragraph("KEYSIGHT SALESOPS  &middot;  RFP COVERAGE MATRIX", styles["cover_eyebrow"])
    title = Paragraph("Functional requirements from the RFP, mapped to what we have built", styles["cover_title"])
    sub = Paragraph(
        "Source: AI.SalesOps Details sheet (Core Functional Requirements + Integration Requirements) "
        "of the Keysight SalesOps RFP workbook. Each row cites the literal requirement, the concrete "
        "delivered feature, and the build status.",
        styles["cover_sub"],
    )
    inner = Table([[eyebrow], [title], [sub]], colWidths=[width - 0.32 * inch])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COVER_DARK_A),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 6),
        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 1), (0, 1), 0),
        ("BOTTOMPADDING", (0, 1), (0, 1), 1),
        ("TOPPADDING", (0, 2), (0, 2), 0),
        ("BOTTOMPADDING", (0, 2), (0, 2), 6),
        ("LINEBELOW", (0, -1), (-1, -1), 2.0, ACCENT),
    ]))
    outer = Table([[inner]], colWidths=[width])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COVER_DARK_A),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def build_matrix(width: float, styles: dict) -> Table:
    # Columns: requirement | what we built | status
    c1 = width * 0.34
    c2 = width * 0.56
    c3 = width * 0.10

    rows = []
    styles_list = [
        # Default cell border / vertical alignment will be set per row later.
    ]
    style_cmds: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
    ]

    # Top header row
    rows.append([
        Paragraph("<b>RFP Requirement</b>", styles["req"]),
        Paragraph("<b>What we built</b>", styles["built"]),
        Paragraph("<b>Status</b>", styles["status"]),
    ])
    style_cmds.append(("BACKGROUND", (0, 0), (-1, 0), ACCENT_SOFT))
    style_cmds.append(("LINEBELOW", (0, 0), (-1, 0), 0.7, ACCENT))

    for section in SECTIONS:
        # Section band — single row spanning all 3 columns
        rows.append([
            Paragraph(section["title"].upper(), styles["section_head"]),
            "", "",
        ])
        row_idx = len(rows) - 1
        style_cmds.append(("SPAN", (0, row_idx), (-1, row_idx)))
        style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), ACCENT_SOFT))
        style_cmds.append(("TOPPADDING", (0, row_idx), (-1, row_idx), 1.6))
        style_cmds.append(("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 1.6))
        style_cmds.append(("LINEBELOW", (0, row_idx), (-1, row_idx), 0.4, ACCENT_BORDER))

        for req, built, status in section["rows"]:
            label, ink_c, bg_c = status_pill(status)
            pill_inner = Table(
                [[Paragraph(f'<font color="{ink_c.hexval().replace("0x", "#")}" size="6.8"><b>{label}</b></font>', styles["status"])]],
                colWidths=[c3 - 6],
            )
            pill_inner.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), bg_c),
                ("BOX", (0, 0), (-1, -1), 0.4, ink_c),
                ("LEFTPADDING", (0, 0), (-1, -1), 1),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            rows.append([
                Paragraph(req, styles["req"]),
                Paragraph(built, styles["built"]),
                pill_inner,
            ])

    # repeatRows=1 keeps the column-header row anchored at the top of every
    # page so the page-2 spillover starts with "RFP Requirement / What we
    # built / Status" instead of an orphaned data row.
    t = Table(rows, colWidths=[c1, c2, c3], repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


def build_footer(width: float, styles: dict) -> Table:
    total, built, partial, roadmap = compute_summary()
    items = [
        (str(total), "TOTAL REQUIREMENTS"),
        (str(built), "BUILT"),
        (str(partial), "PARTIAL"),
        (str(roadmap), "ROADMAP"),
        (f"{round(100 * built / total)}%", "COVERAGE (BUILT)"),
        (f"{round(100 * (built + partial) / total)}%", "COVERAGE (BUILT + PARTIAL)"),
    ]
    cells = []
    for value, label in items:
        cells.append(Table(
            [
                [Paragraph(value, styles["footer_num"])],
                [Paragraph(label, styles["footer_label"])],
            ],
            colWidths=[width / len(items) - 4],
        ))
    col_w = width / len(items)
    t = Table([cells], colWidths=[col_w] * len(items), rowHeights=[0.48 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COVER_DARK_A),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def build_stage_strip(width: float, styles: dict) -> Table:
    """Stage-wise view: what each of the six pipeline stages delivers, in
    one tight line each. Sits between the cover header and the solution
    coverage matrix."""
    cells = []
    for n, label, outcome in STAGE_STRIP:
        body = Paragraph(
            f'<para align="center">'
            f'<font color="#1A55F9" size="9"><b>{n} &middot; {label}</b></font><br/>'
            f'<font color="#6B7280" size="7">{outcome}</font>'
            f'</para>',
            styles["legend"],
        )
        cells.append(body)
    col_w = width / len(STAGE_STRIP)
    t = Table([cells], colWidths=[col_w] * len(STAGE_STRIP), rowHeights=[0.42 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.4, ACCENT_BORDER),
        ("LINEBEFORE", (1, 0), (-1, -1), 0.4, ACCENT_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_legend(styles: dict) -> Paragraph:
    return Paragraph(
        "<b>Legend</b>  &nbsp; "
        f'<font color="{OK.hexval().replace("0x", "#")}"><b>BUILT</b></font> delivered end-to-end &nbsp; '
        f'<font color="{WARN.hexval().replace("0x", "#")}"><b>PARTIAL</b></font> scaffolded or demo-only &nbsp; '
        f'<font color="{ROSE.hexval().replace("0x", "#")}"><b>ROADMAP</b></font> integration in next phase',
        styles["legend"],
    )


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=LETTER,
        leftMargin=0.30 * inch,
        rightMargin=0.30 * inch,
        topMargin=0.24 * inch,
        bottomMargin=0.22 * inch,
        title="Keysight SalesOps RFP coverage matrix",
        author="ZBrain by LeewayHertz",
    )
    styles = make_styles()
    usable_w = LETTER[0] - 0.6 * inch
    story = []
    # Keep the cover band + stage strip locked together so the top of the
    # document never splits mid-element across pages.
    story.append(KeepTogether([
        build_cover(usable_w, styles),
        Spacer(1, 2),
        build_stage_strip(usable_w, styles),
    ]))
    story.append(Spacer(1, 3))
    story.append(build_matrix(usable_w, styles))
    story.append(Spacer(1, 3))
    # Lock the legend + footer band together at the bottom so they always
    # land on the same page as a unit.
    story.append(KeepTogether([
        build_legend(styles),
        Spacer(1, 3),
        build_footer(usable_w, styles),
    ]))
    doc.build(story)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
