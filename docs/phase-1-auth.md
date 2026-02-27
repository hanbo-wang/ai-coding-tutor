# Phase 1: Project Scaffolding and User Authentication

**Visible result:** User can register with an email, username, and password, then log in, log out, and view their profile in the browser. Email is the unique login identifier. Username is a display name that can be changed later.

---

## What This Phase Delivers

- Docker Compose running FastAPI + PostgreSQL.
- A `users` table with email, username, hashed password, and self-assessment fields.
- REST endpoints for register, login, token refresh, get current user, update profile, and change password.
- A React frontend with login, registration ("Tell us about you" onboarding), and profile pages.
- JWT-based auth that survives page refreshes via refresh tokens stored in httpOnly cookies.

---

## Backend Work

### 1. Project Skeleton

`backend/Dockerfile`: Python 3.11-slim, system deps, pip install, Uvicorn.
`backend/requirements.txt`: FastAPI, uvicorn, SQLAlchemy[asyncio], asyncpg, alembic, python-jose, bcrypt, pydantic, pydantic-settings, httpx.

### 2. Configuration

**`backend/app/config.py`:** Pydantic `BaseSettings` loading from `.env`. Core fields: `database_url`, `jwt_secret_key`, `jwt_access_token_expire_minutes`, `jwt_refresh_token_expire_days`, `cors_origins`, plus AI and upload settings. A single global `settings` instance is imported everywhere.

### 3. Database Setup

**`backend/app/db/session.py`:** Async SQLAlchemy engine and session factory (`expire_on_commit=False`).
**`backend/app/db/init_db.py`:** Runs `alembic upgrade head` on startup.

### 4. User Model

**`backend/app/models/user.py`:** SQLAlchemy 2.0 declarative model.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `email` | VARCHAR(255) | Unique, indexed |
| `username` | VARCHAR(50) | Unique, indexed |
| `password_hash` | VARCHAR(255) | Bcrypt |
| `programming_level` | INTEGER | 1-5, default 3 |
| `maths_level` | INTEGER | 1-5, default 3 |
| `created_at` | TIMESTAMP | Server default |

### 5. User Schemas

**`backend/app/schemas/user.py`:** `UserCreate` (email, username, password, optional levels), `UserLogin` (email, password), `UserProfile` (read model with `from_attributes`), `UserProfileUpdate` (optional username and levels; updating a skill slider rebases the corresponding hidden effective level), `ChangePassword`, `TokenResponse`.

### 6. Auth Service

**`backend/app/services/auth_service.py`:** `hash_password`, `verify_password` (bcrypt), `create_access_token` (30 min, HS256), `create_refresh_token` (7 days), `decode_token`.

### 7. Dependencies

**`backend/app/dependencies.py`:** `get_db()` (async session generator), `get_current_user` (extracts Bearer token, validates access type, loads user or raises 401).

### 8. Auth Router

**`backend/app/routers/auth.py`** (prefix `/api/auth`):

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/auth/register` | POST | Create user, return access token, set refresh cookie |
| `/api/auth/login` | POST | Validate credentials, return tokens |
| `/api/auth/refresh` | POST | Read cookie, rotate refresh token, return new access token |
| `/api/auth/logout` | POST | Delete refresh cookie |
| `/api/auth/me` | GET | Return current user profile |
| `/api/auth/me` | PUT | Update username and skill levels |
| `/api/auth/me/password` | PUT | Change password (requires current password) |

Refresh cookie: httpOnly, secure (production), samesite lax, path `/api/auth`, 7 day max age.

### 9. FastAPI App

**`backend/app/main.py`:** Lifespan context manager calls `init_db()` on startup and `engine.dispose()` on shutdown. CORS middleware with `allow_credentials=True`. `GET /health` returns a browser-facing health page or JSON for probes.

### 10. Alembic Migration

First migration creates the `users` table. `init_db()` runs `alembic upgrade head` at startup so containers apply pending revisions automatically.

### 11. Docker Compose

`db`: PostgreSQL 15 with named volume and health check. `backend`: depends on db (healthy), loads `.env`, mounts source for live reload, port 8000.

**`start.bat`**: Windows one-click startup. Checks Docker, starts services, waits for health, verifies AI provider connectivity, then launches the frontend.

---

## Frontend Work

### 12. Project Skeleton

Vite + React + TypeScript + Tailwind CSS v4 (via `@tailwindcss/vite` plugin). API proxy and WebSocket proxy configured in `vite.config.ts`.

### 13. API Layer

**`frontend/src/api/http.ts`:** Fetch wrapper with in-memory access token, automatic Bearer header, `credentials: "include"`, 401 retry via `/api/auth/refresh`, and `getAccessToken()` export for WebSocket use.

**`frontend/src/api/types.ts`:** TypeScript interfaces matching backend schemas.

### 14. Auth Context

**`frontend/src/auth/AuthContext.tsx`:** Provides `user`, `login`, `register`, `logout`, `updateProfile`, `changePassword`, `isLoading`. Restores session on mount via `/api/auth/refresh`.

### 15. Auth Pages

**`LoginPage.tsx`**: Email + password form, redirects to `/chat` on success.
**`RegisterPage.tsx`**: "Tell us about you" onboarding with email, username, password, confirm password, and two skill sliders (1-5).
**`ProtectedRoute.tsx`**: Loading spinner during session check, redirects to `/login` if unauthenticated.

### 16. Profile Page

**`ProfilePage.tsx`**: Read-only email, editable username, skill sliders (updating rebases hidden effective levels), change password link.
**`ChangePasswordPage.tsx`**: Current password verification, new password with confirmation.

### 17. Shared Components

**`Navbar.tsx`**: Brand text, nav links (Chat, My Notebooks, Learning Hub, Profile), Admin link when `is_admin`, Logout button.
**`LoadingSpinner.tsx`**: Tailwind `animate-spin` spinner.

### 18. Routing

| Path | Component | Auth |
|------|-----------|------|
| `/login` | LoginPage | No |
| `/register` | RegisterPage | No |
| `/chat` | ChatPage | Yes |
| `/profile` | ProfilePage | Yes |
| `/change-password` | ChangePasswordPage | Yes |
| `/` | Redirect to `/chat` | No |

---

## Verification Checklist

- [ ] Backend and database start without errors.
- [ ] Health endpoint returns 200.
- [ ] Register creates user, returns token, sets cookie.
- [ ] Duplicate email returns 400.
- [ ] Login works with email + password.
- [ ] Profile returns email and username.
- [ ] Profile update rebases hidden effective levels when skill sliders change.
- [ ] Password change verifies current password.
- [ ] Refresh endpoint rotates tokens.
- [ ] Page refresh preserves session.
- [ ] Logout clears session; protected pages redirect to login.
