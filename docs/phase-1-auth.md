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

### 1. Project skeleton

Create the `backend/` directory with the following files.

| File | Purpose |
|------|---------|
| `backend/Dockerfile` | Python 3.11-slim image. Installs system dependencies (`gcc`, `libpq-dev`), Python requirements, and runs Uvicorn. |
| `backend/requirements.txt` | FastAPI, uvicorn[standard], SQLAlchemy[asyncio], asyncpg, alembic, python-jose[cryptography], passlib[bcrypt], bcrypt, pydantic[email], pydantic-settings, httpx |
| `backend/alembic.ini` | Points to the migrations directory. Logging configured for Alembic and SQLAlchemy. |
| `backend/app/__init__.py` | Empty file that marks the directory as a package. |

### 2. Configuration

**`backend/app/config.py`** uses Pydantic `BaseSettings` to load values from environment variables (with `.env` file support):

```python
class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_access_token_expire_minutes: int
    jwt_refresh_token_expire_days: int
    cors_origins: list[str]
    # Additional AI and upload settings are also defined here.
```

A single global `settings` instance is created at module level and imported everywhere. Keep all keys from `.env.example` in `.env`, because `config.py` defines structure only and does not hard-code runtime values.

### 3. Database setup

**`backend/app/db/session.py`** creates an async SQLAlchemy engine and session factory:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(settings.database_url, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

`echo=True` logs all SQL queries during development. `expire_on_commit=False` keeps ORM objects usable after a commit without re-querying.

**`backend/app/db/init_db.py`** runs on startup and executes `alembic upgrade head`. This keeps the schema aligned with migration history in all environments.

### 4. User model

**`backend/app/models/user.py`** defines the SQLAlchemy 2.0 declarative base and the `User` ORM model.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key, auto-generated via `uuid.uuid4()` |
| `email` | VARCHAR(255) | Unique, indexed. Used for login. |
| `username` | VARCHAR(50) | Unique, indexed. Editable display name used in chat. |
| `password_hash` | VARCHAR(255) | Bcrypt hash |
| `programming_level` | INTEGER | 1 to 5, default 3 |
| `maths_level` | INTEGER | 1 to 5, default 3 |
| `created_at` | TIMESTAMP | Server default via `func.now()` |

The `Base` class declared here is imported by all other models and by Alembic metadata loading.

### 5. User schemas

**`backend/app/schemas/user.py`** contains Pydantic v2 models:

- `UserCreate`: email (validated via `EmailStr`), username (str, 3 to 50 characters), password (minimum 8 characters), programming_level (optional, default 3, range 1 to 5), maths_level (optional, default 3, range 1 to 5).
- `UserLogin`: email, password.
- `UserProfile`: id, email, username, programming_level, maths_level, created_at. Uses `from_attributes = True` to map directly from ORM objects.
- `UserProfileUpdate`: username (optional str), programming_level (optional, range 1 to 5), maths_level (optional, range 1 to 5). Used for the `PUT /api/auth/me` endpoint.
- `ChangePassword`: current_password (str), new_password (str, minimum 8 characters).
- `TokenResponse`: access_token, token_type (defaults to `"bearer"`).

### 6. Auth service

**`backend/app/services/auth_service.py`** contains pure business logic with no HTTP concerns:

- `hash_password(plain: str) -> str`: Hashes a plaintext password using bcrypt.
- `verify_password(plain: str, hashed: str) -> bool`: Verifies a plaintext password against a bcrypt hash.
- `create_access_token(user_id: str) -> str`: Creates a short-lived JWT (30 min by default). The payload includes `sub` (user ID), `exp` (expiry timestamp), and `token_type: "access"`.
- `create_refresh_token(user_id: str) -> str`: Creates a long-lived JWT (7 days by default). Same payload structure with `token_type: "refresh"`.
- `decode_token(token: str) -> dict`: Decodes and validates a JWT. Raises `ValueError` if the token is expired or invalid.

All tokens are signed with HS256 using the `jwt_secret_key` from settings.

### 7. Dependencies

**`backend/app/dependencies.py`**:

- `get_db()`: Async generator that yields an `AsyncSession` and closes it automatically.
- `get_current_user(credentials, db)`: Extracts the Bearer token from the `Authorization` header using FastAPI's `HTTPBearer` scheme. Decodes the token, checks that `token_type` is `"access"`, extracts the user ID from the `sub` claim, and loads the user from the database. Returns the `User` object or raises `401 Unauthorized`.

### 8. Auth router

**`backend/app/routers/auth.py`** is mounted at prefix `/api/auth`.

A helper function `set_refresh_cookie(response, refresh_token)` sets the refresh token as an httpOnly cookie with these properties:

| Property | Value | Notes |
|----------|-------|-------|
| `httponly` | `True` | Prevents JavaScript access |
| `secure` | `False` | Set to `True` in production with HTTPS |
| `samesite` | `"lax"` | CSRF protection |
| `path` | `"/api/auth"` | Cookie is only sent to auth endpoints |
| `max_age` | `604800` | 7 days in seconds |

**Endpoints:**

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/auth/register` | POST | Validates input. Checks email uniqueness (returns 400 "Email already registered" if duplicate). Hashes password, creates user, returns access token in body and sets refresh token cookie. |
| `/api/auth/login` | POST | Accepts email and password. Validates credentials, returns access token in body and sets refresh token cookie. |
| `/api/auth/refresh` | POST | Reads refresh token from cookie, validates it, verifies user still exists, generates a new access token, rotates the refresh token (issues a new one and sets a new cookie), returns new access token. |
| `/api/auth/logout` | POST | Deletes the refresh token cookie. |
| `/api/auth/me` | GET | Returns the current user's profile (requires Bearer token). |
| `/api/auth/me` | PUT | Updates username, programming_level, and maths_level (requires Bearer token). |
| `/api/auth/me/password` | PUT | Changes the user's password. Requires current_password and new_password. Verifies current password before updating. |

The refresh token cookie is never exposed to JavaScript. The session survives page refreshes because the browser automatically sends the cookie, and `AuthContext` calls `/api/auth/refresh` on mount.

### 9. FastAPI app entry point

**`backend/app/main.py`**:

- Creates the FastAPI app with a `lifespan` async context manager. On startup it calls `init_db()` to apply migrations. On shutdown it calls `engine.dispose()` to close the database connection pool.
- Configures CORS middleware with origins from settings and `allow_credentials=True`.
- Includes routers required by the current implementation.
- Provides a `GET /health` endpoint that returns `{"status": "healthy"}` for readiness checks.

### 10. Alembic migration

Create the first migration for the `users` table:

```bash
alembic revision --autogenerate -m "create users table"
alembic upgrade head
```

Migrations are the single source of truth for schema changes. `init_db()` runs `alembic upgrade head` at startup, so containers automatically apply pending revisions.

### 11. Docker Compose

**`docker-compose.yml`** (project root):

- `db` service: PostgreSQL 15 with a named volume (`postgres_data`) for data persistence. Includes a health check using `pg_isready` (5 second interval, 5 retries). Exposed on port 5432.
- `backend` service: Builds from `backend/Dockerfile`, depends on `db` (waits for healthy status), loads `.env` file, mounts `./backend:/app` for live code reloading, runs Uvicorn with `--reload` on port 8000.

**`.env.example`** (project root): Template with all required environment variables including `DATABASE_URL`, `JWT_SECRET_KEY`, `CORS_ORIGINS`, and LLM API keys.

**`start.bat`** (project root): Windows one-click startup script. It checks Docker engine connectivity (15-second timeout), starts `db` and `backend`, waits for `/health`, verifies provider connectivity via `/api/health/ai`, then starts the frontend only when at least one LLM provider is available. If a check fails, it prints diagnostics and recent logs.

---

## Frontend Work

### 12. Project skeleton

Initialise with Vite:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install tailwindcss @tailwindcss/vite react-router-dom
```

This project uses **Tailwind CSS v4**, which does not require a separate `tailwind.config.js` file. Tailwind is loaded via the `@tailwindcss/vite` plugin in `vite.config.ts`.

| File | Purpose |
|------|---------|
| `frontend/vite.config.ts` | Vite config with React and Tailwind v4 plugins, API proxy to `localhost:8000`, WebSocket proxy, and `@` path alias |
| `frontend/src/index.css` | Tailwind import and custom theme colours matching the project logo |
| `frontend/src/main.tsx` | React entry point. Wraps `<App />` in `BrowserRouter` and `AuthProvider` |
| `frontend/src/App.tsx` | React Router setup with four routes (see Section 18) |

### 13. API layer

**`frontend/src/api/http.ts`**: A thin wrapper around `fetch` that manages JWT tokens.

- Stores the access token in memory (not localStorage, for security).
- Attaches the access token to every request as `Authorization: Bearer <token>`.
- Sets `Content-Type: application/json` automatically when a request body is present.
- Includes `credentials: "include"` on all requests so the browser sends httpOnly cookies.
- On a 401 response (except for auth endpoints), automatically calls `/api/auth/refresh`. If the refresh succeeds, retries the original request with the new token. If it fails, redirects to `/login`.
- Handles empty response bodies gracefully (e.g. the logout endpoint).
- Exports `getAccessToken()` so the WebSocket helper (Phase 2) can pass the token as a query parameter.

**`frontend/src/api/types.ts`**: TypeScript interfaces matching the backend schemas: `User` (with email and username), `TokenResponse`, `LoginCredentials` (email + password), `RegisterData` (email + username + password + levels), `UserProfileUpdate`, `ChangePasswordData`.

### 14. Auth context

**`frontend/src/auth/AuthContext.tsx`**:

React context providing: `user`, `login()`, `register()`, `logout()`, `updateProfile()`, `changePassword()`, `isLoading`.

- On mount, calls `/api/auth/refresh` to restore the session. If successful, stores the access token in memory and fetches the user profile via `GET /api/auth/me`. If it fails, the user remains logged out.
- `login()` sends credentials (email + password) to `/api/auth/login`, stores the access token, and fetches the user profile.
- `register()` sends data to `/api/auth/register`, stores the access token, and fetches the user profile.
- `logout()` calls `/api/auth/logout`, then clears the in-memory token and user state.
- `updateProfile()` sends updated username and skill levels to `PUT /api/auth/me` and updates the local user state.
- `changePassword()` sends current and new password to `PUT /api/auth/me/password`.

### 15. Auth pages

**`frontend/src/auth/LoginPage.tsx`**: Form with email and password fields. Calls `login()` from context. Redirects to `/chat` on success. Displays error messages in a red alert box. Submit button is disabled while the request is in progress.

**`frontend/src/auth/RegisterPage.tsx`**: An onboarding-style registration page titled "Tell us about you". The form contains:

1. An email field.
2. A username field (3 to 50 characters).
3. A password field and a confirm password field.
4. A "What best describes you?" section with two range sliders:
   - Programming level (1 to 5, labelled Beginner to Expert).
   - Mathematics level (1 to 5, labelled Beginner to Expert).

Validates that the two passwords match and that the password is at least 8 characters before submitting. On email conflict (400 response), displays "Email already registered." Calls `register()`. Redirects to `/chat` on success.

**`frontend/src/auth/ProtectedRoute.tsx`**: Wraps routes that require authentication. Shows a `LoadingSpinner` while the session check is in progress. If the user is not logged in, redirects to `/login` and preserves the original location so the user can be sent back after logging in.

### 16. Profile page

**`frontend/src/profile/ProfilePage.tsx`**: Displays the user's email (read-only) and "Member since" date. Provides an editable username field. Provides range sliders for programming_level and maths_level (labelled Beginner to Expert). Includes a "Change Password" link that navigates to a separate page. Calls `updateProfile()` on form submission. Shows a green success message or a red error message after saving.

**`frontend/src/profile/ChangePasswordPage.tsx`**: A standalone page at `/change-password`. Contains fields for current password, new password, and confirm new password. Validates that the two new passwords match and the new password is at least 8 characters. Calls `changePassword()` from the auth context. Shows success or error messages. Includes a link back to the profile page.

### 17. Shared components

**`frontend/src/components/Navbar.tsx`**: Top bar with the brand text "Guided Cursor: AI Coding Tutor" (uses the project's brand colour). When logged in, shows links for Chat, My Notebooks, Learning Hub, and Profile, plus a Logout button. An Admin link appears when `user.is_admin` is true. When logged out, shows Login and Register links.

**`frontend/src/components/LoadingSpinner.tsx`**: A simple CSS spinner using Tailwind's `animate-spin` utility. Used by `ProtectedRoute` during session restoration.

### 18. Routing

**`frontend/src/App.tsx`** defines the following routes:

| Path | Component | Auth required |
|------|-----------|---------------|
| `/login` | `LoginPage` | No |
| `/register` | `RegisterPage` | No |
| `/chat` | `ChatPage` (wrapped in `ProtectedRoute`) | Yes |
| `/profile` | `ProfilePage` (wrapped in `ProtectedRoute`) | Yes |
| `/change-password` | `ChangePasswordPage` (wrapped in `ProtectedRoute`) | Yes |
| `/` | Redirects to `/chat` | No (redirect handles auth) |

---

## Verification Checklist

- [ ] `docker compose up db backend` starts the backend and database without errors.
- [ ] `GET /health` returns `{"status": "healthy"}`.
- [ ] `POST /api/auth/register` creates a user with email and username, returns an access token, and sets a refresh cookie.
- [ ] Registering with a duplicate email returns 400 with "Email already registered".
- [ ] `POST /api/auth/login` accepts email and password, returns an access token and sets a refresh cookie.
- [ ] `GET /api/auth/me` returns the user profile with both email and username.
- [ ] `PUT /api/auth/me` updates username and skill levels. Returns the updated profile.
- [ ] `PUT /api/auth/me/password` changes the password after verifying the current password.
- [ ] `POST /api/auth/refresh` returns a new access token and rotates the refresh cookie.
- [ ] Frontend register page shows "Tell us about you" heading with email, username, password, and skill level sliders.
- [ ] Frontend login page accepts email and password.
- [ ] Refreshing the page does not log the user out (refresh token works).
- [ ] Clicking logout clears the session; protected pages redirect to login.
- [ ] Profile page displays the email (read-only), editable username, skill levels, and a "Change Password" link.
- [ ] The Change Password page allows updating the password after verifying the current one.
