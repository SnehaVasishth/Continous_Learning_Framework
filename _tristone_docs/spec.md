# TODO Application — Product Specification

## Project Overview and Goals

A full-stack TODO management application that allows users to create and manage tasks with priority levels, due dates, status tracking, and optional categorisation. The application is structured as a monorepo containing a React/Vite frontend and a Node.js/Express backend that persists data to PostgreSQL.

Primary goals:
- Provide a fast, responsive UI for managing tasks.
- Expose a clean REST API that can be consumed by additional clients in the future.
- Keep the data model simple and extensible.

---

## Target Users

Individual users who need a personal task manager accessible through a web browser.

---

## Core Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | Create todo | Add a new todo with title, optional description, priority, due date, status, and optional category/tag. |
| 2 | Read todos | List all todos; support filtered views. |
| 3 | Update todo | Edit any field of an existing todo. |
| 4 | Delete todo | Permanently remove a todo. |
| 5 | Priority levels | Three levels: `high`, `medium`, `low`. |
| 6 | Due dates | ISO-8601 date stored per todo; optional. |
| 7 | Status tracking | Three states: `pending`, `in-progress`, `completed`. |
| 8 | Categories/tags | Free-text tag field, optional. |
| 9 | Filter by status | Query todos filtered to a specific status value. |
| 10 | Filter by priority | Query todos filtered to a specific priority value. |

---

## Tech Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Frontend framework | React 18 + Vite | Industry-standard SPA framework; Vite provides fast HMR and a minimal config build pipeline. |
| Frontend language | TypeScript (strict) | Catches type errors at compile time; improves IDE support and refactor safety. |
| Backend runtime | Node.js 20 LTS | Same language as the frontend; large ecosystem; LTS stability. |
| Backend framework | Express 4 | Minimal, well-understood HTTP framework; easy to extend. |
| Backend language | TypeScript (strict) | Consistent typing across the monorepo. |
| Database | PostgreSQL 15+ | Mature relational database; strong support for constraints and indexing. |
| DB client | node-postgres (pg) | Official low-level PostgreSQL client; no ORM overhead. |
| Package management | npm workspaces | Native monorepo support without additional tooling. |

---

## Environment Variables

These variables must be defined before running the backend. A `.env.example` file lists them all.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Full PostgreSQL connection string, e.g. `postgresql://user:pass@localhost:5432/todos`. |
| `PORT` | No | Port the Express server listens on. Defaults to `3001`. |
| `CORS_ORIGIN` | No | Allowed origin for CORS. Defaults to `http://localhost:5173`. |

Frontend environment variables (Vite — prefix `VITE_`):

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_BASE_URL` | No | Base URL of the backend API. Defaults to `http://localhost:3001`. |

---

## File and Directory Tree

```
/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── TodoForm.tsx        # Form for creating and editing a todo
│   │   │   ├── TodoItem.tsx        # Single todo row/card with actions
│   │   │   ├── TodoList.tsx        # Renders the list of TodoItem components
│   │   │   └── FilterBar.tsx       # Status and priority filter controls
│   │   ├── hooks/
│   │   │   └── useTodos.ts         # Data-fetching hook; wraps todoApi calls
│   │   ├── types/
│   │   │   └── todo.ts             # Shared TypeScript interfaces for the frontend
│   │   ├── api/
│   │   │   └── todoApi.ts          # Axios/fetch wrappers for every REST endpoint
│   │   ├── App.tsx                 # Root component; composes FilterBar + TodoList + TodoForm
│   │   ├── main.tsx                # Vite entry point; mounts React app
│   │   └── index.css               # Global styles (CSS reset + base tokens)
│   ├── index.html                  # Vite HTML shell
│   ├── package.json
│   ├── tsconfig.json               # Strict TypeScript config (target ES2020, JSX react-jsx)
│   └── vite.config.ts              # Vite config; proxy /api -> backend in dev
├── backend/
│   ├── src/
│   │   ├── routes/
│   │   │   └── todos.ts            # Express router for all /todos endpoints
│   │   ├── db/
│   │   │   ├── index.ts            # pg Pool initialisation and query helper
│   │   │   └── schema.sql          # DDL: CREATE TABLE todos; indexes
│   │   ├── types/
│   │   │   └── todo.ts             # Shared TypeScript interfaces for the backend
│   │   └── server.ts               # Express app setup: CORS, JSON, routes, error handler
│   ├── package.json
│   └── tsconfig.json               # Strict TypeScript config (target ES2022, module CommonJS)
├── preview.config.json             # Preview/deployment configuration
├── .env.example                    # Template for all required environment variables
└── README.md                       # Project setup and run instructions
```
