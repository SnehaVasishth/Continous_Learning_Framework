# Session handoff — parallel work coordination

The user is running TWO Claude Code sessions in parallel to make faster progress on the Keysight SalesOps demo. **Sessions don't share live context** — this file tells each session what the other is doing so we don't step on each other.

## Active sessions

### Session A — Stage 1 / agent fabric / KB infrastructure (this session)

**Currently owns:**
- `backend/app/agents/**` — all agent + tool code
  - especially `agents/intake.py`, `agents/stage1_intake_agent.py`, `agents/llm.py`, `agents/base.py`
  - `agents/tools/*` — every tool: classify_intent, detect_spam, detect_language, translate, llm_spam_check, azure_doc_intelligence, _pdf_convert
- `backend/app/kb.py` and `backend/app/kb_seeds/**` — KB namespace registry, seed data
- `backend/app/services/tunnel.py` — cloudflared auto-tunnel
- `backend/app/services/secrets.py` (Fernet)
- `backend/app/main.py` lifespan (reseed/tunnel hooks)
- `backend/app/routes/seed.py` — seed reset (must reseed KB)
- `backend/app/routes/kb.py` — KB CRUD endpoints
- `backend/app/routes/trace.py`
- `frontend/src/pages/Trace.tsx` — Stage 1 sub-step rendering, drill-down components, RulesEvaluatedTable, AttachmentsBreakdown
- `frontend/src/pages/KnowledgeBase.tsx` — KB Settings UI (all 6 namespaces)
- `SOLUTION.md` — keeps the architectural log + ADRs current

**Working on right now:**
- Stage 2 v2 architecture (just shipped): 4 sub-steps (2.1 Document extraction → 2.2 Schema-driven extraction → 2.3 Customer identification → 2.4 Customer enrichment). Schema-driven extraction renamed from "LLM extraction" per user feedback; now uses OpenAI gpt-5.2 with `response_format=json_object` for guaranteed JSON parse. Customer match + Salesforce enrichment moved INTO Stage 2 (was a separate `enrichment` stage in the orchestrator).
- Intent-aware Salesforce queries: different SOQL templates per intent (orders+opportunities for trade, work-orders for SOM, etc.). Lives at `_ENRICHMENT_QUERIES` in `stage2_extract_agent.py`.
- Stage 2 UI in Trace.tsx still PENDING (sub-step rendering, KB schema visualization, extracted-fields table). Happy to hand this off to Session B once you're free — see "UI work available for handoff" below.

**DO NOT touch from Session B:**
- Anything under `backend/app/agents/`
- `backend/app/kb.py` or `backend/app/kb_seeds/`
- `frontend/src/pages/Trace.tsx`
- `frontend/src/pages/KnowledgeBase.tsx`
- `backend/app/services/tunnel.py`

---

### Session B — Email / inbox / synthetic data / IMAP (the new session)

**Suggested scope** (these are areas the user mentioned wanting to push on; tell Session B to start here):
- `backend/app/services/email_sync.py` — IMAP poller behavior, polling cadence, error handling
- `backend/app/services/imap_client.py` — IMAP connection, mailbox listing, attachment download, encoding fixes
- `backend/app/routes/emails.py` — `/api/emails` API (currently has limited filtering, no search by date/customer/intent)
- `backend/app/routes/email_accounts.py` — IMAP account CRUD, test-connection
- `backend/app/synthetic/catalog.py` and `backend/app/synthetic/generate.py` — generated email bodies, customer emails, attachment associations (THESE ARE OK to edit since the .example→realistic-domain swap is already done; new edits are fine)
- `frontend/src/pages/Inbox.tsx` (if it exists) — email list, filtering, search
- `frontend/src/pages/EmailAccounts.tsx` — IMAP config UI

**Cross-cutting (need coordination, ping the other session if you touch):**
- `backend/app/models.py` — DB schema (rare; only with a migration)
- `backend/app/db.py`
- `backend/app/main.py` (router registrations)
- `backend/app/config.py`
- The `/api/seed/reset` endpoint — Session A just changed this to also re-seed KB. Don't revert.

---

## Current state of the work (as of this handoff)

**Stage 1 v2 architecture (live):**
- 7 sub-steps: receive → heuristic-spam → light-extract → detect-language → translate → llm-spam → classify-intent
- detect_spam consumes `kb.spam_heuristic` (53 SpamAssassin/SwiftFilter rules)
- detect_language consumes `kb.language_heuristic` (13 rules, 4 tiers from stopwords-iso + lingua-py design)
- azure_doc_intelligence does format-aware routing: PDF → Lambda (Azure DocIntel), XLSX → openpyxl, DOCX → python-docx with auto-fallback to convert+Lambda when sparse
- cloudflared auto-tunnel at startup so AWS Lambda can reach localhost (binary at `backend/bin/cloudflared.exe`)
- classify_intent prompt rewritten with positive instructions + 4 worked examples; normalizer kept as a fallback safety net

**Synthetic data:** regenerated with realistic domains (`auroraauto.com`, `raytheon-elseg.com`, `tesserasemiconductor.com.tw`, etc.). Seed reset (`POST /api/seed/reset`) re-seeds both customer/email/quote data AND KB rules.

**Things still pending (Session A is working on these):**
- Verify normalizer notes drop to 0 with the trimmed prompt (in progress)
- KB UI tab additions for translation/spam_heuristic/language_heuristic (just added — needs visual test)

---

## How to use this handoff

When you start the second session, paste this into its first message:

> "Read SESSION_HANDOFF.md at the project root before doing anything. You are Session B (email/inbox/synthetic). Session A is concurrently working on Stage 1 agents + KB. Stay in your lane per that doc. If you must touch cross-cutting files, leave a comment in this handoff doc explaining what and why."

When either session does something that affects the other's scope, add a short note under "## Crossover events" below.

## UI work available for handoff to Session B (when free)

If Session B finishes the email/SMTP push and wants to take frontend work, here are concrete UI tasks that won't conflict with Session A's backend work:

### Stage 2 sub-step rendering in `frontend/src/pages/Trace.tsx`
Stage 1 has rich per-sub-step rendering with Input / Output / Activities sections; Stage 2 currently has nothing. The backend already emits everything you need:

- Sub-step events: `stage="extract"`, `kind="substep_start"` / `"substep_done"`, `data.substep` ∈ {"2.1","2.2","2.3","2.4"}
- Tool events: `kind="tool_end"`, `message` matches the tool name
- New tool: `schema_extract` (renamed from `llm_extract`) — its `data.data` carries:
  - `provider`, `provider_meta`, `prompt_system`, `prompt_user`, `provider_response_raw` — for the Activities drill-down
  - `kb_schema_key_used`, `kb_schema_intent`, `kb_schema_field_count`, `kb_schema_required_populated`/`required_count`, `kb_schema_fields[]` — for showing which KB schema drove this run
  - `extracted_fields` — display this as a labelled value table (po_number, quote_number, line_items[], etc.)
  - `validation_notes` — list of coercion/missing-field notes

**Suggested rendering plan:**
1. Add an `ExtractStageCard` component mirroring `IntakeStageCard`'s shape but with 4 sub-steps:
   - 2.1 → reuse the existing `AttachmentsBreakdown` component on the `azure_doc_intelligence` tool_end events for `stage="extract"` (same pattern as Stage 1.3 but with different events).
   - 2.2 → new component showing: KB schema header (key + intent + N fields), extracted_fields table, then Activities collapsibles for prompt_system, prompt_user, provider_response_raw.
   - 2.3 → entity_resolve_customer output + the salesforce_account_fetched event (matched name, basis, account fields).
   - 2.4 → list of SOQL queries with row counts and a drill-down per query showing the SOQL text + the records[] returned.
2. Wire `ExtractStageCard` into the StageNavStrip + main render so the existing Trace page shows it for `stage="extract"`.
3. Type-check with `npx tsc --noEmit -p .`.

### Other UI tasks Session A doesn't need to own (open for B):
- **HITL outbound delivery toast styling** — the toast you added when "Reply sent to <addr>" / "Send failed: <reason>" is good. Could grow into an inline status pill on the HITL row showing delivery_status (queued | sent | failed) once persisted.
- **Inbox filtering** — `/api/emails` currently returns all 92 with no filter. UI filter by intent / customer / language / date would make demo navigation easier.
- **Trace page "skipped because spam/out_of_scope" rendering** — when the pipeline short-circuits at intake, Stages 2-6 currently appear as ghost cards with no status. Worth showing them with an explicit "skipped — terminal intent at sub-step 1.7" label.

### Files Session A is currently editing (DO NOT touch from B):
- `backend/app/agents/stage2_extract_agent.py`
- `backend/app/agents/extract.py`
- `backend/app/agents/orchestrator.py`
- `backend/app/agents/tools/schema_extract_tool.py` (new, replaced llm_extract_tool.py)
- `backend/app/agents/tools/classify_intent_tool.py` + `intake.py` (Stage 1 prompt)
- `backend/app/services/openai_client.py` (new)
- `SOLUTION.md` (about to update with Stage 2 v2 ADR)

---

## Crossover events (chronological)

### 2026-05-07 — Session A: Stage 2 v2 + OpenAI strict JSON

**My-lane changes (Session A):**
- `backend/app/agents/extract.py` — `run_extract` now prefers OpenAI gpt-5.2 (`response_format=json_object`) when `OPENAI_API_KEY` is set; legacy Claude path remains as fallback. Returns `_provider`, `_provider_meta`, `_prompt_system`, `_prompt_user`, `_provider_response_raw` for trace surfacing.
- `backend/app/agents/tools/llm_extract_tool.py` — DELETED. Replaced by `schema_extract_tool.py` with class `SchemaExtractTool`, tool name `"schema_extract"`. Backwards-compat alias `LlmExtractTool = SchemaExtractTool` exported.
- `backend/app/agents/stage2_extract_agent.py` — fully rewritten as 4-substep flow with `substep_start` / `substep_done` trace events.
- `backend/app/agents/orchestrator.py` — REMOVED the customer_match block + the standalone `enrichment` stage that ran before Stage 2. Stage 2 now owns all of it via sub-steps 2.3 / 2.4. Pipelines created from now on will NOT have a separate `enrichment` stage in their event stream — `extract` is the only relevant stage for that work. Existing pipelines (1-12) retain the old shape.
- `backend/.env` — added `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-5.2`.
- `backend/requirements.txt` — added `openai==2.35.1`, `python-dotenv==1.0.1`.
- `backend/app/config.py` — added `TERMINAL_INTENTS = {"spam", "out_of_scope"}`, added `out_of_scope` to canonical INTENTS list, added intent description.

**Heads-up for Session B:**
- The orchestrator's pre-Stage-2 customer match is now MUCH cheaper — it just sets a seed-based hint from `email_row.customer_id` if present. The full SF customer match happens inside Stage 2 sub-step 2.3.
- Pipeline event stream no longer contains `stage="enrichment"` events for new runs. If your inbox UI was filtering trace events by stage, add `extract` to the filter where you'd previously checked for `enrichment`.

### 2026-05-07 — Session B: SMTP outbound from HITL

Goal: HITL approve actually sends a real reply through the connected Gmail account (was previously a mock that only logged "sent").

**Cross-cutting touches (heads-up for Session A):**
- `backend/app/models.py` — added columns:
  - `Email`: `account_id` (FK email_accounts.id), `message_id`, `in_reply_to`, `email_references`
  - `CommunicationLog`: `delivery_status`, `delivery_error`, `provider_message_id`, `sent_via_account_id`
- `backend/app/db_migrate.py` (new) — additive ALTER TABLE on startup; called from `main.py` lifespan after `create_all`. Idempotent. Add new columns here if you bolt on more.
- `backend/app/main.py` — calls `apply_lightweight_migrations(engine)` after `create_all`.
- `backend/app/routes/hitl.py` — `resolve()` now calls `email_outbound.send_reply()` on approve/edit_and_approve. Returns `{ok, delivery, recipient}` instead of just `{ok}`. Trace event message changed to include "reply sent via SMTP" / "send failed: …".

**My-lane new files / changes:**
- `backend/app/services/email_outbound.py` (new) — SMTP via stdlib smtplib. Reuses the IMAP app password. Provider presets: gmail → smtp.gmail.com:587 STARTTLS.
- `backend/app/services/imap_client.py` — captures `Message-Id`, `In-Reply-To`, `References`, sets `account_id` on incoming Email rows.
- `backend/app/routes/email_accounts.py` — added `POST /api/email-accounts/{id}/test-smtp`.
- `frontend/src/api.ts` — extended `HitlSummary.reply` and `resolveHitl` return type with delivery fields; added `emailAccounts.testSmtp`.
- `frontend/src/pages/Hitl.tsx` — toast on approve showing "Reply sent to <addr>" / "Send failed: <reason>".
- `frontend/src/pages/settings/Connections.tsx` — "✉ Test send" button per account.

**Backfilled** existing 92 emails with `account_id = 1` (the single active gmail account).

**Cloud notes** (still to do): `EMAIL_SECRET_KEY` env var must be pinned before deploy or the encrypted password stops decrypting. Outbound TCP 587 must be allowed.

---

### 2026-05-08 — Session B: Inbox filter fixes + SharePoint connection management

**Inbox filter bug fix (`backend/app/routes/emails.py` rewritten):**
- The intent / autonomy_tier filter was joining on `Email.pipeline_id == Pipeline.id`, but only ~5 of N pipelines have that back-pointer set. Switched to `Pipeline.email_id == Email.id` (canonical FK, set on every Pipeline) with a latest-per-email subquery.
- Added `GET /api/emails/counts` returning per-status counts.
- Frontend dropdown now shows counts inline (e.g. "Processed (0)") and adds a "Rejected" option that was missing.

**SharePoint integration management (new — parallel to Salesforce/ServiceNow):**
- `backend/app/models.py` — added `SharePointConnection` table (cross-cutting touch).
- `backend/app/services/sharepoint.py` — new module: token cache, whoami, test_connection, upsert/refresh, file ops (list/upload/download/delete).
- `backend/app/routes/integrations.py` — added `/sharepoint/{test,connect,status,refresh,disconnect,settings}` plus `/files`, `/files/upload`, `/files/{id}/download`, `/files/{id}` (DELETE).
- `frontend/src/api.ts` — `SharePointConnectBody`, `SharePointStatus`, `SharePointItem` types + `api.integrations.sharepoint` methods.
- `frontend/src/pages/settings/Integrations.tsx` — replaced the static SharePoint card with a real `SharePointTile` + `SharePointConnectModal`. Removed `sharepoint` from the `STATIC_CARDS` list.

**Session A coordination — one-line tool change (please make this when convenient):**

The existing `backend/app/agents/tools/sharepoint_fetch_doc_tool.py` reads creds from `os.environ`. To pick up creds from the DB connection that users configure in the UI, swap the `_credentials_present` / inline env lookup for:

```python
from ...services.sharepoint import current_credentials  # add to imports
# inside invoke():
creds = current_credentials(db)  # ctx exposes a db handle; if not, use SessionLocal()
if not creds:
    # existing "not configured" stub return
    return ToolResult(name=self.name, ok=True, data={"query": query, "fetched": [], "count": 0, "configured": False},
                      notes=["sharepoint_not_configured"])
tenant = creds["tenant_id"]; client_id = creds["client_id"]; client_secret = creds["client_secret"]; site_id = creds["site_id"]
```

Or — even simpler — the helpers in `services/sharepoint.py` (`list_files`, `download_file`) are already written, so the tool can drop its own OAuth/HTTP code entirely:

```python
from ...services.sharepoint import get_active_connection, list_files
conn = get_active_connection(db)
items = list_files(conn, subfolder=…)
```

Connection-test status (verified via SharePoint UI + Test connection button by user 2026-05-08): Tenant Leewayhertz Technologies, site `Salesops`, folder `/Salesops` — read + write working with the credentials user configured.

**Cloud notes**: outbound HTTPS to `graph.microsoft.com:443` and `login.microsoftonline.com:443`. Same `EMAIL_SECRET_KEY` Fernet pin applies — client_secret_enc won't decrypt without it. Client secret has 24-month expiry; rotation is "generate new secret in Entra portal → click Reconfigure in UI".
