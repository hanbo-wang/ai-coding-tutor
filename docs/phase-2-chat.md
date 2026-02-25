# Phase 2: AI Chat with Pedagogy Engine

**Prerequisite:** Phase 1 complete (authentication system working).

**Visible result:** A chat interface where students interact with an AI tutor. Responses stream token by token with LaTeX formula rendering and syntax-highlighted code blocks. The AI uses a graduated hint system, adapting both the amount of information revealed and the communication style to each student's ability.

---

## 1. Pedagogical Engine: Core Principles

### 1.1 Teaching Philosophy

The AI tutor follows a "guided discovery" approach. Rather than providing answers immediately, it offers graduated hints that lead students to work through problems themselves. This encourages genuine understanding and builds problem-solving confidence.

The core rules are:

1. The AI never gives a complete answer on the first response, regardless of the student's level or the problem's difficulty.
2. Hints escalate gradually from guiding questions to conceptual explanations to concrete examples.
3. A complete solution is only provided after multiple interactions on the same problem.
4. The AI adapts its language and depth to the student's assessed ability.
5. The student's true internal ability level is tracked silently and never displayed to them, avoiding unnecessary psychological pressure.

### 1.2 Student Self-Assessment

During registration (Phase 1), students choose a username and rate their own programming and mathematics ability on a scale of 1 to 5 via simple sliders labelled "Beginner" to "Expert". These ratings are stored in the `users` table and serve as the initial baseline for the pedagogy engine.

The table below defines what each level means internally. These descriptions are not shown to the student; the sliders use only "Beginner" and "Expert" as labels to keep the onboarding simple.

| Level | Programming Description                                       | Mathematics Description                             |
| :---: | ------------------------------------------------------------- | --------------------------------------------------- |
|   1   | No experience. New to coding.                                 | Basic arithmetic only.                              |
|   2   | Understands variables, loops, and functions.                  | Comfortable with algebra and basic geometry.        |
|   3   | Can write multi-file programmes. Understands data structures. | Comfortable with calculus and linear algebra.       |
|   4   | Experienced with algorithms and design patterns.              | Comfortable with differential equations and proofs. |
|   5   | Professional level. System design and optimisation.           | Research-level mathematics.                         |

### 1.3 Hidden Effective Levels and Dynamic Adjustment

The system maintains two hidden floating-point values per student: `effective_programming_level` and `effective_maths_level` (range 1.0 to 5.0). These are initialised from the self-assessment integers on the student's first chat interaction. When the student updates a self-assessed skill level in Profile, the corresponding hidden effective level is rebased to that new value.

After each completed problem (detected when the student moves on to a new topic, see Section 2.4), the effective levels are updated using an Exponential Moving Average (EMA). Each dimension is updated independently using its own difficulty rating (see Section 2.5).

**Step 1: Calculate the demonstrated level.**

The number of hints the student needed reveals how well they understood the problem. The formula is applied separately for programming and maths, each using the corresponding difficulty:

```
demonstrated_level = difficulty * (6 - final_hint_level) / 5
```

This gives:

|      Final Hint Level      | Demonstrated Level (as fraction of difficulty) |
| :------------------------: | :--------------------------------------------: |
| 1 (Socratic, minimal help) |               100% of difficulty               |
|       2 (Conceptual)       |                      80%                      |
|       3 (Structural)       |                      60%                      |
|        4 (Concrete)        |                      40%                      |
|     5 (Full solution)     |                      20%                      |

**Step 2: Update the effective level.**

```
learning_rate = 0.2 * min(1.0, difficulty / effective_level)
new_effective_level = effective_level * (1 - learning_rate) + demonstrated_level * learning_rate
```

The `learning_rate` is weighted by `difficulty / effective_level` so that:

- Problems at or above the student's level carry full weight (these are informative).
- Easy problems below the student's level carry reduced weight (solving easy problems should not significantly drag the level down).

The result is clamped to the range [1.0, 5.0].

**Example A (good performance on hard programming problem):**
Student effective programming level = 3.0, programming difficulty = 4, solved at hint level 2.
`demonstrated = 4 * (6-2)/5 = 3.2`, `rate = 0.2 * min(1, 4/3) = 0.2`.
`new = 3.0 * 0.8 + 3.2 * 0.2 = 3.04`. Level increases slightly.

**Example B (struggled on matched problem):**
Student effective programming level = 3.0, programming difficulty = 3, needed hint level 5.
`demonstrated = 3 * (6-5)/5 = 0.6`, `rate = 0.2 * min(1, 3/3) = 0.2`.
`new = 3.0 * 0.8 + 0.6 * 0.2 = 2.52`. Level decreases noticeably.

**Example C (easy problem, solved easily):**
Student effective programming level = 4.0, programming difficulty = 1, solved at hint level 1.
`demonstrated = 1 * (6-1)/5 = 1.0`, `rate = 0.2 * min(1, 1/4) = 0.05`.
`new = 4.0 * 0.95 + 1.0 * 0.05 = 3.85`. Minimal change because easy problems carry low weight.

### 1.4 Five-Level Graduated Hint System

Each hint level controls how much of the answer is revealed. The student's effective level separately controls the communication style (see Section 1.6). These two dimensions are independent.

| Hint Level | Name          | What the AI Does                                                                                                                                        |
| :--------: | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
|     1     | Socratic      | Ask guiding questions only. "What do you think happens when...?" or "Have you considered...?" Never reveal the approach or solution.                    |
|     2     | Conceptual    | Explain the underlying concept or principle relevant to the problem. Identify the area of knowledge needed. Do not show code or specific steps.         |
|     3     | Structural    | Name the specific functions, methods, or algorithmic steps needed. Provide a high-level outline of the solution. Do not write actual code.              |
|     4     | Concrete      | Provide partial code, pseudocode, or a worked example of a similar problem. Show specific syntax or API usage. Leave the final assembly to the student. |
|     5     | Full Solution | Provide the complete working solution with detailed explanation. Explain why each step is necessary. Include common pitfalls and variations.            |

Each follow-up on the same problem increments the hint level by 1, up to a maximum of 5.

### 1.5 Starting Hint Level Determination

The starting hint level for each new problem depends on the gap between the problem's estimated difficulty and the student's effective level. Since difficulty is assessed separately for programming and mathematics, the starting hint is based on whichever dimension has the larger gap.

```
prog_gap = programming_difficulty - round(effective_programming_level)
maths_gap = maths_difficulty - round(effective_maths_level)
gap = max(prog_gap, maths_gap)
starting_hint_level = max(1, min(4, 1 + gap))
```

| Gap (Difficulty minus Student Level) | Starting Hint Level | Rationale                                                                                    |
| :----------------------------------: | :-----------------: | -------------------------------------------------------------------------------------------- |
|              0 or below              |    1 (Socratic)    | The problem is at or below the student's level. They should handle it with minimal guidance. |
|                  1                  |   2 (Conceptual)   | Slightly above their level. A concept explanation should be enough.                          |
|                  2                  |   3 (Structural)   | Notably above their level. They need an outline of the approach.                             |
|              3 or above              |    4 (Concrete)    | Well above their level. They need substantial help with partial code or examples.            |

**Key rule:** The starting hint level is capped at 4. No student ever receives a full solution (level 5) as a first response, regardless of the difficulty gap.

### 1.6 Student Level Adaptation (Communication Style)

The student's effective level determines the language, terminology, and depth of explanations at every hint level. This is orthogonal to the hint level itself.

**Programming level adaptation:**

| Level | Communication Style                                                                                        |
| :---: | ---------------------------------------------------------------------------------------------------------- |
|   1   | Simple terms. No jargon. Explain what variables, loops, and functions are. Use analogies. Show every step. |
|   2   | Assume basic syntax knowledge. Explain standard library functions. Provide simple examples.                |
|   3   | Use standard programming terminology. Mention time and space complexity briefly. Reference documentation.  |
|   4   | Use technical terms freely. Discuss algorithmic trade-offs. Reference design patterns.                     |
|   5   | Concise and precise. Focus on edge cases and optimisation. Discuss advanced concepts directly.             |

**Mathematics level adaptation:**

| Level | Communication Style                                                                          |
| :---: | -------------------------------------------------------------------------------------------- |
|   1   | Intuitive explanations with visual descriptions. No formal notation. Use analogies.          |
|   2   | Introduce basic notation gradually. Use numerical examples before generalising.              |
|   3   | Use standard mathematical notation. Reference theorems by name. Provide derivation sketches. |
|   4   | Use formal notation freely. Discuss proofs and rigour. Reference advanced theorems.          |
|   5   | Precise and formal. Discuss generalisations and connections between fields.                  |

**How hint level and student level combine:**

The hint level controls *how much* to reveal. The student level controls *how* to communicate it. For example, hint level 3 (Structural) looks different for different students:

For a student at programming level 2, maths level 1:

> "To solve this, you need to go through each number in the list one at a time and keep track of the running total. Think of it like adding up items on a receipt. You will need a loop and a variable to store the total."

For a student at programming level 5, maths level 4:

> "Apply a reduction over the array. Alternatively, use NumPy vectorisation for O(1) amortised on contiguous memory. Consider numerical stability if accumulating floating-point values."

Both responses are at hint level 3 (structural outline, no code), but the language is adapted to each student's ability.

---

## 2. Intelligent Pre-Filter Pipeline

User messages are processed through a lightweight pre-processing pipeline before the main tutoring response is generated. Embeddings support optional greeting/off-topic filtering, while the configured LLM handles same-problem detection, elaboration detection, difficulty estimation, and hint selection.

### 2.1 Embedding Service

**Supported models:**

| Provider  | Model                     | Notes                                                                                                |
| --------- | ------------------------- | ---------------------------------------------------------------------------------------------------- |
| Cohere    | `embed-v4.0`              | Text embeddings. Default provider. |
| Vertex AI | `multimodalembedding@001` | Text embeddings. Supported provider. Uses Google Cloud service account auth (Bearer token in code). |
| Voyage AI | `voyage-multimodal-3.5`   | Text embeddings. Supported provider. |

The embedding provider is configured via the `EMBEDDING_PROVIDER` environment variable (`cohere`, `vertex`, or `voyage`, default `cohere`). Model IDs are configured via `EMBEDDING_MODEL_COHERE`, `EMBEDDING_MODEL_VERTEX`, and `EMBEDDING_MODEL_VOYAGE`. Vertex AI uses `GOOGLE_APPLICATION_CREDENTIALS` (service account JSON path), `GOOGLE_VERTEX_EMBEDDING_LOCATION`, and automatic Bearer token refresh. The repository env files use London (`europe-west2`) as the default Vertex location. If the primary provider fails, the service tries the remaining configured providers in order.

**Why these models:**

- **Clear default path.** Cohere `embed-v4.0` is the default embedding provider, with Vertex AI and Voyage AI available when selected.
- **Simple optional filters.** Embeddings are used for greeting/off-topic filtering only, so the service stays lightweight and easy to reason about.
- **Fast similarity checks.** The service uses 256-dimensional vectors for efficient NumPy cosine similarity in the pre-filter pipeline.

**Implementation:** `backend/app/ai/embedding_service.py`

The service uses a primary/fallback architecture. The `EMBEDDING_PROVIDER` setting determines which provider is primary. If that provider's API call fails, the remaining configured providers are tried automatically.

```python
class EmbeddingService:
    def __init__(self, provider: str, ...):
        """Primary provider chosen by EMBEDDING_PROVIDER. Remaining providers are fallbacks."""

    async def embed_text(self, text: str) -> Optional[list[float]]:
        """Return an embedding vector, using cache when available."""

    def check_greeting(self, embedding: list[float]) -> bool:
        """Optional synchronous check against pre-embedded greeting anchors."""

    def check_off_topic(self, embedding: list[float]) -> bool:
        """Optional synchronous check using pre-embedded topic and off-topic anchors."""

```

**Performance optimisations:**

- **Single embed per message (when filters are enabled).** The user message is embedded exactly once, and only when greeting/off-topic filtering is enabled.
- **Persistent HTTP client.** A shared `httpx.AsyncClient` reuses TCP connections across requests, reducing connection overhead.
- **In-memory LRU cache.** Up to 512 recent embeddings are cached by normalised text key, avoiding redundant API calls for repeated or similar inputs.
- **Batched anchor initialisation.** Greeting, topic, and off-topic anchors are embedded in provider-agnostic batches when the embedding service is first initialised, avoiding provider-specific batch-size limits.
- **NumPy vectorised similarity.** Anchor embeddings are stored as NumPy `ndarray` matrices. Cosine similarity against all anchors is computed via a single matrix-vector multiply (`matrix @ vec / (norms * vec_norm)`) instead of N individual dot products.

### 2.2 Greeting Detection (Optional, Disabled by Default)

Pre-embed 14 common greetings: "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "how are you", "what's up", "hi there", "hey there", "hello there", "good day", "howdy", "greetings".

When `CHAT_ENABLE_GREETING_FILTER=true`, a user message with high cosine similarity to a greeting anchor returns a personalised canned response instantly using the student's username:

> "Hello {username}! I am your AI coding tutor. Ask me a question about programming, mathematics, or physics and I will guide you through it."

No LLM call is made for this branch.

### 2.3 Topic Relevance Gate (Optional, Disabled by Default)

Pre-embed **52 topic anchors** (specific STEM/coding phrases) and **20 off-topic anchors** (weather, sports, restaurants, entertainment, small talk, personal assistant questions, and recommendation-style prompts).

The off-topic gate compares both scores:
- `topic_max`: best similarity to the topic anchors
- `off_topic_max`: best similarity to the off-topic anchors

When `CHAT_ENABLE_OFF_TOPIC_FILTER=true`, the provider-specific profile treats a message as off-topic when the off-topic signal is both strong and clearly stronger than the topic signal (plus a low-topic fallback for very weak domain matches).

The relative comparison is the primary rule in all three provider profiles (Cohere, Vertex AI, and Voyage AI) and is more reliable than a topic-only threshold on short conversational prompts.

If the message is classified as off-topic, it is rejected:

> "I can only help with programming, mathematics, and science questions. Please ask me something related to these subjects."

No LLM call is made for this branch.

### 2.4 Same-Problem, Elaboration, Difficulty, and Hint Metadata

The chat path uses a hidden metadata schema with five fields:
- `same_problem`
- `is_elaboration`
- `programming_difficulty`
- `maths_difficulty`
- `hint_level`

The response controller supports three modes for `/ws/chat`:
- `auto` (default): prefer the `Single-Pass Header Route`, automatically switch to the `Two-Step Recovery Route` after repeated header parse failures, and retry the faster route after stable recovery turns.
- `single_pass_header_route`: always use the `Single-Pass Header Route`.
- `two_step_recovery_route`: always use the `Two-Step Recovery Route`.

For the first message in a session, there is no previous Q+A context, so the metadata is expected to mark a new problem.

**Implementation detail:** The student state caches the previous Q+A text (not an embedding). After each LLM response, the previous question and answer text are stored for the next turn. Canned responses do not update the context state. The WebSocket handler keeps this hidden pedagogy runtime state per chat session (not shared across different session IDs on the same socket), and the `auto` response-controller degradation counters follow the same session boundary.

**Implementation:** `backend/app/ai/pedagogy_engine.py`, `backend/app/ai/prompts.py`, and `backend/app/services/stream_meta_parser.py`

See `docs/semantic-recognition-testing.md` for provider-specific semantic threshold values and calibration data (Cohere, Vertex AI, Voyage AI) used by the optional greeting/off-topic filters.

### 2.5 `Single-Pass Header Route` (Default Path)

In the primary response path, one streamed LLM call emits a hidden metadata header before the visible tutor answer.

The backend provides hidden pedagogy context to the model:
- previous Q+A text (when available),
- current effective levels,
- current hint and difficulty state.

The LLM decides `same_problem`, `is_elaboration`, `programming_difficulty`, `maths_difficulty`, and `hint_level` in the same streamed response. The backend validates and clamps all metadata fields to `[1, 5]`.

### 2.6 `Two-Step Recovery Route` (Metadata + Reply)

The recovery route uses two LLM calls:
1. one compact metadata-only JSON call (token-trimmed payload), then
2. one streamed tutor reply call.

This route is used when:
- the controller mode is `two_step_recovery_route`, or
- `auto` mode degrades after repeated `Single-Pass Header Route` header parse failures.

The backend sends the `meta` WebSocket event before the first visible `token` in this route as well.

### 2.7 `Emergency Full-Hint Fallback` (Local Last Resort)

If the `Single-Pass Header Route` header parsing fails for the current turn, the backend discards the failed visible output and runs the `Two-Step Recovery Route`.

If the metadata step also fails, the backend builds local emergency metadata:
- `same_problem = false`
- `is_elaboration = false`
- `hint_level = 5`
- `programming_difficulty = round(current effective programming level)` (clamped to `1..5`)
- `maths_difficulty = round(current effective maths level)` (clamped to `1..5`)

The current turn still generates a visible tutor reply after this local metadata fallback, and the `meta` event is still sent before visible tokens.

### 2.8 Problem Difficulty and Hint Selection

Problem difficulty is tracked separately for programming and mathematics on a 1-to-5 scale, and the next hint level is selected through the hidden metadata schema in both LLM routes.

The backend validates and clamps metadata fields to `[1, 5]`, applies them to the student state, and then persists the final values with the assistant message. In `auto` mode, repeated `Single-Pass Header Route` header failures switch subsequent turns to the `Two-Step Recovery Route` for stability, and successful recovery turns later trigger a retry of the faster route.

**Elaboration requests:** Generic same-problem follow-ups typically keep the current difficulty and move the hint level forward.

**New problems:** The metadata selects fresh difficulty values and a new hint level. The backend updates effective levels using the previous completed interaction before applying the new values.

**Emergency metadata turns:** When `Emergency Full-Hint Fallback` is used, that turn's fallback difficulty values do not contribute to the next EMA update.

**Starting hint level behaviour** remains tied to the gap between estimated difficulty and effective level:

```
prog_gap = programming_difficulty - round(effective_programming_level)
maths_gap = maths_difficulty - round(effective_maths_level)
gap = max(prog_gap, maths_gap)
starting_hint_level = max(1, min(4, 1 + gap))
```

**Effective level updates** use the corresponding difficulty for each dimension independently. `programming_difficulty` feeds the EMA update for `effective_programming_level`, and `maths_difficulty` feeds the EMA update for `effective_maths_level`. The formula from Section 1.3 applies to each.

**Implementation:** `backend/app/ai/pedagogy_engine.py`

### 2.9 Pre-Filter and Metadata Pipeline Summary

The complete pipeline for each user message:

```
1. If optional semantic filters are enabled, embed the user's input once (single API call; cached if seen before).
2. Optional greeting filter (disabled by default): high similarity to greeting anchors → canned response. Stop.
3. Optional off-topic filter (disabled by default): off-topic rule triggers → reject. Stop.
4. Build fast pedagogy signals from the previous Q+A text (for hidden metadata context) and optional filter result.
5. Build prompt + context using either full history or the hidden rolling summary cache plus recent raw turns (no inline summarisation on the `/ws/chat` critical path).
6. In the `Single-Pass Header Route`, make one streamed LLM call that emits a hidden metadata header first, then the visible tutor answer.
7. If the header route fails, discard the failed visible output and run the `Two-Step Recovery Route` (metadata JSON call + streamed reply call).
8. If the recovery metadata step fails, use `Emergency Full-Hint Fallback`, then stream a visible reply.
9. Send a `meta` WebSocket event as soon as metadata is available, stream visible tokens, apply pedagogy metadata to state, and persist the assistant turn.
10. Refresh the hidden rolling summary cache asynchronously after the turn completes.
```

---

## 3. What This Phase Delivers

**Part A (Text-Based Chat):**

- `chat_sessions` and `chat_messages` database tables.
- Updated `users` table with hidden effective level fields.
- An embedding service (Cohere `embed-v4.0` by default, with Vertex AI and Voyage AI as supported providers) for optional greeting/off-topic filtering.
- An LLM abstraction layer supporting three providers with automatic failover.
- A pedagogy engine that manages hint levels, student adaptation, and dynamic levelling.
- A WebSocket endpoint (`/ws/chat`) that streams AI responses.
- A frontend chat page with message history, streaming display, GFM markdown rendering (including tables), syntax-highlighted code blocks, and LaTeX formula rendering.

**Part B (File and Image Uploads):**

- File upload endpoint supporting images and documents.
- Multimodal embedding for uploaded content (using the configured embedding provider).
- Vision-capable LLM processing for screenshots and images.
- Updated chat interface with upload controls, drag-and-drop, and clipboard paste.
- Per-message attachment limits: up to 3 photos and 2 files.
- Support for `.ipynb` documents, with text extraction from notebook cells.

---

## 4. Development Part A: Text-Based Chat

### 4.1 Database Changes

#### Alembic migration: update `users` table

Add two columns to the existing `users` table:

| Column                          | Type  | Default | Notes                                                                                         |
| ------------------------------- | ----- | :-----: | --------------------------------------------------------------------------------------------- |
| `effective_programming_level` | FLOAT |  NULL  | Initialised from `programming_level` on first chat interaction. Never shown to the student. |
| `effective_maths_level`       | FLOAT |  NULL  | Initialised from `maths_level` on first chat interaction. Never shown to the student.       |

When either column is NULL, the system initialises it from the corresponding self-assessed integer value.

#### New table: `chat_sessions`

| Column           | Type        | Notes                                |
| ---------------- | ----------- | ------------------------------------ |
| `id`           | UUID        | Primary key                          |
| `user_id`      | UUID        | Foreign key to `users.id`, indexed |
| `session_type` | VARCHAR(20) | Scope string, default `"general"`  |
| `module_id`    | UUID        | Nullable scope identifier            |
| `created_at`   | TIMESTAMP   | Server default                       |

Index on `(user_id, session_type)`.

#### New table: `chat_messages`

| Column                 | Type        | Notes                                                            |
| ---------------------- | ----------- | ---------------------------------------------------------------- |
| `id`                 | UUID        | Primary key                                                      |
| `session_id`         | UUID        | Foreign key to `chat_sessions.id`, indexed                     |
| `role`               | VARCHAR(10) | `"user"` or `"assistant"`                                    |
| `content`            | TEXT        | Message body                                                     |
| `hint_level_used`    | INTEGER     | Nullable, 1 to 5 (set by pedagogy engine for assistant messages) |
| `problem_difficulty` | INTEGER     | Nullable, 1 to 5 (programming difficulty at time of response)    |
| `maths_difficulty`   | INTEGER     | Nullable, 1 to 5 (maths difficulty at time of response)          |
| `attachments_json`   | TEXT        | Nullable JSON array of uploaded file IDs for user messages       |
| `created_at`         | TIMESTAMP   | Server default                                                   |

Index on `(session_id, created_at)` for efficient history retrieval.

### 4.2 Chat Schemas

**`backend/app/schemas/chat.py`:**

- `ChatMessageIn`: `content` (str), `session_id` (optional UUID), `upload_ids` (list of UUID, up to 5 per message payload).
- `ChatMessageOut`: `id`, `session_id`, `role`, `content`, `hint_level_used`, `problem_difficulty`, `maths_difficulty`, `attachments`, `created_at`.
- `ChatSessionOut`: `id`, `session_type`, `created_at`.
- `ChatSessionListItem`: `id`, `preview`, `created_at`.

### 4.3 Chat Service

**`backend/app/services/chat_service.py`:**

- `get_or_create_session(db, user_id, session_id=None) -> ChatSession`: reuses a provided session only when it is owned by the user and matches the incoming request scope; otherwise it ignores the mismatched `session_id` and resolves or creates a session for the current scope.
- `save_message(...) -> ChatMessage`: stores user/assistant turns with metadata (`hint_level_used`, difficulty values, and optional attachment IDs).
- `get_chat_history(db, session_id) -> list[dict]`: loads chronological role/content history for context building.
- `get_session_messages(db, user_id, session_id) -> list[dict] | None`: ownership-checked history endpoint payload, including resolved attachment metadata.
- `get_user_sessions(db, user_id) -> list[dict]`: newest-first session list with a first-message preview.
- `delete_session(db, user_id, session_id) -> bool`: deletes a session and its messages.

### 4.4 LLM Abstraction Layer (Three-Model Failover)

#### `backend/app/ai/llm_base.py`

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMProvider(ABC):
    @abstractmethod
    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],   # [{"role": "user"/"assistant", "content": "..."}]
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Yield response tokens one at a time."""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Return approximate token count for the given text."""
        ...
```

#### Provider implementations

The LLM provider is configured via the `LLM_PROVIDER` environment variable (`anthropic`, `openai`, or `google`, default `google`). In this codebase, `google` supports **Gemini via Google AI Studio** (`GOOGLE_API_KEY`) and **Gemini via Vertex AI** (Google Cloud service account JSON path via `GOOGLE_APPLICATION_CREDENTIALS`, plus `GOOGLE_VERTEX_GEMINI_LOCATION`, with automatic Bearer token refresh). The Google transport is selected explicitly with `GOOGLE_GEMINI_TRANSPORT` (`aistudio` or `vertex`). The repository env files use `aistudio` as the default Google transport and London (`europe-west2`) as the default Vertex location. If the configured provider is unavailable, the factory falls back to any other configured provider.

| Provider  | Model                | Implementation File  |
| --------- | -------------------- | -------------------- |
| Anthropic | Claude Sonnet 4.6 / Claude Haiku 4.5 | `llm_anthropic.py` |
| Google (AI Studio / Vertex AI) | Gemini 3 Flash Preview / Gemini 3.1 Pro Preview | `llm_google.py` |
| OpenAI    | GPT-5.2 / GPT-5 mini | `llm_openai.py`    |

Each provider implementation:

- Calls its respective API with `stream=True`.
- Reads streamed events and yields content tokens.
- Implements `count_tokens` using a character-based heuristic (chars / 4) or the provider's tokeniser if available.
- Retries on HTTP 429 (rate limit) or 5xx errors up to 3 times with exponential backoff (1s, 2s, 4s).
- Raises a custom `LLMError` exception on unrecoverable failure.

#### `backend/app/ai/llm_factory.py`

```python
def get_llm_provider(settings) -> LLMProvider:
    """Return the configured LLM provider.
    Reads LLM_PROVIDER (default 'google').
    Falls back to any provider with a valid API key."""
```

### 4.5 Pedagogy Engine Implementation

**`backend/app/ai/pedagogy_engine.py`:**

#### Student state

```python
class StudentState:
    user_id: str
    effective_programming_level: float       # 1.0 to 5.0
    effective_maths_level: float             # 1.0 to 5.0
    current_hint_level: int                  # 1 to 5
    starting_hint_level: int                 # 1 to 4 (set at start of each problem)
    current_programming_difficulty: int      # 1 to 5
    current_maths_difficulty: int            # 1 to 5
    last_question_text: str | None           # previous user question text (for hidden pedagogy metadata context)
    last_answer_text: str | None             # previous assistant answer text (for hidden pedagogy metadata context)
    skip_next_ema_update_once: bool          # set when emergency metadata fallback is used
```

#### Processing flow

```python
async def prepare_fast_signals(
    self,
    user_message: str,
    student_state: StudentState,
) -> PedagogyFastSignals:
    """
    Returns optional canned-filter output plus fast metadata context signals.

    1. Optionally embed the user message (only when greeting/off-topic filters are enabled).
    2. Optionally check greeting detection (disabled by default). If greeting, return canned response.
    3. Optionally check topic relevance (disabled by default). If off-topic, return rejection.
    4. Return previous Q+A text (when available) for the LLM metadata routes.
    """

def apply_stream_meta(
    self,
    student_state: StudentState,
    meta: StreamPedagogyMeta,
) -> ProcessResult:
    """
    Validates and applies hidden metadata parsed from the streamed LLM header.
    Updates current hint/difficulty state and effective levels.
    """
```

### 4.6 Prompts

**`backend/app/ai/prompts.py`:**

All system prompts stored as string templates:

- `BASE_SYSTEM_PROMPT`: The tutor persona. Includes instructions to use LaTeX (`$...$` for inline, `$$...$$` for display) for all mathematical expressions and markdown code blocks with language specifiers (e.g. ` ```python `) for all code.
- `HINT_LEVEL_INSTRUCTIONS[1..5]`: Instructions for each hint level defining what the AI may and may not reveal.
- `PROGRAMMING_LEVEL_INSTRUCTIONS[1..5]`: Language adaptation rules for each programming skill tier.
- `MATHS_LEVEL_INSTRUCTIONS[1..5]`: Language adaptation rules for each maths skill tier.
- `PEDAGOGY_TWO_STEP_RECOVERY_JSON_PROMPT`: Strict metadata JSON prompt for the `Two-Step Recovery Route`.
- `SINGLE_PASS_PEDAGOGY_PROTOCOL_PROMPT`: Hidden metadata-header protocol for the single streamed reply path.
  - Requires the `<<GC_META_V1>> ... <<END_GC_META>>` header before any visible answer text.
  - Requires raw JSON (no Markdown code fences) in the metadata block.
  - Requires the visible answer to follow the chosen `hint_level`.

The context builder assembles the final system prompt for the standard hint-specific path and the single-pass hidden-metadata path.

For the `/ws/chat` response path, the implementation uses `build_single_pass_system_prompt(...)` in the `Single-Pass Header Route` and `build_system_prompt(...)` in the `Two-Step Recovery Route` after metadata selection. Same-problem and difficulty classification remain part of the LLM metadata routes and are not split into separate classifier calls.

### 4.7 Context Builder

**`backend/app/ai/context_builder.py`:**

```python
def build_system_prompt(hint_level, programming_level, maths_level) -> str:
    """Assemble the full system prompt from base + hint + student levels."""

def build_single_pass_system_prompt(programming_level, maths_level, *, pedagogy_context) -> str:
    """Assemble the single-pass prompt (hidden metadata header + visible answer)."""

async def build_context_messages(
    chat_history: list[dict],
    user_message: str,
    llm: LLMProvider,
    max_context_tokens: int,
    compression_threshold: float = 0.8,
    *,
    cached_summary: str | None = None,
    cached_summary_message_count: int | None = None,
    allow_inline_compression: bool = True,
) -> list[dict]:
    """
    Build a context message list with automatic compression.

    1. Use full history when the conversation is short.
    2. Prefer a hidden rolling summary cache plus recent raw turns when history grows.
    3. Optionally compress older messages inline when enabled (used by background refresh paths).
    4. Fallback: simple truncation (most recent messages only).
    """
```

The chat response path uses the hidden rolling summary cache (stored on `chat_sessions`) and keeps recent turns intact. The cache is refreshed asynchronously after a completed assistant reply. Inline summarisation remains available as a helper and is used outside the response critical path.

### 4.8 Chat Endpoints

**`backend/app/routers/chat.py`:**

#### REST endpoints

| Endpoint                             | Method | What it does                                                                                                                                                                        |
| ------------------------------------ | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/api/chat/sessions`               | GET    | Returns all chat sessions for the current user, newest first. Each entry includes the session ID, a preview (first 80 characters of the first user message), and the creation date. |
| `/api/chat/sessions/{id}`          | DELETE | Deletes a session and all its messages. Returns 404 if the session does not exist or belongs to another user.                                                                       |
| `/api/chat/sessions/{id}/messages` | GET    | Returns all messages for a session in chronological order.                                                                                                                          |

#### WebSocket endpoint: `/ws/chat`

1. Client connects with JWT as query parameter: `/ws/chat?token=<access_token>`.
2. Backend validates the token. On failure, closes the connection with code 4001.
3. Backend initialises embedding + pedagogy services and manages a session-scoped hidden pedagogy runtime state, seeded from the profile.
4. On each message from the client:
   1. Parse the JSON payload. Core fields include `{content, session_id, upload_ids}`.
   2. Validate upload ID count and UUID format.
   3. Resolve uploads for the current user only, and ignore expired or inaccessible files.
   4. Split uploads into images/documents and enforce per-message mix limits.
   5. Build enriched user text (plain message + extracted document text).
   6. Persist the user turn with optional attachment IDs.
   7. Run fast pedagogy checks:
      - no attachments: optional greeting/off-topic filters may run;
      - all paths prepare previous Q+A text context for the metadata routes.
   8. If filtered, send a canned response and store it.
   9. Otherwise, build prompt + context (using the hidden summary cache where available).
   10. Use the current chat session's hidden pedagogy runtime state (previous Q+A text, hint/difficulty state, and auto-mode degradation counters):
      - `Single-Pass Header Route`: stream one LLM response with a hidden metadata header;
      - on header failure, discard failed visible output and run the `Two-Step Recovery Route`;
      - if recovery metadata fails, use `Emergency Full-Hint Fallback`.
   11. Send a `meta` event as soon as metadata is available, then stream visible `token` events.
   12. Persist the assistant turn, apply pedagogy metadata, write effective levels back to `users`, and send the final `done` event.
   13. Schedule an asynchronous hidden summary-cache refresh for the session.
5. On disconnect, clean up.

### 4.9 Frontend: WebSocket Helper

**`frontend/src/api/ws.ts`:**

```typescript
function createChatSocket(
  onEvent: (event: WsEvent) => void,
  onOpen?: () => void,
  onClose?: () => void
): {
  send: (content: string, sessionId?: string | null, uploadIds?: string[]) => void;
  close: () => void;
}
```

The helper forwards server events (`session`, `meta`, `token`, `done`, `canned`, `error`) and sends message payloads with optional `session_id` and `upload_ids`.

### 4.10 Frontend: Chat Page

**`frontend/src/chat/ChatPage.tsx`:** Full-page chat layout with a collapsible sidebar.

- On first load (empty session with no messages), displays a welcome greeting using the student's username. This is a static UI element, not an LLM response.
- Connects WebSocket on mount.
- Loads the user's chat sessions via `GET /api/chat/sessions` on mount.
- When the user selects a session from the sidebar, loads its messages via `GET /api/chat/sessions/{id}/messages`.
- Renders the streaming AI response in real time.
- Applies the early `meta` event to show a lightweight hint/difficulty preview before the first visible token arrives.
- At the bottom of the page, below the input area, displays a small disclaimer in muted text.

**`frontend/src/chat/ChatSidebar.tsx`:** Collapsible sidebar on the left side of the chat page.

- Lists all chat sessions for the current user, newest first.
- Each entry shows a preview (first line of the first user message) and the date.
- A "New Chat" button at the top creates a new session.
- Each session has a delete button. Clicking it removes the session (with confirmation) via `DELETE /api/chat/sessions/{id}`.
- The sidebar can be collapsed to a narrow strip with a toggle button, giving more space to the chat area.

**`frontend/src/chat/ChatMessageList.tsx`:** Scrollable message container with auto-scroll to the bottom when new content arrives. It also renders the streaming assistant bubble once hidden metadata is parsed, so the hint/difficulty preview can appear before visible answer text.

**`frontend/src/chat/ChatInput.tsx`:** Text input with a send button.

- Disabled whilst the AI is responding.
- Shift+Enter for newlines, Enter to send.

**`frontend/src/chat/ChatBubble.tsx`:** Renders a single message.

- User messages are displayed as plain text in a compact brand-coloured bubble with support for inline image previews and file download buttons.
- Assistant messages render in a soft bordered card that matches the neutral grey brand palette.
- Assistant metadata (hint level and programming/maths difficulty) is shown as compact badges above the answer content for quicker scanning.
- AI messages are rendered via the markdown/LaTeX renderer (see below).

### 4.11 Markdown, Code, and LaTeX Rendering

**`frontend/src/components/MarkdownRenderer.tsx`:**

Renders AI responses with full support for:

- **GFM tables** via `remark-gfm`. Tables render inside a rounded, scrollable wrapper with a soft border, alternating row backgrounds, and hover highlights. A preprocessing step escapes pipe characters (`|`) inside inline math spans on table rows so that `$\pi(a|s)$` renders correctly instead of splitting the cell.
- **Code blocks** with syntax highlighting via `react-syntax-highlighter` using the Prism `one-light` theme. Language-tagged blocks render as compact bordered panels without oversized headers, untagged blocks render as plain compact monospace blocks, and short single-line untagged snippets are collapsed to tight monospace rendering so table rows are not stretched unnecessarily.
- **Inline code** with monospace styling, a subtle border, and a muted background that remains distinct from both paragraph text and full code blocks.
- **LaTeX formulas** rendered via KaTeX with custom spacing:
  - Inline mathematics: `$...$` with increased letter-spacing (`0.035em`) and a larger relative font size (`1.12em`) for clearer in-line readability.
  - Display mathematics: `$$...$$` in a bordered rounded container with a soft neutral-grey gradient, larger relative font size (`1.18em`), and increased letter/word spacing for easier visual parsing.
- **Standard markdown:** bold, italic, links, lists, headings, horizontal rules, and blockquotes.
- **Structural styling:** slightly increased text tracking and line height, clearer heading rhythm, and muted accents for links, blockquotes, and dividers so longer tutor responses remain clean and readable.

**Frontend dependencies:**

- `react-markdown`
- `remark-gfm`
- `remark-math`
- `react-syntax-highlighter`
- `katex` and `rehype-katex`

### 4.12 Update Routing and Profile

**`App.tsx`:** Add the `/chat` route (protected). Update the default redirect from `/` to point to `/chat` instead of `/profile`, so students land on the chat page after login.

**`Navbar.tsx`:** The Chat link is active and routes to `/chat`.

### 4.13 Alembic Migration

Create a migration for:

- Adding `effective_programming_level` and `effective_maths_level` columns to `users`.
- Creating `chat_sessions` and `chat_messages` tables.

---

## 5. Development Part B: File and Image Uploads

### 5.1 Motivation

A common pattern among students learning to code is taking a screenshot of their code or error message and sending it directly to an AI assistant. Supporting image and document uploads enables this natural workflow and removes friction from the tutoring experience. Rather than requiring students to manually copy and paste text, they can simply screenshot their IDE, terminal output, or handwritten equations.

### 5.2 Upload Endpoint

**`backend/app/routers/upload.py`:**

`POST /api/upload` (authenticated)

Accepts multipart form data with:

- Images: PNG, JPG, JPEG, GIF, WebP (max 5 MB each).
- Documents: PDF, TXT, PY, JS, TS, CSV, IPYNB (max 2 MB each).

Per-message limits are enforced when attachments are sent in chat:

- up to 3 photos;
- up to 2 document files.

`POST /api/upload` returns attachment references (`id`, `filename`, `content_type`, `file_type`, `url`) which can be included in the next WebSocket message via `upload_ids`.

`GET /api/upload/{upload_id}/content` (authenticated) serves preview/download content for the same user only.

Uploaded files are temporary and include an expiry timestamp (default 24 hours).

### 5.3 Multimodal Processing

When a chat message includes uploaded files:

1. **Images:** Read from temporary storage and sent to the LLM as base64 image parts in the final user message payload.
2. **Documents:** Text is extracted and appended to the user message as contextual content:
   - PDF via `pypdf`,
   - plain/code files via text decoding,
   - `.ipynb` by reading notebook JSON and concatenating cell sources.
3. **Metadata routing:** Same-problem, elaboration, difficulty, and hint metadata are produced by the LLM metadata routes using previous Q+A text plus the current turn context.
4. **Filter behaviour with attachments:** greeting/off-topic filters are skipped for attachment messages so uploaded learning material is always treated as tutoring context.

### 5.4 Updated Chat Interface

**`frontend/src/chat/ChatInput.tsx`** (updated for Part B):

- Add a file upload button (paperclip icon) next to the text input.
- Show file previews (image thumbnails or file names) before sending.
- Support drag-and-drop onto the chat input area.
- Support paste from clipboard (Ctrl+V) for screenshots.
- Enforce attachment limits per message: up to 3 photos and 2 files.

**`frontend/src/chat/ChatBubble.tsx`** (updated for Part B):

- Render attached images inline within user messages.
- Show document attachments as clickable download buttons.
- Load attachment content through authenticated blob fetches instead of public URLs.

---

## 6. Verification Checklist

### Part A: Text-Based Chat

- [ ] Opening the chat page for the first time shows a personalised welcome addressed to the current username.
- [ ] The disclaimer "AI responses may contain errors. Always verify important information independently." is visible below the input area.
- [ ] Opening the chat page establishes a WebSocket connection (visible in browser dev tools).
- [ ] Sending a message produces a streamed AI response (tokens appear one by one).
- [ ] The AI's first response to any new topic is never a complete answer.
- [ ] For a problem at or below the student's level, the first response uses Socratic questioning (hint level 1).
- [ ] For a problem well above the student's level, the first response provides more concrete guidance (hint level 3 or 4) but still not the full solution.
- [ ] Asking follow-up questions on the same problem escalates the hint level by 1 each time.
- [ ] Asking about a different topic resets the hint counter and recalculates the starting level.
- [ ] The effective student level updates in the database after the student moves to a new problem.
- [ ] Greeting messages ("hello", "hi") receive an instant personalised canned response that includes the student's username, with no LLM delay.
- [ ] Off-topic questions ("what is the weather?") are politely rejected with no LLM delay.
- [ ] AI responses render code blocks with syntax highlighting, with compact monospace rendering for short untagged snippets.
- [ ] AI responses render LaTeX formulas correctly (both inline `$...$` and display `$$...$$`).
- [ ] Refreshing the page preserves and displays the previous chat history.
- [ ] If the primary LLM provider is unavailable (simulate with a wrong API key), the system falls back to the next provider.
- [ ] If all LLM providers fail, the user sees a clear error message.

### Part B: File and Image Uploads

- [ ] The upload button (paperclip icon) appears next to the text input.
- [ ] Dragging an image onto the chat input area shows a preview.
- [ ] Pasting a screenshot via Ctrl+V attaches it to the current message.
- [ ] Per-message attachment limits are enforced as 3 photos and 2 files.
- [ ] Uploading a code file (e.g. `.py`) includes its content in the AI context.
- [ ] Uploading an `.ipynb` file includes notebook cell text in the AI context.
- [ ] Same-problem detection works across text and image inputs (e.g. a typed question followed by a screenshot of the same code).
- [ ] Files exceeding the size limit are rejected with a clear message.
- [ ] Expired attachment references are rejected with a clear error.
- [ ] Unsupported file types are rejected with a clear message.
