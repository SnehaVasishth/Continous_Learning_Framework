# Keysight SalesOps — RFP use-case inventory

Source: `SalesOps - RFP.xlsx` → "use case" sheet. Seven diagrams, each describing the **happy path** through the SalesOps automation for one inbound request type, with **fallout branches** that route to specific CSR queues.

Tracks (the swimlane in the top-right of each diagram):
- **FCNV Track** — Functional Classification & Verification queue (CSR review when classification confidence is low, parties missing, or AI couldn't complete enrichment).
- **AI OA Track** — AI Order Acceptance fallout queue (AIOA validation failed, CSR reviews inside AIOA).
- **Trade Track** — Trade orders / quotes / change orders.
- **SOM Track** — Service Order Management (work-order automation, status, updates).
- **S&A Track** — Service Contracts / Agreements quote or order.
- **Post Order Booking Track** — SSD changes, delivery changes, hold release.
- **CCC Sales Order Track** — Sales-order linkage for change orders.

Status / Stage canon (recurring across diagrams):
- `STATUS = New | Awaiting XXX | Assigned | Closed`
- `STAGE = Automation in Progress | Automation Complete | Review Required`
- Owner labels: AI agent / CSR / FCNV CSR / SOM CSR / AI OA CSR / Factory / Sales Order Owner.

---

## UC1 — Trade Order Entry (Happy Path for PO Received)

**Category:** Trade Order, PO Received
**Tracks:** FCNV → AI OA → Trade

### Happy path (linear)
1. **Email Received** — inbound mail lands in monitored mailbox.
2. **Email Classify** — intent = `po_intake`, category = Trade Order.
3. **Create CCC Request (shell)** — Salesforce Case created with `STATUS=New, STAGE=Automation in Progress`.
4. **CCC Request enrichment** *(AI / no parties)* — extract PO header, line items, ship-to, bill-to, payment terms.
5. **Human-in-Loop FCNV Review** *(optional)* — only if classification or enrichment confidence is low. ⚠ Fallout → **FCNV Scope** (`STATUS=Awaiting XXX, STAGE=Automation in Progress`; CSR completes enrichment manually).
6. **Assign CCC Request owner** — owner_label set (per routing rules).
7. **Human-in-Loop CSR Review** *(optional)* — pre-AIOA CSR check. ⚠ Fallout → **FCNV Scope**.
8. **AIOA AI PO Validation** — webhook handoff to external AIOA application.
9. **Human-in-Loop AI Fallout** — only on AIOA_FAIL. (`STATUS=Assigned, STAGE=Review Required`; CSR works the AI OA Fallout queue inside AIOA.)
10. **AI OA → resolved back to pipeline** *(AIOA_PASS)* — pipeline continues.
11. **Quote Update** — quote in Salesforce updated to match accepted PO.
12. **Quote Update (cont)** — extended fields, region overlay.
13. **Human-in-Loop Q2O Update Fallout** *(optional)*.
14. **Q2O Conversion** — quote promoted to Sales Order.
15. **Q2O Fallout / Oracle EBS SO entered** — booking writes to Oracle EBS (via Jitterbit; today: upcoming integration; demo: simulated).
16. **Human-in-Loop CSR to complete order through booking** *(optional)*.
17. **CCC Request updated to Booked** — `STATUS=Closed`, SOA generated, email queued.
18. **SOA GEN & Email SOA for CSR Review** — SOA PDF generated, attached to CCC Request and SharePoint (DocuNet via Jitterbit when enabled).
19. **Human-in-Loop CSR Review SOA Email & Publishes to Cust** — L3 one-click approval (or L4 sends).
20. **CCC Request Status Updated to Closed** — end.

### Fallouts
- FCNV Scope (step 5 or 7)
- AI OA Fallout (step 9)
- Q2O Update Fallout (step 13)
- CSR-complete-order Fallout (step 16)

---

## UC2 — Trade Sales Change Order, FCNV Happy Path For CCC Request Creation

**Category:** Change Order Request
**Tracks:** FCNV → CCC Sales Order

### Happy path
1. **Email Received** — Change Order Request.
2. **Email Classify** — intent = `trade_change_order`.
3. **Create CCC Request Change Order Rcvd** — `STATUS=New, STAGE=Automation in Progress`.
4. **CCC Request enrichment** — change request fields, references to existing order.
5. **Human-in-Loop FCNV Review** *(optional)* — ⚠ Fallout → **FCNV Scope**.
6. **Assign CCC Request owner**.
7. **CSR completes CCC Request entry, if needed** — manual.
8. **CSR updates CCC Request Status to In Progress**.
9. **CSR Provides Existing Order** — linkage to original SF Order.
10. **CSR Provides Update to Customer** — outbound reply.
11. **CSR Updates CCC Request Status to Closed** — end.

### Fallouts
- FCNV Scope (step 5)

---

## UC3 — SOM Work Order Automation (Single / Multiple Asset)

**Category:** Work Order, Create. PO without WO ⚠ uses **CMD Interface** for customer-master activation.
**Tracks:** FCNV → AI OA → Trade → SOM

### Happy path
1. **Email Received**.
2. **Email Classify** — intent = `service_order`.
3. **Create CCC Request (shell)**.
4. **CCC Request enrichment (incomplete)** — multi-asset / multi-WO need bulk handling.
5. **AI Agent Populate Info to Bulk WO Staging table** — when ≥1 asset and ≥1 WO target, populate staging table.
6. **Automation: Create WO and Assign Owner** — create one WO per asset, assign owner.
7. **SOM AI Agent Attach Email and attachments to WO** — file email + attachments against the new WO.
8. **AI Agent Close CCC Request (no reply)** — `STATUS=Closed`. *No customer reply on this path.*
9. **Human-in-Loop CSR Review of WO** — SOM CSR confirms the auto-created WO.
10. **End**.

### Fallouts
- **FCNV Scope** (minimum info to classify and move to CCC Request shell missing).
- **CCC Request Scope** — multiple assets in 1 email (in body or spreadsheet); same info and AI able to understand = 1 CCC Request → multiple WO create.
- **Fallout Potential** — system errored out → Assign CCC Request to SOM CSR.
- **CMD Interface** — PO received without an existing WO; need customer-master activation request via CMD.
- **Fallout Scope (SOM)** — different information not understood = 1 CCC Request assigned to SOM CSR. Email from WO back to Email for correct assignment (Marsutex).

---

## UC4 — SOM Work Order Update / Change Order / Multiple Assets

**Category:** Update Work Order. PO for existing WO.
**Tracks:** FCNV → AI OA → Trade → SOM

### Happy path
1. **Email Received**.
2. **Email Classify** — intent = `wo_update_request`.
3. **Create CCC Request (shell)**.
4. **CCC Request enrichment**.
5. **Update Existing WO** — Add Note / Add Task on existing WO.
6. **SOM AI Agent Attach Email and attachments to WO**.
7. **PO triggers AIOA Validation** — webhook to AIOA when PO present on the update.
8. **Close CCC Request (no reply)** — auto-close, no reply needed.
9. **Human-in-Loop CSR Review of WO and Reply** — optional CSR confirmation.
10. **End**.

### Fallouts
- **FCNV Scope** — minimum info to classify and move to CCC Request shell missing.
- **CCC Request Scope (SOM)** — multiple assets in 1 email or spreadsheet, AI cannot fully understand; fallout to CSR who completes WO update.
- **Fallout Scope (SOM)** — Marsutex pattern, email back to WO for correct assignment.

---

## UC5 — SOM Work Order Status / Inquiry

**Category:** WO Status, WO Inquiry
**Tracks:** FCNV → AI OA → Trade → SOM

### Happy path
1. **Email Received**.
2. **Email Classify / Reply** — intent = `wo_status_inquiry`.
3. **AI Reply with WO Customer-Friendly Status and KSP statement** — outbound reply uses translated status codes (in_progress → "field team has begun the calibration…", scheduled → "the work is on our schedule for X…", open → "logged and will be assigned within one business day per our standard SLA").
4. **End**.

### Fallouts
- **FCNV Scope** — minimum info to classify; move to CCC Request → FCNV.
- **CCC Request created and assign to CSR** — when status cannot be inferred.

---

## UC6 — Service Contracts (FCNV Happy Path for CCC Request Creation)

**Category:** Service Contracts/Agreements — Quote Request or Order Request.
**Tracks:** FCNV → AI OA → S&A

### Happy path
1. **Email Received**.
2. **Email Classify** — intent = `service_contract_request`. Request Type = Support Agreement (various subtypes); STATUS=New, STAGE=Automation in Progress.
3. **Create CCC Request (shell)**.
4. **CCC Request enrichment**.
5. **Human-in-Loop FCNV Review** *(optional)* — ⚠ Fallout → **FCNV Scope** (`STATUS=Awaiting XXX, STAGE=Review Required`).
6. **Assign CCC Request owner** — STATUS=New, STAGE=Automation in Progress.
7. **Human-in-Loop CSR Review** *(optional)* — ⚠ Fallout → **CTA Scope** (`STATUS=Assigned, STAGE=Review Required`).
8. **AIOA AI PO Validation** — webhook to AIOA. On Complete = PASS → STATUS=Assigned, STAGE=Automation Complete.
9. **Human-in-Loop AI Fallout** — Once Complete = Fail → STATUS=Assigned, STAGE=Review Required, AI OA Fallout (CSR Review).
10. **CCC Request Selected and begin process** — S&A specialist begins the contract workflow.
11. **End**.

### Fallouts
- FCNV Scope (step 5)
- CTA Scope (step 7) — Contract & Agreement specialist queue.
- AI OA Fallout (step 9)

---

## UC7 — SSD Change Request (FCNV Happy Path For CCC Request Creation)

**Category:** Trade Order Modification, Sub-type = SSD Change.
**Tracks:** FCNV → Post Order Booking

### Happy path
1. **Email Received**.
2. **Email Classify** — intent = `ssd_change_request`.
3. **Human-in-Loop FCNV Review** *(optional)* — ⚠ Fallout → **FCNV Scope** (automate miss; info assigned to CCC Request).
4. **Create & Assign CCC Request owner** — Request Type = Trade Order Modification, Sub-type = SSD Change. STATUS = Automation in Progress. Owner = Sales Order Owner or Direct Inquiries (in Oracle).
5. **Add SSD request to the CSR dashboard**.
6. **Notification to CSR & Factories**.
7. **Factory: prepares SSD & triggers CSR from dashboard** *(Human in loop)*.
8. **Factory: CSR interaction to finalize SSD from dashboard** *(Human in loop)*.
9. **Factory: triggers changes to Oracle, from dashboard**.
10. **CCC Request gets closed auto** — STATUS = Closed.
11. **Customer gets notified**.
12. **End**.

### Fallouts
- FCNV Scope (step 3)

---

## Summary table — paths to validate end-to-end

| # | Use case | Happy path | Named fallouts |
|---|---|---|---|
| UC1 | Trade Order Entry (PO Received) | 20 steps | FCNV Scope, AI OA Fallout, Q2O Update Fallout, CSR-complete-order |
| UC2 | Trade Sales Change Order, FCNV | 11 steps | FCNV Scope |
| UC3 | SOM WO Automation (single/multi asset) | 10 steps | FCNV Scope, CCC Request Scope, Fallout Potential, CMD Interface, Fallout Scope (SOM) |
| UC4 | SOM WO Update/Change Order/Multi-Asset | 10 steps | FCNV Scope, CCC Request Scope (SOM), Fallout Scope (SOM) |
| UC5 | SOM WO Status / Inquiry | 4 steps | FCNV Scope, CCC Request → assign CSR |
| UC6 | Service Contracts (FCNV) | 11 steps | FCNV Scope, CTA Scope, AI OA Fallout |
| UC7 | SSD Change Request (FCNV) | 12 steps | FCNV Scope |

**Total distinct paths to seed and validate:** 7 happy paths + 14 named fallouts = **21 paths**.
