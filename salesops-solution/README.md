# Keysight SalesOps Demo (ZBrain)

End-to-end MVP demo for the Keysight RFP — AI-powered SalesOps automation with synthetic data.

## Quick start

```bash
# Backend (port 8000)
cd backend
python -m venv .venv && source .venv/Scripts/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed   # one-time: load synthetic dataset
uvicorn app.main:app --reload --port 8000

# Frontend (port 5173)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## What's in the demo

- **Inbox** — synthetic customer emails (EN/ES/JA) with PO/quote/spam/work-order intents and PDF/Excel/image attachments.
- **Live Trace** — every agent step (input/output/duration/tokens) streams to the UI as the pipeline runs.
- **HITL Queue** — low-confidence cases land here with approve / edit / reject controls; corrections feed back into agent context.
- **Analytics** — automation rate, accuracy, processing time, drift signal.
- **Feedback Log** — every CSR override is captured for continuous-learning.
