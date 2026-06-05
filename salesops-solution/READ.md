# Keysight SalesOps Demo (built on ZBrain)

AI-powered SalesOps automation MVP — synthetic data, ZBrain-branded UI, presented as a ZBrain-built solution. **The product surface is ZBrain.** The code happens to use the `claude-agent-sdk` package as the runtime under the hood, but that's a deployment detail — never describe the product as "Claude" anywhere user-facing (UI strings, docs, comments that surface in the UI).

**RFP source:** `C:\Users\Rituraj\Downloads\Keysight-RFP\SalesOps - RFP.xlsx`. Extracted dumps: `C:\Users\Rituraj\rfp_sheets\`.

## Architecture

```
[ React/Vite UI ] <-> [ FastAPI ] <-> [ ZBrain orchestrator runtime ]
       |                  |                       |
   ZBrain theme       SQLite + files          6 stage subagents
   (#1A55F9)          tracing event bus       Intake -> Extract -> Reconcile ->
                                              Decide -> Execute -> Communicate
```

## Pipeline stages (one ZBrain subagent per stage)

1. **Intake** — language detect, intent classify (12 intents incl. multi-intent), spam/phishing screen, track hint
2. **Extract** — PDF/XLSX/DOCX/image (ZBrain document-intelligence agent for OCR), intent-specific schema, structured fields
3. **Reconcile** — cross-check PO line items vs matched quote in CRM; emit price/qty/sku mismatches
4. **Decide** — confidence scoring (0.45·intent + 0.35·extract + 0.20·customer-match, mismatch-penalty caps), tiered autonomy: L4 ≥95% auto / L3 80–94% one-click / L2 <80% full HITL
5. **Execute** — mocked CRM/ERP calls (writes to SQLite, emits trace events); CommunicationLog auto-written on L4
6. **Communicate** — drafts reply in customer's detected language, attaches synthetic SOA PDF

## Languages (Phase 1)

EN, ES, JA. Add more after demo lands.

## Mocked systems

- **CRM** — Customers, Contacts, Quotes (SQLite tables + `/api/data/*` routes)
- **ERP** — Orders, Holds, Work Orders, Shipments, Invoices
- **Field Service** — Assets / Installed Base, Service Contracts, Calibration Certs (with generated PDFs)
- **Email** — inbound queue + outbound CommunicationLog
- **Document Mgmt** — `uploads/` (inbound attachments), `outputs/` (generated SOAs/Invoices/WOs/Cal Certs)

## Tech stack

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy
- **Orchestrator runtime:** the `claude-agent-sdk` package (deployment detail — present it as ZBrain in any user-visible output)
- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **DB:** SQLite (`backend/data/db/app.db`)
- **Doc generation:** ReportLab (PO/SOA/Invoice/WO/Cal Cert PDFs), openpyxl (BOM XLSX), python-docx (spec)
- **Auth (LLM):** the underlying SDK inherits the local dev auth — no `ANTHROPIC_API_KEY` env var required; LLM cost hits the existing subscription quota.

## Run

```
# Backend
cd backend && python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000 --host 127.0.0.1

# Frontend
cd frontend && npm install && npm run dev
```

Open http://localhost:5173. Solution doc at http://localhost:5173/solution.

## Design tokens

- Primary: `#1A55F9`
- Primary-soft: `#1A55F966` (40% opacity overlay)
- Text: `#131426`
- Muted: `#6B7280`
- BG: `#FFFFFF` / `#F8FAFC`
- Font: Inter
- Logo: `https://app.zbrain.ai/images/zbrain-new-logo.svg` (cached at `frontend/public/zbrain-logo.svg`)

## Don't

- Don't surface "Claude" anywhere user-visible (UI strings, doc copy, trace-event messages, error messages). Use **ZBrain orchestrator** / **ZBrain document-intelligence agent** / **ZBrain vision OCR** instead. Internal Python imports referencing `claude_agent_sdk` are fine — those are implementation, not product.
- Don't add real Salesforce/SAP connectors. Mocks are deliberate.
- Don't ask for `ANTHROPIC_API_KEY` — the runtime inherits local auth.
- Don't add comments explaining what code does. Only WHY when non-obvious.
