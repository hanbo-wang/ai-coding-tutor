# Phase 5: Production Deployment

**Prerequisite:** Phase 4 complete (all tests passing, rate limiting and logging in place).

**Visible result:** The application is live on a public URL with HTTPS, with a documented CI/CD flow for image builds and manual releases.

---

## What This Phase Delivers

- Production Docker images for frontend and backend.
- A production Docker Compose file orchestrating all services.
- Nginx reverse proxy with HTTPS and WebSocket support.
- Optional start-up environment variable validation guidance.
- A CI/CD pipeline via GitHub Actions (GHCR image builds + manual deploy workflow).
- Automated certificate renewal via a `certbot` service profile.
- Database backup guidance.

---

## 1. Production Dockerfiles

### Backend (`backend/Dockerfile.prod`)

The production backend image copies application code into the image and runs without `--reload`.

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

Key points:

- Uses a slim base image with only runtime dependencies.
- Bakes code into the image (no host bind mounts).
- Runs a **single worker** by default to preserve current in-memory rate limiting and WebSocket connection tracking behaviour.

### Frontend (`frontend/Dockerfile.prod`)

The frontend production image is Nginx-based. It serves the built static app and also acts as the reverse proxy.

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
WORKDIR /app/frontend
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/nginx.prod.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/frontend/dist /usr/share/nginx/html
RUN mkdir -p /var/www/certbot
```

Key points:

- Multi-stage build keeps the final image small.
- Nginx loads a template config and substitutes environment variables at container start.
- The same container serves the frontend and proxies `/api`, `/ws`, and `/health`.

---

## 2. Nginx Configuration

Nginx serves three roles in production:

- HTTPS termination
- static frontend hosting
- reverse proxy for backend REST/WebSocket endpoints

Current production config: `nginx/nginx.prod.conf`

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAME};

    client_max_body_size ${CLIENT_MAX_BODY_SIZE};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location = /health {
        proxy_pass http://${BACKEND_UPSTREAM}/health;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${SERVER_NAME};

    ssl_certificate ${TLS_CERT_PATH};
    ssl_certificate_key ${TLS_KEY_PATH};
    client_max_body_size ${CLIENT_MAX_BODY_SIZE};

    root /usr/share/nginx/html;
    index index.html;

    location = /health {
        proxy_pass http://${BACKEND_UPSTREAM}/health;
    }

    location /api/ {
        proxy_pass http://${BACKEND_UPSTREAM};
    }

    location /ws/ {
        proxy_pass http://${BACKEND_UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location ^~ /jupyterlite/ {
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Cross-Origin-Embedder-Policy "require-corp" always;
        try_files $uri $uri/ =404;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Notes:

- `/.well-known/acme-challenge/` is served for certificate issuance and renewal.
- `/health` is exposed on the same origin for low-cost liveness checks.
- `/api/` and `/ws/` are proxied to the backend service.
- `client_max_body_size` is configurable from the server `.env` file.
- JupyterLite requires `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` for Pyodide features.
- Static assets are cached in the current config, and the React SPA uses `index.html` fallback.

---

## 3. Production Docker Compose

**`docker-compose.prod.yml`**

The production stack pulls pre-built images from GHCR and runs four services:

- `db` (PostgreSQL)
- `backend` (FastAPI)
- `frontend` (Nginx-based frontend + reverse proxy)
- `certbot` (certificate renewal, optional `ops` profile)

```yaml
services:
  db:
    image: postgres:15
    env_file:
      - .env
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data

  backend:
    image: ${GHCR_REGISTRY:-ghcr.io}/${GHCR_OWNER:?set GHCR_OWNER}/${GHCR_IMAGE_PREFIX:-ai-coding-tutor}-backend:${IMAGE_TAG:-main}
    env_file:
      - .env
    environment:
      UPLOAD_STORAGE_DIR: /data/uploads
      NOTEBOOK_STORAGE_DIR: /data/notebooks
      BACKEND_RELOAD: "false"
      AUTH_COOKIE_SECURE: ${AUTH_COOKIE_SECURE:-true}
    volumes:
      - uploads_data:/data/uploads
      - notebooks_data:/data/notebooks
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()"]

  frontend:
    image: ${GHCR_REGISTRY:-ghcr.io}/${GHCR_OWNER:?set GHCR_OWNER}/${GHCR_IMAGE_PREFIX:-ai-coding-tutor}-frontend:${IMAGE_TAG:-main}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - certbot_certs:/etc/letsencrypt
      - certbot_www:/var/www/certbot

  certbot:
    image: certbot/certbot:latest
    profiles: ["ops"]
    volumes:
      - certbot_certs:/etc/letsencrypt
      - certbot_www:/var/www/certbot
```

Named volumes used by the production stack:

- `pgdata`
- `uploads_data`
- `notebooks_data`
- `certbot_certs`
- `certbot_www`

Operational notes:

- The backend health check uses `/health`, not `/api/health/ai`, so routine probes do not trigger external API checks.
- Upload and notebook storage paths are forced to persistent container paths (`/data/uploads`, `/data/notebooks`).
- The frontend service depends on valid TLS certificate files at the configured paths (`TLS_CERT_PATH`, `TLS_KEY_PATH`).
- The server-side `.env` file is expected in the same directory as `docker-compose.prod.yml`.

---

## 4. Optional Environment Variable Validation

If you want stricter production checks, add start-up validation in `backend/app/config.py` when the `Settings` object is created:

- If `JWT_SECRET_KEY` is a placeholder or shorter than 32 characters, raise an error immediately.
- If `DATABASE_URL` is not set, raise an error.
- If `LLM_PROVIDER` is set but the corresponding API key is empty, log a warning (or fail fast if you prefer).
- If no embedding provider key is set, log a warning so deployments do not silently miss embedding features.

This is an optional hardening step. It is useful when multiple people deploy the stack.

---

## 5. CI/CD with GitHub Actions

The repository currently uses two workflows:

- **`/.github/workflows/ci-build-images.yml`**
- **`/.github/workflows/deploy-prod.yml`**

### 5.1 CI Build and Publish Images (`ci-build-images.yml`)

This workflow runs on push to `main` (and manually if needed). It has two jobs:

1. **Verify (backend tests + frontend build)**
   - seeds `.env` from `.github/workflows/templates/env.dev.example`
   - installs backend test dependencies
   - runs backend tests from `backend/` with `PYTHONPATH` set to the backend package root
   - builds JupyterLite assets via `scripts/build-jupyterlite.sh`
   - verifies the frontend production build
2. **Build and push GHCR images**
   - builds backend and frontend production images
   - pushes tags to GHCR

Current tag strategy:

- `main`
- `sha-<gitsha>`

This makes rollbacks simple because a deploy can target a specific image build.

### 5.2 Manual Production Deploy (`deploy-prod.yml`)

This workflow is manually triggered and deploys a selected image tag to a server over SSH.

Current deploy flow:

1. Computes lowercase GHCR image names from the repository owner and name.
2. Connects to the server via SSH and creates the deploy directory (`deploy_path`) if needed.
3. Uploads `docker-compose.prod.yml` to that directory.
4. Logs in to GHCR on the server (if `GHCR_USERNAME` and `GHCR_TOKEN` are provided).
5. Runs:
   - `docker compose -f docker-compose.prod.yml pull`
   - `docker compose -f docker-compose.prod.yml up -d`
6. Runs a backend `/health` check from inside the backend container.

Workflow inputs:

- `image_tag`: the GHCR tag to deploy (`main` or `sha-<gitsha>`)
- `deploy_path`: server directory containing the production `.env` file and deployment compose file

Required GitHub Actions repository secrets (deployment workflow):

- `SSH_HOST`
- `SSH_USER`
- `SSH_PORT` (optional if using `22`)
- `SSH_PRIVATE_KEY`
- `GHCR_USERNAME`
- `GHCR_TOKEN`

---

## 6. HTTPS Setup

Use a generic method that works with any server provider and any domain provider.

### 6.1 Prerequisites

1. Point your domain DNS records to the server IP address.
2. Allow inbound traffic on ports `80` and `443`.
3. Prepare the server deployment directory and production `.env` file (see Section 7).
4. Set `TLS_CERT_PATH` and `TLS_KEY_PATH` in the server `.env` file to the certificate paths you will use.

### 6.2 Initial certificate issuance (one-off)

The frontend Nginx container expects certificate files to exist when it starts. For the first certificate, use a one-off Certbot container before the first full deploy.

Example method (standalone challenge):

```bash
docker run --rm -p 80:80 \
  -v <certbot_certs_volume>:/etc/letsencrypt \
  certbot/certbot certonly --standalone \
  -d yourdomain.example \
  -m you@example.com \
  --agree-tos --no-eff-email
```

You can also use a webroot-based method if you already have a temporary HTTP server running and serving the ACME challenge path.

### 6.3 Renewal (ongoing)

After the initial certificate is in place and the stack is deployed, start the renewal service profile:

```bash
docker compose -f docker-compose.prod.yml --profile ops up -d certbot
```

This service renews certificates on a schedule using the webroot path mounted at `/var/www/certbot`.

---

## 7. Deployment Steps

1. **Prepare a Linux server.** Install Docker and Docker Compose.
2. **Create a deploy directory** on the server (for example `/opt/ai-coding-tutor`).
3. **Create the production `.env` file** in that directory using `.github/workflows/templates/env.prod.example` as the template (copy the file contents from your local repository, then save it on the server as `.env`). Fill in real values for:
   - `GHCR_OWNER`
   - `SERVER_NAME`
   - `TLS_CERT_PATH`
   - `TLS_KEY_PATH`
   - `POSTGRES_*`
   - `DATABASE_URL`
   - `JWT_SECRET_KEY`
   - `CORS_ORIGINS`
   - `GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH` (host path to the Google service account JSON file for Vertex AI)
   - `GOOGLE_APPLICATION_CREDENTIALS` (container path, default `/run/secrets/google/service-account.json`)
   - Optional fallback provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `COHERE_API_KEY`, `VOYAGEAI_API_KEY`)
   - `LLM_PROVIDER`, `EMBEDDING_PROVIDER`, and model IDs if you want to override the defaults
4. **Pre-place the Google service account JSON file on the server** at the configured host path (recommended: `/opt/ai-coding-tutor/secrets/ai-coding-tutor-service-account.json`). The backend container mounts this file read-only and exchanges it for Bearer tokens automatically.
   - Recommended setup:
     ```bash
     sudo mkdir -p /opt/ai-coding-tutor/secrets
     sudo cp /path/to/ai-coding-tutor-488300-8641d2e48a27.json /opt/ai-coding-tutor/secrets/ai-coding-tutor-service-account.json
     sudo chmod 600 /opt/ai-coding-tutor/secrets/ai-coding-tutor-service-account.json
     ```
5. **Configure GitHub Actions repository secrets** for SSH and GHCR access (`SSH_*`, `GHCR_*`).
6. **Prepare the first HTTPS certificate** using a one-off Certbot container (Section 6).
7. **Push to `main`** to trigger the image build workflow (`ci-build-images.yml`).
8. **Run `Deploy Production (Manual)`** in GitHub Actions:
   - `image_tag`: use `main` for latest, or `sha-<gitsha>` for a fixed build
   - `deploy_path`: the server directory containing `.env` (for example `/opt/ai-coding-tutor`)
   - `reset_mode`: `none` (default) or `all_volumes` (destructive full volume reset)
   - `reset_confirm`: required only when `reset_mode=all_volumes`; enter `RESET_ALL_VOLUMES`
   - The workflow validates the Google JSON file path from `.env` and runs `docker compose ... config` before pulling images
9. **Verify the deployment**:
   - `https://yourdomain.example/health`
   - login flow
   - chat and WebSocket streaming
   - JupyterLite workspace
   - file upload (within configured size limits)
10. **Start certificate renewal** (recommended):
   ```bash
   docker compose -f docker-compose.prod.yml --profile ops up -d certbot
   ```

---

## 8. Database Backups

Back up PostgreSQL regularly from the production stack using Docker Compose.

Example method (run from the deploy directory on the server):

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U <postgres_user> <postgres_db> \
  | gzip > /backups/ai_coding_tutor_$(date +%Y%m%d).sql.gz
```

If you plan to run the deploy workflow with `reset_mode=all_volumes`, take a backup first. That option runs `docker compose -f docker-compose.prod.yml down -v` and removes all compose-managed volumes for the stack.

Recommended practice:

- run backups daily
- keep a retention window (for example 7 to 30 days)
- test restores periodically
- back up uploaded files and notebooks separately (database backups do not include file volumes)

Example retention cleanup:

```bash
find /backups -name "ai_coding_tutor_*.sql.gz" -mtime +30 -delete
```

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
- [ ] The basic health endpoint `/health` returns 200.
- [ ] The deploy workflow post-check prints `/api/health/ai` and confirms `google` and `vertex_embedding` are available.
- [ ] `reset_mode=all_volumes` requires `reset_confirm=RESET_ALL_VOLUMES` and fails safely without it.
- [ ] The backup job runs and produces valid `.sql.gz` files.
