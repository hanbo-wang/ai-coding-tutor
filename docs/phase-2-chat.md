# Phase 2: AI Chat with Pedagogy Engine

**Prerequisite:** Phase 1 complete (authentication system working).

**Visible result:** A chat interface where students interact with an AI tutor. Responses stream token by token with LaTeX formula rendering and syntax-highlighted code blocks. The AI uses a graduated hint system, adapting both the amount of information revealed and the communication style to each student's ability.

---

## 1. Pedagogical Engine: Core Principles

The pedagogy engine uses a guided discovery approach with independent hint levels for programming and mathematics, deterministic gap-based hint computation, and EMA-based dynamic student levelling.

For the full algorithm reference (teaching philosophy, self-assessment levels, EMA formulae, gap formulae, hint escalation, all prompt text, and the three-route implementation), see [`docs/pedagogy-algorithm.md`](pedagogy-algorithm.md).

**Key points:**

- Students self-assess programming and maths ability (1-5). Hidden effective levels track true ability via EMA.
- Programming and maths hint levels are computed independently using gap formulae: `max(1, min(4, 1 + (difficulty - round(effective_level))))`.
- New problems are capped at hint level 4. Same-problem follow-ups increment by 1, capped at 5.
- Five hint levels per dimension: Socratic, Conceptual, Structural, Concrete, Full Solution.
- Communication style adapts to the student's effective level independently of hint level.

---

## 2. Fast Signals and Metadata Pipeline

User messages are processed through a lightweight local signal step before the main tutoring response is generated.

### 2.1 Same-Problem, Elaboration, Difficulty, and Hint Metadata

The chat path uses a hidden metadata schema with four LLM-classified fields: `same_problem`, `is_elaboration`, `programming_difficulty`, `maths_difficulty`. The backend computes `programming_hint_level` and `maths_hint_level` deterministically using the gap formula (see [`docs/pedagogy-algorithm.md`](pedagogy-algorithm.md) Section 4).

The response controller supports three modes for `/ws/chat`:
- `auto` (default): prefer the `Single-Pass Header Route`, degrade to the `Two-Step Recovery Route` after repeated header parse failures, and retry the faster route after stable recovery turns.
- `single_pass_header_route`: always use the single-pass route.
- `two_step_recovery_route`: always use the two-step route.

The student state caches the previous Q+A text per chat session for metadata context. The `auto` degradation counters follow the same session boundary.

**Implementation:** `backend/app/ai/pedagogy_engine.py`, `backend/app/ai/prompts.py`, `backend/app/services/stream_meta_parser.py`

### 2.2 Single-Pass Header Route (Default Path)

One streamed LLM call emits a hidden metadata header (`<<GC_META_V1>>...<<END_GC_META>>`) before the visible tutor answer. The backend provides hidden pedagogy context (previous Q+A text, effective levels, current hint/difficulty state). The LLM classifies `same_problem`, `is_elaboration`, `programming_difficulty`, and `maths_difficulty`. The backend validates difficulty fields and computes hint levels via the gap formula.

### 2.3 Two-Step Recovery Route (Metadata + Reply)

Two LLM calls: one compact metadata-only JSON call (token-trimmed payload), then one streamed tutor reply. Used when the controller mode is `two_step_recovery_route`, or `auto` mode degrades after repeated header parse failures.

### 2.4 Emergency Full-Hint Fallback (Local Last Resort)

If both routes fail, the backend builds local emergency metadata: `programming_hint_level = 5`, `maths_hint_level = 5`, difficulty set to rounded effective levels, and `skip_next_ema_update_once = true` to prevent distorting the effective level. A visible tutor reply is still generated.

### 2.5 Problem Difficulty and Hint Selection

The LLM classifies difficulty; the backend computes hint levels deterministically. Elaboration requests increment each hint level by 1. New problems trigger an EMA update from the previous interaction before computing new hint levels. Emergency fallback turns do not contribute to the next EMA update.

Each dimension is updated independently: programming EMA uses `programming_difficulty` and `programming_hint_level`; maths EMA uses `maths_difficulty` and `maths_hint_level`. See [`docs/pedagogy-algorithm.md`](pedagogy-algorithm.md) Section 3.

### 2.6 Pipeline Summary

1. Build fast pedagogy signals from previous Q+A text.
2. Build prompt + context using full history or the hidden rolling summary cache plus recent raw turns.
3. Single-Pass Header Route: one streamed LLM call with hidden metadata header.
4. On header failure: discard and run the Two-Step Recovery Route.
5. On recovery failure: use Emergency Full-Hint Fallback.
6. Send `meta` event, stream visible tokens, apply pedagogy metadata, persist the assistant turn.
7. Refresh the hidden rolling summary cache asynchronously.

---

## 3. What This Phase Delivers

**Part A (Text-Based Chat):**

- `chat_sessions` and `chat_messages` database tables.
- Updated `users` table with hidden effective level fields.
- An LLM abstraction layer supporting three providers with automatic failover.
- A pedagogy engine that manages hint levels, student adaptation, and dynamic levelling.
- A WebSocket endpoint (`/ws/chat`) that streams AI responses.
- A frontend chat page with message history, streaming display, GFM markdown rendering (including tables), syntax-highlighted and copyable block code with in-panel text markers and text copy controls, structured teaching panels for space-sensitive diagrams, and KaTeX formula rendering with copy-tex enabled so formula selections copy as LaTeX, plus defensive sanitisation for malformed OCR/AI math delimiters.

**Part B (File and Image Uploads):**

- File upload endpoint supporting images and documents.
- Vision-capable LLM processing for screenshots and images.
- Updated chat interface with upload controls, drag-and-drop, and clipboard paste.
- Per-message attachment limits: up to 3 photos and 2 files.
- Support for `.ipynb` documents, with text extraction from notebook cells.

---

## 4. Development Part A: Text-Based Chat

### 4.1 Database Changes

**Users table** gains `effective_programming_level` (FLOAT, nullable) and `effective_maths_level` (FLOAT, nullable), initialised from self-assessment on first chat interaction.

**`chat_sessions` table:** `id` (UUID PK), `user_id` (FK), `session_type` (VARCHAR, default `"general"`), `module_id` (UUID, nullable), `created_at`. Indexed on `(user_id, session_type)`.

**`chat_messages` table:** `id` (UUID PK), `session_id` (FK), `role`, `content`, `programming_difficulty` (nullable INT 1-5), `maths_difficulty` (nullable INT 1-5), `programming_hint_level_used` (nullable INT 1-5), `maths_hint_level_used` (nullable INT 1-5), `attachments_json`, `created_at`. Indexed on `(session_id, created_at)`.

### 4.2 Chat Schemas

**`backend/app/schemas/chat.py`:** `ChatMessageIn` (content, session_id, upload_ids), `ChatMessageOut` (id, role, content, programming_difficulty, maths_difficulty, programming_hint_level_used, maths_hint_level_used, attachments, created_at), `ChatSessionOut`, `ChatSessionListItem`.

### 4.3 Chat Service

**`backend/app/services/chat_service.py`:** `get_or_create_session` (scope-aware reuse), `save_message` (stores hint/difficulty metadata and attachment IDs), `get_chat_history`, `get_session_messages` (ownership-checked), `get_user_sessions` (newest-first with preview), `delete_session`.

### 4.4 LLM Abstraction Layer

**`backend/app/ai/llm_base.py`:** Abstract `LLMProvider` with `generate_stream` (async token iterator) and `count_tokens`.

Three provider implementations (`llm_google.py`, `llm_anthropic.py`, `llm_openai.py`), each with streaming, retry on 429/5xx (3 attempts, exponential backoff), and `LLMError` on failure. Google supports AI Studio and Vertex AI transports, selected via `GOOGLE_GEMINI_TRANSPORT`.

**`backend/app/ai/llm_factory.py`:** Returns the configured provider (`LLM_PROVIDER`, default `anthropic` in the recommended `.env`), with session-level failover. The factory tries alternate models within the same provider first, then crosses to other providers in a ring (anthropic → openai → google).

| Provider | Models | Implementation |
| -------- | ------ | -------------- |
| Anthropic (default) | Claude Sonnet 4.6 / Claude Haiku 4.5 | `llm_anthropic.py` |
| Google (AI Studio / Vertex AI) | Gemini 3 Flash Preview / Gemini 3.1 Pro Preview | `llm_google.py` |
| OpenAI | GPT-5.2 / GPT-5 mini | `llm_openai.py` |

### 4.5 Pedagogy Engine

**`backend/app/ai/pedagogy_engine.py`:**

`StudentState` tracks: `effective_programming_level`, `effective_maths_level` (floats, 1.0 to 5.0), `current_programming_hint_level`, `current_maths_hint_level` (ints), `starting_programming_hint_level`, `starting_maths_hint_level` (ints, 1 to 4), `current_programming_difficulty`, `current_maths_difficulty`, `last_question_text`, `last_answer_text`, and `skip_next_ema_update_once`.

Key methods: `prepare_fast_signals` (local previous Q+A context), `compute_hint_levels` (deterministic gap formula), `coerce_stream_meta` (validate LLM metadata + compute hints), `apply_stream_meta` (update state and effective levels), `build_emergency_full_hint_fallback_meta` (local fallback with hints = 5).

### 4.6 Prompts

**`backend/app/ai/prompts.py`:** `BASE_SYSTEM_PROMPT` (tutor persona, LaTeX/code formatting rules), `PROGRAMMING_HINT_INSTRUCTIONS[1..5]`, `MATHS_HINT_INSTRUCTIONS[1..5]`, `PROGRAMMING_LEVEL_INSTRUCTIONS[1..5]`, `MATHS_LEVEL_INSTRUCTIONS[1..5]`, `PEDAGOGY_TWO_STEP_RECOVERY_JSON_PROMPT` (metadata-only, no hint level), `SINGLE_PASS_PEDAGOGY_PROTOCOL_PROMPT` (hidden header protocol with explicit gap formula).

Hint levels are always computed by the backend via `compute_hint_levels()`. See [`docs/pedagogy-algorithm.md`](pedagogy-algorithm.md) for full prompt text.

### 4.7 Context Builder

**`backend/app/ai/context_builder.py`:** `build_system_prompt(programming_hint_level, maths_hint_level, programming_level, maths_level)` assembles the system prompt for the Two-Step Recovery Route. `build_single_pass_system_prompt(programming_level, maths_level, pedagogy_context)` assembles the Single-Pass route prompt. `build_context_messages` handles token-aware context assembly using the hidden rolling summary cache (stored on `chat_sessions`, refreshed asynchronously after each turn).

### 4.8 Chat Endpoints

**`backend/app/routers/chat.py`:**

REST: `GET /api/chat/sessions` (list, newest first), `DELETE /api/chat/sessions/{id}`, `GET /api/chat/sessions/{id}/messages`.

WebSocket `/ws/chat`: authenticates via JWT query parameter, initialises pedagogy services, and processes each message through the pipeline (parse, validate uploads, build enriched text, persist user turn, run pedagogy checks, build context, run LLM via route controller, send `meta`/`token`/`done` events, persist assistant turn, refresh summary cache). Non-retryable stage failures send an `error` event and then close the socket with code `1011`.

### 4.9 Frontend: Chat Components

- **`ws.ts`**: WebSocket helper forwarding `session`, `meta`, `token`, `done`, `error` events, with explicit close metadata.
- **`useChatSocket.ts`**: Shared hook managing socket lifecycle, message list, streaming content, and `StreamingMeta` (separate `programmingHintLevel` and `mathsHintLevel`). It reconnects with exponential backoff (300 ms base, 3 s cap), retries one in-flight message only when no terminal event has been received yet, and asks for manual resend when a disconnect happens after session acknowledgement.
- **`ChatPage.tsx`**: Full-page layout with collapsible sidebar, welcome greeting, streaming display, and disclaimer.
- **`ChatSidebar.tsx`**: Session list (newest first), new chat button, delete with confirmation.
- **`ChatMessageList.tsx`**: Auto-scrolling container rendering both persisted and streaming messages.
- **`ChatInput.tsx`**: Text input, Shift+Enter for newlines, disabled during streaming.
- **`ChatBubble.tsx`**: User messages as brand-coloured bubbles with image/file attachments. Assistant messages with four metadata badges (Prog Hint, Maths Hint, Prog Diff, Maths Diff), full-width bubble layout for stable markdown panel centring, and markdown/LaTeX rendering.

### 4.10 Markdown, Code, and LaTeX Rendering

**`frontend/src/components/MarkdownRenderer.tsx`:** GFM tables via `remark-gfm` (pipe escaping in math spans), syntax-highlighted block code via `react-syntax-highlighter` (Prism `one-light` theme), copy button support for block code (language and plain text blocks) with in-panel text markers and text-based `Copy`/`Copied` controls, structured parsing for common teaching layouts (layer pipelines, neuron-rule cards, vector comparisons, confidence pointers), inline code with subtle borders, and KaTeX rendering with the official `copy-tex` integration so mixed text selections keep formulae in LaTeX form (without formula copy buttons). A defensive delimiter sanitiser runs before markdown math parsing to prevent malformed `$`/`$$` fragments from swallowing long prose blocks.

**`frontend/src/index.css`:** Unified markdown panel sizing (`860px` max width on desktop) with centred block panels, larger but low-contrast in-panel text markers, responsive structured-panel layouts, natural KaTeX flow without formula boxes, neutral KaTeX error styling, and overflow-safe behaviour on narrow screens.

Dependencies: `react-markdown`, `remark-gfm`, `remark-math`, `react-syntax-highlighter`, `katex`, `rehype-katex`.

### 4.11 Alembic Migration

Migration `002` adds `effective_programming_level` and `effective_maths_level` to `users`, and creates `chat_sessions` and `chat_messages` tables.

---

## 5. Development Part B: File and Image Uploads

### 5.1 Upload Endpoint

**`backend/app/routers/upload.py`:** `POST /api/upload` accepts images (PNG, JPG, JPEG, GIF, WebP, max 5 MB) and documents (PDF, TXT, PY, JS, TS, CSV, IPYNB, max 2 MB). Per-message limits: up to 3 photos and 2 documents. `GET /api/upload/{id}/content` serves content for the owning user. Uploads expire after 24 hours.

### 5.2 Multimodal Processing

Images are sent as base64 parts to the LLM. Documents have text extracted (PDF via `pypdf`, code files via text decoding, `.ipynb` by concatenating cell sources).

### 5.3 Updated Chat Interface

**`ChatInput.tsx`**: file upload button, drag-and-drop, clipboard paste, attachment limit enforcement, file previews. **`ChatBubble.tsx`**: inline image rendering and document download buttons via authenticated blob fetches.

---

## 6. Verification Checklist

### Part A: Text-Based Chat

- [ ] Welcome greeting with username on first load.
- [ ] Disclaimer visible below input area.
- [ ] WebSocket connection established on page load.
- [ ] Streamed AI response (tokens appear incrementally).
- [ ] First response to a new topic is never a complete answer.
- [ ] Matched-level problems start at Socratic (hint 1); hard problems start at hint 3 or 4.
- [ ] Follow-ups escalate hint by 1; new topics reset and recalculate.
- [ ] Effective level updates in DB after topic change.
- [ ] Block code shows syntax highlighting where relevant and supports one-click copy with keyboard-accessible controls.
- [ ] Structured teaching layouts render as stable panels (layer flows, neuron rules, vector comparisons, confidence pointers) without space-based drift.
- [ ] Markdown block panels are centred and size-consistent (`860px` desktop max width, responsive on mobile).
- [ ] LaTeX rendering works for both inline and display formulae, and normal text selections copy formula content as LaTeX (including mixed prose + maths selections).
- [ ] Chat history persists across page refreshes.
- [ ] LLM provider failover works; clear error when all fail.

### Part B: File and Image Uploads

- [ ] Upload button, drag-and-drop, and Ctrl+V paste work.
- [ ] Attachment limits enforced (3 photos, 2 files).
- [ ] Code and notebook files included in AI context.
- [ ] Same-problem detection works across text and image inputs.
- [ ] Size limit, expiry, and unsupported type rejections work.
