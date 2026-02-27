# Pedagogy Algorithm

A precise reference for the tutoring algorithm as implemented. For deployment context and implementation history, see `phase-2-chat.md`.

---

## 1. Teaching Philosophy

The tutor follows a guided discovery approach. It asks questions, names concepts, and shows structure before revealing code or derivations. The core rules are:

1. A complete answer is never given on the first response, regardless of difficulty or student level.
2. Hints escalate from guiding questions through conceptual explanation to concrete examples.
3. A full solution is only reachable after multiple exchanges on the same problem.
4. Communication style adapts to the student's assessed ability, independently of the hint level.
5. Internal ability levels are never shown to the student.

---

## 2. Student Self-Assessment

At registration, students rate their programming and mathematics ability on a 1-5 slider labelled "Beginner" to "Expert". These integers are stored in the `users` table as `programming_level` and `maths_level` and seed the effective levels on first interaction.

| Level | Programming | Mathematics |
| :---: | ----------- | ----------- |
| 1 | No experience. New to coding. | Basic arithmetic only. |
| 2 | Understands variables, loops, and functions. | Comfortable with algebra and basic geometry. |
| 3 | Can write multi-file programmes. Understands data structures. | Comfortable with calculus and linear algebra. |
| 4 | Experienced with algorithms and design patterns. | Comfortable with differential equations and proofs. |
| 5 | Professional level. System design and optimisation. | Research-level mathematics. |

When a student updates either slider in Profile, the corresponding hidden effective level is rebased to the new integer value immediately.

---

## 3. Hidden Effective Levels and EMA

Two hidden floats per student, clamped to [1.0, 5.0]:

- `effective_programming_level`
- `effective_maths_level`

Both are initialised from the self-assessment integers when the student sends their first message. After each completed problem (detected when the student moves to a new topic), the effective levels are updated using an Exponential Moving Average. Each dimension is updated independently using its own hint level and difficulty.

**EMA formula (applied separately for programming and maths):**

```
demonstrated_level = difficulty * (6 - hint_level) / 5
learning_rate = 0.2 * min(1.0, difficulty / effective_level)
new_effective_level = effective_level * (1 - learning_rate) + demonstrated_level * learning_rate
```

The `learning_rate` is weighted by `difficulty / effective_level` so that problems at or above the student's level carry full weight, while easy problems carry reduced weight and cannot significantly drag the level downward.

| Final Hint Level | Demonstrated Level |
| :--------------: | :----------------: |
| 1 (Socratic) | 100% of difficulty |
| 2 (Conceptual) | 80% |
| 3 (Structural) | 60% |
| 4 (Concrete) | 40% |
| 5 (Full Solution) | 20% |

**Implementation:** `backend/app/ai/pedagogy_engine.py` → `_update_effective_levels`

The EMA update is skipped when `skip_next_ema_update_once` is set (used by the emergency fallback; see Section 10).

---

## 4. Gap Formulae

Programming and maths hint levels are computed independently. The LLM classifies the difficulty of each incoming problem; the backend then derives the hint levels deterministically.

**New problem:**

```
prog_hint  = max(1, min(4, 1 + (programming_difficulty - round(eff_prog))))
maths_hint = max(1, min(4, 1 + (maths_difficulty    - round(eff_maths))))
```

**Same problem (follow-up on the identical task):**

```
prog_hint  = min(5, current_programming_hint_level + 1)
maths_hint = min(5, current_maths_hint_level + 1)
```

The new-problem cap is 4: no student ever receives a full solution as a first response. The same-problem cap is 5, allowing escalation to a full solution only after prior interactions.

| Gap (difficulty minus rounded effective level) | Starting Hint Level |
| :--------------------------------------------: | :-----------------: |
| 0 or below | 1 (Socratic) |
| 1 | 2 (Conceptual) |
| 2 | 3 (Structural) |
| 3 or above | 4 (Concrete) |

**Implementation:** `backend/app/ai/pedagogy_engine.py` → `compute_hint_levels`

---

## 5. Hint Escalation

When the student sends a follow-up on the same problem, each hint level increments by 1 (capped at 5). An elaboration request (e.g. "explain more", "I don't understand") on the same problem is also treated as same-problem, so it increments the hint level but does not change the difficulty rating. The difficulty value associated with the last problem is preserved across same-problem turns.

---

## 6. Programming Hint Levels 1-5

Prompt text injected verbatim into the system prompt (from `backend/app/ai/prompts.py`):

**Level 1 - SOCRATIC**

> "PROGRAMMING HINT 1 (SOCRATIC): Ask targeted questions that point toward the solution. E.g. 'What happens if you trace this with input [2, 5, 1]?' or 'Which data structure gives O(1) lookup?' Never reveal code, function names, or solution steps."

**Level 2 - CONCEPTUAL**

> "PROGRAMMING HINT 2 (CONCEPTUAL): Name the exact concept needed and explain why it solves this problem. E.g. 'This is a classic sliding window problem because you need a contiguous subarray of fixed length.' No code, no function names, no step-by-step."

**Level 3 - STRUCTURAL**

> "PROGRAMMING HINT 3 (STRUCTURAL): Give a numbered step-by-step plan with specific function or method names. E.g. '1. Parse input into a dict. 2. Use collections.Counter to count frequencies. 3. Return the key with max value.' No code or pseudocode."

**Level 4 - CONCRETE**

> "PROGRAMMING HINT 4 (CONCRETE): Show partial code or a worked similar example with key syntax. E.g. show how to set up the loop and condition, but leave the student to handle edge cases and final integration."

**Level 5 - FULL SOLUTION**

> "PROGRAMMING HINT 5 (FULL SOLUTION): Provide the complete working code with line-by-line explanation. Cover edge cases, explain design choices, and note common pitfalls."

---

## 7. Maths Hint Levels 1-5

Prompt text injected verbatim into the system prompt (from `backend/app/ai/prompts.py`):

**Level 1 - SOCRATIC**

> "MATHS HINT 1 (SOCRATIC): Ask targeted questions that guide toward the solution. E.g. 'What happens if you substitute x=0?' or 'Which theorem relates integrals and derivatives?' Never reveal formulae, steps, or strategies."

**Level 2 - CONCEPTUAL**

> "MATHS HINT 2 (CONCEPTUAL): Name the exact theorem or technique needed and explain why it applies. E.g. 'Use integration by parts because the integrand is a product of a polynomial and an exponential.' No derivations or formulae."

**Level 3 - STRUCTURAL**

> "MATHS HINT 3 (STRUCTURAL): Give a numbered step-by-step strategy with theorem names. E.g. '1. Apply the chain rule. 2. Simplify using trig identity sin²x + cos²x = 1. 3. Evaluate at the boundary.' No actual computation."

**Level 4 - CONCRETE**

> "MATHS HINT 4 (CONCRETE): Show key derivation steps or a worked similar example with specific formulae. E.g. show the substitution and first integral, but leave the final evaluation to the student."

**Level 5 - FULL SOLUTION**

> "MATHS HINT 5 (FULL SOLUTION): Provide the complete derivation or proof step by step. Explain reasoning at each step. Note generalisations."

---

## 8. Student Level Adaptation

The effective level (rounded to the nearest integer) selects a communication-style instruction that is injected into the system prompt alongside the hint instruction. Hint level and student level are orthogonal: the hint level controls how much is revealed; the student level controls how it is communicated.

**Programming level instructions (from `backend/app/ai/prompts.py`):**

| Level | Instruction |
| :---: | ----------- |
| 1 | PROGRAMMING LEVEL 1 (BEGINNER): Plain language, no jargon. Explain variables, loops, functions. Use analogies. |
| 2 | PROGRAMMING LEVEL 2 (ELEMENTARY): Assume basic syntax. Explain standard library functions with simple examples. |
| 3 | PROGRAMMING LEVEL 3 (INTERMEDIATE): Standard terminology. Mention complexity briefly. Reference docs. |
| 4 | PROGRAMMING LEVEL 4 (ADVANCED): Technical terms freely. Discuss trade-offs and design patterns. |
| 5 | PROGRAMMING LEVEL 5 (EXPERT): Concise and precise. Focus on edge cases and optimisation. |

**Maths level instructions (from `backend/app/ai/prompts.py`):**

| Level | Instruction |
| :---: | ----------- |
| 1 | MATHS LEVEL 1 (BEGINNER): Intuitive explanations, no formal notation. Use analogies and numerical examples. |
| 2 | MATHS LEVEL 2 (ELEMENTARY): Introduce notation gradually. Numerical examples before generalising. |
| 3 | MATHS LEVEL 3 (INTERMEDIATE): Standard notation. Reference theorems by name. Derivation sketches. |
| 4 | MATHS LEVEL 4 (ADVANCED): Formal notation freely. Discuss proofs and rigour. |
| 5 | MATHS LEVEL 5 (EXPERT): Precise and formal. Generalisations and cross-field connections. |

---

## 9. Three-Route Implementation

Each chat turn follows one of three routes to obtain the pedagogy metadata (`same_problem`, `is_elaboration`, `programming_difficulty`, `maths_difficulty`) and the derived hint levels.

### 9.1 Single-Pass Header Route

One LLM call produces both the hidden metadata header and the student-facing answer in a single stream.

**Protocol:**

The system prompt includes `SINGLE_PASS_PEDAGOGY_PROTOCOL_PROMPT`, which instructs the model to emit:

```
<<GC_META_V1>>
{"same_problem": true|false, "is_elaboration": true|false, "programming_difficulty": 1-5, "maths_difficulty": 1-5}
<<END_GC_META>>
<student-facing answer starts here>
```

The system prompt also includes a hidden pedagogy context block (built by `_build_single_pass_pedagogy_context` in `backend/app/routers/chat.py`) that shows the model the effective levels and the pre-computed hint formulas:

```
--- Hidden Pedagogy Context (Do not reveal) ---
Effective programming level: <eff_prog>
Effective maths level: <eff_maths>
Current programming hint level: <cur_prog_hint>
Current maths hint level: <cur_maths_hint>

HINT LEVEL FORMULA (follow exactly):
New problem:
  prog_hint  = max(1, min(4, 1 + (prog_difficulty  - <round(eff_prog)>)))
  maths_hint = max(1, min(4, 1 + (maths_difficulty - <round(eff_maths)>)))
Same problem:
  prog_hint  = min(5, <cur_prog_hint>  + 1) = <result>
  maths_hint = min(5, <cur_maths_hint> + 1) = <result>

Your answer MUST obey both computed hint levels.
```

The stream is parsed by `StreamMetaParser` (`backend/app/services/stream_meta_parser.py`). As tokens arrive, the parser buffers until `<<GC_META_V1>>` is found, extracts the JSON up to `<<END_GC_META>>`, then passes remaining tokens straight to the client. If the header is absent, malformed, or preceded by visible text, the parser switches to `FALLBACK_PASSTHROUGH` and the route fails.

After the stream completes, the backend calls `pedagogy_engine.coerce_stream_meta` to validate and normalise the raw metadata dict, then `compute_hint_levels` to derive the hint levels. The backend enforces the gap formula regardless of any hint values the model may have attempted to include.

If parsing fails, the route degrades automatically to the Two-Step Recovery Route.

**Implementation:** `backend/app/routers/chat.py` (WebSocket handler), `backend/app/services/stream_meta_parser.py`, `backend/app/ai/context_builder.py` → `build_single_pass_system_prompt`

### 9.2 Two-Step Recovery Route

Two separate LLM calls: first a metadata-only JSON call, then a streamed reply.

**Step 1 - Metadata call:**

`pedagogy_engine.classify_two_step_recovery_meta` sends a compact JSON payload to the LLM using `PEDAGOGY_TWO_STEP_RECOVERY_JSON_PROMPT`. The payload contains the current message (truncated to ~320 tokens), the student state, a flag indicating whether a previous exchange exists, and (if it does) the previous question (~220 tokens) and previous answer (~300 tokens). The model returns a single JSON object:

```json
{"same_problem": true|false, "is_elaboration": true|false, "programming_difficulty": 1-5, "maths_difficulty": 1-5}
```

The backend then calls `compute_hint_levels` to derive hint levels from that metadata before the answer call begins.

**Step 2 - Answer call:**

`build_system_prompt` assembles a standard system prompt containing the base instructions, the pre-computed programming hint instruction, the pre-computed maths hint instruction, and the student level instructions. The LLM generates and streams only the student-facing answer; no metadata header is involved.

**Implementation:** `backend/app/ai/pedagogy_engine.py` → `classify_two_step_recovery_meta`, `backend/app/ai/context_builder.py` → `build_system_prompt`

### 9.3 Auto-Degradation Between Routes

In `auto` mode (default), the backend tracks consecutive single-pass header failures. After a configurable number of failures (`chat_single_pass_header_failures_before_two_step_recovery`, default 1), the session degrades automatically to the Two-Step Recovery Route. After a configurable number of successful two-step turns (`chat_two_step_recovery_turns_before_single_pass_retry`, default 1), the session attempts to return to the single-pass route.

The route mode can also be set explicitly to `single_pass_header_route` or `two_step_recovery_route` via the `chat_metadata_route_mode` setting.

---

## 10. Emergency Full-Hint Fallback

If both the single-pass header parse and the two-step recovery metadata call fail, `build_emergency_full_hint_fallback_meta` is used as a last resort.

**Behaviour:**

- `same_problem` and `is_elaboration` are set to `false`.
- `programming_difficulty` and `maths_difficulty` are set to `round(effective_level)` for each dimension.
- Both `programming_hint_level` and `maths_hint_level` are set to `5` (Full Solution).
- `skip_next_ema_update_once` is set to `true` on the `StudentState`, so the EMA update is skipped when the student moves to their next problem. This prevents the fallback from distorting the effective level.
- The metadata source is tagged `"emergency_full_hint_fallback"`.

The student receives a complete answer but the system does not penalise their effective level for needing that level of help, since the hint level was not determined by genuine assessment.

**Implementation:** `backend/app/ai/pedagogy_engine.py` → `build_emergency_full_hint_fallback_meta`

---

## Key Implementation Files

| File | Responsibility |
| ---- | -------------- |
| `backend/app/ai/pedagogy_engine.py` | EMA updates, hint level computation, metadata coercion, emergency fallback |
| `backend/app/ai/prompts.py` | All hint and level instruction strings, stream metadata delimiters, protocol prompts |
| `backend/app/ai/context_builder.py` | System prompt assembly for both routes |
| `backend/app/routers/chat.py` | WebSocket handler, route selection, pedagogy context block, DB persistence of effective levels |
| `backend/app/services/stream_meta_parser.py` | Stateful streaming parser for the hidden metadata header |
