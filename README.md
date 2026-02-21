<p align="center">
  <img src="docs/logo.svg" alt="Guided Cursor logo" width="120" />
</p>

<h1 align="center">Guided Cursor</h1>
<p align="center"><strong>AI Coding Tutor</strong></p>

<p align="center">
  A web app that helps students learn to code. Instead of giving answers immediately, the AI tutor uses a pedagogy engine with graduated hints, guiding students from Socratic questions through to full solutions. Communication style adapts to the student's self-assessed programming and mathematics ability.
</p>

---

https://github.com/user-attachments/assets/8dbd0589-f60d-4482-9bce-877146652b37

## Development Status

| Phase | Milestone                             | Status   | Guide                                                 |
| ----- | ------------------------------------- | -------- | ----------------------------------------------------- |
| 1     | Auth System                           | Complete | [docs/phase-1-auth.md](docs/phase-1-auth.md)             |
| 2A    | AI Chat and Pedagogy Engine           | Complete | [docs/phase-2-chat.md](docs/phase-2-chat.md)             |
| 2B    | File and Image Uploads                | Complete | [docs/phase-2-chat.md](docs/phase-2-chat.md)             |
| 3A    | Personal Notebook Workspace           | Complete | [docs/phase-3-workspace.md](docs/phase-3-workspace.md)   |
| 3B    | Admin Learning Hub                    | Complete | [docs/phase-3-workspace.md](docs/phase-3-workspace.md)   |
| 4     | Robustness, Cost Control, and Testing | Complete | [docs/phase-4-robustness.md](docs/phase-4-robustness.md) |
| 5     | Production Deployment                 | Planned  | [docs/phase-5-deployment.md](docs/phase-5-deployment.md) |

Additional reference: [docs/semantic-recognition-testing.md](docs/semantic-recognition-testing.md) records the calibration data for the embedding-based pre-filters.

## Features

### Implemented (Phases 1 through 4)

- **Graduated Hints**: the AI tutor escalates from Socratic questions to conceptual nudges, structural outlines, concrete examples, and finally full solutions. A complete answer is never given on the first response.
- **Adaptive Student Levels**: hidden effective levels (floating point, 1.0 to 5.0) update dynamically using an exponential moving average after each completed problem. These levels control communication style independently from hint level.
- **Embedding-Based Pre-Filters**: user messages are classified via cosine similarity against pre-embedded anchors before reaching the LLM. Greetings and off-topic messages are handled instantly with no LLM cost.
- **Three-Provider LLM Failover**: supports Anthropic Claude, Google Gemini, and OpenAI GPT with automatic fallback if the primary provider is unavailable.
- **Streaming Responses**: AI responses stream token by token over a WebSocket connection.
- **File and Image Uploads**: users can attach files directly in chat (drag and drop, file picker, or paste screenshots).
- **Attachment Limits per Message**: up to 3 photos and 2 files per message, with clear validation errors when limits are exceeded.
- **Document Parsing**: document context is extracted from PDF, TXT, PY, JS, TS, CSV, and IPYNB uploads before LLM generation.
- **Secure Attachment Access**: uploaded files are served only through authenticated endpoints tied to the current user.
- **Notebook Workspace (JupyterLite)**: users can open `.ipynb` notebooks in a browser-based Python environment and work in a split layout with tutor chat.
- **Notebook-Aware Tutor Context**: workspace chat includes notebook scope, current cell code, and latest error output.
- **Notebook Autosave and Restore**: notebook state is saved to backend storage and restored on reopen.
- **Scoped Workspace Chat Sessions**: notebook and zone chats are isolated from general chat and restored per module.
- **My Notebooks Management**: upload, open, rename, and delete personal notebooks.
- **Learning Hub**: all users can browse learning zones and open zone notebooks.
- **Admin Dashboard**: admins can create zones, upload/replace/reorder notebooks, view token usage and cost, and review an audit log of all Learning Hub changes.
- **Per-User Zone Progress**: each user gets an independent working copy of zone notebooks, with reset-to-original support.
- **Rate Limiting**: per user LLM request limits (default 5/min), global LLM limits (default 300/min), and concurrent WebSocket connection limits (default 3 per user). All configurable via `.env`.
- **Precise Token Tracking**: input and output token counts are read from each LLM provider's API response, recorded per message, and aggregated into daily usage totals.
- **Admin Cost Visibility**: the admin dashboard shows total input/output tokens and estimated cost for today, this week, and this month.
- **Admin Audit Log**: every Learning Hub modification (zone or notebook create, update, delete) is logged with the admin's email and timestamp.
- **Automated Test Suite**: 34 passing tests covering pedagogy, context building, rate limiting, connection tracking, admin usage, audit log, config parsing, notebook validation, and upload handling.

### Planned (Phase 5)

- **Production Deployment**: Docker + Nginx reverse proxy + HTTPS + CI/CD + database backups.

## Tech Stack

| Layer      | Tools                                                                    |
| ---------- | ------------------------------------------------------------------------ |
| Frontend   | React 18, TypeScript (strict), Vite, Tailwind CSS v4                     |
| Backend    | FastAPI, Uvicorn, SQLAlchemy 2.0 (async), Alembic, Pydantic v2           |
| Auth       | python-jose (JWT), passlib + bcrypt                                      |
| AI         | Anthropic Claude, Google Gemini, OpenAI GPT (configurable with failover) |
| Embeddings | Cohere embed-v4.0 (primary), Voyage AI voyage-multimodal-3.5 (fallback)  |
| Database   | PostgreSQL 15 with asyncpg                                               |
| DevOps     | Docker, Docker Compose                                                   |

## Architecture

```
Frontend (React + TypeScript + Vite + Tailwind)
  ├── Auth pages (login, register, profile, change password)
  ├── Chat page (WebSocket, streaming, session sidebar)
  ├── My Notebooks + Workspace (JupyterLite + scoped chat)
  ├── Learning Hub (zone browse + zone workspace)
  └── Admin dashboard (zone management, usage, audit log)
         │
         │  REST + WebSocket (JWT auth)
         ▼
Backend (FastAPI, async Python)
  ├── Auth API (JWT access tokens + httpOnly refresh cookies)
  ├── Chat API (REST for sessions/usage, WebSocket for streaming)
  ├── Notebook API (upload, list, open, save, rename, delete)
  ├── Zone API (public browse + progress save/reset)
  ├── Admin API (zone management, usage visibility, audit log)
  └── AI subsystem
       ├── LLM abstraction (3 providers, retry + fallback)
       ├── Embedding service (Cohere/Voyage, pre-filter pipeline)
       ├── Pedagogy engine (graduated hints, difficulty classification, EMA levels)
       └── Context builder (system prompt assembly, notebook + cell context injection)
         │
         ▼
PostgreSQL (users, sessions, messages, usage, notebooks, zones, progress)
```

## Getting Started

### Prerequisites

- [Docker](https://www.docker.com/) and Docker Compose
- [Node.js](https://nodejs.org/) 18+
- Git

### Setup

1. Clone the repository:

```bash
git clone https://github.com/your-username/AI-Coding-Tutor.git
cd AI-Coding-Tutor
```

2. Create the environment file:

```bash
cp .env.example .env
```

Edit `.env` and set:

- A strong `JWT_SECRET_KEY` (at least 32 random characters).
- Your LLM API key for the chosen provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`).
- Your embedding API key (`COHERE_API_KEY` or `VOYAGEAI_API_KEY`).
- `LLM_PROVIDER` to your preferred provider (`anthropic`, `openai`, or `google`).
- Optional admin emails in `ADMIN_EMAIL` (supports comma, space, semicolon, or JSON array format).

Keep all keys from `.env.example` in place. `config.py` defines the settings structure only, so missing keys in `.env` will fail startup.

3. Build JupyterLite assets (required for workspace pages):

```bash
bash scripts/build-jupyterlite.sh
```

4. Start the database and backend:

```bash
docker compose up db backend
```

5. In a second terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

6. Open http://localhost:5173 in your browser.

### One-Click Start (Windows)

Double-click `start.bat` in the project root. The script:

- checks Docker engine availability first (15-second timeout);
- starts database and backend containers;
- waits for `http://localhost:8000/health`;
- verifies provider connectivity through `http://localhost:8000/api/health/ai` (retries up to 3 times);
- starts frontend only if at least one LLM provider passes verification; and
- opens your browser and keeps the startup window open for logs.

If startup fails, the script prints container status and recent backend/database logs. If backend container exit code is `137`, it also prints a low-memory hint.

### One-Click Update (Windows)

Double-click `update.bat` in the project root. The script:

- fetches and fast-forwards local Git history (`git pull --ff-only`);
- rebuilds database and backend containers;
- rebuilds the database from scratch via `docker compose down -v` (this removes local DB data);
- runs frontend dependency updates (`npm install`); and
- prints current container status at the end.

If you have local uncommitted changes, `git pull --ff-only` may stop with an error. Resolve that first, then rerun `update.bat`.

## Key Design Decisions

- **Embedding before LLM.** Every user message is embedded once. Greetings and off-topic queries are caught by cosine similarity against pre-embedded anchors, saving LLM calls.
- **Semantic similarity, not hashing.** Same-problem detection uses embedding similarity against prior Q+A context, which is robust to rephrasing.
- **Scoped chat sessions.** Workspace chats are isolated by `(user_id, session_type, module_id)` to avoid session mixing.
- **Token storage.** Access tokens are stored in memory. Refresh tokens are stored in httpOnly cookies. On page load, auth context calls refresh to restore the session.
- **JupyterLite, not JupyterHub.** Notebook execution runs fully in the browser via Pyodide (WebAssembly). The backend persists notebook state and provides tutor context but does not run notebook code server-side.
- **Precise token counts.** Input and output token counts come from each LLM provider's API response, not from character-based estimates. Approximate `count_tokens()` is used only as a pre-call guard.
