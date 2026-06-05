# Keysight Governance Dashboard

A standalone read-only governance / observability dashboard for the
**Keysight SalesOps** AI pipeline. Surfaces Microsoft AGT-inspired
concepts (policy decisions, agent trust, audit trail, MCP gateway
security, OWASP ASI-10 compliance, SLOs) computed from the data the
SalesOps backend already collects.

This project is **frontend-only**. It calls the SalesOps backend at
`/api/governance/*` for every signal. There is no governance DB.

```
                                ┌───────────────────────────────────────┐
                                │  Keysight SalesOps backend (FastAPI)   │
                                │   /api/governance/summary             │
   ┌────────────────────────┐   │   /api/governance/audit-log           │
   │ Governance Dashboard   │──▶│   /api/governance/agents              │
   │ (this project)         │   │   /api/governance/policies            │
   │ React + Vite + Tailwind│   │   /api/governance/compliance          │
   └────────────────────────┘   │   /api/governance/slo                 │
                                │   POST /api/governance/alerts/ack     │
                                │   POST /api/governance/alerts/resolve │
                                └───────────────────────────────────────┘
                                            ▲
                                            └── reads pipelines, trace_events,
                                                hitl_tasks, drift_alerts,
                                                knowledge_rules from the live
                                                SalesOps SQLite database
```

## What it shows

Six tabs, each polled every 15 seconds:

1. **Overview** — fleet rollup. Governed-pipeline count, active policies,
   pending HITL, average trust score, OWASP coverage. Live breach alerts
   from the Continuous-Learning drift monitor. Pipeline funnel.
2. **Audit Trail** — paginated trace-event log with a SHA-256 hash chain.
   Tamper detection visualises a broken chain when an entry's hash does
   not match the recomputed value.
3. **Agent Fleet** — one DID and trust ring per pipeline stage. Allowed /
   denied tools, credential TTL, trust histogram, kill events.
4. **Policy Engine** — active rules, conflict-resolution strategy, per-agent
   policies, confidence gates, tool allow-deny matrix, blocked-pattern
   categories with fire counts, tool-invocation breakdown.
5. **Compliance** — OWASP ASI-10 control coverage with per-control
   evidence grades, attestation hash, MCP gateway tool-scan status,
   per-ring rate limits.
6. **SLO Monitor** — six SLOs (latency, success, HITL resolution,
   confidence floor, cost-per-task, hallucination rate) with budget
   burn rate, per-stage P50/P95/P99, cost guardrails.

## Read / write contract

- **Read-only by default.** Every tab polls the SalesOps backend; nothing
  is written when the dashboard renders.
- **Two write actions** are exposed (acknowledge drift alert, resolve drift
  alert). Both are stamped `actor=governance_dashboard` in the audit
  trail because the dashboard does not collect an operator identity.
  Resolving an alert also clears the circuit breaker so the SalesOps
  orchestrator stops forcing the affected segment to L2 review.

## Run

### Prerequisites

- Node 18+ (Vite 6 requires it)
- The SalesOps backend running on `localhost:8000`. Start it from the
  SalesOps repo:

  ```bash
  cd ~/Downloads/ZBrain-Solution-Builder/salesops-solution/backend
  .venv/bin/python -m uvicorn app.main:app --port 8000 --host 127.0.0.1
  ```

### Install + dev

```bash
cd ~/Downloads/keysight-salesops-governance
npm install
npm run dev
```

Dev server: <http://localhost:5175/keysight-salesops-governance/>

Vite proxies `/api/*` to `localhost:8000` automatically.

### Production build

```bash
npm run build
```

Output: `dist/`. Serve as a static SPA with the base path
`/keysight-salesops-governance/`.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `VITE_SALESOPS_API_URL` | (empty) | Override the API base URL when the dashboard is served from a different origin than the backend. Empty means same-origin (good for dev because of the Vite proxy and for production behind a single reverse proxy). |

## Project layout

```
src/
├── App.tsx                       # router for the 6 tabs
├── api.ts                        # typed HTTP client; flat + nested .governance surface
├── index.css                     # imported from the SalesOps repo (same brand tokens)
├── components/
│   ├── Layout.tsx                # header, nav, "read-only" demo chip
│   └── PageHeader.tsx            # shared title bar + last-refresh stamp
├── lib/
│   └── usePolling.ts             # 15-second auto-refresh hook
├── pages/
│   ├── Overview.tsx
│   ├── Audit.tsx
│   ├── Agents.tsx
│   ├── Policies.tsx
│   ├── Compliance.tsx
│   ├── Slo.tsx
│   └── _governance_source.tsx    # the 3,211-line tab implementations ported
│                                   from the previous SalesOps governance snapshot;
│                                   imported by the route pages above
└── main.tsx
```

`_governance_source.tsx` is the full visual treatment for every tab. It is
imported by the route-level pages so each page is a thin wrapper that
polls the right endpoint and renders the matching tab component.

## Honest gaps

The data backing several governance views is partly synthetic:

- The **five stage agents** (`did:mesh:keysight-salesops-{intake,extract,decide,execute,communicate}`) are static identities defined in the backend; there is no real agent provisioning.
- **Tool fingerprints**, **OWASP ASI-10 control definitions**, **MCP gateway tool-scan results**, and the **policy default values** are seed data in the backend module, not pulled from a control framework or threat-intel service.
- **Hash-chain integrity** is recomputed at request time over the trace events; tampering can only be observed if the underlying `trace_events` table is mutated directly (the orchestrator never writes a row with a mismatched hash, so this branch is exercised only by manual DB edits).
- The **`/seed_demo_slo` endpoint** (`POST /api/governance/seed_demo_slo`) inserts synthetic Pipeline / HitlTask / TraceEvent rows to populate empty SLO rolling windows. Call it once after a fresh DB to make the SLO tab non-empty. The endpoint is opt-in; the old auto-seed-on-read behaviour was removed when the file was ported.

These are honest demo simplifications, not bugs. Real production governance would replace each one with a live integration (Agent Provisioning Service, threat-intel API, signed audit-log service, etc.).
