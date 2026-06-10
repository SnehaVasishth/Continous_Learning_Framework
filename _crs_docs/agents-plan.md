# Agentic Content Studio — Agent Plan (`agents-plan.md`)

Governable, observable specification of **every AI agent** the application runs.
This is the contract the code-generation phase implements directly: each agent's
model, system-prompt intent, tools (with full JSON contracts), assembled input,
output schema, guardrails, and what is persisted/logged. Grounded in `spec.md`
(§3, §7, §10, §11) and `arch.md` (§3, §4, §6).

## 0. Does the app need agents?

**Yes.** The product is an autonomous, tool-using, multi-stage content pipeline.
Four tool-using LLM agents run in sequence plus a fifth conversational agent. They
call external tools (Claude native `web_search`, a custom link-verification tool),
emit structured artifacts other stages consume, and stream their progress live. This
is squarely agentic, not a one-shot API call.

### Topology — sequential, user-gated, single-agent-per-stage (no supervisor)

Each stage is exactly **one** Claude run with its own tools and guardrails. There is
**no supervisor/orchestrator agent**; the Express backend is the deterministic
orchestrator. Stages **do not pass in-memory context** — they share state through
**SQLite repositories** (`research_briefs`, `kb_documents`, `kb_chunks`,
`brand_profiles`, `drafts`, `final_copies`, `chat_messages`). This keeps each agent
independently re-runnable, auditable, and cheap to reason about. The user gates
progression between stages from the UI (Research → KB → Draft → Edit → Refine), and
may re-run any stage at any time.

### SDK / framework

- **`@anthropic-ai/sdk`** (the standard client SDK), using `client.messages.stream`
  for streaming and the **tool-use loop** driven manually by the backend. Chosen over
  `@anthropic-ai/claude-agent-sdk` because the orchestration is a fixed, deterministic
  pipeline where the backend (not an agent loop) owns stage sequencing, SSE relay,
  SQLite persistence, the local vector store, and SSRF-guarded HTTP. We need
  fine-grained control of every tool round-trip (to relay each as an SSE event and to
  inject our own structured-output/repair passes), which the low-level SDK gives
  directly. This matches `spec.md` §5 and `arch.md` §4.
- **Anthropic API key is the only credential** (`ANTHROPIC_API_KEY`). Native
  `web_search` is billed on the same key; embeddings, vector search, persistence,
  scraping, and link verification are all local/server-side with no extra account.
  Cross-referenced in `integrations-config.json` (key: `ANTHROPIC_API_KEY`) — the only
  entry.

### Model assignment (env-driven; names from `spec.md` §11)

Models are read from env so they can be swapped without code changes:

- `ANTHROPIC_MODEL_HEAVY` (default `claude-opus-4-7`) — Research, Drafting, Editor, Refine.
- `ANTHROPIC_MODEL_LIGHT` (default `claude-sonnet-4-6`) — KB distillation.

> Note vs `arch.md` §4 summary table: this plan is the **authoritative** per-agent
> model spec. Per the confirmed model policy ("opus for heavier reasoning/editing
> agents, sonnet for lighter tasks"), **Drafting uses `ANTHROPIC_MODEL_HEAVY` (opus)**
> because long-form, voice-matched, citation-grounded composition is a heavy reasoning
> task; **only KB distillation uses `ANTHROPIC_MODEL_LIGHT` (sonnet)** as it is a
> bounded extraction/summarization task. The build phase must follow this section, and
> `arch.md`'s summary row for Drafting should be read as opus.

---

## 1. Orchestration diagram (sequential + user-gated)

```text
        [ user creates project: topic, contentType?, targetLength? ]
                                  │
                                  ▼
   ╔═══════════════════════════ STAGE 1 ═══════════════════════════╗
   ║  RESEARCH AGENT            model: opus (HEAVY)                 ║
   ║  tool: native web_search (server tool, max_uses=WEB_SEARCH..) ║
   ║  in : topic (+ angle/notes)                                   ║
   ║  out: ResearchBrief JSON  → persist research_briefs           ║
   ╚════════════════════════════════╤══════════════════════════════╝
                                    │  ◇ USER GATE: review brief, proceed / re-run
                                    ▼
   ╔═══════════════════════════ STAGE 2 ═══════════════════════════╗
   ║  KB BUILDER AGENT          model: sonnet (LIGHT)              ║
   ║  (backend first: SSRF-guarded scrape → text → chunk → embed   ║
   ║   locally (MiniLM 384d) → kb_documents / kb_chunks)           ║
   ║  in : concatenated scraped doc text                          ║
   ║  out: BrandVoice + StructureTemplate JSON → brand_profiles    ║
   ╚════════════════════════════════╤══════════════════════════════╝
                                    │  ◇ USER GATE: edit voice/structure, proceed
                                    ▼
   ╔═══════════════════════════ STAGE 3a ══════════════════════════╗
   ║  DRAFTING AGENT            model: opus (HEAVY)                ║
   ║  (backend first: vectorStore.topK(k=6) over project KB)       ║
   ║  in : ResearchBrief + BrandVoice + StructureTemplate          ║
   ║       + top-k KB chunks                                       ║
   ║  out: Draft (markdown + outline + citationsUsed) → drafts     ║
   ╚════════════════════════════════╤══════════════════════════════╝
                                    │  ◇ USER GATE: review draft, run editor / regen
                                    ▼
   ╔═══════════════════════════ STAGE 3b ══════════════════════════╗
   ║  EDITOR AGENT             model: opus (HEAVY)                 ║
   ║  tool: verify_links (custom client tool → backend HTTP)       ║
   ║  in : ResearchBrief + KB context + Draft                      ║
   ║  loop: polish → call verify_links → fix dead/wrong links      ║
   ║        → re-verify (≤2 fix passes)                            ║
   ║  out: FinalCopy v1 (md + linkReport + editSummary)            ║
   ║       → persist final_copies (source='editor')               ║
   ╚════════════════════════════════╤══════════════════════════════╝
                                    │  ◇ USER GATE: review final copy, open chat
                                    ▼
   ╔═══════════════════════════ STAGE 4 ═══════════════════════════╗
   ║  REFINEMENT CHAT AGENT    model: opus (HEAVY)                 ║
   ║  tools: verify_links (always), web_search (gated, optional)   ║
   ║  in : brief + voice + structure + current FinalCopy           ║
   ║       + chat history + new user message                      ║
   ║  out: assistant message (+ FinalCopy v+1 when an edit is made)║
   ║       → final_copies (source='refinement') + chat_messages    ║
   ╚═══════════════════════════════════════════════════════════════╝

   Every stage: run wrapped in try/catch → on failure emits SSE `error`,
   sets agent_runs.status='failed' + project.status='error', prior outputs intact.
   Every stage records an agent_runs row (model, captured events) for audit/reconnect.
   ◇ = human approval gate (UI-driven; backend never auto-advances a stage).
```

---

## 2. Shared conventions (apply to all agents)

### 2.1 Tool-use loop with the streaming SDK

Each agent run is a manual tool loop over `client.messages.stream`:

1. Open a stream with the agent's `system`, `messages`, `tools`, `max_tokens`, and
   (where applicable) `tool_choice`.
2. Relay stream events to the client over SSE as they arrive:
   - text deltas → `message.delta { text }`
   - `web_search` tool blocks → `tool.web_search { state, query?, resultCount? }`
   - custom tool start → `agent.status { phase, message }`
3. On `stop_reason: 'tool_use'` **for custom client tools** (`verify_links`): execute
   the tool in the backend, append a `tool_result` block, and continue the loop with a
   new `messages.stream` turn carrying the updated message array. Native `web_search`
   is a **server tool** — Anthropic executes it; the backend only relays/observes, it
   does not run search itself.
4. Stop when `stop_reason: 'end_turn'` or the agent's **max tool iterations** is hit.
5. After the final turn, run any **structured-output extraction** (zod) needed to
   produce the persisted JSON artifact.

A shared helper (`ai/stream.ts`) relays `messages.stream` → SSE; a shared structured
extractor (`ai/structured.ts`) validates/repairs JSON (see 2.4). The Anthropic client
is a singleton (`ai/anthropic.ts`); model names come from `ai/models.ts` (env-backed).

### 2.2 Global budgets & limits

| Control | Value (source) | Applies to |
|---|---|---|
| Native `web_search` max uses | `WEB_SEARCH_MAX_USES` (default 5) | Research; Refine (when search enabled) |
| Max tool iterations (custom-tool loop) | 6 | Editor, Refine |
| Editor link-fix passes | ≤ 2 | Editor |
| Link-verify concurrency | `LINK_VERIFY_CONCURRENCY` (default 5) | Editor, Refine |
| Per-run wall-clock timeout | 180 s | all agents |
| Structured-output repair attempts | 1 (re-ask) then fail | Research, KB, Draft, Editor |
| `max_tokens` per turn | 4096 (Research/KB/Draft), 8192 (Editor/Refine — full copy) | per agent |
| Top-k KB retrieval | `k = 6` (arch §5.2) | Draft, Refine |

If a budget is exceeded, the agent stops gracefully, persists whatever valid partial
exists (or marks the stage `error`), and emits a `done`/`error` SSE event — it never
loops unbounded.

### 2.3 Citation representation (end-to-end)

Citations are a first-class, traceable chain:

- **Research** assigns each source a stable `id` (e.g. `s1`, `s2`, …) and a canonical
  `url` in `ResearchBrief.sources[]`. Insights/statistics/quotes reference sources by
  `sourceId(s)`.
- **Draft** and **Editor/Refine** render citations as **inline markdown links** whose
  href is exactly a `ResearchBrief.sources[].url`. `Draft.citations[]` and the
  Editor/Refine link reports key off these same URLs.
- **Link verification** (Editor/Refine) operates on the URLs extracted from the
  markdown, which by construction are the brief's source URLs (plus any URLs already
  present in scraped KB content the model chose to cite). A claim is considered
  "grounded" only if its inline link resolves to a `LinkCheck.status` of `ok` or
  benign `redirected`. Broken/unreachable links must be fixed or the claim removed.
- **No bare/uncited external claims** are permitted downstream of Research.

### 2.4 Structured-output extraction & JSON repair

Agents that must emit JSON (Research brief, KB profiles, Draft metadata, Editor final)
use a request-tool / `tool_choice`-forced JSON turn **or** a final
"emit JSON only" turn, then validate with a **zod schema**. On parse/validation
failure: one repair attempt — re-prompt the model with the validation error and the
offending text asking for corrected JSON only. A second failure marks the stage
`error` (never persists malformed JSON). See the failure matrix (§9).

### 2.5 Error handling wrapper

Every agent run is wrapped: a failure (API error, timeout, repair exhaustion, tool
error) → emit SSE `error { message, recoverable }`, set `agent_runs.status='failed'`,
set `project.status='error'` with the message, and **leave all prior persisted outputs
intact**. The UI re-reads the last good state via the matching GET endpoint.

### 2.6 Observability baseline (every run)

For **every** agent run, an `agent_runs` row records: `agent`, `model`, `status`
(`running|succeeded|failed`), `started_at`, `finished_at`, `error_message`, and
`events_json` (the captured SSE event stream — text deltas, tool calls, tool results
metadata). This supports **reconnect** (client re-reads persisted state) and **audit**.
Additionally logged via `lib/logger.ts`/morgan: run id, project id, agent, model,
tool-call counts, `web_search` use count, link-verify counts, repair attempts,
duration, and error stack on failure. **Token/cost** is captured from the SDK
`message.usage` (`input_tokens`, `output_tokens`, plus `server_tool_use.web_search_requests`
where present) and written into `events_json` per run for cost attribution.
**PII:** the app is login-free and topic/brand-content driven; no personal user
profiles are stored. Logs avoid echoing the full `ANTHROPIC_API_KEY` (never logged)
and truncate raw scraped document bodies in logs to previews.

---

## 3. Agent 1 — Research Agent

### 3.1 Purpose / role
Turn a project topic into a structured, citation-backed **research brief** by
autonomously web-searching, reading the strongest sources, and extracting datasets,
statistics, insights, and quotes — each tied to a deduplicated source URL.

### 3.2 Model + justification
**`ANTHROPIC_MODEL_HEAVY` (default `claude-opus-4-7`).** Heavy multi-source synthesis:
the agent must run several searches, weigh and reconcile sources, attribute every
claim correctly, and resist fabricating statistics. Opus's stronger reasoning and
faithfulness justify the higher cost here; this is the highest-stakes factual stage.

### 3.3 Trigger
`POST /api/projects/:id/research/run` (SSE). Re-runnable from the UI ("Re-run research").

### 3.4 Input context assembled
- `project.topic` (required), `project.contentType?`, `project.targetLength?`,
  optional user `angle/notes`.
- Current date (for recency framing) and `WEB_SEARCH_MAX_USES`.

### 3.5 Tools available
**Native `web_search` server tool only.** Declared in `tools`:

```jsonc
{
  "type": "web_search_20250305",   // current native web_search server tool type
  "name": "web_search",
  "max_uses": 5                     // = WEB_SEARCH_MAX_USES (env, default 5)
}
```
Executed by Anthropic; the backend relays each query/result as `tool.web_search` SSE
events and counts uses. No custom tools.

### 3.6 System prompt intent
Role: an exacting research analyst. Governing instructions:
- Use `web_search` to find the most relevant, recent, credible sources for the topic;
  prefer primary sources, reputable publishers, and dated material.
- **Never fabricate** statistics, quotes, dates, or sources. Every statistic, quote,
  and key insight **must** be attributable to a source you actually retrieved.
- Capture exact figures with their context (what is measured, when, by whom).
- Deduplicate sources by canonical URL; assign each a stable id.
- If searches return little or nothing, say so honestly in `summary` and return empty
  arrays rather than inventing content.
- After research, emit the final brief as **strict JSON** matching the schema, with
  citations linking content to `sourceId`s. Output JSON only on the final turn.

Draft system prompt:
> You are a meticulous research analyst. Given a topic, use the web_search tool to
> gather the most relevant, credible, and recent sources, then synthesize a structured
> research brief. Rules: (1) Never invent statistics, quotes, dates, organizations, or
> URLs — only report what appears in sources you retrieved. (2) Every statistic, quote,
> and key insight must cite the source it came from via sourceId. (3) Deduplicate
> sources by canonical URL and give each a short stable id (s1, s2, …). (4) Record
> exact numeric values with their unit and context. (5) If the web returns little or
> nothing on the topic, report that honestly and return empty arrays — do not
> fabricate. When finished, output ONLY the JSON object specified by the schema.

### 3.7 Output schema (zod-validated → `research_briefs.data_json` + `summary`)

```jsonc
{
  "summary": "string (narrative overview)",
  "key_insights": [ { "text": "string", "sourceIds": ["s1", "s3"] } ],
  "statistics":   [ { "value": "string", "label": "string",
                      "context": "string?", "sourceId": "s2" } ],
  "quotes":       [ { "text": "string", "speaker": "string?", "sourceId": "s4" } ],
  "sources":      [ { "id": "s1", "title": "string", "url": "https://…",
                      "publisher": "string?", "accessedAt": "ISO-8601" } ]
}
```
Maps to the `ResearchBrief` DTO (arch §3.1). Backend dedupes `sources` by URL and
verifies every referenced `sourceId` exists (drops dangling references on repair).

### 3.8 Guardrails
- Anti-hallucination: every `statistic`/`quote` must carry a `sourceId` resolving to a
  real retrieved source; insights need ≥1 `sourceId`. Validation drops/repairs any
  item whose `sourceId` is missing from `sources`.
- No source fabrication: `sources[].url` must be a URL the model actually obtained via
  `web_search` (cross-checked against relayed search results where feasible).
- Dedupe sources by normalized URL.
- Budgets: `web_search` ≤ `WEB_SEARCH_MAX_USES`; one structured-output repair; 180 s
  timeout; `max_tokens` 4096.
- Empty-input: empty/whitespace topic → 400 before the agent runs (zod).
- Empty results: produce honest `summary` + empty arrays; **not** an error.

### 3.9 Persisted & logged
- **Persist:** `research_briefs { summary, data_json }`; `agent_runs` (model, events,
  status). Project status transitions `researching` → eligible for KB.
- **Log/observe:** SSE events (`run.start`, `agent.status`, `tool.web_search` ×N,
  `message.delta`, `brief.partial/complete`, `done`); web_search use count; token usage
  + `server_tool_use.web_search_requests`; source count; duration.

---

## 4. Agent 2 — Knowledge Base Builder Agent

### 4.1 Purpose / role
From the user's pasted brand URLs (already scraped + embedded by the backend), distill
two reusable artifacts: a **brand voice profile** and a **content structure template**,
grounded strictly in the actual scraped content.

### 4.2 Model + justification
**`ANTHROPIC_MODEL_LIGHT` (default `claude-sonnet-4-6`).** This is a bounded
extraction/summarization task over text already provided in-context (no tools, no
multi-step reasoning, no factual web claims). Sonnet is fast and cheap and fully
sufficient — reserving opus for the heavy reasoning stages. This is the **only** agent
on the light model.

### 4.3 Trigger
`POST /api/projects/:id/kb/run` body `{ urls: string[] }` (SSE). The backend performs
the deterministic pre-steps **before** the agent:
1. SSRF-guarded fetch of each URL → Readability/cheerio text extraction → `kb_documents`
   (emit `doc.status` per URL).
2. Chunk each doc (~500–800 chars, ~80 overlap) → local MiniLM embeddings (384-dim, L2
   normalized) → `kb_chunks` (emit `kb.embedding` progress).
Only after scraping does the KB Builder Agent run.

### 4.4 Input context assembled
- Concatenated readable text of the successfully scraped documents (`status='done'`),
  truncated to a token budget (e.g. ~12k tokens; longest/representative docs first),
  each prefixed with its title/URL.
- Count of successful vs failed/empty documents (for the "too few sources" guard).

### 4.5 Tools available
**None.** Input is the scraped text; the agent only reads and distills. (Embedding and
retrieval are backend/local, not agent tools.)

### 4.6 System prompt intent
Role: a brand-voice and content-structure analyst. Governing instructions:
- Derive the voice profile and structure template **only** from the supplied example
  content — do not import generic "best practices" or invent traits absent from the
  examples.
- For voice: capture tone, stylistic devices, characteristic vocabulary, explicit
  do's/don'ts inferred from patterns, point-of-view, and an approximate reading level.
- For structure: produce a section-by-section skeleton representative of the examples,
  with typical word count, formatting notes, and heading style.
- If the examples are too few, too short, or empty, say so and produce a conservative
  profile flagged as low-confidence — never confabulate a brand voice from nothing.
- Output strict JSON only.

Draft system prompt:
> You are a brand-voice and content-structure analyst. You are given example articles
> from a single brand. Produce (1) a brand voice profile and (2) a content structure
> template that genuinely reflect THESE examples. Rules: base every trait on evidence
> in the provided text; do not add generic advice or traits not observable in the
> samples. If the samples are too few or too thin to characterize a voice reliably,
> set summary to note the low confidence and keep arrays minimal rather than guessing.
> Output ONLY the JSON object specified by the schema.

### 4.7 Output schema (zod-validated → `brand_profiles.voice_json` / `structure_json`)

**(a) Brand voice profile** (`BrandVoice` DTO):
```jsonc
{
  "tone":       ["string"],   // e.g. "confident", "warm", "data-driven"
  "style":      ["string"],   // stylistic devices: "short punchy sentences", "second person"
  "vocabulary": ["string"],   // characteristic words/phrases observed
  "dos":        ["string"],   // patterns to follow
  "donts":      ["string"],   // patterns to avoid
  "readingLevel": "string?",  // e.g. "Grade 9-10 / conversational professional"
  "summary":    "string"      // 1-2 sentence voice synopsis (notes low confidence if applicable)
}
```
**(b) Content structure template** (`StructureTemplate` DTO):
```jsonc
{
  "sections":         ["string"],  // ordered section skeleton, e.g. "Hook", "Problem", "Solution", "CTA"
  "averageWordCount": 0,           // number? typical total length observed
  "formattingNotes":  "string?",   // lists/subheads/callouts conventions
  "headingStyle":     "string?"    // e.g. "Title Case, question-form H2s"
}
```
Persisted to `brand_profiles`; both are **user-editable** via `PUT /api/projects/:id/kb/profile`.

### 4.8 Guardrails
- Grounded-only: traits must be evidenced by the scraped text; no generic filler.
- **Too-few/empty-sources guard:** if `0` documents scraped successfully → do not run
  the agent; emit `agent.status`/`error` ("No readable content scraped; add valid
  URLs") and leave KB empty. If `1` very short doc (below a min word threshold, e.g.
  < 150 words total) → run but mark `voice.summary` low-confidence.
- Budgets: no tools; one structured-output repair; 180 s; `max_tokens` 4096; input text
  truncated to the token budget.
- Per-URL scrape failures are isolated: a failed URL marks that `kb_document`
  `failed` and is excluded from distillation; the run continues on the rest.

### 4.9 Persisted & logged
- **Persist:** `kb_documents` (per URL, with status/raw_text/word_count),
  `kb_chunks` (text + embedding BLOB), `brand_profiles` (voice + structure);
  `agent_runs`. Project status → `kb_ready`.
- **Log/observe:** `doc.status` per URL (queued/scraping/done/failed + error),
  `kb.embedding` progress, `profile.complete`; counts of docs scraped/failed,
  total chunks embedded, token usage, duration. Raw scraped bodies are truncated to
  previews in logs.

---

## 5. Agent 3a — Drafting Agent

### 5.1 Purpose / role
Write the **initial draft** that follows the brand's structure template, adopts its
voice, and weaves in research facts with inline citations — using only facts present
in the research brief.

### 5.2 Model + justification
**`ANTHROPIC_MODEL_HEAVY` (default `claude-opus-4-7`).** Long-form composition that
must simultaneously (a) obey a structure template, (b) imitate a specific brand voice,
and (c) ground every external claim in the brief with correct inline citations. This is
genuinely heavy generation where faithfulness and voice control matter — opus is
justified over sonnet here per the confirmed "opus for heavier… agents" policy.

### 5.3 Trigger
`POST /api/projects/:id/draft/run` (SSE). Re-runnable ("Regenerate draft").

### 5.4 Input context assembled (backend pre-step + prompt)
- **Retrieval strategy:** build a retrieval query string from the research `summary` +
  top `key_insights` + the brand `structure.sections` intent, embed it locally
  (MiniLM), and call `vectorStore.topK(projectId, queryVector, k=6)` over the project's
  `kb_chunks` (cosine, normalized dot product). Emit `retrieval { chunks }` to the UI.
- Prompt context injected: full `ResearchBrief` (summary, insights, statistics, quotes,
  sources with ids+urls), `BrandVoice`, `StructureTemplate`, and the top-k KB chunks
  (with their document titles) as voice/structure grounding. Plus `contentType` /
  `targetLength` if set.

### 5.5 Tools available
**None.** Retrieval is performed by the backend and injected as context; the model does
not call tools (no risk of new uncited facts entering).

### 5.6 System prompt intent
Role: a senior brand copywriter. Governing instructions:
- Follow the structure template's sections, order, length, and formatting conventions.
- Adopt the brand voice (tone/style/vocabulary, do's/don'ts) shown in the profile and
  the retrieved sample chunks.
- Use **only** facts, statistics, and quotes from the research brief. Do **not**
  introduce external claims that aren't in the brief.
- For each external claim, add an **inline markdown citation** linking to the matching
  `sources[].url` from the brief. Do not invent URLs.
- Produce clean markdown; then list the outline and the citation URLs actually used.

Draft system prompt:
> You are a senior brand copywriter. Write a first draft on the given topic that
> (1) follows the provided content structure template, (2) matches the provided brand
> voice and the style of the sample passages, and (3) incorporates the research
> findings. Strict rules: use ONLY facts, statistics, and quotes that appear in the
> research brief; never add external claims that aren't in it; cite every external claim
> inline as a markdown link to the exact source URL from the brief's sources list; do
> not invent URLs. Output the draft as markdown.

### 5.7 Output schema (→ `drafts`)
Primary output is the streamed markdown draft. A short structured-output turn (or
parse of the response) yields:
```jsonc
{
  "draft":         "string (markdown)",     // → drafts.content_md
  "outline":       ["string"],              // → drafts.outline_json (section headings)
  "citationsUsed": ["https://…"]            // → drafts.citations_json (subset of brief source URLs)
}
```
Maps to the `Draft` DTO. `citationsUsed` must be a subset of `ResearchBrief.sources[].url`.

### 5.8 Guardrails
- Closed-world facts: only brief facts allowed; validation flags any inline link URL
  not present in `sources[]` (repair turn asked to correct/remove).
- Voice/structure adherence: prompt-enforced; sections should map to the template.
- No fabricated URLs/citations.
- Budgets: no tools; 180 s; `max_tokens` 4096; one structured-output repair.
- Empty-input handling: if no research brief exists → 400/`error` ("Run Research
  first"). If no KB/brand profile exists → proceed with a neutral default voice and a
  generic structure, and note in `agent.status` that voice grounding was unavailable
  (do not block drafting).

### 5.9 Persisted & logged
- **Persist:** `drafts { content_md, outline_json, citations_json }`; `agent_runs`.
  Project status → `drafting`.
- **Log/observe:** `retrieval` (k chunks + scores), streamed `message.delta`,
  `draft.complete`; retrieved chunk ids/scores, citation count, token usage, duration.

---

## 6. Agent 3b — Editor Agent

### 6.1 Purpose / role
Produce the **polished final copy** and, critically, **verify every link** in it:
identify all URLs, check each via a deterministic backend tool, then fix or flag
dead/wrong links and confirm every factual claim still maps to a live source.

### 6.2 Model + justification
**`ANTHROPIC_MODEL_HEAVY` (default `claude-opus-4-7`).** Editing + the link-fix
reasoning loop is high-stakes and demands strong judgment (which link to replace vs
remove, preserving meaning/citation integrity while rewriting). Opus is justified.

### 6.3 Trigger
`POST /api/projects/:id/edit/run` (SSE). Re-runnable ("Re-edit / Re-verify links").

### 6.4 Input context assembled
- The current `Draft.content_md`, the full `ResearchBrief` (sources with ids+urls),
  and the KB `BrandVoice` + `StructureTemplate` (to preserve voice while polishing).

### 6.5 Tools available — custom client tool `verify_links`
The agent identifies URLs and calls a **deterministic backend tool** to check them.
(The backend may also auto-extract URLs to seed the first check, but the tool is
exposed so the agent can re-verify after edits.)

**Tool definition (declared to Claude):**
```jsonc
{
  "name": "verify_links",
  "description": "Verify a list of URLs by performing SSRF-guarded HTTP checks. Returns each URL's reachability, HTTP status, final redirect target, and a classification.",
  "input_schema": {
    "type": "object",
    "properties": {
      "urls": { "type": "array", "items": { "type": "string" },
                "description": "Absolute http(s) URLs to verify." }
    },
    "required": ["urls"]
  }
}
```
**Tool input (from the model):** `{ "urls": ["https://…", "https://…"] }`

**Tool output (backend → tool_result, JSON string):**
```jsonc
{
  "results": [
    {
      "url": "https://requested.example/a",
      "status": "ok | redirected | broken | unreachable",
      "httpCode": 200,                 // number? (absent when unreachable)
      "finalUrl": "https://…",         // string? present when redirected
      "note": "string?"                // e.g. "405 on HEAD; GET 200", "TLS error", "timeout"
    }
  ],
  "summary": { "ok": 0, "redirected": 0, "broken": 0, "unreachable": 0 }
}
```
**Implementation (`tools/linkVerify.ts` + `tools/url.ts`):** SSRF guard (reject
loopback/RFC1918/link-local/non-http(s)); try `HEAD`, fall back to `GET` on 405/403;
follow redirects and record `finalUrl`; classify `ok`(2xx) / `redirected`(3xx→2xx with
different host/path) / `broken`(4xx/5xx) / `unreachable`(DNS/timeout/TLS); bounded
concurrency `LINK_VERIFY_CONCURRENCY`; per-request timeout + max response size. Each
checked URL also emits `link.checked { check, index, total }` over SSE.

### 6.6 System prompt intent + loop
Role: a precise managing editor and fact-checker. Governing instructions:
- Polish the draft for clarity, flow, correctness, and adherence to brand voice and
  structure, **without** introducing new external claims or removing valid citations.
- Identify every URL/citation in the copy and call `verify_links` to check them.
- Given the verification results: for any `broken`/`unreachable`/wrong-`redirected`
  link, either replace it with a correct live source URL from the research brief that
  supports the same claim, or remove the unsupported claim — then re-emit corrected
  copy and re-verify.
- Every remaining factual claim must map to a link that verified `ok` (or a benign
  `redirected`). Preserve brand voice and structure throughout.
- Produce final markdown, a per-link verification report, and a brief summary of edits.

**Loop (≤ 2 fix passes, ≤ 6 tool iterations):**
polish → `verify_links` → if any bad links, fix → `verify_links` again → finalize.
Emit `edit.pass { pass, fixedLinks }` per iteration.

Draft system prompt:
> You are a precise managing editor and fact-checker. Polish the draft for clarity,
> flow, and correctness while preserving the brand voice, the structure, and all valid
> citations. Then verify every link: list all URLs in the copy and call verify_links.
> For any link returned as broken, unreachable, or wrongly redirected, replace it with
> a correct live source URL from the research brief that supports the same claim, or
> remove the claim if no live source supports it — then re-verify. Do not introduce new
> external claims. Every factual claim in the final copy must be backed by a link that
> verifies ok. When done, output the final markdown copy, the link verification report,
> and a short summary of what you changed.

### 6.7 Output schema (→ `final_copies`, `source='editor'`, `version=1`)
```jsonc
{
  "finalCopy":   "string (markdown)",          // → final_copies.content_md
  "editSummary": "string",                      // → final_copies.edit_summary
  "linkReport":  [ { "url": "https://…",
                     "status": "ok|redirected|broken|unreachable",
                     "httpCode": 200,
                     "finalUrl": "https://…?",
                     "note": "string?" } ]      // → final_copies.link_report_json
}
```
Maps to `FinalCopy` DTO. `linkReport` is the **final** post-fix verification snapshot
(authoritative, produced by the backend tool — not free-typed by the model).

### 6.8 Guardrails
- Link integrity: the persisted `linkReport` is the backend tool's last-pass output;
  the agent cannot assert a link is `ok` without a real check. If, after ≤2 fix passes,
  links remain `broken`/`unreachable`, they are flagged in the report (the run still
  succeeds — the report surfaces them) and the copy keeps only claims it can support.
- No new external claims introduced during editing.
- Voice/structure preserved.
- Budgets: ≤ 2 fix passes; ≤ 6 tool iterations; link concurrency env-capped; 180 s;
  `max_tokens` 8192 (full copy); one structured-output repair for the final JSON.
- Empty-input: no draft → 400/`error` ("Run Draft first"). Copy with zero URLs →
  skip verification, empty `linkReport`, succeed.

### 6.9 Persisted & logged
- **Persist:** `final_copies { version:1, content_md, edit_summary, link_report_json,
  source:'editor' }`; `agent_runs`. Project status → `final`.
- **Log/observe:** `link.checked` per URL, `edit.pass` per loop, `final.complete`;
  number of links checked, count by status, number fixed, fix-pass count, tool-iteration
  count, token usage, duration.
- **HITL/escalation:** if links remain broken after max passes, the report badges them
  for the human reviewer (UI Link Report) — a soft escalation rather than a hard fail.

---

## 7. Agent 4 — Refinement Chat Agent

### 7.1 Purpose / role
A conversational agent bound to the project's final copy. The user requests revisions,
feedback, and optimizations; the agent refines the copy conversationally while
**preserving brand voice and citations**, can **re-verify links on demand**, and
versions every accepted edit.

### 7.2 Model + justification
**`ANTHROPIC_MODEL_HEAVY` (default `claude-opus-4-7`).** Interactive editing that must
honor nuanced user instructions, keep voice + citation integrity, and reason about
links — same high-stakes editing profile as the Editor. Opus justified.

### 7.3 Trigger
`POST /api/projects/:id/refine/run` body `{ message }` (SSE). Persists the user message
first, then runs.

### 7.4 Input context assembled
- The `ResearchBrief` (for available facts + source URLs), `BrandVoice` +
  `StructureTemplate`, the **current** final copy (highest `final_copies.version`),
  and the prior `chat_messages` history (replayed as conversation), plus the new user
  message.

### 7.5 Conversation / state & versioning model
- **Conversation:** prior `chat_messages` are replayed as alternating user/assistant
  turns; the current final copy is provided as authoritative context each turn (the
  copy is the source of truth, the chat narrates changes).
- **Versioning:** when a turn produces an edit, the new copy is written as
  `final_copies { version = currentMax + 1, source:'refinement' }`; the assistant
  `chat_messages` row stores `version_ref` = that version. If a turn is purely
  feedback/Q&A with no edit, **no new version** is created and `version_ref` is null.
  The UI version switcher lists/compares/restores versions.

### 7.6 Tools available (decided + justified)
- **`verify_links`** (same contract as §6.5) — **always available**, so the agent can
  re-verify links after any edit and keep the live-source guarantee across revisions.
- **`web_search`** (native server tool) — **available but gated.** Justification:
  refinement requests like "add the latest 2026 figure" require *new* facts that aren't
  in the original brief; allowing gated search lets the agent add **cited** new facts
  rather than fabricating. It is gated/conservative: declared with a low `max_uses`
  (`WEB_SEARCH_MAX_USES`), and the system prompt instructs the agent to search **only**
  when the user explicitly asks for new/updated information, and to cite any newly added
  fact with the source URL (and re-verify the link). For pure style/length/tone edits it
  must **not** search. New facts from search are appended to the brief's effective
  source set for citation purposes.

### 7.7 System prompt intent
Role: a collaborative editor refining published-ready copy. Governing instructions:
- Apply the user's requested revision to the current final copy, preserving the brand
  voice, the structure intent, and all existing valid citations.
- Do not silently drop or alter citations; if an edit removes a cited claim, remove its
  citation too — never leave dangling or mismatched links.
- Only call `web_search` when the user explicitly asks for new or updated facts; cite
  any added fact and re-verify its link with `verify_links`. For style/tone/length
  changes, do not search.
- After an edit, call `verify_links` on any new/changed URLs and fix broken ones.
- Respond conversationally: briefly explain what you changed; when you made an edit,
  also output the full updated final copy.

Draft system prompt:
> You are a collaborative editor refining final, near-publish copy through chat. Keep
> the brand voice, structure, and all valid citations intact across every revision.
> When the user asks for new or updated facts, use web_search, cite each new fact with
> its source URL, and verify it with verify_links; otherwise do not search. After any
> edit that changes or adds links, call verify_links and fix anything broken. Never
> leave dangling citations. Reply with a short explanation of your changes, and when you
> edited the copy, include the complete updated markdown copy.

### 7.8 Output schema (streamed + persisted)
- Streamed: `chat.user { message }` (echo of persisted user msg), `message.delta`
  (assistant text), and on an edit `chat.assistant { message, finalCopy }`.
- Persisted:
  - assistant `chat_messages { role:'assistant', content, version_ref? }`.
  - on edit: `final_copies { version+1, content_md, edit_summary (this turn's change),
    link_report_json (post re-verify), source:'refinement' }`.
- The assistant turn yields a small structured object the backend parses:
```jsonc
{
  "reply":     "string",          // conversational explanation → chat_messages.content
  "edited":    true,              // whether an edit was applied
  "finalCopy": "string?",         // markdown, present iff edited → new final_copies.content_md
  "linkReport":[ /* LinkCheck[] */ ] // present iff links changed/verified
}
```

### 7.9 Guardrails
- Voice + citation preservation across edits (prompt-enforced; dangling-citation check
  on output).
- Search gating: no `web_search` for non-factual edits; any searched fact must be
  cited + link-verified.
- Versioning discipline: a new `final_copies` row only on an actual edit; feedback-only
  turns create none.
- Budgets: `web_search` ≤ `WEB_SEARCH_MAX_USES`; ≤ 6 tool iterations; link concurrency
  env-capped; 180 s; `max_tokens` 8192.
- Empty-input: no final copy yet → 400/`error` ("Run the Editor first"). Empty user
  message → 400 (zod).

### 7.10 Persisted & logged
- **Persist:** user + assistant `chat_messages`; new `final_copies` (versioned) on edit;
  `agent_runs`. Project remains `final`.
- **Log/observe:** `chat.user`/`chat.assistant`, `tool.web_search` (if used),
  `link.checked` (on re-verify), `message.delta`; per turn: whether edited, new version,
  search uses, links re-checked, token usage, duration.

---

## 8. Governance & observability (all agents)

### 8.1 What is logged (summary)
For every run: `agent_runs` row (agent, model, status, started/finished, error,
`events_json` = full captured SSE stream). Structured logs capture run/project ids,
tool-call counts, `web_search` use counts, link-verify counts + status breakdown,
JSON-repair attempts, token usage (`input_tokens`/`output_tokens` and
`server_tool_use.web_search_requests`), tool-iteration counts, and duration. The
secret is never logged; raw scraped bodies are truncated to previews.

### 8.2 Cost & rate controls
- Single credential (`ANTHROPIC_API_KEY`); native `web_search` capped per run by
  `WEB_SEARCH_MAX_USES`.
- Per-agent `max_tokens`, ≤ 6 tool iterations, ≤ 2 Editor fix passes, 180 s wall-clock.
- `LINK_VERIFY_CONCURRENCY` bounds outbound HTTP fan-out.
- Model tiering (sonnet for KB distillation; opus only where heavy reasoning is needed)
  controls spend.
- Token/usage written per run enables cost attribution per project/agent.

### 8.3 Security / data handling
- SSRF guard on **all** outbound scraping + link verification (loopback/private/
  link-local/non-http(s) rejected; timeouts; max response size).
- Closed-world facts post-Research; no fabricated stats/URLs; citations validated
  end-to-end.
- Login-free, no personal accounts/PII stored; topic + brand content only.
- Boot resilience: server serves UI without the key; agent endpoints 400 with a clear
  "API key required" message (`/api/health.hasApiKey` gates the UI).

### 8.4 Human-in-the-loop / escalation
- **Stage gates:** the user explicitly approves moving between stages (Research → KB →
  Draft → Edit → Refine) and may re-run any stage. The backend never auto-advances.
- **Editable artifacts:** the brand voice profile + structure template are user-editable
  before drafting (`PUT /api/projects/:id/kb/profile`).
- **Link-report escalation:** links still broken after the Editor's max fix passes are
  badged in the UI Link Report for human review rather than silently dropped.
- **Versioned final copy:** every accepted refinement is a new restorable version, so a
  human can compare/restore — a built-in undo/override path.

### 8.5 Failure → safe default
Every run is wrapped (try/catch): on any failure, emit SSE `error`, set
`agent_runs.status='failed'` and `project.status='error'` with a message, and leave all
prior persisted outputs intact. The client re-reads last-good state via the matching
GET endpoint. No partial/malformed JSON is ever persisted.

---

## 9. Failure-handling matrix

| Scenario | Detection | Agent behavior | Safe default / persistence | UI / observability |
|---|---|---|---|---|
| **Empty web-search results** (Research) | `web_search` returns nothing relevant | Report honestly in `summary`; empty arrays; no fabrication | Persist brief with empty insights/stats; status succeeds | `agent.status` "no strong sources found"; brief shows empty state |
| **Scrape failure for a URL** (KB) | fetch/Readability error, non-html, SSRF-blocked, empty text | Mark that `kb_document` `failed`; exclude from distillation; continue others | Other docs proceed; profile built from successes | `doc.status=failed` + error badge per URL |
| **All URLs fail / no readable content** (KB) | 0 docs `done` | Do not run KB agent | Leave KB empty; stage not advanced | `error` "No readable content scraped; add valid URLs" |
| **Too few/thin sources** (KB) | <150 words total across docs | Run but low-confidence | Persist profile; `voice.summary` flags low confidence | UI note that voice is low-confidence |
| **No KB / no brand profile at Draft** | brand_profiles absent | Draft with neutral default voice + generic structure | Draft persisted; flagged ungrounded | `agent.status` "no brand voice available; using defaults" |
| **No research brief at Draft/Edit** | brief absent | Refuse | 400; no write | `error` "Run Research first" |
| **No draft at Edit** | draft absent | Refuse | 400; no write | `error` "Run Draft first" |
| **No final copy at Refine** | final_copies absent | Refuse | 400; no write | `error` "Run the Editor first" |
| **Copy has zero URLs** (Editor/Refine) | URL extraction empty | Skip `verify_links` | Empty `linkReport`; succeed | report shows "no links" |
| **All links dead** (Editor) | all `broken`/`unreachable` after ≤2 passes | Replace with brief sources where possible, else remove unsupported claims; flag the rest | Persist final copy + report flagging dead links (run still succeeds) | links badged broken in Link Report (HITL escalation) |
| **Link-verify tool error / SSRF block** | tool throws / target blocked | Return that URL as `unreachable` with note; loop continues | Report records `unreachable`; no crash | `link.checked` with `unreachable` + note |
| **Malformed/invalid JSON from model** | zod validation fails | One repair re-prompt with the error | If repair fails → stage `error`; never persist bad JSON | `error` "could not parse agent output"; run `failed` |
| **`web_search` budget exceeded** (Research/Refine) | use count ≥ `WEB_SEARCH_MAX_USES` | Stop searching; synthesize from gathered sources | Persist brief/edit from what was found | budget note logged in `events_json` |
| **Tool-iteration / time budget exceeded** | iterations ≥ 6 or 180 s | Stop loop; finalize best valid output or fail | Persist valid partial, else `error` | duration/iteration logged; `error` if no valid output |
| **Missing `ANTHROPIC_API_KEY`** | config check | Endpoints refuse before model call | 400 "API key required"; UI gated on `/api/health.hasApiKey` | clear UI banner; server still boots/serves |
| **Anthropic API error / timeout** | SDK error | Caught by run wrapper | `agent_runs.failed`, `project.status=error`; prior outputs intact | `error { recoverable }`; retriable from UI |
| **Client disconnects mid-stream** | SSE connection drops | Run continues server-side; state persisted | Latest persisted state re-fetchable via GET | reconnect reads `agent_runs.events_json` / GET endpoint |
```
