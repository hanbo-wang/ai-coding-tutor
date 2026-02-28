# Phase 5: Production Deployment

**Prerequisite:** Phase 4 complete (all tests passing, rate limiting and logging in place).

**Visible result:** The application is live on a public URL with HTTPS, with a documented CI/CD flow for image builds and manual releases.

---

## What This Phase Delivers

- Production Docker images for frontend and backend.
- A production Docker Compose file orchestrating all services.
- Nginx reverse proxy with HTTPS and WebSocket support.
- A CI/CD pipeline via GitHub Actions (GHCR image builds + manual deploy workflow).
- Automated certificate renewal via a `certbot` service profile.
- Database backup guidance.

---

## 1. Production Dockerfiles

### Backend (`backend/Dockerfile.prod`)

Python 3.11-slim base image with runtime dependencies only. Bakes application code into the image (no host bind mounts). Runs Uvicorn with a single worker by default to preserve in-memory rate limiting and WebSocket connection tracking.

### Frontend (`frontend/Dockerfile.prod`)

Multi-stage build: Node 20 builds the React app, then Nginx 1.27-alpine serves the static output. The same container serves the frontend and proxies `/api`, `/ws`, and `/health` to the backend. Nginx loads a template config and substitutes environment variables at container start.

---

## 2. Nginx Configuration

**Config file:** `nginx/nginx.prod.conf`

Nginx serves three roles: HTTPS termination, static frontend hosting, and reverse proxy for backend REST/WebSocket endpoints.

Key behaviours:

- Port 80 redirects to HTTPS (except `/.well-known/acme-challenge/` for certificate issuance and `/health` for liveness probes).
- Port 443 terminates TLS and serves the React SPA with `index.html` fallback.
- `/api/` and `/ws/` are proxied to the backend. WebSocket connections use `Upgrade` headers with 3600s timeouts.
- `/jupyterlite/` adds `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` headers for Pyodide.
- `client_max_body_size` is configurable via the server `.env` file.

---

## 3. Production Docker Compose

**File:** `docker-compose.prod.yml`

Four services: `db` (PostgreSQL 15), `backend` (FastAPI), `frontend` (Nginx), `certbot` (optional `ops` profile for certificate renewal). Images are pulled from GHCR. Named volumes: `pgdata`, `uploads_data`, `notebooks_data`, `certbot_certs`, `certbot_www`.

Operational notes:

- Backend liveness check uses `/health` (non-HTML probes receive JSON), not `/api/health/ai`, so routine probes do not trigger external API checks.
- Upload and notebook storage paths are forced to persistent container paths (`/data/uploads`, `/data/notebooks`).
- The frontend service requires valid TLS certificate files at the configured paths.
- The server-side `.env` file is expected in the same directory as `docker-compose.prod.yml`.

---

## 4. Optional Environment Variable Validation

Optional start-up validation in `backend/app/config.py`:

- Reject placeholder or short `JWT_SECRET_KEY` (minimum 32 characters).
- Reject missing `DATABASE_URL`.
- When `LLM_PROVIDER=google`, ensure `GOOGLE_GEMINI_TRANSPORT` is set and matching credentials are present.
- When using Vertex AI, ensure `GOOGLE_VERTEX_GEMINI_LOCATION` is set (for Gemini 3 preview models, use `global`).

---

## 5. CI/CD with GitHub Actions

### 5.1 CI Build and Publish Images (`ci-build-images.yml`)

Runs on push to `main`. Two jobs:

1. **Verify:** seeds `.env` from `env.dev.example`, runs backend tests with `PYTHONPATH` set, builds JupyterLite assets, and verifies the frontend production build.
2. **Build and push:** builds backend and frontend production images and pushes to GHCR with tags `main` and `sha-<gitsha>`.

### 5.2 Manual Production Deploy (`deploy-prod.yml`)

Manually triggered workflow. Connects to the server via SSH, uploads `docker-compose.prod.yml`, pulls images, and runs `docker compose up -d`. Post-deploy runs a `/health` check.

Inputs: `image_tag` (GHCR tag), `deploy_path` (server directory with `.env`), `reset_mode` (`none` or `all_volumes`), `reset_confirm` (required for volume reset).

Required GitHub Actions secrets: `SSH_HOST`, `SSH_USER`, `SSH_PORT`, `SSH_PRIVATE_KEY`, `GHCR_USERNAME`, `GHCR_TOKEN`.

---

## 6. HTTPS Setup

### 6.1 Prerequisites

Point DNS to the server IP. Allow inbound traffic on ports 80 and 443. Set `TLS_CERT_PATH` and `TLS_KEY_PATH` in the server `.env`.

### 6.2 Initial Certificate Issuance

Use a one-off Certbot container with `--standalone` challenge before the first full deploy. Alternatively, use webroot-based issuance if a temporary HTTP server is available.

### 6.3 Renewal

Start the renewal service profile: `docker compose -f docker-compose.prod.yml --profile ops up -d certbot`. This renews certificates using the webroot path mounted at `/var/www/certbot`.

---

## 7. Deployment Steps

1. Prepare a Linux server with Docker and Docker Compose.
2. Create a deploy directory (e.g. `/opt/ai-coding-tutor`).
3. Create the production `.env` file from `.github/workflows/templates/env.prod.example`. Fill in `GHCR_OWNER`, `SERVER_NAME`, TLS paths, PostgreSQL credentials, `DATABASE_URL`, `JWT_SECRET_KEY`, `CORS_ORIGINS`, Google service account paths, and optional fallback provider keys.
4. Pre-place the Google service account JSON file on the server at the configured host path. Set permissions to 600.
5. Configure GitHub Actions repository secrets for SSH and GHCR access.
6. Prepare the first HTTPS certificate (Section 6).
7. Push to `main` to trigger the image build workflow.
8. Run `Deploy Production (Manual)` with the desired image tag and deploy path. The workflow validates the Google JSON file path and runs `docker compose config` before pulling images.
9. Verify the deployment: `/health` page, login flow, chat streaming, JupyterLite workspace, file uploads.
10. Start certificate renewal (recommended).

---

## 8. Database Backups

Back up PostgreSQL regularly using `docker compose exec` with `pg_dump`. If using the deploy workflow with `reset_mode=all_volumes`, take a backup first. Recommended: daily backups, 7 to 30 day retention, periodic restore tests. Upload and notebook file volumes need separate backup since they are not included in database dumps.

---

## Verification Checklist

- [ ] `docker compose -f docker-compose.prod.yml up -d` starts services without errors.
- [ ] The application loads at `https://yourdomain.example`.
- [ ] The HTTPS certificate is valid.
- [ ] A user can register, log in, chat, and use the workspace.
- [ ] WebSocket connections work through Nginx.
- [ ] JupyterLite loads and runs Python code in production.
- [ ] File uploads work through Nginx within the configured size limits.
- [ ] The CI image build workflow passes on push to `main`.
- [ ] The manual deploy workflow completes successfully.
- [ ] `Deploy Production (Manual)` with `reset_mode=none` completes without removing volumes.
- [ ] The `/health` page returns 200 in a browser, and non-HTML probes still receive liveness JSON.
- [ ] The deploy workflow post-check confirms the current running LLM provider is available.
- [ ] `GET /api/health/ai/models` returns the current running model and smoke-tested available LLM models.
- [ ] `reset_mode=all_volumes` requires `reset_confirm=RESET_ALL_VOLUMES` and fails safely without it.
- [ ] The backup job runs and produces valid `.sql.gz` files.
