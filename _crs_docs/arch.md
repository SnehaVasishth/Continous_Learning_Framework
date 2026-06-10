# Agentic Content Studio — Architecture (`arch.md`)

This document is implementation-ready. The **deep agent design** (per-agent
prompts, tools, guardrails, model assignment, logging) lives in `agents-plan.md`;
this file covers the system architecture, data flow, API contracts (including SSE
event types), the orchestration overview, and the local vector store / embeddings.

---

## 1. Component diagram

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ FRONTEND  (React + Vite + TS, Tailwind 3 / zbrain design system)           │
│                                                                            │
│  AppShell (TopBar tri-pane, StageNav)                                      │
│   ├─ Dashboard ── projects CRUD                                            │
│   ├─ Research   ── AgentStream + ResearchBrief + SourcesPanel              │
│   ├─ Knowledge  ── UrlInput + DocumentList + BrandVoice/Structure cards    │
│   ├─ DraftEdit  ── DraftPanel + FinalCopyPanel + LinkReport                │
│   └─ Refine     ── ChatThread + FinalCopy preview + VersionSwitcher        │
│                                                                            │
│  lib/api.ts (REST)        lib/sse.ts (EventSource)   react-query cache     │
└───────────────┬─────────────────────────┬────────────────────────────────┘
        REST (JSON)                 SSE (text/event-stream)
                │                         │
┌───────────────▼─────────────────────────▼────────────────────────────────┐
│ BACKEND  (Node + Express + TS)                                             │
│                                                                            │
│  routes/ ── projects | research | knowledge | draftedit | refine          │
│     │            │           │            │              │                │
│     ▼            ▼           ▼            ▼              ▼                │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ agents/  researchAgent  kbAgent  draftAgent  editorAgent  refine    │  │
│  └───┬──────────────┬─────────────┬───────────┬───────────────┬───────┘  │
│      │              │             │           │               │          │
│      ▼              ▼             ▼           ▼               ▼          │
│  ai/anthropic   kb/scrape     kb/vectorStore  tools/linkVerify  chat     │
│  (Claude SDK,   kb/embeddings  kb/chunk        tools/url        history  │
│   web_search,   (MiniLM local) (cosine top-k)  (SSRF guard)             │
│   streaming)                                                            │
│                                                                            │
│  db/  better-sqlite3  +  repositories/   (projects, briefs, kb, drafts,   │
│        final_copies, chat, agent_runs)   ── embeddings stored as BLOBs    │
└───────────────┬────────────────────────────────┬──────────────────────────┘
                │                                 │
        ┌───────▼────────┐               ┌────────▼─────────┐
        │ SQLite file    │               │ Local MiniLM     │
        │ data/studio.db │               │ model cache      │
        │ (rows+vectors) │               │ data/models/     │
        └────────────────┘               └──────────────────┘
                │
   external ────▼──────────────────────────────────────────────
   Anthropic API (Claude generation + native web_search server tool)
   Public web (KB URL scraping + Editor link verification)
```

**Only outbound external dependency:** the Anthropic API (covers generation +
web search) plus public HTTP for scraping/link-checks. No embedding API, vector
DB service, or third-party search API.

---

## 2. End-to-end data flow

```text
(1) Topic
    User creates project { topic, contentType?, targetLength? }
        → POST /api/projects → projects row (status=draft)

(2) Research
    POST /api/projects/:id/research/run (SSE)
        → researchAgent: Claude + native web_search tool (streamed)
        → emits run.start, agent.status, tool.web_search.query/result,
          message.delta (thinking/text), then brief.partial/brief.complete
        → persist research_briefs { summary, key_insights, statistics,
          quotes, sources[] }; project.status = kb_ready-eligible

(3) Knowledge Base / Brand Voice
    POST /api/projects/:id/kb/run { urls[] } (SSE)
        → for each url: scrape (SSRF-guarded fetch + Readability) → kb_documents
          (emit doc.status per url)
        → chunk each doc (kb/chunk) → embed locally (MiniLM, 384-dim)
          → kb_chunks { text, embedding BLOB } (emit kb.embedding.progress)
        → kbAgent: Claude distills brand voice profile + structure template
          from scraped docs → brand_profiles (emit profile.complete)

(4) Draft
    POST /api/projects/:id/draft/run (SSE)
        → build retrieval query from research brief + structure intent
        → vectorStore.topK(projectId, queryEmbedding, k=6)  (cosine over BLOBs)
        → draftAgent: Claude writes draft from
          { research brief + brand voice + structure template + retrieved chunks }
          (streamed) → drafts { content_md, outline, citations }

(5) Edit + Link verification
    POST /api/projects/:id/edit/run (SSE)
        → editorAgent: Claude polishes draft → candidate final copy (streamed)
        → tools/linkVerify: extract every URL → HTTP-check (HEAD→GET, redirects,
          timeouts) → classify ok|redirected|broken|unreachable
          (emit link.checked per url)
        → if broken/wrong links: re-prompt Claude to fix/remove → re-verify
        → persist final_copies { version=1, content_md, edit_summary,
          link_report } (source='editor'); project.status=final

(6) Refine chat
    POST /api/projects/:id/refine/run { message } (SSE)
        → persist user chat_message
        → refineAgent: Claude revises current final copy preserving voice +
          citations, using brief/KB context as needed (streamed)
        → optional re-verify of any new/changed links
        → persist new final_copies { version+1, source='refinement' } +
          assistant chat_message (version_ref) → UI live-updates preview
```

Every SSE run also records into `agent_runs` (status + captured events) so a
dropped client can reconnect and re-read the latest persisted state via the
corresponding GET endpoint.

---

## 3. API design

Base path `/api`. All bodies validated with **zod**. Timestamps are ISO-8601
strings. IDs are UUIDv4.

### 3.1 Shared DTOs

```ts
type ProjectStatus =
  'draft' | 'researching' | 'kb_ready' | 'drafting' | 'editing' | 'final' | 'error';
type Stage = 'research' | 'knowledge_base' | 'draft_edit' | 'refine';

interface ProjectSummary {
  id: string; topic: string; contentType?: string; targetLength?: string;
  status: ProjectStatus; stage: Stage; createdAt: string; updatedAt: string;
}

interface Source { id: string; title: string; url: string; publisher?: string; accessedAt: string; }
interface KeyInsight { text: string; sourceIds: string[]; }
interface Statistic { value: string; label: string; context?: string; sourceId?: string; }
interface Quote { text: string; speaker?: string; sourceId?: string; }
interface ResearchBrief {
  id: string; projectId: string; summary: string;
  keyInsights: KeyInsight[]; statistics: Statistic[]; quotes: Quote[];
  sources: Source[]; createdAt: string;
}

interface KbDocument {
  id: string; projectId: string; url: string; title?: string;
  status: 'queued' | 'scraping' | 'done' | 'failed'; errorMessage?: string;
  wordCount?: number; createdAt: string;
}
interface BrandVoice {
  tone: string[]; style: string[]; vocabulary: string[];
  dos: string[]; donts: string[]; readingLevel?: string; summary: string;
}
interface StructureTemplate {
  sections: string[]; averageWordCount?: number;
  formattingNotes?: string; headingStyle?: string;
}
interface BrandProfile { voice: BrandVoice; structure: StructureTemplate; updatedAt: string; }

interface Draft { id: string; projectId: string; contentMd: string; outline: string[]; citations: string[]; createdAt: string; }

type LinkStatus = 'ok' | 'redirected' | 'broken' | 'unreachable';
interface LinkCheck { url: string; status: LinkStatus; httpCode?: number; finalUrl?: string; note?: string; }
interface FinalCopy {
  id: string; projectId: string; version: number; contentMd: string;
  editSummary?: string; linkReport: LinkCheck[]; source: 'editor' | 'refinement'; createdAt: string;
}

interface ChatMessage { id: string; projectId: string; role: 'user' | 'assistant'; content: string; versionRef?: number; createdAt: string; }
```

### 3.2 REST endpoints

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/projects` | `{ topic: string; contentType?: string; targetLength?: string }` | `ProjectSummary` |
| GET | `/api/projects` | — | `ProjectSummary[]` |
| GET | `/api/projects/:id` | — | `{ project, brief?, kb?, draft?, final?, chat? }` |
| DELETE | `/api/projects/:id` | — | `{ ok: true }` |
| GET | `/api/projects/:id/research` | — | `ResearchBrief \| null` |
| GET | `/api/projects/:id/kb` | — | `{ documents: KbDocument[]; brandProfile: BrandProfile \| null }` |
| DELETE | `/api/projects/:id/kb/documents/:docId` | — | `{ ok: true }` |
| PUT | `/api/projects/:id/kb/profile` | `{ voice: BrandVoice; structure: StructureTemplate }` | `BrandProfile` |
| GET | `/api/projects/:id/draft` | — | `Draft \| null` |
| GET | `/api/projects/:id/final` | — | `FinalCopy \| null` |
| GET | `/api/projects/:id/chat` | — | `ChatMessage[]` |
| GET | `/api/projects/:id/versions` | — | `{ version: number; createdAt: string; source: string }[]` |
| GET | `/api/projects/:id/versions/:version` | — | `FinalCopy` |
| GET | `/api/health` | — | `{ status: 'ok'; hasApiKey: boolean }` |

### 3.3 SSE endpoints

All SSE endpoints respond with `Content-Type: text/event-stream`,
`Cache-Control: no-cache`, `Connection: keep-alive`, send periodic `: keepalive`
comments, and end with a terminal `done` event. The frontend opens them via a
`POST`-triggered run; because native `EventSource` only supports GET, the client
uses a **fetch + ReadableStream reader** wrapper (`lib/sse.ts`) to POST and parse
the event stream. (KB/refine carry a request body, so POST is required.)

| Method | Path | Body | Agent |
|---|---|---|---|
| POST | `/api/projects/:id/research/run` | — | Research |
| POST | `/api/projects/:id/kb/run` | `{ urls: string[] }` | KB build |
| POST | `/api/projects/:id/draft/run` | — | Drafting |
| POST | `/api/projects/:id/edit/run` | — | Editor + link verify |
| POST | `/api/projects/:id/refine/run` | `{ message: string }` | Refinement chat |

### 3.4 SSE event types

Each SSE message uses `event: <type>` + `data: <json>`. Event payloads:

```ts
// lifecycle (all runs)
'run.start'        { runId: string; agent: string; model: string }
'agent.status'     { phase: string; message: string }          // human-readable step
'message.delta'    { text: string }                            // streamed model text/thinking
'error'            { message: string; recoverable: boolean }
'done'             { runId: string; status: 'succeeded' | 'failed' }

// research-specific
'tool.web_search'  { state: 'query' | 'result'; query?: string; resultCount?: number }
'brief.partial'    { partial: Partial<ResearchBrief> }
'brief.complete'   { brief: ResearchBrief }

// kb-specific
'doc.status'       { url: string; status: KbDocument['status']; title?: string; wordCount?: number; error?: string }
'kb.embedding'     { documentUrl: string; chunksEmbedded: number; totalChunks: number }
'profile.complete' { brandProfile: BrandProfile }

// draft-specific
'retrieval'        { chunks: { documentTitle?: string; score: number; preview: string }[] }
'draft.complete'   { draft: Draft }

// editor-specific
'link.checked'     { check: LinkCheck; index: number; total: number }
'edit.pass'        { pass: number; fixedLinks: number }        // re-verify loop iteration
'final.complete'   { finalCopy: FinalCopy }

// refine-specific
'chat.user'        { message: ChatMessage }
'chat.assistant'   { message: ChatMessage; finalCopy: FinalCopy } // new version applied
```

The frontend's `useAgentStream` hook maps these events to UI state: status line,
streamed markdown, per-URL scrape/link badges, and final persisted objects (which
also seed the react-query cache so a page reload shows the same state).

---

## 4. Agent orchestration overview

The pipeline is a **sequential, user-gated, single-agent-per-stage** orchestration
(no supervisor agent). Each stage is one Claude run with tool use; stages share
state through the SQLite DB rather than passing in-memory context. Stages can be
re-run independently. **Full prompts, tool schemas, guardrails, model choices, and
logging are defined in `agents-plan.md`** — this is the summary.

```text
   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
   │ Research  │ → │ Knowledge │ → │  Draft    │ → │  Editor   │ → │  Refine   │
   │  Agent    │   │ Base/Voice│   │  Agent    │   │  Agent    │   │  Chat     │
   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
   web_search       scrape+embed    KB retrieval   link verify     revise+verify
   (Claude tool)    +Claude distill +Claude write  +Claude fix     (Claude, loop)
         │               │               │               │               │
         └──── research_briefs · kb_documents/kb_chunks · brand_profiles ─┘
                drafts · final_copies (versioned) · chat_messages
                          (shared via SQLite repositories)
```

| Stage | Agent | Model (default, from env) | Key tools | Persists |
|---|---|---|---|---|
| 1 | Research | `claude-opus-4-7` (heavy) | native `web_search` server tool | `research_briefs` |
| 2 | KB / Voice | `claude-sonnet-4-6` (light) | none (input = scraped text) | `brand_profiles`, `kb_documents`, `kb_chunks` |
| 3a | Drafting | `claude-sonnet-4-6` (light) | local KB retrieval (pre-fetched) | `drafts` |
| 3b | Editor | `claude-opus-4-7` (heavy) | `tools/linkVerify` (server-side HTTP) | `final_copies` (v1) |
| 4 | Refine | `claude-opus-4-7` (heavy) | optional link re-verify | `final_copies` (v+1), `chat_messages` |

**Implementation notes for agents:**
- **Research:** call `client.messages.stream` with `tools: [{ type: 'web_search_<version>', name: 'web_search', max_uses: WEB_SEARCH_MAX_USES }]`. Relay `web_search` tool blocks to `tool.web_search` SSE events. After the run, a structured-output pass (zod-validated, see `ai/structured.ts`) converts the synthesized text + cited URLs into the `ResearchBrief` shape; dedupe sources by URL.
- **KB distillation:** no model tools; feed concatenated/truncated scraped docs and request the `BrandVoice` + `StructureTemplate` JSON (zod-validated, repaired on parse failure).
- **Drafting:** retrieval happens in the backend (vectorStore.topK) and the chunks are injected into the prompt as context; the model itself uses no tools. Enforce inline markdown citations to `research_briefs.sources[].url`.
- **Editor:** stream the polished copy, then run `tools/linkVerify` over extracted URLs; if any are `broken`/`unreachable`/wrong-`redirected`, send a follow-up turn asking Claude to correct them, then re-verify (bounded to e.g. 2 passes).
- **Refine:** maintain conversation by replaying prior `chat_messages` + current final copy; system prompt enforces "preserve brand voice and existing citations." Each accepted revision writes a new versioned `final_copies`.

Every agent run is wrapped in try/catch: failures emit an `error` SSE event, set
`agent_runs.status='failed'`, set `project.status='error'` with a message, and
leave prior persisted outputs intact.

---

## 5. Local vector store + embeddings

### 5.1 Embeddings (in-process, no external API)
- **Model:** `Xenova/all-MiniLM-L6-v2` via **Transformers.js**
  (`@huggingface/transformers`), feature-extraction pipeline.
- **Call:** `extractor(texts, { pooling: 'mean', normalize: true })` → 384-dim,
  L2-normalized vectors.
- **Lifecycle:** lazy singleton in `kb/embeddings.ts`; the model is downloaded once
  and cached on disk at `TRANSFORMERS_CACHE` (default `./data/models`). First call
  incurs a one-time download; subsequent calls are offline and fast.
- **Limits:** MiniLM degrades past ~256 tokens, so chunks are sized ~500–800 chars
  with ~80-char overlap (`kb/chunk.ts`). Texts are batched for throughput.

### 5.2 Vector store (SQLite-backed brute-force cosine)
- **Storage:** each chunk's vector is written to `kb_chunks.embedding` as a
  serialized `Float32Array(384)` BLOB (already L2-normalized).
- **Write path (`vectorStore.upsert`):** for each chunk, embed → serialize Float32
  → insert row `{ id, document_id, project_id, chunk_index, text, embedding }`.
- **Query path (`vectorStore.topK(projectId, queryText|queryVector, k)`):**
  1. Embed the query (normalized) if given as text.
  2. Load all `kb_chunks` BLOBs for `project_id` (KB scale is small).
  3. Deserialize each to Float32Array; cosine = dot product (vectors normalized).
  4. Sort descending, return top-`k` (default 6) as
     `{ chunkId, documentId, text, score }`.
- **Why brute-force:** KB sizes (a handful of pasted brand URLs → tens/low-hundreds
  of chunks) make a full scan trivially fast and avoid any native ANN dependency,
  keeping the app dependency-light and fully local. (If a project ever grows large,
  the same interface can be swapped for `sqlite-vec` without changing callers.)
- **Scoping:** all reads/writes are filtered by `project_id`, so each project has an
  isolated KB; deleting a project or KB document cascades to its chunks.

### 5.3 Retrieval usage
- The **Drafting Agent** queries the store with a retrieval prompt assembled from
  the research summary + structure intent to pull the most voice/structure-relevant
  brand passages, which are injected into the draft prompt as grounding context.

---

## 6. Cross-cutting concerns

- **SSRF protection (`tools/url.ts`):** before any scrape or link check, resolve
  and reject loopback, private (RFC1918), link-local, and non-`http(s)` targets;
  enforce request timeouts and a max response size.
- **Link verification (`tools/linkVerify.ts`):** extract URLs from markdown; try
  `HEAD`, fall back to `GET` on 405/403; follow redirects (record `finalUrl`);
  classify `ok` (2xx), `redirected` (3xx→2xx with different host/path), `broken`
  (4xx/5xx), `unreachable` (DNS/timeout/TLS). Runs with bounded concurrency
  (`LINK_VERIFY_CONCURRENCY`).
- **Boot resilience:** the server starts and serves the UI even without
  `ANTHROPIC_API_KEY`; `/api/health` reports `hasApiKey`, and agent endpoints
  return a clear 400 if the key is missing.
- **Config:** `config.ts` reads all env (`PORT`, `ANTHROPIC_API_KEY`, `DB_PATH`,
  model names, etc.); the server binds `process.env.PORT`; the frontend reads the
  backend base URL from the injected `VITE_BACKEND_URL` / `BACKEND_1_URL`.
- **Logging:** `lib/logger.ts` + morgan; each agent run is recorded in `agent_runs`
  with its captured event stream for audit/reconnect.

---

## 7. Reference: external calls summary

| Concern | Mechanism | Account/secret needed |
|---|---|---|
| Text generation (all agents) | Anthropic Messages API (`@anthropic-ai/sdk`, streaming) | `ANTHROPIC_API_KEY` |
| Web search (Research) | Claude **native `web_search` server tool** | (same key) |
| Embeddings | **Local** Transformers.js MiniLM | none |
| Vector search | **Local** SQLite BLOB cosine | none |
| Persistence | **Local** SQLite file | none |
| KB scraping / link verify | Server-side HTTP to public web | none |

This confirms the spec's core constraint: **`ANTHROPIC_API_KEY` is the only
required credential.**
```
