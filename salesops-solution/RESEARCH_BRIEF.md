# Keysight RFP Research Brief

**Audience:** any agent or session continuing work on the keysight-salesops-demo. Read this end-to-end before making changes — it consolidates everything learned from prior-POC artifacts, ZBrain workflow exports, and the live Keysight RFP Q&A call. Pair it with `SESSION_HANDOFF.md` (active lane coordination) and `CLAUDE.md` (architecture + branding rules).

**Last updated:** 2026-05-08 (deadline 2026-05-10).

---

## TL;DR

We are building an MVP demo (`keysight-salesops-demo`) for a Keysight RFP. LeewayHertz previously delivered a Keysight POC built on the ZBrain platform (Activepieces under the hood, gpt-4.1 on Azure). That POC is **only Agent #1 — email classification + Outlook folder routing**. Agents #2 (CCC creation) and #3 (CCC assignment) were narrated in business-rule docs but the running flow we have is just the classifier.

The customer's RFP expects a comprehensive end-to-end (intake → classify → extract → reconcile → decide → execute → communicate → learn) with ZBrain branding. Our build covers the full pipeline; the prior POC's classifier rules and operational behaviors are not yet adopted into our intent KB or our deterministic-rules layer.

This brief identifies (a) what their POC actually does, (b) what they want from the new system per the RFP and clarifying call, and (c) the prioritized gap list to close before the demo.

---

## Table of contents

1. [Source materials inventory](#source-materials-inventory)
2. [The prior POC — what was actually built](#the-prior-poc--what-was-actually-built)
3. [RFP Q&A call — direct customer answers](#rfp-qa-call--direct-customer-answers)
4. [Their classification taxonomy + override rule book](#their-classification-taxonomy--override-rule-book)
5. [Our current build — delta state](#our-current-build--delta-state)
6. [Recent work in active session](#recent-work-in-active-session)
7. [Comprehensive gap analysis](#comprehensive-gap-analysis)
8. [Specific user feedback captured](#specific-user-feedback-captured)
9. [Lane assignments (Session A vs Session B)](#lane-assignments-session-a-vs-session-b)
10. [Open questions / pending decisions](#open-questions--pending-decisions)

---

## Source materials inventory

### Prior-POC business artifacts — `C:\Users\Rituraj\Downloads\keysight poc\`

| File | What it is | Useful for |
|------|------------|------------|
| `ISC WO RTK.txt` | Three Agent narratives (Agent 1.3 sorter, Agent 2 CCC creator, Agent 3 CCC assigner) for Service Work Order Return-to-Keysight | Multi-asset rules (1 CCC per asset), CCC-status branching, Salesforce field mappings |
| `KeySight-ISC WO RTK-080526-101615.pdf` | Visual one-pager of ISC WO sorting | Same as above, picture form |
| `Sales PO Std Process & Change order (1).pdf` (16 pages) | Three Agent narratives for Sales PO + Change Order processing | Disty list, dummy SKUs (CUSTOM PRODUCT, SOWDUMMY, EXPORTDUMMY), bill-to/ship-to mismatch handling, Stock Rotation / Rebates / eBiz / SOW subtypes |
| `Current Outlook Rules_Narratives (1).pdf` (6 pages) | Six pre-AI Outlook rules: Undeliverable / KSO govt / Collections / Portal Admin / Brazil Tax / Auto-Reply | Deterministic rule layer that runs *before* the AI |
| `FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx` (4 sheets) | Test corpus: 109 emails with expected vs actual tags from two re-runs (24-04-2025, 25-04-2025), accuracy report, non-supported attachment list | Regression testing model; their initial 57% → post-fix 96% accuracy story |
| `Front Office Request - Data Request.xlsx` | Data-request schedule for the design phase (50 emails sample, dept listing, category listing, priority listing, employee listing, dept-assignment logic, employee category, past resolutions) | Their expectations of what data we should be collecting |

### ZBrain workflow exports — `C:\Users\Rituraj\Downloads\Agents\`

| File | What it is |
|------|------------|
| `KS FO Agent.json` (260KB) | Activepieces workflow for **Agent #1 (Outlook classifier)**. 80 steps, 1193 string leaves. |
| `KS FO FLOW.json` (260KB) | **Byte-identical** to `KS FO Agent.json` except for `created`/`updated` timestamps. Same flow exported twice. |

These exports do **not** contain Agent #2 or Agent #3 — only Agent #1.

### RFP Q&A call

- Transcript captured on 2026-05-08
- Participants: Keysight project leads + LeewayHertz team (Rituraj, Deepak, Manuj)
- ~31 minutes
- Topics: confidence scoring, regions, governance, integrations, volume, mailbox consolidation

---

## The prior POC — what was actually built

### Agent #1 — Outlook classifier (running today)

A 80-step Activepieces workflow that fires on every email arriving at `keysight.ai-front-office@keysight.com`:

```
Webhook trigger
  ↓
Telemetry: insert row in Google Sheets (status="Fail", startTime)
  ↓
Generate UID (KV-store COLLECTION-scope counter "KS-UUID")
  ↓
Format thread (parse multi-message thread structure)
  ↓
ROUTER: has attachments?
  YES → Loop on attachments → per-file-type pipeline:
    PDF   → PDF-to-Images → Amazon Textract per page → save to RUN store
    DOCX  → custom JS extractor → save / exception
    CSV   → custom JS extractor → save / exception
    XLSX  → custom JS extractor → save / exception
    TIFF  → OCR handler → save / exception
    Image → Amazon Textract → save
    HTML  → strip tags → save
    Text  → read → save
    (anything else) → "Exception DB"
  NO  → blank-mail check
  ↓
Three AI classifier passes (gpt-4.1 on Azure):
  1. "Checking the Context"  (5077-char system prompt, temp 0.3)
  2. "Checking Override"     (25375-char system prompt, temp 0.4 — the 27-rule override book)
  3. "New rules Test"        (15281-char system prompt, temp 1.0 — modular test classifier)
  ↓
Parse + merge: step_39 (primary final answer), step_63 (test classifier output)
  ↓
Microsoft Graph API:
  PATCH /messages/{id}                  → set isRead=true, flag=notFlagged
  POST  /messages/{id}/move             → move to per-category folder
  ↓
Telemetry: update row (status="Success", endTime, category, keywords, reason, override category, override reason)
  ↓
ROUTER: Call Agent 2 (entry point — calls "Get Country List from KB" + "Info Extraction" + 2 JS post-processors)
  ↓
Cleanup: remove RUN-scoped attachments_data_<id>, EMAIL_DATA_<id>, exception_data
  ↓
Final dashboard output (markdown report + row ID)
```

### Agents #2 and #3 — narrated in business-rule docs only

**Agent #2 — CCC Request Creation** (per `ISC WO RTK.txt` and `Sales PO Std Process` PDF):
- Search Salesforce by PO# / WO# for an existing CCC Request
- Branch on CCC status:
  - `Cancelled` → create new CCC
  - `Closed` → clone as Change Order Request
  - `Assigned`, `New`, `In Progress`, `Continue Processing`, `A/W Internal-FE`, `A/W Internal-System`, `A/W Customer-CIA`, `A/W Customer-info` → attach email + flip status to "Continue Processing" + notify owner via Salesforce Chatter
- If no existing CCC: create from contact (look up sender's email globally; create account/contact if missing; submit account to CMD for activation)
- Populate Origin (E-MAIL/Fax/Portal), Received Date/Time, Type, Subtype, Ship-to address, PO#, Product Interests
- **Multi-asset rule:** 1 CCC per asset, NOT 1 per email. Clone first CCC for each additional asset; update address on each clone.
- Custom-product fallback: SKU not in Salesforce → "CUSTOM PRODUCT" + put model+serial in FE Comments
- Attach email file to CCC ("Files" quick link, doc type FCNV)
- Add Activity task: subject "other", status "Completed", comments "ISC"

**Agent #3 — CCC Request Assignment**:
- Auto-assign via "Assign" button if status=New, type=Order Request/Work Order, ship-to matches
- Verify owner changes from creator to CSR
- Routing exceptions:
  - Disty partners (US/Canada list: RS, Avnet, ConRes, Electrorent, Gap Wireless, Mouser, Newark, RFMW, Tessco, TestEquity, Transcat, TRS) → AMFO_Disty/Rental queue
  - LAR Disty list (AQTK Peru, Complementos Electrónicos, Element14 MX, Grupo Prod&Khym, Hi-Tech, INCAL, Inceleris, Interlatin, JMD, Karimex, Negenex, Nextest, OHMINI, Precision Solutions, Q-Wire, RCBI, Servicios Técnicos, Tecnología y Electrónica, TestEquity MX) → same queue
  - Standard customer ordering disty product → CUSTOM PRODUCT trick to escape AMFO_Disty/Rental
  - Non-US final destination → Export Team via EXPORTDUMMY
  - SOW (Z product, "Statement of Work", "Cover Letter", "EID #") → SOW Team via SOWDUMMY
  - eBiz / KRS / "Keysight Used Equipment Store" → AMFO_Disty/Rental queue
- After assignment: prepend CCC Request # to email subject + move to Outlook "Archive" folder
- **Override:** any specific FE/CSR routing instruction in the email body supersedes system routing.

### Outlook pre-AI rules (six rules, run *before* the AI fires)

| Rule | Trigger | Action |
|------|---------|--------|
| **Undeliverable** | Subjects: "Undeliverable", "Mail Delivery Failure", "Returned Mail", "Mail Delivery Failed", "DELIVERY FAILURE"; sender contains `mailer-daemon`; from `noreply@keysight.com` | Move to "Undeliverable" folder |
| **KSO** | Sender domain in govt/defense list (`@lmco.com`, `@l3harris.com`, `@boeing.com`, `@nasa.gov`, `@baesystems.com`, etc.); body contains govt-prime keywords (`N5194A`/`N5193A`/`N5192A`/`N5191A`, `Boeing`, `Sandia`, `Tevet`, `Peraton`, `Vallen`, `Leidos`, `Raytheon`, `Pratt Whitney`, `Cobham`, `General Dynamics`) | Redirect to `keysightorders@keysight.com` + delete original |
| **Collections** | Subject/body keywords: "Remittance Advice", "Payment Advice", "ACH Payment", "early payment opportunity", "GOOGLE PAYMENT NOTIFICATION", "your invoice has been received and may require additional attention" | Redirect to `collections.pdl-americas@keysight.com` + `usar_keysight@keysight.com` + archive |
| **Portal Admin** | Keywords: "Password", "validation code", "verification code" | Save copy in inbox + redirect to `portal-admin.pdl-ccc-americas@keysight.com` |
| **Brazil Tax** | From `keysight.bra-tax@tmf-group.com` | Redirect to `lar_orders@keysight.com` + archive |
| **Auto Reply** | Subjects: "Automatic Reply", "Out of the office", "OUT OF OFFICE" | Move to "Out of Office" folder |

### Test corpus (`FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx`)

109 emails, expected-vs-actual tags from two reruns (24-04-2025, 25-04-2025) with reason and keywords for each.

**Accuracy progression:**
- 109 total
- 62 passed initial run (57%)
- 47 failed initial → 41 fixed and re-passed (76% of failures recovered)
- 5 still failed after fixes (4.6% hard-fail, 96% post-fix accuracy)

**Non-supported attachment types found in failures:**
- Outlook `.msg` items embedded as attachments (forwarded chains-as-attachments)
- `.gif` images
- `.msg` + `.gif` combinations

---

## RFP Q&A call — direct customer answers

### Confidence / accuracy scoring (Stage 3)

**4 distinct gates:**
1. **Classification confidence** — is this a PO vs WO vs status request?
2. **Extraction confidence** — did we extract all required fields per intent's data schema?
3. **Entity Resolution confidence** — binary, did we find the matching SO/WO record in Salesforce?
4. **Action Feasibility confidence** — can we actually execute the action with the data we have?

Important nuance: Speaker 6 clarified "scope of confidence/accuracy is per-transaction, not historical data." Each email gets its own per-gate score based on what's in that email — not based on past accuracy. **Our current weighted formula `0.45·intent + 0.35·extract + 0.20·customer-match` collapses these into one number**, which the customer will not recognize.

### Regions

- Americas, Europe, APAC, Japan
- Some country-specific nuances (Japan often requires extra fields)
- **Push toward globally-standardized process**, but region-specific exceptions remain (and are clearly documented when they apply)

### CRM / ERP / other systems

- **Salesforce**: ONE global instance (no multi-tenant data sharding needed)
- **ERP**: **Oracle** (must be named explicitly in solution doc, not a generic placeholder). Integration via middleware ("Git for a metal web" — likely a misheard reference to Oracle's REST API or an internal middleware named that way)
- **ServiceNow**: approval engine for change orders, reminder workflow only — **not** part of AI processing path. AI agent calls ServiceNow APIs for approvals/reminders.
- **Document storage**: "M..." (incomplete word, likely Microsoft something — possibly SharePoint or Mosaic)
- **KS support portal**: lookup destination

### Volume

- **530K emails/year** (per RFP — value mentioned as "yearly email volume")
- **80-90 concurrent users** at peak (across global timezones); total user pool 600-700
- **Burst spikes** at quarter-end, year-end, month-end (status check waves)
- **Stress-test target**: "100 emails/second" — Speaker 6's stated benchmark for system load testing

### Government / restricted handling

- Govt customer emails arrive at the same shared inbox
- Agent must apply rules like: "non-US-citizen cannot read this email → route to dedicated box"
- **Citizenship-based routing** (not just keyword/domain-based KSO classification we already have)

### Translation

- Customer emails arrive in many languages
- Internal systems are not standardized to English
- **Reuse existing Keysight translation knowledge base** with modifications/additions for the specific use cases we encounter

### Governance

**Enterprise level:**
- **Microsoft Purview** (or hyperscaler equivalent) — governs entire agent portfolio
- All agents managed through the Microsoft governance toolchain

**Per-application level:**
- RBAC (privilege rings per agent)
- Existing policies applicable to the agent
- SLO definitions
- Circuit-breaker policies
- MCP-tool scanning + connection control + prompt-injection prevention

**Hosting:**
- ZBrain to be deployed on **Azure** (AS = Azure Subscription/Stack inferred from context)
- Cloudflare in front of any internet-exposed agent (most internal-only, so usually not needed)

### Mailbox consolidation

- **Today: ~50 inboxes**
- **Target: 1-2 inboxes**
- Consolidation effort separate from the AI project, partial overlap during transition
- Demo phase target: ~40 inboxes
- Agent must work transparently across N inboxes during transition; downstream classification + routing should not depend on which inbox the email arrived in

### Approach + timeline

- ~1-2 weeks of requirement-gathering after vendor selection
- Then straight into design phase + agile implementation (no big up-front BRD phase)
- Start with classification rules + business rules, expand from there
- Champions and leads identified on both IT and business side already

### Today's automation state (manual baseline)

- First step (classification) is **manual today**
- Some small per-team automations exist (e.g., regional teams have a few Outlook rules for OOO)
- **Validation, parsing, downstream actions are all manual**
- Outlook rules vary by region; some regions have aggressive rule packs, some have almost none

---

## Their classification taxonomy + override rule book

### Nine-class taxonomy (vs our 12-intent taxonomy)

| Their class | Our equivalent | Action |
|-------------|----------------|--------|
| **KSO** | (missing) | Govt/defense — redirect to keysightorders@ |
| **ISC_WO_RTK** | service_order, wo_update_request, wo_status_inquiry, service_contract_request | Service WO Return-to-Keysight |
| **SALES_PO** | po_intake, quote_to_order, trade_change_order, hold_release | Standard PO + Stock Rotation, Rebates, eBiz, Prebuild, Amendment, Cancellation, Change Quantity, Duplicate PO, Confirm orders |
| **UNDELIVERABLE** | (missing — we use spam) | mailer-daemon / noreply@keysight.com / specific subjects |
| **COLLECTIONS** | (missing) | Remittance / payment advice / ACH / banking |
| **PORTAL_ADMIN** | (missing) | Password / verification code / OTP |
| **BRAZIL_TAX** | (missing) | `keysight.bra-tax@tmf-group.com` (also flagged on `@gmail.com` senders!) |
| **AUTO_REPLY** | (missing — we use spam) | OOO / Auto-reply patterns |
| **OTHERS** | general_inquiry, ssd_change_request, delivery_change | Catchall |

### Override prompt — 27 numbered rules

The 25KB override system prompt (in `KS FO Agent.json` step 17 "Checking Override") is months of refined operational logic. Highlights every demo-quality classifier should respect:

- **Empty-fragment skip** — strip messages containing only From/To/Subject, CAUTION banners, disclaimers, quoted threads. Only classify on the *first non-empty* fragment in the body array.
- **Internal Keysight-to-Keysight detection** → OTHERS *unless* `keysight.ai-front-office@keysight.com` is in `To:`.
- **Valid Content taxonomy (8 categories of what counts as actionable):**
  1. User-written business actions ("Please process the attached PO")
  2. Business inquiries (PO/WO status, invoice/payment queries, PO release / tax cert)
  3. Actionable auto-replies (auto-responses with commercial intent)
  4. Undeliverable / bounce messages (from valid sources)
  5. Portal-generated / system-generated transactional messages
  6. Forwarded blocks containing structured data (WO numbers, model details, calibration info)
  7. Scope change / service adjustment requests ("Please provide a 30-day extension")
  8. Auto-reply emails with business context
- **Generic-phrase handling** ("FYI", "see below", "looping you in") — *don't* immediately mark OTHERS, walk back through the thread first to find earlier valid content.
- **Conditional approval detection** — phrases like "Approved – book under resale", "PO is approved for release upon tax confirmation" → SALES_PO.
- **Acknowledgement-only thread (Rule 25)** — if PO# only appears in attachment file named "Sales Order Acknowledgement", *don't* treat as a real PO.
- **PO + WO conflict (Rule 3)** — PO mentioned with WO/Repair/Cal → ISC_WO_RTK *not* SALES_PO.
- **PO + factory calibration of new unit (Rule 3A)** — `cal cert` / `factory calibration` / `with calibration` on a new PO is still SALES_PO, not RTK service.
- **PO Clarification within active transaction (Rule 18A/B)** — if vendor has acknowledged, follow-up clarifying questions retain SALES_PO; vague open questions go to OTHERS.
- **PO Mentions without directive (Rule 19)** — passive verbs like "any update?", "is this okay?" → OTHERS, *but* line-item cancellation is still SALES_PO (Exception 19).
- **Service-only inquiry (Rule 13/20)** — keyword-only mentions of WO/Repair without a directive → OTHERS.
- **Two-stage classification** — they intentionally run a *Context* pass and an *Override* pass and a third "New Rules Test" pass and store BOTH primary and test outputs side-by-side.
- **Actionable auto-reply detection (Rule 7/9)** — patterns like "I'm no longer with", "Please contact", "Kindly reach out" classified as AUTO_REPLY *unless* they include a question/PO/WO instruction.
- **Strict per-rule stop-at-first-match** — modular structure, scan UNDELIVERABLE → AUTO_REPLY → BRAZIL_TAX → PORTAL_ADMIN → COLLECTION → KSO → ISC_WO_RTK → SALES_PO → OTHERS in that order.

### Output schemas

Both classifiers return:
```json
{ "category": "<UNDELIVERABLE|AUTO_REPLY|BRAZIL_TAX|PORTAL_ADMIN|COLLECTION|KSO|ISC_WO_RTK|SALES_PO|Others>",
  "keywords": ["...exact terms matched from rules..."],
  "rule_applied": "<which rule fired>",
  "reason": "<brief explanation>",
  "override_triggered": true|false }
```

### Telemetry sheet (Google Sheets `1jIpjfyRkK1EAxd9CVzl2CRKKC42yIyEAIQBBPObTxrY`)

Every email gets one row, status flips `Fail → Success` at end. Columns:

| Col | Field |
|-----|-------|
| A | currentId (UID) |
| B | inboxTime |
| C | agentTime |
| D | subject |
| F | category (final) |
| V | status (Fail/Success) |
| Z | startTime |
| AA | endTime |
| AJ | senderEmail |
| AL | keywords |
| AM | reason |
| AR | override category (test classifier) |
| AS | override reason (test classifier) |

---

## Our current build — delta state

**Repo:** `C:\Users\Rituraj\keysight-salesops-demo\`. See `CLAUDE.md` for arch + branding rules and `SESSION_HANDOFF.md` for active session coordination.

### Architecture

```
[ React/Vite UI ]  <->  [ FastAPI ]  <->  [ ZBrain orchestrator runtime (claude-agent-sdk) ]
       |                     |                          |
   ZBrain theme         SQLite + files            6 stage subagents
   (#1A55F9)            tracing event bus         Intake → Extract → Reconcile → Decide → Execute → Communicate
```

### Pipeline stages (ours)

1. **Intake** — language detect, intent classify, spam/phishing screen, track hint (Stage 1 v2: 7 sub-steps)
2. **Extract** — PDF/XLSX/DOCX/image, intent-specific schema, structured fields (Stage 2 v2: 4 sub-steps)
3. **Reconcile** — cross-check PO line items vs matched quote in CRM
4. **Decide** — confidence scoring, tiered autonomy: L4 ≥95% auto / L3 80–94% one-click / L2 <80% full HITL
5. **Execute** — CRM/ERP calls (Salesforce real, others mocked → SQLite)
6. **Communicate** — drafts reply in customer's detected language, attaches synthetic SOA PDF; SMTP-sends via the connected Gmail account

### Languages

EN, ES, JA (Phase 1). Add more after demo lands.

### Real integrations live today

- **Email (Gmail IMAP+SMTP)** — orderinbox@leewayhertz.com connected; messages auto-poll every 60s; HITL approve actually sends real reply via SMTP through the same account
- **Salesforce** — OAuth client_credentials + REST/SOQL, Customer/Contacts/Quotes/Orders/Products/Assets queries
- **ServiceNow** — Basic Auth REST, incident table CRUD
- **SharePoint** — OAuth client_credentials + Microsoft Graph, list/upload/download/delete on a configurable folder (currently `/Salesops` in `zbrainsalesops` site)

### Mocked still

- ERP write-backs (need to be Oracle, not generic)
- Field service (assets, service contracts, calibration certs)
- Document Management (uploads/ + outputs/ — partly real now via SharePoint)

### Synthetic data

10 customers, 22 SKUs, 19 quotes, 6 orders, 6 work orders, 31 emails using Keysight vocabulary (DUT, ISO/IEC 17025, Z540.3, A2LA, ECCN/ITAR/EAR99, etc.).

---

## Recent work in active session

(2026-05-07 → 2026-05-08, Session B / email-inbox-synthetic lane)

1. **Gmail account connected** (`orderinbox@leewayhertz.com`) via app password; 50 messages imported initially.

2. **SMTP outbound from HITL** — HITL approve now actually sends a real reply through Gmail SMTP (port 587 STARTTLS), reusing the IMAP app password. Files:
   - `backend/app/services/email_outbound.py` (new)
   - `backend/app/routes/hitl.py` (wired send into resolve)
   - `frontend/src/pages/Hitl.tsx` (toast on send)
   - `backend/app/routes/email_accounts.py` (`/test-smtp` endpoint)
   - `frontend/src/pages/settings/Connections.tsx` ("Test send" button)
   - Outbound kill-switch via `OUTBOUND_EMAIL_ENABLED=0` env var (added later)

3. **Email model extended** with `account_id` (FK), `message_id`, `in_reply_to`, `email_references` columns; `CommunicationLog` extended with `delivery_status`, `delivery_error`, `provider_message_id`, `sent_via_account_id`. Migration via new `db_migrate.py` (idempotent ALTER TABLE on startup).

4. **Inbox filter fix** — bug fix in `routes/emails.py`:
   - Old join `Email.pipeline_id == Pipeline.id` only saw 5 of 21 pipelines (back-pointer set inconsistently)
   - New join `Pipeline.email_id == Email.id` (canonical FK) with latest-per-email subquery
   - Added `GET /api/emails/counts` endpoint
   - Frontend dropdown shows counts inline + adds "Rejected" option

5. **SharePoint full integration** — parallel to Salesforce/ServiceNow connection management:
   - `SharePointConnection` model (encrypted client_secret, site_id, folder_path, drive_id)
   - `services/sharepoint.py` (whoami, test_connection, upsert_connection, refresh_status, list_files, upload_file, download_file, delete_file, current_credentials bridge)
   - 10 routes under `/api/integrations/sharepoint/*`
   - Connect modal + status tile in `Settings → Integrations`
   - Verified end-to-end: upload → list → download → delete in `/Salesops` of `zbrainsalesops` site

6. **`current_credentials(db)` bridge** in `services/sharepoint.py` so Session A's existing `sharepoint_fetch_doc_tool.py` can read creds from DB instead of env vars (one-line tool change pending).

7. **Comprehensive analysis** of (a) prior-POC business artifacts, (b) ZBrain workflow JSONs, (c) RFP Q&A transcript — captured here.

---

## Comprehensive gap analysis

Ranked by RFP impact and demo visibility. Items marked 🟥 should land in the demo; 🟧 strong-credibility adds; 🟨 polish.

### 🟥 P0 — directly answers RFP questions or matches existing operational behavior Keysight already has

| # | Gap | Source | Effort | Lane |
|---|-----|--------|--------|------|
| **1** | **Adopt their 9-class taxonomy + 25KB override rule book** verbatim into our intent KB | ZBrain JSON | 2-4 hrs | Session A |
| **2** | **Restructure intent KB as schema-driven** (keywords, sender_patterns, examples_positive, examples_negative, exceptions, precedence — not just `definition`). Generate classify_intent prompt from KB at request time. | User explicit feedback | 4-6 hrs | Session A |
| **3** | **Pre-AI deterministic Outlook-rules layer** (Undeliverable, KSO redirect, Collections redirect, Portal Admin redirect, Brazil Tax redirect, Auto Reply quarantine) — runs *before* Intake LLM | Outlook Rules PDF | 4-5 hrs | Session A (new stage) + cross-cutting Email model column for "redirected_to" |
| **4** | **4-gate confidence model** — split our single score into Classification / Extraction / Entity Resolution (binary) / Action Feasibility, displayed independently in Trace + HITL UI | RFP Q&A call | 3-4 hrs | Session A (Decide stage) + UI (mostly Session A's Trace.tsx) |
| **5** | **Two-stage classifier** (Context-pass → Override-pass) with side-by-side test classifier slot for shadow A/B | ZBrain JSON | 3-4 hrs | Session A |
| **6** | **Empty-fragment thread pre-processing** (strip empty forwards/banners/disclaimers, walk back to first valid content fragment) — feeds the override prompt's expectations | ZBrain JSON | 2 hrs | Session A or shared (`email_thread.py`) |
| **7** | **Existing-CCC status branch** — search Salesforce by PO#/WO#, branch on CCC status (Cancelled→new / Closed→clone-as-Change-Order / 7 other states→attach+continue) | ISC WO RTK + Sales PO PDFs | 5-6 hrs | Salesforce service (mine) + Decide stage (Session A) + new Pipeline columns |
| **8** | **Multi-asset fan-out** — 1 CCC per asset, not 1 per email. Clone first CCC for each additional asset, address-update per clone | ISC WO RTK | 3 hrs | Execute stage (Session A) |
| **9** | **Outlook back-stamping (IMAP source)** — after pipeline, IMAP COPY+EXPUNGE to move email to per-category folder in `orderinbox@leewayhertz.com`; prepend CCC# to subject | ZBrain JSON Graph API + Sales PO PDF + RFP call | 3 hrs | Mine (`imap_client.py` new method) |
| **10** | **Per-category routing folder map** UI — Settings → Inbox Routing → table mapping each category to a destination folder | ZBrain JSON step_61 | 2 hrs UI + 1 hr backend | Mine |

### 🟧 P1 — significant for credibility

| # | Gap | Source | Effort | Lane |
|---|-----|--------|--------|------|
| **11** | **Distributor partner list + magic-SKU routing** (CUSTOM PRODUCT / SOWDUMMY / EXPORTDUMMY) in KB; UI tab with disty list editor | Sales PO PDF | 2-3 hrs | Session A KB |
| **12** | **Region-aware rule packs** — KB rules can be tagged with applicability region (Americas / EU / APAC / Japan / Global) | RFP Q&A call | 2-3 hrs | Session A KB |
| **13** | **CSR-instruction override detection** — LLM micro-step in Intake returns `{has_override, override_instruction}`; FE/CSR text instructions in body supersede system routing | Sales PO PDF + ISC WO RTK | 1-2 hrs | Session A |
| **14** | **Bill-to / Ship-to mismatch routing** — model both addresses, route on ship-to via Assignment Lookup while CCC carries bill-to entity | Sales PO PDF | 2 hrs | Session A + Email/Order schema |
| **15** | **Telemetry "ops dashboard"** — flat one-row-per-email view with the 13 fields (timing, classification, override, keywords, reason). Match their Google Sheet column scheme so we can claim parity. | ZBrain JSON | 4 hrs | Mine (`pages/OpsDashboard.tsx` + `/api/analytics/ops_log`) |
| **16** | **Test-corpus regression page** — upload labelled emails, run all → see initial-pass / post-fix-pass / still-failing breakdown (matches their Accuracy Report) | Comparison Report xlsx | 3-4 hrs | Mine |
| **17** | **Eight typed attachment pipelines** (PDF / DOCX / XLSX / TIFF / Image / HTML / Text / Unknown) with explicit Exception DB for unhandled | ZBrain JSON | 4-5 hrs | Session A (`azure_doc_intelligence` tool) |
| **18** | **`.msg` attachment unrolling** — extract embedded Outlook items as sub-emails (unfailed-attachment list shows this is their #1 attachment failure mode) | Comparison Report xlsx | 2-3 hrs | Mine + Session A coordination |
| **19** | **Special subtype handlers** — Stock Rotation (quarterly partner, search PO#, match partner), Rebates (monthly, NEGATIVE order amount, Excel summary tab), eBiz (eBiz_CA_MB00053864 format), SOW (Z product, "Statement of Work", "EID #") | Sales PO PDF | 4 hrs | Session A |
| **20** | **Citizenship-based government routing** — non-US-citizen restrictions on KSO emails → forward to dedicated box (rule + UI) | RFP Q&A call | 2 hrs | Session A KB + Mine routing |
| **21** | **Translation KB ingestion** — accept an external Keysight translation KB file/feed and merge into `kb.translation` with override capability | RFP Q&A call | 3 hrs | Session A KB |
| **22** | **Burst load / queue layer** — queue emails on intake, process at controlled rate; show "100 emails/sec stress test" capability | RFP Q&A call | 4-5 hrs | Mine (queue) + Session A (consumer) |

### 🟨 P2 — polish or pure positioning

| # | Gap | Source | Effort | Lane |
|---|-----|--------|--------|------|
| **23** | "Valid Content" 8-category enumeration in KB | ZBrain JSON | 1 hr | Session A KB |
| **24** | KV-store RUN vs COLLECTION semantics + explicit cleanup steps in trace | ZBrain JSON | 1 hr | Shared |
| **25** | "Get Country List from KB" RAG step before Extract — retrieve country list and pipe into extract prompt | ZBrain JSON | 2 hrs | Session A |
| **26** | Markdown-formatted summary report per email (ZBrain step_2 "markdown response") attached to CommunicationLog | ZBrain JSON | 1 hr | Shared |
| **27** | CSR-employee roster + capacity-aware assignment (Routing Rules UI mapping intent+region → queue → CSR) | Data Request xlsx §4 | 4-6 hrs | Mine |
| **28** | Past-resolution RAG memory (top-3 similar past resolutions before agent decides) | Data Request xlsx §5 | 4 hrs | Session A |
| **29** | Priority hierarchy aware of business calendar (last-work-day-of-quarter bumps urgency) | Data Request xlsx §3.4 | 2 hrs | Session A |
| **30** | Microsoft Purview / Entra ID governance integration story (write the architecture slide; no code) | RFP Q&A call | 0 hrs (slide) | Solution doc |
| **31** | Oracle ERP integration story + middleware layer architecture (slide / mock connector with Oracle-specific labels) | RFP Q&A call | 1 hr | Solution doc + integration UI labels |
| **32** | Mailbox-consolidation transition story — agent transparency across N inboxes, single-inbox target | RFP Q&A call | 0 hrs (slide) | Solution doc |

### Recommended ordering for May-10 demo (~36 hours of effort)

If we have time only for the demo-critical work:

1. **#1 + #2** (taxonomy + structured KB) — biggest "we read your docs" signal; 6-8 hrs combined
2. **#3** (pre-AI rules layer) — matches their existing operational behavior; 4-5 hrs
3. **#9 + #10** (back-stamping + folder map) — visual evidence we understand their Outlook flow; 4-5 hrs
4. **#4** (4-gate confidence) — directly answers RFP confidence-scoring question; 3-4 hrs
5. **#15** (ops dashboard) — fast tier-2 with high impact; 4 hrs

Everything else is fast-follow if time permits.

---

## Specific user feedback captured

### 1. Intent KB structure (this session)

The intent KB **must** be structured per intent (keywords, examples, exceptions, exclusions, precedence) — not a one-line definition. The classify_intent prompt template should be **generated** from the structured KB at request time, not hard-coded.

→ Saved to user memory: `feedback_keysight_intent_kb_structured.md`.

### 2. Seed data convention (prior session)

Every seed must touch SF + SharePoint + URL stamping, not SQLite-only.

→ Memory: `feedback_keysight_seed_data_convention.md`.

### 3. Product naming (CLAUDE.md)

Never surface "Claude" anywhere user-visible. Use **ZBrain orchestrator** / **ZBrain document-intelligence agent** / **ZBrain vision OCR**. Internal Python imports referencing `claude_agent_sdk` are fine.

### 4. Don't add real connectors / mocks are deliberate (CLAUDE.md)

(But Salesforce/SharePoint/ServiceNow are already real — this rule is partially superseded by the real integrations we've added. Salesforce + SharePoint + ServiceNow are real; ERP and field-service remain mocked.)

### 5. Comments

Default to no comments. Only WHY when non-obvious. No "what" comments. Never multi-paragraph docstrings.

---

## Lane assignments (Session A vs Session B)

**Session A** owns:
- `backend/app/agents/**` (all agent + tool code)
- `backend/app/kb.py` and `backend/app/kb_seeds/**`
- `backend/app/services/tunnel.py`
- `backend/app/services/secrets.py` (Fernet)
- `backend/app/main.py` lifespan (reseed/tunnel hooks)
- `backend/app/routes/seed.py`
- `backend/app/routes/kb.py`
- `backend/app/routes/trace.py`
- `frontend/src/pages/Trace.tsx`
- `frontend/src/pages/KnowledgeBase.tsx`
- `SOLUTION.md`

**Session B** owns:
- `backend/app/services/email_sync.py`
- `backend/app/services/imap_client.py`
- `backend/app/services/email_outbound.py` (added this session)
- `backend/app/services/sharepoint.py` (added this session)
- `backend/app/routes/emails.py`
- `backend/app/routes/email_accounts.py`
- `backend/app/synthetic/catalog.py` and `generate.py`
- `frontend/src/pages/Inbox.tsx`
- `frontend/src/pages/settings/Connections.tsx`
- `frontend/src/pages/settings/Integrations.tsx` (SharePoint tile)

**Cross-cutting (coordinate via SESSION_HANDOFF.md):**
- `backend/app/models.py`
- `backend/app/db.py`, `db_migrate.py`
- `backend/app/main.py` (router registrations)
- `backend/app/config.py`
- `backend/app/routes/integrations.py` (Salesforce/ServiceNow/SharePoint share this)
- `backend/app/routes/hitl.py`
- `frontend/src/api.ts`

### Mapping the gap list to lanes

| Lane | Gap items |
|------|-----------|
| **Session A primary** | #1, #2, #3, #4, #5, #6, #7 (Decide branch), #8, #11, #12, #13, #14, #17, #19, #20, #21, #23, #25, #28, #29 |
| **Session B (mine) primary** | #9, #10, #15, #16, #18, #22 (queue), #27, #31 (UI labels) |
| **Cross-cutting** | #7 (model + Salesforce service mine, Decide branch Session A), #18 (extraction Session A, IMAP fetch mine), #24 (shared) |
| **Solution doc only** | #30, #32 |

### Suggested Session A handoff (post in SESSION_HANDOFF.md)

Send Session A this list to pick up while I tackle the Session B items:
- Adopt 9-class taxonomy + 25KB override prompt verbatim (#1)
- Restructure intent KB to schema-driven (#2)
- Pre-AI Outlook rules layer (#3)
- 4-gate confidence (#4)
- Two-stage classifier with shadow test slot (#5)
- Empty-fragment thread pre-processing (#6)
- Existing-CCC status branch in Decide (#7's Decide half)
- Disty list + magic-SKU routing in KB (#11)
- Region-aware rule packs (#12)
- CSR-instruction override detection (#13)

I will tackle in parallel:
- IMAP back-stamping + folder map (#9, #10)
- Telemetry ops dashboard (#15)
- Test-corpus regression page (#16)
- `.msg` attachment unrolling — IMAP side (#18 partial)
- Salesforce service additions for existing-CCC lookup (#7's Salesforce half)

---

## Open questions / pending decisions

1. **License/IP** — the override prompt is verbatim from a prior LeewayHertz-built Keysight POC. Confirmed this is reusable as-is in the new demo (same client, same use case). Any internal IP-handling rule to know?
2. **Outbound destinations on pre-AI rules** — should the demo *actually* send to `collections.pdl-americas@keysight.com` etc., or just *flag* "would forward to X"? (Recommendation: flag-only for demo to avoid fat-finger to a real Keysight DL.)
3. **Cloud target** — RFP/call mentioned Azure as the host. Solution doc + deploy artifacts (Dockerfile? Azure Container Apps? AKS? AS) — pick one.
4. **Test corpus seed source** — can we get the actual 109-email corpus from `FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx` synthesized into our `synthetic/generate.py`? Some are real customer emails, may have PII/IP issues.
5. **Multi-region rule pack scope for demo** — do all four regions need a working rule pack for the demo, or is "Americas only + show how to add others" sufficient?
6. **Confidence-gate UI placement** — should the 4 gates show in: (a) HITL queue card, (b) Trace per-stage, (c) both? Default plan: (b), show in Trace under Decide stage; render compact summary in HITL header.
7. **Mailbox consolidation phase** — for the demo, do we wire up multiple connected accounts (showing 2-3 IMAP-connected mailboxes) or stick with one (the orderinbox)? Multi-account adds 2-3 hrs but matches their stated reality.

---

## Quick-reference index

- **CLAUDE.md** — architecture, branding rules, dev commands
- **SESSION_HANDOFF.md** — active parallel-session lane coordination + crossover events log
- **SOLUTION.md** — architectural log + ADRs (Session A maintains)
- **RESEARCH_BRIEF.md** *(this file)* — RFP/POC research synthesis + comprehensive gap list

**Source artifacts:**
- `C:\Users\Rituraj\Downloads\keysight poc\` — prior-POC business docs + test corpus
- `C:\Users\Rituraj\Downloads\Agents\` — ZBrain workflow JSONs (both files identical except timestamps)
- RFP source: `C:\Users\Rituraj\Downloads\Keysight-RFP\SalesOps - RFP.xlsx`
- RFP text dumps: `C:\Users\Rituraj\rfp_sheets\`
