# HANDOVER — Keysight SalesOps Demo (built on ZBrain)

**Audience:** an agent picking up this project in a fresh session. Read this end-to-end before doing anything else. Pair with [CLAUDE.md](CLAUDE.md), [RESEARCH_BRIEF.md](RESEARCH_BRIEF.md), [BUILD_QUEUE.md](BUILD_QUEUE.md), [v1.1_CHANGELOG.md](v1.1_CHANGELOG.md).

**Repo root:** `C:\Users\Rituraj\keysight-salesops-demo`
**User:** Rituraj Shrivastava, LeewayHertz, building MVP demo for Keysight RFP.
**Original demo deadline:** 2026-05-10 (passed — currently iterating on follow-ups).
**Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + Vite + TS + Tailwind (frontend), branded as **ZBrain**.

---

## 0. CRITICAL — hard rules you cannot violate

| Rule | Where it lives | Why |
|---|---|---|
| **Never surface "Claude" in user-visible strings** | CLAUDE.md | Product surface is ZBrain. Use "ZBrain orchestrator" / "ZBrain document-intelligence agent" / "ZBrain vision OCR" in UI, trace messages, doc copy. Internal `claude_agent_sdk` imports are fine. |
| **`DEMO_TRANSMIT_LOCKED = True`** | `backend/app/config.py:66` | NO outbound email. NO SMTP. NO IMAP folder mutation. NO Salesforce Chatter @-mention. The pipeline RECORDS what it would have done (CommunicationLog / trace event with `would_route_to` / `simulated=True`), but never actually transmits. To enable real transmission, the constant must be edited — env vars alone cannot override it. |
| **No real SF/SAP connector additions** | CLAUDE.md | Mocks are deliberate. We DO use a real Salesforce dev org for Customer/Account/Case writes (already in place), but never add a new third-party connector unless asked. |
| **No `ANTHROPIC_API_KEY` env var** | CLAUDE.md | Runtime inherits local auth. |
| **No comments explaining WHAT code does** | CLAUDE.md | Only WHY when non-obvious. Identifiers should already explain WHAT. |
| **v1.1 changes need rollback markers** | This doc + v1.1_CHANGELOG.md | Every code block added in the v1.1 cycle must be wrapped in `# === v1.1 TASK-N START ===` / `# === v1.1 TASK-N END ===` (Python) or `// === v1.1 TASK-N START/END ===` (TSX/TS). Single-line additions can use a trailing `# === v1.1 TASK-N ===`. The user must be able to grep these markers and revert any task independently. |

---

## 1. Architecture (one-page)

```
[ IMAP poller ]
      ↓ pulls new messages every 10s
[ Email table ]
      ↓ POST /api/pipelines/run/{email_id}
[ Orchestrator: 6-stage pipeline (+ pre-intake stage 0) ]
      │
      ├─ STAGE 0 (v1.1 TASK-2) — Pre-AI Outlook rules ─→ short-circuit on match (no LLM)
      ├─ STAGE 1 — Intake & classification (sub-steps 1.1-1.7b)
      ├─ STAGE 2 — Document extraction + SF customer match + reconcile checks
      ├─ STAGE 2.5 — Cross-system validation (reconcile)
      ├─ STAGE 3 — Decision + 4-gate confidence + tier (L4_AUTO / L3_ONE_CLICK / L2_HITL)
      ├─ STAGE 4 — Execute (SF Order / WO / Case writes)
      ├─ STAGE 5 — Communicate (reply draft, attaches synthetic SOA PDF)
      └─ STAGE 6 — Continuous-learning hook
      │
      ↓ Back-stamp (IMAP COPY+EXPUNGE — currently simulated by demo lock)
[ Inbox / HITL / Activity / Analytics / Ops Log / KB / Settings / Test Corpus pages ]
```

Each stage emits `substep_start` / `substep_done` trace events. The Trace UI renders the timeline.

**One ZBrain subagent per stage.** All stages share an `AgentContext` that carries intake/extracted/customer_match/reconcile/decision/execution dicts plus the DB session and pipeline_id.

---

## 2. Code map (where everything lives)

### Backend
```
backend/
├── app/
│   ├── main.py                     # FastAPI app + middleware + router includes
│   ├── config.py                   # INTENTS, INTENT_TO_FLOW, TERMINAL_INTENTS, DEMO_TRANSMIT_LOCKED, INTENT_REDIRECT_TARGETS (v1.1)
│   ├── models.py                   # SQLAlchemy models — Pipeline, Email, EmailAccount, KnowledgeRule, CommunicationLog, TestCase/TestRun/TestRunResult (v1.1), etc.
│   ├── db.py                       # SessionLocal + Base + engine
│   ├── db_migrate.py               # Idempotent ALTER TABLE list — adds new columns on startup
│   ├── kb.py                       # KB seed loop, accessors (intake_intent_rules, outlook_rules, routing_rules, etc.)
│   ├── trace_log.py                # log_event() helper writing to TraceEvent
│   ├── tracing/bus.py              # In-memory pub-sub for live trace stream
│   ├── middleware/
│   │   ├── auth.py                 # Bearer auth (legacy, unused in default config)
│   │   └── basic_auth.py           # v1.0 — Full-site HTTP Basic Auth gate (browser-native prompt)
│   ├── agents/
│   │   ├── orchestrator.py         # run_pipeline() — calls each stage in order
│   │   ├── intake.py               # System-prompt builder (KB-driven, region-aware in v1.1 TASK-6)
│   │   ├── pre_intake.py           # v1.1 TASK-2 — deterministic Outlook-rule engine (no LLM)
│   │   ├── decide.py               # Stage 3 confidence math + 4-gate split (v1.1 TASK-5/B5)
│   │   ├── execute.py              # Stage 4 actions
│   │   ├── routing_resolver.py     # v1.1 TASK-5 — KB routing predicates
│   │   ├── stage1_intake_agent.py  # Sub-steps 1.1-1.7b orchestration (CSR override, override-pass, shadow classifier wired here)
│   │   ├── stage2_extract_agent.py
│   │   ├── stage3_decide_agent.py
│   │   ├── stage4_execute_agent.py
│   │   ├── stage5_communicate_agent.py
│   │   ├── stage6_learning_agent.py
│   │   └── tools/
│   │       ├── classify_intent_tool.py       # Primary OpenAI classify_intent (KB-driven)
│   │       ├── override_pass_tool.py         # Second LLM pass (override book)
│   │       ├── detect_csr_override_tool.py   # CSR-instruction override detector (LLM micro-step)
│   │       ├── shadow_classifier_tool.py     # v1.1 TASK-9 — logged-only third pass
│   │       ├── detect_spam_tool.py           # Regex heuristic spam
│   │       ├── detect_language_tool.py
│   │       ├── translate_tool.py
│   │       ├── llm_spam_check_tool.py
│   │       ├── read_tool.py
│   │       ├── azure_doc_intelligence_tool.py
│   │       ├── claude_vision_tool.py
│   │       └── business_rules_eval_tool.py   # Stage 3 KB business_rules evaluator (safe AST)
│   ├── kb_seeds/
│   │   ├── intent_definitions_v2.py          # Per-intent schema (category/keywords/sender_patterns/exceptions/regions) + 5 first-class intents added in v1.1 TASK-1
│   │   ├── outlook_rules.py                  # v1.1 TASK-2 — 6 deterministic rules
│   │   ├── routing_rules.py                  # v1.1 TASK-5 — disty + magic-SKU rules
│   │   ├── spam_heuristic_rules.py
│   │   ├── language_heuristic_rules.py
│   │   ├── intent_confidence_rubric.py
│   │   ├── language_confidence_rubric.py
│   │   ├── decision_confidence_rubric.py
│   │   ├── reconcile_checks.py
│   │   └── translation_glossary.py
│   ├── routes/
│   │   ├── emails.py
│   │   ├── pipeline.py             # GET /api/pipelines/{id} — exposes v1.1 fields
│   │   ├── threads.py
│   │   ├── hitl.py
│   │   ├── trace.py
│   │   ├── analytics.py            # /api/analytics/summary + /api/analytics/ops_log + /api/analytics/ops_log.csv
│   │   ├── feedback.py
│   │   ├── seed.py
│   │   ├── data.py
│   │   ├── docs.py
│   │   ├── kb.py                   # /api/kb/{namespace} + /{namespace}/{key} + reset + seed
│   │   ├── email_accounts.py       # /api/email-accounts + folder-map PATCH
│   │   ├── integrations.py
│   │   ├── learning.py
│   │   └── test_corpus.py          # v1.1 TASK-7 — labelled regression suite
│   └── services/
│       ├── imap_client.py          # IMAP poller + .msg unrolling (v1.1 TASK-8)
│       ├── imap_back_stamp.py      # COPY+EXPUNGE — simulated by demo lock
│       ├── email_outbound.py       # SMTP — blocked by demo lock
│       ├── email_thread.py         # Thread walker + pick_first_valid_fragment (v1.1 TASK-3)
│       ├── salesforce.py
│       ├── salesforce_cases.py     # Case CRUD + v1.1 TASK-4 helpers (find_by_po_or_wo, attach_email_to_case, chatter_notify_owner [demo-locked], update_case_status)
│       ├── salesforce_seed.py
│       ├── sharepoint.py
│       ├── servicenow.py
│       ├── openai_client.py
│       └── tunnel.py               # Cloudflared quick tunnel auto-start
├── requirements.txt                # extract-msg added in v1.1 TASK-8
├── start_backend.bat               # Bakes OUTBOUND_EMAIL_ENABLED=0 + BasicAuth creds
└── data/
    ├── db/app.db                   # SQLite
    ├── uploads/                    # Inbound attachments
    └── outputs/                    # Generated SOA/Invoice/WO/Cal Cert PDFs
```

### Frontend
```
frontend/
├── src/
│   ├── App.tsx                     # Routes — includes /test-corpus (v1.1 TASK-7)
│   ├── api.ts                      # All API client + types (testCorpusApi added in v1.1 TASK-7)
│   ├── hooks/useTheme.ts
│   ├── components/
│   │   ├── Layout.tsx              # Header + sidebar nav (includes Test Corpus in v1.1)
│   │   └── ui.tsx                  # Apple-style primitives: Surface, Section, Field, Button, Chip, Segmented, PageHeader
│   ├── pages/
│   │   ├── Inbox.tsx               # MODIFIED in latest turn — connected mailbox list stays, Add-mailbox button removed (deferred to Settings)
│   │   ├── Trace.tsx
│   │   ├── Hitl.tsx                # CSR Playbook detail screen + new CCC header card (v1.1 TASK-4 spec)
│   │   ├── Analytics.tsx
│   │   ├── OpsDashboard.tsx        # /ops route — flat one-row-per-email view
│   │   ├── KnowledgeBase.tsx       # Tabs per namespace
│   │   ├── Learning.tsx            # Combined feedback + learning hub
│   │   ├── TestCorpus.tsx          # v1.1 TASK-7 — corpus runs + results dashboard
│   │   ├── Settings.tsx
│   │   ├── settings/Integrations.tsx
│   │   ├── settings/Connections.tsx # IMAP mailbox add/manage + folder-map editor (v1.1 TASK-8 spec)
│   │   ├── SolutionDoc.tsx
│   │   └── SolutionOverview.tsx
│   └── index.css                   # Apple-style tokens (--ease-spring, --elev-resting/raised/floating)
├── public/
│   ├── zbrain-logo.svg
│   └── zbrain-logo-dark.svg
└── dist/                           # Production build, served by FastAPI static mount
```

---

## 3. The 6-stage pipeline in detail

### Stage 0 — Pre-AI Outlook rules (v1.1 TASK-2)

- Engine: [pre_intake.py](backend/app/agents/pre_intake.py)
- Walks KB `outlook_rules` namespace in priority order. First match wins.
- Predicate kinds: `subject_contains`, `subject_equals`, `body_contains`, `sender_equals`, `sender_contains`, `sender_domain`, `regex_subject`, `regex_body`.
- 6 default rules seeded: `outlook.undeliverable` (priority 10), `outlook.auto_reply` (20), `outlook.brazil_tax` (30), `outlook.kso` (40), `outlook.collections` (50), `outlook.portal_admin` (60).
- `actionable_exception=True` means the rule is suppressed if the body has a directive verb (please, kindly, ship, cancel, process, etc.) — UNLESS `severity="hard_block"` (KSO + UNDELIVERABLE), which fires regardless.
- If matched: `ctx.intake.intent` is set directly, Stage 1 LLM is skipped, the existing terminal-intent short-circuit handles the redirect.
- The orchestrator wires this BEFORE Stage 1 — see `orchestrator.py` lines 85-120 (look for `=== v1.1 TASK-2 START ===`).

### Stage 1 — Intake & Classification (7 sub-steps)

1. **1.2** Heuristic spam pre-screen (KB regex rules)
2. **1.3** Light attachment extraction (max 3 pages for Stage 1)
3. **1.4** Language detection (heuristic + LLM agreement check)
4. **1.5** Translate to English (skipped if EN). Per-source breakdown (body + each attachment separately) shown in trace.
5. **1.6** LLM spam check (on translated body)
6. **1.7** Classify intent (OpenAI strict JSON Schema, KB-driven prompt). Region filter applied (v1.1 TASK-6).
7. **1.7a** Override-pass (v1.1 TASK-3 prereq + v1.1 TASK-B3) — second LLM pass with global override book; can revise intent.
8. **1.7b** Detect CSR override (v1.1 TASK-10 / B10) — LLM micro-step flagging internal-staff override instructions in forwarded emails.
9. **1.7c** Shadow classifier (v1.1 TASK-9) — logged-only third pass when KB `shadow_classifier.config.enabled=True`.

### Stage 2 — Document Extraction & Enrichment

- **2.1** Full OCR (Azure DocIntelligence or Claude vision)
- **2.2** Schema-driven structured extraction (per-intent schema from KB)
- **2.3** Salesforce customer match (SOQL: Email → Contact → Account)
- **2.4** Intent-aware enrichment SOQL
- **2.5** Reconcile checks (cross-system validation — KB `reconcile_checks` namespace, 12 default checks)

### Stage 3 — Decision & Confidence Scoring

- **3.0** v1.1 TASK-4 — Existing-CCC lookup. SOQL by PO#/WO# on SF Case. Branch on status:
  - `Cancelled` → `ccc_action="new"`
  - `Closed` → `ccc_action="clone_change_order"`
  - everything else (`Awaiting Customer-*`, `Awaiting Internal-*`, `In Progress`, `Assigned`, `New`, `Continue Processing`, `Working`) → `ccc_action="update"`
- **3.0b** v1.1 TASK-5 — Routing resolver. KB `routing_rules` namespace. Predicates: `csr_override`, `extracted_country_not_in`, `subject_or_body_contains`, `any_sku_starts_with`, `sender_contains`, `po_number_starts_with`, `customer_name_in`.
- **3.1** Confidence formula (KB-driven rubric) — base + weighted signals + floor caps
- **3.2** Business rules (KB `business_rules` namespace — safe AST evaluator with predicate helpers like `days_until`, `regex_match`, `len`)
- **3.3** Final tier — L4_AUTO (≥0.95) / L3_ONE_CLICK (≥0.80) / L2_HITL (<0.80). CSR override force-HITL (v1.1 TASK-10) can drop tier to L2 regardless of confidence.

**4-gate confidence model** (per RFP Q&A call, 2026-05-08):
- Gate 1: Classification (did Stage 1 identify the intent?)
- Gate 2: Extraction (did Stage 2 extract every required field per schema?)
- Gate 3: Entity Resolution (did Stage 2.3 find the matching SF record? binary)
- Gate 4: Action Feasibility (can Stage 4 actually execute with what we have?)
- Composite = `min(g.score for g in 4 gates)`, `tier_driver` = lowest gate name
- Surfaced in `decision.confidence_gates` JSON in the pipeline response.

### Stage 4 — Execute

- v1.1 TASK-4 branches on `ccc_action`:
  - `update` → attach email to existing SF Case (ContentVersion + ContentDocumentLink) + Chatter @-mention (Chatter blocked by demo lock — returns `simulated=True`)
  - `clone_change_order` → records intent only (demo skips actual SF clone)
  - `new` → existing path (creates new SF Case)
- Quote feature gated by `_quote_enabled(sf)` probe — disabled in our SF dev org
- Order TotalAmount is read-only in SF — kept in Description string
- Order Status is restricted picklist — raw statuses mapped to Draft / Activated

### Stage 5 — Communicate

- Drafts reply in detected language (per-language translation glossary KB)
- Attaches synthetic SOA PDF
- Writes CommunicationLog row with `delivery_status="blocked_by_demo_lock"` (per hard rule)

### Stage 6 — Continuous Learning

- Hooks for feedback collection. Pairs with `/learning` page.

---

## 4. Database schema (selected)

```
pipelines
├── id, email_id, ccc_request_id, salesforce_case_id, started_at, finished_at
├── intent, language, confidence, autonomy_tier, status (running/awaiting_hitl/completed/discarded/rejected)
├── customer_match, extracted, reconcile, decision, execution, reply (all JSON)
├── suggested_fix (JSON)
├── error (text)
├── existing_case_id, existing_case_status, ccc_action, duplicate_detected   ← v1.1 TASK-4
├── routing_target, routing_basis                                              ← v1.1 TASK-5
└── shadow_classification (JSON)                                               ← v1.1 TASK-9

emails
├── id, received_at, from_address, subject, body, language_hint, attachments (JSON)
├── status (new/processing/awaiting_hitl/processed/discarded/rejected/redirected ← v1.1 TASK-1)
├── customer_id, pipeline_id (back-pointer)
└── account_id, message_id, in_reply_to, email_references                      ← thread headers

email_accounts
├── id, provider, email_address, label
├── imap_host, imap_port, use_ssl, username, password_enc
├── folder, sync_interval_sec, is_active, last_synced_at, last_uid_seen
├── last_error, last_error_at, messages_imported
├── category_folder_map (JSON — per-category folder routing)
└── region (default "GLOBAL" — AMS/EMEA/APAC/JP/GLOBAL)                        ← v1.1 TASK-6

knowledge_rules
├── id, namespace, key, label, description
├── body (JSON — what operators edit), default_body (JSON — last-seeded shape)
└── version, updated_at, updated_by

communication_logs
├── id, customer_id, pipeline_id, order_id
├── direction (inbound/outbound), channel (email), subject, body
├── intent, autonomy_tier, sent_by, csr_action
└── delivery_status, delivery_error, provider_message_id, sent_via_account_id

pipeline_executions  (thread-level idempotency log)
├── id, thread_root_message_id, action, args_hash
└── pipeline_id, email_id, result (JSON), succeeded, created_at

test_cases / test_runs / test_run_results  ← v1.1 TASK-7
```

All schema changes are applied via `apply_lightweight_migrations()` in [db_migrate.py](backend/app/db_migrate.py) — idempotent ADD COLUMN per ALTER. New tables via `Base.metadata.create_all()` on startup.

---

## 5. KB namespaces (all KB-tunable from /kb)

| Namespace | Purpose | Default seed count |
|---|---|---|
| `intent` | 18 intent definitions (13 original + 5 new in v1.1 TASK-1: kso, collections, portal_admin, brazil_tax, undeliverable). Each row has v2 schema: category/track_hint/priority/regions/description/keywords/sender_patterns/examples_positive/examples_negative/exceptions/exclusions. |
| `outlook_rules` | 6 deterministic pre-AI rules | v1.1 TASK-2 |
| `routing_rules` | 6 routing rules + 3 reference data rows (US/CA disty list, LAR disty list, magic-SKU table) | v1.1 TASK-5 |
| `shadow_classifier` | 1 config row (default `enabled=False`) | v1.1 TASK-9 |
| `extract_schema` | Per-intent extraction schemas |
| `business_rules` | Stage 3 caps + warnings (safe AST evaluator) |
| `spam_heuristic` | ~50 SpamAssassin/SwiftFilter regex rules |
| `language_heuristic` | Heuristic language rules + keyword lists |
| `intent_confidence_rubric` | Per-rule deltas for intent confidence |
| `language_confidence_rubric` | Same shape, per-language overrides |
| `decision_confidence_rubric` | Stage 3 weighted_signal + floor_cap rules |
| `reconcile_checks` | 12 default Stage 2.5 checks (per_line + per_total scopes) |
| `translation_glossary` | Per-language Keysight-specific terminology (EN/ES/JA, 35 terms) |
| `translation` | (Legacy translation rules) |

Operators edit any field in /kb without code changes. The next pipeline picks up the new shape — `kb.intake_intent_rules()` and friends re-read from DB on every call.

---

## 6. Auth + deployment

- **Production build:** `cd frontend && npx vite build` → `frontend/dist/`
- **Backend serves dist** via StaticFiles mount at `/` + SPA fallback (`main.py:121-134`)
- **HTTP Basic Auth gate** wraps everything (v1.0): [basic_auth.py](backend/app/middleware/basic_auth.py)
  - Env vars: `APP_BASIC_AUTH_USER`, `APP_BASIC_AUTH_PASS` (both required)
  - Exempt: `/api/health`, `/api/ready`
  - Default creds (in start_backend.bat): `keysight` / `zbrain-demo-2026`
  - Browser native prompt — no React login screen
- **Cloudflared quick tunnel** auto-starts on backend lifespan: [tunnel.py](backend/app/services/tunnel.py)
  - URL: `https://<random>.trycloudflare.com` — **rotates on every backend restart**
  - Binary at `backend/bin/cloudflared.exe`
  - URL logged to `backend/backend.out.log` — grep for `trycloudflare`
- **Restart pattern** (PowerShell):
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  Start-Sleep -Seconds 2
  $env:OUTBOUND_EMAIL_ENABLED = "0"
  $env:APP_BASIC_AUTH_USER = "keysight"
  $env:APP_BASIC_AUTH_PASS = "zbrain-demo-2026"
  Set-Location "C:\Users\Rituraj\keysight-salesops-demo\backend"
  Start-Process python -ArgumentList "-m","uvicorn","app.main:app","--port","8000","--host","127.0.0.1" `
    -WindowStyle Hidden `
    -RedirectStandardOutput backend.out.log -RedirectStandardError backend.err.log
  ```

---

## 7. v1.1 work — what was built in this cycle

### Rollback convention

- Every block wrapped with `# === v1.1 TASK-N START ===` / `# === v1.1 TASK-N END ===` (Python) or `// === v1.1 TASK-N START/END ===` (TSX/TS)
- Single-line additions get a trailing `# === v1.1 TASK-N ===` marker
- Grep `v1.1 TASK-N` (replace N with task number) to find every block for that task
- [v1.1_CHANGELOG.md](v1.1_CHANGELOG.md) is the ledger — lists every file, every block, every DB migration column, every KB seed

### Task summary

| Task | Status | What it does | Key files |
|---|---|---|---|
| TASK-1 | ✅ | 5 new first-class intents (kso/collections/portal_admin/brazil_tax/undeliverable). Maps to prior POC 9-class taxonomy. Terminal intents short-circuit pipeline; redirect logged as `would_route_to`. | config.py, intent_definitions_v2.py, intake.py, orchestrator.py, imap_back_stamp.py, emails.py, kb.py |
| TASK-2 | ✅ | Pre-AI deterministic Outlook rules. Stage 0 runs BEFORE Stage 1 LLM. 6 rules seeded. Match → short-circuit, no LLM call. | outlook_rules.py (new), pre_intake.py (new), kb.py, orchestrator.py |
| TASK-3 | ✅ | Empty-fragment thread pre-processing. `pick_first_valid_fragment` walks newest-first, skips CAUTION banners / FYI wrappers. | email_thread.py, intake.py (build_user_prompt) |
| TASK-4 | ✅ | Existing-CCC status branch. SF lookup by PO#/WO# → branch on Case status (Cancelled / Closed / 7 awaiting-* statuses). Chatter @-mention demo-locked. | salesforce_cases.py, stage3_decide_agent.py, stage4_execute_agent.py, models.py (4 new Pipeline cols), db_migrate.py, pipeline.py route |
| TASK-5 | ✅ | Distributor list + magic-SKU routing. 6 routing rules + 3 reference rows. Mouser → AMFO_Disty/Rental, non-US/CA → EXPORT_TEAM_QUEUE, Z-prefix SKU → SOW_TEAM_QUEUE. | routing_rules.py (new), routing_resolver.py (new), kb.py, stage3_decide_agent.py, models.py (2 new Pipeline cols) |
| TASK-6 | ✅ | Region-aware intent filtering. `_build_system_prompt(account_region=...)` filters intent menu by `regions` field. | intake.py, classify_intent_tool.py, models.py (EmailAccount.region) |
| TASK-7 | ✅ | Test-corpus regression page. 7 endpoints + frontend page at `/test-corpus`. Labelled emails + run-results dashboard mirroring prior POC's "Initial Pass / Failed / Post-Fix Pass / Still Failed" buckets. | test_corpus.py (new route), TestCorpus.tsx (new page), models.py (3 new tables), api.ts, Layout.tsx, App.tsx |
| TASK-8 | ✅ | `.msg` attachment unrolling. `extract-msg==0.55.0` added. IMAP fetcher unrolls inner subject/body/attachments → appended to parent body as `--- forwarded message (.msg: ...) ---`. | imap_client.py, requirements.txt |
| TASK-9 | ✅ | Shadow classifier slot. Third LLM pass, output logged-only. Default `enabled=False`. | shadow_classifier_tool.py (new), stage1_intake_agent.py, kb.py, models.py (Pipeline.shadow_classification) |
| TASK-10 (a.k.a. B10) | ✅ | CSR-instruction override detection. LLM micro-step at Stage 1.7b. `{has_override, override_kind, override_intent, override_track, override_team, override_instruction, reasoning, confidence}`. force_hitl/do_not_auto/route_to_team forces tier=L2_HITL in Stage 3. | detect_csr_override_tool.py (new), stage1_intake_agent.py, stage3_decide_agent.py |
| B5/4-gate | ✅ | 4-gate confidence model. `_build_4_gate_confidence` helper in decide.py returns gates dict. Surfaced in `decision.confidence_gates`. | decide.py (run_decide) |
| B3 | ✅ | Two-stage classifier — Context-pass (existing classify_intent) + Override-pass (new tool applying global override book). | override_pass_tool.py (new), stage1_intake_agent.py |
| B8 | ✅ | IMAP back-stamping + folder-map UI. COPY+EXPUNGE per category (currently simulated by demo lock). | imap_back_stamp.py, email_accounts.py route, Connections.tsx |
| B9 | ✅ | Telemetry ops dashboard. `/ops` route. CSV export at `/api/analytics/ops_log.csv`. | analytics.py, OpsDashboard.tsx (new) |

### Inbox page edit (just before this handover was requested)

- User instruction: "don't show connected inboxes in the inbox" — then clarified "I meant add mailbox button" + "show the connected email list ofc"
- Action: removed all 3 "+ Add mailbox" / "+ Connect a mailbox" / "Connect Gmail / Outlook" buttons from [Inbox.tsx](frontend/src/pages/Inbox.tsx). Kept the connected-mailbox list. Replaced empty-state CTAs with `navigate("/settings/connections")` link.
- Verified: `npx tsc --noEmit` clean, `npx vite build` clean (313 modules, 707kB / 199kB gzip).
- `showAdd` state still exists but is now never set to true — the AddAccountModal is dead code. Safe to ignore until cleanup pass.

---

## 8. The current pending task

**Build the AS-IS Process SOP document** at `C:\Users\Rituraj\keysight-salesops-demo\AS_IS_PROCESS_SOP.md`.

### What the user asked for (verbatim)

> "I'm gonna provide you again with the RFP Excel sheet as well as the POC specific work, which we have done, the folder of the POC. What I need you to do is understand end to end process, and then I am also gonna provide you with the transcript of what the call which we had for the clarifying questions. Based on that, I need you to create the end to end AS-IS workflow, and then we will look into understanding, are we able to solve each of those issues? So the idea is that we will need the complete as is workflow in as much detail as possible. What does that mean is you need to be looking into all the RFP sheets, for different content pieces, as well as the diagrams. There are multiple diagrams into it. So you should be looking into that. You should also be looking into the POC specific content where we did, like, one part of the POC, which would also provide you some context with which you can actually make the parent AS-IS process much, much better. And then from the transcript also, you should be able to understand few things. So this needs to be a complete SOP around how the work is happening. So it needs to be a very professional document around the as is process. Based on that, we will then write the to be process where we will include all the work which we have done for each of those steps and how we are automating it, and then we will be mapping it end to end."

### Source materials inventory (all already on disk)

| Source | Path | Already extracted? |
|---|---|---|
| RFP Excel (canonical) | `C:\Users\Rituraj\Downloads\Keysight-RFP\SalesOps - RFP.xlsx` | YES — per-sheet text dumps at `C:\Users\Rituraj\rfp_sheets\` |
| Prior POC — ISC WO RTK narrative | `C:\Users\Rituraj\Downloads\keysight poc\ISC WO RTK.txt` | TXT readable directly — full content already in conversation context (handover agent should re-read) |
| Prior POC — ISC WO RTK PDF (mirror of TXT with diagrams) | `C:\Users\Rituraj\Downloads\keysight poc\KeySight-ISC WO RTK-080526-101615.pdf` | PDF — Read tool fails on this Windows box (no pdftoppm); use Python pypdf or pdfplumber via Bash |
| Prior POC — Sales PO Std Process & Change Order | `C:\Users\Rituraj\Downloads\keysight poc\Sales PO Std Process & Change order (1).pdf` | 16-page PDF — same extraction issue. RESEARCH_BRIEF.md already summarizes key bits (disty list, magic SKUs, 9-class taxonomy, override book rules) |
| Prior POC — Current Outlook Rules narrative | `C:\Users\Rituraj\Downloads\keysight poc\Current Outlook Rules_Narratives (1).pdf` | PDF — verbatim source for the 6 deterministic rules already in `kb_seeds/outlook_rules.py` (TASK-2) |
| Prior POC — 109-email comparison report | `C:\Users\Rituraj\Downloads\keysight poc\FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx` | XLSX — source for TASK-7 test corpus sample data |
| Prior POC — Data request workbook | `C:\Users\Rituraj\Downloads\keysight poc\Data request - 2. Front Office Request-...\Front Office Request - Data Request.xlsx` | Not yet read — likely SF schema / Account fields requested by Keysight |
| ZBrain workflow JSON exports | `C:\Users\Rituraj\Downloads\Agents\KS FO Agent.json` and `KS FO FLOW.json` | 260KB each. Contains the running production agent — 25KB override prompt with 27 numbered rules. RESEARCH_BRIEF.md has line citations |
| RFP Q&A transcript | Pasted into the most recent user message (this handover doc captures it below) | Already in conversation context, also in this doc § 9 |

### Concrete next-step plan for the handover agent

1. Read `RESEARCH_BRIEF.md` end-to-end — it already synthesizes a lot of the POC content with line citations. Section 4 (Override rule book) and Section 7 (Comprehensive gap analysis) are particularly relevant.
2. Read `BUILD_QUEUE.md` end-to-end — has the TASK-1 through TASK-9 work plan with verbatim keyword lists, schemas, and acceptance criteria. The KB seeds reproduced there are CANONICAL — they are what the prior POC actually uses in production.
3. Re-read the transcript content in § 9 below — the RFP Q&A call has critical clarifications (4 gates, regions, governance, languages, volume, magic SKUs).
4. Use Bash + Python with `pypdf` (already available — confirmed in this session) to extract text from the 3 PDFs in `Downloads/keysight poc/`. If pypdf fails, try `pdfplumber`. **Do NOT rely on the Read tool for PDFs on this Windows box — pdftoppm is missing.**
5. Read each RFP sheet dump in `C:\Users\Rituraj\rfp_sheets\` directly with the Read tool (they're plain txt).
6. Write the document. Structure should be:
   1. **Executive summary** — what the SalesOps front-office process is, who runs it, scale (500K+ emails/year, 600-700 users globally, 80-90 concurrent), system landscape (Salesforce, Oracle ERP, ServiceNow, Outlook + 50 mailboxes, SP doc storage)
   2. **Roles & RACI** — FCNV user (Front-office CNV operator), CSR / CTA, FE (Field Engineer), Customer, Superuser
   3. **Inputs** — inbound email envelope, attachments (PDF / DOCX / XLSX / TIFF / Image / HTML / Text / .msg), 50 inbox mailboxes per region
   4. **Process narrative — Agent #1.3 (Email sorting / classification)** — verbatim from ISC WO RTK.txt + Outlook Rules PDF
   5. **Process narrative — Agent #2 (CCC Request creation)** — full verbatim from ISC WO RTK.txt
   6. **Process narrative — Agent #3 (CCC Request assignment)** — full verbatim from ISC WO RTK.txt
   7. **Process narrative — Sales PO standard process** — verbatim from Sales PO PDF
   8. **Process narrative — Change Order flow** — verbatim from Sales PO PDF
   9. **Special subtypes** — Stock Rotation, Rebates, eBiz, SOW, Prebuild, Amendment, Cancellation, Change Quantity, Duplicate PO, Confirm orders
   10. **Routing matrix** — by intent + region + customer-type (KSO / disty / direct / Brazil / Collections / Portal admin)
   11. **9-class taxonomy** — UNDELIVERABLE / AUTO_REPLY / BRAZIL_TAX / PORTAL_ADMIN / COLLECTIONS / KSO / ISC_WO_RTK / SALES_PO / OTHERS (strict scan order)
   12. **27-rule override book** — full enumeration (Rule 3, 3A, 7, 9, 13, 18A/B, 19, 20, 25 are highlighted in the brief; rest are in the ZBrain JSON step_17)
   13. **Existing CCC status branching matrix** — verbatim from ISC WO RTK + Sales PO PDF: New / Assigned / In Progress / Continue Processing / Awaiting Customer-CIA / Awaiting Customer-info / Awaiting Internal-FE / Awaiting Internal-System / Cancelled / Closed (10 statuses, 10 distinct actions)
   14. **Distributor partner lists** — US/CA (15 names) + LAR (22 names) — verbatim from Sales PO PDF p.6, 8-9
   15. **Magic SKUs** — CUSTOM PRODUCT / SOWDUMMY / EXPORTDUMMY routing semantics
   16. **Confidence / accuracy expectations** — verbatim from the transcript (4 gates) + the 109-email test corpus (96% post-fix accuracy claim)
   17. **Manual baseline today** — manual classification, manual SF entry, manual routing, no automation except some Outlook rules per region
   18. **Pain points & gaps** — derived from each step + transcript + RFP §202-206 (govt routing), §214-225 (governance), §239 (mailbox consolidation), §246 (manual baseline)
   19. **System integrations** — Salesforce (Cases, Accounts, Contacts, Quotes, Orders, ContentVersion, Chatter), Oracle ERP (via middleware / Web), Outlook (50 mailboxes), ServiceNow (reminders/follow-ups, escalation), Microsoft Purview (enterprise governance), SharePoint / Docnet (customer documents)
   20. **Out of scope (today, per transcript)** — agents in the controlled / government ecosystem (separate system entirely); only routing decisions cross over

### Important wording rules for the SOP document

- This is the **AS-IS** doc — describe how Keysight does things TODAY (manual, with some Outlook rules), NOT how our ZBrain demo automates it. The TO-BE doc comes later.
- Use **business language**, not engineering jargon. The audience includes Keysight stakeholders who may not be technical.
- Cite source line numbers / page numbers where verbatim quotes are pulled from (e.g., "ISC WO RTK.txt, Agent #2 step 6").
- Diagrams: the RFP Excel has them embedded in cells. The handover agent should mention "see RFP §X.Y diagram" rather than try to render them. If the agent has time, it can describe the flow textually.
- Don't reference ZBrain anywhere in the AS-IS doc — that's the TO-BE solution. AS-IS describes the **manual / Outlook-rules / current-state process** only.
- Tone: professional, comprehensive, pretend it's going to a Keysight VP.

---

## 9. RFP Q&A transcript — full content (read this carefully)

Date: 2026-05-08. Participants: Keysight team (CSR lead, IT lead) + LeewayHertz (Rituraj, Deepak, Manuj). Key questions answered:

### 9.1 Confidence scoring (Stage 3)

Keysight defines **4 distinct gates**, not a single weighted score:

1. **Classification** — Did the AI identify the intent correctly? (PO vs WO vs SO status etc.)
2. **Extraction** — Did the AI extract the schema-required fields from the email/attachments?
3. **Entity Resolution** — Did the AI find the matching SF record? (Binary — found or not found)
4. **Action Feasibility** — Can the AI actually execute the downstream action with what was extracted + resolved?

Keysight thinks of "confidence" as **accuracy per gate**, not a probability over historical data. The scope is per-transaction, not population-level. Each gate is independent — a low score on Gate 2 (missing fields) routes to review even if Gate 1 (classification) was 100%.

> "Accuracy is important to continue the rest of the process. If the accuracy is not there, then we have to do a human look-in." — Senthil

### 9.2 Regions

- **Americas, Europe, Asia-Pacific, Japan** are the primary lanes.
- Within APAC there are country-specific nuances (Japan field requirements).
- Globally they're moving toward a standardized process, but until then **region-specific fields and rules will be documented and applied**.
- **Example region rule (verbatim):** government customer emails arriving at a US mailbox — "the non-US citizen cannot read this email or route it to the right category" — agent must check citizenship attribute and route restricted-content emails to a different team.

### 9.3 Mailboxes

- **~50 mailboxes today**, region-segregated.
- Goal: consolidate to **1-2 mailboxes** eventually. **NOT 100% by end of this project** — partial consolidation expected.
- Until then: "transparent to the next step of the workflow" — agent reads all mailboxes, classification happens after.

### 9.4 CRM / ERP / Systems

- **Salesforce — global single instance** (no multi-region instances). CCC Requests live here.
- **Oracle ERP** — single instance, integrated via "Web" (likely middleware / Oracle Integration Cloud or similar).
- **ServiceNow** — NOT for the GenAI work itself. Used for reminder/follow-up workflow approval engines (Change Order approval routing). Keysight handles ServiceNow internally; vendor doesn't build GenAI on top of it.
- **Keysight Support Portal** — read-only lookups.
- **Customer fitting / spec storage** — internal document store (likely SharePoint / Docnet).
- **No other enterprise systems** in the agent's direct integration scope.

### 9.5 Translation

- Customer emails arrive in many languages. Internal systems are **not standardized to English**.
- Keysight has an existing **translation knowledge base** — vendor should reuse with modifications/additions for SalesOps-specific terminology (covered by our `kb.translation_glossary` namespace already).

### 9.6 Governance — two tiers

**Enterprise level:**
- **Microsoft Purview** (or hyperscaler equivalent) governs the entire agent portfolio.
- All agents managed through the Microsoft governance toolchain.

**Application level (per-agent):**
- RBAC / privilege rings
- Applicable existing policies
- SLO definitions
- Circuit-breaker policies
- MCP-tool scanning + connection control + prompt-injection prevention

The agent (Manuj) noted: "We are not there yet in that journey where we have everything defined there" — meaning Keysight hasn't fully defined the application-level governance for this agent, and the vendor's expectation is that ZBrain will be installed in the existing Azure environment with the existing governance toolchain.

### 9.7 Government / Restricted handling

- Government customer emails arrive at the **same shared inbox** as commercial mail.
- Agent must apply rules like: "non-US-citizen cannot read this email → route to dedicated box."
- **Citizenship-based routing** — not just keyword/domain-based KSO classification.
- Government customers have a different controlled system, but emails still come into the same place; agent decides routing.

### 9.8 Volume

- **530K emails/year** (cited in RFP)
- **600-700 users on the wider system** (CSR + adjacent roles)
- **80-90 concurrent users** across global time zones
- **Burst load** during quarter / year / month ends — customers ask for status, send escalations
- Stress test target: **100 emails/sec** capacity

### 9.9 Today's manual baseline

- **Classification = manual** today.
- **Validation = manual.**
- **Parsing = manual.**
- Some **regional Outlook rules** (e.g., "if Out of Office, exclude") exist — those are the 6 deterministic rules captured in TASK-2.
- **No other automation** in the current state.

### 9.10 Timeline / approach

- RFP / face-to-face / requirements phase happens now.
- Vendor selection + tool decision: post-RFP.
- After selection: **1-week (give or take) requirements lock**, then directly into design phase.
- **Agile sprints from there.** No long requirements-gathering phase — start with classification rules and iterate.

### 9.11 Customer documents / specs

- Stored in internal doc store (Docnet / SharePoint).
- API/integration is feasible via standard API calls.

### 9.12 Concurrency / portal users

- ZBrain UI is NOT customer-facing — only internal CSR / CTA users.
- HITL portal is a separate frontend that **calls ZBrain as an API**.
- ZBrain itself handles the email volume — portal usage is secondary.

### 9.13 Out of scope for this RFP

- Building a new customer-facing portal.
- Building a new ServiceNow workflow.
- Replacing Salesforce or Oracle.
- Handling the controlled / classified environment (separate system, only routing crosses over).

---

## 10. Known issues / gotchas

| Issue | Workaround |
|---|---|
| Read tool fails on PDFs (pdftoppm missing on this Windows box) | Use `python -c "from pypdf import PdfReader; ..."` via Bash. pypdf is installed and works. pdfplumber is also available. |
| `Bash` background tasks sometimes return empty output files (race condition) | Use synchronous Bash with explicit `python -c "..."` and pipe through `head`/`tail` to keep output bounded. |
| `cd` inside Bash can trip the harness if working dir conflicts with the project root | Use absolute paths or `Set-Location` in PowerShell |
| Cloudflare quick tunnel URL rotates on every backend restart | After restart, grep `trycloudflare` in `backend/backend.out.log` to get the new URL. To get a stable URL would require a Cloudflare account + a domain + a named tunnel (out of scope). |
| ngrok paid option mentioned by user (~$8/mo) | If user wants stable URL eventually, ngrok with a fixed subdomain is the simplest path. |
| The SF dev org has no `PO_Number__c` / `WO_Number__c` custom Case fields | TASK-4's `find_by_po_or_wo` soft-fails to `None` → orchestrator falls back to `ccc_action="new"`. Logged but non-fatal. Adding the SF custom fields would unlock the full TASK-4 behavior. |
| Quote feature is OFF in our SF dev org | All Quote field creation gated behind `_quote_enabled(sf)` probe. |
| Order TotalAmount read-only in SF | Stuffed into Description string. |
| Order Status restricted picklist | Raw statuses mapped to Draft/Activated. |
| SOA_TEST_LAYOUT.pdf has no customer code | Skipped in SP backfill (known limitation). |
| Pipeline 80 (and similar) — sender `orderinbox@leewayhertz.com` causes Stage 2 SF match to fail → routes to HITL before Stage 3 | Expected — emails seeded with `account_id=None` aren't matched. The new Inbox emails (from real customer domains) will match Salesforce Contacts/Accounts and Stage 3 will run. |
| `showAdd` state in [Inbox.tsx](frontend/src/pages/Inbox.tsx) is now dead code (latest edit removed all triggers) | Safe to leave; cleanup pass later. |

---

## 11. How to verify the current state

```bash
# 1. Confirm backend is up and Basic Auth works
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/                            # → 401
curl -s -o /dev/null -w "%{http_code}\n" -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/   # → 200
curl -s http://127.0.0.1:8000/api/health                                                     # → {"ok":true}

# 2. KB seed counts (after a restart that re-runs seed_defaults)
curl -s -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/api/kb/intent | python -c "import sys,json; print(len(json.load(sys.stdin)))"
# → 18 (13 original + 5 from TASK-1)
curl -s -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/api/kb/outlook_rules | python -c "import sys,json; print(len(json.load(sys.stdin)))"
# → 6 (TASK-2)
curl -s -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/api/kb/routing_rules | python -c "import sys,json; print(len(json.load(sys.stdin)))"
# → 9 (TASK-5: 6 routing rules + 3 reference rows)

# 3. v1.1 fields on pipeline detail
curl -s -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/api/pipelines/87 | python -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ['existing_case_id','ccc_action','duplicate_detected','routing_target','routing_basis','shadow_classification']})"

# 4. Test-corpus
curl -s -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/api/test-corpus/cases | python -c "import sys,json; print(len(json.load(sys.stdin)))"
curl -s -u "keysight:zbrain-demo-2026" http://127.0.0.1:8000/api/test-corpus/runs | python -c "import sys,json; print(json.load(sys.stdin))"

# 5. Frontend build clean
cd C:/Users/Rituraj/keysight-salesops-demo/frontend && npx tsc --noEmit          # → no output
cd C:/Users/Rituraj/keysight-salesops-demo/frontend && npx vite build            # → 313 modules, 707kB / 199kB gzip

# 6. Find every v1.1 block (rollback grep)
cd C:/Users/Rituraj/keysight-salesops-demo
grep -rn "v1.1 TASK-1 " backend/ frontend/        # all TASK-1 blocks (note trailing space)
grep -rn "v1.1 TASK-N START" backend/ frontend/   # all start markers
```

---

## 12. Open questions for the user (not blocking)

1. **AS-IS SOP audience** — internal LeewayHertz only, or will this be shared with Keysight? Tone implications.
2. **SF custom fields** (`PO_Number__c`, `WO_Number__c` on Case) — should the handover agent add them to the SF dev org so TASK-4 can be fully demonstrated, or stay soft-fail-only?
3. **Diagrams in the AS-IS doc** — text description only, or should we generate ASCII / Mermaid diagrams? (The RFP has embedded image diagrams that we can't easily extract.)
4. **Translation glossary expansion** — the RFP mentions "reuse existing Keysight translation knowledge base." Has Keysight shared their actual glossary file yet, or are we using only the synthetic 35-term glossary we seeded?
5. **Government / restricted handling** — beyond the citizenship-based routing rule discussed in transcript §9.7, are there ITAR/EAR/ECCN-specific keyword filters Keysight wants in the pre-AI layer? (Currently captured generically in the KSO intent's keywords array.)

---

## 13. Bookkeeping — files to update as v1.1 work continues

- [v1.1_CHANGELOG.md](v1.1_CHANGELOG.md) — append an entry for each new task with: Files added, Files modified, DB migrations, KB seeds, Dependencies, Acceptance criteria
- This HANDOVER.md — keep § 7 (Task summary) and § 8 (Pending task) in sync with reality
- [CLAUDE.md](CLAUDE.md) — only update if a hard rule changes (rare)

---

## 14. Quick orientation for the new agent — 10-minute warm-up

1. Read this entire HANDOVER.md (you're here)
2. Read [CLAUDE.md](CLAUDE.md) for branding + hard rules
3. Skim [v1.1_CHANGELOG.md](v1.1_CHANGELOG.md) for what's already shipped
4. Read [RESEARCH_BRIEF.md](RESEARCH_BRIEF.md) sections 4 + 7 (override rule book + gap analysis)
5. Read [BUILD_QUEUE.md](BUILD_QUEUE.md) sections TASK-1 through TASK-3 (most detailed examples of the build pattern)
6. Look at [intent_definitions_v2.py](backend/app/kb_seeds/intent_definitions_v2.py) to understand the KB schema
7. Look at [orchestrator.py](backend/app/agents/orchestrator.py) lines 85-200 to see how Stage 0 (TASK-2) and Stage 1 terminal-intent (TASK-1) wire together
8. Restart backend with the PowerShell snippet in § 6 if not already running
9. Open the tunnel URL (grep `trycloudflare` in `backend/backend.out.log`) → log in with `keysight` / `zbrain-demo-2026` → walk through Inbox, Trace, HITL, KB, Test Corpus
10. Start the pending task in § 8 — compose `AS_IS_PROCESS_SOP.md`

When in doubt, default to:
- v1.1 markers on every code block
- DEMO_TRANSMIT_LOCKED stays on (record "would_route_to", don't transmit)
- ZBrain branding in all user-visible strings (never "Claude")
- Append to v1.1_CHANGELOG.md per task — don't rewrite history

Good luck.
