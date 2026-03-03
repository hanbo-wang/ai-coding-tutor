# Phase 5: Production Deployment

**Prerequisite:** Phase 4 complete (all tests passing, rate limiting and logging in place).

**Visible result:** The application is live on a public URL with HTTPS, with a documented CI/CD flow for image builds and manual releases.

---

## What This Phase Delivers

- Production Docker images for frontend and backend.
- A production Docker Compose file orchestrating all services.
- Nginx reverse proxy with HTTPS and WebSocket support.
- A CI/CD pipeline via GitHub Actions (GHCR image builds + manual deploy workflow).
- Automatic deployment snapshots for database and file data.
- Manual local snapshot pull tooling.

---

## 1. Production Dockerfiles

### Backend (`backend/Dockerfile.prod`)

Python 3.11-slim base image with runtime dependencies only. Bakes application code into the image (no host bind mounts). Runs Uvicorn with a single worker by default to preserve in-memory rate limiting and WebSocket connection tracking.

### Frontend (`frontend/Dockerfile.prod`)

Multi-stage build: Node 20 builds the React app, then Nginx 1.27-alpine serves the static output. The same container serves the frontend and proxies `/api`, `/ws`, and `/health` to the backend. Nginx loads a template config and substitutes environment variables at container start. Build-time `node_modules` are not copied into the runtime image.

---

## 2. Nginx Configuration

**Config file:** `nginx/nginx.prod.conf`

Nginx serves three roles: HTTPS termination, static frontend hosting, and reverse proxy for backend REST/WebSocket endpoints.

Key behaviours:

- Port 80 redirects to the primary HTTPS domain (except `/.well-known/acme-challenge/` for certificate issuance and `/health` for liveness probes).
- Port 443 terminates TLS, canonicalises hostnames to the primary domain, and serves the React SPA with `index.html` fallback.
- `/api/` and `/ws/` are proxied to the backend. WebSocket connections use `Upgrade` headers with 3600s timeouts.
- `/jupyterlite/` adds `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` headers for Pyodide.
- `client_max_body_size` is configurable via the server `.env` file.

---

## 3. Production Docker Compose

**File:** `docker-compose.prod.yml`

Four services: `db` (PostgreSQL 15), `backend` (FastAPI), `frontend` (Nginx), `certbot` (optional `ops` profile for certificate renewal). Images are pulled from GHCR. Named volumes: `pgdata`, `uploads_data`, `notebooks_data`, `certbot_certs`, `certbot_www`.

Operational notes:

- Backend liveness check uses `/health` (always JSON), not `/api/health/ai`, so routine probes do not trigger external API checks.
- The frontend runtime receives `SERVER_NAME` (primary + additional domains) and `PRIMARY_DOMAIN` (canonical host) from the deploy workflow.
- Upload and notebook storage paths are forced to persistent container paths (`/data/uploads`, `/data/notebooks`).
- The frontend service requires valid TLS certificate files at the configured paths.
- The server-side `.env` file is expected in the same directory as `docker-compose.prod.yml`.

---

## 4. Runtime Configuration Normalisation

Current runtime normalisation in `backend/app/config.py`:

- `WEBSITE_DOMAIN` is required, trimmed, protocol-stripped, and trailing-slash-stripped.
- `CORS_ORIGINS` is optional; when omitted, backend derives it as `https://<WEBSITE_DOMAIN>`.
- `LLM_PROVIDER`, model aliases, and `GOOGLE_GEMINI_TRANSPORT` values are normalised to canonical runtime values.

---

## 5. CI/CD with GitHub Actions

### 5.1 CI Build and Publish Images (`ci-build-images.yml`)

Runs on push to `main`. Two jobs:

1. **Verify:** seeds `.env` from `env.dev.example`, runs backend tests with `PYTHONPATH` set (wrapped in a 20-minute shell timeout and log tail on failure), builds JupyterLite assets, and verifies the frontend production build.
2. **Build and push:** builds backend and frontend production images and pushes to GHCR with tags `main` and `sha-<gitsha>`.

### 5.2 Manual Production Deploy (`deploy-prod.yml`)

Manually triggered workflow. It connects via SSH, uploads `docker-compose.prod.yml` and `scripts/ops/create_backup_snapshot.sh`, derives domain and TLS settings from `WEBSITE_DOMAIN` plus optional `WEBSITE_ALT_DOMAINS`, validates compose config, creates a deployment snapshot, applies the selected data handling mode, then starts services. It also supports a force-reissue mode for certificate repair and lineage cleanup.

Post-deploy checks call `/health` and `/api/health/ai?force=true` from inside the backend container. The gate passes when at least one configured LLM provider is reachable.

Inputs:

- `image_tag` (GHCR tag)
- `deploy_path` (server directory with `.env`)
- `deployment_data_mode`:
  - `keep_existing_data`
  - `restore_from_deployment_backup`
  - `start_with_empty_data`
- `empty_data_confirm` (required only for `start_with_empty_data`; must be `START_WITH_EMPTY_DATA`)
- `force_reissue_certificate`:
  - `false` (default): only issue or expand certificates when files are missing or SAN coverage does not match configured domains.
  - `true`: always reissue the certificate with current domains and then remove legacy non-primary certificate lineages.

Required GitHub Actions secrets: `SSH_HOST`, `SSH_USER`, `SSH_PORT`, `SSH_PRIVATE_KEY`, `GHCR_USERNAME`, `GHCR_TOKEN`.

---

## 6. HTTPS Setup

### 6.1 Prerequisites

Point DNS to the server IP. Allow inbound traffic on ports 80 and 443. Set `WEBSITE_DOMAIN` in the server `.env`, and add `WEBSITE_ALT_DOMAINS` when additional hostnames should share the same certificate.

### 6.2 Initial Certificate Issuance

The deploy workflow automatically issues or expands the certificate for all configured domains (`WEBSITE_DOMAIN` + `WEBSITE_ALT_DOMAINS`) when files are missing or SAN coverage is incomplete. It validates SAN coverage directly from the active certificate file. This requires `CERTBOT_EMAIL`, or `ADMIN_EMAIL` as a fallback. A manual one-off Certbot `--standalone` run is still a valid fallback option.

When `force_reissue_certificate=true`, the workflow reissues the certificate unconditionally using the current configured domains, then removes legacy certificate lineages and keeps the primary lineage.

### 6.3 Renewal

Start the renewal service profile: `docker compose -f docker-compose.prod.yml --profile ops up -d certbot`. This renews certificates using the webroot path mounted at `/var/www/certbot`.

---

## 7. Deployment Steps

1. Prepare a Linux server with Docker and Docker Compose.
2. Create a deploy directory (e.g. `/opt/ai-coding-tutor`).
3. Create the production `.env` file from `.github/workflows/templates/env.prod.example`. Fill in `GHCR_OWNER`, `WEBSITE_DOMAIN`, optional `WEBSITE_ALT_DOMAINS`, PostgreSQL credentials, `DATABASE_URL`, `JWT_SECRET_KEY`, and at least one LLM provider key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or Google credentials/API key).
4. If using Google Vertex AI, place the Google service account JSON file on the server at the configured host path and set permissions to 600.
5. Configure GitHub Actions repository secrets for SSH and GHCR access.
6. Ensure `CERTBOT_EMAIL` (or `ADMIN_EMAIL`) is configured so the workflow can issue certificates automatically when needed.
7. Push to `main` to trigger the image build workflow.
8. Run `Deploy Production (Manual)` with the desired image tag, deploy path, and data mode.
9. Confirm the deployment snapshot path reported by the workflow.
10. If certificate metadata is out of sync, run deployment with `force_reissue_certificate=true` to reissue and clean up legacy lineages.
11. Verify the deployment: `/health` JSON liveness endpoint, `/system-health` diagnostics page (authenticated), canonical-domain redirect behaviour, login flow, chat streaming, JupyterLite workspace, file uploads.
12. Start certificate renewal (recommended).

---

## 8. Backup Snapshots

Snapshot root path:

- `/opt/backups/ai-coding-tutor/daily/YYYY-MM-DD/HHMMSS/`

Each snapshot contains:

- `db.dump.zst`
- `uploads.tar.zst`
- `notebooks.tar.zst`
- `SHA256SUMS`
- `manifest.json`

`manifest.json` records snapshot metadata including domain, server IP, creation timestamp, source, data mode label (for deployment snapshots), sizes, and checksums.

### 8.1 Daily server snapshots

Use:

- `scripts/ops/create_backup_snapshot.sh`
- `scripts/ops/install_daily_backup_cron.sh`

Recommended default:

- daily schedule at `02:05`
- retention `14` days on the server

### 8.2 Manual local snapshot pull

Use:

- `scripts/ops/pull_backup_to_local.sh`

Default behaviour:

- pulls the latest snapshot from `root@<server-ip>:/opt/backups/ai-coding-tutor/daily`
- verifies checksums locally
- keeps local snapshots for `60` days

### 8.3 Deployment snapshot behaviour

Each deployment creates a fresh snapshot before applying `deployment_data_mode`. The deployment flow does not delete or overwrite older snapshot directories under `/opt/backups/ai-coding-tutor/daily`.

---

## Verification Checklist

- [ ] `docker compose -f docker-compose.prod.yml up -d` starts services without errors.
- [ ] The application loads at `https://<your-primary-domain>`.
- [ ] The HTTPS certificate is valid.
- [ ] The certificate SAN list covers `WEBSITE_DOMAIN` and all entries in `WEBSITE_ALT_DOMAINS`.
- [ ] Requests to additional domains return `301` to `https://<your-primary-domain>`.
- [ ] `force_reissue_certificate=true` reissues the certificate and leaves only the primary lineage active.
- [ ] A user can register, log in, chat, and use the workspace.
- [ ] WebSocket connections work through Nginx.
- [ ] JupyterLite loads and runs Python code in production.
- [ ] File uploads work through Nginx within the configured size limits.
- [ ] The CI image build workflow passes on push to `main`.
- [ ] The manual deploy workflow completes successfully.
- [ ] A deployment snapshot is created at `/opt/backups/ai-coding-tutor/daily/YYYY-MM-DD/HHMMSS/`.
- [ ] `deployment_data_mode=keep_existing_data` keeps existing runtime data.
- [ ] `deployment_data_mode=restore_from_deployment_backup` restores from the deployment snapshot.
- [ ] `deployment_data_mode=start_with_empty_data` requires `empty_data_confirm=START_WITH_EMPTY_DATA`.
- [ ] Deployment does not delete any older snapshot folders.
- [ ] `/system-health` loads the authenticated frontend diagnostics page.
- [ ] `GET /api/health/ai/models` returns the current running model and smoke-tested available LLM models.
