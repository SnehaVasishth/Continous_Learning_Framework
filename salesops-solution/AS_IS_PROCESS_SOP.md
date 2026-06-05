# Keysight SalesOps Front-Office — AS-IS Process SOP

**Document type:** Standard Operating Procedure — current-state process description
**Audience:** Keysight VP / business stakeholders; LeewayHertz delivery team
**Version:** 2.0 (2026-05-11) — restructured around the eight RFP process diagrams; the "Agent #1.3 / #2 / #3" labels from the prior POC narratives have been replaced with the role the human operator performs today (FCNV operator, CSR, CTA, FE, Superuser) because, in current operations, every step is carried out manually.
**Scope:** Front-office Customer Notification & Validation (FCNV) intake — email-to-CCC-Request lifecycle across Trade Order Entry, Trade Sales Change Order, Service Order Management (Work Order Automation, Update / Change Order / Multiple Assets, and Status / Inquiry), Service Contracts, and SSD Change Requests, plus the adjacent triage classes (KSO, Brazil Tax, Collections, Portal Admin, Auto-Reply, Undeliverable, Others). Excludes downstream order fulfilment, calibration laboratory operations, and the classified / government-controlled environment.
**Source attribution:** This SOP consolidates the verbatim business-rule narratives published by Keysight in the proof-of-concept (POC) phase, the eight process diagrams embedded in the RFP workbook (`SalesOps - RFP.xlsx`, AI.SalesOps Details sheet), and the recorded Q&A session of 2026-05-08. Every process step is traceable to an original Keysight artefact; citations appear inline.

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Glossary](#2-glossary)
3. [Operational ownership tracks](#3-operational-ownership-tracks)
4. [Roles & RACI](#4-roles--raci)
5. [Inputs — what arrives at the front office](#5-inputs--what-arrives-at-the-front-office)
6. [The 9-class taxonomy](#6-the-9-class-taxonomy)
7. [Email classification — the manual triage step](#7-email-classification--the-manual-triage-step)
8. [Use case 1 — Trade Order Entry — PO Received](#8-use-case-1--trade-order-entry--po-received)
9. [Use case 2 — Trade Sales Change Order — CCC Request creation](#9-use-case-2--trade-sales-change-order--ccc-request-creation)
10. [Use case 3 — Service Order Management — Work Order Automation (single / multiple asset)](#10-use-case-3--service-order-management--work-order-automation-single--multiple-asset)
11. [Use case 4 — Service Order Management — WO Update / Change Order / Multiple Assets](#11-use-case-4--service-order-management--wo-update--change-order--multiple-assets)
12. [Use case 5 — Service Order Management — WO Status / Inquiry](#12-use-case-5--service-order-management--wo-status--inquiry)
13. [Use case 6 — Service Contracts — CCC Request creation](#13-use-case-6--service-contracts--ccc-request-creation)
14. [Use case 7 — SSD Change Request](#14-use-case-7--ssd-change-request)
15. [Special subtypes](#15-special-subtypes)
16. [Existing-CCC status branching matrix](#16-existing-ccc-status-branching-matrix)
17. [Distributor partner lists](#17-distributor-partner-lists)
18. [Magic SKUs](#18-magic-skus)
19. [Routing matrix](#19-routing-matrix)
20. [Operational decision rule book](#20-operational-decision-rule-book)
21. [Confidence and accuracy expectations](#21-confidence-and-accuracy-expectations)
22. [Manual baseline today](#22-manual-baseline-today)
23. [System integrations](#23-system-integrations)
24. [Out of scope today](#24-out-of-scope-today)
25. [Pain points and gaps](#25-pain-points-and-gaps)
26. [Volume and SLA expectations](#26-volume-and-sla-expectations)
27. [Appendix A — Document provenance](#appendix-a--document-provenance)
28. [Appendix B — The RFP's envisioned six-stage future flow (TO-BE / RFP vision)](#appendix-b--the-rfps-envisioned-six-stage-future-flow-to-be--rfp-vision)

---

## 1. Executive summary

### 1.1 Purpose of the front-office function

Keysight Technologies operates a global Front-office Customer Notification & Validation (FCNV) team that converts inbound customer correspondence into structured records inside Salesforce **and back into outbound communications to the customer**. The output of this function is twofold:

1. **A fully populated CCC Request** inside Salesforce — the system-of-record that downstream Customer Service Representatives (CSRs), Customer Technical Assistants (CTAs), Field Engineers (FEs), and Export / SOW specialists rely upon to fulfil orders, repairs, and service entitlements.
2. **Customer-facing communication** — Sales Order Acknowledgements (SOAs), Work Order acknowledgements, status replies, hold-resolution notifications, delivery / SSD-change confirmations, and ad-hoc clarification replies. Today this outbound communication is **drafted and sent manually** by CSRs / CTAs using templates and (where needed) the customer's language. The RFP explicitly names *"Customer Communications (order acknowledgments, status updates, payment reminders)"* (RFP `AI.SalesOps Details` sheet, Current State bullet 5) as one of the five capability areas in scope, and the seven RFP use-case diagrams (§§8–14) all end at a customer-facing reply or notification step.

The FCNV team does not sell, quote, or fulfil. Its scope is: **read → triage → validate → enrich → route → respond.** Its single business outcome is: **every actionable inbound email is converted into the correct CCC Request, attached to the correct Salesforce Account / Contact, routed to the correct downstream owner, and acknowledged back to the customer in the customer's language within target turnaround.**

### 1.2 Scale

| Dimension | Current value | Source |
|---|---|---|
| Inbound email volume | **≈530,000 emails / year** | RFP §AI.SalesOps Details; confirmed verbally by Keysight in Q&A 2026-05-08 |
| Wider user pool with system access | **600–700 users globally** | Q&A transcript 2026-05-08 §9.8 |
| Peak concurrent users | **80–90 across global time zones** | Q&A transcript 2026-05-08 §9.8 |
| Burst pattern | Quarter-end, month-end, year-end status-check waves | Q&A transcript 2026-05-08 §9.8 |
| Stress-test design target | **100 emails / second** sustained processing capacity | Q&A transcript 2026-05-08 §9.8 |
| Active intake mailboxes | **≈50 region-segregated mailboxes**, target consolidation to **1–2 mailboxes** | Q&A transcript 2026-05-08 §9.3 |
| Languages encountered | EN, ES, FR (incl. Canadian French), PT-BR, KO, zh-Hans, zh-Hant, VI, NL, SV, DA, FI, DE, IT, CS, JA — internal systems are not standardised to English | RFP AI.SalesOps Details §2.9; Q&A §9.5 |

### 1.3 Geographic lanes

The front office operates **four primary lanes**: Americas (AMS), Europe (EMEA), Asia-Pacific (APAC) and Japan (JP). Within APAC, country-specific nuances apply — Japan in particular requires additional fields on every transaction (Q&A transcript 2026-05-08 §9.2). Keysight is moving toward a globally standardised process, but region-specific exceptions remain in force and are documented per lane.

### 1.4 System landscape relied upon today

| System | Role in the AS-IS process |
|---|---|
| Microsoft Outlook (Exchange Online) | Inbound channel; ≈50 mailboxes; per-region Outlook rule packs perform the only fully deterministic automation in the current process |
| Salesforce (single global instance) | System-of-record for Account, Contact, Quote, Opportunity, CCC Request, Order, Activity, Files, Chatter |
| Oracle ERP (single global instance) | Downstream order, hold, schedule, invoice records — accessed via internal middleware |
| ServiceNow | Reminder / follow-up workflow approval engine (Change Order approvals, escalation chains); not used for classification |
| Internal document store (SharePoint / Docunet) | Customer specifications, calibration history, retained PO copies |
| Keysight Support Portal | Read-only customer self-service portal — referenced by Portal-Admin emails (verification codes, password resets) |
| **AIOA — in-house "AI Order Automation" tool** | A Keysight-internal AI utility deployed today on the Trade Order Entry, SOM WO Update, and Service Contracts flows. Performs partial PO-data validation and feeds an "AI OA Fallout" queue for human review of flagged items. Depicted as the dedicated **AI OA Track** swim lane on the RFP use-case diagrams (`trade-po-received.png`, `som-wo-update.png`, `service-contracts.png`). AIOA is **not a full agent** — it does not classify, does not extract, does not write to Salesforce on its own, and does not draft customer-facing communication. It is a check-and-flag aid that runs alongside the human operator. |

### 1.5 Customer communication (outbound) — also in scope

Customer-facing communication is not an afterthought to the CCC creation — it is one of the five capability areas the RFP explicitly names (RFP `AI.SalesOps Details` sheet, Current State bullets 5; Core Functional Requirements → Customer Communication). Today every one of the outbound touch-points below is **drafted and sent manually** by a CSR / CTA after the FCNV operator hands off the CCC Request:

| Communication | When it is sent | Who drafts it today | Where it appears in the use cases |
|---|---|---|---|
| **Sales Order Acknowledgement (SOA)** | After Q2O conversion and Oracle EBS SO entry; attached to the CCC Request (Doc type = `FCNV`) and emailed to the customer | Trade-pool CSR via template + manual edit | Use Case 1 (Trade Order Entry — PO Received), §8 |
| **Change Order confirmation / update** | After CSR updates the existing order against the revised PO | CCC Sales Order CSR | Use Case 2 (Trade Sales Change Order), §9 |
| **Work Order acknowledgement** | After WO is created and assigned (single / multi-asset) | SOM CSR | Use Cases 3 & 4 (SOM Automation; SOM Update), §§10–11 |
| **WO status / inquiry reply** | In response to a status request, optionally with a Keysight Support Portal pointer | FCNV operator | Use Case 5 (WO Status / Inquiry), §12 |
| **Service Contract quote / order acknowledgement** | After S+R CSR processes the contract request | S+R CSR | Use Case 6 (Service Contracts), §13 |
| **SSD change confirmation** | After the factory and Oracle confirm the new ship date; "customer gets notified" closes the loop | Post-Order-Booking CSR | Use Case 7 (SSD Change Request), §14 |
| **Customer-language reply** | All of the above, drafted in the customer's preferred language using Keysight's translation knowledge base | The CSR or, where the CSR lacks the language, an ad-hoc internal lookup | All use cases |

> The RFP requires communications to be "auto-generated [...] using templates with dynamic content", "in the customer's detected language", with SOAs and other documents "generate[d] and attach[ed]" automatically, and all communications "auditable and linked to the originating request" (RFP `AI.SalesOps Details` sheet, Core Functional Requirements → Customer Communication). **None of those four capabilities exists today** — drafts are hand-built, language detection is manual, and attachment of generated documents to Salesforce is a manual upload via the Files quick link.

### 1.6 Business value at stake

Every minute spent by an FCNV operator on classification, parsing, or Salesforce data entry — **and every minute a CSR spends drafting a templated reply by hand** — is a minute not spent on actual customer outcomes. The RFP states the strategic target explicitly:

> "Reduce manual CSR processing effort by 60–70% while improving response times from hours to minutes." (RFP — `AI.SalesOps Details` sheet, Executive Summary)

Today the entire front-office classification, validation, CCC-creation, **and outbound-communication** flow is **manual** apart from (a) the per-region Outlook rule pack (six deterministic rules — §7.1) and (b) the in-house **AIOA** tool, which performs partial PO-data validation on the Trade Order Entry, SOM WO Update, and Service Contracts flows and surfaces flagged items for human review (the "AI OA Fallout" loop). AIOA is a check-and-flag aid, not a full agent — it does not classify, extract, write to Salesforce, or compose customer-facing replies. The remaining sections of this SOP document that current state in full.

---

## 2. Glossary

| Term | Definition |
|---|---|
| **AI OA / AIOA** | "AI Order Automation" — an **in-house Keysight tool** in production today. Performs partial PO-data validation on the Trade Order Entry, SOM WO Update, and Service Contracts flows (the diagrams that explicitly name "AIOA AI PO Validation" / "PO triggers AIOA Validation" boxes). AIOA is **not a full agent**: it does not classify, does not extract from attachments, does not write to Salesforce on its own, and does not draft customer-facing replies. Items it flags as inconsistent are routed to the **AI OA Fallout** queue for human (CSR) review. Boxes labelled "AI Agent" or "AI Reply" on other RFP diagrams (e.g., the SOM WO Automation flow, the WO Status / Inquiry flow) describe forward-looking augmentation beyond AIOA's current scope. |
| **AMFO** | Americas Front Office — operational queue / team identifier |
| **AMS / EMEA / APAC / JP** | Regional lanes: Americas, Europe-Middle-East-Africa, Asia-Pacific (excluding Japan), Japan |
| **CCC Request** | Customer Care Center Request — Salesforce custom object; the canonical record of an inbound customer request. Every actionable email becomes one or more CCC Requests. |
| **CCC Sales Order Track** | Swim lane representing the CSR / Sales Order ownership pool — the people who pick up a CCC after FCNV completes intake and drive it to booking / SOA. Depicted in the Trade Sales Change Order diagram. |
| **CIA** | Customer-in-Action (status sub-code on a CCC Request awaiting customer input) |
| **CMD Interface** | Centralised Master Data interface flag on the SOM diagrams — indicates the WO automation reaches across to the master-data system for account / asset confirmation. |
| **CSR** | Customer Service Representative — downstream owner of a CCC Request after FCNV completes intake |
| **CTA** | Customer Technical Assistant — technical-track equivalent of a CSR; handles service-order specifics |
| **Docunet** | Internal Keysight document classification and retention store — the "Files" quick link on a CCC Request uploads here with a `Doc type = FCNV` tag |
| **eBiz** | Keysight Used Equipment Store channel — orders coming from the `ebiz@keysight.com` node with PO numbers in `eBiz_CA_*` format |
| **EID #** | Engagement / Engineering ID — appears on Statement-of-Work (SOW) Purchase Orders |
| **FCNV Track** | Swim lane representing the Front-office Customer Notification & Validation team — the human operators who read the inbox, classify, and create / enrich CCC Requests today. The primary owning track on every RFP diagram. |
| **FE** | Field Engineer — Keysight-side technical owner of repair / calibration work orders |
| **FCNV** | Front-office Customer Notification & Validation — the role and the team that operates the intake process described by this SOP |
| **HITL** | Human-in-the-Loop — a review / approval intervention by a person before downstream automation continues |
| **ISC** | Internal Service Center — the operational owner of WO/RTK work; "ISC folder" is the Outlook folder the Sales-PO-vs-WO triage routes service work to |
| **KSO** | Keysight Special Orders — restricted / government / federal customer routing; emails forwarded to `keysightorders@keysight.com` |
| **KSP** | Keysight Support Portal — read-only customer self-service portal; referenced by the WO Status / Inquiry happy-path reply template. |
| **LAR** | Latin America Region — distributor partner list maintained separately from US/Canada |
| **PDL** | Public Distribution List — Keysight email-group convention (e.g., `collections.pdl-americas@keysight.com`) |
| **PO** | Purchase Order |
| **Post Order Booking Track** | Swim lane on the SSD Change Request diagram representing post-booking modifications handled in Oracle and on the factory dashboard. |
| **Q2O** | Quote-to-Order conversion |
| **RTK** | Return To Keysight — service work-order lifecycle for instruments returned for repair or recalibration |
| **S+R Track** | Swim lane on the Service Contracts diagram representing the Service & Repair / Support agreements operational pool. |
| **SOA** | Sales Order Acknowledgement — outbound communication confirming receipt and booking of a customer PO |
| **SOM Track** | Swim lane representing Service Order Management — the operational pool that owns service work-orders (single asset, multiple asset, update, status). Depicted on the three SOM diagrams. |
| **SOW** | Statement of Work — engagement contract distinguishing custom-solution work from standard product orders; PO contains `Z*` SKUs, an EID #, and a cover letter |
| **SSD** | Specified Ship Date / Schedule Ship Date — the customer-requested ship date on a PO line; SSD Change Requests are post-booking modifications |
| **Superuser** | Senior FCNV operator authorised to handle exception cases and unassignable CCC Requests |
| **Trade Track** | Swim lane on the trade-order diagrams representing the commercial Trade order pool — the destination once a Trade Order Entry CCC is assigned and progresses to booking. |
| **WO** | Work Order — Salesforce object representing a service / repair / calibration task |

---

## 3. Operational ownership tracks

The RFP's eight happy-path diagrams (see §§8–14, and Appendix B for the future-state six-stage diagram) describe the current front-office process as a set of **swim lanes** — operational ownership tracks across which a single inbound email progresses. The same human teams appear on multiple diagrams; the lane changes depending on the type of work the email represents.

This section names each track, identifies who owns it today, and describes where it picks up work and where it hands off. None of these tracks are automated end-to-end today; the dominant reality is that a human operator carries the email across every track shown.

### 3.1 FCNV Track

**Owner today:** the FCNV operator team (≈50 mailbox-segregated regional teams).
**What it processes:** every inbound email, in every category. The FCNV Track is the entry point on all eight diagrams.
**Pick-up:** the email lands in one of the ≈50 intake mailboxes. After the six deterministic Outlook rules fire (§7.1), the residual emails are read by a human FCNV operator who manually classifies them into the 9-class taxonomy (§6) and performs the relevant data extraction.
**Hand-off:** the operator either redirects the email to a peer mailbox (KSO, Collections, Portal Admin, Brazil Tax) or creates / updates a CCC Request in Salesforce and assigns it to the appropriate downstream queue.
**Diagram references:** all eight diagrams show the FCNV Track as the originating swim lane.

### 3.2 AI OA Track

**Owner today:** the in-house **AIOA** ("AI Order Automation") tool — a Keysight-internal AI utility, not a full agent.
**What it processes:** PO data already extracted onto a CCC Request. AIOA performs partial validation — PO# format, dollar amount sanity, customer-account match, ship-to country, and similar header checks — and flags inconsistencies, missing fields, or mismatched values for human review. It does **not** classify, extract from attachments, route, or write to Salesforce on its own.
**Pick-up:** after the FCNV operator has populated a CCC Request with PO data on the **Trade Order Entry**, **SOM WO Update**, and **Service Contracts** flows (the diagrams that explicitly name AIOA validation steps).
**Hand-off:** AIOA returns a pass / flag result. On pass, the CCC moves forward (in the Service Contracts flow, to `STATUS = Assigned, STAGE = Automation Complete`). On flag, the CCC enters the **"AI OA Fallout"** queue and is sent back to the FCNV operator or a designated Trade-pool / S+R CSR for manual review and correction.
**Diagram references:** the AI OA Track appears alongside the FCNV Track on the Trade Order Entry (`trade-po-received.png`), SOM WO Automation, SOM WO Update (`som-wo-update.png`), WO Status / Inquiry, and Service Contracts (`service-contracts.png`) diagrams. The boxes that explicitly call AIOA by name are on Trade Order Entry, SOM WO Update, and Service Contracts. The "AI Agent" / "AI Reply" labels on the SOM WO Automation and WO Status / Inquiry diagrams describe forward-looking augmentation beyond AIOA's current scope.

### 3.3 CCC Sales Order Track

**Owner today:** the CSR / Sales Order owner pool that picks up assigned CCC Requests.
**What it processes:** Trade Sales Change Orders, post-FCNV-handover work on Trade Order Entry, and CCC Request status maintenance for active orders.
**Pick-up:** when FCNV assigns the CCC Request to the appropriate downstream queue and the queue's CSR claims the record.
**Hand-off:** the CSR updates the CCC Request status (In Progress → Continue Processing → Closed), updates the existing order in Oracle, and provides the customer-facing update.
**Diagram references:** the Trade Sales Change Order diagram shows the CCC Sales Order Track explicitly; the Trade Order Entry diagram shows the same role under "Human in Loop CSR Review" steps.

### 3.4 SOM Track

**Owner today:** the Service Order Management operational pool.
**What it processes:** all service work-orders — single-asset RTK, multi-asset RTK, WO update / change orders, WO status / inquiry replies.
**Pick-up:** after FCNV creates / enriches the CCC Request and the CMD interface confirms account / asset information. On the diagrams, the SOM Track picks up at "AI Agent Populate CCC Request Owner Incomplete → Automation Create WO and Assign Owner" — but this step is partially manual today; an SOM team member manually creates the WO once the CCC Request is populated.
**Hand-off:** the SOM CSR completes the WO, attaches the email and any attachments to the WO, replies to the customer if needed, and closes the CCC Request.
**Diagram references:** SOM Track appears on the three SOM diagrams (WO Automation, WO Update, WO Status / Inquiry).

### 3.5 Trade Track

**Owner today:** the commercial Trade operational pool that owns booking and SOA generation.
**What it processes:** Trade Order Entry happy-path bookings — Q2O conversion, Oracle EBS sales-order entry, SOA generation, customer SOA delivery.
**Pick-up:** once the FCNV-created CCC Request has cleared **AIOA PO Validation** (pass or post-fallout) and the quote update is complete, the Trade Track CSR drives the Q2O conversion and Oracle EBS SO entry.
**Hand-off:** SOA is generated and emailed to the customer; the CCC Request is marked Closed.
**Diagram references:** the Trade Track is shown explicitly on the Trade Order Entry diagram (right-most lanes from the PO-validation block through "CCC Request Status Updated to Closed").

### 3.6 S+R Track

**Owner today:** the Support / Service + Repair operational pool that owns service-contract intake.
**What it processes:** Service Contracts — Support Agreement Quotes and Order Requests (Agreements).
**Pick-up:** after FCNV creates the CCC Request shell and AIOA performs the partial PO-data validation on attached PO information. An AIOA pass moves the CCC to `STATUS = Assigned, STAGE = Automation Complete`; an AIOA flag puts the CCC into the AI OA Fallout queue for S+R CSR review.
**Hand-off:** an S+R CSR / CTA selects the CCC Request from the queue and begins the contract-fulfilment process.
**Diagram references:** the Service Contracts diagram names this track "S+R".

### 3.7 Post Order Booking Track

**Owner today:** the post-booking modification pool that handles in-flight changes to already-booked orders (SSD Change, address change, ship-date change, line cancellation).
**What it processes:** SSD Change Requests and other Trade Order Modification subtypes that require coordination with the factory and Oracle.
**Pick-up:** after FCNV creates / assigns the CCC Request with `Request Type = Trade Order Modification`, `Sub-type = SSD Change`, `Owner = Sales Order Owner or Direct Inquiries (in Oracle)`.
**Hand-off:** the dashboard-driven loop — Factory prepares SSD → triggers CSR → CCC interaction finalises SSD → Insert triggers Oracle changes → CCC Request closes → customer notified.
**Diagram references:** the SSD Change Request diagram names this track "Post Order Booking".

### 3.8 How the tracks interact

In the current AS-IS state, a single inbound email enters the FCNV Track and is then moved across one or more of the other tracks **by the human operators on each track**, with one exception: the **AIOA** tool running on the AI OA Track performs partial PO validation today on the Trade Order Entry, SOM WO Update, and Service Contracts flows, surfacing flagged items for human review. Beyond that one tool, there is no automated baton-passing between lanes. Other diagram labels — "AI Agent" on the SOM WO Automation flow, "AI Reply" on the WO Status / Inquiry flow — describe forward-looking augmentation that does not yet exist in production. Each diagram in §§8–14 explicitly calls out where AIOA is active today versus where the diagram is depicting future-state intent.

---

## 4. Roles & RACI

The AS-IS front-office process involves five role types — two internal to FCNV and three upstream or downstream. The previous POC narratives referred to "Agent #1.3", "Agent #2", and "Agent #3" as the actors carrying out the work. Those labels described future-state design intent. In today's operations, **the FCNV operator is the agent** — a human performs every step.

### 4.1 Role definitions

| Role | Description |
|---|---|
| **Customer** | External party — direct end-customer, distributor, or partner — that sends an inbound email. May also be an internal Keysight forwarder (FE, CSR) acting on a customer's behalf. |
| **FCNV operator** | The front-office human operator who reads each email, decides its class, opens or updates the CCC Request in Salesforce, attaches the email, and assigns ownership. Primary actor for every step described in §§7–14. In the prior POC narratives this role was referred to as "Agent #1.3" (classification), "Agent #2" (CCC creation), and "Agent #3" (assignment) — all three are the same human role today. |
| **CSR / CTA** | Customer Service Representative / Customer Technical Assistant — downstream owner of the CCC Request once FCNV assigns it. Performs the actual order-booking, status communications, hold management, and customer reply. |
| **FE** | Field Engineer — Keysight technical staff who own the calibration / repair side of a WO. May insert routing instructions inside an inbound email that supersede automatic system routing. |
| **Superuser** | Senior FCNV operator who handles exceptions: failed auto-assignments, ambiguous routing, missing Salesforce accounts, escalations. Referenced in `ISC WO RTK.txt`, CCC Request Assignment narrative, step 3 ("If the CCC request is not assigned, refer to Superuser for exception handling"). |

### 4.2 RACI matrix

Legend: R = Responsible (does the work) · A = Accountable (signs off) · C = Consulted · I = Informed

| Activity | FCNV operator | CSR / CTA | FE | Customer | Superuser |
|---|---|---|---|---|---|
| Read inbound email | R / A | I | I | — | I |
| Classify into 9-class taxonomy | R / A | — | — | — | C |
| Apply Outlook pre-AI rules | R / A | — | — | — | — |
| Extract PO / WO / model / serial / addresses | R / A | I | I | — | C |
| Find / create Salesforce Account & Contact | R / A | C | — | — | C |
| Create or update CCC Request | R / A | C | I | — | C |
| Attach email file to CCC (Docunet, Doc type = FCNV) | R / A | I | — | — | — |
| Assign CCC Request to a CSR / CTA queue | R / A | I | — | — | C |
| Notify CCC owner via Salesforce Chatter | R / A | I | — | — | — |
| Action the CCC (book order, manage holds, reply to customer) | I | R / A | C | C | C |
| Apply FE / CSR routing override in email | C | C | R / A | — | — |
| Exception routing for unassignable CCC | R | C | — | — | A |
| Archive original email in Outlook with CCC# in subject | R / A | — | — | — | — |
| AIOA partial PO validation (Trade Order Entry, SOM WO Update, Service Contracts) | C (reviews flagged items in the AI OA Fallout queue) | I | — | — | — |
| End-customer reply / SOA delivery | I | R / A | C | I | — |

---

## 5. Inputs — what arrives at the front office

### 5.1 Inbound envelope

Every transaction begins as an inbound Outlook email. Source: *ISC WO RTK.txt, ISC WO Sorting Data Input*; *Sales PO Std Process & Change order PDF, p.1, Data Input bullet list*. The published Keysight specification states:

> "Outlook email · Inbound emails from any sender with a specific subject line or key words in the body of the email · Inbound emails with PDF attachments · Inbound emails with multiple PDF attachments · Inbound emails with multiple attachments." (Sales PO PDF, p.1)

### 5.2 Mailboxes

There are **≈50 active intake mailboxes** segregated by region and function (Q&A transcript 2026-05-08 §9.3). Distinct mailboxes referenced across the published narratives include:

- `keysight.ai-front-office@keysight.com` — primary FCNV intake mailbox referenced in the operational decision rule book (Internal-Keysight-to-Keysight exception).
- `orderinbox@*` regional variants — primary intake per region.
- `keysightorders@keysight.com` — restricted-customer destination for KSO redirects (Outlook Rules PDF, KSO rule).
- `collections.pdl-americas@keysight.com` — collections team destination.
- `usar_keysight@keysight.com` — Americas accounts-receivable Cc destination on collections redirect.
- `portal-admin.pdl-ccc-americas@keysight.com` — portal-administration team destination.
- `lar_orders@keysight.com` — Latin America destination for Brazil-tax redirect.
- `estore_orders@keysight.com` — parts-order channel (Sales PO PDF p.9 "Standard PO exceptions without Subtype").
- `ebiz@keysight.com` — Keysight Used Equipment Store channel.
- `partner_assistance@keysight.com` — typical sender node for Stock-Rotation and Rebate requests.
- `keysight.bra-tax@tmf-group.com` — external Brazil-tax filing sender that triggers the Brazil-tax redirect.
- `noreply@keysight.com` — system-generated bounces (Undeliverable rule).

The target end-state is consolidation to **1–2 mailboxes** (Q&A transcript 2026-05-08 §9.3) but full consolidation is **not expected within the current project horizon** — partial consolidation is the realistic outcome. The downstream classification and routing logic must remain mailbox-agnostic so consolidation can proceed without rework.

### 5.3 Attachment types

The Keysight specification enumerates the attachment surfaces FCNV must handle today (Sales PO PDF, p.1; ISC WO RTK.txt, Data Input):

| Attachment type | Handling today |
|---|---|
| PDF | Open in Outlook preview / Adobe; manually transcribe PO #, model, serial, addresses, dollar amount, ship-to. |
| DOCX | Open in Word; manually transcribe relevant fields. |
| XLSX | Open in Excel; for Rebates the Summary / Trade-Credit-RMU tab is the source of truth (Sales PO PDF p.12). |
| TIFF / image | Visual inspection — FCNV operator reads the scanned PO. |
| Image (PNG/JPG) | Same as TIFF. |
| HTML | Strip markup mentally; treat as body. |
| Plain text | Read directly. |
| Outlook `.msg` (embedded) | **Failure mode today** — forwarded chains attached as `.msg` files are the leading cause of mis-classification in the POC test corpus (see §21.3). The operator must open the `.msg` separately to see the inner email content. |
| `.gif` / animated images | **Failure mode today** — frequently flagged as "non-supported" in the POC accuracy report. |

### 5.4 Customer documents and reference data

Beyond the email and attachments, the FCNV operator consults:

- Internal document store (SharePoint / Docunet) for customer specifications, prior calibration certificates, and retained POs (Q&A transcript 2026-05-08 §9.11).
- The Keysight Support Portal — read-only — for account and order lookups.
- Distributor partner lists (US / Canada and LAR — see §17) maintained as static reference data.
- The Keysight translation knowledge base — an existing internal asset that the FCNV operator (or an upstream translator) uses when the inbound email is not in English (Q&A transcript 2026-05-08 §9.5). Internal systems are not standardised to English; the translation knowledge base is reused rather than created anew for any SalesOps automation.

---

## 6. Front-office triage taxonomy — and how it relates to the RFP scope

### 6.0 Why this section exists

Two different category systems coexist in this domain and the difference matters:

1. **The RFP scope categories — the seven actionable processes.** The Keysight RFP (`SalesOps - RFP.xlsx`, AI.SalesOps Details sheet + use case sheet) names exactly seven inbound-request flows the vendor's solution must handle end-to-end: **Trade Order Entry (PO Received)**, **Trade Sales Change Order**, **Service Order Management — Work Order Automation (single / multiple asset)**, **Service Order Management — WO Update / Change Order / Multiple Assets**, **Service Order Management — WO Status / Inquiry**, **Service Contracts (CCC Request Creation)**, and **SSD Change Request**. Each has its own diagram and its own dedicated section in this SOP (Use Cases 1–7, §§8–14). **These seven are the canonical in-scope work.** The RFP further enumerates the operational tasks the future solution must perform — "PO intake and validation · Quote-to-Order (Q2O) conversion · Post-order booking management · Work order creation and management · Customer communications" (RFP `AI.SalesOps Details` sheet, Business Context · Current State).

2. **The POC's nine-class triage taxonomy — the front-office mailbox sorter.** Below the RFP scope sits a more granular operational triage that FCNV uses **today** to pre-filter the mailbox. This is the taxonomy from the prior POC's classifier (`Agents/KS FO Agent.json` step "Checking the Context" system prompt) and the 109-email test corpus. It exists because the inbound mailbox receives many emails that are **not** in the RFP scope — bounces, out-of-office replies, government / restricted-customer redirects, tax-document filings, portal verification codes, collection notices, and ad-hoc inquiries. The triage's job is to separate the actionable mail (which then flows into the seven RFP use cases) from everything else (which is redirected, archived, or handled ad hoc).

In other words: **the RFP scope is the work that gets done; the nine-class triage is the upstream filter that decides whether work needs to get done at all.** Five of the nine triage classes (Undeliverable, Auto-Reply, Brazil Tax, Portal Admin, Collections) are redirected or discarded by deterministic Outlook rules **before** the FCNV operator even reads the email — none of them produce a CCC Request and none of them are in RFP scope. KSO is also redirected (compliance). Only three triage classes feed the in-scope use cases: **SALES_PO** (→ Use Cases 1, 2, 6, 7), **ISC_WO_RTK** (→ Use Cases 3, 4, 5), and the actionable subset of **OTHERS** (→ Use Case 7, SSD Change; and Use Case 5, WO Status / Inquiry).

### 6.1 The seven RFP-scoped use cases (in-scope)

| # | Use case (from RFP diagrams) | Source category in the POC triage | SOP section |
|---|---|---|---|
| 1 | **Trade Order Entry — PO Received** | SALES_PO | §8 |
| 2 | **Trade Sales Change Order — CCC Request Creation** | SALES_PO (Change Order subtype) | §9 |
| 3 | **Service Order Management — WO Automation (single / multiple asset)** | ISC_WO_RTK | §10 |
| 4 | **Service Order Management — WO Update / Change Order / Multiple Assets** | ISC_WO_RTK | §11 |
| 5 | **Service Order Management — WO Status / Inquiry** | ISC_WO_RTK | §12 |
| 6 | **Service Contracts — CCC Request Creation** | SALES_PO (Service Contract / Agreement subtype) — handed off to the S+R track | §13 |
| 7 | **SSD Change Request** | OTHERS — Trade Order Modification subtype, handled by the Post-Order-Booking track | §14 |

The RFP's "AI-Powered Operations Automation Platform for Sales Operations" goal text (`AI.SalesOps Details` sheet, Executive Summary) groups these seven into five core capability areas: **PO Validation & Processing**, **Quote-to-Order Conversion**, **Post-Booking Management**, **Service Order Management**, and **Delivery & Schedule Management** — every one of the seven diagrams maps to one of those capability areas. The structure of this SOP follows the diagram-level granularity (seven use cases) because that is the level at which today's FCNV operator steps differ.

### 6.2 The POC's nine triage classes (the mailbox-sorting layer)

Every inbound email is sorted into exactly one of nine business classes during front-office triage. Source: `Agents/KS FO Agent.json` step "Checking the Context" system prompt; cross-validated against `FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx` expected-tag column.

| # | Class | Plain-English definition | Primary downstream destination |
|---|---|---|---|
| 1 | **UNDELIVERABLE** | System-generated bounce / mail-delivery-failure notice from `noreply@keysight.com`, `mailer-daemon`, or with specific subject patterns. | Move original to "Undeliverable" Outlook folder. No CCC. |
| 2 | **AUTO_REPLY** | Out-of-Office / Automatic-Reply messages without actionable business content. | Move original to "Out of Office" folder. No CCC. |
| 3 | **BRAZIL_TAX** | Brazilian fiscal-document filings from `keysight.bra-tax@tmf-group.com`. | Redirect to `lar_orders@keysight.com`; archive original. |
| 4 | **PORTAL_ADMIN** | Verification codes, OTPs, password-reset notifications from the Keysight Support Portal or partner portals. | Save copy in inbox; redirect to `portal-admin.pdl-ccc-americas@keysight.com`. |
| 5 | **COLLECTIONS** | Remittance advice, ACH-payment notifications, payment-method verification, invoice-related notices. | Redirect to `collections.pdl-americas@keysight.com` + `usar_keysight@keysight.com`; archive original. |
| 6 | **KSO** | Government, defence-prime, federal-reseller, or restricted-customer emails. | Redirect to `keysightorders@keysight.com`; delete original from intake mailbox. |
| 7 | **ISC_WO_RTK** | Service work-order intake — repair, calibration, RMA, recalibration, customer return-to-Keysight. | Sort to ISC folder; FCNV operator creates a CCC of type "Work Order", subtype "Return to Keysight". Drives Use Cases 3–5 (§§10–12). |
| 8 | **SALES_PO** | Standard purchase-order intake — new PO, sales order, Stock Rotation, Rebates, eBiz, SOW, Prebuild, Amendment, Cancellation, Change Quantity, Duplicate PO, Confirm-orders. | Sort to Sales PO folder; FCNV operator creates a CCC of type "Order Request". Drives Use Cases 1, 2, 6, 7 (§§8, 9, 13, 14). |
| 9 | **OTHERS** | Catch-all: invoice / payment status queries, tax-certificate requests, PO-form release, service-status queries, post-service certificate retrieval, agreement-settlement discussions, internal Keysight-to-Keysight messages. | Sort to "Others" folder; routed to a CSR for ad-hoc handling. No automated CCC creation. |

### 6.2 Scan order — stop at first match

The classification is evaluated **in strict order** and stops at the first matching class (verbatim from `KS FO Agent.json` step "Checking Override", "Strict per-rule stop-at-first-match" section):

```
1. UNDELIVERABLE
2. AUTO_REPLY
3. BRAZIL_TAX
4. PORTAL_ADMIN
5. COLLECTIONS
6. KSO
7. ISC_WO_RTK
8. SALES_PO
9. OTHERS  (catch-all)
```

### 6.3 Rationale for the scan order

The order encodes three business priorities:

1. **Operational hygiene first.** Bounces, auto-replies, and tax / portal-admin notifications are not business work — clearing them first prevents the FCNV team from spending classification cycles on them. They are handled by deterministic Outlook rules (§7.1), not by human reading.
2. **Compliance before commerce.** KSO precedes both ISC_WO_RTK and SALES_PO. A government or defence-prime customer's email must be redirected to the restricted-handling team even if it also contains a perfectly valid PO. The operational rule book confirms this with its opening directive (`KS FO Agent.json`, step "Checking Override", opening directive):

> "If the standard classification says the email as KSO and has relevant keywords then it should be a KSO, No matter what's the context in email and if it's matching with any other rule, it should be a KSO."

3. **Service before sales.** ISC_WO_RTK precedes SALES_PO so that a PO mentioned alongside a Work Order, Repair, Calibration, or RMA keyword is correctly handled as a service transaction (see Rule 3 in §20).

---

## 7. Email classification — the manual triage step

This section captures the FCNV team's **current** behaviour at intake — the manual reading and sorting of every inbound email into one of the nine classes from §6. It blends two source documents:

- The six deterministic **Outlook rules** that fire before any human reads the email (verbatim from `Current Outlook Rules_Narratives (1).pdf`, all 6 pages).
- The published ISC and Sales-PO sorting narratives (`ISC WO RTK.txt`, ISC WO Sorting section; `Sales PO Std Process & Change order (1).pdf`, p.1–2). In the original POC documents these sections are labelled "Agent #1.3" (ISC sorting) and "Agent #1" (Sales-PO sorting). Today both labels describe the same human step: the FCNV operator reading and sorting the email.

The two together describe the complete top-of-funnel triage that converts a mailbox into a set of classified, folder-sorted emails ready for the downstream use cases described in §§8–14.

### 7.1 The six pre-AI Outlook rules

Six rules are configured directly in Outlook and execute **before** any human inspection. Source: `Current Outlook Rules_Narratives (1).pdf`, six rule narratives across six pages.

#### Rule 1 — Undeliverable Outlook Rule (page 1)

**Goal (verbatim):** "As the Outlook rule, when an email is received, I want to discard auto generated emails so that when complete, there are less emails in the inbox."

**Trigger conditions (verbatim):**
- Subject line contains any of: `"Undeliverable"` · `"Undelivered Mail Returned to Sender"` · `"[Postmaster] Email Delivery Failure"` · `"Returned Mail: see transcript for details"` · `"You have some new Bonfire matches!"` · `"Your message couldn't be delivered"` · `"Delivery delayed: Keysight Support Web Email Update"` · `"Delivery Status Notification"` · `"Returned Mail"` · `"Mail Delivery Failure"` · `"Mail Delivery Failed"` · `"Delivery Delayed"` · `"DELIVERY FAILURE"`.
- Sender address contains `mailer-daemon`.
- Sender is exactly `noreply@keysight.com`.

**Action:** Move to the "Undeliverable" Outlook folder. The email is not further processed.

#### Rule 2 — KSO Outlook Rule (page 2)

**Goal (verbatim):** "As the Outlook rule, when a govt / prime email is received, I want to redirect that email to `keysightorders@keysight.com` so that it adheres to compliance regulations."

**Trigger conditions (verbatim):**
- Sender domain is one of: `@lmco.com` · `@fastx.com` · `@l3harris.com` · `@us.af.mil` · `@caci.com` · `@boeing.com` · `@ngc.com` · `@gov.in` · `@testmart.com` · `@nasa.gov` · `@baesystems.com` · `@tevet.com`.
- OR email body contains any of: `"N5194A"` · `"N5193A"` · `"N5192A"` · `"N5191A"` · `"Boeing"` · `"Sandia"` · `"Tevet"` · `"Peraton"` · `"Vallen"` · `"Leidos"` · `"Raytheon"` · `"Whitney"` · `"Cobham"` · `"General Dynamics"`.

**Action:** Redirect to `keysightorders@keysight.com`; delete the original from the intake mailbox. This rule is a **hard block** — it fires regardless of any actionable business content in the email body, because the controlling concern is export-control / compliance routing rather than commercial intent.

#### Rule 3 — Collections Outlook Rule (page 2–3)

**Goal (verbatim):** "As the Outlook rule, when a collections related email is received, I want to redirect that email to `collections.pdl-americas@keysight.com` so that the appropriate team actions it."

**Trigger conditions (verbatim):**
- Subject or body contains any of: `"Remittance Advice"` · `"Payment Advice"` · `"Payment Remittance Advice"` · `"Notice of new scheduled payment"` · `"Notice of new Remittance Advice"` · `"ACH Payment Remittance Advice"` · `"You got paid by Energy Medical Systems"` · `"early payment opportunity"` · `"GOOGLE PAYMENT NOTIFICATION"`.
- Subject equals `"Your invoice(s) have been received and may require additional attention"` (this variant moves to archive, not to the collections box).

**Action:** Redirect to `collections.pdl-americas@keysight.com` AND `usar_keysight@keysight.com`; archive the original.

#### Rule 4 — Portal Admin Outlook Rule (page 3–4)

**Goal (verbatim):** "As the Outlook rule, when a portal related email is received, I want to redirect that email to `portal-admin.pdl-ccc-americas@keysight.com` so that the email is actioned by the appropriate team."

**Trigger conditions (verbatim):**
- Subject or body contains any of: `"Password"` · `"validation code"` · `"verification code"`.

**Action:** Save a copy in the inbox AND redirect to the portal-administration team distribution list. The copy-and-forward pattern preserves audit while ensuring the right team sees it.

#### Rule 5 — Brazil Tax Outlook Rule (page 4–5)

**Goal (verbatim):** "As the Outlook rule, when a Brazil tax related email is received, I want to redirect that email to `lar_orders@keysight.com` so that the email is actioned by the appropriate team."

**Trigger conditions (verbatim):**
- Sender is `keysight.bra-tax@tmf-group.com`.

**Action:** Redirect to `lar_orders@keysight.com`; move the original to the archive folder.

#### Rule 6 — Auto Reply Outlook Rule (page 5–6)

**Goal (verbatim):** "As the Outlook rule, when an automatic reply is received without any important business information on the body of the message or in the subject line or in the attachment, I want to discard those emails so that FCNV does not spend time on N/A emails."

**Trigger conditions (verbatim):**
- Subject or body contains any of: `"Automatic Reply"` · `"Out of the office"` · `"OUT OF OFFICE"` · `"Automatic Reply: Keysight Support Web Email Update"`.

**Action:** Move to the "Out of Office" Outlook folder.

#### Cross-rule note — "actionable exception"

Rules 3, 4, 5, and 6 are **suppressed** when the email body contains a clear directive verb (please, kindly, ship, cancel, process, etc.) that overrides the surface pattern — i.e. an apparently administrative email that nonetheless carries a real business request must fall through to human classification rather than be auto-routed. This nuance is captured in the operational rule book (see §20, Rule 9 "Actionable Auto-Reply Detection") and explicitly preserved by the FCNV team's working practice. Rules 1 (Undeliverable) and 2 (KSO), by contrast, are **hard blocks** — they fire regardless of body content because the controlling concern is hygiene / compliance, not commerce.

### 7.2 Manual classification — ISC vs Sales-PO keyword filter

For every email that survives the six Outlook rules, an FCNV operator opens the email manually and applies the ISC vs Sales-PO keyword tests in this order.

#### 7.2.1 ISC WO sorting filter (verbatim from `ISC WO RTK.txt`, ISC WO Sorting section)

> "As an FCNV user, when an email is received, I want Services WO request emails categorized separately from every other email so that when completed, I have an isolated type of email to begin creating a CCC Request."

**Business rules (verbatim):**

1. **If the subject or body of the email or email attachment contains any of the following keywords, move to the ISC folder:**
   - `"RMA"`, `"WO"`, `"Work Order"`, `"Model/Serial #"`, `"PO#/Purchase order in conjunction with WO or Work Order or Repair/Calibration"`, `"Repair"`, `"Calibration"`.
2. **If the subject or body does NOT contain the following key words, leave them in the inbox:**
   - `"RMA"`, `"WO"`, `"Work Order"`, `"Serial #"`, `"Repair"`, `"Calibration"`.
3. **If there is important business message on the body of the email — for example, the request is for ISC WO however the customer is asking a question related to invoicing or status of their request — that must be categorized as Others and not ISC.** (Rule 13 / 20 in §20 codifies this.)
4. **All outbound emails from Keysight to external email domains should be categorized as Others. Condition: To = External customer/Clients; From = Keysight.com (Domain).**

**Data output:** Email status — categorized into ISC folder.

#### 7.2.2 Sales PO sorting filter (verbatim from `Sales PO Std Process & Change order (1).pdf`, p.1–2)

> "As an FCNV user, when an email is received, I want Sales PO request emails categorized separately from every other email so that when completed I have an isolated type of email to begin creating a CCC Request." (Sales PO PDF, p.1)

**Business rules (verbatim):**

1. **If the subject or body or attachment of the email contains any of the following keywords, move to the Sales PO folder:**
   - `"Purchase Order"` or `"PO"` or `"order"` or `"Purchase Requisition"` or `"Sales Order"` or `"New PO"`
   - PO accompanied with **Quote starting with 888**
   - Sender `estore_orders@keysight.com`
   - `"Stock Rotation"` or `"Rebates"`
   - eBiz orders coming from the email node `Keysight-Used-Equipment-Store (ebiz@keysight.com)` along with a PO copy
   - `"Amendment"` or `"Cancellation"` or `"Change Quantity"` or `"Duplicate PO"` or `"Confirm orders"` or `"Standard PO"`
   - **AND** does not include any of: `"RMA"`, `"WO"`, `"Work Order"`, `"Serial #"`, `"Repair"`, `"Calibration"`.
2. **If the subject or body contains the following key words, leave them in the inbox:** `"RMA"`, `"WO"`, `"Work Order"`, `"Serial #"`, `"Repair"`, `"Calibration"`.
3. **If there is important business message on the body of the email — for example, the request is for Sales PO however the customer is asking a question related to invoicing or status or providing taxability certificate of their request/order — that must be categorized as Others and not Sales PO.**
4. **Another example (verbatim):** "If you have a new sales order however customer is requesting calibration for the new equipment then that would be categorized as Sales PO and not ISC WO." (Sales PO PDF p.1, rule 3 second example — codified as Rule 3A in §20.)
5. **All outbound emails from Keysight to external email domains should be categorized as Others.** (Same condition as ISC WO rule 4.)

**Data output:** Email status — categorized into Sales PO folder.

### 7.3 Order of evaluation today

In practice, the FCNV operator runs the funnel from §6 each time a new email arrives. The Outlook rules pre-handle classes 1–5 mechanically. For everything that lands in the inbox after those rules fire, the operator:

1. Reads the sender domain — applies KSO judgement on top of the Outlook rule's domain list (some KSO emails arrive from domains not on the static list and must be caught by body-keyword inspection).
2. Reads the subject and first non-empty paragraph of the body — applies the ISC vs Sales-PO keyword tests above.
3. Opens attachments to disambiguate when needed (PO with cal-cert request = Sales PO; PO bundled with Work Order or Repair = ISC).
4. Applies the operational rule book (§20) to handle edge cases like generic-phrase emails, empty forwards, acknowledgement-only threads, and cancellation requests.
5. Moves the email to the corresponding folder (`ISC`, `Sales PO`, `Others`, etc.) — the folder placement determines who picks the email up next and which use case applies.

---

## 8. Use case 1 — Trade Order Entry — PO Received

This is the high-volume Trade Order Entry happy path: a customer sends a new Purchase Order email; the FCNV operator creates a CCC Request, drives validation and quote update, the Trade Track converts quote to order in Oracle EBS, generates the SOA, and notifies the customer.

![Trade Order Entry – PO Received Happy Path](/asis-diagrams/trade-po-received.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level End-to-End Flow — Trade Order Entry Happy Path for PO Received" diagram. Lanes: FCNV / AI OA / Trade. Footnote on diagram: "CCC Request Status & Stage.xlsx".*

### 8.1 What the diagram represents

The diagram shows three swim lanes — FCNV Track, AI OA Track, Trade Track — running in parallel. FCNV-Track work is performed manually by an FCNV operator. **The AI OA Track is the in-house AIOA tool**, which performs partial PO-data validation on the populated CCC Request and feeds an AI OA Fallout queue back to a human reviewer when it flags inconsistencies. Trade-Track work (Q2O conversion, Oracle EBS SO entry, SOA generation, SOA publishing) is performed manually by Trade-pool CSRs. The diagram depicts the happy path; the fallout paths feed back to FCNV or to a CSR for human-in-the-loop review.

### 8.2 Step-by-step walk-through (current operational behaviour)

**Step 1 — Email Received.** A customer sends a PO to one of the ≈50 intake mailboxes (FCNV Track). The operator opens Outlook; the Outlook rule pack has already pre-filtered Undeliverable / Auto-Reply / KSO / Collections / Portal-Admin / Brazil-Tax messages (§7.1).

**Step 2 — Email Classify.** The operator reads the email and applies the Sales-PO keyword filter (§7.2.2). If the email contains `"Purchase Order"`, `"PO"`, `"Order"`, `"Sales Order"`, `"New PO"`, or a Quote starting with `888`, and does not contain Service keywords (`RMA`, `WO`, `Work Order`, `Serial #`, `Repair`, `Calibration`), the email is moved to the Sales PO folder. Today this entire step is a human read; the partial Outlook automation only handles the pre-filter classes.

**Step 3 — Create CCC Request enrich (PO partner).** From the Sales PO folder, the operator opens the first email and begins the 23-step CCC creation procedure (verbatim from `Sales PO Std Process & Change order (1).pdf`, p.2–7). Key steps:

- Open the PO attachment; determine if it is an SOW (key identifiers: `Z*` SKUs, `"Statement of Work"`, `"Cover Letter"`, `"EID #"`, `"Custom Solutions"`). If SOW → apply Special handling step 12e and 14a-b (see §15.4).
- Copy the PO# from the attachment and paste into Salesforce global search to check for an existing CCC Request. Apply the existing-CCC status branching matrix (§16).
- If no existing CCC, locate the buyer email (or sender, unless sender is internal `@keysight.com`) and paste into Salesforce global search to populate a Customer Contact.
- Click into the Contact → hover over **CCC Request** in Quick Links → click **New**.
- Populate Origin = `"E-MAIL"`, Received Date / Time from the email, Type = `"Order Request"`. **Save.**

**Step 4 — CCC Request enrich-ment.** The operator continues populating the CCC Request:

- **Account Address = Ship-to** (unless the customer is a Distributor — in which case the Bill-to address is used, per Sales PO PDF p.5, item 9e, to ensure routing to the `AMFO_Disty/Rental` queue). If multiple ship-to addresses exist, the line-level address adjacent to the product is used (Sales PO PDF p.5, step 9.a.1).
- Quote # (if present in the PO) → Quote Information section.
- Product Interests → New → paste model #; select the top match without "-xxxx" options. If no match, fall back to `CUSTOM PRODUCT` (Sales PO PDF p.5, step 12c). If SOW, use `SOWDUMMY` (step 12e).
- PO# → Order Information section.
- Final Destination Country → dropdown (Sales PO PDF p.5, step 17).
- Order Amount → from PO total (Sales PO PDF p.5, step 19).
- Attach email file to Files quick link → Docunet popup → `Doc type = FCNV` (Sales PO PDF p.6, step 21).
- Activity → Add Task → Subject = `"other"`, Status = `"Completed"`, Save (Sales PO PDF p.6, step 23).

**Step 5 — Human in Loop FCNV Review (optional) [Fallout: FCNV Scope].** If the operator is uncertain about any field, a peer review is performed within the FCNV team. This is informal today — there is no system-enforced approval gate. The "FCNV Scope" fallout flag means the email is returned to FCNV's own backlog for re-work.

**Step 6 — Assign CCC Request owner.** The operator clicks **Assign** in Salesforce. The Assignment Lookup matches Ship-to City + State to a CSR (Sales PO PDF p.8, item 1.b). If the destination country is outside the US, the CCC is manually re-assigned to the Export Team using `EXPORTDUMMY` (Sales PO PDF p.8, item 1.a). If the customer is on the distributor list, the CCC auto-assigns to `AMFO_Disty/Rental` (Sales PO PDF p.9, item 3.a). If a standard customer is ordering disty product, the operator applies the `CUSTOM PRODUCT` escape (Sales PO PDF p.9, item 3.b).

**Step 7 — Human in Loop CSR Review (optional) [Fallout: STATUS Assigned, STAGE Automation in Progress].** Once assigned, the receiving CSR can optionally review the CCC. If the review identifies missing data, the CCC stays in `Assigned` status, `Stage = Automation in Progress`, and the CSR works it manually. There is no automation here today — the "Automation in Progress" stage label is a forward-looking field that describes intent.

**Step 8 — AIOA AI PO Validation.** The in-house **AIOA** tool performs partial validation on the extracted PO data — PO# format, dollar amount sanity, customer-account match, ship-to country. AIOA does **not** create the CCC nor perform the extraction; it is a check-and-flag aid. Pass → continue; flag → step 9.

**Step 9 — Human in Loop AIOA Fallout.** If AIOA flags a field as inconsistent, the CCC enters the **AI OA Fallout** queue. The FCNV operator (or a designated Trade-pool / fallout reviewer) opens the CCC, inspects the flag, and corrects the data manually. The corrected CCC is returned to the pipeline (`STATUS = Assigned, STAGE = Automation in Progress`) and the flow continues.

**Step 10 — Quote Update / Quote Update (cont).** The CSR opens the linked Opportunity and updates the Quote against the customer's PO — adjusting line items, prices, configurations as needed. This is manual work in Salesforce.

**Step 11 — Human in Loop Quote Update Fallout.** If the Quote does not match the PO (price mismatch, line-item mismatch, option mismatch), the CSR works the fallout manually — by contacting the customer or escalating to the relevant pricing team.

**Step 12 — Q2O Conversion.** The CSR converts the Quote to an Order in Salesforce (Quote-to-Order). The Order is then sent downstream to Oracle EBS via internal middleware.

**Step 13 — Q2O Fallout.** If the conversion fails (missing currency, ineligible product, invalid customer entity), the CSR handles the fallout manually — typically by correcting the Quote and retrying.

**Step 14 — Oracle EBS SO entered.** The order is entered into Oracle EBS; the order number is updated on the CCC Request and a confirmation report is attached. This step is automated within the Salesforce → Oracle middleware, but the CSR initiates it.

**Step 15 — Human in Loop CSR to complete order thru booking.** The CSR completes any outstanding fields on the Oracle order (hold release, shipment scheduling, payment terms) and moves the order to booked state.

**Step 16 — CCC Request updated to Booked / SOA GEN & Email SOA for CSR Review.** Once the order is booked, the SOA (Sales Order Acknowledgement) is generated, attached to the CCC Request and to Docunet, and prepared for CSR review.

**Step 17 — Human in Loop CSR Review SOA Email & Publishes to Cust.** The CSR reviews the SOA draft, makes any needed adjustments (language, terms, attachments), and sends the SOA to the customer. This is currently a manual outbound email.

**Step 18 — CCC Request Status Updated to Closed.** The CSR sets the CCC Request status to `Closed`. End of flow.

### 8.3 What is and isn't automated today

| Step | Today's automation | Manual work |
|---|---|---|
| 1 — Email received | Outlook rule pack pre-filters terminal classes | Operator opens inbox |
| 2 — Classify | None for SALES_PO class | Operator reads & decides |
| 3–4 — CCC create + enrich | Salesforce form validation | All field population, attachment opening, transcription |
| 5 — FCNV review | None | Peer review |
| 6 — Assign | Salesforce Assignment Lookup (rule-based) | Operator clicks Assign; applies CUSTOM PRODUCT / EXPORTDUMMY / SOWDUMMY escapes |
| 7 — CSR review | None | CSR reads CCC |
| 8 — AIOA AI PO Validation | **AIOA partial PO validation runs here** | Operator reviews flagged items in the AI OA Fallout queue |
| 9 — Human in Loop AIOA Fallout | None | Manual correction of AIOA-flagged fields, then return to pipeline |
| 10–11 — Quote update | None | Manual Quote edits |
| 12–13 — Q2O conversion | Salesforce Q2O button + middleware | Operator initiates; handles errors |
| 14 — Oracle SO entry | Middleware Salesforce → Oracle | CSR completes fields |
| 15 — CSR booking | None | Manual booking |
| 16 — SOA generation | Salesforce SOA template | Attached to CCC by CSR |
| 17 — SOA delivery | None | Manual outbound email |
| 18 — Close CCC | None | Manual status update |

---

## 9. Use case 2 — Trade Sales Change Order — CCC Request creation

When a customer sends a Change Order email referencing an already-booked PO, the FCNV operator creates a Change Order CCC Request (cloning the prior closed CCC if applicable) and hands off to the CCC Sales Order Track for the in-place order modification.

![Trade Sales Change Order – CCC Request Creation](/asis-diagrams/trade-change-order.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level End-to-End Flow — Trade Sales Change Order - FCNV Happy Path For CCC Request Creation" diagram. Lanes: FCNV / CCC Sales Order.*

### 9.1 What the diagram represents

The diagram has two swim lanes — FCNV Track and CCC Sales Order Track — both manual today. The FCNV operator owns intake and CCC creation; the Sales Order CSR owns the order-modification work in Salesforce + Oracle and the customer-facing update.

### 9.2 Step-by-step walk-through

**Step 1 — Email Received.** The customer sends a Change Order email — typically referencing an existing PO# or quote number. Outlook delivers the email to the FCNV mailbox.

**Step 2 — Email Classify.** The operator reads the email and applies the Sales-PO keyword filter (§7.2.2). Change-order emails typically contain `"Amendment"`, `"Cancellation"`, `"Change Quantity"`, `"Confirm orders"`, or reference a prior PO# — these route to the Sales PO folder per Sales PO PDF p.1, rule 1.

**Step 3 — Create CCC Request Change Order Recvd.** The operator paste the PO# into Salesforce global search to find the prior CCC Request. If the prior CCC is in `Closed` status and the new PO is a **revision** of the closed one, the operator **clones** the closed CCC and converts it to a Change Order Request (Sales PO PDF p.3, item ii.1):

- Click **Clone** in the top right.
- Type = `"Change Order"` (from dropdown).
- Order Amount = `New PO total − Old PO total` (delta amount, not the new absolute total).
- Verify Currency on the cloned CCC matches the PO currency; update if not.
- Verify the Final Destination Country on the cloned CCC matches the new PO's ship-to / end-customer information.
- If the final destination country is **outside USA or Canada**, follow the exception routing process (use `EXPORTDUMMY` and the Assignment Lookup, per Sales PO PDF p.4, item ii.4.a).

**Step 4 — CCC Request enrich-ment.** The operator completes the cloned CCC fields (account / address, currency, country, product, dollar amount delta) and attaches the email to Docunet with `Doc type = FCNV`.

**Step 5 — Human in Loop FCNV Review (optional) [Fallout: FCNV Scope; CSR completes CCC Request entry if needed; Automate miss information assigned to CCC Request].** The diagram annotation indicates two fallout subtypes: (a) FCNV-scope corrections, where the email is returned to FCNV's own queue; and (b) cases where the CSR completes the missing data on the CCC themselves. The "Automate miss information assigned to CCC Request" annotation is forward-looking — it describes the intent to automate missing-field detection; today this is human-driven.

**Step 6 — Assign CCC Request owner.** The operator clicks **Assign**. The Change Order is routed to the same CSR pool that owned the original order (typically the prior CCC's owner is retained as a Chatter recipient via @-mention).

**Step 7 — CSR updates CCC Request Status to In Progress.** The receiving CSR claims the work and moves the CCC to `In Progress`.

**Step 8 — CSR Updates Existing Order.** The CSR modifies the existing Oracle order (line items, quantities, dates, addresses) per the Change Order PO. If the change requires factory action or a re-quote, the CSR engages those teams.

**Step 9 — CSR Provides Update to Customer.** The CSR sends a customer-facing confirmation email summarising the modification.

**Step 10 — CSR Updates CCC Request Status to Closed.** End of flow.

### 9.3 Note on Change Order subtypes

The Change Order flow is also triggered by these intent subtypes (Sales PO PDF p.16; operational rule book §20, Rule 19 Exception and Rule 23):

- **Cancellation** requests (explicit PO or line cancellation).
- **Amendment** requests (revision to a previously submitted PO).
- **Change Quantity** requests.
- **eBiz Change Orders** (Sales PO PDF p.13, eBiz step 1.b).
- **Stock Rotation revisions** (Sales PO PDF p.10, Stock Rotation step 2.b).

The diagram's "Change Order Recvd" label is the FCNV-facing label; downstream subtype handling is described in §15.

---

## 10. Use case 3 — Service Order Management — Work Order Automation (single / multiple asset)

When a customer sends a Service Work Order request — repair, calibration, RMA, or any return-to-Keysight intent — accompanied by a PO without a pre-existing WO, the FCNV operator creates a CCC Request shell, and the SOM Track creates the WO in Salesforce. For multi-asset emails, one CCC Request is created per asset (Model # + Serial # pair).

![SOM – WO Automation Single/Multiple Asset](/asis-diagrams/som-wo-automation.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level SOM Flow — Service Order Management Happy Path – Work Order Automation (Single/Multiple Asset)" diagram. Lanes: FCNV / AI OA / Trade / SOM. Flag: "CMD Interface". Category = Work Order, Create PO without WO.*

### 10.1 What the diagram represents

Four swim lanes — FCNV / AI OA / Trade / SOM. The CMD Interface flag on the diagram indicates the WO automation reaches across to Centralised Master Data to confirm the customer account and the asset (Model # + Serial #) are registered. In current operations, the CMD reach is a manual lookup performed by an FCNV operator or an SOM CSR. The "Automation" labels on the boxes refer to a forward-looking intent; today the WO creation and CCC-Request closing are performed by SOM personnel.

### 10.2 Step-by-step walk-through

**Step 1 — Email Received.** A service request email arrives. The Outlook rule pack pre-filters terminal classes.

**Step 2 — Email Classify [Fallout: FCNV Scope].** The operator applies the ISC keyword filter (§7.2.1). If the subject or body or attachment contains `"RMA"`, `"WO"`, `"Work Order"`, `"Model/Serial #"`, `"PO# in conjunction with WO / Repair / Calibration"`, `"Repair"`, or `"Calibration"`, the email is moved to the ISC folder (ISC WO RTK.txt, rule 1). If the operator is uncertain, the fallout is returned to FCNV's queue.

**Step 3 — Create CCC Request (shell).** From the ISC folder, the operator opens the email and applies the 22-step CCC creation procedure (verbatim from `ISC WO RTK.txt`, ISC WO CCC Request Creation section). Key steps:

- **Pre-filter for quotes (step 1).** If the subject or body contains `"Request for quote"` or `"Quote"`, exit the email — quotes are not RTK work-orders. Continue to the next email.
- **Confirm service intent (step 2).** If the subject or body contains `"Repair"` or `"Calibration"` or `"Work Order"` or `"Evaluation"` or `"Technical Evaluation"`, OR a Purchase Order accompanied by a Model & Serial # — leave in the ISC folder for processing.
- **Extract identifier (step 5).** Copy the Work Order # (`WO-000000`) **or** the PO# from the email or attachment.
- **Search Salesforce for an existing CCC (step 6).** Paste the WO# / PO# into the global search bar. If a CCC exists, follow the existing-CCC status matrix (§16) — branches to Continue Processing for active CCCs, new CCC for Cancelled, Change Order clone for Closed.

**Step 4 — CCC Request enrich-ment Incomplete [Fallout Scope CCC Request: Multiple assets in 1 email — if same info and AI able to understand = 1 CCC Request → Multiple WO create; different information (addresses) not able to understand = 1 CCC Request assigned to SOM CSR].** The operator either populates the CCC Request directly or, for multi-asset emails, applies the verbatim multi-asset rule from `ISC WO RTK.txt`, step 15a:

> "[very frequent to have multiple assets on an email] Note: if there are multiple assets (Model # + Serial #), you will need to repeat steps 8–22 (barring step 20) with each asset. It is **1 CCC Request to 1 asset, NOT 1 email to 1 CCC Request**."

For each additional asset:
1. Click **Clone** in the top-right corner of the CCC Request.
2. Update the address every time the CCC is cloned.
3. Keep a sticky note of all the CCC Requests created so the email can be archived properly.

The diagram fallout annotation captures two practical multi-asset edge cases: (a) when all assets share the same address / customer information, one CCC is created per asset (the operator clones); (b) when the email contains different ship-to addresses or operator-difficult details, a single CCC Request is created and assigned to SOM CSR for manual fan-out. Today there is no AI doing this judgement — the operator decides.

**Step 5 — AI Agent Populate CCC Request Owner Incomplete.** This box on the diagram is forward-looking. Today, the operator manually populates the owner field or relies on Salesforce Assignment Lookup to suggest one.

**Step 6 — Automation Create WO and Assign Owner [Fallout Potential: System errors/fail-out = Assign CCC Request to SOM CSR].** Today the WO record in Salesforce is created by an SOM CSR — not by an automation. If the diagram's "Automation" path fails (or, in current state, is not exercised at all), the CCC Request is assigned to a SOM CSR for manual WO creation.

**Step 7 — SOM AI Agent Attach Email and attachments to WO.** Today this attachment step is performed by the SOM CSR — the email file is uploaded to the WO record's Files quick link with `Doc type = FCNV` (mirroring the CCC attachment step). The diagram label "SOM AI Agent" reflects forward-looking intent; the action is manual today.

**Step 8 — AI Agent Close CCC Request (no reply).** The CCC Request is closed without an outbound customer reply — the customer's confirmation is implicit in the downstream RTK shipment workflow. Today this closure is performed manually by the SOM CSR.

**Step 9 — Human in Loop CSR Review of WO [Fallout Scope; Manuals = SOM: Email from WO back to Email for correct assignment].** The SOM CSR reviews the WO for completeness. If the WO is incorrectly assigned (wrong site, wrong product type, etc.), the diagram fallout path routes the email from the WO back to Email for correct re-classification — i.e., it returns to the inbox triage step.

**Step 10 — End.**

### 10.3 The single-asset operational detail

For a single-asset WO RTK, the 22-step CCC creation flow runs end-to-end on one CCC Request:

| Step | Action |
|---|---|
| 7 | Search Salesforce by sender email to find Customer Contact. |
| 8 | Verify contact / create if missing. Sub-steps 8a–8e cover Account creation, CMD activation request, Contact creation. |
| 9 | Click into the **CCC Request** hyperlink in Quick Links. |
| 10 | Click **New** → populate Origin = `E-MAIL` / Received Date / Time / Type = `Work Order` / Subtype = `Return to Keysight`. |
| 11 | **Save.** |
| 12 | Populate ship-to address. |
| 13 | Populate PO# under Order Information. |
| 14 | **Save.** |
| 15 | Add **Product Interests** → New → Model #. |
| 16 | Resolve product (search; Show More Results; fall back to `CUSTOM PRODUCT` if no match). |
| 17 | Back to CCC Request tab. |
| 18 | Paste Serial # into **FE Comments** (Quote Information section). If `CUSTOM PRODUCT` was used, populate BOTH model and serial. |
| 19 | **Save.** |
| 20 | Attach the email file to the CCC (Files quick link → Add Files → Docunet `Doc type = FCNV`). |
| 21 | Back to CCC Request tab. |
| 22 | Add Activity task (Subject = `"other"`, Status = `"Completed"`, Comments = `"ISC"`). |

### 10.4 Assignment (the prior "Agent #3" role)

After the CCC is created, the operator assigns it via the 5-step procedure (verbatim from `ISC WO RTK.txt`, ISC WO CCC Request Assignment section):

| Step | Action |
|---|---|
| 1 | If the pending CCC's status = `New`, Type = `Work Order`, Subtype = `Return to Keysight`, and Ship-to Address matches the customer's email / PDF → click **Assign**. |
| 2 | Verify the owner changes from the operator's name to the appropriate CSR / CTA. |
| 3 | If the CCC Request is not assigned, refer to **Superuser** for exception handling. |
| 4 | Populate the CCC Request # into the subject of the email and archive in the "Archive" folder. |
| 5 | **Honour FE / CSR routing overrides.** Verbatim: *"Any specific instructions by the FE or the CSR/CTA would supersede system routing, hence check for specific routing instructions on the email."* (`ISC WO RTK.txt`, step 5) |

Step 5 is the single most important downstream-routing rule in the entire AS-IS process: **any human override embedded inside the email body trumps the automatic assignment logic.** A typical override might read "Please route this to Joe Smith in EMEA" or "Send this to the SOW team — EID 12345 attached".

---

## 11. Use case 4 — Service Order Management — WO Update / Change Order / Multiple Assets

When a customer sends a PO referencing an **already-existing** WO (update, addendum, change-order against the existing WO, or additional asset on the same site), the FCNV operator updates the existing WO record rather than creating a new one.

![SOM – WO Update/Change Order/Multiple Assets](/asis-diagrams/som-wo-update.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level SOM Flow — Service Order Management Happy Path – Work Order Update/Change Order/ Multiple Assets" diagram. Lanes: FCNV / AI OA / Trade / SOM. Category = Update Work Order, PO for existing WO.*

### 11.1 What the diagram represents

The same four swim lanes as Use Case 3, but the action is to update an existing WO rather than create a new one. The diagram emphasises the in-house **AIOA** partial PO validation on the inbound PO (because the PO references a WO that's already in flight) and the SOM CSR's review / reply step.

### 11.2 Step-by-step walk-through

**Step 1 — Email Received.** Customer sends a PO referencing an existing WO# (`WO-000000`).

**Step 2 — Email Classify.** Same as Use Case 3 — the ISC keyword filter sorts the email to the ISC folder. The presence of a WO# and "Repair" / "Calibration" makes the classification unambiguous.

**Step 3 — Create CCC Request (shell).** The operator pastes the WO# into Salesforce global search. The search returns an existing CCC Request tied to the WO. Per the existing-CCC status matrix (§16):

- **Active statuses** (Assigned / In Progress / Continue Processing / Awaiting Customer-CIA / Awaiting Customer-info / Awaiting Internal-FE / Awaiting Internal-System) → Attach the email; change status to `Continue Processing`; update PO# on the CCC; change request type to `Work Order` (verbatim from `ISC WO RTK.txt`, step 6a).
- **Continue Processing** specifically → Attach email; update PO#; change type to Work Order (status already correct).
- **Closed** → Clone the CCC as a Change Order.
- **Cancelled** → Create a new CCC.

**Step 4 — CCC Request enrich-ment Incomplete.** The operator populates the PO# field, updates Order Amount if the PO carries a dollar value, and saves.

**Step 5 — Update Existing WO (Add Note, Add Task on WO).** The SOM CSR (not the FCNV operator) opens the existing WO record and adds a Note describing the PO update; also adds a Task to track the change-action. This is manual Salesforce work today.

**Step 6 — SOM Agent Attach Email and attachments to WO.** The SOM CSR uploads the email file to the WO's Files quick link with `Doc type = FCNV`. (Note: the diagram label "SOM Agent" reflects intent; the action is manual today.)

**Step 7 — PO triggers AIOA Validation.** The in-house **AIOA** tool runs partial validation on the new PO data — PO# format, dollar amount, model / serial cross-check against the WO. Flagged items are routed to a human reviewer via the AI OA Fallout queue; the SOM CSR opens the flagged CCC and corrects the data manually.

**Step 8 — Close CCC Request (no Reply).** The CCC Request is closed without a customer reply — the WO update itself is the action; the customer is informed in the downstream shipment / status notifications.

**Step 9 — Human in Loop CSR Review of WO and Reply [Fallout Scope; Manuals = SOM: Email from WO back to Email for correct assignment].** The SOM CSR reviews the WO update and, if a customer reply is warranted (e.g., a question was embedded in the PO email), composes and sends it manually. If the WO assignment was wrong, the email is sent back to the inbox for re-classification.

**Step 10 — End.**

### 11.3 Multi-asset update edge case

When the inbound email references an existing WO **plus** one or more new assets that should be added to the same WO, the operator either:

- Adds Product Interest entries to the existing CCC (one per new asset) and updates the WO Notes / Tasks accordingly, or
- For materially different asset details (different ship-to, different repair scope), creates a separate CCC per new asset following the multi-asset clone rule (§10.2, step 4).

The operator's judgement governs the choice. There is no automated multi-asset detection today.

---

## 12. Use case 5 — Service Order Management — WO Status / Inquiry

When a customer asks for the status of an existing WO — without attaching a PO or requesting a service change — the FCNV operator replies with the current WO status. The diagram annotates this as "AI Reply with WO Customer Friendly Status and KSP statement". Today this is largely a manual reply; the "AI Reply" label reflects forward-looking intent.

![SOM – WO Status/Inquiry](/asis-diagrams/wo-status-inquiry.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level SOM Flow — Service Order Management Happy Path – Work Order Status/Inquiry" diagram. Lanes: FCNV / AI OA / Trade / SOM. Category = WO Status, WO Inquiry.*

### 12.1 What the diagram represents

The shortest of the SOM flows. There is no CCC Request creation in the happy path; the operator simply looks up the WO status in Salesforce and replies. Fallout creates a CCC Request and routes to a CSR for deeper handling.

### 12.2 Step-by-step walk-through

**Step 1 — Email Received.** Customer sends a status inquiry referencing a WO# or asking "what is the status of my repair?".

**Step 2 — Email Classify / Reply [Fallout: FCNV Scope: minimum info to classify and move to CCC Request assign to FCNV].** The operator reads the email. If the inquiry is a clean WO status request (WO# clearly referenced, no service change request, no PO attached), the operator looks up the WO in Salesforce, copies the customer-friendly status (typically: `In Repair`, `Awaiting Parts`, `Calibration in Progress`, `Ready to Ship`, etc.), and composes a reply. If the email contains too little information to classify cleanly, the fallout path creates a CCC Request shell and assigns it to FCNV for follow-up. Operational rule book Rule 13 (§20) supports this — ISC keywords without clear service intent route to `OTHERS`.

**Step 3 — AI Reply with WO Customer Friendly Status and KSP statement [Fallout Scope: CCC Request created and assign to CSR].** Today this is **a manual reply**. The operator composes an email using the WO status pulled from Salesforce, optionally including a pointer to the Keysight Support Portal (KSP) for ongoing tracking. The diagram label "AI Reply" describes the intended future-state automation; today the reply is hand-written. If the inquiry cannot be answered with a status (e.g., the customer is asking about a Cal Cert retrieval — which falls under Override Rule 24, §20), the fallout creates a CCC Request and assigns it to a CSR for full handling.

**Step 4 — End.**

### 12.3 The AI augmentation claim

The diagram's "AI Reply" box describes a forward-looking augmentation beyond AIOA's current scope. In current operations, the FCNV operator performs the WO-status lookup in Salesforce and composes the reply manually — **AIOA does not generate customer-facing text today**; its role is bounded to partial PO validation on the Trade Order Entry, SOM WO Update, and Service Contracts flows. The "KSP statement" referenced in the box is a templated paragraph operators paste into status replies to point customers to the Support Portal for self-service tracking — it is a copy/paste template, not an AI-generated string.

---

## 13. Use case 6 — Service Contracts — CCC Request creation

When a customer sends a Support Agreement Quote request or an Order Request for an Agreement, the FCNV operator creates a CCC Request and the S+R Track picks up.

![Service Contracts – CCC Request Creation](/asis-diagrams/service-contracts.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level Flow — Service Contracts – FCNV Happy Path For CCC Request Creation" diagram. Lanes: FCNV / AI OA / S+R. Category = Service Contracts / Agreements; Quote Request or Order Request.*

### 13.1 What the diagram represents

Three swim lanes — FCNV / AI OA / S+R. The diagram explicitly labels the CCC Request status and stage transitions: `STATUS New, STAGE Automation in Progress` → review stages → `STATUS Awaiting XXX, STAGE Review Required` (fallout) → `STATUS Assigned, STAGE Automation Complete` (pass) / `STATUS Assigned, STAGE Review Required` (fail).

### 13.2 Step-by-step walk-through

**Step 1 — Email Received.** The customer sends a request relating to a Support Agreement Quote (various subtypes) or an Order Request for an Agreement.

**Step 2 — Email Classify [Request Type = Support Agreement Quote (various subtypes) or Order Request (various subtype – Agreement); STATUS New, STAGE Automation in Progress].** The operator reads the email. Service Contracts requests carry distinctive keywords (`Support Agreement`, `Service Contract`, `Agreement Quote`, agreement-renewal language). On classification, the CCC Request is opened with `STATUS = New` and `STAGE = Automation in Progress`. The "Automation in Progress" stage tag reflects the fact that AIOA's partial PO validation will run downstream on this CCC (Step 8 below).

**Step 3 — Create CCC Request (shell).** The operator opens a new CCC Request from the customer's Contact record. The Type field is set to either `Order Request` (for an agreement-order) or to a quote-tracking equivalent (for an agreement-quote).

**Step 4 — CCC Request enrich-ment.** The operator populates the agreement-specific fields:

- Customer / contract entity.
- Agreement type / scope (per the customer's attached document).
- PO# (if attached).
- Product Interests (the assets covered by the agreement).
- Order Amount or Quote Amount.
- Attach the email and any agreement attachments to Files / Docunet (`Doc type = FCNV`).

**Step 5 — Human in Loop FCNV Review (optional) [Fallout: FCNV Scope; STATUS Awaiting XXX, STAGE Review Required].** Service Contracts data is often more complex than a standard PO (custom terms, multi-year coverage, asset-by-asset pricing). If the operator is uncertain, the CCC moves to `STATUS = Awaiting XXX` (where XXX names the awaited party — Customer / Internal / FE) and `STAGE = Review Required`. The fallout returns to FCNV's queue.

**Step 6 — Assign CCC Request owner [STATUS New, STAGE Automation in Progress].** The CCC is assigned to the S+R queue. The operator clicks Assign in Salesforce; the Assignment Lookup steers the work to the right S+R CSR based on region and customer.

**Step 7 — Human in Loop CSR Review (optional) [Fallout: CTA Scope].** The receiving S+R CSR / CTA reviews the CCC. If the CSR identifies missing data or wrong intent, the fallout returns to CTA for re-work.

**Step 8 — AIOA AI PO Validation [Once Complete = PASS: STATUS Assigned, STAGE Automation Complete].** Where the Service Contract is attached as a formal PO, the in-house **AIOA** tool performs partial PO validation. On pass, the CCC moves to `STATUS = Assigned, STAGE = Automation Complete`.

**Step 9 — Human in Loop AI Fallout [Once Complete = Fail: STATUS Assigned, STAGE Review Required].** On AIOA fail, the CCC moves to `STATUS = Assigned, STAGE = Review Required` and the S+R CSR handles the flagged items manually via Salesforce edits and (where needed) an email round-trip with the customer.

**Step 10 — CCC Request Selected and begin process.** The S+R CSR selects the CCC Request from the queue and begins the contract-fulfilment process — which is downstream of FCNV scope and not described further in this SOP.

**Step 11 — End.**

---

## 14. Use case 7 — SSD Change Request

When a customer requests a change to the Specified Ship Date on a booked order — or an equivalent post-booking modification (address change, line-item adjustment, packing change) — the work crosses from FCNV intake to a dashboard-driven loop spanning the CSR, factory, and Oracle.

![SSD Change Request – CCC Request Creation](/asis-diagrams/ssd-change-request.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "High-Level Flow — SSD Change request – FCNV Happy Path For CCC Request Creation" diagram. Lanes: FCNV / Post Order Booking. Category = Trade Order Modification, Sub-type = SSD Change.*

### 14.1 What the diagram represents

Two swim lanes — FCNV Track and Post Order Booking Track. The Post Order Booking Track operates a CSR dashboard against which factory teams and Oracle interact. The dashboard is not new technology; it is the operational tool today's CSRs use to track post-booking modifications.

### 14.2 Step-by-step walk-through

**Step 1 — Email Received.** Customer sends an SSD Change request — typically a short email referencing an Order #, Sales Order #, or PO#, asking for a different ship date.

**Step 2 — Email Classify.** The operator applies the Sales-PO keyword filter (§7.2.2). SSD Change emails frequently contain `"reschedule"`, `"change ship date"`, `"expedite"`, `"new SSD"`, or `"SSD"` keywords. Operational rule book Rule 20 Exception (§20) supports SSD requests as legitimate `SALES_PO` / `ISC_WO_RTK` classifications when tied to a valid PO/WO.

**Step 3 — Human in Loop FCNV Review (optional) [Fallout: FCNV Scope].** The operator confirms intent; if uncertain, the email is returned to FCNV for re-work.

**Step 4 — Create & Assign CCC Request owner [Request Type = Trade Order Modification, Sub-type = SSD Change, STATUS Automation in Progress, Owner = Sales Order Owner or Direct Inquiries (in Oracle)].** The operator creates a CCC Request with the explicit `Request Type = Trade Order Modification` and `Sub-type = SSD Change`, and assigns the owner to the original Sales Order owner (looked up in Oracle) or to `Direct Inquiries` (a generic post-order-booking team) if the original owner is unavailable. The `STATUS = Automation in Progress` tag is the intent-stage marker.

**Step 5 — Add SSD request to the CSR dashboard.** The CCC Request is added to the Post Order Booking CSR dashboard. This is a Salesforce list view today; new SSD entries surface automatically because they carry the right Type / Sub-type tags.

**Step 6 — Notification to CSR & Factories.** The dashboard notifies the assigned CSR. The CSR forwards the request to the relevant factory (Keysight has multiple manufacturing sites) — today this is a manual outbound to a factory-specific email or ServiceNow workflow.

**Step 7 — Factory prepares SSD & triggers CSR from dashboard.** The factory determines feasibility (can the shipment be re-scheduled? what is the impact on capacity?), prepares the SSD change recommendation, and triggers the CSR back via the dashboard.

**Step 8 — Factory triggers CCC interaction to finalize SSD from dashboard.** The factory uses the dashboard to indicate the proposed new SSD. The CSR sees the proposal on the CCC Request's interaction log.

**Step 9 — Insert triggers changes to Oracle, from dashboard [Human in loop bracket].** The CSR confirms the SSD change; the dashboard inserts the modification into Oracle (via the standard Salesforce → Oracle middleware). The "Human in loop bracket" annotation on the diagram emphasises that the Oracle write is gated by CSR approval, not auto-executed.

**Step 10 — CCC Request gets closed auto [STATUS Closed].** Once the Oracle update is confirmed, the CCC Request is closed. The diagram says "closed auto" — in current operations this is a CSR action on the dashboard, not a true automation.

**Step 11 — Customer gets notified.** A confirmation is sent to the customer — typically a templated email from the CSR. End of flow.

### 14.3 Other Trade Order Modification subtypes

The SSD Change flow is one of several Trade Order Modification subtypes. Others handled by the same Post Order Booking Track include:

- **Address change** (Bill-to or Ship-to change after booking).
- **Line-item cancellation** on a booked order.
- **Quantity reduction** on a booked order.
- **Packing / labelling change** requested post-booking.

These follow the same dashboard pattern: FCNV creates the CCC with the appropriate Sub-type; the dashboard surfaces the work; the factory / Oracle update loop completes the modification.

---

## 15. Special subtypes

Source: `Sales PO Std Process & Change order (1).pdf`, p.9–16, "Standard PO exceptions without Subtype" section. These subtypes share the Sales-PO base process (§8) but have specific identification keywords, source mailboxes, and field-population rules. Verbatim content has been retained; the original "Agent #N" labels have been replaced with the FCNV operator role.

### 15.1 Stock Rotation (quarterly partner)

**Source mailbox / keyword:** Typically arrives from `partner_assistance@keysight.com`. Subject contains `"Stock Rotation Request"` (e.g., `"Stock Rotation for February 2025"`).

**Cadence:** Quarterly partner stock-rotation orders. No subtype — categorised under Standard PO.

**Identification:** Open the email; copy the PO # provided on the body of the message; search Salesforce global search for that PO #.

**Processing (verbatim from Sales PO PDF, p.10):**

1. If a result is found, drill down on the relevant CCC and match the customer details:
   - The Partner Name should match the Account name on the relevant CCC.
2. Once the partner name matches, follow the existing-CCC status branching matrix (§16).
3. **If the CCC is in Closed status**, follow Change Order flow:
   - Clone the CCC; change Type to `"Change Order Request"`; populate Received date / time; attach email to Files (Doc type = FCNV); add Activity task with Subject = `"other"`, Status = `"Completed"`; Save.
4. **If no existing CCC**, follow the new-CCC creation flow (Sales PO PDF p.10–11, steps 3–25).

### 15.2 Rebates (monthly partner; negative order amount)

**Source mailbox / keyword:** Typically arrives from `partner_assistance@keysight.com` (but not limited to that node). Subject begins with `"APPROVED -"` followed by the rebate descriptor (e.g., `"APPROVED - US | Canada Distributor Quota Achievement Rebate Report - Q3 CY24 - INSTALLMENT # 3"`).

**Cadence:** Monthly partner rebates. 5–10 transactions / month. No subtype — categorised under Standard PO.

**Identification:** Copy the PO # from the subject line — the PO number starts **after the word "Approved"**. Paste in the global search bar to check for duplicates (highly unlikely to produce results; if it does, leave the email in the folder and treat as exception — Manual Handling).

**Processing (verbatim from Sales PO PDF, p.12–13):**

1. If no existing CCC, refer to the Excel attachment on the email.
2. Open the Excel file; access the **Trade Credit RMU** tab.
3. Locate the distributor name from the list for US Canada & LAR.
4. Once you have identified the partner's name, copy & paste the Account name in the global search bar.
5. Scroll down to the Accounts section and select any Partner account in the **active** status.
6. Click on the account name; hover over the CCC Request hyperlink in Quick Links; click **New** to create a new CCC Request and enter:
   - Origin = `"E-MAIL"`.
   - Received Date = email date.
   - Received Time = email timestamp.
   - Type = `"Order Request"`.
   - Account name from step 3.G.
   - Save.
7. Click **Product Interests** → **New** to add the model # from the **Summary** tab of the Excel file. (Model starts with **`W`** and is in **5×6** format.)
8. Paste model in product search; select top match. If no results, **Show More Results**. If multiple products fail to add, use **`CUSTOM PRODUCT`**. Save.
9. Return to CCC tab; copy PO # from step 3.b; paste into PO# field.
10. Go to the Excel **Summary** tab; add the totals of all Rebates (noted as `Total in USD or CAD or BRL`); **update the combined value in negative on the Order Amount field in the CCC**.
11. Save; attach email file (Doc type = `FCNV`); add Activity task (Subject = `"other"`, Status = `"Completed"`); Save.

> **Distinctive feature:** Rebates carry a **negative Order Amount** to represent credit owed to the partner. The dollar value is the sum of per-partner totals from the Summary tab of the Rebate Excel attachment, in the partner's native currency (USD / CAD / BRL).

### 15.3 eBiz (Keysight Used Equipment Store)

**Source mailbox / keyword:** Emails arrive from `ebiz@keysight.com` (the Keysight Used Equipment Store node), accompanied by a PO copy or sub-attachments with PO details (Bill-to and Ship-to addresses).

**Identification:** PO numbers are formatted as `eBiz_CA_<region>_<digits>`, for example `eBiz_CA_MB00053864`.

**Processing (verbatim from Sales PO PDF, p.13–16):** Identical to Sales PO except for two differences:

1. **PO# identifier:** Copy the PO # from the body of the email (formatted as `PO Number: eBiz_CA_MB00053864`), paste in global search.
2. **Change Order delta amount:** If matched to a closed CCC, clone to Change Order with `Order Amount = New PO total (from body of eBiz email) − Old PO total on CCC`.
3. **Standalone Order Amount** (when creating new CCC): Copy the PO total from the body of the eBiz email and update that amount in the Order Amount field (Sales PO PDF p.16, step 21).

### 15.4 SOW (Statement of Work / Custom Solutions)

**Identification:** PO contains `Z*`-prefix SKUs, the phrase `"Statement of Work"`, a `"Cover Letter"`, an `"EID #"`, or `"Custom Solutions"` language.

**Processing differences from Sales PO standard:**

- **Step 12e:** Use **`SOWDUMMY`** as the Product Interest, regardless of the actual `Z*` SKU.
- **Step 14a:** If an EID # is present (Ctrl+F `"EID"` in the PO attachment), route to the **SOW Team** via the Assignment Lookup using `SOWDUMMY`.
- **Step 14b:** If no EID is found, skip the EID check and follow step 15 of standard Sales PO (PO# → CCC).

### 15.5 Prebuild, Amendment, Cancellation, Change Quantity, Duplicate PO, Confirm Orders

These six are listed in the Sales PO sorting filter (§7.2.2) as keywords that route into the Sales PO folder. Their processing mostly inherits the Sales PO flow with one of these characteristics:

- **Prebuild:** PO sent in advance of physical inventory availability. Standard Sales PO flow applies; the CSR downstream manages the prebuild window.
- **Amendment:** Update to a previously submitted PO. Per Rule 19 Exception (§20), retains `SALES_PO`. Matches existing CCC via PO # → Continue Processing branch (§16).
- **Cancellation:** Explicit PO or line-item cancellation. Per Rule 23 (§20), retains `SALES_PO`. If the original CCC is Closed → Change Order. If still active → Continue Processing.
- **Change Quantity:** Per Rule 19 Exception (§20), retains `SALES_PO`. Same matching logic.
- **Duplicate PO:** Two emails referencing the same PO. The PO-# search in Salesforce will return an existing CCC; the operator attaches the second email to that CCC and notifies the owner via Chatter.
- **Confirm Orders:** Customer-side acknowledgement of a previously placed PO. Treated as `SALES_PO` only if there is a directive (per Rule 25 in §20 — acknowledgement-only threads with no directive map to `OTHERS`).

### 15.6 Excluded subtypes — documented but out of scope today

Per Sales PO PDF p.16 ("Left out of this document"):

- **Consumption Billing** — 4 requests / month — kept out of scope for the POC due to low volume and operational complexity.

Other low-volume specialised subtypes that exist operationally but are not enumerated in the POC scope: government-classified workflows (KSO downstream after redirect), parts-only orders via `estore_orders@keysight.com` (Sales PO PDF p.9, parts orders have a separate narrative under Sales).

---

## 16. Existing-CCC status branching matrix

When the FCNV operator searches Salesforce for an existing CCC by PO# or WO# (§8.2 Step 3; §10.2 Step 3; §11.2 Step 3), Salesforce may return zero, one, or more candidate CCC Requests. If exactly one match is found, the existing-CCC status determines the action. This matrix consolidates the verbatim rules from both source narratives — `Sales PO Std Process & Change order (1).pdf` p.3 and `ISC WO RTK.txt` step 6a.

| CCC status | Source | Action |
|---|---|---|
| **New** | Sales PO PDF p.3, item i.b.iii | Attach email; verify $ amount and update if needed; **notify owner via Salesforce Chatter**; proceed to step 21. |
| **Assigned** | Both — ISC WO RTK.txt step 6a.6; Sales PO PDF p.3, item i.b.i | Attach email; if PO & WO info match (ISC) or no additional condition (Sales PO): change status to **Continue Processing** (ISC only); update PO#; change type to Work Order (ISC) / proceed to step 21 (Sales PO). |
| **In Progress** | ISC WO RTK.txt step 6a.5 | Attach email; change status to **Continue Processing**; update PO#; change request type to Work Order. |
| **Continue Processing** | Both — ISC WO RTK.txt step 6a.7; Sales PO PDF p.3, item i.b.ii | Attach email; **notify owner via Salesforce Chatter**; update PO# (ISC) / proceed to step 21 (Sales PO). Status already correct. |
| **Awaiting Customer-CIA** (A/W Customer-CIA) | Both — ISC WO RTK.txt step 6a.3; Sales PO PDF p.3, item i.b.iv | Attach email; change status to **Continue Processing**; update PO# (ISC) / proceed to step 21 (Sales PO). |
| **Awaiting Customer-info** (A/W Customer-info) | ISC WO RTK.txt step 6a.4 | Attach email; change status to **Continue Processing**; update PO#; change request type to Work Order. |
| **Awaiting Internal-FE** (A/W Internal-FE) | Both — ISC WO RTK.txt step 6a.1; Sales PO PDF p.3, item i.b.vi | Attach email; change status to **Continue Processing**; update PO# (ISC) / proceed to step 21 (Sales PO). |
| **Awaiting Internal-System** (A/W Internal-System) | Both — ISC WO RTK.txt step 6a.2; Sales PO PDF p.3, item i.b.v | Attach email; change status to **Continue Processing**; update PO# (ISC) / proceed to step 21 (Sales PO). |
| **Cancelled** | ISC WO RTK.txt step 6a (Cancelled item) | **Create a new CCC Request** (no clone). The cancelled CCC is treated as if it does not exist. |
| **Closed** | Both — Sales PO PDF p.3, item ii.1 with full Change Order validation | **Clone the existing CCC** as a **Change Order Request** (see §9). Apply delta-amount rule and outside-US / Canada exception routing. |

### 16.1 Cross-narrative reconciliation notes

- ISC WO and Sales PO use **identical** status labels with **functionally equivalent** actions for the seven "active" statuses (Assigned, In Progress, Continue Processing, A/W Customer-CIA, A/W Customer-info, A/W Internal-FE, A/W Internal-System) — the differences are field-specific (ISC updates request type to Work Order; Sales PO proceeds to step 21).
- The two "terminal" statuses (Cancelled, Closed) bifurcate sharply: Cancelled → new CCC; Closed → Change Order clone.
- **Chatter notification** is invoked for `New` and `Continue Processing` matches in the Sales PO narrative (where the existing CCC has an owner who already started work); ISC WO does not explicitly invoke Chatter — it only updates status and PO#.
- The **PO & WO info match** precondition in the ISC WO narrative is implicit in Sales PO (the search returned the CCC because of the PO match — the operator visually confirms account / address / model match before proceeding).

---

## 17. Distributor partner lists

Source: `Sales PO Std Process & Change order (1).pdf`, p.6–7. Verbatim partner names; Latin Americas list overflows page 6 into page 7.

When a CCC Request's Account is a member of either list, the assignment step (§19) auto-routes the CCC to the **`AMFO_Disty/Rental`** queue. When a standard customer orders disty product (via a `CUSTOM PRODUCT` escape — see §18), the routing avoids that queue.

### 17.1 US / Canada Distributor Partners

| # | Distributor name |
|---|---|
| 1 | RS (formerly Allied) |
| 2 | Avnet |
| 3 | Continental Resources (ConRes) |
| 4 | Electrorent |
| 5 | Gap Wireless |
| 6 | Mouser Electronics Inc |
| 7 | Newark |
| 8 | RFMW LTD |
| 9 | Tessco |
| 10 | TestEquity |
| 11 | Transcat |
| 12 | TRS |

*Note: 12 names are tabulated verbatim in Sales PO PDF p.6. The Salesforce Account distributor flag is the system-of-record for partner classification — when a new distributor is on-boarded the Account is flagged in Salesforce; the PDF is a point-in-time snapshot.*

### 17.2 LAR (Latin America Region) Distributor Partners

| # | Distributor name |
|---|---|
| 1 | AQTK Peru S.A. |
| 2 | AQTK S.A. |
| 3 | Complementos Electrónicos S.A. |
| 4 | Element14 S. de R.L. de C.V. |
| 5 | Grupo Prod&Khym, S.A. |
| 6 | Hi-Tech Automatización S.A.S |
| 7 | INCAL Comércio, Importação e Exportação de Instrumentos Ltda. |
| 8 | Inceleris S. de R.L. de C.V. |
| 9 | Interlatin S. de R.L. de C.V. |
| 10 | JMD Produtos Eletrônicos Ltda. |
| 11 | Karimex Componentes Eletrónicos Ltda |
| 12 | Negenex SAS |
| 13 | Nextest Instrumentos e Sistemas Ltda |
| 14 | OHMINI Comercio, Importação e Exportação de Produtos Ltda — EPP |
| 15 | Precision Solutions |
| 16 | Q Wire Inc. |
| 17 | Q-Wire Technologies Inc. |
| 18 | RCBI Instrumentos Ltda. |
| 19 | Servicios Técnicos de Ingeniería S.A. de C.V. |
| 20 | Tecnología y Electrónica S.A. |
| 21 | TestEquity de México S. de R.L. de C.V |

*Note: 21 distinct LAR distributors enumerated verbatim from Sales PO PDF p.6–7.*

### 17.3 Maintenance and authority

The distributor lists in the Sales PO PDF are a **point-in-time snapshot** from the POC phase. The authoritative source for partner classification is the Salesforce **Account** record's distributor flag (or equivalent partner-type custom field). When a new distributor is on-boarded or a name change occurs, the Salesforce record is updated; the PDF is not the system-of-record.

---

## 18. Magic SKUs

Three Salesforce **Product** records have special-routing semantics; they appear on the Product Interest field of a CCC and steer the assignment logic. Source: `Sales PO Std Process & Change order (1).pdf`, p.5 (`CUSTOM PRODUCT`), p.8 (`SOWDUMMY`, `EXPORTDUMMY`).

| Magic SKU | When to use | Effect on routing |
|---|---|---|
| **`CUSTOM PRODUCT`** | Used when (a) the customer's SKU does not resolve in Salesforce after **Show More Results** (Sales PO step 12c; ISC WO step 16c), OR (b) a **standard customer is ordering disty product** and you want to **escape the `AMFO_Disty/Rental` queue** (Sales PO PDF p.9, item 3.b). | Routes to a standard CSR rather than the distributor queue. Also flags FE Comments to capture the original model + serial. |
| **`SOWDUMMY`** | Used when the PO is identified as a **Statement of Work** request (SOW key identifiers: `Z*` product #, `"Statement of Work"`, `"Cover Letter"`, `"EID #"`, `"Custom Solutions"`). Sales PO PDF step 12e. | Routes the CCC to the **SOW Team** via Assignment Lookup. |
| **`EXPORTDUMMY`** | Used when the **Final Destination Country is outside the United States** (Sales PO PDF p.8, item 1.a) **or** the destination country is outside USA AND Canada in a Change Order context (Sales PO PDF p.4, item ii.4.a). | Routes the CCC to the **Export Team** via Assignment Lookup. |

### 18.1 Why magic SKUs exist

The magic-SKU pattern is an in-band routing signal: it lets a single Salesforce field (the Product Interest) carry **both** the commercial intent of the PO and the operational routing decision. This is faster than maintaining a separate routing-rules table per CCC — the operator picks the right "product" and the downstream Assignment Lookup does the rest.

### 18.2 Operational consequences

Because the magic-SKU mechanism is a single dropdown choice, every operator must know the three magic SKUs and the conditions for each. Errors here are silent — picking `CUSTOM PRODUCT` instead of `SOWDUMMY` will mis-route an SOW PO into the standard CSR queue with no system warning. The operational rule book (§20) and the existing-CCC matrix (§16) provide guardrails, but the choice itself is operator-driven and unaudited at the Salesforce-form level.

---

## 19. Routing matrix

The end-state of every successfully classified email is one of a small set of downstream destinations. This section consolidates the routing rules from the Sales PO CCC Request Assignment narrative (Sales PO PDF p.8–9), the ISC WO CCC Request Assignment narrative (`ISC WO RTK.txt`, ISC WO CCC Request Assignment section), the six pre-AI Outlook rules (§7.1), the operational rule book (§20), and the magic-SKU and disty-list interactions.

### 19.1 Top-level routing destinations

| Destination | Trigger conditions |
|---|---|
| **Undeliverable Outlook folder** | Outlook Rule 1 matches (mailer-daemon / noreply / specific subjects). |
| **Out of Office Outlook folder** | Outlook Rule 6 matches AND no actionable directive in body (Rule 9 in §20). |
| **`keysightorders@keysight.com`** (KSO) | Outlook Rule 2 matches (govt / defence domains or body keywords). Original deleted. |
| **`collections.pdl-americas@keysight.com` + `usar_keysight@keysight.com`** | Outlook Rule 3 matches (Remittance / Payment Advice / ACH / banking subjects). Original archived. |
| **`portal-admin.pdl-ccc-americas@keysight.com`** | Outlook Rule 4 matches (Password / verification code / validation code). Copy saved in inbox. |
| **`lar_orders@keysight.com`** | Outlook Rule 5 matches (sender = `keysight.bra-tax@tmf-group.com`). Original archived. |
| **`AMFO_Disty/Rental` queue** | (a) Account is on US / CA or LAR distributor list (§17); (b) eBiz / KRS / Keysight Used Equipment Store sender; (c) by default for distributor-flagged accounts. |
| **SOW Team queue** (via `SOWDUMMY`) | PO contains `Z*` SKU, `"Statement of Work"`, `"Cover Letter"`, `"EID #"`, or `"Custom Solutions"`. |
| **Export Team queue** (via `EXPORTDUMMY`) | Final Destination Country outside US (Sales PO PDF p.8) or outside US / Canada (Change Order). |
| **Standard CSR queue** | Default — domestic standard order. |
| **SOM Track CSR queue** | ISC WO RTK CCC Requests after WO creation (§§10–11). |
| **S+R Track CSR queue** | Service Contracts CCC Requests (§13). |
| **Post Order Booking Track / Sales Order Owner or Direct Inquiries** | SSD Change and other Trade Order Modification subtypes (§14). |
| **Superuser** | Auto-assignment fails (`ISC WO RTK.txt` Assignment step 3) — exception handling path. |
| **FE / CSR named owner** | Email body explicitly instructs routing to a specific person (`ISC WO RTK.txt` Assignment step 5 — FE / CSR override). |
| **Restricted handling team** | KSO emails further screened by **citizenship attribute** of the recipient operator — non-US-citizen operators must not read government emails; route to a dedicated box (Q&A transcript 2026-05-08 §9.7). |

### 19.2 Sales PO CCC Request Assignment — verbatim narrative

Source: `Sales PO Std Process & Change order (1).pdf`, p.8–9. The original document labels this section "Agent #3"; that label is dropped here — the work is performed by the FCNV operator clicking Assign and applying the Assignment Lookup tool.

> "As an FCNV user, after the CCC Request transaction is created, I want to assign it so that it gets to the appropriate next destination." (Sales PO PDF, p.8)

**Step 1 — Auto-assign.** If the pending CCC's status = `New`, Type = `Order Request`, Ship-to Address matching the customer's email / PDF → click **Assign** in Salesforce.

- **1a — Non-US destination:** If the Final Destination Country is not the US, manually assign the CCC Request to the **Export Team** via Assignment Lookup using `EXPORTDUMMY` product.
- **1b — Bill-to ≠ Ship-to:** When the Bill-to and Ship-to accounts are different entities, route the CCC using the Assignment Lookup tool with the **Ship-to** address while the Address / Account on the CCC remains the **Bill-to** entity. Procedure:
  1. From the object dropdown, select **Assignment Lookup**.
  2. Populate the **Ship-to Account name**; select the matching account using City + State.
  3. Add the **Product**:
     - Export scenario → `EXPORTDUMMY`.
     - SOW order → `SOWDUMMY`.
     - Other request → standard model from the Product Interest tab.
  4. Type = `Order Request` → click search.
  5. Select the CSR's name reflected against the Sales Order field.
  6. Copy the first & last name of the CSR; update the CCC owner from the creator to the CSR's name.
  7. Verify the CCC status is `Assigned`.

**Step 2 — Superuser fallback.** If the CCC is not assigned, refer to Superuser for exception handling.

**Step 3 — Routing exceptions:**

- **3a — Disty partners:** Follow automatic assignment. These auto-assign to the **`AMFO_Disty/Rental`** queue when the distributor account is selected on the CCC.
- **3b — Standard customers ordering disty products:** If a non-disty customer's CCC auto-assigns to the `AMFO_Disty/Rental` queue, return to the **Product Interest** hyperlink:
  1. Click **New**.
  2. Add `"CUSTOM PRODUCT"` and check the **Primary Product** checkbox.
  3. Return to the main CCC page and click **Assign**.
  4. The CCC should now route to a CSR, not to `AMFO_Disty/Rental`.
- **3c — eBiz / KRS / Keysight Used Equipment Store:**
  1. No process difference — only different assignment.
  2. These should be assigned to the **`AMFO_Disty/Rental`** queue.
  3. Click the edit icon in the **Owner** field.
  4. Change the blue person icon to the **queue** via the dropdown.
  5. Type `"AMFO_Disty/Rental"` in the search bar and click **Change Owner**.

**Step 4 — Archive.** Populate the CCC Request # into the subject of the email and archive.

### 19.3 Routing decision tree (consolidated)

```
Inbound email
  ├─ Outlook Rule 1 matches → Undeliverable folder
  ├─ Outlook Rule 6 matches (no directive) → Out of Office folder
  ├─ Outlook Rule 2 matches → keysightorders@keysight.com (KSO; delete original)
  ├─ Outlook Rule 5 matches → lar_orders@keysight.com (Brazil Tax; archive)
  ├─ Outlook Rule 4 matches → portal-admin.pdl-ccc-americas@keysight.com (copy in inbox)
  ├─ Outlook Rule 3 matches → collections.pdl-americas@keysight.com + usar_keysight@ (archive)
  │
  ↓ (no Outlook rule fires)
Human classification (FCNV operator)
  ├─ KSO body / domain keyword (Rule book preamble) → KSO redirect
  ├─ ISC WO keywords (Repair / Calibration / RMA / WO) → ISC folder → Use Cases 3–5
  ├─ Sales PO keywords (PO / Sales Order / Quote 888 / etc.) → Sales PO folder → Use Cases 1, 2, 6, 7
  └─ Otherwise → Others folder → ad-hoc CSR handling

CCC Request produced → CCC Request assignment:
  ├─ FE / CSR explicit routing instruction in email body → named owner (highest priority)
  ├─ Final Destination Country ≠ US → Export Team via EXPORTDUMMY
  ├─ SOW indicators (Z*, EID, SOW, Cover Letter) → SOW Team via SOWDUMMY
  ├─ Distributor account (US / CA or LAR) OR eBiz → AMFO_Disty/Rental queue
  ├─ Bill-to ≠ Ship-to → Assignment Lookup on Ship-to → CSR by ship-to City + State
  ├─ Standard customer ordering disty product → CUSTOM PRODUCT escape → CSR
  └─ Otherwise → default CSR queue based on region

If auto-assign fails → Superuser exception handling
```

### 19.4 Region-aware overlays

Per Q&A transcript 2026-05-08 §9.2, the four primary lanes (AMS / EMEA / APAC / JP) each carry region-specific overrides that the FCNV operator applies on top of the routing matrix:

- **Japan (JP):** Additional CCC fields are mandatory (specific Japan-only data points captured during the call).
- **APAC (non-JP):** Generally follows global standardised process with country-specific shipping rules.
- **EMEA:** Includes Brazil-tax forwarding (LAR overlap) and EU-specific export controls.
- **AMS:** The default lane; US-domestic and US / Canada-Distributor routing operate on the standard matrix.

Global standardisation is a **direction of travel** rather than a current reality. Region-specific rule packs are maintained and documented; they apply per intake mailbox today.

### 19.5 Citizenship-based KSO routing

Per Q&A transcript 2026-05-08 §9.7: government and defence-prime customer emails arrive at the same shared inboxes as commercial mail. The Outlook KSO rule pre-filters domain / keyword matches and redirects to `keysightorders@keysight.com`. However, an FCNV operator's **citizenship attribute** determines whether they may read certain restricted emails — a non-US-citizen operator must hand off any KSO-related email to a dedicated team box. Today this hand-off relies on operator self-discipline; there is no automated citizenship-based routing.

---

## 20. Operational decision rule book

Source: `Agents/KS FO Agent.json`, step "Checking Override" — system_prompt field, 25,375 characters total. The original document refers to this as the "override prompt" applied after a first-pass classifier. **In current operations, this is the institutional decision logic the FCNV operator applies when classifying.** It is not running as an automated layer today; it lives in operator training, peer review, and the FCNV team's working practice. This section enumerates every rule in the source document verbatim, in original order.

The rule list as exported is numbered 1, 2, 3, 3A, 4, 5, 6, 6A, 7, 8, 9, 9A, 10, 11, 12, 13, 14, 15, 17, 18A, 18B, 19, 19A, 20, 21, 21A, 22, 23, 24, 25, 26 — **Rule 16 is absent from the source document** (a gap in the original Keysight specification that has propagated through the POC implementation; this SOP retains the original numbering for traceability).

### 20.0 Preamble — three top-level absolutes

**KSO Supremacy (verbatim):**
> "If the standard classification says the email as KSO and has relevant keywords then it should be a KSO, No matter what's the context in email and if it's matching with any other rule, it should be a KSO."

KSO is a hard-overrides-all category. Compliance / export-control concerns trump every other classification consideration.

**Absolute Filter (verbatim):**
> "Always start classification from the first (latest) message in the `body` array and Ignore All Empty Body Messages and read FULL EMAIL THREAD. DO NOT classify email to OTHERS if the latest messages are empty forwards. (Non-Negotiable)"

An "empty or non-meaningful message" is defined as one that contains **only**:
1. `From:`, `To:`, `Subject:` headers.
2. CAUTION banners, email disclaimers, system notices.
3. No actual message body, business text, or request before the first visible `From:`.

The filter walks the thread newest-first and skips empty fragments until valid content is found.

**Internal Keysight-to-Keysight Override (verbatim):**
> If the latest valid message is sent **from** a `@keysight.com` email, AND all `To:` recipients are also `@keysight.com`, AND the `To:` list does **not** include `keysight.ai-front-office@keysight.com` → override classification to `OTHERS`.

Rationale: internal Keysight discussions do not require CCC action; they are catch-all unless explicitly routed to the AI front-office mailbox.

**Definition of Valid Content (8 categories):**
1. **User-written business actions** — direct instructions ("Please process the attached PO"), transaction initiation / confirmation, clarifications / approvals / replies requiring action, questions implying business intent.
2. **Business inquiries** — PO / WO status checks, invoicing / payment / bank queries, requests for PO release / tax certificates / delivery follow-ups.
3. **Actionable auto-replies** — auto-responses containing commercial intent (quote request, order confirmation); OOO emails with business context or instructions.
4. **Undeliverable / bounce-back messages** from valid sources (`noreply@keysight.com`, `mailer-daemon`).
5. **Portal-generated or system-generated messages** with relevant transactional or service-related data.
6. **Forwarded blocks containing structured data** — Work Order numbers, model details, calibration info. Valid **only if** no user-written message with clear intent is present later in the thread.
7. **Scope change / service adjustment requests** — "Please provide a 30-day extension".
8. **Auto-reply emails with business context.**

A message is **not** valid if it includes only headers, banners, disclaimers, system warnings, signatures, empty forwards, generic phrases ("Thanks"), or quoted threads without additional input.

### 20.1 Rule 1 — Generic or Context-Free Latest Message

If the latest message contains only generic phrases — `"For your information"`, `"FYI"`, `"Just a reminder"`, `"Please check below"`, `"See previous message"`, `"Check earlier email"`, `"Sharing for visibility"`, `"Per our earlier discussion"`, `"Looping you in"`, `"Forwarding for reference"` — **do not immediately classify as OTHERS.** Evaluate previous messages in the thread. Apply classification based on the most recent message with valid content. If no valid content anywhere in the thread → `OTHERS`.

### 20.2 Rule 2 — Empty Forward with No Meaningful Content

If the latest message is just forwarding headers + banners + quoted older content → skip and evaluate the next message. Do not classify to `OTHERS` solely because the message is an empty forward; continue scanning until valid content is found.

### 20.3 Rule 3 — Purchase Order + WO Conflict

If `"Purchase Order"` or `"PO"` appears with any of `WO`, `Work Order`, `Repair`, `Calibration` → classify as **`ISC_WO_RTK`**, not `SALES_PO`. (Service supersedes sales when both keywords are present.)

### 20.4 Rule 3A — PO + Calibration = SALES_PO (New Equipment Purchase)

This rule applies when **calibration is bundled with a new unit**, not for repair / service work. Classify as `SALES_PO` if the latest valid message includes **all** of:
- A valid Purchase Order reference (`PO#`, `Purchase Order`, `Sales Order`).
- Calibration terms — `"calibration"`, `"factory calibration"`, `"cal data"`, `"cal cert"`, `"with calibration"`, `"calibration before shipment"`.
- Does **NOT** include service-related keywords — `WO`, `Work Order`, `Repair`, `Service Request`, `RMA`, `Recalibration`, `Service Contract #`.

Also classify as `SALES_PO` if it is a **Stock Rotation Request** with Model#/Serial#/Original PO#/RMA.

### 20.5 Rule 4 — Payment Info Only in Footers

If payment terms or remittance info appears only in footers, disclaimers, or email signatures → **ignore** for `COLLECTIONS` classification.

### 20.6 Rule 5 — Actionable Auto-Replies

If an auto-reply contains actionable content (quote request, order placement) → do **NOT** classify as `AUTO_REPLY`. Apply the relevant business category.

### 20.7 Rule 6 — Sender-Based UNDELIVERABLE

If the latest `senderEmail` is exactly `noreply@keysight.com` or `mailer-daemon` → classify as `UNDELIVERABLE`. Do **NOT** use quoted addresses in forwarded threads. If the latest non-empty body suggests undeliverable but sender is neither of those → still classify as `UNDELIVERABLE`.

### 20.8 Rule 6A — Undeliverable Override (Mailer-Daemon Bounce)

If the latest non-empty message is from a known mailer-daemon or delivery-system address (e.g., `mailer-daemon@*`, `Mail Delivery System`, `postmaster@*`), AND contains a bounce notification, AND there is no new user-written content → classify as `UNDELIVERABLE`.

### 20.9 Rule 7 — Generic/Greeting Phrases → OTHERS

If the latest message contains only short phrases like `"Hello"`, `"Thanks"`, `"Noted"`, `"Test"` → skip and examine earlier messages. Do **NOT** classify as `OTHERS` if an earlier message is valid content.

### 20.10 Rule 8 — SALES_PO Follow-Up Without Intent

If a thread was previously `SALES_PO` but the latest message contains only `"Please check this"`, `"We're still waiting"`, `"Reminder"` → reclassify as `OTHERS`.

### 20.11 Rule 9 — Actionable Auto-Reply Detection (AUTO_REPLY)

Focus on the **last non-empty body**. Classify as `AUTO_REPLY` if:
- Subject contains (case-insensitive): `"Auto reply"` · `"Automatic Reply"` · `"Out of Office"` · `"Auto-responder"`, OR
- Last non-empty body contains (case-insensitive): `"Thank you for contacting"` · `"We appreciate your inquiry"` · `"We are actively working on your request"` · `"For urgent inquiries please contact"` · `"This is an automated response"` · `"Your message has been received"` · `"We will get back to you shortly"` · `"I am no longer with"` · `"No longer with the company"` · `"Please contact"` · `"Kindly reach out to"` · `"You may reach"`

AND there is no actionable user-written content (questions, new requests, PO/WO/Repair instructions, commercial intent). If the message only contains generic terms → `OTHERS`, **not** `AUTO_REPLY`. Sender need not be `noreply@` or `mailer-daemon`. Note: an auto-reply may appear non-actionable but **must** still be tagged `AUTO_REPLY`.

### 20.12 Rule 9A — Auto-Reply Subject with Only Empty Forwards

If the subject contains auto-reply indicators, the latest non-empty body contains a typical auto-reply, AND all other messages are empty / quoted / forwarded-only → override to `AUTO_REPLY`.

### 20.13 Rule 10 — Email Thread Parsing Logic

Use `"From:"` to segment threads. Treat any content before the first `"From:"` as the latest message. If no actual content exists (only HTML or system headers), skip it.

### 20.14 Rule 11 — Invoicing / Payment Follow-Up

If the message contains an invoice number, payment, or bank follow-up → classify as `COLLECTIONS`.

### 20.15 Rule 12 — PO Release / Tax Cert Requests

If the email asks for PO form release, tax certificate, or general PO status → classify as `OTHERS`.

### 20.16 Rule 13 — ISC_WO_RTK Unrelated Conversation

If the email includes ISC_WO_RTK keywords but content is only about a status check, service delay, or agreement discussion → reclassify as `OTHERS`.

### 20.17 Rule 14 — JSON Sender Only

Always use `senderEmail` from the JSON input. Do **NOT** use `"From:"` text in the HTML content for classification logic.

### 20.18 Rule 15 — Ignore Embedded "From:" for Sender Logic

Ignore quoted / forwarded `"From:"` inside the body when determining sender. Use JSON field only.

### 20.19 *(Rule 16 is missing from the source document.)*

### 20.20 Rule 17 — Agreement or Controller Status Discussion

If the latest message discusses the status / settlement of an agreement, a controller hold-up due to legal / contract, or `"Did we settle this?"` questions → classify as `OTHERS`, regardless of older WO/PO mentions.

### 20.21 Rule 18A — PO Clarification Within Active Transaction → Retain SALES_PO

If a valid PO is attached or referenced, AND the vendor has already acknowledged or responded to the PO with a quote / pricing change / replacement model, AND the latest message contains clarifying questions directly related to the PO or the quoted transaction (model availability, options on the quote, pricing validation), AND there is no change in business context → **retain `SALES_PO`**. These are transactional follow-ups, not passive inquiries.

However, if the questions are general / not tied to any attached or acknowledged PO, OR the message contains vague context-free phrases like `"Can you confirm availability?"`, `"Do you carry this item?"`, `"What is your price for X?"`, `"Any update?"`, `"Is this order shipped?"`, `"Sales Order Acknowledgement"`, `"If the thread contains a Sales Order Acknowledgement"` — without referencing a valid attached PO or quote → override to `OTHERS` (Rule 18 / 19).

Do not trigger if the PO is only present in an acknowledgement attachment, or all corrective language ("wrong model", "return", "expedite") comes from a reply / internal acknowledgment. In such cases defer to Rule 25 → `OTHERS` unless the sender explicitly instructs a CCC action.

### 20.22 Rule 18B (Pre-Check) — Clarification Inside Acknowledged PO Thread → DO NOT OVERRIDE

If a valid PO is attached or mentioned, AND a sales acknowledgment / transactional response already exists in the same thread (quote sent, PO replacement offered, pricing confirmation), AND the latest message contains only follow-up questions / clarifications directly related to the PO or quote acknowledged earlier → **DO NOT override `SALES_PO`** even if the message lacks an explicit instruction. **This guard condition takes precedence over Rule 19.**

### 20.23 Rule 19 — PO Mentions Without Directive → OTHERS

If the latest message includes PO-related keywords (`PO`, `Purchase Order`, `Sales Order`, `Quote`) but:
- Does not include any clear directive ("please process", "release", "update", "ship", "cancel", "reschedule", "find attached copy of PO"), AND
- Only contains vague / passive questions ("can you check?", "is this okay?", "any update?", "is it discontinued?", "does the quote include X?", "Can I have contracts approval?")

→ Override to `OTHERS`.

**Exception (Rule 19):** If the latest or further valid message includes any request to cancel, modify, or remove specific line items in a referenced or attached PO (e.g., "please cancel line 2 and 4", "remove this model from PO", "change quantity on line item") → still a valid PO request. Retain `SALES_PO` (or override to `SALES_PO` if previously misclassified).

### 20.24 Rule 19A — Credit Card Purchase Without PO → OTHERS

If the latest message contains commercial intent to buy using a credit card ("I want", "charge my CC", "bill / ship to address") but does **NOT** contain a valid Purchase Order number → classify as `OTHERS`. This avoids misclassifying incomplete transactions Salesforce CCC cannot process due to missing PO fields.

### 20.25 Rule 20 — Avoid ISC_WO_RTK if PO/WO Mention Lacks Clear Intent

If the latest message contains `PO`, `WO`, `Work Order`, `Repair`, or `Calibration` BUT:
- It is a passive inquiry ("Please confirm", "Is this scheduled?", "Can you check status?"), OR
- Lacks a directive to initiate / modify a work order or repair request

→ Override to `OTHERS`, regardless of ISC_WO_RTK keyword presence in prior messages or subject.

**Exception (Rule 20):** Retain `ISC_WO_RTK` (or `SALES_PO` if PO-based) for clear requests for extension, cancellation, change of scope, where to send repair for purchased PO, or rescheduling (e.g., "May I please obtain a 30 day extension?"); OR a question about where to send a unit for repair tied to a valid PO/WO.

### 20.26 Rule 21 — Portal Verification or Login Emails → PORTAL_ADMIN

If the email contains structured system-generated content indicating login, account access, or identity verification — a numeric / alphanumeric code string with context (verification, login, OTP, authentication, one-time password); sentences indicating time-bound usage ("valid for 10 minutes", "expires in 600 seconds"); portal / account access or setup — even mixed with banners / disclaimers / legal warnings → classify as `PORTAL_ADMIN`. Do not rely on sender domain or subject alone — match based on intent and structured pattern in the body.

### 20.27 Rule 21A — Payment Verification Override for PORTAL_ADMIN

If the email contains structured system-generated content **but the context is payment verification, bank account validation, ACH test deposit, or payment-method onboarding** → do **NOT** classify as `PORTAL_ADMIN`. Evaluate against `COLLECTIONS` (Rule 5 / 11). If it matches "test deposit", "ACH setup", "account verification for payments", "bank confirmation" → classify as `COLLECTIONS`. Only `OTHERS` if it fails both.

### 20.28 Rule 22 — Skip Empty Sender Bias

If the latest sender's messages are all empty AND a valid business message (including auto-reply or system-generated response) exists earlier — use that message for classification, even if from a different sender. The Absolute Filter takes precedence over sender continuity.

### 20.29 Rule 23 — Cancellation or Modification Requests

If the email contains explicit **cancellation**, **modification**, or **change of scope** to a PO or Work Order (e.g., "cancel this PO", "please remove line 3", "change quantity to 2", "exception of line 6") → do **NOT** classify as `OTHERS`. Instead:
- PO-related cancellation / change → `SALES_PO`.
- WO / Repair-related cancellation / change → `ISC_WO_RTK`.

Cancellations and modifications still require action under the original business context.

### 20.30 Rule 24 — Post-Service Certificate Requests → OTHERS

If the latest message (or entire thread) requests a calibration certificate, service report, or documentation, AND does not include any directive to initiate / reschedule / modify a Work Order, AND refers only to retrieving documents after service is complete ("Please share the calibration certificate", "Can you send us the service report?", "Requesting previous calibration data", "We need the certificate for our records") → override to `OTHERS`. Do not classify as `ISC_WO_RTK` even if the email references WO/RMA or model/serial numbers — unless there is a clear service-related action required.

### 20.31 Rule 25 — Acknowledgement-Only Threads → OTHERS (with Attachment Check)

If the email thread contains only Sales Order Acknowledgements ("Thank you for your order", "Your PO has been received"), files named `"Sales Order Acknowledgement"` / `"SO Acknowledgement"` / `"Acknowledgement"`, OR mentions of quote numbers, model numbers, internal corrections; AND the thread does NOT contain a valid Purchase Order explicitly provided by the sender, does NOT include a directive ("please process", "ship", "replace", "cancel", "update PO"), and contains no sender-initiated CCC request tied to the PO / quote / product → override to `OTHERS`.

**Additional guard:** If the only place a PO number appears is inside an acknowledgement attachment, inside a quoted trail, or as part of system-generated confirmation text → do **NOT** consider it a valid PO reference for Rule 18 / 23.

**Implementation requirement:** Scan attachment file names and headers for terms like "Acknowledgement" or "Sales Order Acknowledgement". If such files are present and no directive is found in the thread, suppress PO-related override rules (including Rules 18A, 18B, 23).

Do **NOT** override to `OTHERS` if the sender provides a valid PO in a directive (body or attachment), or a CCC-relevant business action is present (RMA, expedite, revise quote tied to PO).

### 20.32 Rule 26 — Early Override to Classify as Others

If sender domain is `keysight.com` AND (subject OR body contains: `"Sales Order Acknowledgement"`, `"Order Confirmation"`, `"Order Acknowledgement"`, `"Contract approval"`, `"Revenue approval"`, `"Approval needed"`, `"Approval to book"`, `"Booking the attached PO"`) AND email content indicates either:
- An acknowledgment or confirmation of a purchase order, OR
- An internal request or instruction related to vendor / internal teams (e.g., "Please issue the following permanent licenses as soon as possible", "Can I have contracts approval to book the attached PO")

→ classify as `OTHERS`.

### 20.33 Output schema and re-evaluation

In its current home as an LLM prompt, the rule book emits a structured decision:

```json
{
  "override_triggered": true | false,
  "category": "CATEGORY_IN_CAPS",
  "keywords": ["...exact terms matched from rules..."],
  "reason": "Brief description of which rule caused override"
}
```

The prompt's closing instruction is a final re-evaluation pass: *"Finally, re-evaluate the classification to ensure all rules have been applied correctly and no valid business content or Valid Content has been overlooked."* For the human operator, the equivalent is a sanity-check read-through of the chosen classification before moving the email to its folder.

---

## 21. Confidence and accuracy expectations

### 21.1 The 4-gate confidence model

Source: RFP Q&A call, 2026-05-08, captured verbatim in `HANDOVER.md` §9.1. Keysight defines per-transaction confidence as **four independent gates**, not a single weighted score:

| Gate | Question answered | Pass criterion |
|---|---|---|
| **Gate 1 — Classification** | Did the operator identify the intent correctly? (PO vs WO vs SO status vs etc.) | Class matches the human-expected label. |
| **Gate 2 — Extraction** | Did the operator extract every required field per intent schema? (PO#, model, serial, ship-to, dollar amount, etc.) | All schema-mandated fields populated and validated. |
| **Gate 3 — Entity Resolution** | Did the operator find the matching Salesforce record? | **Binary** — found-or-not-found. |
| **Gate 4 — Action Feasibility** | Can the downstream action actually execute with the data resolved? | All Salesforce form requirements satisfiable. |

The composite confidence is taken as the **minimum** of the four gates; the lowest gate is the "tier driver" — the reason a transaction is held for human review rather than passed through. A low Gate-2 (missing fields) routes to review even if Gate-1 (classification) is 100%.

> "Accuracy is important to continue the rest of the process. If the accuracy is not there, then we have to do a human look-in." (Senthil, Keysight, Q&A 2026-05-08)

The scope of confidence is **per-transaction**, not historical / population-level. Each email's gates are scored on the data inside that email — not on past accuracy of similar emails.

### 21.2 How the 4 gates manifest in current operations

Today, the FCNV operator does the equivalent of these four gates implicitly — they are enforced by a combination of Salesforce form validation and operator self-check:

| 4-gate | Current FCNV behaviour |
|---|---|
| Gate 1 — Classification | Read email, decide ISC vs Sales PO vs Others vs KSO etc. (§7) |
| Gate 2 — Extraction | Open attachments; copy PO#, Model, Serial, Ship-to, dollar amount (§§8, 10 — CCC creation flows) |
| Gate 3 — Entity Resolution | Salesforce global-search by sender email / PO# / WO#; click into Customer Contact / Opportunity / CCC (§§8.2 Step 3; §10.3) |
| Gate 4 — Action Feasibility | Salesforce CCC form-validation when clicking Save (mandatory fields, currency match, country populated); Assignment Lookup search match (§§19.2) |

Gate 4 failures today manifest as "the Assign button does not work" → step 3 of the Assignment narrative → Superuser fallback. Gate 3 failures manifest as "the customer does not exist in Salesforce yet" → trigger account-creation sub-flow (`ISC WO RTK.txt`, step 8e). Gate 2 failures manifest as "the PO has no dollar amount and we cannot save the CCC".

### 21.3 The 109-email accuracy benchmark

Source: `FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx`, Accuracy Report sheet. This is the operational accuracy benchmark Keysight uses to define "good enough" for the first-pass classifier (i.e., Gate 1 only).

| Metric | Value |
|---|---|
| Total emails processed | **109** |
| Initial passed (first attempt) | **62** |
| Initial failed | **47** |
| Initial accuracy | **56.88%** |
| Post-fix passed (of the 47 failed) | **41** |
| Still failed after fixes | **5** |
| Post-fix recovery rate | **≈87%** on previously failing emails |
| Implied combined post-fix accuracy | **(62 + 41) / 109 = 94.5%** (the cited "96% post-fix accuracy" is an internal Keysight rounding of this figure including operator interventions) |

The 5 still-failed cases were all driven by **attachment-handling failures**: Outlook `.msg` items embedded as attachments (forwarded chains-as-attachments), `.gif` images, and combinations thereof. Filenames-too-long and destination-path-too-long also appear in the failure list. The sheet "Non-supported Attachments" in the comparison report enumerates 46 specific examples.

### 21.4 Implications for SLA and CSR escalation

Gate 1 accuracy below ~95% creates a measurable manual-review burden. Gates 2–4 today are gated by Salesforce form-validation: an operator cannot Save a CCC without all mandatory fields, so Gate 2 failures self-correct via "re-read the attachment and try again" loops. Gate 3 failures lead to the Account-creation sub-flow (longest single operation in the AS-IS process — ~5 minutes per new Account). Gate 4 failures route to Superuser.

The combined effect is that a single email that fails any gate adds 3–5 minutes of operator time compared with a clean transaction.

---

## 22. Manual baseline today

Source: RFP Q&A call 2026-05-08 §9.9 (verbatim Keysight statements); cross-validated against the Outlook-rules PDF and the operational narratives.

### 22.1 What is automated today

Two automations exist in the current state:

1. **The per-region Outlook rule pack** — six deterministic rules (Undeliverable, KSO redirect, Collections, Portal Admin, Brazil Tax, Auto Reply) configured per mailbox in Exchange admin. Triggers before any human reads the email.
2. **AIOA ("AI Order Automation") — the in-house Keysight tool.** Performs partial PO-data validation on the Trade Order Entry, SOM WO Update, and Service Contracts flows. Flagged items enter the AI OA Fallout queue for human review. AIOA is not a full agent — it does not classify, does not extract from attachments, does not write to Salesforce on its own, and does not draft customer-facing replies.

Boxes labelled "AI Agent" (on the SOM WO Automation diagram) or "AI Reply" (on the WO Status / Inquiry diagram) describe forward-looking augmentation beyond AIOA's current scope.

- **Outlook rule pack:** the six rules captured in §7.1 are the totality of automatic processing performed before a human reads an email. The rule pack varies by region — some regional inboxes have aggressive rule packs covering all six rules plus regional variants; others have almost no rules and rely entirely on the human operator. There is no central rule-management UI; rules are configured per-mailbox by IT in Exchange admin and updated reactively when new patterns emerge.

### 22.2 What is manual today

Everything that survives the Outlook rules — and everything that AIOA does not specifically check — is manual. From RFP Q&A 2026-05-08:

> "Classification is manual today. Validation is manual. Parsing is manual. Some small per-team automations exist (e.g., regional teams have a few Outlook rules for OOO). Validation, parsing, and downstream actions are all manual." (paraphrased from the call; transcript captured in HANDOVER.md §9.9)

The full enumeration of manual work:

| Activity | How it is done today | Operator time per transaction |
|---|---|---|
| Read inbound email + attachments | FCNV operator opens in Outlook, opens each attachment in its native viewer | ~30–60 s |
| Translate non-English content | Manual lookup in Keysight translation knowledge base; or operator with native-language skill | ~30 s — 5 min |
| Classify into 9-class taxonomy | Visual inspection + judgement; experienced operators do this in seconds, juniors take longer | ~10 s — 2 min |
| Apply operational rule book mentally | Operators internalise the rule book over training; consistency varies | embedded in classification |
| Search Salesforce by email / PO # / WO # | Global search bar; multiple tries with different keys | ~30 s — 2 min |
| Decide existing-CCC vs new-CCC | Read existing CCC status; apply matrix from §16 | ~30 s |
| Create Account / Contact when missing | New-Account form → CMD activation request → wait → return → New-Contact form | ~5 min (dominant single-step cost) |
| Create CCC Request | New-CCC form, 8–12 fields | ~2 min |
| Resolve product (Model #) | Search SF Product object; Show More Results; fall back to `CUSTOM PRODUCT` | ~30 s — 2 min |
| Multi-asset clone | Clone CCC per asset; update address per clone | ~1 min per additional asset |
| Attach email file (Docunet, Doc type = FCNV) | Files quick link; Add Files; pick from local disk | ~30 s |
| Add Activity task | Activity tab; Add Task; populate Subject / Status / Comments | ~30 s |
| Assign CCC | Click Assign; verify owner change | ~10 s |
| Archive original email with CCC# in subject | Outlook archive folder; subject edit | ~10 s |

A clean transaction takes ~5–7 minutes operator time. A new-Account transaction takes ~10–12 minutes. A multi-asset ISC WO with 5 assets takes ~12–15 minutes. At 530K emails / year, even before bursts, the manual time aggregates substantially.

### 22.3 What is partially automated

- **Salesforce form validation** prevents Save with missing mandatory fields — a passive Gate-4 enforcement.
- **Salesforce Assignment Lookup** does the routing match once the operator has populated the right fields; it does not classify or extract.
- **Salesforce Chatter** is used to notify CCC owners — this is a manual @-mention action by the operator, but the notification itself is delivered automatically.

### 22.4 What is unautomated entirely

- Translation, classification, extraction, entity resolution, attachment parsing, multi-asset fan-out, operational-rule-book application, FE / CSR routing-instruction detection inside email bodies.
- Outbound communication (Sales Order Acknowledgement, status replies) — drafted by hand or via templated copy / paste.
- Continuous-learning / drift detection — no system today tracks classification accuracy over time; the 109-email corpus (§21.3) is a manual periodic audit.

---

## 23. System integrations

The AS-IS process touches a defined set of enterprise systems. Each has a specific role; none today integrate with each other in the front-office flow except through the human operator.

### 23.1 Salesforce — system of record

- **Single global instance** (Q&A 2026-05-08 §9.4). No multi-region sharding.
- Objects touched by the AS-IS process:
  - **Account** — customer master record.
  - **Contact** — buyer contact under an Account.
  - **Address** — Bill-to / Ship-to with `Bill to` and `Ship to` flags.
  - **Opportunity** — quote-linked sales opportunity.
  - **Quote** — quote document (`888...` prefix).
  - **CCC Request** — the primary front-office output. Custom object with fields: Origin, Received Date, Received Time, Type, Subtype, Status, Stage, Owner, Account, Contact, PO#, Quote Information (Quote#, FE Comments), Product Interests (model + serial joined records), Order Amount, Currency, Final Destination Country, Ship-to Address.
  - **Work Order** — Salesforce object representing a service / repair / calibration task (used in Use Cases 3–5).
  - **Product** — Salesforce Product object including the three magic SKUs.
  - **Files / Docunet** — uploaded email files with `Doc type = FCNV`.
  - **Activity** — completed task on each CCC with Subject `"other"`, Comments `"ISC"` (for ISC) or empty (for Sales PO), Status `"Completed"`.
  - **Chatter** — operator @-mentions to notify CCC owners on status changes.
  - **Assignment Lookup** — Salesforce-side routing tool.
  - **CMD** — Centralised Master Data; the back-office Account activation queue.

### 23.2 Oracle ERP — downstream order system

- **Single global instance** integrated via internal middleware (Q&A 2026-05-08 §9.4 — described as "Web" / integration layer; not specified by name beyond "Oracle ERP"). Holds Orders, Schedules, Holds, Invoices, Shipments.
- The AS-IS front-office process does **not** directly write to Oracle ERP — CSRs do, after FCNV creates the CCC.
- The Oracle EBS Sales Order entry step in the Trade Order Entry flow (§8.2, Step 14) crosses this boundary.

### 23.3 ServiceNow

- Reminder / follow-up workflow approval engine (Q&A 2026-05-08 §9.4). Specifically: change-order approval routing.
- ServiceNow is **out of scope** for any GenAI integration in this project. Keysight handles ServiceNow internally; the front-office process consumes it indirectly when a Change Order requires approval before downstream booking.

### 23.4 Microsoft Outlook (Exchange Online)

- ≈50 mailboxes; per-mailbox Outlook rule packs (the only deterministic automation in the AS-IS process apart from the in-house AIOA tool described in §23.X / Glossary).
- Folder structure per mailbox includes: Inbox, ISC, Sales PO, Others, Undeliverable, Out of Office, Archive, plus the named PDL forwarding destinations.

### 23.5 Governance posture today

- **No enterprise-level agent / data governance layer is in place over the front-office process today.** The work is performed manually by FCNV operators; the only access controls are those native to the underlying enterprise systems (Salesforce RBAC, Outlook mailbox permissions, SharePoint folder ACLs, Oracle ERP roles).
- Per Q&A 2026-05-08 §9.6, Keysight has identified **Microsoft Purview (or a hyperscaler equivalent)** as the **intended future** enterprise-level governance layer for any agent portfolio that gets stood up. Application-level governance for an automated SalesOps workflow — RBAC, SLO definitions, circuit-breaker policies, MCP-tool scanning, prompt-injection prevention — was acknowledged by Keysight in the same call as **"not yet defined"** (paraphrasing Manuj: *"we are not there yet in that journey where we have everything defined there"*).
- Practical implication for the AS-IS: today's controls are the legacy enterprise-system controls, not an agentic-governance toolchain.

### 23.6 SharePoint / Docunet

- Internal document store for customer specifications, calibration history, retained PO copies.
- API-accessible via Microsoft Graph (Q&A 2026-05-08 §9.11).
- "Docunet" is the document-classification overlay invoked at the email-attachment step in every CCC creation flow — every attached email is tagged `Doc type = FCNV` when uploaded.

### 23.7 Keysight Support Portal (KSP)

- Read-only customer self-service portal.
- Referenced by the Portal-Admin Outlook rule (verification codes, password resets) and by the WO Status / Inquiry reply template (§12).

### 23.8 Integration map (current state)

```
[ Customer mailbox ]  →  Outlook (~50 mailboxes)
                                |
                                | (Outlook Rule 1–6 fires automatically)
                                ↓
                          (some emails redirected: KSO, Collections, Portal Admin, Brazil Tax)
                                |
                                ↓
                          [ Human FCNV operator ]
                                |
                                | reads, classifies, extracts
                                ↓
                          [ Salesforce ]
                          ├─ search Account / Contact (by email)
                          ├─ search CCC (by PO/WO)
                          ├─ create / update Account, Contact, CCC, WO
                          ├─ attach email to Files (Docunet)
                          ├─ assign owner (Assignment Lookup)
                          └─ Chatter notification to owner
                                |
                          [ AIOA partial PO validation ]   ← runs in parallel on Trade Order Entry, SOM WO Update, Service Contracts
                                |
                                ↓
                          [ CSR / CTA / SOM / S+R / Post-Order-Booking ]
                          ├─ books order in Oracle ERP (via middleware)
                          ├─ manages holds, schedules
                          ├─ communicates with customer (manual)
                          └─ ServiceNow for Change Order approvals
                                |
                                ↓
                          [ Customer reply / SOA ]
```

The single human operator is the integration glue. Removing any step requires both system access and judgement that today resides only in the operator's head.

---

## 24. Out of scope today

Items explicitly out of scope for the AS-IS front-office process (and for the related RFP). Source: Q&A 2026-05-08 §9.13 (verbatim items), cross-validated with internal `HANDOVER.md`.

| Item | Scope status |
|---|---|
| Building a **new customer-facing portal** | Out of scope. Customers continue to send email and use the existing read-only support portal. |
| Building a **new ServiceNow workflow** | Out of scope. ServiceNow remains Keysight-owned for Change Order approvals and reminder workflows. |
| **Replacing Salesforce or Oracle** | Out of scope. They remain the systems of record. |
| Handling the **classified / government-controlled environment** | Out of scope as a primary destination. KSO emails are **routed** to a dedicated team via the KSO Outlook rule and the operational rule book preamble (§20.0). Beyond that routing, the controlled environment operates as a separate system. |
| **Consumption Billing** subtype | Out of scope per Sales PO PDF p.16 — low volume (4 requests / month). |
| **Real customer-facing email transmission from any automated pipeline** | Out of scope today as a current-state behaviour — the operator drafts and sends manually. |

---

## 25. Pain points and gaps

Derived from the use-case narratives in §§8–14, the RFP volume / governance expectations (§§1, 26), and the Q&A transcript. These are the operational problems the current state creates — the holes a future-state solution would close, but documented here as **AS-IS issues**, not solution descriptions.

### 25.1 Classification pain points

| Pain | Frequency | Operational impact |
|---|---|---|
| Empty / forwarded emails with `FYI`, `Please see below`, no body — operator must walk back through thread to find real content (Rules 1, 2, 22 in §20) | Daily | 30–60 s of judgement per email; inconsistent across operators |
| Outlook `.msg` attachments containing the actual business request | High — leading cause of failed classifications in 109-email corpus | Operator must open `.msg` separately; sometimes mis-classifies based on outer envelope only |
| Acknowledgement-only threads that contain a PO number but no directive (Rule 25 in §20) | Daily | Frequently mis-classified as `SALES_PO` when the correct class is `OTHERS` |
| Generic phrasing ("any update?", "is this okay?") on a PO-related thread (Rule 19 in §20) | Daily | Subjective call; juniors vs seniors disagree |
| Mixed PO + WO content (Rules 3, 3A in §20) — calibration of a new unit vs repair of an existing unit | Common | Wrong classification routes the CCC to the wrong queue (SOW vs CSR vs RTK) |
| Auto-replies that contain actionable content (Rules 5, 9 in §20) | Common | Outlook Rule 6 would discard them; operator must intercept |
| Internal Keysight-to-Keysight discussions ending up in the FCNV mailbox | Common | Rule book preamble must fire to mark as `OTHERS`; otherwise opens a meaningless CCC |
| Government / defence customer emails arriving at a non-government inbox (Q&A 2026-05-08 §9.7) | Compliance-critical | Today an FCNV operator who is a non-US-citizen cannot read the email — but the email is already in their inbox; routing must happen pre-read |

### 25.2 Extraction pain points

| Pain | Frequency | Operational impact |
|---|---|---|
| Multiple ship-to addresses on a single PO; line-level address override (Sales PO PDF p.5, step 9.a.1) | Common | Operator must pick correct address per line, prone to error |
| Bill-to ≠ Ship-to entities — must split Account on CCC vs Assignment Lookup (Sales PO PDF p.3 ii.3) | Common | Multi-step manual routing; if mis-handled, CCC goes to the wrong CSR |
| Quote # not on the email — must Ctrl+F in attachment | Common | Adds time; missed quote linkage hurts downstream reconciliation |
| Multi-asset emails (`ISC WO RTK.txt` step 15a note — "1 CCC per asset, NOT 1 per email") | Daily for service work | Tedious clone-and-edit loops; risk of clone with stale address |
| `.gif`, `.tif`, scanned-image POs | Common | OCR is mental; transcription errors propagate downstream |
| Long filenames / long destination paths in `.msg` attachments | 46 distinct examples in the 109-email corpus | Outright extraction failure; manual workaround |
| Translation when the email body and attachments are in different languages | Common in EMEA / APAC | No central glossary at the operator's workstation today |

### 25.3 Validation / reconciliation pain points

| Pain | Frequency | Operational impact |
|---|---|---|
| PO line items don't match the linked Quote (price, qty, terms) | Common | Today caught only by CSR downstream — adds an email round-trip with customer |
| Customer Account doesn't exist in Salesforce — must trigger CMD activation (`ISC WO RTK.txt` step 8e.5; Sales PO PDF p.5, step 9.d) | Common | ~5 min per new Account; blocks the rest of the transaction |
| Existing CCC with a partial-match PO# (same root, different revision) | Common | Operator must judge whether to clone-as-Change-Order or update existing |
| Cancelled CCC needs new-CCC; Closed CCC needs Change Order clone — easy to confuse (§16) | Frequent | Wrong path creates orphan CCCs |
| AIOA flag interpretation — flags are not always self-explanatory; AIOA validates a narrow set of header fields, not line-level reconciliation | Common | Operator may dismiss a true flag or chase a false one; line-level mismatches still reach the downstream CSR |

### 25.4 Routing pain points

| Pain | Frequency | Operational impact |
|---|---|---|
| FE / CSR override instructions inside the email body (`ISC WO RTK.txt` Assignment step 5) | Common | Operator must read every email body for routing hints, not just for content |
| Standard customer ordering disty product — must apply `CUSTOM PRODUCT` escape (Sales PO PDF p.9, 3.b) | Frequent | Routes to disty queue by default if not caught; needs operator vigilance |
| Magic-SKU selection (`CUSTOM PRODUCT` / `SOWDUMMY` / `EXPORTDUMMY`) — operator-driven; no system warning if wrong | Common | Silent mis-routing |
| Non-US destination country missed → CCC routes to US CSR instead of Export Team | Frequent | Eventually caught by Export Team rejection; adds 1–2 days latency |
| Citizenship-based KSO routing — non-US citizen operator must hand off (Q&A 2026-05-08 §9.7) | Compliance-critical | No automated detection; relies on operator self-identification |
| Multi-mailbox consolidation in transition — operators must work across ≈50 mailboxes today, target 1–2 | Q&A 2026-05-08 §9.3 | Inconsistent rule packs per mailbox; classification accuracy varies by inbox of origin |

### 25.5 Communication pain points

| Pain | Frequency | Operational impact |
|---|---|---|
| Sales Order Acknowledgement (SOA) is drafted manually | Every order | Inconsistent template usage; translation errors |
| Replies in customer language — no central glossary enforcement | Common | Translation quality varies by operator |
| No outbound-thread linkage to inbound — manual subject prefixing | Every transaction | CCC# in subject is operator-typed; typos break thread continuity |
| WO Status / Inquiry replies (§12) are still manual, even though the RFP diagram labels the step as "AI Reply" | Daily | Operator time spent on simple status look-ups |

### 25.6 Volume / SLA pain points

| Pain | Source | Operational impact |
|---|---|---|
| 530K emails / year against a manual baseline | RFP AI.SalesOps Details; Q&A 2026-05-08 §9.8 | Current FCNV team operates at ~7–10 minutes / email average — extrapolated to >60,000 operator-hours / year |
| 80–90 concurrent users at peak — quarter-end / year-end / month-end bursts | Q&A 2026-05-08 §9.8 | Burst days the team falls behind; SLA degrades |
| 100 emails/sec stress-test target | Q&A 2026-05-08 §9.8 | No automated path today can sustain this — must rely on Outlook rules + human throughput |

### 25.7 Governance / compliance pain points

| Pain | Source | Operational impact |
|---|---|---|
| No enterprise-level agent / data governance layer in place for the front-office process; Microsoft Purview is the **stated future intent**, not a current control | Q&A 2026-05-08 §9.6 | Today every operator action is gated only by Salesforce / Outlook / SharePoint RBAC; cross-system governance is not standardised |
| KSO citizenship routing — manual operator self-discipline | Q&A 2026-05-08 §9.7 | Compliance risk if an operator reads a restricted email |
| Translation knowledge base reuse — currently a separate internal asset, not integrated with the FCNV operator's tooling | Q&A 2026-05-08 §9.5 | Each operator does ad-hoc translation lookups |
| No central rule-management UI for Outlook rules — IT updates per-mailbox in Exchange admin | Observed | Rule drift across regions; new patterns take days / weeks to deploy |
| No drift / accuracy telemetry over time — only point-in-time audits like the 109-email corpus | §21.3 | Cannot detect classification degradation early |

---

## 26. Volume and SLA expectations

### 26.1 Headline numbers

| Metric | Value | Source |
|---|---|---|
| Annual inbound email volume | **530,000 / year** | RFP AI.SalesOps Details sheet; verbally confirmed Q&A 2026-05-08 §9.8 |
| Mean rate | ≈14,500 emails / weekday (assuming 5-day operation, 50 work-weeks) | Derived |
| Peak day rate | 2–3× mean during quarter / year / month-end status-check waves | Q&A 2026-05-08 §9.8 |
| Peak concurrent operators | **80–90 across global time zones** | Q&A 2026-05-08 §9.8 |
| Total user pool with system access | **600–700 (CSR + adjacent roles)** | Q&A 2026-05-08 §9.8 |
| Stress-test design target | **100 emails / second sustained** | Q&A 2026-05-08 §9.8 |

### 26.2 Burst pattern

Three predictable bursts per year per region:

- **Quarter-end** — customers ask for status updates on outstanding POs, expedite requests, payment confirmations.
- **Year-end** — calendar-year close; additional Rebate-month activity (Rebates are monthly but accumulate around year-end reconciliation).
- **Month-end** — partner Rebates (5–10 PO transactions per month, per Sales PO PDF p.12) plus standard monthly billing-cycle status queries.

These are predictable; the FCNV team plans capacity around them.

### 26.3 Current operator-time baseline

From the manual-baseline enumeration in §22.2, a typical breakdown of operator time per email class:

| Class | Mean operator time | Notes |
|---|---|---|
| Outlook-rule-handled (UNDELIVERABLE / AUTO_REPLY / BRAZIL_TAX / PORTAL_ADMIN / COLLECTIONS) | ~0 s | Zero-touch — rules execute pre-read |
| Outlook-rule-handled KSO | ~0 s | Same |
| OTHERS (catch-all) | 2–5 min | Read, mark, route to ad-hoc CSR |
| ISC_WO_RTK — single asset | 5–7 min | Standard 22-step flow (§10.3) |
| ISC_WO_RTK — multi-asset (avg 3 assets) | 10–14 min | Multi-asset clone overhead |
| ISC_WO_RTK — Update / Change Order | 6–8 min | Existing-CCC update flow (§11) |
| ISC_WO_RTK — Status / Inquiry | 2–3 min | Look-up + manual reply (§12) |
| SALES_PO — Trade Order Entry standard | 5–7 min | Standard 23-step flow (§8) |
| SALES_PO — with new Account | 10–15 min | CMD activation dominates |
| SALES_PO — Change Order | 7–10 min | Clone + delta-amount math + country / currency validation |
| SALES_PO — Rebate (Excel parsing) | 10–12 min | Open Excel; Trade Credit RMU tab; partner-by-partner |
| SALES_PO — eBiz | 6–8 min | Similar to standard with body-extracted PO# |
| SALES_PO — SOW with EID | 8–10 min | EID lookup; `SOWDUMMY` routing |
| SALES_PO — Stock Rotation | 6–8 min | Quarterly batch handling |
| Service Contract — new agreement | 8–12 min | Complex terms; multi-asset coverage (§13) |
| Trade Order Modification — SSD Change | 4–6 min | Dashboard hand-off (§14) |

### 26.4 SLA expectations

The RFP target — "improving response times from hours to minutes" (AI.SalesOps Details sheet, Executive Summary) — is the explicit goal. Today, customer turnaround is **hours to days** depending on burst pressure, new-Account dependencies, and queue depth.

There is no formal published SLA from FCNV to the customer at the inbound stage; the operative SLA is downstream (CSR responds within 4 working hours, Order Acknowledgement within 24 hours). The FCNV intake time is implicit in those downstream SLAs.

### 26.5 Quality benchmark

The 109-email POC corpus (§21.3) yielded **56.88% initial accuracy** and **~94.5% combined post-fix accuracy** for the first-pass classifier specifically. The RFP requires `>90% classification accuracy with confidence scoring per classification` (AI.SalesOps Details sheet, "Email classification" requirement bullet 3) — i.e., the post-fix benchmark is at the floor of the RFP-stated requirement; initial-pass accuracy is well below.

---

## Appendix A — Document provenance

| Section | Primary source | Page / location |
|---|---|---|
| §1.2 (scale) | RFP — AI.SalesOps Details sheet; Q&A transcript 2026-05-08 §9.8 | Cited verbatim |
| §1.4 (system landscape, including AIOA) | Q&A transcript 2026-05-08 §9.4; RFP `SalesOps - RFP.xlsx` AI.SalesOps Details + use case sheet diagram annotations naming "AIOA AI PO Validation" / "AI OA Fallout" boxes | Cited verbatim |
| §3 (Operational ownership tracks) | RFP — AI.SalesOps Details sheet, eight diagrams | Diagram swim-lane labels |
| §6 (9-class taxonomy) | `Agents/KS FO Agent.json` step "Checking the Context"; `Agents/KS FO Agent.json` step "Checking Override" preamble | system_prompt fields |
| §7.1 (six Outlook rules) | `Current Outlook Rules_Narratives (1).pdf` | pp.1–6 |
| §7.2.1 (ISC sorting) | `ISC WO RTK.txt` | "ISC WO Sorting" section |
| §7.2.2 (Sales PO sorting) | `Sales PO Std Process & Change order (1).pdf` | pp.1–2 |
| §8 (Use case 1 — Trade Order Entry PO Received) | RFP — AI.SalesOps Details sheet, `trade-po-received.png`; `Sales PO Std Process & Change order (1).pdf` pp.2–7 | Diagram + verbatim narrative |
| §9 (Use case 2 — Trade Sales Change Order) | RFP — AI.SalesOps Details sheet, `trade-change-order.png`; Sales PO PDF p.3 (Closed-status clone branch) and p.16 (Change-Order subtypes) | Diagram + verbatim narrative |
| §10 (Use case 3 — SOM WO Automation single / multi-asset) | RFP — AI.SalesOps Details sheet, `som-wo-automation.png`; `ISC WO RTK.txt` ISC WO CCC Request Creation section | Diagram + verbatim narrative |
| §11 (Use case 4 — SOM WO Update / Change Order / Multi-Asset) | RFP — AI.SalesOps Details sheet, `som-wo-update.png`; `ISC WO RTK.txt` step 6a; existing-CCC matrix §16 | Diagram + verbatim narrative |
| §12 (Use case 5 — SOM WO Status / Inquiry) | RFP — AI.SalesOps Details sheet, `wo-status-inquiry.png`; Rule book Rule 13, Rule 20, Rule 24 | Diagram + rule citations |
| §13 (Use case 6 — Service Contracts) | RFP — AI.SalesOps Details sheet, `service-contracts.png` | Diagram swim-lane content |
| §14 (Use case 7 — SSD Change Request) | RFP — AI.SalesOps Details sheet, `ssd-change-request.png` | Diagram swim-lane content |
| §15 (Special subtypes) | `Sales PO Std Process & Change order (1).pdf` | pp.9–16 |
| §16 (Existing-CCC matrix) | `ISC WO RTK.txt` step 6a; `Sales PO Std Process & Change order (1).pdf` p.3 | Both sources |
| §17 (Distributor lists) | `Sales PO Std Process & Change order (1).pdf` | pp.6–7 |
| §18 (Magic SKUs) | `Sales PO Std Process & Change order (1).pdf` | pp.5, 8 |
| §19 (Routing matrix) | `Sales PO Std Process & Change order (1).pdf` CCC Request Assignment (pp.8–9); `Current Outlook Rules_Narratives (1).pdf` Outlook destinations; Q&A 2026-05-08 §9.7 (citizenship routing) | Multiple |
| §20 (Operational rule book) | `Agents/KS FO Agent.json` step "Checking Override" | system_prompt field (25,375 chars) |
| §21 (4-gate confidence) | Q&A transcript 2026-05-08 §9.1; `FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx` Accuracy Report sheet | Cited verbatim |
| §22 (Manual baseline) | Q&A transcript 2026-05-08 §9.9 | Cited verbatim |
| §23 (Integrations) | Q&A transcript 2026-05-08 §§9.4, 9.6, 9.11 | Cited verbatim |
| §24 (Out of scope) | Q&A transcript 2026-05-08 §9.13 | Cited verbatim |
| §26 (Volume / SLA) | RFP AI.SalesOps Details sheet; Q&A transcript 2026-05-08 §9.8 | Cited |
| Appendix B | RFP — AI.SalesOps Details sheet, `rfp-six-stage.png` | RFP six-stage envisioned future flow |

---

## Appendix B — The RFP's envisioned six-stage future flow (TO-BE / RFP vision)

> **This appendix is explicitly TO-BE / RFP-vision, not AS-IS.** It is included here only because the source diagram lives in the same RFP workbook as the seven AS-IS happy-path diagrams referenced in §§8–14, and the reader may otherwise encounter it without context. The body of this SOP describes today's manual operations; the six-stage flow below describes what the RFP author intends the future state to look like.

![RFP's envisioned 6-stage future-state flow](/asis-diagrams/rfp-six-stage.png)

*Source: `SalesOps - RFP.xlsx`, AI.SalesOps Details sheet, "RFP six-stage envisioned future flow" diagram.*

### The six stages, briefly

1. **Stage 1 — Intake & Classification.** Inbound email is received; pre-AI Outlook rules pre-filter terminal classes; remaining emails are classified into the 9-class taxonomy (KSO, ISC_WO_RTK, SALES_PO, Service Contracts, Trade Order Modification, OTHERS, etc.). In the RFP vision, this stage is automated; today it is the manual FCNV operator triage described in §7.
2. **Stage 2 — Data Extraction & Enrichment.** PO# / WO# / Model / Serial / Ship-to / Order Amount / Final Destination Country are extracted from email body and attachments; Salesforce Account / Contact match is performed; cross-system reconciliation (PO vs Quote) is performed. In the RFP vision, this stage is automated; today it is the manual extraction described in §§8–14.
3. **Stage 3 — Decision & Confidence Scoring.** The 4-gate confidence model (§21.1) is applied per transaction; the system decides whether to autonomously execute, present a one-click confirmation, or hold for full human review. In the RFP vision, this stage is automated; today the Salesforce form-validation and operator judgement perform this implicitly.
4. **Stage 4 — Workflow Execution.** The CCC Request is created / updated / cloned / closed in Salesforce; downstream Oracle EBS order is created or modified where applicable; WO records are created and updated. In the RFP vision, the system writes to Salesforce and Oracle; today the FCNV operator and downstream CSR / SOM / S+R operators do these writes.
5. **Stage 5 — Communication & Close-out.** The customer-facing reply (status, SOA, KSP statement, contract acknowledgement) is drafted in the customer's language and sent; the CCC Request is closed. In the RFP vision, drafts are automated and operators approve; today operators draft and send manually.
6. **Stage 6 — Continuous Learning.** Outcomes are recorded; classifier drift is detected; the rule book and the operational rules are updated as patterns evolve. In the RFP vision, this is a closed-loop feedback system; today the 109-email manual audit (§21.3) is the only learning mechanism.

The six-stage diagram represents the RFP author's intent for what the future-state automation should accomplish. Mapping the AS-IS use cases in §§8–14 onto this six-stage flow is the substance of the forthcoming TO-BE Process SOP.

---

*End of AS-IS Process SOP. The companion TO-BE Process SOP — to be produced as a separate deliverable — will map each section above onto the proposed automation, retaining identical section structure to enable side-by-side comparison.*
