<p align="center">
  <img src="docs/logo.svg" alt="Guided Cursor logo" width="120" />
</p>

<h1 align="center">Guided Cursor</h1>
<p align="center"><strong>AI Coding Tutor</strong></p>

<p align="center">
  A web app that teaches students to code through guided problem-solving. The AI tutor never gives answers straight away. It uses graduated hints, starting with Socratic questions and escalating to full solutions only when needed. Communication adapts to the student's programming and maths ability.
</p>

<p align="center"><strong>Website:</strong> <a href="https://ai-coding-tutor.duckdns.org">https://ai-coding-tutor.duckdns.org</a></p>

---

## How It Works

The **pedagogy engine** controls every AI response:

1. **Graduated hints**: five levels from Socratic questions, through conceptual nudges, structural outlines, and concrete examples, to full solutions. New problems always start at a lower hint level; follow-ups escalate one level at a time.
2. **Adaptive student levels**: effective programming and maths levels (1.0–5.0) update automatically via exponential moving average, shaping how the tutor explains concepts. When a student updates their self-assessed level in Profile, the corresponding effective level is rebased to that value.
3. **Same-problem and elaboration detection**: the LLM determines whether the student is continuing the same problem and whether the message is a follow-up elaboration request, then adjusts the hint level accordingly.
4. **Difficulty classification**: the LLM rates each message for programming and maths difficulty so the tutor can calibrate the gap between the problem and the student's level.

## Features

- **Streaming AI chat** over WebSocket with session management, chat history, and session-isolated hidden pedagogy state.
- **Three LLM providers with failover**: Google Gemini (Google AI Studio or Vertex AI via explicit transport selection, default provider), Anthropic Claude, OpenAI GPT.
- **File and image uploads**: drag-and-drop, file picker, or paste. Up to 3 images and 2 documents per message. PDFs, code files, and notebooks are parsed for context.
- **Notebook workspace**: open `.ipynb` files in a split-pane layout with JupyterLite (browser-side Python via Pyodide) on the left and AI tutor chat on the right. Pre-loaded with NumPy, SciPy, Pandas, Matplotlib, and SymPy.
- **Notebook-aware tutoring**: the tutor sees notebook content, the current cell code, and the latest error output.
- **Learning Hub**: admin-managed learning zones with curated notebooks and shared dependency files. Each student gets an independent working copy with reset-to-original support.
- **Admin dashboard**: zone management, bulk asset import, token usage and cost tracking (today / this week / this month), a full audit log, and a direct link to the `/health` diagnostics page.
- **Rate limiting and cost control**: per-user and global request limits, weekly token budgets, concurrent connection caps. All configurable via `.env`.
- **Precise token and cost tracking**: counts come from each provider's API response and are stored per message.
- **Optional semantic filters (disabled by default)**: embedding-based greeting and off-topic detection to handle non-tutoring messages without calling the LLM.

## Tech Stack

| Layer      | Tools                                                                     |
| ---------- | ------------------------------------------------------------------------- |
| Frontend   | React 18, TypeScript (strict), Vite, Tailwind CSS v4                      |
| Backend    | FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2                     |
| AI         | Google Gemini (AI Studio or Vertex AI), Anthropic Claude, OpenAI GPT (configurable with failover) |
| Embeddings | Cohere (default), Vertex AI, Voyage AI                                    |
| Database   | PostgreSQL 15, asyncpg                                                    |
| DevOps     | Docker Compose, Nginx, GitHub Actions CI/CD                               |

## Architecture

```
Frontend (React + Vite + Tailwind)
  ├── Auth (login, register, profile)
  ├── Chat (WebSocket streaming, session sidebar)
  ├── Notebook workspace (JupyterLite + scoped chat)
  ├── Learning Hub (zone browse + zone workspace)
  └── Admin dashboard (zones, usage, audit log)
         │
         │  REST + WebSocket (JWT)
         ▼
Backend (FastAPI, async)
  ├── Auth API (access tokens in memory, refresh in httpOnly cookies)
  ├── Chat API (sessions, messages, streaming)
  ├── Notebook API (CRUD, save/restore)
  ├── Zone API (browse, progress, runtime files)
  ├── Admin API (zone management, usage, audit log)
  └── AI subsystem
       ├── LLM providers (3 providers, retry + fallback)
       ├── Embedding service (3 providers, semantic pre-filters)
       ├── Pedagogy engine (graduated hints, difficulty, EMA levels)
       └── Context builder (system prompt, notebook context)
         │
         ▼
PostgreSQL (users, sessions, messages, usage, notebooks, zones, progress)
```

## Getting Started

### Prerequisites

- [Docker](https://www.docker.com/) and Docker Compose
- [Node.js](https://nodejs.org/) 18+

### Setup

1. **Clone and configure:**

```bash
git clone https://github.com/hanbo-wang/ai-coding-tutor.git
cd ai-coding-tutor
cp .github/workflows/templates/env.dev.example .env
```

2. **Edit `.env`** and set at minimum:

   - `JWT_SECRET_KEY`: at least 32 random characters.
   - `GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH`: path to your Google service account JSON file.
   - Optional: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` for fallback providers.
   - Optional: `ADMIN_EMAIL` for admin dashboard access.

3. **Build JupyterLite assets** (required once for notebook workspace):

```bash
bash scripts/build-jupyterlite.sh
```

4. **Start the app:**

```bash
docker compose up db backend        # Terminal 1
cd frontend && npm install && npm run dev  # Terminal 2
```

5. Open **http://localhost:5173**.

### One-Click Start (Windows)

Double-click `start.bat`. It starts Docker containers, waits for health checks, verifies AI provider connectivity, launches the frontend, and opens your browser.

### One-Click Update (Windows)

Double-click `update.bat`. It pulls the latest code, rebuilds containers (with a fresh database), and updates frontend dependencies.

## Production Deployment

Production runs on Docker Compose + Nginx reverse proxy + HTTPS, deployed via GitHub Actions.

- **Images**: pushed to GHCR on every `main` push, tagged `main` and `sha-<gitsha>`.
- **Deploy**: run the manual `Deploy Production` workflow in GitHub Actions with an image tag.
- **Rollback**: re-run the deploy workflow with an earlier image tag.
- **Config**: create `.env` from `.github/workflows/templates/env.prod.example`. Pre-place the Google service account JSON on the server.
- **Health**: `/health` (browser page for configured models and smoke-tested availability; non-HTML probes still get liveness JSON), `/api/health/ai` for provider verification, `/api/health/ai/models` for model-level smoke checks.

## Documentation

| Document | Description |
| -------- | ----------- |
| [phase-1-auth.md](docs/phase-1-auth.md) | Authentication system |
| [phase-2-chat.md](docs/phase-2-chat.md) | Chat, pedagogy engine, file uploads |
| [phase-3-workspace.md](docs/phase-3-workspace.md) | Notebook workspace and Learning Hub |
| [phase-4-robustness.md](docs/phase-4-robustness.md) | Rate limiting, cost control, testing |
| [phase-5-deployment.md](docs/phase-5-deployment.md) | Production deployment and CI/CD |
| [ai-models-and-pricing.md](docs/ai-models-and-pricing.md) | Supported models, defaults, pricing |
| [semantic-recognition-testing.md](docs/semantic-recognition-testing.md) | Embedding threshold calibration |
