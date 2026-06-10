# Agentic Content Studio — Product Specification (`spec.md`)

## 1. Product summary

**Agentic Content Studio** is a polished, shared (no-login) web application that
runs an autonomous **multi-agent content-creation pipeline**. A user enters a
topic, and the system runs **four AI agents in sequence** to produce
brand-aligned, fact-checked content, then exposes a **chat interface** to refine
the final copy conversationally.

The pipeline:

1. **Research Agent** — web-searches the topic, reads the most relevant sources,
   and extracts datasets, statistics, key insights, and quotes into a structured
   **research brief** with source URLs for citation.
2. **Knowledge Base / Brand Voice** — the user pastes brand URLs; the system
   scrapes them and distills (a) a **brand voice profile** and (b) a **content
   structure template**, stored with **local embeddings** for semantic retrieval.
3. **Drafting Agent** — combines research brief + brand voice profile + structure
   template (retrieved over the KB) to write the initial draft.
4. **Editor Agent** — reviews all context, produces the polished final copy, and
   **verifies every link** in the content (HTTP-checks each URL), flagging or
   fixing dead/wrong links.

Plus a **Refinement Chat** attached to the final copy where anyone can request
revisions, feedback, and optimizations; the system refines the content while
preserving brand voice and citations.

All AI runs on **Claude** via the official `@anthropic-ai/sdk` with tool use and
streaming. Web search uses Claude's **native `web_search` server tool**.
Embeddings are generated **locally in-process** (Transformers.js,
`Xenova/all-MiniLM-L6-v2`, 384-dim). Persistence is **SQLite** (better-sqlite3)
plus a **local embedded vector index**. The **Anthropic API key is the only
required credential.**

### Goals

- Turn a single topic into publish-ready, citation-backed, on-brand copy with
  minimal user effort.
- Make the autonomous pipeline **transparent**: stream each agent's progress live.
- Be **local-first**: one process, one DB file, one API key. No external search,
  embedding, or vector-DB accounts.
- Deliver an **enterprise-grade UI** using the zbrain design system (light mode).

### Non-goals (out of scope)

No user accounts/auth, no scheduled/automated runs, no CMS/publishing
integrations, no image generation, no dark mode.

---

## 2. Target users

- **Content marketers / brand writers** producing on-brand articles fast.
- **Content / SEO teams** needing fact-checked, citation-backed drafts.
- **Agencies** matching a client's existing voice from sample URLs.
- **Founders / solo operators** who want a research-to-polished-copy pipeline
  without stitching together multiple tools.

Because the app is shared and login-free, it is intended for a **trusted single
workspace** (a team's internal tool), where multiple projects/topics coexist.

---

## 3. Core features (per section / agent)

### 3.1 Project dashboard
- Create a project from a topic (and optional content type / target length).
- List all projects with status (`draft`, `researching`, `kb_ready`,
  `drafting`, `editing`, `final`, `error`) and the current pipeline stage.
- Open a project into its 4-stage workspace; delete a project (cascades).

### 3.2 Research Agent (Stage 1 — "Research")
- **Input:** project topic (+ optional angle/notes).
- **Behavior:** autonomously calls Claude's native `web_search` tool, reads the
  most relevant results, and synthesizes a **structured research brief**.
- **Output (research brief, JSON):**
  - `summary` — narrative overview of the topic.
  - `key_insights[]` — bullet insights, each with `text` + supporting `sourceIds`.
  - `statistics[]` — `{ value, label, context, sourceId }`.
  - `quotes[]` — `{ text, speaker, sourceId }`.
  - `sources[]` — `{ id, title, url, publisher, accessedAt }` (deduplicated).
- **UI:** live streaming of agent "thinking"/tool-use events; rendered brief with
  clickable citations; a "Sources" panel; **Re-run research** action.

### 3.3 Knowledge Base / Brand Voice (Stage 2 — "Knowledge Base")
- **Input:** a list of brand URLs (textarea, one per line) the user pastes.
- **Behavior:**
  - Scrape each URL (server-side fetch + HTML→clean-text extraction).
  - Chunk text and generate **local embeddings** (`all-MiniLM-L6-v2`, 384-dim);
    store chunks + vectors in the local vector index, scoped to the project.
  - Distill two artifacts via Claude:
    - **Brand voice profile** — `{ tone[], style[], vocabulary[], dos[], donts[], readingLevel, summary }`.
    - **Content structure template** — `{ sections[], averageWordCount, formattingNotes, headingStyle }`
      derived from the example articles.
- **UI:** per-URL scrape status (queued/scraping/done/failed), a documents list,
  editable brand voice profile + structure template cards, **Rebuild KB** action.

### 3.4 Drafting Agent (Stage 3 — "Draft & Edit", draft phase)
- **Input:** research brief + brand voice profile + structure template +
  top-k retrieved KB chunks (semantic retrieval over the project vector index).
- **Behavior:** Claude writes the **initial draft** that follows the structure
  template, adopts the brand voice, and weaves in research insights with inline
  citations (markdown links to source URLs).
- **Output:** `draft` markdown + `outline[]` + `citationsUsed[]`.
- **UI:** streamed draft as it is written; rendered markdown preview; **Regenerate
  draft** action.

### 3.5 Editor Agent (Stage 3 — "Draft & Edit", edit phase)
- **Input:** research brief + KB context + the draft.
- **Behavior:**
  - Claude reviews and produces the **polished final copy** (markdown).
  - Extract every URL from the final copy and **verify each link** via server-side
    HTTP HEAD/GET (status, redirect target, reachability, timeout handling).
  - Annotate each link as `ok | redirected | broken | unreachable`; the agent is
    re-prompted to **fix or remove** broken/wrong links and re-emit corrected copy.
- **Output:** `finalCopy` markdown + `linkReport[]` (`{ url, status, httpCode, finalUrl?, note }`)
  + `editSummary` (what changed).
- **UI:** final copy preview; **Link verification report** with per-link tone
  badges; **Re-edit / Re-verify links** actions.

### 3.6 Refinement Chat (Stage 4 — "Refine")
- A conversational chatbot bound to the project's **final copy**.
- The user requests revisions ("make it shorter", "add a CTA", "more formal",
  "tighten the intro"); the system applies changes while **preserving brand voice
  and citations**, returning updated final copy + a short explanation.
- Each turn is streamed. Chat history persists per project. A **content version**
  is saved on each accepted revision so the user can compare/restore.
- **UI:** chat thread on the left, live final-copy preview on the right that
  updates as revisions are applied; version dropdown.

### 3.7 Cross-cutting
- **Live progress streaming** for every agent run via SSE.
- **Stage gating:** later stages reference earlier outputs; the UI guides the user
  through Research → KB → Draft & Edit → Refine but allows re-running any stage.
- **Export:** copy final copy to clipboard / download as Markdown.

---

## 4. Detailed functional requirements

| # | Requirement |
|---|---|
| FR-1 | Create/list/open/delete projects; each project stores topic, options, status, and stage outputs. |
| FR-2 | Research Agent runs Claude with the native `web_search` tool and streams tool-use + text events; result persisted as a structured brief with deduplicated sources. |
| FR-3 | KB build scrapes each pasted URL server-side, extracts readable text, chunks it, and stores chunks + 384-dim local embeddings in a per-project vector index. |
| FR-4 | KB build distills a brand voice profile and a content structure template from the scraped documents; both are persisted and user-editable. |
| FR-5 | Drafting Agent retrieves top-k KB chunks by semantic similarity and writes a draft that follows the structure template and brand voice, with inline citations. |
| FR-6 | Editor Agent polishes the draft, extracts all URLs, HTTP-verifies each, and fixes/flags broken or redirected links; persists final copy + link report. |
| FR-7 | Refinement Chat applies conversational revisions to the final copy preserving voice/citations; persists chat history and a new content version per accepted revision. |
| FR-8 | All long-running agent operations stream progress to the client over SSE; the client can reconnect and read the latest persisted state if a stream drops. |
| FR-9 | The system requires exactly one secret: `ANTHROPIC_API_KEY`. No other third-party credential is needed. |
| FR-10 | Input validation: topic length, URL format/count limits, request body validation (zod) on every endpoint; graceful, user-facing error messages. |
| FR-11 | Link verification handles timeouts, redirects, TLS errors, and non-200 codes without crashing the run. |
| FR-12 | Embeddings and the vector index run fully in-process with no network calls (after the one-time model download cached on disk). |

---

## 5. Confirmed tech stack

### Frontend (`frontend/`)
- **React 18 + Vite + TypeScript** (strict).
- **Tailwind CSS 3** with the **zbrain design system** (see §9).
- **react-router-dom** for stage navigation within the SPA.
- **@tanstack/react-query** for server state (project/stage fetching, mutations).
- **react-markdown + remark-gfm** for rendering briefs, drafts, and final copy.
- **Native `EventSource`** for SSE streaming of agent progress.
- Fonts: **Inter** (UI) + **JetBrains Mono** (code/mono).

### Backend (`backend/`)
- **Node.js + Express + TypeScript** (strict).
- **@anthropic-ai/sdk** — all four agents + refinement chat, with **tool use**
  (native `web_search` server tool) and **streaming** (`messages.stream`).
- **better-sqlite3** — embedded relational store (synchronous, fast, file-based).
- **@huggingface/transformers** (Transformers.js) — local embeddings via
  `Xenova/all-MiniLM-L6-v2` (feature-extraction pipeline, mean pooling, L2
  normalize → 384-dim). **No external embedding API.**
- **Local vector index** — cosine similarity over vectors stored in SQLite
  (vectors persisted as Float32 BLOBs; brute-force top-k in-process). Small KB
  sizes make brute-force more than adequate and dependency-free.
- **cheerio** + **@mozilla/readability** + **jsdom** — HTML scraping / readable
  text extraction for KB documents and (optionally) research sources.
- **undici / global fetch** — server-side HTTP for scraping and **link
  verification** (HEAD with GET fallback, redirect + timeout handling).
- **zod** — request validation and structured-output parsing/repair.
- **cors**, **morgan** (logging), **dotenv**.

### Justification
- **better-sqlite3 + in-process vector index** keeps the app local-first: a single
  DB file, no DB server, no Pinecone/Weaviate account — matching the "one
  credential" requirement.
- **Transformers.js (all-MiniLM-L6-v2)** removes any embedding API/account; 384-dim
  vectors are small and fast for brute-force cosine search at KB scale.
- **Claude native `web_search`** removes Tavily/Serper; the Anthropic key covers
  search + generation, so `ANTHROPIC_API_KEY` is the only secret.
- **SSE over Express** is the simplest correct fit for one-way live progress
  streaming and reconnection.

---

## 6. Non-functional requirements

- **Streaming-first:** every agent run emits incremental SSE events; the UI shows
  live status, tool calls, and partial text. Target first-event latency < 2 s.
- **Local-first persistence:** all state in one SQLite file (`data/studio.db` by
  default, path from env); vector data co-located in SQLite. App is fully
  functional offline except for Claude API + web search + URL scraping/verification.
- **Single credential:** only `ANTHROPIC_API_KEY` required. App must boot and serve
  the UI even if the key is missing, surfacing a clear "API key required" error on
  agent actions (never crash on boot).
- **Resilience:** agent runs are wrapped so a failure marks the stage `error` with
  a message and never corrupts prior outputs. Streams survive client reconnects by
  re-reading persisted state.
- **Config from env:** ports, URLs, DB path, model names — all from `process.env`;
  no hardcoded ports/URLs/secrets. Backend binds `process.env.PORT`.
- **Security:** SSRF mitigation on scraping/link-verify (block private/loopback/
  link-local IP ranges, cap response size, enforce timeouts, http(s) only).
- **Performance:** model loaded once (lazy singleton) and cached on disk; embeddings
  batched; link checks run with bounded concurrency.
- **Accessibility & polish:** keyboard-navigable, semantic HTML, Apple-spring
  motion, status tones per the design system; light mode only.

---

## 7. Data model

### 7.1 SQLite tables (`better-sqlite3`)

```text
projects
  id            TEXT PRIMARY KEY            -- uuid
  topic         TEXT NOT NULL
  content_type  TEXT                        -- e.g. "Blog post", "Landing page"
  target_length TEXT                        -- e.g. "800-1200 words"
  status        TEXT NOT NULL DEFAULT 'draft'   -- draft|researching|kb_ready|drafting|editing|final|error
  stage         TEXT NOT NULL DEFAULT 'research' -- research|knowledge_base|draft_edit|refine
  error_message TEXT
  created_at    TEXT NOT NULL
  updated_at    TEXT NOT NULL

research_briefs
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  summary       TEXT
  data_json     TEXT NOT NULL    -- JSON: { key_insights[], statistics[], quotes[], sources[] }
  created_at    TEXT NOT NULL
  -- one current brief per project (latest wins; older kept for history)

kb_documents
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  url           TEXT NOT NULL
  title         TEXT
  status        TEXT NOT NULL    -- queued|scraping|done|failed
  error_message TEXT
  raw_text      TEXT             -- extracted readable text
  word_count    INTEGER
  created_at    TEXT NOT NULL

kb_chunks
  id            TEXT PRIMARY KEY
  document_id   TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  chunk_index   INTEGER NOT NULL
  text          TEXT NOT NULL
  embedding     BLOB NOT NULL    -- Float32Array(384) serialized; L2-normalized
  created_at    TEXT NOT NULL

brand_profiles
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  voice_json    TEXT NOT NULL    -- { tone[], style[], vocabulary[], dos[], donts[], readingLevel, summary }
  structure_json TEXT NOT NULL   -- { sections[], averageWordCount, formattingNotes, headingStyle }
  updated_at    TEXT NOT NULL

drafts
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  content_md    TEXT NOT NULL    -- draft markdown
  outline_json  TEXT             -- string[]
  citations_json TEXT            -- string[] of source urls used
  created_at    TEXT NOT NULL

final_copies
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  version       INTEGER NOT NULL          -- increments per accepted revision
  content_md    TEXT NOT NULL
  edit_summary  TEXT
  link_report_json TEXT          -- [{ url, status, httpCode, finalUrl?, note }]
  source        TEXT NOT NULL    -- 'editor' | 'refinement'
  created_at    TEXT NOT NULL
  -- current = highest version per project

chat_messages
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  role          TEXT NOT NULL    -- user|assistant
  content       TEXT NOT NULL
  version_ref   INTEGER          -- final_copies.version produced by this turn (assistant only)
  created_at    TEXT NOT NULL

agent_runs
  id            TEXT PRIMARY KEY
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
  agent         TEXT NOT NULL    -- research|kb|draft|editor|refine
  status        TEXT NOT NULL    -- running|succeeded|failed
  model         TEXT
  events_json   TEXT             -- captured stream events (for reconnect/audit)
  error_message TEXT
  started_at    TEXT NOT NULL
  finished_at   TEXT
```

Indexes: `kb_chunks(project_id)`, `kb_documents(project_id)`,
`chat_messages(project_id, created_at)`, `final_copies(project_id, version)`,
`agent_runs(project_id, started_at)`.

### 7.2 Vector store

- **Storage:** vectors live in `kb_chunks.embedding` as serialized
  `Float32Array(384)` BLOBs (L2-normalized at write time).
- **Index:** in-process brute-force cosine similarity. On retrieval, load the
  project's chunk vectors, compute dot product (= cosine, since normalized) against
  the normalized query embedding, return top-k (default `k=6`).
- **Embedding model:** `Xenova/all-MiniLM-L6-v2` via Transformers.js
  feature-extraction pipeline, `{ pooling: 'mean', normalize: true }`, 384-dim.
  Model is downloaded once and cached on disk (`TRANSFORMERS_CACHE` path).
- **Chunking:** ~500–800 chars per chunk with ~80-char overlap, respecting the
  model's ~256-token limit; batch-embedded.

---

## 8. File tree

> Multi-service layout. Planning/config files at the workspace root; one
> self-contained subdirectory per service.

```text
<workspace root>/
├── spec.md
├── arch.md
├── agents-plan.md                  # produced by agent-planner (deep agent design)
├── README.md
├── .env.example
├── integrations-config.json
├── preview.config.json
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                  # router + layout shell
│       ├── index.css                # Tailwind layers + zbrain tokens, fonts
│       ├── lib/
│       │   ├── api.ts               # REST client (fetch wrappers, typed)
│       │   ├── sse.ts               # EventSource helper for agent streams
│       │   ├── queryClient.ts       # react-query client
│       │   └── types.ts             # shared DTO types (mirror backend)
│       ├── components/
│       │   ├── layout/
│       │   │   ├── TopBar.tsx       # brand-nav-utility tri-pane, sticky
│       │   │   ├── AppShell.tsx     # max-w-[1400px] container
│       │   │   └── StageNav.tsx     # Research/KB/Draft&Edit/Refine nav
│       │   └── ui/                  # zbrain primitives
│       │       ├── Surface.tsx
│       │       ├── Section.tsx
│       │       ├── Field.tsx
│       │       ├── Button.tsx
│       │       ├── Chip.tsx
│       │       ├── Segmented.tsx
│       │       ├── PageHeader.tsx
│       │       ├── Eyebrow.tsx
│       │       ├── Separator.tsx
│       │       ├── StatusBadge.tsx  # 50/700 tone pairs
│       │       ├── Spinner.tsx
│       │       └── Markdown.tsx     # react-markdown wrapper w/ styles
│       ├── features/
│       │   ├── dashboard/
│       │   │   ├── DashboardView.tsx
│       │   │   ├── ProjectCard.tsx
│       │   │   └── NewProjectDialog.tsx
│       │   ├── research/
│       │   │   ├── ResearchView.tsx
│       │   │   ├── ResearchBrief.tsx
│       │   │   ├── SourcesPanel.tsx
│       │   │   └── AgentStream.tsx   # shared live-progress stream renderer
│       │   ├── knowledge/
│       │   │   ├── KnowledgeView.tsx
│       │   │   ├── UrlInput.tsx
│       │   │   ├── DocumentList.tsx
│       │   │   ├── BrandVoiceCard.tsx
│       │   │   └── StructureTemplateCard.tsx
│       │   ├── draftedit/
│       │   │   ├── DraftEditView.tsx
│       │   │   ├── DraftPanel.tsx
│       │   │   ├── FinalCopyPanel.tsx
│       │   │   └── LinkReport.tsx
│       │   └── refine/
│       │       ├── RefineView.tsx
│       │       ├── ChatThread.tsx
│       │       ├── ChatComposer.tsx
│       │       └── VersionSwitcher.tsx
│       └── hooks/
│           ├── useProject.ts
│           ├── useAgentStream.ts     # subscribe to SSE for a run
│           └── useProjects.ts
└── backend/
    ├── package.json
    ├── tsconfig.json
    ├── .env.example                  # local copy for dev convenience (names only)
    └── src/
        ├── server.ts                 # Express app bootstrap, binds process.env.PORT
        ├── app.ts                    # express app factory (routes, middleware, cors)
        ├── config.ts                 # env loading + validation (PORT, ANTHROPIC_API_KEY, DB_PATH, models)
        ├── db/
        │   ├── index.ts              # better-sqlite3 connection (singleton)
        │   ├── schema.ts             # CREATE TABLE migrations (run on boot)
        │   └── repositories/
        │       ├── projects.repo.ts
        │       ├── research.repo.ts
        │       ├── kb.repo.ts
        │       ├── drafts.repo.ts
        │       ├── finalCopies.repo.ts
        │       ├── chat.repo.ts
        │       └── runs.repo.ts
        ├── ai/
        │   ├── anthropic.ts          # @anthropic-ai/sdk client singleton
        │   ├── models.ts             # model name constants from env
        │   ├── stream.ts             # helper to relay messages.stream -> SSE
        │   └── structured.ts         # zod-validated structured-output extraction
        ├── agents/
        │   ├── researchAgent.ts      # web_search tool, builds research brief
        │   ├── kbAgent.ts            # distills brand voice + structure template
        │   ├── draftAgent.ts         # retrieval + draft generation
        │   ├── editorAgent.ts        # polish + link-fix loop
        │   └── refineAgent.ts        # conversational revision of final copy
        ├── kb/
        │   ├── embeddings.ts         # Transformers.js pipeline singleton (MiniLM)
        │   ├── vectorStore.ts        # store/retrieve cosine top-k over kb_chunks
        │   ├── chunk.ts              # text chunking
        │   └── scrape.ts             # fetch + readability/cheerio extraction (SSRF-guarded)
        ├── tools/
        │   ├── linkVerify.ts         # extract URLs, HTTP-check (HEAD/GET), classify
        │   └── url.ts                # url parsing + private-range/SSRF guards
        ├── routes/
        │   ├── projects.routes.ts
        │   ├── research.routes.ts
        │   ├── knowledge.routes.ts
        │   ├── draftedit.routes.ts
        │   └── refine.routes.ts
        ├── sse/
        │   └── sse.ts                # SSE response helpers (headers, write event, keepalive)
        ├── middleware/
        │   ├── errorHandler.ts
        │   └── validate.ts           # zod body/params validation middleware
        └── lib/
            ├── ids.ts                # uuid helpers
            ├── time.ts               # ISO timestamps
            └── logger.ts
```

---

## 9. UI / design system (zbrain)

- **React + Tailwind 3**, **Inter** (UI) + **JetBrains Mono** (mono).
- **Primitives:** Surface, Section, Field, Button, Chip, Segmented, PageHeader,
  Eyebrow, Separator (implemented in `frontend/src/components/ui/`).
- **Layout:** sticky top-bar, **brand-nav-utility tri-pane**, content centered at
  `max-w-[1400px]`.
- **Radii:** Surface 14px, Button 10px, input 8px.
- **Elevation:** soft shadows define cards — **no borders** for card separation.
- **Motion:** Apple spring, `cubic-bezier(0.32,0.72,0,1)`.
- **Status tones:** 50/700 tint pairs (e.g. `bg-*-50 text-*-700`) for statuses
  (researching, done, broken-link, etc.).
- **Light mode only.**

### Primary views (map to pipeline)
1. **Dashboard** — projects list + new-project.
2. **Research** — topic, live agent stream, research brief, sources.
3. **Knowledge Base** — URL input, scrape statuses, brand voice + structure cards.
4. **Draft & Edit** — draft panel + final-copy panel + link verification report.
5. **Refine** — chat thread + live final-copy preview + version switcher.

The app is a **single-page app** with **top-nav stage navigation** between these
views, which fits the zbrain top-bar tri-pane layout.

---

## 10. REST / SSE API surface

Base path `/api`. JSON bodies validated with zod. SSE endpoints stream agent
progress; their final persisted state is always re-fetchable via the matching GET.

### Projects
- `POST /api/projects` — create `{ topic, contentType?, targetLength? }` → project.
- `GET /api/projects` — list projects (summary).
- `GET /api/projects/:id` — full project with all stage outputs.
- `DELETE /api/projects/:id` — delete project (cascade).

### Research (Stage 1)
- `POST /api/projects/:id/research/run` — **SSE**; runs Research Agent, streams
  events, persists `research_briefs`.
- `GET /api/projects/:id/research` — latest research brief.

### Knowledge Base (Stage 2)
- `POST /api/projects/:id/kb/run` — body `{ urls: string[] }`; **SSE**; scrapes,
  embeds, distills voice + structure.
- `GET /api/projects/:id/kb` — `{ documents[], brandProfile }`.
- `DELETE /api/projects/:id/kb/documents/:docId` — remove a KB document + chunks.
- `PUT /api/projects/:id/kb/profile` — save user-edited voice/structure.

### Draft & Edit (Stage 3)
- `POST /api/projects/:id/draft/run` — **SSE**; runs Drafting Agent (retrieval +
  generation), persists `drafts`.
- `GET /api/projects/:id/draft` — latest draft.
- `POST /api/projects/:id/edit/run` — **SSE**; runs Editor Agent (polish +
  link-verify loop), persists `final_copies` (`source='editor'`).
- `GET /api/projects/:id/final` — current final copy (highest version) + link report.

### Refine (Stage 4)
- `POST /api/projects/:id/refine/run` — body `{ message }`; **SSE**; refines final
  copy, persists user + assistant `chat_messages` and a new `final_copies`
  (`source='refinement'`).
- `GET /api/projects/:id/chat` — chat history.
- `GET /api/projects/:id/versions` — list final-copy versions.
- `GET /api/projects/:id/versions/:version` — fetch a specific version.

### Utility
- `GET /api/health` — `{ status, hasApiKey }` (UI gates agent actions on
  `hasApiKey`).

(Request/response shapes and SSE event types are detailed in `arch.md`.)

---

## 11. Environment variables

| Variable | Service | Required | Default | Purpose |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | backend | **Yes** | — | Only required secret; powers all agents + native web search. |
| `PORT` | backend | Yes (injected) | — | Port the backend binds (from platform). |
| `DB_PATH` | backend | No | `./data/studio.db` | SQLite file path. |
| `TRANSFORMERS_CACHE` | backend | No | `./data/models` | On-disk cache for the local embedding model. |
| `ANTHROPIC_MODEL_HEAVY` | backend | No | `claude-opus-4-7` | Heavier reasoning/editing agents (research, editor, refine). |
| `ANTHROPIC_MODEL_LIGHT` | backend | No | `claude-sonnet-4-6` | Lighter tasks (KB distillation, draft). |
| `WEB_SEARCH_MAX_USES` | backend | No | `5` | Cap on native web_search tool uses per research run. |
| `LINK_VERIFY_CONCURRENCY` | backend | No | `5` | Concurrent link checks in the Editor stage. |
| `CORS_ORIGIN` | backend | No | `*` | Allowed frontend origin(s). |
| `PORT` | frontend | Yes (injected) | — | Vite preview/server port. |
| `VITE_BACKEND_URL` / `BACKEND_1_URL` | frontend | Yes (injected) | — | Backend base URL for REST/SSE calls. |

`.env.example` (workspace root) lists every variable above by name only. The only
credential the user must provide is `ANTHROPIC_API_KEY` — recorded in
`integrations-config.json`. Embeddings and the vector store run locally, so **no
embedding API, vector-DB, or search-API account is required.**
