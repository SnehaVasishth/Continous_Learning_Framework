# Keysight SalesOps Automation — Solution Overview

*Built on ZBrain · prepared for the Keysight RFP demo · last updated 2026-05-08*

---

## 1. Solution Overview

Keysight SalesOps receives several thousand customer emails per week — purchase orders, quote-to-order conversions, ship-date changes, calibration requests, hold releases, contract renewals, status inquiries, plus the usual inbox noise (newsletters, internal HR, security notifications, phishing attempts). Each one currently lands on a CSR's plate to triage, classify, extract from attachments, look up the customer in CRM, cross-check against the matching quote, decide whether to write the order, draft the customer reply, send it, and close the case in the ticketing system.

This solution automates that end-to-end with a **5-stage agent pipeline** built on the **ZBrain orchestrator** runtime, plus a separate **Continuous Learning dashboard** at `/learning` that operators visit between runs to review aggregated CSR feedback, drift signals, and KB-tuning suggestions. Every stage is an autonomous agent with its own tool belt; every decision is auditable; every business rule is editable from the UI without a code change. The pipeline integrates **live** with Salesforce + Field Service, SharePoint / Google Drive, Oracle ERP, and Gmail IMAP/SMTP — there is no mocked customer data in the production path.

Three customer principles drive the design:

1. **Tiered autonomy, not blind automation.** L4 auto-applies (≥95% confidence), L3 surfaces a one-click approve, L2 routes to full human review. The CSR is always in control of low-confidence work.
2. **Audit-grade transparency.** Every sub-step inside every stage exposes Input → Processing (provider, prompt, KB rules consulted, raw LLM response) → Output. A CSR opening a trace sees exactly why the agent chose `quote_to_order` over `po_intake`, which Salesforce SOQL queries fired, what each business rule evaluated to, and which fields the schema-driven extraction populated.
3. **Configurable without code.** Six Knowledge Base namespaces — intent definitions, extraction schemas, business rules, translation glossary, spam heuristics, language heuristics — are CRUD-able from the Settings UI. Business operations tunes the system; engineering doesn't redeploy.

---

## 2. Scope

### In scope (Phase 1 — RFP MVP)

| Area | Coverage |
|---|---|
| **Languages** | English, Spanish, Japanese — heuristic + LLM dual-detection on every email |
| **Intents (13 canonical)** | `po_intake`, `quote_to_order`, `trade_change_order`, `ssd_change_request`, `hold_release`, `delivery_change`, `service_order`, `wo_update_request`, `wo_status_inquiry`, `service_contract_request`, `general_inquiry`, `out_of_scope`, `spam` |
| **Email channel** | Gmail IMAP inbound (live), SMTP outbound (live, on HITL approval) |
| **Document formats** | PDF (OCR via Azure Document Intelligence), XLSX (openpyxl), DOCX (python-docx with auto-fallback to OCR), PNG/JPEG (Vision OCR) |
| **CRM / Field Service** | Salesforce — Account, Contact, Opportunity, Quote, Order; Field Service Lightning — Asset, ServiceContract, WorkOrder, ServiceAppointment |
| **ERP** | Oracle Fusion Cloud — Items (master SKU catalog), Inventory, AP/AR Invoices, Shipments |
| **Document store** | SharePoint Online (or Google Drive) — inbound attachments + generated SOA / Invoice / WO / Calibration Cert PDFs |
| **HITL** | One-click approve, edit-and-approve, reject; reasons categorized; outbound reply sent on approval |
| **Continuous learning** | Per-stage feedback (👍/👎 + edits) captured; rolling drift detection; suggested-fix LLM corrective drafts on reconciliation mismatches |
| **Knowledge Base UI** | All 6 namespaces editable in Settings — change an intent definition, add a business rule, adjust spam patterns, without redeploying |

### Out of scope (Phase 2 candidates)

- ServiceNow case lifecycle (the Stage 4.4 placeholder in the trace shows where it'd plug in)
- ML-based drift detection (Phase 1 uses rolling-window threshold heuristics)
- Multi-region routing (single region for MVP)
- Voice channel (only email in Phase 1)
- Customer self-service portal (CSR-facing only)

---

## 3. Architecture

> **Image prompt for high-level architecture diagram** *(paste into Midjourney / DALL-E / Stable Diffusion / Flux / Ideogram)*:
>
> *"Clean enterprise software architecture diagram, isometric layered style, white background, ZBrain blue (#1A55F9) accent color. Six horizontal layers stacked top-to-bottom: (1) **User Interface** — React/Vite SPA browser tile labelled 'CSR Console' with sub-icons for Inbox / Trace / HITL / Knowledge Base / Settings. (2) **API Gateway** — FastAPI rectangle with the routes /api/emails, /api/pipelines, /api/hitl, /api/trace, /api/kb, /api/integrations listed inside. (3) **ZBrain Orchestrator** — central rounded box with six small agent chips inside arranged left-to-right labelled '1 Intake', '2 Extract', '3 Decide', '4 Execute', '5 Communicate', '6 Learning', each with a tiny toolbox icon. (4) **Knowledge Base** — a database cylinder labelled 'KB · 6 namespaces' showing intent / extract_schema / business_rules / translation / spam_heuristic / language_heuristic. (5) **External Systems** — five rounded tiles in a row: 'Salesforce + FSL' (cloud icon), 'Oracle Fusion ERP' (cloud icon), 'SharePoint / Google Drive' (folder icon), 'Gmail IMAP/SMTP' (envelope icon), 'AWS Lambda → Azure Document Intelligence' (lambda + Azure icons). (6) **LLM Provider** — single tile 'OpenAI gpt-5.2 · strict JSON schema'. Arrows flow downward from UI through API → Orchestrator → KB / External / LLM. Show one return arrow back from External → Orchestrator → UI labelled 'trace events (SSE)'. Use thin lines, sans-serif font (Inter), no shadows, a few subtle accent dots in ZBrain blue. Title at top: 'Keysight SalesOps — Solution Architecture'."*

### Component map (text fallback while the image is generated)

```
┌────────────────────────────────────────────────────────────────────────┐
│  CSR CONSOLE (React + Vite + Tailwind)                                 │
│  Inbox · Pipelines · Trace · HITL Queue · Knowledge Base · Settings    │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │  HTTPS · SSE for live trace
┌──────────────────────────────▼─────────────────────────────────────────┐
│  FASTAPI · /api/emails · /api/pipelines · /api/hitl · /api/trace       │
│           /api/kb · /api/integrations · /api/email-accounts            │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────────┐
│  ZBRAIN ORCHESTRATOR (agent fabric)                                    │
│  ┌─────────┬─────────┬─────────┬─────────┬─────────────┬─────────────┐ │
│  │ Stage 1 │ Stage 2 │ Stage 3 │ Stage 4 │ Stage 5     │             │ │
│  │ Intake  │ Extract │ Decide  │ Execute │ Communicate │             │ │
│  │ 7 sub   │ 4 sub   │ 4 sub   │ 4 sub   │ 4 sub       │             │ │
│  └────┬────┴────┬────┴────┬────┴────┬────┴──────┬──────┴─────────────┘ │
└───────┼─────────┼─────────┼─────────┼───────────┼─────────────┼────────┘
        ▼         ▼         ▼         ▼           ▼             ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  KNOWLEDGE BASE (6 namespaces, editable from Settings UI)       │
   │  intent · extract_schema · business_rules · translation         │
   │  spam_heuristic · language_heuristic                            │
   └────────────────────────────────────────────────────────────────┘

   ┌─────────────┬───────────────┬─────────────┬──────────────┬─────────────┐
   │ Salesforce  │ Oracle Fusion │ SharePoint /│ Gmail        │ AWS Lambda  │
   │ + Field     │ Cloud ERP     │ Google Drive│ IMAP / SMTP  │ → Azure Doc │
   │ Service     │ (REST/OAuth2) │ (Graph /    │ (live)       │ Intelligence│
   │ (REST/OAuth)│               │  Drive API) │              │             │
   └─────────────┴───────────────┴─────────────┴──────────────┴─────────────┘

   ┌────────────────────────────────────────────────────────────────┐
   │  OPENAI gpt-5.2 · response_format = json_schema (strict mode)  │
   │  used by: classify_intent · detect_language · llm_spam_check   │
   │           translate_to_english · schema_extract                │
   └────────────────────────────────────────────────────────────────┘
```

### Why this shape

- **Agent fabric over monolith.** Each stage is an isolated `BaseAgent` subclass with its own `Tool` belt and a typed `AgentContext`. Stages cannot reach into each other's internals — they communicate by mutating the context. This makes per-stage replacement (swap Stage 5 for a different reply drafter, swap Stage 2 for a different extractor) a one-class change.
- **OpenAI strict JSON Schema for every LLM call.** The earlier Claude-only path was producing schema drift (intent confidence buried inside an `intents[]` array, autonomy-tier values like `L4_auto` landing in `track_hint`). OpenAI's `response_format=json_schema` with `strict: true` rejects malformed output at the API level — no normalizer, no shape ambiguity downstream.
- **KB at request-time, not deploy-time.** Agents read the KB on every invocation. A business operator changing an intent definition or adding a business rule in the Settings UI sees the new behavior on the very next email — no deployment, no engineer in the loop.
- **Salesforce-only customer match.** Stage 2.3 explicitly does *not* fall back to a local DB. If the customer isn't in Salesforce, the pipeline routes to HITL with `unknown_customer_in_salesforce` — surfacing real master-data gaps instead of silently proceeding on stale local copies.

---

## 4. Implementation Approach

### Agent fabric primitives

```
BaseAgent              ←  abstract stage class; declares stage_key + tools list
  ├── Stage1IntakeAgent
  ├── Stage2ExtractAgent
  ├── Stage3DecideAgent
  ├── Stage4ExecuteAgent
  ├── Stage5CommunicateAgent
  └── Stage6LearningAgent

Tool                   ←  abstract tool class; declares name + kb_namespaces
  ├── DetectSpamTool         (Stage 1.2 · regex KB-driven)
  ├── AzureDocIntelligenceTool (Stage 1.3 + 2.1 · format-aware routing)
  ├── DetectLanguageTool      (Stage 1.4 · heuristic + LLM both)
  ├── TranslateTool            (Stage 1.5 · OpenAI strict-JSON)
  ├── LlmSpamCheckTool         (Stage 1.6 · OpenAI strict-JSON)
  ├── ClassifyIntentTool       (Stage 1.7 · OpenAI strict-JSON)
  ├── SchemaExtractTool        (Stage 2.2 · OpenAI strict-JSON, KB schema)
  ├── EntityResolveTool        (Stage 2.3 · Salesforce only)
  ├── SalesforceQueryTool      (Stage 2.4 · intent-aware SOQL)
  ├── BusinessRulesEvalTool    (Stage 3.3 · KB predicate evaluator)
  ├── SalesforceCreateOrderTool (Stage 4.3)
  └── (more per stage)

AgentContext           ←  shared state across stages: email, intake, extracted,
                          customer_match, reconcile, decision, execution, reply
```

### Strict JSON Schema for every LLM call

Every LLM-bound tool defines its expected output as a JSON Schema:

```python
CLASSIFY_INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["language", "intent", "intent_confidence", "intent_reasoning",
                 "secondary_intents", "spam", "spam_reason", "summary",
                 "track_hint", "language_reasoning"],
    "properties": {
        "intent": {"type": "string", "enum": [13 canonical values]},
        "intent_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "track_hint": {"type": "string", "enum": ["trade", "som",
                                                  "service_contract", "none"]},
        ...
    }
}
```

The schema is sent with `response_format = {"type": "json_schema", "json_schema": {"strict": True, ...}}`. OpenAI rejects any LLM output that doesn't match. The schema is the contract.

### KB-driven configurability

| Namespace | What it controls | Example rule |
|---|---|---|
| `intent` | Canonical intent definitions, track_hint, positive/negative examples for the classifier prompt | `quote_to_order` → "customer asking to convert an existing quote into a sales order"; track=trade |
| `extract_schema` | Per-intent field list the schema-driven extractor pulls | `po_intake` → po_number (required), quote_number, line_items[], total, payment_terms, … |
| `business_rules` | Predicate-driven guardrails that cap confidence or hard-block actions | `total > 500000 AND 'ITAR' in compliance` → cap_at_0.70 (force HITL) |
| `translation` | Glossary + tone instructions injected into the translator | "Preserve verbatim: PO numbers, SKUs, quote IDs"; "Tone: business formal" |
| `spam_heuristic` | Regex/keyword rules from SpamAssassin + SwiftFilter (~50 starter rules) | `subject_emoji_spam` → matches `[🎉🔥💰]{2,}` in subject; weight 1.5 |
| `language_heuristic` | 4-tier ruleset (script → diacritic → keyword density → greeting) for fast pre-LLM language detection | `ja_hiragana_present` (tier 1, severity definitive) |

All six are CRUD-able at `/settings/knowledge-base` in the SPA.

---

## 5. Pipeline — 5 Stages, 23 Sub-steps

The pipeline runs **five stages** per email. Continuous Learning was originally a sixth pipeline stage, but is now a **separate dashboard** at `/learning` (see § 6) — it's organizational work that happens *between* runs, not per-email.

> **Image prompt for pipeline flow diagram**:
>
> *"Horizontal pipeline flow diagram, ZBrain blue accent (#1A55F9), clean and minimal, white background, five rectangular stage cards arranged left-to-right with curved arrows connecting them. Each stage card has the stage number in a circle, a title, and below it a vertical list of sub-steps. Stage 1 'Intake & Classification' shows: 1.1 Receive · 1.2 Heuristic spam · 1.3 Light extraction · 1.4 Detect language · 1.5 Translate · 1.6 LLM spam · 1.7 Classify intent. Stage 2 'Data Extraction & Enrichment' shows: 2.1 Document extraction · 2.2 Schema-driven extraction · 2.3 Customer ID (Salesforce) · 2.4 Customer enrichment. Stage 3 'Decision & Confidence' shows: 3.1 Reconcile vs quote · 3.2 Confidence formula · 3.3 Business rules · 3.4 Final tier. Stage 4 'Workflow Execution' shows: 4.1 Customer guardrail · 4.2 Idempotency check · 4.3 Salesforce write · 4.4 ServiceNow case. Stage 5 'Communication & Closeout' shows: 5.1 Draft reply · 5.2 Translate · 5.3 Attach SOA · 5.4 Comm log. Below the main flow, draw two side-channel branches with dashed arrows: one branch labeled 'Spam / out_of_scope → discard' bypassing Stages 2-5 from after Stage 1.7; another branch labeled 'L2/L3 confidence → HITL queue' branching off from Stage 3. To the right of the pipeline, a separate boxed-out lane labeled 'Continuous Learning Dashboard (/learning)' connected by a single dashed arrow from the HITL queue, captioned 'feedback events · drift signals · KB tuning suggestions'. Use sans-serif Inter font, soft drop shadows on each card, ZBrain blue arrows, slightly rounded corners. Title at top: 'Keysight SalesOps Pipeline · 23 auditable sub-steps + cross-cutting Learning'."*

### Stage-by-stage detail

| # | Stage | Sub-steps | LLM calls |
|---|---|---|---|
| **1** | **Intake & Classification** | Receive · heuristic-spam · light-extract · detect-language (heuristic+LLM) · translate (per source: body + each attachment) · llm-spam · classify-intent | 4 |
| **2** | **Data Extraction & Enrichment** | full-OCR · schema-driven extraction (KB-typed) · Salesforce-only customer ID · intent-aware SF enrichment SOQL | 1 |
| **3** | **Decision & Confidence Scoring** | reconcile vs quote · confidence formula (0.45·intent + 0.35·extract + 0.20·customer-match) · business rules eval · tier decision (L4/L3/L2) | 0 |
| **4** | **Workflow Execution** | customer-match guardrail · idempotency check · SF Order write (or draft) · ServiceNow case (Phase 2) | 0 |
| **5** | **Communication & Close-out** | draft English reply · translate to customer language · attach SOA/Invoice/Cert PDFs · CommunicationLog write | 2 |

**Terminal short-circuit:** when Stage 1.7 returns `intent ∈ {spam, out_of_scope}`, Stages 2-5 are skipped. The pipeline is marked `discarded` with the reason logged. Real Google security alerts and forwarded marketing newsletters never run through the expensive extract / decide / write path.

**QA matrix verified end-to-end** on a sequential 8-pipeline run (2026-05-08): po_intake → L4_AUTO completed; quote_to_order EN/ES/JA → L4_AUTO / L2_HITL / L2_HITL (low-confidence extraction correctly trips the HITL gate); service_order → L4_AUTO completed; service_contract_request → L3_ONE_CLICK; wo_status_inquiry → L3_ONE_CLICK; out_of_scope (Google security + forwarded promo) → discarded in 9s with only Stage 1 running.

---

## 6. HITL & Continuous Learning Loop

> **Image prompt for HITL + Continuous Learning loop diagram**:
>
> *"Cyclical loop diagram, ZBrain blue accent, clean infographic style, white background, suitable for an executive deck. Layout: a horizontal pipeline at the top showing five stages (Intake → Extract → Decide → Execute → Communicate) as small connected circles. Below the pipeline, a tier router fans out into three columns: 'L4 Auto-apply (≥95%)' on the left with a green check, 'L3 One-click approve (80-94%)' in the middle with an amber pause icon, 'L2 Full review (<80%)' on the right with a red person icon. The L3 and L2 columns flow into a central rectangle labeled 'CSR HITL Queue' showing fields: PO summary, extracted JSON preview, draft reply preview, three buttons (Approve · Edit & Approve · Reject). From the HITL queue, three return arrows curve back to: (a) 'Salesforce write' (on approve, triggers Stage 4 execute); (b) 'CommunicationLog + SMTP send' (on approve, Stage 5); (c) 'Feedback Event' database (on any action — approve/edit/reject captured). To the right of the loop, draw a separate boxed-out lane (visually distinct from the pipeline — different shade, dashed border) labeled 'Continuous Learning Dashboard (/learning)' that receives a dashed arrow from the Feedback Event database. Inside that lane, three stacked cards: 'Aggregated CSR feedback (per-stage 👍/👎/edits)', 'Drift detection — confidence baseline shift, business-rules fire-rate spike', and 'KB tuning suggestions — one-click apply'. From the dashboard, a single curving dashed arrow returns to 'KB rules (intent, extract_schema, business_rules)' showing the operator-driven tuning loop. Use Inter sans-serif font, ZBrain blue (#1A55F9) for primary arrows, soft amber/green/red for the tier columns, dashed gray for the cross-cutting Learning lane to visually distinguish it from the per-email pipeline, soft drop shadows, rounded corners. Title at top: 'Human-in-the-Loop & Continuous Learning'."*

### How it actually works

**Tiered autonomy routing** (decided in Stage 3.4):

| Final confidence | Tier | What happens |
|---|---|---|
| **≥ 0.95** | **L4_AUTO** | Stage 4 writes to Salesforce immediately. Stage 5 drafts + sends the reply. Pipeline closes. |
| **0.80 – 0.94** | **L3_ONE_CLICK** | Stage 4 prepares a draft Order in Salesforce. Stage 5 drafts the reply. Pipeline pauses. CSR sees a single Approve button. |
| **< 0.80** | **L2_HITL** | No SF write, no reply sent. Pipeline routes to the HITL queue with full context: extracted fields, decision reasoning, business rules fired, customer match, draft reply. CSR can edit any field, then approve or reject. |

**Cap-down rules** (Stage 3.3 business_rules KB):

| Predicate | Effect | Why |
|---|---|---|
| `'ITAR' in compliance OR 'EAR' in compliance` | cap_at_0.70 → force L2 | Compliance review required |
| `total > 500000` | cap_at_0.88 → force L3 | High-value deals get a one-click human gate |
| `intent in [trade_change_order, hold_release]` | cap_at_0.88 → force L3 | These mutate existing booked orders |
| `payment_terms not in [Net 30, Net 45, Net 60]` | warn | Non-standard terms surfaced |

These predicates are editable in `/settings/knowledge-base` → Business rules.

**HITL UI** (`/hitl`): one row per pending pipeline. Click expands the full trace with every sub-step's Input/Output/Activities. Approve writes through to Salesforce and SMTP-sends via the connected Gmail account. Reject closes the CCC with `csr_rejected`.

**Feedback events** (per stage 👍/👎 + edits): the CSR can leave per-stage thumbs/edits in the trace. Each event is stored as a `FeedbackEvent` row with `pipeline_id`, `stage`, `verdict`, `edit_diff`, `csr_user`, `timestamp`.

**Continuous Learning** lives at **`/learning`** as a dashboard, not as a pipeline stage. Operators visit it between runs to review aggregated signal:

1. **Aggregation** — `GET /api/learning/dashboard?window_days={7|14|30|90}` returns per-stage 👍/👎/edits counts across all pipelines in the window. The page heatmaps stages with high edit volume (where CSRs are doing the most correction work — usually a sign that prompt or KB tuning is needed).
2. **Drift detection** — for every intent with ≥4 pipeline runs, compares the **recent 7-day median confidence** against the **rolling baseline** (the rest of the window). Δ ≤ -0.10 → flag with severity (high if Δ ≤ -0.20, medium otherwise). Surfaces as a banner with a drill-down link to recent runs of that intent.
3. **Intent-misclassification corrections** — when a CSR overrides the classifier in HITL (e.g., changes `general_inquiry` → `service_order` on approve), that's a labelled correction. The dashboard lists recent corrections as `from_intent → to_intent` rows with a link to the original trace.
4. **KB tuning suggestions** — when the same `from→to` correction repeats ≥ 2× in the window, the dashboard surfaces a one-click suggestion: *"Add CSR-corrected examples to '`to_intent`' rule — support: N"*. Clicking opens the relevant KB rule in `/kb` ready to edit and save. **No code change, no redeploy.**
5. **Suggested-fix drafter** — when Stage 3.1 reconciliation finds line-item mismatches between the PO and the matched Quote, a "Suggest fix" button surfaces in the Decide card of that pipeline's trace. Clicking it asks an LLM to draft a corrective email back to the customer (*"we noticed line 3 quantity differs — please confirm 5 vs 6"*). The CSR reviews/edits/sends.

---

## 7. Confidence Rubrics — design and calibration

Two LLM-emitted confidence numbers in the pipeline (intent in 1.7, language in 1.4) used to be opaque LLM-picked values. We made them **deterministic, auditable, and operator-tunable** by attaching a KB rubric to each: the LLM is forced via strict JSON Schema to evaluate every rule and report a per-rule contribution (matched true/false, delta, evidence quote). We then **recompute the final confidence server-side** as `base + sum(matched deltas)`, clamped to `[0, 1]`.

### The math

```
final_confidence = clamp( base + Σ matched_delta_i , 0, 1 )

where matched_delta_i = effective_delta_i  if rule_i.matched == true
                       0                    otherwise

and  effective_delta_i = per_intent_overrides[intent]  if present
                        per_language_overrides[lang]   if present
                        default_delta                  otherwise
```

The clamp guarantees the displayed confidence is always a valid 0–100% probability, even when the rubric math overshoots (e.g., a clear case where five triggers fire totalling +0.92 plus the base +0.50 = 1.42 → clamped to 1.00 = 100%).

### Why 0.50 (intent) and 0.40 (language)?

There are two textbook choices for an uninformed prior, and our values are a **deliberate calibration midpoint** between them:

| Prior | Value (intent, 13 classes) | Value (language, 4 classes) | When it's right |
|---|---:|---:|---|
| **Max-entropy / uniform** (Jaynes 1957) | 1 / 13 ≈ 0.08 | 1 / 4 = 0.25 | When the classifier is *blind* to the input — has zero information before deciding |
| **Laplacian neutral / Beta(1, 1)** | 0.50 | 0.50 | Treat each verdict as a binary outcome ("is it this class or not") with no information — the standard Bayesian uninformed binary prior |
| **Our calibrated midpoint** | **0.50** | **0.40** | The LLM has *already read* the email — it brings real pretrained knowledge before any rubric rule fires. We pick a value above uniform but not all the way up to 0.50 for language (4 classes) because there's less for the LLM's general knowledge to disambiguate. |

The choice is **calibration engineering, not a theorem**. Two implications:

1. **The base reflects the LLM's pre-rubric knowledge, not the task's a-priori uncertainty.** A blind classifier would start at uniform; an LLM that has read the email starts higher.
2. **Operators can tune both bases** in `/kb` → "Intent confidence rubric" / "Language confidence rubric" → `_base` rule. If real-world calibration data shows the system is consistently over-confident at low evidence, drop the base. If it's under-confident even when evidence is strong, raise it. No redeploy.

### Why a clamp instead of a softmax / normalization?

A clamp **preserves how strongly the rubric over-voted the threshold** — anything ≥1.0 reads as "the rubric is screaming this is the right answer; the gap doesn't matter." Softmax-rescaling would compress that signal to ~0.95 even when 5 strong triggers all fire, which is misleading. The clamp is also visible to the operator (the breakdown shows `Sum of matched deltas: +0.92` then `Total (clamped to [0, 1]): 1.00 → 100%`) so the math stays transparent.

### Per-class overrides on every rule, or only where they matter?

We use **per-class overrides only where they matter**. Most rubric rules apply uniformly across intents/languages; only a few have meaningful per-class variance (e.g., `script_definitive_match` is +0.55 for Japanese because hiragana is unambiguous, but +0.30 for Spanish because Latin script alone is weak). This keeps the KB lean — operators add overrides only when they observe miscalibration on a specific class.

### What this gives the customer

- **Auditable** — every confidence number has a paper trail. CSR / compliance / Keysight ops can open any pipeline trace and see the rubric math.
- **Tunable** — the rubric is not in code. Operators change deltas, deactivate rules, add per-class overrides through Settings → Knowledge Base.
- **Explainable to a regulator** — the system can defend any L4 auto-decision by pointing at the rubric rules that fired, with cited evidence quotes from the email itself.

---

## 7b. Email Thread Handling — design rationale

Real customer mailboxes are not single emails — a typical PO conversation is 5–20 messages where the buyer asks clarifying questions, attaches revised BOMs, the CSR confirms terms, and the buyer finally sends a signed PO. The agent's automation has to make sense of that whole conversation, not just the latest message it received.

### Three options we considered

**(a) Single-pipeline, append-and-re-evaluate.** One pipeline per *conversation*, mutated as new messages arrive. Each new reply re-runs the relevant stages with the appended context, the pipeline's autonomy tier may upgrade or downgrade, and side-effects are guarded by the pipeline's own state.
- ✅ Single audit row per conversation; clean for compliance.
- ✅ Mutable state means execution can amend (qty correction) instead of duplicate.
- ❌ Significant orchestration complexity (stage re-entry, partial re-runs, mutation-vs-replay semantics).
- ❌ Doesn't match the "every email triggers a pipeline" pattern operators expect once intake is fully automated.

**(b) Pipeline-per-email, no thread awareness.** Each email is processed independently. Simple, but every reply re-classifies in isolation (often badly — "wait, change qty to 50" is ambiguous without the original PO) and side-effects can duplicate (Pipeline 47 creates the SF Order, Pipeline 48 doesn't know and creates it again).
- ✅ Trivially simple data model.
- ❌ Decision quality drops on replies (no context).
- ❌ Duplicate side-effects across pipelines on the same conversation.

**(c) Pipeline-per-email + thread-aware context + thread-level idempotency at Stage 4.** Each email triggers its own pipeline. Each pipeline loads the entire thread chain (`walk_thread()`) as evidence — root message is the *primary intent source*; subsequent replies are clarifying context. Side-effects are deduped via a `pipeline_executions` table keyed on `(thread_root_message_id, action, args_hash)`: before any Stage 4 write, the orchestrator checks whether an earlier pipeline on the same thread already performed the same action with the same args, and either returns the prior result, amends the existing record (qty correction style), or escalates to HITL on conflict.
- ✅ Same simplicity as (b) at the orchestrator level.
- ✅ Same safety as (a) for side-effects.
- ✅ Thread context still feeds Stage 1 (intent), Stage 2 (extraction), Stage 5 (reply) — no decision quality regression.
- ✅ Inbox UI groups pipelines by thread root, so a CSR sees one conversation even if it spans N pipelines.
- ✅ Audit trail: each pipeline is its own immutable row (no mutation), but they're linked via the thread root for cross-pipeline queries.

### Decision: (c) — hybrid

(c) is what we ship. Why:

1. **Behavioural parity with (a) on the things that matter.** The two visible regressions of (b) — bad classification on replies and duplicate side-effects — are both fixed in (c) without touching the pipeline lifecycle. Loading the thread chain into context recovers classification quality. Thread-level idempotency at Stage 4 prevents duplicate writes.
2. **Behavioural parity with (b) on the things operators expect.** Once intake is fully automated, every inbound email triggers a pipeline. (a)'s "append to existing pipeline" model fights that pattern; (c) embraces it.
3. **Audit trail without mutation.** Each pipeline is an immutable record of what the agent decided given the thread state at that moment. (a)'s mutable pipeline state is harder to defend — "what did the agent decide at 09:08?" requires reading iteration logs.
4. **Idempotency benefits everything, not just threads.** The execution-log layer also catches accidental retries, double-clicks on HITL approve, and re-runs from the test harness — value beyond the thread case.

### How (c) is wired in code

- `app/services/email_thread.py::walk_thread(db, email)` returns the chronological chain via `Message-Id` / `In-Reply-To` / `References` headers (RFC 5322 §3.6.4) with a subject-similarity backstop for phone clients that strip headers.
- Stage 1 (intent classify) and Stage 2 (schema extract) prompts include the full chain. The root message is labeled `ROOT (primary intent source)`; subsequent messages are labeled `REPLY 1`, `REPLY 2`, …
- Stage 4 consults `pipeline_executions` before any side-effect call. The key is `(thread_root_msg_id, action, args_hash)`. On hit: skip + return the prior result. On miss: execute, then record.
- The Inbox view groups by `thread_root_msg_id` and shows "1 conversation · N messages".

### Trade-off we accept

(c) creates more pipeline rows than (a) — one per email instead of one per conversation. For compliance, we treat that as a feature: each email's decision is a discrete, immutable audit record. If conversation-level rollups matter to a customer, the Inbox grouping and the shared `thread_root_msg_id` make that a UI concern, not a data-model one.

---

## 7c. Stage 3 Decision Engine — design rationale

The Stage 3 confidence-and-tier decision is the most consequential point in the pipeline: a wrong tier choice either lets a bad action auto-execute (over-trust) or buries a clean request in HITL backlog (under-trust). Keysight's RFP §38-41 lists every input we should consider — LLM assessment, pattern matching, customer history, reference validation, dollar thresholds, export controls, customer exclusions, regional overrides — and §59 asks for self-tuning thresholds. That's a lot to hand-wire in code; once it's there, every threshold tweak becomes a code change waiting on a sprint cycle.

We designed Stage 3 to put **all of those inputs in the Knowledge Base**, where an operator can see every signal, every weight, every cap, and every business rule, and tune them without a redeploy.

### Three KB namespaces drive Stage 3

| Namespace | Drives | Rule kinds |
|---|---|---|
| `decision_confidence_rubric` | The confidence formula (Stage 3.1) | `weighted_signal` (3 default), `floor_cap` (7 default) |
| `reconcile_checks` | Cross-system validation (Stage 2.5) | `per_line` and `per_total` predicate checks (12 default) |
| `business_rules` | Compliance and policy guardrails (Stage 3.2) | `severity` enum + numeric `cap_at` + dry-run flag (15+ default rules) |

Each namespace is editable in `/kb`; each Stage 3 sub-step in the trace UI shows which rules contributed to the decision and which didn't fire, with evidence quotes.

### Why a KB-driven rubric, not a hardcoded formula

The original design lived inline in `decide.py`:
```
confidence = 0.45·intent + 0.35·extraction + 0.20·customer_match
if blocking_mismatches: confidence = min(confidence, 0.70)
elif soft_mismatches: confidence = min(confidence, 0.88)
if missing_po_number: confidence = min(confidence, 0.40)
# ...
```

That formula works, but it has three problems for an enterprise deployment:

1. **Auditors can't read it.** A regulator reviewing why an order was auto-approved at $179k can read prose ("the rubric capped this at L3 because customer match was fuzzy") in a way they cannot read a Python expression.
2. **Operators can't tune it.** Every weight or threshold tweak — "make customer-match more important for our defense vertical" — becomes a code change.
3. **The math is opaque.** A confidence of 0.93 does not tell you which signal carried the day. With a KB rubric, the output includes a `confidence_breakdown[]` table showing exactly how each rule contributed.

The KB rubric reproduces the formula bit-for-bit on day one (so existing tier behavior is preserved), and from there an operator can rebalance weights, add new caps, or deactivate rules through the UI.

### The two rule kinds, narratively

**`weighted_signal`** rules contribute `weight × signal_var` to a running confidence sum. The three default signals — intent_confidence (×0.45), extraction_completeness (×0.35), customer_match_score (×0.20) — sum to a 1.0 weighting envelope, mirroring Bayesian likelihood combination. Operators rebalance these to match how their data actually predicts HITL escalation.

**`floor_cap`** rules evaluate a predicate against the same eval-context the business_rules engine uses. When the predicate matches, confidence is forced down to the rule's `cap` value. Caps are categorical, not gradient: they encode "we just won't auto-act when X is true," regardless of how clean the rest of the signals are. The seven default caps cover the load-bearing safety scenarios:

- **`exact_match_required_for_l4`** caps fuzzy-name-matched customers at 0.85 — even a perfect-extraction PO from Aurora doesn't auto-execute if Salesforce only matched on a fuzzy Account.Name.
- **`customer_match_low_cap`** / **`customer_match_med_cap`** layer additional pressure for medium and weak matches.
- **`missing_po_number_cap`** / **`empty_line_items_cap`** prevent obviously-incomplete extractions from hitting Stage 4 (where they'd fail anyway).
- **`blocking_mismatch_cap`** / **`soft_mismatch_cap`** translate Stage 2.5 reconcile findings into tier pressure.

### Customer existence is a hard gate, not a signal

A common question: how can the confidence formula run before we've checked Salesforce? The answer is that Stage 2.3 ("Customer identification") is a **hard gate** — if the inbound email doesn't match a Salesforce Account by `Customer_Code__c`, `Contact.Email`, or fuzzy `Account.Name`, the pipeline stops at Stage 2 with `pipeline.status = "awaiting_hitl"` and `CCC.fallout_reason = "unknown customer — please tag in Salesforce"`. **Stage 3 is never reached.** By the time confidence math runs, we already know the customer exists.

The `customer_match_score` signal in the rubric (and the three customer-match floor caps) only differentiate *exact match* from *fuzzy match*. The existence question itself is settled upstream. This three-layer defense — existence gate at 2.3 → match-quality signal at 3.1 → match-quality caps at 3.1 — is intentional: the gate prevents misrouted emails, the signal contributes graded confidence, and the caps enforce categorical "no auto-action on uncertain customer" policy.

### Reconcile lives at Stage 2.5, not Stage 3.1

In the original design, reconcile ran in the orchestrator between Stage 2 and Stage 3, and Stage 3.1 was titled "Reconcile recap" — just re-emitting the result. That was a misnomer. Reconcile is a **cross-system validation** step: it compares the extracted PO against the matched Salesforce Quote (line items, totals, terms, currency, addresses), the matched Account (billing address, recent orders for duplicate detection), and Service objects (Asset entitlement, ServiceContract coverage). It's the close of extraction, not the start of decide.

Moving it into Stage 2 sub-step 2.5 puts the data lineage right: Stage 2 ends with a fully-validated, cross-referenced extraction; Stage 3 takes that as a precondition and decides what to do.

The 12 default reconcile checks live in the `reconcile_checks` KB namespace and cover everything the RFP §37 calls out — pricing, quantities, terms — plus the gaps we identified during enterprise hardening: payment terms, currency consistency, total-amount sum-check, billing-address cross-reference, duplicate-PO detection, service-asset entitlement, service-contract coverage. Like the confidence rubric, every check is operator-tunable: change a tolerance, deactivate a check, add a per-intent override, all from `/kb`.

### Business rules: the third leg

The `business_rules` namespace is the policy layer that sits on top of the pure-math confidence formula. Where reconcile catches data inconsistency and the rubric weights signals, business rules express **organizational policy**: "orders above $500k always need CSR review", "ITAR-flagged customers always go through export-control review", "customers on credit hold cannot receive new orders."

The engine is a sandboxed Python AST evaluator with a whitelisted set of operators and helper functions:

| Helper | Purpose | Example use |
|---|---|---|
| `days_until(date)` | days from today to ISO date (negative if past) | `days_until(asset.calibration_due_date) < 30` |
| `days_since(date)` | days from ISO date to today | `days_since(quote.created_date) > 60` |
| `regex_match(s, pattern)` | regex test | `regex_match(po_number, '^[A-Z]{2,4}-\\d{4,}$')` |

Each rule supports filters by `intent`, `region`, `sla_tier`, and `vertical`, plus a `dry_run` flag for staged rollout: a new rule is added in dry-run mode so the trace shows "would have fired" without affecting the tier; once the data team is comfortable with its precision, dry-run is flipped off and it becomes binding.

Severity is either an enum (`hard_block`, `cap_at_0.70`, `cap_at_0.88`, `warn`) or an explicit numeric `cap_at: 0.65`. The numeric form is what most production deployments will use; the enum is a convenience for common bands.

### How this maps to RFP requirements

| RFP §  | Requirement | Where it lands |
|---|---|---|
| §38 | "Confidence-Gated Decision Engine" | Stage 3.1 (`decision_confidence_rubric`) |
| §39 | "Multiple signals (LLM, pattern matching, customer history, reference validation)" | Three default `weighted_signal` rules + floor caps that consult reconcile findings (pattern matching) and customer-match score (history + reference validation) |
| §40 | "Tiered autonomy levels with configurable thresholds" | L4/L3/L2 thresholds in `config.CONFIDENCE_TIERS`; each tier-cap is a tunable rule in the rubric |
| §41 | "Centralized business rules engine for compliance guardrails (dollar thresholds, export controls, customer exclusions)" | `business_rules` KB namespace, with the 15 default rules covering all three callouts |
| §42 | "Configurable regional overrides for workflow rules without code changes" | Each business rule has `region` + `sla_tier` + `vertical` filter fields |
| §59 | "Self-tuning confidence thresholds based on observed correction patterns" | Continuous Learning hub surfaces drift signals + tuning suggestions; one-click apply edits the live rubric |

### What this gives the customer

A regulator or auditor opening a pipeline trace sees:

- **A confidence breakdown table** showing every signal that contributed (weighted) and every cap that fired (categorical), with plain-English evidence per row.
- **A reconcile checks panel** showing which of the 12 cross-system validations passed, which failed, and what the diff was against the matched quote / account / order history.
- **A business rules panel** showing every rule the engine evaluated, which fired, and what cap (if any) it imposed.
- **A consistent narrative**: existence-gate at 2.3 → cross-system validation at 2.5 → confidence math at 3.1 → policy guardrails at 3.2 → tier picker at 3.3.

For an operator (the AI/MLOps team), the same data is editable. A drift signal in the Continuous Learning hub ("L4 false-positives clustered around fuzzy-customer-match cases") translates into a one-line edit in the rubric ("tighten exact_match_required_for_l4 cap from 0.85 → 0.75"), no engineering ticket required.

For the engineering team, the surface area is small: three KB namespaces, one safe-eval engine, two rule-kind types. Adding a new policy is a row in the KB, not a code change.

---

## 8. Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19 + Vite 6 + TypeScript + Tailwind CSS · Inter font · ZBrain design tokens |
| **Backend** | Python 3.12 + FastAPI 0.115 + SQLAlchemy 2.0 + Pydantic 2 |
| **Orchestrator runtime** | ZBrain agent fabric (BaseAgent + Tool ABC + AgentContext) |
| **LLM** | OpenAI gpt-5.2 with `response_format = json_schema` (strict mode); legacy Claude path retained for graceful fallback |
| **Document OCR** | AWS Lambda → Azure Document Intelligence (PDF/images); openpyxl (XLSX); python-docx (DOCX with auto-fallback to OCR for sparse content) |
| **Format conversion** | reportlab (output PDFs); in-process XLSX→PDF and DOCX→PDF (only when needed for OCR fallback) |
| **CRM** | Salesforce REST + SOQL via simple-salesforce; OAuth2 Client Credentials Flow (Username-Password is disabled in newer orgs) |
| **Field Service** | Salesforce Field Service Lightning (Asset, ServiceContract, WorkOrder, ServiceAppointment) |
| **Documents** | SharePoint Online via Microsoft Graph (Sites.ReadWrite.All + Files.ReadWrite.All) — *or* Google Drive via Service Account |
| **ERP** | Oracle Fusion Cloud REST API via IDCS OAuth2 |
| **Email** | Gmail IMAP (inbound, via stdlib `imaplib` + IMAP IDLE) and SMTP (outbound, via stdlib `smtplib` STARTTLS) |
| **Tunnel (dev only)** | cloudflared quick tunnel for local-dev → AWS Lambda reachability |
| **Database** | PostgreSQL in production · SQLite for local dev · Fernet-encrypted columns for integration secrets |
| **Tracing** | Server-Sent Events stream of TraceEvent rows; per-pipeline `/api/trace/stream?pipeline_id=N` |
| **Auth** | Bearer-token middleware on all `/api/*` routes (configurable via `APP_AUTH_TOKEN` env) |
| **Deployment** | Multi-stage Dockerfile + docker-compose; readiness probe at `/api/ready`; structured JSON logs |

---

## 9. Roadmap

| Phase | Timeline | Deliverables |
|---|---|---|
| **Phase 1 — RFP Demo (current)** | now → 2026-05-10 | 6-stage pipeline live; Salesforce + FSL integrated; OpenAI strict-JSON; KB-editable; HITL queue with real SMTP send; 3 languages; 13 intents; 25 auditable sub-steps |
| **Phase 2 — Production Hardening** | +4 weeks post-RFP | ServiceNow case lifecycle (Stage 4.4); SharePoint document storage live; Oracle Fusion ERP read-side wired (catalog + invoices); Postgres migration; rate-limit middleware; per-CSR audit log |
| **Phase 3 — Scale & Intelligence** | +3 months | ML-based drift detection (replace threshold heuristics); multi-region deployment; voice-channel intake; customer self-service portal; A/B testing of intent prompts |
| **Phase 4 — Adjacent Workflows** | +6 months | Outbound campaigns; renewal forecasting; lead-gen email triage; integration with Salesforce Einstein for opportunity scoring |

---

## 10. Reference: Architecture Decisions (live log)

The full architectural decision log lives in [`SOLUTION.md`](./SOLUTION.md) and includes 18 ADRs covering:
- ADR-001 through ADR-010 — Stage 1 v2 design (7 sub-steps), hybrid OCR, two-pass spam, KB-driven configurability
- ADR-011 — OpenAI strict JSON Schema for Stage 1 LLM tools
- ADR-012 — `out_of_scope` intent + terminal-intent short-circuit
- ADR-013 — Stage 2 v2 design (4 sub-steps + Salesforce-only customer match)
- ADR-014 — Stage 6 (Continuous Learning) reframed as cross-cutting `/learning` dashboard; pipeline becomes 5 stages
- ADR-015 — Stage 3 substep events (4 sub-steps with confidence-formula and business-rules drill-downs)
- ADR-016 — Stage 4 substep events on every action path (not only PO-ack)
- ADR-017 — Stage 5 substep events (draft, translate, attach, comm-log)
- ADR-018 — Pipeline reliability hardening (rollback-on-exception in `stage_timer`, `bus.publish` thread-safety via `loop.call_soon_threadsafe`, `create_order_from_quote` idempotency, SQLite WAL + busy_timeout)

Each ADR is dated, marks confirmation status, and links to the verifying pipeline run.

---

*Document owner: LeewayHertz · Built on ZBrain · Prepared for the Keysight RFP*
