# Phase 4: Robustness, Cost Control, and Testing

**Prerequisite:** Phase 3 complete (notebooks and Learning Hub working end to end).

**Visible result:** The application runs reliably with rate limiting, cost visibility for admins, an audit log for Learning Hub changes, a comprehensive test suite, and structured logging.

---

## 1. What This Phase Delivers

- Per user and global rate limiting for LLM requests.
- Concurrent WebSocket connection limits per user.
- Weekly weighted token budgets enforced per user.
- Cost estimation and usage visibility in the admin dashboard.
- An audit log tracking every Learning Hub module file change.
- A comprehensive automated test suite covering all features.
- Structured JSON logging for significant events.
- Improved error handling on both frontend and backend.

The application exposes three health-related endpoints: `GET /health` for browser-facing health diagnostics (including the current running model, with basic liveness JSON for non-HTML probes), `GET /api/health/ai` for AI provider verification, and `GET /api/health/ai/models` for model-level smoke checks plus the current running model snapshot.

---

## 2. Rate Limiting

All rate limit values are configured in `.env` and read via `config.py`.

### 2.1 Per User LLM Request Rate

Each user may send at most `RATE_LIMIT_USER_PER_MINUTE` LLM chat requests per minute (default: 5). The limiter uses an in-memory sliding window: a dictionary mapping each `user_id` to a deque of message timestamps. Expired timestamps (older than 60s) are pruned on each request.

### 2.2 Global LLM Request Rate

A global limit of `RATE_LIMIT_GLOBAL_PER_MINUTE` LLM API calls per minute applies across all users (default: 300). A single sliding window counter. If exceeded, the WebSocket returns an error instead of calling the LLM.

### 2.3 Concurrent WebSocket Connections

Each user may have at most `MAX_WS_CONNECTIONS_PER_USER` active WebSocket connections simultaneously (default: 3). An in-memory dictionary maps each `user_id` to a set of active connection IDs. Excess connections are rejected with code 4002.

### 2.4 Why In Memory

For a single process deployment, in-memory data structures are sufficient and avoid adding Redis. If the application later scales to multiple processes, replace the in-memory stores with Redis or a shared cache.

### 2.5 Implementation

**`backend/app/services/rate_limiter.py`**: sliding window rate limiter using `collections.deque`. **`backend/app/services/connection_tracker.py`**: active connection tracking per user. Both are integrated in `backend/app/routers/chat.py` at the WebSocket handler level.

---

## 3. Token Governance and Budget Control

### 3.1 Token Accounting Data Model

`chat_messages` stores per-message `input_tokens` and `output_tokens` (both nullable integers). `daily_token_usage` stores per-user daily totals (`input_tokens_used`, `output_tokens_used`) with a unique index on `(user_id, date)`. Weekly budget calculation sums the current Monday-to-Sunday rows for each user.

### 3.2 Usage API Contract

`GET /api/chat/usage` returns the current week's usage snapshot: `week_start`, `week_end`, `input_tokens_used`, `output_tokens_used`, `weighted_tokens_used`, `remaining_weighted_tokens`, `weekly_weighted_limit`, `usage_percentage`.

Weighted usage: `(input_tokens_used / 6) + output_tokens_used`. `usage_percentage` is capped at 100.

### 3.3 Per User Weekly Limit

`USER_WEEKLY_WEIGHTED_TOKEN_LIMIT` (default: 80,000). Input tokens contribute at 1/6 weight; output tokens at full weight.

### 3.4 Per Message Input Guard

Before LLM generation, enriched user text is token-counted via `count_tokens()`. Each attached image adds `IMAGE_TOKEN_ESTIMATE` tokens (default: 512). If total estimated input exceeds `LLM_MAX_USER_INPUT_TOKENS` (default: 6,000), the message is rejected.

### 3.5 Context Budget and Summarisation

`LLM_MAX_CONTEXT_TOKENS` (default: 10,000) and `CONTEXT_COMPRESSION_THRESHOLD` (default: 0.8) govern context size. The chat path uses a hidden rolling summary cache on `chat_sessions`. The cache covers older turns while recent turns remain raw. It is refreshed asynchronously after each assistant reply. If the cache is missing or stale, the context builder falls back to recent-message truncation.

### 3.6 Budget Enforcement in WebSocket Flow

For each `/ws/chat` message:

1. Parse and validate payload.
2. Resolve notebook and attachment references, validate attachment mix limits.
3. Build enriched user text and apply the per-message input guard.
4. Run `check_weekly_limit()` and reject if budget is exhausted.
5. Load the latest profile values and sync the session-scoped hidden pedagogy state with current effective levels.
6. Run fast pedagogy checks (previous Q+A text context).
7. Build prompt + context using the hidden rolling summary cache where available.
8. Run the response controller route (Single-Pass Header, Two-Step Recovery, or emergency fallback).
9. Capture precise `input_tokens` and `output_tokens` (including discarded attempts and recovery-route metadata usage).
10. Persist usage through `record_token_usage()` with an atomic upsert into `daily_token_usage`.
11. Schedule an asynchronous hidden summary-cache refresh task for the session.

### 3.6A Two-Step Recovery Route (Auto Degradation)

If metadata-header compliance degrades, the recovery route uses one metadata JSON call and one streamed tutor reply:

1. Build hidden metadata context from the current message, previous Q+A text, and student state.
2. Run `classify_two_step_recovery_meta(...)` with `PEDAGOGY_TWO_STEP_RECOVERY_JSON_PROMPT` and a compact token-trimmed payload.
3. Validate and clamp difficulties server-side, then compute `programming_hint_level` and `maths_hint_level` via the gap formula.
4. Send the `meta` WebSocket event.
5. Build the tutor reply prompt with `build_system_prompt(...)` using the computed hint levels.
6. Stream one visible tutor reply and persist metadata with the assistant message.
7. If the metadata call fails, use Emergency Full-Hint Fallback metadata and still stream a visible reply.
8. Emergency fallback turns do not contribute fallback difficulty values to the next EMA update.
9. In `auto` mode, repeated header failures degrade to the recovery route, and stable recovery turns later retry the single-pass path.

### 3.7 Profile Display Behaviour

The profile page shows a weekly budget card with the billing week range (Monday to Sunday), a progress bar with capped percentage, and a percentage used label.

### 3.8 Migration Ownership

`007_add_admin_audit_log.py` defines `chat_messages.input_tokens`, `chat_messages.output_tokens`, `daily_token_usage`, and the unique index. `008_add_chat_session_context_summary_cache.py` defines the hidden rolling summary cache fields on `chat_sessions`.

---

## 4. Cost Visibility (Admin Dashboard)

### 4.1 LLM Pricing

Model pricing constants in `backend/app/ai/pricing.py` are used for estimated runtime cost visibility. See `docs/ai-models-and-pricing.md` for the full pricing table. After each LLM response, estimated cost is calculated from input/output token counts and stored per message with the provider and model used.

### 4.2 Admin Usage Endpoints

`GET /api/admin/usage` (requires admin authentication) returns aggregated usage data across all users for today, this week, and this month. Each period includes `input_tokens`, `output_tokens`, `estimated_cost_usd`, and `estimated_cost_coverage` (the fraction of messages with stored cost metadata). This is a visibility tool, not a billing system.

`GET /api/admin/usage/by-model?provider=...&model=...` returns the same period breakdown for one selected provider/model pair, using per-message provider/model metadata in `chat_messages`.

### 4.3 Runtime Model Switching (Admin)

`GET /api/admin/llm/models` returns:
- Current active LLM provider/model (and Google transport when applicable).
- Smoke-tested available LLM switch options.
- Input and output pricing per million tokens for each available option.

In the admin dashboard, `Select LLM model` and `Selected Model Usage` default to the current running model when the page is opened.

`POST /api/admin/llm/switch` requires `provider`, `model`, and `admin_password`. The backend verifies the admin password, validates model availability, updates runtime LLM settings immediately, invalidates model-catalog cache, and records an audit entry.

---

## 5. Audit Log (Admin Dashboard)

### 5.1 Database Table

`admin_audit_log` records every modification to Learning Hub content: `id` (UUID PK), `admin_email`, `action` (create/update/delete), `resource_type` (zone/zone_notebook), `resource_id`, `resource_title`, `details` (optional), `created_at`. Indexed on `created_at DESC`.

### 5.2 What Gets Logged

Every admin endpoint that modifies Learning Hub content automatically records an audit entry: zone create/update/delete, zone notebook create/update/delete.

### 5.3 Admin Audit Log Endpoint

`GET /api/admin/audit-log?page=1&per_page=50` returns paginated entries in reverse chronological order.

### 5.4 Implementation

**Model:** `backend/app/models/audit.py`. **Service:** `backend/app/services/audit_service.py`. **Migration:** `007_add_admin_audit_log.py`.

---

## 6. Stability Fixes

- Workspace layouts use the official `react-split` package directly.
- JupyterLite build pipeline registers the bridge extension on each build.
- Single notebook isolation prevents cross-notebook state leakage.
- Recent documents and extra notebook files are cleared to avoid stale entries.
- Bridge ready/ping handshake reduces timeout races.
- Coalesced restore scheduling reduces workspace flicker.

---

## 7. Automated Test Suite

### 7.1 Test Infrastructure

`backend/tests/conftest.py` provides `MockLLMProvider` for deterministic streaming and token usage. The suite mixes `pytest` function-style tests, `pytest-asyncio` for async tests, and one `unittest.TestCase` module. `backend/pytest.ini` sets `asyncio_mode=auto`.

The default offline run executes the full backend suite. External smoke tests marked `external_ai` are skipped unless explicitly enabled.

### 7.2 Test Files

| File | Scope |
|------|-------|
| `test_admin_audit.py` | Audit log model and service |
| `test_admin_usage.py` | Admin usage and cost logic |
| `test_auth.py` | Auth helpers and token lifecycle |
| `test_auth_profile_update_levels.py` | Profile update effective-level rebasing |
| `test_chat.py` | Chat router helper logic |
| `test_chat_service_scoping.py` | Chat session scope-matching and reuse |
| `test_chat_summary_cache.py` | Hidden rolling summary cache service |
| `test_chat_usage_budget.py` | Weekly budget helper logic |
| `test_chat_ws_single_pass.py` | WebSocket single-pass and recovery-route flow |
| `test_config_admin_email.py` | Admin email parsing |
| `test_config_models.py` | Model alias normalisation |
| `test_connection_tracker.py` | Concurrent WebSocket caps |
| `test_context_builder.py` | Token-aware context assembly |
| `test_e2e_api.py` | End-to-end API flows |
| `test_health_ai.py` | Health check endpoints |
| `test_llm_anthropic.py` | Anthropic provider streaming |
| `test_llm_factory.py` | LLM factory provider selection |
| `test_llm_google_aistudio.py` | Google AI Studio streaming |
| `test_llm_google_vertex.py` | Google Vertex AI streaming |
| `test_llm_openai.py` | OpenAI provider streaming |
| `test_notebook_service.py` | Notebook naming and storage paths |
| `test_pedagogy.py` | Pedagogy engine: hint computation, EMA, metadata coercion, emergency fallback |
| `test_rate_limiter.py` | Sliding-window request limits |
| `test_stream_meta_parser.py` | Hidden metadata header parsing |
| `test_upload_service.py` | Upload classification and count limits |
| `test_verify_keys.py` | API key verification and model smoke tests |
| `test_zone_service.py` | Zone asset path utilities |

### 7.3 Running the Tests

Run from `backend/`: `PYTHONPATH=. pytest tests/ -q -s`

`external_ai` smoke tests are for optional live-provider verification and are not required for routine offline CI runs.

---

## 8. Error Handling

### 8.1 Backend

All route handlers catch exceptions and return structured error responses with `detail` and `code` fields. Standard error codes: `AUTH_INVALID`, `AUTH_FORBIDDEN`, `RATE_LIMITED`, `WEEKLY_LIMIT`, `LLM_UNAVAILABLE`, `NOT_FOUND`, `VALIDATION`. LLM failures after retry and fallback exhaustion send a WebSocket error message. Database connection failures return HTTP 503.

### 8.2 Frontend

WebSocket disconnection shows a banner with exponential backoff reconnection (1, 2, 4, 8s, up to 3 retries). LLM errors display as styled system messages in the chat. REST call failures show a brief toast notification.

---

## 9. Structured Logging

Python `logging` module with a JSON formatter, configured in `backend/app/main.py` at startup. Events logged: LLM calls (provider, model, tokens, cost, latency), metadata header parse results, summary cache refresh, WebSocket connect/disconnect, auth events, rate limit hits, and errors with tracebacks. Development uses human-readable stdout; production uses structured JSON.

---

## 10. Verification Checklist

- [ ] Sending more than 5 LLM requests in one minute returns a rate limit error.
- [ ] Opening a 4th browser tab with the chat page rejects the WebSocket connection with code 4002.
- [ ] All tests pass: `cd backend && PYTHONPATH=. pytest tests/ -q -s`.
- [ ] Pedagogy tests confirm independent programming/maths hint escalation 1, 2, 3, 4, 5 and reset on new problem.
- [ ] The browser health page at `/health` returns 200 (and non-HTML probes still receive liveness JSON).
- [ ] The AI provider verification endpoint at `/api/health/ai` returns 200.
- [ ] The model smoke-check endpoint at `/api/health/ai/models` returns 200.
- [ ] Backend logs show structured entries for LLM calls with cost estimates.
- [ ] When the LLM API key is deliberately invalidated, the user sees a clear error message.
- [ ] `GET /api/chat/usage` returns weekly usage fields and a capped `usage_percentage`.
- [ ] The profile page shows a weekly budget card with the billing week range, a progress bar, and a percentage used label.
- [ ] The admin usage endpoint returns accurate token totals and cost estimates.
- [ ] The admin audit log shows recent Learning Hub changes with admin emails and timestamps.
- [ ] Exceeding the weekly budget shows a friendly usage limit notice.
- [ ] Oversized attachment messages are rejected with a clear error.
- [ ] All rate limit and connection limit values match the `.env` configuration.
