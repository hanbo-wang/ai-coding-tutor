# Phase 1: Project Scaffolding and User Authentication

**Visible result:** A user can register with email verification, log in, reset a password either by current password (signed-in) or by email code, and manage profile details. Email is the unique login identifier and is not editable from profile updates. Username is a separate display field and can be changed.

---

## What This Phase Delivers

- Docker Compose stack with FastAPI + PostgreSQL.
- User authentication with access tokens and refresh cookies.
- Email verification for registration and password reset code flows.
- Two reset-password modes:
  - Signed-in reset using current password.
  - Email-code reset flow.
- React pages for login, registration, forgot-password, and profile password reset actions.

---

## Backend Work

### 1. Project Skeleton

`backend/Dockerfile`: Python 3.11-slim runtime image with app dependencies.  
`backend/requirements.txt`: FastAPI, uvicorn, SQLAlchemy[asyncio], asyncpg, alembic, python-jose, bcrypt, pydantic, pydantic-settings, httpx.

### 2. Configuration

**`backend/app/config.py`** loads settings from environment files.  
Auth and verification-related settings include JWT keys and expiry, email provider settings (`EMAIL_PROVIDER`, `BREVO_*`), and verification code controls (`EMAIL_CODE_*`).

### 3. Database Setup

**`backend/app/db/session.py`**: async SQLAlchemy engine and session factory (`expire_on_commit=False`).  
**`backend/app/db/init_db.py`**: applies migrations with `alembic upgrade head` on startup.

### 4. Data Models

**`backend/app/models/user.py`** stores account identity and profile values:

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `email` | VARCHAR(255) | Unique login identifier |
| `username` | VARCHAR(50) | Display name |
| `password_hash` | VARCHAR(255) | Bcrypt hash |
| `programming_level` | INTEGER | 1-5, default 3 |
| `maths_level` | INTEGER | 1-5, default 3 |
| `created_at` | TIMESTAMP | Server default |

**`backend/app/models/email_verification.py`** stores verification token state for registration and password reset:

| Column | Notes |
|--------|-------|
| `email` | Lower-case email key |
| `purpose` | `register` or `reset_password` |
| `code_hash` | HMAC hash (no plain code stored) |
| `expires_at` | Hard expiry |
| `failed_attempts` | Invalid entry counter |
| `resend_available_at` | Cooldown gate |
| `consumed_at` | Single-use marker |

### 5. Schemas

**`backend/app/schemas/user.py`** includes:

- `RegisterWithCode` for registration with `verification_code`.
- `SendCodeRequest` and `PasswordResetConfirmRequest` for email-code reset.
- `ChangePassword` for signed-in reset with current password.
- `UserProfileUpdate` with `extra="forbid"` so unsupported fields (for example `email`) are rejected.

### 6. Auth Service

**`backend/app/services/auth_service.py`** provides:

- password hashing and verification (`bcrypt`),
- access and refresh token creation,
- token decoding and validation.

### 7. Email Verification and Delivery

**`backend/app/services/email_verification_service.py`**:

- generates 6-digit codes,
- stores HMAC hashes,
- applies cooldown, expiry, max-attempt, and single-use rules,
- builds transactional HTML emails with a full `<html>` document and Outlook-friendly table layout.

**`backend/app/services/email_service.py`**:

- sends via Brevo `POST /v3/smtp/email`,
- retries transient failures,
- validates that `htmlContent` includes an `<html>` tag before dispatch.

### 8. Auth Router

**`backend/app/routers/auth.py`** (prefix `/api/auth`):

| Endpoint | Method | Behaviour |
|----------|--------|-----------|
| `/api/auth/register/send-code` | POST | Send registration code; rejects already-registered email |
| `/api/auth/register` | POST | Verify code, create user, return token, set refresh cookie |
| `/api/auth/login` | POST | Validate credentials and return token |
| `/api/auth/refresh` | POST | Rotate refresh token and return new access token |
| `/api/auth/logout` | POST | Clear refresh cookie |
| `/api/auth/password-reset/send-code` | POST | Send reset code for registered email; returns `404` if email is not registered |
| `/api/auth/password-reset/confirm` | POST | Verify reset code and update password; returns `404` if email is not registered |
| `/api/auth/me` | GET | Return current user profile |
| `/api/auth/me` | PUT | Update username and skill levels |
| `/api/auth/me/password` | PUT | Signed-in password reset using current password |

### 9. FastAPI App

**`backend/app/main.py`** configures:

- application lifespan startup/shutdown,
- CORS middleware with credentials enabled,
- `/health` JSON liveness endpoint for probes and runtime checks.

### 10. Migrations

Alembic revisions create and maintain auth-related tables (`users`, `email_verification_tokens`) and are applied automatically on startup.

### 11. Local Runtime

`docker-compose.yml` runs `db` + `backend` with health checks and live-reload behaviour for local development.

---

## Frontend Work

### 12. Project Skeleton

Vite + React + TypeScript + Tailwind CSS, with API and WebSocket proxy settings in `vite.config.ts`.

### 13. API Layer

**`frontend/src/api/http.ts`**:

- adds bearer token automatically,
- sends requests with `credentials: "include"`,
- retries once after `/api/auth/refresh` on `401` for non-auth endpoints.

### 14. Auth Context

**`frontend/src/auth/AuthContext.tsx`** provides:

- `login`, `register`, `logout`,
- `sendRegisterCode`,
- `sendPasswordResetCode`, `resetPassword`,
- `changePassword` (signed-in mode),
- `updateProfile`,
- session restore on app load.

### 15. Auth Pages

- **`LoginPage.tsx`**: sign-in form and forgot-password entry.
- **`RegisterPage.tsx`**: onboarding with email code send, code entry, username, password, and skill sliders.
- **`ForgotPasswordPage.tsx`**: unauthenticated email-code reset flow with client-side email format validation before API calls.

### 16. Profile Password Pages

- **`ProfilePage.tsx`**: read-only email, editable username/levels, and one `Reset Password` entry that opens the current-password reset page.
- **`ResetPasswordByPasswordPage.tsx`**: signed-in reset by current password.
- **`ResetPasswordByEmailPage.tsx`**: signed-in reset by email code, using the current account email in read-only mode.

### 17. Routing

| Path | Component | Auth |
|------|-----------|------|
| `/login` | LoginPage | No |
| `/register` | RegisterPage | No |
| `/forgot-password` | ForgotPasswordPage | No |
| `/chat` | ChatPage | Yes |
| `/profile` | ProfilePage | Yes |
| `/profile/reset-password/password` | ResetPasswordByPasswordPage | Yes |
| `/profile/reset-password/email` | ResetPasswordByEmailPage | Yes |
| `/my-notebooks` | MyNotebooksPage | Yes |
| `/notebook/:notebookId` | NotebookWorkspacePage | Yes |
| `/learning-hub` | LearningHubPage | Yes |
| `/zones/:zoneId` | ZoneDetailPage | Yes |
| `/zone-notebook/:zoneId/:notebookId` | ZoneNotebookWorkspacePage | Yes |
| `/admin` | AdminDashboardPage | Yes |
| `/system-health` | HealthPage | Yes |
| `/` | Redirect to `/chat` | No |

---

## Verification Checklist

- [ ] Register flow requires a valid 6-digit email code.
- [ ] `/api/auth/password-reset/send-code` returns `404` and `Email is not registered.` for unknown email.
- [ ] Unknown-email forgot-password requests do not create a reset token record.
- [ ] `/api/auth/password-reset/confirm` returns `404` and `Email is not registered.` for unknown email.
- [ ] Signed-in password reset verifies current password and rejects incorrect current password.
- [ ] Profile update accepts username and level changes and rejects unsupported fields such as `email`.
- [ ] Password reset by email code remains single-use and respects expiry/attempt limits.
- [ ] Verification emails contain a full `<html>` document and render correctly in Outlook clients.
- [ ] Refresh endpoint rotates tokens and preserves authenticated browser sessions.
