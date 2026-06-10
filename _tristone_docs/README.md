# TODO App

Full-stack TODO application with React frontend, Express backend, and SQLite database.

## Services

| Service | Stack | Port |
|---------|-------|------|
| Frontend | React + Vite (TypeScript) | Dynamic (preview) |
| Backend | Node.js + Express (TypeScript) | Dynamic (preview) |
| Database | SQLite (via better-sqlite3) | File-based |

## Setup

```bash
# Backend
cd backend && npm install && npm run build

# Frontend
cd frontend && npm install
```

## Environment variables

Copy `.env.example` to `.env` in the `backend/` directory and adjust as needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3001` | Backend listen port |
| `DB_PATH` | `./todos.db` | SQLite database file path |
| `CORS_ORIGIN` | `*` | Allowed CORS origin |

## Running

Start both services via the preview config (handled automatically in preview mode).

For manual local dev:
```bash
# Terminal 1 — backend
cd backend && npm run dev

# Terminal 2 — frontend
cd frontend && VITE_BACKEND_PORT=3001 npm run dev
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/todos` | List todos (filter: `?status=&priority=`) |
| POST | `/api/todos` | Create a todo |
| GET | `/api/todos/:id` | Get a single todo |
| PUT | `/api/todos/:id` | Update a todo |
| DELETE | `/api/todos/:id` | Delete a todo |

## Features

- Create, edit, delete todos
- Priority levels: high, medium, low
- Status tracking: pending, in-progress, completed (click status badge to cycle)
- Due dates and categories
- Filter by status and priority
