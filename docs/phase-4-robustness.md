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

The application exposes two health-related endpoints: `GET /health` for basic liveness and `GET /api/health/ai` for AI provider verification.
This phase defines token-governance and audit schema details used by runtime monitoring and controls.

---

## 2. Rate Limiting

All rate limit values are configured in `.env` and read via `config.py`. The `.env` file is the single source of truth.

### 2.1 Per User LLM Request Rate

Each user may send at most `RATE_LIMIT_USER_PER_MINUTE` LLM chat requests per minute (default: **5**). The limiter uses an in memory sliding window: a dictionary mapping each `user_id` to a deque of message timestamps. On each request, expired timestamps (older than 60 seconds) are pruned. If the remaining count meets or exceeds the limit, the request is rejected:

```json
{"type": "error", "message": "Rate limit reached. Please wait before sending another message."}
```

### 2.2 Global LLM Request Rate

As a cost safety net, a global limit of `RATE_LIMIT_GLOBAL_PER_MINUTE` LLM API calls per minute applies across all users (default: **300**). This is a single sliding window counter. If exceeded, the WebSocket returns an error instead of calling the LLM.

### 2.3 Concurrent WebSocket Connections

Each user may have at most `MAX_WS_CONNECTIONS_PER_USER` active WebSocket connections simultaneously (default: **3**). An in memory dictionary maps each `user_id` to a set of active connection IDs. On connect, if the set size meets the limit, the new connection is rejected:

```python
await websocket.close(code=4002, reason="Too many connections")
```

On disconnect, the connection ID is removed from the set.

### 2.4 Why In Memory

For a single process deployment, in memory data structures are sufficient and avoid adding Redis as a dependency. If the application later scales to multiple backend processes, replace the in memory stores with Redis or a shared cache.

### 2.5 Implementation

**`backend/app/services/rate_limiter.py`**: sliding window rate limiter using `collections.deque`.

**`backend/app/services/connection_tracker.py`**: active connection tracking per user.

Both are integrated into `backend/app/routers/chat.py` at the WebSocket handler level.

---

## 3. Token Governance and Budget Control

### 3.1 Token Accounting Data Model

Token accounting is stored in two tables:

- `chat_messages` stores per-message usage metadata:
  - `input_tokens` (`INTEGER`, nullable)
  - `output_tokens` (`INTEGER`, nullable)
- `daily_token_usage` stores per-user daily totals:
  - `id` (`UUID`, primary key)
  - `user_id` (`UUID`, foreign key to `users.id`)
  - `date` (`DATE`)
  - `input_tokens_used` (`INTEGER`, default `0`)
  - `output_tokens_used` (`INTEGER`, default `0`)

Unique index: `ix_daily_token_usage_user_date` on `(user_id, date)`.

The weekly budget calculation reuses this table by summing the current Monday-to-Sunday rows for each user.

### 3.2 Usage API Contract

`GET /api/chat/usage` returns the current week's usage snapshot for the authenticated user.

`TokenUsageOut` fields:

- `week_start`
- `week_end`
- `input_tokens_used`
- `output_tokens_used`
- `weighted_tokens_used`
- `remaining_weighted_tokens`
- `weekly_weighted_limit`
- `usage_percentage`

Weighted usage is calculated as:

```text
weighted_tokens_used = (input_tokens_used / 6) + output_tokens_used
```

`usage_percentage` is calculated from `weighted_tokens_used / weekly_weighted_limit` and capped at `100`.

### 3.3 Per User Weekly Limit

Each user has one weekly weighted budget (Monday to Sunday):

- `USER_WEEKLY_WEIGHTED_TOKEN_LIMIT` (default: 80,000)

The weighting rule treats input tokens as cheaper for budget control:
- input contribution = `input_tokens / 6`
- output contribution = `output_tokens`

### 3.4 Per Message Input Guard

Before LLM generation, the backend builds an enriched user message (typed text plus extracted document text). It estimates input tokens using `count_tokens()`. Each attached image adds `IMAGE_TOKEN_ESTIMATE` tokens (default: 512). If total estimated input exceeds `LLM_MAX_USER_INPUT_TOKENS` (default: 6,000), the message is rejected:

```
"Files are too large for one message. Please split them and try again."
```

### 3.5 Context Budget and Summarisation

Context compression is controlled by:

- `LLM_MAX_CONTEXT_TOKENS` (default: `10000`)
- `CONTEXT_COMPRESSION_THRESHOLD` (default: `0.8`)

When conversation history exceeds the threshold, older turns are summarised and recent turns are kept intact. If summarisation fails, the system falls back to recent-message truncation.

### 3.6 Budget Enforcement in WebSocket Flow

For each `/ws/chat` message:

1. Parse and validate payload.
2. Resolve notebook and attachment references, then validate attachment mix limits.
3. Build enriched user text and apply the per-message input guard.
4. Run `check_weekly_limit()` and reject if the weekly weighted budget is exhausted.
5. Run pedagogy checks and stream the LLM response.
6. Capture precise `input_tokens` and `output_tokens` from `llm.last_usage`.
7. Persist usage through `record_token_usage()` with an atomic upsert into `daily_token_usage`.

### 3.7 Profile Display Behaviour

The profile page shows a weekly budget card with:
- billing week range (Monday to Sunday),
- a progress bar with a capped percentage, and
- a formal percentage label (`xx.x% used`).

This keeps the display formal and clear. The backend still uses the weighted budgeting rule (`input / 6 + output`) for enforcement and usage calculations.

### 3.8 Migration Ownership

`backend/alembic/versions/007_add_admin_audit_log.py` defines:

- `chat_messages.input_tokens`
- `chat_messages.output_tokens`
- `daily_token_usage`
- unique index `ix_daily_token_usage_user_date`

---

## 4. Cost Visibility (Admin Dashboard)

### 4.1 LLM Pricing

Model pricing constants are defined in `backend/app/ai/pricing.py` and used for **estimated** runtime cost visibility:

| Provider | Model | Input (per MTok) | Output (per MTok) |
|----------|-------|------------------:|-------------------:|
| Google (Vertex AI) | Gemini 3 Flash Preview (`gemini-3-flash-preview`) | \$0.50 | \$3.00 |
| Google (Vertex AI) | Gemini 3.1 Pro Preview (`gemini-3.1-pro-preview`) | \$2.00 | \$12.00 |
| Anthropic | Claude Sonnet 4.6 (`claude-sonnet-4-6`) | \$3.00 | \$15.00 |
| Anthropic | Claude Haiku 4.5 (`claude-haiku-4-5`) | \$1.00 | \$5.00 |
| OpenAI | GPT-5.2 (`gpt-5.2`) | \$1.25 | \$10.00 |
| OpenAI | GPT-5 mini (`gpt-5-mini`) | \$0.25 | \$2.00 |

After each LLM response, the estimated cost is calculated:

```
cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
```

The application stores the actual `provider` and `model` used for each assistant message, together with an `estimated_cost_usd` value. Admin totals are then aggregated from stored per-message cost values.

### 4.2 Admin Usage Endpoint

`GET /api/admin/usage` (requires admin authentication).

Returns aggregated usage data across all users:

```json
{
  "today": {
    "input_tokens": 285000,
    "output_tokens": 310000,
    "estimated_cost_usd": 0.52,
    "estimated_cost_coverage": 1.0
  },
  "this_week": {
    "input_tokens": 1780000,
    "output_tokens": 1950000,
    "estimated_cost_usd": 3.28,
    "estimated_cost_coverage": 0.94
  },
  "this_month": {
    "input_tokens": 6400000,
    "output_tokens": 7000000,
    "estimated_cost_usd": 11.80,
    "estimated_cost_coverage": 0.89
  }
}
```

This is a visibility tool, not a billing system. The `estimated_cost_coverage` field shows the fraction of assistant messages in the time window that include stored model-level cost metadata (older messages may predate this tracking).

---

## 5. Audit Log (Admin Dashboard)

### 5.1 Database Table

A new `admin_audit_log` table records every modification to Learning Hub content:

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `admin_email` | VARCHAR(255) | Email of the admin who performed the action |
| `action` | VARCHAR(50) | `create`, `update`, or `delete` |
| `resource_type` | VARCHAR(50) | `zone` or `zone_notebook` |
| `resource_id` | UUID | ID of the affected resource |
| `resource_title` | VARCHAR(255) | Title of the affected resource at the time of action |
| `details` | TEXT | Optional additional context |
| `created_at` | TIMESTAMP | Server default |

Index on `created_at DESC` for efficient reverse chronological listing.

### 5.2 What Gets Logged

Every admin endpoint that modifies Learning Hub content automatically records an audit entry:

| Endpoint | Action Logged |
|----------|--------------|
| `POST /api/admin/zones` | `create` zone |
| `PUT /api/admin/zones/{id}` | `update` zone |
| `DELETE /api/admin/zones/{id}` | `delete` zone |
| `POST /api/admin/zones/{id}/notebooks` | `create` zone_notebook |
| `PUT /api/admin/notebooks/{id}` | `update` zone_notebook |
| `DELETE /api/admin/notebooks/{id}` | `delete` zone_notebook |

### 5.3 Admin Audit Log Endpoint

`GET /api/admin/audit-log?page=1&per_page=50` (requires admin authentication).

Returns a paginated list of audit entries in reverse chronological order, each containing the admin email, action, resource type, resource title, and timestamp.

### 5.4 Implementation

**Model:** `backend/app/models/audit.py`

**Service:** `backend/app/services/audit_service.py`

**Migration:** `backend/alembic/versions/007_add_admin_audit_log.py`
This migration defines `admin_audit_log` and the token-usage schema used by Phase 4 controls.

---

## 6. Stability Fixes

The following stability measures are in place:

- Workspace layouts use the official `react-split` package directly.
- The JupyterLite build pipeline registers the bridge extension on each build.
- Single notebook isolation in JupyterLite prevents cross notebook state leakage.
- Recent documents and extra notebook files are cleared to avoid stale entries.
- The bridge ready/ping handshake reduces timeout races.
- Coalesced restore scheduling reduces workspace flicker.

---

## 7. Automated Test Suite

### 7.1 Test Infrastructure

`backend/tests/conftest.py` provides `MockLLMProvider`, a lightweight provider used by async tests that need deterministic streaming and deterministic token usage reporting.

The suite mixes:

- `pytest` function-style tests;
- `pytest-asyncio` for async test functions; and
- one `unittest.TestCase` module, still executed by `pytest`.

`backend/pytest.ini` sets `asyncio_mode=auto` so async tests run consistently without command-line flags.

Current automated total (default offline run, excluding `external_ai` smoke tests): **88 tests**.

### 7.2 Test Files

| File | Tests | Scope | Key checks |
|------|------:|-------|------------|
| `test_auth.py` | 5 | Auth helpers and token lifecycle | Password hashing/verification, access/refresh token claims, invalid token rejection, refresh cookie flags. |
| `test_chat.py` | 11 | Chat router helper logic | WebSocket token resolution, upload split and limit validation, enriched message generation, multimodal part generation, context truncation helpers. |
| `test_chat_usage_budget.py` | 2 | Weekly budget helper logic | Monday-Sunday week bounds and weighted usage formula (`input / 6 + output`). |
| `test_pedagogy.py` | 8 | Pedagogy engine behaviour | Greeting/off-topic filtering, default filter disablement, LLM same-problem handling, hint escalation, new-problem reset, hint cap, effective-level EMA update. |
| `test_same_problem_classifier.py` | 5 | LLM same-problem classifier parsing | Strict JSON parse, regex fallback, elaboration normalisation, fallback behaviour on invalid payload, missing-context fallback. |
| `test_context_builder.py` | 3 | Token-aware context assembly | Empty history handling, truncation under small budgets, full-history inclusion when budget allows. |
| `test_rate_limiter.py` | 4 | Sliding-window request limits | Per-user allowance, per-user rejection, global cap enforcement, 60-second expiry pruning. |
| `test_connection_tracker.py` | 3 | Concurrent WebSocket caps | Add/remove accounting, max-connection rejection, per-user isolation. |
| `test_admin_usage.py` | 3 | Admin usage and cost logic | Provider pricing calculation, zero-token behaviour, aggregate usage payload shape. |
| `test_admin_audit.py` | 5 | Audit log model and service | Field mapping, optional values, action set, entry creation/flush, paginated response shape. |
| `test_e2e_api.py` | 5 | End-to-end API flows | Register/profile/refresh/logout chain, new-user usage/sessions baseline, admin access control, admin usage/audit retrieval, owner-scoped upload access. |
| `test_config_admin_email.py` | 2 | Admin email parsing | Comma/space parsing and JSON list parsing with lower-case normalisation. |
| `test_notebook_service.py` | 8 | Notebook naming and storage paths | Title normalisation, filename derivation, safe storage segment mapping, user/zone directory creation. |
| `test_upload_service.py` | 4 | Upload classification and count limits | MIME fallback classification, in-limit acceptance, over-limit rejection, unsupported type rejection. |
| `test_zone_service.py` | 5 | Zone asset path utilities | Relative path normalisation, parent-segment rejection, title derivation, shared-root detection, root stripping. |

### 7.3 Running the Tests

```bash
cd backend
PYTHONPATH=. pytest tests/ -q -s
```

`test_semantic_thresholds.py` is a manual calibration script, not an automated `pytest` test. It runs against Vertex AI `multimodalembedding@001`:

```bash
python -m tests.test_semantic_thresholds
```

---

## 8. Error Handling

### 8.1 Backend

All route handlers catch exceptions and return structured error responses:

```json
{"detail": "Human readable error message", "code": "ERROR_CODE"}
```

Standard error codes:

| Code | Meaning |
|------|---------|
| `AUTH_INVALID` | Token is missing, expired, or malformed |
| `AUTH_FORBIDDEN` | User does not own the requested resource |
| `RATE_LIMITED` | Message rate limit exceeded |
| `WEEKLY_LIMIT` | Weekly weighted token budget exhausted |
| `LLM_UNAVAILABLE` | All LLM providers failed after retry |
| `NOT_FOUND` | Resource does not exist |
| `VALIDATION` | Request body failed Pydantic validation |

LLM failures (after retry and fallback exhaustion) send a WebSocket message:

```json
{"type": "error", "message": "The AI service is temporarily unavailable. Please try again in a moment."}
```

Database connection failures return HTTP 503.

### 8.2 Frontend

- **WebSocket disconnection:** a banner appears: "Connection lost. Reconnecting..." The frontend attempts to reconnect with exponential backoff (1, 2, 4, 8 seconds, up to 3 retries).
- **LLM errors:** displayed as a system message in the chat, styled differently from user and assistant messages.
- **REST call failures:** a toast notification appears briefly with the error message.

---

## 9. Structured Logging

Use Python's built in `logging` module with a JSON formatter. Configure in `backend/app/main.py` at startup.

```python
import logging
logger = logging.getLogger("ai_tutor")
```

Events logged:

| Event | Fields |
|-------|--------|
| LLM call | provider, model, input_tokens, output_tokens, estimated_cost, latency_ms, success |
| WebSocket connect | user_id, session_id, timestamp |
| WebSocket disconnect | user_id, session_id, duration_seconds |
| Auth event | event_type (login, register, refresh, logout), user_id, success |
| Rate limit hit | user_id, limit_type (user or global) |
| Error | logger name, level, message, traceback |

In development, log to stdout in human readable format. In production (detected via environment variable), log as structured JSON.

---

## 10. Verification Checklist

- [ ] Sending more than 5 LLM requests in one minute returns a rate limit error.
- [ ] Opening a 4th browser tab with the chat page rejects the WebSocket connection with code 4002.
- [ ] All tests pass: `cd backend && PYTHONPATH=. pytest tests/ -q -s`.
- [ ] Pedagogy tests confirm hint escalation 1, 2, 3, 4, 5 and reset on new problem.
- [ ] The basic health endpoint at `/health` returns 200.
- [ ] The AI provider verification endpoint at `/api/health/ai` returns 200.
- [ ] Backend logs show structured entries for LLM calls with cost estimates.
- [ ] When the LLM API key is deliberately invalidated, the user sees a clear error message.
- [ ] `GET /api/chat/usage` returns weekly usage fields and a capped `usage_percentage`.
- [ ] The profile page shows a weekly budget card with the billing week range, a progress bar, and a percentage used label.
- [ ] The admin usage endpoint returns accurate token totals and cost estimates.
- [ ] The admin audit log shows recent Learning Hub changes with admin emails and timestamps.
- [ ] Exceeding the weekly budget shows a friendly usage limit notice.
- [ ] Oversized attachment messages are rejected with "Files are too large for one message. Please split them and try again."
- [ ] All rate limit and connection limit values match the `.env` configuration.
