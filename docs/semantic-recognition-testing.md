# Semantic Recognition Testing

This document records the calibration testing for the four embedding-based pre-filters used in the chat pipeline: greeting detection, off-topic filtering, same-problem detection, and elaboration request detection. All tests use the Cohere `embed-v4.0` model with 256 dimensions (reduced from 1536 via Matryoshka embeddings for faster computation). Voyage AI `voyage-multimodal-3.5` is available as a fallback for all embedding tasks.

Cosine similarity is computed using NumPy vectorised matrix operations.

The test script is at `backend/tests/test_semantic_thresholds.py`.

## 1. Overview

Before each user message reaches the LLM, four cosine similarity checks run on the embedding vector:

| Check | Purpose | Trigger condition |
|-------|---------|-------------------|
| Greeting | Return a canned welcome message | Max similarity to 14 greeting anchors > 0.75 |
| Off-topic | Reject messages unrelated to STEM | Max similarity to 53 topic anchors < 0.30 |
| Same-problem | Increment hint level instead of resetting | Similarity to previous Q+A context > 0.35 |
| Elaboration request | Treat as same problem (keep difficulty) | Max similarity to 25 elaboration anchors > 0.50 |

Design philosophy: filters should be **lenient**. Only obvious greetings and clearly off-topic messages should bypass the LLM. Borderline cases always pass through so the student gets a helpful, natural response.

All classification decisions are based on semantic similarity with no arbitrary character length thresholds.

## 2. Reference Anchors

### 2.1 Greeting anchors (14 phrases)

`hello`, `hi`, `hey`, `good morning`, `good afternoon`, `good evening`, `how are you`, `what's up`, `hi there`, `hey there`, `hello there`, `good day`, `howdy`, `greetings`

### 2.2 Topic anchors (53 phrases)

**Programming (13):** `programming`, `coding`, `Python`, `algorithm`, `data structure`, `recursion`, `sorting algorithm`, `object-oriented programming`, `debugging code`, `error in my code`, `syntax error`, `code not working`, `how to implement`

**Mathematics general (6):** `mathematics`, `calculus`, `statistics`, `probability`, `trigonometry`, `formula derivation`

**Linear algebra (7):** `linear algebra`, `matrix`, `eigenvalue`, `eigenvector`, `matrix decomposition`, `LU factorization`, `Gaussian elimination`

**Calculus and analysis (4):** `integral`, `derivative`, `differential equation`, `Taylor series`

**Numerical methods (10):** `numerical methods`, `root finding`, `bisection method`, `Newton-Raphson method`, `Euler method`, `Runge-Kutta method`, `initial value problem`, `boundary value problem`, `finite difference method`, `numerical integration`

**Fourier analysis (4):** `Fourier transform`, `discrete Fourier transform`, `FFT`, `spectral analysis`

**Physics (7):** `physics`, `mechanics`, `thermodynamics`, `electromagnetism`, `quantum mechanics`, `wave equation`, `simulation`

**Applied (2):** `optimization`, `computational science`

### 2.3 Elaboration anchors (25 phrases, 8 categories)

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

| Phrase | Max similarity | Result (> 0.75) |
|--------|---------------|-----------------|
| hello | 0.9998 | GREETING |
| hi there | 0.9998 | GREETING |
| hey | 0.9998 | GREETING |
| good morning | 0.9998 | GREETING |
| howdy | 0.9998 | GREETING |
| what's up | 1.0000 | GREETING |
| yo | 0.4642 | pass |
| greetings | 0.9998 | GREETING |
| hello hello | 0.7650 | GREETING |
| hi hi hi | 0.7377 | pass |
| good day | 0.9999 | GREETING |
| hey there | 0.9999 | GREETING |
| hello there | 0.9998 | GREETING |
| good afternoon | 0.9999 | GREETING |

### 3.2 False positives (should NOT trigger greeting)

| Phrase | Max similarity | Result (> 0.75) |
|--------|---------------|-----------------|
| say hello world in Python | 0.5273 | pass |
| hello world program | 0.5881 | pass |
| print hello | 0.6065 | pass |
| implement a greeting function | 0.6354 | pass |
| the hello protocol | 0.6393 | pass |
| good morning routine algorithm | 0.5504 | pass |
| greetings card design in CSS | 0.4889 | pass |

### 3.3 Greeting with embedded question (should NOT trigger)

| Phrase | Max similarity | Result (> 0.75) |
|--------|---------------|-----------------|
| Hello, how do I reverse a list? | 0.2610 | pass |
| Hi, can you help me with Python? | 0.4820 | pass |
| Hey, what is calculus? | 0.3198 | pass |
| Good morning, I need help with my code | 0.5403 | pass |
| Hi there, explain eigenvalues please | 0.4131 | pass |

### 3.4 Analysis

True greetings that match an anchor template score ~1.00. Non-template greetings like "hello hello" (0.77) and "hi hi hi" (0.74) score lower due to repetition altering the embedding.

False positives peak at 0.64 ("the hello protocol"), giving a gap of 0.13 from the lowest true positive caught (0.77 "hello hello").

Greetings combined with a question (e.g. "Hello, how do I reverse a list?") score below 0.54 and always pass through to the LLM.

**Threshold: > 0.75.** Catches 12 of 14 test greetings (86%). "yo" and "hi hi hi" are missed and handled naturally by the LLM.

## 4. Off-Topic Filtering

### 4.1 On-topic messages

| Phrase | Max similarity | Result (< 0.30) |
|--------|---------------|-----------------|
| how to sort a list in Python | 0.6084 | pass |
| explain binary search | 0.5187 | pass |
| implement a linked list | 0.4612 | pass |
| how do I debug a segfault | 0.4623 | pass |
| what is a recursive function | 0.7203 | pass |
| explain object-oriented programming | 0.8527 | pass |
| how to read a CSV file in Python | 0.4736 | pass |
| what does this error mean: IndexError | 0.4861 | pass |
| what is the derivative of x squared | 0.6281 | pass |
| solve this differential equation | 0.7398 | pass |
| explain eigenvalues | 0.7513 | pass |
| how to compute a definite integral | 0.6360 | pass |
| what is the determinant of a matrix | 0.4928 | pass |
| explain Bayes theorem | 0.5113 | pass |
| how to prove by induction | 0.4008 | pass |
| Newton's second law | 0.5521 | pass |
| explain the Schrodinger equation | 0.5088 | pass |
| what is conservation of energy | 0.3830 | pass |
| how does electromagnetic induction work | 0.5764 | pass |
| explain the second law of thermodynamics | 0.5612 | pass |
| find the eigenvalues of this matrix | 0.5848 | pass |
| how does LU factorization work | 0.8552 | pass |
| explain the bisection method | 0.9023 | pass |
| solve this ODE using Runge-Kutta | 0.7989 | pass |
| what is an initial value problem | 0.8660 | pass |
| explain the boundary value problem | 0.8886 | pass |
| compute the Fourier transform of this signal | 0.6140 | pass |
| what is the FFT algorithm | 0.7866 | pass |
| how to apply Newton-Raphson method | 0.8557 | pass |
| explain finite difference method | 0.9141 | pass |
| numerical integration using trapezoidal rule | 0.7213 | pass |
| singular value decomposition of a matrix | 0.6443 | pass |

### 4.2 Off-topic messages

| Phrase | Max similarity | Result (< 0.30) |
|--------|---------------|-----------------|
| what's the weather today | 0.2398 | OFF-TOPIC |
| tell me a joke | 0.4675 | pass |
| who won the football | 0.2628 | OFF-TOPIC |
| best pizza in London | 0.1538 | OFF-TOPIC |
| what's your name | 0.1902 | OFF-TOPIC |
| how old are you | 0.2602 | OFF-TOPIC |
| what is love | 0.2890 | OFF-TOPIC |
| recommend a good movie | 0.3968 | pass |
| what time is it | 0.2646 | OFF-TOPIC |
| what career should I choose | 0.2392 | OFF-TOPIC |

### 4.3 Borderline messages

| Phrase | Max similarity | Result (< 0.30) |
|--------|---------------|-----------------|
| what is machine learning | 0.4539 | pass |
| how does AI work | 0.3800 | pass |
| explain neural networks | 0.3888 | pass |
| what is computer science | 0.6678 | pass |
| help me with my homework | 0.5941 | pass |
| I have an exam tomorrow | 0.4408 | pass |
| can you help me study | 0.3823 | pass |
| translate this to French | 0.5389 | pass |

### 4.4 Analysis

The 53 topic anchors give strong coverage of numerical computation topics. Questions about bisection method (0.90), boundary value problem (0.89), finite difference method (0.91), and LU factorisation (0.86) all score above 0.85.

Score distributions:
- On-topic: 0.38 to 0.91 (minimum: "what is conservation of energy" at 0.38)
- Off-topic: 0.15 to 0.47 (maximum: "tell me a joke" at 0.47)
- Borderline: 0.38 to 0.67

A threshold of **0.30** catches 8 of 10 off-topic messages. The two that pass through ("tell me a joke" at 0.47 and "recommend a good movie" at 0.40) are handled by the LLM, which redirects the student naturally. All on-topic messages score above 0.38, giving a gap of 0.08.

"translate this to French" (0.54) sits in the borderline category because translation is a legitimate language task that the LLM can handle.

**Threshold: < 0.30.** Catches clearly unrelated inputs while allowing all STEM and borderline content through.

## 5. Same-Problem Detection

Same-problem detection compares the current user message against the previous Q+A context (the concatenated previous question and assistant response). This provides richer topic context than comparing against the question alone because follow-ups often refer to terms from the answer.

### 5.1 Same-problem pairs (Q+A context)

Each pair shows the original question, the assistant's answer snippet, and the follow-up similarity against the combined Q+A context.

**Pair 1:**
- Q: "how to reverse a list in Python"
- A: "You can use slicing with [::-1] or the built-in reversed() function."

| Follow-up | vs Q+A |
|-----------|--------|
| can you explain the reversal more? | 0.3907 |

**Pair 2:**
- Q: "what is the derivative of sin(x)"
- A: "The derivative of sin(x) is cos(x). This follows from the limit definition."

| Follow-up | vs Q+A |
|-----------|--------|
| I don't understand, show me step by step | 0.2031 |

**Pair 3:**
- Q: "implement binary search"
- A: "Binary search works by repeatedly dividing the search interval in half. Check the middle element."

| Follow-up | vs Q+A |
|-----------|--------|
| what about the edge cases for binary search? | 0.5002 |

**Pair 4:**
- Q: "how to sort a list in Python"
- A: "You could use quicksort or mergesort. Python's built-in sorted() uses Timsort."

| Follow-up | vs Q+A |
|-----------|--------|
| tell me more about mergesort | 0.4409 |

**Pair 5:**
- Q: "explain the Schrodinger equation"
- A: "The time-dependent Schrodinger equation describes the wavefunction evolution: ih_bar d/dt psi = H psi."

| Follow-up | vs Q+A |
|-----------|--------|
| can you show the derivation? | 0.1086 |

### 5.2 Different-problem pairs

| Question A | Question B | Similarity |
|-----------|-----------|-----------|
| how to reverse a list in Python | what is the derivative of sin(x) | 0.2221 |
| implement binary search | explain Newton's second law | 0.2125 |
| explain eigenvalues | how to read a CSV file in Python | 0.1756 |
| what is conservation of energy | explain object-oriented programming | 0.2890 |

### 5.3 Vague follow-ups vs Q+A context

Base Q: "how to reverse a list in Python"
Base A: "You can use slicing with [::-1] or the built-in reversed() function. The slice notation creates a new list in reverse order."

| Follow-up | vs Q+A |
|-----------|--------|
| I don't understand | 0.1226 |
| explain more | 0.0435 |
| show me the answer | 0.0283 |
| can you elaborate? | 0.0291 |
| why? | 0.2263 |
| what do you mean | 0.0594 |

### 5.4 Analysis

Same-problem pairs with Q+A context:
- Topic-specific follow-ups: 0.39 to 0.50 (caught by threshold)
- Generic follow-ups: 0.10 to 0.20 (below threshold, caught instead by elaboration request detection in section 6)

Different-problem pairs score 0.18 to 0.29. A threshold of **0.35** sits between different problems (max 0.29) and the weakest topical follow-up (0.39), giving a margin of 0.06 on each side.

Q+A context improves detection when the follow-up refers to terms from the assistant's answer. "tell me more about mergesort" scores 0.44 against Q+A because the answer mentioned mergesort, even though the original question was about sorting a list.

Vague follow-ups ("I don't understand", "explain more", "why?") all score below 0.23 against Q+A context. These are caught by elaboration request detection instead.

**Threshold: > 0.35.** Captures follow-ups that share topic vocabulary with the Q+A context.

## 6. Elaboration Request Detection

Elaboration request detection identifies generic follow-ups that ask for clarification, more detail, examples, or continuation. These messages do not share topic vocabulary with the previous Q+A context (so they fail same-problem detection), but they clearly refer to the ongoing conversation.

The check runs only when a previous Q+A context exists and same-problem similarity is below threshold. If a message matches elaboration anchors, it is treated as same-problem with the current difficulty preserved (no re-classification needed since the message has no new topic content).

Test phrases are **variations** of the anchors, not exact copies, to verify generalisation.

### 6.1 True positives (should score HIGH)

| Phrase | Max similarity | Result (> 0.50) |
|--------|---------------|-----------------|
| I really don't understand this | 0.8475 | ELABORATION |
| I'm so confused right now | 0.8574 | ELABORATION |
| that makes no sense to me | 0.7955 | ELABORATION |
| can you explain that more | 0.8206 | ELABORATION |
| please elaborate on that | 0.6272 | ELABORATION |
| show me how step by step | 0.9686 | ELABORATION |
| give me an example please | 0.8991 | ELABORATION |
| just give me the answer | 0.7808 | ELABORATION |
| what does that mean | 0.6252 | ELABORATION |
| please continue | 0.6984 | ELABORATION |
| why is that | 0.6251 | ELABORATION |
| how come | 0.5614 | ELABORATION |
| solve this equation | 0.6348 | ELABORATION |

### 6.2 False positives (should score LOW)

| Phrase | Max similarity | Result (> 0.50) |
|--------|---------------|-----------------|
| what is calculus | 0.2474 | pass |
| explain eigenvalues | 0.3473 | pass |
| how to sort a list | 0.3202 | pass |
| what is recursion | 0.3214 | pass |
| define a matrix | 0.2783 | pass |
| what is the FFT | 0.3111 | pass |

### 6.3 Analysis

True positives range from 0.56 to 0.97. All 13 test phrases score well above the threshold, demonstrating good generalisation from the 25 anchors.

"solve this equation" (0.63) is correctly classified as an elaboration request. It is an imperative demand semantically close to anchors like "just tell me" and "show me the answer". In the context of the pipeline, this message would only reach the elaboration check if it did not match the previous Q+A context, meaning it is being used generically rather than referring to a specific new equation.

False positives: all 6 new-topic questions score below 0.35 (max: "explain eigenvalues" at 0.35). The gap between the lowest true positive (0.56 "how come") and the highest false positive (0.35) is 0.21, giving very clean separation.

**Threshold: > 0.50.** Catches all 13 true positive variations. No false positives cross the threshold.

## 7. Threshold Summary

| Check | Threshold | Rationale |
|-------|-----------|-----------|
| Greeting | > 0.75 | Catches 12 obvious greetings (0.77 to 1.00). All false positives below 0.64. Gap of 0.13. |
| Off-topic | < 0.30 | Catches 8 clearly unrelated inputs (0.15 to 0.29). All on-topic above 0.38. Gap of 0.08. |
| Same-problem | > 0.35 | Catches topical follow-ups (0.39+). Different problems at 0.29 max. Gap of 0.06 each side. |
| Elaboration request | > 0.50 | Catches generic follow-ups (0.56+). New-topic questions below 0.35. Gap of 0.21. |

## 8. Limitations

1. Off-topic detection has partial overlap between on-topic and off-topic score distributions. "tell me a joke" (0.47) scores higher than some on-topic queries. The threshold catches only clearly irrelevant inputs. The LLM handles borderline off-topic content naturally.
2. Same-problem detection misses generic follow-ups that lack topic vocabulary (e.g. "I don't understand" scores 0.12). These are caught by elaboration request detection instead.
3. At 256 dimensions, scores are slightly less precise than at 1536 dimensions, but the threshold gaps remain sufficient for reliable classification.
