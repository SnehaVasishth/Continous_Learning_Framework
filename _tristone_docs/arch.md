# TODO Application — Architecture Document

## Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                        Browser                          │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │                   React App                      │   │
│  │                                                  │   │
│  │  ┌─────────────┐   ┌──────────────────────────┐  │   │
│  │  │  FilterBar  │   │        TodoList           │  │   │
│  │  │  (status,   │   │  ┌────────────────────┐  │  │   │
│  │  │  priority)  │   │  │     TodoItem       │  │  │   │
│  │  └──────┬──────┘   │  │  (edit / delete)  │  │  │   │
│  │         │          │  └────────────────────┘  │  │   │
│  │         └──────────┤       ...repeated...     │  │   │
│  │                    └──────────────────────────┘  │   │
│  │                                                  │   │
│  │  ┌──────────────────────────────────────────┐    │   │
│  │  │              TodoForm                    │    │   │
│  │  │  (create / edit modal)                   │    │   │
│  │  └──────────────────────────────────────────┘    │   │
│  │                                                  │   │
│  │  ┌──────────────────────────────────────────┐    │   │
│  │  │   useTodos hook  ──►  todoApi.ts         │    │   │
│  │  └──────────────────────────────────────────┘    │   │
│  └──────────────────────────┬───────────────────────┘   │
└─────────────────────────────┼───────────────────────────┘
                              │ HTTP / REST (JSON)
                              │ (proxied via Vite in dev)
┌─────────────────────────────▼───────────────────────────┐
│                   Express Backend                        │
│                                                          │
│  server.ts                                               │
│  ├── CORS middleware  (origin from CORS_ORIGIN)          │
│  ├── express.json()                                      │
│  ├── /api/todos  ──►  routes/todos.ts                    │
│  └── global error handler                               │
│                                                          │
│  routes/todos.ts                                         │
│  ├── GET    /api/todos         list + filter             │
│  ├── POST   /api/todos         create                    │
│  ├── GET    /api/todos/:id     read one                  │
│  ├── PUT    /api/todos/:id     full update               │
│  └── DELETE /api/todos/:id     delete                    │
│                                                          │
│  db/index.ts  (pg.Pool)                                  │
└─────────────────────────────┬────────────────────────────┘
                              │ node-postgres (TCP)
┌─────────────────────────────▼────────────────────────────┐
│                     PostgreSQL                            │
│                                                           │
│   Table: todos                                            │
│   Indexes: status, priority, created_at                   │
└───────────────────────────────────────────────────────────┘
```

---

## Data Flow Description

### Read / Filter

1. User selects a filter value in `FilterBar`.
2. `FilterBar` updates state in `App.tsx` (or via context).
3. `useTodos` hook reacts to the changed filter, calls `todoApi.fetchTodos({ status?, priority? })`.
4. `todoApi` issues `GET /api/todos?status=pending&priority=high` (query params omitted when not set).
5. Express router calls `db/index.ts` with a parameterised query that appends `WHERE` clauses dynamically.
6. PostgreSQL returns matching rows; the router serialises them as JSON and responds with `200 OK`.
7. `useTodos` stores the result in local state; `TodoList` re-renders.

### Create

1. User fills in `TodoForm` and submits.
2. `todoApi.createTodo(payload)` issues `POST /api/todos` with a JSON body.
3. Router validates required fields (`title`), inserts the row, and returns the created todo as `201 Created`.
4. `useTodos` appends the new todo to local state.

### Update

1. User clicks edit on a `TodoItem`; `TodoForm` is pre-populated.
2. On submit, `todoApi.updateTodo(id, payload)` issues `PUT /api/todos/:id`.
3. Router runs `UPDATE todos SET ... WHERE id = $1 RETURNING *`; responds `200 OK`.
4. `useTodos` replaces the modified todo in local state.

### Delete

1. User clicks delete on a `TodoItem`.
2. `todoApi.deleteTodo(id)` issues `DELETE /api/todos/:id`.
3. Router runs `DELETE FROM todos WHERE id = $1`; responds `204 No Content`.
4. `useTodos` removes the todo from local state.

---

## API Contract

### Base URL

Development: `http://localhost:3001`
All endpoints are prefixed with `/api`.

### Shared Types

```
Priority  : "high" | "medium" | "low"
Status    : "pending" | "in-progress" | "completed"

Todo {
  id          : number          -- auto-increment primary key
  title       : string          -- required, max 255 chars
  description : string | null   -- optional
  priority    : Priority        -- default "medium"
  status      : Status          -- default "pending"
  due_date    : string | null   -- ISO-8601 date string, e.g. "2026-06-01"
  category    : string | null   -- free-text tag, optional
  created_at  : string          -- ISO-8601 timestamp (set by DB)
  updated_at  : string          -- ISO-8601 timestamp (updated by DB trigger)
}

CreateTodoBody {
  title       : string          -- required
  description?: string
  priority?   : Priority        -- defaults to "medium"
  status?     : Status          -- defaults to "pending"
  due_date?   : string          -- ISO-8601 date
  category?   : string
}

UpdateTodoBody = Partial<CreateTodoBody>  -- all fields optional; at least one expected
```

---

### Endpoints

#### GET /api/todos

Returns all todos, optionally filtered.

Query parameters (all optional):

| Parameter  | Type     | Description                        |
|------------|----------|------------------------------------|
| `status`   | Status   | Filter by status value.            |
| `priority` | Priority | Filter by priority value.          |

Response `200 OK`:

```json
[
  {
    "id": 1,
    "title": "Buy groceries",
    "description": null,
    "priority": "low",
    "status": "pending",
    "due_date": "2026-06-01",
    "category": "personal",
    "created_at": "2026-05-25T10:00:00.000Z",
    "updated_at": "2026-05-25T10:00:00.000Z"
  }
]
```

---

#### POST /api/todos

Creates a new todo.

Request body `application/json`: `CreateTodoBody`

Response `201 Created`: the created `Todo` object.

Response `400 Bad Request` when `title` is missing:

```json
{ "error": "title is required" }
```

---

#### GET /api/todos/:id

Returns a single todo by its numeric `id`.

Response `200 OK`: a single `Todo` object.

Response `404 Not Found`:

```json
{ "error": "Todo not found" }
```

---

#### PUT /api/todos/:id

Replaces updatable fields on an existing todo.

Request body `application/json`: `UpdateTodoBody`

Response `200 OK`: the updated `Todo` object.

Response `404 Not Found`:

```json
{ "error": "Todo not found" }
```

---

#### DELETE /api/todos/:id

Deletes a todo permanently.

Response `204 No Content`: empty body.

Response `404 Not Found`:

```json
{ "error": "Todo not found" }
```

---

## Database Schema

File: `backend/src/db/schema.sql`

```sql
CREATE TYPE priority_level AS ENUM ('high', 'medium', 'low');
CREATE TYPE todo_status    AS ENUM ('pending', 'in-progress', 'completed');

CREATE TABLE IF NOT EXISTS todos (
  id          SERIAL PRIMARY KEY,
  title       VARCHAR(255)   NOT NULL,
  description TEXT,
  priority    priority_level NOT NULL DEFAULT 'medium',
  status      todo_status    NOT NULL DEFAULT 'pending',
  due_date    DATE,
  category    VARCHAR(100),
  created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Keep updated_at current automatically
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE TRIGGER todos_updated_at
  BEFORE UPDATE ON todos
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Indexes for common filter queries
CREATE INDEX IF NOT EXISTS idx_todos_status   ON todos (status);
CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos (priority);
CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos (due_date);
```

---

## Frontend Type Definitions

File: `frontend/src/types/todo.ts`

```typescript
export type Priority = 'high' | 'medium' | 'low';
export type TodoStatus = 'pending' | 'in-progress' | 'completed';

export interface Todo {
  id: number;
  title: string;
  description: string | null;
  priority: Priority;
  status: TodoStatus;
  due_date: string | null;
  category: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTodoPayload {
  title: string;
  description?: string;
  priority?: Priority;
  status?: TodoStatus;
  due_date?: string;
  category?: string;
}

export type UpdateTodoPayload = Partial<CreateTodoPayload>;

export interface TodoFilters {
  status?: TodoStatus;
  priority?: Priority;
}
```

---

## Backend Type Definitions

File: `backend/src/types/todo.ts`

Mirrors the frontend types (same fields) but lives independently so the two packages remain decoupled.

---

## AI Component Details

This application contains no AI components. All logic is deterministic CRUD backed by PostgreSQL.

---

## Key Implementation Notes

### db/index.ts — Connection Pool

```typescript
import { Pool } from 'pg';
const pool = new Pool({ connectionString: process.env.DATABASE_URL });
export const query = (text: string, params?: unknown[]) => pool.query(text, params);
```

### Dynamic Filter Query in routes/todos.ts

The list endpoint builds a parameterised query to avoid SQL injection while supporting optional filters:

```
const conditions: string[] = [];
const values: unknown[]    = [];

if (status)   { conditions.push(`status = $${values.push(status)}`);   }
if (priority) { conditions.push(`priority = $${values.push(priority)}`); }

const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
const sql   = `SELECT * FROM todos ${where} ORDER BY created_at DESC`;
```

### Vite Dev Proxy

`vite.config.ts` proxies `/api` requests to the backend so the frontend can call `/api/todos` without hardcoding a port or dealing with CORS in development:

```typescript
server: {
  proxy: {
    '/api': 'http://localhost:3001'
  }
}
```

### CORS in Production

The `CORS_ORIGIN` environment variable must be set to the deployed frontend origin. The Express CORS middleware is configured as:

```typescript
app.use(cors({ origin: process.env.CORS_ORIGIN ?? 'http://localhost:5173' }));
```
