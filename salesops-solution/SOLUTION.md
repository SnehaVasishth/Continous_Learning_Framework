# Keysight SalesOps — AI Automation Demo

## 1. Executive Summary

This is a working MVP, built on the **ZBrain orchestrator**, that ingests inbound customer emails — including PDF, Excel, Word, and image attachments — classifies the customer's intent, extracts structured data, reconciles it against CRM/ERP records, makes a **confidence-gated** autonomy decision, executes the work against the connected enterprise systems, and drafts the reply in the customer's language.

The RFP business goal — **reduce manual CSR processing effort by 60–70% and shorten response time from hours to minutes** — is delivered through a six-stage agent pipeline with three-tier autonomy (L4 fully autonomous, L3 one-click approval, L2 full human review), full trace auditability, and a continuous CSR feedback loop.

---

## 2. RFP Coverage

The RFP's End-to-End Process Flow enumerates seven happy paths plus the "discard" and "general inquiry" edges. **All are implemented** and exercised end-to-end in the demo.

| # | RFP Happy Path | Demo Intent | Resulting Action |
|---|---|---|---|
| 1 | Trade Order Entry — Purchase Order | PO intake | Issue Sales Order Acknowledgment (SOA) |
| 2 | Trade Order Entry — Quote-to-Order | Quote → Order conversion | Convert quote, create order, send SOA |
| 3 | Trade Sales Change Order | Change order | Apply line-item changes to the existing order |
| 4 | SSD (Ship Schedule Date) Change | SSD change request | Reschedule ship date in ERP |
| 5 | Hold Release | Hold release | Clear the credit / export / payment hold |
| 6a | Service Order Management — Create WO | New service order | Open work order(s); supports multi-asset spawn |
| 6b | SOM — Update existing WO | WO update request | Add notes/tasks/assets to an open WO |
| 6c | SOM — Status Inquiry | WO status inquiry | Compile customer-friendly status across open WOs |
| 7 | Service Contracts / Agreements | Service contract request | Draft cal-plan / onsite / PM contract quote |
| — | Spam / phishing | Spam screen | Silently discard |
| — | Anything else legitimate | General inquiry | Draft a reply, route to CSR |

---

## 3. Pipeline Stages

Every inbound email runs through the same six-stage ZBrain pipeline. Each stage is independently traceable on the **Live Trace** view, with a per-stage timing, polished summary, and a "show raw" toggle for inspection.

### Stage 1 · Intake & Classification

**Current implementation** (5 sub-steps): Receive inbound communication → Detect language (heuristic, LLM fallback) → Translate to English → Classify intent → Detect spam (regex heuristic).

**Proposed v2 design** (under discussion as of 2026-05-07 — see § Architecture Decision Log below): split into **7 sub-steps** with explicit ordering of the cheap-vs-expensive operations and full LLM confirmation on language detection.

```
1.1  Receive inbound communication        — internal (no LLM)
1.2  Heuristic spam pre-screen            — regex on subject + sender; immediate discard if hit
1.3  Attachment text extraction (light)   — sub-agent: PDF / Word / Excel / image OCR,
                                             capped at 3 pages per attachment
1.4  Detect language                      — heuristic + LLM, both run, agreement check
1.5  Translate to English                 — LLM, KB-aware (translation namespace);
                                             skipped if EN
1.6  LLM spam check                       — LLM on translated subject/body;
                                             catches sophisticated phishing in any language
1.7  Classify intent                      — LLM, 12-intent taxonomy, KB-driven,
                                             reasoning surfaced
```

**What surfaces in the UI per sub-step:**
- **Input** — exact text/data the tool received (with chunking notes for big attachments)
- **Output** — translated text, detected language, classified intent + confidence + reasoning, etc.
- **Activities** — collapsibles for system prompt, user prompt, raw provider response, KB rules consulted, raw JSON
- **Per-sub-step feedback widget** for CSR corrections

**Provider attribution per sub-step:** `ZBrain LLM (Claude Opus 4.7)` for LLM-driven steps; `ZBrain regex heuristic` for pattern-matchers; `Azure AI Translator / DeepL / Google Cloud Translate` when those adapters are enabled via `TRANSLATION_PROVIDER` env.

**KB consumed:** `intent` (intent definitions + examples), `translation` (Keysight terminology preservation rules — SKUs, ECCN, ITAR, brand, currency formatting).

### Stage 2 · Data Extraction & Enrichment
- Reads inline **PDF, Excel, Word, and image attachments**. Images are routed through the ZBrain document-intelligence agent for OCR.
- Selects an **intent-specific extraction schema** — a PO is read with PO fields, a service order is read with asset/standards fields, a SSD change is read with order/date fields, etc.
- Populates structured records: PO number, quote reference, line items, billing/shipping addresses, asset serials, standards referenced, requested ship date, and so on.

### Stage 3 · Cross-reference vs Quote
- For PO and Q2O intents, looks up the referenced quote in CRM and reconciles every line item.
- Flags **price mismatches**, **quantity mismatches**, **SKU not on the quote**, **likely SKU typos**, and **missing quoted lines**.
- Each issue is surfaced both in the trace and in the HITL panel as a side-by-side **Quoted vs PO vs Δ** strip.

### Stage 4 · Decision & Confidence Scoring
- Combines **intent confidence**, **extraction completeness**, and **customer-match score** (CRM lookup with exact-email and fuzzy fallback) into a single confidence value.
- Reconcile mismatches **cap** the confidence: blocking issues (price/qty/sku-not-quoted) cap at 0.70, soft issues (typos, missing lines) cap at 0.88.
- Maps confidence to a **three-tier autonomy** band — L4 fully auto / L3 one-click / L2 full HITL — and selects the action.
- Detects **misroutes** when the email's track hint conflicts with the inferred flow.
- Spam shortcuts the formula and is hard-coded to discard.

### Stage 5 · Workflow Execution
- On **L4 auto**, the action is applied immediately to the connected CRM/ERP/SOM systems: orders are created, holds are released, work orders are opened, line items are mutated, totals are recomputed.
- On **L3 one-click** and **L2 HITL**, the system stages a **preview** but does not write anything yet — the CSR approves first.
- Multi-asset service orders fan out into **N work orders in one pass** when the email lists multiple instruments.

### Stage 6 · Communication & Close-out
- Drafts a customer-facing reply in the **detected language**, matching the customer's profile language when known.
- For PO acknowledgments, generates a real **SOA PDF** with line items, totals, and Keysight branding, and attaches it to the reply.
- For WO status inquiries, translates internal status codes (`scheduled` / `in_progress` / `open`) into customer-friendly KSP-style sentences with ETA + reassurance.
- Every sent reply lands in the **Communication Log** linked to the customer, the order/WO, and the pipeline run — fully auditable.

### Auxiliary · Suggest-fix
On any reconcile variance, the HITL reviewer can click **✎ Suggest fix** to ask the agent to draft a polite corrective email back to the customer, itemizing each variance with the quoted vs PO values and offering three paths forward (accept quoted terms / issue revised PO / request sales-ops approval). Drafted in the customer's language.

---

## 4. Confidence-Gated Decision Engine

> **Why it matters:** the agent never silently does something risky. Every decision lands in one of three explicit autonomy bands, and the math is on screen for the reviewer.

The fused confidence score is:

```
confidence = 0.45 · intent_confidence
           + 0.35 · extraction_completeness
           + 0.20 · customer_match_score
```

**Mismatch caps** are applied after the weighted sum:

- **Blocking** issue present (price / qty / SKU-not-quoted) → confidence capped at **0.70** → L2 HITL
- **Soft** issue present (typos, missing line) → capped at **0.88** → L3 one-click at most
- **Spam** detected → hard-coded to 0.99 / L4 / discard — phishing never reaches a human

**Tier thresholds:**

| Tier | Threshold | Behavior |
|---|---|---|
| **L4 · Fully Autonomous** | confidence ≥ **0.95** | The agent applies the action immediately and sends the reply. |
| **L3 · One-Click Approval** | **0.80 ≤** conf **< 0.95** | The CSR reviews and clicks Approve — no editing required. |
| **L2 · Full Human Review** | confidence **< 0.80** | The CSR can edit the extracted data, edit the drafted reply, then approve, or reject outright. |

The Live Trace view shows the breakdown component-by-component (intent × weight = weighted), the mismatch penalty, the total, and the tier legend with the selected band highlighted.

---

## 5. Dataset (synthetic, deliberately Keysight-flavored)

The demo runs against an enterprise-realistic synthetic dataset that mirrors the depth a Keysight evaluator would expect from a real CRM/ERP. Everything is browseable from the **Data** tab.

### CRM accounts — 10 customers across Keysight's verticals

- **Aerospace & Defense:** Raytheon Aerospace (El Segundo Lab, Platinum SLA, ITAR/AS9100/DFARS), Bluehawk Defense Labs (Gold, ITAR/EAR/AS9100).
- **Semiconductor:** Tessera Semiconductor / Foundry 4 (Platinum, ISO 17025), Sakura Semiconductor KK (Japan, Platinum, ISO 17025).
- **Wireless / 5G·6G:** Meridian Comunicaciones SA (Spain, Gold, ETSI), Nordstern Telecom Labs (Germany, Gold).
- **Automotive Tier-1:** Aurora Automotive Electronics (Gold, IATF 16949 + ISO 26262).
- **Research:** Vertex Quantum Research (Silver).
- **Industrial / Test integrators:** Finolab Electronics GmbH (Germany, Gold, ISO 17025), Ozeki Test Systems (Japan, Silver).

Every customer carries the fields a real CRM would: legal entity, NAICS / industry, annual revenue, employee count, account manager, sales engineer, customer-since date, SLA tier, DUNS, tax ID, payment terms, credit limit, default currency, default incoterms, and a list of structured addresses (HQ / Bill-To / Ship-To with line1/line2/city/state/country/postal). Compliance tags carry their own descriptions visible on hover.

### Contacts — 21 people across the 10 customers

Realistic CSR-side roles per account: Procurement, Lab Operations, Trade Compliance, Accounts Payable. Each contact has name, title, role, email, phone, and language preference.

### Product catalog — 23 SKUs

The actual Keysight portfolio used in the demo:

- **Vector Network Analyzers:** PNA-X N5247B (67 GHz), ENA E5080B (8.5 GHz), legacy ENA E5071C (EOL announced, with successor-SKU pointer), Streamline P9374A USB VNA.
- **Signal Analyzers:** MXA N9020B (26.5 GHz, with EVM/W-CDMA/5G NR personalities), UXA N9040B (50 GHz).
- **Signal Generators:** MXG N5183B (40 GHz analog), VXG M9384B (44 GHz, 2 GHz mod BW vector).
- **Oscilloscopes:** InfiniiVision DSOX3024T, Infiniium S-Series MSOS804A, Infiniium UXR0334A real-time (33 GHz, 128 GS/s).
- **FieldFox handhelds:** N9912A 4 GHz combo, N9952A 50 GHz microwave.
- **DC/SMU:** N6705C DC Power Analyzer, B2902B precision SMU.
- **Logic / Digital:** U4154B AXIe LA, M8040A 64-GBaud BERT.
- **Calibration & Service SKUs:** A2LA / Z540.3 / ANSI cal services, extended warranty, 3.5 mm cal kit (85052D).

Every product carries: MPN, category, **lifecycle status** (active / mature / EOL announced), **EOL date and successor SKU** for items in lifecycle, **lead time in weeks**, **calibration interval in months**, **country of origin**, **ECCN export classification**, **HS code**, **warranty months**, **MOQ**, **hazmat flag**, and weight.

### Operational records

| Record set | Count | What it covers |
|---|---|---|
| **Quotes** | 19 | Realistic quote master incl. four targeted demo quotes the Q2O scenarios reconcile against. |
| **Orders** | 6 | Three on hold (credit review / export compliance / overdue invoice) plus three open, with bill-to/ship-to, payment terms, ship-via, tracking, CSR owner, hold history. |
| **Work Orders** | 6 | Calibration / repair / installation jobs with description, technician, scheduled/SLA dates, standards referenced, parts used, sign-off — each with a **generated PDF document**. |
| **Installed Base / Assets** | 47 | Customer-owned instruments with serial, install date, location, last-cal / cal-due dates, warranty expiry. |
| **Service Contracts** | 13 | Calibration plans, onsite plans, PM plans with SLA hours, included assets, annual value. |
| **Calibration Certs** | 22 | Issued certs with traceability (A2LA / Z540.3 / ANSI), lab ID, technician, OOT flag, as-found / as-left summaries — each with a **generated PDF cert**. |
| **Shipments** | 6 | Carrier, tracking number, ship/ETA dates, weight, incoterms. |
| **Invoices** | 6 | Issued/paid/overdue status with **generated PDF invoices** — overdue invoices feed the credit-hold release logic. |
| **Inbound Emails** | 42 | Cover all seven happy paths plus spam, ambiguity, multi-attachment, multi-asset, JA scanned-PO OCR, mismatched Q2Os, forwarded threads, and CSR-side language variants. |

Every PO PDF, BOM workbook, work order, calibration cert, invoice, and SOA in the demo is a **real generated document** — not a placeholder. All inline-previewable from the Data tab.

---

## 6. Use Cases & Demo Scenarios

> Open the **Inbox**, pick an email, click **Process**, and watch the Live Trace.

### 6.1 Clean PO intake — fully autonomous
Five seeded clean POs in three languages: Bluehawk / Finolab / Vertex (English), Nordstern (Spanish), Ozeki (Japanese). Each lands at L4 with confidence ≥0.97, the agent issues a Sales Order Acknowledgment, and a **SOA PDF** is generated and attached to the customer reply.

### 6.2 Quote-to-Order — clean and variant
Four Q2O scenarios, all referencing the targeted demo quotes:

- **Aurora** — clean Q2O with PDF + Excel BOM + Word acceptance test plan all attached. Reconciles cleanly → L4 auto.
- **Raytheon** — PO unit price = quoted × 0.92 → **price_mismatch** → cap 0.70 → L2 HITL.
- **TSMC** — PO qty = quoted +1 → **qty_mismatch** → cap 0.70 → L2 HITL.
- **Meridian** (Spanish) — PO adds an unsolicited cal kit → **sku_not_quoted** → cap 0.70 → L2 HITL.

### 6.3 Hold Release
Four hold-clearance scenarios — credit review (Bluehawk), payment cleared (Finolab), export-compliance EAR99 cleared (Nordstern), and Raytheon's ITAR / ECCN 3A002.f trade-compliance release.

### 6.4 Trade Change Order
Customer asks to change a booked order — qty bump, add a cal kit, update bill-to. The agent applies the line-item changes, recomputes the order total, and confirms.

### 6.5 SSD Change
Three flavors — pull-in (TSMC NPI gating), partial split shipment (Aurora), three EN/ES/JA reschedule variants.

### 6.6 Service Order Management

- **Create:** annual cal request (ISO 17025 / A2LA, Finolab); Z540.3 + MIL-STD program (Raytheon); A2LA cal in Spanish (Meridian); Japanese repair request with FOSI tag (Sakura); **multi-asset** request — one email lists 6 instruments, agent spawns **6 work orders** in one pass.
- **Update:** add notes/tasks to an open WO (Spanish); add 2 more assets to an existing cal job.
- **Inquiry:** urgent WO status (Tessera, customer audit Friday), routine status update (Aurora), Japanese WO status with OOT check (Ozeki).

### 6.7 Service Contracts
3-yr Cal Plan quote (12 assets, Z540.3 + on-site, Bluehawk); Z540.3 cal-plan renewal (Platinum SLA, Raytheon); PM-plan request in Spanish (Nordstern, ~8 instruments).

### 6.8 OCR — scanned PO image
A Japanese scanned PO PNG. Extract routes the image through the ZBrain document-intelligence agent and pulls PO number, line items, and the requested ship date directly from the picture. Reply drafted in Japanese.

### 6.9 Spam discard
Wire-fraud phishing and a promo-spam email. Both classified as spam, silently discarded, no human touched.

### 6.10 Ambiguous / Misroute / Multi-intent
- One-line "status?" — too little info → L2 HITL.
- WO status + AP question in one email — `misroute=true` flagged, **secondary intent** captured.
- Forwarded thread (with quoted history).
- EOL roadmap question — uses the catalog's lifecycle metadata (EOL date + successor SKU) to draft the migration recommendation.

---

## 7. Multi-language

EN, ES, JA validated end-to-end in this MVP. The detection and reply generation are language-agnostic by design — adding more languages in MVP+1 is a configuration-only change.

- **Detection** — Intake reads the body (and the optional system-supplied language hint) and emits the language tag.
- **Extraction** — All schemas are language-agnostic; the document-intelligence agent reads non-English bodies and attachments natively, including Japanese scanned PO PNGs.
- **Reply** — The communicate stage matches the detected language; the reply card surfaces the language flag and a "matches customer language" indicator.
- **Suggest-fix** — corrective emails are also drafted in the customer's language with proper formality registers (e.g. Spanish "Estimado equipo… Cordialmente").

Seeded coverage today: 5 EN clean POs, 1 ES PO, 2 JA POs (one scanned), 1 ES Q2O, 1 ES calibration request, 1 JA repair, 1 JA WO inquiry, 1 ES WO update, 1 ES service-contract request.

---

## 8. Human-in-the-Loop

When confidence falls below the L4 threshold, the system **does not write anything to the connected systems** until the CSR has approved. The HITL Queue panel surfaces:

- The **drafted customer reply** as the primary editable artifact — subject and body inputs, language flag, "edited" badge if dirty.
- An **intent-aware extracted form** — for PO/Q2O intents the reviewer sees a structured form with editable line items; for other intents it's a read-only summary. A "show raw JSON" toggle is always available.
- A **proposed action panel** with a polished summary plus a "show raw JSON" toggle.
- A **mismatches panel** when reconcile flagged variances, with side-by-side Quoted / PO / Δ comparison cells.
- A **✎ Suggest fix** button to draft a corrective customer email if the variance can't be approved as-is.
- Three resolution buttons: **Send reply** (approve as-is), **Apply edits & send**, **Reject**.

Approving applies the action through the same execution path that L4 auto would have used, marks the reply as sent, writes the Communication Log entry tied to the customer / order / WO, and closes the lifecycle ticket.

---

## 9. Continuous Learning Loop

Every CSR override is captured into the Feedback log with the stage that was overridden, the kind of override (intent correction, extracted-field edit, reply edit, rejection, approve-with-edit), an optional CSR note, and a JSON delta of the original vs corrected payload.

This feeds three loops:

1. **Prompt tuning** — recurring intent-misclassifications drive updates to the intake taxonomy and few-shot examples.
2. **Threshold tuning** — observed override rates per tier inform whether the L4 threshold should be tightened or loosened. (RFP: "Self-tuning confidence thresholds based on observed correction patterns.")
3. **Drift detection** — Analytics surfaces a drift signal when classification accuracy or extraction completeness drops below a baseline.

Every reply the system sends — whether L4-auto or CSR-approved — is logged in the **Communication Log** linked to the customer, the order/WO, and the originating pipeline. From the Data tab, opening any customer's 360° view shows the full chronological history of agent and CSR interactions for that account.

---

## 10. Recommended Demo Flow (≈ 5 minutes)

1. **Inbox tour** *(30s)* — 42 seeded emails across English / Spanish / Japanese with PDF, Excel, Word, and image attachments — covering all seven RFP happy paths.
2. **Clean PO** *(60s)* — pick a Bluehawk PO. Watch Live Trace stream Intake → Extract (PDF parsed) → Reconcile (clean) → Decide (L4 auto, ~0.97) → Execute → Communicate. Open the generated SOA PDF.
3. **Q2O with mismatch** *(60s)* — pick the Raytheon Q2O. Reconcile flags a price mismatch, decision capped at 0.70, tier drops to L2 HITL.
4. **HITL resolve** *(60s)* — open the Raytheon task in HITL Queue, show the variance panel, click **✎ Suggest fix** to watch the corrective email draft, then **Send reply**.
5. **Japanese scanned PO** *(45s)* — process the Sakura JA scanned PNG. The document-intelligence agent OCRs the image, pulls PO number / line items / ship date, and the customer reply is drafted in Japanese.
6. **Multi-asset cal** *(45s)* — process the multi-asset request. Execute creates **6 work orders in one shot**.
7. **Spam + Analytics** *(30s)* — process the phishing email (silently discarded). Open Analytics — automation rate, intent mix, mismatch types, communication log throughput.
8. **Customer 360** *(30s)* — open any customer in the Data tab. The right-rail shows account info, contacts, quotes, orders, WOs, installed base, service contracts, certs, invoices, and the chronological communication history.

---

## 11. Roadmap Beyond This MVP

**MVP+1 (30–60 days post-award)**

- **Salesforce CRM** integration — bidirectional sync of customers, contacts, quotes, opportunities.
- **Oracle EBS / SAP** ERP integration — orders, holds, schedules, shipments, invoices via MuleSoft / TIBCO middleware.
- **ServiceNow CSM** ticket parity — every customer-contact-center request lifecycle becomes a real ServiceNow ticket with the same state machine.
- **Microsoft 365 / Exchange** inbound listener replacing the seeded email queue, with regional mailbox support per RFP.

**Compliance & deployment**

- ITAR / GovCloud deployment for ITAR-flagged accounts.
- Enterprise data-handling tier with BAA + zero-retention model agreements.
- Full audit-trail export for SOX financial-controls audits.

**Continuous-learning operationalization**

- Quarterly prompt-tuning cadence driven by Feedback aggregations.
- A/B harness against a holdout slice before full rollout (RFP: "Support A/B testing of model improvements before full rollout").
- Auto-retraining trigger when classification accuracy drops below a configurable floor.

**Post-launch KPIs**

- Automation rate (RFP target 60–70%).
- Classification accuracy (RFP > 90%).
- Median CSR-touch processing time (hours → minutes).
- L3 one-click approval rate.
- HITL rejection rate per intent (drift signal).
- SOA-issued-to-PO-received SLA (< 1 business day).

---

## 14. Architecture Decision Log

A running log of the design conversations and the decisions taken. Each entry records the question, the options considered, the decision, and the rationale — so future maintainers and Keysight evaluators can audit *why* a particular shape was chosen.

### ADR-001 · Where does attachment OCR happen — Stage 1 or Stage 2?
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · **Status:** ✓ IMPLEMENTED
**Question:** When an inbound email has heavy attachments (multi-page PDFs, BOMs, scanned forms), should the OCR / document text extraction happen as part of Stage 1 (Intake) or Stage 2 (Data Extraction & Enrichment)?

**Options considered:**
1. **A — OCR only in Stage 2.** Stage 1 sees email body only. Pro: cheap, fast Stage 1. Con: insufficient signal when email body is just "Please find attached PO" — language defaults to EN, intent defaults to general_inquiry.
2. **B — OCR fully in Stage 1.** Stage 1 OCRs every attachment. Pro: maximum signal at intent time. Con: ~15-30s Stage 1 latency, $0.05+ per spam email.
3. **C — Hybrid (CHOSEN).** Stage 1 does *light* extraction (first 3 pages per attachment) gated by a cheap heuristic spam pre-check. Stage 2 does *full* extraction (all pages, structured fields per KB schema).

**Decision:** Option C. *Implemented in `Stage1IntakeAgent.run()` sub-step 1.3 with `max_pages=3` passed to `azure_doc_intelligence`. Stage 2 uses the same tool without a page cap.*

**Rationale:** Stage 1 needs *enough* signal to make a routing call but not so much that we waste money on spam. Capping at 3 pages keeps light extraction under $0.01 per email while giving the language detector and intent classifier real text to work with. Heavy extraction is deferred to Stage 2 where we already know the email is legitimate and which KB schema to apply.

### ADR-002 · Spam-check ordering within Stage 1
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · **Status:** ✓ IMPLEMENTED
**Question:** Does spam-check fire before or after language detection / translation?

**Options considered:**
1. **Spam-first** (the user's first instinct): cheaper if email is spam. Con: spam classifier degrades on non-English text.
2. **Language → Translate → Spam → Intent** (CHOSEN): translate cost (~$0.001) is small compared to the cost of a missed non-English phish.

**Decision:** Two-pass spam check.
- **1.2 — Heuristic spam pre-screen** (regex on subject + sender domain; ~free) discards obvious junk before extraction. Catches the 90% case.
- **1.6 — LLM spam check** runs after translate, on translated subject + body. Catches sophisticated multi-language phishing.

**Rationale:** Heuristic-first kills the majority of bulk spam at zero cost. LLM-second catches the rare but high-stakes cases (Spanish phishing, social-engineering) where the heuristic would miss.

### ADR-003 · Language detection: heuristic-only-with-LLM-fallback vs heuristic+LLM-always
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · **Status:** ✓ IMPLEMENTED
**Question:** Should the language detector short-circuit on heuristic match (cheaper) or always confirm with an LLM call (more reliable)?

**Decision:** Always run both.

**Rationale:** Heuristic alone leaks errors on mixed-language emails (German subject + English body, or technical jargon that masks the language). Cost of an LLM language call is ~$0.0002 — negligible. Both signals are surfaced in the UI; agreement implies high confidence, disagreement is flagged. LLM is the source of truth.

### ADR-004 · Provider naming convention
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · **Status:** ✓ IMPLEMENTED
**Decision:** LLM-driven sub-steps display as `ZBrain LLM (Claude Opus 4.7)`. The Claude version goes in parentheses for transparency; the brand surface is ZBrain. Translation steps with non-LLM adapters display as `Azure AI Translator`, `DeepL`, or `Google Cloud Translate v2`.

### ADR-005 · Sub-step expanded view layout
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · **Status:** ✓ IMPLEMENTED
**Decision:** Each sub-step's expanded panel uses a three-section structure: **Input** / **Output** / **Activities**. Input shows the data fed to the tool. Output shows the result (intent + reasoning, translated text, etc.). Activities is a collapsible block holding the system prompt, user prompt, raw response, KB rules consulted, evaluated rules table, and raw JSON.

### ADR-006 · Synthetic email addresses
**Date:** 2026-05-07
**Decision:** All `.example` domains replaced with realistic enterprise domains (`@nordstern-telecom.de`, `@bluehawkdefense.com`, `@meridiancomms.es`, etc.) in catalog.py, generate.py, and live records (Salesforce + SQLite).

**Rationale:** RFP-grade demo data should look like real customer email, not RFC-2606 placeholder.

### ADR-007 · Translation Knowledge Base
**Date:** 2026-05-07
**Decision:** Add a third KB namespace `translation` with 6 seed rules covering Keysight-specific terminology preservation (SKUs / ECCN / ITAR / SOA / brand) and tone/format guidance. The translate tool consults this KB before each LLM call and surfaces the consulted rule keys in the Activity drill-down.

### ADR-008 · Inbound Email card — language pill removed
**Date:** 2026-05-07
**Decision:** The "Spanish / English" pill on the email card was removed. Language detection is a Stage-1 sub-step (1.4 in the new design); showing it on the email card before Stage 1 has run leaks the IMAP-time heuristic and gives the false impression the agent has already classified.

### ADR-009 · Document text extraction adapters
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · **Status:** ✓ IMPLEMENTED
**Decision:** Three-tier adapter chain in `AzureDocIntelligenceTool`, priority order:
1. **AWS Lambda (Azure DocIntel-wrapped)** — set via `LAMBDA_DOCEXTRACT_URL` env. Default for the demo. POSTs `{"pdf_url": "..."}` and parses `{"content": "...", "filePath": "<presigned S3>"}`.
2. **Azure Form Recognizer direct** — set via `AZURE_DOCINTEL_ENDPOINT` + `AZURE_DOCINTEL_KEY`. Used when Lambda not configured or on a local file with no public URL.
3. **Local extractors** — pypdf / openpyxl / python-docx. Always available; runs without any cloud creds.

The tool accepts both a `url` input (preferred for Salesforce / SharePoint presigned URLs) and a `name`/`path` input (local UPLOADS file). For local files with `LAMBDA_DOCEXTRACT_URL` set, the URL is constructed from `APP_BASE_URL/files/uploads/<name>` when `APP_BASE_URL` is publicly reachable; otherwise the chain falls through to Azure-direct or local.

**Stage 1** invokes with `max_pages=3` (light extraction, ADR-001). **Stage 2** invokes without the cap (full extraction).

### ADR-010 · Stage 1 v2 — 7 sub-step flow live
**Date:** 2026-05-07 · **Status:** ✓ IMPLEMENTED
**Decision:** Stage 1 has been rewritten from 5 to 7 sub-steps as confirmed by ADR-001/002/003. Sequence and tool mapping:

| # | Sub-step | Tool | Method |
|---|---|---|---|
| 1.1 | Receive inbound communication | (none — implicit) | IMAP-poller ingestion |
| 1.2 | Heuristic spam pre-screen | `detect_spam` | Regex on subject + sender domain |
| 1.3 | Light attachment extraction | `azure_doc_intelligence` (max_pages=3), `vision_ocr`, `read_attachment` | OCR per attachment, capped |
| 1.4 | Detect language | `detect_language` | Heuristic + LLM, both run, agreement check |
| 1.5 | Translate to English | `translate_to_english` (LLM default; Azure / DeepL / Google adapters available) | KB-aware (translation namespace) |
| 1.6 | LLM spam check | `llm_spam_check` | LLM on translated subject + body |
| 1.7 | Classify intent | `classify_intent` | LLM, KB-driven (intent namespace), reasoning surfaced |

**Spam reconciliation:** if EITHER `detect_spam` (heuristic) OR `llm_spam_check` (LLM) OR `classify_intent` (LLM) flags spam, the pipeline forces `intent=spam`. The Activity-view sub-step 1.6 surfaces all three signals side-by-side so a CSR can see whether they agreed.

**Verified end-to-end on Pipeline #25** (Meridian Comunicaciones SA Spanish service-order email): all 7 sub-steps fired correctly, language detection ran heuristic+LLM with agreement, translation produced English text, LLM spam check categorized the email as `legitimate` at 96% confidence, classifier returned `service_order` at 95%.

---

### ADR-011 · OpenAI gpt-5.2 with strict JSON Schema for Stage 1 LLM tools
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · ✓ IMPLEMENTED
**Context:** The Claude Agent SDK passes the system prompt as a CLI argument (Windows `cmd.exe` 8 KB limit) and even when the prompt fits, the LLM repeatedly drifted from the strict JSON contract — emitting `primary_intent` instead of `intent`, burying confidence inside an `intents: [{...}]` array, putting autonomy-tier values like `"L4_auto"` in the `track_hint` field, and substituting `notes` for `intent_reasoning`. We were patching this with a post-LLM normalizer (~7 corrections per call). The user's principle: *"the normalizer should be the rarely-triggered safety net, not the daily band-aid."*
**Decision:** Switch all three Stage 1 LLM tools (`classify_intent`, `detect_language` LLM corroboration, `llm_spam_check`) to OpenAI **gpt-5.2** with `response_format = json_schema` (strict mode). The schema is enforced at the API level — malformed output never reaches our parser.
**Mechanics:**
- New module `app/services/openai_client.py` exposes `ask_openai_json(system, user, schema, schema_name)` with built-in retry across model fallbacks (gpt-5.2 → gpt-5 → gpt-4.1 → gpt-4o).
- Each tool defines its JSON Schema as a Python dict with `additionalProperties: false`, every field in `required`, and enums where applicable (e.g., `intent` enumerates the 13 canonical values).
- The legacy Claude path stays as a fallback when `OPENAI_API_KEY` is unset, so the demo still runs without the key.
- API key lives in `backend/.env` (gitignored).
**Verified on Pipeline #9:** classify_intent returned all 10 schema fields cleanly, intent=`quote_to_order` at **99.1% confidence**, `schema_enforced=True`, **`normalizer_corrections_applied=[]`** (was 7 corrections per call before).

---

### ADR-012 · `out_of_scope` intent + terminal-intent short-circuit
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · ✓ IMPLEMENTED
**Context:** The user connected their real Gmail inbox and immediately found a class of emails the classifier had nowhere to put: a Google account-security notification ("App password created"). It's not customer business, but it's also not spam — it's a legitimate transactional notification. The classifier defaulted to `spam` (wrong) and then ran ALL 8 stages downstream wasting ~22 seconds of LLM/Lambda calls.
**Decision:** Add a new canonical intent `out_of_scope` for legitimate non-customer-business email — automated notifications (Google/Microsoft account security, AWS billing, GitHub PR alerts), social-network alerts (LinkedIn), newsletter subscriptions, internal admin (HR/IT/payroll), out-of-office auto-replies, calendar invites, vendor receipts. Distinct from `spam` (which is unsolicited or malicious). Define `TERMINAL_INTENTS = {"spam", "out_of_scope"}` — both short-circuit the pipeline at Stage 1 and skip Stages 2-6 entirely.
**Mechanics:**
- `config.py` adds `out_of_scope` to `INTENTS`, defines `TERMINAL_INTENTS`, adds `INTENT_TO_FLOW["out_of_scope"]="discarded"`.
- `orchestrator.run_pipeline` checks `intake.intent in TERMINAL_INTENTS` immediately after Stage 1 commit. If matched, sets `pipe.status="discarded"`, closes the CCC with `fallout_reason ∈ {spam_discarded, out_of_scope_discarded}`, marks email status `discarded`, logs an explicit `short_circuit` trace event listing the skipped stages, and returns.
- `intake.py` system prompt extended with two worked examples (Google security alert; internal HR enrollment reminder) plus an explicit "out_of_scope vs spam" disambiguation block.
- Distinguishing them lets compliance/security report on real phishing separately from inbox noise.
**Verified on Pipeline #11** (the same Google "App password created" email): intent=`out_of_scope` at 97% confidence, status=`discarded`, only `intake` stage ran, total time 12s (vs 33s for the previous spam-misclassification run).

---

### ADR-013 · Stage 2 v2 — 4 sub-step flow with schema-driven extraction
**Date:** 2026-05-07 · **Status:** ✓ Confirmed by user · ✓ IMPLEMENTED
**Context:** Stage 2 was a single opaque "Document extraction" stage running OCR + an "LLM extraction" tool + entity resolve + SOQL queries with no clear sub-step structure for the trace UI. Customer match + Salesforce enrichment ran as separate stages BEFORE Stage 2 in the orchestrator. The user found "LLM extraction" confusing as a label and asked for the same per-sub-step drill-down treatment Stage 1 received.
**Decision:** Restructure Stage 2 into **4 explicit sub-steps**, rename "LLM extraction" → "Schema-driven extraction" (the LLM is driven by the intent's KB extract_schema rule — that's the meaningful framing), and move customer match + enrichment OUT of the orchestrator and INTO Stage 2 as sub-steps 2.3 and 2.4.

| # | Sub-step | Tool | Method |
|---|---|---|---|
| 2.1 | Document extraction | `azure_doc_intelligence` (NO page cap; `vision_ocr` for images; `read_attachment` for text) | Full OCR — fuller version of Stage 1.3 (which capped at 3 pages) |
| 2.2 | Schema-driven extraction | `schema_extract` (renamed from `llm_extract`) | OpenAI gpt-5.2 with `response_format=json_object`. The KB `extract_schema` rule for the email's intent IS the schema (po_intake → po_number/quote_number/line_items/total/…; service_order → service_type/assets[]/standards/…). Output validated and coerced against the KB schema. |
| 2.3 | Customer identification | `entity_resolve_customer` + Salesforce Account match | Uses the JSON from 2.2 (customer_name, customer_code, buyer_contact email) plus the email FROM as fallback. SF lookup chain: `Customer_Code__c` → `Contact.Email`. |
| 2.4 | Customer enrichment | `salesforce_soql` × N (intent-aware) + optional `salesforce_fetch_files` + `sharepoint_fetch_doc` | Different SOQL queries per intent: orders+opportunities+contacts for trade intents, work-orders for SOM, opportunities+contacts for service_contract, orders-on-hold for hold_release. Lives at `_ENRICHMENT_QUERIES` in `stage2_extract_agent.py`. |

**Architectural change:** Removed the standalone `enrichment` stage and pre-Stage-2 customer match block from `orchestrator.py`. Pipelines created from now on do not have a separate `enrichment` stage in their event stream — `extract` owns it via 2.3 / 2.4. The orchestrator retains a cheap pre-Stage-2 seed-based customer hint (just `Customer.email` lookup from the SQLite seed) so Stage 1 still has *some* customer context if needed; the authoritative Salesforce-backed match runs in 2.3.

**Naming:** "LLM extraction" was opaque. The user's mental model: "this is the step where the LLM uses the KB schema to pull structured fields." So: **"Schema-driven extraction"** — both the UI label and internal `tool_name = "schema_extract"`.

**OpenAI provider:** `schema_extract` uses `response_format=json_object` (not strict json_schema) because the per-intent extract_schemas have nested arrays (line_items, assets, line_changes) whose item shapes vary widely and would require building a full JSON Schema dynamically with inner `additionalProperties: false` rules. `json_object` mode guarantees valid JSON parse, which combined with our `_validate_and_coerce` against the KB schema field types (string/int/number/date/list/bool) is sufficient. Strict mode can be promoted later if drift is observed.

**Verified on Pipeline #13** (Aurora Automotive PO+BOM+ATP, intent=`quote_to_order`):
- 2.1: 3 attachments OCR'd (PDF via Lambda 7125ms; XLSX via openpyxl 4ms; DOCX via python-docx 10ms) → 2222 chars total
- 2.2: OpenAI gpt-5.2 extracted **10 fields, 4/4 required populated** (po_number=PO-AURA-AUTO-119-Q2O-72296, quote_number=QT-AURA-AUTO-119-DEMO, customer_name=AURORA AUTOMOTIVE ELECTRONICS, line_items=3 lines)
- 2.3: matched Aurora Automotive Electronics @ score 1.00 via SQLite seed (Salesforce was not reconnected after the most recent /api/seed/reset; mechanism is correct and will fire when SF is reconnected)
- 2.4: skipped (no SF account ID — see 2.3 note); 3 SOQL templates ready and would have fired

---

### ADR-014 · Stage 6 (Continuous Learning) → cross-cutting `/learning` page
**Date:** 2026-05-08 · **Status:** ✓ Confirmed by user · ✓ IMPLEMENTED
**Context:** "Continuous Learning" was Stage 6 in the per-pipeline orchestrator — every email run waited for a placeholder feedback-aggregation step. The user pushed back: *"continuous learning can't be part of the stages here so think about where you will place it as it will be more around collecting the feedback and then working on it."*
**Decision:** Pipeline now ends at Stage 5 (Communicate). The pipeline is **5 stages**, not 6. Continuous learning is reframed as a **cross-cutting dashboard** at `/learning` — operators visit it between runs to see aggregated feedback, drift signals, and KB-tuning suggestions.
**Mechanics:**
- `Stage6LearningAgent` removed from `orchestrator.run_pipeline`. `LearningStageCard` removed from `Trace.tsx`. `STAGES` array no longer includes "learning".
- New backend route `/api/learning/dashboard?window_days={7|14|30|90}` aggregates `feedback` + `pipelines` rows into 4 KPI tiles + per-stage feedback heatmap + drift signals + intent-misclassification corrections + KB-tuning suggestions + 24h throughput.
- New frontend page `/learning` (top-nav item between "Knowledge Base" and "Feedback") renders the dashboard.
- No new schema; built on existing data the system already collects via the 👍/👎 buttons in `Trace.tsx`.

---

### ADR-015 · Stage 3 substep events
**Date:** 2026-05-08 · **Status:** ✓ IMPLEMENTED
**Decision:** Stage 3 (`Stage3DecideAgent.run`) emits `substep_start` / `substep_done` events at all four sub-steps so the trace UI can render rich drill-downs matching Stage 1/2:
- 3.1 Reconcile-vs-quote summary (input: extracted PO/quote_ref; output: matched_quote + issues[])
- 3.2 Confidence formula (input: signals dict; output: formula breakdown by weight + base confidence)
- 3.3 Business rules + floor caps (input: rules-evaluated count; output: each fired rule, each applied cap with from→to confidence shifts)
- 3.4 Final tier decision (input: final confidence; output: tier + action + flow + thresholds)

---

### ADR-016 · Stage 4 substep events on every action path
**Date:** 2026-05-08 · **Status:** ✓ IMPLEMENTED
**Decision:** Stage 4 emits substep events for **all action paths**, not only the `create_order_acknowledgment` (PO-ack) branch. Convert-quote-to-order, release-hold, reschedule-order, service-order, etc. all surface 4.1/4.2/4.3/4.4 events. The 4.4 ServiceNow event explicitly marks the SN integration as "deferred to Phase 2" so the UI shows a clear placeholder rather than a missing step.

---

### ADR-017 · Stage 5 substep events
**Date:** 2026-05-08 · **Status:** ✓ IMPLEMENTED
**Decision:** Stage 5 (`Stage5CommunicateAgent.run`) emits substep events at four points: 5.1 LLM draft (subject + body chars + body preview), 5.2 translation (skipped when customer language is en, otherwise shows source/target language + chars), 5.3 attachment generation (filename list), 5.4 communication-log intent (tier + auto-send eligibility). The actual SMTP send happens later (in `routes/hitl.py` on approval, or in the orchestrator's L4 finalization) — Stage 5 stages the artifacts.

---

### ADR-018 · Pipeline reliability hardening (rollback-on-exception, bus thread-safety, idempotency, WAL)
**Date:** 2026-05-08 · **Status:** ✓ IMPLEMENTED · root-caused via systematic substep tracing during QA
**Context:** During cross-intent QA, repeat-run pipelines (running the same email twice) silently hung for tens of minutes at `[execute stage_start]` with no log output. Root-causing required adding fine-grained `LE_BEFORE_FLUSH/AFTER_FLUSH` tracing inside `log_event` to localize the exact line that hung.
**Findings + fixes** (all live):
1. **Session-aborted hang.** When a stage threw inside `with stage_timer:`, the orchestrator's exception path called `log_event` → `db.flush()` on a session whose previous transaction was already aborted. SQLAlchemy 2.0 raises `PendingRollbackError`, but on Windows + SQLite this flush sometimes BLOCKED instead. → **Fix:** wrap `stage_timer.__exit__` and the orchestrator's outer `except` with `db.rollback()` *before* any post-exception write.
2. **Cross-thread asyncio.Queue puts.** `bus.publish` ran on the orchestrator's BackgroundTasks thread and called `q.put_nowait()` directly on `asyncio.Queue` instances owned by the FastAPI loop — not thread-safe; can block. → **Fix:** cache the FastAPI loop on first SSE subscribe, and route every cross-thread put through `loop.call_soon_threadsafe(_sync_put, q, msg)`. Wrapped publish in try/except so a publish failure can never block the pipeline thread.
3. **`create_order_from_quote` non-idempotency.** Re-runs of the same email hit `UNIQUE constraint failed` when inserting an Order, then `_apply` propagated the exception → bug #1 hung the pipeline. → **Fix:** look up the existing Order on `Order.quote_id == q.id` and return it instead of inserting a duplicate.
4. **SQLite contention.** Email-sync poller + pipeline writes on the same SQLite file occasionally returned `database is locked`. → **Fix:** `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000` on every connection (one-time pragma listener registered in `db.py`).
5. **`email_sync._due()` tz-aware vs tz-naive subtraction crash-loop.** → **Fix:** coerce both sides of the comparison to naive in `_due()`.
**Verified end-to-end on a sequential 8-pipeline QA pass** covering po_intake / quote_to_order (en+es+ja) / service_order / service_contract_request / wo_status_inquiry / out_of_scope (×2). All 8 pipelines completed in 9-105s; routing matrix matches the design (L4_AUTO for clean cases, L3_ONE_CLICK for mid-confidence, L2_HITL for sparse extractions, discarded for out_of_scope).
