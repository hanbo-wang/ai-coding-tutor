# Phase 5: Production Deployment

**Prerequisite:** Phase 4 complete (all tests passing, rate limiting and logging in place).

**Visible result:** The application is live on a public URL with HTTPS. All features work end to end in production.

---

## What This Phase Delivers

- Production Docker images for frontend and backend.
- A production Docker Compose file orchestrating all services.
- Nginx reverse proxy with HTTPS and WebSocket support.
- Optional start-up environment variable validation guidance.
- A CI/CD pipeline via GitHub Actions.
- Automated database backups.

---

## 1. Production Dockerfiles

### Backend (`backend/Dockerfile`)

The development Dockerfile from Phase 1 mounts source code for live reloading. For production, the image contains a copy of the code and runs without `--reload`.

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

Key points:

- Uses a slim base image to minimise attack surface.
- Installs only production dependencies (no pytest or dev tools).
- Runs Uvicorn with 2 or more workers depending on the server's CPU count.
- Does not mount the host filesystem.

### Frontend (`frontend/Dockerfile`)

Multi-stage build:

**Stage 1 (build):**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
```

**Stage 2 (serve):**

```dockerfile
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

The output is a lightweight Nginx image serving the compiled static files.

---

## 2. Nginx Configuration

Nginx serves two roles: reverse proxy for the backend API and static file server for the frontend.

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Frontend static files (SPA fallback)
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # JupyterLite static files
    location /jupyterlite/ {
        root /usr/share/nginx/html;
        add_header Cross-Origin-Opener-Policy same-origin;
        add_header Cross-Origin-Embedder-Policy require-corp;
    }

    # Backend REST API
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket endpoints
    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}

# HTTP to HTTPS redirect
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}
```

**JupyterLite headers.** The `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` headers are required for Pyodide's SharedArrayBuffer support, which enables threading inside the browser-based Python kernel.

**WebSocket timeout.** The `proxy_read_timeout` of 86400 seconds (24 hours) keeps WebSocket connections alive for long tutoring sessions.

---

## 3. Production Docker Compose

**`docker-compose.prod.yml`**

```yaml
services:
  db:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: ai_tutor
    restart: always
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      retries: 5

  backend:
    build: ./backend
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/ai_tutor
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      LLM_PROVIDER: ${LLM_PROVIDER}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY}
      EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER}
      COHERE_API_KEY: ${COHERE_API_KEY}
      VOYAGEAI_API_KEY: ${VOYAGEAI_API_KEY}
      CORS_ORIGINS: '["https://yourdomain.com"]'
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health/ai"]
      interval: 30s
      retries: 3

  frontend:
    build: ./frontend
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      - certbot_certs:/etc/letsencrypt
    depends_on:
      - backend
    restart: always

  certbot:
    image: certbot/certbot
    volumes:
      - certbot_certs:/etc/letsencrypt
      - ./frontend/dist:/var/www/html
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do sleep 12h; certbot renew; done'"

volumes:
  pgdata:
  certbot_certs:
```

All sensitive values are read from the `.env` file. The backend health check uses the actual endpoint at `/api/health/ai`.

Current development startup differs slightly: `start.bat` uses `/health` for backend readiness, then calls `/api/health/ai` as a separate verification step before opening the frontend.

Development maintenance also includes `update.bat` (Windows). It fetches and fast-forwards Git, then rebuilds services. It currently runs `docker compose down -v`, so it resets local database volumes. Use it only when you are happy to recreate local data.

---

## 4. Optional Environment Variable Validation

If you want stricter production checks, add start-up validation in `backend/app/config.py` when the `Settings` object is created:

- If `JWT_SECRET_KEY` is the default placeholder or shorter than 32 characters, raise an error immediately.
- If `DATABASE_URL` is not set, raise an error.
- If `LLM_PROVIDER` is set but the corresponding API key is empty, log a warning. If no LLM keys are configured at all, raise an error.
- If neither `COHERE_API_KEY` nor `VOYAGEAI_API_KEY` is set, log a warning (embeddings will not work, but the application can still start for testing).

This "fail fast" approach is a recommended hardening step for production deployments.

---

## 5. CI/CD with GitHub Actions

**`.github/workflows/ci.yml`**

```yaml
name: CI
on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/tests/ -v --asyncio-mode=auto
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:test@localhost:5432/test_db
          JWT_SECRET_KEY: ci-test-secret-key-minimum-32-chars-long
          LLM_PROVIDER: mock
          EMBEDDING_PROVIDER: mock

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build
      - run: cd frontend && npx tsc --noEmit
```

The backend tests use `LLM_PROVIDER=mock` and `EMBEDDING_PROVIDER=mock` so no real API keys are needed in CI. The mock providers are defined in `conftest.py` and patched into the application during tests.

The frontend job runs the full build (which includes TypeScript compilation) and a separate `tsc --noEmit` check to catch type errors without producing output files.

---

## 6. HTTPS Setup

For the initial deployment on a VPS:

1. Point your domain's DNS A record to the server's IP address.
2. Start the stack with HTTP only (modify the Nginx config to listen on port 80 without SSL).
3. Run Certbot to obtain certificates:
   ```bash
   docker compose -f docker-compose.prod.yml run certbot \
     certonly --webroot -w /var/www/html -d yourdomain.com
   ```
4. Update the Nginx config to enable the HTTPS server block (port 443 with the SSL certificate paths).
5. Restart the frontend container so Nginx loads the new configuration.
6. The Certbot container runs in the background and automatically renews certificates every 12 hours.

---

## 7. Deployment Steps

1. **Provision a VPS.** A machine with 2 CPU cores and 4 GB RAM is sufficient for early usage. Providers such as DigitalOcean, Hetzner, or AWS Lightsail all work.
2. **Install Docker and Docker Compose** on the server.
3. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/AI-Coding-Tutor.git
   cd AI-Coding-Tutor
   ```
4. **Create the production environment file:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set:
   - A strong, randomly generated `JWT_SECRET_KEY` (at least 64 characters).
   - A strong `DB_PASSWORD`.
   - Real LLM API keys for the chosen provider.
   - Real embedding API keys (Cohere and/or Voyage AI).
   - `CORS_ORIGINS` set to `["https://yourdomain.com"]`.
   - `ADMIN_EMAIL` with the email addresses of admin users.
5. **Start all services:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```
6. **Set up HTTPS** following the steps in Section 6 above.
7. **Verify** by visiting `https://yourdomain.com` and running through the full user flow: register, log in, chat, open a module, use the workspace.

---

## 8. Database Backups

Add a cron job on the VPS to back up the PostgreSQL database daily:

```bash
# /etc/cron.d/ai-tutor-backup
0 3 * * * docker exec ai-tutor-db pg_dump -U $DB_USER ai_tutor \
  | gzip > /backups/ai_tutor_$(date +\%Y\%m\%d).sql.gz
```

Keep the last 30 days of backups. Remove older files automatically:

```bash
find /backups -name "ai_tutor_*.sql.gz" -mtime +30 -delete
```

The database contains all user accounts, chat history, notebook progress, and skill assessments. Losing it means losing all student work. Daily backups are essential.

---

## Verification Checklist

- [ ] `docker compose -f docker-compose.prod.yml up -d` starts all services without errors.
- [ ] The application loads at `https://yourdomain.com`.
- [ ] The HTTPS certificate is valid (browser padlock icon).
- [ ] A new user can register, log in, chat with the AI tutor, open a module, and use the workspace.
- [ ] WebSocket connections work through Nginx (chat messages stream correctly).
- [ ] JupyterLite loads and executes Python code in production.
- [ ] The CI pipeline passes on push to main.
- [ ] The health endpoint at `/api/health/ai` returns 200 from the public URL.
- [ ] The database backup cron job runs and produces valid `.sql.gz` files.
