# Semantic Recognition Testing

This document records the calibration testing for the **Vertex AI embedding-based semantic checks** used by the chat pipeline: greeting detection, off-topic filtering, optional embedding same-problem detection, and elaboration request detection.

All calibration data in this document comes from **Vertex AI `multimodalembedding@001` (256 dimensions)**, which is the default embedding provider in the application.

Cosine similarity is computed using NumPy vectorised matrix operations.

The calibration script is at `backend/tests/test_semantic_thresholds.py`. It imports anchors and threshold profiles directly from `backend/app/ai/embedding_service.py` and runs against Vertex AI `multimodalembedding@001`.

## 1. Overview

The application stores and reuses embeddings for multimodal semantics. When the optional greeting/off-topic filters are enabled, or when embedding same-problem mode is selected, the following cosine-similarity checks are used:

| Check | Default status | Purpose | Trigger condition (Vertex profile) |
|-------|----------------|---------|------------------------------------|
| Greeting | Disabled | Return a canned welcome message | Max similarity to 14 greeting anchors > 0.915 |
| Off-topic | Disabled | Reject messages unrelated to STEM | (`off_topic_max >= 0.80` and `off_topic_max - topic_max >= 0.07`) or `topic_max < 0.68` |
| Same-problem (embedding mode) | Optional | Increment hint level instead of resetting | Similarity to previous Q+A context > 0.73 |
| Elaboration request | Used in embedding same-problem mode | Treat as same problem (keep difficulty) | Max similarity to 25 elaboration anchors > 0.88 |

Design philosophy: the semantic gates should be **lenient**. Only obvious greetings and clearly unrelated chat should bypass the LLM when the optional filters are enabled. Borderline cases pass through so the student gets a helpful, natural response.

The default same-problem and difficulty decisions are made by the configured LLM. This document calibrates the Vertex embedding thresholds used by the optional semantic filters and embedding fallback mode.

## 2. Reference Anchors

### 2.1 Greeting anchors (14 phrases)

`hello`, `hi`, `hey`, `good morning`, `good afternoon`, `good evening`, `how are you`, `what's up`, `hi there`, `hey there`, `hello there`, `good day`, `howdy`, `greetings`

### 2.2 Topic anchors (52 phrases)

The topic anchor set uses **specific STEM and coding phrases** (rather than mostly single-word labels) to reduce false matches on general chat with Vertex embeddings.

It covers:
- programming and debugging (algorithms, data structures, Python errors, tests)
- mathematics and calculus (derivatives, integrals, proofs, probability, trigonometry)
- linear algebra (matrices, eigenvalues, decomposition, LU, SVD)
- numerical methods (root finding, ODE solvers, IVP/BVP, finite differences, integration)
- Fourier/signal processing
- physics (mechanics, thermodynamics, electromagnetism, quantum mechanics, wave equations)
- applied/scientific computing and optimisation

Representative anchors:
- `binary search algorithm implementation`
- `syntax error type error index error debugging`
- `calculus derivative and integral problem solving`
- `LU factorisation Gaussian elimination`
- `solve ODE using Runge Kutta method`
- `discrete Fourier transform FFT algorithm`
- `quantum mechanics Schrodinger equation wavefunction`
- `computational science numerical simulation`

### 2.3 Off-topic anchors (20 phrases)

The off-topic anchor set covers common non-tutoring chat categories so the filter can compare **topic vs off-topic** similarity directly.

It includes:
- weather (`weather forecast and temperature today`)
- sports (`football match result and sports scores`)
- food/restaurants (`pizza restaurant review and takeaway`)
- entertainment (`movie recommendation and film review`)
- jokes/small talk (`tell me a joke or funny story`, `general chit chat small talk conversation`)
- personal assistant questions (`what time is it right now`, `who are you and what is your name`)
- life/travel/shopping recommendations (`life advice and career choice guidance`, `travel planning and holiday recommendations`)

### 2.4 Elaboration anchors (25 phrases, 8 categories)

**Not understanding (4):** `I don't understand`, `I'm confused`, `that doesn't make sense`, `I still don't get it`

**Request more detail (4):** `explain more`, `can you elaborate`, `give me more details`, `tell me more`

**Step-by-step (3):** `show me step by step`, `break it down for me`, `walk me through it`

**Examples (2):** `show me an example`, `give me an example`

**Hints/answers (3):** `give me a hint`, `show me the answer`, `just tell me`

**Clarification (3):** `what do you mean`, `can you explain that again`, `could you clarify`

**Continuation (4):** `go on`, `continue`, `what's next`, `and then what`

**Simple interrogatives (2):** `why`, `how`

## 3. Greeting Detection

### 3.1 True greetings

| Phrase | Max similarity | Result (> 0.915) |
|--------|---------------:|------------------|
| hello | 1.0000 | GREETING |
| yo | 0.9394 | GREETING |
| hello hello | 0.9390 | GREETING |
| hi hi hi | 0.9182 | GREETING |
| good afternoon | 1.0000 | GREETING |

### 3.2 False positives (should NOT trigger greeting)

| Phrase | Max similarity | Result (> 0.915) |
|--------|---------------:|------------------|
| print hello | 0.9126 | pass |
| implement a greeting function | 0.8720 | pass |
| the hello protocol | 0.7983 | pass |
| greetings card design in CSS | 0.8073 | pass |

### 3.3 Greeting with embedded question (should NOT trigger)

| Phrase | Max similarity | Result (> 0.915) |
|--------|---------------:|------------------|
| Hello, how do I reverse a list? | 0.7748 | pass |
| Hi, can you help me with Python? | 0.7478 | pass |
| Good morning, I need help with my code | 0.7980 | pass |
| Hi there, explain eigenvalues please | 0.7583 | pass |

### 3.4 Analysis

Vertex greeting scores are tightly clustered at the high end, so the greeting threshold is much higher than the other semantic thresholds in this file.

Observed ranges from the calibration run:
- True greetings: **0.9182 to 1.0000**
- Greeting false positives: **0.7983 to 0.9126**
- Greeting + question: **0.7355 to 0.7980**

**Threshold: > 0.915.** This run catches **14/14** true greetings, with **0/7** false positives and **0/5** greeting+question prompts crossing the threshold.

## 4. Off-Topic Filtering

Vertex off-topic filtering uses a **dual-anchor rule**:
- compare the message against the topic anchors (`topic_max`), and
- compare the same message against the off-topic anchors (`off_topic_max`).

A message is treated as off-topic when the off-topic signal is both strong and clearly stronger than the topic signal.

### 4.1 On-topic messages

| Phrase | Topic | Off | Delta (Off-Topic minus Topic) | Result |
|--------|------:|----:|------------------------------:|--------|
| how to sort a list in Python | 0.9151 | 0.7487 | -0.1664 | pass |
| how do I debug a segfault | 0.8046 | 0.7999 | -0.0046 | pass |
| solve this ODE using Runge-Kutta | 0.6943 | 0.6548 | -0.0395 | pass |
| explain finite difference method | 0.8781 | 0.8567 | -0.0214 | pass |

### 4.2 Off-topic messages

| Phrase | Topic | Off | Delta (Off-Topic minus Topic) | Result |
|--------|------:|----:|------------------------------:|--------|
| what's the weather today | 0.7357 | 0.8123 | 0.0766 | OFF-TOPIC |
| tell me a joke | 0.7418 | 0.9429 | 0.2011 | OFF-TOPIC |
| best pizza in London | 0.7539 | 0.8282 | 0.0743 | OFF-TOPIC |
| what time is it | 0.7583 | 0.9390 | 0.1807 | OFF-TOPIC |
| what career should I choose | 0.8005 | 0.8825 | 0.0820 | OFF-TOPIC |

### 4.3 Borderline messages

| Phrase | Topic | Off | Delta (Off-Topic minus Topic) | Result |
|--------|------:|----:|------------------------------:|--------|
| what is machine learning | 0.8264 | 0.8277 | 0.0013 | pass |
| help me with my homework | 0.7954 | 0.8468 | 0.0514 | pass |
| I have an exam tomorrow | 0.7802 | 0.8434 | 0.0632 | pass |
| translate this to French | 0.7530 | 0.8154 | 0.0624 | pass |

### 4.4 Analysis

The dual-anchor design produces much cleaner separation than a topic-only threshold with Vertex embeddings.

Observed ranges from the calibration run:
- On-topic: `topic_max` **0.6943 to 0.9507**, `off_topic_max` **0.5883 to 0.8567**, delta **-0.3521 to -0.0046**
- Off-topic: `topic_max` **0.7357 to 0.8005**, `off_topic_max` **0.8123 to 0.9429**, delta **0.0743 to 0.2011**
- Borderline: `topic_max` **0.7371 to 0.8461**, `off_topic_max` **0.7988 to 0.8468**, delta **-0.0230 to 0.0632**

The most useful separator is the **delta** (`off_topic_max - topic_max`):
- On-topic sample max delta: **-0.0046**
- Off-topic sample min delta: **0.0743**
- Borderline sample max delta: **0.0632**

**Vertex rule:** `off_topic_max >= 0.80` and delta `>= 0.07`, with a low-topic fallback `topic_max < 0.68`.

On this calibration run, that yields:
- **On-topic:** 32/32 pass
- **Off-topic:** 10/10 rejected
- **Borderline:** 8/8 pass

## 5. Same-Problem Detection (Optional Embedding Mode)

The default same-problem decision in the application is made by the configured LLM using the previous Q+A text and the current message. This section calibrates the **optional embedding-based same-problem mode** (`CHAT_SAME_PROBLEM_DETECTION_MODE=embedding`), which compares the current user message against the previous Q+A context embedding.

### 5.1 Same-problem pairs (Q+A context)

Each pair shows the original question, the assistant's answer snippet, and the follow-up similarity against the combined Q+A context.

**Pair 1:**
- Q: "how to reverse a list in Python"
- A: "You can use slicing with [::-1] or the built-in reversed() function."

| Follow-up | vs Q+A |
|-----------|-------:|
| can you explain the reversal more? | 0.7537 |

**Pair 2:**
- Q: "what is the derivative of sin(x)"
- A: "The derivative of sin(x) is cos(x). This follows from the limit definition."

| Follow-up | vs Q+A |
|-----------|-------:|
| I don't understand, show me step by step | 0.6058 |

**Pair 3:**
- Q: "implement binary search"
- A: "Binary search works by repeatedly dividing the search interval in half. Check the middle element."

| Follow-up | vs Q+A |
|-----------|-------:|
| what about the edge cases for binary search? | 0.7396 |

### 5.2 Different-problem pairs

| Question A | Question B | Similarity |
|-----------|-----------|-----------:|
| how to reverse a list in Python | what is the derivative of sin(x) | 0.6613 |
| implement binary search | explain Newton's second law | 0.7085 |
| explain eigenvalues | how to read a CSV file in Python | 0.6720 |
| what is conservation of energy | explain object-oriented programming | 0.6973 |

### 5.3 Vague follow-ups vs Q+A context

Base Q: "how to reverse a list in Python"

Base A: "You can use slicing with [::-1] or the built-in reversed() function. The slice notation creates a new list in reverse order."

| Follow-up | vs Q+A |
|-----------|-------:|
| I don't understand | 0.7210 |
| explain more | 0.7305 |
| show me the answer | 0.7064 |
| can you elaborate? | 0.6094 |
| why? | 0.6720 |
| what do you mean | 0.7275 |

### 5.4 Analysis

Vertex same-problem scores overlap with different-problem scores in this calibration set, so the threshold is tuned for precision rather than recall.

Observed ranges from the calibration run:
- Same-problem pairs: **0.6058 to 0.7537**
- Different-problem pairs: **0.6613 to 0.7085**
- Vague follow-ups vs Q+A: **0.6094 to 0.7305**

**Threshold: > 0.73.** In this run it catches **3/5** explicit same-problem follow-ups, **0/4** different-problem pairs, and **1/6** vague follow-ups. Generic follow-ups are also covered by the elaboration detector in embedding mode.

## 6. Elaboration Request Detection

Elaboration detection captures generic follow-up messages such as confusion, requests for more detail, and continuation prompts. These can be treated as same-problem even when topic vocabulary is sparse.

### 6.1 True positives (should score HIGH)

| Phrase | Max similarity | Result (> 0.88) |
|--------|---------------:|-----------------|
| I really don't understand this | 0.9491 | ELABORATION |
| show me how step by step | 0.9535 | ELABORATION |
| give me an example please | 0.9792 | ELABORATION |
| how come | 0.8927 | ELABORATION |
| solve this equation | 0.7628 | pass |

### 6.2 False positives (should score LOW)

| Phrase | Max similarity | Result (> 0.88) |
|--------|---------------:|-----------------|
| what is calculus | 0.8074 | pass |
| explain eigenvalues | 0.8014 | pass |
| how to sort a list | 0.8620 | pass |
| what is recursion | 0.7476 | pass |

### 6.3 Analysis

Vertex elaboration similarities sit in a high band, but this check remains useful with a higher threshold.

Observed ranges from the calibration run:
- Elaboration true positives: **0.7628 to 0.9792**
- Elaboration false positives: **0.7476 to 0.8620**

**Threshold: > 0.88.** This run catches **12/13** elaboration-style prompts and **0/6** false positives. The missed phrase ("solve this equation") is a reasonable pass-through case for the LLM.

## 7. Threshold Summary

| Check | Threshold (Vertex profile) | Behaviour on this calibration run |
|-------|----------------------------|-----------------------------------|
| Greeting | > 0.915 | Clean separation in this sample: 14/14 true greetings, no false positives. |
| Off-topic | `off_topic_max >= 0.80` and delta `>= 0.07` (fallback `topic_max < 0.68`) | 10/10 off-topic rejected, 32/32 on-topic passed, 8/8 borderline passed. |
| Same-problem (embedding mode) | > 0.73 | Precision-biased; catches explicit topical follow-ups and avoids cross-topic matches in this sample. |
| Elaboration request | > 0.88 | Strong signal for generic follow-ups; 12/13 true positives with no false positives in this sample. |

These values match the `vertex` threshold profile in `backend/app/ai/embedding_service.py`.

## 8. Limitations

1. This is a calibration snapshot, not a benchmark. Scores will vary slightly as providers evolve their models.
2. The off-topic filter depends on both the topic-anchor set and the off-topic-anchor set. Re-calibrate when either set changes materially.
3. Embedding same-problem detection is precision-biased for Vertex. Some valid follow-ups are handled through the elaboration detector or the default LLM same-problem classifier.
4. Re-run calibration after major anchor changes or provider/model changes.

## Reproducing the Calibration

```bash
cd backend
python -m tests.test_semantic_thresholds
```
